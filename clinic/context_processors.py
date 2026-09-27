"""Small per-request template values shared by the public salon pages."""
from django.conf import settings


def clinic_context(request):
    return {
        "telegram_public_preview": getattr(settings, "TELEGRAM_PUBLIC_PREVIEW", False),
        "guest_ai_enabled": bool(settings.GIGACHAT_CREDENTIALS and not settings.CHAT_FORCE_MOCK),
        "guest_chat_history": request.session.get("clinic_chat", [])[-12:],
    }
