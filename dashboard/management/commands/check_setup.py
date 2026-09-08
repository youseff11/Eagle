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
from django.db.migrations.executor import MigrationExecutor

OK = "  OK   "
BAD = " FAIL  "
SKIP = " SKIP  "
WARN = " TODO  "


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

    def safely(self, label, func, *args):
        """Never let one broken check hide the rest of the report."""
        try:
            return func(*args)
        except Exception as exc:  # noqa: BLE001
            self.line(BAD, label, f"{type(exc).__name__}: {exc}".replace("\n", " ")[:200])
            return None

    def handle(self, *args, **options):
        self.stdout.write("")
        self.stdout.write(self.style.MIGRATE_HEADING("Eagle deployment check"))
        self.stdout.write("")

        env_file = getattr(settings, "ENV_FILE", None)
        env_keys = getattr(settings, "ENV_FILE_KEYS", None)
        if env_file is not None:
            found = f"{env_keys} keys" if env_keys else "NOT FOUND — using defaults"
            self.stdout.write(f"  .env            : {env_file}  ({found})")
        self.stdout.write(f"  DEBUG           : {settings.DEBUG}")
        self.stdout.write(f"  ALLOWED_HOSTS   : {settings.ALLOWED_HOSTS or '(empty)'}")
        self.stdout.write(f"  CSRF origins    : {settings.CSRF_TRUSTED_ORIGINS or '(empty)'}")
        self.stdout.write("")

        db_ok = self.safely("Database", self._check_database)
        migrated = self.safely("Migrations", self._check_migrations) if db_ok else None
        self.safely("File storage", self._check_storage, options["write"])

        if migrated:
            self.safely("WhatsApp", self._check_whatsapp)
            self.safely("E-mail (SMTP)", self._check_email)
        else:
            self.line(SKIP, "WhatsApp", "needs the database tables first")
            self.line(SKIP, "E-mail (SMTP)", "needs the database tables first")
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
            return True
        except Exception as exc:  # noqa: BLE001
            self.line(BAD, f"Database ({engine})", str(exc)[:180])
            return False

    def _check_migrations(self):
        """A fresh Postgres database has no tables until `migrate` is run."""
        executor = MigrationExecutor(connection)
        pending = executor.migration_plan(executor.loader.graph.leaf_nodes())
        if not pending:
            self.line(OK, "Migrations", "database schema is up to date")
            return True
        names = ", ".join(f"{m.app_label}.{m.name}" for m, _ in pending[:4])
        more = f" (+{len(pending) - 4} more)" if len(pending) > 4 else ""
        self.line(
            WARN, f"Migrations — {len(pending)} not applied",
            f"run:  python manage.py migrate   [{names}{more}]",
        )
        return False

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
        from dashboard.models import AppSettings

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
        from dashboard.models import AppSettings

        conf = AppSettings.load()
        if not mailer.is_configured(conf):
            self.line(SKIP, "E-mail (SMTP)", "not configured in /panel/settings/")
            return
        report = mailer.check_connection(conf)
        if report["ok"]:
            self.line(OK, "E-mail (SMTP)", f"{report['host']} as {report['user']}")
        else:
            self.line(BAD, "E-mail (SMTP)", report["error_en"][:180])
