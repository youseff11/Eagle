"""THROWAWAY settings for a browser pass on a local copy (database and files live in the scratchpad). Deleted after the pass."""
from .settings import *  # noqa: F401,F403

DEBUG = True
ALLOWED_HOSTS = ["localhost", "127.0.0.1"]
_SCRATCH = r"C:\Users\JOO\AppData\Local\Temp\claude\D--Progects-Eagle-Core\1dfbec8b-0e19-4597-a490-072a38914ceb\scratchpad"
DATABASES = {"default": {"ENGINE": "django.db.backends.sqlite3", "NAME": _SCRATCH + r"\browser2.sqlite3"}}
MEDIA_ROOT = _SCRATCH + r"\browser_media"
