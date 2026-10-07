"""Live pushes over WebSocket: a ping, never a payload.

The socket tells a browser *that* something changed for it - a notification
arrived, a room has a new message - and nothing about what. The page then asks
the ordinary API, which applies the ordinary permission checks. So a mistake in
this file can make a page refresh needlessly; it cannot show anyone a client's
name or an internal remark. Keep it that way: an event is a kind and an id, and
``clean_event`` drops everything else on the way out, so a future caller that
adds a title to one cannot get it onto the wire.

Who is pinged is decided here, at delivery time, by the same questions the chat
API asks (``ChatRoom.can_open``). Nothing in this module may ever raise into
the caller: a push is a courtesy, and it runs inside code that is mid-way
through saving a conversation with a client. Nor may it make the caller wait:
a delivery has a time limit, and after one failure pushes are skipped for a
while, so a Redis that accepts connections and then says nothing costs one
short wait rather than one per message.

The channel layer is Redis in production and in memory on a laptop; with the
``channels`` package missing altogether (an older server still on WSGI) every
function here quietly does nothing.
"""

import asyncio
import logging
import time

from django.db import transaction
from django.db.models import Q

log = logging.getLogger("dashboard")

#: Event kinds. The page reacts to these two strings, so they are API.
NOTIFY = "notify"
ROOM = "room"
KINDS = (NOTIFY, ROOM)

#: How long one delivery may take, and how long pushes stay off after a failed
#: one. Module state on purpose: it is per process, and so is the problem.
PUSH_TIMEOUT = 2.0
MUTE_SECONDS = 30.0
_muted_until = 0.0


def user_group(user_id):
    return f"user.{int(user_id)}"


def clean_event(event):
    """The event as it may leave this server: a known kind, and an id if any.

    Anything else - a title, a body, a name - is dropped, not forwarded. An
    unknown kind becomes ``None`` and is not sent.
    """
    if not isinstance(event, dict) or event.get("t") not in KINDS:
        return None
    cleaned = {"t": event["t"]}
    identifier = event.get("id")
    if isinstance(identifier, int) and not isinstance(identifier, bool):
        cleaned["id"] = identifier
    return cleaned


def room_audience(room):
    """The active people who may open ``room`` right now.

    Candidates are the room's members and the admins (an admin opens any room
    but a private staff chat); each one then has to pass ``can_open``, so a
    stale membership row buys nothing.
    """
    from .models import Role, User

    people = {}
    for user in room.members.filter(is_active=True):
        people[user.pk] = user
    for user in User.objects.filter(Q(role=Role.ADMIN) | Q(is_superuser=True), is_active=True):
        people.setdefault(user.pk, user)
    return [user for user in people.values() if room.can_open(user)]


def send_to_users(user_ids, event):
    """Push ``event`` to these users once the surrounding transaction commits."""
    ids = sorted({int(i) for i in user_ids if i})
    if ids:
        transaction.on_commit(lambda: _deliver(ids, event))


def push_room(room_id):
    """Tell everyone who may open this room that it has something new.

    The audience is worked out after the commit, not when the message is
    saved, so it reflects who is allowed in at the moment of delivery.
    """
    transaction.on_commit(lambda: _deliver_room(room_id))


def push_room_to(room_id, user_ids):
    """Tell only these people that this room has something new - those of them who may still open it.

    For a change that matters to a few (somebody read your message: the "seen by" under it), where telling the whole
    room would make every page ask for the thread again.
    """
    ids = sorted({int(i) for i in user_ids if i})
    if ids:
        transaction.on_commit(lambda: _deliver_room_to(room_id, ids))


def _deliver_room_to(room_id, user_ids):
    if _is_muted():
        return
    try:
        from .models import ChatRoom, User

        room = ChatRoom.objects.select_related("task").filter(pk=room_id).first()
        if room is None:
            return
        people = User.objects.filter(pk__in=user_ids, is_active=True)
        audience = [user.pk for user in people if room.can_open(user)]
        if audience:
            _deliver(audience, {"t": ROOM, "id": room.pk})
    except Exception:  # noqa: BLE001 - see the module note
        log.exception("realtime: could not work out who to tell about room %s", room_id)


def _deliver_room(room_id):
    if _is_muted():
        return
    try:
        from .models import ChatRoom

        room = ChatRoom.objects.select_related("task").filter(pk=room_id).first()
        if room is None:
            return
        _deliver(
            [user.pk for user in room_audience(room)],
            {"t": ROOM, "id": room.pk},
        )
    except Exception:  # noqa: BLE001 - see the module note
        log.exception("realtime: could not work out who to tell about room %s", room_id)


def _is_muted():
    return time.monotonic() < _muted_until


def _mute():
    global _muted_until
    _muted_until = time.monotonic() + MUTE_SECONDS


async def _fan_out(layer, user_ids, event):
    async def send_all():
        for user_id in user_ids:
            await layer.group_send(user_group(user_id), {"type": "push", "event": event})

    await asyncio.wait_for(send_all(), PUSH_TIMEOUT)


def _deliver(user_ids, event):
    event = clean_event(event)
    if event is None or _is_muted():
        return
    try:
        from asgiref.sync import async_to_sync
        from channels.layers import get_channel_layer
    except ImportError:
        return
    try:
        layer = get_channel_layer()
        if layer is None:
            return
        async_to_sync(_fan_out)(layer, user_ids, event)
    except (Exception, asyncio.CancelledError):  # noqa: BLE001 - see the module note
        _mute()
        log.exception("realtime: could not deliver %r; pushes paused for %ds",
                      event.get("t"), int(MUTE_SECONDS))
