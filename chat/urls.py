from django.urls import path

from . import views

app_name = "chat"
urlpatterns = [
    path("", views.inbox, name="inbox"),
    path("new/", views.compose, name="compose"),
    path("c/<int:pk>/", views.conversation_detail, name="conversation"),
    path("c/<int:pk>/star/", views.toggle_conversation_star, name="star_conversation"),
    path("message/<int:pk>/star/", views.toggle_message_star, name="star_message"),
    path("starred/", views.starred, name="starred"),
    path("drafts/", views.drafts, name="drafts"),
    path("drafts/autosave/", views.draft_autosave, name="draft_autosave"),
    path("drafts/<int:pk>/open/", views.draft_open, name="draft_open"),
    path("drafts/<int:pk>/delete/", views.draft_delete, name="draft_delete"),
    path("scheduled/", views.scheduled, name="scheduled"),
    path("scheduled/<int:pk>/edit/", views.unschedule, name="unschedule"),
]
