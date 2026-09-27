import re

from django import forms
from django.contrib.auth import get_user_model
from django.contrib.auth.forms import UserCreationForm
from django.contrib.auth.password_validation import validate_password
from django.utils import timezone

from .models import Appointment, UserProfile, Doctor


class ClientRegistrationForm(UserCreationForm):
    first_name = forms.CharField(label="Имя", max_length=80)
    last_name = forms.CharField(label="Фамилия", max_length=80)
    phone_number = forms.CharField(label="Телефон", max_length=40)

    class Meta(UserCreationForm.Meta):
        model = get_user_model()
        fields = ("username", "first_name", "last_name", "phone_number")

    def clean_phone_number(self):
        phone = re.sub(r"[\s().-]", "", self.cleaned_data["phone_number"])
        if not re.fullmatch(r"\+?[0-9]{7,15}", phone):
            raise forms.ValidationError("Введите от 7 до 15 цифр.")
        return phone

    def save(self, commit=True):
        user = super().save(commit=False)
        user.first_name = self.cleaned_data["first_name"].strip()
        user.last_name = self.cleaned_data["last_name"].strip()
        if commit:
            user.save()
            UserProfile.objects.create(user=user, role=UserProfile.Role.CLIENT,
                                       phone_number=self.cleaned_data["phone_number"])
        return user


class DoctorAccountForm(forms.Form):
    doctor = forms.ModelChoiceField(queryset=Doctor.objects.all(), label="Врач",
                                    widget=forms.Select(attrs={"class": "form-select"}))
    username = forms.CharField(label="Логин", max_length=150,
                               widget=forms.TextInput(attrs={"class": "form-control"}))
    password = forms.CharField(label="Временный пароль", widget=forms.PasswordInput(attrs={"class": "form-control"}),
                               min_length=12)

    def clean_doctor(self):
        doctor = self.cleaned_data["doctor"]
        if UserProfile.objects.filter(doctor=doctor).exists():
            raise forms.ValidationError("Для этого врача аккаунт уже создан.")
        return doctor

    def clean_username(self):
        username = self.cleaned_data["username"].strip()
        if get_user_model().objects.filter(username__iexact=username).exists():
            raise forms.ValidationError("Такой логин уже занят.")
        return username

    def clean_password(self):
        password = self.cleaned_data["password"]
        validate_password(password)
        return password


class AppointmentForm(forms.ModelForm):
    """Public callers cannot choose the status or other administrative fields."""

    class Meta:
        model = Appointment
        fields = ["client_name", "phone_number", "doctor", "requested_at"]
        widgets = {"requested_at": forms.DateTimeInput(attrs={"type": "datetime-local"})}

    def clean_client_name(self):
        name = " ".join(self.cleaned_data["client_name"].split())
        if len(name) < 2:
            raise forms.ValidationError("Укажите имя и фамилию.")
        return name

    # Allow ordinary phone formatting before model validators enforce digits.
    phone_number = forms.CharField(max_length=40)

    def clean_phone_number(self):
        return re.sub(r"[\s().-]", "", self.cleaned_data["phone_number"])

    def clean_requested_at(self):
        requested_at = self.cleaned_data["requested_at"]
        if requested_at <= timezone.now():
            raise forms.ValidationError("Выберите дату и время в будущем.")
        return requested_at
