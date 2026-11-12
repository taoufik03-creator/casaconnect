from django.contrib import messages
from django.contrib.auth import get_user_model
from django.contrib.auth.decorators import login_required
from django.db.models import Count, F, OuterRef, Q, Subquery
from django.http import HttpResponseForbidden, JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils import timezone
from django.utils.formats import date_format
from django.utils.translation import gettext as _
from django.utils.http import url_has_allowed_host_and_scheme
from django.views.decorators.http import require_POST

from .forms import ComposeForm
from .models import Conversation, Membership, Message
from .services import send_message

User = get_user_model()


def _safe_next(request, default):
    nxt = request.POST.get("next") or request.GET.get("next")
    if nxt and url_has_allowed_host_and_scheme(nxt, allowed_hosts={request.get_host()},
                                               require_https=request.is_secure()):
        return nxt
    return default


def _is_ajax(request):
    return request.headers.get("X-Requested-With") == "XMLHttpRequest"


# ------------------------------------------------------------------ inbox
@login_required
def inbox(request):
    only_starred = request.GET.get("filter") == "starred"
    last_msg = Message.objects.filter(conversation=OuterRef("conversation_id"),
                                      status=Message.SENT).order_by("-sent_at")
    qs = (Membership.objects
          .filter(user=request.user, conversation__last_message_at__isnull=False)
          .select_related("conversation")
          .prefetch_related("conversation__members__profile")
          .annotate(
              unread=Count("conversation__messages",
                           filter=Q(conversation__messages__status=Message.SENT,
                                    conversation__messages__sent_at__gt=F("last_read_at"))
                           & ~Q(conversation__messages__sender=request.user)),
              preview=Subquery(last_msg.values("body")[:1]),
              last_sender=Subquery(last_msg.values("sender__first_name")[:1]))
          .order_by("-conversation__last_message_at"))
    if only_starred:
        qs = qs.filter(is_starred=True)
    rows = list(qs)
    for m in rows:
        conv = m.conversation
        m.title = conv.display_title(request.user)
        others = conv.other_members(request.user)
        m.other = others[0] if others and not conv.is_group else None
    return render(request, "chat/inbox.html", {"rows": rows, "only_starred": only_starred})


# --------------------------------------------------------- compose / send
def _draft_for(user, draft_id, conversation):
    qs = Message.objects.filter(sender=user, status=Message.DRAFT)
    if draft_id:
        draft = qs.filter(pk=draft_id).first()
        if draft and (draft.conversation_id or None) == (conversation.pk if conversation else None):
            return draft
    elif conversation is not None:
        draft = qs.filter(conversation=conversation).order_by("-updated_at").first()
        if draft:
            return draft
    return Message(sender=user, status=Message.DRAFT, conversation=conversation)


def _process(request, form, conversation=None):
    """Shared by the new-message page and the conversation reply box."""
    action = request.POST.get("action", "send")
    msg = _draft_for(request.user, form.cleaned_data.get("draft_id"), conversation)
    msg.body = form.cleaned_data["body"]
    msg.save()
    if conversation is None:
        msg.recipients.set(form.cleaned_data.get("recipients") or [])
    if action == "draft":
        messages.info(request, _("Brouillon enregistré."))
        return redirect("chat:drafts")
    if action == "schedule":
        msg.status = Message.SCHEDULED
        msg.scheduled_for = form.cleaned_data["scheduled_for"]
        msg.save()
        when = date_format(timezone.localtime(msg.scheduled_for), "d/m/Y H:i")
        messages.success(request, _("Envoi programmé pour le %(when)s.") % {"when": when})
        return redirect("chat:scheduled")
    conv = send_message(msg)
    if conv.is_group and conversation is None:
        messages.success(request, _("Message envoyé : une conversation de groupe a été créée automatiquement."))
    return redirect("chat:conversation", pk=conv.pk)


@login_required
def compose(request):
    initial = {}
    draft = None
    draft_pk = request.GET.get("draft", "")
    if draft_pk.isdigit():
        draft = Message.objects.filter(pk=draft_pk, sender=request.user, status=Message.DRAFT).first()
        if draft and draft.conversation_id:
            return redirect("chat:conversation", pk=draft.conversation_id)
    if request.method == "POST":
        form = ComposeForm(request.POST, user=request.user)
        if form.is_valid():
            return _process(request, form)
    else:
        if draft:
            initial = {"body": draft.body, "draft_id": draft.pk,
                       "recipients": list(draft.recipients.values_list("pk", flat=True))}
        elif request.GET.get("to", "").isdigit():
            initial = {"recipients": [int(request.GET["to"])]}
        form = ComposeForm(initial=initial, user=request.user)
    return render(request, "chat/compose.html", {"form": form})


# ------------------------------------------------------------ conversation
@login_required
def conversation_detail(request, pk):
    membership = get_object_or_404(Membership.objects.select_related("conversation"),
                                   conversation_id=pk, user=request.user)
    conv = membership.conversation
    if request.method == "POST":
        form = ComposeForm(request.POST, user=request.user, conversation=conv)
        if form.is_valid():
            return _process(request, form, conversation=conv)
    else:
        draft = (Message.objects.filter(conversation=conv, sender=request.user, status=Message.DRAFT)
                 .order_by("-updated_at").first())
        form = ComposeForm(initial={"body": draft.body, "draft_id": draft.pk} if draft else None,
                           user=request.user, conversation=conv)
        Membership.objects.filter(pk=membership.pk).update(last_read_at=timezone.now())

    conv = Conversation.objects.prefetch_related("members__profile").get(pk=conv.pk)
    thread = list(conv.messages.filter(status=Message.SENT).select_related("sender__profile")
                  .order_by("sent_at"))
    starred_ids = set(request.user.starred_messages.filter(conversation=conv).values_list("pk", flat=True))
    for m in thread:
        m.is_starred = m.pk in starred_ids
    scheduled = conv.messages.filter(sender=request.user, status=Message.SCHEDULED).order_by("scheduled_for")
    return render(request, "chat/conversation.html", {
        "conv": conv, "title": conv.display_title(request.user), "others": conv.other_members(request.user),
        "thread": thread, "form": form, "membership": membership, "scheduled": scheduled,
    })


# ---------------------------------------------------------------- autosave
@login_required
@require_POST
def draft_autosave(request):
    conv = None
    cid = request.POST.get("conversation_id", "")
    if cid:
        conv = Conversation.objects.filter(pk=cid if cid.isdigit() else 0, memberships__user=request.user).first()
        if conv is None:
            return HttpResponseForbidden()
    body = request.POST.get("body", "")[:10000]
    ids = []
    if conv is None:
        ids = [int(x) for x in request.POST.getlist("recipients") if x.isdigit()]
    draft_id = request.POST.get("draft_id", "")
    draft = _draft_for(request.user, int(draft_id) if draft_id.isdigit() else None, conv)
    # _draft_for would silently reuse the conversation's draft; for a brand-new compose, never do that.
    if not body.strip() and not ids:
        if draft.pk:
            draft.delete()
        return JsonResponse({"draft_id": None})
    draft.body = body
    draft.save()
    if conv is None:
        valid = User.objects.filter(pk__in=ids, is_active=True, profile__isnull=False).exclude(pk=request.user.pk)
        draft.recipients.set(valid)
    return JsonResponse({"draft_id": draft.pk, "saved_at": timezone.localtime().strftime("%H:%M:%S")})


@login_required
def drafts(request):
    items = (Message.objects.filter(sender=request.user, status=Message.DRAFT)
             .select_related("conversation").prefetch_related("recipients", "conversation__members")
             .order_by("-updated_at"))
    for m in items:
        m.target = m.target_label(request.user)
    return render(request, "chat/drafts.html", {"items": items})


@login_required
def draft_open(request, pk):
    draft = get_object_or_404(Message, pk=pk, sender=request.user, status=Message.DRAFT)
    if draft.conversation_id:
        return redirect("chat:conversation", pk=draft.conversation_id)
    return redirect(f"{reverse('chat:compose')}?draft={draft.pk}")


@login_required
@require_POST
def draft_delete(request, pk):
    get_object_or_404(Message, pk=pk, sender=request.user, status__in=[Message.DRAFT, Message.SCHEDULED]).delete()
    messages.info(request, _("Supprimé."))
    return redirect(_safe_next(request, reverse("chat:drafts")))


# ---------------------------------------------------------------- scheduled
@login_required
def scheduled(request):
    items = (Message.objects.filter(sender=request.user, status=Message.SCHEDULED)
             .select_related("conversation").prefetch_related("recipients", "conversation__members")
             .order_by("scheduled_for"))
    for m in items:
        m.target = m.target_label(request.user)
    return render(request, "chat/scheduled.html", {"items": items})


@login_required
@require_POST
def unschedule(request, pk):
    """Cancel the schedule: the message goes back to drafts and opens for editing."""
    msg = get_object_or_404(Message, pk=pk, sender=request.user, status=Message.SCHEDULED)
    msg.status, msg.scheduled_for = Message.DRAFT, None
    msg.save()
    return redirect("chat:draft_open", pk=msg.pk)


# -------------------------------------------------------------------- stars
@login_required
@require_POST
def toggle_message_star(request, pk):
    msg = get_object_or_404(Message, pk=pk, status=Message.SENT, conversation__memberships__user=request.user)
    if msg.starred_by.filter(pk=request.user.pk).exists():
        msg.starred_by.remove(request.user)
        starred = False
    else:
        msg.starred_by.add(request.user)
        starred = True
    if _is_ajax(request):
        return JsonResponse({"starred": starred})
    return redirect(_safe_next(request, reverse("chat:conversation", args=[msg.conversation_id])))


@login_required
@require_POST
def toggle_conversation_star(request, pk):
    membership = get_object_or_404(Membership, conversation_id=pk, user=request.user)
    membership.is_starred = not membership.is_starred
    membership.save(update_fields=["is_starred"])
    if _is_ajax(request):
        return JsonResponse({"starred": membership.is_starred})
    return redirect(_safe_next(request, reverse("chat:inbox")))


@login_required
def starred(request):
    msgs = (request.user.starred_messages.filter(status=Message.SENT)
            .select_related("sender__profile", "conversation").prefetch_related("conversation__members")
            .order_by("-sent_at"))
    for m in msgs:
        m.conv_title = m.conversation.display_title(request.user)
        m.is_starred = True
    convs = (Membership.objects.filter(user=request.user, is_starred=True)
             .select_related("conversation").prefetch_related("conversation__members"))
    for c in convs:
        c.title = c.conversation.display_title(request.user)
    return render(request, "chat/starred.html", {"messages_starred": msgs, "convs_starred": convs})
