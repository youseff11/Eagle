"""JSON endpoints powering the live parts of the dashboard (polling based)."""

from decimal import Decimal, InvalidOperation

from django.contrib.auth.decorators import login_required
from django.db import transaction
from django.http import Http404, JsonResponse
from django.shortcuts import get_object_or_404
from django.utils import timezone
from django.views.decorators.http import require_GET, require_POST

from . import ai, attendance, avatars, chatlists, clock, identity, services
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
    InboundMessage,
    Notification,
    OutboundMessage,
    PunchKind,
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
        "created": clock.fmt12(item.created_at, "en"),
        "sender": _sender_json(item.sender) if item.sender_id else None,
    }


def _sender_json(person):
    """Who wrote a notification a person wrote (technical support's announcement): the name, picture and role beside it."""
    return {"id": person.pk, "name": person.short_name, "initials": person.initials, "avatar": avatars.url_of(person), "role": person.role}


def _stamp(moment):
    return clock.fmt12(moment, "en", "%Y-%m-%d") if moment else ""


def _pending_json(assignment, viewer):
    task = assignment.task
    return {
        "id": assignment.id,
        "task_code": task.code,
        "task_title": task.title_for(viewer),
        "task_url": f"/tasks/{task.code}/",
        "client": task.client.label_for(viewer),
        "role": assignment.target_role,
        "seconds_left": assignment.seconds_left,
        "window": AppSettings.load().response_window_seconds,
        "assigned_by": assignment.assigned_by.short_name if assignment.assigned_by else "",
        # Where the files were dropped, so they can be read before deciding.
        # "Read the files first" opens a page of the job itself - files,
        # description and time left - not the chat they were dropped in.
        "files_url": f"/assignments/{assignment.id}/",
        "open_url": f"/api/assignments/{assignment.id}/files/",
        "priority": task.priority,
        # The date that governs whoever is being asked to take this on: a
        # translator is shown theirs, never what the client was promised.
        "deadline": _stamp(task.deadline_for(viewer)),
        # For the live "time left" line under it.
        "deadline_iso": task.deadline_for(viewer).isoformat() if task.deadline_for(viewer) else "",
        # Typed by the sender, who writes the client's name in it: for a person who may not know it, the code.
        "note": identity.mask_client(assignment.note, task.client, viewer),
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
    fresh = Notification.objects.filter(user=user, id__gt=after).select_related("sender").order_by("id")[:20]

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
            # the chat list. Unopened, not unclaimed: a badge that ignores
            # your own reading is a badge you stop looking at.
            "inbox": services.unseen_conversation_count(user),
            "new_tasks": Task.objects.filter(status=TaskStatus.NEW).count(),
            "ready": Task.objects.filter(status=TaskStatus.REVIEWED).count(),
        }
    elif user.is_sales:
        # Their own mail line's badge; the chats badge is added below.
        data["counters"] = {"inbox": services.unseen_conversation_count(user)}
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
    # Every role has the chats page, so every role gets its badge: messages
    # waiting in any tab of it that this person has not opened yet.
    data["counters"]["chats"] = services.unread_chat_total(user)
    # A colleague calling: every page rings.
    data["call"] = services.incoming_call(user)
    # Live pages: a board re-fetches itself when this moves, and a task page
    # follows its own task.
    data["live"] = services.live_stamp()
    # The check-in screen: opens by itself when a shift starts, even on a page
    # that was already open.
    data["attendance"] = attendance.gate_for(user)
    code = (request.GET.get("task") or "").strip()
    if code:
        task = Task.objects.filter(code=code).first()
        if task is not None and task.can_view(user):
            data["task_live"] = services.task_live_stamp(task)
    return JsonResponse(data)


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
    return clock.fmt12(stamp, lang, "%Y-%m-%d")


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
    if assignment.assignee_id != request.user.pk and not request.user.is_admin_role:
        identity.hidden(request, "assignment")
    ok, reason = services.accept_assignment(assignment, request.user)
    return JsonResponse({"ok": ok, "reason": reason, "task": assignment.task.code})


@login_required
@require_POST
def decline_assignment(request, pk):
    """Refuse a hand-off. The reason is not optional - see the service."""
    assignment = get_object_or_404(Assignment, pk=pk)
    if assignment.assignee_id != request.user.pk and not request.user.is_admin_role:
        identity.hidden(request, "assignment")
    ok, error = services.decline_assignment(
        assignment, request.user, reason=request.POST.get("reason", "")
    )
    return JsonResponse(
        {"ok": ok, "error": error, "task": assignment.task.code},
        status=200 if ok else 400,
    )


@login_required
@require_POST
def open_assignment_files(request, pk):
    """Record that the assignee opened the files, without deciding anything.

    Looking is not accepting. Keeping the two apart is what lets somebody read
    a contract before they commit to it, instead of accepting blind because a
    countdown is running.
    """
    assignment = get_object_or_404(Assignment, pk=pk)
    if assignment.assignee_id != request.user.pk:
        identity.hidden(request, "assignment")
    if assignment.opened_at is None:
        assignment.opened_at = timezone.now()
        assignment.save(update_fields=["opened_at"])
    return JsonResponse({"ok": True, "url": f"/assignments/{assignment.id}/"})


@api_role_required(Role.OPERATION)
@require_POST
def assign_lead(request, code):
    task = get_object_or_404(Task, code=code)
    lead = get_object_or_404(User, pk=request.POST.get("user"), role=Role.TEAM_LEAD, is_active=True)
    # Handing a job to a leader is the first step of its way: a job already with a leader, being worked, delivered or cancelled
    # is not handed out again from here.
    if task.status not in (TaskStatus.NEW, TaskStatus.AWAITING_LEAD):
        return JsonResponse({"ok": False, "error": "bad_status"}, status=400)
    assignment = services.assign_to_lead(
        task, lead, request.user, note=request.POST.get("note", "")[:250]
    )
    return JsonResponse({"ok": True, "assignment": assignment.id, "status": task.status})


@api_role_required(Role.OPERATION)
@require_POST
def assign_translator_direct(request, code):
    """A new task straight to a translator, for when no team leader has the site open.

    The server decides that, not the page: with any leader online the answer is ``lead_online`` and nothing happens, so
    the way past a leader cannot be used while there is one to ask. The translator has to be one who has a leader
    (``services.direct_translators``): that leader keeps the review.
    """
    task = get_object_or_404(Task, code=code)
    translator = get_object_or_404(User, pk=request.POST.get("user"), role=Role.TRANSLATOR, is_active=True)
    if task.status not in (TaskStatus.NEW, TaskStatus.AWAITING_LEAD):
        return JsonResponse({"ok": False, "error": "bad_status"}, status=400)
    if services.leads_online():
        return JsonResponse({"ok": False, "error": "lead_online"}, status=400)
    if not translator.team_lead_id or not translator.team_lead.is_active:
        return JsonResponse({"ok": False, "error": "no_leader"}, status=400)
    assignment = services.assign_direct_to_translator(
        task, translator, request.user, note=request.POST.get("note", "")[:250]
    )
    return JsonResponse({"ok": True, "assignment": assignment.id, "status": task.status})


@api_role_required(Role.TEAM_LEAD)
@require_POST
def assign_translator(request, code):
    task = get_object_or_404(Task, code=code)
    user = request.user
    if not user.is_admin_role and task.team_lead_id != user.id:
        # Another leader's job is not found (a 403 would say the code exists), and the try is written down.
        identity.hidden(request, "task")
    translator = get_object_or_404(User, pk=request.POST.get("user"), role=Role.TRANSLATOR, is_active=True)
    if not user.is_admin_role and translator.team_lead_id != user.id:
        return JsonResponse({"ok": False, "error": "not_in_your_team"}, status=403)
    if task.status not in (TaskStatus.LEAD_ACCEPTED, TaskStatus.AWAITING_TRANSLATOR):
        return JsonResponse({"ok": False, "error": "bad_status"}, status=400)

    # The date the leader is handing over with the job. Blank keeps the
    # client's, which is what happened before they could choose.
    from django import forms

    from .forms import DeadlineField

    field = DeadlineField(required=False)
    typed = field.widget.value_from_datadict(request.POST, request.FILES, "tdeadline")
    try:
        their_deadline = field.clean(typed)
    except forms.ValidationError as problem:
        return JsonResponse({"ok": False, "error": problem.messages[0]}, status=400)
    problem = services.deadline_problem(task, their_deadline)
    if problem:
        return JsonResponse({"ok": False, "error": problem}, status=400)

    assignment = services.assign_to_translator(
        task, translator, user, note=request.POST.get("note", "")[:250],
        deadline=their_deadline,
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
        identity.hidden(request, "task")

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

    # "Finished" needs something finished: the translator's file on the task.
    # Said here in words; the service refuses on its own as well.
    if action == "translated" and services.translation_missing(task):
        return JsonResponse({
            "ok": False, "code": "no_translation_file",
            # The action buttons toast ``error`` as it is, so it is the sentence.
            "error": services.TRANSLATION_MISSING_AR,
            "error_en": services.TRANSLATION_MISSING_EN,
        }, status=400)

    ok = handler()
    task.refresh_from_db()
    return JsonResponse({
        "ok": bool(ok),
        "status": task.status,
        "review_score": task.review_score,
        "revision_count": task.revision_count,
    })


@login_required
@require_POST
def upload_translation(request, code):
    """The translator's file, from the task page, into their group."""
    task = get_object_or_404(
        Task.objects.select_related("team_lead", "translator"), code=code
    )
    user = request.user
    if not task.can_view(user):
        identity.hidden(request, "task")
    message, error = services.upload_translation(
        task, user, request.FILES.getlist("files"), request.POST.get("body", ""),
    )
    if message is None:
        status = 403 if error == "forbidden" else 400
        return JsonResponse({"ok": False, "error": error}, status=status)
    return JsonResponse({
        "ok": True,
        "message": _message_json(message, user),
        "room": message.room_id,
    })


@login_required
@require_POST
def hand_in_from_chat(request, code):
    """«خلصت التاسك» in the group: these files are the translation, it is done."""
    task = get_object_or_404(Task.objects.select_related("team_lead"), code=code)
    user = request.user
    if not task.can_view(user):
        identity.hidden(request, "task")
    ok, error = services.hand_in_from_chat(task, user, request.POST.getlist("files"))
    if not ok:
        return JsonResponse({"ok": False, "error": error}, status=400)
    return JsonResponse({"ok": True, "url": f"/tasks/{task.code}/"})


@login_required
@require_POST
def request_extension(request, code):
    """The translator asks for more time: days / hours / minutes, and why."""
    task = get_object_or_404(Task.objects.select_related("team_lead"), code=code)
    user = request.user
    if not task.can_view(user):
        identity.hidden(request, "task")
    minutes = (
        _int(request.POST.get("days"), 0) * 24 * 60
        + _int(request.POST.get("hours"), 0) * 60
        + _int(request.POST.get("minutes"), 0)
    )
    row, error = services.request_extension(
        task, user, minutes, request.POST.get("reason", "")
    )
    if row is None:
        return JsonResponse({"ok": False, "error": error}, status=400)
    return JsonResponse({"ok": True, "id": row.pk})


@login_required
@require_POST
def decide_extension(request, pk, decision):
    """The team leader's yes or no."""
    from .models import ExtensionRequest

    row = get_object_or_404(
        ExtensionRequest.objects.select_related("task", "task__team_lead", "task__translator"),
        pk=pk,
    )
    user = request.user
    if not row.task.can_view(user):
        identity.hidden(request, "task")
    if decision not in ("approve", "decline"):
        return JsonResponse({"ok": False, "error": "unknown_decision"}, status=400)
    ok, error = services.decide_extension(
        row, user, decision == "approve", request.POST.get("note", "")
    )
    if not ok:
        status = 403 if row.task.team_lead_id != user.id and not user.is_admin_role else 400
        return JsonResponse({"ok": False, "error": error}, status=status)
    return JsonResponse({"ok": True})


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


@api_role_required(Role.OPERATION)
@require_POST
def set_deadline(request, code):
    """Set the deadline from the days / hours / minutes boxes.

    Borrows the form field rather than parsing here, so the three rules —
    blank leaves it alone, zeros clear it, numbers count from now — are
    written down once and this page cannot drift from the others.

    A plain ``deadline=<iso>`` still works, for anything that posted the old
    way before the boxes existed.
    """
    from django import forms
    from django.utils.dateparse import parse_datetime

    from .forms import DeadlineField

    task = get_object_or_404(Task, code=code)
    raw = request.POST.get("deadline", "").strip()
    if raw:
        parsed = parse_datetime(raw)
        if parsed is None:
            return JsonResponse({"ok": False, "error": "bad_date"}, status=400)
        if timezone.is_naive(parsed):
            parsed = timezone.make_aware(parsed, timezone.get_current_timezone())
    else:
        field = DeadlineField(required=False)
        typed = field.widget.value_from_datadict(request.POST, request.FILES, "deadline")
        try:
            parsed = field.clean(typed)
        except forms.ValidationError as problem:
            return JsonResponse(
                {"ok": False, "error": "bad_date", "detail": problem.messages[0]},
                status=400,
            )
    task.deadline = parsed
    task.deadline_warned_at = None
    task.deadline_missed_notified = False
    task.save(update_fields=[
        "deadline", "deadline_warned_at", "deadline_missed_notified", "updated_at"
    ])

    # Shortening the client's date can leave the translator on a later one.
    # Pulling theirs back tells them; otherwise the person doing the work is
    # the only one who was not told the job moved.
    pulled = services.cap_translator_deadline(task, request.user)

    if task.translator_id and not pulled:
        # Their own date, which is not the client's when the leader set one.
        due = task.translator_due
        services.notify(
            task.translator,
            title_ar="اتحدد ديدلاين جديد",
            title_en="Deadline updated",
            body_ar=f"ديدلاين {task.code}: {clock.fmt12(due, 'ar', '%Y-%m-%d')}" if due else "الديدلاين اتشال.",
            body_en=f"Deadline for {task.code}: {clock.fmt12(due, 'en', '%Y-%m-%d')}" if due else "Deadline cleared.",
            level="info", url=f"/tasks/{task.code}/", sound=True, task=task,
        )
    return JsonResponse({"ok": True})


@api_role_required(Role.TEAM_LEAD)
@require_POST
def set_translator_deadline(request, code):
    """The leader's own date for the translator — shorter than the client's.

    The gap between the two is what the leader keeps for review. Blank
    boxes clear it, and then the translator works to the client's date
    again, which is what every task did before this existed.
    """
    from django import forms

    from .forms import DeadlineField

    task = get_object_or_404(Task, code=code)
    user = request.user
    if not user.is_admin_role and task.team_lead_id != user.id:
        return JsonResponse({"ok": False, "error": "not_your_task"}, status=403)

    field = DeadlineField(required=False)
    typed = field.widget.value_from_datadict(request.POST, request.FILES, "tdeadline")
    try:
        moment = field.clean(typed)
    except forms.ValidationError as problem:
        return JsonResponse({"ok": False, "error": problem.messages[0]}, status=400)

    ok, error = services.set_translator_deadline(task, moment, user)
    if not ok:
        return JsonResponse({"ok": False, "error": error}, status=400)
    return JsonResponse({"ok": True})


# ---------------------------------------------------------------------------
# Inbound messages
# ---------------------------------------------------------------------------


@api_role_required(Role.OPERATION, Role.SALES)
@require_POST
def mail_reply(request, pk):
    """Answer the conversation ``pk`` is in: text, files, or both, by e-mail.

    The answer says whether it went and, when a letter was made (a failed one is kept, marked failed, the way the chat keeps
    a failed send visible instead of losing it), its id.
    """
    anchor = get_object_or_404(
        InboundMessage.objects.select_related("client"), pk=pk, channel=Channel.EMAIL
    )
    if not anchor.visible_to(request.user):
        identity.hidden(request, "mail")
    ok, outbound, error = services.reply_to_thread(
        anchor, request.user,
        body=request.POST.get("body", ""),
        uploads=request.FILES.getlist("files"),
    )
    payload = {"ok": ok, "error": error}
    if outbound is not None:
        payload["id"] = outbound.pk
    return JsonResponse(payload, status=200 if ok else 400)


@api_role_required(Role.OPERATION, Role.SALES)
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
    if not message.visible_to(request.user):
        identity.hidden(request, "mail")
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
        identity.hidden(request, "room")
    if room.task_id and not room.task.can_view(request.user):
        identity.hidden(request, "task")
    return room


def _message_json(message, viewer):
    from_client = message.from_client
    return {
        "id": message.id,
        "body": services.words_of(message, viewer),
        "system": message.is_system,
        "unsent": message.unsent_at is not None,
        "sender": message.sender.short_name if message.sender_id else "",
        "sender_id": message.sender_id or 0,
        "role": message.sender.role if message.sender_id else "",
        "initials": message.sender.initials if message.sender_id else "•",
        # The colleague's own picture, drawn by the staff's pages only (nothing here is relayed to a client).
        "avatar": avatars.url_of(message.sender) if message.sender_id else None,
        "mine": message.sender_id == viewer.id,
        "time": clock.fmt12(message.created_at, "en"),
        "date": timezone.localtime(message.created_at).strftime("%Y-%m-%d"),
        # Relay bookkeeping — only ever set in a client room.
        "from_client": from_client,
        "relay_status": message.relay_status,
        "relay_error": identity.for_viewer(message.relay_error, viewer),
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


def _prepare_voice(upload):
    """A browser recording, converted for WhatsApp: ``(content, name, error)``.

    Converting before storing means the room and the client hold the same
    bytes — the same rule the client chat follows. It is done before the
    message is written (it takes a moment), and the error is the words for a
    recording that could not be converted (it is kept as it is).
    """
    from . import audio

    raw = upload.read()
    name = upload.name or "voice"
    mime = audio.base_mime(getattr(upload, "content_type", ""))
    error = ""
    try:
        content, name, mime = audio.prepare(raw, name, mime)
    except audio.AudioError as exc:
        content, error = raw, exc.message_ar
    return content, name, error


def _store_voice(message, prepared):
    """Save what ``_prepare_voice`` made as a chat attachment of ``message``."""
    from django.core.files.base import ContentFile

    content, name, _error = prepared
    ChatAttachment.objects.create(
        message=message,
        file=ContentFile(content, name=name),
        original_name=services.short_name(name),
        size=len(content),
    )


def pick_refusal(error, choices):
    """The 400 that says files have to name their task (``pick_task``), or named one that is not theirs (``bad_task``)."""
    text = {
        "pick_task": (services.PICK_TASK_AR, services.PICK_TASK_EN),
        "bad_task": (services.BAD_TASK_AR, services.BAD_TASK_EN),
    }[error]
    return JsonResponse({
        "ok": False, "error": error,
        "message": text[0], "message_en": text[1],
        "choices": [{"code": t.code, "title": t.title} for t in choices],
    }, status=400)


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
        pk=reply_id, room=room, is_system=False, unsent_at__isnull=True
    ).first() if reply_id else None

    # Files sent in a staff chat or a work group are asked which task they
    # are for, before anything is written - see services.pick_file_task.
    picked_task, picking = None, False
    if uploads and room.kind in (RoomKind.STAFF, RoomKind.TEAM):
        raw_task = request.POST.get("task", "")
        picked_task, pick_error, choices = services.pick_file_task(
            request.user, room, raw_task
        )
        if pick_error:
            return pick_refusal(pick_error, choices)
        picking = bool(choices) or raw_task.strip() == services.NO_TASK

    # The recording is converted first: it takes a moment, and the message must not wait in the open for it.
    prepared = _prepare_voice(voice) if voice is not None else None
    voice_error = prepared[2] if prepared else ""

    # The message and its files are one write. Written one by one, a colleague's page that was told about the
    # message (and asked for it) between the two drew it with nothing in it, and then drew it again with the
    # photo or the player a moment later; the pings go out when the whole is saved (`realtime.push_room`).
    with transaction.atomic():
        message = ChatMessage.objects.create(
            room=room, sender=request.user, body=body, reply_to=reply_to,
        )
        for item in uploads:
            ChatAttachment.objects.create(
                message=message, file=item, original_name=services.short_name(item.name), size=item.size
            )
        if prepared is not None:
            _store_voice(message, prepared)

    # Files handed over in a one-to-one chat are work on a task when the two
    # of them have exactly one running between them. See tag_task_message -
    # it refuses to guess, which is why this can be automatic at all.
    if picked_task is not None:
        message.task = picked_task
        message.save(update_fields=["task"])
    elif picking:
        pass  # The sender said these files are not on a task.
    elif uploads or voice is not None:
        services.tag_task_message(message)

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
    staff = room.kind == RoomKind.STAFF
    where = task.code if task else (room.title or room.display_title)
    if task:
        url = f"/tasks/{task.code}/?room={room.id}"
    elif staff:
        url = f"/ops/chats/u/{request.user.pk}/"
    else:
        url = f"/ops/chats/g/{room.id}/"
    # A membership row can outlive the assignment; the notification body quotes
    # the message, so put each member to the test of opening the room rather
    # than trusting the row. In a client room that is also what keeps a
    # translator seated there by hand from being sent the operation's reply.
    # Whoever the words name with "@" (and the page picked) is told so, instead of the ordinary line below.
    mentioned = services.mention_targets(room, request.user, body, request.POST.get("mentions"))
    if mentioned:
        message.mentions.set(mentioned)
    mentioned_ids = {person.pk for person in mentioned}
    # Muted by a member: the ordinary line is not sent to them. A mention still is - it names them.
    silenced = services.muted_user_ids(room=room)
    for member in room.members.exclude(pk=request.user.pk):
        if not room.can_open(member):
            continue
        if member.pk not in mentioned_ids and member.pk in silenced:
            continue
        if member.pk in mentioned_ids:
            preview = identity.for_viewer(body[:60], member)
            services.notify(
                member,
                title_ar=f"{request.user.short_name} عمل لك منشن",
                title_en=f"{request.user.short_name} mentioned you",
                body_ar=f"في {where}: {preview}",
                body_en=f"In {where}: {preview}",
                level="info", url=url, sound=True, task=task,
            )
            continue
        services.notify(
            member,
            title_ar="رسالة جديدة في الشات",
            title_en="New chat message",
            body_ar=(
                f"{request.user.short_name}: {(body or 'ملفات')[:60]}" if staff
                else f"{request.user.short_name} في {where}: {(body or 'ملفات')[:60]}"
            ),
            body_en=(
                f"{request.user.short_name}: {(body or 'files')[:60]}" if staff
                else f"{request.user.short_name} in {where}: {(body or 'files')[:60]}"
            ),
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
    if not request.user.handles_clients:
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
        # Drawn only under a message that carries a document — see
        # ``services.client_thread``.
        "has_docs": entry.get("has_docs", False),
        "claimed_by": entry.get("claimed_by", ""),
        "has_task": entry.get("has_task", False),
        "body": entry["body"],
        "subject": entry.get("subject", ""),
        "channel": entry.get("channel", ""),
        "status": entry.get("status", ""),
        "error": identity.for_viewer(entry.get("error", ""), viewer),
        "sender": entry.get("sender", ""),
        # By id as well: a name is not unique, and the page uses it to tell its own messages from a colleague's.
        "sender_id": entry.get("sender_id", 0),
        # Their picture, when a colleague wrote it: for the staff's own screen, never a part of anything relayed.
        "sender_avatar": entry.get("sender_avatar"),
        "task_code": entry.get("task_code", ""),
        "is_delivery": entry.get("is_delivery", False),
        "quote": entry.get("quote", ""),
        "quote_who": entry.get("quote_who", ""),
        "time": clock.fmt12(entry["at"], "en"),
        "date": timezone.localtime(entry["at"]).strftime("%Y-%m-%d"),
        "files": entry.get("files", []),
        # The ticks: "" (sent), "delivered" or "read" - see services.
        "mine": entry.get("mine", False),
        "receipt": entry.get("receipt", ""),
        "seen_by": entry.get("seen_by", []),
        "forwarded": entry.get("forwarded", False),
        # The colleagues the message pinged, and whether it pinged the viewer: a work group's only.
        "mentions": entry.get("mentions", []),
        "mentions_me": entry.get("mentions_me", False),
        "reactions": entry.get("reactions", []),
        "reactions_sig": entry.get("reactions_sig", ""),
        "unsent": entry.get("unsent", False),
        "can_unsend": entry.get("can_unsend", False),
    }


def _conversation_json(client, viewer, unread=0, facts=None, muted=None):
    """One client's row. ``facts`` is what ``chatlists.client_facts`` fetched for a whole list;
    without it the row asks for itself, which is what a single conversation does. ``muted`` is whether this person muted
    it, known for a whole list at once; left out, it is asked of the database here."""
    if muted is None:
        muted = services.is_muted(viewer, client=client)
    if facts is None:
        facts = {
            "preview": services.conversation_preview(client, viewer),
            "window": client.reply_window_for(viewer),
            "channel": services.client_channel(client),
        }
    preview = facts["preview"]
    # Each line has its own 24 hours - the window of the number this person
    # would answer from, not whichever number the client wrote to last.
    window_open, minutes_left = facts["window"]
    return {
        "code": client.code,
        "group": False,
        "url": f"/ops/chats/{client.code}/",
        "label": client.label_for(viewer),
        "text": preview["text"],
        "outgoing": preview["outgoing"],
        "status": preview.get("status", ""),
        "receipt": preview.get("receipt", ""),
        "time": clock.fmt12(preview["at"], "en"),
        "date": timezone.localtime(preview["at"]).strftime("%Y-%m-%d") if preview["at"] else "",
        # The 24-hour rule is a WhatsApp rule — e-mail has no such window.
        "channel": facts["channel"],
        "window_open": window_open,
        "minutes_left": minutes_left,
        "unread": unread,
        "muted": muted,
    }


def _group_json(room, viewer, unread=0, facts=None, muted=None):
    """A group in the same shape as a 1:1 conversation, so one list renders both.

    ``facts`` is what ``chatlists.group_facts`` fetched for a whole list; without it the row asks
    for itself. ``muted`` as in ``_conversation_json``."""
    if muted is None:
        muted = services.is_muted(viewer, room=room)
    client = room.relay_client
    if facts is None:
        facts = {"preview": services.group_preview(room, viewer)}
        if client:
            facts["window"] = client.reply_window_for(viewer)
            facts["channel"] = services.client_channel(client)
    preview = facts["preview"]
    # The 24-hour window of the line this person answers from, as in
    # ``_conversation_json`` - not whichever line the client wrote to last,
    # which would tell the operation when the client spoke to a Sales number.
    window_open, minutes_left = facts.get("window", (False, 0))
    if room.kind == RoomKind.STAFF:
        person = room.other_member(viewer)
        return {
            "code": f"u{person.pk}" if person else f"g{room.id}",
            "group": False,
            "staff": True,
            "role": person.role if person else "",
            "room": room.id,
            "url": f"/ops/chats/u/{person.pk}/" if person else "",
            "label": room.title_for(viewer),
            "initials": person.initials if person else "?",
            "avatar": avatars.url_of(person) if person else None,
            "client_code": "",
            "text": preview["text"],
            "outgoing": preview["outgoing"],
            "status": preview.get("status", ""),
            "receipt": preview.get("receipt", ""),
            "time": clock.fmt12(preview["at"], "en"),
            "date": timezone.localtime(preview["at"]).strftime("%Y-%m-%d") if preview["at"] else "",
            "channel": "",
            "window_open": False,
            "minutes_left": 0,
            "unread": unread,
            "muted": muted,
        }
    return {
        "code": f"g{room.id}",
        "group": True,
        "team": room.is_team_group,
        "reaches_client": room.reaches_client,
        "room": room.id,
        "url": f"/ops/chats/g/{room.id}/",
        "label": room.display_title,
        "client_code": client.code if client else "",
        "text": preview["text"],
        "outgoing": preview["outgoing"],
        "status": preview.get("status", ""),
        "receipt": preview.get("receipt", ""),
        "time": clock.fmt12(preview["at"], "en"),
        "date": timezone.localtime(preview["at"]).strftime("%Y-%m-%d") if preview["at"] else "",
        "channel": facts.get("channel", ""),
        "window_open": window_open,
        "minutes_left": minutes_left,
        "unread": unread,
        "muted": muted,
    }


@login_required
@require_GET
def client_chat_list(request):
    """Feeds the chats sidebar.

    Any signed-in member can poll it — they only ever get their own groups —
    but the 1:1 list is the whole client directory, so it stays with the roles
    that own the client inbox.
    """
    query = request.GET.get("q", "")
    kind = request.GET.get("type", "clients")
    sees_all_clients = request.user.handles_clients
    if kind == "staff":
        # The order the service returns is the order the page wants: spoken
        # to most recently, then the rest of the directory. Sorting by date
        # here would push everyone never written to into a random heap.
        items = []
        muted_rooms, _muted_clients = services.muted_ids(request.user)
        people = services.staff_conversations(request.user, query)
        unread = services.unread_by_room(
            request.user, [row["room"].id for row in people if row["room"] is not None]
        )
        for row in people:
            person, preview = row["person"], row["preview"]
            items.append({
                "code": f"u{person.pk}",
                "group": False,
                "staff": True,
                "role": person.role,
                "room": row["room"].id if row["room"] else 0,
                "url": f"/ops/chats/u/{person.pk}/",
                "label": person.short_name,
                "initials": person.initials,
                "avatar": avatars.url_of(person),
                "client_code": "",
                "text": preview["text"],
                "outgoing": preview["outgoing"],
                "status": preview.get("status", ""),
                "receipt": preview.get("receipt", ""),
                "time": clock.fmt12(preview["at"], "en"),
                "date": timezone.localtime(preview["at"]).strftime("%Y-%m-%d") if preview["at"] else "",
                "channel": "",
                "window_open": False,
                "minutes_left": 0,
                "unread": unread.get(row["room"].id, 0) if row["room"] else 0,
                "muted": bool(row["room"]) and row["room"].id in muted_rooms,
            })
        return JsonResponse({"ok": True, "items": items})

    items = []
    muted_rooms, muted_clients = services.muted_ids(request.user)
    if kind == "clients" and sees_all_clients:
        clients = list(services.client_conversations(request.user, query)[:100])
        unread = services.unread_by_client(request.user, [c.pk for c in clients])
        facts = chatlists.client_facts(request.user, clients)
        items += [
            (
                facts[row.pk]["preview"]["at"],
                _conversation_json(row, request.user, unread.get(row.pk, 0), facts[row.pk], row.pk in muted_clients),
            )
            for row in clients
        ]
    if kind == "groups":
        rooms = list(services.groups_for(request.user, query)[:100])
        unread = services.unread_by_room(request.user, [room.id for room in rooms])
        facts = chatlists.group_facts(request.user, rooms)
        items += [
            (
                facts[room.pk]["preview"]["at"],
                _group_json(room, request.user, unread.get(room.id, 0), facts[room.pk], room.pk in muted_rooms),
            )
            for room in rooms
        ]
    # Newest activity first, by the moment itself. The rows carry the time as text ("9:30 AM"), and as
    # text it sorts after "10:30 AM" and "11:00 PM" before "9:00 AM": the list was out of order within a day.
    items.sort(key=lambda pair: (pair[0] is not None, pair[0].timestamp() if pair[0] else 0), reverse=True)
    return JsonResponse({"ok": True, "items": [item for _when, item in items]})


# ---------------------------------------------------------------------------
# Calls between colleagues (the media itself is browser to browser)
# ---------------------------------------------------------------------------

def _call_json(call, viewer):
    other = call.other(viewer)
    return {
        "id": call.id, "status": call.status, "video": call.video,
        "caller": call.caller_id == viewer.pk,
        "other": other.short_name, "initials": other.initials,
        "answered_at": call.answered_at.isoformat() if call.answered_at else "",
    }


@login_required
@require_POST
def call_start(request):
    callee = User.objects.filter(pk=_int(request.POST.get("user")), is_active=True).first()
    call, error = services.start_call(
        request.user, callee, video=request.POST.get("video") == "1"
    )
    if call is None:
        return JsonResponse({"ok": False, "error": error}, status=400)
    return JsonResponse({
        "ok": True, "call": _call_json(call, request.user),
        "ice": services.ice_servers(request.user),
    })


@login_required
@require_POST
def call_answer(request, pk):
    call = services.call_for(request.user, pk)
    if call is None:
        identity.hidden(request, "call")
    ok = services.answer_call(call, request.user)
    return JsonResponse({
        "ok": ok, "call": _call_json(call, request.user), "ice": services.ice_servers(request.user),
        "error": "" if ok else "المكالمة خلصت.",
    }, status=200 if ok else 400)


@login_required
@require_POST
def call_end(request, pk):
    call = services.call_for(request.user, pk)
    if call is None:
        identity.hidden(request, "call")
    services.end_call(call, request.user, reason=request.POST.get("reason", "ended"))
    return JsonResponse({"ok": True, "call": _call_json(call, request.user)})


@login_required
def call_signals(request, pk):
    """GET: what the other end sent since ``after`` (and the call's state).
    POST: one offer / answer / network candidate for the other end."""
    call = services.call_for(request.user, pk)
    if call is None:
        identity.hidden(request, "call")
    if request.method == "POST":
        row = services.post_signal(
            call, request.user, request.POST.get("kind", ""), request.POST.get("payload", "")
        )
        return JsonResponse({"ok": row is not None}, status=200 if row else 400)
    return JsonResponse({
        "ok": True, "call": _call_json(call, request.user),
        "signals": services.signals_for(call, request.user, _int(request.GET.get("after"), 0)),
    })


@login_required
@require_GET
def search_tasks(request):
    """The tasks half of the nav search. Only tasks this person may open."""
    return JsonResponse({
        "ok": True,
        "items": services.search_tasks(request.user, request.GET.get("q", "")),
    })


@login_required
@require_POST
def team_group_create(request):
    """Open an internal work group: a name, some people, and no client."""
    members = list(User.objects.filter(
        pk__in=[_int(v) for v in request.POST.getlist("members") if _int(v)],
        is_active=True,
    ))
    room, error = services.create_team_group(
        request.user, title=request.POST.get("title", ""), members=members,
    )
    if room is None:
        status = 403 if "صلاحية" in error else 400
        return JsonResponse({"ok": False, "error": error}, status=status)
    return JsonResponse({"ok": True, "room": room.id, "url": f"/ops/chats/g/{room.id}/"})


def _group_or_404(request, room_id):
    """A room chat.js can drive: a client group, a work group, or a staff chat.

    Both are read and written through the same two endpoints; what separates
    them is inside ``chat_send``, which relays only a client room. A staff
    chat reaching the relay would be an internal conversation landing on a
    client's phone, so the kind is checked here and the relay checks it again.
    """
    room = get_object_or_404(
        ChatRoom.objects.select_related("client", "task"),
        pk=room_id, kind__in=(RoomKind.CLIENT, RoomKind.STAFF, RoomKind.TEAM),
    )
    if not room.can_access(request.user):
        identity.hidden(request, "room")
    if room.task_id and not room.task.can_view(request.user):
        identity.hidden(request, "task")
    return room


@login_required
@require_POST
def group_add_members(request, room_id):
    """Add people to a group. Same gate as creating one — it reaches a client."""
    room = _group_or_404(request, room_id)
    if room.kind == RoomKind.STAFF:
        # A one-to-one chat is one to one. A third person joining it would
        # hand them everything the two already said to each other.
        return JsonResponse(
            {"ok": False, "error": "ده شات بين اتنين — مينفعش تضيف حد."}, status=400
        )
    if room.is_team_group:
        if not request.user.can_create_team_group:
            return JsonResponse(
                {"ok": False, "error": "مالكش صلاحية تضيف أعضاء."}, status=403
            )
        wanted = [_int(v) for v in request.POST.getlist("members") if _int(v)]
        people = list(User.objects.filter(pk__in=wanted, is_active=True))
        if not people:
            return JsonResponse({"ok": False, "error": "اختار حد الأول."}, status=400)
        # Somebody already in is not added again: nothing to tell them, and no second "added" line in the room.
        seated = set(room.members.filter(pk__in=[p.pk for p in people]).values_list("pk", flat=True))
        people = [p for p in people if p.pk not in seated]
        if not people:
            return JsonResponse({"ok": False, "error": "دول في الجروب أصلاً."})
        room.members.add(*people)
        for person in people:
            services.system_message(
                room, key="member_added",
                body_ar=f"{request.user.short_name} ضاف {person.short_name}.",
                body_en=f"{request.user.short_name} added {person.short_name}.",
            )
            services.notify(
                person, level="info",
                title_ar="اتضافت لجروب شغل", title_en="Added to a work group",
                body_ar=f"{request.user.short_name} ضافك في «{room.display_title}».",
                body_en=f"{request.user.short_name} added you to \"{room.display_title}\".",
                url=f"/ops/chats/g/{room.id}/",
            )
        return JsonResponse({"ok": True, "added": [p.short_name for p in people]})
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
    added, refused, translators, outsiders = [], [], [], []
    for person in people:
        # A task-bound group must not hand the task's client conversation to
        # someone who is not on that task.
        if task is not None and not task.can_view(person):
            refused.append(person.short_name)
            continue
        # Nor may a translator be given a seat in a room that reaches the
        # client: they would be listed as a member and see nothing.
        if room.kind == RoomKind.CLIENT and person.is_translator:
            translators.append(person.short_name)
            continue
        # Only the people who talk to clients - the operation, Sales and the admin - are ever in a room with one.
        if room.kind == RoomKind.CLIENT and not person.handles_clients:
            outsiders.append(person.short_name)
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
    if translators:
        error = (error + " " if error else "") + (
            "مش ينفع تضيف " + "، ".join(translators) + " — المترجم مابيدخلش جروب فيه العميل."
        )
    if outsiders:
        error = (error + " " if error else "") + (
            "مش ينفع تضيف " + "، ".join(outsiders) + " — جروب العميل للأوبريشن والـSales بس."
        )
    return JsonResponse({
        "ok": bool(added),
        "added": [p.short_name for p in added],
        "error": error or ("" if added else "دول في الجروب أصلاً."),
    })


@login_required
@require_GET
def group_chat_fetch(request, room_id):
    room = _group_or_404(request, room_id)
    # Fetching is not reading: a phone showing the list, or a tab left in the background, fetches the same thread. A
    # conversation is read by saying so (``api_v1.group_read``).
    return JsonResponse({
        "ok": True,
        "client": _group_json(room, request.user),
        "messages": [
            _thread_entry_json(e, request.user)
            for e in services.group_thread(room, request.user)
        ],
    })


@api_role_required(Role.OPERATION, Role.SALES)
@require_GET
def client_chat_fetch(request, client_code):
    client = _client_or_404(request, client_code)
    # See group_chat_fetch: fetching is not reading.
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
        from . import lines

        row = OutboundMessage.objects.filter(pk=pk, client=client, channel=Channel.WHATSAPP).filter(
            lines.line_q(viewer)
        ).first()
        return (row.provider_id or "", (row.body or "")[:160]) if row else ("", "")
    return "", ""


def may_answer(client, user):
    """Can this person see a conversation with this client - one on a line they work?

    Answering clients is a role, but which clients is a line: an operation person who typed a code
    could otherwise write from the company number to a client who had only ever written to a Sales
    number, and any Sales person could write to any client from their own. What a person may not
    read they may not write to either: a message already seen on their line (the client's, or one
    of ours) is what makes the conversation theirs.

    The admin works every line and may open a conversation: nothing is asked of them, and no refusal
    is written down against them.
    """
    from . import lines

    if user.is_admin_role:
        return True
    if services._visible_inbound(client, user).exists():
        return True
    return client.deliveries.filter(channel=Channel.WHATSAPP).filter(lines.line_q(user)).exists()


def send_to_client(request, client):
    """The send itself: ``(ok, outbound, error_ar)``, and nothing else.

    A conversation the person has no line in is a 404, written down (``may_answer``), the same answer
    as for a code that does not exist. Whether the conversation counts as read afterwards is the
    caller's: the classic page says "answering is reading" for the whole thread, the new app says it
    only for what it showed (``/api/v1/``, ``mark_client_read(upto=)``).
    """
    if not may_answer(client, request.user):
        identity.hidden(request, "client")
    reply_wamid, reply_preview = _resolve_reply(client, request.POST.get("reply_uid", ""), request.user)
    return services.send_client_message(
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


# ---------------------------------------------------------------------------
# Client requirements
# ---------------------------------------------------------------------------


# ---------------------------------------------------------------------------
# AI review
# ---------------------------------------------------------------------------

@login_required
@require_POST
def ai_recheck(request, code):
    """«أعد الفحص» on the AI notes box: the automatic check, run again.

    The team leader of the task or the admin - the two who see the box. It
    runs in the background like the automatic one; the page follows it.
    """
    task = get_object_or_404(Task, code=code)
    user = request.user
    if not task.can_view(user):
        identity.hidden(request, "task")
    if not (user.is_admin_role or task.team_lead_id == user.id):
        return JsonResponse({"ok": False, "error": "مش مسموحلك."}, status=403)
    conf = AppSettings.load()
    if not conf.ai_check_enabled or not conf.claude_api_key:
        return JsonResponse({"ok": False, "error": "فحص الـAI متوقف من الإعدادات."}, status=400)
    if ai.start_background_check(task) is None:
        return JsonResponse({"ok": False, "error": "فيه فحص شغال دلوقتي على التاسك دي."}, status=400)
    services.log(user, "task.ai_recheck", task.code)
    return JsonResponse({"ok": True})


@login_required
@require_POST
def ai_check(request, code):
    task = get_object_or_404(Task, code=code)
    user = request.user
    if not task.can_view(user):
        identity.hidden(request, "task")

    conf = AppSettings.load()
    if not conf.ai_check_enabled:
        return JsonResponse({"ok": False, "error": "disabled"}, status=400)

    source_text = request.POST.get("source_text", "")
    translated_text = request.POST.get("translated_text", "")

    # Blank boxes mean "read the files" - the same ones the automatic check
    # reads, so a re-run by hand cannot quietly look at something else.
    source_docs, translated_docs = [], []
    if not source_text.strip() or not translated_text.strip():
        from_files_source, from_files_translated = ai.collect_texts(task)
        docs_source, docs_translated = ai.collect_documents(task)
        if not source_text.strip():
            source_text, source_docs = from_files_source, docs_source
        if not translated_text.strip():
            translated_text, translated_docs = from_files_translated, docs_translated

    requirements = ai.requirements_text(task)

    result = ai.run_check(
        task, user, source_text, translated_text, requirements,
        source_docs, translated_docs,
    )
    # The words come from reading the client's files and quote them: for whoever may not know the client the name and number
    # are taken out, as they are on every other page that shows a check.
    def masked(value):
        if isinstance(value, str):
            return identity.mask_client(value, task.client, user)
        if isinstance(value, list):
            return [masked(one) for one in value]
        if isinstance(value, dict):
            return {key: masked(one) for key, one in value.items()}
        return value

    return JsonResponse({
        "ok": result.status != result.Status.ERROR,
        "status": result.status,
        "summary": masked(result.summary),
        "issues": masked(result.issues),
        "error": masked(result.error_message),
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


def _day_json(row):
    return {
        "state": "closed" if row.check_out else ("open" if row.check_in else "none"),
        "date": row.date.isoformat(),
        "check_in": clock.fmt12(row.check_in, "en") or None,
        "check_out": clock.fmt12(row.check_out, "en") or None,
        "extra_started_at": clock.fmt12(row.extra_started_at, "en") or None,
        "extra_running": row.extra_running,
        "after_shift": bool(row.scheduled_end and timezone.now() >= row.scheduled_end),
        "checkout_missed": row.checkout_missed,
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
            # A fix worse than this is no fix: the allowance adds the accuracy to the office's radius, so an enormous one
            # would put any position inside.
            accuracy_m=min(max(_int(request.POST.get("accuracy"), 0), 0), attendance.MAX_ACCURACY_M) or None,
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
        "at": clock.fmt12(event.at, "en"),
        "late_minutes": row.late_minutes if kind == PunchKind.CHECK_IN else 0,
        "overtime_minutes": row.overtime_minutes if kind == PunchKind.CHECK_OUT else 0,
        "day": _day_json(row),
    })
