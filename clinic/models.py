"""Salon specialists, services, appointments and private client conversations."""
from django.core.validators import MaxValueValidator, MinValueValidator, RegexValidator
from django.db import models
from django.conf import settings
from django.db.models import Q


class UserProfile(models.Model):
    class Role(models.TextChoices):
        CLIENT = "client", "Клиент"
        DOCTOR = "doctor", "Мастер"
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
    specialty = models.CharField("направление", max_length=100)
    experience = models.PositiveSmallIntegerField("стаж, лет", validators=[MaxValueValidator(70)])
    description = models.TextField("описание")

    class Meta:
        ordering = ["full_name"]
        verbose_name = "мастер"
        verbose_name_plural = "Мастера"

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
        verbose_name = "время записи"
        verbose_name_plural = "Время записи"

    def __str__(self):
        return f"{self.doctor} · {self.starts_at:%d.%m.%Y %H:%M}"


class Appointment(models.Model):
    class Status(models.TextChoices):
        PENDING = "pending", "Ожидает подтверждения"
        CONFIRMED = "confirmed", "Подтверждена"
        CANCELLED = "cancelled", "Отменена"

    client_name = models.CharField("имя и фамилия клиента", max_length=120)
    phone_number = models.CharField(
        "номер телефона",
        max_length=16,
        validators=[RegexValidator(r"^\+?[0-9]{7,15}$", "Введите от 7 до 15 цифр; в начале допустим знак +.")],
    )
    doctor = models.ForeignKey(Doctor, verbose_name="мастер", on_delete=models.PROTECT, related_name="appointments")
    service = models.ForeignKey("SalonService", verbose_name="услуга", null=True, blank=True,
                                on_delete=models.PROTECT, related_name="appointments")
    client = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name="clinic_appointments")
    slot = models.ForeignKey(AppointmentSlot, null=True, blank=True, on_delete=models.PROTECT, related_name="appointments")
    requested_at = models.DateTimeField("желаемые дата и время", db_index=True)
    status = models.CharField("статус", max_length=12, choices=Status.choices, default=Status.PENDING, db_index=True)
    created_at = models.DateTimeField("дата создания", auto_now_add=True)

    class Meta:
        ordering = ["-created_at"]
        verbose_name = "запись"
        verbose_name_plural = "Записи"
        constraints = [
            models.CheckConstraint(
                condition=models.Q(status__in=["pending", "confirmed", "cancelled"]),
                name="appointment_valid_status",
            ),
            models.UniqueConstraint(fields=["doctor", "requested_at"], condition=Q(status__in=["pending", "confirmed"]), name="one_active_appointment_per_time"),
        ]

    def __str__(self):
        return f"{self.client_name} → {self.doctor} ({self.get_status_display()})"


class SalonService(models.Model):
    class Category(models.TextChoices):
        NAILS = "nails", "Маникюр и педикюр"
        HAIR = "hair", "Волосы"
        BROWS = "brows", "Брови и ресницы"
        MAKEUP = "makeup", "Макияж"
        CARE = "care", "Уход"

    title = models.CharField("название", max_length=100)
    category = models.CharField("категория", max_length=10, choices=Category.choices)
    description = models.CharField("описание", max_length=240)
    price = models.PositiveIntegerField("цена, ₽")
    duration_minutes = models.PositiveSmallIntegerField("длительность, минут", default=60,
        validators=[MinValueValidator(60), MaxValueValidator(60)])
    specialists = models.ManyToManyField(Doctor, related_name="services", verbose_name="мастера")
    is_active = models.BooleanField("доступна для записи", default=True)

    class Meta:
        ordering = ["category", "title"]
        verbose_name = "услуга"
        verbose_name_plural = "Услуги"

    def __str__(self):
        return self.title


class ClientMessage(models.Model):
    appointment = models.ForeignKey(Appointment, on_delete=models.CASCADE, related_name="messages")
    sender = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT)
    body = models.TextField("сообщение", max_length=2000)
    created_at = models.DateTimeField("отправлено", auto_now_add=True)

    class Meta:
        ordering = ["created_at", "pk"]
        verbose_name = "сообщение клиента"
        verbose_name_plural = "Чаты клиентов"
