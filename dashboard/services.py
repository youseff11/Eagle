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
    AICheckResult,
    AppSettings,
    Assignment,
    AssignmentStatus,
    AuditLog,
    Channel,
    ChatAttachment,
    ChatMessage,
    ChatRead,
    ChatRoom,
    Client,
    InboundMessage,
    MailRead,
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


def resolve_client(*, phone="", email="", channel="whatsapp", auto_create=True,
                   display_name=""):
    """Map an incoming identity onto a client, creating a coded stub if needed.

    ``display_name`` is the name the sender's own account carries - the
    WhatsApp profile name, or the display part of an e-mail address. It is
    used as the client's name when there is nothing better, which beats a
    row that reads only "CL-0001" on the one screen allowed to show a name.

    It never overwrites a name already there. Whatever an admin typed is a
    decision; a profile name is whatever the person set on their phone, and
    it changes whenever they feel like it.
    """
    client = None
    if phone:
        digits = "".join(ch for ch in phone if ch.isdigit())
        if digits:
            client = Client.objects.filter(phone__endswith=digits[-9:]).first()
    if client is None and email:
        client = Client.objects.filter(email__iexact=email).first()

    display_name = (display_name or "").strip()[:120]
    if client is not None:
        # A client from before this, or one created by a message that carried
        # no profile name, gets the name filled in the first time one arrives.
        if display_name and not client.name:
            client.name = display_name
            client.save(update_fields=["name"])
        return client

    if auto_create:
        client = Client.objects.create(
            name=display_name, phone=phone or "", email=email or "",
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
        # The sender's own profile name, straight off the WhatsApp payload.
        display_name=sender_display,
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

    def __init__(self, ident, messages, replies=(), seen_ids=()):
        self.key = ident
        self.messages = messages
        self.replies = list(replies)
        self.first = messages[0]
        self.latest = messages[-1]
        #: Which of these letters the person looking at the list has opened.
        #: Empty when nobody asked - a conversation nobody claims to have
        #: read is then simply unread, which is the safe way round.
        self.seen_ids = set(seen_ids)

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
        """Letters nobody has taken. Not the same as unread — see below."""
        return [m for m in self.messages if not m.claimed_by_id]

    @property
    def unseen(self):
        return [m for m in self.messages if m.pk not in self.seen_ids]

    @property
    def is_unread(self):
        """Bold on the list: something in here *you* have not opened yet.

        It used to mean "nobody claimed it", which never changed when you
        read the thing — so the badge sat there after you had been through
        the whole mailbox. Whether anyone has taken it is a separate fact,
        and the row still says so through ``claimers``.
        """
        return bool(self.unseen)

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

    # One query for the whole page: which of these letters this person has
    # already opened. Passed to every thread; each picks out its own.
    seen = seen_letter_ids(user, [m for rows in grouped.values() for m in rows])

    threads = [
        MailThread(ident, messages, replies.get(ident, ()), seen)
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


def _conversation_count(waiting):
    """How many conversations that queryset of letters adds up to.

    Gmail counts conversations, not letters, and so does this — a client who
    wrote four times is one thing waiting, not four. A letter from before
    threading existed has no key and is a conversation on its own.
    """
    waiting = waiting.order_by()
    keyed = waiting.exclude(thread_key="").values("thread_key").distinct().count()
    return keyed + waiting.filter(thread_key="").count()


def unclaimed_conversation_count():
    """Conversations holding a letter nobody has taken.

    What the mail page says out loud, and what the "محدش استلمها" filter
    shows. Not the badge: this number stays up until somebody presses
    "استلمت", which is right for a queue and wrong for a doorbell.
    """
    return _conversation_count(InboundMessage.objects.filter(
        channel=Channel.EMAIL, claimed_by__isnull=True, is_rate_blocked=False
    ))


def unseen_conversation_count(user):
    """What the sidebar badge counts: conversations this person has not opened.

    Per person, so it answers "is there anything here I have not looked at"
    rather than "has anyone dealt with this". Opening a conversation drops
    it; nothing else has to happen.
    """
    return _conversation_count(InboundMessage.objects.filter(
        channel=Channel.EMAIL, is_rate_blocked=False
    ).exclude(reads__user=user))


def seen_letter_ids(user, messages):
    """The ids, out of ``messages``, this person has already opened."""
    ids = [m.pk for m in messages]
    if not ids:
        return set()
    return set(
        MailRead.objects.filter(user=user, message_id__in=ids)
        .values_list("message_id", flat=True)
    )


def mark_letters_seen(user, messages):
    """Record that this person opened these letters. Returns the new ones.

    The ids come back so the page can mark what was new *on this visit* —
    the badge drops either way, but the reader still gets to see which
    letters they had not read before they clicked in.

    ``ignore_conflicts`` because two tabs on the same conversation are one
    person reading it once, not a crash.
    """
    already = seen_letter_ids(user, messages)
    fresh = [m for m in messages if m.pk not in already]
    if fresh:
        MailRead.objects.bulk_create(
            [MailRead(user=user, message=m) for m in fresh], ignore_conflicts=True
        )
    return {m.pk for m in fresh}


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
    # A step whose two people are not both known has nowhere to post its note.
    # That is an ordinary state - a task an admin opened for themselves, a
    # task with no leader yet - and never a reason to fail the step itself.
    if room is None:
        return None
    return ChatMessage.objects.create(
        room=room, is_system=True, system_key=key,
        body=f"{body_ar} {body_en}",
    )


def share_files_quietly(task, room):
    """Put the files in the chat without ever undoing the step that asked.

    ``accept_assignment`` runs as one transaction. A file row that refused
    to write would roll the acceptance back with it, and the person who had
    just pressed the button would be left with a window still running and a
    penalty on its way. The files are the second most important thing in
    that moment; the acceptance is the first.

    The inner ``atomic`` is what makes catching it safe: without a savepoint
    a database error poisons the outer transaction, and every query after it
    fails too - so the "safe" version would be the one that broke.
    """
    try:
        with transaction.atomic():
            return share_source_files(task, room=room)
    except Exception:  # noqa: BLE001 - a file must never undo a step
        logger.exception("could not share the files for %s", task.code)
        return []


def share_source_files(task, room=None):
    """Put the client's original files into a room - the task group by default.

    ``room`` is what lets the same mechanism drop the files into the one-to-one
    chat of whoever the task was just handed to. The mechanism itself does not
    change, and that matters: it is the tested path that carries the documents
    across without carrying the client's name or number with them.

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
    # No fallback room: a task has no room of its own now, so a caller that
    # does not say where the files go has nowhere to put them.
    if room is None:
        return []
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
            # This message IS work on the task, and saying so is what lets
            # relay_files honour the ticked files now that the room it sits
            # in no longer belongs to the task.
            task=task,
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
    rows = list(reversed(list(rows)))
    # Ticks on the viewer's own messages: seen by the others, or - in a room
    # that relays - read on the client's phone.
    receipts = room_receipts(room, user, rows) if user is not None else {}
    items = []
    for row in rows:
        if row.is_system:
            continue
        quoted = row.reply_to
        receipt, seen_by = receipts.get(row.id, ("", []))
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
            "mine": user is not None and row.sender_id == user.pk,
            "receipt": receipt,
            "seen_by": seen_by,
            "forwarded": row.forwarded,
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


def _room_last_preview(room, user, last):
    """The list snippet for a room's newest message, with the same ticks the
    bubble inside shows.

    Only your own message gets ticks - the list used to put a check in front
    of anybody's, and a single grey one at that, while the conversation
    itself already showed two blue ones. Same rule on both sides now.
    """
    text = last.body or _attachment_snippet(last.relay_files)
    mine = user is not None and last.sender_id == user.pk
    receipt = ""
    if mine:
        receipt = room_receipts(room, user, [last]).get(last.id, ("", []))[0]
    return {
        "text": text[:70], "at": last.created_at, "outgoing": mine,
        "status": last.relay_status or "", "receipt": receipt, "mine": mine,
    }


def group_preview(room, user):
    """The snippet shown for a group in the conversation list."""
    last = room.messages.exclude(is_system=True).order_by("-id").first()
    if last is None:
        last = room.messages.order_by("-id").first()
    if last is None:
        return {"text": "", "at": room.created_at, "outgoing": False}
    return _room_last_preview(room, user, last)


def default_team_group_name(creator, people):
    """What a new work group is called before anybody types a name.

    The shape is "مترجم: <translator> · ليدر: <team leader>" - each name
    labelled, because a title that reads "adam (omar)" leaves you working out
    which of the two is which every time you scan the list. Both have to be
    known:

    * one translator among the people picked, and
    * a team leader - whoever is opening the group when they are one, and
      otherwise the single team leader they picked.

    That second path is what lets an admin open the group for a pair without
    losing the name. Anything ambiguous returns nothing: two translators, two
    leaders or none at all, because a wrong name is worse than an empty box.
    """
    if creator is None:
        return ""
    people = [p for p in (people or []) if p is not None]
    translators = [p for p in people if p.is_translator]
    if len(translators) != 1:
        return ""

    if creator.is_team_lead:
        lead = creator
    else:
        leads = [p for p in people if p.is_team_lead]
        if len(leads) != 1:
            return ""
        lead = leads[0]
    return f"مترجم: {translators[0].short_name} · ليدر: {lead.short_name}"


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
                preview = _room_last_preview(room, viewer, last)
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
    # Archived rooms stay readable by their URL and stay out of the list.
    qs = ChatRoom.objects.filter(mine | theirs).exclude(is_archived=True)
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
def task_thread(task, one, two):
    """The chat a task's step happens in: the two people doing that step.

    There is no room that belongs to a task any more. A step belongs to the
    pair carrying it - operation and team leader, or team leader and
    translator - and that is their own conversation, which outlives the task.

    Returns ``None`` when one of the two is missing, and every caller treats
    that as "no note to write" rather than an error: a task with no leader yet
    is an ordinary state, not a failure.
    """
    if one is None or two is None or one.pk == two.pk:
        return None
    try:
        return staff_room(one, two)
    except Exception:  # noqa: BLE001 - a note must never undo a step
        logger.exception("could not open the thread for %s", task.code)
        return None


def task_files_filter(task):
    """Messages that are work on this task, under either generation of link.

    New messages carry ``task`` directly. Older ones were in a room that
    belonged to the task. Both answer, so nothing written before this goes
    quiet - which is the difference between a migration and a data loss.
    """
    return Q(message__task=task) | Q(message__room__task=task)


def tag_task_message(message):
    """Mark a chat message as work on a task, when that is unambiguous.

    Called after a message with files is sent in a one-to-one chat. If the
    two of them have exactly one live task together, the files are that
    task's and the link is drawn. If they have none, or more than one, the
    link is left alone.

    Guessing is refused on purpose - the same rule the inbound side already
    follows. A file filed against the wrong task would be delivered to the
    wrong client, and a wrong answer here is worse than no answer.
    """
    room = message.room
    if room.kind != RoomKind.STAFF or message.sender_id is None:
        return None
    # No file, no deliverable. The guard lives here rather than in the caller:
    # a rule that only holds while every caller remembers it is not a rule.
    if not message.attachments.exists():
        return None
    other = room.members.exclude(pk=message.sender_id).first()
    if other is None:
        return None
    pair = {message.sender_id, other.pk}
    candidates = [
        task for task in Task.objects.filter(
            status__in=ACTIVE_TASK_STATUSES
        ).select_related("team_lead", "translator", "created_by")
        if pair <= {task.created_by_id, task.team_lead_id, task.translator_id}
    ]
    if len(candidates) != 1:
        return None
    message.task = candidates[0]
    message.save(update_fields=["task"])
    return candidates[0]


def ai_suggestions_for(viewer, other):
    """The AI's notes on what ``other`` just handed ``viewer`` for review.

    Suggestions, and only that: the person reading them decides. They are
    shown to the team leader alone and never written into the shared room -
    an automated critique of somebody's work, landing in the chat they read
    every day, is not a review, it is a public correction.

    Returns ``None`` when there is nothing to show, which is most of the time.
    """
    if viewer is None or other is None or not viewer.is_team_lead:
        return None
    task = (
        Task.objects.filter(
            team_lead=viewer, translator=other, status=TaskStatus.UNDER_REVIEW
        )
        .order_by("-translated_at", "-id")
        .first()
    )
    if task is None:
        return None
    result = task.ai_checks.order_by("-created_at").first()
    if result is None or result.status != AICheckResult.Status.ISSUES:
        return None
    return {"task": task, "result": result, "issues": result.issues or []}


def notify_in_chat(to_user, from_user, *, body_ar, body_en, key):
    """Say it in the one-to-one chat the two of them already use.

    The way back up the chain is the same line the task came down. Best
    effort: a note that will not write must never undo the step that produced
    it - the task has already moved, and losing that would be far worse.
    """
    if to_user is None or from_user is None or to_user.pk == from_user.pk:
        return None
    try:
        room = staff_room(from_user, to_user)
        if room is None:
            return None
        return system_message(room, key=key, body_ar=body_ar, body_en=body_en)
    except Exception:  # noqa: BLE001
        logger.exception("could not write the chat note (%s)", key)
        return None


def post_handoff(assignment, by_user):
    """Put the task and its files into the chat between the two of them.

    Everything the person needs in order to answer is in one place: what the
    task is, and the documents themselves. Opening a file here is not
    accepting - the window is what accepting is - so they can read before
    they decide instead of accepting blind to stop a countdown.

    Best effort on purpose. A hand-off that fails to post is still a valid
    hand-off with a live window; losing the assignment because a chat message
    would not write would be far worse than a card that is missing.
    """
    task = assignment.task
    if by_user is None or assignment.assignee_id == getattr(by_user, "pk", None):
        return None
    try:
        room = staff_room(by_user, assignment.assignee)
        if room is None:
            return None
        system_message(
            room, key="handoff",
            body_ar=(
                f"{by_user.short_name} سلّمك التاسك {task.code} "
                f"({task.client.code}). افتح الملفات وقرر قبل ما الوقت يخلص."
            ),
            body_en=(
                f"{by_user.short_name} handed you task {task.code} "
                f"({task.client.code}). Open the files and decide before the window closes."
            ),
        )
        share_source_files(task, room=room)
        assignment.room = room
        assignment.save(update_fields=["room"])
        return room
    except Exception:  # noqa: BLE001 - never lose the assignment over a message
        logger.exception("could not post the hand-off for %s", task.code)
        return None


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
    post_handoff(assignment, by_user)
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


def deadline_problem(task, moment):
    """Why this cannot be the translator's deadline. Empty when it can.

    One rule: never later than what the client was promised. A leader who
    could hand out a longer date than the company's own would be creating
    a job that is late before anybody starts it.
    """
    if moment is None:
        return ""
    if task.deadline and moment > task.deadline:
        return "ما ينفعش تدي المترجم وقت أطول من ديدلاين العميل."
    return ""


def set_translator_deadline(task, moment, by_user, tell_translator=True):
    """Set what the translator is working to. ``(ok, error)``.

    ``None`` means "the same as the client's", which is what a task has
    until somebody says otherwise.
    """
    problem = deadline_problem(task, moment)
    if problem:
        return False, problem

    task.translator_deadline = moment
    task.translator_warned_at = None
    task.translator_missed_notified = False
    task.save(update_fields=[
        "translator_deadline", "translator_warned_at",
        "translator_missed_notified", "updated_at",
    ])

    if tell_translator and task.translator_id:
        due = task.translator_due
        notify(
            task.translator,
            title_ar="اتحدد ديدلاين جديد",
            title_en="Deadline updated",
            # The translator's own date, never the client's.
            body_ar=(f"ديدلاين {task.code}: {timezone.localtime(due):%Y-%m-%d %H:%M}"
                     if due else "الديدلاين اتشال."),
            body_en=(f"Deadline for {task.code}: {timezone.localtime(due):%Y-%m-%d %H:%M}"
                     if due else "Deadline cleared."),
            level="info", url=f"/tasks/{task.code}/", sound=True, task=task,
        )
    log(by_user, "task.translator_deadline", task.code,
        f"{timezone.localtime(moment):%Y-%m-%d %H:%M}" if moment else "cleared")
    return True, ""


def cap_translator_deadline(task, by_user):
    """Pull the translator's date back when the client's moves in front of it.

    The operation room can shorten a deadline after the job is already out.
    Leaving the translator on the old, later date would mean the one person
    doing the work is the only one who has not been told.
    """
    if not task.deadline or not task.translator_deadline:
        return False
    if task.translator_deadline <= task.deadline:
        return False
    set_translator_deadline(task, task.deadline, by_user)
    return True


@transaction.atomic
def assign_to_translator(task, translator, by_user, note="", deadline=None):
    conf = AppSettings.load()
    _cancel_pending(task)
    now = timezone.now()
    assignment = Assignment.objects.create(
        task=task, assignee=translator, assigned_by=by_user,
        target_role=Role.TRANSLATOR, assigned_at=now,
        expires_at=now + timedelta(seconds=conf.response_window_seconds),
        note=note,
    )
    post_handoff(assignment, by_user)
    task.translator = translator
    task.status = TaskStatus.AWAITING_TRANSLATOR
    task.translator_accepted_at = None
    # The date the leader is giving them, which is theirs alone. Blank keeps
    # whatever was there, and nothing there means the client's own date.
    if deadline is not None:
        task.translator_deadline = deadline
        task.translator_warned_at = None
        task.translator_missed_notified = False
    task.save(update_fields=[
        "translator", "status", "translator_accepted_at", "translator_deadline",
        "translator_warned_at", "translator_missed_notified", "updated_at",
    ])

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
        # The step belongs to the two carrying it, so the note goes in their
        # own chat. No room is opened for the task - talking to the client is
        # the operation's own conversation with them, under "Clients".
        room = assignment.room or task_thread(task, task.created_by, user)
        # The same safety net the translator's side has always had. The files
        # went into this chat when the task was handed over, and posting them
        # is best effort - so if that attempt failed, this is the only thing
        # that will ever put them right. Sharing is idempotent, so on the
        # ordinary path it finds them already there and does nothing.
        share_files_quietly(task, room)
        system_message(
            room, key="lead_accepted",
            body_ar=f"{user.short_name} استلم التاسك.",
            body_en=f"{user.short_name} accepted the task.",
        )
        notify(
            task.created_by,
            title_ar="التيم ليدر استلم التاسك",
            title_en="Team leader accepted",
            # It used to say "send them the files in the chat". The files go
            # by themselves at hand-off, and have done since the hand-off
            # started posting - so the line was sending the operation off to
            # do a job that was already done.
            body_ar=f"{user.short_name} أكد استلام {task.code}. الملفات وصلته في الشات.",
            body_en=f"{user.short_name} accepted {task.code}. The files are already in their chat.",
            level="success", url=f"/tasks/{task.code}/", task=task,
        )
    else:
        task.status = TaskStatus.IN_PROGRESS
        task.translator_accepted_at = timezone.now()
        task.save(update_fields=["status", "translator_accepted_at", "updated_at"])
        # The work happens between the leader and the translator, in the chat
        # they already have. No group is opened for the task. The files went
        # into this same chat when it was handed over and share_source_files
        # is idempotent, so this fills a gap rather than sending them twice.
        room = assignment.room or task_thread(
            task, task.team_lead or task.created_by, user
        )
        share_files_quietly(task, room)
        system_message(
            room, key="work_started",
            body_ar=f"{user.short_name} استلم {task.code} وبدأ شغل.",
            body_en=f"{user.short_name} accepted {task.code} and started work.",
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
        # Theirs, not the client's: this goes to the translator, and the
        # review time the leader kept back only exists while it is quiet.
        due = task.translator_due
        if due:
            notify(
                user,
                title_ar="الديدلاين بتاع التاسك",
                title_en="Task deadline",
                body_ar=f"ديدلاين {task.code}: {timezone.localtime(due):%Y-%m-%d %H:%M}",
                body_en=f"Deadline for {task.code}: {timezone.localtime(due):%Y-%m-%d %H:%M}",
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
    # An expiry is a refusal with a reason written for them: the sender needs
    # the same sentence either way to know what happened and what to do next.
    assignment.reason = "مارّدش في الوقت المحدد."
    task = assignment.task

    if not assignment.penalty_applied:
        assignment.penalty_applied = True
        assignment.assignee.apply_penalty(
            task,
            reason_en=f"No response within {conf.response_window_seconds}s on {task.code}",
            reason_ar=f"لم يرد خلال {conf.response_window_seconds} ثانية على {task.code}",
        )
    assignment.save(
        update_fields=["status", "responded_at", "penalty_applied", "reason"]
    )
    if assignment.room_id:
        system_message(
            assignment.room, key="handoff_expired",
            body_ar=f"الوقت خلص على {task.code} — رجعت للي بعتها.",
            body_en=f"The window closed on {task.code} - it went back to the sender.",
        )

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


def decline_assignment(assignment, user, reason=""):
    """Refuse a hand-off. A reason is required - returns ``(ok, error_ar)``.

    Without one the sender learns only that it came back, and has to go and
    ask before they can do anything about it. The reason is what turns a
    refusal into something the next person can act on.
    """
    if assignment.assignee_id != user.id or assignment.status != AssignmentStatus.PENDING:
        return False, "التسليمة دي مش مستنية ردك."
    reason = (reason or "").strip()[:250]
    if not reason:
        return False, "اكتب سبب الرفض."
    assignment.status = AssignmentStatus.DECLINED
    assignment.responded_at = timezone.now()
    assignment.reason = reason
    assignment.save(update_fields=["status", "responded_at", "reason"])
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
        body_ar=f"{user.short_name} رفض التاسك {task.code}: {reason}",
        body_en=f"{user.short_name} declined task {task.code}: {reason}",
        level="warning", url=f"/tasks/{task.code}/", sound=True, task=task,
    )
    # The refusal belongs in the conversation the hand-off arrived in, so the
    # sender reads it where they sent it rather than in a notification alone.
    if assignment.room_id:
        system_message(
            assignment.room, key="handoff_declined",
            body_ar=f"{user.short_name} رفض {task.code}: {reason}",
            body_en=f"{user.short_name} declined {task.code}: {reason}",
        )
    log(user, "assignment.decline", task.code, reason)
    return True, ""


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

    room = task_thread(task, task.team_lead, user)
    # The quality pass runs itself. A gate somebody has to remember to press
    # is a gate that gets skipped on the busy days, which are the days it is
    # for. It runs on its own thread - see ai.start_background_check.
    try:
        from . import ai

        ai.start_background_check(task)
    except Exception:  # noqa: BLE001 - never block a handover on the check
        log(user, "task.ai_check.failed_to_start", task.code)

    # The way back up is the same line the task came down: the person who
    # handed it over is told in the conversation they handed it over in, not
    # only in a notification they may never open.
    notify_in_chat(
        task.team_lead, user,
        body_ar=f"خلصت ترجمة {task.code}. جاهزة للمراجعة.",
        body_en=f"{task.code} is translated and ready for review.",
        key="translated",
    )
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
    # The last leg up: whoever opened the task hears it from the team leader
    # in their own conversation, and then delivers to the client.
    notify_in_chat(
        task.created_by, user,
        body_ar=f"راجعت {task.code} وخلصت. تقدر تستلمها وتبعتها للعميل.",
        body_en=f"{task.code} is reviewed. You can take it over and deliver.",
        key="reviewed",
    )
    room = task_thread(task, task.created_by, user)
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
    room = task_thread(task, task.team_lead, user)
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
    """Put somebody into a task's group - where one still exists.

    Tasks stopped opening a group of their own: the work is a chain of
    one-to-one chats now, and there is no room for a third person to join.
    This keeps answering for the tasks that ran under the old shape, and
    returns False for the ones that never had a group.

    Somebody who needs bringing into a live job goes into a work group
    instead - see ``create_team_group``.
    """
    if not user.is_admin_role:
        return False
    if person is None or not person.is_active:
        return False
    room = task.rooms.filter(kind=RoomKind.GROUP).first()
    if room is None:
        return False
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
    room = task_thread(task, task.translator, user)
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

    # The ids come from the browser, so they are fetched again and checked
    # against this task. That check is what stops a file from another job
    # being sent to this client - and it has to accept both links now, since
    # a task's files no longer live in a room that belongs to it.
    attachments = list(
        ChatAttachment.objects.filter(
            task_files_filter(task), id__in=list(attachment_ids or [])
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
    # An outbound with nothing from the client before it is still the last
    # thing said - it used to fall through and leave the row blank.
    if out and (last is None or out.created_at > last.received_at):
        text = out.body or _attachment_snippet(out.uploads.all())
        if text == "—" and out.file_count:
            text = f"{out.file_count} ملف"
        # The same ticks as the bubble: one grey, two grey, two blue.
        return {
            "text": text[:70], "at": out.created_at, "outgoing": True,
            "status": out.status, "mine": True,
            "receipt": out.wa_receipt if out.status == OutboundMessage.Status.SENT else "",
        }
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
            "receipt": "",
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
            # Delivered / read on the client's phone, as WhatsApp reported it.
            # Only a message that actually left can have got anywhere.
            "receipt": row.wa_receipt if row.status == OutboundMessage.Status.SENT else "",
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


# ---------------------------------------------------------------------------
# Unread counters and "seen"
# ---------------------------------------------------------------------------
#
# One cursor per (person, conversation) - see ``ChatRead``. Unread is every
# message past it that somebody else wrote; "seen" on a message you wrote is
# the other side's cursor having passed it. For a client it is WhatsApp that
# says so, through the status events on the webhook.

#: How far a message got on the client's phone. Meta does not promise to send
#: the events in order, so a late "delivered" must never undo a "read".
RECEIPT_RANK = {"": 0, "sent": 0, "delivered": 1, "read": 2}

#: The rooms the chats page lists. Task rooms live on the task page.
CHAT_ROOM_KINDS = (RoomKind.STAFF, RoomKind.TEAM, RoomKind.CLIENT)


def _read_cursor(user, *, room=None, client=None):
    """This person's cursor on one conversation, made on first use."""
    from django.db import IntegrityError

    lookup = {"user": user, "room": room} if room is not None else {
        "user": user, "client": client,
    }
    row = ChatRead.objects.filter(**lookup).first()
    if row is None:
        try:
            with transaction.atomic():
                row = ChatRead.objects.create(**lookup)
        except IntegrityError:
            # Two tabs opening the same conversation at once. Theirs is ours.
            row = ChatRead.objects.get(**lookup)
    return row


def _advance(row, upto):
    """Move a cursor up to ``upto`` - never back. True when it moved.

    A conditional UPDATE rather than read-compare-save: two tabs polling the
    same conversation must not be able to walk the cursor backwards.
    """
    if not upto or upto <= row.last_read_id:
        return False
    moved = ChatRead.objects.filter(pk=row.pk, last_read_id__lt=upto).update(
        last_read_id=upto, updated_at=timezone.now()
    )
    if moved:
        row.last_read_id = upto
    return bool(moved)


def mark_room_read(user, room):
    """``user`` has read this room up to its newest message."""
    from django.db.models import Max

    if user is None or room is None:
        return False
    top = room.messages.aggregate(top=Max("id"))["top"] or 0
    return _advance(_read_cursor(user, room=room), top)


def _wa_inbound(client, user):
    """The client's WhatsApp messages this person is allowed to know about."""
    qs = InboundMessage.objects.filter(client=client, channel=Channel.WHATSAPP)
    if not user.is_admin_role:
        qs = qs.filter(is_rate_blocked=False)
    return qs


def mark_client_read(user, client, receipt=True):
    """``user`` opened the conversation with this client. True when it moved.

    When it moved, the client is told too: WhatsApp's read receipt on the
    newest message turns every tick before it blue on their phone. That was
    a decision (23/09/2026), not a default - pass ``receipt=False`` to read
    without telling.
    """
    if user is None or client is None:
        return False
    if not (user.is_operation or user.is_admin_role):
        return False
    newest = _wa_inbound(client, user).order_by("-id").values_list(
        "id", "external_id"
    ).first()
    if not newest:
        return False
    moved = _advance(_read_cursor(user, client=client), newest[0])
    if moved and receipt and newest[1]:
        send_read_receipt(newest[1])
    return moved


def send_read_receipt(wamid):
    """Tell WhatsApp the client's message was read. Best effort, off-thread.

    The chat polls every few seconds and the Graph API can take the full
    timeout to answer, so the call must not sit inside the request. The
    settings are read here, on the request's own thread - the worker thread
    only makes the HTTP call and never touches the database.
    """
    import json
    import threading

    from . import whatsapp

    conf = AppSettings.load()
    if not (wamid and conf.whatsapp_access_token and conf.whatsapp_phone_number_id):
        return False
    url = (
        f"{whatsapp.GRAPH_HOST}/{whatsapp._version(conf)}/"
        f"{whatsapp.sender_id(conf)}/messages"
    )
    token = conf.whatsapp_access_token
    body = json.dumps({
        "messaging_product": "whatsapp", "status": "read", "message_id": wamid,
    }).encode("utf-8")

    def _go():
        try:
            whatsapp._call(
                url, token=token, data=body,
                headers={"Content-Type": "application/json"}, method="POST",
            )
        except Exception:  # a receipt that did not land is not worth a crash
            logger.info("WhatsApp read receipt for %s did not go through.", wamid)

    threading.Thread(target=_go, daemon=True).start()
    return True


def unread_by_client(user, client_ids=None):
    """{client id: messages from that client this person has not read}."""
    from collections import Counter

    from django.db.models import BigIntegerField, F, OuterRef, Subquery, Value
    from django.db.models.functions import Coalesce

    if not (user.is_operation or user.is_admin_role):
        return {}
    qs = InboundMessage.objects.filter(channel=Channel.WHATSAPP, client__isnull=False)
    if not user.is_admin_role:
        qs = qs.filter(is_rate_blocked=False)
    if client_ids is not None:
        qs = qs.filter(client_id__in=list(client_ids))
    # Somebody who joins the company does not owe it every message sent
    # before they arrived.
    if user.date_joined:
        qs = qs.filter(created_at__gte=user.date_joined)
    cursor = ChatRead.objects.filter(
        user=user, client_id=OuterRef("client_id")
    ).values("last_read_id")[:1]
    qs = qs.alias(
        read_upto=Coalesce(Subquery(cursor), Value(0), output_field=BigIntegerField())
    ).filter(id__gt=F("read_upto"))
    return dict(Counter(qs.order_by().values_list("client_id", flat=True)))


def unread_by_room(user, room_ids):
    """{room id: messages there this person has not read}.

    Their own messages and the system lines do not count - nobody needs to
    be told about what they just said, or that a group was opened.
    """
    from collections import Counter

    from django.db.models import BigIntegerField, F, OuterRef, Subquery, Value
    from django.db.models.functions import Coalesce

    room_ids = list(room_ids)
    if not room_ids:
        return {}
    qs = ChatMessage.objects.filter(room_id__in=room_ids, is_system=False).exclude(
        sender=user
    )
    if user.date_joined:
        qs = qs.filter(created_at__gte=user.date_joined)
    cursor = ChatRead.objects.filter(
        user=user, room_id=OuterRef("room_id")
    ).values("last_read_id")[:1]
    qs = qs.alias(
        read_upto=Coalesce(Subquery(cursor), Value(0), output_field=BigIntegerField())
    ).filter(id__gt=F("read_upto"))
    return dict(Counter(qs.order_by().values_list("room_id", flat=True)))


def listed_room_ids(user):
    """Every room this person's chats page lists, in any tab."""
    mine = Q(members=user, kind__in=CHAT_ROOM_KINDS)
    if user.is_admin_role:
        mine |= Q(kind=RoomKind.CLIENT)
    return list(
        ChatRoom.objects.filter(mine).exclude(is_archived=True)
        .values_list("id", flat=True).distinct()
    )


def unread_chat_total(user):
    """The sidebar badge: everything unread across every tab of the chats."""
    total = sum(unread_by_client(user).values())
    total += sum(unread_by_room(user, listed_room_ids(user)).values())
    return total


def room_receipts(room, viewer, rows):
    """{message id: (receipt, [names who read it])} for the viewer's own messages.

    In a staff chat or a work group, a message has been seen once everybody
    else in the room has read past it. The names are kept for a group, where
    "two of three" is worth being able to find out. A room that relays to a
    client is read on the client's phone, so WhatsApp's own receipt wins.
    """
    mine = [row for row in rows if row.sender_id == viewer.pk and not row.is_system]
    if not mine:
        return {}
    if room.reaches_client:
        return {row.id: (row.relay_receipt, []) for row in mine}

    others = [m for m in room.members.all() if m.pk != viewer.pk]
    cursors = dict(
        ChatRead.objects.filter(room=room, user__in=others)
        .values_list("user_id", "last_read_id")
    )
    out = {}
    for row in mine:
        readers = [m for m in others if cursors.get(m.pk, 0) >= row.id]
        seen = bool(others) and len(readers) == len(others)
        out[row.id] = ("read" if seen else "", [m.short_name for m in readers])
    return out


def record_whatsapp_status(wamid, status, error=""):
    """Fold one WhatsApp status event into the message it is about.

    ``delivered`` and ``read`` only ever move a message forward. ``failed``
    is Meta changing its mind after accepting the send (an expired window,
    a blocked number), so the message is marked failed with Meta's reason -
    unless it was already read, which no later failure can make untrue.
    Returns how many rows it touched.
    """
    status = (status or "").strip().lower()
    if not wamid:
        return 0
    if status == "failed":
        reason = (error or "WhatsApp reported the message as not delivered.")[:500]
        touched = OutboundMessage.objects.filter(provider_id=wamid).exclude(
            wa_receipt="read"
        ).update(status=OutboundMessage.Status.FAILED, error_message=reason)
        touched += ChatMessage.objects.filter(relay_wamid=wamid).exclude(
            relay_receipt="read"
        ).update(relay_status="failed", relay_error=reason)
        return touched

    rank = RECEIPT_RANK.get(status, 0)
    if not rank:
        return 0
    behind = [key for key, value in RECEIPT_RANK.items() if value < rank]
    touched = OutboundMessage.objects.filter(
        provider_id=wamid, wa_receipt__in=behind
    ).update(wa_receipt=status)
    touched += ChatMessage.objects.filter(
        relay_wamid=wamid, relay_receipt__in=behind
    ).update(relay_receipt=status)
    return touched


# ---------------------------------------------------------------------------
# Finding a task from the nav search
# ---------------------------------------------------------------------------

def visible_tasks(user):
    """Every task this person may open - ``Task.can_view`` as a queryset.

    Kept beside ``can_view`` in meaning: a search that returned a task the
    person cannot open would be a list of 404s, and worse, a list of titles
    they were never meant to read.
    """
    qs = Task.objects.all()
    if user.is_admin_role or user.is_operation:
        return qs
    if user.is_team_lead:
        return qs.filter(team_lead=user)
    if user.is_translator:
        return qs.filter(translator=user)
    return qs.none()


def search_tasks(user, query, limit=8):
    """Tasks by code, title or client code - the nav search's "tasks" half.

    The client is shown the way this person is allowed to see them
    (``label_for``): the admin gets the name, everyone else the code. And a
    translator can find a task by its client's *code* only - searching by a
    client's name would be a way of learning which code the name belongs to.
    """
    query = (query or "").strip()
    if len(query) < 2:
        return []
    match = Q(code__icontains=query) | Q(title__icontains=query) | Q(
        client__code__icontains=query
    )
    if user.can_see_client_identity:
        match |= Q(client__name__icontains=query) | Q(client__company__icontains=query)
    from .templatetags.eagle_tags import STATUS_MAP

    rows = (
        visible_tasks(user).filter(match).select_related("client")
        .order_by("-created_at")[:limit]
    )
    return [
        {
            "code": task.code,
            "title": task.title,
            "status_ar": STATUS_MAP.get(task.status, ("", task.status, ""))[1],
            "status_en": task.get_status_display(),
            "client": task.client.label_for(user) if task.client_id else "",
            "href": f"/tasks/{task.code}/",
        }
        for task in rows
    ]


# ---------------------------------------------------------------------------
# Forwarding
# ---------------------------------------------------------------------------
#
# Messages and files pass from one conversation to another the way WhatsApp
# forwards: the same file (the stored one - nothing is copied), a "محوّلة"
# tag, the forwarder as the sender. Two rules decided with the owner on
# 23/09/2026 hold it in place:
#
# * A client's own words travel only to a chat where everyone may read a
#   client's words (operation and admin). Anywhere else - a translator, a team
#   leader - the files go and the text stays behind, the same rule
#   ``share_source_files`` has always followed.
# * A client's file never goes to a *different* client. Forwarding to a client
#   is for the operation and the admin only.


def _chat_ref(user, code, create_staff=False):
    """``("room", room)`` / ``("client", client)`` for a chats-page code, or None.

    The codes are the ones the page already uses: ``g12`` a group, ``u5`` the
    staff chat with user 5, ``CL-0002`` a client's WhatsApp conversation. Only
    a conversation this person can open resolves.
    """
    import re

    code = (code or "").strip()
    if re.fullmatch(r"g\d+", code):
        room = ChatRoom.objects.filter(
            pk=int(code[1:]), kind__in=CHAT_ROOM_KINDS
        ).select_related("task", "client").first()
        if room is None or not room.can_access(user):
            return None
        if room.task_id and not room.task.can_view(user):
            return None
        return ("room", room)
    if re.fullmatch(r"u\d+", code):
        other = User.objects.filter(pk=int(code[1:]), is_active=True).first()
        if other is None or other.pk == user.pk:
            return None
        if create_staff:
            room = staff_room(user, other)
        else:
            room = ChatRoom.objects.filter(pair_key=staff_pair_key(user.pk, other.pk)).first()
        return ("room", room) if room is not None else None
    if code and (user.is_operation or user.is_admin_role):
        client = Client.objects.filter(code=code).first()
        if client is not None:
            return ("client", client)
    return None


def _forward_items(user, source, uids, attachment_ids):
    """What was picked, re-read from the source conversation, in thread order.

    Every id comes from the browser, so each one is looked up again *inside*
    the conversation it claims to be from: an id belonging somewhere else
    simply finds nothing. Each item is ``{"at", "text", "text_owner",
    "files": [(attachment, owner_client_id)]}`` - the owners are what the two
    rules above are checked against.
    """
    from .models import MessageAttachment

    kind, target = source
    items, seen_files = [], set()

    def add(at, text, text_owner, files):
        fresh = []
        for attachment, owner in files:
            key = (attachment.__class__.__name__, attachment.pk)
            if key not in seen_files:
                seen_files.add(key)
                fresh.append((attachment, owner))
        items.append({"at": at, "text": (text or "").strip(),
                      "text_owner": text_owner, "files": fresh})

    for uid in uids or []:
        side, _, raw = str(uid).rpartition("-")
        if not raw.isdigit():
            continue
        pk = int(raw)
        if kind == "client":
            client = target
            if side == "in":
                row = _wa_inbound(client, user).filter(pk=pk).first()
                if row is not None:
                    add(row.received_at, row.body, client.pk,
                        [(a, client.pk) for a in row.attachments.all()])
            elif side == "out":
                row = OutboundMessage.objects.filter(pk=pk, client=client).first()
                if row is not None:
                    add(row.created_at, row.body, client.pk,
                        [(a, client.pk) for a in row.uploads.all()])
        elif side == f"g{target.pk}":
            row = target.messages.filter(pk=pk, is_system=False).select_related(
                "inbound"
            ).first()
            if row is None:
                continue
            if row.from_client:
                owner = row.inbound.client_id
                files = [(a, owner) for a in row.relay_files]
            else:
                owner = row.origin_client_id
                files = [(a, getattr(a, "origin_client_id", None) or owner)
                         for a in row.relay_files]
            add(row.created_at, row.body, owner, files)

    if kind == "client" and attachment_ids:
        client = target
        rows = MessageAttachment.objects.filter(
            pk__in=[int(x) for x in attachment_ids if str(x).isdigit()],
            message__client=client, message__channel=Channel.WHATSAPP,
        ).select_related("message")
        if not user.is_admin_role:
            rows = rows.filter(message__is_rate_blocked=False)
        for row in rows.order_by("message__received_at", "id"):
            add(row.message.received_at, "", client.pk, [(row, client.pk)])

    items.sort(key=lambda item: item["at"])
    return [item for item in items if item["text"] or item["files"]]


def forward_to_chat(user, source_code, target_code, uids=(), attachment_ids=(), note=""):
    """Forward messages and/or files. Returns ``(ok, error_ar, url)``."""
    source = _chat_ref(user, source_code)
    if source is None:
        return False, "المحادثة دي مش متاحة ليك.", ""
    target = _chat_ref(user, target_code, create_staff=True)
    if target is None:
        return False, "اختار شات تحوّل له.", ""
    if target[0] == "room" and target[1].kind not in CHAT_ROOM_KINDS:
        return False, "مينفعش تحوّل للجروب ده.", ""

    items = _forward_items(user, source, uids, attachment_ids)
    if not items:
        return False, "اختار رسالة أو ملف الأول.", ""
    note = (note or "").strip()[:2000]

    if target[0] == "client":
        client = target[1]
        if not (user.is_operation or user.is_admin_role):
            return False, "التحويل للعميل للأوبريشن بس.", ""
        owners = {item["text_owner"] for item in items if item["text"]}
        owners |= {owner for item in items for _f, owner in item["files"]}
        owners.discard(None)
        if owners - {client.pk}:
            return False, "مينفعش تحوّل رسايل أو ملفات عميل لعميل تاني.", ""
        if note:
            ok, _out, error = send_client_message(
                client, user, body=note, force_channel=Channel.WHATSAPP
            )
            if not ok:
                return False, error, ""
        for item in items:
            ok, _out, error = send_client_message(
                client, user, body=item["text"],
                reuse_files=[f for f, _owner in item["files"]],
                force_channel=Channel.WHATSAPP,
            )
            if not ok:
                return False, error, ""
        log(user, "chat.forward", client.code, f"{len(items)} item(s)")
        return True, "", f"/ops/chats/{client.code}/"

    room = target[1]
    # A group that relays to a client is a group like any other (23/09/2026),
    # but what lands in it goes on to that client's WhatsApp - so the client
    # rule holds here exactly as it does for a 1:1 client conversation.
    relays_to = room.relay_client if room.reaches_client else None
    if room.reaches_client:
        if relays_to is None:
            return False, "الجروب ده مش مربوط بعميل.", ""
        owners = {item["text_owner"] for item in items if item["text"]}
        owners |= {owner for item in items for _f, owner in item["files"]}
        owners.discard(None)
        if owners - {relays_to.pk}:
            return False, "مينفعش تحوّل رسايل أو ملفات عميل لجروب عميل تاني.", ""
    members = list(room.members.all())
    # Everyone in the room may read a client's own words - or nobody gets them.
    all_inbox = all(m.is_operation or m.is_admin_role for m in members)

    written = []
    if note:
        written.append(ChatMessage.objects.create(room=room, sender=user, body=note))
    for item in items:
        text = item["text"]
        if text and item["text_owner"] is not None and not all_inbox:
            text = ""
        if not text and not item["files"]:
            continue
        message = ChatMessage.objects.create(
            room=room, sender=user, body=text, forwarded=True,
            origin_client_id=item["text_owner"],
        )
        for attachment, owner in item["files"]:
            ChatAttachment.objects.create(
                message=message, file=attachment.file.name,
                original_name=attachment.original_name
                or attachment.file.name.rsplit("/", 1)[-1],
                size=attachment.size or 0, origin_client_id=owner,
            )
        written.append(message)

    if not [m for m in written if m.forwarded]:
        return False, (
            "كلام العميل مابيتحولش للشات ده، والرسايل اللي اخترتها مفيهاش ملفات."
        ), ""

    relay_error = ""
    if relays_to is not None:
        # Out to the client, one by one, the same way a message typed in the
        # group goes. A failure stays on the bubble (relay_status), and the
        # first one is reported back.
        for message in written:
            ok, error = relay_chat_message(message)
            if not ok and not relay_error:
                relay_error = error

    mark_room_read(user, room)
    where = room.title_for(user)
    url = f"/ops/chats/g/{room.id}/" if room.kind != RoomKind.STAFF else ""
    for member in members:
        if member.pk == user.pk:
            continue
        notify(
            member, level="info",
            title_ar="رسايل محوّلة", title_en="Forwarded messages",
            body_ar=f"{user.short_name} حوّلك {len(written)} رسالة في {where}.",
            body_en=f"{user.short_name} forwarded {len(written)} message(s) in {where}.",
            url=url or f"/ops/chats/u/{user.pk}/",
        )
    if room.kind == RoomKind.STAFF:
        other = room.other_member(user)
        url = f"/ops/chats/u/{other.pk}/" if other else ""
    log(user, "chat.forward", f"room {room.id}", f"{len(written)} message(s)")
    if relay_error:
        return False, f"اتحوّلت للجروب بس مروحتش للعميل: {relay_error}"[:300], url
    return True, "", url


def send_client_message(client, user, body="", uploads=None, voice=None,
                        voice_seconds=0, extra_files=None, reply_to_wamid="",
                        reply_preview="", force_channel="", subject="",
                        in_reply_to="", references=(), thread_key="",
                        reuse_files=None):
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

    ``reuse_files`` are attachment rows already stored (a forward): the new
    outbound row points at the same stored file instead of a copy, so the
    thread still links it and nothing is uploaded twice.

    Returns ``(ok, outbound, error_ar)``. Nothing is ever silently dropped —
    a failure is stored as a FAILED row so it stays visible in the thread.
    """
    from django.core.files.base import ContentFile

    from . import audio, mailer, whatsapp as wa
    from .models import OutboundAttachment, OutboundMessage

    uploads = list(uploads or [])
    reuse_files = list(reuse_files or [])
    extra_files = list(extra_files or [])
    body = (body or "").strip()
    if not body and not uploads and not reuse_files and not extra_files and voice is None:
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
    names.extend(item.original_name or item.file.name.rsplit("/", 1)[-1] for item in reuse_files)
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
    stored.extend(
        OutboundAttachment.objects.create(
            message=outbound, file=item.file.name,
            original_name=item.original_name or item.file.name.rsplit("/", 1)[-1],
            size=item.size or 0, mime=getattr(item, "mime", "") or "",
        )
        for item in reuse_files
    )
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
    payload = [_read_attachment(a) for a in stored[:len(uploads) + len(reuse_files)]]
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


def _warn_deadline(task, now, minutes, people):
    for person, sound in people:
        notify(
            person,
            title_ar="تحذير: الديدلاين قرب",
            title_en="Deadline approaching",
            body_ar=f"فاضل {minutes} دقيقة على ديدلاين {task.code}.",
            body_en=f"{minutes} minutes left before the deadline of {task.code}.",
            level="warning", url=f"/tasks/{task.code}/", sound=sound, task=task,
        )


def _missed_deadline(task, people):
    for person in people:
        notify(
            person,
            title_ar="الديدلاين فات",
            title_en="Deadline missed",
            body_ar=f"التاسك {task.code} عدت الديدلاين.",
            body_en=f"Task {task.code} passed its deadline.",
            level="danger", url=f"/tasks/{task.code}/", sound=True, task=task,
        )


def sweep_deadlines():
    """Two countdowns, because there are two deadlines and two audiences.

    The translator is warned on their own date - the earlier one the leader
    gave them. The leader and the operation room are warned on the client's.
    They need separate "already warned" marks: one flag would mean whichever
    countdown ran first silenced the other.

    A task with no translator deadline of its own has the two fall together,
    and then only the client's pass runs - so nobody is told twice.
    """
    conf = AppSettings.load()
    now = timezone.now()
    threshold = now + timedelta(minutes=conf.deadline_warning_minutes)
    warned = 0

    # -- the client's date: the leader and the operation room --------------
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
        people = [(task.team_lead, False), (task.created_by, False)]
        # Only when the two dates are the same thing: otherwise the
        # translator gets their own warning from the pass below, on their
        # own date, and this one would hand them the client's.
        if not task.translator_deadline:
            people.insert(0, (task.translator, True))
        _warn_deadline(task, now, minutes, people)
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
        people = [task.team_lead, task.created_by]
        if not task.translator_deadline:
            people.insert(0, task.translator)
        _missed_deadline(task, people)

    # -- the translator's own date, which only they hear about -------------
    theirs = Task.objects.filter(
        status__in=ACTIVE_TASK_STATUSES,
        translator__isnull=False,
        translator_deadline__isnull=False,
        translator_deadline__lte=threshold,
        translator_deadline__gt=now,
        translator_warned_at__isnull=True,
    ).select_related("translator")
    for task in theirs:
        task.translator_warned_at = now
        task.save(update_fields=["translator_warned_at"])
        minutes = max(1, int((task.translator_deadline - now).total_seconds() // 60))
        _warn_deadline(task, now, minutes, [(task.translator, True)])
        warned += 1

    theirs_late = Task.objects.filter(
        status__in=ACTIVE_TASK_STATUSES,
        translator__isnull=False,
        translator_deadline__isnull=False,
        translator_deadline__lt=now,
        translator_missed_notified=False,
    ).select_related("translator")
    for task in theirs_late:
        task.translator_missed_notified = True
        task.save(update_fields=["translator_missed_notified"])
        _missed_deadline(task, [task.translator])

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
