"""Message templates as code, not as forms.

Outside the 24-hour customer-service window WhatsApp only carries an approved
template, so a number with zero templates can answer clients but can never open
a conversation. The WhatsApp Manager UI can create them, but a template that
lives only in that UI is invisible to the repo, cannot be reviewed in a diff,
and has to be retyped by hand every time Meta rejects one over a wording
detail. So they live here instead, next to the code that sends them.

    python manage.py wa_templates <WABA_ID> --list
    python manage.py wa_templates <WABA_ID> --submit            # all pending
    python manage.py wa_templates <WABA_ID> --submit order_received
    python manage.py wa_templates <WABA_ID> --show              # print, send nothing

``--submit`` is the only destructive verb here and it never overwrites: Meta
refuses a name that already exists, and this command reports that as "already
there" rather than treating it as a failure.

Every template below is UTILITY — a reply to something the client already did.
Anything that advertises, upsells, or greets without a triggering action is
MARKETING, costs more, and is rejected far more often. Keep it that way.
"""

import json
import urllib.parse

from django.core.management.base import BaseCommand, CommandError

from dashboard import whatsapp

#: Arabic, because that is what Eagle's clients read. A template is submitted
#: per language, so an English set would be separate entries with the same
#: ``name`` and ``language: "en"``.
LANGUAGE = "ar"

#: name -> (category, body, footer, what it is for)
#:
#: Two rules Meta enforces that are easy to trip over:
#:   * a body may not begin or end with a variable, so every one below is
#:     wrapped in real words;
#:   * variables must be numbered {{1}}, {{2}}, ... with no gaps.
TEMPLATES = {
    "order_received": (
        "UTILITY",
        "مرحبًا {{1}}، استلمنا طلب الترجمة رقم {{2}}. "
        "عدد الصفحات: {{3}}، والتسليم المتوقع: {{4}}. "
        "هنبلغك أول ما يخلص.",
        "Eagle Translation",
        "Sent the moment a request is logged, so the client has a reference number.",
    ),
    "quote_ready": (
        "UTILITY",
        "مرحبًا {{1}}، عرض السعر لطلب الترجمة رقم {{2}} جاهز. "
        "الإجمالي {{3}} جنيه ومدة التنفيذ {{4}}. "
        "لو موافق رد على الرسالة دي ونبدأ على طول.",
        "Eagle Translation",
        "Sent when pricing is decided and the client has to approve before work starts.",
    ),
    "missing_info": (
        "UTILITY",
        "مرحبًا {{1}}، عشان نكمّل طلب الترجمة رقم {{2}} ناقصنا: {{3}}. "
        "ابعتها هنا ونكمّل على طول.",
        "Eagle Translation",
        "Sent when a request is blocked waiting on the client.",
    ),
    "order_delivered": (
        "UTILITY",
        "مرحبًا {{1}}، طلب الترجمة رقم {{2}} اتسلّم والملفات موجودة في المحادثة. "
        "لو محتاج أي تعديل رد على الرسالة دي خلال {{3}}.",
        "Eagle Translation",
        "Sent on delivery, and it reopens the 24h window for revisions.",
    ),
}


class Command(BaseCommand):
    help = "List, preview and submit Eagle's WhatsApp message templates."

    def add_arguments(self, parser):
        parser.add_argument("waba_id", help="WhatsApp Business Account ID.")
        parser.add_argument("--list", action="store_true",
                            help="Read the templates Meta already has.")
        parser.add_argument("--show", action="store_true",
                            help="Print the templates defined here. Sends nothing.")
        parser.add_argument("--submit", nargs="*", metavar="NAME",
                            help="Submit templates for review. No names = every "
                                 "one not already at Meta.")

    # ------------------------------------------------------------------
    def handle(self, *args, **options):
        conf = whatsapp._conf()
        token = (conf.whatsapp_access_token or "").strip()
        if not token:
            raise CommandError("No WhatsApp access token in /panel/settings/.")

        waba_id = options["waba_id"].strip()
        base = f"{whatsapp.GRAPH_HOST}/{whatsapp._version(conf)}/{waba_id}/message_templates"

        if options["show"]:
            self._show_local()
            return

        existing = self._existing(base, token)

        if options["submit"] is None:
            self._list(existing)
            return

        wanted = options["submit"] or sorted(TEMPLATES)
        unknown = [n for n in wanted if n not in TEMPLATES]
        if unknown:
            raise CommandError(
                f"Not defined here: {', '.join(unknown)}. "
                f"Known: {', '.join(sorted(TEMPLATES))}"
            )
        self._submit(base, token, wanted, existing)

    # ------------------------------------------------------------------
    def _show_local(self):
        self.stdout.write("")
        self.stdout.write(self.style.MIGRATE_HEADING(
            f"Templates defined in this file ({len(TEMPLATES)}), language {LANGUAGE}"
        ))
        for name, (category, body, footer, purpose) in sorted(TEMPLATES.items()):
            self.stdout.write("")
            self.stdout.write(self.style.SUCCESS(f"  {name}  [{category}]"))
            self.stdout.write(f"    {purpose}")
            for line in body.split("\n"):
                self.stdout.write(f"    | {line}")
            self.stdout.write(f"    | -- {footer}")
        self.stdout.write("")

    def _existing(self, base, token):
        """``{name: status}`` for everything Meta already holds."""
        url = f"{base}?fields=name,status,category,language&limit=200"
        try:
            payload = whatsapp._call(url, token=token)
        except whatsapp.WhatsAppError as exc:
            self.stderr.write(self.style.ERROR(
                f"Could not read existing templates: {exc.raw or exc.message_en}"
            ))
            return {}
        return {
            item.get("name"): (item.get("status"), item.get("language"))
            for item in payload.get("data", [])
        }

    def _list(self, existing):
        self.stdout.write("")
        if not existing:
            self.stdout.write(self.style.WARNING(
                "  Meta has no templates for this WABA."
            ))
            self.stdout.write(
                "  Without one, this number can only reply inside the 24h window —\n"
                "  it cannot start a conversation at all.\n"
                "  Run with --show to read the drafts, then --submit to send them."
            )
            self.stdout.write("")
            return

        self.stdout.write(self.style.MIGRATE_HEADING(f"  At Meta ({len(existing)}):"))
        for name, (status, language) in sorted(existing.items()):
            style = self.style.SUCCESS if status == "APPROVED" else (
                self.style.ERROR if status == "REJECTED" else self.style.WARNING
            )
            here = "" if name in TEMPLATES else "   (not defined in wa_templates.py)"
            self.stdout.write(f"    {name:<24} {language:<6} " + style(status) + here)

        missing = sorted(set(TEMPLATES) - set(existing))
        if missing:
            self.stdout.write("")
            self.stdout.write(f"  Defined here but not submitted: {', '.join(missing)}")
        self.stdout.write("")

    def _submit(self, base, token, wanted, existing):
        self.stdout.write("")
        for name in wanted:
            if name in existing:
                status, _ = existing[name]
                self.stdout.write(self.style.WARNING(
                    f"  {name:<24} already at Meta ({status}) — skipped"
                ))
                continue

            category, body, footer, _purpose = TEMPLATES[name]
            payload = {
                "name": name,
                "language": LANGUAGE,
                "category": category,
                "components": [
                    {"type": "BODY", "text": body},
                    {"type": "FOOTER", "text": footer},
                ],
            }
            try:
                result = whatsapp._call(
                    base, token=token,
                    data=json.dumps(payload).encode("utf-8"),
                    method="POST",
                    headers={"Content-Type": "application/json"},
                )
            except whatsapp.WhatsAppError as exc:
                self.stdout.write(self.style.ERROR(f"  {name:<24} refused"))
                self.stdout.write(f"      {exc.raw or exc.message_en}")
                continue

            status = result.get("status", "?")
            self.stdout.write(self.style.SUCCESS(
                f"  {name:<24} submitted — status {status}"
            ))

        self.stdout.write("")
        self.stdout.write(
            "  Review usually lands within a few hours. Re-run with --list to check.\n"
            "  A REJECTED template can be edited in WhatsApp Manager and resubmitted;\n"
            "  fix the wording here too so the repo stays the source of truth."
        )
        self.stdout.write("")
