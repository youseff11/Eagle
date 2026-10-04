"""The admin panel's tools in the new app: the message simulator and the two clear-outs.

The clear-outs delete real data for good, so what is held here is that nothing gets easier: a GET only counts, the run needs
the admin's own password and the explicit yes, a wrong password or a missing yes deletes nothing, only the admin is answered
(even with their own right password), and the password is in the request and nowhere else.
"""

import json

from datetime import timedelta
from unittest import mock

from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import Client as DjangoClient
from django.urls import reverse
from django.utils import timezone

from . import identity, services
from .models import (
    AppSettings, AuditLog, Channel, ChatRoom, Client, InboundMessage, MessageAttachment, OutboundMessage, Role, Task, User,
)
from .tests_admin_screen import _Admin
from .tests_api_v1 import _json

SIMULATE = "dashboard:v1_admin_simulate"
SEND = "dashboard:v1_admin_simulate_send"
TASKS = "dashboard:v1_admin_reset_tasks"
TASKS_RUN = "dashboard:v1_admin_reset_tasks_run"
MAIL = "dashboard:v1_admin_reset_mail"
MAIL_RUN = "dashboard:v1_admin_reset_mail_run"

#: The admin's password in ``_Site``. A test value: the fixture creates every person with it.
ADMIN_PASSWORD = "pw"


class _Tools(_Admin):
    def post(self, user, name, body):
        browser = DjangoClient()
        if user is not None:
            browser.force_login(user)
        return browser.post(reverse(name), json.dumps(body), content_type="application/json")

    def letter(self, task=None, address="client@example.com"):
        row = InboundMessage.objects.create(channel=Channel.EMAIL, sender_identity=address, subject="Hi", body="A document", task=task)
        MessageAttachment.objects.create(message=row, file=SimpleUploadedFile("doc.pdf", b"data"), original_name="doc.pdf", size=4)
        return row


class DoorMatrixTests(_Tools):
    def doors(self):
        return [("GET", SIMULATE), ("POST", SEND), ("GET", TASKS), ("POST", TASKS_RUN), ("GET", MAIL), ("POST", MAIL_RUN)]

    def call(self, user, method, name):
        browser = DjangoClient()
        if user is not None:
            browser.force_login(user)
        url = reverse(name)
        return browser.get(url) if method == "GET" else browser.post(url, "{}", content_type="application/json")

    def test_only_the_admin_is_answered(self):
        for method, name in self.doors():
            for user in (self.ops, self.lead, self.tr, self.hr, self.reviewer, self.accounting, self.sales):
                denied = self.call(user, method, name)
                self.assertEqual((denied.status_code, _json(denied)), (403, {"ok": False, "error": "forbidden"}), (name, user.username))
            self.assertEqual(self.call(None, method, name).status_code, 401, name)
            self.assertNotEqual(self.call(self.admin, method, name).status_code, 403, name)

    def test_the_wrong_method_is_a_405_that_says_what_is_allowed(self):
        for method, name in self.doors():
            answer = self.call(self.admin, "POST" if method == "GET" else "GET", name)
            self.assertEqual((answer.status_code, answer["Allow"]), (405, method), name)

    def test_every_answer_is_private(self):
        for method, name in self.doors():
            self.assertEqual(self.call(self.admin, method, name)["Cache-Control"], "private, no-store", name)


class SimulateTests(_Tools):
    def send(self, **over):
        fields = {"channel": "whatsapp", "sender_identity": "+201110002222", "subject": "", "body": "Hello from a client"}
        fields.update(over)
        browser = DjangoClient()
        browser.force_login(self.admin)
        return browser.post(reverse(SEND), fields)

    def test_the_form_choices_and_the_latest_messages_are_listed(self):
        body = _json(self.get(self.admin, SIMULATE))
        self.assertEqual([choice["value"] for choice in body["channels"]], ["whatsapp", "email"])
        self.assertEqual([row["code"] for row in body["recent"]], [self.client_obj.code])
        self.assertEqual(body["recent"][0]["body"], "hello there")

    def test_the_latest_twenty_are_listed_newest_first_with_a_start_of_the_words(self):
        for index in range(25):
            InboundMessage.objects.create(channel=Channel.EMAIL, sender_identity=f"a{index}@x.example", body=f"{index} " + "w" * 200)
        rows = _json(self.get(self.admin, SIMULATE))["recent"]
        self.assertEqual(len(rows), 20)
        ids = [row["id"] for row in rows]
        self.assertEqual(ids, sorted(ids, reverse=True))
        self.assertLessEqual(max(len(row["body"]) for row in rows), 60)

    def test_a_held_back_message_is_marked(self):
        conf = AppSettings.load()
        conf.rate_keywords = "price"
        conf.save()
        self.send(body="What is the price")
        self.assertTrue(_json(self.get(self.admin, SIMULATE))["recent"][0]["blocked"])

    def test_a_message_arrives_as_if_a_client_sent_it(self):
        answer = self.send()
        body = _json(answer)
        self.assertEqual((answer.status_code, body["ok"], body["blocked"]), (200, True, False))
        letter = InboundMessage.objects.get(pk=body["id"])
        self.assertEqual((letter.body, letter.sender_identity, letter.channel), ("Hello from a client", "+201110002222", "whatsapp"))
        self.assertEqual(letter.client.code, body["code"])

    def test_the_operation_is_told_as_for_any_message(self):
        before = self.ops.notifications.count()
        self.send()
        self.assertEqual(self.ops.notifications.count(), before + 1)

    def test_files_go_with_it(self):
        browser = DjangoClient()
        browser.force_login(self.admin)
        answer = browser.post(reverse(SEND), {
            "channel": "email", "sender_identity": "files@example.com", "subject": "Docs", "body": "See files",
            "files": [SimpleUploadedFile("a.pdf", b"aaa"), SimpleUploadedFile("b.pdf", b"bbbb")],
        })
        self.assertEqual(answer.status_code, 200)
        letter = InboundMessage.objects.get(pk=_json(answer)["id"])
        self.assertEqual(sorted(a.original_name for a in letter.attachments.all()), ["a.pdf", "b.pdf"])

    def test_what_the_form_refuses_is_refused_with_its_messages_and_nothing_arrives(self):
        before = InboundMessage.objects.count()
        for over, field in (({"channel": "fax"}, "channel"), ({"sender_identity": ""}, "sender_identity"), ({"body": ""}, "body")):
            answer = self.send(**over)
            body = _json(answer)
            self.assertEqual((answer.status_code, body["error"]), (400, "invalid"), over)
            self.assertIn(field, body["errors"])
        self.assertEqual(InboundMessage.objects.count(), before)

    def test_a_get_changes_nothing(self):
        before = (InboundMessage.objects.count(), AuditLog.objects.count())
        self.get(self.admin, SIMULATE)
        self.assertEqual((InboundMessage.objects.count(), AuditLog.objects.count()), before)


class CountsTests(_Tools):
    def test_the_task_counts_are_the_classic_pages(self):
        body = _json(self.get(self.admin, TASKS))
        self.assertEqual(body["counts"], services.task_reset_counts())
        self.assertEqual(body["counts"]["tasks"], 1)

    def test_the_mail_counts_are_the_classic_pages(self):
        self.letter()
        self.letter(task=self.task)
        counts = _json(self.get(self.admin, MAIL))["counts"]
        self.assertEqual(counts, services.mail_reset_counts())
        self.assertEqual((counts["letters"], counts["kept_letters"]), (1, 1))

    def test_a_get_deletes_nothing(self):
        self.letter()
        before = (Task.objects.count(), InboundMessage.objects.count(), AuditLog.objects.count())
        self.get(self.admin, TASKS)
        self.get(self.admin, MAIL)
        self.assertEqual((Task.objects.count(), InboundMessage.objects.count(), AuditLog.objects.count()), before)


class ResetTasksTests(_Tools):
    def run_reset(self, **over):
        body = {"password": ADMIN_PASSWORD, "confirm": True}
        body.update(over)
        return self.post(self.admin, TASKS_RUN, body)

    def test_without_the_explicit_yes_nothing_is_deleted_whatever_the_password(self):
        for body in ({"password": ADMIN_PASSWORD}, {"password": ADMIN_PASSWORD, "confirm": False}, {"password": ADMIN_PASSWORD, "confirm": "1"}, {"password": ADMIN_PASSWORD, "confirm": 1}, {"password": ADMIN_PASSWORD, "confirm": "true"}, {}):
            answer = self.post(self.admin, TASKS_RUN, body)
            self.assertEqual((answer.status_code, _json(answer)["error"]), (400, "confirm_required"), body)
        self.assertTrue(Task.objects.filter(pk=self.task.pk).exists())

    def test_a_wrong_password_is_refused_with_its_reason_and_nothing_is_deleted(self):
        for password in ("not-the-password", "", "pw "):
            answer = self.run_reset(password=password)
            body = _json(answer)
            self.assertEqual((answer.status_code, body["error"]), (400, "refused"), password)
            self.assertTrue(body["message"])
        self.assertTrue(Task.objects.filter(pk=self.task.pk).exists())
        self.assertGreaterEqual(AuditLog.objects.filter(action="task.reset_refused").count(), 3)

    def test_the_refusal_is_written_down_without_the_password(self):
        self.run_reset(password="guess-number-one")
        row = AuditLog.objects.filter(action="task.reset_refused").latest("pk")
        self.assertEqual((row.actor_id, row.detail), (self.admin.pk, "wrong password"))
        self.assertNotIn("guess-number-one", json.dumps(list(AuditLog.objects.values()), default=str))

    def test_a_body_that_is_not_the_shape_is_refused(self):
        browser = DjangoClient()
        browser.force_login(self.admin)
        for payload, kind in (("[]", "application/json"), ("{", "application/json"), ("password=pw&confirm=1", "application/x-www-form-urlencoded")):
            answer = browser.post(reverse(TASKS_RUN), payload, content_type=kind)
            self.assertEqual((answer.status_code, _json(answer)["error"]), (400, "bad_body"), payload)
        for password in (["pw"], 5, None, "x" * 300, "a\x00b"):
            answer = self.run_reset(password=password)
            self.assertEqual(answer.status_code, 400, repr(password))
        self.assertTrue(Task.objects.filter(pk=self.task.pk).exists())

    def test_with_the_password_and_the_yes_every_task_goes_and_the_backup_comes_back_as_a_file(self):
        code = self.task.code
        answer = self.run_reset()
        self.assertEqual(answer.status_code, 200)
        self.assertFalse(Task.objects.exists())
        self.assertRegex(answer["Content-Disposition"], r'^attachment; filename="eagle-tasks-backup-\d{8}-\d{4}\.json"$')
        self.assertIn("application/json", answer["Content-Type"])
        self.assertEqual(answer["X-Eagle-Deleted"], "1")
        self.assertEqual(answer["Cache-Control"], "private, no-store")
        fixture = json.loads(answer.content.decode("utf-8"))
        self.assertIn(code, json.dumps(fixture, ensure_ascii=False))
        self.assertTrue(any(entry["model"] == "dashboard.task" for entry in fixture))

    def test_the_reset_and_the_download_are_written_down(self):
        self.run_reset()
        self.assertTrue(AuditLog.objects.filter(action="task.reset", actor=self.admin).exists())
        self.assertTrue(AuditLog.objects.filter(action=identity.DATA_EXPORT, target="tasks-backup", detail="1 records").exists())

    def test_the_password_is_nowhere_in_what_comes_back_or_in_the_log(self):
        answer = self.run_reset(password=ADMIN_PASSWORD)
        self.assertNotIn(b'"password"', answer.content)
        self.assertNotIn("pbkdf2", answer.content.decode("utf-8"))
        everything = json.dumps(list(AuditLog.objects.values()), default=str)
        self.assertNotIn('"password"', everything)

    def test_numbering_starts_again_and_what_must_stay_stays(self):
        self.run_reset()
        self.assertTrue(InboundMessage.objects.exists())
        self.assertTrue(Client.objects.filter(pk=self.client_obj.pk).exists())
        self.assertTrue(ChatRoom.objects.filter(task__isnull=True).exists())
        fresh = Task.objects.create(client=self.client_obj, title="After", created_by=self.ops)
        self.assertEqual(fresh.code, "TSK-00001")

    def test_anybody_else_is_refused_even_with_their_own_right_password(self):
        for user in (self.ops, self.lead, self.tr, self.hr, self.reviewer, self.accounting, self.sales):
            answer = self.post(user, TASKS_RUN, {"password": ADMIN_PASSWORD, "confirm": True})
            self.assertEqual(answer.status_code, 403, user.username)
        self.assertTrue(Task.objects.filter(pk=self.task.pk).exists())

    def test_the_run_cannot_be_triggered_by_a_get_or_a_form_post_from_another_site(self):
        self.assertEqual(self.get(self.admin, TASKS_RUN).status_code, 405)
        browser = DjangoClient(enforce_csrf_checks=True)
        browser.force_login(self.admin)
        answer = browser.post(reverse(TASKS_RUN), json.dumps({"password": ADMIN_PASSWORD, "confirm": True}), content_type="application/json")
        self.assertEqual(answer.status_code, 403)
        self.assertTrue(Task.objects.filter(pk=self.task.pk).exists())


class ResetMailTests(_Tools):
    def run_reset(self, **over):
        body = {"password": ADMIN_PASSWORD, "confirm": True}
        body.update(over)
        return self.post(self.admin, MAIL_RUN, body)

    def test_without_the_explicit_yes_or_with_a_wrong_password_nothing_is_deleted(self):
        letter = self.letter()
        for body in ({"password": ADMIN_PASSWORD}, {"password": ADMIN_PASSWORD, "confirm": "1"}, {"password": ADMIN_PASSWORD, "confirm": False}):
            self.assertEqual(self.post(self.admin, MAIL_RUN, body).status_code, 400)
        refused = self.run_reset(password="wrong")
        self.assertEqual((refused.status_code, _json(refused)["error"]), (400, "refused"))
        self.assertTrue(InboundMessage.objects.filter(pk=letter.pk).exists())
        self.assertTrue(AuditLog.objects.filter(action="mail.reset_refused", detail="wrong password").exists())

    def test_the_letters_and_replies_no_task_stands_on_go_and_the_ones_a_task_stands_on_stay(self):
        gone = self.letter()
        kept = self.letter(task=self.task, address="kept@example.com")
        reply = OutboundMessage.objects.create(client=self.client_obj, channel=Channel.EMAIL, body="Reply", created_by=self.ops)
        answer = self.run_reset()
        self.assertEqual(answer.status_code, 200)
        self.assertFalse(InboundMessage.objects.filter(pk=gone.pk).exists())
        self.assertTrue(InboundMessage.objects.filter(pk=kept.pk).exists())
        self.assertFalse(OutboundMessage.objects.filter(pk=reply.pk).exists())

    def test_the_backup_is_a_file_with_the_counts_in_headers_and_what_was_written_down(self):
        self.letter()
        answer = self.run_reset()
        self.assertRegex(answer["Content-Disposition"], r'^attachment; filename="eagle-mail-backup-\d{8}-\d{4}\.json"$')
        self.assertEqual((answer["X-Eagle-Deleted"], answer["X-Eagle-Files"]), ("1", "1"))
        self.assertTrue(any(entry["model"] == "dashboard.inboundmessage" for entry in json.loads(answer.content.decode("utf-8"))))
        self.assertTrue(AuditLog.objects.filter(action="mail.reset", actor=self.admin).exists())
        self.assertTrue(AuditLog.objects.filter(action=identity.DATA_EXPORT, target="mail-backup").exists())

    def test_whatsapp_is_not_touched(self):
        chat = InboundMessage.objects.create(channel=Channel.WHATSAPP, sender_identity="+201110002222", body="Hi on whatsapp")
        self.run_reset()
        self.assertTrue(InboundMessage.objects.filter(pk=chat.pk).exists())

    def test_anybody_else_is_refused_even_with_the_right_password(self):
        letter = self.letter()
        for user in (self.ops, self.sales, self.accounting):
            self.assertEqual(self.post(user, MAIL_RUN, {"password": ADMIN_PASSWORD, "confirm": True}).status_code, 403, user.username)
        self.assertTrue(InboundMessage.objects.filter(pk=letter.pk).exists())

    def test_the_password_is_not_in_the_answer_or_the_log(self):
        self.letter()
        answer = self.run_reset()
        self.assertNotIn(b'"password"', answer.content)
        self.assertNotIn('"password"', json.dumps(list(AuditLog.objects.values()), default=str))


class HandOnTests(_Tools):
    def test_the_pages_go_on_with_the_switch(self):
        self.turn_on()
        for name, target in (
            ("dashboard:admin_simulate", "/app/admin/simulate"),
            ("dashboard:admin_reset_tasks", "/app/admin/reset-tasks"),
            ("dashboard:admin_reset_mail", "/app/admin/reset-mail"),
        ):
            answer = self.get(self.admin, name)
            self.assertEqual((answer.status_code, answer["Location"]), (302, target), name)

class ResetLockTests(_Tools):
    """Five wrong passwords in a quarter of an hour shut both clear-outs to that admin, whatever comes next."""

    WRONG = ("TASK", "task.reset_refused"), ("MAIL", "mail.reset_refused")

    def guess(self, route, times, user=None):
        for _ in range(times):
            self.post(user or self.admin, route, {"password": "not-it", "confirm": True})

    def test_four_wrong_passwords_are_still_a_way_in_and_the_fifth_shuts_it(self):
        self.guess(TASKS_RUN, 4)
        right = self.post(self.admin, TASKS_RUN, {"password": ADMIN_PASSWORD, "confirm": True})
        self.assertEqual(right.status_code, 200)
        self.assertFalse(Task.objects.exists())

    def test_after_five_wrong_ones_even_the_right_password_is_refused_and_nothing_is_deleted(self):
        self.guess(TASKS_RUN, 5)
        answer = self.post(self.admin, TASKS_RUN, {"password": ADMIN_PASSWORD, "confirm": True})
        body = _json(answer)
        self.assertEqual((answer.status_code, body["error"], body["message"]), (429, "too_many_attempts", services.RESET_LOCKED_MESSAGE))
        self.assertTrue(Task.objects.filter(pk=self.task.pk).exists())
        self.assertTrue(AuditLog.objects.filter(action="task.reset_locked", actor=self.admin, detail="too many wrong passwords").exists())

    def test_the_count_is_over_both_clear_outs_together(self):
        self.guess(TASKS_RUN, 3)
        self.guess(MAIL_RUN, 2)
        for route in (TASKS_RUN, MAIL_RUN):
            answer = self.post(self.admin, route, {"password": ADMIN_PASSWORD, "confirm": True})
            self.assertEqual(answer.status_code, 429, route)
        self.assertTrue(Task.objects.filter(pk=self.task.pk).exists())

    def test_it_is_a_quarter_of_an_hour_and_not_for_ever(self):
        self.guess(TASKS_RUN, 5)
        AuditLog.objects.filter(action="task.reset_refused").update(created_at=timezone.now() - timedelta(minutes=services.RESET_LOCK_MINUTES + 1))
        answer = self.post(self.admin, TASKS_RUN, {"password": ADMIN_PASSWORD, "confirm": True})
        self.assertEqual(answer.status_code, 200)

    def test_trying_while_shut_does_not_push_the_end_further_away(self):
        self.guess(TASKS_RUN, 5)
        self.guess(TASKS_RUN, 3)
        AuditLog.objects.filter(action="task.reset_refused").update(created_at=timezone.now() - timedelta(minutes=services.RESET_LOCK_MINUTES + 1))
        self.assertTrue(AuditLog.objects.filter(action="task.reset_locked", created_at__gte=timezone.now() - timedelta(minutes=5)).exists())
        answer = self.post(self.admin, TASKS_RUN, {"password": ADMIN_PASSWORD, "confirm": True})
        self.assertEqual(answer.status_code, 200)

    def test_it_is_per_admin(self):
        other = User.objects.create_user("person_admin_two", password="pw-two", role=Role.ADMIN)
        self.guess(TASKS_RUN, 5)
        answer = self.post(other, TASKS_RUN, {"password": "pw-two", "confirm": True})
        self.assertEqual(answer.status_code, 200)

    def test_somebody_who_is_not_an_admin_neither_counts_nor_is_counted(self):
        before = AuditLog.objects.filter(action__in=("task.reset_refused", "mail.reset_refused")).count()
        for user in (self.ops, self.sales):
            self.guess(TASKS_RUN, 7, user)
        self.assertEqual(AuditLog.objects.filter(action__in=("task.reset_refused", "mail.reset_refused")).count(), before)
        ok, error, _backup, _deleted = services.reset_all_tasks(self.ops, "x")
        self.assertFalse(ok)
        self.assertNotEqual(error, services.RESET_LOCKED_MESSAGE)

    def test_the_wrong_password_itself_still_says_wrong_before_the_limit(self):
        answer = self.post(self.admin, TASKS_RUN, {"password": "not-it", "confirm": True})
        self.assertEqual((answer.status_code, _json(answer)["error"]), (400, "refused"))


class TheBackupSurvivesTests(_Tools):
    """The backup is the only copy of what was deleted: a failure after the delete must not cost the admin the file."""

    def test_a_failed_audit_row_does_not_lose_the_tasks_backup(self):
        with mock.patch("dashboard.identity.record_export", side_effect=RuntimeError("audit write failed")):
            answer = self.post(self.admin, TASKS_RUN, {"password": ADMIN_PASSWORD, "confirm": True})
        self.assertEqual(answer.status_code, 200)
        self.assertIn("attachment", answer["Content-Disposition"])
        self.assertTrue(any(entry["model"] == "dashboard.task" for entry in json.loads(answer.content.decode("utf-8"))))
        self.assertFalse(Task.objects.exists())

    def test_a_failed_audit_row_does_not_lose_the_mail_backup(self):
        self.letter()
        with mock.patch("dashboard.identity.record_export", side_effect=RuntimeError("audit write failed")):
            answer = self.post(self.admin, MAIL_RUN, {"password": ADMIN_PASSWORD, "confirm": True})
        self.assertEqual(answer.status_code, 200)
        self.assertEqual(answer["X-Eagle-Deleted"], "1")
