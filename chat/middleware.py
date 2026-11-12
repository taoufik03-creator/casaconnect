from django.core.cache import cache

from .services import dispatch_due_messages


class DispatchScheduledMiddleware:
    """Fallback so scheduled messages go out even without cron (at most every 15 s per process).
    In production, also run `python manage.py send_scheduled` every minute."""

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        if cache.add("chat:dispatch-lock", 1, 15):
            dispatch_due_messages()
        return self.get_response(request)
