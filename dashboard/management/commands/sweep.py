"""Run the workflow housekeeping once (expiries + deadline warnings).

The browser heartbeat already runs this, but a scheduled job keeps the rules
firing even when nobody has the dashboard open.
"""

from django.core.management.base import BaseCommand

from dashboard import attendance, b2b, employees, services


class Command(BaseCommand):
    help = "Expire stale assignments, push deadline warnings, raise attendance alerts, remind Sales of follow-ups."

    def handle(self, *args, **options):
        expired = services.sweep_expired_assignments()
        warned = services.sweep_deadlines()
        # Attendance alerts are time-based, not request-based: a missing
        # check-in is only noticeable when nobody is there to trigger it.
        alerts = attendance.sweep_alerts()
        # Probation reviews come due on a date, so nothing in a request ever
        # notices them.
        lifecycle = employees.sweep()
        # A B2B follow-up comes due on a date too: one reminder a day to each Sales person who has some.
        follow_ups = b2b.sweep()
        self.stdout.write(
            self.style.SUCCESS(
                f"expired={expired} deadline_warnings={warned} "
                f"attendance_alerts={alerts} probation_due={lifecycle['probation']} "
                f"b2b_follow_up_reminders={follow_ups}"
            )
        )
