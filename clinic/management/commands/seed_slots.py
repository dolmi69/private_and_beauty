from django.core.management.base import BaseCommand

from clinic.scheduling import seed_demo_slots


class Command(BaseCommand):
    help = "Создать демонстрационные свободные часы врачей на ближайшие 21 день"

    def handle(self, *args, **options):
        self.stdout.write(f"Создано новых времён: {seed_demo_slots()}")
