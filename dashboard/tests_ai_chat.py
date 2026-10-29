"""The team leader's talk with the AI that has his task (29/10/2026).

What these tests hold:

- the talk opens only for the task's own leader (and the admin), only once the task was given to the AI, and only while the owner has the AI on;
- a line is stored with the AI's answer pending, one at a time; the answer is filled from a call that is given the source, the AI's own
  translation, the leader's words and the file he attached (a picture goes to the model as a picture);
- nothing in the task moves: no status, no file, no gate;
- a failed call leaves a failed line and the leader writes again; a pending line a dead process left is closed;
- what he attached opens for him and the admin, and for nobody else.
"""

from datetime import timedelta
from unittest import mock

from django.core.files.uploadedfile import SimpleUploadedFile
from django.urls import reverse
from django.utils import timezone

from . import ai_chat, files
from .models import AIChatMessage, AppSettings, AuditLog
from .tests_ai_translate import _AiTask, _json

CHAT = "dashboard:v1_task_ai_chat"
SEND = "dashboard:v1_task_ai_chat_send"
PNG = b"\x89PNG\r\n\x1a\n" + b"0" * 32


class _Talk(_AiTask):
    def read(self, user=None):
        return self.browser(user or self.lead).get(reverse(CHAT, args=[self.task.code]))

    def write(self, text="", user=None, upload=None):
        body = {"text": text}
        if upload is not None:
            body["file"] = upload
        return self.browser(user or self.lead).post(reverse(SEND, args=[self.task.code]), body)

    def answer(self, text="الجواب", fail=None):
        """Let the thread's work run here, with the model answering ``text`` (or raising ``fail``)."""
        pending = AIChatMessage.objects.get(status="pending")
        model = mock.patch.object(ai_chat, "call", side_effect=fail) if fail else mock.patch.object(ai_chat, "call", return_value=text)
        with model as call:
            ai_chat.finish(pending.pk)
        return call


class OpeningTests(_Talk):
    def test_no_talk_before_the_task_went_to_the_ai(self):
        self.assertFalse(self.page()["lead"]["ai_chat"])
        self.assertEqual(self.read().status_code, 403)
        self.assertEqual(self.write("hi").status_code, 403)
        self.assertFalse(AIChatMessage.objects.exists())

    def test_it_opens_once_the_task_went_to_the_ai(self):
        self.translate()
        self.assertTrue(self.page()["lead"]["ai_chat"])
        self.assertEqual(_json(self.read()), {"ok": True, "pending": False, "messages": []})

    def test_it_opens_while_the_ai_is_still_at_the_translation(self):
        self.press()
        self.assertTrue(self.page()["lead"]["ai_chat"])

    def test_switched_off_it_is_gone(self):
        self.translate()
        conf = AppSettings.load()
        conf.ai_translate_enabled = False
        conf.save()
        self.assertFalse(self.page()["lead"]["ai_chat"])
        self.assertEqual(self.write("hi").status_code, 403)

    def test_the_operation_and_a_translator_do_not_get_it(self):
        self.translate()
        self.assertFalse(self.page(self.ops)["lead"] and self.page(self.ops)["lead"]["ai_chat"])
        for who in (self.ops, self.translator):
            self.assertEqual(self.read(who).status_code, 403)
            self.assertEqual(self.write("hi", who).status_code, 403)
        self.assertFalse(AIChatMessage.objects.exists())

    def test_another_leaders_task_is_not_found_and_written_down(self):
        self.translate()
        before = AuditLog.objects.count()
        self.assertEqual(self.read(self.other_lead).status_code, 404)
        self.assertEqual(self.write("hi", self.other_lead).status_code, 404)
        self.assertGreater(AuditLog.objects.count(), before)

    def test_the_admin_may(self):
        self.translate()
        self.assertEqual(self.write("hi", self.admin).status_code, 200)
        self.assertEqual(AIChatMessage.objects.get(role="user").sender, self.admin)


class SendingTests(_Talk):
    def setUp(self):
        super().setUp()
        self.translate()

    def test_a_line_is_stored_with_the_answer_pending(self):
        response = self.write("ليه اخترت كلمة مرحبا؟")
        self.assertEqual(response.status_code, 200)
        data = _json(response)
        self.assertTrue(data["pending"])
        self.assertEqual([(m["role"], m["status"]) for m in data["messages"]], [("user", "done"), ("assistant", "pending")])
        self.assertEqual(data["messages"][0]["body"], "ليه اخترت كلمة مرحبا؟")

    def test_nothing_goes_while_an_answer_is_being_written(self):
        self.write("one")
        refused = self.write("two")
        self.assertEqual(refused.status_code, 400)
        self.assertEqual(_json(refused)["code"], "busy")
        self.assertEqual(AIChatMessage.objects.filter(role="user").count(), 1)

    def test_empty_long_and_unreadable_are_refused_with_the_reason(self):
        self.assertEqual(_json(self.write("   "))["code"], "empty")
        self.assertEqual(_json(self.write("x" * (ai_chat.MAX_TEXT + 1)))["code"], "text_too_long")
        sheet = SimpleUploadedFile("sheet.xlsx", b"PK", content_type="application/octet-stream")
        self.assertEqual(_json(self.write("look", upload=sheet))["code"], "file_unreadable")
        self.assertFalse(AIChatMessage.objects.exists())

    def test_a_file_over_the_limit_is_refused(self):
        big = SimpleUploadedFile("page.png", b"0" * (ai_chat.MAX_FILE_BYTES + 1), content_type="image/png")
        self.assertEqual(_json(self.write("look", upload=big))["code"], "file_too_big")

    def test_a_message_of_only_a_file_goes(self):
        picture = SimpleUploadedFile("page.png", PNG, content_type="image/png")
        data = _json(self.write("", upload=picture))
        line = data["messages"][0]
        self.assertEqual(line["file"]["name"], "page.png")
        self.assertTrue(line["file"]["image"])
        self.assertTrue(line["file"]["url"].startswith("/files/"))

    def test_the_talk_is_capped(self):
        for _ in range(ai_chat.MAX_USER_MESSAGES):
            AIChatMessage.objects.create(task=self.task, role="user", sender=self.lead, body="x")
        self.assertEqual(_json(self.write("one more"))["code"], "chat_full")

    def test_the_task_does_not_move(self):
        before = (self.task.status, self.task.updated_at, self.task.ai_translations.count())
        self.write("هل الترجمة دقيقة؟")
        self.answer()
        self.task.refresh_from_db()
        self.assertEqual((self.task.status, self.task.updated_at, self.task.ai_translations.count()), before)


class AnswerTests(_Talk):
    def setUp(self):
        super().setUp()
        self.translate()

    def test_the_ai_is_given_the_source_its_translation_and_the_leaders_words(self):
        self.write("ليه اخترت الكلمة دي؟")
        call = self.answer("عشان كده")
        messages = call.call_args.args[1]
        first = messages[0]["content"]
        context = " ".join(block["text"] for block in first if block["type"] == "text")
        self.assertIn("Hello world", context)
        self.assertIn("مرحبا بالعالم", context)
        self.assertIn("EN", context)
        self.assertEqual(messages[-1]["role"], "user")
        self.assertIn("ليه اخترت الكلمة دي؟", str(messages[-1]["content"]))
        line = AIChatMessage.objects.get(role="assistant")
        self.assertEqual((line.status, line.body), ("done", "عشان كده"))

    def test_the_answer_shows_in_the_talk(self):
        self.write("hi")
        self.answer("hello back")
        data = _json(self.read())
        self.assertFalse(data["pending"])
        self.assertEqual([m["body"] for m in data["messages"]], ["hi", "hello back"])

    def test_the_second_question_carries_the_first_round(self):
        self.write("one")
        self.answer("first answer")
        self.write("two")
        call = self.answer("second answer")
        messages = call.call_args.args[1]
        roles = [m["role"] for m in messages]
        self.assertEqual(roles, ["user", "user", "assistant", "user"])
        self.assertEqual(messages[2]["content"], "first answer")

    def test_a_picture_goes_to_the_model_as_a_picture(self):
        self.write("هل الصورة دي صح؟", upload=SimpleUploadedFile("page.png", PNG, content_type="image/png"))
        call = self.answer()
        blocks = call.call_args.args[1][-1]["content"]
        self.assertTrue(any(block["type"] == "image" and block["source"]["media_type"] == "image/png" for block in blocks))
        self.assertIn("هل الصورة دي صح؟", str(blocks))

    def test_a_word_file_goes_as_its_words(self):
        import io
        import zipfile

        buffer = io.BytesIO()
        with zipfile.ZipFile(buffer, "w") as archive:
            archive.writestr("word/document.xml", "<w:document><w:p><w:t>كلمات الملف</w:t></w:p></w:document>")
        upload = SimpleUploadedFile("notes.docx", buffer.getvalue())
        self.write("اقرا ده", upload=upload)
        call = self.answer()
        self.assertIn("كلمات الملف", str(call.call_args.args[1][-1]["content"]))

    def test_older_files_are_named_not_sent_again(self):
        for place in range(ai_chat.FILES_RESENT + 1):
            self.write(f"q{place}", upload=SimpleUploadedFile(f"p{place}.png", PNG, content_type="image/png"))
            call = self.answer()
        sent = [
            block for message in call.call_args.args[1][1:] if message["role"] == "user"
            for block in message["content"] if block["type"] == "image"
        ]
        self.assertEqual(len(sent), ai_chat.FILES_RESENT)
        self.assertIn("p0.png", str(call.call_args.args[1]))

    def test_a_failed_call_leaves_a_failed_line_and_the_leader_writes_again(self):
        self.write("hi")
        self.answer(fail=RuntimeError("down"))
        line = AIChatMessage.objects.get(role="assistant")
        self.assertEqual((line.status, line.error_message), ("error", "RuntimeError"))
        self.assertFalse(_json(self.read())["pending"])
        self.assertEqual(self.write("again").status_code, 200)

    def test_an_empty_answer_is_a_failure(self):
        self.write("hi")
        self.answer("")
        self.assertEqual(AIChatMessage.objects.get(role="assistant").status, "error")

    def test_a_line_a_dead_process_left_is_closed(self):
        self.write("hi")
        AIChatMessage.objects.update(created_at=timezone.now() - timedelta(minutes=ai_chat.STALE_MINUTES + 1))
        data = _json(self.read())
        self.assertFalse(data["pending"])
        self.assertEqual(data["messages"][-1]["status"], "error")
        self.assertEqual(self.write("again").status_code, 200)

    def test_the_call_is_written_down_as_its_own_feature(self):
        from .models import ClaudeUsage

        body = {"model": "claude-sonnet-4-5", "usage": {"input_tokens": 10, "output_tokens": 5}, "content": [{"type": "text", "text": "ok"}]}

        class Reply:
            def __enter__(self):
                return self

            def __exit__(self, *args):
                return False

            def read(self):
                import json

                return json.dumps(body).encode("utf-8")

        self.write("hi")
        with mock.patch.object(ai_chat.net, "urlopen", return_value=Reply()):
            ai_chat.finish(AIChatMessage.objects.get(status="pending").pk)
        self.assertEqual(AIChatMessage.objects.get(role="assistant").body, "ok")
        self.assertTrue(ClaudeUsage.objects.filter(feature="ai_chat").exists())


class FileTests(_Talk):
    def test_what_he_attached_opens_for_him_and_the_admin_only(self):
        self.translate()
        self.write("look", upload=SimpleUploadedFile("page.png", PNG, content_type="image/png"))
        name = AIChatMessage.objects.get(role="user").file.name
        self.assertTrue(files.may_open(self.lead, name)[0])
        self.assertTrue(files.may_open(self.admin, name)[0])
        self.assertFalse(files.may_open(self.ops, name)[0])
        self.assertFalse(files.may_open(self.other_lead, name)[0])
        self.assertFalse(files.may_open(self.translator, name)[0])
        url = AIChatMessage.objects.get(role="user").file.url
        self.assertEqual(self.browser(self.ops).get(url).status_code, 404)
