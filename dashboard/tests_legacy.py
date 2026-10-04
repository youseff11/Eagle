"""The classic interface is gone (2026-10-04); its addresses are kept as redirects into the app (``dashboard/legacy.py``).

Held here:

* every old address and URL name answers a signed-in person with a redirect to the same thing under ``/app``, and a person who is
  not signed in is sent to sign in first;
* what of the query goes along (and what never does: a long value, markup, an unknown state);
* a page that was one role's own sends anybody else to the app's home;
* what is not left: no classic template, no classic view, no switch, and no address that still renders a classic page.
"""

from pathlib import Path
from unittest import mock

from django.conf import settings
from django.test import Client as DjangoClient
from django.urls import resolve, reverse

from . import identity, legacy
from .models import Role, User
from .tests_api_v1 import _Site


class _Door(_Site):
    def go(self, who, name, args=None, **query):
        browser = DjangoClient()
        if who is not None:
            browser.force_login(who)
        return browser.get(reverse(f"dashboard:{name}", args=args), query)

    def lands(self, who, name, target, args=None, **query):
        answer = self.go(who, name, args, **query)
        self.assertEqual(answer.status_code, 302, (name, answer.status_code))
        self.assertEqual(answer["Location"], target, name)


class EveryOldAddressTests(_Door):
    #: The arguments a route needs to be reversed, by the converter in its address.
    ARGS = {"pk": 7, "code": "CL-0001", "room_id": 5, "user_id": 9}

    def test_each_old_address_goes_to_its_page_in_the_app(self):
        for route, name, target, _pairs, _only in legacy.PAGES:
            kwargs = {key: value for key, value in self.ARGS.items() if f"<{'int' if key != 'code' else 'str'}:{key}>" in route}
            args = [kwargs[key] for key in ("pk", "code", "room_id", "user_id") if key in kwargs]
            who = self.admin
            if name in ("lead_home", "lead_translators"):
                who = self.lead
            elif name in ("translator_home", "translator_payroll", "assignment_preview"):
                who = self.tr
            elif name == "sales_line":
                who = self.sales
            expected = "/app" + target.format(**kwargs)
            self.lands(who, name, expected, args or None)

    def test_a_person_who_is_not_signed_in_is_sent_to_sign_in_first(self):
        for route, name, _target, _pairs, _only in legacy.PAGES[:6]:
            if "<" in route:
                continue
            answer = self.go(None, name)
            self.assertEqual(answer.status_code, 302, name)
            self.assertTrue(answer["Location"].startswith("/login/"), (name, answer["Location"]))

    def test_every_old_address_resolves_under_its_old_name(self):
        for route, name, *_rest in legacy.PAGES:
            probe = route.replace("<int:pk>", "7").replace("<str:code>", "CL-0001").replace("<int:room_id>", "5").replace("<int:user_id>", "9")
            match = resolve("/" + probe)
            self.assertEqual(match.url_name, name, route)
            self.assertEqual(match.func.__module__, "dashboard.legacy", route)

    def test_a_task_the_notification_carries_opens_in_the_app_for_everybody_who_has_tasks(self):
        for who in (self.admin, self.ops, self.lead, self.tr, self.accounting, self.sales, self.hr):
            self.lands(who, "task_detail", f"/app/tasks/{self.task.code}", [self.task.code])

    def test_the_conversation_links_the_old_notifications_carry(self):
        self.lands(self.ops, "ops_group_chat", "/app/chats/g5", [5])
        self.lands(self.ops, "ops_staff_chat", "/app/chats/u9", [9])
        self.lands(self.ops, "ops_chat_detail", "/app/chats/CL-0001", ["CL-0001"])
        self.lands(self.ops, "ops_chats", "/app/chats?type=staff", type="staff")


class QueryTests(_Door):
    def test_the_inbox_carries_a_known_state_and_a_short_search_and_nothing_else(self):
        self.lands(self.ops, "ops_inbox", "/app/inbox?state=mine&q=invoice", state="mine", q=" invoice ", x="1")
        self.lands(self.ops, "ops_inbox", "/app/inbox", state="everything")
        self.lands(self.ops, "ops_inbox", "/app/inbox", q="x" * 201)

    def test_the_task_list_carries_a_status_it_knows(self):
        self.lands(self.ops, "ops_tasks", "/app/tasks?status=open", status="open")
        self.lands(self.ops, "ops_tasks", "/app/tasks?status=in_progress", status="in_progress")
        self.lands(self.ops, "ops_tasks", "/app/tasks", status="<script>")

    def test_the_new_task_form_carries_ids_and_a_code_only(self):
        self.lands(self.ops, "ops_task_new", "/app/tasks/new?message=4&messages=3%2C4&files=8%2C9&from=TSK-00001",
                   message="4", messages="3, 4", files="8,9", **{"from": "TSK-00001"})
        self.lands(self.ops, "ops_task_new", "/app/tasks/new", message="4; drop", **{"from": "//evil.example"})

    def test_a_month_goes_as_the_one_period_the_app_reads(self):
        self.lands(self.accounting, "accounts_overview", "/app/accounts?period=2026-9", period="2026-09")
        self.lands(self.accounting, "accounts_overview", "/app/accounts?period=2026-3", year="2026", month="3")
        self.lands(self.accounting, "accounts_overview", "/app/accounts", other="x")
        # A month that does not exist, or a year nobody works in, is this month, not an error.
        for odd in ("2026-13", "1999-05", "3000-01", "x-y"):
            answer = self.go(self.accounting, "accounts_overview", period=odd)
            self.assertTrue(answer["Location"].startswith("/app/accounts?period="), odd)
            self.assertNotIn(odd, answer["Location"], odd)
        answer = self.go(self.accounting, "accounts_overview", year="9999", month="1")
        self.assertNotIn("9999", answer["Location"])

    def test_a_translators_payslip_carries_a_month_only_when_it_reads_as_one(self):
        self.lands(self.tr, "translator_payroll", "/app/payroll?period=2026-09", period="2026-09")
        self.lands(self.tr, "translator_payroll", "/app/payroll", period="soon")

    def test_a_month_of_thousands_of_digits_is_not_a_month_and_not_an_error(self):
        from . import payroll

        self.assertIsNone(payroll.parse_period("9" * 5000 + "-1"))
        self.assertIsNone(payroll.parse_period("2026-" + "9" * 5000))
        self.assertIsNone(payroll.parse_period("202-5"))
        self.assertIsNone(payroll.parse_period("2026-123"))
        self.assertEqual(payroll.parse_period("2026-9"), (2026, 9))
        self.lands(self.tr, "translator_payroll", "/app/payroll", period="9" * 5000 + "-1")
        self.lands(self.accounting, "accounts_overview", "/app/accounts?period=2026-9", period="2026-09", extra="x" * 5000)

    def test_a_person_filter_on_the_accounts_sheet_is_a_number(self):
        self.lands(self.accounting, "accounts_attendance", "/app/accounts/attendance?period=2026-9&user=12", period="2026-09", user="12")
        self.lands(self.accounting, "accounts_attendance", "/app/accounts/attendance", user="12; drop")

    def test_the_hr_pages_carry_what_they_filter_by_when_it_is_short_and_printable(self):
        self.lands(self.hr, "hr_candidates", "/app/hr/candidates?status=new&q=sam", status="new", q="sam", other="x")
        self.lands(self.hr, "hr_candidates", "/app/hr/candidates", q="x" * 81)
        self.lands(self.hr, "hr_candidates", "/app/hr/candidates", q="line\nbreak")
        self.lands(self.hr, "hr_employees", "/app/hr/employees?department=3", department="3")

    def test_the_client_search_and_the_admin_lists(self):
        self.lands(self.sales, "client_list", "/app/clients?q=abc", q=" abc ")
        self.lands(self.admin, "admin_clients", "/app/admin/clients?show=robots&q=abc", show="robots", q="abc")
        self.lands(self.admin, "admin_clients", "/app/admin/clients", show="all")
        self.lands(self.admin, "admin_audit", "/app/admin/audit?only=denied", only="denied")
        self.lands(self.admin, "admin_audit", "/app/admin/audit", only="everything")

    def test_a_code_goes_into_an_address_only_when_it_looks_like_one(self):
        self.lands(self.hr, "hr_candidate", "/app/hr/candidates/CAN-0001", ["CAN-0001"])
        self.lands(self.hr, "hr_candidate", "/app/", ["a b"])
        self.lands(self.ops, "task_detail", "/app/", ["x" * 41])
        self.lands(self.admin, "admin_client_edit", "/app/admin/clients/CL-0001/edit", ["CL-0001"])


class OneRolesOwnPagesTests(_Door):
    def test_the_leaders_pages_send_anybody_else_to_the_apps_home(self):
        self.lands(self.lead, "lead_home", "/app/lead")
        self.lands(self.lead, "lead_translators", "/app/lead/translators")
        for who in (self.admin, self.ops, self.tr):
            self.lands(who, "lead_home", "/app/")
            self.lands(who, "lead_translators", "/app/")

    def test_the_translators_pages_send_anybody_else_to_the_apps_home(self):
        self.lands(self.tr, "translator_home", "/app/translator")
        self.lands(self.tr, "translator_payroll", "/app/payroll")
        self.lands(self.tr, "assignment_preview", "/app/assignments/7", [7])
        for who in (self.admin, self.ops, self.lead):
            self.lands(who, "translator_home", "/app/")
            self.lands(who, "translator_payroll", "/app/")
            self.lands(who, "assignment_preview", "/app/", [7])

    def test_the_sales_line_sends_anybody_else_to_the_apps_home(self):
        self.lands(self.sales, "sales_line", "/app/line")
        self.lands(self.ops, "sales_line", "/app/")

    def test_a_redirect_gives_nobody_a_page_they_could_not_open(self):
        """The redirect is not the gate: the page behind it asks the same questions the classic page did."""
        self.client.force_login(self.tr)
        for path in ("/api/v1/admin/overview/", "/api/v1/hr/recruitment/", "/api/v1/accounts/overview/"):
            self.assertIn(self.client.get(path).status_code, (403, 404), path)


class AnOldAddressOpenedByTheWrongPersonIsWrittenDownTests(_Door):
    """The classic page's 403 was a row in the audit log; the app draws the refusal in the browser without asking, so the redirect writes it."""

    def denied(self, who):
        from .models import AuditLog

        return AuditLog.objects.filter(action=identity.ACCESS_DENIED, actor=who).count()

    def test_a_page_that_was_not_for_the_person_is_a_row_and_still_a_redirect(self):
        for who, name, args in (
            (self.tr, "ops_inbox", None), (self.tr, "ops_tasks", None), (self.tr, "client_list", None),
            (self.tr, "client_detail", ["CL-0001"]), (self.sales, "ops_team", None), (self.hr, "ops_mail_thread", [7]),
            (self.tr, "admin_users", None), (self.ops, "admin_overview", None), (self.tr, "hr_candidates", None),
            (self.sales, "accounts_overview", None), (self.ops, "accounts_rules", None), (self.tr, "reviewer_tests", None),
            (self.sales, "task_detail", ["TSK-00001"]), (self.hr, "task_detail", ["TSK-00001"]),
            (self.accounting, "task_detail", ["TSK-00001"]), (self.reviewer, "task_detail", ["TSK-00001"]),
            (self.ops, "translator_home", None), (self.tr, "lead_home", None), (self.ops, "sales_line", None),
        ):
            before = self.denied(who)
            answer = self.go(who, name, args)
            self.assertEqual(answer.status_code, 302, name)
            self.assertEqual(self.denied(who), before + 1, (who.username, name))

    def test_a_page_that_was_for_the_person_writes_nothing(self):
        for who, name, args in (
            (self.ops, "ops_inbox", None), (self.sales, "ops_inbox", None), (self.ops, "ops_tasks", None),
            (self.lead, "client_list", None), (self.tr, "task_detail", ["TSK-00001"]), (self.ops, "task_detail", ["TSK-00001"]),
            (self.lead, "task_detail", ["TSK-00001"]), (self.admin, "admin_users", None), (self.hr, "hr_candidates", None),
            (self.accounting, "accounts_overview", None), (self.tr, "accounts_line", [7]), (self.tr, "my_leave", None),
            (self.tr, "ops_chats", None), (self.lead, "lead_home", None), (self.tr, "translator_home", None),
            (self.sales, "sales_line", None), (self.reviewer, "reviewer_tests", None), (self.lead, "reviewer_tests", None),
        ):
            before = self.denied(who)
            self.go(who, name, args)
            self.assertEqual(self.denied(who), before, (who.username, name))

    def test_the_admin_is_never_written_down(self):
        for name in ("ops_inbox", "ops_tasks", "client_list", "admin_users", "hr_candidates", "accounts_rules"):
            before = self.denied(self.admin)
            self.go(self.admin, name)
            self.assertEqual(self.denied(self.admin), before, name)

    def test_the_same_refusal_again_is_one_row_and_a_count(self):
        from .models import AuditLog

        for _ in range(3):
            self.go(self.tr, "ops_inbox")
        rows = AuditLog.objects.filter(action=identity.ACCESS_DENIED, actor=self.tr)
        self.assertEqual(rows.count(), 1)
        self.assertIn("x3", rows.get().detail)


class NothingClassicIsLeftTests(_Site):
    ROOT = Path(settings.BASE_DIR)

    def test_the_only_templates_left_are_the_ones_a_page_still_renders(self):
        found = sorted(str(p.relative_to(self.ROOT / "templates")).replace("\\", "/") for p in (self.ROOT / "templates").rglob("*.html"))
        self.assertEqual(found, [
            "403.html", "app/shell.html", "auth/login.html", "mail/sales_letter.html", "partials/icons.html",
            "public/base.html", "public/data_deletion.html", "public/privacy.html", "public/terms.html",
        ])

    def test_the_only_views_left_are_the_sign_in_the_public_pages_the_file_door_and_the_google_round_trip(self):
        from . import views

        public = {name for name, value in vars(views).items() if callable(value) and getattr(value, "__module__", "") == views.__name__}
        self.assertEqual(public - {"_failed"}, {
            "login_view", "logout_view", "healthz", "home", "serve_file", "privacy", "terms", "data_deletion",
            "google_connect", "google_callback", "csrf_failure", "permission_denied",
        })

    def test_no_screen_switch_is_stored_or_read(self):
        from .models import AppSettings

        self.assertNotIn("new_ui", {field.name for field in AppSettings._meta.get_fields()})

    def test_the_home_page_is_the_apps(self):
        self.client.force_login(self.ops)
        answer = self.client.get("/")
        self.assertEqual((answer.status_code, answer["Location"]), (302, "/app/"))

    def test_a_cookie_cannot_write_into_the_page_what_the_pages_do_not_know(self):
        for cookies, lang, theme in (
            ({"eagle_lang": 'x"; alert(1);//', "eagle_theme": "<b>"}, "ar", "dark"),
            ({"eagle_lang": "en", "eagle_theme": "light"}, "en", "light"),
            ({"eagle_lang": "fr"}, "ar", "dark"),
        ):
            browser = DjangoClient()
            for name, value in cookies.items():
                browser.cookies[name] = value
            page = browser.get("/login/").content.decode()
            self.assertIn(f'lang: "{lang}"', page, cookies)
            self.assertIn(f'theme: "{theme}"', page, cookies)
            self.assertNotIn("alert(1)", page, cookies)

    def test_a_form_that_is_not_a_page_is_not_an_address_any_more(self):
        self.client.force_login(self.admin)
        for path in ("/accounts/recalculate/", "/hr/leave/1/approved/", "/panel/users/1/shifts/add/", "/leave/1/cancel/"):
            self.assertEqual(self.client.post(path).status_code, 404, path)

    def test_the_login_the_public_pages_and_the_403_still_render_without_the_old_menu(self):
        for path in ("/login/", "/privacy/", "/terms/", "/data-deletion/"):
            answer = DjangoClient().get(path)
            self.assertEqual(answer.status_code, 200, path)
            self.assertContains(answer, 'dir="rtl"')
        with mock.patch("dashboard.spa.built_assets", return_value={"js": "x.js", "css": []}):
            self.client.force_login(self.tr)
            answer = self.client.get("/api/v1/admin/overview/")
            self.assertIn(answer.status_code, (403, 404))


    def test_the_pages_that_are_still_django_load_the_small_script_and_not_the_old_runtime(self):
        self.client.force_login(self.tr)
        refused = self.client.get("/panel/settings/google/connect/")
        self.assertEqual(refused.status_code, 403)
        for page in (
            DjangoClient().get("/login/"), DjangoClient().get("/privacy/"), DjangoClient().get("/terms/"),
            DjangoClient().get("/data-deletion/"), refused,
        ):
            body = page.content.decode()
            self.assertIn("js/pages.js", body)
            self.assertNotIn("js/app.js", body)
            self.assertIn("EAGLE_CFG", body)
        self.assertFalse((Path(settings.BASE_DIR) / "static" / "js" / "app.js").exists())
        self.assertTrue((Path(settings.BASE_DIR) / "static" / "js" / "pages.js").exists())


class SignInStillWorksTests(_Site):
    def test_a_person_arriving_from_an_old_link_signs_in_and_lands_on_their_own_page(self):
        User.objects.filter(pk=self.tr.pk).update(role=Role.TRANSLATOR)
        browser = DjangoClient()
        answer = browser.post("/login/", {"username": self.tr.username, "password": "pw", "next": f"/tasks/{self.task.code}/"})
        self.assertEqual(answer.status_code, 302)
        self.assertEqual(answer["Location"], f"/tasks/{self.task.code}/")
        followed = browser.get(answer["Location"])
        self.assertEqual((followed.status_code, followed["Location"]), (302, f"/app/tasks/{self.task.code}"))
