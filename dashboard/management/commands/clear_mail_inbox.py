"""Empty the mail inbox (/ops/inbox/) to start over - the owner's call, 29/09/2026.

    python manage.py clear_mail_inbox                   # count what would go
    python manage.py clear_mail_inbox --apply           # delete it
    python manage.py clear_mail_inbox --apply --include-tasks

What goes: every e-mail a client sent (``InboundMessage``, channel e-mail),
the replies written to them from the mail page (``OutboundMessage`` of kind
"chat" in the same conversations), who-read-what, and the stored files of
both - off the disk / Bunny too, not just the rows.

What stays, unless ``--include-tasks``: a letter that became a task, or whose
files a task was made from. Those files are the task's source; deleting them
would leave a translator with nothing to translate.

What never goes: WhatsApp, task deliveries, clients, tasks. Gmail keeps its
own copy of every letter; they are already read there, so the next fetch
does not bring them back.
"""

from django.core.management.base import BaseCommand
from django.db import transaction
from django.db.models import Q

from dashboard.models import AuditLog, Channel, InboundMessage, OutboundMessage


class Command(BaseCommand):
    help = "Delete the e-mails in the mail inbox (dry run unless --apply)."

    def add_arguments(self, parser):
        parser.add_argument("--apply", action="store_true", help="Really delete.")
        parser.add_argument(
            "--include-tasks", action="store_true",
            help="Also delete letters that became tasks or gave a task its files.",
        )

    def handle(self, *args, **options):
        letters = InboundMessage.objects.filter(channel=Channel.EMAIL)
        kept = 0
        if not options["include_tasks"]:
            tasked = letters.filter(
                Q(task__isnull=False) | Q(attachments__tasks__isnull=False)
            ).distinct()
            kept = tasked.count()
            letters = letters.exclude(pk__in=tasked.values("pk"))
        letters = letters.distinct()

        keys = set(letters.exclude(thread_key="").values_list("thread_key", flat=True))
        replies = OutboundMessage.objects.filter(
            channel=Channel.EMAIL, kind=OutboundMessage.Kind.CHAT, task__isnull=True,
            thread_key__in=keys,
        )

        n_letters, n_replies = letters.count(), replies.count()
        self.stdout.write(f"letters: {n_letters}  replies: {n_replies}  kept (tasks): {kept}")
        if not options["apply"]:
            self.stdout.write("Nothing deleted. Run again with --apply.")
            return

        files = []
        for letter in letters.prefetch_related("attachments"):
            files += [a.file for a in letter.attachments.all() if a.file]
        for reply in replies.prefetch_related("uploads"):
            files += [u.file for u in reply.uploads.all() if u.file]

        with transaction.atomic():
            replies.delete()
            letters.delete()
            AuditLog.objects.create(
                actor=None, action="mail.cleared", target="inbox",
                detail=f"letters={n_letters} replies={n_replies} kept={kept}",
            )

        # After the rows are gone for good: a file that will not delete is a
        # leftover on the disk, not a reason to bring the inbox back.
        missed = 0
        for stored in files:
            try:
                stored.storage.delete(stored.name)
            except Exception:  # noqa: BLE001
                missed += 1
        self.stdout.write(self.style.SUCCESS(
            f"Deleted {n_letters} letters and {n_replies} replies."
            + (f" {missed} files could not be removed from storage." if missed else "")
        ))
