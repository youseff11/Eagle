"""A team leader makes a task himself (11/10/2026), with the files from his own machine.

The owner's rules: the task is the leader's from the first moment (accepted, ready to hand out), no operation is on it, and the
admin is who takes it over after the review and delivers. The client is a code to the leader, as everywhere. The files are the
task's: listed with the client's files, put in the translator's chat when the job is handed over, and opened only by whoever
may open the task.
"""

import tempfile

from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import Client as DjangoClient
from django.test import override_settings
from django.urls import reverse

from . import files, services, taskstart, wordcount
from .models import (
    AssignmentStatus, AuditLog, ChatAttachment, Notification, Role, Task, TaskStatus, TaskUpload, User,
)
from .tests_api_v1 import CLIENT_NAME, IDENTITY_MARKERS, _json, _Site

LOCAL = {"default": {"BACKEND": "dashboard.storages.ProtectedFileSystemStorage"}}


class _Lead(_Site):
    def setUp(self):
        super().setUp()
        from django.conf import settings

        media = tempfile.TemporaryDirectory()
        self.addCleanup(media.cleanup)
        override = override_settings(MEDIA_ROOT=media.name, STORAGES={**dict(settings.STORAGES), **LOCAL})
        override.enable()
        self.addCleanup(override.disable)
        self.lead2 = User.objects.create_user("person_leader_two", password="pw", role=Role.TEAM_LEAD)
        self.tr2 = User.objects.create_user("person_translator_two", password="pw", role=Role.TRANSLATOR, team_lead=self.lead2)

    def browser(self, who):
        browser = DjangoClient()
        if who is not None:
            browser.force_login(who)
        return browser

    def fields(self, **over):
        values = {
            "client": str(self.client_obj.pk), "title": "Contract", "description": "Two pages",
            "source_lang": "en", "target_lang": "ar", "priority": "normal", "deadline_days": "2",
        }
        values.update(over)
        return values

    def upload(self, name="contract.txt", body=b"one two three four"):
        return SimpleUploadedFile(name, body, content_type="text/plain")

    def make(self, who=None, files_=None, **over):
        payload = self.fields(**over)
        payload["files"] = files_ if files_ is not None else [self.upload()]
        return self.browser(who or self.lead).post(reverse("dashboard:v1_lead_task_create"), payload)

    def made(self, **kw):
        answer = self.make(**kw)
        self.assertEqual(answer.status_code, 200, answer.content)
        return Task.objects.get(code=_json(answer)["code"])


class LeadFormTests(_Lead):
    def test_the_form_answers_the_leader_with_codes_and_nothing_to_start_from(self):
        answer = self.browser(self.lead).get(reverse("dashboard:v1_task_start"), {"message": "1", "from": self.task.code})
        self.assertEqual(answer.status_code, 200)
        body = _json(answer)
        self.assertTrue(body["lead"])
        # What the address named is not read: no client message, no task to repeat.
        self.assertEqual((body["messages"], body["picked"], body["from_task"]), ([], [], None))
        self.assertEqual([c["label"] for c in body["clients"]], [self.client_obj.code])
        text = answer.content.decode("utf-8")
        for marker in IDENTITY_MARKERS:
            self.assertNotIn(marker, text)

    def test_the_operation_still_gets_its_own_form(self):
        body = _json(self.browser(self.ops).get(reverse("dashboard:v1_task_start")))
        self.assertFalse(body["lead"])

    def test_the_translator_is_refused_the_form(self):
        self.assertEqual(self.browser(self.tr).get(reverse("dashboard:v1_task_start")).status_code, 403)


class LeadCreateTests(_Lead):
    def test_the_task_is_his_accepted_and_the_admin_answers_for_it(self):
        before = Notification.objects.filter(user=self.admin).count()
        task = self.made()
        self.assertEqual(task.status, TaskStatus.LEAD_ACCEPTED)
        self.assertEqual((task.team_lead, task.opened_by_lead, task.created_by), (self.lead, self.lead, self.admin))
        self.assertIsNotNone(task.lead_accepted_at)
        self.assertEqual((task.source_lang, task.target_lang), ("EN", "AR"))
        self.assertIsNotNone(task.deadline)
        (mine,) = task.assignments.all()
        self.assertEqual((mine.assignee, mine.target_role, mine.status), (self.lead, Role.TEAM_LEAD, AssignmentStatus.ACCEPTED))
        self.assertEqual(Notification.objects.filter(user=self.admin).count(), before + 1)
        self.assertTrue(AuditLog.objects.filter(action="task.lead_create", target=task.code).exists())
        # The operation is not on it: nobody of the operation is told.
        self.assertFalse(Notification.objects.filter(user=self.ops, task=task).exists())

    def test_the_files_are_the_tasks_source(self):
        task = self.made(files_=[self.upload("a.txt"), self.upload("b.txt")])
        self.assertEqual(TaskUpload.objects.filter(task=task).count(), 2)
        self.assertEqual(sorted(a.original_name for a in services.task_source_files(task)), ["a.txt", "b.txt"])
        self.assertEqual(len(wordcount.source_attachments(task)), 2)

    def test_a_file_named_after_the_client_is_shown_by_the_code(self):
        task = self.made(files_=[self.upload(f"{CLIENT_NAME} contract.txt")])
        (row,) = task.lead_files.all()
        self.assertNotIn("ACME", row.original_name)
        self.assertIn(self.client_obj.code, row.original_name)
        self.assertEqual(row.raw_name, f"{CLIENT_NAME} contract.txt")
        self.assertNotIn("ACME", files.download_name(self.lead, row.file.name, ("task_upload", row)))
        self.assertIn("ACME", files.download_name(self.admin, row.file.name, ("task_upload", row)))

    def test_no_file_is_refused_and_nothing_is_made(self):
        count = Task.objects.count()
        answer = self.make(files_=[])
        self.assertEqual((answer.status_code, _json(answer)["error"]), (400, "no_files"))
        self.assertEqual(Task.objects.count(), count)

    def test_the_form_rules_are_the_operations(self):
        count = Task.objects.count()
        answer = self.make(target_lang="")
        self.assertEqual(answer.status_code, 400)
        self.assertIn("target_lang", _json(answer)["fields"])
        self.assertEqual(Task.objects.count(), count)

    def test_only_a_team_leader(self):
        for who in (self.ops, self.admin, self.tr, self.hr, self.sales):
            answer = self.make(who=who)
            self.assertEqual(answer.status_code, 403, who.username)
        self.assertEqual(self.browser(None).post(reverse("dashboard:v1_lead_task_create"), self.fields()).status_code, 401)
        self.assertFalse(Task.objects.filter(opened_by_lead__isnull=False).exists())

    def test_no_admin_is_refused(self):
        User.objects.filter(role=Role.ADMIN).update(is_active=False)
        answer = self.make()
        self.assertEqual((answer.status_code, _json(answer)["error"]), (409, "no_admin"))


class LeadFilesTests(_Lead):
    def test_the_files_reach_the_translator_it_is_handed_to_and_nobody_else(self):
        task = self.made()
        (row,) = task.lead_files.all()
        name = row.file.name
        self.assertFalse(files.may_open(self.tr, name)[0])
        services.assign_to_translator(task, self.tr, self.lead)
        # Offered and not answered yet: the preview is what the offer is for.
        self.assertTrue(files.may_open(self.tr, name)[0])
        room = services.pair_room(self.lead, self.tr)
        self.assertEqual(ChatAttachment.objects.filter(message__room=room, file=name).count(), 1)
        # Sharing again posts nothing new.
        services.share_source_files(task, room=room)
        self.assertEqual(ChatAttachment.objects.filter(message__room=room, file=name).count(), 1)
        for who in (self.lead, self.admin, self.ops):
            self.assertTrue(files.may_open(who, name)[0], who.username)
        for who in (self.lead2, self.tr2, self.hr, self.sales):
            self.assertFalse(files.may_open(who, name)[0], who.username)

    def test_the_reviewed_files_go_to_the_admin(self):
        task = self.made()
        offer = services.assign_to_translator(task, self.tr, self.lead)
        services.accept_assignment(offer, self.tr)
        task.refresh_from_db()
        message, error = services.upload_translation(task, self.tr, [self.upload("done.txt")])
        self.assertEqual(error, "")
        shared = services.share_reviewed_files(task, self.lead)
        self.assertIsNotNone(shared)
        self.assertEqual(set(shared.room.members.values_list("pk", flat=True)), {self.lead.pk, self.admin.pk})

    def test_the_leader_adds_a_forgotten_file_and_the_translator_gets_it(self):
        task = self.made()
        offer = services.assign_to_translator(task, self.tr, self.lead)
        services.accept_assignment(offer, self.tr)
        url = reverse("dashboard:v1_task_lead_files", args=[task.code])
        answer = self.browser(self.lead).post(url, {"files": [self.upload("late.txt")]})
        self.assertEqual(answer.status_code, 200, answer.content)
        late = task.lead_files.get(original_name="late.txt")
        room = services.pair_room(self.lead, self.tr)
        self.assertTrue(ChatAttachment.objects.filter(message__room=room, file=late.file.name).exists())

    def test_adding_files_is_his_alone_and_only_on_a_task_he_made(self):
        task = self.made()
        url = reverse("dashboard:v1_task_lead_files", args=[task.code])
        # Another leader may not open the task at all: a 404, as for any task that is not theirs.
        self.assertEqual(self.browser(self.lead2).post(url, {"files": [self.upload()]}).status_code, 404)
        self.assertEqual(self.browser(self.ops).post(url, {"files": [self.upload()]}).status_code, 403)
        self.assertEqual(self.browser(self.tr).post(url, {"files": [self.upload()]}).status_code, 403)
        # The operation's task the leader leads is not his to add files to.
        other = reverse("dashboard:v1_task_lead_files", args=[self.task.code])
        answer = self.browser(self.lead).post(other, {"files": [self.upload()]})
        self.assertEqual((answer.status_code, _json(answer)["error"]), (403, "forbidden"))
        # Nor once the translation is in.
        Task.objects.filter(pk=task.pk).update(status=TaskStatus.UNDER_REVIEW)
        self.assertEqual(self.browser(self.lead).post(url, {"files": [self.upload()]}).status_code, 403)
        self.assertEqual(task.lead_files.count(), 1)

    def test_the_task_page_says_who_made_it_and_who_may_add(self):
        task = self.made()
        url = reverse("dashboard:v1_task", args=[task.code])
        mine = _json(self.browser(self.lead).get(url))["task"]
        self.assertTrue(mine["opened_by_lead"])
        self.assertTrue(mine["can_add_files"])
        self.assertEqual(len(mine["files"]["original"]), 1)
        ops = _json(self.browser(self.ops).get(url))["task"]
        self.assertFalse(ops["can_add_files"])
        self.assertFalse(_json(self.browser(self.lead).get(reverse("dashboard:v1_task", args=[self.task.code])))["task"]["opened_by_lead"])

    def test_a_new_request_on_a_leaders_task_does_not_take_his_files_as_a_clients(self):
        task = self.made()
        start = taskstart.resolve(self.ops, from_code=task.code)
        self.assertEqual(start.picked, [])
