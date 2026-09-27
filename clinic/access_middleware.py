"""Master accounts live in a focused workspace with calendar and client chats."""
from django.http import JsonResponse
from django.shortcuts import redirect

from .models import UserProfile


class MasterWorkspaceMiddleware:
    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        user = request.user
        if user.is_authenticated and not user.is_staff and UserProfile.objects.filter(
            user=user, role=UserProfile.Role.DOCTOR).exists():
            path = request.path_info
            allowed = (path.startswith("/specialist/") or path.startswith("/chats/")
                       or path.startswith("/static/") or path in {"/logout/", "/login/"})
            if not allowed:
                if path.startswith("/api/"):
                    return JsonResponse({"error": "Откройте рабочий кабинет мастера."}, status=403)
                return redirect("clinic:master_calendar")
        return self.get_response(request)
