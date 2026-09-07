"""Inbound webhooks for WhatsApp and e-mail.

Both endpoints are written against the shape of the WhatsApp Cloud API and a
generic mail relay, but they also accept a plain ``{"from", "body"}`` payload so
the flow can be exercised before the real integrations are wired up.
"""

import base64
import json

from django.core.files.base import ContentFile
from django.http import HttpResponse, HttpResponseForbidden, JsonResponse
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_http_methods

from . import services
from .models import AppSettings


def _guard(request):
    """Optional shared-secret check for the non-Meta payloads."""
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


@csrf_exempt
@require_http_methods(["GET", "POST"])
def whatsapp(request):
    conf = AppSettings.load()

    # Meta verification handshake.
    if request.method == "GET":
        mode = request.GET.get("hub.mode")
        token = request.GET.get("hub.verify_token")
        challenge = request.GET.get("hub.challenge", "")
        if mode == "subscribe" and token and token == conf.whatsapp_verify_token:
            return HttpResponse(challenge, content_type="text/plain")
        return HttpResponseForbidden("verification failed")

    data = _payload(request)

    # --- WhatsApp Cloud API shape -----------------------------------------
    created = []
    for entry in data.get("entry", []) or []:
        for change in entry.get("changes", []) or []:
            value = change.get("value", {}) or {}
            contacts = {c.get("wa_id"): c.get("profile", {}).get("name", "")
                        for c in value.get("contacts", []) or []}
            for msg in value.get("messages", []) or []:
                sender = msg.get("from", "")
                body = ""
                if msg.get("type") == "text":
                    body = (msg.get("text") or {}).get("body", "")
                else:
                    block = msg.get(msg.get("type"), {}) or {}
                    body = block.get("caption", "") or f"[{msg.get('type')}]"
                message = services.ingest_message(
                    channel="whatsapp",
                    body=body,
                    sender_identity=sender,
                    sender_display=contacts.get(sender, ""),
                    external_id=msg.get("id", ""),
                )
                created.append(message.id)

    # --- Simple/manual shape ----------------------------------------------
    if not created and data.get("from"):
        if not _guard(request):
            return HttpResponseForbidden("bad secret")
        message = services.ingest_message(
            channel="whatsapp",
            body=data.get("body", ""),
            sender_identity=str(data.get("from", "")),
            sender_display=data.get("name", ""),
            external_id=data.get("id", ""),
            attachments=_decode_files(data.get("attachments")),
        )
        created.append(message.id)

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
    message = services.ingest_message(
        channel="email",
        subject=data.get("subject", ""),
        body=data.get("body") or data.get("text", ""),
        sender_identity=sender,
        sender_display=data.get("name", ""),
        external_id=data.get("message_id", ""),
        attachments=_decode_files(data.get("attachments")),
    )
    return JsonResponse({"ok": True, "created": [message.id]})
