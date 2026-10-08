"""A notification says what was sent - "a photo", "a voice note", "a PDF" - not just "files".

Three places write the line a person reads when a message with a file lands: a chat message in a room or between two
colleagues (``api.chat_send``), a client's message copied into a room the team watches (``services._mirror_into``), and
the first ring when a client writes (``services.ingest_message``). They share ``services.files_phrase`` and
``services.chat_line``; the tests here pin the kinds, the counts, and the places a line could go wrong:

* a file with words: the words win the line and the kind follows them; a file alone: the kind is the line;
* a recording made in the page is a "voice note", an audio file someone attached is "an audio file";
* a file name is never in the line (a client's name can be in it);
* a letter's attachments stay out of the ring: they are mostly a signature logo.
"""

from django.core.files.base import ContentFile
from django.core.files.uploadedfile import SimpleUploadedFile

from . import services, webhooks
from .models import Channel, ChatAttachment, InboundMessage, MessageAttachment, Notification
from .tests_chat_send import _Send


def upload(name, mime="application/octet-stream"):
    return SimpleUploadedFile(name, b"x", mime)


class FilesPhraseTests(_Send):
    """The words for what a message carries, from the stored files."""

    def phrase(self, *names, voice=False):
        message = self.team.messages.create(sender=self.ops, body="")
        rows = [ChatAttachment.objects.create(message=message, file=ContentFile(b"x", name=name), original_name=name) for name in names]
        return services.files_phrase(rows, voice_ids={rows[0].pk} if voice else ())

    def test_each_kind_is_called_by_what_it_is(self):
        cases = {
            "photo.jpg": ("صورة", "a photo"),
            "scan.PNG": ("صورة", "a photo"),
            "note.pdf": ("ملف PDF", "a PDF"),
            "contract.docx": ("مستند Word", "a Word document"),
            "letter.txt": ("مستند", "a document"),
            "rates.xlsx": ("جدول Excel", "an Excel sheet"),
            "deck.pptx": ("عرض PowerPoint", "a PowerPoint"),
            "clip.mp4": ("فيديو", "a video"),
            "song.mp3": ("ملف صوتي", "an audio file"),
            "bundle.zip": ("ملف مضغوط", "a ZIP file"),
            "mystery.bin": ("ملف", "a file"),
            "noextension": ("ملف", "a file"),
        }
        for name, expected in cases.items():
            with self.subTest(name):
                self.assertEqual(self.phrase(name), expected)

    def test_a_vector_picture_is_a_file_and_not_a_photo(self):
        # The same rule as the bubble: an SVG is a document that can carry script, not a picture.
        self.assertEqual(self.phrase("logo.svg"), ("ملف", "a file"))

    def test_a_recording_made_in_the_page_is_a_voice_note_and_an_attached_audio_file_is_not(self):
        self.assertEqual(self.phrase("voice.ogg", voice=True), ("رسالة صوتية", "a voice note"))
        self.assertEqual(self.phrase("voice.ogg"), ("ملف صوتي", "an audio file"))

    def test_a_clients_voice_note_is_a_voice_note(self):
        letter = InboundMessage.objects.create(client=self.client_obj, channel=Channel.WHATSAPP, body="")
        note = MessageAttachment.objects.create(
            message=letter, file=ContentFile(b"x", name="v.ogg"), original_name="v.ogg", mime="audio/ogg", is_voice=True,
        )
        self.assertEqual(services.files_phrase([note]), ("رسالة صوتية", "a voice note"))

    def test_the_mime_type_tells_when_the_name_cannot(self):
        letter = InboundMessage.objects.create(client=self.client_obj, channel=Channel.WHATSAPP, body="")
        made = lambda name, mime: MessageAttachment.objects.create(
            message=letter, file=ContentFile(b"x", name="f"), original_name=name, mime=mime,
        )
        self.assertEqual(services.files_phrase([made("file1", "application/pdf")]), ("ملف PDF", "a PDF"))
        self.assertEqual(services.files_phrase([made("file2", "video/mp4")]), ("فيديو", "a video"))
        self.assertEqual(services.files_phrase([made("file3", "image/jpeg")]), ("صورة", "a photo"))

    def test_counts_use_the_arabic_forms_for_one_two_few_and_many(self):
        self.assertEqual(self.phrase("a.jpg", "b.jpg"), ("صورتين", "2 photos"))
        self.assertEqual(self.phrase(*[f"{n}.jpg" for n in range(3)]), ("3 صور", "3 photos"))
        self.assertEqual(self.phrase(*[f"{n}.jpg" for n in range(10)]), ("10 صور", "10 photos"))
        self.assertEqual(self.phrase(*[f"{n}.jpg" for n in range(11)]), ("11 صورة", "11 photos"))

    def test_two_kinds_are_both_named_and_more_than_three_are_a_count(self):
        self.assertEqual(self.phrase("a.jpg", "b.jpg", "c.pdf"), ("صورتين وملف PDF", "2 photos and a PDF"))
        self.assertEqual(
            self.phrase("a.jpg", "b.pdf", "c.mp4"), ("صورة وملف PDF وفيديو", "a photo, a PDF and a video"),
        )
        self.assertEqual(self.phrase("a.jpg", "b.pdf", "c.mp4", "d.zip"), ("4 ملفات", "4 files"))

    def test_no_files_is_no_phrase(self):
        self.assertEqual(services.files_phrase([]), ("", ""))

    def test_the_file_name_is_never_in_the_phrase(self):
        ar, en = self.phrase("ACME contract 2291.pdf")
        self.assertNotIn("ACME", ar + en)
        self.assertNotIn("2291", ar + en)


class ChatLineTests(_Send):
    def test_words_alone_read_as_they_always_did(self):
        self.assertEqual(services.chat_line("Sara", "ready", ("", "")), ("Sara: ready", "Sara: ready"))
        self.assertEqual(services.chat_line("Sara", "ready", ("", ""), where="Work"), ("Sara في Work: ready", "Sara in Work: ready"))

    def test_a_file_alone_is_the_line(self):
        files = ("صورة", "a photo")
        self.assertEqual(services.chat_line("Sara", "", files), ("Sara بعت صورة", "Sara sent a photo"))
        self.assertEqual(
            services.chat_line("Sara", "", files, where="Work"), ("Sara بعت صورة في Work", "Sara sent a photo in Work"),
        )

    def test_words_with_a_file_keep_the_words_and_add_the_kind(self):
        self.assertEqual(
            services.chat_line("Sara", "look", ("ملف PDF", "a PDF")), ("Sara: look (+ ملف PDF)", "Sara: look (+ a PDF)"),
        )

    def test_the_words_are_cut_and_the_kind_is_not(self):
        ar, en = services.chat_line("Sara", "w" * 100, ("صورة", "a photo"))
        self.assertEqual(ar, "Sara: " + "w" * 60 + " (+ صورة)")
        self.assertEqual(en, "Sara: " + "w" * 60 + " (+ a photo)")

    def test_a_client_is_named_in_each_language(self):
        ar, en = services.chat_line("العميل C-1", "", ("صورة", "a photo"), who_en="Client C-1")
        self.assertEqual((ar, en), ("العميل C-1 بعت صورة", "Client C-1 sent a photo"))

    def test_nothing_known_falls_back_to_files(self):
        self.assertEqual(services.chat_line("Sara", "", ("", "")), ("Sara بعت ملفات", "Sara sent files"))


class ChatSendNotificationTests(_Send):
    """The line a colleague is rung with, through the real doors."""

    def notice(self, user):
        return Notification.objects.filter(user=user, title_en="New chat message").get()

    def test_a_photo_sent_to_a_colleague_says_so(self):
        answer = self.to_staff(self.ops, self.lead, body="", task="none", files=upload("p.jpg", "image/jpeg"))
        self.assertEqual(answer.status_code, 200)
        notice = self.notice(self.lead)
        name = self.ops.short_name
        self.assertEqual(notice.body_en, f"{name} sent a photo")
        self.assertEqual(notice.body_ar, f"{name} بعت صورة")

    def test_a_recording_sent_to_a_colleague_says_voice_note(self):
        answer = self.to_staff(self.ops, self.lead, voice=upload("voice.ogg", "audio/ogg"))
        self.assertEqual(answer.status_code, 200)
        notice = self.notice(self.lead)
        self.assertEqual(notice.body_en, f"{self.ops.short_name} sent a voice note")
        self.assertEqual(notice.body_ar, f"{self.ops.short_name} بعت رسالة صوتية")

    def test_an_audio_file_attached_is_not_called_a_voice_note(self):
        self.to_staff(self.ops, self.lead, task="none", files=upload("song.mp3", "audio/mpeg"))
        self.assertEqual(self.notice(self.lead).body_en, f"{self.ops.short_name} sent an audio file")

    def test_a_pdf_and_a_document_in_a_work_group_name_the_group_and_both_kinds(self):
        files = [upload("a.pdf", "application/pdf"), upload("b.docx")]
        self.to_group(self.lead, self.team, body="", task="none", files=files)
        notice = self.notice(self.ops)
        self.assertEqual(notice.body_en, f"{self.lead.short_name} sent a PDF and a Word document in Work")
        self.assertEqual(notice.body_ar, f"{self.lead.short_name} بعت ملف PDF ومستند Word في Work")
        self.assertEqual(self.notice(self.tr).body_en, notice.body_en)

    def test_words_with_a_file_keep_the_words(self):
        self.to_staff(self.ops, self.lead, body="the quote", task="none", files=upload("p.jpg", "image/jpeg"))
        self.assertEqual(self.notice(self.lead).body_en, f"{self.ops.short_name}: the quote (+ a photo)")

    def test_words_alone_are_unchanged(self):
        self.to_staff(self.ops, self.lead, body="ready when you are")
        self.assertEqual(self.notice(self.lead).body_en, f"{self.ops.short_name}: ready when you are")

    def test_a_mention_with_a_file_says_so_after_the_words(self):
        self.to_group(
            self.ops, self.team, body=f"@{self.tr.short_name} see this", mentions=str(self.tr.pk), task="none",
            files=upload("p.png", "image/png"),
        )
        ping = Notification.objects.get(user=self.tr, title_en__endswith="mentioned you")
        self.assertIn("see this (+ a photo)", ping.body_en)
        self.assertIn("(+ صورة)", ping.body_ar)

    def test_a_mention_without_a_file_is_unchanged(self):
        self.to_group(self.ops, self.team, body=f"@{self.tr.short_name} see this", mentions=str(self.tr.pk))
        ping = Notification.objects.get(user=self.tr, title_en__endswith="mentioned you")
        self.assertTrue(ping.body_en.endswith("see this"))


class ClientMessageNotificationTests(_Send):
    """What a client sent, told by kind, in the room and in the first ring."""

    def came(self, body="", files=(), channel=Channel.WHATSAPP):
        items = [{"file": ContentFile(b"x", name=name), "name": name, "mime": mime, "is_voice": voice} for name, mime, voice in files]
        return services.ingest_message(
            channel=channel, body=body, sender_identity=self.client_obj.phone, external_id=f"wamid.kind.{len(files)}.{body}",
            attachments=items,
        )

    def ring(self, user):
        return Notification.objects.filter(user=user, title_en__in=["New client message", "New client e-mail"])

    def test_a_clients_photo_rings_the_operation_as_a_photo(self):
        self.came(files=[("p.jpg", "image/jpeg", False)])
        ring = self.ring(self.ops).get()
        code = self.client_obj.code
        self.assertEqual(ring.body_en, f"Client {code} sent a photo.")
        self.assertEqual(ring.body_ar, f"العميل {code} بعت صورة.")

    def test_a_file_with_no_caption_is_a_file_alone_though_the_webhook_writes_a_placeholder_as_its_words(self):
        # What the webhook stores for a photo or a document sent without a caption is "[image]" / "[document]" -
        # that is not something the client said, and the ring must not read it as "a message with a photo".
        for kind, name, mime, expected in (
            ("image", "p.jpg", "image/jpeg", "a photo"), ("document", "c.pdf", "application/pdf", "a PDF"),
        ):
            with self.subTest(kind):
                Notification.objects.all().delete()
                words = webhooks._body_of({"type": kind, kind: {}})
                self.assertEqual(words, f"[{kind}]")
                self.came(body=words, files=[(name, mime, False)])
                self.assertEqual(self.ring(self.ops).get().body_en, f"Client {self.client_obj.code} sent {expected}.")

    def test_a_clients_voice_note_is_a_voice_note(self):
        self.came(files=[("v.ogg", "audio/ogg", True)])
        self.assertEqual(self.ring(self.ops).get().body_en, f"Client {self.client_obj.code} sent a voice note.")

    def test_words_with_a_file_say_the_message_came_with_it(self):
        self.came(body="the contract", files=[("c.pdf", "application/pdf", False)])
        ring = self.ring(self.ops).get()
        self.assertEqual(ring.body_en, f"A new message arrived from client {self.client_obj.code} with a PDF.")

    def test_words_alone_are_unchanged(self):
        self.came(body="hello")
        self.assertEqual(self.ring(self.ops).get().body_en, f"A new message arrived from client {self.client_obj.code}.")

    def test_a_letters_attachments_stay_out_of_the_ring(self):
        self.came(body="Dear all", files=[("logo.png", "image/png", False)], channel=Channel.EMAIL)
        ring = self.ring(self.ops).get()
        self.assertEqual(ring.body_en, f"A new e-mail arrived from client {self.client_obj.code}.")

    def mirrored(self, body="", channel=Channel.WHATSAPP, name="c.pdf", mime="application/pdf"):
        """A client's message with one file, copied into the client group, and the line its Sales member is rung with."""
        self.group.members.add(self.sales)
        letter = InboundMessage.objects.create(client=self.client_obj, channel=channel, body=body)
        MessageAttachment.objects.create(message=letter, file=ContentFile(b"x", name=name), original_name=name, mime=mime)
        services._mirror_into(self.group, letter)
        return Notification.objects.get(user=self.sales, title_en="New message from the client")

    def test_a_client_file_copied_into_a_room_names_the_client_by_code_and_the_kind(self):
        note = self.mirrored()
        code = self.client_obj.code
        self.assertEqual(note.body_en, f"Client {code} sent a PDF in With the client")
        self.assertEqual(note.body_ar, f"العميل {code} بعت ملف PDF في With the client")
        # The name and the number of the client are never in it.
        self.assertNotIn("Zebulon", note.body_en + note.body_ar)
        self.assertNotIn("1234567890", note.body_en + note.body_ar)

    def test_the_placeholder_the_webhook_writes_is_not_quoted_in_the_room(self):
        note = self.mirrored(body="[image]", name="p.jpg", mime="image/jpeg")
        self.assertEqual(note.body_en, f"Client {self.client_obj.code} sent a photo in With the client")
        self.assertNotIn("[image]", note.body_en + note.body_ar)

    def test_words_with_a_file_in_the_room_keep_the_words_and_add_the_kind(self):
        note = self.mirrored(body="the contract")
        self.assertEqual(note.body_en, f"Client {self.client_obj.code} in With the client: the contract (+ a PDF)")

    def test_a_letters_attachments_stay_out_of_the_room_line_as_they_do_out_of_the_ring(self):
        note = self.mirrored(body="Dear all", channel=Channel.EMAIL, name="logo.png", mime="image/png")
        self.assertEqual(note.body_en, f"Client {self.client_obj.code} in With the client: Dear all")
