"""Small HTML views and same-origin, CSRF-protected JSON endpoints."""
import hashlib
import json
import time
from datetime import date, timedelta

from django.conf import settings
from django.contrib.admin.views.decorators import staff_member_required
from django.contrib.auth import login
from django.contrib.auth.decorators import login_required
from django.contrib.auth import get_user_model
from django.core.cache import cache
from django.core.exceptions import PermissionDenied, RequestDataTooBig
from django.http import JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.db import IntegrityError, transaction
from django.utils import timezone
from django.views.decorators.cache import never_cache
from django.views.decorators.http import require_GET, require_POST

from .forms import AppointmentForm, ClientRegistrationForm, DoctorAccountForm
from .models import Appointment, AppointmentSlot, Doctor, SalonService, UserProfile
from .scheduling import available_on_day, available_slots
from .services import receptionist_reply


@never_cache
@require_GET
def home(request):
    catalogue = list(SalonService.objects.filter(is_active=True))
    highlights = [next((item for item in catalogue if item.category == category), None)
                  for category in ("nails", "hair", "brows")]
    return render(request, "clinic/home.html", {
        "featured_masters": Doctor.objects.all()[:3],
        "featured_services": [item for item in highlights if item],
    })


@never_cache
@require_GET
def services(request):
    return render(request, "clinic/services.html", {"services": SalonService.objects.filter(is_active=True)})


@never_cache
@require_GET
def doctors(request):
    return render(request, "clinic/doctors.html", {"masters": Doctor.objects.all()})


@never_cache
@require_GET
def contacts(request):
    return render(request, "clinic/contacts.html")


@never_cache
@require_GET
def booking(request):
    return render(request, "clinic/booking.html", {
        "services": SalonService.objects.filter(is_active=True),
        "selected_service": request.GET.get("service", ""),
        "selected_master": request.GET.get("master", ""),
        "minimum_date": timezone.localdate().isoformat(),
        "maximum_date": (timezone.localdate() + timedelta(days=60)).isoformat(),
    })


@never_cache
@require_GET
def availability_api(request):
    try:
        service = SalonService.objects.get(pk=int(request.GET.get("service", "")), is_active=True)
        day = date.fromisoformat(request.GET.get("date", ""))
        if not timezone.localdate() <= day <= timezone.localdate() + timedelta(days=60):
            raise ValueError
    except (ValueError, TypeError, SalonService.DoesNotExist):
        return JsonResponse({"error": "Выберите услугу и дату в ближайшие 60 дней."}, status=400)
    masters = [{"id": master.pk, "name": master.full_name, "specialty": master.specialty,
                "slots": [{"id": slot.pk, "time": timezone.localtime(slot.starts_at).strftime("%H:%M")}
                          for slot in slots]}
               for master, slots in available_on_day(service, day)]
    return JsonResponse({"service": service.title, "date": day.isoformat(), "masters": masters})


def account_role(user):
    if user.is_staff:
        return UserProfile.Role.MANAGER
    profile = UserProfile.objects.filter(user=user).first()
    return profile.role if profile else UserProfile.Role.CLIENT


@never_cache
def register(request):
    if request.user.is_authenticated:
        return redirect("clinic:dashboard")
    form = ClientRegistrationForm(request.POST or None)
    if request.method == "POST" and form.is_valid():
        with transaction.atomic():
            user = form.save()
        login(request, user)
        return redirect("clinic:dashboard")
    return render(request, "clinic/register.html", {"form": form})


@login_required
@never_cache
def dashboard(request):
    role = account_role(request.user)
    if role == UserProfile.Role.MANAGER:
        return redirect("clinic:manager_dashboard")
    if role == UserProfile.Role.DOCTOR:
        return redirect("clinic:master_calendar")
    appointments = (Appointment.objects.filter(client=request.user, service__isnull=False)
                    .select_related("doctor", "service").order_by("-requested_at"))
    return render(request, "clinic/client_dashboard.html", {"appointments": appointments})


@login_required
@require_POST
def cancel_appointment(request, pk):
    appointment = get_object_or_404(Appointment, pk=pk, client=request.user)
    if account_role(request.user) != UserProfile.Role.CLIENT:
        raise PermissionDenied
    if appointment.requested_at > timezone.now() and appointment.status == Appointment.Status.PENDING:
        appointment.status = Appointment.Status.CANCELLED
        appointment.save(update_fields=["status"])
    return redirect("clinic:dashboard")


@staff_member_required
def manager_team(request):
    if not request.user.has_perm("clinic.view_appointment"):
        raise PermissionDenied
    form = DoctorAccountForm(request.POST or None)
    created = False
    if request.method == "POST" and form.is_valid():
        with transaction.atomic():
            doctor = form.cleaned_data["doctor"]
            user = get_user_model().objects.create_user(
                username=form.cleaned_data["username"], password=form.cleaned_data["password"])
            names = doctor.full_name.split(maxsplit=1)
            user.first_name = names[0]
            user.last_name = names[1] if len(names) > 1 else ""
            user.save(update_fields=["first_name", "last_name"])
            UserProfile.objects.create(user=user, role=UserProfile.Role.DOCTOR, doctor=doctor)
        form = DoctorAccountForm()
        created = True
    accounts = UserProfile.objects.filter(role=UserProfile.Role.DOCTOR).select_related("user", "doctor")
    return render(request, "clinic/manager_team.html", {"form": form, "accounts": accounts, "created": created})


@never_cache
@require_GET
def slots_api(request, doctor_id):
    get_object_or_404(Doctor, pk=doctor_id)
    return JsonResponse({"slots": [{"id": slot.pk, "starts_at": timezone.localtime(slot.starts_at).strftime("%d.%m.%Y %H:%M")}
                                   for slot in available_slots(doctor_id)[:100]]})


def _payload(request):
    if request.content_type != "application/json":
        raise ValueError("Отправьте объект JSON с заголовком Content-Type: application/json.")
    try:
        body = request.body
        if len(body) > 8192:
            raise ValueError("Запрос слишком большой.")
        payload = json.loads(body)
    except (json.JSONDecodeError, UnicodeDecodeError, RequestDataTooBig) as exc:
        raise ValueError("Отправьте корректный объект JSON небольшого размера.") from exc
    if not isinstance(payload, dict):
        raise ValueError("Тело запроса должно быть объектом JSON.")
    return payload


def _rate_limited(request, action, limit):
    # Never trust client-supplied X-Forwarded-For. Configure proxies explicitly later.
    identity = request.META.get("REMOTE_ADDR", "unknown")
    digest = hashlib.sha256(identity.encode()).hexdigest()
    key = f"{action}:{digest}:{int(time.time()) // 60}"
    if cache.add(key, 1, timeout=65):
        return False
    try:
        return cache.incr(key) > limit
    except ValueError:
        cache.set(key, 1, timeout=65)
        return False


def _too_many():
    response = JsonResponse({"error": "Подождите минуту и повторите попытку."}, status=429)
    response["Retry-After"] = "60"
    return response


@never_cache
@require_POST
def chat(request):
    if request.user.is_authenticated and account_role(request.user) == UserProfile.Role.DOCTOR:
        return JsonResponse({"error": "Чат гостей недоступен мастеру."}, status=403)
    try:
        payload = _payload(request)
        message = payload.get("message")
        if not isinstance(message, str) or not 1 <= len(message.strip()) <= 1000:
            raise ValueError("Введите сообщение длиной от 1 до 1000 символов.")
    except ValueError as exc:
        return JsonResponse({"error": str(exc)}, status=400)
    if _rate_limited(request, "chat", settings.CHAT_RATE_LIMIT):
        return _too_many()

    # Roles and previous messages come from the server session, never the caller.
    history = request.session.get("clinic_chat", [])[-10:]
    history.append({"role": "user", "content": message.strip()})
    directory = list(SalonService.objects.filter(is_active=True).values("id", "title", "category"))
    result = receptionist_reply(history, directory)
    history.append({"role": "assistant", "content": result["reply"]})
    request.session["clinic_chat"] = history[-12:]
    request.session.set_expiry(1800)
    return JsonResponse(result)


@never_cache
@require_POST
def reset_chat(request):
    request.session.pop("clinic_chat", None)
    return JsonResponse({"ok": True})


@never_cache
@require_POST
def book_appointment(request):
    if not request.user.is_authenticated:
        return JsonResponse({"error": "Для записи войдите или зарегистрируйтесь.", "login_url": "/login/"}, status=401)
    if account_role(request.user) != UserProfile.Role.CLIENT:
        return JsonResponse({"error": "Запись доступна только клиентам."}, status=403)
    try:
        payload = _payload(request)
        fields = ["service", "doctor", "slot"]
        if any(not isinstance(payload.get(key), (str, int)) or isinstance(payload.get(key), bool) for key in fields):
            raise ValueError("Заполните все поля записи.")
    except ValueError as exc:
        return JsonResponse({"error": str(exc)}, status=400)
    if _rate_limited(request, "booking", settings.BOOKING_RATE_LIMIT):
        return _too_many()
    try:
        service = SalonService.objects.get(pk=int(payload["service"]), is_active=True,
                                           specialists__pk=int(payload["doctor"]))
        slot = available_slots(int(payload["doctor"])).get(pk=int(payload["slot"]))
    except (ValueError, TypeError, AppointmentSlot.DoesNotExist, SalonService.DoesNotExist):
        return JsonResponse({"error": "Услуга, мастер или время уже недоступны. Выберите другие."}, status=400)
    profile = UserProfile.objects.filter(user=request.user).first()
    if not profile or not profile.phone_number:
        return JsonResponse({"error": "Добавьте телефон в профиле клиента."}, status=400)
    form = AppointmentForm({"client_name": request.user.get_full_name() or request.user.username,
                            "phone_number": profile.phone_number, "doctor": slot.doctor_id,
                            "requested_at": timezone.localtime(slot.starts_at).strftime("%Y-%m-%dT%H:%M")})
    if not form.is_valid():
        return JsonResponse({"error": "Проверьте данные заявки.", "errors": form.errors.get_json_data()}, status=400)
    appointment = form.save(commit=False)
    appointment.client = request.user
    appointment.slot = slot
    appointment.service = service
    appointment.requested_at = slot.starts_at
    try:
        with transaction.atomic():
            appointment.save()
    except IntegrityError:
        return JsonResponse({"error": "Это время только что заняли. Выберите другое."}, status=409)
    return JsonResponse({
        "id": appointment.pk,
        "status": appointment.status,
        "message": f"Запись на «{service.title}» к мастеру {slot.doctor.full_name} создана. Менеджер подтвердит её.",
    }, status=201)


@staff_member_required
def manager_dashboard(request):
    if not request.user.has_perm("clinic.view_appointment"):
        raise PermissionDenied
    return redirect("admin:clinic_appointment_changelist")


def csrf_failure(request, reason=""):
    if request.path.startswith("/api/"):
        return JsonResponse({"error": "Срок действия защитного кода истёк. Обновите страницу и повторите попытку."}, status=403)
    return render(request, "clinic/csrf_failure.html", status=403)
