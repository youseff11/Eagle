"""Run the workflow housekeeping once (expiries + deadline warnings).

The browser heartbeat already runs this, but a scheduled job keeps the rules
firing even when nobody has the dashboard open.
"""

from django.core.management.base import BaseCommand

from dashboard import services


class Command(BaseCommand):
    help = "Expire stale assignments and push deadline warnings."

    def handle(self, *args, **options):
        expired = services.sweep_expired_assignments()
        warned = services.sweep_deadlines()
        self.stdout.write(
            self.style.SUCCESS(f"expired={expired} deadline_warnings={warned}")
        )
