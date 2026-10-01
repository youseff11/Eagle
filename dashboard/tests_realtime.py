"""Live pushes over WebSocket: who is let in, who is told, and what is said.

The socket is only a doorbell. These tests hold three promises:

* only a signed-in session stays connected, and only from an allowed origin;
* a ping goes to exactly the people who could open the room by hand - a stale
  membership row, a closed task and a private staff chat all stay silent;
* an event never carries a title, a body, a client or a sender.

They are ``TransactionTestCase`` on purpose: the consumer reads the database
from another thread, and an open test transaction would hide every row from it.
"""

import json
import logging
from datetime import timedelta
from unittest import mock

from asgiref.sync import sync_to_async
from channels.auth import AuthMiddlewareStack
from channels.routing import URLRouter
from channels.security.websocket import AllowedHostsOriginValidator, OriginValidator
from channels.testing import WebsocketCommunicator
from django.conf import settings
from django.contrib.sessions.models import Session
from django.http import Http404
from django.core.exceptions import PermissionDenied
from django.test import Client as DjangoClient
from django.test import RequestFactory, TestCase, TransactionTestCase, override_settings
from django.utils import timezone

from . import api, realtime, services
from .consumers import CLOSE_UNAUTHENTICATED
from .models import ChatMessage, ChatRoom, Client, Notification, Role, RoomKind, User
from .routing import websocket_urlpatterns

from Core.asgi import application


def _login(user, origin=None):
    """Request headers a browser would send for ``user`` - and the session key."""
    browser = DjangoClient()
    browser.force_login(user)
    key = browser.cookies[settings.SESSION_COOKIE_NAME].value
    headers = [(b"cookie", f"{settings.SESSION_COOKIE_NAME}={key}".encode())]
    if origin:
        headers.append((b"origin", origin.encode()))
    return headers, key


class _Socket:
    """``async with _Socket(user) as s`` - connected, and always disconnected."""

    def __init__(self, user=None, origin=None, app=application):
        self.user, self.origin, self.app = user, origin, app
        self.session_key = None

    async def __aenter__(self):
        headers = []
        if self.user is not None:
            headers, self.session_key = await sync_to_async(_login)(self.user, self.origin)
        elif self.origin:
            headers = [(b"origin", self.origin.encode())]
        self.comm = WebsocketCommunicator(self.app, "/ws/events/", headers=headers)
        self.connected, self.code = await self.comm.connect()
        return self

    async def __aexit__(self, *exc):
        if self.connected:
            await self.comm.disconnect()

    async def event(self):
        return await self.comm.receive_json_from(timeout=2)

    async def silent(self):
        return await self.comm.receive_nothing(timeout=0.4)


class _World(TransactionTestCase):
    """An operator, a leader, a translator on one task, an admin and a stranger."""

    def setUp(self):
        self.admin = User.objects.create_user("adm", password="x", role=Role.ADMIN)
        self.ops = User.objects.create_user("ops", password="x", role=Role.OPERATION)
        self.lead = User.objects.create_user("lead", password="x", role=Role.TEAM_LEAD)
        self.tr = User.objects.create_user(
            "tr", password="x", role=Role.TRANSLATOR, team_lead=self.lead
        )
        self.stranger = User.objects.create_user(
            "stranger", password="x", role=Role.TRANSLATOR, team_lead=self.lead
        )
        self.client_obj = Client.objects.create(name="ACME Secret Ltd", phone="+201000000000")
        self.task = services.create_task(
            client=self.client_obj, title="Doc", created_by=self.ops,
            deadline=timezone.now() + timedelta(hours=2),
        )
        self.task.team_lead = self.lead
        self.task.translator = self.tr
        self.task.save()
        self.group = services.ensure_room(self.task, RoomKind.GROUP)
        self.client_room = services.ensure_room(self.task, RoomKind.CLIENT)
        self.staff = ChatRoom.objects.create(
            kind=RoomKind.STAFF, pair_key=f"{self.ops.pk}-{self.lead.pk}"
        )
        self.staff.members.add(self.ops, self.lead)

    @staticmethod
    async def say(room, sender, body="hello"):
        return await sync_to_async(ChatMessage.objects.create)(
            room=room, sender=sender, body=body
        )


class SocketAccessTests(_World):
    async def test_no_session_is_refused(self):
        async with _Socket() as sock:
            self.assertFalse(sock.connected)
            self.assertEqual(sock.code, CLOSE_UNAUTHENTICATED)

    async def test_a_signed_in_user_connects(self):
        async with _Socket(self.ops) as sock:
            self.assertTrue(sock.connected)

    async def test_an_inactive_account_is_refused(self):
        await sync_to_async(User.objects.filter(pk=self.ops.pk).update)(is_active=False)
        async with _Socket(self.ops) as sock:
            self.assertFalse(sock.connected)

    async def test_a_ping_is_answered(self):
        async with _Socket(self.ops) as sock:
            await sock.comm.send_json_to({"t": "ping"})
            self.assertEqual(await sock.event(), {"t": "pong"})

    async def test_a_ping_after_deactivation_closes_the_socket(self):
        async with _Socket(self.ops) as sock:
            await sync_to_async(User.objects.filter(pk=self.ops.pk).update)(is_active=False)
            await sock.comm.send_json_to({"t": "ping"})
            out = await sock.comm.receive_output(timeout=2)
            self.assertEqual(out["type"], "websocket.close")
            self.assertEqual(out["code"], CLOSE_UNAUTHENTICATED)

    async def test_a_ping_after_the_session_is_gone_closes_the_socket(self):
        async with _Socket(self.ops) as sock:
            await sync_to_async(Session.objects.filter(session_key=sock.session_key).delete)()
            await sock.comm.send_json_to({"t": "ping"})
            out = await sock.comm.receive_output(timeout=2)
            self.assertEqual(out["type"], "websocket.close")

    async def test_other_messages_from_the_browser_are_ignored(self):
        async with _Socket(self.ops) as sock:
            await sock.comm.send_json_to({"t": "subscribe", "room": self.client_room.pk})
            await sock.comm.send_json_to(["not", "a", "dict"])
            self.assertTrue(await sock.silent())

    def test_the_real_application_checks_the_origin(self):
        # The test below builds its own stack; this one pins the stack that is shipped.
        self.assertIsInstance(application.application_mapping["websocket"], OriginValidator)

    async def test_only_an_allowed_origin_connects(self):
        with override_settings(ALLOWED_HOSTS=["eagle.example"]):
            app = AllowedHostsOriginValidator(AuthMiddlewareStack(URLRouter(websocket_urlpatterns)))
        async with _Socket(self.ops, origin="https://eagle.example", app=app) as good:
            self.assertTrue(good.connected)
        async with _Socket(self.ops, origin="https://evil.example", app=app) as foreign:
            self.assertFalse(foreign.connected)
        async with _Socket(self.ops, origin=None, app=app) as missing:
            self.assertFalse(missing.connected)


class NotificationPingTests(_World):
    async def test_a_notification_pings_its_owner_and_nobody_else(self):
        async with _Socket(self.ops) as owner, _Socket(self.lead) as other:
            await sync_to_async(services.notify)(
                self.ops, title_ar="x", title_en="x", body_en="ACME Secret Ltd is waiting",
            )
            self.assertEqual(await owner.event(), {"t": "notify"})
            self.assertTrue(await other.silent())

    async def test_editing_a_notification_does_not_ping_again(self):
        async with _Socket(self.ops) as sock:
            note = await sync_to_async(services.notify)(self.ops, title_ar="x", title_en="x")
            await sock.event()
            note.is_read = True
            await sync_to_async(note.save)()
            self.assertTrue(await sock.silent())


class RoomPingTests(_World):
    async def test_a_group_message_pings_everyone_who_may_open_the_room(self):
        async with _Socket(self.ops) as a, _Socket(self.lead) as b, \
                _Socket(self.tr) as c, _Socket(self.admin) as d, _Socket(self.stranger) as e:
            await self.say(self.group, self.ops)
            want = {"t": "room", "id": self.group.pk}
            for sock in (a, b, c, d):
                self.assertEqual(await sock.event(), want)
            self.assertTrue(await e.silent())

    async def test_a_stale_membership_row_is_not_pinged(self):
        # Taken off the task, still in the members table.
        self.task.translator = None
        await sync_to_async(self.task.save)()
        self.assertTrue(await sync_to_async(self.group.members.filter(pk=self.tr.pk).exists)())
        async with _Socket(self.tr) as gone, _Socket(self.lead) as still:
            await self.say(self.group, self.ops)
            self.assertEqual(await still.event(), {"t": "room", "id": self.group.pk})
            self.assertTrue(await gone.silent())

    async def test_the_translator_is_never_pinged_for_the_client_room(self):
        async with _Socket(self.tr) as tr, _Socket(self.ops) as ops:
            await self.say(self.client_room, self.ops)
            self.assertEqual(await ops.event(), {"t": "room", "id": self.client_room.pk})
            self.assertTrue(await tr.silent())

    async def test_a_private_staff_chat_does_not_reach_the_admin(self):
        async with _Socket(self.ops) as ops, _Socket(self.lead) as lead, _Socket(self.admin) as admin:
            await self.say(self.staff, self.ops)
            want = {"t": "room", "id": self.staff.pk}
            self.assertEqual(await ops.event(), want)
            self.assertEqual(await lead.event(), want)
            self.assertTrue(await admin.silent())

    async def test_an_event_carries_a_kind_and_an_id_and_nothing_else(self):
        async with _Socket(self.ops) as sock:
            await self.say(
                self.client_room, self.lead, body="ACME Secret Ltd wants it by Friday"
            )
            event = await sock.event()
            self.assertEqual(set(event), {"t", "id"})
            self.assertNotIn("ACME", json.dumps(event))
            self.assertNotIn("Friday", json.dumps(event))
            self.assertNotIn(self.lead.username, json.dumps(event))


class DeliveryNeverBreaksTheCallerTests(TestCase):
    def setUp(self):
        # The fast settings switch every logger off; assertLogs needs it on.
        previous = logging.root.manager.disable
        logging.disable(logging.NOTSET)
        self.addCleanup(logging.disable, previous)

    def test_a_broken_layer_is_logged_not_raised(self):
        with mock.patch("channels.layers.get_channel_layer", side_effect=RuntimeError("redis down")):
            with self.assertLogs("dashboard", level="ERROR"):
                realtime._deliver([1], {"t": realtime.NOTIFY})

    def test_no_layer_configured_is_silent(self):
        with mock.patch("channels.layers.get_channel_layer", return_value=None):
            realtime._deliver([1], {"t": realtime.NOTIFY})

    def test_a_message_save_survives_a_failing_push(self):
        ops = User.objects.create_user("o", password="x", role=Role.OPERATION)
        client = Client.objects.create(name="C", phone="+201000000001")
        task = services.create_task(
            client=client, title="T", created_by=ops,
            deadline=timezone.now() + timedelta(hours=2),
        )
        room = services.ensure_room(task, RoomKind.GROUP)
        with mock.patch("channels.layers.get_channel_layer", side_effect=RuntimeError("redis down")):
            with self.captureOnCommitCallbacks(execute=True):
                message = ChatMessage.objects.create(room=room, sender=ops, body="kept")
        self.assertTrue(ChatMessage.objects.filter(pk=message.pk).exists())


class AudienceMatchesTheChatApiTests(TestCase):
    """``ChatRoom.can_open`` must give the answer ``api._room_or_404`` gives.

    Two copies of a permission rule drift. This pins them together: for every
    person and every room below, the push audience and the API agree.
    """

    def test_every_person_and_every_room(self):
        admin = User.objects.create_user("adm", password="x", role=Role.ADMIN)
        ops = User.objects.create_user("ops", password="x", role=Role.OPERATION)
        lead = User.objects.create_user("lead", password="x", role=Role.TEAM_LEAD)
        other_lead = User.objects.create_user("lead2", password="x", role=Role.TEAM_LEAD)
        tr = User.objects.create_user("tr", password="x", role=Role.TRANSLATOR, team_lead=lead)
        stray = User.objects.create_user("stray", password="x", role=Role.TRANSLATOR, team_lead=lead)
        hr = User.objects.create_user("hr", password="x", role=Role.HR)
        client = Client.objects.create(name="ACME", phone="+201000000002")
        task = services.create_task(
            client=client, title="T", created_by=ops,
            deadline=timezone.now() + timedelta(hours=2),
        )
        task.team_lead, task.translator = lead, tr
        task.save()
        group = services.ensure_room(task, RoomKind.GROUP)
        client_room = services.ensure_room(task, RoomKind.CLIENT)
        staff = ChatRoom.objects.create(kind=RoomKind.STAFF, pair_key=f"{ops.pk}-{lead.pk}")
        staff.members.add(ops, lead)
        team = ChatRoom.objects.create(kind=RoomKind.TEAM, title="Team")
        team.members.add(lead, tr)
        # Stale: still a member, no longer on the task.
        group.members.add(other_lead, hr)

        factory = RequestFactory()
        compared = 0
        for room in (group, client_room, staff, team):
            for person in (admin, ops, lead, other_lead, tr, stray, hr):
                request = factory.get("/")
                request.user = person
                try:
                    api._room_or_404(request, room.pk)
                    by_api = True
                except (Http404, PermissionDenied):
                    by_api = False
                self.assertEqual(
                    room.can_open(person), by_api,
                    f"{person.username} / {room.kind}: push says {room.can_open(person)}, API says {by_api}",
                )
                compared += 1
        self.assertEqual(compared, 28)
