from importlib import import_module

from django.core.management.base import BaseCommand
from django.db import transaction

from clinic.models import Doctor


class Command(BaseCommand):
    help = "Восстановить демонстрационную команду салона."

    @transaction.atomic
    def handle(self, *args, **options):
        migration = import_module("clinic.migrations.0006_seed_beauty")
        for pk, (name, specialty, experience, description) in migration.MASTERS.items():
            Doctor.objects.get_or_create(pk=pk, defaults={
                "full_name": name, "specialty": specialty,
                "experience": experience, "description": description,
            })
        self.stdout.write(self.style.SUCCESS("Демонстрационная команда готова: шесть мастеров."))
