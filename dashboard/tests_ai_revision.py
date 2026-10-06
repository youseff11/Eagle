"""The team leader accepts AI notes and a corrected copy of the translation is made.

What these tests hold: only the task's leader and the admin accept notes, and only notes of the latest check that exist; the ids are
places in the check (not places on the screen); the model is asked to apply the accepted notes and no other; what comes back is
written as a new Word file and the translator's own file is never touched; a copy that cannot be made says so instead of leaving a
broken file; and the file opens for the leader and the admin alone, through the one door every file goes through.
"""

import io
import json
import zipfile
from unittest import mock

from django.db import connection
from django.test import Client as DjangoClient
from django.test.utils import CaptureQueriesContext
from django.urls import reverse

from . import ai, files
from .models import AICheckResult, AIRevision, AppSettings, AuditLog, ChatAttachment, ChatMessage, Notification, User
from .tests_ai_notes import NOTES, _Notes, issue
from .tests_api_v1 import _json

REVISE = "dashboard:v1_ai_revise"


def _words(raw):
    return ai._docx_text(raw)


class _Revise(_Notes):
    def setUp(self):
        super().setUp()
        conf = AppSettings.load()
        conf.ai_check_enabled = True
        conf.claude_api_key = "sk-test"
        conf.save()
        self.three = [issue("first", "high"), issue("second", "low", location="page 9"), issue("third", "medium")]

    def post(self, user, body=None, raw=None, code=None):
        browser = DjangoClient()
        if user is not None:
            browser.force_login(user)
        if raw is None:
            body = dict(body if body is not None else {})
            latest = self.task.ai_checks.order_by("-created_at", "-id").first()
            # The box sends the check it showed; a test that is not about that sends the latest.
            body.setdefault("check", latest.pk if latest else 0)
        data = raw if raw is not None else json.dumps(body)
        return browser.post(reverse(REVISE, args=[code or self.task.code]), data=data, content_type="application/json")

    def accept(self, user, body=None, **kw):
        """Press the button without starting a real thread: the row is written and left running."""
        with mock.patch("dashboard.ai.threading.Thread") as thread:
            answer = self.post(user, body, **kw)
        return answer, thread

    def done_revision(self, check=None, accepted=(0,), text="corrected words"):
        check = check or self.check(self.three)
        row = AIRevision.objects.create(result=check, requested_by=self.lead, accepted=list(accepted))
        with mock.patch.object(ai, "collect_texts", return_value=("source", "translated words")), \
                mock.patch.object(ai, "collect_documents", return_value=([], [])), \
                mock.patch.object(ai, "_call_reviser", return_value=(text, "end_turn")):
            ai.finish_revision(row.pk)
        row.refresh_from_db()
        return row


class DoorTests(_Revise):
    def test_the_leader_of_the_task_and_the_admin_accept_notes(self):
        for user in (self.lead, self.admin):
            AIRevision.objects.all().delete()
            check = self.check(self.three)
            answer, thread = self.accept(user, {"issues": [0, 2]})
            self.assertEqual(answer.status_code, 200, user.username)
            self.assertEqual(answer["Cache-Control"], "private, no-store")
            row = AIRevision.objects.get(result=check)
            self.assertEqual((row.accepted, row.status, row.requested_by), ([0, 2], AIRevision.Status.RUNNING, user))
            self.assertTrue(thread.return_value.start.called)
            body = _json(answer)["revision"]
            self.assertEqual((body["status"], body["accepted"], body["file"]), ("running", [0, 2], None))
            self.assertTrue(AuditLog.objects.filter(actor=user, action="task.ai_revision", target=self.task.code).exists())
            AICheckResult.objects.all().delete()

    def test_nobody_else_accepts_and_nothing_is_written(self):
        self.check(self.three)
        for user in (self.ops, self.tr, self.hr, self.reviewer, self.accounting, self.sales):
            answer, thread = self.accept(user, {"all": True})
            self.assertEqual(answer.status_code, 403, user.username)
            self.assertFalse(thread.return_value.start.called)
        self.assertEqual(self.post(None, {"all": True}).status_code, 401)
        self.assertEqual(AIRevision.objects.count(), 0)

    def test_another_leaders_task_is_a_404_and_a_row_in_the_audit_log(self):
        self.check(self.three)
        answer, _thread = self.accept(self.other_lead, {"all": True})
        self.assertEqual(answer.status_code, 404)
        self.assertEqual(AIRevision.objects.count(), 0)
        self.assertTrue(AuditLog.objects.filter(actor=self.other_lead, action__startswith="security.denied").exists())

    def test_all_takes_every_note_and_the_ids_are_places_in_the_check(self):
        check = self.check(self.three)
        self.accept(self.lead, {"all": True})
        self.assertEqual(AIRevision.objects.get(result=check).accepted, [0, 1, 2])
        # The box lists most serious first, so the screen's order is not the check's: ``id`` is.
        body = self.notes()
        self.assertEqual([one["id"] for one in body["issues"]], [0, 2, 1])
        self.assertEqual([one["severity"] for one in body["issues"]], ["high", "medium", "low"])

    def test_ids_are_unique_sorted_and_must_be_notes_of_this_check(self):
        check = self.check(self.three)
        for bad in ([3], [-1], [True], ["0"], [1.5], [None], "0", 0, {"a": 1}, [0] * 101):
            answer, _thread = self.accept(self.lead, {"issues": bad})
            self.assertEqual(answer.status_code, 400, bad)
        self.assertEqual(AIRevision.objects.count(), 0)
        self.accept(self.lead, {"issues": [2, 0, 2, 0]})
        self.assertEqual(AIRevision.objects.get(result=check).accepted, [0, 2])

    def test_nothing_accepted_is_refused_in_words_and_all_must_be_the_true_flag(self):
        self.check(self.three)
        refused, _thread = self.accept(self.lead, {"issues": []})
        self.assertEqual((refused.status_code, _json(refused)["error"]), (400, "nothing_accepted"))
        for flag in ("true", 1, "all"):
            answer, _thread = self.accept(self.lead, {"all": flag})
            self.assertEqual(answer.status_code, 400, flag)
        self.assertEqual(AIRevision.objects.count(), 0)

    def test_a_body_that_is_not_json_or_not_an_object_is_refused(self):
        self.check(self.three)
        for raw in ("not json", "[1]", "5"):
            answer, _thread = self.accept(self.lead, raw=raw)
            self.assertEqual(answer.status_code, 400, raw)

    def test_a_check_with_no_notes_or_no_check_at_all_has_nothing_to_accept(self):
        answer, _thread = self.accept(self.lead, {"all": True})
        self.assertEqual((answer.status_code, _json(answer)["error"]), (400, "no_notes"))
        self.check([], status=AICheckResult.Status.CLEAN)
        answer, _thread = self.accept(self.lead, {"all": True})
        self.assertEqual((answer.status_code, _json(answer)["error"]), (400, "no_notes"))
        self.assertEqual(AIRevision.objects.count(), 0)

    def test_only_the_latest_check_can_be_accepted_from(self):
        old = self.check(self.three)
        new = self.check([issue("only one")])
        # Ids of the old check do not exist in the new one.
        answer, _thread = self.accept(self.lead, {"issues": [2]})
        self.assertEqual(answer.status_code, 400)
        self.accept(self.lead, {"issues": [0]})
        self.assertEqual(AIRevision.objects.get().result, new)
        self.assertNotEqual(old, new)

    def test_the_switch_being_off_or_no_key_is_refused(self):
        self.check(self.three)
        conf = AppSettings.load()
        conf.ai_check_enabled = False
        conf.save()
        answer, thread = self.accept(self.lead, {"all": True})
        self.assertEqual((answer.status_code, _json(answer)["error"]), (400, "off"))
        conf.ai_check_enabled, conf.claude_api_key = True, ""
        conf.save()
        answer, _thread = self.accept(self.lead, {"all": True})
        self.assertEqual((answer.status_code, _json(answer)["error"]), (400, "off"))
        self.assertFalse(thread.return_value.start.called)
        self.assertEqual(AIRevision.objects.count(), 0)

    def test_two_presses_make_one_copy(self):
        check = self.check(self.three)
        self.accept(self.lead, {"all": True})
        answer, _thread = self.accept(self.lead, {"all": True})
        self.assertEqual((answer.status_code, _json(answer)["error"]), (409, "running"))
        self.assertEqual(AIRevision.objects.filter(result=check).count(), 1)

    def test_a_finished_copy_does_not_stop_the_next(self):
        check = self.check(self.three)
        self.done_revision(check)
        answer, _thread = self.accept(self.lead, {"issues": [1]})
        self.assertEqual(answer.status_code, 200)
        self.assertEqual(AIRevision.objects.filter(result=check).count(), 2)

    def test_it_is_a_post_and_a_get_writes_nothing(self):
        self.check(self.three)
        browser = DjangoClient()
        browser.force_login(self.lead)
        self.assertEqual(browser.get(reverse(REVISE, args=[self.task.code])).status_code, 405)
        self.assertEqual(reverse(REVISE, args=["TSK-1"]), "/api/v1/tasks/TSK-1/ai-notes/revise/")
        self.assertEqual(AIRevision.objects.count(), 0)


class StuckCopyTests(_Revise):
    def stale(self, row):
        from datetime import timedelta

        from django.utils import timezone

        AIRevision.objects.filter(pk=row.pk).update(created_at=timezone.now() - timedelta(minutes=AIRevision.STALE_MINUTES + 1))
        row.refresh_from_db()
        return row

    def test_a_copy_left_running_by_a_dead_process_stops_blocking_and_stops_lying(self):
        check = self.check(self.three)
        row = self.stale(AIRevision.objects.create(result=check, requested_by=self.lead, accepted=[0]))
        self.assertTrue(row.is_stale)
        body = self.notes()
        self.assertTrue(body["can_revise"])
        self.assertEqual(body["revisions"][0]["status"], "error")
        self.assertTrue(body["revisions"][0]["error"])
        answer, thread = self.accept(self.lead, {"issues": [1]})
        self.assertEqual(answer.status_code, 200)
        self.assertTrue(thread.return_value.start.called)
        row.refresh_from_db()
        self.assertEqual(row.status, AIRevision.Status.ERROR)

    def test_a_young_running_copy_still_blocks_and_still_says_running(self):
        check = self.check(self.three)
        row = AIRevision.objects.create(result=check, requested_by=self.lead, accepted=[0])
        self.assertFalse(row.is_stale)
        body = self.notes()
        self.assertFalse(body["can_revise"])
        self.assertEqual(body["revisions"][0]["status"], "running")
        answer, _thread = self.accept(self.lead, {"issues": [1]})
        self.assertEqual(answer.status_code, 409)

    def test_the_finished_and_the_failed_are_never_stale(self):
        row = self.done_revision()
        self.assertFalse(self.stale(row).is_stale)

    def test_all_is_capped_at_the_most_one_copy_carries(self):
        check = self.check([issue(f"n{number}") for number in range(ai.MAX_ACCEPTED + 10)])
        self.accept(self.lead, {"all": True})
        self.assertEqual(len(AIRevision.objects.get(result=check).accepted), ai.MAX_ACCEPTED)


class WhichCheckTests(_Revise):
    def test_notes_ticked_on_an_older_check_are_not_applied_to_a_newer_one(self):
        old = self.check(self.three)
        self.check([issue("other one"), issue("other two"), issue("other three")])
        answer, thread = self.accept(self.lead, {"issues": [0, 2], "check": old.pk})
        self.assertEqual((answer.status_code, _json(answer)["error"]), (409, "stale_check"))
        self.assertFalse(thread.return_value.start.called)
        self.assertEqual(AIRevision.objects.count(), 0)

    def test_a_request_that_names_no_check_or_a_wrong_kind_is_refused(self):
        check = self.check(self.three)
        for body in ({"all": True}, {"all": True, "check": "1"}, {"all": True, "check": True}, {"all": True, "check": None}):
            answer, _thread = self.accept(self.lead, raw=json.dumps(body))
            self.assertEqual(answer.status_code, 400, body)
        self.assertEqual(AIRevision.objects.filter(result=check).count(), 0)

    def test_a_check_that_has_had_its_share_of_copies_is_run_again_instead(self):
        check = self.check(self.three)
        for _ in range(ai.MAX_REVISIONS_PER_CHECK):
            AIRevision.objects.create(result=check, status=AIRevision.Status.ERROR)
        answer, thread = self.accept(self.lead, {"all": True})
        self.assertEqual((answer.status_code, _json(answer)["error"]), (409, "limit"))
        self.assertFalse(thread.return_value.start.called)


class BoxTests(_Revise):
    def test_the_box_says_whether_a_copy_can_be_made_and_lists_the_copies(self):
        check = self.check(self.three)
        body = self.notes()
        self.assertTrue(body["can_revise"])
        self.assertEqual(body["revisions"], [])
        row = self.done_revision(check, accepted=(0, 1))
        body = self.notes(self.admin)
        self.assertTrue(body["can_revise"])
        listed = body["revisions"][0]
        self.assertEqual((listed["id"], listed["status"], listed["accepted"]), (row.pk, "done", [0, 1]))
        self.assertEqual(listed["file"]["name"], f"{self.task.code}-revised.docx")
        self.assertEqual(listed["file"]["url"], row.file.url)
        self.assertTrue(listed["file"]["url"].startswith("/files/revisions/"))

    def test_the_box_cannot_accept_while_a_copy_is_made_or_with_the_switch_off_or_a_clean_check(self):
        check = self.check(self.three)
        AIRevision.objects.create(result=check, requested_by=self.lead, accepted=[0])
        self.assertFalse(self.notes()["can_revise"])
        AIRevision.objects.all().delete()
        conf = AppSettings.load()
        conf.ai_check_enabled = False
        conf.save()
        self.assertFalse(self.notes()["can_revise"])
        conf.ai_check_enabled = True
        conf.save()
        self.check([], status=AICheckResult.Status.CLEAN)
        self.assertFalse(self.notes()["can_revise"])

    def test_a_failed_copy_shows_its_error_and_no_file(self):
        check = self.check(self.three)
        AIRevision.objects.create(result=check, status=AIRevision.Status.ERROR, error_message="The model returned nothing.")
        listed = self.notes()["revisions"][0]
        self.assertEqual((listed["status"], listed["file"]), ("error", None))
        self.assertEqual(listed["error"], "The model returned nothing.")

    def test_only_the_copies_of_the_latest_check_are_listed_and_a_few_of_them(self):
        old = self.check(self.three)
        self.done_revision(old)
        new = self.check(self.three)
        self.assertEqual(self.notes()["revisions"], [])
        for _ in range(8):
            AIRevision.objects.create(result=new, status=AIRevision.Status.ERROR)
        self.assertEqual(len(self.notes()["revisions"]), 5)

    def test_the_box_costs_the_same_queries_with_many_copies(self):
        check = self.check(self.three)

        def queries():
            with CaptureQueriesContext(connection) as captured:
                self.notes()
            return len(captured)

        before = queries()
        for _ in range(4):
            AIRevision.objects.create(result=check, status=AIRevision.Status.ERROR)
        self.assertLessEqual(queries(), before + 1)

    def test_the_notes_of_a_group_panel_carry_the_ids_too_and_the_translator_sees_neither(self):
        self.check(self.three)
        self.assertEqual(self.get(self.tr, NOTES, [self.task.code]).status_code, 403)


class MakingTests(_Revise):
    def run_revision(self, accepted, **patches):
        check = self.check(self.three)
        row = AIRevision.objects.create(result=check, requested_by=self.lead, accepted=list(accepted))
        prompts = []

        def reply(conf, prompt, documents=None):
            prompts.append(prompt)
            return patches.get("reply", ("The corrected translation.\nSecond paragraph.", "end_turn"))

        texts = patches.get("texts", ("the source", "the translated words"))
        with mock.patch.object(ai, "collect_texts", return_value=texts), \
                mock.patch.object(ai, "collect_documents", return_value=patches.get("docs", ([], []))), \
                mock.patch.object(ai, "_call_reviser", side_effect=reply) as reviser:
            result = ai.finish_revision(row.pk)
        row.refresh_from_db()
        return row, prompts, reviser, result

    def test_the_file_is_a_new_word_file_with_the_corrected_text(self):
        row, _prompts, _reviser, result = self.run_revision([0])
        self.assertEqual(result.pk, row.pk)
        self.assertEqual(row.status, AIRevision.Status.DONE)
        self.assertEqual(row.original_name, f"{self.task.code}-revised.docx")
        self.assertTrue(row.file.name.startswith("revisions/"), row.file.name)
        self.assertTrue(row.file.name.endswith(".docx"))
        self.assertEqual(row.size, row.file.size)
        self.assertNotIn(self.task.code, row.file.name)
        with row.file.open("rb") as handle:
            raw = handle.read()
        self.assertEqual(_words(raw).strip().split("\n"), ["The corrected translation.", "Second paragraph."])
        self.assertTrue(zipfile.is_zipfile(io.BytesIO(raw)))

    def test_the_model_is_asked_to_apply_the_accepted_notes_and_no_other(self):
        _row, prompts, _reviser, _result = self.run_revision([0, 2])
        self.assertEqual(len(prompts), 1)
        self.assertIn("first en", prompts[0])
        self.assertIn("third en", prompts[0])
        self.assertNotIn("second en", prompts[0])
        self.assertNotIn("page 9", prompts[0])
        self.assertIn("the translated words", prompts[0])
        # What it is told to do: only the list, never a free hand.
        self.assertIn("nothing else", ai.REVISE_PROMPT)

    def test_the_translators_own_file_and_the_chats_are_not_touched(self):
        before = (ChatAttachment.objects.count(), ChatMessage.objects.count())
        self.run_revision([0])
        self.assertEqual((ChatAttachment.objects.count(), ChatMessage.objects.count()), before)

    def test_who_asked_is_told_when_it_is_ready(self):
        row, _prompts, _reviser, _result = self.run_revision([0, 1])
        told = Notification.objects.get(user=self.lead, title_en="The corrected file is ready")
        self.assertIn("2", told.body_en)
        self.assertEqual(told.task, self.task)
        self.assertEqual(row.requested_by, self.lead)

    def test_a_model_that_fails_leaves_an_error_row_and_no_file_and_says_so(self):
        check = self.check(self.three)
        row = AIRevision.objects.create(result=check, requested_by=self.lead, accepted=[0])
        with mock.patch.object(ai, "collect_texts", return_value=("s", "t")), \
                mock.patch.object(ai, "collect_documents", return_value=([], [])), \
                mock.patch.object(ai, "_call_reviser", side_effect=RuntimeError("boom")):
            ai.finish_revision(row.pk)
        row.refresh_from_db()
        self.assertEqual((row.status, row.error_message, bool(row.file)), (AIRevision.Status.ERROR, "boom", False))
        self.assertTrue(Notification.objects.filter(user=self.lead, title_en="The corrected file was not made").exists())

    def test_an_answer_cut_short_or_empty_is_not_made_into_a_file(self):
        for reply, why in ((("half a transl", "max_tokens"), "cut short"), (("   ", "end_turn"), "nothing")):
            row, _prompts, _reviser, _result = self.run_revision([0], reply=reply)
            self.assertEqual(row.status, AIRevision.Status.ERROR, why)
            self.assertIn(why, row.error_message)
            self.assertFalse(row.file)

    def test_a_translation_too_long_for_one_go_is_refused_before_the_model_is_asked(self):
        row, _prompts, reviser, _result = self.run_revision([0], texts=("s", "x" * (ai.MAX_CHARS + 1)))
        self.assertEqual(row.status, AIRevision.Status.ERROR)
        self.assertIn("too long", row.error_message)
        reviser.assert_not_called()

    def test_no_translation_to_correct_is_an_error_and_not_a_file_of_the_notes(self):
        row, _prompts, reviser, _result = self.run_revision([0], texts=("s", "  "))
        self.assertEqual(row.status, AIRevision.Status.ERROR)
        reviser.assert_not_called()

    def test_a_pdf_translation_is_handed_over_whole(self):
        doc = {"name": "t.pdf", "media_type": "application/pdf", "data": b"%PDF-1.4 hello"}
        row, prompts, reviser, _result = self.run_revision([0], texts=("s", ""), docs=([], [doc]))
        self.assertEqual(row.status, AIRevision.Status.DONE)
        documents = reviser.call_args[0][2]
        self.assertEqual(len(documents), 2)
        self.assertIn("TRANSLATION", documents[0]["text"] if documents[0].get("type") == "text" else json.dumps(documents))
        self.assertIn("see the TRANSLATION files above", prompts[0])

    def test_a_row_that_dies_in_a_background_thread_ends_in_error_not_running_forever(self):
        check = self.check(self.three)
        row = AIRevision.objects.create(result=check, requested_by=self.lead, accepted=[0])
        with mock.patch.object(ai, "collect_texts", side_effect=RuntimeError("disk")):
            self.assertIsNone(ai.finish_revision(row.pk))
        row.refresh_from_db()
        self.assertEqual(row.status, AIRevision.Status.ERROR)
        self.assertEqual(row.error_message, "The file was not made.")

    def test_a_note_that_is_gone_from_the_check_is_skipped_not_a_crash(self):
        check = self.check([issue("only")])
        row = AIRevision.objects.create(result=check, requested_by=self.lead, accepted=[0, 5])
        with mock.patch.object(ai, "collect_texts", return_value=("s", "t")), \
                mock.patch.object(ai, "collect_documents", return_value=([], [])), \
                mock.patch.object(ai, "_call_reviser", return_value=("fixed", "end_turn")) as reviser:
            ai.finish_revision(row.pk)
        row.refresh_from_db()
        self.assertEqual(row.status, AIRevision.Status.DONE)
        self.assertIn("only en", reviser.call_args[0][1])


class DocxTests(_Revise):
    def test_a_word_file_holds_every_line_as_a_paragraph_and_reads_back(self):
        raw = ai.build_docx("one\ntwo & <three>\n\nfour")
        with zipfile.ZipFile(io.BytesIO(raw)) as archive:
            self.assertEqual(set(archive.namelist()), {"[Content_Types].xml", "_rels/.rels", "word/document.xml"})
            xml = archive.read("word/document.xml").decode("utf-8")
        self.assertEqual(xml.count("<w:p>"), 4)
        self.assertEqual(_words(raw).split("\n")[:4], ["one", "two & <three>".replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;"), "", "four"])

    def test_an_arabic_text_is_laid_out_right_to_left_and_an_english_one_is_not(self):
        arabic = zipfile.ZipFile(io.BytesIO(ai.build_docx("ترجمة عربية كاملة"))).read("word/document.xml").decode("utf-8")
        english = zipfile.ZipFile(io.BytesIO(ai.build_docx("A plain English text"))).read("word/document.xml").decode("utf-8")
        self.assertIn("<w:bidi/>", arabic)
        self.assertIn("<w:rtl/>", arabic)
        self.assertNotIn("<w:bidi/>", english)

    def test_characters_a_word_file_cannot_hold_are_dropped_not_written(self):
        raw = ai.build_docx("a" + chr(0) + "b" + chr(11) + "c\r\nd")
        xml = zipfile.ZipFile(io.BytesIO(raw)).read("word/document.xml").decode("utf-8")
        self.assertIn(">abc<", xml)
        self.assertEqual(xml.count("<w:p>"), 2)

    def test_the_accepted_ids_helper_is_strict(self):
        check = self.check([issue("a"), "not a note", issue("b")])
        self.assertEqual(ai.accepted_indexes(check, [2, 0]), [0, 2])
        self.assertIsNone(ai.accepted_indexes(check, [1]))
        self.assertIsNone(ai.accepted_indexes(check, [3]))
        self.assertIsNone(ai.accepted_indexes(check, None))


class FileDoorTests(_Revise):
    def open(self, user, row):
        browser = DjangoClient()
        if user is not None:
            browser.force_login(user)
        return browser.get(f"/files/{row.file.name}")

    def test_the_leader_of_the_task_and_the_admin_open_it_and_it_downloads_under_its_name(self):
        row = self.done_revision()
        for user in (self.lead, self.admin):
            answer = self.open(user, row)
            self.assertEqual(answer.status_code, 200, user.username)
            self.assertIn("attachment", answer["Content-Disposition"])
            self.assertIn(f"{self.task.code}-revised.docx", answer["Content-Disposition"])
            self.assertEqual(answer["X-Content-Type-Options"], "nosniff")
            self.assertTrue(files.may_open(user, row.file.name)[0])

    def test_nobody_else_opens_it_not_even_the_translator_whose_work_it_corrects(self):
        row = self.done_revision()
        for user in (self.tr, self.ops, self.hr, self.reviewer, self.accounting, self.sales, self.other_lead):
            self.assertEqual(self.open(user, row).status_code, 404, user.username)
            self.assertFalse(files.may_open(user, row.file.name)[0], user.username)
        # Not signed in: sent to the login page, never the file.
        self.assertEqual(self.open(None, row).status_code, 302)
        self.assertTrue(AuditLog.objects.filter(actor=self.tr, action__startswith="security.denied").exists())

    def test_a_leader_who_no_longer_leads_the_task_loses_the_file(self):
        row = self.done_revision()
        self.task.team_lead = self.other_lead
        self.task.save(update_fields=["team_lead"])
        self.assertEqual(self.open(self.lead, row).status_code, 404)
        self.assertEqual(self.open(self.other_lead, row).status_code, 200)

    def test_a_name_that_is_not_a_copy_is_not_opened_through_this_rule(self):
        self.done_revision()
        self.assertEqual(files.owner_of("revisions/2026/10/none.docx"), [])
        self.assertFalse(files.may_open(self.lead, "revisions/2026/10/none.docx")[0])
        # The admin may open a name no row owns, as for any other file.
        self.assertTrue(files.may_open(self.admin, "revisions/2026/10/none.docx")[0])
        self.assertFalse(files.may_open(self.lead, "../revisions/x")[0])

    def test_the_name_a_leader_is_given_is_the_copys_own_and_masks_nothing_of_the_task(self):
        row = self.done_revision()
        owner = files.owner_of(row.file.name)
        self.assertEqual([kind for kind, _row in owner], ["revision"])
        self.assertEqual(files.download_name(self.lead, row.file.name, owner[0]), f"{self.task.code}-revised.docx")


class StaleUserTests(_Revise):
    def test_a_switched_off_leader_opens_nothing(self):
        row = self.done_revision()
        User.objects.filter(pk=self.lead.pk).update(is_active=False)
        self.lead.refresh_from_db()
        self.assertFalse(files.may_open(self.lead, row.file.name)[0])
