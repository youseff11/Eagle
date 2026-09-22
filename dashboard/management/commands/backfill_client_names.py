"""Fill in blank client names from the messages already in the inbox.

Every WhatsApp message carries the sender's profile name, and it has been
stored on the message (``sender_display``) all along - it just never reached
the client row. New messages fill it in by themselves now; this is for the
clients who wrote before that.

    python manage.py backfill_client_names --dry-run
    python manage.py backfill_client_names

Only blank names are touched. A name an admin typed is a decision, and a
profile name is whatever the person happens to have set on their phone.
"""

from django.core.management.base import BaseCommand

from dashboard.models import Client


class Command(BaseCommand):
    help = "Fill blank client names from the profile name on their messages."

    def add_arguments(self, parser):
        parser.add_argument(
            "--dry-run", action="store_true",
            help="List what would change and write nothing.",
        )

    def handle(self, *args, **options):
        filled, skipped = 0, 0
        for client in Client.objects.filter(name="").prefetch_related("messages"):
            # Newest first: if they changed their profile name, the latest is
            # the one they answer to now.
            name = (
                client.messages.exclude(sender_display="")
                .order_by("-received_at")
                .values_list("sender_display", flat=True)
                .first()
            )
            name = (name or "").strip()[:120]
            if not name:
                skipped += 1
                continue
            self.stdout.write(f"  {client.code} -> {name}")
            if not options["dry_run"]:
                client.name = name
                client.save(update_fields=["name"])
            filled += 1

        if options["dry_run"]:
            self.stdout.write(
                f"would fill {filled} client(s). {skipped} have no profile "
                f"name on any message. Nothing written."
            )
            return
        self.stdout.write(self.style.SUCCESS(
            f"filled {filled} client(s). {skipped} had nothing to fill from."
        ))
