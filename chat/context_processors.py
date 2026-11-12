from django.db.models import F

from .models import Message


def sidebar_counts(request):
    user = request.user
    if not user.is_authenticated:
        return {}
    mine = Message.objects.filter(sender=user)
    unread = (Message.objects
              .filter(status=Message.SENT, conversation__memberships__user=user,
                      sent_at__gt=F("conversation__memberships__last_read_at"))
              .exclude(sender=user).count())
    return {
        "draft_count": mine.filter(status=Message.DRAFT).count(),
        "scheduled_count": mine.filter(status=Message.SCHEDULED).count(),
        "unread_total": unread,
    }
