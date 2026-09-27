"""Create a manager with salon booking, team and service permissions."""
from getpass import getpass

from django.contrib.auth import get_user_model
from django.contrib.auth.models import Group, Permission
from django.contrib.auth.password_validation import validate_password
from django.core.exceptions import ValidationError
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction
from clinic.models import UserProfile


class Command(BaseCommand):
    help = "Создать менеджера салона с запросом пароля."

    def add_arguments(self, parser):
        parser.add_argument("username")

    @transaction.atomic
    def handle(self, *args, **options):
        User = get_user_model()
        username = options["username"]
        if User.objects.filter(username=username).exists():
            raise CommandError("Такой логин уже существует. Выберите другой логин администратора.")
        user = User(username=username, is_staff=True, is_superuser=False)
        try:
            user.full_clean(exclude=["password"])
            password = getpass("Пароль: ")
            if password != getpass("Пароль ещё раз: "):
                raise CommandError("Пароли не совпадают.")
            validate_password(password, user=user)
        except ValidationError as exc:
            raise CommandError(" ".join(exc.messages)) from exc
        user.set_password(password)
        user.save()
        UserProfile.objects.create(user=user, role=UserProfile.Role.MANAGER)
        group, _ = Group.objects.get_or_create(name="Менеджеры салона")
        group.permissions.set(Permission.objects.filter(
            content_type__app_label="clinic",
            codename__in=["view_appointment", "change_appointment", "view_doctor",
                "view_appointmentslot", "add_appointmentslot", "change_appointmentslot",
                "view_salonservice", "add_salonservice", "change_salonservice",
                "add_doctor", "change_doctor", "view_clientmessage"],
        ))
        user.groups.add(group)
        self.stdout.write(self.style.SUCCESS(f"Администратор «{username}» создан. Вход: /admin/."))
