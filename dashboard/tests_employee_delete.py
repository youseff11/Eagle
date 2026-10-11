"""Deleting a person from the staff (``employees.delete_employee``): the admin's alone, and the tasks keep the name.

The row stays, switched off and stamped ``deleted_at``: the person cannot sign in, the register and the pickers leave them out,
and every task they worked still names them, marked ``gone`` so the page draws the name in the "deleted" colour. The admin
reads the deleted on their own list (``?deleted=1``) and may take a delete back. Somebody who still holds work, an admin and
the admin themself are refused.
"""

import json

from django.contrib.auth import authenticate
from django.test import Client as DjangoClient
from django.urls import reverse

from .models import AuditLog, Task, TaskStatus, User
from .tests_admin_screen import _Admin
from .tests_api_v1 import _json

DELETE = "dashboard:v1_hr_employee_delete"
RESTORE = "dashboard:v1_hr_employee_restore"
REGISTER = "dashboard:v1_hr_register"
FILE = "dashboard:v1_hr_employee"
SAVE = "dashboard:v1_admin_user_save"
TASKS = "dashboard:v1_tasks"
TASK = "dashboard:v1_task"
TRANSLATOR_TASK = "dashboard:v1_translator_task"


class _Deleting(_Admin):
    def post(self, user, name, args=None, body=None):
        browser = DjangoClient()
        if user is not None:
            browser.force_login(user)
        return browser.post(reverse(name, args=args), json.dumps(body or {}), content_type="application/json")

    def finish(self):
        """The task is delivered: nobody holds it any more."""
        Task.objects.filter(pk=self.task.pk).update(status=TaskStatus.DELIVERED)

    def register_ids(self, user, **query):
        answer = self.get(user, REGISTER, **query)
        self.assertEqual(answer.status_code, 200)
        return {row["id"] for row in _json(answer)["rows"]}


class DoorTests(_Deleting):
    def test_only_the_admin_reaches_the_doors(self):
        self.finish()
        for door in (DELETE, RESTORE):
            for user in (self.ops, self.lead, self.tr, self.hr, self.reviewer, self.accounting, self.sales):
                denied = self.post(user, door, [self.tr.pk])
                self.assertEqual(denied.status_code, 403, (door, user.username))
            self.assertEqual(self.post(None, door, [self.tr.pk]).status_code, 401)
        self.tr.refresh_from_db()
        self.assertIsNone(self.tr.deleted_at)
        self.assertTrue(self.tr.is_active)

    def test_an_unknown_person_is_404(self):
        self.assertEqual(self.post(self.admin, DELETE, [999999]).status_code, 404)


class RefusalTests(_Deleting):
    def test_a_translator_still_on_a_task_is_refused_and_nothing_moves(self):
        answer = self.post(self.admin, DELETE, [self.tr.pk])
        self.assertEqual(answer.status_code, 409)
        self.assertEqual(_json(answer)["error"], "refused")
        self.tr.refresh_from_db()
        self.assertIsNone(self.tr.deleted_at)
        self.assertTrue(self.tr.is_active)
        self.assertFalse(AuditLog.objects.filter(action="user.delete").exists())

    def test_a_leader_whose_task_is_not_reviewed_yet_is_refused(self):
        Task.objects.filter(pk=self.task.pk).update(status=TaskStatus.UNDER_REVIEW)
        self.assertEqual(self.post(self.admin, DELETE, [self.lead.pk]).status_code, 409)
        self.lead.refresh_from_db()
        self.assertIsNone(self.lead.deleted_at)

    def test_the_admin_cannot_delete_themself_or_another_admin(self):
        other = User.objects.create_user("person_admin_two", password="pw", role="admin")
        self.assertEqual(self.post(self.admin, DELETE, [self.admin.pk]).status_code, 409)
        self.assertEqual(self.post(self.admin, DELETE, [other.pk]).status_code, 409)
        self.assertFalse(User.objects.filter(deleted_at__isnull=False).exists())

    def test_twice_is_refused(self):
        self.finish()
        self.assertEqual(self.post(self.admin, DELETE, [self.tr.pk]).status_code, 200)
        self.assertEqual(self.post(self.admin, DELETE, [self.tr.pk]).status_code, 409)


class DeleteTests(_Deleting):
    def setUp(self):
        super().setUp()
        self.finish()
        answer = self.post(self.admin, DELETE, [self.tr.pk])
        self.assertEqual((answer.status_code, _json(answer)), (200, {"ok": True}))
        self.tr.refresh_from_db()

    def test_the_person_is_switched_off_stamped_and_written_down(self):
        self.assertIsNotNone(self.tr.deleted_at)
        self.assertFalse(self.tr.is_active)
        self.assertTrue(AuditLog.objects.filter(action="user.delete", target=self.tr.username, actor=self.admin).exists())
        # The row is kept: the task still points at them.
        self.assertEqual(Task.objects.get(pk=self.task.pk).translator_id, self.tr.pk)

    def test_they_can_no_longer_sign_in(self):
        self.assertIsNone(authenticate(username=self.tr.username, password="pw"))

    def test_the_register_leaves_them_out_and_the_admin_reads_them_on_their_own_list(self):
        self.assertNotIn(self.tr.pk, self.register_ids(self.admin))
        self.assertNotIn(self.tr.pk, self.register_ids(self.hr))
        self.assertEqual(self.register_ids(self.admin, deleted="1"), {self.tr.pk})
        # HR asking for the deleted list gets the ordinary one: the list of the deleted is the admin's.
        self.assertNotIn(self.tr.pk, self.register_ids(self.hr, deleted="1"))
        row = _json(self.get(self.admin, REGISTER, deleted="1"))["rows"][0]
        self.assertIsNotNone(row["deleted_at"])

    def test_the_task_list_still_names_them_marked_gone(self):
        rows = _json(self.get(self.ops, TASKS, status="delivered"))["tasks"]
        row = next(one for one in rows if one["code"] == self.task.code)
        self.assertEqual(row["translator"], self.tr.short_name)
        self.assertEqual(row["gone"], ["translator"])

    def test_the_task_page_still_names_them_marked_gone(self):
        people = _json(self.get(self.ops, TASK, [self.task.code]))["task"]["people"]
        self.assertEqual(people["translator"], self.tr.short_name)
        self.assertEqual(people["gone"], ["translator"])

    def test_a_person_still_here_is_not_marked(self):
        people = _json(self.get(self.ops, TASK, [self.task.code]))["task"]["people"]
        self.assertNotIn("team_lead", people["gone"])
        self.assertNotIn("operation", people["gone"])

    def test_the_file_says_deleted_offers_restore_and_nothing_else(self):
        body = _json(self.get(self.admin, FILE, [self.tr.pk]))
        self.assertIsNotNone(body["person"]["deleted_at"])
        self.assertEqual(
            (body["can"]["edit"], body["can"]["delete"], body["can"]["restore"], body["can"]["shift"]), (False, False, True, False)
        )
        # HR reads the file but may not take the delete back.
        self.assertFalse(_json(self.get(self.hr, FILE, [self.tr.pk]))["can"]["restore"])

    def test_the_account_form_cannot_switch_them_back_on_half_deleted(self):
        answer = self.post(self.admin, SAVE, [self.tr.pk], {"values": {"is_active": True}})
        self.assertEqual((answer.status_code, _json(answer)["error"]), (409, "deleted"))
        self.tr.refresh_from_db()
        self.assertFalse(self.tr.is_active)

    def test_restore_brings_them_back_and_clears_the_mark(self):
        answer = self.post(self.admin, RESTORE, [self.tr.pk])
        self.assertEqual(answer.status_code, 200)
        self.tr.refresh_from_db()
        self.assertIsNone(self.tr.deleted_at)
        self.assertTrue(self.tr.is_active)
        self.assertTrue(AuditLog.objects.filter(action="user.restore", target=self.tr.username).exists())
        self.assertIn(self.tr.pk, self.register_ids(self.admin))
        self.assertEqual(_json(self.get(self.ops, TASK, [self.task.code]))["task"]["people"]["gone"], [])
        # Restoring somebody who is not deleted is refused.
        self.assertEqual(self.post(self.admin, RESTORE, [self.tr.pk]).status_code, 409)


class OperationGoneTests(_Deleting):
    def test_the_translator_page_marks_a_deleted_operation(self):
        self.finish()
        self.assertEqual(self.post(self.admin, DELETE, [self.ops.pk]).status_code, 200)
        people = _json(self.get(self.admin, TRANSLATOR_TASK, [self.task.code]))["task"]["people"]
        self.assertEqual(people["operation"], self.ops.short_name)
        self.assertEqual(people["gone"], ["operation"])
