"""Finish AI checks that were left running.

The automatic check runs on a thread inside the web process. That is fine
almost always, and wrong exactly when the process is recycled mid-call: the
row stays in ``running`` and the team leader waits for notes that will never
come. This finishes those rows.

Point a scheduled task at it, or run it by hand:

    python manage.py run_ai_checks            # rows older than 10 minutes
    python manage.py run_ai_checks --minutes 2
"""

from datetime import timedelta

from django.core.management.base import BaseCommand
from django.utils import timezone

from dashboard import ai
from dashboard.models import AICheckResult


class Command(BaseCommand):
    help = "Finish AI checks stuck in the running state."

    def add_arguments(self, parser):
        parser.add_argument(
            "--minutes", type=int, default=10,
            help="Only touch rows older than this (default: 10). A younger row "
                 "is probably still being worked on by a live thread.",
        )

    def handle(self, *args, **options):
        cutoff = timezone.now() - timedelta(minutes=max(1, options["minutes"]))
        # Materialised before the loop: finishing a row takes it out of the
        # queryset, so a lazy one would count differently afterwards.
        stuck = list(
            AICheckResult.objects.filter(
                status=AICheckResult.Status.RUNNING, created_at__lt=cutoff
            ).select_related("task").order_by("id")
        )

        done = 0
        for result in stuck:
            self.stdout.write(f"{result.task.code}: finishing check {result.pk}")
            if ai.finish_check(result.pk) is not None:
                done += 1
        self.stdout.write(self.style.SUCCESS(f"finished={done} of {len(stuck)}"))
