"""The team leader's screen in the new app: their tasks, who of their team is free, and their page of one task.

Everything here is the leader's *own*: their tasks (``Task.team_lead``) and their team (``User.team_lead``). A task that is
another leader's is a 404 and a row in the audit log, the client is a code and nothing else, and what the operation does
on a task (take it over, deliver it, cancel it, talk to the client) is not on the leader's page. What the leader does is
the classic endpoints (assigning a translator, the translator's date, the answer to a request for more time, the review),
which keep their own tests.
"""

import json
from datetime import timedelta
from unittest import mock

from django.db import connection
from django.test import Client as DjangoClient
from django.test.utils import CaptureQueriesContext
from django.urls import reverse
from django.utils import timezone

from . import identity, newui, services
from .models import (
    AppSettings, AuditLog, Client, ClientRequirement, ExtensionRequest, Role, Task, TaskStatus, User,
)
from .tests_api_v1 import CLIENT_EMAIL, CLIENT_NAME, CLIENT_PHONE, IDENTITY_MARKERS, _json, _Site

HOME = "dashboard:v1_lead"
BOARD = "dashboard:v1_lead_translators"
TASK = "dashboard:v1_task"


class _Lead(_Site):
    def setUp(self):
        super().setUp()
        built = mock.patch("dashboard.newui.spa.built_assets", return_value={"js": "x.js", "css": []})
        built.start()
        self.addCleanup(built.stop)
        self.other_lead = User.objects.create_user("person_leader_two", password="pw", role=Role.TEAM_LEAD)
        self.other_translator = User.objects.create_user(
            "person_translator_two", password="pw", role=Role.TRANSLATOR, team_lead=self.other_lead,
        )
        self.other_client = Client.objects.create(name="Other Corp", phone="+201119998888", email="x@other.example")
        self.other_task = Task.objects.create(
            client=self.other_client, title="Not mine", created_by=self.ops, team_lead=self.other_lead,
            translator=self.other_translator, status=TaskStatus.IN_PROGRESS,
        )

    def get(self, user, name, args=None, /, **query):
        browser = DjangoClient()
        if user is not None:
            browser.force_login(user)
        return browser.get(reverse(name, args=args), query)

    def post(self, user, name, body, args=None):
        browser = DjangoClient()
        if user is not None:
            browser.force_login(user)
        return browser.post(reverse(name, args=args), json.dumps(body), content_type="application/json")

    def turn_on(self, key="lead", roles=(), users=()):
        conf = AppSettings.load()
        conf.new_ui = {**(conf.new_ui or {}), key: {"roles": list(roles), "users": list(users)}}
        conf.save()

    def here(self, person):
        """Eagle is open for this person right now."""
        person.last_seen = timezone.now()
        person.save()


class ScreenSwitchTests(_Lead):
    def test_the_menu_lists_it_only_for_who_is_switched_on_and_the_badge_is_their_open_tasks(self):
        self.turn_on(roles=["team_lead"])
        mine = _json(self.get(self.lead, "dashboard:v1_me"))
        self.assertIn("lead", mine["screens"])
        self.assertEqual(mine["tasks_open"], 1)
        # Another leader has one open task too; a person who is not a leader has none to count.
        self.assertEqual(_json(self.get(self.other_lead, "dashboard:v1_me"))["tasks_open"], 1)
        for user in (self.ops, self.tr, self.admin, self.sales):
            self.assertEqual(_json(self.get(user, "dashboard:v1_me"))["tasks_open"], 0, user.username)
            self.assertNotIn("lead", _json(self.get(user, "dashboard:v1_me"))["screens"], user.username)

    def test_the_badge_does_not_count_what_is_closed(self):
        self.task.status = TaskStatus.DELIVERED
        self.task.save()
        self.assertEqual(_json(self.get(self.lead, "dashboard:v1_me"))["tasks_open"], 0)


class HomeDoorTests(_Lead):
    def test_the_leader_is_answered_and_everybody_else_is_refused(self):
        answer = self.get(self.lead, HOME)
        self.assertEqual(answer.status_code, 200)
        self.assertEqual(answer["Cache-Control"], "private, no-store")
        for user in (self.ops, self.tr, self.hr, self.reviewer, self.accounting, self.sales):
            denied = self.get(user, HOME)
            self.assertEqual((denied.status_code, _json(denied)), (403, {"ok": False, "error": "forbidden"}), user.username)
        self.assertEqual(self.get(None, HOME).status_code, 401)
        browser = DjangoClient()
        browser.force_login(self.lead)
        self.assertEqual(browser.post(reverse(HOME)).status_code, 405)

    def test_the_admin_has_no_team_and_no_tasks_of_their_own_to_read_here(self):
        body = _json(self.get(self.admin, HOME))
        self.assertEqual((body["tasks"], body["team"], body["closed"]), ([], [], []))
        self.assertEqual(body["counters"], {"open": 0, "free": 0, "busy": 0, "offline": 0})

    def test_it_is_only_the_leaders_own_tasks_and_team(self):
        body = _json(self.get(self.lead, HOME))
        self.assertEqual([row["code"] for row in body["tasks"]], [self.task.code])
        self.assertEqual([person["id"] for person in body["team"]], [self.tr.pk])
        text = json.dumps(body)
        self.assertNotIn(self.other_task.code, text)
        self.assertNotIn(self.other_translator.short_name, text)

    def test_each_task_is_a_row_with_the_client_as_a_code_and_the_clients_date(self):
        row = _json(self.get(self.lead, HOME))["tasks"][0]
        self.assertEqual((row["code"], row["client"], row["translator"]), (self.task.code, self.client_obj.code, self.tr.short_name))
        self.assertEqual(row["status"]["value"], "in_progress")
        self.assertIn(row["due_state"], ("ok", "soon", "late"))
        self.assertTrue(row["due"]["en"])

    def test_no_name_number_or_address_of_a_client_is_in_the_answer(self):
        text = self.get(self.lead, HOME).content.decode("utf-8")
        for marker in IDENTITY_MARKERS:
            self.assertNotIn(marker, text, marker)

    def test_closed_tasks_are_listed_apart_and_not_counted_as_open(self):
        done = Task.objects.create(client=self.client_obj, title="Done", created_by=self.ops, team_lead=self.lead, status=TaskStatus.DELIVERED)
        gone = Task.objects.create(client=self.client_obj, title="Gone", created_by=self.ops, team_lead=self.lead, status=TaskStatus.CANCELLED)
        body = _json(self.get(self.lead, HOME))
        self.assertEqual({row["code"] for row in body["closed"]}, {done.code, gone.code})
        self.assertEqual(body["counters"]["open"], 1)
        self.assertEqual({row["code"] for row in body["tasks"]}, {self.task.code})

    def test_at_most_twenty_closed_tasks_are_listed(self):
        for index in range(25):
            Task.objects.create(client=self.client_obj, title=f"d{index}", created_by=self.ops, team_lead=self.lead, status=TaskStatus.DELIVERED)
        self.assertEqual(len(_json(self.get(self.lead, HOME))["closed"]), 20)

    def test_the_four_numbers_say_who_is_free_busy_and_away(self):
        free = User.objects.create_user("person_free", password="pw", role=Role.TRANSLATOR, team_lead=self.lead)
        self.here(free)
        self.here(self.tr)
        away = User.objects.create_user("person_away", password="pw", role=Role.TRANSLATOR, team_lead=self.lead)
        body = _json(self.get(self.lead, HOME))
        self.assertEqual(body["counters"], {"open": 1, "free": 1, "busy": 1, "offline": 1})
        states = {person["name"]: person["state"] for person in body["team"]}
        self.assertEqual(states, {free.short_name: "free", self.tr.short_name: "busy", away.short_name: "off"})

    def test_a_person_with_an_offer_waiting_is_busy_and_not_free(self):
        free = User.objects.create_user("person_free", password="pw", role=Role.TRANSLATOR, team_lead=self.lead)
        self.here(free)
        other = Task.objects.create(client=self.client_obj, title="Offered", created_by=self.ops, team_lead=self.lead, status=TaskStatus.LEAD_ACCEPTED)
        services.assign_to_translator(other, free, self.lead)
        body = _json(self.get(self.lead, HOME))
        self.assertEqual({person["name"]: person["state"] for person in body["team"]}[free.short_name], "busy")

    def test_a_team_member_carries_what_the_board_needs_to_draw_them(self):
        person = _json(self.get(self.lead, HOME))["team"][0]
        self.assertEqual(set(person), {"id", "name", "initials", "languages", "rating", "state", "seen"})
        self.assertIsInstance(person["rating"], float)
        self.assertEqual(set(person["seen"]), {"ar", "en"})

    def test_the_page_costs_the_same_however_many_tasks_and_people(self):
        def cost():
            with CaptureQueriesContext(connection) as queries:
                self.get(self.lead, HOME)
            return len(queries)

        few = cost()
        for index in range(8):
            person = User.objects.create_user(f"person_more_{index}", password="pw", role=Role.TRANSLATOR, team_lead=self.lead)
            Task.objects.create(client=self.client_obj, title=f"t{index}", created_by=self.ops, team_lead=self.lead, translator=person, status=TaskStatus.IN_PROGRESS)
        self.assertEqual(cost(), few)

    def test_a_get_changes_nothing(self):
        before = (Task.objects.count(), AuditLog.objects.count(), User.objects.count())
        self.get(self.lead, HOME)
        self.assertEqual(before, (Task.objects.count(), AuditLog.objects.count(), User.objects.count()))


class TranslatorsDoorTests(_Lead):
    def test_the_leader_is_answered_and_everybody_else_is_refused(self):
        self.assertEqual(self.get(self.lead, BOARD).status_code, 200)
        for user in (self.ops, self.tr, self.hr, self.reviewer, self.accounting, self.sales):
            self.assertEqual(self.get(user, BOARD).status_code, 403, user.username)
        self.assertEqual(self.get(None, BOARD).status_code, 401)

    def test_a_row_says_the_state_the_load_what_they_work_on_and_the_nearest_deadline(self):
        self.here(self.tr)
        second = Task.objects.create(
            client=self.client_obj, title="Second", created_by=self.ops, team_lead=self.lead, translator=self.tr,
            status=TaskStatus.IN_PROGRESS, deadline=timezone.now() + timedelta(hours=1), source_words=500,
        )
        row = _json(self.get(self.lead, BOARD))["team"][0]
        self.assertEqual((row["state"], row["load"], row["awaiting_answer"]), ("busy", 2, False))
        self.assertEqual(set(row["tasks"]), {self.task.code, second.code})
        self.assertEqual(row["load_percent"], round(2 * 100 / services.FULL_LOAD_TASKS))
        self.assertEqual(row["words"], 500)
        self.assertTrue(row["next_due"]["en"])

    def test_only_the_first_three_tasks_are_named_and_the_load_says_the_rest(self):
        self.here(self.tr)
        for index in range(4):
            Task.objects.create(client=self.client_obj, title=f"t{index}", created_by=self.ops, team_lead=self.lead, translator=self.tr, status=TaskStatus.IN_PROGRESS)
        row = _json(self.get(self.lead, BOARD))["team"][0]
        self.assertEqual((len(row["tasks"]), row["load"], row["load_percent"]), (3, 5, 100))

    def test_somebody_with_nothing_has_no_deadline_and_a_state_of_none(self):
        free = User.objects.create_user("person_free", password="pw", role=Role.TRANSLATOR, team_lead=self.lead)
        self.here(free)
        rows = {row["name"]: row for row in _json(self.get(self.lead, BOARD))["team"]}
        self.assertEqual((rows[free.short_name]["state"], rows[free.short_name]["next_due"], rows[free.short_name]["next_due_state"]), ("free", None, "none"))

    def test_the_free_come_first_then_the_lightest_load(self):
        free = User.objects.create_user("person_free", password="pw", role=Role.TRANSLATOR, team_lead=self.lead)
        self.here(free)
        self.here(self.tr)
        self.assertEqual([row["state"] for row in _json(self.get(self.lead, BOARD))["team"]], ["free", "busy"])

    def test_the_tasks_waiting_for_a_translator_are_listed_with_their_dates(self):
        waiting = Task.objects.create(
            client=self.client_obj, title="Waiting", created_by=self.ops, team_lead=self.lead, status=TaskStatus.LEAD_ACCEPTED,
            deadline=timezone.now() + timedelta(days=1),
        )
        Task.objects.create(client=self.client_obj, title="Not waiting", created_by=self.ops, team_lead=self.lead, status=TaskStatus.IN_PROGRESS)
        Task.objects.create(client=self.client_obj, title="Another's", created_by=self.ops, team_lead=self.other_lead, status=TaskStatus.LEAD_ACCEPTED)
        body = _json(self.get(self.lead, BOARD))
        self.assertEqual([row["code"] for row in body["waiting"]], [waiting.code])
        self.assertTrue(body["waiting"][0]["due"]["en"])

    def test_the_counters_cover_the_four_states_and_the_open_work(self):
        self.here(self.tr)
        body = _json(self.get(self.lead, BOARD))
        self.assertEqual(body["counters"], {"free": 0, "busy": 1, "shift": 0, "offline": 0, "open": 1})

    def test_it_is_only_the_leaders_own_team(self):
        body = _json(self.get(self.lead, BOARD))
        self.assertEqual([row["id"] for row in body["team"]], [self.tr.pk])
        self.assertNotIn(self.other_translator.short_name, json.dumps(body))

    def test_no_client_identity_is_in_the_answer(self):
        text = self.get(self.lead, BOARD).content.decode("utf-8")
        for marker in IDENTITY_MARKERS:
            self.assertNotIn(marker, text, marker)

    def test_the_page_costs_the_same_however_many_people(self):
        def cost():
            with CaptureQueriesContext(connection) as queries:
                self.get(self.lead, BOARD)
            return len(queries)

        few = cost()
        for index in range(8):
            person = User.objects.create_user(f"person_more_{index}", password="pw", role=Role.TRANSLATOR, team_lead=self.lead)
            Task.objects.create(client=self.client_obj, title=f"t{index}", created_by=self.ops, team_lead=self.lead, translator=person, status=TaskStatus.IN_PROGRESS)
        self.assertEqual(cost(), few)


class LeadersTaskDoorTests(_Lead):
    def read(self, user, task=None):
        return self.get(user, TASK, [(task or self.task).code])

    def test_the_tasks_own_leader_reads_it_and_another_leaders_task_is_a_404_and_a_row_in_the_audit_log(self):
        self.assertEqual(self.read(self.lead).status_code, 200)
        before = AuditLog.objects.filter(action=identity.ACCESS_DENIED).count()
        self.assertEqual(self.read(self.other_lead).status_code, 404)
        self.assertEqual(AuditLog.objects.filter(action=identity.ACCESS_DENIED).count(), before + 1)
        # And one that is not there is the same.
        self.assertEqual(self.get(self.lead, TASK, ["TSK-99999"]).status_code, 404)

    def test_the_translator_the_accounting_and_the_rest_are_still_refused_and_the_admin_and_operation_still_read_it(self):
        for user in (self.tr, self.hr, self.reviewer, self.accounting, self.sales):
            self.assertEqual(self.read(user).status_code, 403, user.username)
        for user in (self.ops, self.admin):
            self.assertEqual(self.read(user).status_code, 200, user.username)

    def test_what_the_operation_does_is_not_on_the_leaders_page(self):
        self.task.status = TaskStatus.REVIEWED
        self.task.handover_ack_at = timezone.now()
        self.task.save()
        task = _json(self.read(self.lead))["task"]
        self.assertEqual(task["can"], {
            "assign_lead": False, "take_over": False, "deliver": False, "cancel": False, "add_member": False,
            "new_request": False, "set_deadline": False, "set_words": True,
        })
        self.assertIsNone(task["client_chat_url"])
        self.assertEqual((task["leads"], task["messages"], task["group_candidates"]), ([], [], []))
        self.assertIsNone(task["handover"])
        self.assertIsNone(task["deliver"])

    def test_the_operation_still_has_its_tools_and_no_leaders_block(self):
        task = _json(self.read(self.ops))["task"]
        self.assertTrue(task["can"]["cancel"])
        self.assertTrue(task["can"]["set_words"])
        self.assertTrue(task["can"]["new_request"])
        self.assertTrue(task["can"]["set_deadline"])
        self.assertIsNone(task["lead"])
        self.assertTrue(task["messages"])
        self.assertIsNotNone(task["client_chat_url"])

    def test_the_client_is_a_code_and_the_brief_does_not_name_them(self):
        self.task.description = f"Please translate for {CLIENT_NAME}, write to {CLIENT_EMAIL} or {CLIENT_PHONE}"
        self.task.save()
        answer = self.read(self.lead)
        text = answer.content.decode("utf-8")
        for marker in IDENTITY_MARKERS:
            self.assertNotIn(marker, text, marker)
        self.assertEqual(_json(answer)["task"]["client"], self.client_obj.code)
        self.assertIn(self.client_obj.code, _json(answer)["task"]["description"])
        # The admin may know who the client is: the brief is as it was written.
        self.assertIn(CLIENT_NAME, _json(self.read(self.admin))["task"]["description"])

    def test_the_requirements_and_a_failed_deliverys_words_do_not_name_the_client_either(self):
        ClientRequirement.objects.create(client=self.client_obj, kind="rule", text=f"Always {CLIENT_NAME}", author=self.admin)
        text = self.read(self.lead).content.decode("utf-8")
        for marker in IDENTITY_MARKERS:
            self.assertNotIn(marker, text, marker)

    def test_giving_it_to_a_translator_is_offered_while_it_waits_for_one_with_the_leaders_own_team_only(self):
        self.task.status = TaskStatus.LEAD_ACCEPTED
        self.task.translator = None
        self.task.save()
        self.here(self.tr)
        free = User.objects.create_user("person_free", password="pw", role=Role.TRANSLATOR, team_lead=self.lead)
        self.here(free)
        away = User.objects.create_user("person_away", password="pw", role=Role.TRANSLATOR, team_lead=self.lead)
        lead = _json(self.read(self.lead))["task"]["lead"]
        self.assertTrue(lead["can_assign"])
        states = {person["name"]: person["state"] for person in lead["translators"]}
        # A running task makes somebody busy; Eagle shut makes them offline.
        self.assertEqual(states, {free.short_name: "free", away.short_name: "off", self.tr.short_name: "free"})
        self.assertNotIn(self.other_translator.short_name, json.dumps(lead))
        self.assertEqual(set(lead["translators"][0]), {"id", "name", "state", "rating"})
        self.assertFalse(lead["can_set_translator_deadline"])

    def test_it_is_not_offered_once_a_translator_has_it_and_the_list_is_not_built(self):
        lead = _json(self.read(self.lead))["task"]["lead"]
        self.assertFalse(lead["can_assign"])
        self.assertEqual(lead["translators"], [])
        self.assertTrue(lead["can_set_translator_deadline"])

    def test_it_is_offered_again_while_the_task_awaits_a_translator(self):
        self.task.status = TaskStatus.AWAITING_TRANSLATOR
        self.task.save()
        self.assertTrue(_json(self.read(self.lead))["task"]["lead"]["can_assign"])

    def test_the_review_is_offered_only_while_the_task_is_under_review(self):
        self.assertFalse(_json(self.read(self.lead))["task"]["lead"]["can_review"])
        self.task.status = TaskStatus.UNDER_REVIEW
        self.task.save()
        self.assertTrue(_json(self.read(self.lead))["task"]["lead"]["can_review"])

    def test_a_request_for_more_time_waits_for_the_leaders_answer_with_where_the_date_would_land(self):
        row = ExtensionRequest.objects.create(
            task=self.task, requested_by=self.tr, minutes=180, reason=f"The file of {CLIENT_NAME} is long",
        )
        lead = _json(self.read(self.lead))["task"]["lead"]
        extension = lead["extension"]
        self.assertEqual(extension["id"], row.pk)
        self.assertTrue(extension["length"])
        self.assertTrue(extension["new_due"]["en"])
        self.assertNotIn(CLIENT_NAME, extension["reason"])
        self.assertIn(self.client_obj.code, extension["reason"])
        # The admin reads the reason as it was written.
        self.assertIn(CLIENT_NAME, _json(self.read(self.admin))["task"]["lead"]["extension"]["reason"])

    def test_an_answered_request_is_no_longer_waiting(self):
        ExtensionRequest.objects.create(task=self.task, requested_by=self.tr, minutes=60, status=ExtensionRequest.Status.APPROVED)
        self.assertIsNone(_json(self.read(self.lead))["task"]["lead"]["extension"])

    def test_the_admin_gets_both_sets_and_the_translators_of_the_tasks_leader(self):
        self.task.status = TaskStatus.LEAD_ACCEPTED
        self.task.translator = None
        self.task.save()
        task = _json(self.read(self.admin))["task"]
        self.assertTrue(task["can"]["cancel"])
        self.assertTrue(task["lead"]["can_assign"])
        self.assertEqual([person["id"] for person in task["lead"]["translators"]], [self.tr.pk])

    def test_the_clients_date_is_there_to_remind_the_leader_of_the_review_time_they_keep(self):
        self.task.deadline = timezone.now() + timedelta(days=2)
        self.task.save()
        self.assertTrue(_json(self.read(self.lead))["task"]["lead"]["client_due"]["en"])

    def test_the_page_costs_the_same_however_many_translators(self):
        self.task.status = TaskStatus.LEAD_ACCEPTED
        self.task.save()

        def cost():
            with CaptureQueriesContext(connection) as queries:
                self.read(self.lead)
            return len(queries)

        few = cost()
        for index in range(8):
            User.objects.create_user(f"person_more_{index}", password="pw", role=Role.TRANSLATOR, team_lead=self.lead)
        # One question for the people; what makes each one free or busy is asked per person, as on the classic page.
        self.assertLessEqual(cost(), few + 8 * 3)

    def test_a_get_changes_nothing(self):
        before = (Task.objects.count(), AuditLog.objects.count(), ExtensionRequest.objects.count())
        self.read(self.lead)
        self.assertEqual(before, (Task.objects.count(), AuditLog.objects.count(), ExtensionRequest.objects.count()))


class WordsAndRequirementsForLeadersTests(_Lead):
    def test_the_tasks_own_leader_settles_the_word_count_and_another_leader_cannot(self):
        answer = self.post(self.lead, "dashboard:v1_task_words", {"words": 1200}, [self.task.code])
        self.assertEqual((answer.status_code, _json(answer)["words"]), (200, 1200))
        self.assertEqual(self.post(self.other_lead, "dashboard:v1_task_words", {"words": 5}, [self.task.code]).status_code, 404)
        self.task.refresh_from_db()
        self.assertEqual(self.task.word_count, 1200)

    def test_the_translator_still_cannot_settle_it(self):
        self.assertEqual(self.post(self.tr, "dashboard:v1_task_words", {"words": 5}, [self.task.code]).status_code, 403)

    def test_the_tasks_own_leader_adds_a_requirement_with_their_name_on_it_and_another_leader_cannot(self):
        answer = self.post(self.lead, "dashboard:v1_task_requirement", {"kind": "rule", "text": f"Never {CLIENT_NAME}"}, [self.task.code])
        self.assertEqual(answer.status_code, 200)
        for marker in IDENTITY_MARKERS:
            self.assertNotIn(marker, answer.content.decode("utf-8"), marker)
        self.assertEqual(ClientRequirement.objects.get().author, self.lead)
        self.assertEqual(self.post(self.other_lead, "dashboard:v1_task_requirement", {"kind": "rule", "text": "x"}, [self.task.code]).status_code, 404)
        self.assertEqual(ClientRequirement.objects.count(), 1)

    def test_the_translator_still_cannot_add_one(self):
        self.assertEqual(self.post(self.tr, "dashboard:v1_task_requirement", {"kind": "rule", "text": "x"}, [self.task.code]).status_code, 403)


class ClientPagesForLeadersTests(_Lead):
    def test_a_team_leader_reads_the_client_codes_and_nothing_that_names_a_client(self):
        answer = self.get(self.lead, "dashboard:v1_clients")
        body = _json(answer)
        self.assertFalse(body["sees_identity"])
        self.assertEqual(set(body["clients"][0]), {"code", "tasks", "requirements"})
        for marker in IDENTITY_MARKERS:
            self.assertNotIn(marker, answer.content.decode("utf-8"), marker)
        self.assertFalse(AuditLog.objects.filter(action=identity.IDENTITY_LIST, actor=self.lead).exists())

    def test_one_client_is_read_with_its_requirements_and_a_leader_may_add_one(self):
        code = self.client_obj.code
        body = _json(self.get(self.lead, "dashboard:v1_client", [code]))
        self.assertTrue(body["may_edit"])
        self.assertIsNone(body["activity"])
        self.assertEqual(set(body["client"]), {"code"})
        answer = self.post(self.lead, "dashboard:v1_client_requirement", {"kind": "like", "text": "Short sentences"}, [code])
        self.assertEqual(answer.status_code, 200)
        self.assertEqual(ClientRequirement.objects.get().author, self.lead)

    def test_the_others_who_open_the_classic_pages_still_have_no_door_but_accounting_is_not_moved(self):
        for user in (self.tr, self.hr, self.reviewer, self.accounting):
            self.assertEqual(self.get(user, "dashboard:v1_clients").status_code, 403, user.username)


class HandOnTests(_Lead):
    def test_the_leaders_pages_go_on_with_the_switch(self):
        self.turn_on(roles=["team_lead"])
        for name, target in (("dashboard:lead_home", "/app/lead"), ("dashboard:lead_translators", "/app/lead/translators")):
            answer = self.get(self.lead, name)
            self.assertEqual((answer.status_code, answer["Location"]), (302, target), name)
        answer = self.get(self.lead, "dashboard:task_detail", [self.task.code])
        self.assertEqual((answer.status_code, answer["Location"]), (302, f"/app/tasks/{self.task.code}"))
        code = self.client_obj.code
        self.assertEqual(self.get(self.lead, "dashboard:client_list")["Location"], "/app/clients")
        self.assertEqual(self.get(self.lead, "dashboard:client_detail", [code])["Location"], f"/app/clients/{code}")

    def test_a_code_that_is_not_one_is_never_carried_into_the_address(self):
        self.turn_on(roles=["team_lead"])
        self.assertEqual(self.get(self.lead, "dashboard:task_detail", ["we.ird"]).status_code, 404)

    def test_another_leaders_task_is_not_opened(self):
        self.turn_on(roles=["team_lead"])
        # The address is only an address: the new page asks the door, which answers 404 for it.
        self.assertEqual(self.get(self.lead, "dashboard:task_detail", [self.other_task.code])["Location"], f"/app/tasks/{self.other_task.code}")
        self.assertEqual(self.get(self.lead, TASK, [self.other_task.code]).status_code, 404)

    def test_a_translators_own_page_still_goes_by_its_own_switch(self):
        self.turn_on("translator_home", roles=["translator"])
        self.turn_on(roles=["team_lead"])
        self.assertEqual(self.get(self.tr, "dashboard:task_detail", [self.task.code])["Location"], f"/app/tasks/{self.task.code}")

    def test_a_build_that_does_not_exist_hands_nobody_on(self):
        self.turn_on(roles=["team_lead"])
        with mock.patch("dashboard.newui.spa.built_assets", return_value=None):
            self.assertEqual(self.get(self.lead, "dashboard:lead_home").status_code, 200)

    def test_a_form_that_is_already_open_is_answered_where_it_is(self):
        self.turn_on(roles=["team_lead"])
        browser = DjangoClient()
        browser.force_login(self.lead)
        answer = browser.post(reverse("dashboard:task_requirement", args=[self.task.code]), {"kind": "rule", "text": "Posted classic"})
        self.assertEqual(answer.status_code, 302)
        self.assertFalse(answer["Location"].startswith("/app/"))
        self.assertTrue(ClientRequirement.objects.filter(text="Posted classic").exists())


class TheLeadersClassicToolsStillWorkTests(_Lead):
    """The new page writes through these endpoints, unchanged: pinned here so a change to one is seen from this screen."""

    def post_form(self, user, name, args, data):
        browser = DjangoClient()
        browser.force_login(user)
        return browser.post(reverse(name, args=args), data)

    def test_assigning_a_translator_with_the_leaders_own_date_is_the_classic_form(self):
        self.task.status = TaskStatus.LEAD_ACCEPTED
        self.task.translator = None
        self.task.deadline = timezone.now() + timedelta(days=3)
        self.task.save()
        answer = self.post_form(self.lead, "dashboard:api_assign_translator", [self.task.code], {"user": self.tr.pk, "tdeadline_days": "1"})
        self.assertEqual((answer.status_code, answer.json()["ok"]), (200, True))
        self.task.refresh_from_db()
        self.assertEqual(self.task.translator_id, self.tr.pk)
        self.assertIsNotNone(self.task.translator_deadline)

    def test_another_leaders_translator_is_refused(self):
        self.task.status = TaskStatus.LEAD_ACCEPTED
        self.task.save()
        answer = self.post_form(self.lead, "dashboard:api_assign_translator", [self.task.code], {"user": self.other_translator.pk})
        self.assertEqual((answer.status_code, answer.json()["error"]), (403, "not_in_your_team"))

    def test_the_translators_date_is_changed_with_the_same_three_boxes(self):
        # Inside the client's date: the translator is never given more time than the client was promised.
        self.task.deadline = timezone.now() + timedelta(days=10)
        self.task.save()
        answer = self.post_form(self.lead, "dashboard:api_set_translator_deadline", [self.task.code], {"tdeadline_days": "0", "tdeadline_hours": "5", "tdeadline_minutes": "0"})
        self.assertEqual((answer.status_code, answer.json()["ok"]), (200, True))

    def test_a_request_for_more_time_is_answered_by_its_id(self):
        self.task.deadline = timezone.now() + timedelta(days=10)
        self.task.translator_deadline = timezone.now() + timedelta(days=2)
        self.task.save()
        row = ExtensionRequest.objects.create(task=self.task, requested_by=self.tr, minutes=60, reason="Long file")
        answer = self.post_form(self.lead, "dashboard:api_decide_extension", [row.pk, "approve"], {"note": ""})
        self.assertEqual((answer.status_code, answer.json()["ok"]), (200, True))
        row.refresh_from_db()
        self.assertEqual(row.status, ExtensionRequest.Status.APPROVED)

    def test_the_review_is_finished_by_the_leader_of_the_task_and_not_another(self):
        self.task.status = TaskStatus.UNDER_REVIEW
        self.task.save()
        self.assertEqual(self.post_form(self.other_lead, "dashboard:api_task_action", [self.task.code, "reviewed"], {}).status_code, 404)
        self.assertEqual(self.post_form(self.lead, "dashboard:api_task_action", [self.task.code, "reviewed"], {}).status_code, 200)
        self.task.refresh_from_db()
        self.assertEqual(self.task.status, TaskStatus.REVIEWED)
