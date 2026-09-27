"""Минимальный Bot API клиент. Не записывает токен и URL запросов в журналы."""
from urllib.parse import urlsplit

import requests
from django.conf import settings


class TelegramError(Exception):
    pass


def api(method, payload=None, timeout=15):
    if not settings.TELEGRAM_BOT_TOKEN:
        raise TelegramError("Не задан TELEGRAM_BOT_TOKEN в .env.")
    try:
        response = requests.post(
            f"https://api.telegram.org/bot{settings.TELEGRAM_BOT_TOKEN}/{method}",
            json=payload or {}, timeout=(5, timeout), allow_redirects=False,
        )
        if response.status_code != 200:
            raise TelegramError(f"Telegram API вернул HTTP {response.status_code}. Проверьте токен и сеть.")
        result = response.json()
        if not result.get("ok"):
            raise TelegramError("Telegram API отклонил запрос.")
        return result["result"]
    except (requests.RequestException, ValueError):
        raise TelegramError("Не удалось соединиться с Telegram API.") from None


def mini_app_url():
    url = settings.TELEGRAM_MINI_APP_URL
    if not url:
        return None
    parsed = urlsplit(url)
    if parsed.scheme != "https" or not parsed.hostname or parsed.username or parsed.password:
        raise TelegramError("TELEGRAM_MINI_APP_URL должен быть публичным HTTPS-адресом без учётных данных.")
    if parsed.hostname in {"localhost", "127.0.0.1", "::1"}:
        raise TelegramError("Telegram не может открыть localhost. Нужен публичный HTTPS-адрес.")
    return url


def handle_update(update):
    message = update.get("message", {})
    chat = message.get("chat", {})
    # В группах не отвечаем: кнопка web_app предназначена для личного чата.
    if chat.get("type") != "private" or not isinstance(message.get("text"), str):
        return
    command = message["text"].split()[0].split("@")[0] if message["text"].strip() else ""
    if command not in {"/start", "/help", "/clinic"}:
        return
    url = mini_app_url()
    payload = {"chat_id": chat["id"], "text": (
        "Здравствуйте! Это клиника «Эвервелл». Откройте приложение: там наши услуги, врачи, "
        "контакты, помощник и запись на приём. Заявку подтвердит администратор."
        if url else "Здравствуйте! Бот клиники «Эвервелл» подключён. Приложение готовится к запуску: "
        "администратору нужно подключить публичный HTTPS-адрес."
    )}
    if url:
        payload["reply_markup"] = {"inline_keyboard": [[{
            "text": "Открыть клинику", "web_app": {"url": url},
        }]]}
    api("sendMessage", payload)
