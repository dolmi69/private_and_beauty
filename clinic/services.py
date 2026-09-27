"""GigaChat salon concierge and staff assistant, with local fallbacks.

Staff schedule questions are reduced to intents before they leave Django. Guest
messages are scrubbed of phone numbers and email addresses before the API call.
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


def _gigachat_answer(system_prompt, question, *, history=(), temperature=0, max_tokens=180):
    messages = [{"role": "system", "content": system_prompt}]
    messages.extend({"role": item["role"], "content": item["content"]}
                    for item in history if item.get("role") in {"user", "assistant"}
                    and isinstance(item.get("content"), str))
    messages.append({"role": "user", "content": question})
    response = requests.post(f"{settings.GIGACHAT_BASE_URL}/chat/completions",
        headers={"Authorization": f"Bearer {_access_token()}", "Accept": "application/json"},
        json={"model": settings.GIGACHAT_MODEL, "messages": messages,
              "temperature": temperature, "max_tokens": max_tokens, "stream": False},
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
EMAIL_RE = re.compile(r"\b[A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,}\b", re.IGNORECASE)
PHONE_RE = re.compile(r"(?<!\w)(?:\+?7|8)[\s().-]*(?:\d[\s().-]*){10}(?!\d)")


def scrub_guest_message(message):
    """Booking does not need contact details; keep them out of model context."""
    return PHONE_RE.sub("[номер скрыт]", EMAIL_RE.sub("[адрес скрыт]", message))


def recommended_service(history, services, previous_service_id=None):
    message = history[-1]["content"].casefold()
    for phrase, title in (("без покрытия", "Маникюр без покрытия"),
                          ("с покрытием", "Маникюр с покрытием"),
                          ("гель-лак", "Маникюр с покрытием")):
        if phrase in message:
            match = next((item for item in services if item["title"] == title), None)
            if match:
                return match
    chosen = next((item for item in services if item["title"].casefold() in message), None)
    if chosen:
        return chosen
    category = next((key for key, words in SERVICE_HINTS.items()
                     if any(word in message for word in words)), None)
    if category:
        return next((item for item in services if item["category"] == category), None)
    for previous in reversed(history[:-1]):
        if previous.get("role") == "assistant":
            chosen = next((item for item in services
                           if item["title"].casefold() in previous.get("content", "").casefold()), None)
            if chosen:
                return chosen
    return next((item for item in services if item["id"] == previous_service_id), None)


def _local_guest_answer(history, chosen, availability):
    message = history[-1]["content"].casefold()
    if chosen and any(word in message for word in ("стоим", "цен", "сколько стоит", "дорог")):
        return (f"«{chosen['title']}» стоит {chosen['price']} ₽, длится "
                f"{chosen['duration_minutes']} минут. Могу подсказать мастера и свободное время.")
    if availability is not None:
        masters = availability["masters"]
        day_label = date.fromisoformat(availability["date"]).strftime("%d.%m.%Y")
        requested_master = availability.get("requested_master")
        selected = next((item for item in masters if item["name"] == requested_master), None)
        if selected:
            times = ", ".join(selected["times"][:8])
            return (f"{day_label}, мастер {selected['name']}: свободно {times}. "
                    "Выберите удобный час в форме записи.")
        if masters and requested_master:
            alternative = masters[0]
            return (f"{day_label}, мастер {requested_master}: свободных часов нет. "
                    f"Мастер {alternative['name']}: {', '.join(alternative['times'][:5])}.")
        if masters:
            options = "; ".join(f"{item['name']}: {', '.join(item['times'][:4])}"
                                for item in masters[:3])
            return f"На {day_label} есть свободное время: {options}. Выберите удобный час в форме записи."
        return f"На {day_label} свободного времени пока нет. Попробуйте соседний день."
    if chosen and any(word in message for word in ("длит", "долго", "сколько времени")):
        return f"«{chosen['title']}» занимает {chosen['duration_minutes']} минут."
    if any(word in message for word in ("работаете", "режим", "часы работы", "открыты")):
        return "Салон работает с понедельника по субботу, запись доступна с 10:00 до 20:00."
    if chosen:
        variants = (
            f"Для вашего запроса подойдёт «{chosen['title']}»: {chosen['description']} Стоимость {chosen['price']} ₽.",
            f"Можно начать с услуги «{chosen['title']}». Её делают наши мастера: "
            f"{', '.join(chosen['specialists'])}.",
        )
        return variants[len(history) % len(variants)]
    return "Расскажите, какой результат хочется получить: маникюр, волосы, брови, ресницы или макияж?"


def mentioned_day(message):
    text = message.casefold()
    if any(word in text for word in ("сегодня", "завтра", "послезавтра", *WEEKDAY_STEMS)) or re.search(r"\d{1,2}\.\d{1,2}", text):
        return requested_schedule_date(message)
    return None


def receptionist_reply(history, services, availability=None, previous_service_id=None):
    """Answer from the live salon catalogue; preserve conversational context."""
    chosen = recommended_service(history, services, previous_service_id)
    fallback = _local_guest_answer(history, chosen, availability)
    # Availability is a hard fact. A language model may misread a list of free
    # slots, so construct that answer from the booking database directly.
    if availability is not None and not any(word in history[-1]["content"].casefold()
                                            for word in ("стоим", "цен", "сколько стоит")):
        return {"reply": fallback, "recommended_service": chosen, "mode": "verified"}
    if settings.GIGACHAT_CREDENTIALS and not settings.CHAT_FORCE_MOCK:
        catalogue = [{key: item[key] for key in
                     ("title", "category", "description", "price", "duration_minutes", "specialists")}
                     for item in services]
        prompt = (
            "Ты Лави, живой и тактичный консьерж салона красоты LAVIE. Пиши по-русски, "
            "на 'вы', тепло и естественно, 1–3 короткими предложениями, без Markdown. "
            "Отвечай именно на последний вопрос с учётом истории диалога. Не повторяй прежний "
            "ответ и не предлагай снова выбрать день, если клиент уже назвал его. "
            "Точные услуги, цены, длительность и мастеров бери только из JSON каталога. "
            "У LAVIE один демонстрационный салон; не упоминай филиалы, адреса, акции, "
            "скидки или способы связи, которых нет в данных. "
            "Свободные часы называй только если они есть в JSON доступности. "
            "Если данных нет, честно скажи об этом и предложи форму онлайн-записи. "
            "Не обещай запись: её подтверждает менеджер. Не спрашивай телефон или диагноз, "
            "не давай медицинских советов. При неясном запросе задай только один уместный вопрос. "
            "Каталог: " + json.dumps(catalogue, ensure_ascii=False) +
            " Услуга, обсуждаемая сейчас: " + json.dumps(chosen["title"] if chosen else None, ensure_ascii=False) +
            " Доступность на запрошенную дату: " + json.dumps(availability, ensure_ascii=False)
        )
        try:
            answer = _gigachat_answer(prompt, history[-1]["content"], history=history[-9:-1],
                                      temperature=0.55, max_tokens=260)
            return {"reply": answer, "recommended_service": chosen, "mode": "gigachat"}
        except (requests.RequestException, ValueError, KeyError, IndexError, TypeError, OSError) as exc:
            logger.warning("GigaChat concierge unavailable; using local answer (%s).", type(exc).__name__)
    return {"reply": fallback, "recommended_service": chosen, "mode": "local"}


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
    bookings = [{"start": timezone.localtime(item.requested_at).strftime("%H:%M"),
                 "end": timezone.localtime(item.requested_at + timedelta(minutes=item.service.duration_minutes)).strftime("%H:%M"),
                 "service": item.service.title, "status": item.status}
                for item in appointments]
    service_counts = {}
    for item in appointments:
        service_counts[item.service.title] = service_counts.get(item.service.title, 0) + 1
    return {
        "date": day.strftime("%d.%m.%Y"), "weekday": WEEKDAYS[day.weekday()],
        "capacity": len(slots), "booked": len(appointments), "free": free,
        "first_booking": timezone.localtime(appointments[0].requested_at).strftime("%H:%M") if appointments else None,
        "last_end": timezone.localtime(last_end).strftime("%H:%M") if last_end else None,
        "shift_end": timezone.localtime(slots[-1].starts_at + timedelta(minutes=60)).strftime("%H:%M") if slots else None,
        "bookings": bookings, "service_counts": service_counts,
    }


def mentioned_schedule_service(question, service_counts):
    """Recognize common Russian inflections without forwarding the raw question."""
    text = question.casefold()
    for title in service_counts:
        if title.casefold() in text:
            return title
    if "маник" in text:
        if "без покры" in text:
            return next((title for title in service_counts if "маникюр без покрытия" in title.casefold()), None)
        if "покры" in text:
            return next((title for title in service_counts if "маникюр с покрытием" in title.casefold()), None)
    for stem in ("стриж", "уклад", "тонир", "педик", "бров", "ресниц", "макияж"):
        if stem in text:
            return next((title for title in service_counts if stem in title.casefold()), None)
    return None


def local_schedule_answer(question, facts):
    title = f"{facts['weekday'].capitalize()}, {facts['date']}"
    if not facts["capacity"]:
        return f"{title}: рабочих часов пока нет в календаре."
    service = mentioned_schedule_service(question, facts["service_counts"])
    if service:
        count = facts["service_counts"][service]
        times = ", ".join(item["start"] for item in facts["bookings"] if item["service"] == service)
        return f"{title}: «{service}» — {count} записей, начало в {times}."
    if any(word in question.casefold() for word in ("освобожд", "заканч", "конец", "последн")):
        if facts["last_end"]:
            return (f"{title}: последний клиент заканчивает в {facts['last_end']}. "
                    f"По календарю смена до {facts['shift_end']}; свободных окон: {len(facts['free'])}.")
        return f"{title}: записей нет. По календарю смена до {facts['shift_end']}."
    free = ", ".join(facts["free"][:12]) or "нет"
    return (f"{title}: клиентов {facts['booked']} из {facts['capacity']} возможных записей. "
            f"Первый клиент: {facts['first_booking'] or 'нет'}. "
            f"Последний заканчивает: {facts['last_end'] or 'нет'}. Свободно: {free}.")


def specialist_schedule_reply(question, specialist, day=None):
    day = day or requested_schedule_date(question)
    if day is None:
        return {"reply": "Не смогла распознать дату. Напишите, например: «Во сколько я освобождаюсь во вторник?»", "mode": "local"}
    facts = schedule_facts(specialist, day)
    fallback = local_schedule_answer(question, facts)
    if settings.GIGACHAT_CREDENTIALS and not settings.CHAT_FORCE_MOCK:
        try:
            # The master's raw question may contain a client name or phone number.
            # Send only a normalized schedule intent and aggregate facts outside Django.
            lowered = question.casefold()
            service = mentioned_schedule_service(question, facts["service_counts"])
            if service:
                safe_question = f"Сколько записей на услугу «{service}» и в какое время они начинаются?"
            elif any(word in lowered for word in ("освобожд", "заканч", "конец", "последн")):
                safe_question = "Когда заканчивается последний клиент и смена?"
            elif any(word in lowered for word in ("свобод", "окн", "мест")):
                safe_question = "Какие часы свободны для записи?"
            else:
                safe_question = "Какова загрузка, число клиентов и расписание на этот день?"
            prompt = ("Ты персональный помощник мастера салона красоты LAVIE. Отвечай по-русски "
                      "по существу, обычно одним-двумя предложениями, только на основании JSON расписания ниже. "
                      "Различай окончание последней услуги и конец смены. "
                      "Дата в JSON может быть будущей: не говори «сейчас» о будущих записях. "
                      "Не придумывай записи, клиентов или время. Не повторяй шаблонную фразу. "
                      "Если вопрос за пределами расписания, так и скажи. Персональных данных нет. "
                      "Расписание: " + json.dumps(facts, ensure_ascii=False))
            return {"reply": _gigachat_answer(prompt, safe_question, temperature=0.3,
                                               max_tokens=160), "mode": "gigachat", "facts": facts}
        except (requests.RequestException, ValueError, KeyError, IndexError, TypeError, OSError) as exc:
            logger.warning("GigaChat schedule unavailable; using local answer (%s).", type(exc).__name__)
    return {"reply": fallback, "mode": "local", "facts": facts}
