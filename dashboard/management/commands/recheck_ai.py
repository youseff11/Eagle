"""Run the AI check again on tasks whose notes came from the old check.

The check became a side-by-side comparison of the source and the
translation on 28/09/2026. Notes written before that carry no quotes and
no verdict; this runs those tasks again so the task page shows the new
kind. One task at a time, and it waits for each - a long PDF can take a
minute.

    python manage.py recheck_ai --dry-run            # just list them
    python manage.py recheck_ai                      # every task with old notes
    python manage.py recheck_ai --task TSK-00004     # one (or several) by code
    python manage.py recheck_ai --notify             # also tell each team leader

Every run spends API credit, so --dry-run first.
"""

from django.core.management.base import BaseCommand

from dashboard import ai
from dashboard.models import Task


class Command(BaseCommand):
    help = "Run the AI check again on tasks whose latest notes are in the old format."

    def add_arguments(self, parser):
        parser.add_argument("--task", action="append", default=[],
                            help="A task code. Repeat for more. Runs these whatever their notes look like.")
        parser.add_argument("--dry-run", action="store_true", help="List the tasks, run nothing.")
        parser.add_argument("--notify", action="store_true",
                            help="Tell each team leader when their notes are ready.")

    def handle(self, *args, **options):
        codes = [c.strip() for c in options["task"] if c.strip()]
        if codes:
            tasks = list(Task.objects.filter(code__in=codes).order_by("id"))
            missing = set(codes) - {t.code for t in tasks}
            for code in sorted(missing):
                self.stdout.write(self.style.WARNING(f"{code}: no such task"))
        else:
            tasks = []
            for task in Task.objects.filter(ai_checks__isnull=False).distinct().order_by("id"):
                latest = task.ai_checks.order_by("-created_at", "-id").first()
                if ai.is_old_format(latest):
                    tasks.append(task)

        if not tasks:
            self.stdout.write("nothing to run")
            return
        for task in tasks:
            self.stdout.write(f"{task.code}  {task.title[:60]}")
        if options["dry_run"]:
            self.stdout.write(self.style.SUCCESS(f"dry run: {len(tasks)} task(s) would be checked again"))
            return

        done = failed = 0
        for task in tasks:
            result = ai.recheck_now(task, notify_lead=options["notify"])
            if result is None:
                failed += 1
                self.stdout.write(self.style.WARNING(
                    f"{task.code}: not run (check switched off, no key, or one already running)"))
            elif result.status == result.Status.ERROR:
                failed += 1
                self.stdout.write(self.style.WARNING(f"{task.code}: {result.error_message[:200]}"))
            else:
                done += 1
                self.stdout.write(f"{task.code}: {result.get_status_display()} - {result.issue_count} note(s)")
        self.stdout.write(self.style.SUCCESS(f"checked={done} failed={failed}"))
