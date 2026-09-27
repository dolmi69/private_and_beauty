from django.urls import path

from . import views
from . import portal

app_name = "clinic"
urlpatterns = [
    path("", views.home, name="home"),
    path("services/", views.services, name="services"),
    path("masters/", views.doctors, name="doctors"),
    path("doctors/", views.doctors, name="legacy_doctors"),
    path("contacts/", views.contacts, name="contacts"),
    path("register/", views.register, name="register"),
    path("cabinet/", views.dashboard, name="dashboard"),
    path("booking/", views.booking, name="booking"),
    path("api/availability/", views.availability_api, name="availability_api"),
    path("specialist/", portal.master_calendar, name="master_calendar"),
    path("specialist/chats/", portal.master_chats, name="master_chats"),
    path("specialist/assistant/", portal.master_assistant, name="master_assistant"),
    path("chats/<int:pk>/", portal.conversation, name="conversation"),
    path("cabinet/appointments/<int:pk>/cancel/", views.cancel_appointment, name="cancel_appointment"),
    path("manager/team/", views.manager_team, name="manager_team"),
    path("api/doctors/<int:doctor_id>/slots/", views.slots_api, name="slots_api"),
    path("api/chat/", views.chat, name="chat"),
    path("api/chat/reset/", views.reset_chat, name="reset_chat"),
    path("api/appointments/", views.book_appointment, name="book_appointment"),
    path("manager/dashboard/", views.manager_dashboard, name="manager_dashboard"),
]
