"""JSON endpoints powering the live parts of the dashboard (polling based)."""

from django.contrib.auth.decorators import login_required
from django.http import Http404, JsonResponse
from django.shortcuts import get_object_or_404
from django.utils import timezone
from django.views.decorators.http import require_GET, require_POST

from . import ai, services
from .models import (
    ACTIVE_TASK_STATUSES,
    AppSettings,
    Assignment,
    AssignmentStatus,
    ChatAttachment,
    ChatMessage,
    ChatRoom,
    Client,
    ClientRequirement,
    InboundMessage,
    Notification,
    Role,
    RoomKind,
    Task,
    TaskStatus,
    User,
)
from .permissions import api_role_required


def _int(value, default=0):
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def _notification_json(item):
    return {
        "id": item.id,
        "level": item.level,
        "title_ar": item.title_ar,
        "title_en": item.title_en,
        "body_ar": item.body_ar,
        "body_en": item.body_en,
        "url": item.url,
        "sound": item.sound,
        "created": timezone.localtime(item.created_at).strftime("%H:%M"),
    }


def _pending_json(assignment, viewer):
    task = assignment.task
    return {
        "id": assignment.id,
        "task_code": task.code,
        "task_title": task.title,
        "task_url": f"/tasks/{task.code}/",
        "client": task.client.label_for(viewer),
        "role": assignment.target_role,
        "seconds_left": assignment.seconds_left,
        "window": AppSettings.load().response_window_seconds,
        "assigned_by": assignment.assigned_by.short_name if assignment.assigned_by else "",
        "priority": task.priority,
        "deadline": (
            timezone.localtime(task.deadline).strftime("%Y-%m-%d %H:%M")
            if task.deadline else ""
        ),
        "note": assignment.note,
    }


# ---------------------------------------------------------------------------
# Heartbeat
# ---------------------------------------------------------------------------

@login_required
@require_GET
def heartbeat(request):
    user = request.user
    services.heartbeat(user)

    after = _int(request.GET.get("after"), 0)
    fresh = Notification.objects.filter(user=user, id__gt=after).order_by("id")[:20]

    pending = (
        Assignment.objects.filter(assignee=user, status=AssignmentStatus.PENDING)
        .select_related("task", "task__client", "assigned_by")
        .order_by("-id")
        .first()
    )

    data = {
        "ok": True,
        "server_time": timezone.now().isoformat(),
        "unread": Notification.objects.filter(user=user, is_read=False).count(),
        "notifications": [_notification_json(n) for n in fresh],
        "pending": _pending_json(pending, user) if pending else None,
        "counters": {},
    }

    if user.is_operation or user.is_admin_role:
        data["counters"] = {
            "inbox": InboundMessage.objects.filter(
                claimed_by__isnull=True, is_rate_blocked=False
            ).count(),
            "new_tasks": Task.objects.filter(status=TaskStatus.NEW).count(),
            "ready": Task.objects.filter(status=TaskStatus.REVIEWED).count(),
        }
    elif user.is_team_lead:
        data["counters"] = {
            "review": Task.objects.filter(
                team_lead=user, status=TaskStatus.UNDER_REVIEW
            ).count(),
            "open": Task.objects.filter(
                team_lead=user, status__in=ACTIVE_TASK_STATUSES
            ).count(),
        }
    else:
        data["counters"] = {
            "open": Task.objects.filter(
                translator=user, status__in=ACTIVE_TASK_STATUSES
            ).count(),
            "rating": float(user.rating),
        }
    return JsonResponse(data)


@login_required
@require_POST
def mark_notifications_read(request):
    Notification.objects.filter(user=request.user, is_read=False).update(is_read=True)
    return JsonResponse({"ok": True})


@login_required
@require_POST
def set_prefs(request):
    user = request.user
    lang = request.POST.get("lang")
    theme = request.POST.get("theme")
    fields = []
    if lang in ("ar", "en"):
        user.ui_lang = lang
        fields.append("ui_lang")
    if theme in ("dark", "light"):
        user.ui_theme = theme
        fields.append("ui_theme")
    if fields:
        user.save(update_fields=fields)
    response = JsonResponse({"ok": True})
    if lang:
        response.set_cookie("eagle_lang", lang, max_age=31536000, samesite="Lax")
    if theme:
        response.set_cookie("eagle_theme", theme, max_age=31536000, samesite="Lax")
    return response


# ---------------------------------------------------------------------------
# Assignments
# ---------------------------------------------------------------------------

@login_required
@require_POST
def accept_assignment(request, pk):
    assignment = get_object_or_404(Assignment, pk=pk)
    ok, reason = services.accept_assignment(assignment, request.user)
    return JsonResponse({"ok": ok, "reason": reason, "task": assignment.task.code})


@login_required
@require_POST
def decline_assignment(request, pk):
    assignment = get_object_or_404(Assignment, pk=pk)
    ok = services.decline_assignment(assignment, request.user)
    return JsonResponse({"ok": ok, "task": assignment.task.code})


@api_role_required(Role.OPERATION)
@require_POST
def assign_lead(request, code):
    task = get_object_or_404(Task, code=code)
    lead = get_object_or_404(User, pk=request.POST.get("user"), role=Role.TEAM_LEAD)
    assignment = services.assign_to_lead(
        task, lead, request.user, note=request.POST.get("note", "")[:250]
    )
    return JsonResponse({"ok": True, "assignment": assignment.id, "status": task.status})


@api_role_required(Role.TEAM_LEAD)
@require_POST
def assign_translator(request, code):
    task = get_object_or_404(Task, code=code)
    user = request.user
    if not user.is_admin_role and task.team_lead_id != user.id:
        return JsonResponse({"ok": False, "error": "not_your_task"}, status=403)
    translator = get_object_or_404(User, pk=request.POST.get("user"), role=Role.TRANSLATOR)
    if not user.is_admin_role and translator.team_lead_id != user.id:
        return JsonResponse({"ok": False, "error": "not_in_your_team"}, status=403)
    if task.status not in (TaskStatus.LEAD_ACCEPTED, TaskStatus.AWAITING_TRANSLATOR):
        return JsonResponse({"ok": False, "error": "bad_status"}, status=400)
    assignment = services.assign_to_translator(
        task, translator, user, note=request.POST.get("note", "")[:250]
    )
    return JsonResponse({"ok": True, "assignment": assignment.id, "status": task.status})


# ---------------------------------------------------------------------------
# Task lifecycle
# ---------------------------------------------------------------------------

@login_required
@require_POST
def task_action(request, code, action):
    task = get_object_or_404(Task, code=code)
    user = request.user
    if not task.can_view(user):
        raise Http404

    handlers = {
        "translated": lambda: services.mark_translated(task, user),
        "reviewed": lambda: services.mark_reviewed(task, user),
        "delivered": lambda: services.mark_delivered(task, user),
        "cancel": lambda: services.cancel_task(task, user, request.POST.get("reason", "")),
    }
    handler = handlers.get(action)
    if handler is None:
        return JsonResponse({"ok": False, "error": "unknown_action"}, status=400)

    guard = {
        "translated": task.translator_id == user.id,
        "reviewed": task.team_lead_id == user.id,
        "delivered": user.is_operation,
        "cancel": user.is_operation,
    }[action]
    if not (guard or user.is_admin_role):
        return JsonResponse({"ok": False, "error": "forbidden"}, status=403)

    ok = handler()
    task.refresh_from_db()
    return JsonResponse({"ok": bool(ok), "status": task.status})


@api_role_required(Role.OPERATION)
@require_POST
def deliver(request, code):
    """Send the finished files to the client and close the task."""
    task = get_object_or_404(Task.objects.select_related("client"), code=code)
    user = request.user

    if task.status not in (TaskStatus.REVIEWED, TaskStatus.DELIVERED) and not user.is_admin_role:
        return JsonResponse({"ok": False, "error": "bad_status"}, status=400)

    ids = [_int(v) for v in request.POST.getlist("attachments") if _int(v)]
    note = (request.POST.get("note") or "").strip()
    send = request.POST.get("send", "1") == "1"

    ok, delivery, error = services.deliver_to_client(
        task, user, attachment_ids=ids, note=note, send=send
    )
    return JsonResponse({
        "ok": ok,
        "error": error,
        "status": delivery.status,
        "channel": delivery.get_channel_display(),
        "files": delivery.file_count,
    }, status=200 if ok else 400)


@api_role_required(Role.ADMIN)
@require_POST
def whatsapp_test(request):
    from . import whatsapp as wa

    report = wa.check_connection(request.POST.get("to", "").strip())
    return JsonResponse(report)


@api_role_required(Role.ADMIN)
@require_POST
def email_test(request):
    from . import mailer

    report = mailer.check_connection(AppSettings.load(), request.POST.get("to", "").strip())
    return JsonResponse(report)


@api_role_required(Role.OPERATION)
@require_POST
def set_deadline(request, code):
    from django.utils.dateparse import parse_datetime

    task = get_object_or_404(Task, code=code)
    raw = request.POST.get("deadline", "")
    parsed = parse_datetime(raw) if raw else None
    if raw and parsed is None:
        return JsonResponse({"ok": False, "error": "bad_date"}, status=400)
    if parsed is not None and timezone.is_naive(parsed):
        parsed = timezone.make_aware(parsed, timezone.get_current_timezone())
    task.deadline = parsed
    task.deadline_warned_at = None
    task.deadline_missed_notified = False
    task.save(update_fields=[
        "deadline", "deadline_warned_at", "deadline_missed_notified", "updated_at"
    ])
    if task.translator_id:
        services.notify(
            task.translator,
            title_ar="اتحدد ديدلاين جديد",
            title_en="Deadline updated",
            body_ar=f"ديدلاين {task.code}: {timezone.localtime(parsed):%Y-%m-%d %H:%M}" if parsed else "الديدلاين اتشال.",
            body_en=f"Deadline for {task.code}: {timezone.localtime(parsed):%Y-%m-%d %H:%M}" if parsed else "Deadline cleared.",
            level="info", url=f"/tasks/{task.code}/", sound=True, task=task,
        )
    return JsonResponse({"ok": True})


# ---------------------------------------------------------------------------
# Inbound messages
# ---------------------------------------------------------------------------

@api_role_required(Role.OPERATION)
@require_GET
def inbox_feed(request):
    """Messages newer than ``after``, rendered with the same partial as the page."""
    from django.template.loader import render_to_string

    after = _int(request.GET.get("after"), 0)
    rows = services.inbox_queryset(
        request.user, request.GET.get("state", ""), request.GET.get("q", "")
    ).filter(id__gt=after)[:20]

    # Oldest first so the client can prepend each one and keep newest on top.
    rows = list(rows)[::-1]
    return JsonResponse({
        "ok": True,
        "items": [
            {
                "id": row.id,
                "html": render_to_string("ops/_message_item.html", {"item": row}, request=request),
            }
            for row in rows
        ],
    })


@api_role_required(Role.OPERATION)
@require_POST
def claim_message(request, pk):
    message = get_object_or_404(InboundMessage, pk=pk)
    if message.is_rate_blocked and not request.user.is_admin_role:
        raise Http404
    ok = services.claim_message(message, request.user)
    return JsonResponse({
        "ok": ok,
        "claimed_by": message.claimed_by.short_name if message.claimed_by_id else "",
    })


# ---------------------------------------------------------------------------
# Chat
# ---------------------------------------------------------------------------

def _room_or_404(request, room_id):
    room = get_object_or_404(
        ChatRoom.objects.select_related("task", "task__client"), pk=room_id
    )
    # Membership alone is not enough for a task room: someone taken off the
    # task keeps their row in the members table, and a client room relays to a
    # real person. A standalone group has no task, so membership is the rule.
    if not room.can_access(request.user):
        raise Http404
    if room.task_id and not room.task.can_view(request.user):
        raise Http404
    return room


def _message_json(message, viewer):
    from_client = message.from_client
    return {
        "id": message.id,
        "body": message.body,
        "system": message.is_system,
        "sender": message.sender.short_name if message.sender_id else "",
        "sender_id": message.sender_id or 0,
        "role": message.sender.role if message.sender_id else "",
        "initials": message.sender.initials if message.sender_id else "•",
        "mine": message.sender_id == viewer.id,
        "time": timezone.localtime(message.created_at).strftime("%H:%M"),
        "date": timezone.localtime(message.created_at).strftime("%Y-%m-%d"),
        # Relay bookkeeping — only ever set in a client room.
        "from_client": from_client,
        "relay_status": message.relay_status,
        "relay_error": message.relay_error,
        "attachments": [
            {
                "url": a.file.url,
                "name": a.original_name or a.file.name,
                "size": a.pretty_size,
                "audio": a.is_audio,
            }
            for a in message.relay_files
        ],
    }


@login_required
@require_GET
def chat_fetch(request, room_id):
    room = _room_or_404(request, room_id)
    after = _int(request.GET.get("after"), 0)
    qs = room.messages.filter(id__gt=after).select_related(
        "sender", "inbound"
    ).prefetch_related("attachments", "inbound__attachments")[:100]
    return JsonResponse({
        "ok": True,
        "messages": [_message_json(m, request.user) for m in qs],
    })


def _store_voice(message, upload):
    """Save a browser recording as a chat attachment, converted for WhatsApp.

    Converting before storing means the room and the client hold the same
    bytes — the same rule the client chat follows.
    """
    from django.core.files.base import ContentFile

    from . import audio

    raw = upload.read()
    name = upload.name or "voice"
    mime = audio.base_mime(getattr(upload, "content_type", ""))
    error = ""
    try:
        content, name, mime = audio.prepare(raw, name, mime)
    except audio.AudioError as exc:
        content, error = raw, exc.message_ar

    ChatAttachment.objects.create(
        message=message,
        file=ContentFile(content, name=name),
        original_name=name,
        size=len(content),
    )
    return error


@login_required
@require_POST
def chat_send(request, room_id):
    room = _room_or_404(request, room_id)
    body = (request.POST.get("body") or "").strip()
    uploads = request.FILES.getlist("files")
    voice = request.FILES.get("voice")
    if not body and not uploads and voice is None:
        return JsonResponse({"ok": False, "error": "empty"}, status=400)

    message = ChatMessage.objects.create(room=room, sender=request.user, body=body)
    for item in uploads:
        ChatAttachment.objects.create(
            message=message, file=item, original_name=item.name, size=item.size
        )
    voice_error = ""
    if voice is not None:
        voice_error = _store_voice(message, voice)

    # A client room is a relay: whatever lands here goes on to the client's
    # WhatsApp. A failure is recorded on the message, never swallowed.
    relay_error = ""
    if room.kind == RoomKind.CLIENT:
        if voice_error:
            # The recording is saved but WhatsApp would reject it, so say so
            # instead of relaying a file the client cannot play.
            message.relay_status = "failed"
            message.relay_error = voice_error
            message.save(update_fields=["relay_status", "relay_error"])
            relay_error = voice_error
        else:
            _ok, relay_error = services.relay_chat_message(message)

    task = room.task
    where = task.code if task else (room.title or room.display_title)
    url = f"/tasks/{task.code}/?room={room.id}" if task else f"/ops/chats/g/{room.id}/"
    # A membership row can outlive the assignment; the notification body quotes
    # the message, so re-check access rather than trusting the row.
    for member in room.members.exclude(pk=request.user.pk):
        if task is not None and not task.can_view(member):
            continue
        services.notify(
            member,
            title_ar="رسالة جديدة في الشات",
            title_en="New chat message",
            body_ar=f"{request.user.short_name} في {where}: {(body or 'ملفات')[:60]}",
            body_en=f"{request.user.short_name} in {where}: {(body or 'files')[:60]}",
            level="info", url=url, task=task,
        )
    return JsonResponse({
        "ok": True,
        "relay_error": relay_error,
        "message": _message_json(message, request.user),
    })


# ---------------------------------------------------------------------------
# Client conversations (the WhatsApp-style chat)
# ---------------------------------------------------------------------------

def _client_or_404(request, client_code):
    client = get_object_or_404(Client, code=client_code)
    if not (request.user.is_operation or request.user.is_admin_role):
        raise Http404
    return client


def _thread_entry_json(entry, viewer):
    return {
        "uid": entry["uid"],
        "kind": entry["kind"],
        "body": entry["body"],
        "subject": entry.get("subject", ""),
        "channel": entry.get("channel", ""),
        "status": entry.get("status", ""),
        "error": entry.get("error", ""),
        "sender": entry.get("sender", ""),
        "task_code": entry.get("task_code", ""),
        "is_delivery": entry.get("is_delivery", False),
        "time": timezone.localtime(entry["at"]).strftime("%H:%M"),
        "date": timezone.localtime(entry["at"]).strftime("%Y-%m-%d"),
        "files": entry.get("files", []),
    }


def _conversation_json(client, viewer):
    preview = services.conversation_preview(client, viewer)
    return {
        "code": client.code,
        "group": False,
        "url": f"/ops/chats/{client.code}/",
        "label": client.label_for(viewer),
        "text": preview["text"],
        "outgoing": preview["outgoing"],
        "time": timezone.localtime(preview["at"]).strftime("%H:%M") if preview["at"] else "",
        "date": timezone.localtime(preview["at"]).strftime("%Y-%m-%d") if preview["at"] else "",
        # The 24-hour rule is a WhatsApp rule — e-mail has no such window.
        "channel": services.client_channel(client),
        "window_open": client.reply_window_open,
        "minutes_left": client.reply_window_minutes_left,
    }


def _group_json(room, viewer):
    """A group in the same shape as a 1:1 conversation, so one list renders both."""
    preview = services.group_preview(room, viewer)
    client = room.relay_client
    return {
        "code": f"g{room.id}",
        "group": True,
        "room": room.id,
        "url": f"/ops/chats/g/{room.id}/",
        "label": room.display_title,
        "client_code": client.code if client else "",
        "text": preview["text"],
        "outgoing": preview["outgoing"],
        "time": timezone.localtime(preview["at"]).strftime("%H:%M") if preview["at"] else "",
        "date": timezone.localtime(preview["at"]).strftime("%Y-%m-%d") if preview["at"] else "",
        "channel": services.client_channel(client) if client else "",
        "window_open": client.reply_window_open if client else False,
        "minutes_left": client.reply_window_minutes_left if client else 0,
    }


@login_required
@require_GET
def client_chat_list(request):
    """Feeds the chats sidebar. Mirrors views._chat_sidebar exactly.

    Any signed-in member can poll it — they only ever get their own groups —
    but the 1:1 list is the whole client directory, so it stays with the roles
    that own the client inbox.
    """
    query = request.GET.get("q", "")
    kind = request.GET.get("type", "all")
    sees_all_clients = request.user.is_operation or request.user.is_admin_role
    items = []
    if kind in ("all", "chats") and sees_all_clients:
        items += [
            _conversation_json(row, request.user)
            for row in services.client_conversations(request.user, query)[:100]
        ]
    if kind in ("all", "groups"):
        items += [
            _group_json(room, request.user)
            for room in services.groups_for(request.user, query)[:100]
        ]
    # Newest activity first across both kinds.
    items.sort(key=lambda row: (row.get("date", ""), row.get("time", "")), reverse=True)
    return JsonResponse({"ok": True, "items": items})


@login_required
@require_POST
def group_create(request):
    """Open a group with a client. The role gate lives in AppSettings."""
    conf = AppSettings.load()
    if not conf.can_create_group(request.user):
        return JsonResponse(
            {"ok": False, "error": "مالكش صلاحية تعمل جروب. الأدمن بيظبطها من الإعدادات."},
            status=403,
        )

    client = Client.objects.filter(code=request.POST.get("client", "").strip()).first()
    task = None
    task_code = (request.POST.get("task") or "").strip()
    if task_code:
        task = Task.objects.filter(code=task_code).first()
        if task is None:
            return JsonResponse({"ok": False, "error": "التاسك دي مش موجودة."}, status=400)
        # Attaching a task pulls its people into the group, so the person
        # opening it has to be allowed to see that task in the first place.
        if not task.can_view(request.user):
            return JsonResponse(
                {"ok": False, "error": "التاسك دي مش من حقك."}, status=403
            )
        if client is not None and task.client_id != client.id:
            return JsonResponse(
                {"ok": False, "error": "التاسك دي مش بتاعة العميل ده."}, status=400
            )

    members = list(User.objects.filter(
        pk__in=[_int(v) for v in request.POST.getlist("members") if _int(v)],
        is_active=True,
    ))

    room, error = services.create_client_group(
        request.user, client,
        title=request.POST.get("title", ""), task=task, members=members,
    )
    if room is None:
        return JsonResponse({"ok": False, "error": error}, status=400)
    return JsonResponse({"ok": True, "room": room.id, "url": f"/ops/chats/g/{room.id}/"})


def _group_or_404(request, room_id):
    room = get_object_or_404(
        ChatRoom.objects.select_related("client", "task"),
        pk=room_id, kind=RoomKind.CLIENT,
    )
    if not room.can_access(request.user):
        raise Http404
    if room.task_id and not room.task.can_view(request.user):
        raise Http404
    return room


@login_required
@require_GET
def group_chat_fetch(request, room_id):
    room = _group_or_404(request, room_id)
    return JsonResponse({
        "ok": True,
        "client": _group_json(room, request.user),
        "messages": [
            _thread_entry_json(e, request.user)
            for e in services.group_thread(room, request.user)
        ],
    })


@login_required
@require_POST
def group_chat_send(request, room_id):
    """Same contract as client_chat_send, so chat.js drives both identically."""
    room = _group_or_404(request, room_id)
    response = chat_send(request, room_id)
    ok = response.status_code == 200
    payload = {
        "ok": ok,
        "error": "",
        "messages": [
            _thread_entry_json(e, request.user)
            for e in services.group_thread(room, request.user)
        ],
        "client": _group_json(room, request.user),
    }
    if ok:
        import json as _json

        relay_error = _json.loads(response.content).get("relay_error") or ""
        if relay_error:
            payload["ok"] = False
            payload["error"] = relay_error
    else:
        payload["error"] = "مفيش حاجة تتبعت."
    return JsonResponse(payload, status=200)


@api_role_required(Role.OPERATION)
@require_GET
def client_chat_fetch(request, client_code):
    client = _client_or_404(request, client_code)
    entries = services.client_thread(client, request.user)
    return JsonResponse({
        "ok": True,
        "client": _conversation_json(client, request.user),
        "messages": [_thread_entry_json(e, request.user) for e in entries],
    })


@api_role_required(Role.OPERATION)
@require_POST
def client_chat_send(request, client_code):
    client = _client_or_404(request, client_code)
    ok, outbound, error = services.send_client_message(
        client,
        request.user,
        body=request.POST.get("body", ""),
        uploads=request.FILES.getlist("files"),
        voice=request.FILES.get("voice"),
        voice_seconds=_int(request.POST.get("seconds"), 0),
    )
    payload = {"ok": ok, "error": error}
    if outbound is not None:
        # Re-render the whole thread tail so a failed send still shows up.
        entries = services.client_thread(client, request.user)
        payload["messages"] = [_thread_entry_json(e, request.user) for e in entries]
        payload["client"] = _conversation_json(client, request.user)
    return JsonResponse(payload, status=200 if ok else 400)


# ---------------------------------------------------------------------------
# Client requirements
# ---------------------------------------------------------------------------

@login_required
@require_POST
def add_requirement(request, client_code):
    from .models import Client

    client = get_object_or_404(Client, code=client_code)
    user = request.user
    if user.is_translator:
        return JsonResponse({"ok": False, "error": "forbidden"}, status=403)
    text = (request.POST.get("text") or "").strip()
    kind = request.POST.get("kind", "rule")
    if not text:
        return JsonResponse({"ok": False, "error": "empty"}, status=400)
    req = ClientRequirement.objects.create(
        client=client, kind=kind, text=text, author=user
    )
    return JsonResponse({
        "ok": True,
        "id": req.id,
        "kind": req.kind,
        "text": req.text,
        "author": user.short_name,
    })


# ---------------------------------------------------------------------------
# AI review
# ---------------------------------------------------------------------------

@login_required
@require_POST
def ai_check(request, code):
    task = get_object_or_404(Task, code=code)
    user = request.user
    if not task.can_view(user):
        raise Http404

    conf = AppSettings.load()
    if not conf.ai_check_enabled:
        return JsonResponse({"ok": False, "error": "disabled"}, status=400)

    source_text = request.POST.get("source_text", "")
    translated_text = request.POST.get("translated_text", "")

    # Fall back to text extracted from the chat attachments.
    if not translated_text.strip():
        room = task.rooms.filter(kind=RoomKind.GROUP).first()
        if room:
            latest = (
                ChatAttachment.objects.filter(
                    message__room=room, message__sender=task.translator
                ).order_by("-id")[:3]
            )
            translated_text = "\n\n".join(
                ai.extract_text(a.file, a.original_name) for a in latest
            ).strip()

    requirements = "\n".join(
        f"- [{r.get_kind_display()}] {r.text}" for r in task.client.requirements.all()[:30]
    )

    result = ai.run_check(task, user, source_text, translated_text, requirements)
    return JsonResponse({
        "ok": result.status != result.Status.ERROR,
        "status": result.status,
        "summary": result.summary,
        "issues": result.issues,
        "error": result.error_message,
        "count": result.issue_count,
    })
