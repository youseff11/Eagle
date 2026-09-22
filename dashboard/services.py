"""Workflow engine for Eagle Phase 1.

Everything that mutates the state machine lives here so views stay thin and the
same logic can be reused by the webhooks, the management commands and the API.
"""

import logging
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

logger = logging.getLogger(__name__)


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
                   attachments=None, reply_to_external="", references=""):
    """Create an :class:`InboundMessage` and fan out the notifications.

    ``references`` is the e-mail ``References`` header. It is not stored; it
    only decides which conversation the letter joins.
    """
    from . import threads

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

    thread_key = ""
    if channel == Channel.EMAIL:
        thread_key = threads.find_thread_key(
            InboundMessage,
            channel=Channel.EMAIL,
            client_id=client.pk if client else None,
            sender=sender_identity or "",
            subject=subject or "",
            refs=threads.message_ids(reply_to_external, references),
            when=received_at,
            outbound_model=OutboundMessage,
        ) or threads.new_key()

    message = InboundMessage.objects.create(
        thread_key=thread_key,
        client=client,
        channel=channel,
        external_id=external_id or "",
        sender_identity=sender_identity or "",
        sender_display=sender_display or "",
        subject=subject or "",
        body=body or "",
        received_at=received_at or timezone.now(),
        reply_to_external=reply_to_external or "",
        is_rate_blocked=bool(keyword),
        blocked_keyword=keyword,
    )

    for item in attachments or []:
        message.attachments.create(
            file=item["file"],
            original_name=item.get("name", ""),
            size=item.get("size", 0),
            mime=item.get("mime", ""),
            is_voice=bool(item.get("is_voice")),
            duration=item.get("duration", 0) or 0,
        )

    code = client.code if client else "UNKNOWN"
    # The two channels now live on two pages, so the notification has to point
    # at the one the message is actually on. A link to an inbox that filters
    # this message out is worse than no link.
    is_mail = channel == Channel.EMAIL
    # A letter opens on its conversation, the replies before it included.
    where = (
        f"/ops/inbox/thread/{message.pk}/" if is_mail
        else (f"/ops/chats/{code}/" if client else "/ops/chats/")
    )
    if keyword:
        notify_role(
            Role.ADMIN,
            title_ar="رسالة محجوبة عن الأوبريشن",
            title_en="Message hidden from Operation",
            body_ar=f"رسالة من العميل {code} فيها كلمة «{keyword}».",
            body_en=f"A message from client {code} contains “{keyword}”.",
            level="warning",
            url=where,
        )
    else:
        for user in User.objects.filter(role__in=[Role.OPERATION, Role.ADMIN], is_active=True):
            notify(
                user,
                title_ar="ميل جديد من عميل" if is_mail else "رسالة جديدة من عميل",
                title_en="New client e-mail" if is_mail else "New client message",
                body_ar=(
                    f"وصل ميل جديد من العميل {code}." if is_mail
                    else f"وصلت رسالة جديدة من العميل {code}."
                ),
                body_en=(
                    f"A new e-mail arrived from client {code}." if is_mail
                    else f"A new message arrived from client {code}."
                ),
                level="info",
                url=where,
                sound=user.is_operation,
            )

    # If this client has a live task with a client room open, the team sees the
    # message there too — that room is the "group chat" they actually work in.
    #
    # on_commit + a swallowed exception on purpose: this runs inside an atomic
    # block that the webhook depends on. A failure here must never roll back
    # the InboundMessage itself, because Meta retries any non-200 forever.
    def _mirror():
        try:
            mirror_inbound_to_room(message)
        except Exception:  # noqa: BLE001
            logger.exception("Could not mirror inbound message %s into a room", message.pk)

    transaction.on_commit(_mirror)
    return message


def inbox_queryset(user, state="", query=""):
    """The e-mail inbox, filtered identically for the page and the live feed.

    E-mail only, on purpose. WhatsApp is a conversation and lives in the client
    chat; a mailbox is a list of letters and lives here. A message that is in
    both places is a message two people answer twice.
    """
    from django.db.models import Q

    qs = InboundMessage.objects.filter(channel=Channel.EMAIL).select_related(
        "client", "claimed_by", "task"
    ).prefetch_related("attachments")
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
        qs = qs.filter(
            Q(body__icontains=query)
            | Q(subject__icontains=query)
            | Q(client__code__icontains=query)
            | Q(sender_identity__icontains=query)
        )
    return qs


# ---------------------------------------------------------------------------
# Mail conversations
# ---------------------------------------------------------------------------

def _thread_ident(key, pk):
    """A letter keyed before threading existed is a conversation of its own."""
    return key or f"m{pk}"


def _visible_mail(user):
    """Every e-mail this user may read, with what a mail row needs loaded."""
    qs = InboundMessage.objects.filter(channel=Channel.EMAIL).select_related(
        "client", "claimed_by", "task"
    ).prefetch_related("attachments")
    if not user.is_admin_role:
        qs = qs.filter(is_rate_blocked=False)
    return qs


class MailThread:
    """One conversation on /ops/inbox/: the letters that answer each other.

    ``messages`` is oldest first — the order they are read in. The row on the
    list speaks for the newest one, the way Gmail's does. ``replies`` is what
    we sent into it from the conversation page (Gmail's "me").
    """

    def __init__(self, ident, messages, replies=()):
        self.key = ident
        self.messages = messages
        self.replies = list(replies)
        self.first = messages[0]
        self.latest = messages[-1]

    @property
    def count(self):
        return len(self.messages) + len(self.replies)

    @property
    def entries(self):
        """Their letters and our replies on one timeline, oldest first."""
        rows = [("in", m.received_at, m.pk, m) for m in self.messages]
        rows += [("out", r.created_at, r.pk, r) for r in self.replies]
        rows.sort(key=lambda row: (row[1], row[0] == "out", row[2]))
        return [{"kind": kind, "item": item} for kind, _at, _pk, item in rows]

    @property
    def answered(self):
        """Our reply is the last word — nothing from the client since."""
        sent = [r for r in self.replies if r.status == "sent"]
        return bool(sent) and sent[-1].created_at >= self.latest.received_at

    @property
    def last_reply_id(self):
        return max((r.pk for r in self.replies), default=0)

    @property
    def subject(self):
        # The subject the client first wrote, not "Re: Re: Fwd:" of the last.
        for message in self.messages:
            if (message.subject or "").strip():
                return message.subject
        return ""

    @property
    def client(self):
        return self.latest.client

    @property
    def unclaimed(self):
        return [m for m in self.messages if not m.claimed_by_id]

    @property
    def is_unread(self):
        return bool(self.unclaimed)

    @property
    def is_blocked(self):
        return any(m.is_rate_blocked for m in self.messages)

    @property
    def attachment_count(self):
        return sum(len(m.attachments.all()) for m in self.messages)

    @property
    def tasks(self):
        seen, tasks = set(), []
        for message in self.messages:
            if message.task_id and message.task_id not in seen:
                seen.add(message.task_id)
                tasks.append(message.task)
        return tasks

    @property
    def claimers(self):
        seen, names = set(), []
        for message in self.messages:
            if message.claimed_by_id and message.claimed_by_id not in seen:
                seen.add(message.claimed_by_id)
                names.append(message.claimed_by.short_name)
        return names

    @property
    def last_id(self):
        return max(m.pk for m in self.messages)


def _build_threads(user, idents):
    """``[MailThread]`` for the given conversation idents, newest first."""
    keys = [i for i in idents if not i.startswith("m")]
    loose = [int(i[1:]) for i in idents if i.startswith("m")]
    if not keys and not loose:
        return []

    grouped = {}
    rows = _visible_mail(user).filter(
        Q(thread_key__in=keys) | Q(pk__in=loose, thread_key="")
    ).order_by("received_at", "id")
    for row in rows:
        grouped.setdefault(_thread_ident(row.thread_key, row.pk), []).append(row)

    replies = {}
    if keys:
        from .models import OutboundMessage

        for reply in OutboundMessage.objects.filter(
            channel=Channel.EMAIL, thread_key__in=keys
        ).select_related("created_by").prefetch_related("uploads").order_by("created_at", "id"):
            replies.setdefault(reply.thread_key, []).append(reply)

    threads = [
        MailThread(ident, messages, replies.get(ident, ()))
        for ident, messages in grouped.items()
    ]
    threads.sort(key=lambda t: (t.latest.received_at, t.latest.pk), reverse=True)
    return threads


def inbox_threads(user, state="", query="", limit=100, after=0):
    """The mail page as conversations, filtered like :func:`inbox_queryset`.

    A conversation is on the list when *any* letter in it matches — a search
    for "word count" finds the conversation that has it — and the row then
    carries the whole conversation, as Gmail's does. ``after`` limits it to
    conversations that gained a letter with a higher id: the live feed.
    """
    matching = inbox_queryset(user, state, query)
    if after:
        matching = matching.filter(id__gt=after)

    idents = []
    for pk, key in matching.order_by("-received_at", "-id").values_list(
        "pk", "thread_key"
    )[: limit * 20]:
        ident = _thread_ident(key, pk)
        if ident not in idents:
            idents.append(ident)
            if len(idents) >= limit:
                break
    return _build_threads(user, idents)


def unclaimed_conversation_count():
    """What the mail badge counts: conversations with a letter nobody claimed.

    Gmail counts unread conversations, not unread letters, and so does this —
    a client who wrote four times is one thing waiting, not four.
    """
    waiting = InboundMessage.objects.filter(
        channel=Channel.EMAIL, claimed_by__isnull=True, is_rate_blocked=False
    ).order_by()
    keyed = waiting.exclude(thread_key="").values("thread_key").distinct().count()
    return keyed + waiting.filter(thread_key="").count()


def inbox_filter_qs(state="", query=""):
    """The list's filters as a query string, carried into a conversation and
    back out again, so "back" returns to the list as it was left."""
    from django.utils.http import urlencode

    params = [(k, v) for k, v in (("state", state), ("q", query)) if v]
    return urlencode(params) if params else ""


def thread_messages(user, message):
    """The whole conversation ``message`` is in, oldest first, as ``user`` sees it."""
    if not message.thread_key:
        return list(_visible_mail(user).filter(pk=message.pk))
    return list(
        _visible_mail(user)
        .filter(thread_key=message.thread_key)
        .order_by("received_at", "id")
    )


def thread_replies(thread_key):
    """What we sent into this mail conversation, oldest first."""
    from .models import OutboundMessage

    if not thread_key:
        return []
    return list(
        OutboundMessage.objects.filter(channel=Channel.EMAIL, thread_key=thread_key)
        .select_related("created_by").prefetch_related("uploads")
        .order_by("created_at", "id")
    )


def thread_references(thread_key):
    """Every Message-ID in the conversation, oldest first — ``References``.

    The client's letters and ours together, so whichever of them their mail
    program looks at, it finds the conversation.
    """
    from .models import OutboundMessage

    if not thread_key:
        return []
    stamped = [
        (at, pk, mid) for pk, at, mid in InboundMessage.objects.filter(
            channel=Channel.EMAIL, thread_key=thread_key
        ).exclude(external_id="").values_list("pk", "received_at", "external_id")
    ]
    stamped += [
        (at, pk, mid) for pk, at, mid in OutboundMessage.objects.filter(
            channel=Channel.EMAIL, thread_key=thread_key,
            status=OutboundMessage.Status.SENT,
        ).exclude(provider_id="").values_list("pk", "created_at", "provider_id")
    ]
    stamped.sort(key=lambda row: (row[0], row[1]))
    return [mid for _at, _pk, mid in stamped]


#: Gmail refuses a letter whose attachments add up to more than this.
MAX_MAIL_BYTES = 25 * 1024 * 1024


def reply_to_thread(anchor, user, body="", uploads=None):
    """Answer a mail conversation by e-mail, from its own page.

    Goes to the client who wrote the newest letter this user can see, as
    ``Re:`` its subject, with ``In-Reply-To`` / ``References`` set — so in the
    client's Gmail it lands inside their own conversation, not as a new one.
    A reply is somebody handling the conversation, so the letters in it that
    nobody had claimed are claimed by whoever sent it.

    Returns ``(ok, outbound, error_ar)``, like :func:`send_client_message`.
    """
    from . import threads

    body = (body or "").strip()
    uploads = list(uploads or [])
    if not body and not uploads:
        return False, None, "اكتب رد أو ارفق ملف."
    if sum(item.size or 0 for item in uploads) > MAX_MAIL_BYTES:
        return False, None, "الملفات مع بعض أكبر من 25 ميجا — الإيميل مش هيقبلها."

    letters = thread_messages(user, anchor)
    if not letters:
        return False, None, "المحادثة دي مش موجودة."
    latest = letters[-1]
    client = next((m.client for m in reversed(letters) if m.client_id), None)
    if client is None:
        return False, None, "المحادثة دي مش مربوطة بعميل معروف."

    # A letter from before threading: give it a key now, so the reply has a
    # conversation to be shown in.
    if not anchor.thread_key:
        anchor.thread_key = threads.new_key()
        anchor.save(update_fields=["thread_key"])
        latest.thread_key = anchor.thread_key

    titled = next((m for m in reversed(letters) if (m.subject or "").strip()), latest)
    ok, outbound, error = send_client_message(
        client, user,
        body=body,
        uploads=uploads,
        force_channel=Channel.EMAIL,
        subject=_reply_subject(titled),
        in_reply_to=latest.external_id,
        references=thread_references(anchor.thread_key),
        thread_key=anchor.thread_key,
    )
    if ok:
        for letter in letters:
            if not letter.claimed_by_id:
                claim_message(letter, user)
        log(user, "mail.reply", client.code, (body or f"{len(uploads)} file(s)")[:120])
    return ok, outbound, error


def claim_message(message, user):
    if message.claimed_by_id:
        return False
    message.claimed_by = user
    message.claimed_at = timezone.now()
    message.save(update_fields=["claimed_by", "claimed_at"])
    log(user, "message.claim", message.client_code)
    return True


#: What the client is told when somebody presses "استلمت". One word, in both
#: directions of the conversation, and never anything the client has to read
#: twice - this is a receipt, not an answer.
RECEIPT_BODY = "confirmed"


def confirm_receipt(message, user):
    """Tell the client their message arrived, and mark it claimed.

    Returns ``(ok, error_ar)``. The claim only happens once the reply is out:
    a row that says "handled" next to a client who was never told is exactly
    the state this button exists to prevent.
    """
    if not message.client_id:
        return False, "الرسالة دي مش مربوطة بعميل معروف."
    if message.is_rate_blocked and not user.is_admin_role:
        return False, "الرسالة دي محجوبة."

    is_mail = message.channel == Channel.EMAIL
    ok, _outbound, error = send_client_message(
        message.client, user,
        body=RECEIPT_BODY,
        force_channel=message.channel,
        subject=_reply_subject(message),
        # An e-mail receipt is a reply like any other: threaded in the
        # client's mailbox, and shown inside the conversation on our side.
        in_reply_to=message.external_id if is_mail else "",
        references=thread_references(message.thread_key) if is_mail else (),
        thread_key=message.thread_key if is_mail else "",
    )
    if not ok:
        return False, error

    if not message.claimed_by_id:
        claim_message(message, user)
    log(user, "message.confirm", message.client_code)
    return True, ""


def _reply_subject(message):
    """``Re:`` the client's own subject, so the reply lands in their thread."""
    subject = (message.subject or "").strip()
    if not subject:
        return ""
    if subject.lower().startswith("re:"):
        return subject[:200]
    return f"Re: {subject}"[:200]


# ---------------------------------------------------------------------------
# Chat rooms
# ---------------------------------------------------------------------------

def ensure_room(task, kind):
    room, created = ChatRoom.objects.get_or_create(
        task=task, kind=kind,
        defaults={"client": task.client if kind == RoomKind.CLIENT else None},
    )
    if kind == RoomKind.CLIENT and room.client_id != task.client_id:
        # Mirrored from the task so every client room is findable by client.
        room.client_id = task.client_id
        room.save(update_fields=["client"])
    # The group is the whole team. The client room is not: only the people who
    # speak to clients belong there, so the translator is deliberately absent -
    # anything they need to ask the client goes through the operation.
    members = [task.created_by, task.team_lead]
    if kind == RoomKind.GROUP:
        members.append(task.translator)
    members = [m for m in members if m is not None]

    if members:
        room.members.add(*members)

    if kind == RoomKind.CLIENT:
        # This room relays to a real client, so no translator belongs in it at
        # all - not even the one who accepted. Any translator left over from
        # the days when they did is removed here. Other roles are left alone,
        # so an admin can still add somebody (an accountant, say) on purpose.
        stale = room.members.filter(role=Role.TRANSLATOR)
        if stale.exists():
            room.members.remove(*stale)
    if created:
        if kind == RoomKind.CLIENT:
            system_message(
                room,
                key="client_room_opened",
                body_ar="الغرفة دي بتوصل العميل على واتساب. أي رسالة هنا هتروحله.",
                body_en="This room reaches the client on WhatsApp. Anything here is sent to them.",
            )
        else:
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


def share_source_files(task):
    """Put the client's original files into the task group.

    The translator never sees the inbound message itself - it carries the
    client's name and number, and the whole dashboard is built on them seeing
    a client code and nothing else. But the document *is* the job, so the
    files themselves belong in the group.

    The row points at the InboundMessage instead of copying the file, the same
    trick the client room uses: ``relay_files`` serves the attachments, the
    bubble reads as the client, and nothing is stored twice. Only the files
    cross - the inbound's own text, which is where the name and number sit,
    never does.

    Idempotent: an inbound already shared is not shared again, so this is safe
    to call on every acceptance and to re-run over tasks that predate it.
    """
    room = ensure_room(task, RoomKind.GROUP)
    already = set(
        room.messages.filter(inbound__isnull=False).values_list("inbound_id", flat=True)
    )
    # When the operation ticked specific files while making the task, only
    # those cross. Nothing ticked means everything, which is what every task
    # made before the picker existed means as well.
    picked = set(task.source_files.values_list("id", flat=True))

    shared = []
    for inbound in task.source_messages.prefetch_related("attachments"):
        files = list(inbound.attachments.all())
        if picked:
            files = [f for f in files if f.id in picked]
        if inbound.id in already or not files:
            continue
        shared.append(ChatMessage.objects.create(
            room=room,
            inbound=inbound,
            sender=None,
            body="ملفات العميل الأصلية. The client's original files.",
        ))
    return shared


# ---------------------------------------------------------------------------
# The relayed client room
#
# WhatsApp's Groups API is closed to this number (see the project notes), and a
# real WhatsApp group would expose every participant's phone number to everyone
# anyway — which would undo the client-identity masking the whole dashboard is
# built around. So the group lives here instead: the team is in a room on the
# site, the client stays in their ordinary 1:1 WhatsApp chat, and Eagle carries
# messages both ways. The client sees a role, never a name or a number.

#: What the client sees in front of a relayed message.
CLIENT_ROLE_LABELS = {
    Role.ADMIN: "الإدارة",
    Role.OPERATION: "الأوبريشن",
    Role.TEAM_LEAD: "التيم ليدر",
    Role.TRANSLATOR: "المترجم",
}


def client_prefix(user):
    """Never empty: an unlabelled relay would read to the client as anonymous."""
    label = CLIENT_ROLE_LABELS.get(getattr(user, "role", ""), "") or "الفريق"
    return f"[{label}]\n"


def relay_chat_message(message):
    """Carry one room message out to the client. Returns ``(ok, error_ar)``.

    The files are sent from the copies already stored on the ChatAttachment
    rows, so the room and WhatsApp always show the same bytes.
    """
    if message.room.kind != RoomKind.CLIENT:
        # Belt and braces: relaying an internal room would leak the team's
        # private discussion to the client.
        return False, "الغرفة دي مش بتوصل العميل."

    try:
        room = message.room
        client = room.relay_client
        if client is None:
            return False, "الغرفة دي مش مربوطة بعميل."
        sender = message.sender
        prefix = client_prefix(sender)
        # A files-only message still needs a caption, otherwise WhatsApp shows
        # the internal filename as the only text the client sees.
        body = prefix + (message.body or "").strip()
        if not (message.body or "").strip():
            body = prefix + "مرفق ملف."

        quoted = message.reply_to
        quote_wamid, quote_preview = "", ""
        if quoted is not None:
            # Quote whichever side it came from: the client's own message id,
            # or the id WhatsApp gave our relayed copy.
            quote_wamid = (
                quoted.inbound.external_id if quoted.inbound_id else quoted.relay_wamid
            ) or ""
            quote_preview = _quote_text(quoted)

        extra = [_read_attachment(a) for a in message.attachments.all()]
        ok, outbound, error = send_client_message(
            client, sender, body=body.strip(), extra_files=extra,
            reply_to_wamid=quote_wamid, reply_preview=quote_preview,
        )
        if ok and outbound is not None and outbound.provider_id:
            # Remembered so a later reply to THIS message can quote it too.
            message.relay_wamid = outbound.provider_id
    except Exception as exc:  # noqa: BLE001
        # The room message is already saved. Anything that goes wrong on the
        # way out has to end up on the bubble, never as a silent non-delivery.
        logger.exception("Relay of chat message %s failed", message.pk)
        ok, error = False, f"الرسالة اتحفظت بس مروحتش للعميل: {exc}"[:300]

    message.relay_status = "sent" if ok else "failed"
    message.relay_error = "" if ok else (error or "")
    message.save(update_fields=["relay_status", "relay_error", "relay_wamid"])
    return ok, message.relay_error


def client_rooms_for(client_id, only_open=True):
    """Every relayed room that talks to this client, task-bound or standalone."""
    qs = ChatRoom.objects.filter(kind=RoomKind.CLIENT, client_id=client_id)
    if only_open:
        # A task room stops receiving once its task is finished; a standalone
        # group has no lifecycle, so it stays open until it is deleted.
        qs = qs.filter(Q(task__isnull=True) | Q(task__status__in=ACTIVE_TASK_STATUSES))
    return qs.select_related("task", "client")


def create_client_group(user, client, title="", task=None, members=None):
    """Open a standalone relayed group for a client. Returns ``(room, error_ar)``."""
    conf = AppSettings.load()
    if not conf.can_create_group(user):
        return None, "مالكش صلاحية تعمل جروب. الأدمن بيظبطها من الإعدادات."
    if client is None:
        return None, "لازم تختار عميل."
    if not client_channel(client):
        return None, "العميل ده مفيش عنده رقم واتساب ولا إيميل مسجل — ضيفهم من صفحة العميل."

    # A task may only ever have one client room (the unique constraint says so),
    # so asking for a second one joins the existing room instead of failing.
    existing = None
    if task is not None:
        existing = ChatRoom.objects.filter(task=task, kind=RoomKind.CLIENT).first()

    if existing is not None:
        room, created = existing, False
        if title and not room.title:
            room.title = title.strip()[:120]
            room.save(update_fields=["title"])
    else:
        room = ChatRoom.objects.create(
            kind=RoomKind.CLIENT, client=client, task=task,
            title=(title or "").strip()[:120], created_by=user,
        )
        created = True

    people = {user}
    people.update(m for m in (members or []) if m is not None)
    if task is not None:
        people.update(p for p in (task.created_by, task.team_lead) if p is not None)
        if task.translator_accepted_at and task.translator_id:
            people.add(task.translator)
    # add, not set: joining an existing task room must not evict its members.
    room.members.add(*people)

    if created:
        system_message(
            room, key="client_room_opened",
            body_ar="الجروب ده بيوصل العميل على واتساب. أي رسالة هنا هتروحله.",
            body_en="This group reaches the client on WhatsApp. Anything here is sent to them.",
        )
    for member in room.members.exclude(pk=user.pk):
        notify(
            member,
            title_ar="اتضفت في جروب عميل",
            title_en="Added to a client group",
            body_ar=f"{user.short_name} ضافك في جروب مع العميل {client.code}.",
            body_en=f"{user.short_name} added you to a group with client {client.code}.",
            level="info", url=f"/ops/chats/g/{room.id}/",
        )
    log(user, "group.create", client.code, room.title or "-")
    return room, ""


def group_thread(room, user, limit=200):
    """A group's messages in the same shape ``client_thread`` returns.

    Reusing that shape means the bubble template and chat.js work unchanged.
    """
    rows = (
        room.messages
        .select_related("sender", "inbound", "reply_to", "reply_to__sender")
        .prefetch_related("attachments", "inbound__attachments")
        .order_by("-id")[:limit]
    )
    items = []
    for row in reversed(list(rows)):
        if row.is_system:
            continue
        quoted = row.reply_to
        items.append({
            "quote": _quote_text(quoted),
            "quote_who": (
                ("العميل" if quoted.from_client else (
                    quoted.sender.short_name if quoted.sender_id else ""))
                if quoted else ""
            ),
            "uid": f"g{room.id}-{row.id}",
            "kind": "in" if row.from_client else "out",
            "body": row.body,
            "subject": "",
            "channel": "",
            "at": row.created_at,
            "status": row.relay_status,
            "error": row.relay_error,
            "sender": row.sender.short_name if row.sender_id else "",
            "is_delivery": False,
            "task_code": room.task.code if room.task_id else "",
            "files": [_file_json(a) for a in row.relay_files],
        })
    return items


def _quote_text(message):
    """A one-line stand-in for a quoted message — its text, or its file's name."""
    if message is None:
        return ""
    text = (message.body or "").strip()
    if not text:
        first = next(iter(message.relay_files), None)
        text = (first.original_name or first.file.name) if first else ""
    return text[:160]


def group_preview(room, user):
    """The snippet shown for a group in the conversation list."""
    last = room.messages.order_by("-id").first()
    if last is None:
        return {"text": "", "at": room.created_at, "outgoing": False}
    text = last.body or _attachment_snippet(last.relay_files)
    return {"text": text[:70], "at": last.created_at, "outgoing": not last.from_client}


def default_team_group_name(creator, people):
    """What a new work group is called before anybody types a name.

    A team leader opening a group for one translator gets
    "<translator> (<team leader>)" - the shape asked for, and the one that
    makes a list of a dozen such groups readable at a glance. Anything else
    gets nothing, because a wrong guess is worse than an empty box.
    """
    if creator is None or not creator.is_team_lead:
        return ""
    translators = [p for p in (people or []) if p is not None and p.is_translator]
    if len(translators) != 1:
        return ""
    return f"{translators[0].short_name} ({creator.short_name})"


def create_team_group(creator, title="", members=None):
    """Open an internal work group. Returns ``(room, error_ar)``.

    Nothing here reaches a client: no client, no task, no relay. That is the
    whole point of it existing beside the client group, so the two must not
    be collapsed into one later on.
    """
    if not creator.can_create_team_group:
        return None, "مالكش صلاحية تعمل جروب شغل."

    people = [m for m in (members or []) if m is not None and m.pk != creator.pk]
    if not people:
        return None, "اختار عضو واحد على الأقل."

    title = (title or "").strip()[:120]
    if not title:
        title = default_team_group_name(creator, people)
    if not title:
        return None, "اكتب اسم للجروب."

    room = ChatRoom.objects.create(kind=RoomKind.TEAM, title=title, created_by=creator)
    room.members.add(creator, *people)
    system_message(
        room, key="team_group_opened",
        body_ar="جروب شغل داخلي. مفيش حاجة هنا بتوصل العميل.",
        body_en="An internal work group. Nothing here reaches the client.",
    )
    for person in people:
        notify(
            person,
            level="info",
            title_ar="اتضافت لجروب شغل",
            title_en="Added to a work group",
            body_ar=f"{creator.short_name} ضافك في «{title}».",
            body_en=f"{creator.short_name} added you to \"{title}\".",
            url=f"/ops/chats/g/{room.id}/",
        )
    return room, ""


def staff_pair_key(one, two):
    """The key that makes a pair of people a single conversation."""
    low, high = sorted((int(one), int(two)))
    return f"{low}-{high}"


def staff_room(viewer, other):
    """The one-to-one room between two employees, opening it if it is new.

    Keyed on the pair rather than looked up by membership: two people who open
    each other at the same moment would both find nothing and both create a
    room, and the unique index is what decides that race instead of luck.
    """
    from django.db import IntegrityError, transaction

    if viewer.pk == other.pk:
        return None
    key = staff_pair_key(viewer.pk, other.pk)
    room = ChatRoom.objects.filter(pair_key=key).first()
    if room is None:
        try:
            with transaction.atomic():
                room = ChatRoom.objects.create(kind=RoomKind.STAFF, pair_key=key)
        except IntegrityError:
            # The other side won the race. Theirs is the room.
            room = ChatRoom.objects.get(pair_key=key)
    # Membership is repaired every time, so a room that lost a member to a
    # half-finished write still opens for both of them.
    room.members.add(viewer, other)
    return room


def staff_conversations(viewer, query=""):
    """Everyone in the company, with the conversation if there is one.

    The directory IS the list: a person you have never written to sits in it
    with an empty preview, so starting a chat is opening a row rather than
    hunting through a picker. Whoever you have spoken to most recently rises
    to the top; the rest follow by name.
    """
    people = User.objects.filter(is_active=True).exclude(pk=viewer.pk)
    query = (query or "").strip()
    if query:
        people = people.filter(
            Q(first_name__icontains=query)
            | Q(last_name__icontains=query)
            | Q(username__icontains=query)
        )
    people = list(people.order_by("role", "username")[:200])

    rooms = {
        room.pair_key: room
        for room in ChatRoom.objects.filter(kind=RoomKind.STAFF, members=viewer)
    }

    rows = []
    for person in people:
        room = rooms.get(staff_pair_key(viewer.pk, person.pk))
        preview = {"text": "", "at": None, "outgoing": False}
        if room is not None:
            last = room.messages.order_by("-id").first()
            if last is not None:
                text = last.body or _attachment_snippet(last.relay_files)
                preview = {
                    "text": text[:70],
                    "at": last.created_at,
                    "outgoing": last.sender_id == viewer.pk,
                }
        rows.append({"person": person, "room": room, "preview": preview})

    # Two passes rather than one sort with a stand-in date: a person never
    # written to has no time at all, and inventing one to sort by is how a
    # silent ordering bug gets in.
    spoken = [row for row in rows if row["preview"]["at"]]
    fresh = [row for row in rows if not row["preview"]["at"]]
    spoken.sort(key=lambda row: row["preview"]["at"], reverse=True)
    return spoken + fresh


def groups_for(user, query=""):
    """The groups this person has: internal work groups, and client rooms.

    Two different things share the tab while the client rooms are still in
    use. They are told apart on screen, and by ``room.reaches_client`` in the
    code - the banner and the relay both read it.

    The membership rule is deliberately not the same for the two. A client
    room is the company's conversation with a client, so the admin sees every
    one of them. A work group is a group: you are in it or you are not, and a
    list of every group in the company would be noise. The admin can still
    open one by its URL, which ``can_access`` allows.
    """
    from django.db.models import Max, Q as _Q

    mine = _Q(kind=RoomKind.TEAM, members=user)
    theirs = _Q(kind=RoomKind.CLIENT)
    if not user.is_admin_role:
        theirs &= _Q(members=user)
    qs = ChatRoom.objects.filter(mine | theirs)
    query = (query or "").strip()
    if query:
        qs = qs.filter(
            Q(title__icontains=query)
            | Q(client__code__icontains=query)
            | Q(task__code__icontains=query)
        )
    return (
        qs.select_related("client", "task")
        .annotate(last_at=Max("messages__created_at"))
        .distinct()
        .order_by("-last_at", "-id")
    )


def mirror_inbound_to_room(inbound):
    """Drop a message the client just sent into the room the team watches.

    Works for a task's client room and for a standalone group alike. With no
    open room — or with more than one, where routing would be a guess — the
    message stays in the inbox only, which is the old behaviour and correct.
    """
    if inbound.client_id is None or inbound.is_rate_blocked:
        return None

    rooms = list(client_rooms_for(inbound.client_id)[:10])
    if not rooms:
        return None

    # A standalone group belongs to the client, not to one piece of work, so
    # every group is entitled to the client's words. Task rooms are different:
    # with two live tasks there is no honest way to tell which one a message is
    # about, and guessing would show it to the wrong team — so a task room only
    # receives when it is the client's only one.
    groups = [r for r in rooms if r.task_id is None]
    task_rooms = [r for r in rooms if r.task_id is not None]
    targets = list(groups)
    if len(task_rooms) == 1:
        targets.append(task_rooms[0])
    if not targets:
        return None

    first = None
    for room in targets:
        message = _mirror_into(room, inbound)
        first = first or message
    return first


def _mirror_into(room, inbound):
    message = ChatMessage.objects.create(
        room=room, sender=None, body=inbound.body or "", inbound=inbound,
    )

    task = room.task
    code = room.relay_client.code if room.relay_client else "—"
    where = task.code if task else (room.title or code)
    url = f"/tasks/{task.code}/?room={room.id}" if task else f"/ops/chats/g/{room.id}/"
    preview = (inbound.body or "ملفات")[:60]

    # Operation and admin already got the generic "new client message" ping
    # from the inbox; only the people who would otherwise miss it are told.
    # For a task room, can_view is re-checked per member so a stale membership
    # row cannot leak a preview of the client's words to someone off the task.
    # A standalone group has no task, so membership is the whole rule there.
    recipients = [
        m for m in room.members.exclude(role__in=[Role.OPERATION, Role.ADMIN])
        if task is None or task.can_view(m)
    ]
    for member in recipients:
        notify(
            member,
            title_ar="رسالة جديدة من العميل",
            title_en="New message from the client",
            body_ar=f"العميل {code} في {where}: {preview}",
            body_en=f"Client {code} in {where}: {preview}",
            level="info", url=url, sound=True, task=task,
        )
    return message


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
        # The client-facing room opens at the same moment, so the team can talk
        # to the client from the task page from the very first day.
        ensure_room(task, RoomKind.CLIENT)
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
        # Re-run so the translator who just joined is added to the client room.
        ensure_room(task, RoomKind.CLIENT)
        # The client's document is the job. Leaving it to somebody to forward
        # by hand left a translator looking at an empty group (20/09/2026).
        share_source_files(task)
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

    # The moment the files are all in is the moment to read them. A failure
    # here must never block the translator from handing the job over, so the
    # count is best-effort and the task detail page says what it found.
    try:
        from . import wordcount

        wordcount.recount_task(task)
    except Exception:
        log(user, "task.word_count.failed", task.code)

    room = ensure_room(task, RoomKind.GROUP)
    # The quality pass runs itself. A gate somebody has to remember to press
    # is a gate that gets skipped on the busy days, which are the days it is
    # for. It runs on its own thread - see ai.start_background_check.
    try:
        from . import ai

        ai.start_background_check(task)
    except Exception:  # noqa: BLE001 - never block a handover on the check
        log(user, "task.ai_check.failed_to_start", task.code)
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
        body_ar=f"{user.short_name} \u0623\u0646\u0647\u0649 \u0627\u0644\u0645\u0631\u0627\u062c\u0639\u0629. \u0627\u0644\u0623\u0648\u0628\u0631\u064a\u0634\u0646 \u064a\u0633\u062a\u0644\u0645 \u0648\u064a\u0633\u0644\u0651\u0645 \u0644\u0644\u0639\u0645\u064a\u0644.",
        body_en=f"{user.short_name} completed the review. Operation takes it over and delivers.",
    )
    # The group is the audience, not whoever happened to create the task: an
    # admin who took the client's message opens a group with no operation in
    # it, and telling only the creator leaves the handover with nobody in it.
    for person in room.members.exclude(pk=user.pk):
        if person.id == task.translator_id:
            notify(
                person,
                title_ar="\u062a\u0645\u062a \u0645\u0631\u0627\u062c\u0639\u0629 \u062a\u0631\u062c\u0645\u062a\u0643",
                title_en="Your translation was reviewed",
                body_ar=f"\u0627\u0644\u062a\u064a\u0645 \u0644\u064a\u062f\u0631 \u062e\u0644\u0635 \u0645\u0631\u0627\u062c\u0639\u0629 {task.code}.",
                body_en=f"The team leader reviewed {task.code}.",
                level="success", url=f"/tasks/{task.code}/", task=task,
            )
        else:
            notify(
                person,
                title_ar="\u062a\u0645\u062a \u0627\u0644\u0645\u0631\u0627\u062c\u0639\u0629 - \u0627\u0633\u062a\u0644\u0645 \u0627\u0644\u062a\u0627\u0633\u0643",
                title_en="Reviewed - take the task over",
                body_ar=f"{task.code} \u0627\u062a\u0631\u0627\u062c\u0639\u062a. \u0627\u0636\u063a\u0637 \u00ab\u0627\u0633\u062a\u0644\u0645\u062a \u0627\u0644\u062a\u0627\u0633\u0643\u00bb \u0639\u0634\u0627\u0646 \u062a\u0642\u062f\u0631 \u062a\u0628\u0639\u062a\u0647\u0627 \u0644\u0644\u0639\u0645\u064a\u0644.",
                body_en=f"{task.code} is reviewed. Press \u201cI have the task\u201d before you can send it.",
                level="success", url=f"/tasks/{task.code}/", sound=True, task=task,
            )
    log(user, "task.reviewed", task.code)
    return True


def acknowledge_handover(task, user):
    """The operation taking the reviewed job off the team leader's hands.

    This is the last human decision before files leave the building, and it is
    deliberately a separate press rather than something the delivery button
    implies: sending to a client cannot be undone, so somebody has to be on
    record as having the job before it can go.
    """
    if not (user.is_operation or user.is_admin_role):
        return False
    if task.status != TaskStatus.REVIEWED:
        return False
    if task.handover_ack_at:
        return True

    task.handover_ack_at = timezone.now()
    task.handover_ack_by = user
    task.save(update_fields=["handover_ack_at", "handover_ack_by", "updated_at"])
    room = ensure_room(task, RoomKind.GROUP)
    system_message(
        room, key="handover_ack",
        body_ar=f"{user.short_name} \u0627\u0633\u062a\u0644\u0645 \u0627\u0644\u062a\u0627\u0633\u0643 \u0648\u0647\u064a\u0633\u0644\u0651\u0645\u0647\u0627 \u0644\u0644\u0639\u0645\u064a\u0644.",
        body_en=f"{user.short_name} took the task over and will deliver it to the client.",
    )
    notify(
        task.team_lead,
        title_ar="\u0627\u0644\u0623\u0648\u0628\u0631\u064a\u0634\u0646 \u0627\u0633\u062a\u0644\u0645 \u0627\u0644\u062a\u0627\u0633\u0643",
        title_en="Operation took the task over",
        body_ar=f"{user.short_name} \u0627\u0633\u062a\u0644\u0645 {task.code}.",
        body_en=f"{user.short_name} has {task.code}.",
        level="info", url=f"/tasks/{task.code}/", task=task,
    )
    log(user, "task.handover_ack", task.code)
    return True


def add_group_member(task, user, person):
    """Put somebody into the task group after it has already opened.

    An admin who claimed the client's message themselves opens a group with no
    operation in it. This is how one joins later, which is the case the
    workflow was written around.
    """
    if not user.is_admin_role:
        return False
    if person is None or not person.is_active:
        return False
    room = ensure_room(task, RoomKind.GROUP)
    if room.members.filter(pk=person.pk).exists():
        return True
    room.members.add(person)
    system_message(
        room, key="member_added",
        body_ar=f"{user.short_name} \u0636\u0627\u0641 {person.short_name} \u0644\u0644\u062c\u0631\u0648\u0628.",
        body_en=f"{user.short_name} added {person.short_name} to the group.",
    )
    notify(
        person,
        title_ar="\u0627\u062a\u0636\u0641\u062a \u0644\u062c\u0631\u0648\u0628 \u062a\u0627\u0633\u0643",
        title_en="You were added to a task group",
        body_ar=f"\u0627\u0646\u062a \u062f\u0644\u0648\u0642\u062a\u064a \u0641\u064a \u062c\u0631\u0648\u0628 {task.code}.",
        body_en=f"You are now in the group for {task.code}.",
        level="info", url=f"/tasks/{task.code}/", task=task,
    )
    log(user, "task.group_member_add", task.code, person.username)
    return True


def send_back_for_revision(task, user, reason=""):
    """The team leader returns a reviewed translation to the translator.

    This is the missing half of the review loop, and it is also the only
    source the revision rate in the performance module can have: a job that
    came back is a job that came back, and nothing else records that.
    """
    if task.team_lead_id != user.id and not user.is_admin_role:
        return False
    if task.status not in (TaskStatus.UNDER_REVIEW, TaskStatus.REVIEWED):
        return False

    task.status = TaskStatus.IN_PROGRESS
    task.revision_count += 1
    task.returned_at = timezone.now()
    task.reviewed_at = None
    # The handover is off. Whoever takes it next says so again, on the new
    # version - an acknowledgement of a translation that no longer exists is
    # worse than none at all.
    task.handover_ack_at = None
    task.handover_ack_by = None
    task.save(update_fields=[
        "status", "revision_count", "returned_at", "reviewed_at",
        "handover_ack_at", "handover_ack_by", "updated_at",
    ])
    room = ensure_room(task, RoomKind.GROUP)
    system_message(
        room, key="returned",
        body_ar=f"{user.short_name} رجّع الترجمة للتعديل. {reason}".strip(),
        body_en=f"{user.short_name} sent the translation back. {reason}".strip(),
    )
    notify(
        task.translator,
        title_ar="الترجمة رجعتلك للتعديل",
        title_en="Your translation came back",
        body_ar=reason or f"التيم ليدر رجّع {task.code} للتعديل.",
        body_en=reason or f"The team leader returned {task.code}.",
        level="warning", url=f"/tasks/{task.code}/", sound=True, task=task,
    )
    log(user, "task.returned", task.code, reason)
    return True


def score_review(task, user, score, note=""):
    """The team leader's mark out of ten, recorded with the review.

    Separate from `mark_reviewed` so a leader can go back and score a job
    they already signed off, and so a review with no mark stays unmarked
    rather than quietly becoming a zero.
    """
    if task.team_lead_id != user.id and not user.is_admin_role:
        return False
    try:
        score = int(score)
    except (TypeError, ValueError):
        return False
    if not 0 <= score <= 10:
        return False
    task.review_score = score
    task.review_note = (note or "")[:250]
    task.save(update_fields=["review_score", "review_note", "updated_at"])
    log(user, "task.review_score", task.code, f"{score}/10")
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
    # ``mime`` is only set on rows saved since voice notes landed; older rows
    # and plain uploads still fall back to the filename.
    return name, content, getattr(attachment, "mime", "") or wa.guess_mime(name)


def deliver_to_client(task, user, attachment_ids=None, note="", send=True):
    """Send the finished files to the client, then close the task.

    Returns ``(ok, delivery, error)``. On a send failure the task stays at
    ``reviewed`` so the operation can fix things and try again.
    """
    from . import mailer, whatsapp as wa
    from .models import ChatAttachment, OutboundMessage

    # A reviewed status is not consent to send. Somebody has to have the job.
    if not task.handover_ack_at:
        return False, None, "\u0644\u0627\u0632\u0645 \u062a\u0636\u063a\u0637 \u00ab\u0627\u0633\u062a\u0644\u0645\u062a \u0627\u0644\u062a\u0627\u0633\u0643\u00bb \u0627\u0644\u0623\u0648\u0644."

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

    # WhatsApp only — this list is the WhatsApp line. A client we have only
    # ever e-mailed belongs on the mail page, not in a chat with no thread.
    if user.is_admin_role:
        rows = Client.objects.filter(messages__channel=Channel.WHATSAPP)
    else:
        # One filter, one join: the operation never sees a conversation made
        # only of rate-blocked messages, and the Max below then reflects only
        # the messages that role is allowed to know about.
        rows = Client.objects.filter(
            messages__channel=Channel.WHATSAPP, messages__is_rate_blocked=False
        )
    rows = rows.annotate(
        last_activity=Max(
            "messages__received_at",
            filter=Q(messages__channel=Channel.WHATSAPP),
        )
    ).distinct()

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
    """The client's messages for the chat page — WhatsApp only.

    The chat is the WhatsApp line and nothing else; e-mail has its own page
    (``inbox_queryset``). Mixing the two put the same letter in two inboxes and
    left two people answering it.
    """
    qs = client.messages.filter(channel=Channel.WHATSAPP).prefetch_related("attachments")
    if not user.is_admin_role:
        qs = qs.filter(is_rate_blocked=False)
    return qs


def _attachment_snippet(attachments):
    """What the conversation list shows when a message is only files."""
    rows = list(attachments)
    if not rows:
        return "—"
    # getattr: a ChatAttachment shares the audio behaviour without the columns.
    if any(getattr(a, "is_voice", False) or a.is_audio for a in rows):
        return "رسالة صوتية"
    return f"{len(rows)} ملف"


def _file_json(attachment):
    """One attachment as the chat templates and chat.js expect it.

    getattr throughout: a ChatAttachment carries the same behaviour as an
    inbound or outbound attachment but without the mime/voice/duration columns.
    """
    return {
        # The id is what the "convert to task" picker ticks. It is only ever
        # meaningful for an inbound attachment; the server re-checks it against
        # the message anyway, so an outbound id here is harmless.
        "id": attachment.pk,
        "url": attachment.file.url,
        "name": attachment.original_name or attachment.file.name,
        "size": attachment.size,
        "mime": getattr(attachment, "mime", ""),
        "voice": getattr(attachment, "is_voice", False),
        "audio": attachment.is_audio,
        "length": attachment.pretty_duration,
    }


def conversation_preview(client, user):
    """The snippet shown in the conversation list."""
    last = _visible_inbound(client, user).order_by("-received_at").first()
    out = (
        client.deliveries.filter(channel=Channel.WHATSAPP)
        .prefetch_related("uploads").order_by("-created_at").first()
    )
    if out and last and out.created_at > last.received_at:
        text = out.body or _attachment_snippet(out.uploads.all())
        if text == "—" and out.file_count:
            text = f"{out.file_count} ملف"
        return {"text": text[:70], "at": out.created_at, "outgoing": True}
    if last:
        text = last.body or _attachment_snippet(last.attachments.all())
        return {"text": text[:70], "at": last.received_at, "outgoing": False}
    return {"text": "", "at": None, "outgoing": False}


def client_thread(client, user, limit=200):
    """Merged inbound + outbound timeline for one client, oldest first."""
    items = []

    for row in _visible_inbound(client, user).order_by("-received_at")[:limit]:
        files = [_file_json(a) for a in row.attachments.all()]
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
            "wamid": row.external_id or "",
            "reply_to": row.reply_to_external or "",
            "files": files,
            # What the two buttons under a client message need: who has it,
            # and whether it is already a task. ``actions`` is what says the
            # entry is a real InboundMessage — a group's bubbles share this
            # shape but stand for relayed room messages, and "convert this to
            # a task" would have nothing to point at.
            "actions": True,
            # Both buttons stand for work on a file the client sent: one
            # confirms the file arrived, the other turns it into a task. A
            # message carrying only text — or only a voice note, which is not
            # a document to translate — gets neither.
            "has_docs": any(not f["audio"] for f in files),
            "claimed_by": row.claimed_by.short_name if row.claimed_by_id else "",
            "has_task": bool(row.task_id),
        })

    # WhatsApp only, to match the inbound side: an e-mailed delivery has no
    # place in a thread whose other half was filtered out.
    outbound = (
        client.deliveries.filter(channel=Channel.WHATSAPP)
        .select_related("created_by", "task").prefetch_related("uploads")
    )
    for row in outbound.order_by("-created_at")[:limit]:
        files = [_file_json(a) for a in row.uploads.all()]
        # Task deliveries keep their file list in JSON (the bytes went straight
        # to WhatsApp), so show the names without a link.
        if not files:
            files = [
                {"id": 0, "url": "", "name": f.get("name", ""), "size": 0,
                 "mime": "", "voice": False, "audio": False, "length": ""}
                for f in (row.files or [])
            ]
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
            "wamid": row.provider_id or "",
            "reply_to": row.reply_to_wamid or "",
            "quote": row.reply_preview or "",
            "files": files,
        })

    items.sort(key=lambda entry: entry["at"])
    _resolve_quotes(items)
    return items


def _resolve_quotes(items):
    """Fill each entry's ``quote`` from the message it replies to.

    The client's own replies arrive with only a WhatsApp id, so the text has to
    be looked up in the thread we already hold rather than fetched again.
    """
    by_wamid = {e["wamid"]: e for e in items if e.get("wamid")}
    for entry in items:
        target = by_wamid.get(entry.get("reply_to") or "")
        if target is None:
            # An outbound row may already carry the snippet it was sent with,
            # even when the quoted message is older than this page of thread.
            entry.setdefault("quote", "")
            entry["quote_who"] = entry.get("quote_who", "")
            continue
        # Keep a stored snippet if there is one; the author still has to be
        # derived either way, which is what the old early-exit skipped.
        text = entry.get("quote") or target.get("body") or ""
        if not text and target.get("files"):
            text = target["files"][0].get("name", "")
        entry["quote"] = text[:160]
        entry["quote_who"] = "العميل" if target["kind"] == "in" else (target.get("sender") or "")
    for entry in items:
        entry.setdefault("quote", "")
        entry.setdefault("quote_who", "")


def send_client_message(client, user, body="", uploads=None, voice=None,
                        voice_seconds=0, extra_files=None, reply_to_wamid="",
                        reply_preview="", force_channel="", subject="",
                        in_reply_to="", references=(), thread_key=""):
    """Free-form reply to a client on whichever channel they used last.

    ``force_channel`` names the line instead of guessing it. The two pages are
    each tied to one channel now — the chat is WhatsApp, the mail page is
    e-mail — so a reply written on one of them must not leave by the other
    just because the client's most recent message happened to arrive there.
    ``subject`` is the e-mail subject; blank keeps the old ``Eagle — CODE``.

    ``in_reply_to`` / ``references`` / ``thread_key`` are e-mail only: the
    client's letter this answers, the conversation's Message-IDs, and the
    conversation on /ops/inbox/ the reply is shown in (see :func:`reply_to_thread`).

    ``voice`` is a recording made in the browser. It is converted to whatever
    WhatsApp accepts *before* it is stored, so the file kept in the thread is
    byte-for-byte the one the client received.

    ``extra_files`` is a list of ``(name, bytes, mime)`` already stored
    elsewhere — the client room passes its ChatAttachments through it so the
    same file is not saved twice.

    Returns ``(ok, outbound, error_ar)``. Nothing is ever silently dropped —
    a failure is stored as a FAILED row so it stays visible in the thread.
    """
    from django.core.files.base import ContentFile

    from . import audio, mailer, whatsapp as wa
    from .models import OutboundAttachment, OutboundMessage

    uploads = list(uploads or [])
    extra_files = list(extra_files or [])
    body = (body or "").strip()
    if not body and not uploads and not extra_files and voice is None:
        return False, None, "مفيش حاجة تتبعت."

    conf = AppSettings.load()
    channel = force_channel or client_channel(client)
    if channel not in (Channel.WHATSAPP, Channel.EMAIL):
        channel = client_channel(client)
    target = client.phone if channel == Channel.WHATSAPP else client.email

    # Convert first: a recording Meta would reject must never reach the thread
    # pretending it was sent.
    recording, convert_error = None, ""
    if voice is not None:
        raw = voice.read()
        name = voice.name or "voice"
        mime = audio.base_mime(getattr(voice, "content_type", ""))
        try:
            content, name, mime = audio.prepare(raw, name, mime)
        except audio.AudioError as exc:
            content, convert_error = raw, exc.message_ar
            log(user, "client.voice_failed", client.code, exc.message_en[:200])
        recording = {
            "content": content, "name": name, "mime": mime,
            "seconds": max(0, min(int(voice_seconds or 0), audio.MAX_SECONDS)),
        }

    names = [item.name for item in uploads]
    names.extend(name for name, _content, _mime in extra_files)
    if recording:
        names.append(recording["name"])

    is_mail = channel == Channel.EMAIL
    mail_subject = ((subject or "").strip() or f"Eagle — {client.code}")[:250]

    outbound = OutboundMessage.objects.create(
        client=client, task=None, kind=OutboundMessage.Kind.CHAT,
        created_by=user, channel=channel, to_identity=target or "", body=body,
        files=[{"name": name, "status": "pending"} for name in names],
        reply_to_wamid=reply_to_wamid or "", reply_preview=(reply_preview or "")[:160],
        subject=mail_subject if is_mail else "",
        thread_key=(thread_key or "") if is_mail else "",
    )
    stored = [
        OutboundAttachment.objects.create(
            message=outbound, file=item, original_name=item.name, size=item.size
        )
        for item in uploads
    ]
    if recording:
        stored.append(OutboundAttachment.objects.create(
            message=outbound,
            file=ContentFile(recording["content"], name=recording["name"]),
            original_name=recording["name"],
            size=len(recording["content"]),
            mime=recording["mime"],
            is_voice=True,
            duration=recording["seconds"],
        ))

    if convert_error:
        outbound.status = OutboundMessage.Status.FAILED
        outbound.error_message = convert_error
        outbound.save(update_fields=["status", "error_message"])
        return False, outbound, convert_error

    if not channel or not target:
        outbound.status = OutboundMessage.Status.FAILED
        outbound.error_message = (
            "العميل ده مفيش عنده رقم واتساب ولا إيميل مسجل — ضيفهم من صفحة العميل."
        )
        outbound.save(update_fields=["status", "error_message"])
        return False, outbound, outbound.error_message

    # The recording is already in memory — no point fetching it back from the CDN.
    payload = [_read_attachment(a) for a in stored[:len(uploads)]]
    payload.extend(extra_files)
    if recording:
        payload.append((recording["name"], recording["content"], recording["mime"]))

    try:
        if channel == Channel.WHATSAPP:
            quote = reply_to_wamid or ""
            if body:
                outbound.provider_id = wa.send_text(target, body, context_id=quote)
                quote = ""       # only the first message carries the quote
            for index, (name, content, mime) in enumerate(payload):
                wa.send_file(target, content, name, mime,
                             caption="" if body else name, context_id=quote)
                quote = ""
                outbound.files[index]["status"] = "sent"
        else:
            from . import threads

            # Our own Message-ID, stored, so the client's answer to this letter
            # comes back into the same conversation (threads.find_thread_key).
            message_id = mailer.new_message_id(conf)
            parents = threads.message_ids(in_reply_to)
            chain = threads.message_ids(*references) if references else []
            mailer.send_delivery(
                conf, target,
                subject=mail_subject,
                body=body or "مرفق الملفات.",
                attachments=payload,
                headers={
                    "Message-ID": message_id,
                    "In-Reply-To": parents[0] if parents else "",
                    # Newest ids last, and not unbounded: a long exchange must
                    # not grow the header past what a mail server accepts.
                    "References": " ".join(chain[-20:]),
                },
            )
            outbound.provider_id = message_id[:190]
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

#: A translator with this many open tasks is treated as fully loaded. It is a
#: display threshold for the load bar, not a rule the code enforces anywhere —
#: the team leader decides who can take one more, not a constant.
FULL_LOAD_TASKS = 3


def translator_board(lead=None):
    """Who can take a job right now, and who already has one.

    Built for the team leader's own question — "who is free?" — so the answer
    is a state per person plus the evidence behind it: their open tasks, what
    those tasks are waiting on, and the nearest deadline. A board that says
    "busy" without saying what with sends the leader looking anyway.

    ``lead=None`` means every translator, which is what the operation's team
    page wants.
    """
    people = User.objects.filter(role=Role.TRANSLATOR, is_active=True)
    if lead is not None:
        people = people.filter(team_lead=lead)
    people = people.select_related("team_lead").prefetch_related("shifts")

    open_tasks = (
        Task.objects.filter(
            status__in=ACTIVE_TASK_STATUSES, translator__in=people
        )
        .select_related("client")
        .order_by("deadline", "code")
    )
    by_person = {}
    for task in open_tasks:
        by_person.setdefault(task.translator_id, []).append(task)

    # A translator who has been offered a task and has not answered yet is not
    # free — the offer is already holding them.
    pending = set(
        Assignment.objects.filter(
            status=AssignmentStatus.PENDING, assignee__in=people
        ).values_list("assignee_id", flat=True)
    )

    rows = []
    for person in people:
        tasks = by_person.get(person.pk, [])
        if not person.is_online:
            state = "shift" if person.on_shift else "off"
        elif tasks or person.pk in pending:
            state = "busy"
        else:
            state = "free"

        deadlines = [t.deadline for t in tasks if t.deadline]
        rows.append({
            "person": person,
            "state": state,
            "tasks": tasks,
            "load": len(tasks),
            # Capped at 100 on purpose: a bar that overflows says less than a
            # full bar next to the number it is actually carrying.
            "load_percent": min(100, int(round(len(tasks) * 100 / FULL_LOAD_TASKS))),
            "awaiting_answer": person.pk in pending,
            "words": sum(t.source_words or t.word_count or 0 for t in tasks),
            "next_deadline": min(deadlines) if deadlines else None,
        })

    # Free first — this board is read to answer one question, so the answer
    # sits at the top of it. Then the lightest load, then the name.
    order = {"free": 0, "busy": 1, "shift": 2, "off": 3}
    rows.sort(key=lambda row: (order.get(row["state"], 9), row["load"], row["person"].short_name))
    return rows


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
