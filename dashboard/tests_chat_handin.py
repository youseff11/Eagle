"""The chats screen in the new app, step 3e part 2: the translator's "task done" from a work group
(``/api/v1/groups/<id>/handin-tasks/`` and ``/api/v1/tasks/<code>/hand-in/``).

``services.handin_tasks_for`` and ``services.hand_in_from_chat`` decide everything - which tasks, which files,
who - so what is pinned here is the contract around them, and above all that the new door is exactly as strict as
the classic one:

* the list of tasks is the translator's own, from their own work group, and nobody else's;
* the files are theirs, in a work group the task's leader is in, no voice note, none already on another task;
* a refusal is a 4xx and nothing was tagged and the task did not move; the reason is in ``message``;
* nothing goes to a client, and nothing of a client's comes back.
"""

import json
from unittest import mock

from django.core.files.base import ContentFile
from django.test import Client as DjangoClient
from django.test import TestCase
from django.urls import reverse

from . import services
from .models import AuditLog, ChatAttachment, ChatMessage, Client, Role, Task, TaskStatus, User
from .tests_chat_lists import _json

NAME = "Zebulon Quartermaine"
PHONE = "+201234567890"


class _HandIn(TestCase):
    def setUp(self):
        make = lambda name, role, **kw: User.objects.create_user(name, password="pw", role=role, **kw)
        self.admin = make("own_hi", Role.ADMIN)
        self.ops = make("ops_hi", Role.OPERATION)
        self.lead = make("lead_hi", Role.TEAM_LEAD)
        self.tr = make("tr_hi", Role.TRANSLATOR, team_lead=self.lead)
        self.tr2 = make("tr_hi2", Role.TRANSLATOR, team_lead=self.lead)
        self.hr = make("hr_hi", Role.HR)
        self.sales = make("sales_hi", Role.SALES)
        self.everyone = [self.admin, self.ops, self.lead, self.tr, self.tr2, self.hr, self.sales]

        self.client_obj = Client.objects.create(name=NAME, phone=PHONE, email="zeb@example.test")
        self.task = self.make_task("Doc", self.tr)
        self.group = services.find_lead_translator_group(self.lead, self.tr)
        # The owner watching the group.
        self.group.members.add(self.admin)

        self.text = mock.patch("dashboard.whatsapp.send_text", return_value="wamid.x").start()
        self.file = mock.patch("dashboard.whatsapp.send_file", return_value="wamid.y").start()
        self.addCleanup(mock.patch.stopall)

    def make_task(self, title, translator):
        task = services.create_task(client=self.client_obj, title=title, created_by=self.ops)
        first = services.assign_to_lead(task, self.lead, self.ops)
        services.accept_assignment(first, self.lead)
        second = services.assign_to_translator(task, translator, self.lead)
        services.accept_assignment(second, translator)
        task.refresh_from_db()
        return task

    def send(self, name="done.docx", sender=None, room=None):
        message = ChatMessage.objects.create(room=room or self.group, sender=sender or self.tr, body="")
        return ChatAttachment.objects.create(message=message, file=ContentFile(b"t", name=name), original_name=name, size=1)

    def browser(self, user):
        browser = DjangoClient()
        if user is not None:
            browser.force_login(user)
        return browser

    def tasks_for(self, user, room=None):
        return self.browser(user).get(reverse("dashboard:v1_group_handin_tasks", args=[(room or self.group).pk]))

    def hand_in(self, user, files, code=None, raw=None, content_type="application/json"):
        data = raw if raw is not None else json.dumps({"files": [f.pk if hasattr(f, "pk") else f for f in files]})
        return self.browser(user).post(
            reverse("dashboard:v1_task_hand_in", args=[code or self.task.code]), data, content_type=content_type,
        )

    def status(self, task=None):
        task = task or self.task
        task.refresh_from_db()
        return task.status


class TasksTests(_HandIn):
    def test_the_translator_is_offered_their_own_task_from_their_own_group(self):
        body = _json(self.tasks_for(self.tr))
        self.assertEqual(body["tasks"], [{"code": self.task.code, "title": "Doc"}])

    def test_a_second_translator_in_the_same_group_is_not_offered_the_first_ones_task(self):
        # A leader's group may seat several translators: each is offered what is theirs and nothing else.
        self.group.members.add(self.tr2)
        self.assertEqual(_json(self.tasks_for(self.tr2))["tasks"], [])
        mine = self.make_task("Second translator's job", self.tr2)
        self.assertEqual([t["code"] for t in _json(self.tasks_for(self.tr2))["tasks"]], [mine.code])
        self.assertEqual([t["code"] for t in _json(self.tasks_for(self.tr))["tasks"]], [self.task.code])

    def test_nobody_else_is_offered_anything(self):
        for user in (self.lead, self.admin):
            self.assertEqual(_json(self.tasks_for(user))["tasks"], [], user.username)

    def test_somebody_who_is_not_in_the_room_does_not_find_it(self):
        for user in (self.ops, self.hr, self.sales, self.tr2):
            self.assertEqual(self.tasks_for(user).status_code, 404, user.username)

    def test_only_a_task_still_being_worked_is_offered(self):
        self.send()
        self.hand_in(self.tr, [ChatAttachment.objects.get()])
        self.assertEqual(self.status(), TaskStatus.UNDER_REVIEW)
        self.assertEqual(_json(self.tasks_for(self.tr))["tasks"], [])

    def test_several_tasks_are_all_offered_and_only_the_ones_of_a_leader_in_the_room(self):
        second = self.make_task("Second job", self.tr)
        codes = [t["code"] for t in _json(self.tasks_for(self.tr))["tasks"]]
        self.assertEqual(codes, [self.task.code, second.code])
        # A task led by somebody who is not in this group is not offered here.
        other_lead = User.objects.create_user("lead_other", password="pw", role=Role.TEAM_LEAD)
        stray = services.create_task(client=self.client_obj, title="Elsewhere", created_by=self.ops)
        Task.objects.filter(pk=stray.pk).update(translator=self.tr, team_lead=other_lead, status=TaskStatus.IN_PROGRESS)
        self.assertEqual([t["code"] for t in _json(self.tasks_for(self.tr))["tasks"]], codes)

    def test_a_private_line_has_no_tasks_to_hand_in_to(self):
        private = services.staff_room(self.tr, self.lead)
        self.assertEqual(_json(self.tasks_for(self.tr, private))["tasks"], [])

    def test_a_session_and_a_get(self):
        url = reverse("dashboard:v1_group_handin_tasks", args=[self.group.pk])
        self.assertEqual(DjangoClient().get(url).status_code, 401)
        self.assertEqual(self.browser(self.tr).post(url, "{}", content_type="application/json").status_code, 405)

    def test_nothing_about_the_client_comes_back(self):
        answer = self.tasks_for(self.tr)
        for text in (NAME.encode(), PHONE.encode(), b"zeb@example.test"):
            self.assertNotIn(text, answer.content)


class HandInTests(_HandIn):
    def test_the_translator_hands_in_several_files_and_the_task_goes_to_review(self):
        one, two = self.send("a.docx"), self.send("b.docx")
        answer = self.hand_in(self.tr, [one, two])
        body = _json(answer)
        self.assertEqual((answer.status_code, body["ok"], body["code"]), (200, True, self.task.code))
        self.assertEqual(self.status(), TaskStatus.UNDER_REVIEW)
        self.assertEqual(
            sorted(a.original_name for a in services.translator_files(self.task)), ["a.docx", "b.docx"],
        )
        one.message.refresh_from_db()
        self.assertEqual(one.message.task_id, self.task.pk)
        self.assertTrue(AuditLog.objects.filter(action="task.handed_in_from_chat", target=self.task.code).exists())

    def test_it_is_exactly_what_the_classic_door_does_for_every_role(self):
        for user in self.everyone:
            Task.objects.filter(pk=self.task.pk).update(status=TaskStatus.IN_PROGRESS)
            ChatMessage.objects.all().update(task=None)
            file = self.send("same.docx")
            old = self.browser(user).post(reverse("dashboard:api_task_handin", args=[self.task.code]), {"files": [file.pk]})
            old_state = (old.status_code == 200, self.status(), ChatMessage.objects.filter(task=self.task).count())
            Task.objects.filter(pk=self.task.pk).update(status=TaskStatus.IN_PROGRESS)
            ChatMessage.objects.all().update(task=None)
            new = self.hand_in(user, [file])
            new_state = (new.status_code == 200, self.status(), ChatMessage.objects.filter(task=self.task).count())
            self.assertEqual(new_state, old_state, user.username)
            self.assertEqual(new_state[0], user == self.tr, user.username)

    def test_somebody_elses_file_a_voice_note_and_a_file_from_another_room_are_refused_and_nothing_moves(self):
        other, _e = services.create_team_group(self.ops, "Elsewhere", [self.tr])
        for name, file in (
            ("the leader's file", self.send(sender=self.lead)),
            ("a voice note", self.send("note.ogg")),
            ("a room without the leader", self.send(room=other)),
        ):
            answer = self.hand_in(self.tr, [file])
            body = _json(answer)
            self.assertEqual((answer.status_code, body["ok"], body["error"]), (400, False, "refused"), name)
            self.assertTrue(body["message"], name)
            self.assertEqual(self.status(), TaskStatus.IN_PROGRESS, name)
            file.message.refresh_from_db()
            self.assertIsNone(file.message.task_id, name)

    def test_a_file_that_is_already_on_another_task_is_refused(self):
        second = self.make_task("Second job", self.tr)
        file = self.send("one.docx")
        ChatMessage.objects.filter(pk=file.message_id).update(task=second)
        answer = self.hand_in(self.tr, [file])
        self.assertEqual(answer.status_code, 400)
        self.assertEqual(self.status(), TaskStatus.IN_PROGRESS)

    def test_a_task_that_is_not_in_progress_is_refused(self):
        file = self.send()
        Task.objects.filter(pk=self.task.pk).update(status=TaskStatus.UNDER_REVIEW)
        answer = self.hand_in(self.tr, [file])
        self.assertEqual(answer.status_code, 400)
        file.message.refresh_from_db()
        self.assertIsNone(file.message.task_id)

    def test_nothing_ticked_is_nothing_to_hand_in(self):
        answer = self.hand_in(self.tr, [])
        self.assertEqual((answer.status_code, _json(answer)["error"]), (400, "empty"))
        self.assertEqual(self.status(), TaskStatus.IN_PROGRESS)

    def test_ids_that_are_not_files_are_refused_not_ignored(self):
        answer = self.hand_in(self.tr, [999999])
        self.assertEqual((answer.status_code, _json(answer)["error"]), (400, "refused"))
        self.assertEqual(self.status(), TaskStatus.IN_PROGRESS)

    def test_a_task_that_does_not_exist_or_is_not_yours_to_see_is_a_404(self):
        file = self.send()
        self.assertEqual(self.hand_in(self.tr, [file], code="TSK-99999").status_code, 404)
        before = AuditLog.objects.filter(action="security.denied").count()
        self.assertEqual(self.hand_in(self.sales, [file]).status_code, 404)
        self.assertEqual(AuditLog.objects.filter(action="security.denied").count(), before + 1)
        self.assertEqual(self.status(), TaskStatus.IN_PROGRESS)

    def test_the_body_is_a_small_json_object(self):
        file = self.send()
        ok = {"files": [file.pk]}
        cases = {
            "a form": (f"files={file.pk}", "application/x-www-form-urlencoded"),
            "a list": ("[]", "application/json"),
            "garbage": ("{", "application/json"),
            "files not a list": (json.dumps({"files": file.pk}), "application/json"),
            "a file that is text": (json.dumps({"files": ["x"]}), "application/json"),
            "a file that is a float": (json.dumps({"files": [1.5]}), "application/json"),
            "a file that is a bool": (json.dumps({"files": [True]}), "application/json"),
            "a file id too big": (json.dumps({"files": [2 ** 70]}), "application/json"),
            "too many files": (json.dumps({"files": list(range(1, 102))}), "application/json"),
        }
        for name, (data, content_type) in cases.items():
            answer = self.hand_in(self.tr, [], raw=data, content_type=content_type)
            self.assertEqual((answer.status_code, _json(answer)["error"]), (400, "bad_request"), name)
        self.assertEqual(self.status(), TaskStatus.IN_PROGRESS)
        self.assertEqual(self.hand_in(self.tr, [], raw=json.dumps(ok)).status_code, 200)

    def test_a_session_a_post_and_the_csrf_token(self):
        file = self.send()
        url = reverse("dashboard:v1_task_hand_in", args=[self.task.code])
        self.assertEqual(DjangoClient().post(url, "{}", content_type="application/json").status_code, 401)
        self.assertEqual(self.browser(self.tr).get(url).status_code, 405)
        strict = DjangoClient(enforce_csrf_checks=True)
        strict.force_login(self.tr)
        answer = strict.post(url, json.dumps({"files": [file.pk]}), content_type="application/json")
        self.assertEqual(answer.status_code, 403)
        self.assertEqual(self.status(), TaskStatus.IN_PROGRESS)

    def test_nothing_goes_to_the_client_and_nothing_of_the_clients_comes_back(self):
        file = self.send()
        answer = self.hand_in(self.tr, [file])
        self.text.assert_not_called()
        self.file.assert_not_called()
        for text in (NAME.encode(), PHONE.encode(), b"zeb@example.test"):
            self.assertNotIn(text, answer.content)
