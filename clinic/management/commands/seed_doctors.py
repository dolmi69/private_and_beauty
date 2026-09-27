from importlib import import_module

from django.core.management.base import BaseCommand
from django.db import transaction

from clinic.models import Doctor


class Command(BaseCommand):
    help = "Восстановить отсутствующих демонстрационных врачей, сохранив существующие анкеты."

    @transaction.atomic
    def handle(self, *args, **options):
        migration = import_module("clinic.migrations.0002_seed_doctors")
        for name, specialty, experience, description in migration.DEMO_DOCTORS:
            Doctor.objects.get_or_create(
                full_name=name, specialty=specialty,
                defaults={"experience": experience, "description": description},
            )
        self.stdout.write(self.style.SUCCESS("Демонстрационный список готов: шесть вымышленных врачей."))
