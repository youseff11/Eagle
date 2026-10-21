"""«ترجمها بالـAI»: the team leader gives a task to the AI instead of a translator, and reviews what comes back (21/10/2026).

What these tests hold:

- the leader of a task that is his and not being translated has the choice on his page, only while the owner has it on and a key is
  saved; the door refuses everybody else, and a task that cannot go now (no pair, nothing readable, already going) says why;
- the model is asked once, streamed, and its answer becomes a Word file of the task's code (never a client's name); the task goes to
  the leader's review, and a failure leaves the task with him with nothing changed;
- at the review the AI's file is what goes on unless he uploaded his own; it cannot be sent back to a translator who does not exist;
- the file opens for those who may open the task, and for nobody else;
- while the AI is at it, the task cannot also be given to a translator.
"""

import io
import json
import zipfile
from datetime import timedelta
from unittest import mock

from django.core.files.uploadedfile import SimpleUploadedFile
from django.core.management import call_command
from django.test import Client as DjangoClient
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from . import ai, ai_translate, files, services
from .models import (
    AITranslation, AppSettings, AuditLog, ChatAttachment, Client, Notification, Role, TaskStatus, TaskUpload, User,
)

DOOR = "dashboard:v1_task_ai_translate"
TASK = "dashboard:v1_task"
ANSWER = "مرحبا بالعالم\nسطر تاني فيه <رمز> & علامة\n\nآخر سطر"


def _json(response):
    return json.loads(response.content.decode("utf-8"))


def _docx_lines(row):
    row.file.open("rb")
    try:
        raw = row.file.read()
    finally:
        row.file.close()
    return ai._docx_text(raw)


class _AiTask(TestCase):
    """A task with its source uploaded, accepted by its team leader and given to nobody yet; the switch on and a key saved."""

    def setUp(self):
        make = lambda name, role, **kw: User.objects.create_user(name, password="x", role=role, **kw)
        self.ops = make("ops_ait", Role.OPERATION)
        self.lead = make("lead_ait", Role.TEAM_LEAD)
        self.other_lead = make("lead_ait_two", Role.TEAM_LEAD)
        self.admin = make("admin_ait", Role.ADMIN)
        self.translator = make("tr_ait", Role.TRANSLATOR, team_lead=self.lead)
        self.acme = Client.objects.create(name="ACME Secret Ltd", phone="+201000000193")
        conf = AppSettings.load()
        conf.ai_translate_enabled = True
        conf.claude_api_key = "test-key"
        conf.save()
        self.task = services.create_task(
            client=self.acme, title="Contract", created_by=self.ops, deadline=timezone.now() + timedelta(days=3),
            source_lang="EN", target_lang="AR",
        )
        services.accept_assignment(services.assign_to_lead(self.task, self.lead, self.ops), self.lead)
        self.task.refresh_from_db()
        self.source = TaskUpload.objects.create(
            task=self.task, file=SimpleUploadedFile("contract.txt", b"Hello world", content_type="text/plain"),
            original_name="contract.txt", size=11,
        )

    def browser(self, user):
        browser = DjangoClient()
        browser.force_login(user)
        return browser

    def press(self, user=None, instructions=None):
        body = {} if instructions is None else {"instructions": instructions}
        return self.browser(user or self.lead).post(reverse(DOOR, args=[self.task.code]), body)

    def page(self, user=None):
        return _json(self.browser(user or self.lead).get(reverse(TASK, args=[self.task.code])))["task"]

    def translate(self, answer=ANSWER, stop="end_turn", instructions=None):
        """Press, and let the thread's work run here, with the model answering ``answer``."""
        response = self.press(instructions=instructions)
        self.assertEqual(response.status_code, 200, response.content)
        with mock.patch.object(ai_translate, "stream_text", return_value=(answer, stop)) as model:
            row = ai_translate.finish(_json(response)["id"])
        self.task.refresh_from_db()
        return row, model


class ChoiceTests(_AiTask):
    def test_the_leader_has_both_ways_forward(self):
        lead = self.page()["lead"]
        self.assertTrue(lead["can_assign"])
        self.assertEqual(lead["ai_translate"], {"running": False, "can_start": True, "problem": None, "failed": False})

    def test_switched_off_or_no_key_there_is_no_button(self):
        conf = AppSettings.load()
        conf.ai_translate_enabled = False
        conf.save()
        self.assertIsNone(self.page()["lead"]["ai_translate"])
        self.assertEqual(self.press().status_code, 400)
        conf.ai_translate_enabled = True
        conf.claude_api_key = ""
        conf.save()
        self.assertIsNone(self.page()["lead"]["ai_translate"])
        self.assertEqual(_json(self.press())["code"], "unavailable")
        self.assertFalse(AITranslation.objects.exists())

    def test_the_operation_does_not_get_the_choice(self):
        self.assertIsNone(self.page(self.ops)["lead"])
        self.assertEqual(self.press(self.ops).status_code, 403)
        self.assertEqual(self.press(self.translator).status_code, 403)
        self.assertFalse(AITranslation.objects.exists())

    def test_another_leaders_task_is_not_found_and_written_down(self):
        before = AuditLog.objects.count()
        self.assertEqual(self.press(self.other_lead).status_code, 404)
        self.assertGreater(AuditLog.objects.count(), before)
        self.assertFalse(AITranslation.objects.exists())

    def test_the_admin_may(self):
        self.assertEqual(self.press(self.admin).status_code, 200)
        self.assertEqual(AITranslation.objects.get().requested_by, self.admin)

    def test_a_task_without_the_pair_says_so(self):
        self.task.target_lang = ""
        self.task.save()
        lead = self.page()["lead"]
        self.assertFalse(lead["ai_translate"]["can_start"])
        self.assertIn("لغة الترجمة", lead["ai_translate"]["problem"])
        self.assertEqual(_json(self.press())["code"], "task_needs_languages")

    def test_nothing_the_model_can_read_says_so(self):
        self.source.original_name = "sheet.xlsx"
        self.source.save()
        self.assertEqual(_json(self.press())["code"], "no_source")

    def test_a_task_already_with_a_translator_cannot_go_to_the_ai(self):
        share = services.assign_to_translators(self.task, [services.Part(self.translator, "EN", "AR", 0, None, None)], self.lead)[0]
        services.accept_assignment(share, self.translator)
        self.task.refresh_from_db()
        self.assertEqual(self.task.status, TaskStatus.IN_PROGRESS)
        self.assertIsNone(self.page()["lead"]["ai_translate"])
        self.assertEqual(_json(self.press())["code"], "bad_status")


class WhileRunningTests(_AiTask):
    def test_one_or_the_other_not_both(self):
        self.assertEqual(self.press().status_code, 200)
        lead = self.page()["lead"]
        self.assertTrue(lead["ai_translate"]["running"])
        self.assertFalse(lead["can_assign"])
        # The assign door says it too, not only the page.
        response = self.browser(self.lead).post(
            f"/api/tasks/{self.task.code}/assign-translator/", {"user": self.translator.pk, "tdeadline_mode": "same"},
        )
        self.assertEqual(response.status_code, 400)
        self.assertEqual(_json(response)["code"], "ai_running")
        # A second press does not start a second call.
        self.assertEqual(_json(self.press())["code"], "running")
        self.assertEqual(AITranslation.objects.count(), 1)

    def test_a_row_a_dead_process_left_does_not_block_for_ever(self):
        self.assertEqual(self.press().status_code, 200)
        AITranslation.objects.update(created_at=timezone.now() - timedelta(minutes=ai_translate.STALE_MINUTES + 1))
        self.assertTrue(self.page()["lead"]["ai_translate"]["can_start"])
        self.assertEqual(self.press().status_code, 200)
        self.assertEqual(AITranslation.objects.filter(status="running").count(), 1)
        self.assertEqual(AITranslation.objects.filter(status="error").count(), 1)

    def test_the_command_finishes_a_stuck_row(self):
        self.assertEqual(self.press().status_code, 200)
        AITranslation.objects.update(created_at=timezone.now() - timedelta(minutes=ai_translate.STALE_MINUTES + 1))
        with mock.patch.object(ai_translate, "stream_text", return_value=(ANSWER, "end_turn")):
            call_command("run_ai_checks", stdout=io.StringIO())
        self.assertEqual(AITranslation.objects.get().status, "done")
        self.task.refresh_from_db()
        self.assertEqual(self.task.status, TaskStatus.UNDER_REVIEW)

    def test_a_young_row_is_left_to_its_thread(self):
        self.assertEqual(self.press().status_code, 200)
        AITranslation.objects.update(created_at=timezone.now() - timedelta(minutes=11))
        with mock.patch.object(ai_translate, "stream_text") as model:
            call_command("run_ai_checks", stdout=io.StringIO())
        model.assert_not_called()


class TranslatedTests(_AiTask):
    def test_the_answer_becomes_a_word_file_and_the_task_goes_to_review(self):
        row, model = self.translate()
        self.assertEqual(row.status, "done")
        self.assertEqual(self.task.status, TaskStatus.UNDER_REVIEW)
        self.assertIsNotNone(self.task.translated_at)
        self.assertIsNone(self.task.translator_id)
        # The source and the pair reached the model; the source's words went as text.
        prompt = model.call_args.args[2]
        self.assertIn("Translate from: EN", prompt)
        self.assertIn("Translate into: AR", prompt)
        self.assertIn("Hello world", prompt)
        # A Word file named by the task, never the client.
        self.assertEqual(row.original_name, f"{self.task.code}-AI-AR.docx")
        self.assertNotIn("ACME", row.original_name)
        text = _docx_lines(row)
        self.assertIn("مرحبا بالعالم", text)
        self.assertIn("<رمز> & علامة", text)
        with zipfile.ZipFile(row.file.open("rb")) as archive:
            self.assertIn("<w:bidi/>", archive.read("word/document.xml").decode("utf-8"))
        row.file.close()

    def test_what_the_leader_asks_goes_with_the_files_and_is_kept(self):
        row, model = self.translate(instructions="  Formal legal tone; keep company names in English.  ")
        self.assertEqual(row.instructions, "Formal legal tone; keep company names in English.")
        prompt = model.call_args.args[2]
        self.assertIn("<instructions>\nFormal legal tone; keep company names in English.\n</instructions>", prompt)
        self.assertEqual(self.page()["files"]["ai"][0]["instructions"], row.instructions)

    def test_no_instructions_says_nothing_about_them(self):
        _, model = self.translate()
        self.assertNotIn("<instructions>", model.call_args.args[2])

    def test_long_instructions_are_cut_to_what_is_kept(self):
        row, _ = self.translate(instructions="x" * (ai_translate.MAX_INSTRUCTIONS + 500))
        self.assertEqual(len(row.instructions), ai_translate.MAX_INSTRUCTIONS)

    def test_the_model_is_asked_for_the_layout(self):
        self.assertIn("Markdown table", ai_translate.SYSTEM_PROMPT)
        self.assertIn("'# '", ai_translate.SYSTEM_PROMPT)

    def test_the_leader_and_the_operation_are_told(self):
        self.translate()
        self.assertTrue(Notification.objects.filter(user=self.lead, title_en="The AI translation is ready for review").exists())
        self.assertTrue(Notification.objects.filter(user=self.ops, title_en="The task is under review").exists())

    def test_the_page_lists_the_file_and_the_review_tools(self):
        self.translate()
        task = self.page()
        self.assertEqual([f["name"] for f in task["files"]["ai"]], [f"{self.task.code}-AI-AR.docx"])
        self.assertFalse(task["files"]["ai"][0]["cut_short"])
        self.assertTrue(task["lead"]["can_review"])
        self.assertTrue(task["lead"]["can_upload_reviewed"])
        self.assertTrue(task["lead"]["made_by_ai"])
        self.assertFalse(task["lead"]["can_set_part_words"])

    def test_a_translation_cut_short_says_so(self):
        row, _ = self.translate(stop="max_tokens")
        self.assertTrue(row.cut_short)
        self.assertTrue(self.page()["files"]["ai"][0]["cut_short"])
        self.assertIn("وقف قبل آخر الملف", Notification.objects.filter(user=self.lead).latest("id").body_ar)

    def test_a_failure_leaves_the_task_with_the_leader(self):
        response = self.press()
        with mock.patch.object(ai_translate, "stream_text", side_effect=OSError("down")):
            row = ai_translate.finish(_json(response)["id"])
        self.task.refresh_from_db()
        self.assertEqual(row.status, "error")
        self.assertEqual(self.task.status, TaskStatus.LEAD_ACCEPTED)
        self.assertTrue(Notification.objects.filter(user=self.lead, title_en="The AI translation did not finish").exists())
        lead = self.page()["lead"]
        self.assertTrue(lead["can_assign"])
        self.assertTrue(lead["ai_translate"]["can_start"])
        self.assertTrue(lead["ai_translate"]["failed"])

    def test_an_empty_answer_is_a_failure(self):
        row, _ = self.translate(answer="")
        self.assertEqual(row.status, "error")
        self.assertEqual(self.task.status, TaskStatus.LEAD_ACCEPTED)

    def test_given_to_a_translator_meanwhile_the_task_stays_where_it_is(self):
        response = self.press()
        # The press was taken back by hand (an old page, the admin): the task moved on before the answer came.
        AITranslation.objects.update(created_at=timezone.now() - timedelta(minutes=ai_translate.STALE_MINUTES + 1))
        services.cancel_task(self.task, self.ops, "client withdrew")
        with mock.patch.object(ai_translate, "stream_text", return_value=(ANSWER, "end_turn")):
            ai_translate.finish(_json(response)["id"])
        self.task.refresh_from_db()
        self.assertEqual(self.task.status, TaskStatus.CANCELLED)

    def test_nobody_is_paid_words_for_it(self):
        from . import payroll

        self.translate()
        today = timezone.localdate()
        for person in (self.lead, self.translator):
            self.assertEqual(payroll.production(person, today - timedelta(days=1), today + timedelta(days=1)), [])


class ReviewTests(_AiTask):
    def review(self):
        return _json(self.browser(self.lead).post(f"/api/tasks/{self.task.code}/reviewed/"))

    def test_left_as_it_is_the_ai_file_is_what_goes_on(self):
        row, _ = self.translate()
        self.assertTrue(self.review()["ok"])
        self.task.refresh_from_db()
        self.assertEqual(self.task.status, TaskStatus.REVIEWED)
        final = services.final_files(self.task)
        self.assertEqual([a.file.name for a in final], [row.file.name])
        # It reached the operation in the leader's chat with them, as a reviewed version would.
        room = services.pair_room(self.lead, self.ops)
        self.assertTrue(ChatAttachment.objects.filter(message__room=room, file=row.file.name).exists())
        # And the operation's delivery list has it ticked.
        self.browser(self.ops).post(f"/api/tasks/{self.task.code}/ack/")
        delivered = self.page(self.ops)["deliver"]["files"]
        self.assertTrue(any(f["final"] and f["name"] == row.original_name for f in delivered))

    def test_his_own_corrected_file_goes_on_instead(self):
        row, _ = self.translate()
        message, error = services.upload_reviewed(
            self.task, self.lead, [SimpleUploadedFile("fixed.docx", b"fixed", content_type="application/octet-stream")],
        )
        self.assertEqual(error, "")
        self.assertTrue(self.review()["ok"])
        self.task.refresh_from_db()
        names = [a.original_name for a in services.final_files(self.task)]
        self.assertEqual(names, ["fixed.docx"])
        self.assertFalse(ChatAttachment.objects.filter(file=row.file.name).exists())

    def test_a_second_press_does_not_post_it_twice(self):
        row, _ = self.translate()
        self.review()
        self.review()
        room = services.pair_room(self.lead, self.ops)
        self.assertEqual(
            ChatAttachment.objects.filter(message__room=room, message__reviewed_version=True, file=row.file.name).count(), 1,
        )

    def test_it_cannot_be_sent_back_to_a_translator_who_does_not_exist(self):
        self.translate()
        response = self.browser(self.lead).post(f"/api/tasks/{self.task.code}/return/", {"reason": "redo"})
        self.assertFalse(_json(response)["ok"])
        self.task.refresh_from_db()
        self.assertEqual(self.task.status, TaskStatus.UNDER_REVIEW)


class FileAccessTests(_AiTask):
    def test_who_may_open_the_ai_file(self):
        row, _ = self.translate()
        self.assertTrue(files.may_open(self.lead, row.file.name)[0])
        self.assertTrue(files.may_open(self.ops, row.file.name)[0])
        self.assertTrue(files.may_open(self.admin, row.file.name)[0])
        self.assertFalse(files.may_open(self.other_lead, row.file.name)[0])
        self.assertFalse(files.may_open(self.translator, row.file.name)[0])

    def test_the_page_answers_with_a_link_that_opens(self):
        self.translate()
        url = self.page()["files"]["ai"][0]["url"]
        self.assertEqual(self.browser(self.lead).get(url).status_code, 200)
        self.assertEqual(self.browser(self.other_lead).get(url).status_code, 404)


class PiecesTests(TestCase):
    def test_right_to_left_languages(self):
        for value in ("AR", "ar", "Arabic", "عربي", "FA", "Urdu"):
            self.assertTrue(ai_translate.is_rtl(value), value)
        for value in ("EN", "French", "", "DE"):
            self.assertFalse(ai_translate.is_rtl(value), value)

    def _document(self, text, rtl=False):
        with zipfile.ZipFile(io.BytesIO(ai_translate.docx_bytes(text, rtl=rtl))) as archive:
            return archive.read("word/document.xml").decode("utf-8")

    def test_the_word_file_keeps_lines_and_tabs(self):
        raw = ai_translate.docx_bytes("one\ttwo\n\nthree", rtl=False)
        self.assertEqual(ai._docx_text(raw).split("\n")[:2], ["one\ttwo", "three"])
        self.assertNotIn("<w:bidi/>", self._document("one"))

    def test_the_layout_headings_bold_and_lists(self):
        from xml.dom import minidom

        xml = self._document("# Lease contract\n## Article 1\nThe **tenant** pays.\n- first\n* second\n1. numbered")
        minidom.parseString(xml)  # a file Word can open is well-formed XML first
        # A heading is bold, larger and kept with what follows, without the marks.
        self.assertIn("<w:keepNext/>", xml)
        self.assertIn('<w:sz w:val="36"/>', xml)
        self.assertIn('<w:sz w:val="30"/>', xml)
        self.assertNotIn("#", xml.split("<w:body>")[1])
        self.assertNotIn("**", xml)
        # The bold words are their own bold run, and the rest is not bold.
        self.assertIn('<w:b/><w:bCs/><w:sz w:val="24"/><w:szCs w:val="24"/></w:rPr><w:t xml:space="preserve">tenant</w:t>', xml)
        self.assertIn('<w:sz w:val="24"/><w:szCs w:val="24"/></w:rPr><w:t xml:space="preserve">The </w:t>', xml)
        self.assertIn("\u2022 first", xml)
        self.assertIn("\u2022 second", xml)
        self.assertIn("1. numbered", xml)
        self.assertIn('w:ascii="Arial"', xml)

    def test_the_layout_tables_and_pages(self):
        from xml.dom import minidom

        text = "Before\n| Name | Amount |\n|---|---:|\n| Rent | 1,000 |\n| Tax |\n---\nAfter"
        xml = self._document(text, rtl=True)
        minidom.parseString(xml)
        self.assertEqual(xml.count("<w:tbl>"), 1)
        self.assertEqual(xml.count("<w:tr>"), 3)
        # The header row repeats on each page; a short row is padded to the table's width.
        self.assertEqual(xml.count("<w:tblHeader/>"), 1)
        self.assertEqual(xml.count("<w:tc>"), 6)
        self.assertNotIn("---", xml)
        self.assertIn("<w:bidiVisual/>", xml)
        self.assertIn('<w:br w:type="page"/>', xml)
        self.assertIn("<w:insideV ", xml)
        # Right to left: the paragraphs, the runs and the page.
        self.assertIn("<w:bidi/>", xml)
        self.assertIn("<w:rtl/>", xml)
        self.assertIn('<w:pgSz w:w="11906" w:h="16838"/>', xml)
        lines = ai._docx_text(ai_translate.docx_bytes(text)).split("\n")
        self.assertEqual(lines[:5], ["Before", "Name", "Amount", "Rent", "1,000"])

    def test_code_fences_are_left_out(self):
        self.assertNotIn("```", self._document("```\nText\n```"))

    def test_the_stream_is_read_to_its_end(self):
        events = [
            b'event: message_start\n', b'data: {"type": "message_start", "message": {}}\n', b'\n',
            b'data: {"type": "content_block_delta", "index": 0, "delta": {"type": "thinking_delta", "thinking": "hidden"}}\n',
            'data: {"type": "content_block_delta", "index": 1, "delta": {"type": "text_delta", "text": "مرحبا "}}\n'.encode(),
            b'data: {"type": "content_block_delta", "index": 1, "delta": {"type": "text_delta", "text": "world"}}\n',
            b'data: {"type": "message_delta", "delta": {"stop_reason": "max_tokens"}}\n',
            b'data: {"type": "message_stop"}\n',
        ]
        response = mock.MagicMock()
        response.__enter__.return_value = iter(events)
        conf = AppSettings.load()
        with mock.patch.object(ai_translate.net, "urlopen", return_value=response) as opened:
            text, stop = ai_translate.stream_text(conf, "system", "prompt", [])
        self.assertEqual((text, stop), ("مرحبا world", "max_tokens"))
        sent = json.loads(opened.call_args.args[0].data.decode("utf-8"))
        self.assertTrue(sent["stream"])
        self.assertEqual(sent["max_tokens"], ai_translate.MAX_TOKENS)

    def test_an_error_event_is_a_failure(self):
        response = mock.MagicMock()
        response.__enter__.return_value = iter([b'data: {"type": "error", "error": {"type": "overloaded_error"}}\n'])
        with mock.patch.object(ai_translate.net, "urlopen", return_value=response):
            with self.assertRaises(RuntimeError):
                ai_translate.stream_text(AppSettings.load(), "s", "p", [])
