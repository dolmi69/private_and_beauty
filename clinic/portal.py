"""Private calendar, appointment chats and workload answers for salon masters."""
import calendar
import json
import time
from datetime import date, datetime, timedelta

from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied
from django.core.cache import cache
from django.http import JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone
from django.views.decorators.cache import never_cache
from django.views.decorators.http import require_POST

from .models import Appointment, AppointmentSlot, ClientMessage, UserProfile
from .scheduling import workload
from .services import schedule_facts, specialist_schedule_reply


def _master_profile(user):
    profile = UserProfile.objects.filter(user=user, role=UserProfile.Role.DOCTOR).select_related("doctor").first()
    if profile is None or profile.doctor_id is None or user.is_staff:
        raise PermissionDenied
    return profile


def _date_parameter(request):
    try:
        return date.fromisoformat(request.GET.get("date", ""))
    except ValueError:
        return timezone.localdate()


@login_required
@never_cache
def master_calendar(request):
    profile = _master_profile(request.user)
    selected = _date_parameter(request)
    first = selected.replace(day=1)
    weeks = calendar.Calendar(firstweekday=0).monthdatescalendar(first.year, first.month)
    range_start = timezone.make_aware(datetime.combine(weeks[0][0], datetime.min.time()))
    range_end = timezone.make_aware(datetime.combine(weeks[-1][-1] + timedelta(days=1), datetime.min.time()))
    slots = AppointmentSlot.objects.filter(doctor=profile.doctor, is_active=True,
        starts_at__gte=range_start, starts_at__lt=range_end)
    appointments = Appointment.objects.filter(doctor=profile.doctor, service__isnull=False,
        status__in=[Appointment.Status.PENDING, Appointment.Status.CONFIRMED],
        requested_at__gte=range_start, requested_at__lt=range_end).select_related("service", "client")
    capacity_by_day = {}
    booked_by_day = {}
    for slot in slots:
        day = timezone.localtime(slot.starts_at).date()
        capacity_by_day[day] = capacity_by_day.get(day, 0) + 1
    for item in appointments:
        day = timezone.localtime(item.requested_at).date()
        booked_by_day[day] = booked_by_day.get(day, 0) + 1
    grid = [[{"date": day, "in_month": day.month == first.month, "selected": day == selected,
              "capacity": capacity_by_day.get(day, 0), "booked": booked_by_day.get(day, 0),
              "percent": round(booked_by_day.get(day, 0) * 100 / capacity_by_day[day])
                         if capacity_by_day.get(day) else 0} for day in week] for week in weeks]
    selected_appointments = [item for item in appointments
                             if timezone.localtime(item.requested_at).date() == selected]
    selected_appointments.sort(key=lambda item: item.requested_at)
    previous_month = (first - timedelta(days=1)).replace(day=1)
    next_month = (first + timedelta(days=32)).replace(day=1)
    return render(request, "clinic/master_calendar.html", {
        "master": profile.doctor, "selected": selected, "weeks": grid,
        "appointments": selected_appointments, "workload": workload(profile.doctor),
        "selected_facts": schedule_facts(profile.doctor, selected),
        "previous_month": previous_month, "next_month": next_month,
    })


@login_required
@never_cache
def master_chats(request):
    profile = _master_profile(request.user)
    appointments = (Appointment.objects.filter(doctor=profile.doctor, service__isnull=False,
        client__isnull=False).select_related("client", "service").order_by("-requested_at"))
    return render(request, "clinic/master_chats.html", {"master": profile.doctor,
        "appointments": appointments})


@login_required
@never_cache
def conversation(request, pk):
    appointment = get_object_or_404(Appointment.objects.select_related("client", "doctor", "service"),
                                    pk=pk, service__isnull=False)
    profile = UserProfile.objects.filter(user=request.user).first()
    is_master = bool(profile and profile.role == UserProfile.Role.DOCTOR
                     and profile.doctor_id == appointment.doctor_id and not request.user.is_staff)
    is_client = appointment.client_id == request.user.pk and bool(profile and profile.role == UserProfile.Role.CLIENT)
    if not (is_master or is_client):
        raise PermissionDenied
    error = None
    if request.method == "POST":
        body = request.POST.get("body", "").strip()
        if appointment.status == Appointment.Status.CANCELLED:
            error = "Чат отменённой записи закрыт."
        elif not 1 <= len(body) <= 2000:
            error = "Сообщение должно содержать от 1 до 2000 символов."
        else:
            ClientMessage.objects.create(appointment=appointment, sender=request.user, body=body)
            return redirect("clinic:conversation", pk=pk)
    return render(request, "clinic/conversation.html", {
        "appointment": appointment, "chat_messages": appointment.messages.select_related("sender").order_by("created_at", "pk")[:100],
        "is_master": is_master, "layout": "clinic/master_base.html" if is_master else "clinic/base.html",
        "error": error,
    })


@login_required
@require_POST
def master_assistant(request):
    profile = _master_profile(request.user)
    key = f"schedule-assistant:{request.user.pk}:{int(time.time()) // 60}"
    if cache.get(key, 0) >= 12:
        return JsonResponse({"error": "Подождите минуту перед следующим вопросом."}, status=429)
    if not cache.add(key, 1, timeout=65):
        cache.incr(key)
    try:
        payload = json.loads(request.body)
        question = payload.get("question") if isinstance(payload, dict) else None
        if not isinstance(question, str) or not 1 <= len(question.strip()) <= 500:
            raise ValueError
    except (ValueError, UnicodeDecodeError):
        return JsonResponse({"error": "Введите вопрос до 500 символов."}, status=400)
    result = specialist_schedule_reply(question.strip(), profile.doctor)
    return JsonResponse(result)
