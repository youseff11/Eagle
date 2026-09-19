"""Run the workflow housekeeping once (expiries + deadline warnings).

The browser heartbeat already runs this, but a scheduled job keeps the rules
firing even when nobody has the dashboard open.
"""

from django.core.management.base import BaseCommand

from dashboard import attendance, services


class Command(BaseCommand):
    help = "Expire stale assignments, push deadline warnings, raise attendance alerts."

    def handle(self, *args, **options):
        expired = services.sweep_expired_assignments()
        warned = services.sweep_deadlines()
        # Attendance alerts are time-based, not request-based: a missing
        # check-in is only noticeable when nobody is there to trigger it.
        alerts = attendance.sweep_alerts()
        self.stdout.write(
            self.style.SUCCESS(
                f"expired={expired} deadline_warnings={warned} attendance_alerts={alerts}"
            )
        )
