"""What a client reads under a file that is forwarded to them: the caption the sender chose.

Forwarding to a client's own conversation used to send a file that came without words under its stored name
(``TSK-00042 - Ahmed.docx``: a task code, maybe a translator's name). Now the note typed in the forward dialog is the
caption of the first file that has none of its own, a file with nothing said about it goes with a neutral line, and
no stored name is ever used as the words under a file. A note that has no file to ride on goes ahead of the messages,
as it always did.
"""

import json
from unittest import mock

from django.core.files.base import ContentFile
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import Client as DjangoClient, TestCase
from django.urls import reverse

from . import services, whatsapp
from .models import Channel, ChatAttachment, ChatMessage, Client, OutboundMessage, Role, User

PHONE = "+201000000091"
STORED = "TSK-00042 - Ahmed Translator.docx"
NEUTRAL = services.FORWARD_FILE_CAPTION_AR


class _Forward(TestCase):
    def setUp(self):
        self.ops = User.objects.create_user("ops_cap", password="x", role=Role.OPERATION)
        self.tr = User.objects.create_user("tr_cap", password="x", role=Role.TRANSLATOR)
        self.acme = Client.objects.create(name="ACME", phone=PHONE)
        self.room = services.staff_room(self.ops, self.tr)
        self.text = mock.patch("dashboard.whatsapp.send_text", return_value="wamid.text").start()
        self.file = mock.patch("dashboard.whatsapp.send_file", return_value="wamid.file").start()
        self.addCleanup(mock.patch.stopall)

    def message(self, name=STORED, body="", content=b"x"):
        """A colleague's message with one file, as a uid the forward can name."""
        row = ChatMessage.objects.create(room=self.room, sender=self.tr, body=body)
        ChatAttachment.objects.create(
            message=row, file=ContentFile(content, name=name), original_name=name, size=len(content),
        )
        return f"g{self.room.pk}-{row.pk}"

    def forward(self, uids, note=""):
        return services.forward_messages(self.ops, f"u{self.tr.pk}", self.acme.code, uids=uids, note=note)

    def captions(self):
        """The caption each file went out with, in order."""
        return [call.kwargs["caption"] for call in self.file.call_args_list]


class CaptionTests(_Forward):
    def test_the_note_is_the_caption_of_the_file_and_not_a_message_of_its_own(self):
        ok, error, _url, written = self.forward([self.message()], note="Here is the translation")
        self.assertTrue(ok, error)
        self.assertTrue(written)
        self.text.assert_not_called()
        self.assertEqual(self.captions(), ["Here is the translation"])
        sent = OutboundMessage.objects.get(client=self.acme)
        # The thread shows what the client reads, and the ticks follow the message that holds the words.
        self.assertEqual(sent.body, "Here is the translation")
        self.assertEqual(sent.provider_id, "wamid.file")

    def test_a_file_with_no_caption_typed_goes_with_a_neutral_line_never_with_its_stored_name(self):
        ok, error, _url, _written = self.forward([self.message()])
        self.assertTrue(ok, error)
        self.text.assert_not_called()
        self.assertEqual(self.captions(), [NEUTRAL])
        self.assertEqual(OutboundMessage.objects.get(client=self.acme).body, NEUTRAL)
        for call in self.file.call_args_list:
            self.assertNotIn("TSK-", call.kwargs["caption"])

    def test_the_note_rides_on_the_first_file_and_the_others_go_with_the_neutral_line(self):
        uids = [self.message("a.pdf"), self.message("b.pdf"), self.message("c.pdf")]
        ok, error, _url, _written = self.forward(uids, note="All three")
        self.assertTrue(ok, error)
        self.text.assert_not_called()
        self.assertEqual(self.captions(), ["All three", NEUTRAL, NEUTRAL])
        self.assertEqual([c.args[2] for c in self.file.call_args_list], ["a.pdf", "b.pdf", "c.pdf"])

    def test_one_message_with_two_files_puts_the_caption_on_the_first_only(self):
        row = ChatMessage.objects.create(room=self.room, sender=self.tr, body="")
        for name in ("one.pdf", "two.pdf"):
            ChatAttachment.objects.create(message=row, file=ContentFile(b"x", name=name), original_name=name, size=1)
        ok, error, _url, _written = self.forward([f"g{self.room.pk}-{row.pk}"], note="Both")
        self.assertTrue(ok, error)
        self.assertEqual(self.captions(), ["Both", ""])

    def test_a_note_with_no_file_to_ride_on_goes_ahead_of_the_words_as_a_text(self):
        words = ChatMessage.objects.create(room=self.room, sender=self.tr, body="team talk")
        ok, error, _url, _written = self.forward([f"g{self.room.pk}-{words.pk}"], note="Here it is")
        self.assertTrue(ok, error)
        self.assertEqual([c.args[1] for c in self.text.call_args_list], ["Here it is", "team talk"])
        self.file.assert_not_called()

    def test_words_that_come_with_their_file_stay_the_words_and_the_note_goes_ahead(self):
        uid = self.message("report.pdf", body="the report")
        ok, error, _url, _written = self.forward([uid], note="Please read")
        self.assertTrue(ok, error)
        self.assertEqual([c.args[1] for c in self.text.call_args_list], ["Please read", "the report"])
        # The file after its words carries no caption of its own, as before.
        self.assertEqual(self.captions(), [""])

    def test_a_note_and_a_mix_of_words_and_a_bare_file_puts_the_note_on_the_file(self):
        words = ChatMessage.objects.create(room=self.room, sender=self.tr, body="see below")
        ok, error, _url, _written = self.forward([f"g{self.room.pk}-{words.pk}", self.message("t.pdf")], note="FYI")
        self.assertTrue(ok, error)
        self.assertEqual([c.args[1] for c in self.text.call_args_list], ["see below"])
        self.assertEqual(self.captions(), ["FYI"])

    def test_an_audio_file_cannot_carry_a_caption_so_the_note_is_sent_as_words_before_it(self):
        ok, error, _url, _written = self.forward([self.message("note.ogg")], note="Listen to this")
        self.assertTrue(ok, error)
        self.assertEqual([c.args[1] for c in self.text.call_args_list], ["Listen to this"])
        self.assertEqual(self.captions(), [""])

    def test_a_note_longer_than_whatsapp_takes_as_a_caption_is_sent_as_words_in_full(self):
        long_note = "x" * (whatsapp.CAPTION_LIMIT + 1)
        ok, error, _url, _written = self.forward([self.message()], note=long_note)
        self.assertTrue(ok, error)
        self.assertEqual([c.args[1] for c in self.text.call_args_list], [long_note])
        self.assertEqual(self.captions(), [NEUTRAL])

    def test_a_note_of_exactly_the_limit_still_rides_on_the_file(self):
        note = "y" * whatsapp.CAPTION_LIMIT
        ok, error, _url, _written = self.forward([self.message()], note=note)
        self.assertTrue(ok, error)
        self.text.assert_not_called()
        self.assertEqual(self.captions(), [note])

    def test_a_note_of_spaces_is_no_note(self):
        ok, error, _url, _written = self.forward([self.message()], note="   ")
        self.assertTrue(ok, error)
        self.assertEqual(self.captions(), [NEUTRAL])

    def test_a_refused_send_leaves_the_caption_unsaid_and_the_rest_unsent(self):
        self.file.side_effect = whatsapp.WhatsAppError("واتساب رجّع خطأ (131)", "WhatsApp error (131)")
        ok, _error, _url, written = self.forward([self.message("a.pdf"), self.message("b.pdf")], note="Both")
        self.assertFalse(ok)
        self.assertFalse(written)
        self.assertEqual(self.file.call_count, 1)

    def test_it_is_the_same_through_the_new_door(self):
        browser = DjangoClient()
        browser.force_login(self.ops)
        body = {"source": f"u{self.tr.pk}", "target": self.acme.code, "uids": [self.message()], "note": "Via the door"}
        answer = browser.post(reverse("dashboard:v1_chat_forward"), json.dumps(body), content_type="application/json")
        self.assertEqual(answer.status_code, 200, answer.content)
        self.assertTrue(json.loads(answer.content)["delivered"])
        self.text.assert_not_called()
        self.assertEqual(self.captions(), ["Via the door"])


class UnchangedTests(_Forward):
    """What this does not touch."""

    def test_a_file_the_person_uploads_without_words_is_still_captioned_with_its_own_name(self):
        ok, _out, error = services.send_client_message(
            self.acme, self.ops, uploads=[SimpleUploadedFile("my-own-file.pdf", b"%PDF", "application/pdf")],
            force_channel=Channel.WHATSAPP,
        )
        self.assertTrue(ok, error)
        self.assertEqual(self.captions(), ["my-own-file.pdf"])

    def test_words_and_a_file_without_caption_files_are_still_two_messages(self):
        ok, _out, error = services.send_client_message(
            self.acme, self.ops, body="the brief",
            uploads=[SimpleUploadedFile("brief.pdf", b"%PDF", "application/pdf")], force_channel=Channel.WHATSAPP,
        )
        self.assertTrue(ok, error)
        self.assertEqual([c.args[1] for c in self.text.call_args_list], ["the brief"])
        self.assertEqual(self.captions(), [""])

    def test_a_forward_to_a_colleague_keeps_the_note_as_a_message_of_its_own(self):
        # Inside the team there is no caption: the note is a line in the chat, as it was.
        other = User.objects.create_user("ops_cap2", password="x", role=Role.OPERATION)
        ok, error, _url, _written = services.forward_messages(
            self.ops, f"u{self.tr.pk}", f"u{other.pk}", uids=[self.message()], note="For you",
        )
        self.assertTrue(ok, error)
        room = services.staff_room(self.ops, other)
        self.assertEqual([m.body for m in room.messages.filter(is_system=False)], ["For you", ""])
        self.file.assert_not_called()
