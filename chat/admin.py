from django.contrib import admin
from .models import Conversation, Membership, Message


class MembershipInline(admin.TabularInline):
    model = Membership
    extra = 0


@admin.register(Conversation)
class ConversationAdmin(admin.ModelAdmin):
    list_display = ("id", "name", "is_group", "last_message_at")
    inlines = [MembershipInline]


@admin.register(Message)
class MessageAdmin(admin.ModelAdmin):
    list_display = ("id", "sender", "status", "sent_at", "scheduled_for")
    list_filter = ("status",)
