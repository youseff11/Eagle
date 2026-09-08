"""
Django settings for Core project (Eagle Dashboard).

Phase 1 - Translation workflow dashboard.
"""

import os
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent


def _load_env(path):
    """Minimal .env reader so the project stays dependency-free.

    Real environment variables always win over the file.
    """
    if not path.exists():
        return
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        os.environ.setdefault(key.strip(), value.strip().strip('"').strip("'"))


_load_env(BASE_DIR / ".env")


# SECURITY WARNING: keep the secret key used in production secret!
SECRET_KEY = os.environ.get(
    "EAGLE_SECRET_KEY",
    "django-insecure-%3+irrxs4*-kz$q8*o6y90=274x0-^2a-ojpyf+i*nps#%=pun",
)

DEBUG = os.environ.get("EAGLE_DEBUG", "1") == "1"

ALLOWED_HOSTS = ["*"] if DEBUG else os.environ.get("EAGLE_HOSTS", "").split(",")

CSRF_TRUSTED_ORIGINS = [
    o for o in os.environ.get("EAGLE_CSRF_ORIGINS", "").split(",") if o
]


# Application definition

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


# Database

DATABASES = {
    "default": {
        "ENGINE": "django.db.backends.sqlite3",
        "NAME": BASE_DIR / "db.sqlite3",
    }
}


# Authentication

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


# Internationalization
# UI translation is handled inside the HTML (data-ar / data-en attributes).

LANGUAGE_CODE = "en-us"
TIME_ZONE = "Africa/Cairo"
USE_I18N = True
USE_TZ = True


# Static & media files

STATIC_URL = "static/"
STATICFILES_DIRS = [BASE_DIR / "static"]
STATIC_ROOT = BASE_DIR / "staticfiles"

MEDIA_URL = "media/"
MEDIA_ROOT = BASE_DIR / "media"

DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"

FILE_UPLOAD_MAX_MEMORY_SIZE = 10 * 1024 * 1024
DATA_UPLOAD_MAX_MEMORY_SIZE = 64 * 1024 * 1024


# Email

MAILERS = {
    "default": {
        "BACKEND": "django.core.mail.backends.console.EmailBackend",
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
