"""Django settings for Core (Eagle Dashboard).

One file, two environments:

* **Local**  — nothing configured, so SQLite + the local ``media/`` folder.
* **Server** — set ``DATABASE_URL`` and the ``BUNNY_*`` variables and the same
  code switches to Neon PostgreSQL and Bunny.net storage. No separate settings
  module, no code change.

Every value is read from the environment (or a ``.env`` file next to
manage.py). Both the ``EAGLE_``-prefixed names and the plain ones are accepted.
"""

import os
import urllib.parse
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent


# ---------------------------------------------------------------------------
# Environment helpers (no third-party packages)
# ---------------------------------------------------------------------------

def _load_env(path):
    """Minimal .env reader. Real environment variables always win.

    Returns the number of keys read, or ``None`` when the file is absent —
    ``check_setup`` reports this, because a missing .env silently sends the
    whole project back to its local defaults.
    """
    if not path.exists():
        return None
    count = 0
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        os.environ.setdefault(key.strip(), value.strip().strip('"').strip("'"))
        count += 1
    return count


ENV_FILE = BASE_DIR / ".env"
ENV_FILE_KEYS = _load_env(ENV_FILE)


def env(*names, default=""):
    """First non-empty value among ``names``."""
    for name in names:
        value = os.environ.get(name)
        if value not in (None, ""):
            return value.strip()
    return default


def env_bool(*names, default=False):
    value = env(*names, default="").lower()
    if not value:
        return default
    return value in ("1", "true", "yes", "on")


def env_list(*names, default=""):
    return [item.strip() for item in env(*names, default=default).split(",") if item.strip()]


# ---------------------------------------------------------------------------
# Core
# ---------------------------------------------------------------------------

SECRET_KEY = env(
    "EAGLE_SECRET_KEY", "SECRET_KEY",
    default="django-insecure-%3+irrxs4*-kz$q8*o6y90=274x0-^2a-ojpyf+i*nps#%=pun",
)

DEBUG = env_bool("EAGLE_DEBUG", "DEBUG", default=True)

ALLOWED_HOSTS = env_list("EAGLE_HOSTS", "ALLOWED_HOSTS")
if DEBUG and not ALLOWED_HOSTS:
    ALLOWED_HOSTS = ["*"]

# Django needs the scheme-qualified origin for POSTs over HTTPS. Derive it from
# ALLOWED_HOSTS so a deploy does not silently break every form.
CSRF_TRUSTED_ORIGINS = env_list("EAGLE_CSRF_ORIGINS", "CSRF_TRUSTED_ORIGINS")
if not CSRF_TRUSTED_ORIGINS:
    CSRF_TRUSTED_ORIGINS = [
        f"https://{host.lower()}" for host in ALLOWED_HOSTS
        if host not in ("*", "localhost", "127.0.0.1", "0.0.0.0")
    ]

if not DEBUG:
    # PythonAnywhere (and most PaaS) terminate TLS in front of the app.
    SECURE_PROXY_SSL_HEADER = ("HTTP_X_FORWARDED_PROTO", "https")
    SESSION_COOKIE_SECURE = True
    CSRF_COOKIE_SECURE = True
    X_FRAME_OPTIONS = "DENY"


# ---------------------------------------------------------------------------
# Applications
# ---------------------------------------------------------------------------

INSTALLED_APPS = [
    "django.contrib.admin",
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "django.contrib.staticfiles",
    "dashboard",
]

MIDDLEWARE = [
    "django.middleware.security.SecurityMiddleware",
    "django.contrib.sessions.middleware.SessionMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    "django.contrib.messages.middleware.MessageMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
]

ROOT_URLCONF = "Core.urls"

TEMPLATES = [
    {
        "BACKEND": "django.template.backends.django.DjangoTemplates",
        "DIRS": [BASE_DIR / "templates"],
        "APP_DIRS": True,
        "OPTIONS": {
            "context_processors": [
                "django.template.context_processors.request",
                "django.contrib.auth.context_processors.auth",
                "django.contrib.messages.context_processors.messages",
                "dashboard.context_processors.eagle",
            ],
        },
    },
]

WSGI_APPLICATION = "Core.wsgi.application"
ASGI_APPLICATION = "Core.asgi.application"


# ---------------------------------------------------------------------------
# Database — DATABASE_URL (Neon/Postgres) when present, otherwise SQLite
# ---------------------------------------------------------------------------

#: libpq parameters we forward from the URL's query string.
_PG_OPTION_KEYS = (
    "sslmode", "channel_binding", "sslrootcert", "sslcert", "sslkey",
    "application_name", "connect_timeout", "options", "target_session_attrs",
)


def database_from_url(url):
    """Parse a ``postgres://user:pass@host:port/name?sslmode=require`` URL."""
    parsed = urllib.parse.urlparse(url)
    if parsed.scheme not in ("postgres", "postgresql", "psql"):
        raise ValueError(f"Unsupported DATABASE_URL scheme: {parsed.scheme!r}")

    query = dict(urllib.parse.parse_qsl(parsed.query))
    options = {key: query[key] for key in _PG_OPTION_KEYS if key in query}
    options.setdefault("sslmode", "require")  # Neon always needs TLS

    return {
        "ENGINE": "django.db.backends.postgresql",
        "NAME": urllib.parse.unquote(parsed.path.lstrip("/")),
        "USER": urllib.parse.unquote(parsed.username or ""),
        "PASSWORD": urllib.parse.unquote(parsed.password or ""),
        "HOST": parsed.hostname or "",
        "PORT": str(parsed.port or ""),
        "OPTIONS": options,
        # Neon's pooler is happy with reused connections; health checks keep a
        # dropped one from surfacing as a 500.
        "CONN_MAX_AGE": int(env("EAGLE_CONN_MAX_AGE", default="60")),
        "CONN_HEALTH_CHECKS": True,
    }


DATABASE_URL = env("DATABASE_URL", "EAGLE_DATABASE_URL")

if DATABASE_URL:
    DATABASES = {"default": database_from_url(DATABASE_URL)}
else:
    DATABASES = {
        "default": {
            "ENGINE": "django.db.backends.sqlite3",
            "NAME": BASE_DIR / "db.sqlite3",
        }
    }


# ---------------------------------------------------------------------------
# Authentication
# ---------------------------------------------------------------------------

AUTH_USER_MODEL = "dashboard.User"

LOGIN_URL = "/login/"
LOGIN_REDIRECT_URL = "/"
LOGOUT_REDIRECT_URL = "/login/"

AUTH_PASSWORD_VALIDATORS = [
    {"NAME": "django.contrib.auth.password_validation.UserAttributeSimilarityValidator"},
    {"NAME": "django.contrib.auth.password_validation.MinimumLengthValidator"},
    {"NAME": "django.contrib.auth.password_validation.CommonPasswordValidator"},
    {"NAME": "django.contrib.auth.password_validation.NumericPasswordValidator"},
]


# ---------------------------------------------------------------------------
# Internationalization — UI translation lives in the HTML (data-ar / data-en)
# ---------------------------------------------------------------------------

LANGUAGE_CODE = "en-us"
TIME_ZONE = env("EAGLE_TIME_ZONE", "TIME_ZONE", default="Africa/Cairo")
USE_I18N = True
USE_TZ = True


# ---------------------------------------------------------------------------
# Static & media — Bunny.net for uploads when configured, local disk otherwise
# ---------------------------------------------------------------------------

STATIC_URL = "static/"
STATICFILES_DIRS = [BASE_DIR / "static"]
STATIC_ROOT = BASE_DIR / "staticfiles"

MEDIA_URL = "media/"
MEDIA_ROOT = BASE_DIR / "media"

BUNNY = {
    "STORAGE_ZONE": env("BUNNY_STORAGE_ZONE_NAME", "BUNNY_STORAGE_ZONE"),
    "API_KEY": env("BUNNY_API_KEY", "BUNNY_STORAGE_PASSWORD"),
    "REGION": env("BUNNY_REGION"),
    "CDN_URL": env("BUNNY_CDN_URL"),
}
USE_BUNNY = all(BUNNY[key] for key in ("STORAGE_ZONE", "API_KEY", "CDN_URL"))

STORAGES = {
    "default": (
        {"BACKEND": "dashboard.storages.BunnyStorage"}
        if USE_BUNNY else
        {"BACKEND": "django.core.files.storage.FileSystemStorage"}
    ),
    # In production, content-hashed names (``app.4f2c1e9a.css``) so a deploy
    # always produces a URL Cloudflare has never seen and the edge can never
    # keep serving yesterday's stylesheet. Under DEBUG the dev server serves
    # files straight from ``static/`` by their plain names, so hashing there
    # would just 404.
    "staticfiles": {
        "BACKEND": (
            "django.contrib.staticfiles.storage.StaticFilesStorage"
            if DEBUG else
            "dashboard.storages.HashedStaticStorage"
        )
    },
}

DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"

FILE_UPLOAD_MAX_MEMORY_SIZE = 10 * 1024 * 1024
DATA_UPLOAD_MAX_MEMORY_SIZE = 64 * 1024 * 1024


# ---------------------------------------------------------------------------
# Logging — keep integration failures visible in the server log
# ---------------------------------------------------------------------------

LOGGING = {
    "version": 1,
    "disable_existing_loggers": False,
    "handlers": {"console": {"class": "logging.StreamHandler"}},
    "loggers": {
        "dashboard": {"handlers": ["console"], "level": env("EAGLE_LOG_LEVEL", default="INFO")},
    },
}


# ---------------------------------------------------------------------------
# Eagle workflow defaults (overridable at runtime from the admin panel)
# ---------------------------------------------------------------------------

EAGLE = {
    # Seconds an assignee has to confirm an assignment.
    "RESPONSE_WINDOW_SECONDS": 60,
    # Minutes before the deadline a warning is pushed to the translator.
    "DEADLINE_WARNING_MINUTES": 15,
    # Rating penalty applied when an assignment expires (1/8 of a star).
    "PENALTY": "0.125",
    "MAX_RATING": "5.000",
    # Words that make an inbound message invisible to the operation role.
    "RATE_KEYWORDS": "rate,rates,rating,ratings,ريت,الريت,سعر,الاسعار",
    # Front-end polling interval (ms).
    "POLL_MS": 3000,
}
