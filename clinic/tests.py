"""Salon booking, private chats and master schedule behavior."""
import json
from datetime import date, datetime, time, timedelta
from unittest.mock import patch
import requests

from django.conf import settings
from django.contrib.auth import get_user_model
from django.contrib.auth.models import Permission
from django.core.cache import cache
from django.test import Client, SimpleTestCase, TestCase, override_settings
from django.urls import reverse
from django.utils import timezone

from .models import Appointment, AppointmentSlot, ClientMessage, Doctor, SalonService, UserProfile
from .services import requested_schedule_date, specialist_schedule_reply


@override_settings(CHAT_FORCE_MOCK=True, CHAT_RATE_LIMIT=100, BOOKING_RATE_LIMIT=100)
class BeautyTests(TestCase):
    def setUp(self):
        cache.clear()
        self.master = Doctor.objects.get(pk=3)
        self.other_master = Doctor.objects.get(pk=1)
        self.service = SalonService.objects.get(title="Маникюр с покрытием")
        self.other_service = SalonService.objects.get(title="Женская стрижка")
        self.day = timezone.localdate() + timedelta(days=2)
        self.start = timezone.make_aware(datetime.combine(self.day, time(11)))
        self.slot = AppointmentSlot.objects.create(doctor=self.master, starts_at=self.start)

    def patient(self, username="anna"):
        user = get_user_model().objects.create_user(
            username=username, password="Patient-Password-93!", first_name="Анна", last_name="Иванова")
        UserProfile.objects.create(user=user, role="client", phone_number="+79001112233")
        return user

    def master_account(self, master=None, username="master"):
        user = get_user_model().objects.create_user(username=username, password="Master-Password-93!")
        UserProfile.objects.create(user=user, role="doctor", doctor=master or self.master)
        return user

    def book(self, **overrides):
        data = {"service": self.service.pk, "doctor": self.master.pk, "slot": self.slot.pk}
        data.update(overrides)
        return self.client.post(reverse("clinic:book_appointment"),
            data=json.dumps(data), content_type="application/json")

    def test_seeded_salon_directory_and_public_pages(self):
        self.assertEqual(Doctor.objects.count(), 6)
        self.assertEqual(SalonService.objects.count(), 9)
        self.assertEqual(self.master.specialty, "Мастер маникюра")
        for page in ("home", "services", "doctors", "contacts", "booking"):
            with self.subTest(page=page):
                response = self.client.get(reverse("clinic:" + page))
                self.assertEqual(response.status_code, 200)
                self.assertContains(response, "LAVIE")

    def test_registration_can_only_create_a_client(self):
        response = self.client.post(reverse("clinic:register"), {
            "username": "newclient", "first_name": "Анна", "last_name": "Иванова",
            "phone_number": "+7 900 111 22 33", "role": "doctor", "is_staff": "on",
            "password1": "Patient-Password-93!", "password2": "Patient-Password-93!",
        })
        self.assertRedirects(response, reverse("clinic:dashboard"))
        user = get_user_model().objects.get(username="newclient")
        self.assertEqual(user.clinic_profile.role, "client")
        self.assertFalse(user.is_staff)

    def test_day_and_service_filter_available_masters(self):
        response = self.client.get(reverse("clinic:availability_api"), {
            "service": self.service.pk, "date": self.day.isoformat()})
        self.assertEqual(response.status_code, 200)
        masters = response.json()["masters"]
        self.assertEqual([item["id"] for item in masters], [self.master.pk])
        self.assertEqual(masters[0]["slots"], [{"id": self.slot.pk, "time": "11:00"}])
        self.assertEqual(self.client.get(reverse("clinic:availability_api"), {
            "service": self.service.pk, "date": "2020-01-01"}).status_code, 400)

    @override_settings(GIGACHAT_CREDENTIALS="fake", CHAT_FORCE_MOCK=False)
    @patch("clinic.services._gigachat_answer", side_effect=[
        "Конечно, помогу подобрать!",
        "Эта услуга стоит 2500 ₽ и занимает час.",
    ])
    def test_guest_ai_uses_catalogue_history_and_hides_phone(self, provider):
        first = self.client.post(reverse("clinic:chat"),
            data=json.dumps({"message": "Хочу маникюр с покрытием"}), content_type="application/json")
        second = self.client.post(reverse("clinic:chat"),
            data=json.dumps({"message": "Сколько стоит? Мой номер +79001112233"}),
            content_type="application/json")
        self.assertEqual(first.json()["mode"], "gigachat")
        self.assertEqual(second.json()["reply"], "Эта услуга стоит 2500 ₽ и занимает час.")
        self.assertEqual(second.json()["recommended_service"]["id"], self.service.pk)
        self.assertIn("2500", provider.call_args.args[0])
        self.assertIn("Конечно, помогу", str(provider.call_args.kwargs["history"]))
        self.assertNotIn("+79001112233", str(provider.call_args))
        self.assertNotIn("+79001112233", str(self.client.session["clinic_chat"]))

    @override_settings(GIGACHAT_CREDENTIALS="fake", CHAT_FORCE_MOCK=False)
    @patch("clinic.services._gigachat_answer", side_effect=requests.RequestException("offline"))
    def test_guest_ai_outage_has_specific_local_answer(self, provider):
        response = self.client.post(reverse("clinic:chat"),
            data=json.dumps({"message": "Сколько стоит маникюр с покрытием?"}),
            content_type="application/json")
        self.assertEqual(response.json()["mode"], "local")
        self.assertIn("2500 ₽", response.json()["reply"])

    @override_settings(GIGACHAT_CREDENTIALS="fake", CHAT_FORCE_MOCK=False)
    @patch("clinic.services._gigachat_answer", return_value="Помогу с маникюром.")
    def test_guest_ai_receives_real_availability_and_can_reset(self, provider):
        first = self.client.post(reverse("clinic:chat"),
            data=json.dumps({"message": "Хочу маникюр с покрытием"}), content_type="application/json")
        self.assertEqual(first.json()["mode"], "gigachat")
        second = self.client.post(reverse("clinic:chat"),
            data=json.dumps({"message": f"Есть время {self.day:%d.%m.%Y} у Софии?"}),
            content_type="application/json")
        self.assertEqual(second.json()["mode"], "verified")
        self.assertIn("11:00", second.json()["reply"])
        self.assertIn(self.master.full_name, second.json()["reply"])
        self.assertEqual(provider.call_count, 1)
        self.assertEqual(self.client.post(reverse("clinic:reset_chat")).status_code, 200)
        self.assertNotIn("clinic_chat_service_id", self.client.session)

    def test_booking_checks_login_service_master_and_unique_time(self):
        self.assertEqual(self.book().status_code, 401)
        user = self.patient()
        self.client.force_login(user)
        self.assertEqual(self.book(service=self.other_service.pk).status_code, 400)
        self.assertEqual(self.book(status="confirmed", client_name="Fake").status_code, 201)
        item = Appointment.objects.get()
        self.assertEqual(item.client, user)
        self.assertEqual(item.service, self.service)
        self.assertEqual(item.client_name, "Анна Иванова")
        self.assertEqual(item.status, "pending")
        self.assertEqual(self.book().status_code, 400)
        self.client.post(reverse("clinic:cancel_appointment", args=[item.pk]))
        self.assertEqual(self.book().status_code, 201)

    def test_client_and_master_can_chat_only_on_their_own_booking(self):
        client = self.patient()
        self.client.force_login(client)
        self.book()
        item = Appointment.objects.get()
        url = reverse("clinic:conversation", args=[item.pk])
        self.assertEqual(self.client.post(url, {"body": "Нужен спокойный оттенок"}).status_code, 302)
        self.assertEqual(ClientMessage.objects.count(), 1)
        self.client.force_login(self.patient("stranger"))
        self.assertEqual(self.client.get(url).status_code, 403)
        self.client.force_login(self.master_account(self.other_master, "othermaster"))
        self.assertEqual(self.client.get(url).status_code, 403)
        master = self.master_account()
        self.client.force_login(master)
        self.assertContains(self.client.get(url), "Нужен спокойный оттенок")
        self.assertEqual(self.client.post(url, {"body": "Подготовим варианты"}).status_code, 302)
        self.assertEqual(ClientMessage.objects.count(), 2)

    def test_master_calendar_shows_own_clients_and_load(self):
        client = self.patient()
        self.client.force_login(client)
        self.book()
        master = self.master_account()
        self.client.force_login(master)
        response = self.client.get(reverse("clinic:master_calendar"), {"date": self.day.isoformat()})
        self.assertContains(response, "Анна Иванова")
        self.assertContains(response, "Календарь мастера")
        self.assertContains(response, "11:00")
        self.assertNotContains(response, "Подтвердить запись")
        self.assertRedirects(self.client.get(reverse("clinic:home")), reverse("clinic:master_calendar"))
        self.assertEqual(self.book().status_code, 403)

    def test_schedule_assistant_answers_finish_time_and_uses_only_own_facts(self):
        client = self.patient()
        self.client.force_login(client)
        self.book()
        master = self.master_account()
        self.client.force_login(master)
        response = self.client.post(reverse("clinic:master_assistant"),
            data=json.dumps({"question": f"Во сколько я освобождаюсь {self.day:%d.%m.%Y}?"}),
            content_type="application/json")
        self.assertEqual(response.status_code, 200)
        self.assertIn("12:00", response.json()["reply"])
        self.assertEqual(response.json()["facts"]["booked"], 1)
        self.assertNotIn("Анна", json.dumps(response.json(), ensure_ascii=False))

    def test_master_assistant_follow_up_keeps_requested_day(self):
        self.client.force_login(self.master_account())
        endpoint = reverse("clinic:master_assistant")
        first = self.client.post(endpoint,
            data=json.dumps({"question": f"Какова загрузка {self.day:%d.%m.%Y}?"}),
            content_type="application/json")
        follow_up = self.client.post(endpoint,
            data=json.dumps({"question": "А какие свободные часы?"}),
            content_type="application/json")
        self.assertEqual(first.status_code, 200)
        self.assertEqual(follow_up.status_code, 200)
        self.assertEqual(follow_up.json()["facts"]["date"], self.day.strftime("%d.%m.%Y"))
        self.assertIn("11:00", follow_up.json()["reply"])

    @override_settings(GIGACHAT_CREDENTIALS="fake", CHAT_FORCE_MOCK=False)
    @patch("clinic.services._gigachat_answer", return_value="Последний клиент до 12:00.")
    def test_external_assistant_gets_no_client_identity(self, provider):
        client = self.patient()
        self.client.force_login(client)
        self.book()
        result = specialist_schedule_reply(
            f"Когда освобождаюсь {self.day:%d.%m.%Y} после Анны +79001112233?", self.master)
        self.assertEqual(result["mode"], "gigachat")
        self.assertNotIn("Анна", provider.call_args.args[0])
        self.assertNotIn("+7900", provider.call_args.args[0])
        self.assertNotIn("Анна", provider.call_args.args[1])
        self.assertNotIn("+7900", provider.call_args.args[1])

    @override_settings(GIGACHAT_CREDENTIALS="fake", CHAT_FORCE_MOCK=False)
    @patch("clinic.services._gigachat_answer", return_value="Один маникюр с покрытием в 11:00.")
    def test_master_ai_understands_inflected_service_name(self, provider):
        self.client.force_login(self.patient())
        self.book()
        result = specialist_schedule_reply(
            f"Сколько маникюров с покрытием {self.day:%d.%m.%Y}?", self.master)
        self.assertEqual(result["mode"], "gigachat")
        self.assertIn("Маникюр с покрытием", provider.call_args.args[1])
        self.assertEqual(result["facts"]["service_counts"]["Маникюр с покрытием"], 1)

    def test_master_workspace_and_manager_access_are_separate(self):
        master = self.master_account()
        self.client.force_login(master)
        self.assertEqual(self.client.get(reverse("clinic:manager_team")).status_code, 302)
        self.client.logout()
        manager = get_user_model().objects.create_user(username="manager", password="Manager-Password-93!", is_staff=True)
        manager.user_permissions.add(Permission.objects.get(content_type__app_label="clinic", codename="view_appointment"))
        self.client.force_login(manager)
        self.assertEqual(self.client.get(reverse("clinic:master_calendar")).status_code, 403)
        response = self.client.post(reverse("clinic:manager_team"), {
            "doctor": self.other_master.pk, "username": "newmaster", "password": "Master-Password-93!"})
        self.assertEqual(response.status_code, 200)
        self.assertEqual(get_user_model().objects.get(username="newmaster").clinic_profile.role, "doctor")

    def test_csrf_protects_booking_and_private_messages(self):
        user = self.patient()
        secure = Client(enforce_csrf_checks=True, HTTP_HOST="127.0.0.1")
        secure.force_login(user)
        response = secure.post(reverse("clinic:book_appointment"),
            data=json.dumps({"service": self.service.pk, "doctor": self.master.pk, "slot": self.slot.pk}),
            content_type="application/json")
        self.assertEqual(response.status_code, 403)
        self.assertEqual(Appointment.objects.count(), 0)


class DateLanguageTests(SimpleTestCase):
    def test_tuesday_means_next_tuesday(self):
        self.assertEqual(requested_schedule_date("Во сколько я освобождаюсь во вторник?", date(2026, 9, 27)), date(2026, 9, 29))
        self.assertEqual(requested_schedule_date("Завтра", date(2026, 9, 27)), date(2026, 9, 28))
