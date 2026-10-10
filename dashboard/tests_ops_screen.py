"""The operation's screen in the new app: the task list, the team board (and, below them, the rest of the screen).

The doors answer to the operation and the admin, as the classic pages do, and show the same people the same
things: the client is a code for the operation and the name only for whoever may know it, the date is the
client's, and a GET changes nothing. What is pinned for each page is what it may *read*; the writes are the classic
endpoints, which keep their own tests.
"""

import json
from datetime import timedelta

from django.db import connection
from django.test import Client as DjangoClient
from django.test.utils import CaptureQueriesContext
from django.urls import reverse
from django.utils import timezone

from . import services
from .models import AuditLog, Role, Task, TaskStatus, User
from .tests_api_v1 import CLIENT_EMAIL, CLIENT_NAME, CLIENT_PHONE, IDENTITY_MARKERS, _json, _Site
from .tests_translator_home import _make_task


class _Ops(_Site):
    def door(self, user, name, args=None, /, **query):
        browser = DjangoClient()
        if user is not None:
            browser.force_login(user)
        return browser.get(reverse(name, args=args), query)

    def classic(self, user, name, args=None, /, **query):
        browser = DjangoClient()
        browser.force_login(user)
        return browser.get(reverse(name, args=args), {"classic": 1, **query})

    def refused_for_everybody_else(self, name, args=None):
        for user in (self.lead, self.tr, self.hr, self.reviewer, self.accounting, self.sales):
            answer = self.door(user, name, args)
            self.assertEqual((answer.status_code, _json(answer)), (403, {"ok": False, "error": "forbidden"}), user.username)
        self.assertEqual(self.door(None, name, args).status_code, 401)

    def post_refused(self, name, args=None):
        browser = DjangoClient()
        browser.force_login(self.ops)
        self.assertEqual(browser.post(reverse(name, args=args)).status_code, 405)


# ---------------------------------------------------------------------------------------------------------------------
# The task list
# ---------------------------------------------------------------------------------------------------------------------

class TaskListTests(_Ops):
    def test_the_operation_and_the_admin_are_answered_everybody_else_is_refused(self):
        for user in (self.ops, self.admin):
            self.assertEqual(self.door(user, "dashboard:v1_tasks").status_code, 200, user.username)
        self.refused_for_everybody_else("dashboard:v1_tasks")
        self.post_refused("dashboard:v1_tasks")
        self.assertEqual(self.door(self.ops, "dashboard:v1_tasks")["Cache-Control"], "private, no-store")

    def test_a_refusal_is_written_to_the_audit_log(self):
        before = AuditLog.objects.filter(action="security.denied", actor=self.tr).count()
        self.door(self.tr, "dashboard:v1_tasks")
        self.assertEqual(AuditLog.objects.filter(action="security.denied", actor=self.tr).count(), before + 1)

    def test_a_row_is_what_the_classic_table_shows(self):
        body = _json(self.door(self.ops, "dashboard:v1_tasks"))
        (row,) = [t for t in body["tasks"] if t["code"] == self.task.code]
        self.assertEqual((row["title"], row["client"]), ("Doc", self.client_obj.code))
        self.assertEqual(row["status"]["value"], self.task.status)
        self.assertTrue(row["status"]["ar"] and row["status"]["en"] and row["status"]["tone"])
        self.assertEqual((row["team_lead"], row["translator"]), (self.lead.short_name, self.tr.short_name))
        self.assertTrue(row["priority"]["ar"] and row["priority"]["en"])
        self.assertTrue(row["due"]["ar"] and row["due"]["en"])
        self.assertIn(row["due_state"], ("ok", "soon"))

    def test_nobody_assigned_yet_is_null_and_no_deadline_is_null(self):
        task = services.create_task(client=self.client_obj, title="Fresh", created_by=self.ops, deadline=None)
        row = next(t for t in _json(self.door(self.ops, "dashboard:v1_tasks"))["tasks"] if t["code"] == task.code)
        self.assertEqual((row["team_lead"], row["translator"], row["due"], row["due_state"]), (None, None, None, "none"))

    def test_the_date_is_the_clients_never_the_translators(self):
        mine = timezone.now() + timedelta(hours=2)
        clients = timezone.now() + timedelta(days=9)
        Task.objects.filter(pk=self.task.pk).update(translator_deadline=mine, deadline=clients)
        row = next(t for t in _json(self.door(self.ops, "dashboard:v1_tasks"))["tasks"] if t["code"] == self.task.code)
        self.assertIn(timezone.localtime(clients).strftime("%m-%d"), row["due"]["en"])

    def test_the_operation_reads_a_code_and_the_admin_may_read_the_name(self):
        raw = self.door(self.ops, "dashboard:v1_tasks").content.decode("utf-8")
        for marker in IDENTITY_MARKERS + (CLIENT_NAME, CLIENT_PHONE, CLIENT_EMAIL):
            self.assertNotIn(marker, raw, marker)
        admin = _json(self.door(self.admin, "dashboard:v1_tasks"))
        row = next(t for t in admin["tasks"] if t["code"] == self.task.code)
        self.assertIn(CLIENT_NAME, row["client"])

    def test_the_counters_are_over_every_task_and_not_over_the_page(self):
        _make_task(self, status=TaskStatus.NEW, title="n1")
        _make_task(self, status=TaskStatus.UNDER_REVIEW, title="r1")
        _make_task(self, status=TaskStatus.REVIEWED, title="d1")
        _make_task(self, status=TaskStatus.REVIEWED, title="d2")
        _make_task(self, status=TaskStatus.DELIVERED, title="gone")
        everything = _json(self.door(self.ops, "dashboard:v1_tasks"))["counters"]
        narrowed = _json(self.door(self.ops, "dashboard:v1_tasks", status="delivered"))["counters"]
        self.assertEqual(everything, narrowed)
        self.assertEqual(everything["new"], 1)
        self.assertEqual(everything["review"], 1)
        self.assertEqual(everything["ready"], 2)
        # Open: the task of the site (in progress), the under-review one and the two ready ones.
        self.assertEqual(everything["open"], 4)

    def test_open_means_the_statuses_that_are_still_being_worked(self):
        _make_task(self, status=TaskStatus.DELIVERED, title="gone")
        _make_task(self, status=TaskStatus.CANCELLED, title="dropped")
        codes = {t["code"]: t["status"]["value"] for t in _json(self.door(self.ops, "dashboard:v1_tasks", status="open"))["tasks"]}
        self.assertIn(self.task.code, codes)
        self.assertNotIn(TaskStatus.DELIVERED, codes.values())
        self.assertNotIn(TaskStatus.CANCELLED, codes.values())

    def test_the_board_is_what_is_being_worked_and_delivered_and_cancelled_have_a_tab_each(self):
        fresh = _make_task(self, status=TaskStatus.NEW, title="fresh")
        gone = _make_task(self, status=TaskStatus.DELIVERED, title="gone")
        dropped = _make_task(self, status=TaskStatus.CANCELLED, title="dropped")
        board = {t["code"] for t in _json(self.door(self.ops, "dashboard:v1_tasks"))["tasks"]}
        # Everything still alive, a task that has not been given to a leader yet included.
        self.assertIn(fresh.code, board)
        self.assertIn(self.task.code, board)
        self.assertNotIn(gone.code, board)
        self.assertNotIn(dropped.code, board)
        # Each has its own tab, and nothing else is in it.
        delivered = _json(self.door(self.ops, "dashboard:v1_tasks", status="delivered"))
        self.assertEqual([t["code"] for t in delivered["tasks"]], [gone.code])
        cancelled = _json(self.door(self.ops, "dashboard:v1_tasks", status="cancelled"))
        self.assertEqual([t["code"] for t in cancelled["tasks"]], [dropped.code])

    def test_one_status_lists_only_that_status(self):
        done = _make_task(self, status=TaskStatus.DELIVERED, title="gone")
        body = _json(self.door(self.ops, "dashboard:v1_tasks", status="delivered"))
        self.assertEqual([t["code"] for t in body["tasks"]], [done.code])
        self.assertEqual(body["status"], "delivered")

    def test_a_status_that_is_not_one_is_refused_and_not_an_empty_list(self):
        for bad in ("evil", "OPEN", "delivered,new", "new'--", "../x"):
            answer = self.door(self.ops, "dashboard:v1_tasks", status=bad)
            self.assertEqual((answer.status_code, _json(answer)), (400, {"ok": False, "error": "bad_status"}), bad)

    def test_the_tabs_are_every_status_with_both_languages(self):
        statuses = _json(self.door(self.ops, "dashboard:v1_tasks"))["statuses"]
        self.assertEqual([s["value"] for s in statuses], [value for value, _label in TaskStatus.choices])
        self.assertTrue(all(s["ar"] and s["en"] for s in statuses))

    def test_at_most_two_hundred_rows_are_answered(self):
        client = self.client_obj
        for index in range(210):
            Task.objects.create(code=f"BULK-{index:04d}", client=client, title=f"Bulk {index}", created_by=self.ops)
        body = _json(self.door(self.ops, "dashboard:v1_tasks"))
        self.assertEqual(len(body["tasks"]), 200)
        self.assertGreater(body["counters"]["new"], 200)

    def test_a_list_costs_the_same_queries_however_long_it_is(self):
        def cost():
            browser = DjangoClient()
            browser.force_login(self.ops)
            browser.get(reverse("dashboard:v1_tasks"))
            with CaptureQueriesContext(connection) as queries:
                self.assertEqual(browser.get(reverse("dashboard:v1_tasks")).status_code, 200)
            return len(queries)

        few = cost()
        for index in range(12):
            _make_task(self, title=f"More {index}")
        self.assertEqual(cost(), few)


# ---------------------------------------------------------------------------------------------------------------------
# The team board
# ---------------------------------------------------------------------------------------------------------------------

class TeamBoardTests(_Ops):
    def setUp(self):
        super().setUp()
        self.fast = User.objects.create_user("person_second_translator", password="pw", role=Role.TRANSLATOR,
                                             team_lead=self.lead, languages="EN, AR")
        self.idle = User.objects.create_user("person_idle_translator", password="pw", role=Role.TRANSLATOR,
                                             team_lead=self.lead)

    def board(self, user=None):
        return _json(self.door(user or self.ops, "dashboard:v1_team"))

    def lead_row(self, body=None):
        return next(row for row in (body or self.board())["leads"] if row["id"] == self.lead.pk)

    def test_the_operation_and_the_admin_are_answered_everybody_else_is_refused(self):
        for user in (self.ops, self.admin):
            self.assertEqual(self.door(user, "dashboard:v1_team").status_code, 200, user.username)
        self.refused_for_everybody_else("dashboard:v1_team")
        self.post_refused("dashboard:v1_team")
        self.assertEqual(self.door(self.ops, "dashboard:v1_team")["Cache-Control"], "private, no-store")

    def test_a_leader_and_the_translators_under_them(self):
        row = self.lead_row()
        self.assertEqual((row["name"], row["initials"]), (self.lead.short_name, self.lead.initials))
        names = {m["name"] for m in row["members"]}
        self.assertEqual(names, {self.tr.short_name, self.fast.short_name, self.idle.short_name})
        member = next(m for m in row["members"] if m["id"] == self.fast.pk)
        self.assertEqual(member["languages"], "EN, AR")
        self.assertIsInstance(member["rating"], float)
        self.assertTrue(member["seen"]["ar"] and member["seen"]["en"])

    def test_only_a_translator_under_that_leader_is_on_the_row_and_nobody_inactive(self):
        other_lead = User.objects.create_user("person_other_leader", password="pw", role=Role.TEAM_LEAD)
        stranger = User.objects.create_user("person_stranger", password="pw", role=Role.TRANSLATOR, team_lead=other_lead)
        gone = User.objects.create_user("person_gone", password="pw", role=Role.TRANSLATOR, team_lead=self.lead, is_active=False)
        body = self.board()
        mine = {m["id"] for m in self.lead_row(body)["members"]}
        self.assertNotIn(stranger.pk, mine)
        self.assertNotIn(gone.pk, mine)
        other = next(row for row in body["leads"] if row["id"] == other_lead.pk)
        self.assertEqual([m["id"] for m in other["members"]], [stranger.pk])

    def test_who_is_free_busy_offline_or_only_on_shift(self):
        now = timezone.now()
        # Open now, with a task (busy), without (free); the third has not opened the site (off).
        User.objects.filter(pk=self.tr.pk).update(last_seen=now)
        User.objects.filter(pk=self.fast.pk).update(last_seen=now)
        User.objects.filter(pk=self.idle.pk).update(last_seen=None)
        row = self.lead_row()
        states = {m["id"]: m["state"] for m in row["members"]}
        self.assertEqual(states[self.tr.pk], "busy")
        self.assertEqual(states[self.fast.pk], "free")
        self.assertEqual(states[self.idle.pk], "off")
        self.assertEqual(row["counts"], {"free": 1, "busy": 1, "offline": 1})

    def test_the_counts_are_the_classic_boards(self):
        User.objects.filter(pk__in=[self.tr.pk, self.fast.pk]).update(last_seen=timezone.now())
        for classic in services.team_overview():
            row = next(r for r in self.board()["leads"] if r["id"] == classic["lead"].pk)
            self.assertEqual(
                row["counts"], {"free": len(classic["free"]), "busy": len(classic["busy"]), "offline": len(classic["offline"])},
            )
            self.assertEqual(row["tasks"], classic["lead_tasks"])
            self.assertEqual(row["online"], classic["online"])

    def test_a_person_shows_at_most_two_task_codes_and_never_a_client(self):
        for index in range(3):
            _make_task(self, translator=self.tr, title=f"Another {index}")
        member = next(m for m in self.lead_row()["members"] if m["id"] == self.tr.pk)
        self.assertEqual(len(member["tasks"]), 2)
        self.assertTrue(all(code.startswith("TSK-") for code in member["tasks"]))
        raw = self.door(self.ops, "dashboard:v1_team").content.decode("utf-8")
        for marker in IDENTITY_MARKERS + (CLIENT_NAME, CLIENT_PHONE, CLIENT_EMAIL):
            self.assertNotIn(marker, raw, marker)

    def test_a_person_with_no_task_has_an_empty_list(self):
        member = next(m for m in self.lead_row()["members"] if m["id"] == self.idle.pk)
        self.assertEqual(member["tasks"], [])

    def test_a_leader_with_nobody_is_a_row_with_no_members(self):
        loner = User.objects.create_user("person_lonely_leader", password="pw", role=Role.TEAM_LEAD)
        row = next(r for r in self.board()["leads"] if r["id"] == loner.pk)
        self.assertEqual((row["members"], row["counts"]), ([], {"free": 0, "busy": 0, "offline": 0}))

    def test_nothing_but_leaders_are_listed_as_leaders(self):
        ids = {row["id"] for row in self.board()["leads"]}
        self.assertEqual(ids, {u.pk for u in User.objects.filter(role=Role.TEAM_LEAD, is_active=True)})
        raw = self.door(self.ops, "dashboard:v1_team").content.decode("utf-8")
        for secret in ("pw", "password", "email"):
            self.assertNotIn(f'"{secret}"', raw)


# ---------------------------------------------------------------------------------------------------------------------
# The switch: the classic pages hand the operation on to the same page in the new app
# ---------------------------------------------------------------------------------------------------------------------

class _Switched(_Ops):
    def setUp(self):
        super().setUp()
        from unittest import mock

        # As if ``npm run build`` had run: a checkout that never built the app must not change what these say.
        built = mock.patch("dashboard.spa.built_assets", return_value={"js": "x.js", "css": []})
        built.start()
        self.addCleanup(built.stop)

    def turn_on(self, roles=(), users=()):
        from .models import AppSettings

        conf = AppSettings.load()
        conf.save()

    def page(self, user, name, args=None, /, **query):
        browser = DjangoClient()
        browser.force_login(user)
        return browser.get(reverse(name, args=args), query)


class OpsHandOnTests(_Switched):
    def test_the_operation_with_the_switch_lands_on_the_same_page_in_the_new_app(self):
        self.turn_on(roles=["operation"])
        for name, expected in (("dashboard:ops_tasks", "/app/tasks"), ("dashboard:ops_team", "/app/team")):
            answer = self.page(self.ops, name)
            self.assertEqual((answer.status_code, answer["Location"]), (302, expected), name)

    def test_the_task_list_keeps_its_tab_and_only_a_tab_that_is_one(self):
        self.turn_on(roles=["operation"])
        self.assertEqual(self.page(self.ops, "dashboard:ops_tasks", status="open")["Location"], "/app/tasks?status=open")
        self.assertEqual(self.page(self.ops, "dashboard:ops_tasks", status="delivered")["Location"], "/app/tasks?status=delivered")
        for bad in ("evil", "x&y=1", "//evil.example", "OPEN"):
            self.assertEqual(self.page(self.ops, "dashboard:ops_tasks", status=bad)["Location"], "/app/tasks", bad)

    def test_a_role_the_screen_is_not_for_cannot_be_switched_on_for(self):
        from . import newui

        self.turn_on(roles=["sales", "team_lead", "translator"])
        for user in (self.sales, self.lead, self.tr):
            self.assertNotIn("operation", newui.enabled_keys(user), user.username)

    def test_the_new_apps_menu_lists_the_screen_for_those_it_is_on_for(self):
        self.turn_on(roles=["operation"])
        browser = DjangoClient()
        browser.force_login(self.ops)
        self.assertIn("operation", _json(browser.get(reverse("dashboard:v1_me")))["screens"])
        browser.force_login(self.lead)
        self.assertNotIn("operation", _json(browser.get(reverse("dashboard:v1_me")))["screens"])


# ---------------------------------------------------------------------------------------------------------------------
# One task, as the operation reads it
# ---------------------------------------------------------------------------------------------------------------------

class OpsTaskDoorTests(_Ops):
    def read(self, user, code=None):
        return self.door(user, "dashboard:v1_task", [code or self.task.code])

    def body(self, user=None, code=None):
        return _json(self.read(user or self.ops, code))["task"]

    def settle(self, **fields):
        Task.objects.filter(pk=self.task.pk).update(**fields)

    def test_the_operation_and_the_admin_are_answered_everybody_else_is_refused(self):
        for user in (self.ops, self.admin):
            self.assertEqual(self.read(user).status_code, 200, user.username)
        for user in (self.tr, self.hr, self.reviewer, self.accounting, self.sales):
            answer = self.read(user)
            self.assertEqual((answer.status_code, _json(answer)), (403, {"ok": False, "error": "forbidden"}), user.username)
        self.assertEqual(self.read(None).status_code, 401)
        browser = DjangoClient()
        browser.force_login(self.ops)
        self.assertEqual(browser.post(reverse("dashboard:v1_task", args=[self.task.code])).status_code, 405)
        self.assertEqual(self.read(self.ops)["Cache-Control"], "private, no-store")
        self.assertEqual(_json(self.read(self.ops, "TSK-99999")), {"ok": False, "error": "not_found"})

    def test_the_head_of_the_page(self):
        clients = timezone.now() + timedelta(days=4)
        mine = timezone.now() + timedelta(days=2)
        self.settle(deadline=clients, translator_deadline=mine, source_lang="Arabic", target_lang="English",
                    description="[document]\nTranslate pages 2-4")
        task = self.body()
        self.assertEqual((task["code"], task["title"], task["client"], task["client_code"]),
                         (self.task.code, "Doc", self.client_obj.code, self.client_obj.code))
        self.assertEqual(task["status"]["value"], TaskStatus.IN_PROGRESS)
        self.assertEqual((task["source_lang"], task["target_lang"]), ("Arabic", "English"))
        self.assertEqual(task["description"], "Translate pages 2-4")
        self.assertEqual(task["people"], {"operation": self.ops.short_name, "team_lead": self.lead.short_name,
                                          "translator": self.tr.short_name})
        # The client date is the operation's; what the translator was given is a chip beside it.
        self.assertIn(timezone.localtime(clients).strftime("%Y-%m-%d"), task["due"]["en"])
        self.assertIn(timezone.localtime(mine).strftime("%m-%d"), task["translator_due"]["en"])
        self.assertTrue(task["origin"] is None or task["origin"]["value"])

    def test_no_deadline_and_no_translator_date_are_null(self):
        self.settle(deadline=None, translator_deadline=None)
        task = self.body()
        self.assertEqual((task["due"], task["due_state"], task["translator_due"]), (None, "none", None))

    def test_the_operation_reads_a_code_and_the_admin_the_name_beside_it(self):
        self.assertEqual(self.body()["client"], self.client_obj.code)
        self.assertIn(CLIENT_NAME, self.body(self.admin)["client"])
        raw = self.read(self.ops).content.decode("utf-8")
        for marker in IDENTITY_MARKERS + (CLIENT_NAME, CLIENT_PHONE, CLIENT_EMAIL):
            self.assertNotIn(marker, raw, marker)

    def test_a_new_task_can_be_sent_to_a_leader_and_says_who_is_here(self):
        User.objects.filter(pk=self.lead.pk).update(last_seen=timezone.now())
        quiet = User.objects.create_user("person_quiet_leader", password="pw", role=Role.TEAM_LEAD)
        task = _make_task(self, status=TaskStatus.NEW, title="Fresh")
        body = self.body(code=task.code)
        self.assertTrue(body["can"]["assign_lead"])
        leads = {lead["id"]: lead for lead in body["leads"]}
        self.assertEqual(set(leads), {self.lead.pk, quiet.pk})
        self.assertTrue(leads[self.lead.pk]["online"])
        self.assertFalse(leads[quiet.pk]["online"])
        self.assertEqual(leads[self.lead.pk]["tasks"], self.lead.active_task_count)
        # Not before it is new, and not for a task that is on its way.
        other = self.body()
        self.assertEqual((other["can"]["assign_lead"], other["leads"]), (False, []))

    def fresh(self):
        """A new task: nobody has it yet, no leader and no translator."""
        task = _make_task(self, status=TaskStatus.NEW, title="Fresh")
        Task.objects.filter(pk=task.pk).update(translator=None, team_lead=None)
        return Task.objects.get(pk=task.pk)

    def direct(self, user, task, translator):
        browser = DjangoClient()
        browser.force_login(user)
        return browser.post(reverse("dashboard:api_assign_translator_direct", args=[task.code]), {"user": translator.pk})

    def test_the_way_past_the_leader_is_offered_only_while_no_leader_is_online(self):
        task = self.fresh()
        User.objects.filter(pk=self.lead.pk).update(last_seen=timezone.now())
        self.assertIsNone(self.body(code=task.code)["direct"])
        User.objects.filter(pk=self.lead.pk).update(last_seen=None)
        loose = User.objects.create_user("person_loose_translator", password="pw", role=Role.TRANSLATOR)
        direct = self.body(code=task.code)["direct"]
        # The translator with no leader is not offered: nobody would review their work.
        self.assertEqual([p["id"] for p in direct["translators"]], [self.tr.pk])
        self.assertNotIn(loose.pk, [p["id"] for p in direct["translators"]])
        self.assertEqual(direct["translators"][0]["lead"], self.lead.short_name)
        # Not on a task that has moved on, and not for what is not new.
        self.assertIsNone(self.body()["direct"])

    def test_a_new_task_goes_straight_to_a_translator_and_the_leader_keeps_the_review(self):
        from .models import Notification

        task = self.fresh()
        answer = self.direct(self.ops, task, self.tr)
        self.assertEqual((answer.status_code, _json(answer)["status"]), (200, "awaiting_translator"))
        task.refresh_from_db()
        self.assertEqual((task.translator_id, task.team_lead_id), (self.tr.pk, self.lead.pk))
        self.assertTrue(task.assignments.filter(assignee=self.tr, target_role=Role.TRANSLATOR, assigned_by=self.ops).exists())
        self.assertTrue(Notification.objects.filter(user=self.lead, task=task).exists())
        self.assertTrue(Notification.objects.filter(user=self.tr, task=task, sound=True).exists())
        self.assertTrue(AuditLog.objects.filter(action="task.assign_direct", target=task.code, actor=self.ops).exists())

    def test_it_is_refused_while_a_leader_is_online_and_nothing_is_written(self):
        User.objects.filter(pk=self.lead.pk).update(last_seen=timezone.now())
        task = self.fresh()
        answer = self.direct(self.ops, task, self.tr)
        self.assertEqual((answer.status_code, _json(answer)["error"]), (400, "lead_online"))
        task.refresh_from_db()
        self.assertEqual((task.status, task.translator_id), (TaskStatus.NEW, None))

    def test_it_is_refused_for_a_translator_with_no_leader_and_for_a_task_that_is_not_new(self):
        loose = User.objects.create_user("person_loose_translator", password="pw", role=Role.TRANSLATOR)
        task = self.fresh()
        self.assertEqual(_json(self.direct(self.ops, task, loose))["error"], "no_leader")
        started = _make_task(self, status=TaskStatus.IN_PROGRESS, title="Going", translator=self.tr)
        self.assertEqual(_json(self.direct(self.ops, started, self.tr))["error"], "bad_status")
        task.refresh_from_db()
        self.assertIsNone(task.translator_id)

    def test_only_the_operation_and_the_admin_may_send_a_task_past_the_leader(self):
        task = self.fresh()
        for user in (self.lead, self.tr, self.hr, self.reviewer, self.accounting, self.sales):
            self.assertEqual(self.direct(user, task, self.tr).status_code, 403, user.username)
        task.refresh_from_db()
        self.assertEqual(task.status, TaskStatus.NEW)
        self.assertEqual(self.direct(self.admin, task, self.tr).status_code, 200)

    def test_who_is_being_waited_for_and_for_how_long(self):
        task = _make_task(self, status=TaskStatus.LEAD_ACCEPTED, title="Needs an answer")
        services.assign_to_translator(task, self.tr, self.lead)
        waiting = self.body(code=task.code)["waiting_for"]
        self.assertEqual(waiting["name"], self.tr.short_name)
        self.assertTrue(0 < waiting["seconds_left"] <= 60)
        self.assertIsNone(self.body()["waiting_for"])

    def test_a_reviewed_task_waits_for_somebody_to_take_it_over_and_nothing_can_be_sent_yet(self):
        self.settle(status=TaskStatus.REVIEWED, handover_ack_at=None)
        task = self.body()
        self.assertEqual((task["can"]["take_over"], task["can"]["deliver"], task["deliver"], task["handover"]),
                         (True, False, None, None))

    def test_a_task_taken_over_offers_the_translators_files_ticked_and_says_where_they_would_go(self):
        from django.core.files.base import ContentFile

        from .models import ChatAttachment, ChatMessage

        self.settle(status=TaskStatus.REVIEWED, handover_ack_at=timezone.now(), handover_ack_by=self.ops)
        mine = ChatMessage.objects.create(room=self.work_group, sender=self.tr, task=self.task, body="done")
        ChatAttachment.objects.create(message=mine, file=ContentFile(b"t", name="translated.docx"),
                                      original_name="translated.docx", size=1536)
        ChatAttachment.objects.create(message=mine, file=ContentFile(b"v", name="talk.ogg"), original_name="talk.ogg", size=5)
        theirs = ChatMessage.objects.create(room=self.work_group, sender=self.lead, task=self.task, body="notes")
        ChatAttachment.objects.create(message=theirs, file=ContentFile(b"n", name="notes.pdf"), original_name="notes.pdf", size=1)
        task = self.body()
        self.assertEqual((task["can"]["take_over"], task["can"]["deliver"]), (False, True))
        self.assertEqual((task["handover"]["by"], bool(task["handover"]["at"])), (self.ops.short_name, True))
        files = {f["name"]: f for f in task["deliver"]["files"]}
        # A voice note is talk, not a translation, and is not even offered.
        self.assertEqual(sorted(files), ["notes.pdf", "translated.docx"])
        self.assertTrue(files["translated.docx"]["final"])
        self.assertFalse(files["notes.pdf"]["final"])
        self.assertEqual((files["translated.docx"]["sender"], files["translated.docx"]["size"]),
                         (self.tr.short_name, "1.5 KB"))
        self.assertEqual((task["deliver"]["channel"], task["deliver"]["reachable"]), ("whatsapp", True))

    def test_a_client_with_no_number_and_no_address_cannot_be_reached(self):
        from .models import Client

        self.settle(status=TaskStatus.REVIEWED, handover_ack_at=timezone.now(), handover_ack_by=self.ops)
        Client.objects.filter(pk=self.client_obj.pk).update(phone="", email="", extra_phones="", extra_emails="")
        self.assertFalse(self.body()["deliver"]["reachable"])

    def test_only_a_task_that_is_not_finished_can_be_cancelled(self):
        self.assertTrue(self.body()["can"]["cancel"])
        for status in (TaskStatus.DELIVERED, TaskStatus.CANCELLED):
            self.settle(status=status)
            self.assertFalse(self.body()["can"]["cancel"], status)

    def test_only_the_admin_can_add_somebody_to_the_group_and_is_told_who(self):
        extra = User.objects.create_user("person_second_operation", password="pw", role=Role.OPERATION)
        self.task_group.members.add(self.lead)
        ops_view = self.body()
        self.assertEqual((ops_view["can"]["add_member"], ops_view["group_candidates"]), (False, []))
        admin_view = self.body(self.admin)
        self.assertTrue(admin_view["can"]["add_member"])
        ids = {p["id"] for p in admin_view["group_candidates"]}
        self.assertIn(extra.pk, ids)
        self.assertNotIn(self.lead.pk, ids)
        self.assertTrue(all(p["role"] in ("operation", "team_lead") for p in admin_view["group_candidates"]))

    def test_the_word_count_says_whether_it_is_set(self):
        self.assertEqual(self.body()["words"], {"state": "empty", "value": None})
        self.settle(word_count=1200, word_count_state="confirmed")
        self.assertEqual(self.body()["words"], {"state": "confirmed", "value": 1200})

    def test_what_the_translator_handed_in_and_what_the_client_sent_are_listed_apart(self):
        from django.core.files.base import ContentFile

        from .models import ChatAttachment, ChatMessage, InboundMessage, MessageAttachment

        inbound = InboundMessage.objects.filter(task=self.task).first()
        MessageAttachment.objects.create(message=inbound, file=ContentFile(b"o", name="contract.pdf"),
                                         original_name="contract.pdf", size=2048)
        sent = ChatMessage.objects.create(room=self.work_group, sender=self.tr, task=self.task, body="done")
        ChatAttachment.objects.create(message=sent, file=ContentFile(b"t", name="translated.docx"),
                                      original_name="translated.docx", size=1)
        files = self.body()["files"]
        self.assertEqual([f["name"] for f in files["original"]], ["contract.pdf"])
        self.assertEqual([f["name"] for f in files["translation"]], ["translated.docx"])
        self.assertTrue(files["translation"][0]["at"]["ar"])

    def test_the_chat_links_are_the_leader_group_and_the_clients_own_conversation(self):
        task = self.body()
        self.assertEqual(task["client_chat_url"], f"/ops/chats/{self.client_obj.code}/")
        self.assertIn("/ops/chats/", task["chat"]["url"])

    def test_the_clients_messages_are_the_ones_this_person_may_read(self):
        from .models import InboundMessage

        InboundMessage.objects.create(client=self.client_obj, channel="whatsapp", body="RATE TALK",
                                      sender_identity=CLIENT_PHONE, task=self.task, is_rate_blocked=True)
        InboundMessage.objects.create(client=self.client_obj, channel="whatsapp", body="SALES LINE ONLY",
                                      sender_identity=CLIENT_PHONE, task=self.task, owner=self.sales)
        ops_bodies = [m["body"] for m in self.body()["messages"]]
        self.assertIn("hello there", ops_bodies)
        self.assertNotIn("RATE TALK", ops_bodies)
        self.assertNotIn("SALES LINE ONLY", ops_bodies)
        admin_bodies = [m["body"] for m in self.body(self.admin)["messages"]]
        self.assertIn("RATE TALK", admin_bodies)
        self.assertIn("SALES LINE ONLY", admin_bodies)

    def test_a_long_message_is_cut_and_the_placeholders_are_taken_out(self):
        from .models import InboundMessage

        InboundMessage.objects.create(client=self.client_obj, channel="whatsapp", body="[document]\n" + "x" * 400,
                                      sender_identity=CLIENT_PHONE, task=self.task)
        long_one = [m for m in self.body()["messages"] if m["body"].startswith("x")][0]
        self.assertEqual(len(long_one["body"]), 220)

    def test_the_words_of_a_failed_delivery_carry_no_number_or_address_for_the_operation(self):
        from .models import Channel, OutboundMessage

        OutboundMessage.objects.create(client=self.client_obj, task=self.task, kind=OutboundMessage.Kind.DELIVERY,
                                       created_by=self.ops, channel=Channel.WHATSAPP, status=OutboundMessage.Status.FAILED,
                                       error_message=f"WhatsApp refused {CLIENT_PHONE} and {CLIENT_EMAIL}")
        for marker in IDENTITY_MARKERS + (CLIENT_PHONE, CLIENT_EMAIL):
            self.assertNotIn(marker, self.read(self.ops).content.decode("utf-8"), marker)
        (row,) = self.body()["deliveries"]
        self.assertEqual((row["status"], row["channel"], row["by"]), ("failed", "whatsapp", self.ops.short_name))
        self.assertIn(CLIENT_PHONE, self.body(self.admin)["deliveries"][0]["error"])

    def test_the_requirements_and_the_assignment_history(self):
        from .models import ClientRequirement

        ClientRequirement.objects.create(client=self.client_obj, kind="like", author=self.ops, text="Formal tone")
        task = self.body()
        self.assertEqual([(r["kind"]["value"], r["author"], r["text"]) for r in task["requirements"]],
                         [("like", self.ops.short_name, "Formal tone")])
        names = [(h["name"], h["role"], h["status"]) for h in task["history"]]
        self.assertIn((self.lead.short_name, "team_lead", "accepted"), names)
        self.assertIn((self.tr.short_name, "translator", "accepted"), names)

    def test_a_page_costs_the_same_queries_however_much_is_on_it(self):
        from django.core.files.base import ContentFile

        from .models import ChatAttachment, ChatMessage, ClientRequirement, InboundMessage, MessageAttachment

        def cost():
            browser = DjangoClient()
            browser.force_login(self.ops)
            browser.get(reverse("dashboard:v1_task", args=[self.task.code]))
            with CaptureQueriesContext(connection) as queries:
                self.assertEqual(browser.get(reverse("dashboard:v1_task", args=[self.task.code])).status_code, 200)
            return len(queries)

        few = cost()
        sent = ChatMessage.objects.create(room=self.work_group, sender=self.tr, task=self.task, body="done")
        for index in range(10):
            ClientRequirement.objects.create(client=self.client_obj, kind="rule", author=self.ops, text=f"Rule {index}")
            inbound = InboundMessage.objects.create(client=self.client_obj, channel="whatsapp", body=f"m{index}",
                                                    sender_identity=CLIENT_PHONE, task=self.task)
            MessageAttachment.objects.create(message=inbound, file=ContentFile(b"o", name=f"in{index}.pdf"),
                                             original_name=f"in{index}.pdf", size=1)
            ChatAttachment.objects.create(message=sent, file=ContentFile(b"t", name=f"out{index}.docx"),
                                          original_name=f"out{index}.docx", size=1)
        self.assertEqual(cost(), few)


class OpsTaskWordsAndRequirementTests(_Ops):
    def post(self, user, name, body, code=None):
        browser = DjangoClient()
        if user is not None:
            browser.force_login(user)
        return browser.post(reverse(name, args=[code or self.task.code]), json.dumps(body), content_type="application/json")

    def test_the_word_count_is_settled_by_the_operation_and_the_admin_and_nobody_else(self):
        for user in (self.ops, self.admin):
            answer = self.post(user, "dashboard:v1_task_words", {"words": 1500})
            self.assertEqual((answer.status_code, _json(answer)), (200, {"ok": True, "words": 1500, "state": "confirmed"}),
                             user.username)
        for user in (self.tr, self.hr, self.reviewer, self.accounting, self.sales):
            self.assertEqual(self.post(user, "dashboard:v1_task_words", {"words": 7}).status_code, 403, user.username)
        self.assertEqual(self.post(None, "dashboard:v1_task_words", {"words": 7}).status_code, 401)
        self.task.refresh_from_db()
        self.assertEqual((self.task.word_count, self.task.word_count_state), (1500, "confirmed"))

    def test_the_word_count_is_written_to_the_audit_log(self):
        self.post(self.ops, "dashboard:v1_task_words", {"words": 2500})
        self.assertTrue(AuditLog.objects.filter(action="task.word_count.confirm", target=self.task.code, actor=self.ops).exists())

    def test_a_number_that_is_not_a_count_is_refused_and_nothing_is_written(self):
        for bad in ("12", "", None, -1, 1.5, True, [1], {"a": 1}, 10_000_001, "1e3"):
            answer = self.post(self.ops, "dashboard:v1_task_words", {"words": bad})
            self.assertEqual((answer.status_code, _json(answer)), (400, {"ok": False, "error": "bad_words"}), repr(bad))
        self.task.refresh_from_db()
        self.assertEqual(self.task.word_count_state, "empty")

    def test_the_boundaries_of_a_count(self):
        for words in (0, 10_000_000):
            self.assertEqual(self.post(self.ops, "dashboard:v1_task_words", {"words": words}).status_code, 200, words)

    def test_the_word_door_takes_only_a_json_object(self):
        browser = DjangoClient()
        browser.force_login(self.ops)
        url = reverse("dashboard:v1_task_words", args=[self.task.code])
        for kwargs in (
            {"data": "words=5", "content_type": "application/x-www-form-urlencoded"},
            {"data": "[1]", "content_type": "application/json"},
            {"data": "{", "content_type": "application/json"},
        ):
            self.assertEqual(browser.post(url, **kwargs).status_code, 400, kwargs["data"])
        self.assertEqual(browser.get(url).status_code, 405)
        self.task.refresh_from_db()
        self.assertEqual(self.task.word_count_state, "empty")

    def test_a_task_that_does_not_exist_is_a_404(self):
        self.assertEqual(self.post(self.ops, "dashboard:v1_task_words", {"words": 1}, "TSK-99999").status_code, 404)
        self.assertEqual(self.post(self.ops, "dashboard:v1_task_requirement", {"kind": "rule", "text": "x"}, "TSK-99999").status_code, 404)

    def test_a_requirement_is_added_to_the_client_and_comes_back_as_the_row(self):
        from .models import ClientRequirement

        answer = self.post(self.ops, "dashboard:v1_task_requirement", {"kind": "dislike", "text": "  No contractions "})
        body = _json(answer)
        self.assertEqual((answer.status_code, body["ok"]), (200, True))
        self.assertEqual((body["requirement"]["kind"]["value"], body["requirement"]["author"], body["requirement"]["text"]),
                         ("dislike", self.ops.short_name, "No contractions"))
        row = ClientRequirement.objects.get()
        self.assertEqual((row.client_id, row.author_id), (self.client_obj.pk, self.ops.pk))
        self.assertTrue(AuditLog.objects.filter(action="client.requirement", target=self.client_obj.code).exists())

    def test_a_requirement_is_the_operations_and_the_admins_alone(self):
        from .models import ClientRequirement

        for user in (self.tr, self.hr, self.reviewer, self.accounting, self.sales):
            self.assertEqual(self.post(user, "dashboard:v1_task_requirement", {"kind": "rule", "text": "x"}).status_code, 403,
                             user.username)
        self.assertEqual(self.post(self.admin, "dashboard:v1_task_requirement", {"kind": "rule", "text": "from admin"}).status_code, 200)
        self.assertEqual(ClientRequirement.objects.count(), 1)

    def test_a_requirement_that_is_not_one_is_refused_and_nothing_is_written(self):
        from .models import ClientRequirement

        for body in ({"kind": "rule", "text": ""}, {"kind": "rule", "text": "   "}, {"kind": "evil", "text": "x"},
                     {"kind": "", "text": "x"}, {"text": "x"}):
            answer = self.post(self.ops, "dashboard:v1_task_requirement", body)
            self.assertEqual(answer.status_code, 400, body)
            self.assertIn(_json(answer)["error"], ("bad_requirement", "bad_request"), body)
        for body in ({"kind": 5, "text": "x"}, {"kind": "rule", "text": ["x"]}, {"kind": "rule", "text": "x" * 2001},
                     {"kind": "rule", "text": "a\x00b"}):
            self.assertEqual(self.post(self.ops, "dashboard:v1_task_requirement", body).status_code, 400, repr(body)[:40])
        self.assertEqual(ClientRequirement.objects.count(), 0)

    def test_a_requirement_is_for_the_tasks_own_client_only(self):
        from .models import Client, ClientRequirement

        other = Client.objects.create(name="Other Co", phone="+201005550000")
        self.post(self.ops, "dashboard:v1_task_requirement", {"kind": "rule", "text": "mine"})
        self.assertEqual(ClientRequirement.objects.filter(client=other).count(), 0)
        self.assertEqual(ClientRequirement.objects.filter(client=self.client_obj).count(), 1)


# ---------------------------------------------------------------------------------------------------------------------
# Starting a task
# ---------------------------------------------------------------------------------------------------------------------

class _Start(_Ops):
    def setUp(self):
        super().setUp()
        from django.core.files.base import ContentFile

        from .models import Channel, Client, InboundMessage, MessageAttachment

        self.heard = InboundMessage.objects.create(
            client=self.client_obj, channel=Channel.WHATSAPP, body="Please translate the contract", sender_identity=CLIENT_PHONE,
        )
        self.contract = MessageAttachment.objects.create(
            message=self.heard, file=ContentFile(b"c", name="contract.pdf"), original_name="contract.pdf", size=2048,
        )
        self.annex = MessageAttachment.objects.create(
            message=self.heard, file=ContentFile(b"a", name="annex.pdf"), original_name="annex.pdf", size=10,
        )
        self.other_client = Client.objects.create(name="Other Co", phone="+201005550000")
        self.elsewhere = InboundMessage.objects.create(
            client=self.other_client, channel=Channel.WHATSAPP, body="from another client", sender_identity="+201005550000",
        )
        self.stranger = MessageAttachment.objects.create(
            message=self.elsewhere, file=ContentFile(b"s", name="stranger.pdf"), original_name="stranger.pdf", size=1,
        )

    def start(self, user=None, **query):
        return self.door(user or self.ops, "dashboard:v1_task_start", **query)

    def create(self, body, user=None):
        browser = DjangoClient()
        browser.force_login(user or self.ops)
        return browser.post(reverse("dashboard:v1_task_create"), json.dumps(body), content_type="application/json")

    def good(self, **over):
        return {"client": self.client_obj.pk, "title": "A new job", "description": "", "source_lang": "en", "target_lang": "ar",
                "priority": "normal", **over}


class TaskStartDoorTests(_Start):
    def test_the_operation_and_the_admin_are_answered_everybody_else_is_refused(self):
        for user in (self.ops, self.admin):
            self.assertEqual(self.start(user).status_code, 200, user.username)
        self.refused_for_everybody_else("dashboard:v1_task_start")
        self.post_refused("dashboard:v1_task_start")
        self.assertEqual(self.start()["Cache-Control"], "private, no-store")

    def test_a_blank_form_has_the_clients_the_languages_and_the_priorities(self):
        from .models import Client

        Client.objects.filter(pk=self.other_client.pk).update(is_active=False)
        body = _json(self.start())
        self.assertEqual((body["messages"], body["picked"], body["from_task"], body["requirements"]), ([], [], None, []))
        self.assertEqual(body["initial"], {
            "client": None, "title": "", "description": "", "source_lang": "",
            "target_lang": "", "word_count": None, "deadline_days": None,
        })
        self.assertIsNone(body["quote"])
        self.assertEqual([c["code"] for c in body["clients"]], [self.client_obj.code])
        self.assertEqual(body["quick_languages"], ["AR", "EN", "FR", "DE", "IT", "ES"])
        self.assertIn("EN", [lang["code"] for lang in body["languages"]])
        self.assertEqual([p["value"] for p in body["priorities"]], ["low", "normal", "high", "urgent"])
        self.assertTrue(all(p["ar"] and p["en"] for p in body["priorities"]))

    def test_the_operation_is_offered_codes_and_the_admin_the_name_beside_them(self):
        ops_clients = _json(self.start())["clients"]
        self.assertTrue(all(c["label"] == c["code"] for c in ops_clients))
        raw = self.start().content.decode("utf-8")
        for marker in IDENTITY_MARKERS + (CLIENT_NAME, CLIENT_PHONE, CLIENT_EMAIL):
            self.assertNotIn(marker, raw, marker)
        admin_labels = {c["code"]: c["label"] for c in _json(self.start(self.admin))["clients"]}
        self.assertIn(CLIENT_NAME, admin_labels[self.client_obj.code])

    def test_a_task_made_from_a_message_starts_with_its_client_its_words_and_its_files(self):
        body = _json(self.start(message=self.heard.pk))
        self.assertEqual(body["initial"]["client"], self.client_obj.pk)
        self.assertEqual(body["initial"]["title"], "Please translate the contract")
        self.assertEqual(body["initial"]["description"], "Please translate the contract")
        self.assertEqual(body["client_code"], self.client_obj.code)
        (message,) = body["messages"]
        self.assertEqual((message["id"], message["channel"]), (self.heard.pk, "whatsapp"))
        self.assertEqual([f["name"] for f in message["files"]], ["contract.pdf", "annex.pdf"])
        # Nothing ticked is every file of the message: the page says so, so none is listed as picked.
        self.assertEqual(body["picked"], [])

    def test_a_letters_subject_is_the_title_and_a_long_first_line_is_cut(self):
        from .models import Channel, InboundMessage

        letter = InboundMessage.objects.create(client=self.client_obj, channel=Channel.EMAIL, subject="Quote for the lease",
                                               body="Dear all", sender_identity=CLIENT_EMAIL)
        self.assertEqual(_json(self.start(message=letter.pk))["initial"]["title"], "Quote for the lease")
        long_one = InboundMessage.objects.create(client=self.client_obj, channel=Channel.WHATSAPP, body="w" * 100,
                                                 sender_identity=CLIENT_PHONE)
        self.assertEqual(len(_json(self.start(message=long_one.pk))["initial"]["title"]), 60)

    def test_files_with_no_words_make_a_title_that_says_how_many_and_the_placeholders_are_dropped(self):
        from django.core.files.base import ContentFile

        from .models import Channel, InboundMessage, MessageAttachment

        bare = InboundMessage.objects.create(client=self.client_obj, channel=Channel.WHATSAPP, body="[document]",
                                             sender_identity=CLIENT_PHONE)
        for name in ("a.pdf", "b.pdf"):
            MessageAttachment.objects.create(message=bare, file=ContentFile(b"x", name=name), original_name=name, size=1)
        body = _json(self.start(message=bare.pk))
        self.assertEqual(body["initial"]["title"], f"2 ملفات من {self.client_obj.code}")
        self.assertEqual(body["initial"]["description"], "")

    def test_a_run_of_messages_and_the_files_ticked_across_them(self):
        from .models import Channel, InboundMessage

        second = InboundMessage.objects.create(client=self.client_obj, channel=Channel.WHATSAPP, body="and this one",
                                               sender_identity=CLIENT_PHONE)
        body = _json(self.start(messages=f"{self.heard.pk},{second.pk}", files=str(self.annex.pk)))
        self.assertEqual([m["id"] for m in body["messages"]], [self.heard.pk, second.pk])
        self.assertEqual([f["name"] for f in body["picked"]], ["annex.pdf"])
        self.assertEqual(body["initial"]["description"], "Please translate the contract\n\nand this one")

    def test_only_the_messages_ticked_for_the_details_are_written_there(self):
        from .models import Channel, InboundMessage

        second = InboundMessage.objects.create(client=self.client_obj, channel=Channel.WHATSAPP, body="and this one",
                                               sender_identity=CLIENT_PHONE)
        both = f"{self.heard.pk},{second.pk}"
        body = _json(self.start(messages=both, files=str(self.annex.pk), texts=str(second.pk)))
        self.assertEqual(body["initial"]["description"], "and this one")
        self.assertEqual([m["id"] for m in body["messages"]], [self.heard.pk, second.pk])
        self.assertEqual([f["name"] for f in body["picked"]], ["annex.pdf"])
        # A message ticked for the details is a message of the task even when none of its files is: it is found by id.
        body = _json(self.start(messages=both, texts=f"{second.pk},{self.heard.pk}"))
        self.assertEqual(body["initial"]["description"], "Please translate the contract\n\nand this one")
        # Ticked but not among the messages (another client's): not written, and not offered.
        body = _json(self.start(messages=str(second.pk), texts=f"{self.elsewhere.pk}"))
        self.assertEqual(body["initial"]["description"], "")
        self.assertNotIn("from another client", self.start(messages=str(second.pk), texts=str(self.elsewhere.pk)).content.decode())
        # Nothing ticked is every message's words, as before.
        body = _json(self.start(messages=both))
        self.assertEqual(body["initial"]["description"], "Please translate the contract\n\nand this one")

    def test_one_message_ticked_alone_is_the_title_and_the_details(self):
        from .models import Channel, InboundMessage

        first = InboundMessage.objects.create(client=self.client_obj, channel=Channel.WHATSAPP, body="Not this one",
                                              sender_identity=CLIENT_PHONE)
        second = InboundMessage.objects.create(client=self.client_obj, channel=Channel.WHATSAPP, body="Only this line",
                                               sender_identity=CLIENT_PHONE)
        body = _json(self.start(messages=f"{first.pk},{second.pk}", texts=str(second.pk)))
        self.assertEqual(body["initial"]["description"], "Only this line")
        self.assertEqual(body["initial"]["title"], "Only this line")

    def test_a_task_has_one_client_a_message_of_another_does_not_join_it(self):
        body = _json(self.start(messages=f"{self.heard.pk},{self.elsewhere.pk}"))
        self.assertEqual([m["id"] for m in body["messages"]], [self.heard.pk])
        # And a file of that other message is not walked in either.
        body = _json(self.start(message=self.heard.pk, files=f"{self.annex.pk},{self.stranger.pk}"))
        self.assertEqual([f["name"] for f in body["picked"]], ["annex.pdf"])
        self.assertNotIn("stranger.pdf", self.start(message=self.heard.pk, files=str(self.stranger.pk)).content.decode())

    def test_a_message_this_person_may_not_read_is_not_offered(self):
        from .models import Channel, InboundMessage

        blocked = InboundMessage.objects.create(client=self.client_obj, channel=Channel.WHATSAPP, body="RATE WORDS",
                                                sender_identity=CLIENT_PHONE, is_rate_blocked=True)
        sales_line = InboundMessage.objects.create(client=self.client_obj, channel=Channel.WHATSAPP, body="SALES LINE WORDS",
                                                   sender_identity=CLIENT_PHONE, owner=self.sales)
        for hidden, word in ((blocked, "RATE WORDS"), (sales_line, "SALES LINE WORDS")):
            ops_view = self.start(message=hidden.pk)
            self.assertEqual(_json(ops_view)["messages"], [], word)
            self.assertNotIn(word, ops_view.content.decode("utf-8"))
        self.assertEqual([m["id"] for m in _json(self.start(self.admin, messages=f"{blocked.pk},{sales_line.pk}"))["messages"]],
                         [blocked.pk, sales_line.pk])

    def test_a_new_request_on_the_same_files_starts_from_the_old_task(self):
        from .models import InboundMessage

        InboundMessage.objects.filter(pk=self.heard.pk).update(task=self.task)
        Task.objects.filter(pk=self.task.pk).update(description="Keep the table", source_lang="EN", title="Original contract")
        body = _json(self.start(**{"from": self.task.code}))
        self.assertEqual(body["from_task"], {"code": self.task.code, "title": "Original contract"})
        self.assertEqual(body["initial"]["title"], "طلب جديد — Original contract")
        self.assertEqual((body["initial"]["client"], body["initial"]["source_lang"]), (self.client_obj.pk, "EN"))
        self.assertEqual(body["initial"]["description"], "Keep the table")
        self.assertIn(self.heard.pk, [m["id"] for m in body["messages"]])
        self.assertEqual(body["client_code"], self.client_obj.code)

    def test_the_clients_requirements_are_shown_beside_the_form(self):
        from .models import ClientRequirement

        ClientRequirement.objects.create(client=self.client_obj, kind="rule", author=self.ops, text="British spelling")
        ClientRequirement.objects.create(client=self.other_client, kind="rule", author=self.ops, text="NOT THIS CLIENT")
        body = _json(self.start(message=self.heard.pk))
        self.assertEqual([r["text"] for r in body["requirements"]], ["British spelling"])

    def test_nothing_is_written_by_looking(self):
        before = (Task.objects.count(), AuditLog.objects.count())
        self.start(message=self.heard.pk)
        self.start(**{"from": self.task.code})
        self.heard.refresh_from_db()
        self.assertIsNone(self.heard.claimed_by_id)
        self.assertIsNone(self.heard.task_id)
        self.assertEqual((Task.objects.count(), AuditLog.objects.count()), before)

    def test_an_address_with_too_much_in_it_or_a_task_code_that_is_not_one_is_refused(self):
        for query in ({"messages": ",".join(str(n) for n in range(1, 202))}, {"files": "9" * 2001},
                      {"from": "T" * 41}, {"from": "a\x00b"}):
            answer = self.start(**query)
            self.assertEqual(answer.status_code, 400, str(query)[:30])
        self.assertEqual(self.start(**{"from": "TSK-99999"}).status_code, 200)

    def test_what_is_not_an_id_is_ignored(self):
        body = _json(self.start(messages="abc,,-1,%s" % self.heard.pk, files="x,%s" % self.contract.pk))
        self.assertEqual([m["id"] for m in body["messages"]], [self.heard.pk])
        self.assertEqual([f["name"] for f in body["picked"]], ["contract.pdf"])


class TaskCreateDoorTests(_Start):
    def test_the_operation_and_the_admin_may_make_a_task_and_nobody_else(self):
        for user in (self.ops, self.admin):
            self.assertEqual(self.create(self.good(), user).status_code, 200, user.username)
        for user in (self.lead, self.tr, self.hr, self.reviewer, self.accounting, self.sales):
            self.assertEqual(self.create(self.good(), user).status_code, 403, user.username)
        browser = DjangoClient()
        self.assertEqual(browser.post(reverse("dashboard:v1_task_create"), "{}", content_type="application/json").status_code, 401)
        browser.force_login(self.ops)
        self.assertEqual(browser.get(reverse("dashboard:v1_task_create")).status_code, 405)

    def test_the_task_is_made_as_the_form_says_and_the_languages_are_kept_as_codes(self):
        before = Task.objects.count()
        answer = self.create(self.good(title="  Lease agreement ", description="Two pages", source_lang="English",
                                       target_lang="انجليزي", priority="high"))
        body = _json(answer)
        self.assertEqual((answer.status_code, body["ok"]), (200, True))
        self.assertEqual(Task.objects.count(), before + 1)
        task = Task.objects.get(code=body["code"])
        self.assertEqual((task.title, task.description, task.priority, task.status), ("Lease agreement", "Two pages", "high", TaskStatus.NEW))
        self.assertEqual((task.source_lang, task.target_lang), ("EN", "EN"))
        self.assertEqual((task.client_id, task.created_by_id), (self.client_obj.pk, self.ops.pk))
        self.assertTrue(AuditLog.objects.filter(action="task.create", target=task.code, actor=self.ops).exists())

    def test_the_deadline_is_in_how_long_as_the_client_said_it(self):
        task = Task.objects.get(code=_json(self.create(self.good(deadline={"days": "2", "hours": "3", "minutes": ""})))["code"])
        expected = timezone.now() + timedelta(days=2, hours=3)
        self.assertLess(abs((task.deadline - expected).total_seconds()), 60)

    def test_blank_boxes_and_no_deadline_mean_no_deadline_and_zeros_too(self):
        for deadline in (None, {}, {"days": "", "hours": "", "minutes": ""}, {"days": "0", "hours": "0", "minutes": "0"}):
            task = Task.objects.get(code=_json(self.create(self.good(deadline=deadline)))["code"])
            self.assertIsNone(task.deadline, deadline)

    def test_a_deadline_that_is_not_one_is_refused_in_the_words_of_the_form(self):
        for deadline in ({"days": "-1"}, {"days": "x"}, {"hours": "1.5"}):
            answer = self.create(self.good(deadline=deadline))
            self.assertEqual((answer.status_code, _json(answer)["error"]), (400, "invalid"), deadline)
            self.assertIn("deadline", _json(answer)["fields"])
            self.assertTrue(_json(answer)["fields"]["deadline"][0])

    def test_the_boxes_that_are_wrong_are_named_and_nothing_is_made(self):
        before = Task.objects.count()
        for over, field in (({"title": "   "}, "title"), ({"client": 999999}, "client"), ({"priority": "evil"}, "priority"),
                            ({"title": "x" * 201}, "title")):
            answer = self.create(self.good(**over))
            self.assertEqual((answer.status_code, _json(answer)["error"]), (400, "invalid"), over)
            self.assertIn(field, _json(answer)["fields"], over)
        self.assertEqual(Task.objects.count(), before)

    def test_a_client_that_is_not_active_cannot_be_chosen(self):
        from .models import Client

        Client.objects.filter(pk=self.other_client.pk).update(is_active=False)
        answer = self.create(self.good(client=self.other_client.pk))
        self.assertEqual((answer.status_code, "client" in _json(answer)["fields"]), (400, True))

    def test_a_body_that_is_not_the_shape_is_refused_before_anything_is_read(self):
        before = Task.objects.count()
        for body in ({**self.good(), "client": "5"}, {**self.good(), "client": True}, {**self.good(), "title": 5},
                     {**self.good(), "messages": "1"}, {**self.good(), "messages": [True]}, {**self.good(), "files": [1.5]},
                     {**self.good(), "deadline": "soon"}, {**self.good(), "deadline": {"days": [1]}},
                     {**self.good(), "deadline": {"days": "1" * 7}}, {**self.good(), "word_count": "5"},
                     {**self.good(), "word_count": -1}, {**self.good(), "word_count": 10_000_001},
                     {**self.good(), "title": "a\x00b"}, {**self.good(), "from": "T" * 41}, {**self.good(), "description": "d" * 20001}):
            answer = self.create(body)
            self.assertEqual((answer.status_code, _json(answer)["error"]), (400, "bad_request"), str(body)[:60])
        self.assertEqual(Task.objects.count(), before)
        browser = DjangoClient()
        browser.force_login(self.ops)
        for kwargs in ({"data": "client=1", "content_type": "application/x-www-form-urlencoded"}, {"data": "[1]", "content_type": "application/json"}):
            self.assertEqual(browser.post(reverse("dashboard:v1_task_create"), **kwargs).status_code, 400)

    def test_the_word_count_and_the_two_switches_typed_on_the_form_are_kept(self):
        task = Task.objects.get(code=_json(self.create(self.good(word_count=1200, is_difficult=True, is_secondary_language=True)))["code"])
        self.assertEqual((task.word_count, task.word_count_state, task.is_difficult, task.is_secondary_language),
                         (1200, "confirmed", True, True))
        self.assertTrue(AuditLog.objects.filter(action="task.word_count.confirm", target=task.code, actor=self.ops).exists())

    def test_without_them_the_task_is_as_it_always_was(self):
        for over in ({}, {"word_count": None}, {"word_count": 0}, {"is_difficult": False}):
            task = Task.objects.get(code=_json(self.create(self.good(**over)))["code"])
            self.assertEqual((task.word_count_state, task.is_difficult, task.is_secondary_language), ("empty", False, False), over)

    def test_a_task_made_from_a_message_takes_it_and_its_ticked_files_and_claims_it(self):
        task = Task.objects.get(code=_json(self.create(self.good(messages=[self.heard.pk], files=[self.annex.pk])))["code"])
        self.heard.refresh_from_db()
        self.assertEqual((self.heard.task_id, self.heard.claimed_by_id), (task.pk, self.ops.pk))
        self.assertEqual(list(task.source_files.values_list("pk", flat=True)), [self.annex.pk])
        self.assertEqual(task.origin, "whatsapp")

    def test_a_file_of_another_message_is_not_walked_into_the_task(self):
        task = Task.objects.get(code=_json(self.create(self.good(messages=[self.heard.pk], files=[self.annex.pk, self.stranger.pk])))["code"])
        self.assertEqual(list(task.source_files.values_list("pk", flat=True)), [self.annex.pk])

    def test_a_message_of_another_client_cannot_be_joined_to_this_clients_task(self):
        before = Task.objects.count()
        answer = self.create(self.good(messages=[self.elsewhere.pk]))
        self.assertEqual((answer.status_code, _json(answer)["error"]), (400, "client_mismatch"))
        self.assertEqual(Task.objects.count(), before)
        self.elsewhere.refresh_from_db()
        self.assertEqual((self.elsewhere.task_id, self.elsewhere.claimed_by_id), (None, None))

    def test_a_message_this_person_may_not_read_does_not_join_the_task(self):
        from .models import Channel, InboundMessage

        sales_line = InboundMessage.objects.create(client=self.client_obj, channel=Channel.WHATSAPP, body="SALES ONLY",
                                                   sender_identity=CLIENT_PHONE, owner=self.sales)
        task = Task.objects.get(code=_json(self.create(self.good(messages=[sales_line.pk])))["code"])
        sales_line.refresh_from_db()
        self.assertEqual((sales_line.task_id, sales_line.claimed_by_id), (None, None))
        self.assertEqual(task.source_files.count(), 0)

    def test_a_new_request_on_the_same_files_repeats_the_old_ones_channel_and_leaves_it_alone(self):
        from .models import InboundMessage

        InboundMessage.objects.filter(pk=self.heard.pk).update(task=self.task)
        Task.objects.filter(pk=self.task.pk).update(origin="email")
        new = Task.objects.get(code=_json(self.create(self.good(**{"from": self.task.code})))["code"])
        self.heard.refresh_from_db()
        # The first task keeps its message; the new one reaches the files through ``source_files``.
        self.assertEqual(self.heard.task_id, self.task.pk)
        self.assertEqual(new.origin, "whatsapp")
        self.assertEqual(sorted(new.source_files.values_list("pk", flat=True)), sorted([self.contract.pk, self.annex.pk]))

class OpsHandOnFormAndTaskTests(_Switched):
    def test_the_new_task_form_goes_on_with_the_messages_the_files_and_the_task_it_repeats(self):
        self.turn_on(roles=["operation"])
        answer = self.page(self.ops, "dashboard:ops_task_new", message=7, messages="8, 9", files="3", **{"from": "TSK-00001"})
        self.assertEqual(answer.status_code, 302)
        self.assertEqual(answer["Location"], "/app/tasks/new?message=7&messages=8%2C9&files=3&from=TSK-00001")
        self.assertEqual(self.page(self.ops, "dashboard:ops_task_new")["Location"], "/app/tasks/new")

    def test_only_ids_and_a_task_code_go_along_and_everything_else_stays_behind(self):
        self.turn_on(roles=["operation"])
        for query in ({"message": "<script>"}, {"messages": "1;2"}, {"files": "1" * 401}, {"from": "//evil.example"},
                      {"from": "a:b"}, {"evil": "1"}, {"message": "7&x=1"}):
            answer = self.page(self.ops, "dashboard:ops_task_new", **query)
            self.assertEqual(answer["Location"], "/app/tasks/new", query)
