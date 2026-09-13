"""Check — and if needed repair — the link between the WABA and this app.

A WhatsApp Business Account only forwards incoming messages to an app that is
explicitly *subscribed* to it (``POST /{waba-id}/subscribed_apps``). Subscribing
the webhook *fields* in the App Dashboard is a separate thing: it says which
event types the app wants, not which WABA sends them. When a WABA is created by
hand in Business settings instead of through embedded signup, that subscription
is easy to miss — and the symptom is exactly this: test events fired from the
App Dashboard arrive, real customer messages never do.

    python manage.py wa_webhook_link <WABA_ID>              # report only
    python manage.py wa_webhook_link <WABA_ID> --subscribe  # create the link

Credentials come from AppSettings, so the token never has to be typed in.
"""

from django.core.management.base import BaseCommand, CommandError

from dashboard import whatsapp
from dashboard.models import AppSettings


class Command(BaseCommand):
    help = "Show (and optionally create) the WABA -> app webhook subscription."

    def add_arguments(self, parser):
        parser.add_argument("waba_id", help="WhatsApp Business Account ID")
        parser.add_argument(
            "--subscribe", action="store_true",
            help="Subscribe this app to the WABA if it is not already.",
        )

    def handle(self, *args, **options):
        conf = AppSettings.load()
        token = (conf.whatsapp_access_token or "").strip()
        if not token:
            raise CommandError("No WhatsApp access token in /panel/settings/.")

        waba_id = options["waba_id"].strip()
        version = (conf.whatsapp_api_version or whatsapp.DEFAULT_VERSION).strip()
        url = f"{whatsapp.GRAPH_HOST}/{version}/{waba_id}/subscribed_apps"

        self.stdout.write(f"WABA        : {waba_id}")
        self.stdout.write(f"API version : {version}")
        self.stdout.write("")

        try:
            current = whatsapp._call(url, token=token)
        except whatsapp.WhatsAppError as exc:
            raise CommandError(f"Could not read subscribed_apps: {exc.message_en}")

        apps = current.get("data") or []
        if apps:
            self.stdout.write(self.style.SUCCESS("Subscribed apps:"))
            for item in apps:
                app = item.get("whatsapp_business_api_data", {}) or item
                self.stdout.write(f"  - {app.get('name', '?')}  (id {app.get('id', '?')})")
        else:
            self.stdout.write(self.style.ERROR("NO APP IS SUBSCRIBED TO THIS WABA."))
            self.stdout.write("This is why real customer messages never reach the webhook.")

        if not options["subscribe"]:
            if not apps:
                self.stdout.write("")
                self.stdout.write("Re-run with --subscribe to create the link.")
            return

        self.stdout.write("")
        self.stdout.write("Subscribing this app to the WABA ...")
        try:
            result = whatsapp._call(url, token=token, data=b"", method="POST")
        except whatsapp.WhatsAppError as exc:
            raise CommandError(f"Subscribe failed: {exc.message_en}")

        if result.get("success"):
            self.stdout.write(self.style.SUCCESS("Subscribed."))
        else:
            self.stdout.write(f"Unexpected reply: {result}")

        after = whatsapp._call(url, token=token).get("data") or []
        self.stdout.write("")
        self.stdout.write("Subscribed apps now:")
        for item in after:
            app = item.get("whatsapp_business_api_data", {}) or item
            self.stdout.write(f"  - {app.get('name', '?')}  (id {app.get('id', '?')})")
