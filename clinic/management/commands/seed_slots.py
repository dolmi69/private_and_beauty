from django.core.management.base import BaseCommand

from clinic.scheduling import seed_demo_slots


class Command(BaseCommand):
    help = "Создать часы мастеров на ближайшие 30 дней"

    def handle(self, *args, **options):
        self.stdout.write(f"Создано новых времён: {seed_demo_slots()}")
