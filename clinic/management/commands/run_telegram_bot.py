"""Запуск: python manage.py run_telegram_bot. Работает без webhook и домена бота."""
import time

from django.core.management.base import BaseCommand, CommandError

from clinic.telegram_bot import TelegramError, api, handle_update, mini_app_url


class Command(BaseCommand):
    help = "Запустить бота через long polling или проверить его токен."

    def add_arguments(self, parser):
        parser.add_argument("--check", action="store_true", help="Только проверить подключение.")
        parser.add_argument("--configure", action="store_true", help="Настроить команды и кнопку меню Mini App.")

    def handle(self, *args, **options):
        try:
            identity = api("getMe")
            self.stdout.write(self.style.SUCCESS(f"Подключён бот @{identity['username']}"))
            url = mini_app_url()
            if options["configure"]:
                api("setMyCommands", {"commands": [
                    {"command": "start", "description": "Открыть LAVIE"},
                    {"command": "salon", "description": "Услуги, мастера и запись"},
                    {"command": "help", "description": "Помощь"},
                ]})
                if url:
                    api("setChatMenuButton", {"menu_button": {
                        "type": "web_app", "text": "LAVIE", "web_app": {"url": url},
                    }})
                self.stdout.write("Команды настроены." if not url else "Команды и кнопка приложения настроены.")
            if options["check"]:
                return
            webhook = api("getWebhookInfo")
            if webhook.get("url"):
                raise CommandError("У бота уже настроен webhook. Остановите прежнюю интеграцию перед polling.")
            if not url:
                self.stdout.write("HTTPS-адрес ещё не задан. Бот ответит сообщением о подготовке приложения.")
            offset = None
            self.stdout.write("Бот работает. Для остановки нажмите Ctrl+C.")
            while True:
                try:
                    updates = api("getUpdates", {
                        "offset": offset, "timeout": 25, "allowed_updates": ["message"],
                    }, timeout=35)
                    for update in updates:
                        handle_update(update)
                        offset = update["update_id"] + 1
                except TelegramError as exc:
                    self.stderr.write(str(exc))
                    time.sleep(5)
        except TelegramError as exc:
            raise CommandError(str(exc)) from None
        except KeyboardInterrupt:
            self.stdout.write("Бот остановлен.")
