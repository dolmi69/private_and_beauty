"""Beauty concierge and an optional GigaChat-powered schedule assistant.

Only aggregate schedule facts reach GigaChat; client identities and messages stay local.
"""
import hashlib
import json
import logging
import re
import time
import uuid
from datetime import date, datetime, timedelta

import requests
from django.conf import settings
from django.core.cache import cache
from django.utils import timezone

from .models import Appointment, AppointmentSlot

logger = logging.getLogger(__name__)
OAUTH_URL = "https://ngw.devices.sberbank.ru:9443/api/v2/oauth"


def _token_cache_key():
    digest = hashlib.sha256(f"{settings.GIGACHAT_CREDENTIALS}:{settings.GIGACHAT_SCOPE}".encode()).hexdigest()
    return f"gigachat-token:{digest}"


def _access_token():
    key = _token_cache_key()
    token = cache.get(key)
    if token:
        return token
    response = requests.post(OAUTH_URL,
        headers={"Authorization": f"Basic {settings.GIGACHAT_CREDENTIALS}",
                 "RqUID": str(uuid.uuid4()), "Accept": "application/json"},
        data={"scope": settings.GIGACHAT_SCOPE}, timeout=(5, 10),
        verify=settings.GIGACHAT_CA_BUNDLE or True, allow_redirects=False)
    response.raise_for_status()
    payload = response.json()
    token = payload["access_token"]
    if not isinstance(token, str) or not token:
        raise ValueError("Invalid access token")
    expires_at = float(payload["expires_at"])
    if expires_at > 100_000_000_000:
        expires_at /= 1000
    cache.set(key, token, timeout=max(1, min(1740, int(expires_at - time.time() - 60))))
    return token


def _gigachat_answer(system_prompt, question):
    response = requests.post(f"{settings.GIGACHAT_BASE_URL}/chat/completions",
        headers={"Authorization": f"Bearer {_access_token()}", "Accept": "application/json"},
        json={"model": settings.GIGACHAT_MODEL, "messages": [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": question}],
            "temperature": 0, "max_tokens": 180, "stream": False},
        timeout=(5, 15), verify=settings.GIGACHAT_CA_BUNDLE or True,
        allow_redirects=False)
    if response.status_code == 401:
        cache.delete(_token_cache_key())
    response.raise_for_status()
    answer = response.json()["choices"][0]["message"]["content"]
    if not isinstance(answer, str) or not 1 <= len(answer) <= 1200:
        raise ValueError("Invalid assistant response")
    return answer.strip()


SERVICE_HINTS = {
    "nails": ("маник", "педик", "ногт", "покрыти"),
    "hair": ("волос", "стриж", "окраш", "уклад", "тонир"),
    "brows": ("бров", "ресниц", "ламинир"),
    "makeup": ("макияж", "визаж", "мейкап"),
}


def receptionist_reply(history, services):
    """Recommend a real service and lead the guest to date-based booking."""
    message = history[-1]["content"].casefold()
    chosen = next((item for item in services if item["title"].casefold() in message), None)
    if chosen is None:
        category = next((key for key, words in SERVICE_HINTS.items()
                         if any(word in message for word in words)), None)
        chosen = next((item for item in services if item["category"] == category), None)
    if chosen:
        reply = (f"Вам может подойти «{chosen['title']}». Выберите день — покажем мастеров "
                 "и свободное время. Если хотите, расскажите о желаемом результате.")
    else:
        reply = "Подскажу с выбором. Что вам ближе: волосы, маникюр, брови и ресницы или макияж?"
    return {"reply": reply, "recommended_service": chosen, "mode": "local"}


WEEKDAYS = ("понедельник", "вторник", "среда", "четверг", "пятница", "суббота", "воскресенье")
WEEKDAY_STEMS = ("понедель", "втор", "сред", "четвер", "пятниц", "суббот", "воскресен")


def requested_schedule_date(question, today=None):
    """Resolve a Russian day reference to the next occurrence in local time."""
    today = today or timezone.localdate()
    text = question.casefold()
    if "послезавтра" in text:
        return today + timedelta(days=2)
    if "завтра" in text:
        return today + timedelta(days=1)
    if "сегодня" in text:
        return today
    match = re.search(r"(?<!\d)(\d{1,2})\.(\d{1,2})(?:\.(\d{4}))?(?!\d)", text)
    if match:
        try:
            candidate = date(int(match[3] or today.year), int(match[2]), int(match[1]))
            if match[3] is None and candidate < today:
                candidate = candidate.replace(year=today.year + 1)
            return candidate
        except ValueError:
            return None
    for number, stem in enumerate(WEEKDAY_STEMS):
        if stem in text:
            delta = (number - today.weekday()) % 7
            if "следующ" in text and delta == 0:
                delta = 7
            return today + timedelta(days=delta)
    return today


def schedule_facts(specialist, day):
    starts = timezone.make_aware(datetime.combine(day, datetime.min.time()))
    ends = starts + timedelta(days=1)
    slots = list(AppointmentSlot.objects.filter(doctor=specialist, is_active=True,
        starts_at__gte=starts, starts_at__lt=ends).order_by("starts_at"))
    appointments = list(Appointment.objects.filter(doctor=specialist, service__isnull=False,
        status__in=["pending", "confirmed"], requested_at__gte=starts,
        requested_at__lt=ends).select_related("service").order_by("requested_at"))
    booked = {item.requested_at for item in appointments}
    free = [timezone.localtime(slot.starts_at).strftime("%H:%M")
            for slot in slots if slot.starts_at not in booked]
    last_end = max((item.requested_at + timedelta(minutes=item.service.duration_minutes)
                    for item in appointments), default=None)
    return {
        "date": day.strftime("%d.%m.%Y"), "weekday": WEEKDAYS[day.weekday()],
        "capacity": len(slots), "booked": len(appointments), "free": free,
        "first_booking": timezone.localtime(appointments[0].requested_at).strftime("%H:%M") if appointments else None,
        "last_end": timezone.localtime(last_end).strftime("%H:%M") if last_end else None,
        "shift_end": timezone.localtime(slots[-1].starts_at + timedelta(minutes=60)).strftime("%H:%M") if slots else None,
    }


def local_schedule_answer(question, facts):
    title = f"{facts['weekday'].capitalize()}, {facts['date']}"
    if not facts["capacity"]:
        return f"{title}: рабочих часов пока нет в календаре."
    if any(word in question.casefold() for word in ("освобожд", "заканч", "конец", "последн")):
        if facts["last_end"]:
            return (f"{title}: последний клиент заканчивает в {facts['last_end']}. "
                    f"По календарю смена до {facts['shift_end']}; свободных окон: {len(facts['free'])}.")
        return f"{title}: записей нет. По календарю смена до {facts['shift_end']}."
    free = ", ".join(facts["free"][:12]) or "нет"
    return (f"{title}: клиентов {facts['booked']} из {facts['capacity']} возможных записей. "
            f"Первый клиент: {facts['first_booking'] or 'нет'}. "
            f"Последний заканчивает: {facts['last_end'] or 'нет'}. Свободно: {free}.")


def specialist_schedule_reply(question, specialist):
    day = requested_schedule_date(question)
    if day is None:
        return {"reply": "Не смогла распознать дату. Напишите, например: «Во сколько я освобождаюсь во вторник?»", "mode": "local"}
    facts = schedule_facts(specialist, day)
    fallback = local_schedule_answer(question, facts)
    if settings.GIGACHAT_CREDENTIALS and not settings.CHAT_FORCE_MOCK:
        try:
            # The master's raw question may contain a client name or phone number.
            # Send only a normalized schedule intent and aggregate facts outside Django.
            finish_intent = any(word in question.casefold() for word in
                                ("освобожд", "заканч", "конец", "последн"))
            safe_question = ("Когда заканчивается последний клиент и смена?" if finish_intent
                             else "Сколько клиентов записано и какие часы свободны?")
            prompt = ("Ты помощник мастера салона красоты. Отвечай по-русски кратко и только "
                      "на основании JSON расписания ниже. Не придумывай записи, клиентов или время. "
                      "Если вопрос за пределами расписания, так и скажи. Персональных данных нет. "
                      "Расписание: " + json.dumps(facts, ensure_ascii=False))
            return {"reply": _gigachat_answer(prompt, safe_question), "mode": "gigachat", "facts": facts}
        except (requests.RequestException, ValueError, KeyError, IndexError, TypeError, OSError) as exc:
            logger.warning("GigaChat schedule unavailable; using local answer (%s).", type(exc).__name__)
    return {"reply": fallback, "mode": "local", "facts": facts}
