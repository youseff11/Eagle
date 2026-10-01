"""What every row of a chat list says, fetched for all the rows at once.

A row used to ask the database for itself: the newest thing the client said, the newest thing we
said, which line the 24-hour window belongs to, how the client was last heard from. Seven or eight
queries a row, a hundred rows, polled again each time the page refreshed. Here the same questions are
asked once for the whole list, as sub-queries on the client (or the room), and what each row says
about the answers is decided by the very functions the single-row path uses - ``preview_from``,
``Client.window_from``, ``channel_from``, ``receipt_of`` - so there is one rule and two ways to feed it.

The single-row functions stay, and are the specification: ``tests_chat_lists`` compares every row of
every list, for every role, with what they say. What may be read is still decided by ``lines.line_q``
and the rate-block rule, exactly as ``services._visible_inbound`` applies them; nothing here widens it.

One difference, harmless and deliberate: two messages with the same timestamp are ordered by id here,
where the single-row path left the tie to the database.
"""

from django.db.models import OuterRef, Subquery

from . import lines, services
from .models import (
    Channel, ChatMessage, ChatRead, ChatRoom, Client, InboundMessage, OutboundMessage, RoomKind,
)


def _window_messages(user):
    """The client's WhatsApp messages on the line this person answers from, newest first.

    ``lines.reply_line`` in one picture: a Sales person answers from their own number, the operation
    from the company's, and the admin from whichever number the client wrote to last - whose newest
    message is, by definition, the newest of all.
    """
    rows = InboundMessage.objects.filter(channel=Channel.WHATSAPP, client=OuterRef("pk"))
    if user.is_sales:
        rows = rows.filter(owner=user)
    elif not user.is_admin_role:
        rows = rows.filter(owner__isnull=True)
    return rows.order_by("-received_at", "-id")


def client_facts(user, clients, previews=True):
    """``{client id: {"preview", "window", "channel"}}`` for these clients, as this person sees them.

    ``previews=False`` leaves the snippet out (a group's row has its own, and only needs the window
    and the channel of the client behind it).
    """
    clients = [c for c in clients if c is not None]
    if not clients:
        return {}

    notes = {
        "f_started": Subquery(_window_messages(user).values("received_at")[:1]),
        "f_channel": Subquery(
            InboundMessage.objects.filter(client=OuterRef("pk"))
            .order_by("-received_at", "-id").values("channel")[:1]
        ),
    }
    if previews:
        said = InboundMessage.objects.filter(channel=Channel.WHATSAPP).filter(lines.line_q(user))
        if not user.is_admin_role:
            said = said.filter(is_rate_blocked=False)
        sent = OutboundMessage.objects.filter(channel=Channel.WHATSAPP).filter(lines.line_q(user))
        notes["f_in"] = Subquery(said.filter(client=OuterRef("pk")).order_by("-received_at", "-id").values("pk")[:1])
        notes["f_out"] = Subquery(sent.filter(client=OuterRef("pk")).order_by("-created_at", "-id").values("pk")[:1])

    rows = {
        row["pk"]: row
        for row in Client.objects.filter(pk__in={c.pk for c in clients}).annotate(**notes).values("pk", *notes)
    }
    inbound, outbound = {}, {}
    if previews:
        inbound = {
            m.pk: m for m in InboundMessage.objects
            .filter(pk__in={r["f_in"] for r in rows.values() if r["f_in"]}).prefetch_related("attachments")
        }
        outbound = {
            m.pk: m for m in OutboundMessage.objects
            .filter(pk__in={r["f_out"] for r in rows.values() if r["f_out"]}).prefetch_related("uploads")
        }

    facts = {}
    for client in clients:
        row = rows.get(client.pk, {})
        fact = {
            "window": Client.window_from(row.get("f_started")),
            "channel": services.channel_from(client, row.get("f_channel")),
        }
        if previews:
            fact["preview"] = services.preview_from(inbound.get(row.get("f_in")), outbound.get(row.get("f_out")))
        facts[client.pk] = fact
    return facts


def _files_of(message):
    """``message.relay_files`` from what was fetched with it, or ``None`` to let the model work it out.

    The one case it will not guess is a mirrored client message inside an internal room, where the
    files shown are filtered by the task's own source files (``ChatMessage.relay_files``).
    """
    if not message.inbound_id:
        return list(message.attachments.all())
    internal = message.room_id and message.room.kind != RoomKind.CLIENT
    task = message.task or (message.room.task if message.room_id else None)
    if task and internal:
        return None
    return list(message.inbound.attachments.all())


def group_facts(user, rooms, staff=False):
    """``{room id: {"preview", "window", "channel"}}`` for these rooms (the last two for client rooms).

    ``staff=True`` is for the one-to-one staff chats, whose row shows the newest message of any kind
    (a group's skips the system lines) and, with no message at all, no time (a group shows when it
    was opened).
    """
    rooms = list(rooms)
    if not rooms:
        return {}

    newest = {
        "f_user": Subquery(
            ChatMessage.objects.filter(room=OuterRef("pk"), is_system=False).order_by("-id").values("pk")[:1]
        ),
        "f_any": Subquery(ChatMessage.objects.filter(room=OuterRef("pk")).order_by("-id").values("pk")[:1]),
    }
    last_ids = {
        pk: any_id if staff else (user_id or any_id)
        for pk, user_id, any_id in ChatRoom.objects.filter(pk__in=[r.pk for r in rooms])
        .annotate(**newest).values_list("pk", "f_user", "f_any")
    }
    messages = {
        m.pk: m for m in ChatMessage.objects.filter(pk__in={i for i in last_ids.values() if i})
        .select_related("inbound", "room", "room__task", "task")
        .prefetch_related("attachments", "inbound__attachments")
    }

    # Ticks are only drawn on the viewer's own last message, and only in a room that stays inside.
    owed = [
        r for r in rooms
        if (m := messages.get(last_ids.get(r.pk))) and m.sender_id == user.pk and not m.is_system
        and not r.reaches_client
    ]
    members, cursors = {}, {}
    if owed:
        ids = [r.pk for r in owed]
        for room_id, person_id in ChatRoom.members.through.objects.filter(chatroom_id__in=ids).values_list(
            "chatroom_id", "user_id"
        ):
            members.setdefault(room_id, []).append(person_id)
        for room_id, person_id, upto in ChatRead.objects.filter(room_id__in=ids).values_list(
            "room_id", "user_id", "last_read_id"
        ):
            cursors.setdefault(room_id, {})[person_id] = upto

    clients = {r.pk: r.relay_client for r in rooms}
    behind = client_facts(user, [c for c in clients.values() if c is not None], previews=False)

    facts = {}
    for room in rooms:
        last = messages.get(last_ids.get(room.pk))
        if last is None:
            preview = {"text": "", "at": None, "outgoing": False} if staff else services._empty_group_preview(room)
        else:
            receipt = None
            if last.sender_id == user.pk:
                if last.is_system:
                    receipt = ""
                elif room.reaches_client:
                    receipt = last.relay_receipt
                else:
                    others = [pk for pk in members.get(room.pk, ()) if pk != user.pk]
                    receipt = services.receipt_of(room, last, others, cursors.get(room.pk, {}))[0]
            files = _files_of(last) if not last.body else None
            preview = services._room_last_preview(room, user, last, files=files, receipt=receipt)
        fact = {"preview": preview}
        client = clients[room.pk]
        if client is not None:
            fact["window"] = behind[client.pk]["window"]
            fact["channel"] = behind[client.pk]["channel"]
        facts[room.pk] = fact
    return facts
