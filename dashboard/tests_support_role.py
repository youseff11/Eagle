"""Technical support: the owner's own account for checking that everything runs.

What is held here:

* it reads the tasks (the list, a task's page, the team board) and nothing of the client's or the work's in them: no files, no
  messages, no requirements, no deliveries, no name - and it has no tool on a task at all;
* it is on none of the company's rules: no attendance, no roster, no leave, no pay, and the wipe of the staff leaves it alone;
* it is in the chats like a colleague, and says so (the role is on the row), and everybody can reach it from the assistant;
* it is never a way round the other roles' doors: whatever it may not do is a 403 from the same doors as before.
"""

import json
from unittest import mock

from django.core.files.base import ContentFile
from django.test import Client as DjangoClient
from django.urls import reverse

from . import files, helpactions, helpbot, newui, services
from .models import AppSettings, ChatAttachment, ClientRequirement, OutboundMessage, Role, Task, TaskStatus, User
from .tests_api_v1 import IDENTITY_MARKERS, _Site, _json


class _Support(_Site):
    def setUp(self):
        super().setUp()
        self.support = User.objects.create_user(
            "person_support", password="pw", role=Role.SUPPORT, first_name="Sami", last_name="Support", attendance_enabled=True
        )

    def post(self, user, name, body=None, args=None, form=None):
        browser = DjangoClient()
        browser.force_login(user)
        if form is not None:
            return browser.post(reverse(f"dashboard:{name}", args=args), form)
        return browser.post(reverse(f"dashboard:{name}", args=args), json.dumps(body or {}), content_type="application/json")


class TheAccountTests(_Support):
    def test_it_is_a_role_with_a_label(self):
        from .templatetags.eagle_tags import ROLE_MAP

        self.assertEqual(Role.SUPPORT.value, "support")
        self.assertEqual(ROLE_MAP["support"], ("دعم فني", "Technical support"))
        self.assertTrue(self.support.is_support)
        self.assertFalse(self.support.is_admin_role)

    def test_it_follows_none_of_the_company_rules_and_never_clocks_in(self):
        self.assertFalse(self.support.follows_company_rules)
        # Created with attendance on: the model turns it off, as it does for the owner.
        self.support.refresh_from_db()
        self.assertFalse(self.support.attendance_enabled)
        # Somebody who is moved to support stops clocking in too.
        self.tr.attendance_enabled = True
        self.tr.save()
        self.tr.role = Role.SUPPORT
        self.tr.save()
        self.tr.refresh_from_db()
        self.assertFalse(self.tr.attendance_enabled)
        for other in (self.ops, self.hr, self.sales):
            self.assertTrue(other.follows_company_rules)

    def test_the_owner_makes_one_from_the_staff_form(self):
        body = {"values": {"username": "second_support", "first_name": "Nada", "last_name": "Tech", "role": "support",
                           "password1": "Mx7-quiet-harbour-41", "password2": "Mx7-quiet-harbour-41"}}
        answer = self.post(self.admin, "v1_admin_user_create", body)
        self.assertEqual(answer.status_code, 200, answer.content)
        made = User.objects.get(username="second_support")
        self.assertEqual((made.role, made.attendance_enabled), (Role.SUPPORT, False))

    def test_its_attendance_box_is_off_and_cannot_be_ticked(self):
        answer = self.post(self.admin, "v1_admin_user_save", {"values": {"attendance_enabled": True}}, args=[self.support.pk])
        self.assertEqual(answer.status_code, 200, answer.content)
        self.support.refresh_from_db()
        self.assertFalse(self.support.attendance_enabled)

    def test_it_has_no_screen_of_the_company_rules(self):
        self.assertEqual(sorted(newui.enabled_keys(self.support)), ["chats", "support"])
        for person in self.everyone:
            self.assertNotIn("support", newui.enabled_keys(person))
        self.assertNotIn("attendance", newui.enabled_keys(self.support))
        self.assertNotIn("leave", newui.enabled_keys(self.support))

    def test_it_cannot_ask_for_leave_or_clock_in(self):
        refused = self.post(self.support, "v1_leave_request", {"values": {"kind": "annual", "start_date": "2026-11-01", "end_date": "2026-11-02"}})
        self.assertEqual(refused.status_code, 409, refused.content)
        self.assertEqual(self.support.leave_requests.count(), 0)
        card = _json(self.get(self.support, "v1_attendance"))
        self.assertFalse(card["enabled"])

    def test_the_wipe_of_the_staff_leaves_it_and_the_owner(self):
        left = set(services._staff_to_clear().values_list("pk", flat=True))
        self.assertNotIn(self.support.pk, left)
        self.assertNotIn(self.admin.pk, left)
        self.assertIn(self.ops.pk, left)

    def test_a_day_cannot_be_set_for_it(self):
        with self.assertRaises(helpactions.Problem):
            helpactions._override_check({"employee": {"id": self.support.pk, "name": "Sami"}, "day_off": True}, None)
        helpactions._override_check({"employee": {"id": self.ops.pk, "name": "Omar"}, "day_off": True}, None)

    def test_the_employee_file_says_why_it_has_no_rules(self):
        data = _json(self.get(self.hr, "v1_hr_employee", [self.support.pk]))
        self.assertEqual((data["person"]["exempt"], data["person"]["exempt_why"]), (True, "support"))
        self.assertEqual((data["shifts"], data["leave"], data["salary"]), ([], [], []))
        owner = _json(self.get(self.hr, "v1_hr_employee", [self.admin.pk]))
        self.assertEqual(owner["person"]["exempt_why"], "owner")
        ordinary = _json(self.get(self.hr, "v1_hr_employee", [self.ops.pk]))
        self.assertEqual((ordinary["person"]["exempt"], ordinary["person"]["exempt_why"]), (False, ""))

    def test_no_shift_can_be_given_to_it(self):
        self.assertEqual(self.post(self.hr, "v1_hr_employee_shift", {}, args=[self.support.pk]).status_code, 400)


class WatchingTheTasksTests(_Support):
    def test_support_reads_the_list_and_the_team_board(self):
        data = _json(self.get(self.support, "v1_tasks"))
        self.assertEqual([row["code"] for row in data["tasks"]], [self.task.code])
        self.assertEqual(data["tasks"][0]["client"], self.client_obj.code)
        self.assertEqual(self.get(self.support, "v1_team").status_code, 200)

    def test_it_reads_a_task_that_is_not_its_own_with_everything_of_the_clients_left_out(self):
        answer = self.get(self.support, "v1_ops_task", [self.task.code]) if False else self.client_get(f"/api/v1/tasks/{self.task.code}/", self.support)
        self.assertEqual(answer.status_code, 200)
        task = _json(answer)["task"]
        self.assertTrue(task["watching"])
        self.assertEqual(task["files"], {"original": [], "translation": []})
        self.assertEqual((task["requirements"], task["deliveries"], task["messages"]), ([], [], []))
        self.assertIsNone(task["chat"])
        self.assertIsNone(task["client_chat_url"])
        self.assertIsNone(task["lead"])
        self.assertEqual(task["leads"], [])
        self.assertEqual(task["group_candidates"], [])
        self.assertFalse(any(task["can"].values()), task["can"])
        # What it is there for is in it: who has the task, its state and the hand-off history.
        self.assertEqual(task["people"]["team_lead"], self.lead.short_name)
        self.assertEqual(task["people"]["translator"], self.tr.short_name)
        self.assertTrue(task["history"])
        self.assertEqual(task["client"], self.client_obj.code)
        for marker in IDENTITY_MARKERS:
            self.assertNotIn(marker, answer.content.decode("utf-8"))

    def rich_task(self):
        """A task with everything on it that support must not read: the client's file, a message, a requirement and a delivery."""
        message = services.ingest_message(
            channel="whatsapp", body="Please translate the secret lease", sender_identity=self.client_obj.phone,
            attachments=[{"file": ContentFile(b"%PDF-1.4 lease", name="lease.pdf"), "name": "lease.pdf", "size": 14}],
        )
        task = services.create_task(client=self.client_obj, title="Lease", created_by=self.ops, messages=[message])
        ClientRequirement.objects.create(client=self.client_obj, kind="rule", text="Formal tone, no contractions", author=self.ops)
        OutboundMessage.objects.create(client=self.client_obj, task=task, channel="email", body="here it is", status="sent")
        return task

    def test_the_operation_sees_what_support_does_not_and_support_sees_none_of_it(self):
        task = self.rich_task()
        seen = _json(self.client_get(f"/api/v1/tasks/{task.code}/", self.ops))["task"]
        self.assertFalse(seen["watching"])
        self.assertTrue(seen["can"]["cancel"])
        # The same task: the operation has all of it, so the emptiness for support is the door's doing, not the fixture's.
        self.assertEqual([f["name"] for f in seen["files"]["original"]], ["lease.pdf"])
        self.assertTrue(seen["requirements"])
        self.assertTrue(seen["deliveries"])
        self.assertTrue(seen["messages"])
        answer = self.client_get(f"/api/v1/tasks/{task.code}/", self.support)
        watched = _json(answer)["task"]
        self.assertEqual(watched["files"], {"original": [], "translation": []})
        self.assertEqual((watched["requirements"], watched["deliveries"], watched["messages"]), ([], [], []))
        text = answer.content.decode("utf-8")
        for leaked in ("lease.pdf", "secret lease", "Formal tone", "here it is"):
            self.assertNotIn(leaked, text)

    def test_a_task_that_is_not_there_is_not_found(self):
        self.assertEqual(self.client_get("/api/v1/tasks/TSK-99999/", self.support).status_code, 404)

    def test_support_may_watch_but_never_view(self):
        self.assertTrue(self.task.can_watch(self.support))
        self.assertFalse(self.task.can_view(self.support))
        for other in (self.ops, self.lead, self.tr, self.hr, self.reviewer, self.accounting, self.sales):
            self.assertFalse(self.task.can_watch(other), other.role)

    def test_the_files_of_the_task_do_not_open_for_it(self):
        client = self.client_obj
        message = services.ingest_message(
            channel="whatsapp", body="the file", sender_identity=client.phone,
            attachments=[{"file": ContentFile(b"%PDF-1.4 secret", name="lease.pdf"), "name": "lease.pdf", "size": 15}],
        )
        task = services.create_task(client=client, title="Lease", created_by=self.ops, messages=[message])
        name = message.attachments.get().file.name
        self.assertTrue(files.may_open(self.ops, name)[0])
        self.assertFalse(files.may_open(self.support, name)[0])
        # Nor the translator's own hand-in, nor a task room's attachment.
        chat = services.ensure_room(task, services.RoomKind.GROUP) if hasattr(services, "RoomKind") else self.task_group
        post = chat.messages.create(sender=self.ops, body="x")
        attachment = ChatAttachment.objects.create(message=post, file=ContentFile(b"translated", name="out.docx"), original_name="out.docx")
        self.assertFalse(files.may_open(self.support, attachment.file.name)[0])

    def test_it_changes_nothing_on_a_task(self):
        before = Task.objects.get(pk=self.task.pk).status
        code = self.task.code
        attempts = [
            ("api_task_action", [code, "cancel"], {"form": {"reason": "x"}}),
            ("api_task_action", [code, "delivered"], {"form": {}}),
            ("api_task_action", [code, "ack"], {"form": {}}),
            ("api_assign_lead", [code], {"form": {"user": str(self.lead.pk)}}),
            ("api_deliver", [code], {"form": {"send": "1"}}),
            ("v1_task_words", [code], {"body": {"words": 100}}),
            ("v1_task_requirement", [code], {"body": {"kind": "rule", "text": "x"}}),
            ("v1_task_create", None, {"body": {}}),
        ]
        for name, args, how in attempts:
            answer = self.post(self.support, name, how.get("body"), args=args, form=how.get("form"))
            with self.subTest(door=name):
                self.assertIn(answer.status_code, (400, 403, 404), answer.content)
        self.assertEqual(Task.objects.get(pk=self.task.pk).status, before)
        self.assertEqual(Task.objects.count(), 1)

    def test_it_is_turned_away_from_every_other_roles_doors(self):
        for name, args in (
            ("v1_clients", None), ("v1_client", [self.client_obj.code]), ("v1_mail_threads", None), ("v1_task_start", None),
            ("v1_translator_home", None), ("v1_lead", None), ("v1_admin_overview", None), ("v1_accounts_overview", None),
            ("v1_hr_board", None), ("v1_sales_line", None),
        ):
            answer = self.get(self.support, name, args)
            with self.subTest(door=name):
                self.assertEqual(answer.status_code, 403, answer.content)

    def test_it_has_no_client_conversations_in_its_chats(self):
        me = _json(self.get(self.support, "v1_me"))
        self.assertEqual(me["chats"]["types"], ["groups", "staff"])
        self.assertEqual(sorted(me["screens"]), ["chats", "support"])
        self.assertEqual(me["can"], {"manage_attendance": False, "recruit": False, "review_tests": False, "approve_hiring": False})
        self.assertFalse(me["chats"]["can_create_group"])
        self.assertIn(self.get(self.support, "v1_client_messages", [self.client_obj.code]).status_code, (403, 404))
        self.assertIn(self.get(self.support, "v1_room_messages", [self.task_client_room.pk]).status_code, (403, 404))

    def client_get(self, path, user):
        browser = DjangoClient()
        browser.force_login(user)
        return browser.get(path)


class InTheChatsTests(_Support):
    def test_it_is_in_everybodys_colleague_list_tagged_as_support(self):
        for person in self.everyone:
            data = _json(self.get(person, "v1_chats", type="staff"))
            rows = {row["code"]: row for row in data["items"]}
            with self.subTest(person=person.role):
                self.assertEqual(rows[f"u{self.support.pk}"]["role"], "support")
                other = next(row for code, row in rows.items() if code != f"u{self.support.pk}")
                self.assertNotEqual(other["role"], "support")

    def test_the_chat_header_row_says_it_too_before_anybody_has_written(self):
        data = _json(self.get(self.ops, "v1_staff_messages", [self.support.pk]))
        self.assertEqual(data["client"]["role"], "support")

    def test_everybody_can_write_to_it_and_it_can_write_back(self):
        for person in (self.ops, self.lead, self.tr, self.hr, self.reviewer, self.accounting, self.sales, self.admin):
            sent = self.post(person, "v1_staff_send", args=[self.support.pk], form={"body": f"hello from {person.role}"})
            with self.subTest(person=person.role):
                self.assertEqual(sent.status_code, 200, sent.content)
        back = self.post(self.support, "v1_staff_send", args=[self.ops.pk], form={"body": "on it"})
        self.assertEqual(back.status_code, 200, back.content)
        seen = _json(self.get(self.ops, "v1_staff_messages", [self.support.pk]))["messages"]
        self.assertEqual([m["body"] for m in seen], ["hello from operation", "on it"])

    def test_it_cannot_open_a_work_group_with_a_client_or_make_one(self):
        self.assertEqual(self.get(self.support, "v1_people").status_code, 403)
        self.assertEqual(self.post(self.support, "v1_group_create", {"title": "x", "members": [self.ops.pk]}).status_code, 403)


class AssistantTests(_Support):
    def test_everybody_but_support_is_told_who_to_write_to(self):
        for person in self.everyone:
            data = _json(self.get(person, "v1_help"))
            with self.subTest(person=person.role):
                self.assertEqual(data["support"], {"id": self.support.pk, "name": "Sami Support"})
        self.assertIsNone(_json(self.get(self.support, "v1_help"))["support"])

    def test_nobody_is_pointed_at_when_there_is_no_support_account(self):
        User.objects.filter(role=Role.SUPPORT).update(is_active=False)
        self.assertIsNone(_json(self.get(self.tr, "v1_help"))["support"])
        User.objects.filter(pk=self.support.pk).update(is_active=True)
        second = User.objects.create_user("second_support", password="pw", role=Role.SUPPORT)
        # The first account is the one named.
        self.assertEqual(_json(self.get(self.tr, "v1_help"))["support"]["id"], self.support.pk)
        self.assertNotEqual(second.pk, self.support.pk)

    def test_support_is_given_its_own_guides_and_questions(self):
        guides_for = helpbot.guides.for_user(self.support)
        ids = {guide.id for guide in guides_for}
        self.assertIn("support-tasks", ids)
        self.assertIn("chat-send", ids)
        self.assertTrue({"attendance-checkin", "leave-ask", "tr-work", "ops-deliver", "acc-month", "hr-board", "admin-settings"}.isdisjoint(ids))
        starters = [guide.id for guide in helpbot.starters(self.support)]
        self.assertEqual(starters[0], "support-tasks")
        self.assertGreaterEqual(len(starters), 3)
        # Nobody else is told how support reads tasks, and support is not told how to contact itself.
        for person in self.everyone:
            self.assertNotIn("support-tasks", {guide.id for guide in helpbot.guides.for_user(person)})
        self.assertNotIn("contact-support", ids)
        for person in self.everyone:
            self.assertIn("contact-support", {guide.id for guide in helpbot.guides.for_user(person)})

    def test_a_question_about_contacting_support_finds_the_guide(self):
        user = self.tr
        answer = helpbot._from_search(user, helpbot.guides.for_user(user), "عندي مشكلة في السيستم عايز اكلم الدعم الفني", "", "ar")
        self.assertEqual(answer.guide.id, "contact-support")
        self.assertIn("«تواصل مع الدعم الفني»", answer.text)

    def test_the_assistant_gives_it_no_orders_and_it_cannot_be_the_target_of_the_wrong_one(self):
        AppSettings.objects.update(helpbot_ai_enabled=True, helpbot_actions_enabled=True, claude_api_key="sk-test-key-1234567890")
        self.assertFalse(helpactions.available(AppSettings.load(), self.support))
        # An order that names support is looked up like any person (and it has no schedule to change).
        with mock.patch.object(helpbot, "_call_claude") as call:
            call.return_value = json.dumps({"answer": "x", "guides": [], "found": True, "action": {
                "name": "day.override", "params": {"employee": "Sami", "date": "2026-11-01", "day_off": True}}})
            self.client.force_login(self.admin)
            data = self.client.post(
                reverse("dashboard:v1_help_ask"), json.dumps({"question": "اعمل اجازة لسامي", "lang": "ar"}), content_type="application/json"
            ).json()
        self.assertIsNone(data["order"])
        self.assertIn("جدول", data["answer"])
