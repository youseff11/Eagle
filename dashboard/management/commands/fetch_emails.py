"""Pull unread mail over IMAP and turn each message into an inbound record.

Configure the IMAP host / user / password in the admin panel, then run:

    python manage.py fetch_emails

The parsing lives in ``dashboard/mailbox.py`` so the button on the mail page
and this command run the same code — a "fetch now" that behaves differently
from the scheduled fetch is a bug waiting for a busy morning.

On PythonAnywhere, schedule this on the **Tasks** tab (or let ``run_worker``
call it on its loop). Without one of the two, no client e-mail ever arrives.
"""

from django.core.management.base import BaseCommand

from dashboard import mailbox


class Command(BaseCommand):
    help = "Fetch unseen e-mails over IMAP into the operation inbox."

    def add_arguments(self, parser):
        parser.add_argument("--limit", type=int, default=25)
        parser.add_argument(
            "--keep-unread", action="store_true",
            help="Leave the messages unread in the mailbox (they will be re-read).",
        )

    def handle(self, *args, **options):
        created, error = mailbox.fetch_and_record(
            limit=options["limit"], keep_unread=options["keep_unread"]
        )
        if error:
            self.stderr.write(error)
            return
        self.stdout.write(self.style.SUCCESS(f"Imported {created} message(s)."))
