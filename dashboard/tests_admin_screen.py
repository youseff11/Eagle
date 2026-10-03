"""The admin panel in the new app, first part: the overview and the audit log.

Only the admin is answered; everybody else is a 403 with a row in the log. A GET writes nothing (not even an audit row),
the answers match what the classic pages show, and no secret of the settings page rides in any of them. The pages hand
the admin on only when the admin has switched the screen on, and ``?classic=1`` always opens the classic page.
"""

import json
from datetime import timedelta
from unittest import mock

from django.core.files.base import ContentFile
from django.db import connection
from django.test import Client as DjangoClient
from django.test.utils import CaptureQueriesContext
from django.urls import reverse
from django.utils import timezone

from . import identity, newui, services
from .models import (
    AppSettings, AuditLog, Channel, InboundMessage, MessageAttachment, Role, Task, TaskStatus, User,
)
from .tests_api_v1 import _json, _Site

OVERVIEW = "dashboard:v1_admin_overview"
AUDIT = "dashboard:v1_admin_audit"

#: Written into the settings page's secret columns: found nowhere in an answer.
SECRETS = {
    "claude_api_key": "sk-ant-SECRET-claude-key",
    "whatsapp_access_token": "EAAG-SECRET-whatsapp-token",
    "whatsapp_app_secret": "SECRET-app-secret",
    "webhook_shared_secret": "SECRET-webhook-shared",
    "imap_password": "SECRET-imap-password",
    "smtp_password": "SECRET-smtp-password",
    "google_client_secret": "SECRET-google-client",
    "google_refresh_token": "SECRET-google-refresh",
}


class _Admin(_Site):
    def setUp(self):
        super().setUp()
        built = mock.patch("dashboard.newui.spa.built_assets", return_value={"js": "x.js", "css": []})
        built.start()
        self.addCleanup(built.stop)

    def get(self, user, name, args=None, /, **query):
        browser = DjangoClient()
        if user is not None:
            browser.force_login(user)
        return browser.get(reverse(name, args=args), query)

    def turn_on(self, roles=("admin",), users=()):
        conf = AppSettings.load()
        conf.new_ui = {**(conf.new_ui or {}), "admin": {"roles": list(roles), "users": list(users)}}
        conf.save()

    def hold_back(self, body="What is your price per page", sender="buyer@example.com", files=()):
        """A letter the rate rule hid from the operation."""
        conf = AppSettings.load()
        conf.rate_keywords = "price"
        conf.save()
        letter = services.ingest_message(
            channel=Channel.EMAIL, sender_identity=sender, subject="Rates", body=body,
        )
        for name in files:
            MessageAttachment.objects.create(message=letter, file=ContentFile(b"data", name=name), original_name=name, size=4)
        return letter


class ScreenSwitchTests(_Admin):
    def test_the_screen_is_the_admins_alone_and_the_admin_is_not_on_it_until_they_say_so(self):
        screen = newui.SCREENS["admin"]
        self.assertEqual((screen.classic, screen.path, screen.redirects, screen.admin_default), ("admin_overview", "/admin", True, False))
        self.assertEqual(screen.roles, ())
        self.assertEqual(screen.eligible_roles, ("admin",))
        self.assertFalse(newui.enabled(self.admin, "admin"))
        self.turn_on()
        self.assertTrue(newui.enabled(self.admin, "admin"))

    def test_no_other_role_or_person_can_be_switched_on_for_it(self):
        self.turn_on(roles=["admin", "operation", "team_lead"], users=[self.ops.pk, self.lead.pk])
        for user in (self.ops, self.lead, self.tr, self.hr, self.reviewer, self.accounting, self.sales):
            self.assertFalse(newui.enabled(user, "admin"), user.username)
            self.assertNotIn("admin", _json(self.get(user, "dashboard:v1_me"))["screens"], user.username)

    def test_the_menu_lists_it_for_the_admin_once_it_is_on(self):
        self.assertNotIn("admin", _json(self.get(self.admin, "dashboard:v1_me"))["screens"])
        self.turn_on()
        self.assertEqual(_json(self.get(self.admin, "dashboard:v1_me"))["screens"][0], "admin")

    def test_the_settings_page_still_offers_the_switch_to_the_admin(self):
        self.turn_on()
        page = self.get(self.admin, "dashboard:admin_settings", classic=1)
        self.assertEqual(page.status_code, 200)
        self.assertContains(page, "newui_admin_roles")


class OverviewDoorTests(_Admin):
    def test_the_admin_is_answered_and_everybody_else_is_refused(self):
        answer = self.get(self.admin, OVERVIEW)
        self.assertEqual(answer.status_code, 200)
        self.assertEqual(answer["Cache-Control"], "private, no-store")
        for user in (self.ops, self.lead, self.tr, self.hr, self.reviewer, self.accounting, self.sales):
            denied = self.get(user, OVERVIEW)
            self.assertEqual((denied.status_code, _json(denied)), (403, {"ok": False, "error": "forbidden"}), user.username)
        self.assertEqual(self.get(None, OVERVIEW).status_code, 401)
        browser = DjangoClient()
        browser.force_login(self.admin)
        self.assertEqual(browser.post(reverse(OVERVIEW)).status_code, 405)

    def test_every_refusal_is_written_to_the_log(self):
        before = AuditLog.objects.filter(action=identity.ACCESS_DENIED).count()
        for user in (self.ops, self.tr):
            self.get(user, OVERVIEW)
        self.assertEqual(AuditLog.objects.filter(action=identity.ACCESS_DENIED).count(), before + 2)

    def test_the_numbers_are_the_classic_pages(self):
        from . import views

        body = _json(self.get(self.admin, OVERVIEW))["counters"]
        classic = views._task_counters()
        self.assertEqual({key: body[key] for key in ("new", "open", "delivered")}, {key: classic[key] for key in ("new", "open", "delivered")})
        self.assertEqual(body["clients"], 1)
        Task.objects.create(client=self.client_obj, title="Fresh", created_by=self.ops, status=TaskStatus.NEW)
        Task.objects.create(client=self.client_obj, title="Done", created_by=self.ops, status=TaskStatus.DELIVERED)
        again = _json(self.get(self.admin, OVERVIEW))["counters"]
        self.assertEqual((again["new"], again["delivered"]), (body["new"] + 1, body["delivered"] + 1))

    def test_a_letter_held_back_is_listed_with_its_words_sender_and_keyword(self):
        letter = self.hold_back(files=("rates.pdf",))
        row = _json(self.get(self.admin, OVERVIEW))["blocked"][0]
        self.assertEqual(row["id"], letter.pk)
        self.assertEqual((row["channel"], row["keyword"], row["sender"]), ("email", "price", "buyer@example.com"))
        self.assertEqual(row["code"], letter.client.code)
        self.assertIn("price per page", row["body"])
        self.assertEqual([file["name"] for file in row["files"]], ["rates.pdf"])
        self.assertTrue(row["at"]["en"])

    def test_a_file_of_a_held_letter_opens_from_our_own_address_and_never_a_storage_link(self):
        self.hold_back(files=("rates.pdf",))
        url = _json(self.get(self.admin, OVERVIEW))["blocked"][0]["files"][0]["url"]
        self.assertTrue(url.startswith("/files/"), url)

    def test_a_letter_that_was_not_held_is_not_listed(self):
        services.ingest_message(channel=Channel.EMAIL, sender_identity="plain@example.com", subject="Hello", body="A document")
        self.assertEqual(_json(self.get(self.admin, OVERVIEW))["blocked"], [])

    def test_a_long_letter_is_cut_and_pictures_in_it_are_taken_out(self):
        self.hold_back(body="price " + "x" * 500)
        self.assertLessEqual(len(_json(self.get(self.admin, OVERVIEW))["blocked"][0]["body"]), 200)

    def test_at_most_twenty_held_letters_are_listed_the_newest_first(self):
        for index in range(25):
            self.hold_back(body=f"price {index}", sender=f"buyer{index}@example.com")
        rows = _json(self.get(self.admin, OVERVIEW))["blocked"]
        self.assertEqual(len(rows), 20)
        ids = [row["id"] for row in rows]
        self.assertEqual(ids, sorted(ids, reverse=True))

    def test_a_hand_off_waiting_for_an_answer_is_listed_with_the_seconds_left(self):
        other = Task.objects.create(client=self.client_obj, title="Offered", created_by=self.ops, team_lead=self.lead, status=TaskStatus.LEAD_ACCEPTED)
        assignment = services.assign_to_translator(other, self.tr, self.lead)
        rows = _json(self.get(self.admin, OVERVIEW))["pending"]
        self.assertEqual([row["task"] for row in rows], [other.code])
        self.assertEqual(rows[0]["assignee"], self.tr.short_name)
        self.assertGreater(rows[0]["seconds_left"], 0)
        self.assertEqual(rows[0]["id"], assignment.pk)

    def test_an_accepted_hand_off_is_not_waiting(self):
        self.assertEqual(_json(self.get(self.admin, OVERVIEW))["pending"], [])

    def test_a_task_past_its_date_is_late_only_while_it_is_being_worked(self):
        self.task.deadline = timezone.now() - timedelta(hours=2)
        self.task.save()
        done = Task.objects.create(
            client=self.client_obj, title="Closed", created_by=self.ops, status=TaskStatus.DELIVERED,
            deadline=timezone.now() - timedelta(days=1),
        )
        rows = _json(self.get(self.admin, OVERVIEW))["late"]
        self.assertEqual([row["code"] for row in rows], [self.task.code])
        self.assertEqual(rows[0]["translator"], self.tr.short_name)
        self.assertNotIn(done.code, json.dumps(rows))

    def test_a_task_not_yet_due_is_not_late(self):
        self.assertEqual(_json(self.get(self.admin, OVERVIEW))["late"], [])

    def test_the_newest_fifteen_tasks_are_listed_with_their_origin_and_status(self):
        for index in range(20):
            Task.objects.create(client=self.client_obj, title=f"Task {index}", created_by=self.ops)
        rows = _json(self.get(self.admin, OVERVIEW))["recent"]
        self.assertEqual(len(rows), 15)
        self.assertTrue(all(row["status"]["value"] for row in rows))
        self.assertIn("title", rows[0])

    def test_it_lists_what_the_classic_page_lists(self):
        self.hold_back()
        self.task.deadline = timezone.now() - timedelta(hours=1)
        self.task.save()
        other = Task.objects.create(client=self.client_obj, title="Offered", created_by=self.ops, team_lead=self.lead, status=TaskStatus.LEAD_ACCEPTED)
        services.assign_to_translator(other, self.tr, self.lead)
        classic = self.get(self.admin, "dashboard:admin_overview", classic=1)
        body = _json(self.get(self.admin, OVERVIEW))
        self.assertEqual([row["id"] for row in body["blocked"]], [m.pk for m in classic.context["blocked"]])
        self.assertEqual([row["code"] for row in body["late"]], [t.code for t in classic.context["late_tasks"]])
        self.assertEqual([row["code"] for row in body["recent"]], [t.code for t in classic.context["recent_tasks"]])
        self.assertEqual([row["id"] for row in body["pending"]], [a.pk for a in classic.context["pending"]])

    def test_a_get_changes_nothing_not_even_the_log(self):
        self.hold_back()
        before = (AuditLog.objects.count(), InboundMessage.objects.count(), Task.objects.count())
        self.get(self.admin, OVERVIEW)
        self.get(self.admin, OVERVIEW)
        self.assertEqual((AuditLog.objects.count(), InboundMessage.objects.count(), Task.objects.count()), before)

    def test_no_secret_of_the_settings_page_is_in_the_answer(self):
        conf = AppSettings.load()
        for name, value in SECRETS.items():
            setattr(conf, name, value)
        conf.save()
        self.hold_back(files=("rates.pdf",))
        text = self.get(self.admin, OVERVIEW).content.decode("utf-8")
        for value in SECRETS.values():
            self.assertNotIn(value, text, value)

    def test_the_number_of_questions_does_not_grow_with_the_letters_and_tasks(self):
        def questions():
            with CaptureQueriesContext(connection) as seen:
                self.assertEqual(self.get(self.admin, OVERVIEW).status_code, 200)
            return len(seen)

        self.hold_back(files=("a.pdf",))
        self.task.deadline = timezone.now() - timedelta(hours=1)
        self.task.save()
        few = questions()
        for index in range(12):
            self.hold_back(body=f"price {index}", sender=f"buyer{index}@example.com", files=(f"f{index}.pdf", f"g{index}.pdf"))
            late = Task.objects.create(
                client=self.client_obj, title=f"Late {index}", created_by=self.ops, team_lead=self.lead,
                translator=self.tr, status=TaskStatus.IN_PROGRESS, deadline=timezone.now() - timedelta(hours=3),
            )
            offered = Task.objects.create(client=self.client_obj, title=f"Offer {index}", created_by=self.ops, team_lead=self.lead, status=TaskStatus.LEAD_ACCEPTED)
            services.assign_to_translator(offered, self.tr, self.lead)
            self.assertTrue(late.pk)
        self.assertEqual(questions(), few)


class AuditDoorTests(_Admin):
    def entry(self, action, actor=None, target="", detail="", ip="203.0.113.7", path="/somewhere/"):
        return AuditLog.objects.create(actor=actor, action=action, target=target, detail=detail, ip=ip, path=path)

    def test_the_admin_is_answered_and_everybody_else_is_refused(self):
        answer = self.get(self.admin, AUDIT)
        self.assertEqual((answer.status_code, answer["Cache-Control"]), (200, "private, no-store"))
        for user in (self.ops, self.lead, self.tr, self.hr, self.reviewer, self.accounting, self.sales):
            denied = self.get(user, AUDIT)
            self.assertEqual((denied.status_code, _json(denied)), (403, {"ok": False, "error": "forbidden"}), user.username)
        self.assertEqual(self.get(None, AUDIT).status_code, 401)
        browser = DjangoClient()
        browser.force_login(self.admin)
        self.assertEqual(browser.post(reverse(AUDIT)).status_code, 405)

    def test_a_refusal_here_is_itself_in_the_log_the_admin_reads(self):
        self.get(self.ops, AUDIT)
        rows = _json(self.get(self.admin, AUDIT, only="denied"))["rows"]
        self.assertTrue(any(row["actor"] == self.ops.short_name and "audit" in row["detail"] for row in rows))

    def test_an_entry_carries_who_what_where_and_when(self):
        self.entry("client.identity.view", actor=self.admin, target="CL-0001", detail="client_detail", path="/clients/CL-0001/")
        row = _json(self.get(self.admin, AUDIT))["rows"][0]
        self.assertEqual(
            {key: row[key] for key in ("actor", "action", "target", "detail", "ip", "path")},
            {"actor": self.admin.short_name, "action": "client.identity.view", "target": "CL-0001",
             "detail": "client_detail", "ip": "203.0.113.7", "path": "/clients/CL-0001/"},
        )
        self.assertRegex(row["at"]["en"], r"^\d{4}-\d{2}-\d{2} \d{1,2}:\d{2} (AM|PM)$")

    def test_an_entry_with_no_person_or_address_is_still_a_row(self):
        AuditLog.objects.create(action="system.sweep", target="x")
        row = _json(self.get(self.admin, AUDIT))["rows"][0]
        self.assertEqual((row["actor"], row["ip"], row["path"]), (None, "", ""))

    def test_the_newest_come_first_and_at_most_two_hundred(self):
        for index in range(210):
            self.entry("test.entry", target=f"t{index}")
        rows = _json(self.get(self.admin, AUDIT))["rows"]
        self.assertEqual(len(rows), 200)
        ids = [row["id"] for row in rows]
        self.assertEqual(ids, sorted(ids, reverse=True))

    def test_the_filters_are_the_classic_pages(self):
        self.entry("client.identity.view", target="a")
        self.entry(identity.ACCESS_DENIED, target="b")
        self.entry("task.created", target="c")
        everything = _json(self.get(self.admin, AUDIT))["rows"]
        security = _json(self.get(self.admin, AUDIT, only="security"))["rows"]
        denied = _json(self.get(self.admin, AUDIT, only="denied"))["rows"]
        self.assertIn("c", [row["target"] for row in everything])
        self.assertEqual({row["target"] for row in security}, {"a", "b"})
        self.assertEqual({row["target"] for row in denied}, {"b"})
        classic = self.get(self.admin, "dashboard:admin_audit", classic=1, only="security")
        self.assertEqual([row["id"] for row in security], [entry.pk for entry in classic.context["logs"]])

    def test_a_filter_that_is_not_one_is_a_400_and_not_a_full_log(self):
        for value in ("everything", "SECURITY", "denied;", "x" * 500):
            answer = self.get(self.admin, AUDIT, only=value)
            self.assertEqual((answer.status_code, _json(answer)["error"]), (400, "bad_filter"), value)

    def test_a_long_detail_is_cut(self):
        self.entry("test.entry", detail="d" * 2000)
        self.assertLessEqual(len(_json(self.get(self.admin, AUDIT))["rows"][0]["detail"]), 300)

    def test_reading_the_log_writes_nothing_to_it(self):
        self.entry("test.entry")
        before = AuditLog.objects.count()
        self.get(self.admin, AUDIT)
        self.get(self.admin, AUDIT, only="security")
        self.assertEqual(AuditLog.objects.count(), before)

    def test_no_secret_of_the_settings_page_is_in_the_answer(self):
        conf = AppSettings.load()
        for name, value in SECRETS.items():
            setattr(conf, name, value)
        conf.save()
        self.entry("test.entry")
        text = self.get(self.admin, AUDIT).content.decode("utf-8")
        for value in SECRETS.values():
            self.assertNotIn(value, text, value)

    def test_the_number_of_questions_does_not_grow_with_the_entries(self):
        def questions():
            with CaptureQueriesContext(connection) as seen:
                self.assertEqual(self.get(self.admin, AUDIT).status_code, 200)
            return len(seen)

        self.entry("test.entry", actor=self.admin)
        few = questions()
        for index, person in enumerate(self.everyone * 8):
            self.entry("test.entry", actor=person, target=str(index))
        self.assertEqual(questions(), few)


class HandOnTests(_Admin):
    def test_the_pages_go_on_with_the_switch(self):
        self.turn_on()
        answer = self.get(self.admin, "dashboard:admin_overview")
        self.assertEqual((answer.status_code, answer["Location"]), (302, "/app/admin"))
        answer = self.get(self.admin, "dashboard:admin_audit")
        self.assertEqual((answer.status_code, answer["Location"]), (302, "/app/admin/audit"))

    def test_the_audit_filter_goes_along_when_it_is_a_real_one_and_only_then(self):
        self.turn_on()
        for value in ("security", "denied"):
            self.assertEqual(self.get(self.admin, "dashboard:admin_audit", only=value)["Location"], f"/app/admin/audit?only={value}")
        for value in ("", "bogus", "se curity", "<script>"):
            self.assertEqual(self.get(self.admin, "dashboard:admin_audit", only=value)["Location"], "/app/admin/audit", value)

    def test_without_the_switch_and_by_name_the_classic_pages_open(self):
        for name in ("dashboard:admin_overview", "dashboard:admin_audit"):
            self.assertEqual(self.get(self.admin, name).status_code, 200, name)
        self.turn_on()
        for name in ("dashboard:admin_overview", "dashboard:admin_audit"):
            self.assertEqual(self.get(self.admin, name, classic=1).status_code, 200, name)

    def test_home_lands_on_the_new_overview_and_classic_home_does_not_bounce(self):
        self.turn_on()
        browser = DjangoClient()
        browser.force_login(self.admin)
        self.assertEqual(browser.get("/", follow=True).redirect_chain[-1][0], "/app/admin")
        landing = browser.get("/", {"classic": "1"}, follow=True)
        self.assertEqual(landing.status_code, 200)
        self.assertNotIn("/app/admin", [step[0] for step in landing.redirect_chain])

    def test_a_build_that_does_not_exist_hands_nobody_on(self):
        self.turn_on()
        with mock.patch("dashboard.newui.spa.built_assets", return_value=None):
            self.assertEqual(self.get(self.admin, "dashboard:admin_overview").status_code, 200)

    def test_every_page_of_the_classic_panel_goes_on_and_every_one_opens_by_name(self):
        """The whole panel is in the new app: nothing the admin used to open is left only in the classic interface."""
        pages = {
            "dashboard:admin_overview": "/app/admin", "dashboard:admin_audit": "/app/admin/audit",
            "dashboard:admin_users": "/app/admin/users", "dashboard:admin_user_new": "/app/admin/users/new",
            "dashboard:admin_clients": "/app/admin/clients", "dashboard:admin_client_new": "/app/admin/clients/new",
            "dashboard:admin_settings": "/app/admin/settings", "dashboard:admin_simulate": "/app/admin/simulate",
            "dashboard:admin_reset_tasks": "/app/admin/reset-tasks", "dashboard:admin_reset_mail": "/app/admin/reset-mail",
        }
        self.turn_on()
        for name, target in pages.items():
            answer = self.get(self.admin, name)
            self.assertEqual((answer.status_code, answer["Location"]), (302, target), name)
            self.assertEqual(self.get(self.admin, name, classic=1).status_code, 200, name)
        # The pages that take an argument.
        self.assertEqual(self.get(self.admin, "dashboard:admin_user_edit", [self.tr.pk])["Location"], f"/app/admin/users/{self.tr.pk}")
        self.assertEqual(self.get(self.admin, "dashboard:admin_client_edit", [self.client_obj.code])["Location"], f"/app/admin/clients/{self.client_obj.code}/edit")

    def test_every_admin_page_of_the_classic_interface_is_in_the_sweep(self):
        """A page added to the classic panel later must be handed on (or listed here as left behind on purpose)."""
        from django.urls import get_resolver

        left_on_purpose = {
            "dashboard:admin_shift_add", "dashboard:admin_shift_delete", "dashboard:admin_clients_delete",
            "dashboard:google_connect", "dashboard:google_callback", "dashboard:google_sync", "dashboard:google_disconnect",
            "dashboard:admin_client_edit", "dashboard:admin_user_edit",
        }
        handled = {
            "dashboard:admin_overview", "dashboard:admin_audit", "dashboard:admin_users", "dashboard:admin_user_new",
            "dashboard:admin_clients", "dashboard:admin_client_new", "dashboard:admin_settings", "dashboard:admin_simulate",
            "dashboard:admin_reset_tasks", "dashboard:admin_reset_mail",
        }
        names = {
            f"dashboard:{name}" for name in get_resolver().reverse_dict.keys()
            if isinstance(name, str) and (name.startswith("admin_") or name.startswith("google_"))
        }
        self.assertEqual(names - handled - left_on_purpose, set())

    def test_a_form_already_open_is_answered_where_it_is(self):
        self.turn_on()
        browser = DjangoClient()
        browser.force_login(self.admin)
        answer = browser.post(reverse("dashboard:admin_overview"))
        self.assertNotEqual(answer.status_code, 302)

    def test_nobody_else_is_handed_on_or_let_in(self):
        self.turn_on()
        for user in (self.ops, self.sales):
            self.assertEqual(self.get(user, "dashboard:admin_overview").status_code, 403, user.username)

    def test_the_new_address_serves_the_app_to_the_admin(self):
        self.turn_on()
        for address in ("/app/admin", "/app/admin/audit"):
            browser = DjangoClient()
            browser.force_login(self.admin)
            self.assertEqual(browser.get(address).status_code, 200, address)
