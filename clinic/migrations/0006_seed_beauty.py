"""Replace fictional medical staff with the fictional LAVIE salon team."""
from django.db import migrations


MASTERS = {
    1: ("Анна Воронцова", "Парикмахер-стилист", 9,
        "Стрижки и укладки с вниманием к форме, текстуре и вашему настроению."),
    2: ("Мария Белова", "Колорист", 8,
        "Мягкие оттенки, сложное окрашивание и бережный уход за волосами."),
    3: ("София Лебедева", "Мастер маникюра", 7,
        "Чистый маникюр, деликатное покрытие и лаконичный дизайн."),
    4: ("Алина Морозова", "Мастер маникюра и педикюра", 6,
        "Аккуратные руки и стопы, эстетика деталей и комфорт на каждом этапе."),
    5: ("Екатерина Соколова", "Бровист и лэшмейкер", 5,
        "Естественная форма бровей и выразительный взгляд без лишнего."),
    6: ("Полина Смирнова", "Визажист", 8,
        "Макияж для события или просто для дня, когда хочется сиять."),
}

SERVICES = [
    ("Маникюр с покрытием", "nails", "Форма, уход и стойкое покрытие.", 2500, [3, 4]),
    ("Маникюр без покрытия", "nails", "Ухоженные руки и идеальная форма.", 1700, [3, 4]),
    ("Педикюр", "nails", "Деликатный уход и лёгкость в каждом шаге.", 3000, [4]),
    ("Женская стрижка", "hair", "Форма, которая работает каждый день.", 3200, [1]),
    ("Укладка", "hair", "Образ для встречи, события или себя.", 2600, [1, 2]),
    ("Тонирование волос", "hair", "Свежий оттенок и блеск волос.", 4800, [2]),
    ("Архитектура бровей", "brows", "Форма и окрашивание в вашем стиле.", 1900, [5]),
    ("Ламинирование ресниц", "brows", "Выразительный взгляд с естественным эффектом.", 3100, [5]),
    ("Макияж", "makeup", "Свежий образ, который подчёркивает вас.", 3900, [6]),
]


def seed_beauty(apps, schema_editor):
    Doctor = apps.get_model("clinic", "Doctor")
    SalonService = apps.get_model("clinic", "SalonService")
    for pk, (name, specialty, experience, description) in MASTERS.items():
        Doctor.objects.update_or_create(pk=pk, defaults={
            "full_name": name, "specialty": specialty,
            "experience": experience, "description": description,
        })
    for title, category, description, price, specialist_ids in SERVICES:
        service, _ = SalonService.objects.update_or_create(title=title, defaults={
            "category": category, "description": description, "price": price,
            "duration_minutes": 60, "is_active": True,
        })
        service.specialists.set(Doctor.objects.filter(pk__in=specialist_ids))


class Migration(migrations.Migration):
    dependencies = [("clinic", "0005_alter_appointment_options_and_more")]
    operations = [migrations.RunPython(seed_beauty, migrations.RunPython.noop)]
