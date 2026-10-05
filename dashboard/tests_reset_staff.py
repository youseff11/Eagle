"""Clearing the staff (``services.reset_all_staff``, ``api_admin_tools.reset_staff_*``), for an owner who starts again with real people.

Held here: it is as hard to do by accident as the other two clear-outs (the admin alone, their own password, an explicit yes, one
count of wrong passwords for all of them); every admin stays; what is a person's goes with them; what would turn somebody's
private line into the company's does not happen (the letters go with the person, or nothing is done); a client's rooms and the
tasks stay; and the backup carries no password hash.
"""

import json
import tempfile
from datetime import time

from django.conf import settings
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import override_settings
from django.urls import reverse

from . import avatars, identity, services
from .models import (
    AuditLog, Channel, ChatMessage, ChatRoom, InboundMessage, LeaveRequest, MessageAttachment, OutboundMessage, Role, RoomKind, Shift,
    Task, User, WorkDay,
)
from .tests_admin_tools import ADMIN_PASSWORD, _Tools
from .tests_api_v1 import _json
from .tests_avatar import jpeg

COUNTS = "dashboard:v1_admin_reset_staff"
RUN = "dashboard:v1_admin_reset_staff_run"
GONE = ("ops", "lead", "tr", "hr", "reviewer", "accounting", "sales")


class _Staff(_Tools):
    def run_reset(self, who=None, **over):
        body = {"password": ADMIN_PASSWORD, "confirm": True}
        body.update(over)
        return self.post(who or self.admin, RUN, body)

    def staff_ids(self):
        return [getattr(self, name).pk for name in GONE]

    def survivors(self):
        return set(User.objects.values_list("username", flat=True))


class DoorTests(_Staff):
    def test_only_the_admin_is_answered(self):
        for method, name in (("GET", COUNTS), ("POST", RUN)):
            for user in (self.ops, self.lead, self.tr, self.hr, self.reviewer, self.accounting, self.sales):
                browser = self.client_for(user)
                answer = browser.get(reverse(name)) if method == "GET" else browser.post(reverse(name), json.dumps({"password": "pw", "confirm": True}), content_type="application/json")
                self.assertEqual((answer.status_code, _json(answer)), (403, {"ok": False, "error": "forbidden"}), (name, user.username))
            anonymous = self.client_for(None)
            answer = anonymous.get(reverse(name)) if method == "GET" else anonymous.post(reverse(name), "{}", content_type="application/json")
            self.assertEqual(answer.status_code, 401, name)
        self.assertEqual(len(self.staff_ids()), 7)
        self.assertEqual(User.objects.filter(pk__in=self.staff_ids()).count(), 7)

    def test_the_wrong_method_is_a_405_that_says_what_is_allowed(self):
        browser = self.client_for(self.admin)
        for method, name, wrong in (("GET", COUNTS, "post"), ("POST", RUN, "get")):
            answer = getattr(browser, wrong)(reverse(name))
            self.assertEqual((answer.status_code, answer["Allow"]), (405, method), name)

    def test_every_answer_is_private_and_a_get_changes_nothing(self):
        before = (User.objects.count(), AuditLog.objects.count())
        answer = self.client_for(self.admin).get(reverse(COUNTS))
        self.assertEqual(answer["Cache-Control"], "private, no-store")
        self.assertEqual((User.objects.count(), AuditLog.objects.count()), before)

    def client_for(self, user):
        from django.test import Client as DjangoClient

        browser = DjangoClient()
        if user is not None:
            browser.force_login(user)
        return browser


class CountsTests(_Staff):
    def test_it_counts_the_people_and_what_is_theirs(self):
        Shift.objects.create(user=self.tr, weekday=0, start_time=time(9), end_time=time(17))
        WorkDay.objects.create(user=self.tr, date=self.today if hasattr(self, "today") else __import__("datetime").date.today(), status="present")
        ChatRoom.objects.create(kind=RoomKind.STAFF, pair_key=services.staff_pair_key(self.ops.pk, self.lead.pk)).members.add(self.ops, self.lead)
        counts = _json(self.get(self.admin, COUNTS))["counts"]
        self.assertEqual((counts["people"], counts["kept"]), (7, 1))
        self.assertEqual((counts["shifts"], counts["work_days"], counts["rooms"]), (1, 1, 1))
        # The task in the fixture names the operation, the leader and the translator.
        self.assertEqual(counts["tasks_touched"], 1)

    def test_it_says_when_a_task_stands_on_a_private_line(self):
        InboundMessage.objects.create(channel=Channel.EMAIL, sender_identity="a@x.example", body="b", owner=self.sales, task=self.task)
        counts = _json(self.get(self.admin, COUNTS))["counts"]
        self.assertEqual((counts["line_letters"], counts["line_blocked"]), (1, 1))


class GuardTests(_Staff):
    def assert_nothing_deleted(self):
        self.assertEqual(User.objects.filter(pk__in=self.staff_ids()).count(), 7)

    def test_without_the_explicit_yes_nothing_is_deleted(self):
        for confirm in (None, False, "true", 1, "yes"):
            body = {"password": ADMIN_PASSWORD}
            if confirm is not None:
                body["confirm"] = confirm
            answer = self.post(self.admin, RUN, body)
            self.assertEqual((answer.status_code, _json(answer)["error"]), (400, "confirm_required"), confirm)
        self.assert_nothing_deleted()

    def test_a_wrong_password_deletes_nothing_and_is_written_down(self):
        answer = self.run_reset(password="not-it")
        self.assertEqual((answer.status_code, _json(answer)["error"]), (400, "refused"))
        self.assert_nothing_deleted()
        self.assertEqual(AuditLog.objects.filter(actor=self.admin, action="staff.reset_refused").count(), 1)
        self.assertNotIn("not-it", " ".join(row.detail + row.target for row in AuditLog.objects.all()))

    def test_five_wrong_ones_shut_it_even_to_the_right_password_and_the_other_clear_outs_with_it(self):
        for _ in range(services.RESET_WRONG_LIMIT):
            self.run_reset(password="not-it")
        answer = self.run_reset()
        self.assertEqual((answer.status_code, _json(answer)["error"]), (429, "too_many_attempts"))
        self.assert_nothing_deleted()
        # One count: the tasks and mail clear-outs are shut too.
        self.assertEqual(self.post(self.admin, "dashboard:v1_admin_reset_tasks_run", {"password": ADMIN_PASSWORD, "confirm": True}).status_code, 429)

    def test_wrong_tries_at_the_other_doors_count_here(self):
        for _ in range(services.RESET_WRONG_LIMIT):
            self.post(self.admin, "dashboard:v1_admin_reset_mail_run", {"password": "not-it", "confirm": True})
        self.assertEqual(self.run_reset().status_code, 429)
        self.assert_nothing_deleted()

    def test_a_body_that_is_not_the_shape_deletes_nothing(self):
        for body in ({"password": 5, "confirm": True}, {"password": ["x"], "confirm": True}, {"password": "x" * 500, "confirm": True}):
            self.assertEqual(self.post(self.admin, RUN, body).status_code, 400)
        self.assert_nothing_deleted()

    def test_the_password_is_nowhere_in_the_answer_or_the_log(self):
        answer = self.run_reset()
        text = answer.content.decode("utf-8") + " ".join(f"{row.target} {row.detail}" for row in AuditLog.objects.all())
        self.assertNotIn("md5$", text)
        self.assertNotIn("pbkdf2", text)


class RunTests(_Staff):
    def test_every_employee_goes_and_every_admin_stays(self):
        second = User.objects.create_user("second_admin", password="pw", role=Role.ADMIN)
        boss = User.objects.create_superuser("the_owner", password="pw", role=Role.HR)
        answer = self.run_reset()
        self.assertEqual(answer.status_code, 200)
        self.assertEqual(self.survivors(), {self.admin.username, second.username, boss.username})
        self.assertEqual(answer["X-Eagle-Deleted"], "7")

    def test_the_answer_is_the_backup_file_without_a_password_hash(self):
        answer = self.run_reset()
        self.assertTrue(answer["Content-Disposition"].startswith('attachment; filename="eagle-staff-backup-'))
        rows = json.loads(answer.content.decode("utf-8"))
        people = [row for row in rows if row["model"] == "dashboard.user"]
        self.assertEqual(len(people), 7)
        self.assertEqual({row["fields"]["username"] for row in people}, {getattr(self, name).username for name in GONE})
        for row in people:
            self.assertNotIn("password", row["fields"])
        self.assertNotIn("md5$", answer.content.decode("utf-8"))

    def test_what_is_a_persons_goes_with_them(self):
        Shift.objects.create(user=self.tr, weekday=0, start_time=time(9), end_time=time(17))
        LeaveRequest.objects.create(user=self.tr, start_date=__import__("datetime").date.today(), end_date=__import__("datetime").date.today())
        self.run_reset()
        self.assertEqual(Shift.objects.count(), 0)
        self.assertEqual(LeaveRequest.objects.count(), 0)

    def test_the_internal_chats_they_were_in_go_and_a_clients_room_stays(self):
        staff = ChatRoom.objects.create(kind=RoomKind.STAFF, pair_key=services.staff_pair_key(self.ops.pk, self.lead.pk))
        staff.members.add(self.ops, self.lead)
        ChatMessage.objects.create(room=staff, sender=self.ops, body="internal talk")
        team = ChatRoom.objects.create(kind=RoomKind.TEAM, title="Team", created_by=self.lead)
        team.members.add(self.lead, self.admin)
        client_room = ChatRoom.objects.create(kind=RoomKind.CLIENT, client=self.client_obj, title="Client group", created_by=self.ops)
        client_room.members.add(self.ops, self.admin)
        said = ChatMessage.objects.create(room=client_room, sender=self.ops, body="hello client")
        self.run_reset()
        self.assertFalse(ChatRoom.objects.filter(pk__in=[staff.pk, team.pk]).exists())
        self.assertFalse(ChatMessage.objects.filter(body="internal talk").exists())
        self.assertTrue(ChatRoom.objects.filter(pk=client_room.pk).exists())
        said.refresh_from_db()
        self.assertEqual((said.body, said.sender), ("hello client", None))
        self.assertEqual(list(client_room.members.values_list("pk", flat=True)), [self.admin.pk])

    def test_a_sales_persons_private_letters_go_with_them_and_never_become_the_companys(self):
        mine = InboundMessage.objects.create(channel=Channel.EMAIL, sender_identity="a@x.example", body="private", owner=self.sales)
        MessageAttachment.objects.create(message=mine, file=SimpleUploadedFile("p.pdf", b"data"), original_name="p.pdf", size=4)
        reply = OutboundMessage.objects.create(channel=Channel.EMAIL, body="private reply", owner=self.sales, created_by=self.sales)
        company = InboundMessage.objects.create(channel=Channel.EMAIL, sender_identity="b@x.example", body="company mail")
        self.run_reset()
        self.assertFalse(InboundMessage.objects.filter(pk=mine.pk).exists())
        self.assertFalse(OutboundMessage.objects.filter(pk=reply.pk).exists())
        self.assertFalse(InboundMessage.objects.filter(body="private").exists())
        self.assertTrue(InboundMessage.objects.filter(pk=company.pk, owner__isnull=True).exists())

    def test_a_task_standing_on_a_private_letter_stops_the_whole_thing(self):
        InboundMessage.objects.create(channel=Channel.EMAIL, sender_identity="a@x.example", body="private", owner=self.sales, task=self.task)
        answer = self.run_reset()
        body = _json(answer)
        self.assertEqual((answer.status_code, body["error"], body["message"]), (400, "refused", services.STAFF_RESET_BLOCKED))
        self.assertEqual(User.objects.filter(pk__in=self.staff_ids()).count(), 7)
        self.assertTrue(InboundMessage.objects.filter(body="private", owner=self.sales).exists())

    def test_the_tasks_stay_and_lose_the_people_they_named(self):
        self.run_reset()
        task = Task.objects.get(pk=self.task.pk)
        self.assertEqual((task.translator, task.team_lead, task.created_by), (None, None, None))

    def test_it_is_written_down_and_the_download_too(self):
        self.run_reset()
        self.assertEqual(AuditLog.objects.filter(actor=self.admin, action="staff.reset").count(), 1)
        self.assertEqual(AuditLog.objects.filter(actor=self.admin, action=identity.DATA_EXPORT).count(), 1)

    def test_with_nobody_to_delete_it_says_so_and_deletes_nothing(self):
        User.objects.filter(pk__in=self.staff_ids()).delete()
        answer = self.run_reset()
        self.assertEqual((answer.status_code, answer["X-Eagle-Deleted"]), (200, "0"))
        self.assertEqual(json.loads(answer.content.decode("utf-8")), [])

    def test_the_stored_pictures_of_the_deleted_go_too(self):
        folder = tempfile.TemporaryDirectory()
        self.addCleanup(folder.cleanup)
        with override_settings(
            MEDIA_ROOT=folder.name,
            STORAGES={**settings.STORAGES, "default": {"BACKEND": "dashboard.storages.ProtectedFileSystemStorage"}},
        ):
            avatars.replace(self.tr, jpeg(40, 40))
            self.tr.refresh_from_db()
            storage, name = self.tr.avatar.storage, self.tr.avatar.name
            self.assertTrue(storage.exists(name))
            with self.captureOnCommitCallbacks(execute=True):
                self.assertEqual(self.run_reset().status_code, 200)
            self.assertFalse(storage.exists(name))
