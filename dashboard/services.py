"""Workflow engine for Eagle Phase 1.

Everything that mutates the state machine lives here so views stay thin and the
same logic can be reused by the webhooks, the management commands and the API.
"""

import logging
import os
import re
from datetime import timedelta

from django.db import transaction
from django.db.models import Q
from django.utils import timezone

from . import avatars, clock
from .models import (
    ACTIVE_TASK_STATUSES,
    TRANSLATOR_HOLDING_STATUSES,
    AICheckResult,
    AppSettings,
    Assignment,
    AssignmentStatus,
    AuditLog,
    Channel,
    ChatAttachment,
    ChatMessage,
    ChatMute,
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

def safe_notification_path(url):
    """``url`` if it is a plain path on this site, else ``""``.

    The link is drawn as a button on the notifications page and followed by
    scripts, so it must never be another site, a ``javascript:`` address, a
    protocol-relative ``//host``, or a path whose dot-segments collapse into one
    (``/.//host`` is ``//host`` once a browser has parsed it). Every caller passes
    a path built from codes and ids; this is what keeps it so when one of them
    one day passes something a person typed.
    """
    import re

    url = (url or "").strip()
    if not url.startswith("/") or url.startswith("//") or "\\" in url:
        return ""
    if any(ord(char) < 32 for char in url):
        return ""
    path = re.split(r"[?#]", url, maxsplit=1)[0]
    segments = path.split("/")[1:]
    if "//" in path or any(
        segment.lower() in (".", "..", "%2e", ".%2e", "%2e.", "%2e%2e") for segment in segments
    ):
        return ""
    return url


def notify(user, *, title_ar, title_en, body_ar="", body_en="", level="info",
           url="", sound=False, task=None, sender=None):
    if user is None:
        return None
    return Notification.objects.create(
        user=user, title_ar=title_ar, title_en=title_en,
        body_ar=body_ar, body_en=body_en, level=level,
        url=safe_notification_path(url), sound=sound, task=task, sender=sender,
    )


def notify_role(role, **kwargs):
    for user in User.objects.filter(role=role, is_active=True):
        notify(user, **kwargs)


#: What a support announcement is written down as, how long it may be, and how soon the same words from the same person are
#: taken as a double press rather than a second announcement.
ANNOUNCE_ACTION = "support.announce"
ANNOUNCE_TITLE_MAX = 200
ANNOUNCE_BODY_MAX = 1000
ANNOUNCE_REPEAT_SECONDS = 60
ANNOUNCE_LEVELS = ("info", "warning")


def announce_recipients(sender):
    """Everybody who works here and is switched on, but the sender: the people an announcement reaches."""
    return User.objects.filter(is_active=True).exclude(pk=sender.pk)


def announce(sender, *, title, body="", level="info", sound=False):
    """Send a notification from technical support to every active employee. Returns ``(how_many, problem)``.

    ``problem`` is a short code (``empty``, ``too_long``, ``level``, ``repeat``) and nothing was sent when it is not ``""``. The
    words are the sender's own and go out as typed, in both languages: nothing of a client is in a support account's reach, so
    nothing of one can be in them. Every announcement is written to the audit log with who sent it and to how many.
    """
    title = " ".join((title or "").split())
    # Lines the sender wrote stay lines (a list under the title): only the line ends are made one kind, and a run of empty
    # lines is one empty line.
    body = re.sub(r"\n{3,}", "\n\n", (body or "").replace("\r\n", "\n").replace("\r", "\n")).strip()
    if not title:
        return 0, "empty"
    if len(title) > ANNOUNCE_TITLE_MAX or len(body) > ANNOUNCE_BODY_MAX:
        return 0, "too_long"
    if level not in ANNOUNCE_LEVELS:
        return 0, "level"
    since = timezone.now() - timedelta(seconds=ANNOUNCE_REPEAT_SECONDS)
    if AuditLog.objects.filter(
        actor=sender, action=ANNOUNCE_ACTION, target=title[:160], detail__startswith=f"{body}\n", created_at__gte=since
    ).exists():
        return 0, "repeat"
    people = list(announce_recipients(sender))
    with transaction.atomic():
        for person in people:
            notify(person, title_ar=title, title_en=title, body_ar=body, body_en=body, level=level, sound=bool(sound), sender=sender)
        log(sender, ANNOUNCE_ACTION, title[:160], f"{body}\n{len(people)}")
    return len(people), ""


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
        # The main number or any of the client's other ones (``extra_phones``).
        client = Client.find_by_phone(phone)
    if client is None and email:
        client = Client.find_by_email(email)

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
                   attachments=None, reply_to_external="", references="",
                   owner=None, recipients=()):
    """Create an :class:`InboundMessage` and fan out the notifications.

    ``references`` is the e-mail ``References`` header. It is not stored; it
    only decides which conversation the letter joins.

    ``owner`` is the Sales person whose own WhatsApp number this came in on
    (the webhook knows it from the number). ``recipients`` are the addresses
    a letter was sent to; one of them being somebody's address on the company
    mailbox (``User.mail_alias``) makes the letter theirs. Neither = the
    company line, as before (``lines.py``).
    """
    from . import lines, threads

    if owner is None and channel == Channel.EMAIL and recipients:
        owner = lines.owner_for_addresses(recipients)

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
            # A letter joins the conversations of its own line only.
            owner_id=owner.pk if owner is not None else None,
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
        owner=owner,
    )

    from .files import mask_name

    for item in attachments or []:
        # A client's file name often carries the client's own name ("ABC -
        # PO 2291.pdf"). The dashboard shows the masked one; the admin's
        # download keeps the real one.
        raw = str(item.get("name") or getattr(item["file"], "name", "") or "")
        raw = raw.replace("\\", "/").rsplit("/", 1)[-1][:250]
        message.attachments.create(
            file=item["file"],
            original_name=mask_name(raw, client)[:250],
            raw_name=raw,
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
        # A Sales line rings its owner (and the admin), never the operation
        # room - they do not see that conversation at all. Same for a letter
        # to somebody's own address, and for a letter to no one's when the
        # admin keeps those (``lines.line_q``).
        if owner is not None:
            audience = User.objects.filter(Q(pk=owner.pk) | Q(role=Role.ADMIN), is_active=True)
        elif is_mail and lines._unassigned_mail_is_admins():
            audience = User.objects.filter(role=Role.ADMIN, is_active=True)
        else:
            audience = User.objects.filter(role__in=[Role.OPERATION, Role.ADMIN], is_active=True)
        # Whoever muted this client's chat is not rung for it.
        silenced = muted_user_ids(client=client) if client else set()
        for user in audience:
            if user.pk in silenced:
                continue
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
                sound=user.is_operation or (owner is not None and user.pk == owner.pk),
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

    from . import lines

    qs = InboundMessage.objects.filter(channel=Channel.EMAIL).filter(
        lines.line_q(user)
    ).select_related(
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
        match = Q(body__icontains=query) | Q(subject__icontains=query) | Q(
            client__code__icontains=query
        )
        # The sender's address is identity. Matching on it would let anyone
        # type a company's e-mail and read back which code it belongs to.
        if user.can_see_client_identity:
            match |= Q(sender_identity__icontains=query)
        qs = qs.filter(match)
        if not user.can_see_client_identity:
            qs = _search_what_is_shown(qs, user, query)
    return qs


#: How many of the newest matching letters a search reads the shown words of (see ``_search_what_is_shown``).
SEARCH_SCAN = 500


def _search_what_is_shown(qs, user, query):
    """Keep the letters whose words, as ``user`` reads them (the client's name and contacts taken out), contain the query, or
    whose client code does.

    The words are matched in the database as they were written, but shown with the name taken out: a search for a company's
    name would otherwise bring up exactly the letters that name it, under a code, and the search would tell the operation who
    that client is.
    """
    from . import identity
    from .models import Client

    needle = query.lower()
    rows = list(qs.order_by("-received_at", "-id").values_list("pk", "subject", "body", "client_id")[:SEARCH_SCAN])
    clients = Client.objects.in_bulk({row[3] for row in rows if row[3]})
    kept = []
    for pk, subject, body, client_id in rows:
        client = clients.get(client_id)
        shown = identity.mask_client(f"{subject}\n{body}", client, user).lower()
        if needle in shown or (client is not None and needle in client.code.lower()):
            kept.append(pk)
    return qs.filter(pk__in=kept)


# ---------------------------------------------------------------------------
# Mail conversations
# ---------------------------------------------------------------------------

def _thread_ident(key, pk):
    """A letter keyed before threading existed is a conversation of its own."""
    return key or f"m{pk}"


def _visible_mail(user):
    """Every e-mail this user may read, with what a mail row needs loaded."""
    from . import lines

    qs = InboundMessage.objects.filter(channel=Channel.EMAIL).filter(
        lines.line_q(user)
    ).select_related(
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
        from . import lines
        from .models import OutboundMessage

        # The replies of the lines this person works: one question, not one per reply.
        for reply in OutboundMessage.objects.filter(
            channel=Channel.EMAIL, thread_key__in=keys
        ).filter(lines.line_q(user)).select_related("created_by").prefetch_related("uploads").order_by("created_at", "id"):
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


def inbox_threads(user, state="", query="", limit=100):
    """The mail page as conversations, filtered like :func:`inbox_queryset`.

    A conversation is on the list when *any* letter in it matches — a search
    for "word count" finds the conversation that has it — and the row then
    carries the whole conversation, as Gmail's does.
    """
    matching = inbox_queryset(user, state, query)

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


def unclaimed_conversation_count(user=None):
    """Conversations holding a letter nobody has taken.

    What the mail page says out loud, and what the "محدش استلمها" filter
    shows. Not the badge: this number stays up until somebody presses
    "استلمت", which is right for a queue and wrong for a doorbell.
    ``user`` narrows it to the line(s) that person works (``lines.py``).
    """
    from . import lines

    qs = InboundMessage.objects.filter(
        channel=Channel.EMAIL, claimed_by__isnull=True, is_rate_blocked=False
    )
    if user is not None:
        qs = qs.filter(lines.line_q(user))
    return _conversation_count(qs)


def unseen_conversation_count(user):
    """What the sidebar badge counts: conversations this person has not opened.

    Per person, so it answers "is there anything here I have not looked at"
    rather than "has anyone dealt with this". Opening a conversation drops
    it; nothing else has to happen.
    """
    from . import lines

    return _conversation_count(InboundMessage.objects.filter(
        channel=Channel.EMAIL, is_rate_blocked=False
    ).filter(lines.line_q(user)).exclude(reads__user=user))


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


def thread_messages(user, message):
    """The whole conversation ``message`` is in, oldest first, as ``user`` sees it."""
    if not message.thread_key:
        return list(_visible_mail(user).filter(pk=message.pk))
    return list(
        _visible_mail(user)
        .filter(thread_key=message.thread_key)
        .order_by("received_at", "id")
    )


def thread_replies(thread_key, user=None):
    """What we sent into this mail conversation, oldest first.

    With ``user``, only what that person's line may read (``lines.sees``): a conversation can span the company address and a
    Sales address (a client replies "Re:" to the other one), and the replies of one line are not the other's to read.
    """
    from . import lines
    from .models import OutboundMessage

    if not thread_key:
        return []
    replies = OutboundMessage.objects.filter(channel=Channel.EMAIL, thread_key=thread_key)
    if user is not None:
        replies = replies.filter(lines.line_q(user))
    return list(replies.select_related("created_by").prefetch_related("uploads").order_by("created_at", "id"))


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
        line_owner=latest.owner,
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
        line_owner=message.owner if is_mail else LINE_FROM_CLIENT,
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
    # speak to clients belong there - the operation, Sales, the admin - so the
    # team leader and the translator are deliberately absent. Anything they
    # need to ask the client goes through the operation.
    members = [task.created_by, task.team_lead]
    if kind == RoomKind.GROUP:
        members.append(task.translator)
    elif kind == RoomKind.CLIENT:
        members = [m for m in members if m is not None and m.handles_clients]
    members = [m for m in members if m is not None]

    if members:
        room.members.add(*members)

    if kind == RoomKind.CLIENT:
        # This room relays to a real client, so nobody who does not talk to
        # clients belongs in it at all - not the translator who accepted, not the
        # team leader, not HR or accounting (the owner's rule, 2026-10-02).
        # Whoever is left over from the days when they did is removed here.
        stale = [m for m in room.members.all() if not m.handles_clients or m.is_translator]
        if stale:
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


def task_inbounds(task):
    """Every client message a task was made from.

    A message belongs to the *first* task made from it (``InboundMessage.task``).
    A second request on the same material - the same contract, another
    language - does not take the message away from the first; it holds the
    files through ``source_files`` instead. So "this task's messages" is both.
    """
    return InboundMessage.objects.filter(
        Q(task=task) | Q(attachments__tasks=task)
    ).distinct()


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
    # Already shared *for this task*. The same message can be the material
    # of two tasks now, and sharing it for the first must not stop it being
    # shared for the second. Rows from before the link existed (task NULL)
    # still count, so nothing old is posted twice.
    already = set(
        room.messages.filter(inbound__isnull=False)
        .filter(Q(task=task) | Q(task__isnull=True))
        .values_list("inbound_id", flat=True)
    )
    # When the operation ticked specific files while making the task, only
    # those cross. Nothing ticked means everything, which is what every task
    # made before the picker existed means as well.
    picked = set(task.source_files.values_list("id", flat=True))

    shared = []
    for inbound in task_inbounds(task).prefetch_related("attachments"):
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


#: What a room is told when sending to the client failed in a way nobody foresaw. The reason is in the log.
RELAY_FAILED_AR = "الرسالة اتحفظت بس مروحتش للعميل. جرّب تاني، ولو استمرت المشكلة بلّغ الأدمن."

#: And a 1:1 send that broke half way: Meta may or may not have the message, so the person is told to look first.
SEND_UNSURE_AR = "حصلت مشكلة وإحنا بنبعت، ومش متأكدين إن الرسالة وصلت للعميل. اتأكد قبل ما تبعتها تاني."


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
            message.relay_status = "failed"
            message.relay_error = "الغرفة دي مش مربوطة بعميل."
            message.save(update_fields=["relay_status", "relay_error"])
            return False, message.relay_error
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
        ok, error = False, RELAY_FAILED_AR

    from . import identity

    message.relay_status = "sent" if ok else "failed"
    # Stored where every member of the room reads it: SMTP and Meta quote the recipient back in a refusal.
    message.relay_error = "" if ok else identity.scrub_contacts(error or "")
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


#: The most people one message may mention.
MAX_MENTIONS = 20


def mention_pattern(name):
    """``@name`` as a whole word: "@Nour" is not found inside "@Nourhan". The page draws with the same rule (``lib/mentions.ts``)."""
    return re.compile(r"(?<!\w)@" + re.escape(name) + r"(?!\w)")


def mention_targets(room, sender, body, raw):
    """The colleagues a message really mentions: who gets the ping, and whom the bubble marks.

    ``raw`` is what the page sent, the ids it picked from the box ("3,5"): a name is not unique, so the words alone
    cannot say which Mohamed was meant. An id counts only if that person is in the room and may open it (the same
    test every notification is put to, ``ChatRoom.can_open``), is not the sender, and is still named in the words:
    taking the "@name" out of a message takes the ping with it.

    Never in a client room - what is typed there is relayed to the client word for word, and an "@name" would put a
    colleague's name in front of them (client-privacy rule 4) - nor in a chat of two, where there is nobody to pick.
    """
    if room.kind in (RoomKind.CLIENT, RoomKind.STAFF) or not (body or "").strip():
        return []
    ids = []
    for part in str(raw or "")[:400].split(",")[:MAX_MENTIONS]:
        part = part.strip()
        if part.isascii() and part.isdigit():
            ids.append(int(part))
    if not ids:
        return []
    people = room.members.filter(pk__in=ids, is_active=True).exclude(pk=sender.pk).order_by("id")
    return [
        person for person in people
        if mention_pattern(person.short_name).search(body) and room.can_open(person)
    ]


def group_thread(room, user, limit=200):
    """A group's messages in the same shape ``client_thread`` returns.

    Reusing that shape means the bubble template and chat.js work unchanged.
    """
    rows = (
        room.messages
        .select_related("sender", "inbound", "reply_to", "reply_to__sender", "task", "origin_client")
        .prefetch_related("attachments", "inbound__attachments", "mentions")
        .order_by("-id")[:limit]
    )
    rows = list(reversed(list(rows)))
    # Ticks on the viewer's own messages: seen by the others, or - in a room
    # that relays - read on the client's phone.
    receipts = room_receipts(room, user, rows) if user is not None else {}
    reacts = reactions_for("message", [row.id for row in rows], user)
    items = []
    for row in rows:
        if row.is_system:
            continue
        quoted = row.reply_to
        receipt, seen_by = receipts.get(row.id, ("", []))
        items.append({
            "quote": _quote_text(quoted, user),
            "quote_who": (
                ("العميل" if quoted.from_client else (
                    quoted.sender.short_name if quoted.sender_id else ""))
                if quoted else ""
            ),
            "uid": f"g{room.id}-{row.id}",
            "kind": "in" if row.from_client else "out",
            "body": words_of(row, user),
            "subject": "",
            "channel": "",
            "at": row.created_at,
            "status": row.relay_status,
            "error": row.relay_error,
            "sender": row.sender.short_name if row.sender_id else "",
            "sender_id": row.sender_id or 0,
            "sender_avatar": avatars.url_of(row.sender) if row.sender_id else None,
            "is_delivery": False,
            # The task this message is work on (a file handed in from the
            # group), else the old room's own task.
            "task_code": (
                row.task.code if row.task_id else (room.task.code if room.task_id else "")
            ),
            "files": [_file_json(a) for a in row.relay_files],
            "mine": user is not None and row.sender_id == user.pk,
            "receipt": receipt,
            "seen_by": seen_by,
            "forwarded": row.forwarded,
            # Who this message pinged (by id: a name is not unique), and whether it pinged the viewer.
            "mentions": [{"id": person.pk, "name": person.short_name} for person in row.mentions.all()],
            "mentions_me": user is not None and any(person.pk == user.pk for person in row.mentions.all()),
            "reactions": reacts.get(row.id, []),
            "reactions_sig": reactions_sig(reacts.get(row.id, [])),
            # Taken back by its sender: the bubble says so and has nothing else. ``can_unsend``: this person may take it back.
            "unsent": row.unsent_at is not None,
            "can_unsend": can_unsend(user, row),
        })
    return items


#: What takes the place of a message its sender took back, in a list's snippet.
UNSENT_SNIPPET_AR = "الرسالة اتمسحت"


def can_unsend(user, message):
    """Whether ``user`` may take this message back.

    Only the sender, and only what stayed inside: a message of a work group or a colleague's chat. Anything that was (or
    could have been) relayed to a client is final - WhatsApp and e-mail give us no way to delete it on their phone, and a
    message that vanished from our screen while still sitting on theirs would be a lie about what the client was told.
    Work on a task (a file handed in, a step of the hand-over) is the task's record and stays, and so does anything that
    carries a client's words or files (``origin_client``): that is the client's record, not the sender's.
    """
    if user is None or message is None or message.is_system or message.unsent_at is not None:
        return False
    if message.sender_id != user.pk or message.task_id or message.inbound_id or message.origin_client_id:
        return False
    if message.room.kind not in (RoomKind.STAFF, RoomKind.TEAM):
        return False
    return not any(a.origin_client_id for a in message.attachments.all())


@transaction.atomic
def unsend_message(user, source_code, uid):
    """Take back a message the person sent. Returns ``(ok, error)``: ``not_found`` or ``not_allowed``.

    The row stays, so the thread keeps its shape and the others see "deleted" where it was; the words, the files, the
    mentions and the reactions go. A copy somebody forwarded keeps its own words (as it does on WhatsApp). The act is
    written to the audit log - who, where, which message - without the words.
    """
    from .models import ChatReaction

    source = _chat_ref(user, source_code)
    if source is None or source[0] != "room":
        return False, "not_found"
    room = source[1]
    side, _, raw = str(uid or "").rpartition("-")
    if side != f"g{room.pk}" or not raw.isdecimal():
        return False, "not_found"
    message = (
        room.messages.select_for_update().select_related("room")
        .filter(pk=int(raw), is_system=False).first()
    )
    if message is None:
        return False, "not_found"
    if not can_unsend(user, message):
        # A colleague's message, or one that may not be taken back, reads the same to someone who may not touch it.
        return False, "not_allowed"
    stored = [(a.file.storage, a.file.name) for a in message.attachments.all()]
    message.attachments.all().delete()
    ChatReaction.objects.filter(message=message).delete()
    message.mentions.clear()
    message.body = ""
    message.unsent_at = timezone.now()
    message.save(update_fields=["body", "unsent_at"])
    _remove_unreferenced_files(stored)
    log(user, "chat.unsend", f"g{room.pk}-{message.pk}")
    return True, ""


def muted_ids(user):
    """``({room ids}, {client ids})`` this person has muted."""
    rooms, clients = set(), set()
    for room_id, client_id in ChatMute.objects.filter(user=user).values_list("room_id", "client_id"):
        if room_id:
            rooms.add(room_id)
        else:
            clients.add(client_id)
    return rooms, clients


def is_muted(user, room=None, client=None):
    if room is not None:
        return ChatMute.objects.filter(user=user, room=room).exists()
    return client is not None and ChatMute.objects.filter(user=user, client=client).exists()


def muted_user_ids(room=None, client=None):
    """The ids of the people who muted this room or this client's chat: they are not notified of what is said in it."""
    if room is not None:
        return set(ChatMute.objects.filter(room=room).values_list("user_id", flat=True))
    if client is not None:
        return set(ChatMute.objects.filter(client=client).values_list("user_id", flat=True))
    return set()


def set_muted(user, source_code, muted):
    """Mute or un-mute a conversation this person can open. Returns ``(ok, error)``.

    Resolved by ``_chat_ref`` like every other chats door, so a code of somewhere this person may not look finds nothing.
    A colleague nobody has written to yet has no room to mute.
    """
    source = _chat_ref(user, source_code)
    if source is None:
        return False, "not_found"
    where, target = source
    field = "room" if where == "room" else "client"
    if muted:
        ChatMute.objects.get_or_create(user=user, **{field: target})
    else:
        ChatMute.objects.filter(user=user, **{field: target}).delete()
    return True, ""


def words_of(message, viewer):
    """A room message's words as ``viewer`` may read them.

    A client's own words are forwarded into a room only where everybody in it may read them (``forward_messages``:
    the operation and the admin) - unless the admin opens them (``words_open``, the owner's choice). That is a rule about
    who reads, so it holds when somebody reads, not only when it is written: whoever is seated in the room afterwards - a
    translator, a team leader, HR - sees the files and not the client's words, the same as if they had been forwarded to
    them, unless the admin opened these. (The row says whose words they are: ``origin_client``.)
    """
    if message.unsent_at is not None:
        return ""
    if message.origin_client_id and not (
        viewer is not None and (viewer.is_operation or viewer.is_admin_role)
    ):
        if not message.words_open:
            return ""
        # The admin sent them here on purpose: they are read, but the client stays a code and a number stays out.
        from . import identity

        return identity.mask_client(message.body, message.origin_client, viewer)
    return message.body


def _quote_text(message, viewer=None):
    """A one-line stand-in for a quoted message — its text, or its file's name."""
    if message is None:
        return ""
    text = (words_of(message, viewer) or "").strip()
    if not text:
        first = next(iter(message.relay_files), None)
        text = (first.original_name or first.file.name) if first else ""
    return text[:160]


def _room_last_preview(room, user, last, files=None, receipt=None):
    """The list snippet for a room's newest message, with the same ticks the
    bubble inside shows.

    Only your own message gets ticks - the list used to put a check in front
    of anybody's, and a single grey one at that, while the conversation
    itself already showed two blue ones. Same rule on both sides now.

    ``files`` and ``receipt`` are for a list that has already fetched them for
    every room at once (``chatlists``); left out, each is asked of the database
    here, for this one room.
    """
    text = words_of(last, user) or _attachment_snippet(last.relay_files if files is None else files)
    if last.unsent_at is not None:
        text = UNSENT_SNIPPET_AR
    mine = user is not None and last.sender_id == user.pk
    ticks = ""
    if mine:
        ticks = room_receipts(room, user, [last]).get(last.id, ("", []))[0] if receipt is None else receipt
    return {
        "text": text[:70], "at": last.created_at, "outgoing": mine,
        "status": last.relay_status or "", "receipt": ticks, "mine": mine,
    }


def _empty_group_preview(room):
    return {"text": "", "at": room.created_at, "outgoing": False}


def group_preview(room, user):
    """The snippet shown for a group in the conversation list."""
    last = room.messages.exclude(is_system=True).order_by("-id").first()
    if last is None:
        last = room.messages.order_by("-id").first()
    if last is None:
        return _empty_group_preview(room)
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


def may_add_members(user, room):
    """May ``user`` add people to ``room``?

    Never to a private line between two people: a third would read everything the two already said. A work
    group reaches nobody outside, so whoever may open one may add to one. Adding somebody to a client room hands
    them a live line to that client, so that stays behind the client-group setting.
    """
    if room.kind == RoomKind.STAFF:
        return False
    if room.is_team_group:
        return user.can_create_team_group
    # A room with a client in it is for the people who talk to clients, and only they may add to it.
    return user.handles_clients and AppSettings.load().can_create_group(user)


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

    from . import chatlists

    rooms = {
        room.pair_key: room
        for room in ChatRoom.objects.filter(kind=RoomKind.STAFF, members=viewer)
    }
    # One fetch for every room, not one per person (``chatlists``).
    facts = chatlists.group_facts(viewer, list(rooms.values()), staff=True)

    rows = []
    for person in people:
        room = rooms.get(staff_pair_key(viewer.pk, person.pk))
        preview = facts[room.pk]["preview"] if room is not None else {"text": "", "at": None, "outgoing": False}
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
    # Only the people who talk to clients (the operation, Sales, the admin) are ever shown a client room, seat or no
    # seat: the list would carry its title and the last thing the client wrote, even though ``ChatRoom.can_access``
    # refuses to open it. A translator is refused first, as there.
    qs = ChatRoom.objects.filter(
        mine if (user.is_translator or not user.handles_clients) else (mine | theirs)
    )
    # A task's room is listed only to someone who may open the task: a seat
    # that outlived the assignment would otherwise show the title, the unread
    # count and the last thing the client wrote, for a room that answers 404.
    qs = qs.filter(Q(task__isnull=True) | Q(task__in=visible_tasks(user)))
    # Archived rooms stay readable by their URL and stay out of the list.
    qs = qs.exclude(is_archived=True)
    query = (query or "").strip()
    if query:
        qs = qs.filter(
            Q(title__icontains=query)
            | Q(client__code__icontains=query)
            | Q(task__code__icontains=query)
        )
    return (
        qs.select_related("client", "task", "task__client")
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
    # A Sales person's own conversation stays theirs: the rooms are watched
    # by the operation room and the task team. So does a letter to somebody's
    # own address, and one the admin keeps for themselves.
    if inbound.owner_id:
        return None
    if inbound.channel == Channel.EMAIL:
        from . import lines

        if lines._unassigned_mail_is_admins():
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
    # The notification quotes the client's words, so each member is put to the
    # same test as opening the room (``can_open``): a stale membership row, a
    # person taken off the task, or a translator seated here by hand gets
    # nothing - not a preview, not a sound.
    silenced = muted_user_ids(room=room)
    recipients = [
        m for m in room.members.exclude(role__in=[Role.OPERATION, Role.ADMIN])
        if room.can_open(m) and m.pk not in silenced
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
    # Translator first, as in ``ChatRoom.can_access``; then anybody who does not talk to clients.
    if user.is_translator or not user.handles_clients:
        qs = qs.exclude(kind=RoomKind.CLIENT)
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
def lead_translator_group(lead, translator):
    """The work group of one team leader and one translator - found, or opened.

    Decided 23/09/2026: a task the leader hands a translator lives in *their
    group*, the one named "مترجم: <translator> · ليدر: <leader>", not in the
    private one-to-one chat. The private chat stays theirs for anything else.

    Found in this order, so nobody ends up with a second group for the same
    pair: the group carrying exactly that name; else a group of just the two
    of them; else a new one, opened the way the leader would open it by hand
    (``create_team_group`` - same name, same note, same "you were added").
    Archived groups are not reused.
    """
    room = find_lead_translator_group(lead, translator)
    if room is not None:
        return room
    title = default_team_group_name(lead, [translator])
    room, _error = create_team_group(lead, title, [translator])
    return room


def find_lead_translator_group(lead, translator):
    """``lead_translator_group`` without the opening: ``None`` if there is none.

    For reading - the task page links the group, and a page view must not
    open one as a side effect.
    """
    if lead is None or translator is None:
        return None
    title = default_team_group_name(lead, [translator])
    rooms = list(
        ChatRoom.objects.filter(kind=RoomKind.TEAM, is_archived=False, members=lead)
        .filter(members=translator).order_by("id")
    )
    for room in rooms:
        if room.title == title:
            return room
    for room in rooms:
        if room.members.count() == 2:
            return room
    return None


def room_url_for(room, viewer):
    """Where this room opens on the chats page, for this person.

    A staff chat opens by the *other* person's id (``/ops/chats/u/<id>/``);
    a group by its own (``/ops/chats/g/<id>/``). Linking a staff chat by
    ``g/<id>`` - which the hand-off prompt used to - is a 404.
    """
    if room is None:
        return ""
    if room.kind == RoomKind.STAFF:
        other = room.other_member(viewer)
        return f"/ops/chats/u/{other.pk}/" if other else ""
    return f"/ops/chats/g/{room.id}/"


def pair_room(one, two):
    """Where a task step between these two people is written.

    A team leader and a translator: their work group (see
    ``lead_translator_group``). Anyone else: the one-to-one chat, as before.
    """
    if one is None or two is None or one.pk == two.pk:
        return None
    lead, translator = None, None
    if one.is_team_lead and two.is_translator:
        lead, translator = one, two
    elif two.is_team_lead and one.is_translator:
        lead, translator = two, one
    if lead is not None:
        room = lead_translator_group(lead, translator)
        if room is not None:
            return room
    return staff_room(one, two)


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
        return pair_room(one, two)
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


def live_stamp():
    """A short fingerprint of "has anything on the boards moved".

    Polled with the heartbeat. When it changes, an open list page (tasks,
    the leader's and translator's desks, the overview) fetches itself again
    and swaps the parts marked ``data-live`` - so a board left open all day
    stays current without a reload (28/09/2026).

    Global on purpose: it says only *that* something changed, never what or
    for whom, so it leaks nothing, and the page that re-fetches itself still
    goes through its own permission checks. Every workflow step notifies
    somebody, which is why the newest notification id is in it.
    """
    import hashlib

    from django.db.models import Count, Max

    from .models import Notification

    tasks = Task.objects.aggregate(n=Count("id"), at=Max("updated_at"))
    assignments = Assignment.objects.aggregate(
        top=Max("id"), answered=Max("responded_at"), opened=Max("opened_at"),
    )
    top_note = Notification.objects.aggregate(top=Max("id"))["top"]
    raw = "|".join(str(x) for x in (
        tasks["n"], tasks["at"], assignments["top"], assignments["answered"],
        assignments["opened"], top_note,
    ))
    return hashlib.sha1(raw.encode()).hexdigest()[:16]


def task_live_stamp(task):
    """The same, for one task's page: status, files, the AI check, hand-offs.

    ``None`` when there is no such task, or the viewer may not see it - the
    page they have open then simply stops following it.
    """
    import hashlib

    from django.db.models import Max

    latest_ai = task.ai_checks.order_by("-id").values_list("id", "status").first()
    files = ChatAttachment.objects.filter(task_files_filter(task)).aggregate(top=Max("id"))
    handoffs = task.assignments.aggregate(top=Max("id"), answered=Max("responded_at"))
    raw = "|".join(str(x) for x in (
        task.status, task.updated_at, files["top"], latest_ai,
        handoffs.get("top"), handoffs.get("answered"),
        getattr(task, "word_count", None), getattr(task, "word_count_state", None),
    ))
    return hashlib.sha1(raw.encode()).hexdigest()[:16]


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
    # A staff chat, or a work group - the leader and translator's group is
    # where a handed-over task lives now (``lead_translator_group``).
    if room.kind not in (RoomKind.STAFF, RoomKind.TEAM) or message.sender_id is None:
        return None
    # No file, no deliverable. The guard lives here rather than in the caller:
    # a rule that only holds while every caller remembers it is not a rule.
    if not message.attachments.exists():
        return None
    # Everyone in the room has to be on the task: a group with a third person
    # in it could be about anything, and guessing is what this refuses to do.
    # The admin is left out of that count: an owner who joined a group to
    # watch it is not a third party the files could be about, and counting
    # them is what left a translator's file untagged (27/09/2026).
    pair = set(
        room.members.exclude(role=Role.ADMIN).exclude(is_superuser=True)
        .values_list("pk", flat=True)
    ) | {message.sender_id}
    if len(pair) < 2:
        return None
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


#: The value the chat's task picker sends for "these files are not on a task".
NO_TASK = "none"


def file_task_choices(user, room):
    """The tasks a file ``user`` sends in ``room`` could belong to.

    A live task the sender works on together with somebody else in this room
    (the admin, who joins groups to watch them, does not count as that
    somebody). The chat asks the sender to pick one of these when they attach
    files - see ``pick_file_task``.

    Empty for a client room or a task's own room: those already say which
    task they are about.
    """
    if user is None or room is None or room.kind not in (RoomKind.STAFF, RoomKind.TEAM):
        return []
    members = set(room.members.values_list("pk", flat=True))
    if user.pk not in members:
        return []
    others = set(
        room.members.exclude(pk=user.pk).exclude(role=Role.ADMIN)
        .exclude(is_superuser=True).values_list("pk", flat=True)
    )
    return _shared_tasks(user, others)


def file_task_choices_with(user, other):
    """What ``file_task_choices`` would say for the one-to-one chat with ``other`` - before that room exists.

    A first message to a colleague opens the room; the files in it are asked about the same tasks as in any
    other message of the chat, so the page needs the answer before it has anything to open.
    """
    if user is None or other is None or other.pk == user.pk or other.is_admin_role:
        return []
    return _shared_tasks(user, {other.pk})


def _shared_tasks(user, others):
    """The live tasks ``user`` works on together with somebody in ``others`` (ids)."""
    if not others:
        return []
    mine = (
        Q(created_by=user) | Q(team_lead=user) | Q(translator=user)
    )
    theirs = (
        Q(created_by_id__in=others) | Q(team_lead_id__in=others)
        | Q(translator_id__in=others)
    )
    return list(
        Task.objects.filter(status__in=ACTIVE_TASK_STATUSES)
        .filter(mine).filter(theirs)
        .select_related("client").distinct().order_by("id")
    )


def short_name(name, limit=250):
    """``name`` cut to fit a file-name column, keeping its extension.

    Django accepts an upload name up to 255 characters and the columns hold 250: on Postgres the longer
    one is an error after the message around it has been written, which left a half-written message behind.
    """
    name = str(name or "")
    if len(name) <= limit:
        return name
    stem, extension = os.path.splitext(name)
    extension = extension[:12]
    return stem[: limit - len(extension)] + extension


PICK_TASK_AR = "حدد الملفات دي تبع أنهي تاسك قبل ما تبعت."
PICK_TASK_EN = "Pick which task these files are for before sending."
BAD_TASK_AR = "التاسك دي مش من التاسكات اللي بينك وبين الناس في الشات ده. حدّث الصفحة واختار تاني."
BAD_TASK_EN = "That task is not one you share with this chat. Reload and pick again."


def pick_file_task(user, room, raw):
    """Which task files sent now belong to, from the chat's task picker.

    Returns ``(task, error_code, choices)``:

    - ``raw`` is a task code among the choices -> that task.
    - ``raw`` is ``NO_TASK`` -> ``None``; the sender said so.
    - nothing picked, one choice -> that one (the picker shows it preselected).
    - nothing picked, more than one -> ``"pick_task"``. Guessing is what put a
      translator's file on TSK-00003 while they were working on TSK-00004
      (28/09/2026), so the sender is asked instead.
    - a code that is not a choice -> ``"bad_task"``: it comes from the browser.
    - no choices at all -> ``None``, and the caller falls back to
      ``tag_task_message``.
    """
    return _pick_from(file_task_choices(user, room), raw)


def pick_file_task_with(user, other, raw):
    """``pick_file_task`` for the one-to-one chat with ``other`` before that room exists (a first message)."""
    return _pick_from(file_task_choices_with(user, other), raw)


def _pick_from(choices, raw):
    raw = (raw or "").strip()
    if raw == NO_TASK:
        return None, "", choices
    if raw:
        task = next((t for t in choices if t.code == raw), None)
        return (task, "", choices) if task else (None, "bad_task", choices)
    if len(choices) == 1:
        return choices[0], "", choices
    if len(choices) > 1:
        return None, "pick_task", choices
    return None, "", choices


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
        room = pair_room(from_user, to_user)
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
        room = pair_room(by_user, assignment.assignee)
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


def leads_online():
    """The team leaders who have the site open right now (the same "online" the team page and the task page show)."""
    return [lead for lead in User.objects.filter(role=Role.TEAM_LEAD, is_active=True) if lead.is_online]


def direct_translators():
    """The translators a task can be sent to without going through a team leader first.

    Only those who have an active leader: the leader keeps the review, the translator's date and the way back when
    the translator declines, so a translator under nobody would leave the task with no one to look at the work.
    """
    return list(
        User.objects.filter(role=Role.TRANSLATOR, is_active=True, team_lead__isnull=False, team_lead__is_active=True)
        .select_related("team_lead").prefetch_related("shifts").order_by("first_name", "username")
    )


@transaction.atomic
def assign_direct_to_translator(task, translator, by_user, note=""):
    """The operation gives a new task straight to a translator, because no team leader is here to hand it out.

    The task becomes the translator's own leader's (so the review, the translator's date and a refusal all go where they
    always go), the translator has the usual window to say yes, and the leader - who is away - is told what was done in
    their team, in the notification they will find when they open the site. Nothing is skipped after this: the
    leader still reviews before the operation takes the task over.
    """
    lead = translator.team_lead
    task.team_lead = lead
    task.lead_accepted_at = None
    task.save(update_fields=["team_lead", "lead_accepted_at", "updated_at"])
    assignment = assign_to_translator(task, translator, by_user, note=note)
    notify(
        lead,
        title_ar="تاسك اتبعتت لمترجم عندك",
        title_en="A task was sent to a translator of yours",
        body_ar=f"{by_user.short_name} بعت {task.code} لـ{translator.short_name} مباشرة لأن مفيش تيم ليدر أونلاين. المراجعة عندك.",
        body_en=f"{by_user.short_name} sent {task.code} straight to {translator.short_name} because no team leader was online. The review is yours.",
        level="info", url=f"/tasks/{task.code}/", task=task,
    )
    log(by_user, "task.assign_direct", task.code, f"→ {translator} (leader {lead}, no leader online)")
    return assignment


#: What the leader is told when he hands a job over: the three ways it can be wrong (07/10/2026).
PICK_TRANSLATOR_DEADLINE_AR = "اختار تبعت للمترجم نفس الديدلاين ولا ديدلاين أقل."
TYPE_SHORTER_DEADLINE_AR = "اخترت ديدلاين أقل: اكتب كام يوم أو ساعة أو دقيقة، أو اختار نفس الديدلاين."
SHORTER_THAN_OPERATIONS_AR = "الديدلاين اللي للمترجم لازم يكون أقل من ديدلاين الأوبريشن."


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
            body_ar=(f"ديدلاين {task.code}: {clock.fmt12(due, 'ar', '%Y-%m-%d')}"
                     if due else "الديدلاين اتشال."),
            body_en=(f"Deadline for {task.code}: {clock.fmt12(due, 'en', '%Y-%m-%d')}"
                     if due else "Deadline cleared."),
            level="info", url=f"/tasks/{task.code}/", sound=True, task=task,
        )
    log(by_user, "task.translator_deadline", task.code,
        f"{timezone.localtime(moment):%Y-%m-%d %H:%M}" if moment else "cleared")
    return True, ""


#: The most a translator can ask for in one go. A request for a month is a
#: conversation with the leader, not a button.
MAX_EXTENSION_MINUTES = 14 * 24 * 60


def _moment_text(moment):
    return clock.fmt12(moment, "ar", "%Y-%m-%d") if moment else "—"


def extension_new_due(task, minutes, now=None):
    """Where the translator's deadline lands if ``minutes`` are added now.

    Added to the deadline they are working to; if that has already passed,
    to now - more time on a date gone by would still be a date gone by.
    """
    now = now or timezone.now()
    due = task.translator_due
    base = due if (due and due > now) else now
    return base + timedelta(minutes=int(minutes))


def extension_state(task, user):
    """What a task page shows about requests for more time, for this person.

    The translator sees their own request and the answer. The team leader
    (and the admin) sees the open one with where the deadline would land -
    and the client's date next to it, which the translator never sees.
    """
    from .models import ExtensionRequest

    is_translator = task.translator_id == user.id
    is_lead = task.team_lead_id == user.id or user.is_admin_role
    if not (is_translator or is_lead):
        return {}
    rows = list(task.extension_requests.select_related("requested_by", "decided_by")[:5])
    pending = next((r for r in rows if r.status == ExtensionRequest.Status.PENDING), None)
    last = next((r for r in rows if r.status != ExtensionRequest.Status.PENDING), None)
    return {
        "extension_pending": pending,
        "extension_last": last,
        "extension_new_due": (
            extension_new_due(task, pending.minutes) if pending and is_lead else None
        ),
        "extension_can_ask": (
            is_translator and task.status == TaskStatus.IN_PROGRESS and pending is None
        ),
        "extension_can_decide": is_lead and pending is not None,
    }


def request_extension(task, user, minutes, reason=""):
    """The translator asks the team leader for more time. ``(request, error)``.

    Nothing moves until the leader answers. One open request per task.
    """
    from .models import ExtensionRequest

    if task.translator_id != user.id:
        return None, "التاسك دي مش بتاعتك."
    if task.status != TaskStatus.IN_PROGRESS:
        return None, "الطلب بيتبعت والتاسك شغالة بس."
    if not task.team_lead_id:
        return None, "مفيش تيم ليدر على التاسك دي."
    try:
        minutes = int(minutes)
    except (TypeError, ValueError):
        minutes = 0
    if minutes <= 0:
        return None, "اكتب قد إيه محتاج — يوم أو ساعة أو دقايق."
    if minutes > MAX_EXTENSION_MINUTES:
        return None, "أقصى طلب مرة واحدة 14 يوم."
    if task.extension_requests.filter(status=ExtensionRequest.Status.PENDING).exists():
        return None, "عندك طلب لسه التيم ليدر مارّدش عليه."

    reason = (reason or "").strip()[:300]
    row = ExtensionRequest.objects.create(
        task=task, requested_by=user, minutes=minutes, reason=reason,
        due_before=task.translator_due,
    )
    new_due = extension_new_due(task, minutes)
    notify_in_chat(
        task.team_lead, user,
        body_ar=(f"{user.short_name} طالب وقت إضافي على {task.code}: {row.pretty_length}"
                 + (f" — {reason}" if reason else "")),
        body_en=f"{user.short_name} asks for more time on {task.code}: {minutes} min.",
        key="extension_asked",
    )
    notify(
        task.team_lead,
        title_ar="طلب وقت إضافي",
        title_en="More time requested",
        body_ar=(f"{user.short_name} عايز {row.pretty_length} زيادة على {task.code} "
                 f"(الديدلاين الجديد: {_moment_text(new_due)})."),
        body_en=f"{user.short_name} asks for {minutes} more minutes on {task.code}.",
        level="warning", url=f"/tasks/{task.code}/", sound=True, task=task,
    )
    log(user, "task.extension_asked", task.code, f"{minutes}m {reason}"[:200])
    return row, ""


def decide_extension(row, user, approve, note=""):
    """The team leader answers a request for more time. ``(ok, error)``.

    A yes moves the translator's own deadline - never past the client's. When
    what was asked would cross it, the answer says how far it can go instead
    of quietly giving less: the leader decides that, not the system.
    """
    from .models import ExtensionRequest

    task = row.task
    if task.team_lead_id != user.id and not user.is_admin_role:
        return False, "الطلب ده للتيم ليدر بتاع التاسك."
    if row.status != ExtensionRequest.Status.PENDING:
        return False, "الطلب ده اتردّ عليه قبل كده."

    note = (note or "").strip()[:300]
    now = timezone.now()
    if approve:
        if task.status != TaskStatus.IN_PROGRESS:
            return False, "التاسك مابقتش شغالة."
        new_due = extension_new_due(task, row.minutes, now)
        problem = deadline_problem(task, new_due)
        if problem:
            return False, (
                f"الوقت ده بيعدّي ديدلاين العميل ({_moment_text(task.deadline)}). "
                "يا تدّي أقل من ديدلاين المترجم، يا الأوبريشن يمد ديدلاين العميل الأول."
            )
        ok, error = set_translator_deadline(task, new_due, user, tell_translator=False)
        if not ok:
            return False, error
        row.status = ExtensionRequest.Status.APPROVED
    else:
        row.status = ExtensionRequest.Status.DECLINED
    row.decided_by = user
    row.decided_at = now
    row.decision_note = note
    row.save(update_fields=["status", "decided_by", "decided_at", "decision_note"])

    translator = task.translator
    if approve:
        body_ar = f"التيم ليدر وافق على الوقت الإضافي. الديدلاين الجديد: {_moment_text(task.translator_due)}"
        title_ar, title_en, level = "اتوافق على الوقت الإضافي", "More time approved", "success"
    else:
        body_ar = "التيم ليدر رفض الوقت الإضافي." + (f" {note}" if note else "")
        title_ar, title_en, level = "اترفض طلب الوقت الإضافي", "More time declined", "warning"
    notify_in_chat(
        translator, user,
        body_ar=f"{task.code}: {body_ar}",
        body_en=f"{task.code}: {title_en}.",
        key="extension_answered",
    )
    notify(
        translator, title_ar=title_ar, title_en=title_en,
        body_ar=body_ar, body_en=title_en,
        level=level, url=f"/tasks/{task.code}/", sound=True, task=task,
    )
    log(user, "task.extension_approved" if approve else "task.extension_declined",
        task.code, f"{row.minutes}m {note}"[:200])
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


#: ``assign_to_translator(deadline=KEEP_DEADLINE)``: leave the translator's date as it is. ``None`` is a choice too: the same as the client's.
KEEP_DEADLINE = object()


@transaction.atomic
def assign_to_translator(task, translator, by_user, note="", deadline=KEEP_DEADLINE):
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
    # The date the leader is giving them, which is theirs alone: a moment (shorter than the client's), or ``None`` for the same as the
    # client's. Not saying leaves whatever was there.
    if deadline is not KEEP_DEADLINE:
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


def _lock_assignment(assignment):
    """Read the assignment's state under a row lock, so two answers (an accept and a sweep that expires it, two sweeps) are
    taken one at a time and the second sees what the first did."""
    row = Assignment.objects.select_for_update().filter(pk=assignment.pk).values("status", "penalty_applied").first()
    if row is not None:
        assignment.status = row["status"]
        assignment.penalty_applied = row["penalty_applied"]


@transaction.atomic
def accept_assignment(assignment, user):
    """Confirm an assignment. Returns ``(ok, reason)``."""
    if assignment.assignee_id != user.id:
        return False, "forbidden"
    _lock_assignment(assignment)
    if assignment.status != AssignmentStatus.PENDING:
        return False, assignment.status
    # An offer the task has moved on from (it was handed to somebody else since) is not a job to accept.
    held = assignment.task.team_lead_id if assignment.target_role == Role.TEAM_LEAD else assignment.task.translator_id
    if held is not None and held != assignment.assignee_id:
        return False, AssignmentStatus.CANCELLED
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
                body_ar=f"ديدلاين {task.code}: {clock.fmt12(due, 'ar', '%Y-%m-%d')}",
                body_en=f"Deadline for {task.code}: {clock.fmt12(due, 'en', '%Y-%m-%d')}",
                level="info", url=f"/tasks/{task.code}/", task=task,
            )
    log(user, "assignment.accept", task.code)
    return True, "accepted"


@transaction.atomic
def expire_assignment(assignment):
    """Mark a pending assignment as expired, apply the penalty and alert."""
    _lock_assignment(assignment)
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
    if assignment.assignee_id != user.id:
        return False, "التسليمة دي مش مستنية ردك."
    _lock_assignment(assignment)
    if assignment.status != AssignmentStatus.PENDING:
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
                priority="normal", source_lang="", target_lang="", messages=None,
                origin=""):
    # The request's own channel wins over anything passed in: it is the fact.
    # ``origin`` is for the case with no messages - a follow-up on a task that
    # already had them.
    for message in messages or []:
        if message.channel in (Channel.WHATSAPP, Channel.EMAIL):
            origin = message.channel
            break
    if origin not in (Channel.WHATSAPP, Channel.EMAIL):
        origin = ""
    task = Task.objects.create(
        client=client, title=title, created_by=created_by,
        description=description, deadline=deadline, priority=priority,
        source_lang=source_lang, target_lang=target_lang,
        status=TaskStatus.NEW, origin=origin,
    )
    for message in messages or []:
        # A message already behind a task stays with that one: a new request
        # on the same material reaches its files through ``source_files``.
        if message.task_id is None:
            message.task = task
            message.save(update_fields=["task"])
    log(created_by, "task.create", task.code)
    return task


def mark_translated(task, user):
    if task.translator_id != user.id and not user.is_admin_role:
        return False
    # Only a job being worked can be handed in. A delivered or cancelled one handed in again would come back to life, and its
    # words (counted by the day they were translated) would move into another month's pay.
    if task.status != TaskStatus.IN_PROGRESS:
        return False
    # "Finished" with nothing handed in used to go through. It does not any
    # more: the translator's file is what the review, the AI check, the word
    # count and the delivery all read, so no file means nothing is finished.
    if translation_missing(task):
        return False
    task.status = TaskStatus.UNDER_REVIEW
    task.translated_at = timezone.now()
    task.save(update_fields=["status", "translated_at", "updated_at"])

    # The word count is typed by a person now (28/09/2026) - nothing is read
    # out of the files. A number somebody already typed (on the new-task
    # form, or on the task page) stands; otherwise the task is marked as
    # waiting for one, which is what the payroll page warns about.
    from .models import WordCountState

    if task.word_count_state != WordCountState.CONFIRMED:
        task.word_count_state = (
            WordCountState.CONFIRMED if task.word_count else WordCountState.MANUAL_NEEDED
        )
        task.word_count_note = "" if task.word_count else "اكتب عدد الكلمات بإيدك"
        task.save(update_fields=["word_count_state", "word_count_note", "updated_at"])

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


def share_reviewed_files(task, lead, updated=False):
    """Put the reviewed translation into the leader's chat with the operation.

    What goes is the leader's own version when he uploaded one (``final_files``), the translator's file otherwise.
    ``updated`` says these files replace what the operation was given at the review: the leader fixed something after
    pressing it, and the card says so.

    The operation used to hear "reviewed" and then go to the task page to find
    the files. Now the files arrive in the private chat with the leader, under
    a card that says which task they are, and the operation forwards them to
    the client's chat from there (28/09/2026).

    Two messages on purpose:

    - the card is a system line, so it can never be forwarded - it carries the
      task code and the title, which are ours, not the client's;
    - the files go in a message of their own with no text, so forwarding it
      sends the client the files and nothing else.

    The file message carries no ``task``: the translator's own message already
    does, and a second link would list every file twice for delivery and
    count its words twice. Each file is marked as that client's
    (``origin_client``), which is what stops it being forwarded to anybody
    else and masks its name for whoever may not see the client.

    Returns the file message, or ``None`` when there is nothing to send or
    nobody to send it to. Best effort: never undoes the review.
    """
    ops = task.created_by
    if ops is None or lead is None or ops.pk == lead.pk:
        return None
    try:
        files = final_files(task)
        room = pair_room(lead, ops)
        if room is None or not files:
            return None
        langs = " → ".join(x for x in (task.source_lang, task.target_lang) if x)
        facts = " · ".join(x for x in (task.code, task.client.code, task.title, langs) if x)
        with transaction.atomic():
            system_message(
                room, key="reviewed_files",
                body_ar=(
                    (
                        f"تحديث من التيم ليدر - النسخة المعدّلة بدل اللي اتبعتت قبل كده: {facts} · {len(files)} ملف. "
                        if updated else f"الترجمة النهائية بعد المراجعة: {facts} · {len(files)} ملف. "
                    )
                    + "تقدر تستلمها وتبعتها للعميل: حدد رسالة الملفات اللي تحت وحوّلها لشات العميل."
                ),
                body_en=(
                    (
                        f"Update from the team leader - the corrected version replaces what was sent before: {facts} · {len(files)} file(s). "
                        if updated else f"Final translation after review: {facts} · {len(files)} file(s). "
                    )
                    + "Pick the files message below and forward it to the client's chat."
                ),
            )
            message = ChatMessage.objects.create(room=room, sender=lead, body="")
            for attachment in files:
                ChatAttachment.objects.create(
                    message=message, file=attachment.file.name,
                    original_name=attachment.original_name
                    or attachment.file.name.rsplit("/", 1)[-1],
                    size=attachment.size or 0, origin_client_id=task.client_id,
                )
        log(lead, "task.reviewed_files_shared", task.code, f"{len(files)} file(s)")
        return message
    except Exception:  # noqa: BLE001 - a chat message must never undo a review
        logger.exception("could not share the reviewed files for %s", task.code)
        return None


def mark_reviewed(task, user):
    if task.team_lead_id != user.id and not user.is_admin_role:
        return False
    # A review closes a translation that is waiting for one. A press on a job still being worked, delivered or cancelled is
    # refused (a second press on a reviewed one is the idempotent case below).
    if task.status not in (TaskStatus.UNDER_REVIEW, TaskStatus.REVIEWED):
        return False
    # A second press on a reviewed task must not post the files again.
    already = task.status == TaskStatus.REVIEWED
    task.status = TaskStatus.REVIEWED
    task.reviewed_at = timezone.now()
    task.save(update_fields=["status", "reviewed_at", "updated_at"])
    # The last leg up: the reviewed files land in the leader's private chat
    # with whoever opened the task, and they forward them to the client.
    # With no file to send, the plain note is still written.
    shared = None if already else share_reviewed_files(task, task.team_lead or user)
    if shared is None and not already:
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


def channel_from(client, last_channel):
    """The channel to answer on, given the channel of the client's newest message (or ``None``)."""
    if last_channel in (Channel.WHATSAPP, Channel.EMAIL):
        return last_channel
    if client.all_phones:
        return Channel.WHATSAPP
    if client.all_emails:
        return Channel.EMAIL
    return ""


def client_channel(client):
    """How we last heard from this client — that's how we answer back."""
    last = client.messages.order_by("-received_at").first()
    return channel_from(client, last.channel if last else None)


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


#: How long a send in flight keeps a second one off the same job. A send takes seconds; a row older than this is a crash's.
DELIVERY_CLAIM_SECONDS = 180


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
    # The number / address they last wrote from, if it is one of theirs.
    target = client.reply_target(channel)

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

    # One send at a time per job. The files leave before the job is marked delivered, so two presses (a double click, two people
    # on the operation desk) would both find it reviewed and both send. The first writes a "sending" row under a lock on the
    # job; the second finds it and waits for it to finish. A row left by a crash stops counting after a few minutes.
    with transaction.atomic():
        Task.objects.select_for_update().filter(pk=task.pk).first()
        in_flight = OutboundMessage.objects.filter(
            task=task, kind=OutboundMessage.Kind.DELIVERY, status=OutboundMessage.Status.SENDING,
            created_at__gte=timezone.now() - timedelta(seconds=DELIVERY_CLAIM_SECONDS),
        ).exists()
        if in_flight:
            delivery.status = OutboundMessage.Status.FAILED
            delivery.error_message = "فيه إرسال شغال للتاسك دي دلوقتي — استنى لحد ما يخلص وراجع التاسك."
            return False, delivery, delivery.error_message
        delivery.status = OutboundMessage.Status.SENDING
        delivery.save()

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
        from . import identity

        # SMTP and Meta quote the recipient back in a refusal; the operation who sends this must not learn it.
        # The audit log keeps the original.
        delivery.status = OutboundMessage.Status.FAILED
        delivery.error_message = identity.scrub_contacts(exc.message_ar)
        delivery.save()
        log(user, "task.deliver_failed", task.code, exc.message_en[:200])
        notify(
            user,
            title_ar="التسليم فشل",
            title_en="Delivery failed",
            body_ar=identity.scrub_contacts(exc.message_ar)[:380],
            body_en=identity.scrub_contacts(exc.message_en)[:380],
            level="danger", url=f"/tasks/{task.code}/", task=task,
        )
        return False, delivery, delivery.error_message

    delivery.status = OutboundMessage.Status.SENT
    delivery.save()
    mark_delivered(task, user, delivery=delivery)
    return True, delivery, ""


def mark_delivered(task, user, delivery=None):
    if not (user.is_operation or user.is_admin_role):
        return False
    # A finished job is not delivered twice. The operation closes a job it has taken over (reviewed, and acknowledged: nothing
    # reaches the client before that); the owner may close any job still open.
    if task.status in (TaskStatus.DELIVERED, TaskStatus.CANCELLED):
        return False
    if not user.is_admin_role and (task.status != TaskStatus.REVIEWED or not task.handover_ack_at):
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
    # What was delivered stays delivered (its words are in somebody's pay) and a cancelled job is already cancelled.
    if task.status in (TaskStatus.DELIVERED, TaskStatus.CANCELLED):
        return False
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

    from . import lines

    # Which line(s): the company's for the operation, their own for Sales,
    # all of them for the admin. In the same filter() as the channel, so it
    # is one join and the Max below counts only messages on those lines.
    on_line = lines.line_q(user, "messages__owner")
    # WhatsApp only — this list is the WhatsApp line. A client we have only
    # ever e-mailed belongs on the mail page, not in a chat with no thread.
    if user.is_admin_role:
        rows = Client.objects.filter(messages__channel=Channel.WHATSAPP)
    else:
        # One filter, one join: the operation never sees a conversation made
        # only of rate-blocked messages, and the Max below then reflects only
        # the messages that role is allowed to know about.
        rows = Client.objects.filter(
            on_line, messages__channel=Channel.WHATSAPP, messages__is_rate_blocked=False
        )
    rows = rows.annotate(
        last_activity=Max(
            "messages__received_at",
            filter=Q(messages__channel=Channel.WHATSAPP) & on_line,
        )
    ).distinct()

    query = (query or "").strip()
    if query:
        # Searching a name is seeing it (identity.py): only for who may.
        if user.can_see_client_identity:
            rows = rows.filter(
                Q(code__icontains=query)
                | Q(name__icontains=query)
                | Q(company__icontains=query)
                | Q(phone__icontains=query)
                | Q(extra_phones__icontains=query)
                | Q(email__icontains=query)
                | Q(extra_emails__icontains=query)
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
    from . import lines

    qs = client.messages.filter(channel=Channel.WHATSAPP).filter(
        lines.line_q(user)
    ).prefetch_related("attachments")
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
    if all(is_image(a) for a in rows):
        return "صورة" if len(rows) == 1 else f"{len(rows)} صور"
    return f"{len(rows)} ملف"


#: What a browser draws in an <img> everywhere. SVG is left out on purpose:
#: it is a document that can carry script, not a picture, and it stays a link.
_IMAGE_EXTENSIONS = (".jpg", ".jpeg", ".png", ".gif", ".webp", ".bmp")


def is_image(attachment):
    """True when the file can be shown in the bubble instead of as a link."""
    mime = (getattr(attachment, "mime", "") or "").lower()
    name = (attachment.original_name or attachment.file.name or "").lower()
    if mime == "image/svg+xml" or name.endswith(".svg"):
        return False
    return mime.startswith("image/") or name.endswith(_IMAGE_EXTENSIONS)


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
        # A photo is shown as a photo; anything else stays a link.
        "image": is_image(attachment),
    }


def conversation_preview(client, user):
    """The snippet shown in the conversation list."""
    from . import lines

    last = _visible_inbound(client, user).order_by("-received_at").first()
    out = (
        client.deliveries.filter(channel=Channel.WHATSAPP).filter(lines.line_q(user))
        .prefetch_related("uploads").order_by("-created_at").first()
    )
    return preview_from(last, out)


def preview_from(last, out):
    """The list snippet, from the newest message the client sent (``last``) and the newest we sent (``out``).

    Which of the two the person may see is decided where they are fetched; this
    is only what the row says about them, once for one row and once for a list.
    """
    # A reply whose files are still being stored is not in the thread yet (``client_thread``), so it is not the last thing said.
    state = _writing_state(out) if out and not out.uploads.all() else ""
    if state == "writing":
        out = None
    # An outbound with nothing from the client before it is still the last
    # thing said - it used to fall through and leave the row blank.
    if out and (last is None or out.created_at > last.received_at):
        text = out.body or _attachment_snippet(out.uploads.all())
        if text == "—" and out.file_count:
            text = f"{out.file_count} ملف"
        status = OutboundMessage.Status.FAILED if state == "stuck" else out.status
        # The same ticks as the bubble: one grey, two grey, two blue.
        return {
            "text": text[:70], "at": out.created_at, "outgoing": True,
            "status": status, "mine": True,
            "receipt": out.wa_receipt if status == OutboundMessage.Status.SENT else "",
        }
    if last:
        text = clean_client_text(last.body) or _attachment_snippet(last.attachments.all())
        return {"text": text[:70], "at": last.received_at, "outgoing": False}
    return {"text": "", "at": None, "outgoing": False}


#: How long a reply may take to get its files stored and sent before it is told as a send that broke (a worker that was
#: killed half way leaves a row that nothing will ever finish).
WRITING_MINUTES = 5


def _writing_state(row):
    """What a chat reply to a client is doing right now: ``""`` (nothing unusual), ``"writing"`` or ``"stuck"``.

    ``send_client_message`` writes the row first and its files after, and storing them (and converting a
    recording) takes seconds. A page that asked in between would draw the names with no picture or player
    and then turn them into the real thing a moment later, so a reply that is ``writing`` is left out until
    its files are there. One that has been at it for ``WRITING_MINUTES`` is ``stuck``: it is shown, as a send
    that failed, so that nothing a person sent is ever missing from the thread. A reply that failed is shown as
    it is, and so is a delivery (its files never become rows).
    """
    if row.kind != OutboundMessage.Kind.CHAT or row.status == OutboundMessage.Status.FAILED:
        return ""
    if not row.files or not all(entry.get("status") == "pending" for entry in row.files):
        return ""
    if row.created_at > timezone.now() - timedelta(minutes=WRITING_MINUTES):
        return "writing"
    return "stuck"


def client_thread(client, user, limit=200):
    """Merged inbound + outbound timeline for one client, oldest first."""
    items = []

    for row in _visible_inbound(client, user).order_by("-received_at")[:limit]:
        files = [_file_json(a) for a in row.attachments.all()]
        items.append({
            "kind": "in",
            "id": row.id,
            "uid": f"in-{row.id}",
            # "[image]" is what the webhook writes for a file with no caption;
            # with the picture right there in the bubble it only says it twice.
            "body": clean_client_text(row.body) if files else row.body,
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
    from . import lines

    outbound = (
        client.deliveries.filter(channel=Channel.WHATSAPP).filter(lines.line_q(user))
        .select_related("created_by", "task").prefetch_related("uploads")
    )
    for row in outbound.order_by("-created_at")[:limit]:
        files = [_file_json(a) for a in row.uploads.all()]
        writing = _writing_state(row) if not files else ""
        if writing == "writing":
            continue
        # A reply nothing finished is a send that broke, however it was left in the row.
        status = OutboundMessage.Status.FAILED if writing == "stuck" else row.status
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
            "status": status,
            "error": SEND_UNSURE_AR if writing == "stuck" else row.error_message,
            "is_delivery": row.kind == OutboundMessage.Kind.DELIVERY,
            "task_code": row.task.code if row.task_id else "",
            "sender": row.created_by.short_name if row.created_by_id else "",
            "sender_id": row.created_by_id or 0,
            "sender_avatar": avatars.url_of(row.created_by) if row.created_by_id else None,
            "wamid": row.provider_id or "",
            "reply_to": row.reply_to_wamid or "",
            "quote": row.reply_preview or "",
            "files": files,
            # Delivered / read on the client's phone, as WhatsApp reported it.
            # Only a message that actually left can have got anywhere.
            "receipt": row.wa_receipt if status == OutboundMessage.Status.SENT else "",
        })

    items.sort(key=lambda entry: entry["at"])
    _resolve_quotes(items)
    # Reactions, one query per side.
    ins = reactions_for("inbound", [e["id"] for e in items if e["kind"] == "in"], user)
    outs = reactions_for("outbound", [e["id"] for e in items if e["kind"] == "out"], user)
    for entry in items:
        found = (ins if entry["kind"] == "in" else outs).get(entry["id"], [])
        entry["reactions"] = found
        entry["reactions_sig"] = reactions_sig(found)
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


def mark_room_read(user, room, upto=None):
    """``user`` has read this room up to its newest message - or, with ``upto``, up to that message.

    ``upto`` is for a page that fetched the messages and says "read" a moment later: what arrived in
    between has not been on anybody's screen, and is not read.
    """
    from django.db.models import Max

    if user is None or room is None:
        return False
    messages = room.messages.all()
    if upto is not None:
        messages = messages.filter(id__lte=upto)
    top = messages.aggregate(top=Max("id"))["top"] or 0
    cursor = _read_cursor(user, room=room)
    before = cursor.last_read_id
    moved = _advance(cursor, top)
    if moved:
        _tell_senders_seen(user, room, before, top)
    return moved


def _tell_senders_seen(reader, room, before, top):
    """Ring the people whose messages ``reader`` has just read, so the "seen by" under them fills in at once.

    Only they are rung, not the whole room: a room of ten that reads one message would otherwise ask every page
    for the thread nine more times, for a line that only the sender draws. The ring carries nothing (see
    ``realtime``): the page asks for the thread, as it does for any other change.
    """
    from . import realtime

    senders = set(
        room.messages.filter(id__gt=before, id__lte=top, is_system=False, sender__isnull=False)
        .exclude(sender=reader).values_list("sender_id", flat=True).distinct()
    )
    if senders:
        realtime.push_room_to(room.pk, senders)


def _wa_inbound(client, user):
    """The client's WhatsApp messages this person is allowed to know about."""
    from . import lines

    qs = InboundMessage.objects.filter(client=client, channel=Channel.WHATSAPP).filter(
        lines.line_q(user)
    )
    if not user.is_admin_role:
        qs = qs.filter(is_rate_blocked=False)
    return qs


def mark_client_read(user, client, receipt=True, upto=None):
    """``user`` opened the conversation with this client. True when it moved.

    When it moved, the client is told too: WhatsApp's read receipt on the
    newest message turns every tick before it blue on their phone. That was
    a decision (23/09/2026), not a default - pass ``receipt=False`` to read
    without telling.

    ``upto`` (an inbound message id) is for a page that fetched the thread and says "read" a
    moment later: the receipt goes for the newest message *it showed*, and anything the client
    wrote in between stays unread - their phone is not told it was seen when nobody saw it.
    """
    if user is None or client is None:
        return False
    if not user.handles_clients:
        return False
    visible = _wa_inbound(client, user)
    if upto is not None:
        visible = visible.filter(id__lte=upto)
    newest = visible.order_by("-id").values_list(
        "id", "external_id", "owner__wa_phone_number_id"
    ).first()
    if not newest:
        return False
    moved = _advance(_read_cursor(user, client=client), newest[0])
    if moved and receipt and newest[1]:
        # Marked read on the number it arrived on - a Sales line's own.
        if newest[2]:
            send_read_receipt(newest[1], from_id=newest[2])
        else:
            send_read_receipt(newest[1])
    return moved


def send_read_receipt(wamid, from_id=""):
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
        f"{whatsapp.sender_id(conf, from_id)}/messages"
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

    from . import lines

    if not user.handles_clients:
        return {}
    qs = InboundMessage.objects.filter(
        channel=Channel.WHATSAPP, client__isnull=False
    ).filter(lines.line_q(user))
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


def _listed_rooms(user):
    """The rooms this person's chats page lists, in any tab, as a query."""
    mine = Q(members=user, kind__in=CHAT_ROOM_KINDS)
    if user.is_admin_role:
        mine |= Q(kind=RoomKind.CLIENT)
    rooms = ChatRoom.objects.filter(mine).exclude(is_archived=True)
    # Counting unread messages in a room they may not open would still tell
    # them the client is writing. The translator rule overrides the admin one,
    # as in ``ChatRoom.can_access``: a superuser whose role is still the
    # default "translator" is refused client rooms there, so they are not
    # counted here either.
    if user.is_translator or not user.handles_clients:
        rooms = rooms.exclude(kind=RoomKind.CLIENT)
    rooms = rooms.filter(Q(task__isnull=True) | Q(task__in=visible_tasks(user)))
    return rooms.distinct()


def listed_room_ids(user):
    """Every room this person's chats page lists, in any tab."""
    return list(_listed_rooms(user).values_list("id", flat=True))


def unread_chat_breakdown(user):
    """``(messages unread in every tab of the chats, {tab: conversations with something unread})``.

    The first is the sidebar badge. The second is what each tab draws on its own button, in conversations and not in messages:
    ``clients`` (a client's chat), ``groups`` (the work groups and the client rooms, which share the tab) and ``staff`` (the
    one-to-one chats with a colleague). One pass over the client messages and one over the rooms, for all of them.
    """
    # A muted conversation keeps its own number in the list but is not counted in the badge or on the tabs.
    muted_rooms, muted_clients = muted_ids(user)
    by_client = {k: v for k, v in unread_by_client(user).items() if k not in muted_clients}
    kinds = {k: v for k, v in _listed_rooms(user).values_list("id", "kind") if k not in muted_rooms}
    by_room = unread_by_room(user, kinds)
    tabs = {"clients": len(by_client), "groups": 0, "staff": 0}
    for room_id in by_room:
        tabs["staff" if kinds.get(room_id) == RoomKind.STAFF else "groups"] += 1
    return sum(by_client.values()) + sum(by_room.values()), tabs


def unread_chat_counts(user):
    """``(messages unread in every tab of the chats, clients with something unread)``: the first is the sidebar badge, the
    second is the clients tab's own (conversations, not messages)."""
    total, tabs = unread_chat_breakdown(user)
    return total, tabs["clients"]


def unread_chat_total(user):
    """The sidebar badge: everything unread across every tab of the chats."""
    return unread_chat_counts(user)[0]


def receipt_of(room, row, other_ids, cursors):
    """``(receipt, [ids of the people who read it])`` for one of the viewer's own messages.

    The one rule, for a single room and for a list of them: in a staff chat or a
    work group a message has been seen once everybody else in the room has read
    past it (``cursors`` is {person id: last message read}); a room that relays
    to a client is read on the client's phone, so WhatsApp's own receipt wins.
    """
    if room.reaches_client:
        return row.relay_receipt, []
    readers = [pk for pk in other_ids if cursors.get(pk, 0) >= row.id]
    seen = bool(other_ids) and len(readers) == len(other_ids)
    return ("read" if seen else ""), readers


def room_receipts(room, viewer, rows):
    """{message id: (receipt, [names who read it])} for the viewer's own messages.

    In a staff chat or a work group, a message has been seen once everybody
    else in the room has read past it. The names are kept for a group, where
    "two of three" is worth being able to find out. A room that relays to a
    client is read on the client's phone, so WhatsApp's own receipt wins - and
    its names are still the room's own people who have read it.
    """
    mine = [row for row in rows if row.sender_id == viewer.pk and not row.is_system]
    if not mine:
        return {}

    others = [m for m in room.members.all() if m.pk != viewer.pk]
    if room.reaches_client:
        # Whoever kept a seat after losing the right to open the room (a changed role) has not "read" anything of it.
        others = [m for m in others if m.is_active and room.can_open(m)]
    cursors = dict(
        ChatRead.objects.filter(room=room, user__in=others)
        .values_list("user_id", "last_read_id")
    )
    by_id = {m.pk: m for m in others}
    out = {}
    for row in mine:
        receipt, readers = receipt_of(room, row, list(by_id), cursors)
        if room.reaches_client:
            # The ticks are the client's phone's; the names are which of the room's own people have read it.
            readers = [pk for pk in by_id if cursors.get(pk, 0) >= row.id]
        out[row.id] = (receipt, [by_id[pk].short_name for pk in readers])
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
        from . import identity

        # Meta's own words: they may quote the number or address back, and they are shown to the whole room.
        reason = identity.scrub_contacts((error or "WhatsApp reported the message as not delivered.")[:500])
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
# A task's own files, and its text without the placeholders
# ---------------------------------------------------------------------------

#: What the webhook writes as the body of a file sent with no caption
#: (``webhooks._body_of``): "[document]", "[image]"... Useful in a chat
#: bubble next to the file, meaningless as a task's description.
_PLACEHOLDER_LINE = r"^\s*\[[a-z_]+\]\s*$"


def clean_client_text(text):
    """The client's text with the "[document]" / "[image]" lines taken out."""
    import re

    lines = [
        line for line in (text or "").splitlines()
        if not re.match(_PLACEHOLDER_LINE, line)
    ]
    return re.sub(r"\n{3,}", "\n\n", "\n".join(lines)).strip()


def task_source_files(task):
    """The client files this task is about, for the top of the task page.

    The ones the operation ticked when making it; nothing ticked means every
    file on the messages it was made from - the same rule
    ``share_source_files`` uses for what reaches the translator, so the page
    and the chat never disagree about what the job is. Voice notes are left
    out: they are talk, not a document to translate.
    """
    picked = list(task.source_files.select_related("message").order_by("message__received_at", "id"))
    if not picked:
        from .models import MessageAttachment

        picked = list(
            MessageAttachment.objects.filter(message__task=task)
            .select_related("message").order_by("message__received_at", "id")
        )
    return [a for a in picked if not a.is_audio]


def translator_files(task, since=None):
    """The files the translator handed in on this task, oldest first.

    Wherever they were handed in: uploaded from the task page, or dropped in
    their group and tagged there (``tag_task_message``) - both carry the task
    on the message. Voice notes are talk, not a translation, and are left out.
    ``since`` keeps only what came in after that moment.
    """
    if not task.translator_id:
        return []
    qs = (
        ChatAttachment.objects
        .filter(task_files_filter(task), message__sender_id=task.translator_id)
        .select_related("message")
        .order_by("id")
    )
    if since is not None:
        qs = qs.filter(message__created_at__gt=since)
    return [a for a in qs if not a.is_audio]


def reviewed_files(task):
    """The files the team leader (or the admin) uploaded on this task as the version he corrected (``upload_reviewed``).

    Only an upload from the task page counts: a file he sent in chat - notes, instructions, a sample - is not the translation, even
    when it carries the task. And only what came after the translator's newest file: a file from before it was the version the
    translator then replaced. Voice notes are talk, and are left out.
    """
    translated = translator_files(task)
    since = max((a.message.created_at for a in translated), default=None)
    qs = (
        ChatAttachment.objects
        .filter(task_files_filter(task), message__reviewed_version=True)
        .select_related("message")
        .order_by("id")
    )
    if since is not None:
        qs = qs.filter(message__created_at__gt=since)
    return [a for a in qs if not a.is_audio]


def final_files(task):
    """What goes on to the operation and, ticked, to the client: the leader's corrected version when there is one, else the translator's.

    After a send-back only a translator file that came in after it counts, as in ``translation_missing``.
    """
    return reviewed_files(task) or translator_files(task, since=task.returned_at) or translator_files(task)


UPLOAD_REVIEWED_STATUSES = (TaskStatus.UNDER_REVIEW, TaskStatus.REVIEWED)


def can_upload_reviewed(task, user):
    """The task's own team leader and the admin, while the task is under review or reviewed and not yet sent on to the client."""
    if user is None or not (user.is_admin_role or (user.is_team_lead and task.team_lead_id == user.pk)):
        return False
    return task.status in UPLOAD_REVIEWED_STATUSES


def upload_reviewed(task, user, uploads):
    """The team leader hands in the file he corrected, from the task page: ``(message, error)``.

    It is what the review sends on (``final_files``). Uploaded before «تمت المراجعة», it waits for it and goes with it; after it
    (he noticed something once it was pressed), it goes to the operation at once, under a card that says it replaces what they
    were given. Errors: ``forbidden``, ``bad_status`` (not under review, or already delivered), ``empty``, ``no_room``.
    """
    if not (user.is_admin_role or (user.is_team_lead and task.team_lead_id == user.pk)):
        return None, "forbidden"
    if task.status not in UPLOAD_REVIEWED_STATUSES:
        return None, "bad_status"
    uploads = [u for u in (uploads or []) if u]
    if not uploads:
        return None, "empty"
    lead = task.team_lead or user
    room = pair_room(lead, task.translator) or pair_room(lead, task.created_by)
    if room is None:
        return None, "no_room"

    with transaction.atomic():
        message = ChatMessage.objects.create(
            room=room, sender=user, task=task, body=f"النسخة بعد المراجعة - {task.code}", reviewed_version=True,
        )
        for item in uploads:
            ChatAttachment.objects.create(message=message, file=item, original_name=short_name(item.name), size=item.size)
    log(user, "task.reviewed_uploaded", task.code, str(len(uploads)))
    if task.status == TaskStatus.REVIEWED:
        # Pressed already: what the operation holds is the old version, so the new one is sent on to them now.
        share_reviewed_files(task, lead, updated=True)
    return message, ""


TRANSLATION_MISSING_AR = "ارفع ملف الترجمة الأول من صفحة التاسك، وبعدين دوس «خلصت»."
TRANSLATION_MISSING_EN = "Upload the translated file on the task page first, then press Finished."


def translation_missing(task):
    """True while there is nothing to review: no translator file on the task.

    After a send-back only a file that came in after it counts - the one the
    leader returned is the version that was not good enough.
    """
    return not translator_files(task, since=task.returned_at)


def upload_translation(task, user, uploads, body=""):
    """The translator hands in the translated file from the task page.

    It goes where the rest of the job is talked about - the group of the
    leader and the translator - so the leader sees it there without anybody
    forwarding it, and the message carries the task so the page, the review,
    the word count and the delivery all find it. No guessing is involved:
    the page it came from says which task it is.

    Returns ``(message, error)``.
    """
    if task.translator_id != user.id:
        return None, "forbidden"
    if task.status != TaskStatus.IN_PROGRESS:
        return None, "bad_status"
    uploads = [u for u in (uploads or []) if u]
    if not uploads:
        return None, "empty"
    room = pair_room(task.team_lead, user)
    if room is None:
        return None, "no_room"

    with transaction.atomic():
        message = ChatMessage.objects.create(
            room=room, sender=user, task=task,
            body=(body or "").strip() or f"ملف الترجمة - {task.code}",
        )
        for item in uploads:
            ChatAttachment.objects.create(
                message=message, file=item, original_name=item.name, size=item.size,
            )

    notify(
        task.team_lead,
        title_ar="المترجم رفع ملف الترجمة",
        title_en="The translator uploaded the translation",
        body_ar=f"{user.short_name} رفع ملف الترجمة على {task.code}.",
        body_en=f"{user.short_name} uploaded the translation for {task.code}.",
        level="info", url=f"/tasks/{task.code}/", task=task,
    )
    log(user, "task.translation_uploaded", task.code, str(len(uploads)))
    return message, ""


def handin_tasks_for(user, room):
    """The tasks a translator may hand files in to from this group.

    Theirs, still being worked, and led by someone who is in this group - the
    files they pick here are then plainly that task's. Empty for anybody who
    is not a translator, and for rooms that are not work groups.
    """
    if user is None or not user.is_translator or room is None:
        return []
    if room.kind != RoomKind.TEAM:
        return []
    members = set(room.members.values_list("pk", flat=True))
    if user.pk not in members:
        return []
    return list(
        Task.objects.filter(
            translator=user, status=TaskStatus.IN_PROGRESS, team_lead_id__in=members,
        ).select_related("client").order_by("id")
    )


def hand_in_from_chat(task, user, attachment_ids):
    """«خلصت التاسك» from the group: the picked files become the task's, and
    the task goes to review. ``(ok, error)``.

    The translator ticks the files they sent in their group with the team
    leader; the messages carrying them are tagged with the task (the same
    link an upload from the task page makes), so the task page, the review,
    the word count and the delivery all find them. Then "finished" runs as
    if pressed on the task page - and refuses the same way if nothing that
    counts was handed in.

    A tag is per message: a message carrying three files that has one of
    them ticked brings all three.
    """
    if task.translator_id != user.id:
        return False, "التاسك دي مش بتاعتك."
    if task.status != TaskStatus.IN_PROGRESS:
        return False, "التاسك دي مش شغالة دلوقتي."
    ids = []
    for raw in attachment_ids or []:
        try:
            ids.append(int(raw))
        except (TypeError, ValueError):
            continue
    if not ids:
        return False, "اختار ملف الترجمة الأول."

    # Only files this person sent, in a work group the task's leader is in.
    # The ids come from the browser, so everything is checked again here.
    rows = [
        a for a in ChatAttachment.objects.filter(
            pk__in=ids, message__sender=user, message__room__kind=RoomKind.TEAM,
            message__room__members=task.team_lead_id,
        ).select_related("message").distinct()
        if not a.is_audio
    ]
    if not rows:
        return False, "الملفات دي مش ملفاتك في الجروب مع التيم ليدر."
    messages = {a.message_id: a.message for a in rows}.values()
    other = next((m for m in messages if m.task_id and m.task_id != task.pk), None)
    if other is not None:
        return False, "فيه ملف من دول متسجّل على تاسك تانية."

    for message in messages:
        if message.task_id != task.pk:
            message.task = task
            message.save(update_fields=["task"])
    log(user, "task.handed_in_from_chat", task.code, f"{len(rows)} file(s)")

    if translation_missing(task):
        # Tagged, but all of it older than the send-back: the leader returned
        # that version, so it cannot be the finished one.
        return False, "الملفات دي أقدم من رجوع التاسك للتعديل — ابعت النسخة الجديدة."
    if not mark_translated(task, user):
        return False, TRANSLATION_MISSING_AR
    return True, ""


def task_chat_link(task, viewer):
    """Where "open the chat" on the task page takes this person, or ``None``.

    The task has no chat of its own; its work lives in the conversation of the
    two people carrying the step. The leader and the translator - and the
    admin - go to their group. The operation goes to their chat with the
    leader. Nothing is opened by looking: the group is only found, and a
    staff chat opens itself when its page is visited.

    Returns ``{"url", "label_ar", "label_en"}``.
    """
    lead, translator, ops = task.team_lead, task.translator, task.created_by
    if lead is not None and translator is not None and (
        viewer.pk in (lead.pk, translator.pk) or viewer.is_admin_role
    ):
        room = find_lead_translator_group(lead, translator)
        if room is not None:
            return {
                "url": room_url_for(room, viewer),
                "label_ar": "افتح الجروب", "label_en": "Open the group",
            }
    other = None
    if lead is not None and viewer.pk != lead.pk and (
        viewer.is_operation or (ops is not None and viewer.pk == ops.pk)
    ):
        other = lead
    elif lead is not None and viewer.pk == lead.pk and ops is not None:
        other = ops
    if other is not None and other.pk != viewer.pk:
        return {
            "url": f"/ops/chats/u/{other.pk}/",
            "label_ar": f"افتح الشات مع {other.short_name}",
            "label_en": f"Open the chat with {other.short_name}",
        }
    return None


# ---------------------------------------------------------------------------
# Starting the tasks over (admin only)
# ---------------------------------------------------------------------------

def task_reset_counts():
    """What a reset would take with it - drawn on the page before anybody asks."""
    from .models import AICheckResult, Assignment, OutboundMessage

    return {
        "tasks": Task.objects.count(),
        "open": Task.objects.filter(status__in=ACTIVE_TASK_STATUSES).count(),
        "assignments": Assignment.objects.count(),
        "deliveries": OutboundMessage.objects.filter(task__isnull=False).count(),
        "ai_checks": AICheckResult.objects.count(),
        "rooms": ChatRoom.objects.filter(task__isnull=False).count(),
    }


#: Wrong passwords the two clear-outs allow in the window below, counted across both of them together. They delete real data
#: for good, and the password is what stands between that and a session left open on a desk: it must not be guessable at
#: the speed of a script. Counted from the audit rows the refusals already write, so it holds across processes and restarts.
RESET_WRONG_LIMIT = 5
RESET_LOCK_MINUTES = 15
RESET_LOCKED_MESSAGE = "محاولات باسورد غلط كتير. المسح اتقفل 15 دقيقة."
#: Every row that says "this person typed a wrong password": the clear-outs' and the profile's own change. One count for all of them,
#: so a person has five wrong tries in the window, not five at each door.
WRONG_PASSWORD_ACTIONS = (
    "task.reset_refused", "mail.reset_refused", "staff.reset_refused", "client.reset_refused", "profile.password_refused",
)
_RESET_WRONG_ACTIONS = WRONG_PASSWORD_ACTIONS


def reset_password_problem(admin, password, kind):
    """Why this admin's password does not open a clear-out (``kind`` is ``task`` or ``mail``), or ``""`` when it does.

    After ``RESET_WRONG_LIMIT`` wrong passwords in ``RESET_LOCK_MINUTES`` the clear-outs are shut to this admin, and a right
    password is no way in until the window has passed. A refusal while shut is written down as ``<kind>.reset_locked`` and is
    not counted: it does not push the end of the window further away for someone who simply waits.
    """
    since = timezone.now() - timedelta(minutes=RESET_LOCK_MINUTES)
    wrong = AuditLog.objects.filter(actor=admin, action__in=_RESET_WRONG_ACTIONS, created_at__gte=since).count()
    if wrong >= RESET_WRONG_LIMIT:
        log(admin, f"{kind}.reset_locked", "", "too many wrong passwords")
        return RESET_LOCKED_MESSAGE
    if not password or not admin.check_password(password):
        log(admin, f"{kind}.reset_refused", "", "wrong password")
        return "الباسورد غلط."
    return ""


def reset_all_tasks(admin, password):
    """Delete every task so numbering starts again at TSK-00001.

    Returns ``(ok, error_ar, backup_json, deleted)``.

    Decided with the owner 23/09/2026. Guarded three ways, because nothing
    else in the product is this final: the admin role, the admin's *own*
    password typed again (a session left open on a desk is not consent), and
    one transaction - it all goes, or none of it does.

    What goes with the tasks (CASCADE): their hand-offs, their deliveries to
    clients, their AI checks, their notifications and the old per-task rooms.
    What stays: every client message (``InboundMessage.task`` goes NULL, so a
    message can be turned into a task again), every staff chat and work group
    (a message's ``task`` goes NULL), ratings and violations (their ``task``
    goes NULL). Payroll reads production from tasks, so the current month's
    production goes with them - the page says so before the button.

    The JSON returned is a Django fixture of everything deleted, handed to the
    admin as a download. It is not stored on the server: files live on a
    public CDN here, and a backup full of client work does not belong there.
    """
    from django.core import serializers

    from .models import AICheckResult, Assignment, OutboundAttachment, OutboundMessage

    if admin is None or not admin.is_admin_role:
        return False, "الخطوة دي للأدمن بس.", "", 0
    problem = reset_password_problem(admin, password, "task")
    if problem:
        return False, problem, "", 0

    with transaction.atomic():
        tasks = list(Task.objects.all())
        deliveries = OutboundMessage.objects.filter(task__isnull=False)
        rooms = ChatRoom.objects.filter(task__isnull=False)
        # The client's files shared into a work chat for a task. The link to the task is what limited them to the files
        # operation ticked; once the task is gone the link is gone, and each would read as every file of its letter,
        # the unticked ones (a contract, a purchase order) included. They go with the task.
        shares = ChatMessage.objects.filter(task__isnull=False, inbound__isnull=False).exclude(room__kind=RoomKind.CLIENT)
        backup = serializers.serialize("json", [
            *tasks,
            *Assignment.objects.all(),
            *deliveries,
            *OutboundAttachment.objects.filter(message__in=deliveries),
            *AICheckResult.objects.all(),
            *rooms,
            *ChatMessage.objects.filter(room__in=rooms),
            *shares.exclude(room__in=rooms),
        ], indent=1, ensure_ascii=False)
        deleted = len(tasks)
        shares.delete()
        Task.objects.all().delete()
    log(admin, "task.reset", f"{deleted} task(s)", "all tasks deleted; numbering restarts")
    return True, "", backup, deleted


# ---------------------------------------------------------------------------
# Clearing the mail (admin only)
# ---------------------------------------------------------------------------

def _mail_to_clear():
    """``(letters, sent, kept_letters, kept_sent)`` - what goes, and what stays.

    A letter stays while a task stands on it: the task page reads the job's
    files off the letter's attachments (``Task.source_files``, or every file
    of the letter the task was made from), so deleting it would take the
    original documents out from under work in progress. The same goes for a
    delivery sent to the client on a task. Those leave with the task - the
    reset on the tasks page - and not before.
    """
    from .models import MessageAttachment, OutboundMessage

    used = MessageAttachment.objects.filter(tasks__isnull=False).values("message_id")
    mail = InboundMessage.objects.filter(channel=Channel.EMAIL)
    letters = mail.filter(task__isnull=True).exclude(pk__in=used)
    sent_all = OutboundMessage.objects.filter(channel=Channel.EMAIL)
    sent = sent_all.filter(task__isnull=True)
    return letters, sent, mail.count() - letters.count(), sent_all.count() - sent.count()


def mail_reset_counts():
    """What clearing the mail would take - drawn on the page before anybody asks."""
    from .models import MessageAttachment, OutboundAttachment

    letters, sent, kept_letters, kept_sent = _mail_to_clear()
    return {
        "letters": letters.count(),
        "sent": sent.count(),
        "files": (
            MessageAttachment.objects.filter(message__in=letters).count()
            + OutboundAttachment.objects.filter(message__in=sent).count()
        ),
        "kept_letters": kept_letters,
        "kept_sent": kept_sent,
    }


def _remove_unreferenced_files(stored):
    """Delete the stored copy of each file that no row points at any more.

    Forwarding moves a file into a chat without copying it, so the same
    stored name can be held by a chat attachment as well; that one is left
    alone. Best effort: a file that will not go is not worth failing the
    clear-out for, and the rows are already gone.
    """
    from .models import ChatAttachment, MessageAttachment, OutboundAttachment

    removed, seen = 0, set()
    for storage, name in stored:
        if not name or name in seen:
            continue
        seen.add(name)
        if any(
            model.objects.filter(file=name).exists()
            for model in (MessageAttachment, OutboundAttachment, ChatAttachment)
        ):
            continue
        try:
            storage.delete(name)
            removed += 1
        except Exception:  # noqa: BLE001 - see the docstring
            logging.getLogger(__name__).warning("could not delete stored file %s", name)
    return removed


def reset_all_mail(admin, password):
    """Delete every e-mail that no task depends on.

    Returns ``(ok, error_ar, backup_json, deleted, files_removed)``.

    Guarded the way the tasks reset is, because it is just as final: the admin
    role, the admin's own password typed again, one transaction. It covers
    every mailbox - the company's and each Sales person's own address - both
    the letters that came in and the replies that went out, with their
    attachments, and then the stored files nothing else uses. WhatsApp is not
    touched. Nothing is done to the real mailbox: a letter still unread there
    is fetched again by the next pull.

    The JSON is a Django fixture of the rows deleted (files are not in it),
    handed to the admin as a download and never kept on the server.
    """
    from django.core import serializers

    from .models import MessageAttachment, OutboundAttachment, OutboundMessage

    if admin is None or not admin.is_admin_role:
        return False, "الخطوة دي للأدمن بس.", "", 0, 0
    problem = reset_password_problem(admin, password, "mail")
    if problem:
        return False, problem, "", 0, 0

    with transaction.atomic():
        letters_qs, sent_qs, _kept_letters, _kept_sent = _mail_to_clear()
        letters = list(letters_qs)
        sent = list(sent_qs)
        letter_files = list(MessageAttachment.objects.filter(message__in=letters))
        sent_files = list(OutboundAttachment.objects.filter(message__in=sent))
        backup = serializers.serialize(
            "json", [*letters, *letter_files, *sent, *sent_files],
            indent=1, ensure_ascii=False,
        )
        stored = [(a.file.storage, a.file.name) for a in (*letter_files, *sent_files)]
        for model, rows in ((InboundMessage, letters), (OutboundMessage, sent)):
            ids = [row.pk for row in rows]
            for start in range(0, len(ids), 500):
                model.objects.filter(pk__in=ids[start:start + 500]).delete()
    deleted = len(letters) + len(sent)
    removed = _remove_unreferenced_files(stored)
    log(
        admin, "mail.reset", f"{deleted} mail(s)",
        f"{len(letters)} received, {len(sent)} sent, {removed} stored file(s) removed",
    )
    return True, "", backup, deleted, removed


# ---------------------------------------------------------------------------
# Clearing the staff (admin only)
# ---------------------------------------------------------------------------

STAFF_RESET_BLOCKED = "فيه تاسكات مبنية على رسايل أو ملفات تخص موظف هيتمسح (خط خاص أو ملف ترجمة). اعمل «ريستارت التاسكات» الأول وبعدين ارجع."
STAFF_RESET_RACE = "وصلت رسالة جديدة على خط خاص أثناء المسح. ماتمسحش حاجة، جرّب تاني."


def _staff_to_clear():
    """Everybody who is not an admin: the owner's own account, any other admin and the technical-support account stay."""
    return User.objects.exclude(role__in=(Role.ADMIN, Role.SUPPORT)).exclude(is_superuser=True)


def _staff_lines(ids):
    """``(letters, sent)``: the mail and the WhatsApp on these people's private lines (``owner``)."""
    from .models import OutboundMessage

    return InboundMessage.objects.filter(owner_id__in=ids), OutboundMessage.objects.filter(owner_id__in=ids)


def _lines_with_tasks(letters, sent):
    """How many of those messages (or their files) a task stands on: the same rule as the mail clear-out."""
    from .models import MessageAttachment

    return (
        letters.filter(task__isnull=False).count()
        + sent.filter(task__isnull=False).count()
        + MessageAttachment.objects.filter(message__in=letters, tasks__isnull=False).values("pk").distinct().count()
    )


def _staff_rooms(ids):
    """The internal rooms (not a client's) that one of these people is in: their conversations go with them."""
    found = ChatRoom.objects.exclude(kind=RoomKind.CLIENT).filter(members__in=ids).values_list("pk", flat=True)
    return ChatRoom.objects.filter(pk__in=list(found))


def _task_files_in(rooms):
    """The files shared in these rooms as work on a task (a translator's deliverable, a file sent for review): the task still needs them."""
    return ChatAttachment.objects.filter(message__room__in=rooms, message__task__isnull=False)


def staff_reset_counts():
    """What clearing the staff would take - drawn on the page before anybody asks."""
    from .models import LeaveRequest, PayrollLine, SalaryRecord, Shift, Violation, WorkDay

    staff = _staff_to_clear()
    ids = list(staff.values_list("pk", flat=True))
    letters, sent = _staff_lines(ids)
    return {
        "people": len(ids),
        "kept": User.objects.count() - len(ids),
        "shifts": Shift.objects.filter(user_id__in=ids).count(),
        "work_days": WorkDay.objects.filter(user_id__in=ids).count(),
        "leave": LeaveRequest.objects.filter(user_id__in=ids).count(),
        "salary_records": SalaryRecord.objects.filter(user_id__in=ids).count(),
        "payroll_lines": PayrollLine.objects.filter(user_id__in=ids).count(),
        "violations": Violation.objects.filter(user_id__in=ids).count(),
        "rooms": _staff_rooms(ids).count(),
        "line_letters": letters.count(),
        "line_sent": sent.count(),
        "line_blocked": _lines_with_tasks(letters, sent),
        "task_files_blocked": _task_files_in(_staff_rooms(ids)).count(),
        "lines_released": User.objects.filter(pk__in=ids).filter(~Q(wa_phone_number_id="") | ~Q(mail_alias="")).count(),
        "tasks_touched": Task.objects.filter(
            Q(translator_id__in=ids) | Q(team_lead_id__in=ids) | Q(created_by_id__in=ids),
        ).count(),
    }


def reset_all_staff(admin, password):
    """Delete every employee who is not an admin, with what is theirs, so the team can start again with real people.

    Returns ``(ok, error_ar, backup_json, deleted, files_removed)``.

    Guarded the way the other two clear-outs are, because it is just as final: the admin role, the admin's own password typed
    again (counted with the others' wrong tries), one transaction.

    What goes with a person (CASCADE, as the models say): their shifts, attendance, leave, salary records, payroll lines,
    violations, rating events, devices, notifications and call history. What goes by this function, because leaving it would be
    worse: the internal chats they were in (a conversation with nobody left in it), and the mail and WhatsApp on their private
    line - ``owner`` goes NULL when a person is deleted, and NULL is the company's line, so a Sales person's private letters
    would otherwise turn up in the operation's inbox. If a task stands on one of those letters, or on a file shared in one of
    those chats (a translator's deliverable), nothing is done and the answer says to clear the tasks first; the same if a new
    letter reaches a private line while this runs (the whole run is undone). What stays: every admin, the clients and their rooms
    (a message a deleted person sent there stays, with no name on it), tasks (they lose the people they named), candidates and
    vacancies, departments, shifts of the company, pay plans and the settings. A deleted person's audit rows stay, with their
    sign-in name written into the detail (the row's own link to the person goes NULL with them).

    The JSON is a Django fixture of what was deleted, without the password hashes, handed to the admin as a download and never
    kept on the server. It leaves out on purpose: the words and files of a one-to-one staff chat (the admin may not open those
    chats, so the file must not carry them either), and where people clocked in from, their devices, notifications and call history.
    """
    import json

    from django.core import serializers
    from django.db.models import Value
    from django.db.models.functions import Concat

    from .models import (
        LeaveRequest, MessageAttachment, OutboundAttachment, OvertimeClaim, PayrollLine, ProbationReview, RatingEvent,
        SalaryChangeRequest, SalaryRecord, ScheduleOverride, Shift, Violation, WorkDay,
    )

    if admin is None or not admin.is_admin_role:
        return False, "الخطوة دي للأدمن بس.", "", 0, 0
    problem = reset_password_problem(admin, password, "staff")
    if problem:
        return False, problem, "", 0, 0

    with transaction.atomic():
        people = list(_staff_to_clear())
        ids = [person.pk for person in people]
        if not ids:
            return True, "", "[]", 0, 0
        letters_qs, sent_qs = _staff_lines(ids)
        rooms_qs = _staff_rooms(ids)
        if _lines_with_tasks(letters_qs, sent_qs) or _task_files_in(rooms_qs).exists():
            return False, STAFF_RESET_BLOCKED, "", 0, 0
        letters, sent = list(letters_qs), list(sent_qs)
        rooms = list(rooms_qs)
        # A one-to-one staff chat is the two people's and nobody else's, the admin included: its words are not in the file.
        shared = [room for room in rooms if room.kind != RoomKind.STAFF]
        room_messages = list(ChatMessage.objects.filter(room__in=shared))
        letter_files = list(MessageAttachment.objects.filter(message__in=letters))
        sent_files = list(OutboundAttachment.objects.filter(message__in=sent))
        chat_files = list(ChatAttachment.objects.filter(message__in=room_messages))
        stored_chat_files = list(ChatAttachment.objects.filter(message__room__in=rooms))
        # The people without their password hashes: a file that is downloaded is not the place for them.
        keep = [field.name for field in User._meta.concrete_fields if field.name != "password"]
        rows = json.loads(serializers.serialize("json", people, fields=keep))
        mine = {"user_id__in": ids}
        rows += json.loads(serializers.serialize("json", [
            *Shift.objects.filter(**mine), *SalaryRecord.objects.filter(**mine), *SalaryChangeRequest.objects.filter(**mine),
            *LeaveRequest.objects.filter(**mine), *OvertimeClaim.objects.filter(**mine), *ScheduleOverride.objects.filter(**mine),
            *WorkDay.objects.filter(**mine), *PayrollLine.objects.filter(**mine), *Violation.objects.filter(**mine),
            *RatingEvent.objects.filter(**mine), *ProbationReview.objects.filter(**mine),
            *rooms, *room_messages, *chat_files, *letters, *letter_files, *sent, *sent_files,
        ]))
        backup = json.dumps(rows, indent=1, ensure_ascii=False)
        stored = [(a.file.storage, a.file.name) for a in (*letter_files, *sent_files, *stored_chat_files)]
        for person in people:
            for held in (person.avatar, person.contract):
                if held:
                    avatars._delete_after_commit(held.storage, held.name)
            # The row's link to the person goes NULL with them: what it was about is kept, and so is who did it.
            AuditLog.objects.filter(actor_id=person.pk).update(detail=Concat("detail", Value(f" [by {person.username}]")))
        # By id, from the snapshot the backup was made from, and in pieces (a long list is more than a query may hold).
        for model, pks in ((InboundMessage, [row.pk for row in letters]), (OutboundMessage, [row.pk for row in sent])):
            for start in range(0, len(pks), 500):
                model.objects.filter(pk__in=pks[start:start + 500]).delete()
        ChatRoom.objects.filter(pk__in=[room.pk for room in rooms]).delete()
        if InboundMessage.objects.filter(owner_id__in=ids).exists() or OutboundMessage.objects.filter(owner_id__in=ids).exists():
            # A letter reached a private line after the snapshot: deleting the person now would hand it to the company's line.
            transaction.set_rollback(True)
            return False, STAFF_RESET_RACE, "", 0, 0
        User.objects.filter(pk__in=ids).delete()
    removed = _remove_unreferenced_files(stored)
    log(
        admin, "staff.reset", f"{len(people)} staff",
        f"{len(rooms)} room(s), {len(letters) + len(sent)} line message(s), {removed} stored file(s) removed",
    )
    return True, "", backup, len(people), removed


# ---------------------------------------------------------------------------
# Deleting clients (admin only)
# ---------------------------------------------------------------------------

def automated_clients():
    """Clients that are only a robot's address: ``no-reply@`` and the like.

    Every one of them was made by ``resolve_client`` from a notice nobody can
    answer. A client with a phone number is somebody's WhatsApp and never
    counts, nor one with another address on file.
    """
    from .mailbox import AUTOMATED_SENDER_PATTERN

    return Client.objects.filter(
        email__iregex=AUTOMATED_SENDER_PATTERN, phone="", extra_phones="", extra_emails="",
    )


def client_delete_plan(clients):
    """For each client: what deleting them takes with them, or why it cannot.

    A client stays while a task stands on them - the task itself (``PROTECT``),
    or one of their files being a task's source - because deleting it would
    take the job's original documents out from under work in progress. What
    goes otherwise is the client, their letters and files, what was sent to
    them, and their old chat rooms; HR complaints and staff chats stay.
    """
    from django.db.models import Count

    from .models import ChatRoom, MessageAttachment, OutboundMessage

    clients = list(clients)
    ids = [c.pk for c in clients]

    def counts(queryset, key):
        return dict(queryset.order_by().values_list(key).annotate(n=Count("id")))

    has_tasks = set(Task.objects.filter(client_id__in=ids).values_list("client_id", flat=True))
    task_files = set(
        MessageAttachment.objects.filter(message__client_id__in=ids, tasks__isnull=False)
        .values_list("message__client_id", flat=True)
    )
    letters = counts(InboundMessage.objects.filter(client_id__in=ids), "client_id")
    files = counts(MessageAttachment.objects.filter(message__client_id__in=ids), "message__client_id")
    replies = counts(OutboundMessage.objects.filter(client_id__in=ids), "client_id")
    rooms = counts(ChatRoom.objects.filter(client_id__in=ids), "client_id")

    rows = []
    for client in clients:
        blocked = ""
        if client.pk in has_tasks:
            blocked = "عليه تاسكات."
        elif client.pk in task_files:
            blocked = "ملف من ملفاته مستخدم في تاسك."
        rows.append({
            "client": client, "blocked": blocked,
            "letters": letters.get(client.pk, 0), "files": files.get(client.pk, 0),
            "replies": replies.get(client.pk, 0), "rooms": rooms.get(client.pk, 0),
        })
    return rows


def delete_clients(admin, client_ids):
    """Delete the chosen clients that nothing depends on.

    Returns ``(ok, error_ar, deleted_codes, blocked_codes, files_removed)``.

    Admin only, one transaction. The clients' letters go with them - left
    behind they would sit in the inbox as "UNKNOWN", which is exactly the
    clutter this is for - and so do the stored files nothing else uses. The
    blockers are worked out again here, not trusted from the confirm page: a
    task can have been made from one of them since it was drawn.
    """
    from django.db.models import ProtectedError

    from .models import ChatAttachment, MessageAttachment, OutboundAttachment

    if admin is None or not admin.is_admin_role:
        return False, "الخطوة دي للأدمن بس.", [], [], 0

    ids = [int(x) for x in client_ids if str(x).isdecimal()]
    try:
        with transaction.atomic():
            plan = client_delete_plan(Client.objects.filter(pk__in=ids))
            doomed = [row["client"] for row in plan if not row["blocked"]]
            blocked = [row["client"].code for row in plan if row["blocked"]]
            if not doomed:
                return False, "مفيش عميل من اللي اخترتهم ينفع يتمسح.", [], blocked, 0

            doomed_ids = [c.pk for c in doomed]
            letters = InboundMessage.objects.filter(client_id__in=doomed_ids)
            stored = [
                (a.file.storage, a.file.name)
                for a in (
                    *MessageAttachment.objects.filter(message__in=letters),
                    *OutboundAttachment.objects.filter(message__client_id__in=doomed_ids),
                    *ChatAttachment.objects.filter(message__room__client_id__in=doomed_ids),
                )
            ]
            # What was forwarded out of their letters into other chats is their words too. Once the client is gone nothing says
            # whose words they were, and the rule that hides a client's words from a team leader reads the owner: the copies go
            # with the letters, and so do the files they carry.
            copies = ChatMessage.objects.filter(origin_client_id__in=doomed_ids)
            copied = ChatAttachment.objects.filter(Q(origin_client_id__in=doomed_ids) | Q(message__in=copies))
            stored.extend((a.file.storage, a.file.name) for a in copied)
            copied.delete()
            copies.delete()
            codes = [c.code for c in doomed]
            letters.delete()
            Client.objects.filter(pk__in=doomed_ids).delete()
    except ProtectedError:
        return False, "فيه تاسك لسه ماسك واحد من العملاء دول. محدش اتمسح.", [], [], 0

    removed = _remove_unreferenced_files(stored)
    # Codes, not names: the log is read by people who may not see a client's identity.
    log(admin, "client.delete", f"{len(codes)} client(s)", ", ".join(codes))
    return True, "", codes, blocked, removed


def delete_clients_safely(admin, client_ids, password):
    """``delete_clients``, behind what the two clear-outs ask: the owner's own password, and a backup of what goes.

    Returns ``(ok, error_ar, backup_json, deleted_codes, blocked_codes, files_removed)``. Deleting a client takes their
    letters, our replies and the chats built on them; a session left open on a desk is not consent, and there is no undo, so
    the password is typed again (the same lockout counts the wrong ones) and the rows are handed back as a fixture before they
    go. The backup holds rows, not the stored files: those are removed with the client.
    """
    from django.core import serializers

    from .models import (
        ChatAttachment, MessageAttachment, OutboundAttachment, OutboundMessage,
    )

    if admin is None or not admin.is_admin_role:
        return False, "الخطوة دي للأدمن بس.", "", [], [], 0
    problem = reset_password_problem(admin, password, "client")
    if problem:
        return False, problem, "", [], [], 0

    ids = [int(x) for x in client_ids if str(x).isdecimal()]
    plan = client_delete_plan(Client.objects.filter(pk__in=ids))
    doomed_ids = [row["client"].pk for row in plan if not row["blocked"]]
    letters = InboundMessage.objects.filter(client_id__in=doomed_ids)
    deliveries = OutboundMessage.objects.filter(client_id__in=doomed_ids)
    rooms = ChatRoom.objects.filter(client_id__in=doomed_ids)
    copies = ChatMessage.objects.filter(origin_client_id__in=doomed_ids)
    room_messages = ChatMessage.objects.filter(room__in=rooms)
    backup = serializers.serialize("json", [
        *Client.objects.filter(pk__in=doomed_ids),
        *letters,
        *MessageAttachment.objects.filter(message__in=letters),
        *deliveries,
        *OutboundAttachment.objects.filter(message__in=deliveries),
        *rooms,
        *room_messages,
        *copies.exclude(pk__in=room_messages.values("pk")),
        *ChatAttachment.objects.filter(Q(message__in=room_messages) | Q(message__in=copies) | Q(origin_client_id__in=doomed_ids)),
    ], indent=1, ensure_ascii=False)

    ok, error, codes, blocked, removed = delete_clients(admin, client_ids)
    if not ok:
        return False, error, "", [], blocked, 0
    return True, "", backup, codes, blocked, removed


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


#: How many closed tasks and rating events the translator's desk lists.
DESK_DONE = 20
DESK_RATING_EVENTS = 10


def translator_desk(user):
    """What the translator's own page lists: open tasks, recently closed ones, rating history.

    Only tasks where this person is the translator. The classic page and
    ``/api/v1/translator/home/`` both read it from here, so the two cannot come
    to show different people different work.
    """
    tasks = Task.objects.filter(translator=user).select_related("client", "team_lead")
    return {
        "open_tasks": tasks.filter(status__in=ACTIVE_TASK_STATUSES),
        "done_tasks": tasks.filter(status__in=[TaskStatus.DELIVERED, TaskStatus.CANCELLED])[:DESK_DONE],
        "rating_events": user.rating_events.all()[:DESK_RATING_EVENTS],
    }


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
    sees = user.can_see_client_identity
    if sees:
        match |= Q(client__name__icontains=query) | Q(client__company__icontains=query)
    from .templatetags.eagle_tags import STATUS_MAP

    rows = visible_tasks(user).filter(match).select_related("client").order_by("-created_at")
    # The title is free words and is often the client's own (the subject of their letter), so it is shown as this person
    # may read it (``Task.title_for``) and it is matched as they read it: a query that hits only the client's name
    # inside a title would otherwise tell a translator which tasks that name belongs to.
    found = []
    for task in rows[: limit if sees else limit * 6]:
        title = task.title_for(user)
        if not sees:
            seen = f"{task.code} {task.client.code if task.client_id else ''} {title}"
            if query.lower() not in seen.lower():
                continue
        found.append((task, title))
        if len(found) == limit:
            break
    return [
        {
            "code": task.code,
            "title": title,
            "origin": task.origin,
            "status_ar": STATUS_MAP.get(task.status, ("", task.status, ""))[1],
            "status_en": task.get_status_display(),
            "client": task.client.label_for(user) if task.client_id else "",
            "href": f"/tasks/{task.code}/",
        }
        for task, title in found
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
    from . import lines
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
        if not raw.isdecimal():
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
                # What the thread lists and nothing else: a WhatsApp message of a line this person works.
                # An id of a message of another line (a Sales person's own number) finds nothing.
                row = OutboundMessage.objects.filter(
                    pk=pk, client=client, channel=Channel.WHATSAPP
                ).filter(lines.line_q(user)).first()
                if row is not None:
                    add(row.created_at, row.body, client.pk,
                        [(a, client.pk) for a in row.uploads.all()])
        elif side == f"g{target.pk}":
            row = target.messages.filter(pk=pk, is_system=False, unsent_at__isnull=True).select_related(
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
        # Only files of messages this person may read: their line, and no rate-blocked one unless admin.
        rows = MessageAttachment.objects.filter(
            pk__in=[int(x) for x in attachment_ids if str(x).isdecimal()],
            message__in=_wa_inbound(client, user),
        ).select_related("message")
        for row in rows.order_by("message__received_at", "id"):
            add(row.message.received_at, "", client.pk, [(row, client.pk)])

    items.sort(key=lambda item: item["at"])
    return [item for item in items if item["text"] or item["files"]]


_TOO_MANY_TO_CLIENT_AR = "كتير على عميل في مرة واحدة: لحد %d. قسّمهم على كذا مرة."

#: The line a forwarded file goes to a client with when its sender wrote no caption for it.
FORWARD_FILE_CAPTION_AR = "مرفق ملف."


def forward_to_chat(user, source_code, target_code, uids=(), attachment_ids=(), note=""):
    """Forward messages and/or files. Returns ``(ok, error_ar, url)``."""
    ok, error, url, _written = forward_messages(
        user, source_code, target_code, uids=uids, attachment_ids=attachment_ids, note=note
    )
    return ok, error, url


def forward_messages(user, source_code, target_code, uids=(), attachment_ids=(), note="", max_relayed=None):
    """Forward messages and/or files. Returns ``(ok, error_ar, url, written)``.

    ``max_relayed`` (a number, or ``None`` for no limit) is the most that may go OUT to a client in one call - to a
    client's own conversation or to a room that relays to one: each is a send to WhatsApp, made while the page waits,
    and a request that outlasts the proxy ends in "not sure" and a second send of what already went.

    ``written`` says whether anything reached the target, even when ``ok`` is False: a group's relay that
    failed after the messages were in the room, or a client who got the first of three. A page that is told
    "nothing was forwarded" must be right, or it offers a second send of what has already arrived.
    """
    source = _chat_ref(user, source_code)
    if source is None:
        return False, "المحادثة دي مش متاحة ليك.", "", False
    target = _chat_ref(user, target_code, create_staff=True)
    if target is None:
        return False, "اختار شات تحوّل له.", "", False
    if target[0] == "room" and target[1].kind not in CHAT_ROOM_KINDS:
        return False, "مينفعش تحوّل للجروب ده.", "", False

    items = _forward_items(user, source, uids, attachment_ids)
    if not items:
        return False, "اختار رسالة أو ملف الأول.", "", False
    note = (note or "").strip()[:2000]

    if target[0] == "client":
        client = target[1]
        if not (user.is_operation or user.is_admin_role):
            return False, "التحويل للعميل للأوبريشن بس.", "", False
        owners = {item["text_owner"] for item in items if item["text"]}
        owners |= {owner for item in items for _f, owner in item["files"]}
        owners.discard(None)
        if owners - {client.pk}:
            return False, "مينفعش تحوّل رسايل أو ملفات عميل لعميل تاني.", "", False
        if max_relayed is not None and len(items) > max_relayed:
            return False, _TOO_MANY_TO_CLIENT_AR % max_relayed, "", False
        # What the client reads under a file is the caption the sender chose: the note, on the first file that
        # came without words of its own. A file with nothing to say goes with a neutral line, never with the
        # name it was stored under (it may carry a task code or a translator's name). A note with no file
        # to ride on - or too long for a caption - goes ahead of the messages, as words.
        from . import whatsapp as wa

        file_only = [item for item in items if not item["text"] and item["files"]]
        caption = note if file_only and len(note) <= wa.CAPTION_LIMIT else ""
        reached = False
        if note and not caption:
            ok, _out, error = send_client_message(
                client, user, body=note, force_channel=Channel.WHATSAPP
            )
            if not ok:
                return False, error, "", False
            reached = True
        for item in items:
            body, carries = item["text"], False
            if not body and item["files"]:
                body, caption, carries = caption or FORWARD_FILE_CAPTION_AR, "", True
            ok, _out, error = send_client_message(
                client, user, body=body, reuse_files=[f for f, _owner in item["files"]],
                caption_files=carries, force_channel=Channel.WHATSAPP,
            )
            if not ok:
                return False, error, "", reached
            reached = True
        log(user, "chat.forward", client.code, f"{len(items)} item(s)")
        return True, "", f"/ops/chats/{client.code}/", True

    room = target[1]
    # A group that relays to a client is a group like any other (23/09/2026),
    # but what lands in it goes on to that client's WhatsApp - so the client
    # rule holds here exactly as it does for a 1:1 client conversation.
    relays_to = room.relay_client if room.reaches_client else None
    if room.reaches_client:
        if relays_to is None:
            return False, "الجروب ده مش مربوط بعميل.", "", False
        owners = {item["text_owner"] for item in items if item["text"]}
        owners |= {owner for item in items for _f, owner in item["files"]}
        owners.discard(None)
        if owners - {relays_to.pk}:
            return False, "مينفعش تحوّل رسايل أو ملفات عميل لجروب عميل تاني.", "", False
        if max_relayed is not None and len(items) > max_relayed:
            return False, _TOO_MANY_TO_CLIENT_AR % max_relayed, "", False
    members = list(room.members.all())
    # Everyone in the room may read a client's own words - or nobody gets them. Except that the admin may send them on
    # to anybody: the words are then marked open, and the room reads them without the client's name and contacts.
    all_inbox = all(m.is_operation or m.is_admin_role for m in members)
    opens = user.is_admin_role and not all_inbox

    # What will really be written is decided before anything is: a refusal leaves no note behind in the room.
    kept = []
    for item in items:
        text = item["text"]
        opened = False
        if text and item["text_owner"] is not None and not all_inbox:
            if opens:
                opened = True
            else:
                text = ""
        if text or item["files"]:
            kept.append((item, text, opened))
    if not kept:
        return False, (
            "كلام العميل مابيتحولش للشات ده، والرسايل اللي اخترتها مفيهاش ملفات."
        ), "", False

    written = []
    if note:
        written.append(ChatMessage.objects.create(room=room, sender=user, body=note))
    for item, text, opened in kept:
        message = ChatMessage.objects.create(
            room=room, sender=user, body=text, forwarded=True,
            origin_client_id=item["text_owner"], words_open=opened,
        )
        for attachment, owner in item["files"]:
            ChatAttachment.objects.create(
                message=message, file=attachment.file.name,
                original_name=attachment.original_name
                or attachment.file.name.rsplit("/", 1)[-1],
                size=attachment.size or 0, origin_client_id=owner,
            )
        written.append(message)

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
    url = f"/ops/chats/g/{room.id}/" if room.kind != RoomKind.STAFF else ""
    for member in members:
        if member.pk == user.pk:
            continue
        # The notice carries the room's title and a link into it, so it goes only to
        # people who could open the room by hand: not a translator seated in a client
        # room, not somebody whose seat outlived the task.
        if not room.can_open(member):
            continue
        # A colleague's chat is called by the other person's name: each one's own view of it.
        where = room.title_for(member)
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
        return False, f"اتحوّلت للجروب بس مروحتش للعميل: {relay_error}"[:300], url, True
    return True, "", url, True


# ---------------------------------------------------------------------------
# Reactions
# ---------------------------------------------------------------------------

#: (key, icon in the sprite, Arabic, English), in WhatsApp's order. Drawn
#: in colour as the r-<key> symbols (templates/partials/icons.html) to look
#: like WhatsApp's set - not real emoji, which the codebase does not carry
#: (verify.py) because they render differently on every machine. "done" is
#: WhatsApp's folded hands, so it reads "شكرًا"; the stored key stays.
REACTIONS = (
    ("like", "thumbs-up", "لايك", "Like"),
    ("love", "heart", "حب", "Love"),
    ("laugh", "smile", "ضحك", "Laugh"),
    ("wow", "surprised", "واو", "Wow"),
    ("sad", "frown", "زعلان", "Sad"),
    ("done", "check-circle", "شكرًا", "Thanks"),
)
_REACTION_ORDER = {key: index for index, (key, *_rest) in enumerate(REACTIONS)}
_REACTION_ICON = {key: icon for key, icon, _ar, _en in REACTIONS}


def reactions_for(field, ids, viewer):
    """{target id: [{kind, icon, count, mine, who}]} for the ids given.

    ``field`` is "message", "inbound" or "outbound" - which kind of row the
    ids are. One query for a whole thread.
    """
    from .models import ChatReaction

    ids = [i for i in ids if i]
    if not ids:
        return {}
    rows = (
        ChatReaction.objects.filter(**{f"{field}_id__in": ids})
        .select_related("user").order_by("created_at")
    )
    grouped = {}
    for row in rows:
        target = getattr(row, f"{field}_id")
        kinds = grouped.setdefault(target, {})
        entry = kinds.setdefault(row.kind, {
            "kind": row.kind, "icon": _REACTION_ICON.get(row.kind, "thumbs-up"),
            "count": 0, "mine": False, "who": [],
        })
        entry["count"] += 1
        entry["who"].append(row.user.short_name)
        if viewer is not None and row.user_id == viewer.pk:
            entry["mine"] = True
    return {
        target: sorted(kinds.values(), key=lambda e: _REACTION_ORDER.get(e["kind"], 99))
        for target, kinds in grouped.items()
    }


def reactions_sig(reactions):
    """A short fingerprint of a message's reactions, so a poll redraws the
    bubble when they change - and only then. Same in the template and JS."""
    return ",".join(
        f"{r['kind']}{r['count']}{'m' if r['mine'] else ''}" for r in reactions or []
    )


def toggle_reaction(user, source_code, uid, kind):
    """React to one message. Returns ``(ok, error_ar, reactions)``.

    Same one again takes it back; a different one replaces it. The message is
    looked up *inside* the conversation it is said to be from, so an id from
    somewhere this person cannot see finds nothing.
    """
    from .models import ChatReaction

    if kind not in _REACTION_ORDER:
        return False, "رياكت مش معروف.", []
    source = _chat_ref(user, source_code)
    if source is None:
        return False, "المحادثة دي مش متاحة ليك.", []
    side, _, raw = str(uid or "").rpartition("-")
    if not raw.isdecimal():
        return False, "الرسالة مش موجودة.", []
    pk = int(raw)
    where, target = source
    field, row = None, None
    if where == "client":
        if side == "in":
            field, row = "inbound", _wa_inbound(target, user).filter(pk=pk).first()
        elif side == "out":
            from . import lines

            field, row = "outbound", OutboundMessage.objects.filter(
                pk=pk, client=target, channel=Channel.WHATSAPP
            ).filter(lines.line_q(user)).first()
    elif side == f"g{target.pk}":
        field, row = "message", target.messages.filter(pk=pk, is_system=False).first()
    if row is None:
        return False, "الرسالة مش موجودة.", []

    lookup = {"user": user, field: row}
    existing = ChatReaction.objects.filter(**lookup).first()
    if existing is not None and existing.kind == kind:
        existing.delete()
    elif existing is not None:
        existing.kind = kind
        existing.save(update_fields=["kind"])
    else:
        from django.db import IntegrityError

        try:
            with transaction.atomic():
                ChatReaction.objects.create(kind=kind, **lookup)
        except IntegrityError:
            # A double tap raced itself; the first one stands.
            pass
    return True, "", reactions_for(field, [row.pk], user).get(row.pk, [])


# ---------------------------------------------------------------------------
# Calls between colleagues
# ---------------------------------------------------------------------------
#
# Browser to browser (WebRTC). The server keeps the record and passes the two
# browsers' connection details between them; the heartbeat is how a callee
# learns their phone is ringing. See ``CallSession``.

#: How long a call rings before it is a missed call.
CALL_RING_SECONDS = 45
#: A call keeps at most this many signals (an offer, an answer and the network candidates are a few dozen) of at most this
#: many characters each, and one read returns at most a page of them. The rows go with the call.
CALL_MAX_SIGNALS = 200
CALL_MAX_SIGNAL_BYTES = 65536
CALL_SIGNALS_PAGE = 100
#: Ringing the same colleague more than this many times a minute is refused: each ring is a missed-call note, a chat line
#: and a ping on the other side.
CALL_REDIAL_LIMIT = 6
CALL_REDIAL_SECONDS = 60
#: A call nobody hung up (a tab closed, a computer asleep) stops keeping two people busy after this long.
CALL_MAX_HOURS = 6


#: How long the relay's credentials handed to a browser stay good: a call is at most ``CALL_MAX_HOURS`` long, with an hour to spare.
TURN_CREDENTIAL_SECONDS = (CALL_MAX_HOURS + 1) * 3600


def ice_servers(user=None, now=None):
    """Where the browsers look for a path to each other.

    A public STUN server finds the way on most networks. Some offices and
    mobile carriers need a TURN relay as well; set EAGLE_TURN_URL and it is handed out too.

    With ``EAGLE_TURN_SECRET`` (the relay's ``static-auth-secret``, with ``use-auth-secret`` on) the browser is given a username
    that carries its own expiry and the person's id, and the password made from it with that secret (HMAC-SHA1): good for one
    call's length, for that person, and worthless afterwards. Without it, the older ``EAGLE_TURN_USER`` / ``EAGLE_TURN_PASSWORD``
    pair is handed out as it was - one password that every employee who places a call receives and that never expires.
    """
    import base64
    import hashlib
    import hmac
    import os
    import time

    servers = [{"urls": ["stun:stun.l.google.com:19302", "stun:stun1.l.google.com:19302"]}]
    turn = os.environ.get("EAGLE_TURN_URL", "").strip()
    if not turn:
        return servers
    secret = os.environ.get("EAGLE_TURN_SECRET", "").strip()
    if secret and user is not None:
        expires = int(now if now is not None else time.time()) + TURN_CREDENTIAL_SECONDS
        username = f"{expires}:{user.pk}"
        credential = base64.b64encode(hmac.new(secret.encode("utf-8"), username.encode("utf-8"), hashlib.sha1).digest()).decode("ascii")
        servers.append({"urls": [turn], "username": username, "credential": credential})
    else:
        servers.append({
            "urls": [turn],
            "username": os.environ.get("EAGLE_TURN_USER", ""),
            "credential": os.environ.get("EAGLE_TURN_PASSWORD", ""),
        })
    return servers


def _expire_ringing():
    """Calls nobody answered in time become missed calls - with their note."""
    from .models import CallSession

    cutoff = timezone.now() - timedelta(seconds=CALL_RING_SECONDS)
    for call in CallSession.objects.filter(
        status=CallSession.Status.RINGING, created_at__lt=cutoff
    ).select_related("caller", "callee", "room"):
        end_call(call, call.caller, reason="missed")


def _expire_stale_active():
    """Calls answered long ago that nobody ended are ended, so two people are not busy for ever."""
    from .models import CallSession

    cutoff = timezone.now() - timedelta(hours=CALL_MAX_HOURS)
    for call in CallSession.objects.filter(
        status=CallSession.Status.ACTIVE, answered_at__lt=cutoff
    ).select_related("caller", "callee", "room"):
        end_call(call, call.caller, reason="ended")


def start_call(caller, callee, video=False):
    """Ring a colleague. Returns ``(call, error_ar)``."""
    from .models import CallSession

    if callee is None or not callee.is_active or callee.pk == caller.pk:
        return None, "مينفعش تكلم الشخص ده."
    _expire_ringing()
    _expire_stale_active()
    recent = CallSession.objects.filter(
        caller=caller, callee=callee, created_at__gte=timezone.now() - timedelta(seconds=CALL_REDIAL_SECONDS),
    ).count()
    if recent >= CALL_REDIAL_LIMIT:
        return None, "كلمته كتير في وقت قصير. استنى شوية."
    busy = CallSession.objects.filter(
        Q(caller__in=[caller, callee]) | Q(callee__in=[caller, callee]),
        status__in=[CallSession.Status.RINGING, CallSession.Status.ACTIVE],
    )
    for call in busy.select_related("caller", "callee", "room"):
        # A call of your own still open (a tab closed mid-call) is not a
        # reason to stay unreachable: it is closed now. Theirs means busy.
        if caller.pk in (call.caller_id, call.callee_id):
            end_call(call, caller, reason="ended")
        else:
            return None, f"{callee.short_name} في مكالمة تانية دلوقتي."
    room = staff_room(caller, callee)
    call = CallSession.objects.create(
        room=room, caller=caller, callee=callee, video=bool(video)
    )
    return call, ""


def call_for(user, pk):
    """The call, if this person is one of its two ends."""
    from .models import CallSession

    return CallSession.objects.filter(
        Q(caller=user) | Q(callee=user), pk=pk
    ).select_related("caller", "callee", "room").first()


def answer_call(call, user):
    from .models import CallSession

    if call.callee_id != user.pk or call.status != CallSession.Status.RINGING:
        return False
    # One conditional write: a call that was hung up or timed out while this answer was on its way stays as it ended, and a
    # call that rang past its time is not answered (the ringing is only closed when the next call starts).
    now = timezone.now()
    moved = CallSession.objects.filter(
        pk=call.pk, status=CallSession.Status.RINGING, created_at__gte=now - timedelta(seconds=CALL_RING_SECONDS),
    ).update(status=CallSession.Status.ACTIVE, answered_at=now)
    if not moved:
        return False
    call.status = CallSession.Status.ACTIVE
    call.answered_at = now
    return True


def _clock(seconds):
    seconds = max(0, int(seconds))
    return f"{seconds // 60}:{seconds % 60:02d}"


def end_call(call, user, reason="ended"):
    """Hang up, decline, or give up ringing. Writes one line into the chat.

    ``reason`` is "ended", "declined" or "missed". Idempotent: a call already
    over is left as it was, so both ends hanging up at once write one note.
    """
    from .models import CallSession

    if not call.is_open:
        return False
    now = timezone.now()
    if call.status == CallSession.Status.ACTIVE:
        status = CallSession.Status.ENDED
    elif reason == "declined" and user.pk == call.callee_id:
        status = CallSession.Status.DECLINED
    else:
        status = CallSession.Status.MISSED
    moved = CallSession.objects.filter(
        pk=call.pk, status__in=[CallSession.Status.RINGING, CallSession.Status.ACTIVE]
    ).update(status=status, ended_at=now)
    if not moved:
        return False
    call.status, call.ended_at = status, now
    # What the two browsers passed each other to set the call up is of no use once it is over, and holds their addresses.
    call.signals.all().delete()

    kind_ar = "مكالمة فيديو" if call.video else "مكالمة صوتية"
    kind_en = "Video call" if call.video else "Voice call"
    if status == CallSession.Status.ENDED:
        body = f"{kind_ar} · {_clock((now - call.answered_at).total_seconds())}"
    elif status == CallSession.Status.DECLINED:
        body = f"{kind_ar} · اترفضت"
    else:
        body = f"{kind_ar} فايتة"
        notify(
            call.callee, level="warning",
            title_ar="مكالمة فايتة", title_en=f"Missed {kind_en.lower()}",
            body_ar=f"{call.caller.short_name} كلمك ومردتش.",
            body_en=f"{call.caller.short_name} called you.",
            url=f"/ops/chats/u/{call.caller_id}/",
        )
    # Written as the caller's message, so it lands in the chat like WhatsApp's
    # call line: counted as unread for the other one, ticked for the caller.
    ChatMessage.objects.create(room=call.room, sender=call.caller, body=body)
    return True


def incoming_call(user):
    """The call ringing for this person right now, for the heartbeat."""
    from .models import CallSession

    cutoff = timezone.now() - timedelta(seconds=CALL_RING_SECONDS)
    call = (
        CallSession.objects.filter(
            callee=user, status=CallSession.Status.RINGING, created_at__gte=cutoff
        ).select_related("caller").order_by("-id").first()
    )
    if call is None:
        return None
    return {
        "id": call.id, "video": call.video,
        "from": call.caller.short_name, "initials": call.caller.initials,
        "chat_url": f"/ops/chats/u/{call.caller_id}/",
    }


def post_signal(call, user, kind, payload):
    from .models import CallSignal

    if kind not in CallSignal.Kind.values or not call.is_open:
        return None
    payload = payload or ""
    # Refused, not cut: half an SDP is not a description of anything. And a call has only so many.
    if len(payload) > CALL_MAX_SIGNAL_BYTES or call.signals.count() >= CALL_MAX_SIGNALS:
        return None
    return CallSignal.objects.create(call=call, sender=user, kind=kind, payload=payload)


def signals_for(call, user, after=0):
    """What the other end has sent since ``after``, oldest first."""
    return list(
        call.signals.filter(id__gt=after).exclude(sender=user)
        .order_by("id").values("id", "kind", "payload")[:CALL_SIGNALS_PAGE]
    )


#: ``send_client_message(line_owner=...)`` left out: the line is worked out from the client's last message (``lines.reply_line``).
LINE_FROM_CLIENT = object()


def send_client_message(client, user, body="", uploads=None, voice=None,
                        voice_seconds=0, extra_files=None, reply_to_wamid="",
                        reply_preview="", force_channel="", subject="",
                        in_reply_to="", references=(), thread_key="",
                        reuse_files=None, caption_files=False, line_owner=LINE_FROM_CLIENT):
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

    ``caption_files`` says the words are the caption of the files, not a text
    of their own: on WhatsApp they ride on the first file that can carry one
    (a short caption on a document, an image or a video), and the files after
    it go with none. Without a file that can carry them (an audio message, or
    words past WhatsApp's caption limit) they are sent first as a text, as
    always. Without ``caption_files`` and without words a file is captioned
    with its own name.

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

    from . import lines

    conf = AppSettings.load()
    channel = force_channel or client_channel(client)
    if channel not in (Channel.WHATSAPP, Channel.EMAIL):
        channel = client_channel(client)
    # The number / address they last wrote from, if it is one of theirs.
    target = client.reply_target(channel)
    # Which of our lines it leaves from: a Sales person's own, or the
    # company's (``owner`` None). Answers go back the way the client came.
    # An answer to one particular letter leaves from the line that letter came to (``line_owner``: the Sales person, or ``None``
    # for the company); otherwise from the line the client wrote to last.
    owner = lines.reply_line(client, user, channel) if line_owner is LINE_FROM_CLIENT else line_owner
    from_number = (owner.wa_phone_number_id or "").strip() if owner else ""
    from_address = (owner.mail_alias or "").strip() if owner else ""
    line_missing = ""
    if owner is not None:
        if channel == Channel.WHATSAPP and not from_number:
            line_missing = "مفيش رقم واتساب متسجّل للـSales ده — ضيفه من صفحة «خطي»."
        if channel == Channel.EMAIL and not from_address:
            line_missing = "مفيش إيميل متحدد لصاحب المحادثة دي — الأدمن يحدده من صفحة الموظف."

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
            "content": content, "name": short_name(name), "mime": mime[:120],
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
        owner=owner,
    )
    try:
        stored = [
            OutboundAttachment.objects.create(
                message=outbound, file=item, original_name=short_name(item.name), size=item.size
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

        if line_missing:
            outbound.status = OutboundMessage.Status.FAILED
            outbound.error_message = line_missing
            outbound.save(update_fields=["status", "error_message"])
            return False, outbound, line_missing

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

        if channel == Channel.WHATSAPP:
            quote = reply_to_wamid or ""
            # The words ride on the first file that can carry them, if they were meant to.
            carried = (
                body if caption_files and len(body) <= wa.CAPTION_LIMIT
                and any(wa.can_caption(name, mime) for name, _content, mime in payload)
                else ""
            )
            if body and not carried:
                outbound.provider_id = wa.send_text(
                    target, body, context_id=quote, from_id=from_number
                )
                quote = ""       # only the first message carries the quote
            for index, (name, content, mime) in enumerate(payload):
                caption = "" if body else name
                if carried:
                    caption = ""
                    if wa.can_caption(name, mime):
                        caption, carried = carried, ""
                sent_id = wa.send_file(target, content, name, mime,
                                       caption=caption, context_id=quote,
                                       from_id=from_number)
                # The message that holds the words is the one WhatsApp's ticks will name.
                if body and caption and not outbound.provider_id:
                    outbound.provider_id = sent_id
                quote = ""
                outbound.files[index]["status"] = "sent"
        else:
            from . import threads

            # Our own Message-ID, stored, so the client's answer to this letter
            # comes back into the same conversation (threads.find_thread_key).
            message_id = mailer.new_message_id(conf)
            parents = threads.message_ids(in_reply_to)
            chain = threads.message_ids(*references) if references else []
            # A Sales person's letters go out dressed: logo, name, title,
            # number (mailbrand.py). Everybody else's stay plain.
            from . import mailbrand

            html_body, inline_images = "", []
            if mailbrand.applies_to(user):
                html_body, inline_images = mailbrand.sales_letter(
                    user, body or "مرفق الملفات.", mail_subject, conf, from_address,
                )
            mailer.send_delivery(
                conf, target,
                subject=mail_subject,
                body=body or "مرفق الملفات.",
                attachments=payload,
                from_email=from_address,
                html_body=html_body,
                inline_images=inline_images,
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
        from . import identity

        # The library's words quote the recipient back ("550 <address> refused"); the row is read by people who
        # may not know the address, so it is kept out of the text. The audit log keeps the original.
        outbound.status = OutboundMessage.Status.FAILED
        outbound.error_message = identity.scrub_contacts(exc.message_ar)
        outbound.save(update_fields=["status", "error_message", "files", "provider_id"])
        log(user, "client.reply_failed", client.code, exc.message_en[:200])
        return False, outbound, outbound.error_message
    except Exception:  # noqa: BLE001 - a timeout while reading Meta's answer, a dropped connection ...
        # The row was created before the call and starts as SENT: left like that, a send that broke half way
        # would show a tick for a message nobody knows reached the client.
        logger.exception("Sending to client %s failed unexpectedly", client.code)
        outbound.status = OutboundMessage.Status.FAILED
        outbound.error_message = SEND_UNSURE_AR
        outbound.save(update_fields=["status", "error_message", "files", "provider_id"])
        log(user, "client.reply_failed", client.code, "unexpected error")
        return False, outbound, SEND_UNSURE_AR

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
            status__in=TRANSLATOR_HOLDING_STATUSES, translator__in=people
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
