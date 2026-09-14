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

#: name -> {category, body, footer, example, purpose}
#:
#: Rules Meta enforces that are easy to trip over:
#:   * variables must be numbered {{1}}, {{2}}, ... with no gaps;
#:   * a body may not begin or end with a variable;
#:   * **a body containing variables must ship sample values**. The first
#:     submission left ``example`` out and every template came back rejected
#:     or refused outright, which is the only signal Meta gives for it.
TEMPLATES = {
    "translation_order_received": {
        "category": "UTILITY",
        "body": "مرحبًا {{1}}، استلمنا طلب الترجمة رقم {{2}}. "
                "عدد الصفحات: {{3}}، والتسليم المتوقع: {{4}}. "
                "هنبلغك أول ما يخلص.",
        "footer": "Eagle Translation",
        "example": ["أحمد", "T-1042", "12", "الخميس 18 سبتمبر"],
        "purpose": "Sent the moment a request is logged, so the client has a reference number.",
    },
    "translation_quote_ready": {
        "category": "UTILITY",
        "body": "مرحبًا {{1}}، عرض السعر لطلب الترجمة رقم {{2}} جاهز. "
                "الإجمالي {{3}} جنيه ومدة التنفيذ {{4}}. "
                "لو موافق رد على الرسالة دي ونبدأ على طول.",
        "footer": "Eagle Translation",
        "example": ["أحمد", "T-1042", "850", "يومين"],
        "purpose": "Sent when pricing is decided and the client has to approve before work starts.",
    },
    "translation_missing_info": {
        "category": "UTILITY",
        "body": "مرحبًا {{1}}، عشان نكمّل طلب الترجمة رقم {{2}} ناقصنا: {{3}}. "
                "ابعتها هنا ونكمّل على طول.",
        "footer": "Eagle Translation",
        "example": ["أحمد", "T-1042", "صورة واضحة للصفحة الأخيرة"],
        "purpose": "Sent when a request is blocked waiting on the client.",
    },
    "order_delivered": {
        "category": "UTILITY",
        "body": "مرحبًا {{1}}، طلب الترجمة رقم {{2}} اتسلّم والملفات موجودة في المحادثة. "
                "لو محتاج أي تعديل رد على الرسالة دي خلال {{3}} من استلامك للملفات.",
        "footer": "Eagle Translation",
        "example": ["أحمد", "T-1042", "48 ساعة"],
        "purpose": "Sent on delivery, and it reopens the 24h window for revisions.",
    },
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
        parser.add_argument("--delete", nargs="+", metavar="NAME",
                            help="Remove templates at Meta by name. WARNING: this "
                                 "BURNS the name for 30 days — to fix a rejected "
                                 "template, rename it here and submit, do not delete.")

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

        if options["delete"]:
            self._delete(base, token, options["delete"])
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
        for name, spec in sorted(TEMPLATES.items()):
            self.stdout.write("")
            self.stdout.write(self.style.SUCCESS(f"  {name}  [{spec['category']}]"))
            self.stdout.write(f"    {spec['purpose']}")
            self.stdout.write(f"    | {spec['body']}")
            self.stdout.write(f"    | -- {spec['footer']}")
            # Show the body as the reviewer will read it — the sample values are
            # what a human at Meta actually judges, not the {{1}} placeholders.
            filled = spec["body"]
            for index, value in enumerate(spec["example"], start=1):
                filled = filled.replace("{{%d}}" % index, value)
            self.stdout.write(f"    as reviewed: {filled}")
        self.stdout.write("")

    def _existing(self, base, token):
        """``{name: status}`` for everything Meta already holds."""
        # `rejected_reason` is the whole point of this read: a template that
        # comes back REJECTED says nothing useful without it, and guessing at
        # the wording instead of asking is how the first round was wasted.
        url = (f"{base}?fields=name,status,category,language,rejected_reason,id"
               f"&limit=200")
        try:
            payload = whatsapp._call(url, token=token)
        except whatsapp.WhatsAppError as exc:
            self.stderr.write(self.style.ERROR(
                f"Could not read existing templates: {exc.raw or exc.message_en}"
            ))
            return {}
        return {
            item.get("name"): item
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
        for name, item in sorted(existing.items()):
            status = item.get("status", "?")
            style = self.style.SUCCESS if status == "APPROVED" else (
                self.style.ERROR if status == "REJECTED" else self.style.WARNING
            )
            here = "" if name in TEMPLATES else "   (not defined in wa_templates.py)"
            self.stdout.write(
                f"    {name:<24} {item.get('language', '?'):<6} "
                + style(status) + here
            )
            reason = item.get("rejected_reason")
            if reason and reason != "NONE":
                self.stdout.write(self.style.ERROR(f"        reason: {reason}"))

        rejected = [n for n, i in existing.items() if i.get("status") == "REJECTED"]
        if rejected:
            self.stdout.write("")
            self.stdout.write(
                "  A rejected name stays taken, so resubmitting under it does\n"
                "  nothing. Do NOT --delete to free it: that burns the name for\n"
                "  30 days. Rename the entry in wa_templates.py and --submit.\n"
                f"    rejected: {', '.join(sorted(rejected))}"
            )

        missing = sorted(set(TEMPLATES) - set(existing))
        if missing:
            self.stdout.write("")
            self.stdout.write(f"  Defined here but not submitted: {', '.join(missing)}")
        self.stdout.write("")

    def _delete(self, base, token, names):
        """Remove a template at Meta — and burn its name for 30 days.

        This is NOT how a rejected template gets another try, which is what it
        looks like and what cost a round here. Meta's own wording:

            "Names of an approved template that has been deleted cannot be
             used again for 30 days."

        Measured, it holds for rejected ones too: three rejected templates were
        deleted, and every resubmission under the same names was refused with a
        bare "Invalid parameter" while an untouched name went through.

        To fix a rejected template, give it a NEW name in TEMPLATES above and
        submit that. Names are internal — no client ever sees one — so renaming
        costs nothing and a deletion costs a month. Use this only to retire a
        template for good.
        """
        self.stdout.write("")
        self.stdout.write(self.style.WARNING(
            "  Deleting burns each name for 30 days. To fix a rejected template,\n"
            "  rename it in wa_templates.py and --submit instead."
        ))
        for name in names:
            url = f"{base}?name={urllib.parse.quote(name)}"
            try:
                whatsapp._call(url, token=token, method="DELETE")
            except whatsapp.WhatsAppError as exc:
                self.stdout.write(self.style.ERROR(f"  {name:<24} not deleted"))
                self.stdout.write(f"      {exc.raw or exc.message_en}")
                continue
            self.stdout.write(self.style.SUCCESS(f"  {name:<24} deleted"))
        self.stdout.write("")
        self.stdout.write("  Now re-run with --submit to send the fixed version.")
        self.stdout.write("")

    def _submit(self, base, token, wanted, existing):
        self.stdout.write("")
        for name in wanted:
            if name in existing:
                status = existing[name].get("status", "?")
                hint = "  — --delete it first" if status == "REJECTED" else ""
                self.stdout.write(self.style.WARNING(
                    f"  {name:<24} already at Meta ({status}) — skipped{hint}"
                ))
                continue

            spec = TEMPLATES[name]
            body = {"type": "BODY", "text": spec["body"]}
            if spec.get("example"):
                body["example"] = {"body_text": [spec["example"]]}
            payload = {
                "name": name,
                "language": LANGUAGE,
                "category": spec["category"],
                "components": [body, {"type": "FOOTER", "text": spec["footer"]}],
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
