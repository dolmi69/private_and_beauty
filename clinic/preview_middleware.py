"""Never expose manager routes through the public preview, even with a forged Host."""
from django.http import HttpResponseNotFound


class VisitorOnlyMiddleware:
    allowed_paths = {
        "/", "/services/", "/doctors/", "/contacts/",
        "/api/chat/", "/api/chat/reset/", "/api/appointments/",
        "/register/", "/login/", "/logout/", "/cabinet/",
    }

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        if request.path_info not in self.allowed_paths and not (
            request.path_info.startswith("/api/doctors/") and request.path_info.endswith("/slots/")
        ) and not (
            request.path_info.startswith("/cabinet/appointments/") and request.path_info.endswith("/cancel/")
        ):
            return HttpResponseNotFound("Страница недоступна.")
        response = self.get_response(request)
        # Telegram Web embeds the visitor app in an iframe.
        if "X-Frame-Options" in response:
            del response["X-Frame-Options"]
        response["Content-Security-Policy"] = (
            "frame-ancestors 'self' https://web.telegram.org https://*.telegram.org"
        )
        return response
