"""The database stores the care directory and appointment requests."""
from django.core.validators import MaxValueValidator, RegexValidator
from django.db import models
from django.conf import settings
from django.db.models import Q


class UserProfile(models.Model):
    class Role(models.TextChoices):
        CLIENT = "client", "Пациент"
        DOCTOR = "doctor", "Врач"
        MANAGER = "manager", "Менеджер"

    user = models.OneToOneField(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="clinic_profile")
    role = models.CharField(max_length=10, choices=Role.choices, default=Role.CLIENT)
    doctor = models.OneToOneField("Doctor", null=True, blank=True, on_delete=models.SET_NULL, related_name="account")
    phone_number = models.CharField(max_length=16, blank=True)

    def __str__(self):
        return f"{self.user.username} · {self.get_role_display()}"


class Doctor(models.Model):
    # Django adds the primary-key ID automatically.
    full_name = models.CharField("имя и фамилия", max_length=120)
    specialty = models.CharField("специальность", max_length=100)
    experience = models.PositiveSmallIntegerField("стаж, лет", validators=[MaxValueValidator(70)])
    description = models.TextField("описание")

    class Meta:
        ordering = ["full_name"]
        verbose_name = "врач"
        verbose_name_plural = "Врачи"

    def __str__(self):
        return f"{self.full_name} · {self.specialty}"

    @property
    def initials(self):
        return "".join(part[0] for part in self.full_name.split()[:2])


class AppointmentSlot(models.Model):
    doctor = models.ForeignKey(Doctor, on_delete=models.CASCADE, related_name="slots")
    starts_at = models.DateTimeField(db_index=True)
    is_active = models.BooleanField(default=True)

    class Meta:
        ordering = ["starts_at"]
        constraints = [models.UniqueConstraint(fields=["doctor", "starts_at"], name="unique_doctor_slot")]
        verbose_name = "время приёма"
        verbose_name_plural = "Время приёма"

    def __str__(self):
        return f"{self.doctor} · {self.starts_at:%d.%m.%Y %H:%M}"


class Appointment(models.Model):
    class Status(models.TextChoices):
        PENDING = "pending", "Ожидает подтверждения"
        CONFIRMED = "confirmed", "Подтверждена"
        CANCELLED = "cancelled", "Отменена"

    client_name = models.CharField("имя и фамилия пациента", max_length=120)
    phone_number = models.CharField(
        "номер телефона",
        max_length=16,
        validators=[RegexValidator(r"^\+?[0-9]{7,15}$", "Введите от 7 до 15 цифр; в начале допустим знак +.")],
    )
    # Preserve the clinician reference while an appointment still exists.
    doctor = models.ForeignKey(Doctor, verbose_name="врач", on_delete=models.PROTECT, related_name="appointments")
    client = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name="clinic_appointments")
    slot = models.ForeignKey(AppointmentSlot, null=True, blank=True, on_delete=models.PROTECT, related_name="appointments")
    requested_at = models.DateTimeField("желаемые дата и время", db_index=True)
    status = models.CharField("статус", max_length=12, choices=Status.choices, default=Status.PENDING, db_index=True)
    created_at = models.DateTimeField("дата создания", auto_now_add=True)

    class Meta:
        ordering = ["-created_at"]
        verbose_name = "заявка на приём"
        verbose_name_plural = "Заявки на приём"
        constraints = [
            models.CheckConstraint(
                condition=models.Q(status__in=["pending", "confirmed", "cancelled"]),
                name="appointment_valid_status",
            ),
            models.UniqueConstraint(fields=["doctor", "requested_at"], condition=Q(status__in=["pending", "confirmed"]), name="one_active_appointment_per_time"),
        ]

    def __str__(self):
        return f"{self.client_name} → {self.doctor} ({self.get_status_display()})"
