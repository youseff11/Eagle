"""The one WebSocket a logged-in page keeps open.

It joins a single group, ``user.<id>``, and passes on what ``realtime`` puts
there. It never decides who may hear what - that was decided before the event
was sent - and it carries nothing the page could not already learn from the
ordinary API. All it owns is who may stay connected.

The browser sends ``{"t": "ping"}`` on a timer. Each ping re-reads the session
from the database, so signing out somewhere else, a changed password, an
expired session or a deactivated account ends the connection within one ping
rather than at some distant reconnect.
"""

from importlib import import_module

from channels.db import database_sync_to_async
from channels.generic.websocket import AsyncJsonWebsocketConsumer
from django.conf import settings

from . import realtime

#: Close codes in the 4000s are ours. 4401 mirrors HTTP 401.
CLOSE_UNAUTHENTICATED = 4401


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

    async def connect(self):
        user = self.scope.get("user")
        if user is None or not user.is_authenticated or not user.is_active:
            await self.close(code=CLOSE_UNAUTHENTICATED)
            return
        self.group = realtime.user_group(user.pk)
        await self.channel_layer.group_add(self.group, self.channel_name)
        await self.accept()

    async def disconnect(self, code):
        if self.group:
            await self.channel_layer.group_discard(self.group, self.channel_name)

    async def receive_json(self, content, **kwargs):
        if not isinstance(content, dict) or content.get("t") != "ping":
            return
        session = self.scope.get("session")
        user = await _user_for_session(getattr(session, "session_key", None))
        if user is None or user.pk != self.scope["user"].pk:
            await self.close(code=CLOSE_UNAUTHENTICATED)
            return
        await self.send_json({"t": "pong"})

    async def push(self, message):
        """A ``group_send`` with ``"type": "push"`` lands here."""
        await self.send_json(message["event"])
