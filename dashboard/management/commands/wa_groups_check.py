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
    "code_verification_status,name_status,is_official_business_account,"
    "is_pin_enabled,messaging_limit_tier,health_status"
)
PHONE_FIELDS_SAFE = "display_phone_number,verified_name,quality_rating"

WABA_FIELDS = ("name,account_review_status,is_official_business_account,"
               "ownership_type,created_time")
WABA_FIELDS_SAFE = "name,account_review_status,ownership_type"

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
        parser.add_argument(
            "--create-test", action="store_true",
            help="Actually create a throwaway group, read it back, then delete it.",
        )
        parser.add_argument(
            "--keep", action="store_true",
            help="With --create-test: leave the group in place instead of deleting it.",
        )
        parser.add_argument(
            "--metadata", action="store_true",
            help="Ask Graph which fields these nodes actually expose, and dump them. "
                 "Use this instead of trusting the docs when a field comes back empty.",
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

        self.phone = {}
        self.waba = {}
        self.blockers = []

        self._phone(base, phone_id, token)
        if options["waba_id"]:
            self._waba(base, options["waba_id"].strip(), token)
        if options["metadata"]:
            self._metadata(base, phone_id, token, "phone number")
            if options["waba_id"]:
                self._metadata(base, options["waba_id"].strip(), token, "WABA")
        can_read = self._groups(base, phone_id, token)

        open_door = can_read
        if can_read and options["create_test"]:
            # Reading the edge and being allowed to write to it are two
            # different permissions. Only a real create settles it.
            open_door = self._create_test(base, phone_id, token, keep=options["keep"])

        self.stdout.write("")
        if open_door and options["create_test"]:
            self.stdout.write(self.style.SUCCESS(
                "VERDICT: groups can be created on this number — safe to build."
            ))
            self.stdout.write(
                "  Next: subscribe the app to "
                + ", ".join(GROUP_WEBHOOK_FIELDS)
                + " in the App Dashboard, then re-run wa_webhook_link."
            )
        elif open_door:
            oba = self.phone.get("is_official_business_account")
            self.stdout.write(self.style.WARNING(
                "VERDICT: the groups edge READS fine. Creating is untested."
            ))
            if oba is False:
                # Reading is allowed for everyone; creating is the gated part.
                self.stdout.write(
                    "  But is_official_business_account is False, so a create will"
                    " almost certainly be refused."
                )
            self.stdout.write("  Re-run with --create-test to settle it.")
        else:
            self.stdout.write(self.style.ERROR(
                "VERDICT: the Groups API is closed for this number."
            ))
            self.stdout.write(
                "  Almost always this is Official Business Account status — a higher\n"
                "  bar than business verification. Groups cannot be built until Meta\n"
                "  grants it; the error line above is the authority, not the docs."
            )

        # The checklist is most useful in exactly the case it used to skip:
        # the edge reads, the flag is False, and nothing says what to do next.
        if self.phone.get("is_official_business_account") is not True:
            self._oba_checklist()
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
        self.phone = payload
        self.stdout.write("  Phone number:")
        self._show(payload, [
            "display_phone_number", "verified_name", "quality_rating",
            "platform_type", "code_verification_status", "name_status",
            "is_official_business_account", "is_pin_enabled",
            "messaging_limit_tier",
        ])
        self.stdout.write("")
        self._health(payload.get("health_status"))

    def _health(self, health):
        """What Meta says is wrong *right now*, in its own words.

        ``health_status`` is the only field on the whole node that states the
        current blockers outright instead of leaving them to be inferred from
        flags. It outranks everything else here: a flag can be read two ways,
        but "your display name has not been approved yet" cannot.
        """
        if not isinstance(health, dict):
            return

        overall = health.get("can_send_message", "?")
        style = self.style.SUCCESS if overall == "AVAILABLE" else self.style.ERROR
        self.stdout.write("  Health — what Meta says is blocking this account:")
        self.stdout.write("    " + style(f"can_send_message = {overall}"))

        self.blockers = []
        for entity in health.get("entities") or []:
            kind = entity.get("entity_type", "?")
            state = entity.get("can_send_message", "?")
            if state == "AVAILABLE":
                continue
            self.stdout.write(f"    {kind} ({state}):")
            for err in entity.get("errors") or []:
                # Calling/SIP errors are noise for a messaging integration.
                if err.get("error_code") in (138024, 138025):
                    continue
                text = err.get("error_description", "")
                self.stdout.write(self.style.ERROR(f"      - [{err.get('error_code')}] {text}"))
                fix = err.get("possible_solution")
                if fix:
                    self.stdout.write(f"        fix: {fix}")
                self.blockers.append(text)
            for note in entity.get("additional_info") or []:
                self.stdout.write(self.style.WARNING(f"      ! {note}"))
                self.blockers.append(note)
        self.stdout.write("")

    def _waba(self, base, waba_id, token):
        url = f"{base}/{waba_id}?fields={urllib.parse.quote(WABA_FIELDS)}"
        payload, error = self._get(url, token)
        if payload is None:
            url = f"{base}/{waba_id}?fields={urllib.parse.quote(WABA_FIELDS_SAFE)}"
            payload, error = self._get(url, token)
        if payload is None:
            self.stdout.write(self.style.ERROR(f"  WABA            : {error[:200]}"))
            self.stdout.write("")
            return
        self.stdout.write(f"  WABA {waba_id}:")
        self._show(payload, [
            "name", "account_review_status", "is_official_business_account",
            "ownership_type", "created_time",
        ])
        self.stdout.write("")
        self.waba = payload

    #: Fields worth asking about one at a time when introspection comes back
    #: empty. The two open questions are the number's age (the 30-day rule) and
    #: whether two-step is on, so anything date-shaped or pin-shaped is here,
    #: plus the handful of status fields that are useful when they do exist.
    PROBE_FIELDS = {
        "phone number": (
            "last_onboarded_time", "created_time", "is_pin_enabled",
            "two_step_verification_enabled", "status", "account_mode",
            "messaging_limit_tier", "certificate", "throughput",
            "eligibility_for_api_business_global_search", "health_status",
        ),
        "WABA": (
            "created_time", "business_verification_status", "country",
            "currency", "timezone_id", "message_template_namespace",
            "primary_business_location", "health_status",
        ),
    }

    def _metadata(self, base, node_id, token, label):
        """Ask Graph what this node really exposes.

        ``?metadata=1`` makes Graph describe the node instead of reading it, so
        this answers "does a registration date exist on this version at all?"
        with the API's own answer rather than with a docs page that may describe
        a different node. Two fields are worth hunting for by hand — anything
        date-shaped (the 30-day requirement) and anything pin-shaped (two-step)
        — so those are pulled out of the list and shown first.
        """
        payload, error = self._get(f"{base}/{node_id}?metadata=1", token)
        names = []
        if payload is None:
            self.stdout.write(self.style.ERROR(f"  {label} metadata: {error[:200]}"))
        else:
            fields = (payload.get("metadata") or {}).get("fields") or []
            names = sorted(f.get("name", "") for f in fields if f.get("name"))

        if names:
            self.stdout.write(f"  {label} node exposes {len(names)} field(s):")
            interesting = [
                n for n in names
                if any(w in n for w in ("time", "date", "created", "onboard", "pin", "verif"))
            ]
            if interesting:
                self.stdout.write("    of interest here: " + ", ".join(interesting))
            self.stdout.write("    all: " + ", ".join(names))
            self.stdout.write("")
            return

        # Introspection came back empty — Graph does this for the WhatsApp nodes
        # rather than erroring, which looks like "the node has no fields" and is
        # not an answer. Ask about each candidate field instead: Graph answers a
        # field it does not have with "nonexisting field", so one request per
        # name settles existence AND reads the value in the same call.
        self.stdout.write(self.style.WARNING(
            f"  {label} metadata: introspection returned nothing — probing fields one by one."
        ))
        for name in self.PROBE_FIELDS.get(label, ()):
            probe, probe_error = self._get(f"{base}/{node_id}?fields={name}", token)
            if probe is None:
                short = probe_error.split(".")[0][:90]
                self.stdout.write(f"    {name:<34} — no ({short})")
            else:
                value = probe.get(name, "(returned, but empty)")
                self.stdout.write(self.style.SUCCESS(f"    {name:<34} = {value}"))
        self.stdout.write("")

    def _oba_checklist(self):
        """What is still missing for Official Business Account status.

        Meta's own summary page says "business verified" and "account approved"
        in green, and neither of those is OBA — they are the bar Eagle already
        cleared. OBA is a separate flag, and this prints the five requirements
        with the three that can be measured actually measured.
        """
        self.stdout.write("")
        self.stdout.write(self.style.MIGRATE_HEADING(
            "  Official Business Account — what is still missing"
        ))
        self.stdout.write(
            "  Note: 'business verified' and 'account approved' are NOT this.\n"
            "  Those are already green and are a different, lower bar.\n"
        )

        quality = (self.phone.get("quality_rating") or "").upper()
        review = (self.waba.get("account_review_status") or "").upper()
        name_status = (self.phone.get("name_status") or "").upper()
        verified_name = (self.phone.get("verified_name") or "").strip()
        created = self.waba.get("created_time") or ""

        def row(done, label, detail=""):
            mark = self.style.SUCCESS(" done ") if done is True else (
                self.style.ERROR(" TODO ") if done is False else self.style.WARNING(" ?    ")
            )
            self.stdout.write(f"  [{mark}] {label}" + (f" — {detail}" if detail else ""))

        row(None if not quality else quality == "GREEN",
            "Messaging policy in good standing", f"quality_rating = {quality or 'unknown'}")
        # A missing field is not a failed requirement. Without a WABA id on the
        # command line there is no `account_review_status` to read at all, and
        # printing TODO for that sent the last run chasing a box that was
        # already ticked in Business Settings.
        if not review:
            row(None, "Business verification complete",
                "not read — pass the WABA id (wa_groups_check <WABA_ID>), or see "
                "Business Settings > Security Centre > Business verification")
        else:
            row(review == "APPROVED", "Business verification complete",
                f"account_review_status = {review}")

        age = self._account_age_days(created)
        if age is None:
            row(None, "Registered 30+ days",
                "no created_time on the API — read the real date in WhatsApp Manager > "
                "Activity log, the row 'تمت إضافة <number>' / 'added <number>'")
        else:
            row(age >= 30, "Registered 30+ days", f"{age} days old")

        pin = self.phone.get("is_pin_enabled")
        if pin is None:
            row(None, "Two-step verification ON for the number",
                "is_pin_enabled not returned — set it with `manage.py wa_set_pin`")
        else:
            row(bool(pin), "Two-step verification ON for the number",
                f"is_pin_enabled = {pin}"
                + ("" if pin else " — run `manage.py wa_set_pin`"))

        # Read this one from health_status, not from flags. `verified_name`
        # holds the name Eagle ASKED for, and it is filled in whether or not
        # review has passed — reading approval out of it was wrong, and this
        # row said "done" while Meta was saying the opposite in plain English.
        unapproved = any("display name has not been approved" in b.lower()
                         for b in getattr(self, "blockers", []))
        if unapproved:
            # "not approved YET" covers both "never submitted" and "sitting in
            # review", and nothing on the API tells the two apart. Telling the
            # reader to go submit a name is therefore dangerous advice: a new
            # submission REPLACES a review already in flight and restarts the
            # clock. The activity log is what distinguishes them, so send the
            # reader there instead of at the edit box.
            row(False, "Display name approved",
                f'Meta: the display name ("{verified_name}") is NOT approved yet. '
                "Before submitting anything, open WhatsApp Manager > Activity log "
                "and look for 'name verification requested' — if one is there, the "
                "review is already running and a new submission would replace it.")
        elif verified_name and name_status == "APPROVED":
            row(True, "Display name approved", f'verified_name = "{verified_name}"')
        elif name_status in ("PENDING_REVIEW", "AVAILABLE_WITHOUT_REVIEW"):
            row(None, "Display name approved", f"in review ({name_status})")
        else:
            row(None, "Display name approved",
                f'verified_name = "{verified_name or "—"}", name_status = '
                f"{name_status or 'unknown'} — check the Profile tab; the flags alone "
                "do not say whether review passed")

        self.stdout.write("")
        self.stdout.write(
            "  When all five are green: WhatsApp Manager > the number > "
            "Official business account > Submit Request.\n"
            "  A rejection locks the request for 30 days, so do not submit early.\n"
            "  Green does not mean approved, either: Meta's own wording on that\n"
            "  page is that the badge marks 'a well-known real brand'. The five\n"
            "  rows below are what lets you APPLY; recognition is what the\n"
            "  reviewer then judges, and this command cannot measure that.\n"
            "  Then re-run this command with --create-test."
        )

    @staticmethod
    def _account_age_days(created):
        """``created_time`` is an ISO stamp when Meta sends one at all."""
        if not created:
            return None
        from datetime import datetime, timezone as dt_timezone

        text = str(created).replace("Z", "+00:00")
        try:
            stamp = datetime.fromisoformat(text)
        except ValueError:
            return None
        if stamp.tzinfo is None:
            stamp = stamp.replace(tzinfo=dt_timezone.utc)
        return (datetime.now(dt_timezone.utc) - stamp).days

    def _post(self, url, token, payload):
        try:
            body = json.dumps(payload).encode("utf-8")
            return whatsapp._call(
                url, token=token, data=body, method="POST",
                headers={"Content-Type": "application/json"},
            ), ""
        except whatsapp.WhatsAppError as exc:
            return None, (exc.raw or exc.message_en)

    def _delete(self, url, token):
        try:
            return whatsapp._call(url, token=token, method="DELETE"), ""
        except whatsapp.WhatsAppError as exc:
            return None, (exc.raw or exc.message_en)

    def _create_test(self, base, phone_id, token, keep=False):
        """Create a throwaway group, read it back, then clean up after itself."""
        self.stdout.write("")
        self.stdout.write("  Create test:")

        created, error = self._post(
            f"{base}/{phone_id}/groups", token,
            {
                "messaging_product": "whatsapp",
                "subject": "Eagle API test",
                "description": "Temporary group created by wa_groups_check.",
                "join_approval_mode": "approval_required",
            },
        )
        if created is None:
            self.stdout.write(self.style.ERROR(f"    POST /groups -> {error[:300]}"))
            return False

        group_id = created.get("id", "")
        self.stdout.write(self.style.SUCCESS("    POST /groups -> created"))
        self.stdout.write(f"      id          {group_id}")
        if created.get("invite_link"):
            self.stdout.write(f"      invite_link {created['invite_link']}")

        if not group_id:
            self.stdout.write(self.style.ERROR("    No group id came back — cannot continue."))
            return False

        info, error = self._get(
            f"{base}/{group_id}"
            "?fields=subject,description,participants,join_approval_mode", token,
        )
        if info is None:
            self.stdout.write(self.style.WARNING(f"    GET /{{group}} -> {error[:200]}"))
        else:
            self.stdout.write("    GET /{group} -> "
                              + json.dumps(info, ensure_ascii=False)[:300])

        link, error = self._get(f"{base}/{group_id}/invite_link", token)
        if link is None:
            self.stdout.write(self.style.WARNING(f"    GET /invite_link -> {error[:200]}"))
        else:
            self.stdout.write(f"    GET /invite_link -> {link.get('invite_link', link)}")

        if keep:
            self.stdout.write(self.style.WARNING(
                "    --keep: the test group was LEFT IN PLACE. Delete it yourself."
            ))
            return True

        gone, error = self._delete(f"{base}/{group_id}", token)
        if gone is None:
            self.stdout.write(self.style.ERROR(
                f"    DELETE /{{group}} -> {error[:200]}  (delete it by hand!)"
            ))
        else:
            self.stdout.write(self.style.SUCCESS("    DELETE /{group} -> cleaned up"))
        return True

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
