"""Long-running background worker.

Does two jobs on a loop:

1. **Housekeeping** — expires assignments nobody confirmed (applying the rating
   penalty) and pushes deadline warnings. The browser heartbeat already does
   this, but only while somebody has the dashboard open; this keeps the rules
   firing at 3am too.
2. **E-mail polling** — pulls new client mail over IMAP.

Built for a PythonAnywhere *always-on task* (paid accounts), but it works under
any supervisor, or in a spare terminal:

    python manage.py run_worker

Scheduled tasks on PythonAnywhere only go down to hourly, which is far too slow
for a 60-second confirmation window — that is why this exists.
"""

import time
import traceback

from django.core.management import call_command
from django.core.management.base import BaseCommand
from django.db import close_old_connections
from django.utils import timezone

from dashboard import services
from dashboard.models import AppSettings


class Command(BaseCommand):
    help = "Run housekeeping (and optional e-mail polling) in a loop, forever."

    def add_arguments(self, parser):
        parser.add_argument(
            "--interval", type=int, default=60,
            help="Seconds between cycles (default: 60).",
        )
        parser.add_argument(
            "--mail-every", type=int, default=3,
            help="Fetch e-mail once every N cycles (default: 3).",
        )
        parser.add_argument("--no-mail", action="store_true", help="Housekeeping only.")
        parser.add_argument("--once", action="store_true", help="Run one cycle and exit.")

    def handle(self, *args, **options):
        interval = max(10, options["interval"])
        mail_every = max(1, options["mail_every"])
        cycle = 0

        self.stdout.write(self.style.SUCCESS(
            f"Eagle worker started — every {interval}s"
            f"{'' if options['no_mail'] else f', mail every {interval * mail_every}s'}"
        ))

        while True:
            cycle += 1
            close_old_connections()
            stamp = timezone.localtime().strftime("%H:%M:%S")

            try:
                expired = services.sweep_expired_assignments()
                warned = services.sweep_deadlines()
                if expired or warned:
                    self.stdout.write(f"[{stamp}] expired={expired} deadline_warnings={warned}")
            except Exception:  # noqa: BLE001 - the loop must survive anything
                self.stderr.write(f"[{stamp}] housekeeping failed:\n{traceback.format_exc()}")

            if not options["no_mail"] and cycle % mail_every == 0:
                try:
                    conf = AppSettings.load()
                    if conf.imap_host and conf.imap_user:
                        call_command("fetch_emails")
                except Exception:  # noqa: BLE001
                    self.stderr.write(f"[{stamp}] mail fetch failed:\n{traceback.format_exc()}")

            if options["once"]:
                self.stdout.write(self.style.SUCCESS("Single cycle done."))
                return

            self.stdout.flush()
            time.sleep(interval)
