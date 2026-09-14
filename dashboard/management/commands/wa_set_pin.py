"""Set the WhatsApp two-step verification PIN through the Cloud API.

WhatsApp Manager has a PIN dialog, but it fails often and unhelpfully — it just
says "The PIN could not be changed" with no reason. The Cloud API does the same
job and, when it refuses, says why:

    POST /{phone-number-id}   with   pin=<6 digits>

Meta's own reference confirms this is the only way to set the code, and that
there is no endpoint to turn two-step verification back off — so pick a PIN you
can live with and write it down.

    python manage.py wa_set_pin 123456
    python manage.py wa_set_pin            # prompts, and does not echo the PIN

Credentials come from AppSettings, so the access token never has to be typed or
pasted anywhere.
"""

import getpass
import urllib.parse

from django.core.management.base import BaseCommand, CommandError

from dashboard import whatsapp


class Command(BaseCommand):
    help = "Set the two-step verification PIN for the configured WhatsApp number."

    def add_arguments(self, parser):
        parser.add_argument(
            "pin",
            nargs="?",
            help="The new 6-digit PIN. Omit it to be prompted without echo.",
        )

    def handle(self, *args, **options):
        conf = whatsapp._conf()
        whatsapp._require(conf)

        pin = options["pin"] or getpass.getpass("New 6-digit PIN: ")
        pin = pin.strip()
        if not (pin.isdigit() and len(pin) == 6):
            raise CommandError("The PIN has to be exactly 6 digits.")

        phone_id = conf.whatsapp_phone_number_id.strip()
        url = f"{whatsapp.GRAPH_HOST}/{whatsapp._version(conf)}/{phone_id}"
        body = urllib.parse.urlencode({"pin": pin}).encode("utf-8")

        self.stdout.write(f"POST {url}  (pin: 6 digits, not shown)")

        try:
            result = whatsapp._call(
                url,
                token=conf.whatsapp_access_token,
                data=body,
                method="POST",
                headers={"Content-Type": "application/x-www-form-urlencoded"},
            )
        except whatsapp.WhatsAppError as exc:
            # The point of this command is the reason, so print everything Meta
            # said — the code and the raw detail, not just our friendly wording.
            self.stderr.write(self.style.ERROR(exc.message_en))
            if exc.code:
                self.stderr.write(f"  code:   {exc.code}")
            if exc.raw:
                self.stderr.write(f"  detail: {exc.raw}")
            raise CommandError("Meta refused to set the PIN — the reason is above.")

        if result.get("success") is True:
            self.stdout.write(self.style.SUCCESS("Two-step verification is on. Keep the PIN somewhere safe."))
        else:
            self.stdout.write(self.style.WARNING(f"Unexpected response: {result}"))
