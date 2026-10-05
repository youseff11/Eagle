"""Phase 5, first screen: the translator's desk in the new interface.

Three things are pinned here.

* ``/api/v1/translator/home/`` shows a translator their own work and nothing of
  the client: the date they work to (never the client's), a code (never a name),
  no description, no number, no address. Every role is run against it.
* The page and the API list the same tasks, because both read
  ``services.translator_desk``, and a list costs the same number of queries
  however long it is.
* The switch (``AppSettings.new_ui``, ``dashboard/newui.py``) decides which page a
  person is sent to, can be turned back from the settings page with no deploy, and
  can never grant a role what the role does not have.
"""

import json
from datetime import timedelta
from unittest import mock

from django.db import connection
from django.test import Client as DjangoClient
from django.test.utils import CaptureQueriesContext
from django.urls import reverse
from django.utils import timezone

from . import clock, newui, services
from .forms import SettingsForm
from .models import AppSettings, RatingEvent, Role, Task, TaskStatus, User
from .tests_api_v1 import CLIENT_EMAIL, CLIENT_NAME, CLIENT_PHONE, IDENTITY_MARKERS, _json, _Site

DESK = "dashboard:v1_translator_home"
CLASSIC = "dashboard:translator_home"


def _make_task(site, *, translator=None, status=TaskStatus.IN_PROGRESS, title="Another doc", **fields):
    task = services.create_task(
        client=site.client_obj, title=title, created_by=site.ops,
        deadline=timezone.now() + timedelta(hours=5),
    )
    Task.objects.filter(pk=task.pk).update(
        translator=translator or site.tr, team_lead=site.lead, status=status, **fields
    )
    return Task.objects.get(pk=task.pk)


class _Desk(_Site):
    def setUp(self):
        super().setUp()
        # As if ``npm run build`` had run: a checkout that never built the app must not
        # change what these tests say about the switch.
        built = mock.patch("dashboard.spa.built_assets", return_value={"js": "x.js", "css": []})
        built.start()
        self.addCleanup(built.stop)

    def desk(self, user):
        browser = DjangoClient()
        if user is not None:
            browser.force_login(user)
        return browser.get(reverse(DESK))

    def classic(self, user, **query):
        browser = DjangoClient()
        browser.force_login(user)
        return browser.get(reverse(CLASSIC), query)

    def turn_on(self, roles=(), users=()):
        conf = AppSettings.load()
        conf.save()


class DeskApiTests(_Desk):
    def test_the_translator_and_the_admin_are_answered_everybody_else_is_refused(self):
        for user in (self.tr, self.admin):
            self.assertEqual(self.desk(user).status_code, 200, user.username)
        for user in (self.ops, self.lead, self.hr, self.reviewer, self.accounting, self.sales):
            answer = self.desk(user)
            self.assertEqual(answer.status_code, 403, user.username)
            self.assertEqual(_json(answer), {"ok": False, "error": "forbidden"})
        anonymous = self.desk(None)
        self.assertEqual(anonymous.status_code, 401)
        self.assertEqual(_json(anonymous), {"ok": False, "error": "auth"})

    def test_a_refusal_is_written_to_the_audit_log(self):
        from . import identity
        from .models import AuditLog

        before = AuditLog.objects.filter(action=identity.ACCESS_DENIED, actor=self.ops).count()
        self.desk(self.ops)
        self.assertEqual(AuditLog.objects.filter(action=identity.ACCESS_DENIED, actor=self.ops).count(), before + 1)

    def test_only_a_get_is_answered(self):
        browser = DjangoClient()
        browser.force_login(self.tr)
        self.assertEqual(browser.post(reverse(DESK)).status_code, 405)

    def test_the_answer_is_private_and_not_stored(self):
        self.assertEqual(self.desk(self.tr)["Cache-Control"], "private, no-store")

    def test_the_translator_sees_their_own_task_as_the_classic_page_shows_it(self):
        body = _json(self.desk(self.tr))
        row = next(item for item in body["open"] if item["code"] == self.task.code)
        self.assertEqual(row["title"], "Doc")
        self.assertEqual(row["status"]["value"], self.task.status)
        self.assertTrue(row["status"]["ar"] and row["status"]["en"] and row["status"]["tone"])
        # The client is a code, as ``label_for`` gives a translator.
        self.assertEqual(row["client"], self.client_obj.code)
        self.assertEqual(row["url"], f"/tasks/{self.task.code}/")
        self.assertIsInstance(body["rating"], float)

    def test_only_their_own_work_is_listed(self):
        other = User.objects.create_user("person_other_translator", password="pw",
                                         role=Role.TRANSLATOR, team_lead=self.lead)
        theirs = _make_task(self, translator=other, title="Not yours")
        body = self.desk(self.tr).content.decode("utf-8")
        self.assertNotIn(theirs.code, body)
        self.assertNotIn("Not yours", body)

    def test_the_date_is_the_translators_own_never_the_clients(self):
        mine = timezone.now() + timedelta(hours=2)
        clients = timezone.now() + timedelta(days=9)
        task = _make_task(self, translator_deadline=mine, deadline=clients)
        row = next(i for i in _json(self.desk(self.tr))["open"] if i["code"] == task.code)
        self.assertEqual(row["due"]["en"], clock.fmt12(mine, "en", "%Y-%m-%d"))
        self.assertEqual(row["due"]["ar"], clock.fmt12(mine, "ar", "%Y-%m-%d"))
        raw = self.desk(self.tr).content.decode("utf-8")
        self.assertNotIn(timezone.localtime(clients).strftime("%Y-%m-%d"), raw)

    def test_no_deadline_at_all_is_null_and_not_an_error(self):
        task = _make_task(self, translator_deadline=None)
        Task.objects.filter(pk=task.pk).update(deadline=None)
        row = next(i for i in _json(self.desk(self.tr))["open"] if i["code"] == task.code)
        self.assertIsNone(row["due"])
        self.assertEqual(row["due_state"], "none")

    def test_nothing_of_the_clients_identity_reaches_the_translator(self):
        # A task with a client who has a name, a number and an address, in the
        # states the desk lists: working, delivered, cancelled.
        _make_task(self, status=TaskStatus.DELIVERED, title="Finished one")
        _make_task(self, status=TaskStatus.CANCELLED, title="Dropped one")
        raw = self.desk(self.tr).content.decode("utf-8")
        for marker in IDENTITY_MARKERS + (CLIENT_NAME, CLIENT_PHONE, CLIENT_EMAIL):
            self.assertNotIn(marker, raw, marker)
        # The control: the admin, who is allowed to know, gets the name when a
        # task of theirs is listed - so the sweep above is not passing for lack of data.
        mine = _make_task(self, translator=self.admin, title="Admin's own")
        admin_raw = self.desk(self.admin).content.decode("utf-8")
        self.assertIn(mine.code, admin_raw)
        self.assertIn(CLIENT_NAME, admin_raw)

    def test_the_description_and_the_notes_are_not_part_of_the_answer(self):
        Task.objects.filter(pk=self.task.pk).update(description="PRIVATE BRIEF " + CLIENT_NAME)
        self.assertNotIn("PRIVATE BRIEF", self.desk(self.tr).content.decode("utf-8"))

    def test_the_closed_list_and_the_history_are_capped_and_newest_first(self):
        for index in range(services.DESK_DONE + 5):
            _make_task(self, status=TaskStatus.DELIVERED, title=f"Done {index}")
        for index in range(services.DESK_RATING_EVENTS + 4):
            RatingEvent.objects.create(user=self.tr, delta="-0.125", reason_ar=f"سبب {index}", reason_en=f"Reason {index}")
        body = _json(self.desk(self.tr))
        self.assertEqual(len(body["done"]), services.DESK_DONE)
        self.assertEqual(len(body["rating_events"]), services.DESK_RATING_EVENTS)
        self.assertEqual(body["rating_events"][0]["reason_en"], f"Reason {services.DESK_RATING_EVENTS + 3}")
        self.assertEqual(body["rating_events"][0]["delta"], "-0.125")

    def test_only_a_task_in_progress_can_ask_for_more_time(self):
        waiting = _make_task(self, status=TaskStatus.UNDER_REVIEW, title="In review")
        self.task.refresh_from_db()
        self.assertEqual(self.task.status, TaskStatus.IN_PROGRESS)
        rows = {i["code"]: i for i in _json(self.desk(self.tr))["open"]}
        self.assertTrue(rows[self.task.code]["can_ask_more_time"])
        self.assertFalse(rows[waiting.code]["can_ask_more_time"])

    def test_a_list_costs_the_same_queries_however_long_it_is(self):
        def cost():
            browser = DjangoClient()
            browser.force_login(self.tr)
            browser.get(reverse(DESK))  # warm the session and the settings row
            with CaptureQueriesContext(connection) as queries:
                self.assertEqual(browser.get(reverse(DESK)).status_code, 200)
            return len(queries)

        few = cost()
        for index in range(12):
            _make_task(self, title=f"More {index}")
        self.assertEqual(cost(), few)


class SwitchTests(_Desk):
    def test_switched_on_for_the_role_the_classic_page_hands_them_on(self):
        self.turn_on(roles=["translator"])
        answer = self.classic(self.tr)
        self.assertEqual(answer.status_code, 302)
        self.assertEqual(answer["Location"], "/app/translator")

    def test_me_lists_the_screens_of_that_persons_role_and_the_admins_overview(self):
        self.assertEqual(_json(self.get(self.tr, "v1_me"))["screens"], ["translator_home", "attendance", "leave", "performance", "chats"])
        self.assertEqual(_json(self.get(self.ops, "v1_me"))["screens"], ["operation", "attendance", "leave", "performance", "chats"])
        self.assertEqual(_json(self.get(self.lead, "v1_me"))["screens"], ["lead", "reviewer", "attendance", "leave", "performance", "chats"])
        self.assertEqual(_json(self.get(self.sales, "v1_me"))["screens"], ["sales", "attendance", "leave", "performance", "chats"])
        self.assertEqual(_json(self.get(self.reviewer, "v1_me"))["screens"], ["reviewer", "attendance", "leave", "performance", "chats"])
        self.assertEqual(_json(self.get(self.accounting, "v1_me"))["screens"], ["accounts", "attendance", "leave", "performance", "chats"])
        self.assertEqual(_json(self.get(self.hr, "v1_me"))["screens"], ["hr", "attendance", "leave", "performance", "chats"])
        # The admin oversees: the panel, the money, HR, the operation, and not another role's own desk.
        self.assertEqual(_json(self.get(self.admin, "v1_me"))["screens"], ["admin", "accounts", "hr", "operation", "chats"])

    def test_the_data_does_not_depend_on_the_switch(self):
        # The switch decides the page. Who may see the work is the role: a
        # translator with it off, typing the new address by hand, sees exactly
        # what their own classic page shows them.
        self.assertEqual(self.desk(self.tr).status_code, 200)
        self.turn_on(roles=["translator"])
        self.assertEqual(self.desk(self.tr).status_code, 200)


class HandOnOnlyWhenNothingStandsInTheWayTests(_Desk):
    """The classic page hands a switched-on person to the new app unless something is waiting
    that only the classic interface can show - or the new app is not there to receive them."""

    def setUp(self):
        super().setUp()
        self.turn_on(roles=["translator"])

    def test_the_control_with_nothing_in_the_way_it_hands_on(self):
        self.assertEqual(self.classic(self.tr).status_code, 302)

    def test_an_assignment_waiting_for_an_answer_no_longer_holds_them_back_the_new_app_shows_it_itself(self):
        from .models import Assignment, AssignmentStatus

        Assignment.objects.filter(assignee=self.tr).delete()
        task = _make_task(self, status=TaskStatus.LEAD_ACCEPTED, title="Needs an answer")
        services.assign_to_translator(task, self.tr, self.lead)
        self.assertTrue(Assignment.objects.filter(assignee=self.tr, status=AssignmentStatus.PENDING).exists())
        # It was the classic page's job alone to show the accept screen; the new app draws it over any page.
        self.assertEqual(self.classic(self.tr).status_code, 302)

    def test_an_answered_assignment_no_longer_holds_them_back(self):
        from .models import Assignment, AssignmentStatus

        Assignment.objects.filter(assignee=self.tr).update(status=AssignmentStatus.ACCEPTED)
        self.assertEqual(self.classic(self.tr).status_code, 302)


class HandOffsDoNotBounceTests(_Desk):
    """``/`` is the app's, for everybody; the classic landing page is only for a checkout that never built it."""

    def test_every_role_lands_in_the_app_with_and_without_the_old_parameter(self):
        for user in (self.admin, self.ops, self.hr, self.reviewer, self.accounting, self.sales, self.lead, self.tr):
            browser = DjangoClient()
            browser.force_login(user)
            self.assertEqual(browser.get("/")["Location"], "/app/", user.username)
            self.assertEqual(browser.get("/?classic=1")["Location"], "/app/", user.username)
