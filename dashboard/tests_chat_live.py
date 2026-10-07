"""What a person sees while a message with files is still being sent, and who has seen it once it is there.

Two things, one cause each:

* a message is shown whole or not at all. A reply to a client is written in two steps (the row, then its files),
  and a message in a room too; a page that asked in between drew the names of the files as plain words and then
  turned them into the photo or the player a moment later;
* in a group the sender sees under a message which of the others have read it, and is rung when one more has -
  and only the sender: the line is theirs alone.
"""

from datetime import timedelta
from unittest import mock

from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import Client as DjangoClient
from django.test import TestCase, TransactionTestCase
from django.urls import reverse
from django.utils import timezone

from . import realtime, services
from .models import (
    ChatAttachment, ChatMessage, ChatRoom, Client, OutboundAttachment, OutboundMessage, Role, RoomKind, User,
)


def _people():
    make = lambda name, role: User.objects.create_user(name, password="pw", role=role)
    return make("live_ops", Role.OPERATION), make("live_lead", Role.TEAM_LEAD), make("live_tr", Role.TRANSLATOR)


class ReplyBeingWrittenTests(TestCase):
    """A reply to a client whose files are not stored yet is not in the thread; one that has them is, whole."""

    def setUp(self):
        self.ops, _lead, _tr = _people()
        self.client_obj = Client.objects.create(name="ACME", phone="+201000000091")

    def reply(self, files, status=OutboundMessage.Status.SENT, kind=OutboundMessage.Kind.CHAT):
        return OutboundMessage.objects.create(
            client=self.client_obj, kind=kind, created_by=self.ops, channel="whatsapp", body="",
            status=status, files=[{"name": name, "status": "pending"} for name in files],
        )

    def thread(self):
        return [entry for entry in services.client_thread(self.client_obj, self.ops) if entry["kind"] == "out"]

    def test_a_reply_whose_files_are_not_stored_yet_is_not_drawn_as_their_names(self):
        self.reply(["photo.jpg", "voice.ogg"])
        self.assertEqual(self.thread(), [])

    def test_it_is_there_with_its_files_the_moment_they_are_stored(self):
        row = self.reply(["photo.jpg"])
        OutboundAttachment.objects.create(
            message=row, file=SimpleUploadedFile("photo.jpg", b"x", "image/jpeg"), original_name="photo.jpg", size=1,
            mime="image/jpeg",
        )
        entry = self.thread()[0]
        self.assertEqual([f["name"] for f in entry["files"]], ["photo.jpg"])
        self.assertNotEqual(entry["files"][0]["url"], "")
        self.assertTrue(entry["files"][0]["image"])

    def test_words_alone_are_there_at_once(self):
        OutboundMessage.objects.create(
            client=self.client_obj, kind=OutboundMessage.Kind.CHAT, created_by=self.ops, channel="whatsapp", body="hello",
        )
        self.assertEqual([entry["body"] for entry in self.thread()], ["hello"])

    def test_a_reply_that_failed_before_its_files_were_stored_is_still_shown_with_its_names(self):
        self.reply(["photo.jpg"], status=OutboundMessage.Status.FAILED)
        entry = self.thread()[0]
        self.assertEqual([f["name"] for f in entry["files"]], ["photo.jpg"])

    def test_a_reply_with_words_and_files_not_stored_yet_waits_whole(self):
        row = self.reply(["photo.jpg"])
        OutboundMessage.objects.filter(pk=row.pk).update(body="look at this")
        self.assertEqual(self.thread(), [])

    def old(self, files, **fields):
        row = self.reply(files, **fields)
        OutboundMessage.objects.filter(pk=row.pk).update(
            created_at=timezone.now() - timedelta(minutes=services.WRITING_MINUTES + 1)
        )
        return row

    def test_a_reply_that_nothing_ever_finished_is_shown_as_a_send_that_broke(self):
        self.old(["photo.jpg"])
        (entry,) = self.thread()
        self.assertEqual(entry["status"], OutboundMessage.Status.FAILED)
        self.assertEqual(entry["error"], services.SEND_UNSURE_AR)
        self.assertEqual(entry["receipt"], "")
        self.assertEqual([f["name"] for f in entry["files"]], ["photo.jpg"])

    def test_the_list_row_does_not_say_sent_for_what_the_thread_does_not_show(self):
        self.reply(["photo.jpg"])
        self.assertNotEqual(services.conversation_preview(self.client_obj, self.ops)["text"], "1 ملف")

    def test_the_list_row_says_the_send_broke_for_a_reply_nothing_finished(self):
        self.old(["photo.jpg"])
        preview = services.conversation_preview(self.client_obj, self.ops)
        self.assertEqual(
            (preview["text"], preview["status"], preview["outgoing"]), ("1 ملف", OutboundMessage.Status.FAILED, True)
        )

    def test_a_task_delivery_keeps_showing_its_names_without_a_link(self):
        self.reply(["translated.docx"], kind=OutboundMessage.Kind.DELIVERY)
        entry = self.thread()[0]
        self.assertEqual([(f["name"], f["url"]) for f in entry["files"]], [("translated.docx", "")])


class GroupSendIsOneWriteTests(TransactionTestCase):
    """The message and its files are saved together: nobody is told of a message that has none yet.

    A transaction test, because only a real commit shows when the ring goes out (inside a `TestCase` nothing is ever
    committed, so the order of the two writes could not be told apart).
    """

    def test_every_ring_for_the_room_comes_after_the_files_are_stored(self):
        ops, lead, _tr = _people()
        room = ChatRoom.objects.create(kind=RoomKind.TEAM, title="Work", created_by=lead)
        room.members.add(ops, lead)
        seen = []

        def ring(user_ids, event):
            # The one place everything goes out through: nothing reaches a real channel layer from a test.
            if event.get("t") == realtime.ROOM:
                seen.append(ChatMessage.objects.get(room_id=event["id"]).attachments.count())

        browser = DjangoClient()
        browser.force_login(ops)
        with mock.patch.object(realtime, "_deliver", side_effect=ring):
            answer = browser.post(
                reverse("dashboard:v1_group_send", args=[room.pk]),
                {"body": "", "task": "none", "files": SimpleUploadedFile("photo.jpg", b"x", "image/jpeg")},
            )
        self.assertEqual(answer.status_code, 200)
        self.assertEqual(ChatAttachment.objects.count(), 1)
        self.assertTrue(seen)
        self.assertEqual(set(seen), {1})


class GroupSendFailureTests(TestCase):
    """A file that cannot be stored leaves no message behind: the page says it is not sure, and sends it again whole."""

    def test_a_failed_file_takes_the_message_back_with_it(self):
        ops, lead, _tr = _people()
        room = ChatRoom.objects.create(kind=RoomKind.TEAM, title="Work", created_by=lead)
        room.members.add(ops, lead)
        browser = DjangoClient(raise_request_exception=False)
        browser.force_login(ops)
        with mock.patch.object(ChatAttachment.objects, "create", side_effect=OSError("storage is down")):
            answer = browser.post(
                reverse("dashboard:v1_group_send", args=[room.pk]),
                {"body": "with a file", "task": "none", "files": SimpleUploadedFile("photo.jpg", b"x", "image/jpeg")},
            )
        self.assertEqual(answer.status_code, 500)
        self.assertEqual(ChatMessage.objects.count(), 0)


class SeenByTests(TestCase):
    """Who has read my message, in a group, and the ring that tells me when one more has."""

    def setUp(self):
        self.ops, self.lead, self.tr = _people()
        self.room, _error = services.create_team_group(self.lead, "Team", [self.tr, self.ops])

    def rung(self, reader):
        """The people rung when ``reader`` reads the room now: ``None`` when nothing was rung."""
        with mock.patch.object(realtime, "_deliver") as deliver, self.captureOnCommitCallbacks(execute=True):
            moved = services.mark_room_read(reader, self.room)
        told = set()
        for call in deliver.call_args_list:
            ids, event = call.args
            self.assertEqual(event, {"t": realtime.ROOM, "id": self.room.pk})
            told.update(ids)
        return moved, told

    def test_reading_rings_the_one_who_wrote_and_nobody_else(self):
        ChatMessage.objects.create(room=self.room, sender=self.lead, body="plan")
        moved, told = self.rung(self.tr)
        self.assertTrue(moved)
        self.assertEqual(told, {self.lead.pk})

    def test_each_writer_is_rung_for_what_they_wrote(self):
        ChatMessage.objects.create(room=self.room, sender=self.lead, body="plan")
        ChatMessage.objects.create(room=self.room, sender=self.ops, body="done")
        _moved, told = self.rung(self.tr)
        self.assertEqual(told, {self.lead.pk, self.ops.pk})

    def test_reading_what_you_wrote_yourself_rings_nobody(self):
        ChatMessage.objects.create(room=self.room, sender=self.lead, body="plan")
        moved, told = self.rung(self.lead)
        self.assertTrue(moved)
        self.assertEqual(told, set())

    def test_reading_again_with_nothing_new_rings_nobody(self):
        ChatMessage.objects.create(room=self.room, sender=self.lead, body="plan")
        self.rung(self.tr)
        moved, told = self.rung(self.tr)
        self.assertFalse(moved)
        self.assertEqual(told, set())

    def test_only_what_is_new_to_the_reader_rings_its_writer(self):
        ChatMessage.objects.create(room=self.room, sender=self.lead, body="plan")
        self.rung(self.tr)
        ChatMessage.objects.create(room=self.room, sender=self.ops, body="done")
        _moved, told = self.rung(self.tr)
        self.assertEqual(told, {self.ops.pk})

    def test_someone_who_has_left_the_room_is_not_rung(self):
        ChatMessage.objects.create(room=self.room, sender=self.ops, body="done")
        self.room.members.remove(self.ops)
        _moved, told = self.rung(self.tr)
        self.assertEqual(told, set())

    def test_the_names_are_the_ones_who_have_read_it(self):
        message = ChatMessage.objects.create(room=self.room, sender=self.lead, body="plan")
        services.mark_room_read(self.tr, self.room)
        entry = [e for e in services.group_thread(self.room, self.lead) if e["uid"].endswith(f"-{message.pk}")][0]
        self.assertEqual(entry["seen_by"], [self.tr.short_name])
        # The other two have no names under what the lead wrote: it is the writer's line.
        as_reader = [e for e in services.group_thread(self.room, self.tr) if e["uid"].endswith(f"-{message.pk}")][0]
        self.assertEqual(as_reader["seen_by"], [])

    def test_a_group_that_reaches_a_client_names_its_own_readers_and_keeps_the_phones_ticks(self):
        client = Client.objects.create(name="ACME", phone="+201000000092")
        colleague = User.objects.create_user("live_ops_two", password="pw", role=Role.OPERATION)
        room = ChatRoom.objects.create(kind=RoomKind.CLIENT, client=client, title="With the client", created_by=self.ops)
        room.members.add(self.ops, colleague)
        message = ChatMessage.objects.create(
            room=room, sender=self.ops, body="hello", relay_status="sent", relay_receipt="delivered",
        )
        services.mark_room_read(colleague, room)
        entry = [e for e in services.group_thread(room, self.ops) if e["uid"].endswith(f"-{message.pk}")][0]
        self.assertEqual(entry["receipt"], "delivered")
        self.assertEqual(entry["seen_by"], [colleague.short_name])

    def test_somebody_who_kept_a_seat_in_a_client_room_but_may_not_open_it_is_not_named(self):
        client = Client.objects.create(name="ACME", phone="+201000000093")
        room = ChatRoom.objects.create(kind=RoomKind.CLIENT, client=client, title="With the client", created_by=self.ops)
        # The seat outlived the right: a translator is never let into a room that reaches a client.
        room.members.add(self.ops, self.tr)
        message = ChatMessage.objects.create(room=room, sender=self.ops, body="hello", relay_status="sent")
        services.mark_room_read(self.tr, room)
        entry = [e for e in services.group_thread(room, self.ops) if e["uid"].endswith(f"-{message.pk}")][0]
        self.assertEqual(entry["seen_by"], [])

    def test_the_door_that_says_a_room_was_read_rings_the_one_who_wrote(self):
        ChatMessage.objects.create(room=self.room, sender=self.lead, body="plan")
        browser = DjangoClient()
        browser.force_login(self.tr)
        with mock.patch.object(realtime, "_deliver") as deliver, self.captureOnCommitCallbacks(execute=True):
            answer = browser.post(
                reverse("dashboard:v1_group_read", args=[self.room.pk]), "{}", content_type="application/json"
            )
        self.assertEqual(answer.status_code, 200)
        told = set()
        for call in deliver.call_args_list:
            told.update(call.args[0])
        self.assertEqual(told, {self.lead.pk})

    def test_an_inactive_person_is_not_rung(self):
        ChatMessage.objects.create(room=self.room, sender=self.ops, body="done")
        User.objects.filter(pk=self.ops.pk).update(is_active=False)
        _moved, told = self.rung(self.tr)
        self.assertEqual(told, set())

    def test_the_ring_never_goes_out_to_nobody(self):
        ChatMessage.objects.create(room=self.room, sender=self.ops, body="done")
        self.room.members.remove(self.ops)
        with mock.patch.object(realtime, "_deliver") as deliver, self.captureOnCommitCallbacks(execute=True):
            services.mark_room_read(self.tr, self.room)
        deliver.assert_not_called()
