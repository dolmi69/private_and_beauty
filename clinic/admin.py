from django.contrib import admin

from .models import Appointment, AppointmentSlot, Doctor, UserProfile

admin.site.site_header = "Эвервелл · Управление клиникой"
admin.site.site_title = "Эвервелл · Администратор"
admin.site.index_title = "Управление записями и врачами"


@admin.register(Doctor)
class DoctorAdmin(admin.ModelAdmin):
    list_display = ["full_name", "specialty", "experience"]
    search_fields = ["full_name", "specialty"]
    list_filter = ["specialty"]


@admin.register(AppointmentSlot)
class AppointmentSlotAdmin(admin.ModelAdmin):
    list_display = ["doctor", "starts_at", "is_active"]
    list_filter = ["doctor", "is_active", "starts_at"]
    list_editable = ["is_active"]
    date_hierarchy = "starts_at"


@admin.register(UserProfile)
class UserProfileAdmin(admin.ModelAdmin):
    list_display = ["user", "role", "doctor", "phone_number"]
    list_filter = ["role"]
    search_fields = ["user__username", "user__first_name", "user__last_name"]
    readonly_fields = ["user", "role", "doctor", "phone_number"]

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False


@admin.register(Appointment)
class AppointmentAdmin(admin.ModelAdmin):
    list_display = ["id", "client_name", "phone_number", "doctor", "requested_at", "status"]
    list_display_links = ["id", "client_name"]
    list_editable = ["status"]
    list_filter = ["status", "doctor", "requested_at"]
    search_fields = ["client_name", "phone_number", "doctor__full_name"]
    date_hierarchy = "requested_at"
    readonly_fields = ["created_at", "client", "slot"]
    list_select_related = ["doctor"]
    list_per_page = 25
    ordering = ["-created_at"]
