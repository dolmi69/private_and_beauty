"""Small HTML views and same-origin, CSRF-protected JSON endpoints."""
import hashlib
import json
import time

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
from .models import Appointment, AppointmentSlot, Doctor, UserProfile
from .scheduling import available_slots, workload
from .services import receptionist_reply


@never_cache
@require_GET
def home(request):
    return render(request, "clinic/home.html", {"featured_doctors": Doctor.objects.all()[:3]})


@never_cache
@require_GET
def services(request):
    return render(request, "clinic/services.html")


@never_cache
@require_GET
def doctors(request):
    return render(request, "clinic/doctors.html", {"doctors": Doctor.objects.all()})


@never_cache
@require_GET
def contacts(request):
    return render(request, "clinic/contacts.html")


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
        profile = get_object_or_404(UserProfile, user=request.user, role=UserProfile.Role.DOCTOR)
        if not profile.doctor_id:
            raise PermissionDenied
        appointments = Appointment.objects.filter(doctor=profile.doctor, requested_at__gte=timezone.now(),
                                                  status__in=[Appointment.Status.PENDING, Appointment.Status.CONFIRMED])
        slots = available_slots(profile.doctor_id)[:40]
        return render(request, "clinic/doctor_dashboard.html", {
            "doctor": profile.doctor, "appointments": appointments.order_by("requested_at")[:40],
            "slots": slots, "workload": workload(profile.doctor),
        })
    appointments = Appointment.objects.filter(client=request.user).select_related("doctor").order_by("-requested_at")
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
    directory = list(Doctor.objects.values("id", "full_name", "specialty"))
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
        return JsonResponse({"error": "Запись доступна только пациентам."}, status=403)
    try:
        payload = _payload(request)
        fields = ["doctor", "slot"]
        if any(not isinstance(payload.get(key), (str, int)) or isinstance(payload.get(key), bool) for key in fields):
            raise ValueError("Заполните все поля заявки на приём.")
    except ValueError as exc:
        return JsonResponse({"error": str(exc)}, status=400)
    if _rate_limited(request, "booking", settings.BOOKING_RATE_LIMIT):
        return _too_many()
    try:
        slot = available_slots(int(payload["doctor"])).get(pk=int(payload["slot"]))
    except (ValueError, TypeError, AppointmentSlot.DoesNotExist):
        return JsonResponse({"error": "Это время уже недоступно. Выберите другое."}, status=400)
    profile = UserProfile.objects.filter(user=request.user).first()
    if not profile or not profile.phone_number:
        return JsonResponse({"error": "Добавьте телефон в профиле пациента."}, status=400)
    form = AppointmentForm({"client_name": request.user.get_full_name() or request.user.username,
                            "phone_number": profile.phone_number, "doctor": slot.doctor_id,
                            "requested_at": timezone.localtime(slot.starts_at).strftime("%Y-%m-%dT%H:%M")})
    if not form.is_valid():
        return JsonResponse({"error": "Проверьте данные заявки.", "errors": form.errors.get_json_data()}, status=400)
    appointment = form.save(commit=False)
    appointment.client = request.user
    appointment.slot = slot
    appointment.requested_at = slot.starts_at
    try:
        with transaction.atomic():
            appointment.save()
    except IntegrityError:
        return JsonResponse({"error": "Это время только что заняли. Выберите другое."}, status=409)
    return JsonResponse({
        "id": appointment.pk,
        "status": appointment.status,
        "message": "Время зарезервировано. Заявка ожидает подтверждения менеджера.",
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
