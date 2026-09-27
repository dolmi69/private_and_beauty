"""Role and slot boundaries for the new patient/doctor workflows."""
import json
from datetime import timedelta

from django.contrib.auth import get_user_model
from django.contrib.auth.models import Permission
from django.core.cache import cache
from django.test import TestCase, override_settings
from django.urls import reverse
from django.utils import timezone

from .models import Appointment, AppointmentSlot, Doctor, UserProfile


@override_settings(BOOKING_RATE_LIMIT=100)
class AccountAndSlotTests(TestCase):
    def setUp(self):
        cache.clear()
        self.doctor = Doctor.objects.first()
        self.other_doctor = Doctor.objects.last()
        self.slot = AppointmentSlot.objects.create(doctor=self.doctor, starts_at=timezone.now() + timedelta(days=2))

    def register_patient(self, username="patient"):
        response = self.client.post(reverse("clinic:register"), {
            "username": username, "first_name": "Анна", "last_name": "Иванова",
            "phone_number": "+7 900 111 22 33", "password1": "Green-River-Patient-93!",
            "password2": "Green-River-Patient-93!",
        })
        self.assertRedirects(response, reverse("clinic:dashboard"))
        return get_user_model().objects.get(username=username)

    def book(self):
        return self.client.post(reverse("clinic:book_appointment"),
                                data=json.dumps({"doctor": self.doctor.pk, "slot": self.slot.pk}),
                                content_type="application/json")

    def test_registration_only_creates_client_and_booking_uses_profile(self):
        self.assertEqual(self.book().status_code, 401)
        patient = self.register_patient()
        self.assertEqual(patient.clinic_profile.role, "client")
        self.assertFalse(patient.is_staff)
        self.assertEqual(self.book().status_code, 201)
        appointment = Appointment.objects.get()
        self.assertEqual(appointment.client, patient)
        self.assertEqual(appointment.client_name, "Анна Иванова")
        self.assertEqual(appointment.phone_number, "+79001112233")
        self.assertEqual(appointment.slot, self.slot)
        self.assertContains(self.client.get(reverse("clinic:dashboard")), self.doctor.full_name)

    def test_slot_cannot_be_double_booked_but_cancel_reopens_it(self):
        self.register_patient()
        self.assertEqual(self.book().status_code, 201)
        self.assertEqual(self.book().status_code, 400)
        appointment = Appointment.objects.get()
        self.client.post(reverse("clinic:cancel_appointment", args=[appointment.pk]))
        appointment.refresh_from_db()
        self.assertEqual(appointment.status, "cancelled")
        self.assertEqual(self.book().status_code, 201)

    def test_patient_cannot_view_or_cancel_another_patients_record(self):
        self.register_patient()
        self.book()
        appointment = Appointment.objects.get()
        self.client.logout()
        self.register_patient("otherpatient")
        self.assertNotContains(self.client.get(reverse("clinic:dashboard")), appointment.client_name)
        self.assertEqual(self.client.post(reverse("clinic:cancel_appointment", args=[appointment.pk])).status_code, 404)

    def test_doctor_only_sees_assigned_patients_and_cannot_book(self):
        self.register_patient()
        self.book()
        self.client.logout()
        doctor_user = get_user_model().objects.create_user(username="doctor1", password="Doctor-Password-93!")
        UserProfile.objects.create(user=doctor_user, role="doctor", doctor=self.doctor)
        other_user = get_user_model().objects.create_user(username="doctor2", password="Doctor-Password-93!")
        UserProfile.objects.create(user=other_user, role="doctor", doctor=self.other_doctor)
        self.client.force_login(doctor_user)
        self.assertContains(self.client.get(reverse("clinic:dashboard")), "Анна Иванова")
        self.assertEqual(self.book().status_code, 403)
        self.client.force_login(other_user)
        self.assertNotContains(self.client.get(reverse("clinic:dashboard")), "Анна Иванова")

    def test_manager_can_create_only_doctor_account(self):
        manager = get_user_model().objects.create_user(username="manager", password="Manager-Password-93!", is_staff=True)
        manager.user_permissions.add(Permission.objects.get(content_type__app_label="clinic", codename="view_appointment"))
        self.client.force_login(manager)
        response = self.client.post(reverse("clinic:manager_team"), {
            "doctor": self.doctor.pk, "username": "newdoctor", "password": "Doctor-Password-93!",
        })
        self.assertEqual(response.status_code, 200)
        doctor_user = get_user_model().objects.get(username="newdoctor")
        self.assertEqual(doctor_user.clinic_profile.role, "doctor")
        self.assertEqual(doctor_user.clinic_profile.doctor, self.doctor)
        self.assertFalse(doctor_user.is_staff)
