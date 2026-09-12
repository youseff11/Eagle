"""Bunny.net Edge Storage backend for Django's file storage API.

Uploaded files (client documents, chat attachments) go to a Bunny storage zone
and are served from the pull zone / CDN. Activated automatically when the Bunny
settings are present; otherwise Django keeps using the local ``media/`` folder,
so local development is untouched.

Docs: https://bunny.net/docs/storage/http
"""

import posixpath
import urllib.error
import urllib.parse
import urllib.request
import uuid

from django.contrib.staticfiles.storage import ManifestStaticFilesStorage
from django.core.exceptions import ImproperlyConfigured
from django.core.files.base import ContentFile
from django.core.files.storage import Storage
from django.utils.deconstruct import deconstructible

from . import net

#: Frankfurt is the default zone and has no region prefix.
DEFAULT_HOST = "storage.bunnycdn.com"
DEFAULT_REGIONS = ("", "de", "falkenstein", "frankfurt")


class BunnyError(IOError):
    pass


@deconstructible
class BunnyStorage(Storage):
    """Minimal, dependency-free Bunny Edge Storage backend."""

    def __init__(self, zone=None, key=None, region=None, cdn_url=None, timeout=90):
        from django.conf import settings

        config = getattr(settings, "BUNNY", {}) or {}
        self.zone = (zone or config.get("STORAGE_ZONE") or "").strip()
        self.key = (key or config.get("API_KEY") or "").strip()
        self.region = (region or config.get("REGION") or "").strip().lower()
        self.cdn_url = (cdn_url or config.get("CDN_URL") or "").strip().rstrip("/")
        self.timeout = timeout

        missing = [
            name for name, value in (
                ("BUNNY_STORAGE_ZONE_NAME", self.zone),
                ("BUNNY_API_KEY", self.key),
                ("BUNNY_CDN_URL", self.cdn_url),
            ) if not value
        ]
        if missing:
            raise ImproperlyConfigured(
                "BunnyStorage is missing: " + ", ".join(missing)
            )

    # -- plumbing ----------------------------------------------------------
    @property
    def host(self):
        if self.region in DEFAULT_REGIONS:
            return DEFAULT_HOST
        return f"{self.region}.{DEFAULT_HOST}"

    @staticmethod
    def _clean(name):
        return str(name).replace("\\", "/").lstrip("/")

    def _endpoint(self, name):
        path = urllib.parse.quote(self._clean(name))
        return f"https://{self.host}/{self.zone}/{path}"

    def _request(self, name, method="GET", data=None, expect=(200, 201)):
        request = urllib.request.Request(self._endpoint(name), data=data, method=method)
        request.add_header("AccessKey", self.key)
        request.add_header("Accept", "application/json")
        if data is not None:
            request.add_header("Content-Type", "application/octet-stream")
        try:
            with net.urlopen(request, timeout=self.timeout) as response:
                if response.status not in expect:
                    raise BunnyError(f"Bunny {method} {name} returned {response.status}")
                return response.status, response.read(), dict(response.headers)
        except urllib.error.HTTPError as exc:
            detail = exc.read().decode("utf-8", errors="ignore")[:200]
            raise BunnyError(f"Bunny {method} {name} failed ({exc.code}): {detail}")
        except urllib.error.URLError as exc:
            raise BunnyError(f"Cannot reach Bunny storage: {exc.reason}")

    # -- Django Storage API ------------------------------------------------
    def get_available_name(self, name, max_length=None):
        """Make every upload unique instead of round-tripping to check.

        Two clients can easily send ``contract.pdf`` in the same month, and a
        remote existence check per save is both slow and racy.
        """
        directory, filename = posixpath.split(self._clean(name))
        stem, dot, extension = filename.rpartition(".")
        suffix = uuid.uuid4().hex[:8]
        if dot:
            filename = f"{stem}-{suffix}.{extension}"
        else:
            filename = f"{filename}-{suffix}"
        candidate = posixpath.join(directory, filename) if directory else filename
        if max_length and len(candidate) > max_length:
            keep = max_length - len(suffix) - len(extension) - 2
            candidate = f"{candidate[:max(keep, 1)]}-{suffix}.{extension}" if dot else candidate[:max_length]
        return candidate

    def _save(self, name, content):
        name = self._clean(name)
        if hasattr(content, "seek"):
            try:
                content.seek(0)
            except (OSError, ValueError):
                pass
        self._request(name, method="PUT", data=content.read(), expect=(200, 201))
        return name

    def _open(self, name, mode="rb"):
        if "w" in mode:
            raise BunnyError("BunnyStorage files are write-once; save a new file instead.")
        _status, body, _headers = self._request(name, method="GET", expect=(200,))
        return ContentFile(body, name=posixpath.basename(self._clean(name)))

    def delete(self, name):
        try:
            self._request(name, method="DELETE", expect=(200,))
        except BunnyError:
            # Deleting something already gone must not blow up a cascade.
            pass

    def exists(self, name):
        try:
            self._request(name, method="HEAD", expect=(200,))
            return True
        except BunnyError:
            return False

    def size(self, name):
        try:
            _status, _body, headers = self._request(name, method="HEAD", expect=(200,))
            return int(headers.get("Content-Length", 0))
        except (BunnyError, TypeError, ValueError):
            return 0

    def url(self, name):
        return f"{self.cdn_url}/{urllib.parse.quote(self._clean(name))}"

    def listdir(self, path):
        path = self._clean(path)
        if path and not path.endswith("/"):
            path += "/"
        import json

        _status, body, _headers = self._request(path, method="GET", expect=(200,))
        try:
            entries = json.loads(body.decode("utf-8"))
        except (ValueError, UnicodeDecodeError):
            return [], []
        directories = [e["ObjectName"] for e in entries if e.get("IsDirectory")]
        files = [e["ObjectName"] for e in entries if not e.get("IsDirectory")]
        return directories, files


class HashedStaticStorage(ManifestStaticFilesStorage):
    """Static files served under a content-hashed name (``app.4f2c1e9a.css``).

    The hash changes whenever the file's bytes change, so every deploy hands
    browsers and Cloudflare a URL they have never seen — a stale copy of the
    stylesheet can no longer survive at the edge, and no cache purge is needed
    after a deploy.

    ``manifest_strict = False`` keeps the site up if ``collectstatic`` has not
    been run yet: a name missing from the manifest falls back to the plain
    filename instead of raising and taking every page down with it.
    """

    manifest_strict = False
