"""Workflow engine for Eagle Phase 1.

Everything that mutates the state machine lives here so views stay thin and the
same logic can be reused by the webhooks, the management commands and the API.
"""

from datetime import timedelta

from django.db import transaction
from django.db.models import Q
from django.utils import timezone

from .models import (
    ACTIVE_TASK_STATUSES,
    AppSettings,
    Assignment,
    AssignmentStatus,
    AuditLog,
    Channel,
    ChatMessage,
    ChatRoom,
    Client,
    InboundMessage,
    Notification,
    OutboundMessage,
    Role,
    RoomKind,
    Task,
    TaskStatus,
    User,
)


# ---------------------------------------------------------------------------
# Notifications
# ---------------------------------------------------------------------------

def notify(user, *, title_ar, title_en, body_ar="", body_en="", level="info",
           url="", sound=False, task=None):
    if user is None:
        return None
    return Notification.objects.create(
        user=user, title_ar=title_ar, title_en=title_en,
        body_ar=body_ar, body_en=body_en, level=level,
        url=url, sound=sound, task=task,
    )


def notify_role(role, **kwargs):
    for user in User.objects.filter(role=role, is_active=True):
        notify(user, **kwargs)


def log(actor, action, target="", detail=""):
    AuditLog.objects.create(actor=actor, action=action, target=target, detail=detail)


# ---------------------------------------------------------------------------
# Inbound messages
# ---------------------------------------------------------------------------

def detect_rate_keyword(text):
    """Return the first rate-related keyword found in ``text`` (or '')."""
    haystack = (text or "").lower()
    for keyword in AppSettings.load().keyword_list:
        if keyword and keyword in haystack:
            return keyword
    return ""


def resolve_client(*, phone="", email="", channel="whatsapp", auto_create=True):
    """Map an incoming identity onto a client, creating a coded stub if needed."""
    client = None
    if phone:
        digits = "".join(ch for ch in phone if ch.isdigit())
        if digits:
            client = Client.objects.filter(phone__endswith=digits[-9:]).first()
    if client is None and email:
        client = Client.objects.filter(email__iexact=email).first()
    if client is None and auto_create:
        client = Client.objects.create(
            name="", phone=phone or "", email=email or "",
            admin_notes=f"Auto-created from an inbound {channel} message.",
        )
    return client


@transaction.atomic
def ingest_message(*, channel, body="", subject="", sender_identity="",
                   sender_display="", external_id="", received_at=None,
                   attachments=None):
    """Create an :class:`InboundMessage` and fan out the notifications."""
    if external_id:
        existing = InboundMessage.objects.filter(external_id=external_id).first()
        if existing:
            return existing

    is_email = "@" in (sender_identity or "")
    client = resolve_client(
        phone="" if is_email else sender_identity,
        email=sender_identity if is_email else "",
        channel=channel,
    )
    keyword = detect_rate_keyword(f"{subject} {body}")

    message = InboundMessage.objects.create(
        client=client,
        channel=channel,
        external_id=external_id or "",
        sender_identity=sender_identity or "",
        sender_display=sender_display or "",
        subject=subject or "",
        body=body or "",
        received_at=received_at or timezone.now(),
        is_rate_blocked=bool(keyword),
        blocked_keyword=keyword,
    )

    for item in attachments or []:
        message.attachments.create(
            file=item["file"],
            original_name=item.get("name", ""),
            size=item.get("size", 0),
        )

    code = client.code if client else "UNKNOWN"
    if keyword:
        notify_role(
            Role.ADMIN,
            title_ar="رسالة محجوبة عن الأوبريشن",
            title_en="Message hidden from Operation",
            body_ar=f"رسالة من العميل {code} فيها كلمة «{keyword}».",
            body_en=f"A message from client {code} contains “{keyword}”.",
            level="warning",
            url="/ops/inbox/",
        )
    else:
        for user in User.objects.filter(role__in=[Role.OPERATION, Role.ADMIN], is_active=True):
            notify(
                user,
                title_ar="رسالة جديدة من عميل",
                title_en="New client message",
                body_ar=f"وصلت رسالة جديدة من العميل {code}.",
                body_en=f"A new message arrived from client {code}.",
                level="info",
                url="/ops/inbox/",
                sound=user.is_operation,
            )
    return message


def inbox_queryset(user, state="", query=""):
    """The operation inbox, filtered identically for the page and the live feed."""
    from django.db.models import Q

    qs = InboundMessage.objects.select_related("client", "claimed_by", "task").prefetch_related(
        "attachments"
    )
    # Rate talk never reaches the operation role.
    if not user.is_admin_role:
        qs = qs.filter(is_rate_blocked=False)

    if state == "unclaimed":
        qs = qs.filter(claimed_by__isnull=True)
    elif state == "mine":
        qs = qs.filter(claimed_by=user)
    elif state == "notask":
        qs = qs.filter(task__isnull=True)

    query = (query or "").strip()
    if query:
        qs = qs.filter(Q(body__icontains=query) | Q(client__code__icontains=query))
    return qs


def claim_message(message, user):
    if message.claimed_by_id:
        return False
    message.claimed_by = user
    message.claimed_at = timezone.now()
    message.save(update_fields=["claimed_by", "claimed_at"])
    log(user, "message.claim", message.client_code)
    return True


# ---------------------------------------------------------------------------
# Chat rooms
# ---------------------------------------------------------------------------

def ensure_room(task, kind):
    room, created = ChatRoom.objects.get_or_create(task=task, kind=kind)
    members = [task.created_by, task.team_lead]
    if kind == RoomKind.GROUP:
        members.append(task.translator)
    members = [m for m in members if m is not None]
    if members:
        room.members.add(*members)
    if created:
        system_message(
            room,
            key="room_opened",
            body_ar="تم فتح الشات. ابعت الملفات هنا.",
            body_en="Chat opened. Share the files here.",
        )
    return room


def system_message(room, *, key, body_ar, body_en):
    return ChatMessage.objects.create(
        room=room, is_system=True, system_key=key,
        body=f"{body_ar} {body_en}",
    )


def rooms_for(task, user):
    qs = task.rooms.all()
    if user.is_admin_role:
        return qs
    return qs.filter(members=user).distinct()


# ---------------------------------------------------------------------------
# Assignments
# ---------------------------------------------------------------------------

def _cancel_pending(task, exclude_id=None):
    qs = task.assignments.filter(status=AssignmentStatus.PENDING)
    if exclude_id:
        qs = qs.exclude(pk=exclude_id)
    qs.update(status=AssignmentStatus.CANCELLED, responded_at=timezone.now())


@transaction.atomic
def assign_to_lead(task, lead, by_user, note=""):
    conf = AppSettings.load()
    _cancel_pending(task)
    now = timezone.now()
    assignment = Assignment.objects.create(
        task=task, assignee=lead, assigned_by=by_user,
        target_role=Role.TEAM_LEAD, assigned_at=now,
        expires_at=now + timedelta(seconds=conf.response_window_seconds),
        note=note,
    )
    task.team_lead = lead
    task.status = TaskStatus.AWAITING_LEAD
    task.lead_accepted_at = None
    task.save(update_fields=["team_lead", "status", "lead_accepted_at", "updated_at"])

    notify(
        lead,
        title_ar="تاسك جديدة محتاجة تأكيد",
        title_en="New task needs your confirmation",
        body_ar=f"عندك {conf.response_window_seconds} ثانية تأكد استلام التاسك {task.code}.",
        body_en=f"You have {conf.response_window_seconds}s to accept task {task.code}.",
        level="warning", url=f"/tasks/{task.code}/", sound=True, task=task,
    )
    log(by_user, "task.assign_lead", task.code, f"→ {lead}")
    return assignment


@transaction.atomic
def assign_to_translator(task, translator, by_user, note=""):
    conf = AppSettings.load()
    _cancel_pending(task)
    now = timezone.now()
    assignment = Assignment.objects.create(
        task=task, assignee=translator, assigned_by=by_user,
        target_role=Role.TRANSLATOR, assigned_at=now,
        expires_at=now + timedelta(seconds=conf.response_window_seconds),
        note=note,
    )
    task.translator = translator
    task.status = TaskStatus.AWAITING_TRANSLATOR
    task.translator_accepted_at = None
    task.save(update_fields=["translator", "status", "translator_accepted_at", "updated_at"])

    notify(
        translator,
        title_ar="تاسك ترجمة جديدة",
        title_en="New translation task",
        body_ar=f"عندك {conf.response_window_seconds} ثانية تأكد استلام التاسك {task.code}.",
        body_en=f"You have {conf.response_window_seconds}s to accept task {task.code}.",
        level="warning", url=f"/tasks/{task.code}/", sound=True, task=task,
    )
    log(by_user, "task.assign_translator", task.code, f"→ {translator}")
    return assignment


@transaction.atomic
def accept_assignment(assignment, user):
    """Confirm an assignment. Returns ``(ok, reason)``."""
    if assignment.assignee_id != user.id:
        return False, "forbidden"
    if assignment.status != AssignmentStatus.PENDING:
        return False, assignment.status
    if timezone.now() >= assignment.expires_at:
        expire_assignment(assignment)
        return False, "expired"

    assignment.status = AssignmentStatus.ACCEPTED
    assignment.responded_at = timezone.now()
    assignment.save(update_fields=["status", "responded_at"])

    task = assignment.task
    if assignment.target_role == Role.TEAM_LEAD:
        task.status = TaskStatus.LEAD_ACCEPTED
        task.lead_accepted_at = timezone.now()
        task.save(update_fields=["status", "lead_accepted_at", "updated_at"])
        room = ensure_room(task, RoomKind.OPS_LEAD)
        system_message(
            room, key="lead_accepted",
            body_ar=f"{user.short_name} استلم التاسك.",
            body_en=f"{user.short_name} accepted the task.",
        )
        notify(
            task.created_by,
            title_ar="التيم ليدر استلم التاسك",
            title_en="Team leader accepted",
            body_ar=f"{user.short_name} أكد استلام {task.code}. ابعتله الملفات في الشات.",
            body_en=f"{user.short_name} accepted {task.code}. Send the files in the chat.",
            level="success", url=f"/tasks/{task.code}/", task=task,
        )
    else:
        task.status = TaskStatus.IN_PROGRESS
        task.translator_accepted_at = timezone.now()
        task.save(update_fields=["status", "translator_accepted_at", "updated_at"])
        room = ensure_room(task, RoomKind.GROUP)
        system_message(
            room, key="group_opened",
            body_ar=f"جروب التاسك {task.code} اتفتح: أوبريشن + تيم ليدر + مترجم.",
            body_en=f"Group chat for {task.code} opened: Operation + Team leader + Translator.",
        )
        for person in (task.created_by, task.team_lead):
            notify(
                person,
                title_ar="المترجم استلم التاسك",
                title_en="Translator accepted",
                body_ar=f"{user.short_name} أكد استلام {task.code}.",
                body_en=f"{user.short_name} accepted {task.code}.",
                level="success", url=f"/tasks/{task.code}/", task=task,
            )
        if task.deadline:
            notify(
                user,
                title_ar="الديدلاين بتاع التاسك",
                title_en="Task deadline",
                body_ar=f"ديدلاين {task.code}: {timezone.localtime(task.deadline):%Y-%m-%d %H:%M}",
                body_en=f"Deadline for {task.code}: {timezone.localtime(task.deadline):%Y-%m-%d %H:%M}",
                level="info", url=f"/tasks/{task.code}/", task=task,
            )
    log(user, "assignment.accept", task.code)
    return True, "accepted"


@transaction.atomic
def expire_assignment(assignment):
    """Mark a pending assignment as expired, apply the penalty and alert."""
    if assignment.status != AssignmentStatus.PENDING:
        return assignment
    conf = AppSettings.load()
    assignment.status = AssignmentStatus.EXPIRED
    assignment.responded_at = timezone.now()
    task = assignment.task

    if not assignment.penalty_applied:
        assignment.penalty_applied = True
        assignment.assignee.apply_penalty(
            task,
            reason_en=f"No response within {conf.response_window_seconds}s on {task.code}",
            reason_ar=f"لم يرد خلال {conf.response_window_seconds} ثانية على {task.code}",
        )
    assignment.save(update_fields=["status", "responded_at", "penalty_applied"])

    notify(
        assignment.assignee,
        title_ar="خصم من التقييم",
        title_en="Rating penalty",
        body_ar=f"معدتش على تاسك {task.code} في الوقت، اتخصم {conf.penalty_value} نجمة.",
        body_en=f"You missed task {task.code}, {conf.penalty_value} star deducted.",
        level="danger", url=f"/tasks/{task.code}/", task=task,
    )

    if assignment.target_role == Role.TEAM_LEAD:
        task.status = TaskStatus.NEW
        task.team_lead = None
        task.save(update_fields=["status", "team_lead", "updated_at"])
        for user in User.objects.filter(role__in=[Role.OPERATION, Role.ADMIN], is_active=True):
            notify(
                user,
                title_ar="التيم ليدر مردش — تصرف",
                title_en="Team leader did not respond",
                body_ar=f"{assignment.assignee.short_name} مردش على {task.code}. اعمل assign لتيم ليدر تاني.",
                body_en=f"{assignment.assignee.short_name} missed {task.code}. Assign another team leader.",
                level="danger", url=f"/tasks/{task.code}/", sound=True, task=task,
            )
    else:
        task.status = TaskStatus.LEAD_ACCEPTED
        task.translator = None
        task.save(update_fields=["status", "translator", "updated_at"])
        notify(
            task.team_lead,
            title_ar="المترجم مردش — تصرف",
            title_en="Translator did not respond",
            body_ar=f"{assignment.assignee.short_name} مردش على {task.code}. اعمل assign لمترجم تاني.",
            body_en=f"{assignment.assignee.short_name} missed {task.code}. Assign another translator.",
            level="danger", url=f"/tasks/{task.code}/", sound=True, task=task,
        )
        notify(
            task.created_by,
            title_ar="المترجم مردش",
            title_en="Translator did not respond",
            body_ar=f"التاسك {task.code} رجعت للتيم ليدر عشان يعيد التوزيع.",
            body_en=f"Task {task.code} went back to the team leader for reassignment.",
            level="warning", url=f"/tasks/{task.code}/", task=task,
        )
    log(None, "assignment.expire", task.code, str(assignment.assignee))
    return assignment


def decline_assignment(assignment, user):
    if assignment.assignee_id != user.id or assignment.status != AssignmentStatus.PENDING:
        return False
    assignment.status = AssignmentStatus.DECLINED
    assignment.responded_at = timezone.now()
    assignment.save(update_fields=["status", "responded_at"])
    task = assignment.task
    if assignment.target_role == Role.TEAM_LEAD:
        task.status = TaskStatus.NEW
        task.team_lead = None
        task.save(update_fields=["status", "team_lead", "updated_at"])
        target = task.created_by
    else:
        task.status = TaskStatus.LEAD_ACCEPTED
        task.translator = None
        task.save(update_fields=["status", "translator", "updated_at"])
        target = task.team_lead
    notify(
        target,
        title_ar="تم رفض التاسك",
        title_en="Assignment declined",
        body_ar=f"{user.short_name} رفض التاسك {task.code}.",
        body_en=f"{user.short_name} declined task {task.code}.",
        level="warning", url=f"/tasks/{task.code}/", sound=True, task=task,
    )
    log(user, "assignment.decline", task.code)
    return True


# ---------------------------------------------------------------------------
# Task lifecycle
# ---------------------------------------------------------------------------

@transaction.atomic
def create_task(*, client, title, created_by, description="", deadline=None,
                priority="normal", source_lang="", target_lang="", messages=None):
    task = Task.objects.create(
        client=client, title=title, created_by=created_by,
        description=description, deadline=deadline, priority=priority,
        source_lang=source_lang, target_lang=target_lang,
        status=TaskStatus.NEW,
    )
    for message in messages or []:
        message.task = task
        message.save(update_fields=["task"])
    log(created_by, "task.create", task.code)
    return task


def mark_translated(task, user):
    if task.translator_id != user.id and not user.is_admin_role:
        return False
    task.status = TaskStatus.UNDER_REVIEW
    task.translated_at = timezone.now()
    task.save(update_fields=["status", "translated_at", "updated_at"])
    room = ensure_room(task, RoomKind.GROUP)
    system_message(
        room, key="translated",
        body_ar=f"{user.short_name} خلص الترجمة وبعت الملفات للمراجعة.",
        body_en=f"{user.short_name} finished the translation and sent the files for review.",
    )
    notify(
        task.team_lead,
        title_ar="ترجمة جاهزة للمراجعة",
        title_en="Translation ready for review",
        body_ar=f"التاسك {task.code} جاهزة للمراجعة.",
        body_en=f"Task {task.code} is ready for your review.",
        level="info", url=f"/tasks/{task.code}/", sound=True, task=task,
    )
    notify(
        task.created_by,
        title_ar="المترجم خلص",
        title_en="Translator finished",
        body_ar=f"التاسك {task.code} تحت مراجعة التيم ليدر.",
        body_en=f"Task {task.code} is under the team leader's review.",
        level="info", url=f"/tasks/{task.code}/", task=task,
    )
    log(user, "task.translated", task.code)
    return True


def mark_reviewed(task, user):
    if task.team_lead_id != user.id and not user.is_admin_role:
        return False
    task.status = TaskStatus.REVIEWED
    task.reviewed_at = timezone.now()
    task.save(update_fields=["status", "reviewed_at", "updated_at"])
    room = ensure_room(task, RoomKind.GROUP)
    system_message(
        room, key="reviewed",
        body_ar=f"{user.short_name} أنهى المراجعة. الأوبريشن يقدر يسلّم للعميل.",
        body_en=f"{user.short_name} completed the review. Operation can deliver to the client.",
    )
    notify(
        task.created_by,
        title_ar="تمت المراجعة",
        title_en="Review completed",
        body_ar=f"التاسك {task.code} اتراجعت. تقدر تبعت الملفات للعميل.",
        body_en=f"Task {task.code} is reviewed. You can send the files to the client.",
        level="success", url=f"/tasks/{task.code}/", sound=True, task=task,
    )
    notify(
        task.translator,
        title_ar="تمت مراجعة ترجمتك",
        title_en="Your translation was reviewed",
        body_ar=f"التيم ليدر خلص مراجعة {task.code}.",
        body_en=f"The team leader reviewed {task.code}.",
        level="success", url=f"/tasks/{task.code}/", task=task,
    )
    log(user, "task.reviewed", task.code)
    return True


def client_channel(client):
    """How we last heard from this client — that's how we answer back."""
    last = client.messages.order_by("-received_at").first()
    if last and last.channel in (Channel.WHATSAPP, Channel.EMAIL):
        return last.channel
    if client.phone:
        return Channel.WHATSAPP
    if client.email:
        return Channel.EMAIL
    return ""


def _read_attachment(attachment):
    """Return ``(filename, bytes, mime)`` for a stored chat attachment."""
    from . import whatsapp as wa

    name = attachment.original_name or attachment.file.name.rsplit("/", 1)[-1]
    attachment.file.open("rb")
    try:
        content = attachment.file.read()
    finally:
        attachment.file.close()
    return name, content, wa.guess_mime(name)


def deliver_to_client(task, user, attachment_ids=None, note="", send=True):
    """Send the finished files to the client, then close the task.

    Returns ``(ok, delivery, error)``. On a send failure the task stays at
    ``reviewed`` so the operation can fix things and try again.
    """
    from . import mailer, whatsapp as wa
    from .models import ChatAttachment, OutboundMessage

    conf = AppSettings.load()
    client = task.client
    channel = client_channel(client)
    target = client.phone if channel == Channel.WHATSAPP else client.email

    attachments = list(
        ChatAttachment.objects.filter(
            id__in=list(attachment_ids or []), message__room__task=task
        ).order_by("id")
    )

    delivery = OutboundMessage(
        task=task, client=client, created_by=user, channel=channel,
        to_identity=target or "", body=note,
        files=[{"name": a.original_name or a.file.name, "status": "pending"} for a in attachments],
    )

    if not send:
        delivery.status = OutboundMessage.Status.SKIPPED
        delivery.save()
        mark_delivered(task, user, delivery=delivery)
        return True, delivery, ""

    if not channel or not target:
        delivery.status = OutboundMessage.Status.FAILED
        delivery.error_message = (
            "العميل ده مفيش عنده رقم واتساب ولا إيميل مسجل — ضيفهم من صفحة العميل."
        )
        delivery.save()
        return False, delivery, delivery.error_message

    payload = [_read_attachment(a) for a in attachments]
    caption = note or f"{task.title} — {task.code}"

    try:
        if channel == Channel.WHATSAPP:
            if note:
                delivery.provider_id = wa.send_text(target, note)
            for index, (name, content, mime) in enumerate(payload):
                wa.send_file(target, content, name, mime, caption="" if note else caption)
                delivery.files[index]["status"] = "sent"
            if not payload and not note:
                delivery.provider_id = wa.send_text(target, caption)
        else:
            mailer.send_delivery(
                conf, target,
                subject=f"{task.title} — {task.code}",
                body=note or "مرفق الملفات المترجمة. شكرًا لتعاملكم معنا.",
                attachments=payload,
            )
            for entry in delivery.files:
                entry["status"] = "sent"
    except (wa.WhatsAppError, mailer.MailError) as exc:
        delivery.status = OutboundMessage.Status.FAILED
        delivery.error_message = exc.message_ar
        delivery.save()
        log(user, "task.deliver_failed", task.code, exc.message_en[:200])
        notify(
            user,
            title_ar="التسليم فشل",
            title_en="Delivery failed",
            body_ar=exc.message_ar[:380],
            body_en=exc.message_en[:380],
            level="danger", url=f"/tasks/{task.code}/", task=task,
        )
        return False, delivery, exc.message_ar

    delivery.status = OutboundMessage.Status.SENT
    delivery.save()
    mark_delivered(task, user, delivery=delivery)
    return True, delivery, ""


def mark_delivered(task, user, delivery=None):
    if not (user.is_operation or user.is_admin_role):
        return False
    task.status = TaskStatus.DELIVERED
    task.delivered_at = timezone.now()
    task.save(update_fields=["status", "delivered_at", "updated_at"])

    if delivery is not None and delivery.status == delivery.Status.SENT:
        channel = delivery.get_channel_display()
        detail_ar = f"اتبعت {delivery.file_count} ملف للعميل على {channel}."
        detail_en = f"{delivery.file_count} file(s) sent to the client over {channel}."
    else:
        detail_ar = "التاسك اتقفلت من غير إرسال من السيستم."
        detail_en = "Task closed without sending from the system."

    for room in task.rooms.all():
        system_message(room, key="delivered", body_ar=detail_ar, body_en=detail_en)
    for person in task.participants():
        notify(
            person,
            title_ar="تم التسليم",
            title_en="Delivered",
            body_ar=f"التاسك {task.code} اتسلمت للعميل.",
            body_en=f"Task {task.code} was delivered to the client.",
            level="success", url=f"/tasks/{task.code}/", task=task,
        )
    log(user, "task.delivered", task.code)
    return True


def cancel_task(task, user, reason=""):
    task.status = TaskStatus.CANCELLED
    task.save(update_fields=["status", "updated_at"])
    _cancel_pending(task)
    for person in task.participants():
        notify(
            person,
            title_ar="تم إلغاء التاسك",
            title_en="Task cancelled",
            body_ar=f"التاسك {task.code} اتلغت. {reason}",
            body_en=f"Task {task.code} was cancelled. {reason}",
            level="warning", url=f"/tasks/{task.code}/", task=task,
        )
    log(user, "task.cancel", task.code, reason)
    return True


# ---------------------------------------------------------------------------
# Client conversations — the WhatsApp-style chat with the client
# ---------------------------------------------------------------------------
#
# A conversation is not stored as its own table. It is simply everything we
# ever exchanged with one client: ``InboundMessage`` rows coming in and
# ``OutboundMessage`` rows going out, merged on time. That way the chat and
# the task deliveries live in the same thread and nothing is duplicated.

def client_conversations(user, query=""):
    """One row per client we have ever talked to, most recent activity first."""
    from django.db.models import Max

    if user.is_admin_role:
        rows = Client.objects.filter(messages__isnull=False)
    else:
        # One filter, one join: the operation never sees a conversation made
        # only of rate-blocked messages, and the Max below then reflects only
        # the messages that role is allowed to know about.
        rows = Client.objects.filter(messages__is_rate_blocked=False)
    rows = rows.annotate(last_activity=Max("messages__received_at")).distinct()

    query = (query or "").strip()
    if query:
        if user.is_admin_role:
            rows = rows.filter(
                Q(code__icontains=query)
                | Q(name__icontains=query)
                | Q(company__icontains=query)
                | Q(phone__icontains=query)
            )
        else:
            rows = rows.filter(code__icontains=query)

    return rows.order_by("-last_activity")


def _visible_inbound(client, user):
    qs = client.messages.prefetch_related("attachments")
    if not user.is_admin_role:
        qs = qs.filter(is_rate_blocked=False)
    return qs


def conversation_preview(client, user):
    """The snippet shown in the conversation list."""
    last = _visible_inbound(client, user).order_by("-received_at").first()
    out = client.deliveries.order_by("-created_at").first()
    if out and last and out.created_at > last.received_at:
        text = out.body or (f"{out.file_count} ملف" if out.file_count else "—")
        return {"text": text[:70], "at": out.created_at, "outgoing": True}
    if last:
        text = last.body or (f"{last.attachments.count()} ملف" if last.attachments.exists() else "—")
        return {"text": text[:70], "at": last.received_at, "outgoing": False}
    return {"text": "", "at": None, "outgoing": False}


def client_thread(client, user, limit=200):
    """Merged inbound + outbound timeline for one client, oldest first."""
    items = []

    for row in _visible_inbound(client, user).order_by("-received_at")[:limit]:
        items.append({
            "kind": "in",
            "id": row.id,
            "uid": f"in-{row.id}",
            "body": row.body,
            "subject": row.subject,
            "channel": row.channel,
            "at": row.received_at,
            "blocked": row.is_rate_blocked,
            "task_code": row.task.code if row.task_id else "",
            "files": [
                {"url": a.file.url, "name": a.original_name or a.file.name, "size": a.size}
                for a in row.attachments.all()
            ],
        })

    outbound = client.deliveries.select_related("created_by", "task").prefetch_related("uploads")
    for row in outbound.order_by("-created_at")[:limit]:
        files = [
            {"url": a.file.url, "name": a.original_name or a.file.name, "size": a.size}
            for a in row.uploads.all()
        ]
        # Task deliveries keep their file list in JSON (the bytes went straight
        # to WhatsApp), so show the names without a link.
        if not files:
            files = [{"url": "", "name": f.get("name", ""), "size": 0} for f in (row.files or [])]
        items.append({
            "kind": "out",
            "id": row.id,
            "uid": f"out-{row.id}",
            "body": row.body,
            "subject": "",
            "channel": row.channel,
            "at": row.created_at,
            "blocked": False,
            "status": row.status,
            "error": row.error_message,
            "is_delivery": row.kind == OutboundMessage.Kind.DELIVERY,
            "task_code": row.task.code if row.task_id else "",
            "sender": row.created_by.short_name if row.created_by_id else "",
            "files": files,
        })

    items.sort(key=lambda entry: entry["at"])
    return items


def send_client_message(client, user, body="", uploads=None):
    """Free-form reply to a client on whichever channel they used last.

    Returns ``(ok, outbound, error_ar)``. Nothing is ever silently dropped —
    a failure is stored as a FAILED row so it stays visible in the thread.
    """
    from . import mailer, whatsapp as wa
    from .models import OutboundAttachment, OutboundMessage

    uploads = list(uploads or [])
    body = (body or "").strip()
    if not body and not uploads:
        return False, None, "مفيش حاجة تتبعت."

    conf = AppSettings.load()
    channel = client_channel(client)
    target = client.phone if channel == Channel.WHATSAPP else client.email

    outbound = OutboundMessage.objects.create(
        client=client, task=None, kind=OutboundMessage.Kind.CHAT,
        created_by=user, channel=channel, to_identity=target or "", body=body,
        files=[{"name": item.name, "status": "pending"} for item in uploads],
    )
    stored = [
        OutboundAttachment.objects.create(
            message=outbound, file=item, original_name=item.name, size=item.size
        )
        for item in uploads
    ]

    if not channel or not target:
        outbound.status = OutboundMessage.Status.FAILED
        outbound.error_message = (
            "العميل ده مفيش عنده رقم واتساب ولا إيميل مسجل — ضيفهم من صفحة العميل."
        )
        outbound.save(update_fields=["status", "error_message"])
        return False, outbound, outbound.error_message

    payload = [_read_attachment(a) for a in stored]

    try:
        if channel == Channel.WHATSAPP:
            if body:
                outbound.provider_id = wa.send_text(target, body)
            for index, (name, content, mime) in enumerate(payload):
                wa.send_file(target, content, name, mime, caption="" if body else name)
                outbound.files[index]["status"] = "sent"
        else:
            mailer.send_delivery(
                conf, target,
                subject=f"Eagle — {client.code}",
                body=body or "مرفق الملفات.",
                attachments=payload,
            )
            for entry in outbound.files:
                entry["status"] = "sent"
    except (wa.WhatsAppError, mailer.MailError) as exc:
        outbound.status = OutboundMessage.Status.FAILED
        outbound.error_message = exc.message_ar
        outbound.save(update_fields=["status", "error_message", "files"])
        log(user, "client.reply_failed", client.code, exc.message_en[:200])
        return False, outbound, exc.message_ar

    outbound.status = OutboundMessage.Status.SENT
    outbound.save(update_fields=["status", "provider_id", "files"])
    log(user, "client.reply", client.code, (body or f"{len(payload)} file(s)")[:120])
    return True, outbound, ""


# ---------------------------------------------------------------------------
# Housekeeping — run on every heartbeat
# ---------------------------------------------------------------------------

def sweep_expired_assignments():
    now = timezone.now()
    stale = Assignment.objects.filter(
        status=AssignmentStatus.PENDING, expires_at__lte=now
    ).select_related("task", "assignee")
    count = 0
    for assignment in stale:
        expire_assignment(assignment)
        count += 1
    return count


def sweep_deadlines():
    conf = AppSettings.load()
    now = timezone.now()
    threshold = now + timedelta(minutes=conf.deadline_warning_minutes)
    warned = 0

    upcoming = Task.objects.filter(
        status__in=ACTIVE_TASK_STATUSES,
        deadline__isnull=False,
        deadline__lte=threshold,
        deadline__gt=now,
        deadline_warned_at__isnull=True,
    ).select_related("translator", "team_lead", "created_by")
    for task in upcoming:
        task.deadline_warned_at = now
        task.save(update_fields=["deadline_warned_at"])
        minutes = max(1, int((task.deadline - now).total_seconds() // 60))
        for person, sound in ((task.translator, True), (task.team_lead, False), (task.created_by, False)):
            notify(
                person,
                title_ar="تحذير: الديدلاين قرب",
                title_en="Deadline approaching",
                body_ar=f"فاضل {minutes} دقيقة على ديدلاين {task.code}.",
                body_en=f"{minutes} minutes left before the deadline of {task.code}.",
                level="warning", url=f"/tasks/{task.code}/", sound=sound, task=task,
            )
        warned += 1

    late = Task.objects.filter(
        status__in=ACTIVE_TASK_STATUSES,
        deadline__isnull=False,
        deadline__lt=now,
        deadline_missed_notified=False,
    ).select_related("translator", "team_lead", "created_by")
    for task in late:
        task.deadline_missed_notified = True
        task.save(update_fields=["deadline_missed_notified"])
        for person in (task.translator, task.team_lead, task.created_by):
            notify(
                person,
                title_ar="الديدلاين فات",
                title_en="Deadline missed",
                body_ar=f"التاسك {task.code} عدت الديدلاين.",
                body_en=f"Task {task.code} passed its deadline.",
                level="danger", url=f"/tasks/{task.code}/", sound=True, task=task,
            )
    return warned


def heartbeat(user):
    """Called from the browser poller: refresh presence + run housekeeping."""
    User.objects.filter(pk=user.pk).update(last_seen=timezone.now())
    sweep_expired_assignments()
    sweep_deadlines()


# ---------------------------------------------------------------------------
# Team overview for the Operation screen
# ---------------------------------------------------------------------------

def team_overview():
    """Team leaders with their live availability and team load."""
    rows = []
    leads = User.objects.filter(role=Role.TEAM_LEAD, is_active=True).prefetch_related(
        "team_members", "shifts"
    )
    for lead in leads:
        members = [m for m in lead.team_members.all() if m.is_active]
        busy, free, offline = [], [], []
        for member in members:
            if not member.is_online:
                offline.append(member)
            elif member.is_busy:
                busy.append(member)
            else:
                free.append(member)
        rows.append({
            "lead": lead,
            "online": lead.is_online,
            "lead_tasks": lead.active_task_count,
            "members": members,
            "busy": busy,
            "free": free,
            "offline": offline,
            "total": len(members),
        })
    rows.sort(key=lambda r: (not r["online"], -len(r["free"])))
    return rows
