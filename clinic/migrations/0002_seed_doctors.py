"""Six fictional clinicians, installed once by migrate (no import-time DB writes)."""
from django.db import migrations

DEMO_DOCTORS = [
    ("Анна Смирнова", "Терапевт", 12, "Внимательный первый приём по вопросам самочувствия, профилактические осмотры и дальнейшее наблюдение."),
    ("Дмитрий Волков", "Кардиолог", 15, "Консультации по вопросам здоровья сердца, артериального давления и дальнейшего наблюдения."),
    ("Ирина Соколова", "Педиатр", 10, "Бережные приёмы для детей и родителей — от первых лет жизни до подросткового возраста."),
    ("Михаил Орлов", "Стоматолог", 9, "Профилактические осмотры полости рта и консультации по вопросам здоровья зубов и дёсен."),
    ("Ольга Кузнецова", "Дерматолог", 11, "Консультации по вопросам здоровья кожи, волос и ногтей с вниманием к каждому вопросу."),
    ("Алексей Морозов", "Невролог", 14, "Консультации по поводу повторяющихся головных болей и других вопросов о работе нервной системы."),
]


def seed_doctors(apps, schema_editor):
    Doctor = apps.get_model("clinic", "Doctor")
    for name, specialty, experience, description in DEMO_DOCTORS:
        Doctor.objects.using(schema_editor.connection.alias).get_or_create(
            full_name=name, specialty=specialty,
            defaults={"experience": experience, "description": description},
        )


class Migration(migrations.Migration):
    dependencies = [("clinic", "0001_initial")]
    # Reversing must not delete doctors that managers may have used or edited.
    operations = [migrations.RunPython(seed_doctors, reverse_code=migrations.RunPython.noop)]
