"""Available slots and capacity calculations use clinic local time."""
from datetime import datetime, time, timedelta

from django.utils import timezone

from .models import Appointment, AppointmentSlot


def available_slots(doctor_id):
    booked = Appointment.objects.filter(status__in=[Appointment.Status.PENDING, Appointment.Status.CONFIRMED])
    return (AppointmentSlot.objects.filter(doctor_id=doctor_id, is_active=True, starts_at__gt=timezone.now())
            .exclude(pk__in=booked.exclude(slot=None).values("slot_id"))
            .exclude(starts_at__in=booked.filter(doctor_id=doctor_id).values("requested_at"))
            .order_by("starts_at"))


def seed_demo_slots(days=21):
    """Create weekday 09:00–17:00 hourly slots; safe to run repeatedly."""
    from .models import Doctor
    today = timezone.localdate()
    created = 0
    for offset in range(1, days + 1):
        day = today + timedelta(days=offset)
        if day.weekday() >= 5:
            continue
        for doctor in Doctor.objects.all():
            for hour in range(9, 17):
                starts_at = timezone.make_aware(datetime.combine(day, time(hour)))
                _, was_created = AppointmentSlot.objects.get_or_create(doctor=doctor, starts_at=starts_at)
                created += int(was_created)
    return created


def workload(doctor):
    today = timezone.localdate()
    start = timezone.make_aware(datetime.combine(today, time.min))
    end = start + timedelta(days=7)
    slots = list(AppointmentSlot.objects.filter(doctor=doctor, is_active=True, starts_at__gte=start, starts_at__lt=end))
    occupied = list(Appointment.objects.filter(doctor=doctor, status__in=["pending", "confirmed"], requested_at__gte=start, requested_at__lt=end))
    capacity = len(slots)
    count = len(occupied)
    days = []
    for offset in range(7):
        day = today + timedelta(days=offset)
        day_capacity = sum(timezone.localtime(slot.starts_at).date() == day for slot in slots)
        day_booked = sum(timezone.localtime(item.requested_at).date() == day for item in occupied)
        days.append({"date": day, "capacity": day_capacity, "booked": day_booked,
                     "free": max(day_capacity - day_booked, 0),
                     "percent": round(day_booked * 100 / day_capacity) if day_capacity else 0})
    return {"capacity": capacity, "booked": count, "percent": round(count * 100 / capacity) if capacity else 0,
            "pending": sum(item.status == "pending" for item in occupied),
            "confirmed": sum(item.status == "confirmed" for item in occupied), "days": days}
