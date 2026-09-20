"""Put the client's original files into task groups that never got them.

Acceptance does this by itself from 20/09/2026 onward. A task accepted before
that leaves its translator in a group with nothing in it, so this walks the old
ones once. Re-running is free - sharing an inbound twice is a no-op.

    python manage.py share_task_files TSK-00002   # one task
    python manage.py share_task_files             # every task with a translator
"""

from django.core.management.base import BaseCommand

from dashboard import services
from dashboard.models import Task


class Command(BaseCommand):
    help = "Share each task's client files into its group chat."

    def add_arguments(self, parser):
        parser.add_argument(
            "code", nargs="?", default="",
            help="A single task code. Omit it to walk every task with a translator.",
        )

    def handle(self, *args, **options):
        code = (options["code"] or "").strip()
        tasks = (
            Task.objects.filter(code=code)
            if code
            else Task.objects.filter(translator__isnull=False)
        )
        if code and not tasks.exists():
            self.stdout.write(self.style.ERROR(f"No task with code {code}."))
            return

        total = 0
        for task in tasks.select_related("client"):
            shared = services.share_source_files(task)
            if shared:
                total += len(shared)
                self.stdout.write(f"{task.code}: {len(shared)} shared")
        self.stdout.write(self.style.SUCCESS(f"shared={total}"))
