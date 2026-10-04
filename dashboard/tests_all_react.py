"""The whole site is the app (2026-10-04): there is no per-screen switch, no way back to the classic pages, and the menu is the role's.

Held here:

* what ``newui`` says each person has, with no setting able to change it (a stale ``AppSettings.new_ui`` is ignored);
* a classic page the app has a screen for always hands on, with ``?classic=1`` or without, and nobody is left on a classic page
  because a check-in screen is due (the app draws it);
* a classic page view added later must hand on or be listed here as left behind on purpose (a public page, a form's POST, an
  OAuth step), so the day the classic pages are deleted nothing is found still serving one;
* the settings page carries no rollout card, and ``/me/`` carries what the menu's lines answer to.
"""

import ast
import re
from pathlib import Path
from unittest import mock

from django.conf import settings
from django.test import Client as DjangoClient
from django.urls import reverse

from . import newui
from .models import AppSettings, Role, User
from .tests_api_v1 import _json, _Site


class _Built(_Site):
    """The app counts as built, as it is in production."""

    def setUp(self):
        super().setUp()
        built = mock.patch("dashboard.newui.spa.built_assets", return_value={"js": "x.js", "css": []})
        built.start()
        self.addCleanup(built.stop)
        User.objects.update(attendance_enabled=False)
        self.flagged = User.objects.create_user("person_flagged", password="pw", role=Role.OPERATION, attendance_manager=True)

    def classic(self, user, name, args=None, **query):
        browser = DjangoClient()
        browser.force_login(user)
        return browser.get(reverse(f"dashboard:{name}", args=args), query)


class WhatEachPersonHasTests(_Built):
    def keys(self, user):
        return newui.enabled_keys(user)

    def test_a_role_has_its_own_screens_then_the_attendance_leave_and_chats(self):
        self.assertEqual(self.keys(self.tr), ["translator_home", "attendance", "leave", "chats"])
        self.assertEqual(self.keys(self.ops), ["operation", "attendance", "leave", "chats"])
        self.assertEqual(self.keys(self.sales), ["sales", "attendance", "leave", "chats"])
        self.assertEqual(self.keys(self.accounting), ["accounts", "attendance", "leave", "chats"])
        self.assertEqual(self.keys(self.hr), ["hr", "attendance", "leave", "chats"])
        self.assertEqual(self.keys(self.reviewer), ["reviewer", "attendance", "leave", "chats"])

    def test_a_team_leader_also_has_the_candidate_tests_they_may_mark(self):
        self.assertEqual(self.keys(self.lead), ["lead", "reviewer", "attendance", "leave", "chats"])

    def test_the_admin_has_the_panel_the_money_hr_and_the_operation_and_not_another_roles_desk(self):
        self.assertEqual(self.keys(self.admin), ["admin", "accounts", "hr", "operation", "attendance", "chats"])

    def test_a_person_who_manages_attendance_has_the_hr_screen_and_nobody_else_of_another_role_does(self):
        self.assertIn("hr", self.keys(self.flagged))
        for user in (self.ops, self.tr, self.lead, self.sales, self.accounting, self.reviewer):
            self.assertNotIn("hr", self.keys(user), user.username)

    def test_nobody_has_a_screen_that_is_not_theirs(self):
        for user in (self.ops, self.lead, self.tr, self.hr, self.reviewer, self.accounting, self.sales):
            for key, screen in newui.SCREENS.items():
                if key not in self.keys(user):
                    self.assertFalse(newui.enabled(user, key), (user.username, key))

    def test_no_setting_changes_it(self):
        conf = AppSettings.load()
        for broken in ({}, [], "text", 5, {"translator_home": {"roles": [], "users": []}}, {"hr": {"roles": ["hr"], "users": [self.tr.pk]}}):
            conf.new_ui = broken
            conf.save()
            self.assertEqual(self.keys(self.tr), ["translator_home", "attendance", "leave", "chats"], repr(broken))
            self.assertFalse(newui.enabled(self.tr, "hr"), repr(broken))

    def test_the_machinery_of_the_switches_is_gone(self):
        for name in ("config", "default_for", "pilot_candidates", "wants_classic", "CLASSIC_PARAM", "DEFAULT"):
            self.assertFalse(hasattr(newui, name), name)
        self.assertFalse(hasattr(newui.SCREENS["admin"], "admin_default"))
        self.assertFalse(hasattr(newui.SCREENS["admin"], "eligible_roles"))


class ClassicPagesAlwaysHandOnTests(_Built):
    def test_a_classic_page_hands_on_with_or_without_the_old_parameter_and_whatever_is_stored(self):
        conf = AppSettings.load()
        conf.new_ui = {key: {"roles": [], "users": []} for key in newui.SCREENS}
        conf.save()
        for who, name, target in (
            (self.ops, "ops_inbox", "/app/inbox"), (self.ops, "ops_tasks", "/app/tasks"), (self.lead, "lead_home", "/app/lead"),
            (self.tr, "translator_home", "/app/translator"), (self.hr, "hr_recruitment", "/app/hr/recruitment"),
            (self.accounting, "accounts_overview", "/app/accounts"), (self.sales, "client_list", "/app/clients"),
            (self.reviewer, "reviewer_tests", "/app/reviewer/tests"), (self.admin, "admin_overview", "/app/admin"),
            (self.tr, "my_leave", "/app/leave"), (self.tr, "my_attendance", "/app/attendance"), (self.ops, "ops_chats", "/app/chats"),
        ):
            for query in ({}, {"classic": "1"}):
                answer = self.classic(who, name, **query)
                self.assertEqual((answer.status_code, answer["Location"]), (302, target), (name, query))

    def test_the_notifications_page_hands_on_too_and_is_not_marked_read_by_the_classic_page(self):
        from .models import Notification

        Notification.objects.create(user=self.ops, title_ar="x", title_en="x", body_ar="y", body_en="y")
        answer = self.classic(self.ops, "notifications")
        self.assertEqual((answer.status_code, answer["Location"]), (302, "/app/notifications"))
        self.assertTrue(Notification.objects.filter(user=self.ops, is_read=False).exists())

    def test_the_admin_is_handed_on_from_the_other_roles_pages_to_the_apps_home(self):
        for name in ("lead_home", "lead_translators"):
            self.assertEqual(self.classic(self.admin, name)["Location"], "/app/", name)
        self.assertEqual(self.classic(self.admin, "translator_home")["Location"], "/app/translator")

    def test_the_admin_task_page_is_the_apps_too(self):
        answer = self.classic(self.admin, "task_detail", [self.task.code])
        self.assertEqual((answer.status_code, answer["Location"]), (302, f"/app/tasks/{self.task.code}"))

    def test_a_form_already_open_is_still_answered_where_it_is(self):
        browser = DjangoClient()
        browser.force_login(self.lead)
        answer = browser.post(reverse("dashboard:task_requirement", args=[self.task.code]), {"kind": "rule", "text": "Posted"})
        self.assertEqual(answer.status_code, 302)
        self.assertFalse(answer["Location"].startswith("/app/"))

    def test_without_a_built_app_the_classic_pages_are_served_so_nobody_is_sent_to_a_503(self):
        with mock.patch("dashboard.newui.spa.built_assets", return_value=None):
            self.assertEqual(self.classic(self.ops, "ops_inbox").status_code, 200)
            self.assertEqual(self.classic(self.tr, "translator_home").status_code, 200)

    def test_a_due_check_in_does_not_keep_anybody_on_a_classic_page(self):
        User.objects.filter(pk=self.tr.pk).update(attendance_enabled=True)
        with mock.patch("dashboard.attendance.gate_for", return_value={"kind": "check_in"}):
            self.assertEqual(self.classic(self.tr, "translator_home")["Location"], "/app/translator")
            browser = DjangoClient()
            browser.force_login(self.tr)
            self.assertEqual(browser.get("/app/").status_code, 200)


class EveryClassicPageViewIsAccountedForTests(_Site):
    """A classic page view added later hands on, or is listed here as left behind on purpose."""

    #: Views with no page to hand on: public pages, the sign-in, files, health, and the steps of Google's sign-in.
    NOT_PAGES = {
        "login_view", "logout_view", "healthz", "privacy", "terms", "data_deletion", "serve_file",
        "google_connect", "google_callback", "google_sync", "google_disconnect",
    }

    def test_every_view_that_has_a_classic_url_hands_on_or_is_a_form_post_or_is_listed(self):
        base = Path(settings.BASE_DIR) / "dashboard"
        urls = (base / "urls.py").read_text(encoding="utf-8")
        source = (base / "views.py").read_text(encoding="utf-8")
        tree = ast.parse(source)
        bodies = {node.name: ast.get_source_segment(source, node) for node in tree.body if isinstance(node, ast.FunctionDef)}
        seen, loose = set(), []
        for route, name in re.findall(r'path\(\s*"([^"]*)",\s*views\.(\w+)', urls, flags=re.S):
            if name in seen or route.startswith(("api/", "webhooks")) or name in self.NOT_PAGES:
                continue
            seen.add(name)
            body = bodies.get(name, "")
            if "hand_on" in body or "spa.built_assets" in body:
                continue
            # A view that has no page of its own answers a form: it is `@require_POST`, or it redirects every GET.
            if "require_POST" in source[: source.index(f"def {name}(")].rsplit("\n\n", 1)[-1] or "request.method" in body:
                continue
            loose.append(name)
        self.assertEqual(sorted(loose), sorted(self.POST_ONLY), "a classic page that neither hands on nor is a form's answer")

    #: Views that answer a form and show no page. Listed, so that a new one is a decision.
    POST_ONLY = []
