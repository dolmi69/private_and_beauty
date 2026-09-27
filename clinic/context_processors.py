"""Small per-request template values shared by the public salon pages."""
from django.conf import settings


def clinic_context(request):
    return {"telegram_public_preview": getattr(settings, "TELEGRAM_PUBLIC_PREVIEW", False)}
