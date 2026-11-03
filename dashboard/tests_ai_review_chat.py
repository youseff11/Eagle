"""«مراجعة بالـAI» as a chat with sessions (03/11/2026).

What these tests hold:

- the page is the leader's and the admin's; a session is its owner's alone (another person's, the admin's included, is a 404);
- a line opens a session or goes on in one, stored with the AI's answer pending, one answer at a time per session and three at a time per
  person; what is refused is refused with a reason and writes nothing;
- the AI is given the talk so far and the files (newest first, as far as one request holds, the rest only named) and answers into the
  session; a failed answer is asked again with the files that were kept; a pending row a dead process left is closed;
- a session is deleted with its files, but not while the AI is answering in it; a stored file opens for its owner and nobody else;
- the reviews of the old form became sessions.
"""

import importlib
import json
from datetime import timedelta
from unittest import mock

from django.apps import apps
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import Client as DjangoClient
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from . import doc_review, files
from .models import AIReviewFile, AIReviewMessage, AIReviewSession, AppSettings, ClaudeUsage, DocumentCheck, Notification, Role, User

BOARD = "dashboard:v1_ai_review"
SEND = "dashboard:v1_ai_review_send"
DETAIL = "dashboard:v1_ai_review_detail"
RETRY = "dashboard:v1_ai_review_retry"
DELETE = "dashboard:v1_ai_review_delete"
PNG = b"\x89PNG\r\n\x1a\n" + b"0" * 32


def _json(response):
    return json.loads(response.content.decode("utf-8"))


def _png(name="page.png"):
    return SimpleUploadedFile(name, PNG, content_type="image/png")


def _txt(name, text):
    return SimpleUploadedFile(name, text.encode("utf-8"), content_type="text/plain")


class _Review(TestCase):
    def setUp(self):
        make = lambda name, role, **kw: User.objects.create_user(name, password="x", role=role, **kw)
        self.lead = make("lead_rv", Role.TEAM_LEAD)
        self.other_lead = make("lead_rv_two", Role.TEAM_LEAD)
        self.admin = make("admin_rv", Role.ADMIN)
        self.ops = make("ops_rv", Role.OPERATION)
        self.translator = make("tr_rv", Role.TRANSLATOR, team_lead=self.lead)
        conf = AppSettings.load()
        conf.ai_check_enabled = True
        conf.claude_api_key = "test-key"
        conf.save()

    def browser(self, user):
        browser = DjangoClient()
        browser.force_login(user)
        return browser

    def board(self, user=None):
        return self.browser(user or self.lead).get(reverse(BOARD))

    def read(self, pk, user=None):
        return self.browser(user or self.lead).get(reverse(DETAIL, args=[pk]))

    def write(self, text="", uploads=(), labels=(), session=None, user=None):
        body = {"text": text}
        if uploads:
            body["files"] = list(uploads)
        if labels:
            body["labels"] = list(labels)
        if session is not None:
            body["session"] = str(session)
        return self.browser(user or self.lead).post(reverse(SEND), body)

    def answer(self, text="الجواب", fail=None):
        """Let the thread's work run here, with the model answering ``text`` (or raising ``fail``)."""
        pending = AIReviewMessage.objects.filter(status="pending").latest("id")
        model = mock.patch.object(doc_review, "call", side_effect=fail) if fail else mock.patch.object(doc_review, "call", return_value=text)
        with model as call:
            doc_review.finish(pending.pk)
        return call


class AccessTests(_Review):
    def test_the_operation_and_a_translator_do_not_get_it(self):
        for who in (self.ops, self.translator):
            self.assertEqual(self.board(who).status_code, 403)
            self.assertEqual(self.write("hi", user=who).status_code, 403)
        self.assertFalse(AIReviewSession.objects.exists())

    def test_nobody_signed_out_gets_it(self):
        self.assertEqual(DjangoClient().get(reverse(BOARD)).status_code, 401)

    def test_a_session_is_its_owners_alone(self):
        session = _json(self.write("سؤال"))["session"]["id"]
        for who in (self.other_lead, self.admin):
            self.assertEqual(self.read(session, who).status_code, 404)
            self.assertEqual(self.browser(who).post(reverse(DELETE, args=[session])).status_code, 404)
            self.assertEqual(self.browser(who).post(reverse(RETRY, args=[session])).status_code, 404)
            self.assertEqual(self.write("ادخل", session=session, user=who).status_code, 404)
            self.assertEqual(_json(self.board(who))["sessions"], [])
        self.assertEqual(AIReviewMessage.objects.filter(role="user").count(), 1)

    def test_the_admin_has_sessions_of_their_own(self):
        self.assertEqual(self.write("hi", user=self.admin).status_code, 200)
        self.assertEqual(AIReviewSession.objects.get().owner, self.admin)

    def test_switched_off_it_says_so(self):
        conf = AppSettings.load()
        conf.ai_check_enabled = False
        conf.save()
        self.assertFalse(_json(self.board())["available"])
        refused = self.write("hi")
        self.assertEqual(refused.status_code, 400)
        self.assertEqual(_json(refused)["code"], "unavailable")
        self.assertFalse(AIReviewSession.objects.exists())

    def test_the_board_lists_the_persons_sessions_newest_first(self):
        first = _json(self.write("الأولى"))["session"]["id"]
        AIReviewMessage.objects.filter(status="pending").update(status="done", body="ok")
        second = _json(self.write("التانية"))["session"]["id"]
        data = _json(self.board())
        self.assertEqual([one["id"] for one in data["sessions"]], [second, first])
        self.assertEqual([one["pending"] for one in data["sessions"]], [True, False])
        self.assertEqual(data["limits"]["files"], doc_review.MAX_FILES)


class SendingTests(_Review):
    def test_a_line_opens_a_session_with_the_answer_pending(self):
        response = self.write("راجع الترجمة دي")
        self.assertEqual(response.status_code, 200)
        data = _json(response)
        self.assertEqual(data["session"]["title"], "راجع الترجمة دي")
        self.assertTrue(data["session"]["pending"])
        self.assertEqual([(m["role"], m["status"]) for m in data["messages"]], [("user", "done"), ("assistant", "pending")])
        self.assertEqual(data["messages"][0]["body"], "راجع الترجمة دي")

    def test_a_line_of_only_files_is_titled_by_the_first_file(self):
        data = _json(self.write("", [_txt("contract.txt", "Hello")]))
        self.assertEqual(data["session"]["title"], "contract.txt")

    def test_files_are_kept_with_their_label_and_open_by_a_link(self):
        data = _json(self.write(
            "قارن", [_txt("a.txt", "Hello"), _txt("b.txt", "مرحبا"), _png("c.png")], ["source", "translation", "junk"],
        ))
        shown = data["messages"][0]["files"]
        self.assertEqual([(f["name"], f["label"]) for f in shown], [("a.txt", "source"), ("b.txt", "translation"), ("c.png", "other")])
        self.assertTrue(all(f["url"].startswith("/files/aireview/") for f in shown))
        self.assertEqual([f["image"] for f in shown], [False, False, True])

    def test_the_line_goes_on_in_the_same_session(self):
        session = _json(self.write("one"))["session"]["id"]
        self.answer("first")
        data = _json(self.write("two", session=session))
        self.assertEqual(data["session"]["id"], session)
        self.assertEqual([m["body"] for m in data["messages"]], ["one", "first", "two", ""])
        self.assertEqual(AIReviewSession.objects.count(), 1)

    def test_nothing_goes_while_an_answer_is_being_written_in_that_session(self):
        session = _json(self.write("one"))["session"]["id"]
        refused = self.write("two", session=session)
        self.assertEqual(refused.status_code, 400)
        self.assertEqual(_json(refused)["code"], "busy")
        self.assertEqual(AIReviewMessage.objects.filter(role="user").count(), 1)

    def test_another_session_is_not_blocked_by_it(self):
        self.write("one")
        self.assertEqual(self.write("two").status_code, 200)
        self.assertEqual(AIReviewSession.objects.count(), 2)

    def test_only_three_answers_at_a_time(self):
        for place in range(doc_review.MAX_PARALLEL):
            self.assertEqual(self.write(f"s{place}").status_code, 200)
        refused = self.write("one more")
        self.assertEqual(_json(refused)["code"], "too_busy")
        self.assertEqual(AIReviewSession.objects.count(), doc_review.MAX_PARALLEL)

    def test_refusals_say_why_and_write_nothing(self):
        cases = {
            "empty": self.write("   "),
            "text_too_long": self.write("x" * (doc_review.MAX_TEXT + 1)),
            "file_unreadable": self.write("look", [SimpleUploadedFile("sheet.xlsx", b"PK")]),
            "file_too_big": self.write("look", [SimpleUploadedFile("big.png", b"0" * (doc_review.MAX_FILE_BYTES + 1))]),
            "too_many_files": self.write("look", [_txt(f"f{n}.txt", "x") for n in range(doc_review.MAX_FILES + 1)]),
        }
        with mock.patch.object(doc_review, "MAX_MESSAGE_BYTES", 10):
            cases["message_too_big"] = self.write("look", [_txt("a.txt", "x" * 6), _txt("b.txt", "y" * 6)])
        for code, response in cases.items():
            self.assertEqual(response.status_code, 400, code)
            self.assertEqual(_json(response)["code"], code)
        self.assertFalse(AIReviewSession.objects.exists())
        self.assertFalse(AIReviewFile.objects.exists())

    def test_a_line_may_carry_as_many_files_as_the_limit_says(self):
        response = self.write("ten at once", [_txt(f"f{n}.txt", f"words {n}") for n in range(doc_review.MAX_FILES)])
        self.assertEqual(response.status_code, 200)
        self.assertGreaterEqual(doc_review.MAX_FILES, 30)
        self.assertEqual(AIReviewFile.objects.count(), doc_review.MAX_FILES)

    def test_the_chat_call_asks_for_the_cache_and_a_review_call_does_not(self):
        self.write("hi")
        with mock.patch.object(doc_review.ai, "stream_messages", return_value=("ok", "end_turn")) as stream:
            doc_review.finish(AIReviewMessage.objects.get(status="pending").pk)
        self.assertTrue(stream.call_args.kwargs["cache"])

    def test_a_session_is_capped(self):
        session = AIReviewSession.objects.create(owner=self.lead, title="full")
        for _ in range(doc_review.MAX_USER_MESSAGES):
            AIReviewMessage.objects.create(session=session, role="user", body="x")
        self.assertEqual(_json(self.write("one more", session=session.pk))["code"], "chat_full")

    def test_the_sessions_are_capped(self):
        AIReviewSession.objects.bulk_create([AIReviewSession(owner=self.lead, title="s") for _ in range(doc_review.MAX_SESSIONS)])
        self.assertEqual(_json(self.write("one more"))["code"], "too_many_sessions")

    def test_a_bad_session_id_is_refused(self):
        self.assertEqual(self.browser(self.lead).post(reverse(SEND), {"text": "hi", "session": "abc"}).status_code, 400)


class ContextTests(_Review):
    def test_the_ai_is_given_the_files_with_their_labels_and_the_words(self):
        self.write("راجع", [_txt("src.txt", "Hello world"), _txt("tr.txt", "مرحبا بالعالم")], ["source", "translation"])
        call = self.answer("تمام")
        messages = call.call_args.args[1]
        self.assertEqual([m["role"] for m in messages], ["user"])
        text = " ".join(block["text"] for block in messages[0]["content"] if block["type"] == "text")
        self.assertIn("=== SOURCE FILE: src.txt ===\nHello world", text)
        self.assertIn("=== TRANSLATION FILE: tr.txt ===\nمرحبا بالعالم", text)
        self.assertEqual(messages[0]["content"][-1], {"type": "text", "text": "راجع"})
        line = AIReviewMessage.objects.get(role="assistant")
        self.assertEqual((line.status, line.body), ("done", "تمام"))

    def test_a_picture_goes_to_the_model_as_a_picture(self):
        self.write("الصورة دي صح؟", [_png()])
        blocks = self.answer().call_args.args[1][-1]["content"]
        self.assertTrue(any(block["type"] == "image" and block["source"]["media_type"] == "image/png" for block in blocks))

    def test_the_second_question_carries_the_first_round_and_the_files(self):
        session = _json(self.write("one", [_txt("a.txt", "alpha words")]))["session"]["id"]
        self.answer("first answer")
        self.write("two", session=session)
        messages = self.answer("second answer").call_args.args[1]
        self.assertEqual([m["role"] for m in messages], ["user", "assistant", "user"])
        self.assertEqual(messages[1]["content"], "first answer")
        self.assertIn("alpha words", str(messages[0]["content"]))

    def test_a_failed_answer_is_not_part_of_the_next_talk(self):
        session = _json(self.write("one"))["session"]["id"]
        self.answer(fail=RuntimeError("down"))
        self.write("two", session=session)
        messages = self.answer().call_args.args[1]
        self.assertEqual([m["role"] for m in messages], ["user", "user"])

    def test_the_newest_files_are_sent_and_the_rest_only_named(self):
        session = _json(self.write("old", [_png(f"old{n}.png") for n in range(doc_review.ai.MAX_DOCUMENTS)]))["session"]["id"]
        self.answer("seen")
        self.write("new", [_png("new.png")], session=session)
        messages = self.answer().call_args.args[1]
        sent = [block for m in messages if m["role"] == "user" for block in m["content"] if block["type"] == "image"]
        self.assertEqual(len(sent), doc_review.ai.MAX_DOCUMENTS)
        self.assertIn("FILE: new.png", str(messages[-1]["content"]))
        # The newest file takes a slot, so the last of the old ones is the one that no longer fits.
        self.assertIn(f"old{doc_review.ai.MAX_DOCUMENTS - 1}.png: sent earlier, not shown now", str(messages[0]["content"]))

    def test_words_past_the_budget_are_cut_and_the_rest_named(self):
        self.write("go", [_txt("a.txt", "x" * 50), _txt("b.txt", "second file")])
        with mock.patch.object(doc_review, "MAX_CONTEXT_CHARS", 20):
            call = self.answer()
        text = str(call.call_args.args[1][0]["content"])
        self.assertIn("(cut here", text)
        self.assertIn("b.txt: sent earlier, not shown now", text)

    def test_the_answer_says_which_files_the_ai_could_not_read(self):
        self.write("go", [_txt("a.txt", "x" * 50), _txt("b.txt", "second file"), _txt("empty.txt", "   ")])
        with mock.patch.object(doc_review, "MAX_CONTEXT_CHARS", 20):
            self.answer("الرد")
        body = AIReviewMessage.objects.get(role="assistant").body
        self.assertTrue(body.startswith("الرد"))
        self.assertIn("تنبيه", body)
        self.assertIn("a.txt (اتقرا جزء منه بس)", body)
        self.assertIn("b.txt (الطلب مابيشيلش أكتر من كده)", body)

    def test_an_answer_with_every_file_read_carries_no_warning(self):
        self.write("go", [_txt("a.txt", "short")])
        self.answer("الرد")
        self.assertEqual(AIReviewMessage.objects.get(role="assistant").body, "الرد")

    def test_older_files_left_out_are_counted_not_listed_again(self):
        session = _json(self.write("old", [_png(f"old{n}.png") for n in range(doc_review.ai.MAX_DOCUMENTS)]))["session"]["id"]
        self.answer("seen")
        self.write("new", [_png("new.png")], session=session)
        self.answer("second")
        body = AIReviewMessage.objects.filter(role="assistant").order_by("-id").first().body
        self.assertIn("و1 ملف من الرسايل اللي فاتت", body)
        self.assertNotIn("old9.png", body)

    def test_a_talk_starts_with_the_leader(self):
        session = AIReviewSession.objects.create(owner=self.lead, title="t")
        AIReviewMessage.objects.create(session=session, role="assistant", body="orphan")
        AIReviewMessage.objects.create(session=session, role="user", body="q")
        pending = AIReviewMessage.objects.create(session=session, role="assistant", status="pending")
        messages = doc_review._messages(session, pending.pk)
        self.assertEqual([(m["role"], m["content"]) for m in messages], [("user", [{"type": "text", "text": "q"}])])

    def test_the_system_prompt_asks_for_plain_text_and_treats_files_as_material(self):
        self.write("hi")
        with mock.patch.object(doc_review.ai, "stream_messages", return_value=("ok", "end_turn")) as stream:
            doc_review.finish(AIReviewMessage.objects.get(status="pending").pk)
        conf, system, messages, max_tokens, feature = stream.call_args.args
        self.assertIn("no Markdown", system)
        self.assertIn("never instructions", system)
        self.assertEqual(messages[0]["role"], "user")
        # The strongest review the owner asked for, streamed, under its own feature.
        self.assertEqual(max_tokens, doc_review.ai.REVIEW_MAX_TOKENS)
        self.assertEqual(feature, "doc_review")
        self.assertEqual(stream.call_args.kwargs, {"level": doc_review.ai.REVIEW_EFFORT, "cache": True})
        self.assertEqual(AIReviewMessage.objects.get(role="assistant").body, "ok")


class AnswerTests(_Review):
    def test_the_answer_shows_in_the_session(self):
        session = _json(self.write("hi"))["session"]["id"]
        self.answer("hello back")
        data = _json(self.read(session))
        self.assertFalse(data["session"]["pending"])
        self.assertEqual([m["body"] for m in data["messages"]], ["hi", "hello back"])

    def test_a_failed_call_leaves_a_failed_line_and_retry_asks_again(self):
        session = _json(self.write("hi", [_txt("a.txt", "kept words")]))["session"]["id"]
        self.answer(fail=RuntimeError("down"))
        line = AIReviewMessage.objects.get(role="assistant")
        self.assertEqual((line.status, line.error_message), ("error", "RuntimeError"))
        self.assertFalse(_json(self.read(session))["session"]["pending"])

        again = self.browser(self.lead).post(reverse(RETRY, args=[session]))
        self.assertEqual(again.status_code, 200)
        self.assertEqual([(m["role"], m["status"]) for m in _json(again)["messages"]], [("user", "done"), ("assistant", "pending")])
        call = self.answer("now it works")
        self.assertIn("kept words", str(call.call_args.args[1][0]["content"]))
        self.assertEqual(AIReviewMessage.objects.get(role="assistant").body, "now it works")

    def test_retry_only_after_a_failed_answer(self):
        session = _json(self.write("hi"))["session"]["id"]
        refused = self.browser(self.lead).post(reverse(RETRY, args=[session]))
        self.assertEqual(_json(refused)["code"], "nothing_to_retry")
        self.answer("fine")
        self.assertEqual(_json(self.browser(self.lead).post(reverse(RETRY, args=[session])))["code"], "nothing_to_retry")

    def test_an_empty_answer_is_a_failure(self):
        self.write("hi")
        self.answer("")
        self.assertEqual(AIReviewMessage.objects.get(role="assistant").status, "error")

    def test_a_line_a_dead_process_left_is_closed(self):
        session = _json(self.write("hi"))["session"]["id"]
        AIReviewMessage.objects.update(created_at=timezone.now() - timedelta(minutes=doc_review.STALE_MINUTES + 1))
        data = _json(self.read(session))
        self.assertFalse(data["session"]["pending"])
        self.assertEqual(data["messages"][-1]["status"], "error")
        self.assertEqual(doc_review.close_stale(), 0)
        self.assertEqual(self.write("again", session=session).status_code, 200)

    def test_the_command_helper_closes_every_stale_answer(self):
        self.write("hi")
        AIReviewMessage.objects.update(created_at=timezone.now() - timedelta(minutes=doc_review.STALE_MINUTES + 1))
        self.assertEqual(doc_review.close_stale(), 1)

    def test_the_call_is_written_down_under_the_review_feature(self):
        events = [
            {"type": "message_start", "message": {"model": "claude-sonnet-4-5", "usage": {"input_tokens": 10}}},
            {"type": "content_block_delta", "delta": {"type": "text_delta", "text": "o"}},
            {"type": "content_block_delta", "delta": {"type": "text_delta", "text": "k"}},
            {"type": "message_delta", "delta": {"stop_reason": "end_turn"}, "usage": {"output_tokens": 5}},
        ]

        class Reply:
            def __enter__(self):
                return self

            def __exit__(self, *args):
                return False

            def __iter__(self):
                return iter([f"data: {json.dumps(event)}\n".encode("utf-8") for event in events])

        self.write("hi")
        with mock.patch.object(doc_review.ai.net, "urlopen", return_value=Reply()):
            doc_review.finish(AIReviewMessage.objects.get(status="pending").pk)
        self.assertEqual(AIReviewMessage.objects.get(role="assistant").body, "ok")
        self.assertTrue(ClaudeUsage.objects.filter(feature="doc_review").exists())

    def test_a_slow_answer_is_told_to_the_leader_and_a_quick_one_is_not(self):
        self.write("quick")
        self.answer("fast")
        self.assertFalse(Notification.objects.filter(user=self.lead).exists())
        session = _json(self.write("slow"))["session"]["id"]
        AIReviewMessage.objects.filter(status="pending").update(
            created_at=timezone.now() - timedelta(seconds=doc_review.NOTIFY_AFTER_SECONDS + 5),
        )
        self.answer("late")
        note = Notification.objects.get(user=self.lead)
        self.assertEqual(note.url, f"/app/lead/ai-review?s={session}")

    def test_the_session_moves_to_the_top_when_it_is_answered(self):
        first = _json(self.write("one"))["session"]["id"]
        self.answer("ok")
        second = _json(self.write("two"))["session"]["id"]
        self.answer("ok")
        self.assertEqual([s["id"] for s in _json(self.board())["sessions"]], [second, first])
        self.write("again", session=first)
        self.answer("ok")
        self.assertEqual([s["id"] for s in _json(self.board())["sessions"]], [first, second])


class DeleteTests(_Review):
    def test_a_session_goes_with_its_files(self):
        session = _json(self.write("hi", [_txt("a.txt", "words")]))["session"]["id"]
        self.answer("ok")
        row = AIReviewFile.objects.get()
        name = row.file.name
        self.assertTrue(row.file.storage.exists(name))
        self.assertEqual(self.browser(self.lead).post(reverse(DELETE, args=[session])).status_code, 200)
        self.assertFalse(AIReviewSession.objects.exists())
        self.assertFalse(AIReviewMessage.objects.exists())
        self.assertFalse(AIReviewFile.objects.exists())
        self.assertFalse(row.file.storage.exists(name))

    def test_not_while_the_ai_is_answering(self):
        session = _json(self.write("hi"))["session"]["id"]
        self.assertEqual(self.browser(self.lead).post(reverse(DELETE, args=[session])).status_code, 409)
        self.assertTrue(AIReviewSession.objects.filter(pk=session).exists())

    def test_a_row_a_dead_process_left_does_not_block_the_delete(self):
        session = _json(self.write("hi"))["session"]["id"]
        AIReviewMessage.objects.update(created_at=timezone.now() - timedelta(minutes=doc_review.STALE_MINUTES + 1))
        self.assertEqual(self.browser(self.lead).post(reverse(DELETE, args=[session])).status_code, 200)


class FileTests(_Review):
    def test_a_stored_file_opens_for_its_owner_and_nobody_else(self):
        self.write("look", [_png()])
        row = AIReviewFile.objects.get()
        self.assertTrue(files.may_open(self.lead, row.file.name)[0])
        for who in (self.admin, self.ops, self.other_lead, self.translator):
            self.assertFalse(files.may_open(who, row.file.name)[0], who.username)
        self.assertEqual(self.browser(self.lead).get(row.file.url).status_code, 200)
        self.assertEqual(self.browser(self.admin).get(row.file.url).status_code, 404)
        self.assertEqual(self.browser(self.ops).get(row.file.url).status_code, 404)

    def test_the_admin_opens_their_own(self):
        self.write("look", [_png()], user=self.admin)
        self.assertTrue(files.may_open(self.admin, AIReviewFile.objects.get().file.name)[0])


class OldReviewsTests(_Review):
    def test_the_old_reviews_became_sessions(self):
        issues = [{"severity": "high", "location": "p1", "source_excerpt": "ten", "translation_excerpt": "تسعة", "issue_ar": "رقم غلط", "correct_meaning_ar": "عشرة"}]
        DocumentCheck.objects.create(
            created_by=self.lead, status="issues", source_lang="EN", target_lang="AR", instructions="الأرقام",
            source_names=["src.docx"], target_names=["tr.docx"], summary="فيه غلط", issues=issues,
        )
        DocumentCheck.objects.create(created_by=self.lead, status="running", target_names=["x.docx"])
        DocumentCheck.objects.create(created_by=None, status="clean", target_names=["gone.docx"])
        migration = importlib.import_module("dashboard.migrations.0095_ai_review_chat")
        migration.convert_old_checks(apps, None)

        self.assertEqual(AIReviewSession.objects.count(), 2)
        first = AIReviewSession.objects.get(title="tr.docx")
        self.assertEqual(first.owner, self.lead)
        asked, answered = first.messages.all()
        self.assertIn("src.docx", asked.body)
        self.assertIn("الأرقام", asked.body)
        self.assertEqual(answered.status, "done")
        for part in ("فيه غلط", "1. [خطير] p1", "الأصل: «ten»", "الترجمة: «تسعة»", "الغلط: رقم غلط", "المعنى الصحيح: عشرة"):
            self.assertIn(part, answered.body)
        failed = AIReviewSession.objects.get(title="x.docx").messages.last()
        self.assertEqual(failed.status, "error")
        # What he reads on the page is what was converted.
        shown = _json(self.read(first.pk))
        self.assertEqual([m["role"] for m in shown["messages"]], ["user", "assistant"])
