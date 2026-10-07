"""The team leader sends the operation the file he corrected, not the translator's old one (07/10/2026).

The leader takes the translator's file, fixes it and wants it to be what goes on: to the operation at the review, and ticked for the
client. Before, only the translator's own file was ever the task's file, so what the operation received was the version the leader
had just corrected. What these tests hold: his upload is what the review sends (the translator's file when he uploaded none), it
counts only if it came after the translator's last hand-in, one noticed late goes to the operation at once and says it replaces the
first, only the task's own leader and the admin may, and the delivery picks it by default.
"""

from unittest import mock

from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import Client as DjangoClient
from django.test import TestCase
from django.urls import reverse

from . import api_ops, services
from .models import AuditLog, ChatAttachment, Client, Role, TaskStatus, User
from .tests import hand_in_translation


def _file(name="fixed.docx", content=b"fixed", kind="application/octet-stream"):
    return SimpleUploadedFile(name, content, content_type=kind)


class ReviewedUploadTests(TestCase):
    def setUp(self):
        make = lambda name, role, **kw: User.objects.create_user(name, password="x", role=role, **kw)
        self.ops = make("ops_ru", Role.OPERATION)
        self.lead = make("lead_ru", Role.TEAM_LEAD)
        self.other_lead = make("lead_ru_two", Role.TEAM_LEAD)
        self.admin = make("admin_ru", Role.ADMIN)
        self.tr = make("tr_ru", Role.TRANSLATOR, team_lead=self.lead)
        self.acme = Client.objects.create(name="ACME", phone="+201000000081")
        self.task = services.create_task(client=self.acme, title="Contract", created_by=self.ops)
        first = services.assign_to_lead(self.task, self.lead, self.ops)
        services.accept_assignment(first, self.lead)
        second = services.assign_to_translator(self.task, self.tr, self.lead)
        services.accept_assignment(second, self.tr)
        hand_in_translation(self.task, self.tr)
        self.task.refresh_from_db()
        self.room = services.staff_room(self.lead, self.ops)

    def sent_to_operation(self):
        """The names of the files in the leader's chat with the operation, in order, one list per message."""
        return [
            [a.original_name for a in m.attachments.all()]
            for m in self.room.messages.filter(is_system=False).order_by("id") if m.attachments.exists()
        ]

    # -- what is sent -------------------------------------------------------------------------------
    def test_the_leaders_file_is_what_the_review_sends_and_not_the_translators(self):
        message, error = services.upload_reviewed(self.task, self.lead, [_file("fixed.docx")])
        self.assertEqual(error, "")
        self.assertEqual(message.sender_id, self.lead.pk)
        self.assertEqual(message.task_id, self.task.pk)
        services.mark_reviewed(self.task, self.lead)
        self.assertEqual(self.sent_to_operation(), [["fixed.docx"]])

    def test_with_no_file_of_his_own_the_translators_goes_as_it_always_did(self):
        services.mark_reviewed(self.task, self.lead)
        self.assertEqual(self.sent_to_operation(), [["translated.txt"]])

    def test_several_files_all_go_and_the_translators_stays_behind(self):
        services.upload_reviewed(self.task, self.lead, [_file("a.docx"), _file("b.docx")])
        services.mark_reviewed(self.task, self.lead)
        self.assertEqual(self.sent_to_operation(), [["a.docx", "b.docx"]])

    def test_a_file_of_his_from_before_the_translators_last_hand_in_is_not_the_final_one(self):
        services.upload_reviewed(self.task, self.lead, [_file("old-fix.docx")])
        services.send_back_for_revision(self.task, self.lead, "again")
        self.task.refresh_from_db()
        services.upload_translation(self.task, self.tr, [_file("v2.txt", b"v2", "text/plain")])
        services.mark_translated(self.task, self.tr)
        self.task.refresh_from_db()
        self.assertEqual([a.original_name for a in services.final_files(self.task)], ["v2.txt"])
        services.mark_reviewed(self.task, self.lead)
        self.assertEqual(self.sent_to_operation(), [["v2.txt"]])

    def test_a_voice_note_of_the_leaders_is_talk_and_never_the_final_file(self):
        voice = SimpleUploadedFile("note.ogg", b"ogg", content_type="audio/ogg")
        services.upload_reviewed(self.task, self.lead, [voice])
        self.assertEqual(services.reviewed_files(self.task), [])
        self.assertEqual([a.original_name for a in services.final_files(self.task)], ["translated.txt"])

    def test_a_file_the_leader_merely_sent_in_chat_is_never_the_final_one_even_when_it_carries_the_task(self):
        from .models import ChatMessage

        room = services.pair_room(self.lead, self.tr)
        message = ChatMessage.objects.create(room=room, sender=self.lead, task=self.task, body="notes for you")
        ChatAttachment.objects.create(message=message, file="chat/notes.pdf", original_name="notes.pdf", size=3)
        self.assertEqual(services.reviewed_files(self.task), [])
        self.assertEqual([a.original_name for a in services.final_files(self.task)], ["translated.txt"])
        services.mark_reviewed(self.task, self.lead)
        self.assertEqual(self.sent_to_operation(), [["translated.txt"]])

    def test_what_the_translator_or_the_operation_wrote_is_never_the_leaders_file(self):
        from .models import ChatMessage

        room = services.pair_room(self.lead, self.tr)
        for person in (self.tr, self.ops):
            message = ChatMessage.objects.create(room=room, sender=person, task=self.task, body="x")
            ChatAttachment.objects.create(message=message, file=f"chat/{person.username}.docx", original_name=f"{person.username}.docx", size=1)
        self.assertEqual(services.reviewed_files(self.task), [])

    def test_what_goes_on_is_the_same_stored_file_and_belongs_to_the_client(self):
        services.upload_reviewed(self.task, self.lead, [_file("fixed.docx")])
        stored = services.reviewed_files(self.task)[0]
        services.mark_reviewed(self.task, self.lead)
        copy = [m for m in self.room.messages.filter(is_system=False) if m.attachments.exists()][0].attachments.get()
        self.assertEqual(copy.file.name, stored.file.name)
        self.assertEqual(copy.origin_client_id, self.acme.pk)

    # -- noticed after the review ---------------------------------------------------------------------
    def test_one_noticed_after_the_review_goes_to_the_operation_at_once_and_says_it_replaces_the_first(self):
        services.mark_reviewed(self.task, self.lead)
        self.assertEqual(self.sent_to_operation(), [["translated.txt"]])
        message, error = services.upload_reviewed(self.task, self.lead, [_file("fixed.docx")])
        self.assertEqual(error, "")
        self.assertEqual(self.sent_to_operation(), [["translated.txt"], ["fixed.docx"]])
        cards = list(self.room.messages.filter(system_key="reviewed_files").order_by("id"))
        self.assertEqual(len(cards), 2)
        self.assertIn("تحديث", cards[1].body)
        self.assertIn("replaces", cards[1].body)
        self.assertNotIn("تحديث", cards[0].body)

    def test_a_task_that_reached_the_client_takes_no_more(self):
        services.mark_reviewed(self.task, self.lead)
        self.task.refresh_from_db()
        self.task.status = TaskStatus.DELIVERED
        self.task.save(update_fields=["status"])
        self.assertEqual(services.upload_reviewed(self.task, self.lead, [_file()]), (None, "bad_status"))

    def test_a_task_the_leader_does_not_have_is_not_his_to_upload_to(self):
        task = services.create_task(client=self.acme, title="Fresh", created_by=self.ops)
        self.assertEqual(services.upload_reviewed(task, self.lead, [_file()]), (None, "forbidden"))
        self.assertEqual(services.reviewed_files(task), [])

    def test_a_task_still_being_translated_takes_none_from_the_leader(self):
        services.send_back_for_revision(self.task, self.lead, "again")
        self.task.refresh_from_db()
        self.assertEqual(self.task.status, TaskStatus.IN_PROGRESS)
        self.assertEqual(services.upload_reviewed(self.task, self.lead, [_file()]), (None, "bad_status"))

    # -- who ----------------------------------------------------------------------------------------
    def test_only_the_tasks_own_leader_and_the_admin_may(self):
        for person in (self.tr, self.ops, self.other_lead):
            self.assertEqual(services.upload_reviewed(self.task, person, [_file()]), (None, "forbidden"), person.username)
            self.assertFalse(services.can_upload_reviewed(self.task, person), person.username)
        self.assertTrue(services.can_upload_reviewed(self.task, self.lead))
        self.assertTrue(services.can_upload_reviewed(self.task, self.admin))
        message, error = services.upload_reviewed(self.task, self.admin, [_file("by-admin.docx")])
        self.assertEqual(error, "")
        self.assertEqual([a.original_name for a in services.final_files(self.task)], ["by-admin.docx"])

    def test_nothing_uploaded_is_nothing(self):
        self.assertEqual(services.upload_reviewed(self.task, self.lead, []), (None, "empty"))
        self.assertEqual(services.upload_reviewed(self.task, self.lead, [None]), (None, "empty"))

    def test_it_is_in_the_audit_log(self):
        services.upload_reviewed(self.task, self.lead, [_file()])
        self.assertTrue(AuditLog.objects.filter(action="task.reviewed_uploaded", actor=self.lead).exists())

    # -- the door ----------------------------------------------------------------------------------
    def post(self, user, files, code=None):
        browser = DjangoClient()
        if user is not None:
            browser.force_login(user)
        return browser.post(reverse("dashboard:api_task_reviewed", args=[code or self.task.code]), {"files": files})

    def test_the_door_is_not_the_one_that_finishes_the_review(self):
        # `.../reviewed/` is the review's own action (`api.task_action`); the files have a door of their own that must not shadow it.
        self.assertEqual(reverse("dashboard:api_task_reviewed", args=["TSK-1"]), "/api/tasks/TSK-1/reviewed-files/")
        browser = DjangoClient()
        browser.force_login(self.lead)
        answer = browser.post("/api/tasks/%s/reviewed/" % self.task.code)
        self.assertEqual(answer.status_code, 200, answer.content)
        self.task.refresh_from_db()
        self.assertEqual(self.task.status, TaskStatus.REVIEWED)

    def test_the_door_takes_the_leaders_files(self):
        answer = self.post(self.lead, [_file("a.docx"), _file("b.docx")])
        self.assertEqual(answer.status_code, 200)
        self.assertEqual(answer.json()["files"], 2)
        self.assertEqual([a.original_name for a in services.final_files(self.task)], ["a.docx", "b.docx"])

    def test_the_door_refuses_who_may_not_and_a_task_that_is_not_theirs_is_not_there(self):
        self.assertEqual(self.post(self.tr, [_file()]).status_code, 403)
        self.assertEqual(self.post(self.ops, [_file()]).status_code, 403)
        self.assertEqual(self.post(self.other_lead, [_file()]).status_code, 404)
        self.assertEqual(self.post(None, [_file()]).status_code, 302)
        self.assertEqual(services.reviewed_files(self.task), [])

    def test_the_door_says_why_when_it_refuses_a_task_in_the_wrong_state(self):
        services.send_back_for_revision(self.task, self.lead, "again")
        answer = self.post(self.lead, [_file()])
        self.assertEqual((answer.status_code, answer.json()["error"]), (400, "bad_status"))

    # -- the task page and the delivery -----------------------------------------------------------------
    def test_the_delivery_ticks_the_leaders_file_and_not_the_translators(self):
        services.upload_reviewed(self.task, self.lead, [_file("fixed.docx")])
        rows = {row["name"]: row["final"] for row in api_ops._deliverables_json(self.task)}
        self.assertEqual(rows, {"fixed.docx": True, "translated.txt": False})

    def test_with_none_of_his_the_delivery_ticks_the_translators_as_before(self):
        rows = {row["name"]: row["final"] for row in api_ops._deliverables_json(self.task)}
        self.assertEqual(rows, {"translated.txt": True})

    def test_the_client_is_sent_the_leaders_file_when_it_is_picked(self):
        services.upload_reviewed(self.task, self.lead, [_file("fixed.docx")])
        services.mark_reviewed(self.task, self.lead)
        self.task.refresh_from_db()
        services.acknowledge_handover(self.task, self.ops)
        self.task.refresh_from_db()
        wanted = [a.pk for a in services.final_files(self.task)]
        with mock.patch("dashboard.whatsapp.send_file", return_value="wamid.1") as send, mock.patch("dashboard.whatsapp.send_text", return_value="wamid.0"):
            ok, delivery, error = services.deliver_to_client(self.task, self.ops, attachment_ids=wanted)
        self.assertTrue(ok, error)
        self.assertEqual([call.args[2] for call in send.call_args_list], ["fixed.docx"])

    def test_the_task_page_says_who_may_upload_and_lists_what_the_leader_put(self):
        def page(user):
            browser = DjangoClient()
            browser.force_login(user)
            return browser.get(reverse("dashboard:v1_task", args=[self.task.code])).json()["task"]

        before = page(self.lead)
        self.assertTrue(before["lead"]["can_upload_reviewed"])
        self.assertEqual(before["files"]["reviewed"], [])
        services.upload_reviewed(self.task, self.lead, [_file("fixed.docx")])
        after = page(self.lead)
        self.assertEqual([f["name"] for f in after["files"]["reviewed"]], ["fixed.docx"])
        # The operation is told what the leader put, and has no way to put anything.
        as_ops = page(self.ops)
        self.assertEqual([f["name"] for f in as_ops["files"]["reviewed"]], ["fixed.docx"])
        self.assertIsNone(as_ops["lead"])
        services.send_back_for_revision(self.task, self.lead, "again")
        self.assertFalse(page(self.lead)["lead"]["can_upload_reviewed"])
