from unittest.mock import patch

from django.test import SimpleTestCase, override_settings

from .telegram_bot import TelegramError, handle_update, mini_app_url


class TelegramTests(SimpleTestCase):
    @override_settings(TELEGRAM_MINI_APP_URL="https://clinic.example/")
    @patch("clinic.telegram_bot.api")
    def test_start_opens_same_site(self, api):
        handle_update({"message": {"text": "/start", "chat": {"id": 12, "type": "private"}}})
        payload = api.call_args.args[1]
        self.assertEqual(payload["reply_markup"]["inline_keyboard"][0][0]["web_app"]["url"], "https://clinic.example/")

    @override_settings(TELEGRAM_MINI_APP_URL="")
    @patch("clinic.telegram_bot.api")
    def test_without_url_does_not_offer_broken_button(self, api):
        handle_update({"message": {"text": "/start", "chat": {"id": 12, "type": "private"}}})
        self.assertNotIn("reply_markup", api.call_args.args[1])

    @patch("clinic.telegram_bot.api")
    def test_groups_do_not_receive_replies(self, api):
        handle_update({"message": {"text": "/start", "chat": {"id": 12, "type": "group"}}})
        api.assert_not_called()

    def test_invalid_urls_are_rejected(self):
        for url in ("http://clinic.example/", "https://localhost/", "https://user:password@clinic.example/"):
            with self.subTest(url=url), override_settings(TELEGRAM_MINI_APP_URL=url):
                with self.assertRaises(TelegramError):
                    mini_app_url()
