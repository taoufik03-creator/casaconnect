from django.core.management.base import BaseCommand

from chat.services import dispatch_due_messages


class Command(BaseCommand):
    help = "Send all scheduled messages that are due (run every minute from cron / a scheduler)."

    def handle(self, *args, **options):
        self.stdout.write(f"{dispatch_due_messages()} message(s) envoyé(s).")
