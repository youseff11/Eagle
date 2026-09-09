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
    room = get_object_or_404(ChatRoom.objects.select_related("task"), pk=room_id)
    if not room.can_access(request.user):
        raise Http404
    return room


def _message_json(message, viewer):
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
        "attachments": [
            {"url": a.file.url, "name": a.original_name or a.file.name, "size": a.pretty_size}
            for a in message.attachments.all()
        ],
    }


@login_required
@require_GET
def chat_fetch(request, room_id):
    room = _room_or_404(request, room_id)
    after = _int(request.GET.get("after"), 0)
    qs = room.messages.filter(id__gt=after).select_related("sender").prefetch_related(
        "attachments"
    )[:100]
    return JsonResponse({
        "ok": True,
        "messages": [_message_json(m, request.user) for m in qs],
    })


@login_required
@require_POST
def chat_send(request, room_id):
    room = _room_or_404(request, room_id)
    body = (request.POST.get("body") or "").strip()
    uploads = request.FILES.getlist("files")
    if not body and not uploads:
        return JsonResponse({"ok": False, "error": "empty"}, status=400)

    message = ChatMessage.objects.create(room=room, sender=request.user, body=body)
    for item in uploads:
        ChatAttachment.objects.create(
            message=message, file=item, original_name=item.name, size=item.size
        )

    task = room.task
    for member in room.members.exclude(pk=request.user.pk):
        services.notify(
            member,
            title_ar="رسالة جديدة في الشات",
            title_en="New chat message",
            body_ar=f"{request.user.short_name} في {task.code}: {(body or 'ملفات')[:60]}",
            body_en=f"{request.user.short_name} in {task.code}: {(body or 'files')[:60]}",
            level="info", url=f"/tasks/{task.code}/?room={room.id}", task=task,
        )
    return JsonResponse({"ok": True, "message": _message_json(message, request.user)})


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


@api_role_required(Role.OPERATION)
@require_GET
def client_chat_list(request):
    rows = services.client_conversations(request.user, request.GET.get("q", ""))[:100]
    return JsonResponse({
        "ok": True,
        "items": [_conversation_json(row, request.user) for row in rows],
    })


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
