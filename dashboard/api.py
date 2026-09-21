"""JSON endpoints powering the live parts of the dashboard (polling based)."""

from decimal import Decimal, InvalidOperation

from django.contrib.auth.decorators import login_required
from django.http import Http404, JsonResponse
from django.shortcuts import get_object_or_404
from django.utils import timezone
from django.views.decorators.http import require_GET, require_POST

from . import ai, attendance, services
from .models import (
    ACTIVE_TASK_STATUSES,
    AppSettings,
    Assignment,
    AssignmentStatus,
    Channel,
    ChatAttachment,
    ChatMessage,
    ChatRoom,
    Client,
    ClientRequirement,
    InboundMessage,
    Notification,
    # Used by `_quoted_of` when somebody replies to a message we sent. It was
    # missing, so quoting an outbound message raised NameError at runtime.
    OutboundMessage,
    PunchKind,
    Role,
    RoomKind,
    Task,
    TaskStatus,
    User,
    WorkDay,
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
            # The sidebar badge counts what its page shows, and that page is
            # e-mail conversations now. WhatsApp has its own unread marks in
            # the chat list.
            "inbox": services.unclaimed_conversation_count(),
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


@api_role_required(Role.OPERATION, Role.TEAM_LEAD)
@require_GET
def presence(request):
    """Who has Eagle open right now, for the pages that show a status dot.

    Polled by the browser so the dots move on their own — the whole point of
    the column is to answer "can I hand this to them this minute", and a value
    that is only correct at page load cannot answer that.

    Only the roles with a status board get it, and a team leader gets their own
    team: everyone's login pattern and workload is not something a translator
    needs, and an endpoint that lists all staff is a roster anyone can harvest.
    """
    from django.db.models import Count, Q as _Q

    user = request.user
    people = User.objects.filter(is_active=True)
    if user.is_team_lead and not user.is_admin_role:
        people = people.filter(_Q(pk=user.pk) | _Q(team_lead=user))

    # One query instead of one per person: this is polled every 20 seconds by
    # every open board, so a per-row count would dominate the database.
    people = people.annotate(
        open_as_translator=Count(
            "translator_tasks",
            filter=_Q(translator_tasks__status__in=ACTIVE_TASK_STATUSES),
            distinct=True,
        ),
        open_as_lead=Count(
            "lead_tasks",
            filter=_Q(lead_tasks__status__in=ACTIVE_TASK_STATUSES),
            distinct=True,
        ),
    ).prefetch_related("shifts")

    rows = []
    for person in people:
        seconds = person.seconds_since_seen
        if person.is_translator:
            busy = person.open_as_translator > 0
        elif person.is_team_lead:
            busy = person.open_as_lead > 0
        else:
            busy = False
        rows.append({
            "id": person.id,
            "online": person.is_online,
            "busy": busy,
            "on_shift": person.on_shift,
            "seen_ar": _seen_label(seconds, person.last_seen, "ar"),
            "seen_en": _seen_label(seconds, person.last_seen, "en"),
        })
    return JsonResponse({"ok": True, "people": rows})


def _seen_label(seconds, stamp, lang):
    """Mirrors the last_seen_label template filter — keep the two in step."""
    if stamp is None:
        return "عمره ما دخل" if lang == "ar" else "Never signed in"
    seconds = int(seconds or 0)
    if seconds < 60:
        return "دلوقتي" if lang == "ar" else "just now"
    if seconds < 3600:
        n = seconds // 60
        return f"من {n} دقيقة" if lang == "ar" else f"{n} min ago"
    if seconds < 86400:
        n = seconds // 3600
        return f"من {n} ساعة" if lang == "ar" else f"{n}h ago"
    if seconds < 86400 * 7:
        n = seconds // 86400
        return f"من {n} يوم" if lang == "ar" else f"{n}d ago"
    return timezone.localtime(stamp).strftime("%Y-%m-%d %H:%M")


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
        # The other half of the review loop, and the only thing that can
        # ever record a revision (section 20's revision rate).
        "return": lambda: services.send_back_for_revision(
            task, user, request.POST.get("reason", "")
        ),
        "score": lambda: services.score_review(
            task, user, request.POST.get("score"), request.POST.get("note", "")
        ),
        # The operation putting their hand up for a reviewed job. Nothing
        # reaches the client before this.
        "ack": lambda: services.acknowledge_handover(task, user),
        # An admin who claimed the client's message opens a group with no
        # operation in it; this is how one joins afterwards.
        "add-member": lambda: services.add_group_member(
            task, user,
            User.objects.filter(pk=_int(request.POST.get("user")), is_active=True).first(),
        ),
    }
    handler = handlers.get(action)
    if handler is None:
        return JsonResponse({"ok": False, "error": "unknown_action"}, status=400)

    guard = {
        "translated": task.translator_id == user.id,
        "reviewed": task.team_lead_id == user.id,
        "delivered": user.is_operation,
        "cancel": user.is_operation,
        "return": task.team_lead_id == user.id,
        "score": task.team_lead_id == user.id,
        "ack": user.is_operation,
        "add-member": user.is_admin_role,
    }[action]
    if not (guard or user.is_admin_role):
        return JsonResponse({"ok": False, "error": "forbidden"}, status=403)

    ok = handler()
    task.refresh_from_db()
    return JsonResponse({
        "ok": bool(ok),
        "status": task.status,
        "review_score": task.review_score,
        "revision_count": task.revision_count,
    })


@api_role_required(Role.OPERATION)
@require_POST
def deliver(request, code):
    """Send the finished files to the client and close the task."""
    task = get_object_or_404(Task.objects.select_related("client"), code=code)
    user = request.user

    if task.status not in (TaskStatus.REVIEWED, TaskStatus.DELIVERED) and not user.is_admin_role:
        return JsonResponse({"ok": False, "error": "bad_status"}, status=400)
    # Checked here as well as in the service: this endpoint reads the delivery
    # row it gets back, and a refused send has no row to read.
    if not task.handover_ack_at:
        return JsonResponse(
            {"ok": False, "error": "\u0627\u0633\u062a\u0644\u0645 \u0627\u0644\u062a\u0627\u0633\u0643 \u0627\u0644\u0623\u0648\u0644 \u0642\u0628\u0644 \u0645\u0627 \u062a\u0628\u0639\u062a\u0647\u0627 \u0644\u0644\u0639\u0645\u064a\u0644."},
            status=400,
        )

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
    """Conversations that gained a letter newer than ``after``.

    Each comes back as the whole row, rendered with the page's own partial. The
    page swaps out the row with the same ``data-thread`` and puts the new one
    on top — a reply moves its conversation up, the way it does in Gmail,
    instead of appearing as a second row.
    """
    from django.template.loader import render_to_string

    after = _int(request.GET.get("after"), 0)
    state = request.GET.get("state", "")
    query = request.GET.get("q", "").strip()
    # after=0 is an inbox that was empty when the page loaded: everything
    # that matches now is new to it.
    threads = services.inbox_threads(request.user, state, query, limit=20, after=after)
    back_qs = services.inbox_filter_qs(state, query)

    # Oldest first so the client can prepend each one and keep newest on top.
    threads = threads[::-1]
    return JsonResponse({
        "ok": True,
        "last": max([after] + [t.last_id for t in threads]),
        "items": [
            {
                "id": thread.last_id,
                "thread": thread.key,
                "html": render_to_string(
                    "ops/_thread_item.html",
                    {"thread": thread, "back_qs": back_qs},
                    request=request,
                ),
            }
            for thread in threads
        ],
    })


@api_role_required(Role.OPERATION)
@require_GET
def mail_thread_feed(request, pk):
    """What is new in the conversation ``pk`` belongs to.

    ``after`` is the newest client letter on screen, ``after_out`` our newest
    reply. Keeps an open conversation current: the client's next letter — or a
    colleague's reply — lands at the bottom of the page somebody is reading.
    """
    from django.template.loader import render_to_string

    anchor = get_object_or_404(InboundMessage, pk=pk, channel=Channel.EMAIL)
    if not anchor.visible_to(request.user):
        raise Http404
    after = _int(request.GET.get("after"), 0)
    after_out = _int(request.GET.get("after_out"), 0)

    items = [
        {
            "kind": "in",
            "id": row.id,
            "html": render_to_string(
                "ops/_message_item.html",
                {"item": row, "in_thread": True, "open": True},
                request=request,
            ),
        }
        for row in services.thread_messages(request.user, anchor)
        if row.pk > after
    ]
    items += [
        {
            "kind": "out",
            "id": reply.id,
            "html": render_to_string(
                "ops/_reply_item.html", {"reply": reply, "open": True}, request=request,
            ),
        }
        for reply in services.thread_replies(anchor.thread_key)
        if reply.pk > after_out
    ]
    return JsonResponse({"ok": True, "items": items})


@api_role_required(Role.OPERATION)
@require_POST
def mail_reply(request, pk):
    """Answer the conversation ``pk`` is in: text, files, or both, by e-mail.

    The reply comes back rendered, so the page can put it under the letters
    without a reload — and it comes back on a failure too, marked failed, the
    way the chat keeps a failed send visible instead of losing it.
    """
    from django.template.loader import render_to_string

    anchor = get_object_or_404(
        InboundMessage.objects.select_related("client"), pk=pk, channel=Channel.EMAIL
    )
    if not anchor.visible_to(request.user):
        raise Http404
    ok, outbound, error = services.reply_to_thread(
        anchor, request.user,
        body=request.POST.get("body", ""),
        uploads=request.FILES.getlist("files"),
    )
    payload = {"ok": ok, "error": error}
    if outbound is not None:
        payload["id"] = outbound.pk
        payload["html"] = render_to_string(
            "ops/_reply_item.html", {"reply": outbound, "open": True}, request=request,
        )
    return JsonResponse(payload, status=200 if ok else 400)


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


@api_role_required(Role.OPERATION)
@require_POST
def confirm_message(request, pk):
    """"استلمت" — tell the client it arrived, then mark it claimed.

    The receipt goes out on the channel the message came in on, so a WhatsApp
    message is answered on WhatsApp and an e-mail by e-mail, whatever the
    client's most recent message happened to be.
    """
    message = get_object_or_404(
        InboundMessage.objects.select_related("client"), pk=pk
    )
    if message.is_rate_blocked and not request.user.is_admin_role:
        raise Http404
    ok, error = services.confirm_receipt(message, request.user)
    return JsonResponse(
        {
            "ok": ok,
            "error": error,
            "claimed_by": message.claimed_by.short_name if message.claimed_by_id else "",
        },
        status=200 if ok else 400,
    )


@api_role_required(Role.OPERATION)
@require_POST
def fetch_mail(request):
    """Poll the mailbox now, instead of waiting for the scheduled run."""
    from . import mailbox

    created, error = mailbox.fetch_and_record()
    return JsonResponse(
        {"ok": not error, "created": created, "error": error},
        status=200 if not error else 400,
    )


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

    # "gR-N" from the group page, or a bare id from the task page.
    reply_raw = (request.POST.get("reply_uid") or request.POST.get("reply_to") or "").strip()
    reply_id = _int(reply_raw.rsplit("-", 1)[-1], 0)
    reply_to = ChatMessage.objects.filter(
        pk=reply_id, room=room, is_system=False
    ).first() if reply_id else None

    message = ChatMessage.objects.create(
        room=room, sender=request.user, body=body, reply_to=reply_to,
    )
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
        "id": entry.get("id", 0),
        "kind": entry["kind"],
        # The two actions under a client message. A translator or team leader
        # never gets them: turning a message into a task and answering the
        # client both belong to the operation.
        "actions": bool(
            entry.get("actions") and (viewer.is_operation or viewer.is_admin_role)
        ),
        "claimed_by": entry.get("claimed_by", ""),
        "has_task": entry.get("has_task", False),
        "body": entry["body"],
        "subject": entry.get("subject", ""),
        "channel": entry.get("channel", ""),
        "status": entry.get("status", ""),
        "error": entry.get("error", ""),
        "sender": entry.get("sender", ""),
        "task_code": entry.get("task_code", ""),
        "is_delivery": entry.get("is_delivery", False),
        "quote": entry.get("quote", ""),
        "quote_who": entry.get("quote_who", ""),
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
@require_POST
def group_add_members(request, room_id):
    """Add people to a group. Same gate as creating one — it reaches a client."""
    room = _group_or_404(request, room_id)
    conf = AppSettings.load()
    if not conf.can_create_group(request.user):
        return JsonResponse(
            {"ok": False, "error": "مالكش صلاحية تضيف أعضاء. الأدمن بيظبطها من الإعدادات."},
            status=403,
        )

    wanted = [_int(v) for v in request.POST.getlist("members") if _int(v)]
    people = list(User.objects.filter(pk__in=wanted, is_active=True))
    if not people:
        return JsonResponse({"ok": False, "error": "اختار حد الأول."}, status=400)

    task = room.task
    added, refused = [], []
    for person in people:
        # A task-bound group must not hand the task's client conversation to
        # someone who is not on that task.
        if task is not None and not task.can_view(person):
            refused.append(person.short_name)
            continue
        if room.members.filter(pk=person.pk).exists():
            continue
        room.members.add(person)
        added.append(person)

    client = room.relay_client
    for person in added:
        services.notify(
            person,
            title_ar="اتضفت في جروب عميل",
            title_en="Added to a client group",
            body_ar=f"{request.user.short_name} ضافك في جروب مع العميل "
                    f"{client.code if client else '—'}.",
            body_en=f"{request.user.short_name} added you to a group with client "
                    f"{client.code if client else '—'}.",
            level="info", url=f"/ops/chats/g/{room.id}/",
        )
    if added:
        services.system_message(
            room, key="members_added",
            body_ar="اتضاف للجروب: " + "، ".join(p.short_name for p in added),
            body_en="Added to the group: " + ", ".join(p.short_name for p in added),
        )
        services.log(request.user, "group.add_members", client.code if client else "-",
                     ", ".join(p.short_name for p in added)[:120])

    error = ""
    if refused:
        error = "مش ينفع تضيف " + "، ".join(refused) + " — التاسك دي مش من حقهم."
    return JsonResponse({
        "ok": bool(added),
        "added": [p.short_name for p in added],
        "error": error or ("" if added else "دول في الجروب أصلاً."),
    })


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


def _resolve_reply(client, reply_uid, viewer):
    """Turn a thread uid ("in-12" / "out-5") into a WhatsApp id and a snippet.

    The uid comes from the browser, so the row is re-fetched and checked against
    this client — a uid from another client's thread must not quote into here.
    Rate-blocked messages are hidden from the operation role, so the same filter
    applies: quoting one would put its text back on screen and on the client's
    phone, which is precisely what the block exists to prevent.
    """
    reply_uid = (reply_uid or "").strip()
    if "-" not in reply_uid:
        return "", ""
    side, _, raw = reply_uid.partition("-")
    try:
        pk = int(raw)
    except (TypeError, ValueError):
        return "", ""

    if side == "in":
        row = services._visible_inbound(client, viewer).filter(pk=pk).first()
        return (row.external_id or "", (row.body or "")[:160]) if row else ("", "")
    if side == "out":
        row = OutboundMessage.objects.filter(pk=pk, client=client).first()
        return (row.provider_id or "", (row.body or "")[:160]) if row else ("", "")
    return "", ""


@api_role_required(Role.OPERATION)
@require_POST
def client_chat_send(request, client_code):
    client = _client_or_404(request, client_code)
    reply_wamid, reply_preview = _resolve_reply(client, request.POST.get("reply_uid", ""), request.user)
    ok, outbound, error = services.send_client_message(
        client,
        request.user,
        body=request.POST.get("body", ""),
        uploads=request.FILES.getlist("files"),
        voice=request.FILES.get("voice"),
        voice_seconds=_int(request.POST.get("seconds"), 0),
        reply_to_wamid=reply_wamid,
        reply_preview=reply_preview,
        # This page is the WhatsApp line. Without pinning it, a reply typed
        # here would leave by e-mail whenever the client's most recent message
        # happened to be one — which the page no longer even shows.
        force_channel=Channel.WHATSAPP,
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

    # Blank boxes mean "read the files" - the same ones the automatic check
    # reads, so a re-run by hand cannot quietly look at something else.
    if not source_text.strip() or not translated_text.strip():
        from_files_source, from_files_translated = ai.collect_texts(task)
        source_text = source_text or from_files_source
        translated_text = translated_text or from_files_translated

    requirements = ai.requirements_text(task)

    result = ai.run_check(task, user, source_text, translated_text, requirements)
    return JsonResponse({
        "ok": result.status != result.Status.ERROR,
        "status": result.status,
        "summary": result.summary,
        "issues": result.issues,
        "error": result.error_message,
        "count": result.issue_count,
    })


# ---------------------------------------------------------------------------
# Attendance
#
# The location in these payloads is read by the browser at the instant the
# person presses the button and is sent with that one request. Nothing polls a
# position, and the server stores what arrived on the punch and nothing else.
# ---------------------------------------------------------------------------

def _client_ip(request):
    forwarded = request.META.get("HTTP_X_FORWARDED_FOR", "")
    if forwarded:
        return forwarded.split(",")[0].strip()
    return request.META.get("REMOTE_ADDR") or None


def _decimal(value):
    try:
        return Decimal(str(value)).quantize(Decimal("0.000001"))
    except (InvalidOperation, TypeError, ValueError):
        return None


def _day_json(row, plan=None):
    if row is None:
        return {
            "state": "none",
            "check_in": None,
            "check_out": None,
            "break_minutes": 0,
            "on_break": False,
            "late_minutes": 0,
            "work_minutes": 0,
            "needs_review": False,
        }
    return {
        "state": "closed" if row.check_out else ("open" if row.check_in else "none"),
        "date": row.date.isoformat(),
        "check_in": timezone.localtime(row.check_in).strftime("%H:%M") if row.check_in else None,
        "check_out": timezone.localtime(row.check_out).strftime("%H:%M") if row.check_out else None,
        "break_minutes": row.break_minutes,
        "on_break": row.on_break,
        "late_minutes": row.late_minutes,
        "work_minutes": row.work_minutes,
        "overtime_minutes": row.overtime_minutes,
        "hours": row.hours_display,
        "work_mode": row.work_mode,
        "needs_review": row.needs_review,
        "review_reason": row.review_reason,
        "schedule": row.schedule_label,
    }


@login_required
@require_GET
def attendance_state(request):
    """What the buttons should look like right now."""
    user = request.user
    day, plan = attendance.resolve_work_date(user)
    row = WorkDay.objects.filter(user=user, date=day).first()
    return JsonResponse({
        "ok": True,
        "enabled": user.attendance_enabled,
        "work_date": day.isoformat(),
        "planned": plan.working,
        "schedule": plan.label,
        "work_mode": row.work_mode if row is not None else plan.mode,
        "needs_location": (row.is_office_day if row is not None else plan.mode == "office"),
        "day": _day_json(row, plan),
    })


@login_required
@require_POST
def attendance_punch(request):
    """Check in, start or end a break, check out.

    A refusal comes back as ``ok: false`` with a bilingual reason rather than
    an HTTP error, because every one of them is a thing the person can act on:
    check in first, close the break, move closer to the office.
    """
    kind = request.POST.get("action", "")
    if kind not in PunchKind.values:
        return JsonResponse({"ok": False, "error": "bad_action"}, status=400)

    try:
        row, event = attendance.punch(
            request.user, kind,
            latitude=_decimal(request.POST.get("lat")),
            longitude=_decimal(request.POST.get("lng")),
            accuracy_m=_int(request.POST.get("accuracy"), 0) or None,
            fingerprint=(request.POST.get("device") or "").strip()[:64],
            ip=_client_ip(request),
            user_agent=request.META.get("HTTP_USER_AGENT", ""),
            note=(request.POST.get("note") or "")[:160],
        )
    except attendance.PunchRefused as refused:
        return JsonResponse(
            {"ok": False, "error": refused.code, "ar": refused.ar, "en": refused.en},
            status=200,
        )

    return JsonResponse({
        "ok": True,
        "action": kind,
        "at": timezone.localtime(event.at).strftime("%H:%M"),
        "day": _day_json(row),
    })
