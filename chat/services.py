from django.db import transaction
from django.utils import timezone

from .models import Conversation, Membership, Message


def get_or_create_conversation(sender, recipients):
    """1 recipient -> direct conversation; 2+ recipients -> group conversation (created automatically).
    An existing conversation with exactly the same members is reused."""
    members = {sender.pk: sender}
    for r in recipients:
        members[r.pk] = r
    ids = set(members)
    is_group = len(ids) > 2
    candidates = (Conversation.objects.filter(is_group=is_group, members=sender).prefetch_related("members"))
    for conv in candidates:
        if {m.pk for m in conv.members.all()} == ids:
            return conv
    conv = Conversation.objects.create(is_group=is_group, created_by=sender)
    Membership.objects.bulk_create([Membership(conversation=conv, user=u) for u in members.values()])
    return conv


@transaction.atomic
def send_message(msg):
    """Turn a draft/scheduled message into a sent one. Raises ValueError if it cannot be sent."""
    if not msg.body.strip():
        raise ValueError("Message vide.")
    conv = msg.conversation
    if conv is None:
        recipients = list(msg.recipients.all())
        if not recipients:
            raise ValueError("Aucun destinataire.")
        conv = get_or_create_conversation(msg.sender, recipients)
        msg.conversation = conv
        msg.recipients.clear()
    now = timezone.now()
    msg.status = Message.SENT
    msg.sent_at = now
    msg.save()
    Conversation.objects.filter(pk=conv.pk).update(last_message_at=now)
    Membership.objects.filter(conversation=conv, user=msg.sender).update(last_read_at=now)
    return conv


def dispatch_due_messages():
    """Send every scheduled message whose time has come. Safe to call repeatedly / concurrently."""
    now = timezone.now()
    ids = list(Message.objects.filter(status=Message.SCHEDULED, scheduled_for__lte=now).values_list("pk", flat=True))
    sent = 0
    for pk in ids:
        with transaction.atomic():
            msg = Message.objects.select_for_update().filter(pk=pk, status=Message.SCHEDULED).first()
            if msg is None:
                continue
            try:
                send_message(msg)
                sent += 1
            except ValueError:
                Message.objects.filter(pk=pk).update(status=Message.DRAFT, scheduled_for=None)
    return sent
