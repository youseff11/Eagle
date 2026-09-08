"""One-shot health check for a deployment.

    python manage.py check_setup

Reports which backend each part of the stack is actually using and whether the
external services answer. Run it right after a deploy — it is much faster than
discovering a bad key when a client message arrives.
"""

from django.conf import settings
from django.core.files.base import ContentFile
from django.core.files.storage import default_storage
from django.core.management.base import BaseCommand
from django.db import connection

from dashboard.models import AppSettings

OK = "  OK   "
BAD = " FAIL  "
SKIP = " SKIP  "


class Command(BaseCommand):
    help = "Check database, file storage, WhatsApp and e-mail configuration."

    def add_arguments(self, parser):
        parser.add_argument(
            "--write", action="store_true",
            help="Also upload and delete a small test file in the storage backend.",
        )

    def line(self, status, label, detail=""):
        style = self.style.SUCCESS if status == OK else (
            self.style.ERROR if status == BAD else self.style.WARNING
        )
        self.stdout.write(f"[{style(status)}] {label}" + (f" — {detail}" if detail else ""))

    def handle(self, *args, **options):
        self.stdout.write("")
        self.stdout.write(self.style.MIGRATE_HEADING("Eagle deployment check"))
        self.stdout.write("")

        self.stdout.write(f"  DEBUG           : {settings.DEBUG}")
        self.stdout.write(f"  ALLOWED_HOSTS   : {settings.ALLOWED_HOSTS or '(empty)'}")
        self.stdout.write(f"  CSRF origins    : {settings.CSRF_TRUSTED_ORIGINS or '(empty)'}")
        self.stdout.write("")

        self._check_database()
        self._check_storage(options["write"])
        self._check_whatsapp()
        self._check_email()
        self.stdout.write("")

    # ------------------------------------------------------------------
    def _check_database(self):
        engine = settings.DATABASES["default"]["ENGINE"].rsplit(".", 1)[-1]
        host = settings.DATABASES["default"].get("HOST") or "local file"
        try:
            with connection.cursor() as cursor:
                cursor.execute("SELECT 1")
                cursor.fetchone()
            self.line(OK, f"Database ({engine})", host)
        except Exception as exc:  # noqa: BLE001
            self.line(BAD, f"Database ({engine})", str(exc)[:180])

    def _check_storage(self, do_write):
        backend = settings.STORAGES["default"]["BACKEND"].rsplit(".", 1)[-1]
        if not getattr(settings, "USE_BUNNY", False):
            self.line(SKIP, f"File storage ({backend})", "local media/ folder — Bunny not configured")
            return

        detail = f"zone={settings.BUNNY['STORAGE_ZONE']} cdn={settings.BUNNY['CDN_URL']}"
        if not do_write:
            self.line(OK, f"File storage ({backend})", detail + "  (add --write to test an upload)")
            return
        try:
            name = default_storage.save("healthcheck/ping.txt", ContentFile(b"eagle ok"))
            url = default_storage.url(name)
            default_storage.delete(name)
            self.line(OK, f"File storage ({backend})", f"upload+delete fine — {url}")
        except Exception as exc:  # noqa: BLE001
            self.line(BAD, f"File storage ({backend})", str(exc)[:180])

    def _check_whatsapp(self):
        from dashboard import whatsapp

        conf = AppSettings.load()
        if not (conf.whatsapp_access_token and conf.whatsapp_phone_number_id):
            self.line(SKIP, "WhatsApp", "no credentials in /panel/settings/")
            return
        report = whatsapp.check_connection()
        if report["ok"]:
            self.line(OK, "WhatsApp", f"{report['name']} {report['number']} ({report['quality']})")
        else:
            self.line(BAD, "WhatsApp", report["error_en"][:180])

    def _check_email(self):
        from dashboard import mailer

        conf = AppSettings.load()
        if not mailer.is_configured(conf):
            self.line(SKIP, "E-mail (SMTP)", "not configured in /panel/settings/")
            return
        report = mailer.check_connection(conf)
        if report["ok"]:
            self.line(OK, "E-mail (SMTP)", f"{report['host']} as {report['user']}")
        else:
            self.line(BAD, "E-mail (SMTP)", report["error_en"][:180])
