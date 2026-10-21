"""The admin panel in the new app, first part: the overview (the audit log is still written but has no page since 21/10/2026).

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
        built = mock.patch("dashboard.spa.built_assets", return_value={"js": "x.js", "css": []})
        built.start()
        self.addCleanup(built.stop)

    def get(self, user, name, args=None, /, **query):
        browser = DjangoClient()
        if user is not None:
            browser.force_login(user)
        return browser.get(reverse(name, args=args), query)

    def turn_on(self, roles=("admin",), users=()):
        conf = AppSettings.load()
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



class OverviewDeliverTests(_Admin):
    """«سلّم للعميل» beside a task awaiting delivery (21/10/2026): one press takes it over and sends its final files."""

    DELIVER = "dashboard:v1_admin_overview_deliver"

    def setUp(self):
        super().setUp()
        from .models import ChatAttachment, ChatMessage

        Task.objects.filter(pk=self.task.pk).update(status=TaskStatus.REVIEWED)
        self.task.refresh_from_db()
        handed = ChatMessage.objects.create(room=self.work_group, sender=self.tr, task=self.task, body="done")
        ChatAttachment.objects.create(message=handed, file=ContentFile(b"t", name="translated.docx"), original_name="translated.docx", size=1)
        # The leader's notes carry the task as well, and are not the translation: never sent from here.
        notes = ChatMessage.objects.create(room=self.work_group, sender=self.lead, task=self.task, body="notes")
        ChatAttachment.objects.create(message=notes, file=ContentFile(b"n", name="notes.pdf"), original_name="notes.pdf", size=1)

    def press(self, user, task=None):
        browser = DjangoClient()
        browser.force_login(user)
        url = reverse(self.DELIVER, args=[(task or self.task).code])
        self.assertTrue(url.startswith("/api/v1/admin/overview/deliver/"), url)
        with mock.patch("dashboard.whatsapp.send_text", return_value="wamid.0"),                 mock.patch("dashboard.whatsapp.send_file", return_value="wamid.1") as sender:
            answer = browser.post(url, "{}", content_type="application/json")
        return answer, sender

    def test_the_admin_takes_it_over_and_the_final_file_goes_to_the_client(self):
        from .models import OutboundMessage

        answer, sender = self.press(self.admin)
        self.assertEqual(answer.status_code, 200, answer.content)
        self.assertEqual(_json(answer)["files"], 1)
        self.assertEqual([call.args[1] for call in sender.call_args_list], [b"t"])
        self.task.refresh_from_db()
        self.assertEqual((self.task.status, self.task.handover_ack_by_id), (TaskStatus.DELIVERED, self.admin.pk))
        delivery = OutboundMessage.objects.get(task=self.task, kind=OutboundMessage.Kind.DELIVERY)
        self.assertEqual((delivery.status, delivery.created_by_id), (OutboundMessage.Status.SENT, self.admin.pk))

    def test_a_task_somebody_took_over_keeps_who_took_it(self):
        Task.objects.filter(pk=self.task.pk).update(handover_ack_at=timezone.now(), handover_ack_by=self.ops)
        answer, _sender = self.press(self.admin)
        self.assertEqual(answer.status_code, 200, answer.content)
        self.task.refresh_from_db()
        self.assertEqual((self.task.status, self.task.handover_ack_by_id), (TaskStatus.DELIVERED, self.ops.pk))

    def test_only_the_admin_may_press_it(self):
        for user in (self.ops, self.lead, self.tr, self.hr, self.reviewer, self.accounting, self.sales):
            answer, sender = self.press(user)
            self.assertEqual(answer.status_code, 403, user.username)
            self.assertFalse(sender.called, user.username)
        self.task.refresh_from_db()
        self.assertEqual((self.task.status, self.task.handover_ack_at), (TaskStatus.REVIEWED, None))
        browser = DjangoClient()
        browser.force_login(self.admin)
        self.assertEqual(browser.get(reverse(self.DELIVER, args=[self.task.code])).status_code, 405)

    def test_a_task_that_is_not_awaiting_delivery_is_refused_in_words(self):
        for status in (TaskStatus.IN_PROGRESS, TaskStatus.UNDER_REVIEW, TaskStatus.DELIVERED, TaskStatus.CANCELLED):
            Task.objects.filter(pk=self.task.pk).update(status=status)
            answer, sender = self.press(self.admin)
            self.assertEqual((answer.status_code, _json(answer)["error"]), (400, "التاسك مش مستنية التسليم للعميل دلوقتي."), status)
            self.assertFalse(sender.called, status)
        self.task.refresh_from_db()
        self.assertIsNone(self.task.handover_ack_at)

    def test_with_no_final_file_nothing_is_taken_over_or_sent(self):
        from .models import ChatAttachment

        ChatAttachment.objects.filter(original_name="translated.docx").delete()
        answer, sender = self.press(self.admin)
        self.assertEqual(answer.status_code, 400)
        self.assertIn("مفيش ملف نهائي", _json(answer)["error"])
        self.assertFalse(sender.called)
        self.task.refresh_from_db()
        self.assertEqual((self.task.status, self.task.handover_ack_at), (TaskStatus.REVIEWED, None))

    def test_a_client_who_cannot_be_reached_leaves_the_task_awaiting_delivery(self):
        from .models import Client

        Client.objects.filter(pk=self.client_obj.pk).update(phone="", email="", extra_phones="", extra_emails="")
        answer, sender = self.press(self.admin)
        self.assertEqual(answer.status_code, 400)
        self.assertTrue(_json(answer)["error"])
        self.assertFalse(sender.called)
        self.task.refresh_from_db()
        self.assertEqual(self.task.status, TaskStatus.REVIEWED)

    def test_an_unknown_task_is_a_404(self):
        browser = DjangoClient()
        browser.force_login(self.admin)
        answer = browser.post(reverse(self.DELIVER, args=["TSK-99999"]), "{}", content_type="application/json")
        self.assertEqual(answer.status_code, 404)

class AuditLogWithoutAPageTests(_Admin):
    """21/10/2026: the audit log has no page (the owner did not use it), but everything is still written to it."""

    def test_the_door_is_gone_for_everybody(self):
        for user in (self.admin, self.ops, None):
            browser = DjangoClient()
            if user is not None:
                browser.force_login(user)
            self.assertEqual(browser.get("/api/v1/admin/audit/").status_code, 404)

    def test_a_refusal_is_still_written_down(self):
        before = AuditLog.objects.count()
        denied = self.get(self.ops, "dashboard:v1_admin_overview")
        self.assertEqual(denied.status_code, 403)
        self.assertEqual(AuditLog.objects.count(), before + 1)


class HandOnTests(_Admin):
    def test_the_pages_go_on_with_the_switch(self):
        self.turn_on()
        answer = self.get(self.admin, "dashboard:admin_overview")
        self.assertEqual((answer.status_code, answer["Location"]), (302, "/app/admin"))
        # The audit log has no page: an old link to it lands on the overview, whatever filter it carried.
        for value in ("", "security", "denied"):
            answer = self.get(self.admin, "dashboard:admin_audit", only=value)
            self.assertEqual((answer.status_code, answer["Location"]), (302, "/app/admin"), value)

    def test_every_page_of_the_classic_panel_goes_on(self):
        """The whole panel is in the new app: nothing the admin used to open is left only in the classic interface."""
        pages = {
            "dashboard:admin_overview": "/app/admin", "dashboard:admin_audit": "/app/admin",
            "dashboard:admin_users": "/app/hr/employees", "dashboard:admin_user_new": "/app/hr/employees/new",
            "dashboard:admin_clients": "/app/admin/clients", "dashboard:admin_client_new": "/app/admin/clients/new",
            "dashboard:admin_settings": "/app/admin/settings", "dashboard:admin_simulate": "/app/admin",
            "dashboard:admin_reset_tasks": "/app/admin/reset-tasks", "dashboard:admin_reset_mail": "/app/admin/reset-mail",
        }
        for name, target in pages.items():
            answer = self.get(self.admin, name)
            self.assertEqual((answer.status_code, answer["Location"]), (302, target), name)
            # The old way back to the classic page is not a thing any more.
            self.assertEqual(self.get(self.admin, name, classic=1)["Location"], target, name)
        # The pages that take an argument.
        self.assertEqual(self.get(self.admin, "dashboard:admin_user_edit", [self.tr.pk])["Location"], f"/app/hr/employees/{self.tr.pk}")
        self.assertEqual(self.get(self.admin, "dashboard:admin_client_edit", [self.client_obj.code])["Location"], f"/app/admin/clients/{self.client_obj.code}/edit")

    def test_the_new_address_serves_the_app_to_the_admin(self):
        self.turn_on()
        for address in ("/app/admin",):
            browser = DjangoClient()
            browser.force_login(self.admin)
            self.assertEqual(browser.get(address).status_code, 200, address)
