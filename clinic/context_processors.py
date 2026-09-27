from django.conf import settings

from .models import Doctor


def clinic_context(request):
    # Admin does not need the visitor widget or a second directory query.
    if request.path.startswith("/admin/"):
        return {}
    return {
        "telegram_public_preview": getattr(settings, "TELEGRAM_PUBLIC_PREVIEW", False),
        "clinic_doctors": Doctor.objects.all(),
        "clinic_timezone": settings.TIME_ZONE,
        "clinic_timezone_label": "Московское время" if settings.TIME_ZONE == "Europe/Moscow" else settings.TIME_ZONE,
        "chat_is_mock": settings.CHAT_FORCE_MOCK or not settings.GIGACHAT_CREDENTIALS,
        "chat_history": request.session.get("clinic_chat", []),
    }
