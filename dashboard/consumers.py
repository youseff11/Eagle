"""The one WebSocket a logged-in page keeps open.

It joins a single group, ``user.<id>``, and passes on what ``realtime`` puts
there. It never decides who may hear what - that was decided before the event
was sent - and it carries nothing the page could not already learn from the
ordinary API. All it owns is who may stay connected.

The browser sends ``{"t": "ping"}`` on a timer. A ping re-reads the session
from the database, so signing out somewhere else, a changed password, an
expired session or a deactivated account ends the connection at the next ping
rather than at some distant reconnect. Pings closer together than ``PING_GAP``
are ignored without touching the database, and one person may hold only a few
sockets, so a script in a logged-in tab cannot turn this into a way of
hammering the database. ``daphne --websocket_timeout`` ends every connection
after a fixed time too, which forces a reconnect and a fresh login check even
from a browser that never pings.
"""

import json
import logging
import time
from collections import Counter
from importlib import import_module

from channels.db import database_sync_to_async
from channels.generic.websocket import AsyncJsonWebsocketConsumer
from django.conf import settings

from . import realtime

log = logging.getLogger("dashboard")

#: Close codes in the 4000s are ours. They echo the nearest HTTP status.
CLOSE_BAD_FRAME = 4400
CLOSE_UNAUTHENTICATED = 4401
CLOSE_TOO_MANY = 4429
CLOSE_UNAVAILABLE = 4503

#: Seconds between two pings that are looked at; the earlier one wins.
PING_GAP = 10.0
#: Sockets one person may hold open at once on this process (tabs, a phone).
MAX_SOCKETS_PER_USER = 5

_open = Counter()


@database_sync_to_async
def _user_for_session(session_key):
    """The user this session belongs to *now*, or ``None``.

    Built from a fresh ``SessionStore`` on purpose: the one in the scope caches
    what it read at connect time and would never notice a later logout.
    """
    from django.contrib.auth import get_user

    if not session_key:
        return None

    class _Request:
        pass

    request = _Request()
    request.session = import_module(settings.SESSION_ENGINE).SessionStore(session_key)
    user = get_user(request)
    return user if user.is_authenticated and user.is_active else None


class EventsConsumer(AsyncJsonWebsocketConsumer):
    group = None
    user_pk = None
    last_ping = float("-inf")

    async def connect(self):
        user = self.scope.get("user")
        if user is None or not user.is_authenticated or not user.is_active:
            await self.close(code=CLOSE_UNAUTHENTICATED)
            return
        if _open[user.pk] >= MAX_SOCKETS_PER_USER:
            await self.close(code=CLOSE_TOO_MANY)
            return
        # Counted before the first await: with a real layer the join is a network round trip, and a burst of handshakes that all
        # checked the count before any of them added to it would all be let in.
        _open[user.pk] += 1
        group = realtime.user_group(user.pk)
        try:
            await self.channel_layer.group_add(group, self.channel_name)
        except Exception:  # noqa: BLE001 - the layer being down must not be a traceback
            log.exception("realtime: could not join %s", group)
            _open[user.pk] -= 1
            if _open[user.pk] <= 0:
                del _open[user.pk]
            await self.close(code=CLOSE_UNAVAILABLE)
            return
        self.group, self.user_pk = group, user.pk
        await self.accept()

    async def disconnect(self, code):
        if self.group is None:
            return
        _open[self.user_pk] -= 1
        if _open[self.user_pk] <= 0:
            del _open[self.user_pk]
        try:
            await self.channel_layer.group_discard(self.group, self.channel_name)
        except Exception:  # noqa: BLE001
            log.exception("realtime: could not leave %s", self.group)

    async def receive(self, text_data=None, bytes_data=None, **kwargs):
        """Text JSON only: anything else closes the socket instead of raising."""
        if not text_data:
            await self.close(code=CLOSE_BAD_FRAME)
            return
        try:
            content = json.loads(text_data)
        except (ValueError, RecursionError):
            await self.close(code=CLOSE_BAD_FRAME)
            return
        await self.receive_json(content, **kwargs)

    async def receive_json(self, content, **kwargs):
        if not isinstance(content, dict) or content.get("t") != "ping":
            return
        now = time.monotonic()
        if now - self.last_ping < PING_GAP:
            return
        self.last_ping = now
        session = self.scope.get("session")
        user = await _user_for_session(getattr(session, "session_key", None))
        if user is None or user.pk != self.scope["user"].pk:
            await self.close(code=CLOSE_UNAUTHENTICATED)
            return
        await self.send_json({"t": "pong"})

    async def push(self, message):
        """A ``group_send`` with ``"type": "push"`` lands here.

        Re-cleaned on the way out: whatever reached the layer, only a known
        kind and an id go to the browser.
        """
        event = realtime.clean_event(message.get("event"))
        if event is not None:
            await self.send_json(event)
