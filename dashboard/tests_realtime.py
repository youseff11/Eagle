"""Live pushes over WebSocket: who is let in, who is told, and what is said.

The socket is only a doorbell. These tests hold three promises:

* only a signed-in session stays connected, and only from an allowed origin;
* a ping goes to exactly the people who could open the room by hand - a stale
  membership row, a closed task and a private staff chat all stay silent;
* an event never carries a title, a body, a client or a sender.

They are ``TransactionTestCase`` on purpose: the consumer reads the database
from another thread, and an open test transaction would hide every row from it.
"""

import asyncio
import json
import logging
import time
from datetime import timedelta
from unittest import mock

from asgiref.sync import sync_to_async
from channels.layers import get_channel_layer
from channels.routing import URLRouter
from channels.security.websocket import AllowedHostsOriginValidator, OriginValidator
from channels.testing import WebsocketCommunicator
from django.conf import settings
from django.contrib.sessions.models import Session
from django.http import Http404
from django.core.exceptions import PermissionDenied
from django.test import Client as DjangoClient
from django.core.files.base import ContentFile
from django.test import RequestFactory, TestCase, TransactionTestCase, override_settings
from django.urls import reverse
from django.utils import timezone

from . import api, consumers, realtime, services
from .consumers import CLOSE_BAD_FRAME, CLOSE_TOO_MANY, CLOSE_UNAUTHENTICATED, CLOSE_UNAVAILABLE
from .models import ChatAttachment, ChatMessage, ChatRoom, Client, Notification, Role, RoomKind, User
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

    def __init__(self, user=None, origin=None, app=application, path="/ws/events/"):
        self.user, self.origin, self.app, self.path = user, origin, app, path
        self.session_key = None

    async def __aenter__(self):
        headers = []
        if self.user is not None:
            headers, self.session_key = await sync_to_async(_login)(self.user, self.origin)
        elif self.origin:
            headers = [(b"origin", self.origin.encode())]
        self.comm = WebsocketCommunicator(self.app, self.path, headers=headers)
        self.connected, self.code = await self.comm.connect()
        return self

    async def __aexit__(self, *exc):
        if self.connected:
            await self.comm.disconnect()

    async def event(self):
        return await self.comm.receive_json_from(timeout=2)

    async def silent(self):
        return await self.comm.receive_nothing(timeout=0.4)


def _reset_process_state():
    """The pause after a failed push and the per-user socket counts are module
    state; a test that trips them must not leave them tripped."""
    realtime._muted_until = 0.0
    consumers._open.clear()


class _World(TransactionTestCase):
    """An operator, a leader, a translator on one task, an admin and a stranger."""

    def setUp(self):
        _reset_process_state()
        self.addCleanup(_reset_process_state)
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
            app = AllowedHostsOriginValidator(URLRouter(websocket_urlpatterns))
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
        _reset_process_state()
        self.addCleanup(_reset_process_state)
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
            with self.assertLogs("dashboard", level="ERROR"), self.captureOnCommitCallbacks(execute=True):
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


class TranslatorNeverEntersAClientRoomTests(_World):
    """Found by the privacy review: a leader could add a translator to a client room.

    The cleanup that keeps translators out lives in ``ensure_room``, which no
    production code calls, and the add-members endpoint only asked whether the
    person was on the task. The gate every reader shares is ``can_access``.
    """

    def _seat_translator(self):
        # The way the endpoint used to, or a row left over from before the rule.
        self.client_room.members.add(self.tr)

    def test_a_translator_with_a_seat_cannot_open_the_room_by_hand(self):
        self._seat_translator()
        self.assertFalse(self.client_room.can_access(self.tr))
        self.assertFalse(self.client_room.can_open(self.tr))
        request = RequestFactory().get("/")
        request.user = self.tr
        with self.assertRaises((Http404, PermissionDenied)):
            api._room_or_404(request, self.client_room.pk)

    def test_the_messages_endpoint_gives_that_translator_nothing(self):
        self._seat_translator()
        ChatMessage.objects.create(room=self.client_room, sender=self.ops, body="the clients own words")
        browser = DjangoClient()
        browser.force_login(self.tr)
        answer = browser.get(reverse("dashboard:api_chat_fetch", args=[self.client_room.pk]))
        self.assertEqual(answer.status_code, 404)
        self.assertNotIn(b"own words", answer.content)

    async def test_that_translator_is_not_pinged_either(self):
        await sync_to_async(self._seat_translator)()
        async with _Socket(self.tr) as tr, _Socket(self.ops) as ops:
            await self.say(self.client_room, self.ops)
            self.assertEqual(await ops.event(), {"t": "room", "id": self.client_room.pk})
            self.assertTrue(await tr.silent())

    def test_the_add_members_endpoint_refuses_a_translator(self):
        browser = DjangoClient()
        browser.force_login(self.ops)
        answer = browser.post(
            reverse("dashboard:api_group_add_members", args=[self.client_room.pk]),
            {"members": [self.tr.pk]},
        )
        self.assertFalse(self.client_room.members.filter(pk=self.tr.pk).exists())
        body = answer.json()
        self.assertFalse(body["ok"])
        self.assertTrue(body["error"])

    def test_other_rooms_still_admit_a_translator_on_the_task(self):
        self.assertTrue(self.group.can_access(self.tr))
        self.assertTrue(self.group.can_open(self.tr))


class AudienceSkipsInactiveAccountsTests(_World):
    def test_inactive_members_and_admins_are_not_in_the_audience(self):
        User.objects.filter(pk__in=[self.tr.pk, self.admin.pk]).update(is_active=False)
        names = {u.username for u in realtime.room_audience(self.group)}
        self.assertEqual(names, {"ops", "lead"})


class RoomPingFollowsTheMessageToCompletionTests(_World):
    """The first moment of a message is not its last: files, tags and the relay result follow."""

    async def test_a_later_save_of_the_message_pings_again(self):
        async with _Socket(self.ops) as sock:
            message = await self.say(self.group, self.lead)
            want = {"t": "room", "id": self.group.pk}
            self.assertEqual(await sock.event(), want)
            message.relay_status = "failed"
            await sync_to_async(message.save)(update_fields=["relay_status"])
            self.assertEqual(await sock.event(), want)

    async def test_an_attachment_arriving_pings(self):
        message = await self.say(self.group, self.lead)
        async with _Socket(self.ops) as sock:
            await sync_to_async(ChatAttachment.objects.create)(
                message=message, file=ContentFile(b"data", name="a.txt"), original_name="a.txt",
            )
            self.assertEqual(await sock.event(), {"t": "room", "id": self.group.pk})


class WhatEventsMayCarryTests(_World):
    def test_clean_event_keeps_a_kind_and_an_integer_id_only(self):
        self.assertEqual(
            realtime.clean_event({"t": "room", "id": 7, "title": "ACME", "body": "x"}),
            {"t": "room", "id": 7},
        )
        self.assertEqual(realtime.clean_event({"t": "notify", "title": "x"}), {"t": "notify"})
        self.assertEqual(realtime.clean_event({"t": "room", "id": "7"}), {"t": "room"})
        self.assertEqual(realtime.clean_event({"t": "room", "id": True}), {"t": "room"})
        for junk in (None, "room", [], {"id": 1}, {"t": "reboot"}):
            self.assertIsNone(realtime.clean_event(junk))

    async def test_what_reaches_the_browser_is_cleaned_even_if_the_layer_was_fed_more(self):
        async with _Socket(self.ops) as sock:
            await get_channel_layer().group_send(
                realtime.user_group(self.ops.pk),
                {"type": "push", "event": {"t": "room", "id": 3, "title": "ACME Secret Ltd"}},
            )
            self.assertEqual(await sock.event(), {"t": "room", "id": 3})
            await get_channel_layer().group_send(
                realtime.user_group(self.ops.pk),
                {"type": "push", "event": {"t": "something-else"}},
            )
            self.assertTrue(await sock.silent())


class SlowOrBrokenRedisTests(TestCase):
    """A push must never make a request wait, and a failing layer is left alone for a while."""

    def setUp(self):
        _reset_process_state()
        self.addCleanup(_reset_process_state)
        previous = logging.root.manager.disable
        logging.disable(logging.NOTSET)
        self.addCleanup(logging.disable, previous)

    def test_a_hanging_layer_is_cut_off_at_the_time_limit(self):
        class Hangs:
            async def group_send(self, *args, **kwargs):
                await asyncio.sleep(30)

        started = time.monotonic()
        with mock.patch.object(realtime, "PUSH_TIMEOUT", 0.2), \
                mock.patch("channels.layers.get_channel_layer", return_value=Hangs()):
            with self.assertLogs("dashboard", level="ERROR"):
                realtime._deliver([1], {"t": realtime.NOTIFY})
        self.assertLess(time.monotonic() - started, 5)

    def test_after_a_failure_the_layer_is_not_tried_again_until_the_pause_ends(self):
        calls = []

        def broken():
            calls.append(1)
            raise RuntimeError("redis down")

        with mock.patch("channels.layers.get_channel_layer", side_effect=broken):
            with self.assertLogs("dashboard", level="ERROR"):
                realtime._deliver([1], {"t": realtime.NOTIFY})
            realtime._deliver([1], {"t": realtime.NOTIFY})
            realtime._deliver([2], {"t": realtime.NOTIFY})
            self.assertEqual(len(calls), 1)
            # Once the pause is over it tries again.
            realtime._muted_until = 0.0
            with self.assertLogs("dashboard", level="ERROR"):
                realtime._deliver([1], {"t": realtime.NOTIFY})
            self.assertEqual(len(calls), 2)

    def test_a_cancelled_delivery_does_not_escape_into_the_caller(self):
        with mock.patch("channels.layers.get_channel_layer", side_effect=asyncio.CancelledError()):
            with self.assertLogs("dashboard", level="ERROR"):
                realtime._deliver([1], {"t": realtime.NOTIFY})


class SocketLimitsTests(_World):
    async def test_two_quick_pings_cost_one_database_check(self):
        async with _Socket(self.ops) as sock:
            await sock.comm.send_json_to({"t": "ping"})
            await sock.comm.send_json_to({"t": "ping"})
            self.assertEqual(await sock.event(), {"t": "pong"})
            self.assertTrue(await sock.silent())

    async def test_a_person_may_hold_only_so_many_sockets(self):
        sockets = []
        try:
            for _ in range(consumers.MAX_SOCKETS_PER_USER):
                sock = await _Socket(self.ops).__aenter__()
                self.assertTrue(sock.connected)
                sockets.append(sock)
            extra = await _Socket(self.ops).__aenter__()
            self.assertFalse(extra.connected)
            self.assertEqual(extra.code, CLOSE_TOO_MANY)
            # Closing one makes room again.
            await sockets.pop().__aexit__()
            again = await _Socket(self.ops).__aenter__()
            self.assertTrue(again.connected)
            sockets.append(again)
        finally:
            for sock in sockets:
                await sock.__aexit__()

    async def test_a_binary_frame_closes_the_socket_without_a_traceback(self):
        async with _Socket(self.ops) as sock:
            await sock.comm.send_to(bytes_data=b"\x00\x01")
            out = await sock.comm.receive_output(timeout=2)
            self.assertEqual(out["type"], "websocket.close")
            self.assertEqual(out["code"], CLOSE_BAD_FRAME)

    async def test_broken_json_closes_the_socket_without_a_traceback(self):
        async with _Socket(self.ops) as sock:
            await sock.comm.send_to(text_data="{not json")
            out = await sock.comm.receive_output(timeout=2)
            self.assertEqual(out["code"], CLOSE_BAD_FRAME)

    async def test_an_unknown_socket_path_is_refused(self):
        async with _Socket(self.ops, path="/ws/other/") as sock:
            self.assertFalse(sock.connected)

    async def test_a_layer_that_is_down_refuses_the_connection_politely(self):
        with mock.patch.object(
            get_channel_layer().__class__, "group_add", side_effect=RuntimeError("redis down")
        ):
            async with _Socket(self.ops) as sock:
                self.assertFalse(sock.connected)
                self.assertEqual(sock.code, CLOSE_UNAVAILABLE)
