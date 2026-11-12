from datetime import timedelta

from django import forms
from django.contrib.auth import get_user_model
from django.utils import timezone
from django.utils.translation import gettext_lazy as _

User = get_user_model()


class RecipientField(forms.ModelMultipleChoiceField):
    def label_from_instance(self, u):
        pbr = getattr(getattr(u, "profile", None), "PBR", "")
        return f"{u.get_full_name() or u.username} · {pbr}"


class ComposeForm(forms.Form):
    recipients = RecipientField(queryset=User.objects.none(), required=False, widget=forms.CheckboxSelectMultiple)
    body = forms.CharField(required=False, max_length=10000,
                           widget=forms.Textarea(attrs={"rows": 6, "dir": "auto", "placeholder": _("Votre message…")}))
    scheduled_for = forms.DateTimeField(
        required=False, label=_("Programmer l'envoi"),
        input_formats=["%Y-%m-%dT%H:%M", "%Y-%m-%dT%H:%M:%S"],
        widget=forms.DateTimeInput(attrs={"type": "datetime-local"}, format="%Y-%m-%dT%H:%M"),
    )
    draft_id = forms.IntegerField(required=False, widget=forms.HiddenInput)

    def __init__(self, *args, user, conversation=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.user, self.conversation = user, conversation
        if conversation is not None:
            del self.fields["recipients"]
        else:
            self.fields["recipients"].queryset = (
                User.objects.filter(is_active=True, profile__isnull=False).exclude(pk=user.pk)
                .select_related("profile").order_by("first_name", "last_name"))

    def clean(self):
        data = super().clean()
        action = self.data.get("action", "send")
        if action not in ("send", "schedule", "draft"):
            raise forms.ValidationError(_("Action invalide."))
        if action == "draft":
            return data
        if not (data.get("body") or "").strip():
            self.add_error("body", _("Le message est vide."))
        if self.conversation is None and not data.get("recipients"):
            self.add_error("recipients", _("Choisissez au moins un destinataire."))
        if action == "schedule":
            when = data.get("scheduled_for")
            if not when:
                if "scheduled_for" not in self.errors:
                    self.add_error("scheduled_for", _("Choisissez une date et une heure d'envoi."))
            elif when <= timezone.now() + timedelta(seconds=30):
                self.add_error("scheduled_for", _("La date d'envoi doit être dans le futur."))
        return data
