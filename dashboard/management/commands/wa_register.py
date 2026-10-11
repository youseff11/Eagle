"""Register a WhatsApp number with the Cloud API after it was verified.

A number added in WhatsApp Manager and verified by SMS stays "Pending" there
until it is registered, and Manager has no button for it — it says to use the
API:

    POST /{phone-number-id}/register   with   messaging_product=whatsapp, pin=<6 digits>

The PIN becomes the number's two-step verification code, so write it down.
The phone number ID is the one WhatsApp Manager shows under the number.

    python manage.py wa_register 1409717205552232            # prompts, no echo
    python manage.py wa_register 1409717205552232 --pin 123456

The access token comes from AppSettings, so it never has to be typed or pasted.
"""

import getpass
import urllib.parse

from django.core.management.base import BaseCommand, CommandError

from dashboard import whatsapp


class Command(BaseCommand):
    help = "Register a verified WhatsApp number with the Cloud API (Pending -> Connected)."

    def add_arguments(self, parser):
        parser.add_argument("phone_number_id", help="The number's ID from WhatsApp Manager.")
        parser.add_argument("--pin", help="6-digit PIN. Omit it to be prompted without echo.")

    def handle(self, *args, **options):
        conf = whatsapp._conf()
        if not conf.whatsapp_access_token:
            raise CommandError("No access token configured.")

        phone_id = options["phone_number_id"].strip()
        if not phone_id.isdigit():
            raise CommandError("The phone number ID is digits only.")

        pin = (options["pin"] or getpass.getpass("6-digit PIN for this number: ")).strip()
        if not (pin.isdigit() and len(pin) == 6):
            raise CommandError("The PIN has to be exactly 6 digits.")

        url = f"{whatsapp.GRAPH_HOST}/{whatsapp._version(conf)}/{phone_id}/register"
        body = urllib.parse.urlencode({"messaging_product": "whatsapp", "pin": pin}).encode("utf-8")

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
            self.stderr.write(self.style.ERROR(exc.message_en))
            if exc.code:
                self.stderr.write(f"  code:   {exc.code}")
            if exc.raw:
                self.stderr.write(f"  detail: {exc.raw}")
            raise CommandError("Meta refused to register the number - the reason is above.")

        if result.get("success") is True:
            self.stdout.write(self.style.SUCCESS("Registered. Keep the PIN somewhere safe."))
        else:
            self.stdout.write(self.style.WARNING(f"Unexpected response: {result}"))
