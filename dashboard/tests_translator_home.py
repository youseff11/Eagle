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
        built = mock.patch("dashboard.newui.spa.built_assets", return_value={"js": "x.js", "css": []})
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
        conf.new_ui = {"translator_home": {"roles": list(roles), "users": list(users)}}
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

    def test_the_page_and_the_api_list_the_same_work(self):
        _make_task(self, status=TaskStatus.DELIVERED, title="Closed lately")
        outsider = User.objects.create_user("person_other_translator", password="pw", role=Role.TRANSLATOR)
        stranger = _make_task(self, translator=outsider, title="Somebody else's")
        body = _json(self.desk(self.tr))
        page = self.classic(self.tr, classic=1).content.decode("utf-8")
        listed = [i["code"] for i in body["open"]] + [i["code"] for i in body["done"]]
        self.assertGreaterEqual(len(listed), 2)
        for code in listed:
            self.assertIn(code, page)
        self.assertNotIn(stranger.code, page)
        self.assertNotIn(stranger.code, json.dumps(body))

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
    def test_nothing_set_means_the_admin_alone(self):
        self.assertEqual(AppSettings.load().new_ui, {})
        self.assertTrue(newui.enabled(self.admin, "translator_home"))
        self.assertFalse(newui.enabled(self.tr, "translator_home"))

    def test_the_classic_page_is_what_a_translator_gets_until_it_is_switched_on(self):
        self.assertEqual(self.classic(self.tr).status_code, 200)

    def test_switched_on_for_the_role_the_classic_page_hands_them_on(self):
        self.turn_on(roles=["translator"])
        answer = self.classic(self.tr)
        self.assertEqual(answer.status_code, 302)
        self.assertEqual(answer["Location"], "/app/translator")

    def test_the_classic_page_still_opens_by_name(self):
        self.turn_on(roles=["translator", "admin"])
        for user in (self.tr, self.admin):
            answer = self.classic(user, classic=1)
            self.assertEqual(answer.status_code, 200, user.username)
            self.assertTemplateUsed(answer, "translator/home.html")
        # Only the exact value: it is a way back, not a way to guess.
        self.assertEqual(self.classic(self.tr, classic="true").status_code, 302)
        self.assertEqual(self.classic(self.tr, classic="0").status_code, 302)

    def test_one_person_can_be_tried_before_the_role(self):
        other = User.objects.create_user("person_other_translator", password="pw", role=Role.TRANSLATOR)
        self.turn_on(roles=[], users=[self.tr.pk])
        self.assertEqual(self.classic(self.tr).status_code, 302)
        self.assertEqual(self.classic(other).status_code, 200)

    def test_switched_off_again_the_page_comes_back_at_once(self):
        self.turn_on(roles=["translator"])
        self.assertEqual(self.classic(self.tr).status_code, 302)
        self.turn_on(roles=[])
        self.assertEqual(self.classic(self.tr).status_code, 200)
        self.assertEqual(self.classic(self.admin).status_code, 200)

    def test_the_switch_cannot_give_a_role_what_the_role_does_not_have(self):
        # Hand-edited JSON naming a role and a person the screen is not for.
        self.turn_on(roles=["hr", "operation", "translator"], users=[self.hr.pk, self.ops.pk])
        for user in (self.hr, self.ops, self.reviewer, self.accounting, self.sales, self.lead):
            self.assertFalse(newui.enabled(user, "translator_home"), user.username)
            self.assertEqual(newui.enabled_keys(user), [], user.username)
        # And what is not a role of the screen is dropped on the way in.
        self.assertEqual(
            newui.config(AppSettings.load(), "translator_home")["roles"], ["translator"]
        )

    def test_unreadable_settings_fall_back_to_the_admin_alone_never_to_everybody(self):
        for broken in ([], "text", 5, {"translator_home": "yes"}, {"translator_home": {"roles": "translator"}},
                       {"translator_home": [1, 2]}):
            conf = AppSettings.load()
            conf.new_ui = broken
            conf.save()
            self.assertFalse(newui.enabled(self.tr, "translator_home"), repr(broken))
            self.assertTrue(newui.enabled(self.admin, "translator_home"), repr(broken))
        # The column cannot hold null, but a value read before it is saved can be one.
        unsaved = AppSettings(new_ui=None)
        self.assertFalse(newui.enabled(self.tr, "translator_home", unsaved))
        self.assertTrue(newui.enabled(self.admin, "translator_home", unsaved))

    def test_bad_ids_in_the_list_are_ignored(self):
        self.turn_on(roles=[], users=["7", True, -1, 0, None, 2.5, self.tr.pk])
        self.assertEqual(newui.config(AppSettings.load(), "translator_home")["users"], [self.tr.pk])

    def test_me_lists_the_screens_that_are_on_for_that_person_only(self):
        self.turn_on(roles=["translator"])
        mine = _json(self.get(self.tr, "v1_me"))["screens"]
        self.assertEqual(mine, ["translator_home"])
        for user in (self.ops, self.hr, self.sales):
            self.assertEqual(_json(self.get(user, "v1_me"))["screens"], [], user.username)

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

    def test_a_check_in_or_check_out_or_extra_time_screen_keeps_them_on_the_classic_page(self):
        for kind in ("check_in", "check_out", "extra"):
            with mock.patch("dashboard.newui.attendance.gate_for", return_value={"kind": kind}):
                answer = self.classic(self.tr)
            self.assertEqual(answer.status_code, 200, kind)
            self.assertTemplateUsed(answer, "translator/home.html")

    def test_an_assignment_waiting_for_an_answer_keeps_them_on_the_classic_page(self):
        from .models import Assignment, AssignmentStatus

        Assignment.objects.filter(assignee=self.tr).delete()
        task = _make_task(self, status=TaskStatus.LEAD_ACCEPTED, title="Needs an answer")
        services.assign_to_translator(task, self.tr, self.lead)
        self.assertTrue(Assignment.objects.filter(assignee=self.tr, status=AssignmentStatus.PENDING).exists())
        self.assertEqual(self.classic(self.tr).status_code, 200)

    def test_a_missing_build_keeps_them_on_the_classic_page_instead_of_a_bare_503(self):
        with mock.patch("dashboard.newui.spa.built_assets", return_value=None):
            self.assertEqual(self.classic(self.tr).status_code, 200)

    def test_an_answered_assignment_no_longer_holds_them_back(self):
        from .models import Assignment, AssignmentStatus

        Assignment.objects.filter(assignee=self.tr).update(status=AssignmentStatus.ACCEPTED)
        self.assertEqual(self.classic(self.tr).status_code, 302)


class HandOffsDoNotBounceTests(_Desk):
    """The new app sends a person to the classic pages for what only they can show.

    The check-in screen, an assignment with a 60-second clock and a ringing call
    live in the classic interface. If ``/`` handed a translator on to the new
    app, and the new app handed them back to ``/``, they would go back and forth
    and never see the screen that decides whether they lose the assignment.
    """

    def test_the_way_into_the_classic_interface_ends_on_the_classic_page(self):
        self.turn_on(roles=["translator"])
        browser = DjangoClient()
        browser.force_login(self.tr)
        answer = browser.get("/?classic=1", follow=True)
        self.assertEqual(answer.redirect_chain, [("/translator/?classic=1", 302)])
        self.assertEqual(answer.status_code, 200)
        self.assertTemplateUsed(answer, "translator/home.html")

    def test_without_it_a_translator_who_has_the_switch_lands_in_the_new_app(self):
        self.turn_on(roles=["translator"])
        browser = DjangoClient()
        browser.force_login(self.tr)
        answer = browser.get("/", follow=True)
        self.assertEqual(answer.redirect_chain[-1], ("/app/translator", 302))

    def test_every_role_still_lands_where_it_did_with_and_without_the_parameter(self):
        landing = {
            self.admin: "dashboard:admin_overview", self.ops: "dashboard:ops_inbox",
            self.hr: "dashboard:hr_recruitment", self.reviewer: "dashboard:reviewer_tests",
            self.accounting: "dashboard:accounts_overview", self.sales: "dashboard:client_list",
            self.lead: "dashboard:lead_home",
        }
        for user, name in landing.items():
            browser = DjangoClient()
            browser.force_login(user)
            plain = browser.get("/")
            self.assertEqual(plain["Location"], reverse(name), user.username)
            kept = browser.get("/?classic=1")
            self.assertEqual(kept["Location"], reverse(name) + "?classic=1", user.username)

    def test_the_check_in_hand_off_lands_on_a_classic_page_even_with_the_switch_on(self):
        self.turn_on(roles=["translator", "admin"])
        browser = DjangoClient()
        browser.force_login(self.tr)
        with mock.patch("dashboard.spa.attendance.gate_for", return_value={"kind": "check_in"}):
            first = browser.get("/app/translator")
        self.assertEqual(first["Location"], "/?classic=1")
        landed = browser.get(first["Location"], follow=True)
        self.assertEqual(landed.status_code, 200)
        self.assertTemplateUsed(landed, "translator/home.html")


class SettingsSectionTests(_Desk):
    def post(self, user, skip_section=False, **changes):
        form = SettingsForm(instance=AppSettings.load())
        data = {}
        for name in form.fields:
            if skip_section and name.startswith("newui_"):
                continue
            value = form[name].value()
            if value in (None, False, ""):
                continue
            data[name] = "on" if value is True else (
                [str(v) for v in value] if isinstance(value, (list, tuple, set)) else str(value)
            )
        data.update(changes)
        browser = DjangoClient()
        browser.force_login(user)
        return browser.post(reverse("dashboard:admin_settings"), data)

    def test_the_settings_page_carries_the_section_and_the_marker(self):
        browser = DjangoClient()
        browser.force_login(self.admin)
        page = browser.get(reverse("dashboard:admin_settings")).content.decode("utf-8")
        self.assertIn('id="s-newui"', page)
        self.assertIn('name="newui_present_translator_home"', page)
        self.assertIn('name="newui_present_chats"', page)
        self.assertIn('name="newui_chats_roles"', page)
        self.assertIn('name="newui_translator_home_roles"', page)
        self.assertIn('name="newui_translator_home_users"', page)

    def test_the_admin_switches_a_screen_on_for_a_role_and_one_person(self):
        answer = self.post(
            self.admin, newui_present_translator_home="1",
            newui_translator_home_roles=["admin", "translator"],
            newui_translator_home_users=[str(self.tr.pk)],
        )
        self.assertEqual(answer.status_code, 302)
        self.assertEqual(
            AppSettings.load().new_ui,
            {"translator_home": {"roles": ["admin", "translator"], "users": [self.tr.pk]}},
        )
        self.assertTrue(newui.enabled(self.tr, "translator_home"))

    def test_unticking_everything_sends_everybody_back_to_the_classic_page(self):
        self.turn_on(roles=["translator"])
        self.post(self.admin, newui_present_translator_home="1", newui_translator_home_roles=[], newui_translator_home_users=[])
        self.assertEqual(self.classic(self.tr).status_code, 200)
        self.assertEqual(self.classic(self.admin).status_code, 200)

    def test_a_post_that_never_carried_the_section_leaves_the_switch_alone(self):
        self.turn_on(roles=["translator"])
        # The same post as every other test here, minus the section: as an old
        # page, or the "save and test" button's partial post, would send it.
        answer = self.post(self.admin, poll_ms="4000", skip_section=True)
        self.assertEqual(answer.status_code, 302)
        self.assertEqual(AppSettings.load().poll_ms, 4000)
        self.assertEqual(AppSettings.load().new_ui["translator_home"]["roles"], ["translator"])

    def test_a_role_the_screen_is_not_for_is_refused_and_nothing_is_saved(self):
        for bad in ({"newui_translator_home_roles": ["hr"]},
                    {"newui_translator_home_roles": ["translator", "sales"]},
                    {"newui_translator_home_users": [str(self.hr.pk)]},
                    {"newui_translator_home_users": [str(self.admin.pk)]}):
            answer = self.post(self.admin, newui_present_translator_home="1", **bad)
            self.assertEqual(answer.status_code, 200, bad)
            self.assertEqual(AppSettings.load().new_ui, {}, bad)

    def test_only_the_admin_can_change_it(self):
        for user in (self.ops, self.lead, self.tr, self.hr, self.sales):
            answer = self.post(user, newui_present_translator_home="1", newui_translator_home_roles=["translator"])
            self.assertEqual(answer.status_code, 403, user.username)
        self.assertEqual(AppSettings.load().new_ui, {})

    def test_a_deactivated_person_cannot_be_picked(self):
        User.objects.filter(pk=self.tr.pk).update(is_active=False)
        answer = self.post(self.admin, newui_present_translator_home="1", newui_translator_home_users=[str(self.tr.pk)])
        self.assertEqual(answer.status_code, 200)
        self.assertEqual(AppSettings.load().new_ui, {})

    def test_a_refused_post_says_so_and_shows_the_error_beside_the_field(self):
        User.objects.filter(pk=self.tr.pk).update(is_active=False)
        answer = self.post(self.admin, newui_present_translator_home="1", poll_ms="4000",
                           newui_translator_home_users=[str(self.tr.pk)])
        self.assertEqual(answer.status_code, 200)
        page = answer.content.decode("utf-8")
        self.assertIn("errorlist", page)
        self.assertIn("اتحفظش حاجة", page)
        self.assertNotEqual(AppSettings.load().poll_ms, 4000)

    def test_a_change_of_the_switch_is_written_to_the_audit_log_in_full(self):
        from .models import AuditLog

        self.post(self.admin, newui_present_translator_home="1", newui_translator_home_roles=["admin", "translator"],
                  newui_translator_home_users=[])
        row = AuditLog.objects.filter(action="settings.new_ui", actor=self.admin).get()
        self.assertEqual(json.loads(row.detail), {"translator_home": {"roles": ["admin", "translator"], "users": []}})

    def test_a_post_that_changes_something_else_writes_no_switch_row(self):
        from .models import AuditLog

        self.post(self.admin, poll_ms="4000", skip_section=True)
        self.assertFalse(AuditLog.objects.filter(action="settings.new_ui").exists())

    def test_a_screen_whose_row_was_not_posted_is_left_alone(self):
        conf = AppSettings.load()
        conf.new_ui = {"chats": {"roles": ["operation"], "users": []}}
        conf.save()
        self.post(self.admin, newui_present_translator_home="1", newui_translator_home_roles=["admin"],
                  newui_translator_home_users=[])
        saved = AppSettings.load().new_ui
        self.assertEqual(saved["chats"], {"roles": ["operation"], "users": []})
        self.assertEqual(saved["translator_home"], {"roles": ["admin"], "users": []})

    def test_each_screen_is_saved_on_its_own_marker(self):
        self.turn_on(roles=["translator"])
        self.post(self.admin, newui_present_chats="1", newui_chats_roles=["operation", "hr"], newui_chats_users=[])
        saved = AppSettings.load().new_ui
        self.assertEqual(saved["chats"], {"roles": ["operation", "hr"], "users": []})
        self.assertEqual(saved["translator_home"], {"roles": ["translator"], "users": []})

    def test_a_role_the_other_screen_is_not_for_is_refused_for_this_one(self):
        # "translator" is for the translator desk and for the chats; "accounting" is for chats and not for the desk.
        answer = self.post(self.admin, newui_present_translator_home="1", newui_translator_home_roles=["accounting"])
        self.assertEqual(answer.status_code, 200)
        self.assertNotIn("translator_home", AppSettings.load().new_ui)

