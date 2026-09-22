"""Settings for a fast test run on the machine — nothing else.

``python manage.py test dashboard`` with the real settings pays four costs
before a single assertion runs: it builds a test database (on Neon, over the
internet, when ``DATABASE_URL`` is set), replays all seventeen migrations into
it, hashes every test password with the production hasher, and — if the Bunny
keys are in ``.env`` — uploads every file a test writes to the CDN.

None of the four tells you anything about the code you just changed, so this
file takes all four out:

    python manage.py test dashboard --settings=Core.settings_test

What it does NOT cover, and what the run before a deploy is for:

* the migrations are not replayed here, so a migration that does not match
  ``models.py`` still passes. ``makemigrations --check`` is what catches that.
* Postgres is not exercised. SQLite is more forgiving about some queries.

So: this one while you work, the real one before you push.

    python manage.py test dashboard
    python manage.py makemigrations --check --dry-run
"""

from .settings import *  # noqa: F401,F403
from .settings import BASE_DIR


# The database lives in RAM and dies with the process. Nothing to create, drop
# or reach over the network.
DATABASES = {
    "default": {
        "ENGINE": "django.db.backends.sqlite3",
        "NAME": ":memory:",
    }
}


class _SkipMigrations:
    """``None`` for every app: Django builds the tables from the models.

    Seventeen migrations replayed per run, for tables the models already
    describe. The models are what the tests talk to.
    """

    def __contains__(self, item):
        return True

    def __getitem__(self, item):
        return None


MIGRATION_MODULES = _SkipMigrations()


# Every ``create_user`` in the suite hashes a password. The production hasher
# is slow on purpose; here it is only slow.
PASSWORD_HASHERS = ["django.contrib.auth.hashers.MD5PasswordHasher"]


# A test that saves an attachment must not reach Bunny, and must not drop
# anything into media/ either. This folder is throwaway - it is in .gitignore.
STORAGES = {
    "default": {"BACKEND": "django.core.files.storage.FileSystemStorage"},
    "staticfiles": {"BACKEND": "django.contrib.staticfiles.storage.StaticFilesStorage"},
}
MEDIA_ROOT = BASE_DIR / ".test-media"

# No SMTP connection: django.core.mail collects the letters in memory, which is
# also what the mail tests read.
EMAIL_BACKEND = "django.core.mail.backends.locmem.EmailBackend"

# A failing test should print its assertion, not a wall of warnings.
import logging  # noqa: E402

logging.disable(logging.CRITICAL)
