# Initial schema. The following migration populates the fictional directory.
import django.core.validators
import django.db.models.deletion
from django.db import migrations, models


class Migration(migrations.Migration):
    initial = True
    dependencies = []
    operations = [
        migrations.CreateModel(
            name="Doctor",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("full_name", models.CharField(max_length=120)),
                ("specialty", models.CharField(max_length=100)),
                ("experience", models.PositiveSmallIntegerField(validators=[django.core.validators.MaxValueValidator(70)])),
                ("description", models.TextField()),
            ],
            options={"ordering": ["full_name"]},
        ),
        migrations.CreateModel(
            name="Appointment",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("client_name", models.CharField(max_length=120)),
                ("phone_number", models.CharField(max_length=16, validators=[django.core.validators.RegexValidator("^\\+?[0-9]{7,15}$", "Enter 7–15 digits, optionally starting with +.")])),
                ("requested_at", models.DateTimeField(db_index=True, verbose_name="requested date/time")),
                ("status", models.CharField(choices=[("pending", "Pending"), ("confirmed", "Confirmed"), ("cancelled", "Cancelled")], db_index=True, default="pending", max_length=12)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("doctor", models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name="appointments", to="clinic.doctor")),
            ],
            options={
                "ordering": ["-created_at"],
                "constraints": [models.CheckConstraint(condition=models.Q(("status__in", ["pending", "confirmed", "cancelled"])), name="appointment_valid_status")],
            },
        ),
    ]
