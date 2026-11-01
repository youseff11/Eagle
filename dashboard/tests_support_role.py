"""Technical support: the owner's own account, with the admin's screens and the admin's powers (01/11/2026).

What is held here:

* every screen and every door the admin has answers the support account the same way (``User.is_admin_role``), and it starts
  where the owner does;
* it is on none of the company's rules: no attendance, no roster, no leave, no pay, and the wipe of the staff leaves it alone;
* it is still not the owner: it is a role of its own (``is_owner_role`` is False), tagged as support in the chats, reachable by
  everybody from the assistant, and it keeps the one page that is its own (the notice to all employees).
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
        self.assertTrue(self.support.is_admin_role)
        self.assertFalse(self.support.is_owner_role)
        self.assertTrue(self.admin.is_owner_role)

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

    def test_it_has_the_admins_screens_and_none_of_the_company_rules(self):
        # The admin's menu, then the one screen that is the support's own.
        self.assertEqual(newui.enabled_keys(self.support), [*newui.enabled_keys(self.admin), "support"])
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


class LikeTheAdminTests(_Support):
    """Every door the admin has answers support the same way: a status that differs is a door the role still blocks."""

    def rich_task(self):
        message = services.ingest_message(
            channel="whatsapp", body="Please translate the secret lease", sender_identity=self.client_obj.phone,
            attachments=[{"file": ContentFile(b"%PDF-1.4 lease", name="lease.pdf"), "name": "lease.pdf", "size": 14}],
        )
        task = services.create_task(client=self.client_obj, title="Lease", created_by=self.ops, messages=[message])
        ClientRequirement.objects.create(client=self.client_obj, kind="rule", text="Formal tone, no contractions", author=self.ops)
        OutboundMessage.objects.create(client=self.client_obj, task=task, channel="email", body="here it is", status="sent")
        return task

    def client_get(self, path, user):
        browser = DjangoClient()
        browser.force_login(user)
        return browser.get(path)

    def test_it_reads_the_list_and_the_team_board(self):
        data = _json(self.get(self.support, "v1_tasks"))
        self.assertEqual([row["code"] for row in data["tasks"]], [self.task.code])
        self.assertEqual(self.get(self.support, "v1_team").status_code, 200)

    def test_a_task_is_the_same_page_for_support_as_for_the_admin(self):
        task = self.rich_task()
        seen = _json(self.client_get(f"/api/v1/tasks/{task.code}/", self.admin))["task"]
        got = _json(self.client_get(f"/api/v1/tasks/{task.code}/", self.support))["task"]
        self.assertFalse(got["watching"])
        self.assertEqual(got["can"], seen["can"])
        self.assertTrue(got["can"]["cancel"])
        self.assertEqual([f["name"] for f in got["files"]["original"]], ["lease.pdf"])
        self.assertTrue(got["requirements"])
        self.assertTrue(got["deliveries"])
        self.assertTrue(got["messages"])
        self.assertEqual(got["files"], seen["files"])

    def test_the_files_of_the_task_open_for_it(self):
        message = services.ingest_message(
            channel="whatsapp", body="the file", sender_identity=self.client_obj.phone,
            attachments=[{"file": ContentFile(b"%PDF-1.4 secret", name="lease.pdf"), "name": "lease.pdf", "size": 15}],
        )
        services.create_task(client=self.client_obj, title="Lease", created_by=self.ops, messages=[message])
        name = message.attachments.get().file.name
        self.assertTrue(files.may_open(self.admin, name)[0])
        self.assertTrue(files.may_open(self.support, name)[0])

    def test_the_admins_doors_open_for_it(self):
        for name, args in (
            ("v1_clients", None), ("v1_mail_threads", None), ("v1_admin_overview", None), ("v1_accounts_overview", None),
            ("v1_hr_board", None),
        ):
            admin = self.get(self.admin, name, args)
            support = self.get(self.support, name, args)
            with self.subTest(door=name):
                self.assertEqual(support.status_code, admin.status_code, support.content)
                self.assertNotEqual(support.status_code, 403)

    def test_it_changes_a_task_as_the_admin_does(self):
        code = self.task.code
        for name, args, how in (
            ("v1_task_words", [code], {"body": {"words": 100}}),
            ("v1_task_requirement", [code], {"body": {"kind": "rule", "text": "x"}}),
        ):
            with self.subTest(door=name):
                admin = self.post(self.admin, name, how.get("body"), args=args, form=how.get("form"))
                support = self.post(self.support, name, how.get("body"), args=args, form=how.get("form"))
                self.assertEqual(support.status_code, admin.status_code, support.content)
                self.assertNotEqual(support.status_code, 403)

    def test_it_is_told_what_the_admin_is_told(self):
        admin = _json(self.get(self.admin, "v1_me"))
        me = _json(self.get(self.support, "v1_me"))
        self.assertTrue(me["user"]["is_admin"])
        self.assertEqual(me["user"]["role"], "support")
        self.assertEqual(me["screens"], [*admin["screens"], "support"])
        self.assertEqual(me["can"], admin["can"])
        self.assertEqual(me["chats"]["types"], admin["chats"]["types"])
        self.assertEqual(me["chats"]["can_create_group"], admin["chats"]["can_create_group"])

    def test_the_client_conversations_open_for_it_as_for_the_admin(self):
        for name, args in (("v1_client_messages", [self.client_obj.code]), ("v1_room_messages", [self.task_client_room.pk])):
            admin = self.get(self.admin, name, args)
            with self.subTest(door=name):
                self.assertEqual(self.get(self.support, name, args).status_code, admin.status_code)

    def test_it_is_still_not_the_owner(self):
        # The owner's account cannot be deleted or demoted from the support account's file, and the last-owner rule counts owners only.
        owner = _json(self.get(self.support, "v1_hr_employee", [self.admin.pk]))
        self.assertFalse(owner["can"]["delete"])
        answer = self.post(self.admin, "v1_admin_user_save", {"values": {"first_name": "Samy"}}, args=[self.support.pk])
        self.assertEqual(answer.status_code, 200, answer.content)


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

    def test_it_makes_work_groups_as_the_admin_does(self):
        self.assertEqual(self.get(self.support, "v1_people").status_code, self.get(self.admin, "v1_people").status_code)
        made = self.post(self.support, "v1_group_create", {"title": "x", "members": [self.ops.pk]})
        self.assertEqual(made.status_code, self.post(self.admin, "v1_group_create", {"title": "x", "members": [self.ops.pk]}).status_code)


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

    def test_support_is_given_the_admins_guides_and_questions(self):
        mine = {guide.id for guide in helpbot.guides.for_user(self.support)}
        theirs = {guide.id for guide in helpbot.guides.for_user(self.admin)}
        # Everything the admin is told, except how to write to itself.
        self.assertEqual(mine, theirs - {"contact-support"})
        self.assertIn("admin-settings", mine)
        self.assertIn("ops-deliver", mine)
        self.assertEqual(
            [guide.id for guide in helpbot.starters(self.support)], [guide.id for guide in helpbot.starters(self.admin)],
        )
        for person in self.everyone:
            if person.is_support:
                continue
            self.assertIn("contact-support", {guide.id for guide in helpbot.guides.for_user(person)})

    def test_a_question_about_contacting_support_finds_the_guide(self):
        user = self.tr
        answer = helpbot._from_search(user, helpbot.guides.for_user(user), "عندي مشكلة في السيستم عايز اكلم الدعم الفني", "", "ar")
        self.assertEqual(answer.guide.id, "contact-support")
        self.assertIn("«تواصل مع الدعم الفني»", answer.text)

    def test_the_assistant_gives_it_orders_as_the_admin_and_a_support_day_cannot_be_set(self):
        AppSettings.objects.update(helpbot_ai_enabled=True, helpbot_actions_enabled=True, claude_api_key="sk-test-key-1234567890")
        self.assertTrue(helpactions.available(AppSettings.load(), self.support))
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
