"""The chats screen in the new app, step 3e part 1: work groups (``/api/v1/people/``, ``/api/v1/groups/``,
``/api/v1/groups/<id>/members/`` and ``.../members/add/``).

The doors are thin: who may open a work group, what it is called, who is told, who may be seated where - a work
group, a client room, a task's own people, never a translator in a room that reaches a client - is decided by the
functions the classic page uses. What is pinned here is the contract around them:

* who is offered whom (the list of people exists only for those who may open a group, the people to add only for
  those who may add), every role;
* a refusal is a 4xx and nothing was written, with the reason in ``message``; a partial one is a 200 that says who
  was left out;
* what these doors do is what the classic ones do, for every role;
* nothing here reaches a client, and no client name or number comes back.
"""

import json
from unittest import mock

from django.test import Client as DjangoClient
from django.urls import reverse

from . import services
from .models import AppSettings, AuditLog, ChatMessage, ChatRoom, Client, Notification, Role, RoomKind, Task, User
from .tests_chat_lists import _json
from .tests_chat_send import PHONE, _Send


class _Groups(_Send):
    def setUp(self):
        super().setUp()
        self.text.reset_mock()
        self.ops2 = User.objects.create_user("person_operation_b", password="pw", role=Role.OPERATION)
        self.lead2 = User.objects.create_user("person_leader_b", password="pw", role=Role.TEAM_LEAD)
        self.tr2 = User.objects.create_user("person_translator_b", password="pw", role=Role.TRANSLATOR, team_lead=self.lead2)

    def post(self, name, user, body=None, raw=None, content_type="application/json", args=()):
        data = raw if raw is not None else json.dumps(body if body is not None else {})
        return self.browser(user).post(reverse(f"dashboard:{name}", args=args), data, content_type=content_type)

    def create(self, user, title="", members=(), **kw):
        return self.post("v1_group_create", user, {"title": title, "members": [m.pk for m in members]}, **kw)

    def add(self, user, room, members, **kw):
        return self.post("v1_group_add", user, {"members": [m.pk for m in members]}, args=[room.pk], **kw)

    def members(self, user, room):
        return self.browser(user).get(reverse("dashboard:v1_group_members", args=[room.pk]))

    def groups_made(self):
        return ChatRoom.objects.filter(kind=RoomKind.TEAM).count()


class PeopleTests(_Groups):
    def test_only_those_who_may_open_a_group_are_given_the_list(self):
        for user in self.everyone:
            answer = self.browser(user).get(reverse("dashboard:v1_people"))
            self.assertEqual(answer.status_code == 200, user.can_create_team_group, user.username)
            if answer.status_code != 200:
                self.assertEqual((answer.status_code, _json(answer)["error"]), (403, "forbidden"), user.username)
        self.assertEqual(
            {u.username for u in self.everyone if u.can_create_team_group},
            {"person_admin", "person_operation", "person_leader", "person_boss_sales"},
        )

    def test_it_is_everybody_active_but_the_person_asking_in_the_order_of_role_then_name(self):
        User.objects.filter(pk=self.hr.pk).update(is_active=False)
        body = _json(self.browser(self.lead).get(reverse("dashboard:v1_people")))
        ids = [p["id"] for p in body["people"]]
        self.assertNotIn(self.lead.pk, ids)
        self.assertNotIn(self.hr.pk, ids)
        self.assertIn(self.tr.pk, ids)
        expected = list(
            User.objects.filter(is_active=True).exclude(pk=self.lead.pk).order_by("role", "username").values_list("pk", flat=True)
        )
        self.assertEqual(ids, expected)
        first = body["people"][0]
        self.assertEqual(set(first), {"id", "name", "initials", "role"})

    def test_no_client_and_no_secret_in_it(self):
        answer = self.browser(self.ops).get(reverse("dashboard:v1_people"))
        for text in (b"Zebulon", PHONE.encode(), b"zeb@example.test", b"password", b"mail_alias", b"wa_phone"):
            self.assertNotIn(text, answer.content)

    def test_a_session_and_a_get(self):
        url = reverse("dashboard:v1_people")
        self.assertEqual(DjangoClient().get(url).status_code, 401)
        self.assertEqual(self.browser(self.ops).post(url, "{}", content_type="application/json").status_code, 405)

    def test_a_refusal_is_written_to_the_audit_log(self):
        before = AuditLog.objects.filter(action="security.denied").count()
        self.browser(self.tr).get(reverse("dashboard:v1_people"))
        self.assertEqual(AuditLog.objects.filter(action="security.denied").count(), before + 1)


class CreateTests(_Groups):
    def test_a_leader_opens_a_group_with_a_translator_and_it_is_named_for_them(self):
        answer = self.create(self.lead, members=[self.tr, self.ops2])
        body = _json(answer)
        self.assertEqual(answer.status_code, 200)
        room = ChatRoom.objects.get(pk=body["room"], kind=RoomKind.TEAM)
        self.assertEqual(body["code"], f"g{room.pk}")
        self.assertEqual({m.pk for m in room.members.all()}, {self.lead.pk, self.tr.pk, self.ops2.pk})
        self.assertEqual(room.created_by_id, self.lead.pk)
        self.assertEqual(room.title, f"مترجم: {self.tr.short_name} · ليدر: {self.lead.short_name}")
        self.assertTrue(room.messages.filter(is_system=True).exists())
        self.assertEqual(Notification.objects.filter(title_en="Added to a work group").count(), 2)
        self.assertFalse(Notification.objects.filter(user=self.lead, title_en="Added to a work group").exists())

    def test_a_title_that_was_typed_is_kept_and_cut_at_the_columns_length(self):
        body = _json(self.create(self.ops, title="  Plan the week  ", members=[self.lead]))
        self.assertEqual(ChatRoom.objects.get(pk=body["room"]).title, "Plan the week")

    def test_without_a_name_and_without_one_to_suggest_it_is_refused_and_nothing_is_made(self):
        answer = self.create(self.ops, members=[self.lead])
        body = _json(answer)
        self.assertEqual((answer.status_code, body["ok"], body["error"]), (400, False, "refused"))
        self.assertTrue(body["message"])
        self.assertEqual(self.groups_made(), 1)  # the one the fixtures made

    def test_nobody_named_is_refused(self):
        before = self.groups_made()
        for members in ([], [self.lead.pk + 1000], [self.ops.pk]):
            answer = self.post("v1_group_create", self.ops, {"title": "x", "members": members})
            self.assertEqual((answer.status_code, _json(answer)["error"]), (400, "refused"), members)
        self.assertEqual(self.groups_made(), before)

    def test_somebody_who_is_gone_is_not_seated(self):
        User.objects.filter(pk=self.tr.pk).update(is_active=False)
        answer = self.create(self.lead, title="x", members=[self.tr])
        self.assertEqual(answer.status_code, 400)

    def test_only_those_who_may_open_a_group_do_and_a_refusal_makes_none(self):
        for user in self.everyone:
            before = self.groups_made()
            answer = self.create(user, title="a group", members=[self.ops2])
            self.assertEqual(answer.status_code == 200, user.can_create_team_group, user.username)
            self.assertEqual(self.groups_made(), before + (1 if answer.status_code == 200 else 0), user.username)
            if answer.status_code != 200:
                self.assertEqual((answer.status_code, _json(answer)["error"]), (403, "forbidden"), user.username)

    def test_it_reaches_no_client_and_returns_none(self):
        answer = self.create(self.ops, title="internal", members=[self.lead, self.tr])
        self.nothing_left_the_building()
        for text in (b"Zebulon", PHONE.encode()):
            self.assertNotIn(text, answer.content)
        room = ChatRoom.objects.get(pk=_json(answer)["room"])
        self.assertIsNone(room.client_id)
        self.assertFalse(room.reaches_client)

    def test_the_body_is_a_small_json_object(self):
        before = self.groups_made()
        ok = {"title": "x", "members": [self.lead.pk]}
        cases = {
            "a form": ("title=x&members=1", "application/x-www-form-urlencoded"),
            "a list": ("[]", "application/json"),
            "garbage": ("{", "application/json"),
            "members not a list": (json.dumps({**ok, "members": "1"}), "application/json"),
            "a member that is text": (json.dumps({**ok, "members": ["x"]}), "application/json"),
            "a member that is a float": (json.dumps({**ok, "members": [1.5]}), "application/json"),
            "a member that is a bool": (json.dumps({**ok, "members": [True]}), "application/json"),
            "a member too big": (json.dumps({**ok, "members": [2 ** 70]}), "application/json"),
            "too many members": (json.dumps({**ok, "members": list(range(1, 102))}), "application/json"),
            "a title that is a list": (json.dumps({**ok, "title": ["x"]}), "application/json"),
            "a title too long": (json.dumps({**ok, "title": "t" * 121}), "application/json"),
        }
        for name, (data, content_type) in cases.items():
            answer = self.post("v1_group_create", self.ops, raw=data, content_type=content_type)
            self.assertEqual((answer.status_code, _json(answer)["error"]), (400, "bad_request"), name)
        self.assertEqual(self.groups_made(), before)

    def test_a_session_a_post_and_the_csrf_token(self):
        url = reverse("dashboard:v1_group_create")
        self.assertEqual(DjangoClient().post(url, "{}", content_type="application/json").status_code, 401)
        self.assertEqual(self.browser(self.ops).get(url).status_code, 405)
        strict = DjangoClient(enforce_csrf_checks=True)
        strict.force_login(self.ops)
        before = self.groups_made()
        answer = strict.post(url, json.dumps({"title": "x", "members": [self.lead.pk]}), content_type="application/json")
        self.assertEqual(answer.status_code, 403)
        self.assertEqual(self.groups_made(), before)


class MembersTests(_Groups):
    def test_who_is_in_it_and_who_could_be_added_for_somebody_who_may(self):
        body = _json(self.members(self.lead, self.team))
        self.assertEqual({m["id"] for m in body["members"]}, {self.ops.pk, self.lead.pk, self.tr.pk})
        self.assertTrue(body["can_add"])
        offered = {p["id"] for p in body["addable"]}
        self.assertIn(self.hr.pk, offered)
        self.assertIn(self.sales.pk, offered)
        self.assertFalse(offered & {self.ops.pk, self.lead.pk, self.tr.pk})

    def test_somebody_who_may_not_add_is_given_the_members_and_nobody_to_add(self):
        body = _json(self.members(self.tr, self.team))
        self.assertEqual(len(body["members"]), 3)
        self.assertEqual((body["can_add"], body["addable"]), (False, []))

    def test_only_those_who_talk_to_clients_are_offered_for_a_room_that_reaches_a_client(self):
        AppSettings.objects.filter(pk=AppSettings.load().pk).update(group_creator_roles="operation")
        body = _json(self.members(self.ops, self.group))
        self.assertTrue(body["can_add"])
        roles = {p["role"] for p in body["addable"]}
        # The owner's rule: a client is never in a group with a team leader, a translator, HR, accounting or a reviewer.
        self.assertEqual(roles - {"operation", "sales", "admin"}, set())
        self.assertIn("sales", roles)
        offered = {p["id"] for p in body["addable"]}
        self.assertFalse(offered & {self.lead.pk, self.tr.pk, self.hr.pk, self.reviewer.pk, self.accounting.pk})

    def test_adding_to_a_client_room_is_behind_the_client_group_setting(self):
        AppSettings.objects.filter(pk=AppSettings.load().pk).update(group_creator_roles="")
        self.assertFalse(_json(self.members(self.ops, self.group))["can_add"])
        self.assertTrue(_json(self.members(self.admin, self.group))["can_add"])
        # The team leader seated in it by hand is not in a room with the client at all: nothing to ask.
        self.assertEqual(self.members(self.lead, self.group).status_code, 404)

    def test_a_private_line_has_two_people_and_nobody_to_add(self):
        for user in (self.ops, self.lead):
            body = _json(self.members(user, self.private))
            self.assertEqual({m["id"] for m in body["members"]}, {self.ops.pk, self.lead.pk})
            self.assertEqual((body["can_add"], body["addable"]), (False, []), user.username)

    def test_a_room_that_is_not_yours_is_not_there(self):
        for user in (self.sales, self.hr, self.tr2):
            self.assertEqual(self.members(user, self.team).status_code, 404, user.username)
        # Not even the admin reads a private line.
        self.assertEqual(self.members(self.admin, self.private).status_code, 404)
        self.assertEqual(self.members(self.admin, self.team).status_code, 200)

    def test_the_answer_carries_nothing_about_a_client(self):
        answer = self.members(self.admin, self.group)
        for text in (b"Zebulon", PHONE.encode(), b"zeb@example.test"):
            self.assertNotIn(text, answer.content)

    def test_a_session_and_a_get(self):
        url = reverse("dashboard:v1_group_members", args=[self.team.pk])
        self.assertEqual(DjangoClient().get(url).status_code, 401)
        self.assertEqual(self.browser(self.lead).post(url, "{}", content_type="application/json").status_code, 405)


class AddTests(_Groups):
    def test_a_leader_adds_somebody_to_a_work_group_and_they_are_told(self):
        answer = self.add(self.lead, self.team, [self.hr, self.lead2])
        body = _json(answer)
        self.assertEqual((answer.status_code, body["ok"], body["message"]), (200, True, ""))
        self.assertEqual(sorted(body["added"]), sorted([self.hr.short_name, self.lead2.short_name]))
        self.assertTrue(self.team.members.filter(pk=self.hr.pk).exists())
        self.assertTrue(Notification.objects.filter(user=self.hr, title_en="Added to a work group").exists())
        self.assertEqual(ChatMessage.objects.filter(room=self.team, is_system=True, body__contains=self.hr.short_name).count(), 1)
        self.nothing_left_the_building()

    def test_somebody_already_in_it_is_a_refusal_and_changes_nothing(self):
        answer = self.add(self.lead, self.team, [self.tr])
        self.assertEqual((answer.status_code, _json(answer)["error"]), (400, "refused"))
        self.assertTrue(_json(answer)["message"])
        self.assertEqual(self.team.members.count(), 3)

    def test_only_those_who_may_add_do_and_a_refusal_adds_nobody(self):
        for user in self.everyone:
            candidate = User.objects.create_user(f"guest_{user.pk}", password="pw", role=Role.HR)
            answer = self.add(user, self.team, [candidate])
            allowed = user.can_create_team_group and (user.is_admin_role or self.team.members.filter(pk=user.pk).exists())
            self.assertEqual(answer.status_code == 200, allowed, user.username)
            self.assertEqual(self.team.members.filter(pk=candidate.pk).exists(), allowed, user.username)

    def test_a_room_that_is_not_yours_is_a_404(self):
        for user in (self.sales, self.hr, self.tr2):
            answer = self.add(user, self.team, [self.hr])
            self.assertEqual(answer.status_code, 404, user.username)

    def test_a_private_line_takes_no_third_person(self):
        for user in (self.ops, self.lead, self.admin):
            answer = self.add(user, self.private, [self.hr])
            self.assertIn(answer.status_code, (400, 404), user.username)
        self.assertEqual(self.private.members.count(), 2)

    def test_no_translator_is_seated_in_a_room_that_reaches_a_client(self):
        AppSettings.objects.filter(pk=AppSettings.load().pk).update(group_creator_roles="operation")
        answer = self.add(self.ops, self.group, [self.tr2, self.sales2])
        body = _json(answer)
        # The one who may be added is; the translator is left out and the answer says so.
        self.assertEqual((answer.status_code, body["ok"]), (200, True))
        self.assertIn("المترجم", body["message"])
        self.assertFalse(self.group.members.filter(pk=self.tr2.pk).exists())
        self.assertTrue(self.group.members.filter(pk=self.sales2.pk).exists())
        self.assertEqual(self.add(self.ops, self.group, [self.tr2]).status_code, 400)

    def test_nobody_else_who_does_not_talk_to_clients_is_seated_there_either(self):
        # A client is never in a group with a team leader, HR, accounting or a reviewer, any more than with a translator.
        AppSettings.objects.filter(pk=AppSettings.load().pk).update(group_creator_roles="operation")
        for person in (self.lead2, self.hr, self.reviewer, self.accounting):
            answer = self.add(self.ops, self.group, [person])
            self.assertEqual((answer.status_code, _json(answer)["error"]), (400, "refused"), person.username)
            self.assertIn("Sales", _json(answer)["message"], person.username)
            self.assertFalse(self.group.members.filter(pk=person.pk).exists(), person.username)

    def test_somebody_who_may_not_see_the_task_is_not_seated_in_its_room(self):
        task = Task.objects.create(client=self.client_obj, title="A job", created_by=self.ops, team_lead=self.lead, translator=self.tr)
        room = ChatRoom.objects.create(kind=RoomKind.CLIENT, client=self.client_obj, task=task, title="Task room", created_by=self.ops)
        room.members.add(self.ops, self.lead)
        AppSettings.objects.filter(pk=AppSettings.load().pk).update(group_creator_roles="operation")
        answer = self.add(self.ops, room, [self.sales])
        body = _json(answer)
        self.assertFalse(room.members.filter(pk=self.sales.pk).exists())
        self.assertIn(self.sales.short_name, body["message"])

    def test_nobody_named_and_bad_bodies(self):
        self.assertEqual(
            (self.post("v1_group_add", self.lead, {"members": []}, args=[self.team.pk]).status_code,
             _json(self.post("v1_group_add", self.lead, {"members": []}, args=[self.team.pk]))["error"]),
            (400, "empty"),
        )
        for name, data, content_type in (
            ("a form", "members=1", "application/x-www-form-urlencoded"),
            ("a list", "[]", "application/json"),
            ("garbage", "{", "application/json"),
            ("members not a list", json.dumps({"members": 5}), "application/json"),
            ("a member that is text", json.dumps({"members": ["x"]}), "application/json"),
            ("too many", json.dumps({"members": list(range(1, 102))}), "application/json"),
        ):
            answer = self.post("v1_group_add", self.lead, raw=data, content_type=content_type, args=[self.team.pk])
            self.assertEqual((answer.status_code, _json(answer)["error"]), (400, "bad_request"), name)
        self.assertEqual(self.team.members.count(), 3)

    def test_a_session_a_post_and_the_csrf_token(self):
        url = reverse("dashboard:v1_group_add", args=[self.team.pk])
        self.assertEqual(DjangoClient().post(url, "{}", content_type="application/json").status_code, 401)
        self.assertEqual(self.browser(self.lead).get(url).status_code, 405)
        strict = DjangoClient(enforce_csrf_checks=True)
        strict.force_login(self.lead)
        answer = strict.post(url, json.dumps({"members": [self.hr.pk]}), content_type="application/json")
        self.assertEqual(answer.status_code, 403)
        self.assertFalse(self.team.members.filter(pk=self.hr.pk).exists())
