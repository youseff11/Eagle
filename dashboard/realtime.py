"""Live pushes over WebSocket: a ping, never a payload.

The socket tells a browser *that* something changed for it - a notification
arrived, a room has a new message - and nothing about what. The page then asks
the ordinary API, which applies the ordinary permission checks. So a mistake in
this file can make a page refresh needlessly; it cannot show anyone a client's
name or an internal remark. Keep it that way: no title, no body, no client, no
sender in an event, only a kind and an id.

Who is pinged is decided here, at delivery time, by the same questions the chat
API asks (``ChatRoom.can_open``). Nothing in this module may ever raise into
the caller: a push is a courtesy, and it runs inside code that is mid-way
through saving a conversation with a client.

The channel layer is Redis in production and in memory on a laptop; with the
``channels`` package missing altogether (an older server still on WSGI) every
function here quietly does nothing.
"""

import logging

from django.db import transaction
from django.db.models import Q

log = logging.getLogger("dashboard")

#: Event kinds. The page reacts to these two strings, so they are API.
NOTIFY = "notify"
ROOM = "room"


def user_group(user_id):
    return f"user.{int(user_id)}"


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


def _deliver_room(room_id):
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


def _deliver(user_ids, event):
    try:
        from asgiref.sync import async_to_sync
        from channels.layers import get_channel_layer
    except ImportError:
        return
    try:
        layer = get_channel_layer()
        if layer is None:
            return
        send = async_to_sync(layer.group_send)
        for user_id in user_ids:
            send(user_group(user_id), {"type": "push", "event": event})
    except Exception:  # noqa: BLE001 - see the module note
        log.exception("realtime: could not deliver %r", event.get("t"))
