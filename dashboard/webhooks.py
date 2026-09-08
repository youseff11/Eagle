"""Inbound webhooks for WhatsApp and e-mail.

The WhatsApp endpoint speaks the real Meta Cloud API: it answers the verification
handshake, checks the X-Hub-Signature-256 header when an App Secret is set, and
downloads any media the client attached. It also accepts a plain
``{"from", "body"}`` payload so the flow can be exercised without Meta.
"""

import base64
import json
import logging

from django.core.files.base import ContentFile
from django.http import HttpResponse, HttpResponseForbidden, JsonResponse
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_http_methods

from . import services, whatsapp
from .models import AppSettings

logger = logging.getLogger(__name__)

#: WhatsApp message types that carry a file.
MEDIA_TYPES = ("image", "document", "audio", "video", "sticker", "voice")


def _guard(request):
    """Optional shared-secret check for the simplified (non-Meta) payload."""
    conf = AppSettings.load()
    if not conf.webhook_shared_secret:
        return True
    provided = request.headers.get("X-Eagle-Secret") or request.GET.get("secret", "")
    return provided == conf.webhook_shared_secret


def _payload(request):
    try:
        return json.loads(request.body.decode("utf-8") or "{}")
    except (ValueError, UnicodeDecodeError):
        return {}


def _decode_files(items):
    files = []
    for item in items or []:
        content = item.get("content_base64")
        if not content:
            continue
        try:
            raw = base64.b64decode(content)
        except Exception:
            continue
        name = item.get("filename") or "attachment.bin"
        files.append({"file": ContentFile(raw, name=name), "name": name, "size": len(raw)})
    return files


def _pull_media(message):
    """Download the file attached to one WhatsApp message, if any."""
    kind = message.get("type")
    if kind not in MEDIA_TYPES:
        return []
    block = message.get(kind) or {}
    media_id = block.get("id")
    if not media_id:
        return []
    try:
        content, fallback_name, mime = whatsapp.fetch_media(media_id)
    except Exception as exc:  # noqa: BLE001 - a bad file must never break the hook
        # Returning non-200 makes Meta retry forever, so swallow and log instead.
        logger.warning("WhatsApp media %s could not be downloaded: %s", media_id, exc)
        return []

    name = block.get("filename") or fallback_name
    return [{"file": ContentFile(content, name=name), "name": name, "size": len(content)}]


def _body_of(message):
    kind = message.get("type")
    if kind == "text":
        return (message.get("text") or {}).get("body", "")
    block = message.get(kind) or {}
    caption = block.get("caption") or ""
    if caption:
        return caption
    if kind in MEDIA_TYPES:
        return f"[{kind}]"
    if kind == "location":
        return "[location]"
    return f"[{kind}]"


@csrf_exempt
@require_http_methods(["GET", "POST"])
def whatsapp_hook(request):
    conf = AppSettings.load()

    # --- Meta verification handshake --------------------------------------
    if request.method == "GET":
        mode = request.GET.get("hub.mode")
        token = request.GET.get("hub.verify_token")
        challenge = request.GET.get("hub.challenge", "")
        if mode == "subscribe" and token and token == conf.whatsapp_verify_token:
            return HttpResponse(challenge, content_type="text/plain")
        return HttpResponseForbidden("verification failed")

    data = _payload(request)
    is_meta = bool(data.get("entry"))

    # --- Signature check (only when an App Secret is configured) ----------
    if is_meta and conf.whatsapp_app_secret:
        if not whatsapp.verify_signature(
            conf.whatsapp_app_secret, request.body,
            request.headers.get("X-Hub-Signature-256", ""),
        ):
            logger.warning("Rejected a WhatsApp webhook with a bad signature.")
            return HttpResponseForbidden("bad signature")

    created = []

    # --- WhatsApp Cloud API shape -----------------------------------------
    for entry in data.get("entry", []) or []:
        for change in entry.get("changes", []) or []:
            value = change.get("value", {}) or {}
            contacts = {
                c.get("wa_id"): (c.get("profile", {}) or {}).get("name", "")
                for c in value.get("contacts", []) or []
            }
            for message in value.get("messages", []) or []:
                sender = message.get("from", "")
                record = services.ingest_message(
                    channel="whatsapp",
                    body=_body_of(message),
                    sender_identity=sender,
                    sender_display=contacts.get(sender, ""),
                    external_id=message.get("id", ""),
                    attachments=_pull_media(message),
                )
                created.append(record.id)

    # --- Simplified/manual shape ------------------------------------------
    if not is_meta and data.get("from"):
        if not _guard(request):
            return HttpResponseForbidden("bad secret")
        record = services.ingest_message(
            channel="whatsapp",
            body=data.get("body", ""),
            sender_identity=str(data.get("from", "")),
            sender_display=data.get("name", ""),
            external_id=data.get("id", ""),
            attachments=_decode_files(data.get("attachments")),
        )
        created.append(record.id)

    # Meta retries anything that is not a 200, so always acknowledge.
    return JsonResponse({"ok": True, "created": created})


@csrf_exempt
@require_http_methods(["POST"])
def email_hook(request):
    if not _guard(request):
        return HttpResponseForbidden("bad secret")
    data = _payload(request)
    sender = data.get("from") or data.get("sender") or ""
    if not sender:
        return JsonResponse({"ok": False, "error": "missing sender"}, status=400)
    record = services.ingest_message(
        channel="email",
        subject=data.get("subject", ""),
        body=data.get("body") or data.get("text", ""),
        sender_identity=sender,
        sender_display=data.get("name", ""),
        external_id=data.get("message_id", ""),
        attachments=_decode_files(data.get("attachments")),
    )
    return JsonResponse({"ok": True, "created": [record.id]})
