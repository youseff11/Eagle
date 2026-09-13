"""Is this number allowed to use the WhatsApp Groups API? Ask Meta, don't guess.

The Groups API is gated behind **Official Business Account** status, which is a
different and much higher bar than the business verification Eagle already
passed. There is no reliable way to read that from a settings page, and the
public docs describe the requirement without telling you where you stand, so
this command asks the only source that decides: the Graph API itself.

    python manage.py wa_groups_check                 # phone number + groups probe
    python manage.py wa_groups_check <WABA_ID>       # also read the WABA node

The probe is ``GET /{phone-number-id}/groups``. A 200 (even with an empty list)
means the door is open. An error means it is not, and the error text says why.

Credentials come from AppSettings, so the token never has to be typed in.
"""

import json
import urllib.parse

from django.core.management.base import BaseCommand, CommandError

from dashboard import whatsapp
from dashboard.models import AppSettings

#: Everything worth knowing about the number. Graph rejects the whole request
#: when one field is unknown to the version in use, so there is a fallback.
PHONE_FIELDS = (
    "display_phone_number,verified_name,quality_rating,platform_type,"
    "code_verification_status,name_status,is_official_business_account"
)
PHONE_FIELDS_SAFE = "display_phone_number,verified_name,quality_rating"

WABA_FIELDS = "name,account_review_status,is_official_business_account,ownership_type"

#: The four webhook fields a groups integration has to be subscribed to.
GROUP_WEBHOOK_FIELDS = (
    "group_lifecycle_update",
    "group_participants_update",
    "group_settings_update",
    "group_status_update",
)


class Command(BaseCommand):
    help = "Report whether this WhatsApp number can use the Groups API."

    def add_arguments(self, parser):
        parser.add_argument(
            "waba_id", nargs="?", default="",
            help="WhatsApp Business Account ID (optional — adds the WABA read).",
        )

    # ------------------------------------------------------------------
    def handle(self, *args, **options):
        conf = AppSettings.load()
        token = (conf.whatsapp_access_token or "").strip()
        phone_id = (conf.whatsapp_phone_number_id or "").strip()
        if not token:
            raise CommandError("No WhatsApp access token in /panel/settings/.")
        if not phone_id:
            raise CommandError("No WhatsApp phone number ID in /panel/settings/.")

        version = (conf.whatsapp_api_version or whatsapp.DEFAULT_VERSION).strip()
        base = f"{whatsapp.GRAPH_HOST}/{version}"

        self.stdout.write("")
        self.stdout.write(self.style.MIGRATE_HEADING("WhatsApp Groups API — eligibility"))
        self.stdout.write("")
        self.stdout.write(f"  Phone number ID : {phone_id}")
        self.stdout.write(f"  API version     : {version}")
        self.stdout.write("")

        self._phone(base, phone_id, token)
        if options["waba_id"]:
            self._waba(base, options["waba_id"].strip(), token)
        open_door = self._groups(base, phone_id, token)

        self.stdout.write("")
        if open_door:
            self.stdout.write(self.style.SUCCESS(
                "VERDICT: the Groups API answers for this number — it can be built."
            ))
            self.stdout.write(
                "  Next: subscribe the app to "
                + ", ".join(GROUP_WEBHOOK_FIELDS)
                + " in the App Dashboard, then re-run wa_webhook_link."
            )
        else:
            self.stdout.write(self.style.ERROR(
                "VERDICT: the Groups API is closed for this number."
            ))
            self.stdout.write(
                "  Almost always this is Official Business Account status — a higher\n"
                "  bar than business verification. Groups cannot be built until Meta\n"
                "  grants it; the error line above is the authority, not the docs."
            )
        self.stdout.write("")

    # ------------------------------------------------------------------
    def _get(self, url, token):
        """Return ``(payload, error_text)`` — never raises."""
        try:
            return whatsapp._call(url, token=token), ""
        except whatsapp.WhatsAppError as exc:
            return None, (exc.raw or exc.message_en)

    def _show(self, payload, keys):
        for key in keys:
            if key in payload:
                value = payload[key]
                self.stdout.write(f"    {key:<32} {value}")

    def _phone(self, base, phone_id, token):
        url = f"{base}/{phone_id}?fields={urllib.parse.quote(PHONE_FIELDS)}"
        payload, error = self._get(url, token)
        if payload is None:
            # An unknown field fails the whole read; fall back to the safe set.
            url = f"{base}/{phone_id}?fields={urllib.parse.quote(PHONE_FIELDS_SAFE)}"
            payload, error = self._get(url, token)
        if payload is None:
            self.stdout.write(self.style.ERROR(f"  Phone number    : {error[:200]}"))
            return
        self.stdout.write("  Phone number:")
        self._show(payload, [
            "display_phone_number", "verified_name", "quality_rating",
            "platform_type", "code_verification_status", "name_status",
            "is_official_business_account",
        ])
        self.stdout.write("")

    def _waba(self, base, waba_id, token):
        url = f"{base}/{waba_id}?fields={urllib.parse.quote(WABA_FIELDS)}"
        payload, error = self._get(url, token)
        if payload is None:
            self.stdout.write(self.style.ERROR(f"  WABA            : {error[:200]}"))
            self.stdout.write("")
            return
        self.stdout.write(f"  WABA {waba_id}:")
        self._show(payload, [
            "name", "account_review_status", "is_official_business_account",
            "ownership_type",
        ])
        self.stdout.write("")

    def _groups(self, base, phone_id, token):
        """The decisive test: does the groups edge answer at all?"""
        url = f"{base}/{phone_id}/groups?limit=1"
        self.stdout.write(f"  Probe           : GET /{phone_id}/groups?limit=1")
        payload, error = self._get(url, token)
        if payload is None:
            self.stdout.write(self.style.ERROR(f"    -> {error[:300]}"))
            return False
        groups = (payload.get("data") or {})
        if isinstance(groups, dict):
            groups = groups.get("groups") or []
        self.stdout.write(self.style.SUCCESS(
            f"    -> 200 OK, {len(groups)} group(s) returned"
        ))
        if groups:
            self.stdout.write("    " + json.dumps(groups[0], ensure_ascii=False)[:300])
        return True
