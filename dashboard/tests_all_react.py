"""The whole site is the app (2026-10-04): there is no per-screen switch and the menu is the role's.

Held here: what ``newui`` says each person has. The classic addresses that redirect into the app are held in ``tests_legacy.py``.
"""

from unittest import mock

from . import newui
from .models import Role, User
from .tests_api_v1 import _Site


class WhatEachPersonHasTests(_Site):
    def setUp(self):
        super().setUp()
        User.objects.update(attendance_enabled=False)
        self.flagged = User.objects.create_user("person_flagged", password="pw", role=Role.OPERATION, attendance_manager=True)

    def keys(self, user):
        return newui.enabled_keys(user)

    def test_a_role_has_its_own_screens_then_the_attendance_leave_and_chats(self):
        self.assertEqual(self.keys(self.tr), ["translator_home", "attendance", "leave", "performance", "chats"])
        self.assertEqual(self.keys(self.ops), ["operation", "attendance", "leave", "performance", "chats"])
        self.assertEqual(self.keys(self.sales), ["sales", "attendance", "leave", "performance", "chats"])
        self.assertEqual(self.keys(self.accounting), ["accounts", "attendance", "leave", "performance", "chats"])
        self.assertEqual(self.keys(self.hr), ["hr", "attendance", "leave", "performance", "chats"])
        self.assertEqual(self.keys(self.reviewer), ["reviewer", "attendance", "leave", "performance", "chats"])

    def test_a_team_leader_also_has_the_candidate_tests_they_may_mark(self):
        self.assertEqual(self.keys(self.lead), ["lead", "reviewer", "attendance", "leave", "performance", "chats"])

    def test_the_admin_has_the_panel_the_money_hr_and_the_operation_and_not_another_roles_desk(self):
        self.assertEqual(self.keys(self.admin), ["admin", "accounts", "hr", "operation", "attendance", "chats"])

    def test_the_performance_board_is_every_employees_and_the_admin_reaches_it_through_the_hr_screen(self):
        # Seven roles carry the board in their own menu; the admin's menu carries HR, whose people section has the same line.
        for user in (self.ops, self.lead, self.tr, self.hr, self.reviewer, self.accounting, self.sales, self.flagged):
            self.assertIn("performance", self.keys(user), user.username)
        self.assertNotIn("performance", self.keys(self.admin))
        self.assertTrue(newui.SCREENS["performance"].allows(self.admin))
        self.assertEqual(newui.SCREENS["performance"].path, "/hr/performance")

    def test_a_person_who_manages_attendance_has_the_hr_screen_and_nobody_else_of_another_role_does(self):
        self.assertIn("hr", self.keys(self.flagged))
        for user in (self.ops, self.tr, self.lead, self.sales, self.accounting, self.reviewer):
            self.assertNotIn("hr", self.keys(user), user.username)

    def test_nobody_has_a_screen_that_is_not_theirs(self):
        for user in (self.ops, self.lead, self.tr, self.hr, self.reviewer, self.accounting, self.sales):
            for key, screen in newui.SCREENS.items():
                if key not in self.keys(user):
                    self.assertFalse(screen.allows(user), (user.username, key))

    def test_a_person_who_is_not_signed_in_has_no_screen(self):
        from django.contrib.auth.models import AnonymousUser

        self.assertEqual(newui.enabled_keys(AnonymousUser()), [])

    def test_the_machinery_of_the_switches_is_gone(self):
        for name in (
            "config", "default_for", "pilot_candidates", "wants_classic", "CLASSIC_PARAM", "DEFAULT", "enabled", "hand_on",
            "app_url", "gate_in_app",
        ):
            self.assertFalse(hasattr(newui, name), name)
        self.assertFalse(hasattr(newui.SCREENS["admin"], "classic"))
        self.assertFalse(hasattr(newui.SCREENS["admin"], "redirects"))

    def test_me_carries_the_screens_in_the_menu(self):
        self.client.force_login(self.tr)
        with mock.patch("dashboard.spa.built_assets", return_value={"js": "x.js", "css": []}):
            body = self.client.get("/api/v1/me/").json()
        self.assertEqual(body["screens"], ["translator_home", "attendance", "leave", "performance", "chats"])
