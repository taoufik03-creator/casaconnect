import re
from datetime import date

from django import forms
from django.contrib.auth import get_user_model
from django.contrib.auth.forms import AuthenticationForm
from django.contrib.auth.password_validation import validate_password
from django.core.exceptions import ValidationError
from django.db import transaction
from django.utils.translation import gettext_lazy as _

import unicodedata

from .models import UserProfile, PBRMapper

User = get_user_model()
PBR_RE = re.compile(r"^[A-Z0-9]{3,20}$")
DATE_FORMATS = ["%Y-%m-%d", "%d/%m/%Y"]


def normalize_pbr(value):
    return (value or "").strip().upper().replace(" ", "")

def name_key(value):
    text = unicodedata.normalize("NFKD", value or "")
    text = "".join(c for c in text if not unicodedata.combining(c))
    return tuple(sorted(text.casefold().replace("-", " ").split()))

def date_field(label):
    return forms.DateField(
        label=label, input_formats=DATE_FORMATS,
        widget=forms.DateInput(attrs={"type": "date"}, format="%Y-%m-%d"),
    )


def check_birth_date(value):
    today = date.today()
    if value > today or value.year < 1900:
        raise ValidationError(_("Date de naissance invalide."))
    return value


class PBRAuthenticationForm(AuthenticationForm):
    username = forms.CharField(label="PPR", widget=forms.TextInput(attrs={"autofocus": True}))

    def clean_username(self):
        return normalize_pbr(self.cleaned_data["username"])


class SignUpForm(forms.Form):
    """Account creation: PBR, first name, last name, birth date, password. Nothing else."""

    PBR = forms.CharField(label="PBR", max_length=20)
    first_name = forms.CharField(label=_("Prénom"), max_length=150)
    last_name = forms.CharField(label=_("Nom"), max_length=150)
    birth_date = date_field(_("Date de naissance"))
    password1 = forms.CharField(label=_("Mot de passe"), strip=False,
                                widget=forms.PasswordInput(attrs={"autocomplete": "new-password"}))
    password2 = forms.CharField(label=_("Confirmer le mot de passe"), strip=False,
                                widget=forms.PasswordInput(attrs={"autocomplete": "new-password"}))

    def clean_PBR(self):
        pbr = normalize_pbr(self.cleaned_data["PBR"])
        if not PBR_RE.match(pbr):
            raise ValidationError(_("Le PBR doit contenir 3 à 20 lettres/chiffres."))
        if User.objects.filter(username__iexact=pbr).exists() or UserProfile.objects.filter(PBR=pbr).exists():
            raise ValidationError(_("Un compte existe déjà avec ce PBR."))
        return pbr

    def clean_birth_date(self):
        return check_birth_date(self.cleaned_data["birth_date"])

    def clean(self):
        cd = super().clean()

        #For PBR mapping

        pbr, first, last = cd.get("PBR"), cd.get("first_name"), cd.get("last_name")
        if pbr and first and last:
            entry = PBRMapper.objects.filter(PBR=pbr).first()
            if entry is None or name_key(entry.employee_name) != name_key(f"{first} {last}"):
                self.add_error("PBR", _("Ce PBR ne correspond pas au nom saisi. Vérifiez vos informations ou contactez l'administrateur."))

        #end

        p1, p2 = cd.get("password1"), cd.get("password2")
        if p1 and p2:
            if p1 != p2:
                self.add_error("password2", _("Les deux mots de passe ne correspondent pas."))
            else:
                candidate = User(username=cd.get("PBR", ""), first_name=cd.get("first_name", ""),
                                 last_name=cd.get("last_name", ""))
                try:
                    validate_password(p1, candidate)
                except ValidationError as exc:
                    self.add_error("password1", exc)
        return cd

    @transaction.atomic
    def save(self):
        cd = self.cleaned_data



        user = User.objects.create_user(
            username=cd["PBR"], password=cd["password1"],
            first_name=cd["first_name"].strip(), last_name=cd["last_name"].strip(),
        )
        UserProfile.objects.create(user=user, PBR=cd["PBR"], birth_date=cd["birth_date"])
        return user


class ForgotPasswordForm(forms.Form):
    PBR = forms.CharField(label="PBR")
    birth_date = date_field(_("Date de naissance"))

    def clean_PBR(self):
        return normalize_pbr(self.cleaned_data["PBR"])


class ProfileForm(forms.ModelForm):
    first_name = forms.CharField(label=_("Prénom"), max_length=150)
    last_name = forms.CharField(label=_("Nom"), max_length=150)

    class Meta:
        model = UserProfile
        fields = ["avatar"]

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["avatar"].required = False
        self.fields["first_name"].initial = self.instance.user.first_name
        self.fields["last_name"].initial = self.instance.user.last_name
        self.order_fields(["first_name", "last_name", "avatar"])

    def clean_avatar(self):
        f = self.cleaned_data.get("avatar")
        if f and hasattr(f, "size") and f.size > 2 * 1024 * 1024:
            raise ValidationError(_("L'image ne doit pas dépasser 2 Mo."))
        return f

    def save(self, commit=True):
        profile = super().save(commit=False)
        user = profile.user
        user.first_name = self.cleaned_data["first_name"].strip()
        user.last_name = self.cleaned_data["last_name"].strip()
        user.save()
        profile.save()
        return profile


