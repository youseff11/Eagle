"""WhatsApp Cloud API client (Meta Graph API).

Everything here is stdlib only — no extra packages to install. Credentials come
from :class:`AppSettings`, so the integration starts working the moment the
admin fills them in at /panel/settings/ (no code change, no restart).
"""

import hashlib
import hmac
import json
import mimetypes
import re
import urllib.error
import urllib.request
import uuid

from .models import AppSettings

GRAPH_HOST = "https://graph.facebook.com"
DEFAULT_VERSION = "v21.0"
TIMEOUT = 60
USER_AGENT = "EagleDashboard/1.0"

#: Meta error codes we can explain in plain language.
ERROR_HINTS = {
    190: ("التوكن غلط أو منتهي — اعمل واحد جديد من Meta.",
          "The access token is invalid or expired — generate a new one in Meta."),
    100: ("Phone number ID غلط أو ناقص، أو الصلاحيات مش مظبوطة.",
          "Wrong/missing Phone number ID, or the token is missing permissions."),
    131047: ("فات أكتر من 24 ساعة على آخر رسالة من العميل. واتساب مش بيسمح تبعتله "
             "رسالة حرة بعد كده — لازم العميل يبعتلك رسالة الأول، أو تستخدم Message Template معتمد.",
             "More than 24h since the client's last message. WhatsApp only allows an "
             "approved template outside that window."),
    131026: ("الرقم ده مش مسجل على واتساب.", "That number is not on WhatsApp."),
    133010: ("الرقم مش مسجل على واتساب.", "That number is not registered on WhatsApp."),
    131051: ("نوع الرسالة ده مش مدعوم.", "Unsupported message type."),
    131056: ("بعت رسايل كتير للرقم ده في وقت قصير — استنى شوية.",
             "Too many messages to this number in a short window."),
}


class WhatsAppError(Exception):
    """Raised for any Graph API failure; carries a human-readable message."""

    def __init__(self, message_ar, message_en="", code=None, raw=""):
        super().__init__(message_ar)
        self.message_ar = message_ar
        self.message_en = message_en or message_ar
        self.code = code
        self.raw = raw


# ---------------------------------------------------------------------------
# Low-level plumbing
# ---------------------------------------------------------------------------

def _conf():
    return AppSettings.load()


def _version(conf):
    return (conf.whatsapp_api_version or DEFAULT_VERSION).strip()


def _require(conf):
    if not conf.whatsapp_access_token:
        raise WhatsAppError("مفيش Access token في الإعدادات.", "No access token configured.")
    if not conf.whatsapp_phone_number_id:
        raise WhatsAppError("مفيش Phone number ID في الإعدادات.", "No phone number ID configured.")


def _raise_from_body(status, body):
    try:
        payload = json.loads(body)
        err = payload.get("error", {}) or {}
        code = err.get("code")
        detail = (err.get("error_data") or {}).get("details") or err.get("message") or body
    except (ValueError, AttributeError):
        code, detail = None, body[:400]

    hint_ar, hint_en = ERROR_HINTS.get(code, ("", ""))
    message_ar = hint_ar or f"واتساب رجّع خطأ ({status}): {detail}"
    message_en = hint_en or f"WhatsApp returned an error ({status}): {detail}"
    raise WhatsAppError(message_ar, message_en, code=code, raw=str(detail)[:500])


def _call(url, *, token, data=None, headers=None, method="GET", raw_response=False):
    request = urllib.request.Request(url, data=data, method=method)
    request.add_header("Authorization", f"Bearer {token}")
    request.add_header("User-Agent", USER_AGENT)
    for key, value in (headers or {}).items():
        request.add_header(key, value)
    try:
        with urllib.request.urlopen(request, timeout=TIMEOUT) as response:
            body = response.read()
    except urllib.error.HTTPError as exc:
        _raise_from_body(exc.code, exc.read().decode("utf-8", errors="ignore"))
    except urllib.error.URLError as exc:
        raise WhatsAppError(
            f"مش قادر أوصل لسيرفر واتساب: {exc.reason}",
            f"Cannot reach the WhatsApp servers: {exc.reason}",
        )
    if raw_response:
        return body
    try:
        return json.loads(body.decode("utf-8"))
    except ValueError:
        return {}


def _multipart(fields, filename, content, mime):
    """Build a multipart/form-data body without pulling in `requests`."""
    boundary = "EagleBoundary" + uuid.uuid4().hex
    safe_name = re.sub(r'[^A-Za-z0-9._-]', "_", filename) or "file"
    parts = []
    for key, value in fields.items():
        parts.append(
            f'--{boundary}\r\nContent-Disposition: form-data; name="{key}"\r\n\r\n{value}\r\n'
            .encode("utf-8")
        )
    parts.append(
        f'--{boundary}\r\nContent-Disposition: form-data; name="file"; filename="{safe_name}"\r\n'
        f"Content-Type: {mime}\r\n\r\n".encode("utf-8")
    )
    parts.append(content)
    parts.append(f"\r\n--{boundary}--\r\n".encode("utf-8"))
    return b"".join(parts), f"multipart/form-data; boundary={boundary}"


def normalize_number(value):
    """WhatsApp wants digits only, in international format."""
    return "".join(ch for ch in str(value or "") if ch.isdigit())


def guess_mime(filename, fallback="application/octet-stream"):
    return mimetypes.guess_type(filename or "")[0] or fallback


def media_kind(mime):
    """Which WhatsApp message type suits this file."""
    mime = (mime or "").lower()
    if mime in ("image/jpeg", "image/png"):
        return "image"
    if mime in ("video/mp4", "video/3gpp"):
        return "video"
    if mime in ("audio/aac", "audio/mp4", "audio/mpeg", "audio/amr", "audio/ogg"):
        return "audio"
    return "document"


# ---------------------------------------------------------------------------
# Inbound: download the media the client sent us
# ---------------------------------------------------------------------------

def fetch_media(media_id):
    """Return ``(bytes, filename, mime)`` for an inbound media id."""
    conf = _conf()
    _require(conf)
    token = conf.whatsapp_access_token

    meta = _call(f"{GRAPH_HOST}/{_version(conf)}/{media_id}", token=token)
    url = meta.get("url")
    if not url:
        raise WhatsAppError("واتساب مرجّعش رابط للملف.", "WhatsApp returned no media URL.")

    mime = meta.get("mime_type", "application/octet-stream").split(";")[0].strip()
    content = _call(url, token=token, raw_response=True)

    extension = mimetypes.guess_extension(mime) or ".bin"
    return content, f"{media_id}{extension}", mime


# ---------------------------------------------------------------------------
# Outbound: send text and files to the client
# ---------------------------------------------------------------------------

def _send(payload):
    conf = _conf()
    _require(conf)
    url = f"{GRAPH_HOST}/{_version(conf)}/{conf.whatsapp_phone_number_id}/messages"
    body = json.dumps(payload).encode("utf-8")
    result = _call(
        url, token=conf.whatsapp_access_token, data=body,
        headers={"Content-Type": "application/json"}, method="POST",
    )
    messages = result.get("messages") or [{}]
    return messages[0].get("id", "")


def send_text(to, body):
    return _send({
        "messaging_product": "whatsapp",
        "recipient_type": "individual",
        "to": normalize_number(to),
        "type": "text",
        "text": {"preview_url": False, "body": body[:4000]},
    })


def upload_media(content, filename, mime):
    """Upload bytes to Meta and return the media id used when sending."""
    conf = _conf()
    _require(conf)
    url = f"{GRAPH_HOST}/{_version(conf)}/{conf.whatsapp_phone_number_id}/media"
    data, content_type = _multipart(
        {"messaging_product": "whatsapp", "type": mime}, filename, content, mime
    )
    result = _call(
        url, token=conf.whatsapp_access_token, data=data,
        headers={"Content-Type": content_type}, method="POST",
    )
    media_id = result.get("id")
    if not media_id:
        raise WhatsAppError("رفع الملف فشل.", "Media upload failed.")
    return media_id


def send_file(to, content, filename, mime=None, caption=""):
    """Upload then send one file. Returns the WhatsApp message id."""
    mime = mime or guess_mime(filename)
    kind = media_kind(mime)
    media_id = upload_media(content, filename, mime)

    block = {"id": media_id}
    if kind == "document":
        block["filename"] = filename
    if caption and kind in ("document", "image", "video"):
        block["caption"] = caption[:1000]

    return _send({
        "messaging_product": "whatsapp",
        "recipient_type": "individual",
        "to": normalize_number(to),
        "type": kind,
        kind: block,
    })


def mark_read(message_id):
    """Best-effort read receipt; never raises."""
    try:
        _send({"messaging_product": "whatsapp", "status": "read", "message_id": message_id})
    except WhatsAppError:
        pass


# ---------------------------------------------------------------------------
# Webhook signature
# ---------------------------------------------------------------------------

def verify_signature(app_secret, raw_body, header_value):
    """Validate Meta's ``X-Hub-Signature-256`` header."""
    if not app_secret:
        return True  # verification not configured
    if not header_value or not header_value.startswith("sha256="):
        return False
    expected = hmac.new(app_secret.encode("utf-8"), raw_body, hashlib.sha256).hexdigest()
    return hmac.compare_digest(expected, header_value[7:])


# ---------------------------------------------------------------------------
# Connection test (used by the button in the admin panel)
# ---------------------------------------------------------------------------

def check_connection(test_number=""):
    """Verify the credentials and optionally send a test message."""
    conf = _conf()
    report = {
        "ok": False,
        "token": bool(conf.whatsapp_access_token),
        "phone_id": bool(conf.whatsapp_phone_number_id),
        "verify_token": bool(conf.whatsapp_verify_token),
        "app_secret": bool(conf.whatsapp_app_secret),
        "number": "",
        "name": "",
        "quality": "",
        "sent": False,
        "error_ar": "",
        "error_en": "",
    }
    try:
        _require(conf)
        info = _call(
            f"{GRAPH_HOST}/{_version(conf)}/{conf.whatsapp_phone_number_id}"
            "?fields=display_phone_number,verified_name,quality_rating",
            token=conf.whatsapp_access_token,
        )
        report["number"] = info.get("display_phone_number", "")
        report["name"] = info.get("verified_name", "")
        report["quality"] = info.get("quality_rating", "")
        report["ok"] = True

        if test_number:
            send_text(test_number, "Eagle — رسالة اختبار. الاتصال شغال.")
            report["sent"] = True
    except WhatsAppError as exc:
        report["ok"] = False
        report["error_ar"] = exc.message_ar
        report["error_en"] = exc.message_en
    return report
