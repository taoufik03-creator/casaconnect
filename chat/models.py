from django.conf import settings
from django.db import models
from django.utils import timezone
from django.utils.translation import gettext, gettext_lazy as _


def full_name(user):
    return user.get_full_name() or user.username


class Conversation(models.Model):
    """A direct (2 members) or group (3+ members) conversation. Groups are created automatically."""

    name = models.CharField(max_length=120, blank=True)
    is_group = models.BooleanField(default=False)
    members = models.ManyToManyField(settings.AUTH_USER_MODEL, through="Membership", related_name="conversations")
    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, on_delete=models.SET_NULL, related_name="+")
    created_at = models.DateTimeField(auto_now_add=True)
    last_message_at = models.DateTimeField(null=True, blank=True, db_index=True)

    class Meta:
        ordering = ["-last_message_at"]

    def other_members(self, user):
        return [m for m in self.members.all() if m.pk != user.pk]

    def display_title(self, user):
        if self.name:
            return self.name
        return ", ".join(full_name(m) for m in self.other_members(user)) or full_name(user)

    def __str__(self):
        return self.name or f"Conversation #{self.pk}"


class Membership(models.Model):
    """Per-user state of a conversation: starred or not, read position."""

    conversation = models.ForeignKey(Conversation, on_delete=models.CASCADE, related_name="memberships")
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="memberships")
    is_starred = models.BooleanField(default=False)
    last_read_at = models.DateTimeField(default=timezone.now)
    joined_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        constraints = [models.UniqueConstraint(fields=["conversation", "user"], name="unique_member")]


class Message(models.Model):
    DRAFT, SCHEDULED, SENT = "draft", "scheduled", "sent"
    STATUS_CHOICES = [(DRAFT, _("Brouillon")), (SCHEDULED, _("Programmé")), (SENT, _("Envoyé"))]

    # NULL while a draft / scheduled message has no conversation yet (it is created at send time).
    conversation = models.ForeignKey(Conversation, null=True, blank=True, on_delete=models.CASCADE,
                                     related_name="messages")
    sender = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="sent_messages")
    # Intended recipients, only used until the message is attached to a conversation.
    recipients = models.ManyToManyField(settings.AUTH_USER_MODEL, blank=True, related_name="+")
    body = models.TextField(blank=True, max_length=10000)
    status = models.CharField(max_length=10, choices=STATUS_CHOICES, default=DRAFT, db_index=True)
    scheduled_for = models.DateTimeField(null=True, blank=True, db_index=True)
    sent_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    starred_by = models.ManyToManyField(settings.AUTH_USER_MODEL, blank=True, related_name="starred_messages")

    class Meta:
        ordering = ["sent_at", "created_at"]

    def target_label(self, user):
        if self.conversation_id:
            return self.conversation.display_title(user)
        return ", ".join(full_name(u) for u in self.recipients.all()) or gettext("(aucun destinataire)")

    def __str__(self):
        return f"{self.get_status_display()} · {self.body[:30]}"
