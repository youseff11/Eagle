"""Pull unread mail over IMAP and turn each message into an inbound record.

Configure the IMAP host / user / password in the admin panel, then run:

    python manage.py fetch_emails
"""

import email
import email.utils
import imaplib
from email.header import decode_header, make_header

from django.core.files.base import ContentFile
from django.core.management.base import BaseCommand

from dashboard import services
from dashboard.models import AppSettings


def _decode(value):
    if not value:
        return ""
    try:
        return str(make_header(decode_header(value)))
    except Exception:
        return str(value)


class Command(BaseCommand):
    help = "Fetch unseen e-mails over IMAP into the operation inbox."

    def add_arguments(self, parser):
        parser.add_argument("--limit", type=int, default=25)
        parser.add_argument("--keep-unread", action="store_true")

    def handle(self, *args, **options):
        conf = AppSettings.load()
        if not (conf.imap_host and conf.imap_user):
            self.stderr.write("IMAP is not configured in the admin panel.")
            return

        box = imaplib.IMAP4_SSL(conf.imap_host, conf.imap_port)
        box.login(conf.imap_user, conf.imap_password)
        box.select(conf.imap_folder or "INBOX")

        status, data = box.search(None, "UNSEEN")
        if status != "OK":
            self.stderr.write("IMAP search failed.")
            return

        ids = data[0].split()[: options["limit"]]
        created = 0
        for num in ids:
            fetch_type = "(BODY.PEEK[])" if options["keep_unread"] else "(RFC822)"
            status, payload = box.fetch(num, fetch_type)
            if status != "OK" or not payload or not payload[0]:
                continue
            message = email.message_from_bytes(payload[0][1])

            sender = email.utils.parseaddr(message.get("From", ""))[1]
            subject = _decode(message.get("Subject", ""))
            body, attachments = "", []

            for part in message.walk():
                disposition = str(part.get("Content-Disposition") or "")
                if part.get_content_type() == "text/plain" and "attachment" not in disposition:
                    payload_bytes = part.get_payload(decode=True) or b""
                    body += payload_bytes.decode(
                        part.get_content_charset() or "utf-8", errors="ignore"
                    )
                elif "attachment" in disposition:
                    raw = part.get_payload(decode=True) or b""
                    name = _decode(part.get_filename() or "attachment.bin")
                    attachments.append({
                        "file": ContentFile(raw, name=name),
                        "name": name,
                        "size": len(raw),
                    })

            services.ingest_message(
                channel="email", subject=subject, body=body.strip(),
                sender_identity=sender, external_id=message.get("Message-ID", ""),
                attachments=attachments,
            )
            created += 1

        box.close()
        box.logout()
        self.stdout.write(self.style.SUCCESS(f"Imported {created} message(s)."))
