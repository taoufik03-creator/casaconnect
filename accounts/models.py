from django.conf import settings
from django.core.validators import RegexValidator
from django.db import models
from django.utils.translation import gettext_lazy as _


def avatar_path(instance, filename):
    ext = filename.rsplit(".", 1)[-1].lower() if "." in filename else "jpg"
    return f"avatars/user_{instance.user_id}.{ext}"


class UserProfile(models.Model):
    """Extra data attached to Django's built-in User."""

    user = models.OneToOneField(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="profile")
    PBR = models.CharField(
        "PBR", max_length=20, unique=True,
        validators=[RegexValidator(r"^[A-Z0-9]{3,20}$", _("Le PBR doit contenir 3 à 20 lettres/chiffres."))],
    )
    birth_date = models.DateField(_("Date de naissance"))
    avatar = models.ImageField(_("Photo de profil"), upload_to=avatar_path, blank=True, null=True)

    def __str__(self):
        return f"{self.user.get_full_name() or self.user.username} ({self.PBR})"


class PBRMapper(models.Model):
    PBR = models.CharField(
        "PBR", max_length=20, unique=True,
        validators=[RegexValidator(r"^[A-Z0-9]{3,20}$", _("Le PBR doit contenir 3 à 20 lettres/chiffres."))],
    )
    employee_name = models.CharField(max_length=100)

    def __str__(self):
        return f"{self.PBR} · {self.employee_name}"
