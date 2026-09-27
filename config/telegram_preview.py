"""Isolated visitor-only server for a temporary Telegram HTTPS tunnel."""
from .settings import *  # noqa: F403

DEBUG = False
SECRET_KEY = os.environ["TELEGRAM_PREVIEW_SECRET"]
ALLOWED_HOSTS = [os.environ["TELEGRAM_PREVIEW_HOST"], "127.0.0.1"]
CSRF_TRUSTED_ORIGINS = ["https://" + os.environ["TELEGRAM_PREVIEW_HOST"]]
TELEGRAM_PUBLIC_PREVIEW = True
SECURE_SSL_REDIRECT = False  # HTTPS terminates at Cloudflare; upstream is loopback.
SECURE_PROXY_SSL_HEADER = ("HTTP_X_FORWARDED_PROTO", "https")
SESSION_COOKIE_SECURE = True
CSRF_COOKIE_SECURE = True
SESSION_COOKIE_NAME = "clinic_telegram_session"
CSRF_COOKIE_NAME = "clinic_telegram_csrf"
MIDDLEWARE = ["clinic.preview_middleware.VisitorOnlyMiddleware"] + MIDDLEWARE
