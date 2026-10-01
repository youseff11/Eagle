"""``/api/v1/``: who gets in, who gets what, and that nothing names a client.

Every role is run against every route. The point is the sweep at the bottom:
whatever a route returns to a role that may not see a client's identity, the
client's name, number and address are nowhere in the bytes.
"""

import json
import logging
from datetime import timedelta
from io import StringIO
from unittest import mock

from django.core.management import call_command
from django.test import Client as DjangoClient
from django.test import TestCase
from django.urls import resolve, reverse
from django.utils import timezone

from . import api_v1, identity, services
from .models import (
    AuditLog, ChatMessage, ChatRead, ChatRoom, Client, Notification, Role, RoomKind, Task, User,
)

CHAT_KINDS = ("clients", "groups", "staff")
CLIENT_NAME = "ACME Secret Ltd"
CLIENT_PHONE = "+201001234567"
CLIENT_EMAIL = "boss@acme-secret.example"
#: What must never reach a role without identity access.
IDENTITY_MARKERS = ("ACME Secret", "acme-secret", "201001234567", "1234567")


def _json(response):
    return json.loads(response.content.decode("utf-8"))


class _Site(TestCase):
    """One of each role, one client, a task in progress and the rooms around it."""

    def setUp(self):
        make = lambda name, role, **kw: User.objects.create_user(name, password="pw", role=role, **kw)
        # Long, distinctive names: a short one ("tr") is a substring of "true".
        self.admin = make("person_admin", Role.ADMIN)
        self.ops = make("person_operation", Role.OPERATION)
        self.lead = make("person_leader", Role.TEAM_LEAD)
        self.tr = make("person_translator", Role.TRANSLATOR, team_lead=self.lead)
        self.hr = make("person_hr_staff", Role.HR)
        self.reviewer = make("person_reviewer", Role.REVIEWER)
        self.accounting = make("person_accountant", Role.ACCOUNTING)
        self.sales = make("person_salesman", Role.SALES)
        self.everyone = [self.admin, self.ops, self.lead, self.tr, self.hr,
                         self.reviewer, self.accounting, self.sales]
        #: Roles that may see a real client name. Everybody else must not.
        self.masked = [self.ops, self.lead, self.tr, self.hr, self.reviewer, self.accounting]

        self.client_obj = Client.objects.create(
            name=CLIENT_NAME, phone=CLIENT_PHONE, email=CLIENT_EMAIL
        )
        inbound = services.ingest_message(
            channel="whatsapp", body="hello there", sender_identity=CLIENT_PHONE
        )
        self.task = services.create_task(
            client=self.client_obj, title="Doc", created_by=self.ops,
            deadline=timezone.now() + timedelta(hours=3), messages=[inbound],
        )
        first = services.assign_to_lead(self.task, self.lead, self.ops)
        services.accept_assignment(first, self.lead)
        second = services.assign_to_translator(self.task, self.tr, self.lead)
        services.accept_assignment(second, self.tr)

        self.task_client_room = services.ensure_room(self.task, RoomKind.CLIENT)
        self.task_group = services.ensure_room(self.task, RoomKind.GROUP)
        self.work_group = services.lead_translator_group(self.lead, self.tr)
        self.staff = services.staff_room(self.ops, self.lead)
        self.client_group = ChatRoom.objects.create(
            kind=RoomKind.CLIENT, client=self.client_obj, title="Client group",
            created_by=self.ops,
        )
        self.client_group.members.add(self.ops)
        for room, who in ((self.task_client_room, self.ops), (self.task_group, self.lead),
                          (self.work_group, self.lead), (self.staff, self.ops),
                          (self.client_group, self.ops)):
            ChatMessage.objects.create(room=room, sender=who, body="Please look at this")

    # -- helpers ------------------------------------------------------------
    def get(self, user, name, args=None, **query):
        browser = DjangoClient()
        if user is not None:
            browser.force_login(user)
        return browser.get(reverse(f"dashboard:{name}", args=args), query)

    def every_get_route(self):
        """Each GET route of the layer, with working arguments."""
        return [
            ("v1_me", None, {}),
            ("v1_notifications", None, {}),
            ("v1_chats", None, {"type": "clients"}),
            ("v1_chats", None, {"type": "groups"}),
            ("v1_chats", None, {"type": "staff"}),
            ("v1_room_messages", [self.task_client_room.pk], {}),
            ("v1_room_messages", [self.task_group.pk], {}),
            ("v1_group_messages", [self.client_group.pk], {}),
            ("v1_group_messages", [self.work_group.pk], {}),
            ("v1_group_messages", [self.staff.pk], {}),
            ("v1_client_messages", [self.client_obj.code], {}),
        ]


class ContractTests(_Site):
    def test_every_route_answers_the_anonymous_with_json_401(self):
        for name, args, query in self.every_get_route():
            answer = self.get(None, name, args, **query)
            self.assertEqual(answer.status_code, 401, name)
            self.assertEqual(_json(answer), {"ok": False, "error": "auth"}, name)
            self.assertIn("application/json", answer["Content-Type"])
        answer = DjangoClient().post(reverse("dashboard:v1_notifications_read"))
        self.assertEqual(answer.status_code, 401)

    def test_an_unknown_path_under_v1_is_json_404(self):
        for user in (None, self.ops):
            browser = DjangoClient()
            if user:
                browser.force_login(user)
            answer = browser.get("/api/v1/nothing/here/")
            self.assertEqual(answer.status_code, 404)
            self.assertEqual(_json(answer), {"ok": False, "error": "not_found"})

    def test_the_wrong_method_is_405_and_says_what_is_allowed(self):
        browser = DjangoClient()
        browser.force_login(self.ops)
        answer = browser.post(reverse("dashboard:v1_me"))
        self.assertEqual(answer.status_code, 405)
        self.assertEqual(answer["Allow"], "GET")
        answer = browser.get(reverse("dashboard:v1_notifications_read"))
        self.assertEqual(answer.status_code, 405)
        self.assertEqual(answer["Allow"], "POST")

    def test_a_bad_chat_type_is_a_400(self):
        answer = self.get(self.ops, "v1_chats", type="everything")
        self.assertEqual(answer.status_code, 400)
        self.assertEqual(_json(answer)["error"], "bad_type")

    def test_the_csrf_cookie_comes_with_me_and_a_post_needs_the_token(self):
        browser = DjangoClient(enforce_csrf_checks=True)
        browser.force_login(self.ops)
        self.assertEqual(browser.post(reverse("dashboard:v1_notifications_read")).status_code, 403)
        refused = browser.post(reverse("dashboard:v1_notifications_read"))
        self.assertEqual(_json(refused), {"ok": False, "error": "csrf"})
        browser.get(reverse("dashboard:v1_me"))
        token = browser.cookies["csrftoken"].value
        allowed = browser.post(
            reverse("dashboard:v1_notifications_read"), {"all": "1"}, HTTP_X_CSRFTOKEN=token
        )
        self.assertEqual(allowed.status_code, 200)

    def test_a_page_outside_the_api_keeps_djangos_own_csrf_page(self):
        browser = DjangoClient(enforce_csrf_checks=True)
        browser.force_login(self.ops)
        answer = browser.post(reverse("dashboard:api_notifications_read"))
        self.assertEqual(answer.status_code, 403)
        self.assertNotIn("application/json", answer["Content-Type"])


class MeTests(_Site):
    def test_me_is_the_callers_own_record_and_only_that(self):
        for user in self.everyone:
            body = _json(self.get(user, "v1_me"))
            self.assertTrue(body["ok"])
            self.assertEqual(body["user"]["id"], user.pk)
            self.assertEqual(body["user"]["username"], user.username)
            self.assertEqual(body["user"]["role"], user.role)
            for other in self.everyone:
                if other is not user:
                    self.assertNotIn(other.username, json.dumps(body), f"{user.username} sees {other.username}")

    def test_only_the_roles_that_own_the_client_inbox_get_the_client_tab(self):
        with_clients = {Role.ADMIN, Role.OPERATION, Role.SALES}
        for user in self.everyone:
            types = _json(self.get(user, "v1_me"))["chats"]["types"]
            self.assertEqual("clients" in types, user.role in with_clients, user.username)
            self.assertIn("groups", types)
            self.assertIn("staff", types)

    def test_me_tells_the_page_where_the_socket_is(self):
        realtime = _json(self.get(self.ops, "v1_me"))["realtime"]
        self.assertEqual(realtime["path"], "/ws/events/")
        self.assertGreaterEqual(realtime["ping_seconds"], 10)


class NotificationTests(_Site):
    def setUp(self):
        super().setUp()
        Notification.objects.all().delete()
        self.mine = [
            services.notify(self.ops, title_ar=f"n{i}", title_en=f"n{i}") for i in range(5)
        ]
        self.others = [services.notify(self.lead, title_ar="theirs", title_en="theirs")]

    def test_a_page_of_my_own_newest_first(self):
        body = _json(self.get(self.ops, "v1_notifications", limit=2))
        self.assertEqual([n["id"] for n in body["items"]], [self.mine[4].id, self.mine[3].id])
        self.assertEqual(body["next_before"], self.mine[3].id)
        self.assertEqual(body["unread"], 5)
        self.assertTrue(all(item["read"] is False for item in body["items"]))

    def test_the_cursor_walks_back_to_the_end(self):
        seen, before = [], None
        for _ in range(10):
            query = {"limit": 2, **({"before": before} if before else {})}
            body = _json(self.get(self.ops, "v1_notifications", **query))
            seen += [n["id"] for n in body["items"]]
            before = body["next_before"]
            if before is None:
                break
        self.assertEqual(seen, [n.id for n in reversed(self.mine)])

    def test_the_page_size_is_clamped(self):
        for asked, got in ((0, 1), (-5, 1), (10000, 5), ("abc", 5)):
            body = _json(self.get(self.ops, "v1_notifications", limit=asked))
            self.assertEqual(len(body["items"]), got, asked)

    def test_nobody_sees_anyone_elses(self):
        body = _json(self.get(self.ops, "v1_notifications"))
        self.assertNotIn("theirs", json.dumps(body))
        self.assertEqual(len(_json(self.get(self.lead, "v1_notifications"))["items"]), 1)
        self.assertEqual(_json(self.get(self.tr, "v1_notifications"))["items"], [])

    def test_read_with_ids_marks_only_those_and_only_mine(self):
        browser = DjangoClient()
        browser.force_login(self.ops)
        url = reverse("dashboard:v1_notifications_read")
        answer = browser.post(url, {"ids": [self.mine[0].id, self.others[0].id]})
        body = _json(answer)
        self.assertEqual(body["updated"], 1)
        self.assertEqual(body["unread"], 4)
        self.others[0].refresh_from_db()
        self.assertFalse(self.others[0].is_read)

    def test_read_takes_a_json_body_too(self):
        browser = DjangoClient()
        browser.force_login(self.ops)
        answer = browser.post(
            reverse("dashboard:v1_notifications_read"),
            data=json.dumps({"ids": [self.mine[1].id]}), content_type="application/json",
        )
        self.assertEqual(_json(answer)["updated"], 1)

    def test_read_all_marks_everything_of_mine_and_only_when_asked(self):
        browser = DjangoClient()
        browser.force_login(self.ops)
        body = _json(browser.post(reverse("dashboard:v1_notifications_read"), {"all": "1"}))
        self.assertEqual(body["updated"], 5)
        self.assertEqual(body["unread"], 0)
        self.others[0].refresh_from_db()
        self.assertFalse(self.others[0].is_read)


class ChatReadTests(_Site):
    def labels(self, user, kind):
        body = _json(self.get(user, "v1_chats", type=kind))
        return body, [item["label"] for item in body["items"]]

    def test_the_client_directory_is_only_for_the_roles_that_own_the_inbox(self):
        for user in (self.tr, self.lead, self.hr, self.reviewer, self.accounting):
            self.assertEqual(_json(self.get(user, "v1_chats", type="clients"))["items"], [], user.username)
        body, labels = self.labels(self.ops, "clients")
        self.assertIn(self.client_obj.code, labels)
        self.assertNotIn(CLIENT_NAME, json.dumps(body))

    def test_a_translators_groups_are_their_work_group_and_never_a_client_room(self):
        body, labels = self.labels(self.tr, "groups")
        rooms = {item["room"] for item in body["items"]}
        self.assertIn(self.work_group.pk, rooms)
        self.assertNotIn(self.client_group.pk, rooms)
        self.assertNotIn(self.task_client_room.pk, rooms)
        self.assertFalse(any(item.get("reaches_client") for item in body["items"]))

    def test_a_translator_seated_in_a_client_room_still_gets_nothing_from_it(self):
        self.task_client_room.members.add(self.tr)
        self.client_group.members.add(self.tr)
        body, _ = self.labels(self.tr, "groups")
        rooms = {item["room"] for item in body["items"]}
        self.assertNotIn(self.task_client_room.pk, rooms)
        self.assertNotIn(self.client_group.pk, rooms)
        self.assertEqual(self.get(self.tr, "v1_room_messages", [self.task_client_room.pk]).status_code, 404)
        self.assertEqual(self.get(self.tr, "v1_group_messages", [self.client_group.pk]).status_code, 404)

    def test_a_seated_translators_unread_count_ignores_the_client_rooms(self):
        self.task_client_room.members.add(self.tr)
        self.client_group.members.add(self.tr)
        ChatMessage.objects.create(room=self.client_group, sender=self.ops, body="the client wrote")
        listed = services.listed_room_ids(self.tr)
        self.assertNotIn(self.client_group.pk, listed)
        self.assertNotIn(self.task_client_room.pk, listed)
        self.assertNotIn(self.task_client_room, services.rooms_for(self.task, self.tr))
        self.assertNotIn(self.client_group, services.groups_for(self.tr))

    def test_the_list_never_carries_a_clients_words_to_a_seated_translator(self):
        self.client_group.members.add(self.tr)
        ChatMessage.objects.create(room=self.client_group, sender=self.ops, body="what the client wrote")
        for kind in CHAT_KINDS:
            self.assertNotIn(b"what the client wrote", self.get(self.tr, "v1_chats", type=kind).content)

    def test_a_room_is_a_404_to_someone_who_may_not_open_it(self):
        for user in (self.tr, self.hr, self.reviewer, self.accounting, self.sales):
            answer = self.get(user, "v1_room_messages", [self.task_client_room.pk])
            self.assertEqual(answer.status_code, 404, user.username)
            self.assertEqual(_json(answer), {"ok": False, "error": "not_found"})

    def test_members_and_the_admin_read_a_room(self):
        for user in (self.ops, self.lead, self.admin):
            answer = self.get(user, "v1_room_messages", [self.task_client_room.pk])
            self.assertEqual(answer.status_code, 200, user.username)
            self.assertTrue(_json(answer)["messages"])

    def test_a_private_staff_chat_is_closed_to_the_admin(self):
        self.assertEqual(self.get(self.admin, "v1_group_messages", [self.staff.pk]).status_code, 404)
        for user in (self.ops, self.lead):
            self.assertEqual(self.get(user, "v1_group_messages", [self.staff.pk]).status_code, 200)

    def test_the_work_group_is_for_its_members(self):
        for user in (self.lead, self.tr, self.admin):
            self.assertEqual(self.get(user, "v1_group_messages", [self.work_group.pk]).status_code, 200, user.username)
        self.assertEqual(self.get(self.hr, "v1_group_messages", [self.work_group.pk]).status_code, 404)

    def test_a_client_conversation_is_refused_to_everyone_but_the_inbox_roles(self):
        for user in (self.tr, self.lead, self.hr, self.reviewer, self.accounting):
            answer = self.get(user, "v1_client_messages", [self.client_obj.code])
            self.assertEqual(answer.status_code, 403, user.username)
            self.assertEqual(_json(answer)["error"], "forbidden")
        self.assertEqual(self.get(self.ops, "v1_client_messages", [self.client_obj.code]).status_code, 200)

    def test_a_refusal_is_written_to_the_audit_log(self):
        before = AuditLog.objects.filter(action=identity.ACCESS_DENIED, actor=self.tr).count()
        self.get(self.tr, "v1_room_messages", [self.task_client_room.pk])
        self.get(self.tr, "v1_client_messages", [self.client_obj.code])
        after = AuditLog.objects.filter(action=identity.ACCESS_DENIED, actor=self.tr).count()
        self.assertEqual(after - before, 2)


class NoClientIdentityLeaksTests(_Site):
    """Every route, every role without identity access: the name is nowhere in the bytes."""

    def test_no_route_gives_a_masked_role_the_clients_name_number_or_address(self):
        checked = 0
        for user in self.masked:
            for name, args, query in self.every_get_route():
                answer = self.get(user, name, args, **query)
                text = answer.content.decode("utf-8")
                for marker in IDENTITY_MARKERS:
                    self.assertNotIn(marker, text, f"{user.username} {name} {args} leaks {marker!r}")
                checked += 1
        self.assertEqual(checked, len(self.masked) * len(self.every_get_route()))

    def test_the_sweep_would_notice_a_leak(self):
        # The same scan, pointed at a role that is allowed to see the name: the
        # admin's notifications do carry it, so the markers are findable at all.
        services.notify(
            self.admin, title_ar="x", title_en=f"Chat with {self.client_obj.label_for(self.admin)}",
        )
        text = self.get(self.admin, "v1_notifications").content.decode("utf-8")
        self.assertTrue(any(marker in text for marker in IDENTITY_MARKERS))

    def test_notifications_the_workflow_wrote_do_not_name_the_client_to_masked_roles(self):
        for user in self.masked:
            text = self.get(user, "v1_notifications", limit=50).content.decode("utf-8")
            for marker in IDENTITY_MARKERS:
                self.assertNotIn(marker, text, f"{user.username} notification leaks {marker!r}")
        # And the workflow really did write some, or the line above proves nothing.
        self.assertTrue(Notification.objects.filter(user=self.tr).exists())
        self.assertTrue(Notification.objects.filter(user=self.lead).exists())


# ---------------------------------------------------------------------------
# Found by the privacy and security reviews of this layer
# ---------------------------------------------------------------------------

class SeatedPeopleAreNotToldWhatTheClientSaidTests(_Site):
    """The notification quotes the client's words, so it goes only to people who may open the room."""

    WORDS = "CLIENT WORDS ABOUT THE PRICE"

    def client_writes(self):
        with self.captureOnCommitCallbacks(execute=True):
            services.ingest_message(
                channel="whatsapp", body=self.WORDS, sender_identity=CLIENT_PHONE,
            )

    def quoting(self, user):
        return [
            n for n in Notification.objects.filter(user=user)
            if "CLIENT WORDS" in (n.body_en + n.body_ar)
        ]

    def test_a_member_who_may_open_the_room_is_told(self):
        # The control: without it the tests below could pass because nobody is told anything.
        self.client_writes()
        self.assertTrue(self.quoting(self.lead))

    def test_a_translator_seated_in_a_client_room_or_group_is_told_nothing(self):
        self.task_client_room.members.add(self.tr)
        self.client_group.members.add(self.tr)
        self.client_writes()
        self.assertEqual(self.quoting(self.tr), [])
        text = self.get(self.tr, "v1_notifications", limit=50).content.decode("utf-8")
        self.assertNotIn("CLIENT WORDS", text)

    def test_a_team_lead_taken_off_the_task_is_told_nothing(self):
        other = User.objects.create_user("person_other_leader", password="pw", role=Role.TEAM_LEAD)
        self.task_client_room.members.add(other)
        self.client_writes()
        self.assertEqual(self.quoting(other), [])

    def test_an_operation_reply_in_a_client_room_does_not_notify_a_seated_translator(self):
        self.task_client_room.members.add(self.tr)
        browser = DjangoClient()
        browser.force_login(self.ops)
        with mock.patch("dashboard.services.relay_chat_message", return_value=(True, "")):
            answer = browser.post(
                reverse("dashboard:api_chat_send", args=[self.task_client_room.pk]),
                {"body": "OPS REPLY FOR THE CLIENT"},
            )
        self.assertEqual(answer.status_code, 200)
        self.assertFalse(
            Notification.objects.filter(user=self.tr, body_en__contains="OPS REPLY").exists()
        )
        # And the leader, who may open the room, is told.
        self.assertTrue(
            Notification.objects.filter(user=self.lead, body_en__contains="OPS REPLY").exists()
        )


class ListsFollowTheRoomGateTests(_Site):
    """A list or a badge must not show what opening the room would refuse."""

    def seat_everyone_everywhere(self):
        self.stale_leader = User.objects.create_user(
            "person_stale_leader", password="pw", role=Role.TEAM_LEAD
        )
        for room in ChatRoom.objects.all():
            room.members.add(self.tr, self.hr, self.reviewer, self.accounting, self.stale_leader)

    def test_a_listed_room_is_always_one_the_person_may_open(self):
        self.seat_everyone_everywhere()
        everyone = self.everyone + [self.stale_leader]
        listed_somewhere = 0
        for user in everyone:
            for room in services.groups_for(user):
                listed_somewhere += 1
                self.assertTrue(room.can_open(user), f"{user.username} is listed room {room.pk} but cannot open it")
            for room_id in services.listed_room_ids(user):
                room = ChatRoom.objects.get(pk=room_id)
                if room.kind != RoomKind.STAFF:
                    self.assertTrue(room.can_open(user), f"{user.username} is counted room {room.pk} but cannot open it")
        self.assertGreater(listed_somewhere, 3)

    def test_people_seated_in_a_task_room_without_the_task_see_nothing_of_it(self):
        self.seat_everyone_everywhere()
        ChatMessage.objects.create(room=self.task_client_room, sender=self.ops, body="LAST WORDS TO CLIENT")
        for user in (self.hr, self.reviewer, self.accounting, self.stale_leader):
            body = _json(self.get(user, "v1_chats", type="groups"))
            self.assertNotIn(self.task_client_room.pk, {item["room"] for item in body["items"]}, user.username)
            self.assertNotIn(b"LAST WORDS TO CLIENT", self.get(user, "v1_chats", type="groups").content)
            self.assertNotIn(self.task_client_room.pk, services.listed_room_ids(user), user.username)

    def test_the_people_who_may_open_the_task_room_still_see_it(self):
        for user in (self.admin, self.ops, self.lead):
            ids = {room.pk for room in services.groups_for(user)}
            self.assertIn(self.task_client_room.pk, ids, user.username)

    def test_a_superuser_with_the_default_translator_role_is_not_shown_client_rooms(self):
        # ``User.save`` turns a NEW superuser into an admin, so the edge is a translator who is
        # made a superuser afterwards (Django's admin does it): still a translator by role,
        # an admin by ``is_admin_role``.
        boss = User.objects.create_user("person_superuser", password="pw", role=Role.TRANSLATOR)
        User.objects.filter(pk=boss.pk).update(is_superuser=True)
        boss = User.objects.get(pk=boss.pk)
        self.assertTrue(boss.is_translator and boss.is_admin_role)
        self.assertFalse(self.client_group.can_access(boss))
        self.assertNotIn(self.client_group.pk, services.listed_room_ids(boss))
        self.assertNotIn(self.client_group, services.groups_for(boss))
        self.assertNotIn(self.task_client_room, services.rooms_for(self.task, boss))

    def test_visible_tasks_is_can_view_as_a_queryset(self):
        other_task = services.create_task(
            client=self.client_obj, title="Other", created_by=self.ops,
            deadline=timezone.now() + timedelta(hours=1),
        )
        for user in self.everyone:
            for task in (self.task, other_task):
                self.assertEqual(
                    task.can_view(user),
                    services.visible_tasks(user).filter(pk=task.pk).exists(),
                    f"{user.username} / {task.code}",
                )


class ReadingIsNotAGetTests(_Site):
    """``?read=1`` marks a conversation read - and tells the client's phone. Not on a GET."""

    def setUp(self):
        super().setUp()
        services.ingest_message(
            channel="whatsapp", body="a message to read", sender_identity=CLIENT_PHONE,
            external_id="wamid.TEST-READ-1",
        )

    def test_the_old_endpoint_marks_a_group_read_on_get_the_new_one_does_not(self):
        old = reverse("dashboard:api_group_chat_fetch", args=[self.client_group.pk])
        browser = DjangoClient()
        browser.force_login(self.ops)
        browser.get(old, {"read": "1"})
        self.assertTrue(ChatRead.objects.filter(user=self.ops, room=self.client_group).exists())
        ChatRead.objects.all().delete()
        new = reverse("dashboard:v1_group_messages", args=[self.client_group.pk])
        self.assertEqual(browser.get(new, {"read": "1"}).status_code, 200)
        self.assertFalse(ChatRead.objects.filter(user=self.ops, room=self.client_group).exists())

    def test_a_get_never_sends_the_client_a_read_receipt(self):
        browser = DjangoClient()
        browser.force_login(self.ops)
        with mock.patch("dashboard.services.send_read_receipt") as receipt:
            answer = browser.get(
                reverse("dashboard:v1_client_messages", args=[self.client_obj.code]), {"read": "1"}
            )
        self.assertEqual(answer.status_code, 200)
        receipt.assert_not_called()
        self.assertFalse(ChatRead.objects.filter(user=self.ops, client=self.client_obj).exists())

    def test_the_post_reads_and_only_the_post_sends_the_receipt(self):
        browser = DjangoClient(enforce_csrf_checks=True)
        browser.force_login(self.ops)
        url = reverse("dashboard:v1_client_read", args=[self.client_obj.code])
        self.assertEqual(browser.post(url).status_code, 403)
        browser.get(reverse("dashboard:v1_me"))
        token = browser.cookies["csrftoken"].value
        with mock.patch("dashboard.services.send_read_receipt") as receipt:
            answer = browser.post(url, HTTP_X_CSRFTOKEN=token)
        self.assertEqual(answer.status_code, 200)
        self.assertTrue(_json(answer)["moved"])
        receipt.assert_called_once()

    def test_reading_a_client_conversation_is_for_the_inbox_roles(self):
        for user in (self.tr, self.lead, self.hr, self.reviewer, self.accounting):
            browser = DjangoClient()
            browser.force_login(user)
            answer = browser.post(reverse("dashboard:v1_client_read", args=[self.client_obj.code]))
            self.assertEqual(answer.status_code, 403, user.username)

    def test_reading_a_group_needs_the_right_to_open_it(self):
        url = reverse("dashboard:v1_group_read", args=[self.work_group.pk])
        for user, status in ((self.hr, 404), (self.tr, 200), (self.lead, 200)):
            browser = DjangoClient()
            browser.force_login(user)
            self.assertEqual(browser.post(url).status_code, status, user.username)
        self.assertTrue(ChatRead.objects.filter(user=self.tr, room=self.work_group).exists())

    def test_a_get_on_a_read_route_is_a_405(self):
        for name, args in (("v1_group_read", [self.work_group.pk]), ("v1_client_read", [self.client_obj.code])):
            self.assertEqual(self.get(self.ops, name, args).status_code, 405)


class BadInputTests(_Site):
    def setUp(self):
        super().setUp()
        Notification.objects.all().delete()
        self.notes = [services.notify(self.ops, title_ar="n", title_en="n") for _ in range(3)]
        self.browser = DjangoClient()
        self.browser.force_login(self.ops)
        self.url = reverse("dashboard:v1_notifications_read")

    def post_json(self, payload):
        data = payload if isinstance(payload, (str, bytes)) else json.dumps(payload)
        return self.browser.post(self.url, data=data, content_type="application/json")

    def assert_refused_and_nothing_marked(self, answer, label):
        self.assertEqual(answer.status_code, 400, label)
        self.assertEqual(_json(answer), {"ok": False, "error": "bad_ids"}, label)
        self.assertEqual(Notification.objects.filter(user=self.ops, is_read=True).count(), 0, label)

    def test_unreadable_selections_are_a_400_and_clear_nothing(self):
        bad = {
            "empty list": {"ids": []},
            "no ids and no all": {},
            "ids is not a list": {"ids": "abc"},
            "zero": {"ids": [0]},
            "negative": {"ids": [-3]},
            "text": {"ids": ["x"]},
            "boolean": {"ids": [True]},
            "float": {"ids": [1.5]},
            "huge integer": {"ids": [10 ** 40]},
            "all that is not true": {"all": "yes"},
            "ids and all together": {"ids": [1], "all": True},
            "too many ids": {"ids": list(range(1, api_v1.MAX_IDS + 2))},
            "a list body": [1, 2, 3],
        }
        for label, payload in bad.items():
            self.assert_refused_and_nothing_marked(self.post_json(payload), label)
        for label, raw in {
            "Infinity": '{"ids": [Infinity]}',
            "1e400": '{"ids": [1e400]}',
            "broken json": "{not json",
            "deeply nested": "[" * 100000,
            "nested in ids": '{"ids": ' + "[" * 100000 + "}",
            "bad utf-8": b'{"ids": [\xff]}',
        }.items():
            self.assert_refused_and_nothing_marked(self.post_json(raw), label)

    def test_form_selections_are_checked_too(self):
        for label, data in {
            "nothing": {}, "text": {"ids": "abc"}, "zero": {"ids": "0"}, "all with ids": {"ids": "1", "all": "1"},
        }.items():
            self.assert_refused_and_nothing_marked(self.browser.post(self.url, data), label)

    def test_the_selection_that_is_meant_still_works(self):
        answer = self.post_json({"ids": [self.notes[0].id, self.notes[1].id]})
        self.assertEqual(_json(answer)["updated"], 2)
        answer = self.post_json({"all": True})
        self.assertEqual(_json(answer)["updated"], 1)
        self.assertEqual(_json(answer)["unread"], 0)

    def test_an_unexpected_error_is_json_without_the_exception_text(self):
        previous = logging.root.manager.disable
        logging.disable(logging.NOTSET)
        self.addCleanup(logging.disable, previous)
        with mock.patch.object(api_v1, "_unread", side_effect=RuntimeError("secret internal detail")):
            with self.assertLogs("dashboard", level="ERROR"):
                answer = self.browser.get(reverse("dashboard:v1_me"))
        self.assertEqual(answer.status_code, 500)
        self.assertEqual(_json(answer), {"ok": False, "error": "server"})
        self.assertNotIn(b"secret internal detail", answer.content)

    def test_every_answer_is_private_and_not_stored(self):
        cases = [
            (self.browser.get(reverse("dashboard:v1_me")), 200),
            (DjangoClient().get(reverse("dashboard:v1_me")), 401),
            (self.browser.get("/api/v1/nothing/"), 404),
            (self.browser.post(reverse("dashboard:v1_me")), 405),
            (self.browser.get(reverse("dashboard:v1_chats"), {"type": "x"}), 400),
        ]
        for answer, status in cases:
            self.assertEqual(answer.status_code, status)
            self.assertEqual(answer["Cache-Control"], "private, no-store", status)

    def test_the_catch_all_is_the_last_route_so_it_shadows_nothing(self):
        from . import urls

        self.assertEqual(urls.urlpatterns[-1].name, "v1_not_found")
        for name, args in (("v1_group_read", [1]), ("v1_client_read", ["CL-1"]), ("v1_me", None)):
            self.assertEqual(resolve(reverse(f"dashboard:{name}", args=args)).url_name, name)


class ClientRoomTranslatorsCommandTests(_Site):
    def seat(self):
        self.task_client_room.members.add(self.tr)
        self.mine = services.notify(
            self.tr, title_ar="x", title_en="New message from the client",
            body_en="Client CL-0001: the words", url=f"/tasks/{self.task.code}/?room={self.task_client_room.pk}",
        )
        self.unrelated = services.notify(self.tr, title_ar="x", title_en="Task assigned", url="/tasks/TSK-1/")

    def run_command(self, *flags):
        out = StringIO()
        call_command("client_room_translators", *flags, stdout=out)
        return out.getvalue()

    def test_a_report_changes_nothing(self):
        self.seat()
        text = self.run_command()
        self.assertIn("person_translator", text)
        self.assertIn("Nothing changed", text)
        self.assertTrue(self.task_client_room.members.filter(pk=self.tr.pk).exists())
        self.assertTrue(Notification.objects.filter(pk=self.mine.pk).exists())

    def test_remove_takes_the_seat_away_and_keeps_the_notifications(self):
        self.seat()
        self.run_command("--remove")
        self.assertFalse(self.task_client_room.members.filter(pk=self.tr.pk).exists())
        self.assertTrue(Notification.objects.filter(pk=self.mine.pk).exists())

    def test_purge_deletes_only_the_notifications_about_that_room(self):
        self.seat()
        self.run_command("--purge-notifications")
        self.assertFalse(Notification.objects.filter(pk=self.mine.pk).exists())
        self.assertTrue(Notification.objects.filter(pk=self.unrelated.pk).exists())

    def test_nobody_seated_says_so(self):
        self.assertIn("No translator is seated", self.run_command())


class GroupRowUsesTheViewersOwnLineTests(_Site):
    def test_the_reply_window_is_the_one_on_the_line_this_person_answers_from(self):
        # The client wrote just now, so the whole-client window is open. What the
        # operation is shown must come from its own line's method, not from that.
        with mock.patch.object(Client, "reply_window_for", return_value=(False, 0)):
            body = _json(self.get(self.ops, "v1_chats", type="groups"))
        row = next(item for item in body["items"] if item["room"] == self.client_group.pk)
        self.assertFalse(row["window_open"])
        self.assertEqual(row["minutes_left"], 0)
        self.assertTrue(self.client_obj.reply_window_open)
