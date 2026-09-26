"""Mask the client's identity out of the names of files already received.

New files are masked as they arrive (``services.ingest_message``). This does
the same for the ones that came in before: the name the client used moves to
``raw_name`` (the admin's download) and ``original_name`` - what everybody
else reads - gets the client's name, company, e-mail domain and number
replaced by their code.

    python manage.py mask_file_names            # show what would change
    python manage.py mask_file_names --apply    # change it

Safe to run twice: a row that already has a ``raw_name`` is masked from it,
so the result is the same the second time.
"""

from django.core.management.base import BaseCommand

from dashboard.files import mask_name
from dashboard.models import MessageAttachment


class Command(BaseCommand):
    help = "Mask client identity out of stored client file names."

    def add_arguments(self, parser):
        parser.add_argument("--apply", action="store_true", help="Write the changes.")

    def handle(self, *args, **options):
        rows = MessageAttachment.objects.select_related("message__client").exclude(
            message__client__isnull=True
        )
        changed = 0
        for row in rows.iterator():
            raw = row.raw_name or row.original_name
            masked = mask_name(raw, row.message.client)[:250]
            if masked == row.original_name and row.raw_name:
                continue
            if masked != raw:
                changed += 1
                # Codes and ids only - this output may be pasted anywhere.
                self.stdout.write(f"#{row.pk} {row.message.client.code}: masked")
            if options["apply"]:
                row.raw_name = raw
                row.original_name = masked
                row.save(update_fields=["raw_name", "original_name"])
        verb = "masked" if options["apply"] else "would be masked"
        self.stdout.write(self.style.SUCCESS(f"{changed} file name(s) {verb}."))
