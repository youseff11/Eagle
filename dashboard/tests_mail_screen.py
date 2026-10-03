"""The mailbox in the new app: the list of conversations, one conversation, and the mark that it was read.

The doors answer to the operation and the Sales people (each on their own line) and the admin, and show what the
classic pages show them, from the same functions: a letter that is not theirs - another line, the rate rule - is not
in the answer, and an id that names one is a 404 and a row in the audit log. A GET changes nothing; being read is a
POST of its own.
"""

import json
from datetime import timedelta

from django.core.files.base import ContentFile
from django.db import connection
from django.test import Client as DjangoClient
from django.test.utils import CaptureQueriesContext
from django.urls import reverse
from django.utils import timezone

from . import services
from .models import (
    AppSettings, AuditLog, Channel, Client, InboundMessage, MailRead, MessageAttachment, OutboundMessage, Role, Task,
)
from .tests_api_v1 import CLIENT_EMAIL, CLIENT_NAME, CLIENT_PHONE, IDENTITY_MARKERS, _json, _Site

LIST = "dashboard:v1_mail_threads"
THREAD = "dashboard:v1_mail_thread"
SEEN = "dashboard:v1_mail_thread_seen"


class _Mail(_Site):
    def setUp(self):
        super().setUp()
        now = timezone.now()
        self.first = self.letter("Quote for the lease", "Dear all, we need a quote", key="k1", at=now - timedelta(hours=5))
        self.second = self.letter("Re: Quote for the lease", "And a deadline of Friday", key="k1", at=now - timedelta(hours=4))
        self.single = self.letter("Another thing", "A separate letter", key="k2", at=now - timedelta(hours=1))

    def letter(self, subject, body, key="", at=None, client="default", **fields):
        count = InboundMessage.objects.count()
        return InboundMessage.objects.create(
            client=self.client_obj if client == "default" else client, channel=Channel.EMAIL, subject=subject, body=body,
            sender_identity=fields.pop("sender_identity", CLIENT_EMAIL), thread_key=key, external_id=f"<m{count}@mail.test>",
            received_at=at or timezone.now(), **fields,
        )

    def reply(self, key, body, by=None, at=None, status="sent", **fields):
        return OutboundMessage.objects.create(
            client=self.client_obj, channel=Channel.EMAIL, thread_key=key, body=body, created_by=by or self.ops,
            kind=OutboundMessage.Kind.CHAT, status=status, **fields,
        )

    def attach(self, message, name, content=b"x", size=10):
        return MessageAttachment.objects.create(message=message, file=ContentFile(content, name=name), original_name=name, size=size)

    def get(self, user, name, args=None, /, **query):
        browser = DjangoClient()
        if user is not None:
            browser.force_login(user)
        return browser.get(reverse(name, args=args), query)

    def post(self, user, name, args=None, /):
        browser = DjangoClient()
        if user is not None:
            browser.force_login(user)
        return browser.post(reverse(name, args=args))

    def rows(self, user=None, **query):
        return _json(self.get(user or self.ops, LIST, **query))["threads"]

    def thread(self, user=None, letter=None):
        return _json(self.get(user or self.ops, THREAD, [(letter or self.second).pk]))["thread"]


class MailListTests(_Mail):
    def test_the_operation_the_sales_and_the_admin_are_answered_everybody_else_is_refused(self):
        for user in (self.ops, self.sales, self.admin):
            self.assertEqual(self.get(user, LIST).status_code, 200, user.username)
        for user in (self.lead, self.tr, self.hr, self.reviewer, self.accounting):
            answer = self.get(user, LIST)
            self.assertEqual((answer.status_code, _json(answer)), (403, {"ok": False, "error": "forbidden"}), user.username)
        self.assertEqual(self.get(None, LIST).status_code, 401)
        self.assertEqual(self.post(self.ops, LIST).status_code, 405)
        self.assertEqual(self.get(self.ops, LIST)["Cache-Control"], "private, no-store")

    def test_one_row_for_a_conversation_the_newest_first_speaking_for_its_newest_letter(self):
        rows = self.rows()
        self.assertEqual([r["subject"] for r in rows], ["Another thing", "Quote for the lease"])
        talk = rows[1]
        self.assertEqual((talk["id"], talk["count"]), (self.second.pk, 2))
        self.assertEqual(talk["snippet"], "And a deadline of Friday")
        self.assertEqual((talk["from"], talk["code"]), (self.client_obj.code, self.client_obj.code))
        self.assertTrue(talk["at"]["ar"] and talk["at"]["en"])

    def test_our_replies_count_and_say_the_conversation_was_answered(self):
        self.reply("k1", "Here is the quote", at=timezone.now())
        talk = next(r for r in self.rows() if r["subject"] == "Quote for the lease")
        self.assertEqual((talk["count"], talk["answered"]), (3, True))
        other = next(r for r in self.rows() if r["subject"] == "Another thing")
        self.assertEqual((other["count"], other["answered"]), (1, False))

    def test_a_reply_that_did_not_go_does_not_make_it_answered(self):
        self.reply("k1", "Never sent", status="failed")
        talk = next(r for r in self.rows() if r["subject"] == "Quote for the lease")
        self.assertFalse(talk["answered"])

    def test_the_tasks_the_files_and_who_took_it(self):
        task = Task.objects.get(code=self.task.code)
        InboundMessage.objects.filter(pk=self.first.pk).update(task=task, claimed_by=self.ops)
        self.attach(self.first, "contract.pdf")
        self.attach(self.second, "annex.pdf")
        talk = next(r for r in self.rows() if r["subject"] == "Quote for the lease")
        self.assertEqual((talk["tasks"], talk["files"], talk["claimers"]), ([task.code], 2, [self.ops.short_name]))
        other = next(r for r in self.rows() if r["subject"] == "Another thing")
        self.assertEqual((other["tasks"], other["files"], other["claimers"]), ([], 0, []))

    def test_a_row_is_unread_until_the_person_has_opened_a_letter_in_it(self):
        self.assertEqual([r["unread"] for r in self.rows()], [True, True])
        self.post(self.ops, SEEN, [self.second.pk])
        by_subject = {r["subject"]: r["unread"] for r in self.rows()}
        self.assertEqual(by_subject, {"Another thing": True, "Quote for the lease": False})
        # Per person: the admin has opened nothing.
        self.assertEqual([r["unread"] for r in self.rows(self.admin)], [True, True])

    def test_a_search_finds_the_conversation_that_has_the_words_anywhere_in_it(self):
        self.assertEqual([r["subject"] for r in self.rows(q="Friday")], ["Quote for the lease"])
        self.assertEqual([r["subject"] for r in self.rows(q="separate")], ["Another thing"])
        self.assertEqual([r["subject"] for r in self.rows(q=self.client_obj.code)], ["Another thing", "Quote for the lease"])
        self.assertEqual(self.rows(q="nothing like it"), [])

    def test_the_senders_address_is_not_searchable_by_the_operation_and_is_by_the_admin(self):
        # Matching on it would answer "which code is this company".
        self.assertEqual(self.rows(q="acme-secret"), [])
        self.assertEqual(len(self.rows(self.admin, q="acme-secret")), 2)

    def test_the_filters(self):
        InboundMessage.objects.filter(pk=self.single.pk).update(claimed_by=self.ops)
        InboundMessage.objects.filter(pk=self.second.pk).update(task=Task.objects.get(code=self.task.code))
        self.assertEqual([r["subject"] for r in self.rows(state="unclaimed")], ["Quote for the lease"])
        self.assertEqual([r["subject"] for r in self.rows(state="mine")], ["Another thing"])
        self.assertEqual([r["subject"] for r in self.rows(state="notask")], ["Another thing", "Quote for the lease"])
        body = _json(self.get(self.ops, LIST, state="mine", q="separate"))
        self.assertEqual((body["state"], body["q"]), ("mine", "separate"))

    def test_a_filter_that_is_not_one_is_refused_and_is_not_an_empty_list(self):
        for query in ({"state": "evil"}, {"state": "UNCLAIMED"}, {"q": "x" * 201}, {"q": "a\x00b"}):
            answer = self.get(self.ops, LIST, **query)
            self.assertEqual((answer.status_code, _json(answer)), (400, {"ok": False, "error": "bad_filter"}), str(query)[:30])

    def test_the_two_numbers_over_the_list_answer_two_questions(self):
        body = _json(self.get(self.ops, LIST))
        self.assertEqual((body["unseen"], body["unclaimed"]), (2, 2))
        self.post(self.ops, SEEN, [self.second.pk])
        InboundMessage.objects.filter(pk=self.single.pk).update(claimed_by=self.ops)
        body = _json(self.get(self.ops, LIST))
        # Opened is not taken: one conversation fewer unseen, and still one unclaimed (the two letters of the first).
        self.assertEqual((body["unseen"], body["unclaimed"]), (1, 1))

    def test_the_rate_rule_hides_letters_from_the_operation_and_the_admin_is_told_how_many(self):
        self.letter("Price list", "Please quote a rate", key="k3", is_rate_blocked=True)
        self.assertNotIn("Price list", [r["subject"] for r in self.rows()])
        admin = _json(self.get(self.admin, LIST))
        self.assertIn("Price list", [r["subject"] for r in admin["threads"]])
        self.assertEqual(admin["blocked"], 1)
        self.assertEqual(_json(self.get(self.ops, LIST))["blocked"], 0)
        row = next(r for r in admin["threads"] if r["subject"] == "Price list")
        self.assertTrue(row["blocked"])

    def test_each_line_is_its_owners_alone(self):
        self.letter("On a sales line", "For the sales person only", key="k4", owner=self.sales)
        self.assertNotIn("On a sales line", [r["subject"] for r in self.rows()])
        self.assertEqual([r["subject"] for r in self.rows(self.sales)], ["On a sales line"])
        self.assertIn("On a sales line", [r["subject"] for r in self.rows(self.admin)])
        self.assertNotIn("Quote for the lease", [r["subject"] for r in self.rows(self.sales)])

    def test_the_operation_reads_a_code_and_never_the_name_the_number_or_the_address(self):
        raw = self.get(self.ops, LIST).content.decode("utf-8")
        for marker in IDENTITY_MARKERS + (CLIENT_NAME, CLIENT_PHONE, CLIENT_EMAIL):
            self.assertNotIn(marker, raw, marker)

    def test_a_letter_from_nobody_known_is_an_unknown_sender_and_only_the_admin_reads_the_address(self):
        self.letter("Who is this", "Hello", key="k5", client=None, sender_identity="stranger@elsewhere.test")
        row = next(r for r in self.rows() if r["subject"] == "Who is this")
        self.assertEqual((row["from"], row["code"]), ("", ""))
        self.assertNotIn("stranger@elsewhere.test", self.get(self.ops, LIST).content.decode("utf-8"))
        admin_row = next(r for r in self.rows(self.admin) if r["subject"] == "Who is this")
        self.assertEqual(admin_row["from"], "stranger@elsewhere.test")

    def test_the_mail_that_is_not_set_up_and_the_last_fetch(self):
        conf = AppSettings.load()
        mail = _json(self.get(self.ops, LIST))["mail"]
        self.assertEqual((mail["configured"], mail["last_fetch"], mail["last_count"], mail["last_error"]), (False, None, 0, ""))
        conf.imap_host, conf.imap_user, conf.imap_password = "imap.example.test", "mailbox", "secret"
        conf.mail_last_fetch_at, conf.mail_last_count = timezone.now(), 7
        conf.mail_last_error = f"login refused for {CLIENT_EMAIL}"
        conf.save()
        mail = _json(self.get(self.ops, LIST))["mail"]
        self.assertTrue(mail["configured"] and mail["last_fetch"]["ar"])
        self.assertEqual(mail["last_count"], 7)
        # The words of an error quote an address back: whoever may not know it does not read it.
        self.assertNotIn("acme-secret", mail["last_error"])
        self.assertIn("acme-secret", _json(self.get(self.admin, LIST))["mail"]["last_error"])
        # The password is not part of what the page is told.
        self.assertNotIn("secret", self.get(self.ops, LIST).content.decode("utf-8").replace("imap.example.test", ""))

    def test_the_page_and_the_door_list_the_same_conversations_in_the_same_order(self):
        for index in range(4):
            self.letter(f"More {index}", "x", key=f"extra{index}", at=timezone.now() - timedelta(minutes=index))
        listed = [r["subject"] for r in self.rows()]
        page = self.get(self.ops, "dashboard:ops_inbox", classic=1).content.decode("utf-8")
        positions = [page.index(subject) for subject in listed]
        self.assertEqual(positions, sorted(positions))

    def test_a_list_costs_the_same_queries_however_long_it_is(self):
        def cost():
            browser = DjangoClient()
            browser.force_login(self.ops)
            browser.get(reverse(LIST))
            with CaptureQueriesContext(connection) as queries:
                self.assertEqual(browser.get(reverse(LIST)).status_code, 200)
            return len(queries)

        # One conversation with a reply and a file to begin with: the queries that load them are there from the start.
        self.attach(self.first, "base.pdf")
        self.reply("k1", "base answer")
        few = cost()
        for index in range(12):
            message = self.letter(f"Bulk {index}", "x", key=f"bulk{index}")
            self.attach(message, f"f{index}.pdf")
            self.reply(f"bulk{index}", "answer")
        self.assertEqual(cost(), few)


class MailThreadTests(_Mail):
    def test_the_operation_the_sales_and_the_admin_are_answered_and_nobody_else(self):
        self.letter("Sales only", "mine", key="k6", owner=self.sales)
        sales_letter = InboundMessage.objects.get(subject="Sales only")
        for user, letter in ((self.ops, self.second), (self.sales, sales_letter), (self.admin, self.second)):
            self.assertEqual(self.get(user, THREAD, [letter.pk]).status_code, 200, user.username)
        for user in (self.lead, self.tr, self.hr, self.reviewer, self.accounting):
            self.assertEqual(self.get(user, THREAD, [self.second.pk]).status_code, 403, user.username)
        self.assertEqual(self.get(None, THREAD, [self.second.pk]).status_code, 401)
        self.assertEqual(self.post(self.ops, THREAD, [self.second.pk]).status_code, 405)

    def test_any_letter_opens_the_whole_conversation_oldest_first_with_our_replies_among_them(self):
        self.reply("k1", "Here is the quote", at=timezone.now())
        for letter in (self.first, self.second):
            thread = self.thread(letter=letter)
            self.assertEqual((thread["subject"], thread["count"]), ("Quote for the lease", 3))
            self.assertEqual([(e["kind"], e["id"]) for e in thread["entries"]][:2], [("in", self.first.pk), ("in", self.second.pk)])
            self.assertEqual(thread["entries"][2]["kind"], "out")

    def test_the_newest_entry_and_the_letter_the_link_named_start_open(self):
        thread = self.thread(letter=self.first)
        self.assertEqual([e["open"] for e in thread["entries"]], [True, True])
        self.reply("k1", "Our answer", at=timezone.now())
        thread = self.thread(letter=self.first)
        self.assertEqual([e["open"] for e in thread["entries"]], [True, False, True])

    def test_a_letter_with_no_conversation_key_is_a_conversation_of_its_own(self):
        loose = self.letter("Loose", "alone", key="")
        thread = self.thread(letter=loose)
        self.assertEqual((thread["subject"], thread["count"], len(thread["entries"])), ("Loose", 1, 1))

    def test_what_a_letter_carries(self):
        task = Task.objects.get(code=self.task.code)
        InboundMessage.objects.filter(pk=self.first.pk).update(task=task, claimed_by=self.ops)
        self.attach(self.first, "contract.pdf", size=2048)
        self.attach(self.first, "talk.ogg", size=5)
        thread = self.thread(letter=self.first)
        first = thread["entries"][0]
        self.assertEqual((first["task"], first["claimed_by"], first["blocked"]), (task.code, self.ops.short_name, False))
        self.assertEqual([(f["name"], f["size"], f["audio"]) for f in first["files"]], [("contract.pdf", "2.0 KB", False), ("talk.ogg", "5 B", True)])
        self.assertEqual(first["documents"], [first["files"][0]["id"]])
        self.assertEqual((first["body"], first["snippet"]), ("Dear all, we need a quote", "Dear all, we need a quote"))
        self.assertEqual(thread["tasks"], [task.code])

    def test_the_image_lines_a_mail_program_writes_are_taken_out_of_the_text(self):
        noisy = self.letter("Pictures", "See below\n[image: logo.png]\nThanks", key="k7")
        entry = self.thread(letter=noisy)["entries"][0]
        self.assertNotIn("[image", entry["body"])
        self.assertIn("See below", entry["body"])

    def test_received_and_convert_stand_for_work_on_a_document_the_client_sent(self):
        none = self.thread(letter=self.second)["entries"][1]
        self.assertEqual((none["can_confirm"], none["can_convert"]), (False, False))
        self.attach(self.second, "doc.pdf")
        has = self.thread(letter=self.second)["entries"][1]
        self.assertEqual((has["can_confirm"], has["can_convert"]), (True, True))
        # Only a voice note is not a document.
        voice = self.letter("Voice", "listen", key="k8")
        self.attach(voice, "note.ogg")
        self.assertEqual(self.thread(letter=voice)["entries"][0]["documents"], [])
        # Tasks are the operation's, not Sales': they can say received, not convert.
        InboundMessage.objects.filter(pk=self.second.pk).update(owner=self.sales)
        # (On their own line the letter stands alone: the first one is not theirs to read.)
        sales = self.thread(self.sales, self.second)["entries"][0]
        self.assertEqual((sales["can_confirm"], sales["can_convert"]), (True, False))
        # A letter already behind a task cannot be converted again.
        InboundMessage.objects.filter(pk=self.second.pk).update(owner=None, task=Task.objects.get(code=self.task.code))
        again = self.thread(letter=self.second)["entries"][1]
        self.assertEqual((again["can_confirm"], again["can_convert"]), (True, False))

    def test_the_conversation_can_be_answered_only_when_it_is_a_clients(self):
        self.assertTrue(self.thread()["can_reply"])
        stray = self.letter("Nobody", "who", key="k9", client=None, sender_identity="who@elsewhere.test")
        thread = self.thread(letter=stray)
        self.assertEqual((thread["can_reply"], thread["client"]), (False, None))

    def test_the_operation_reads_a_code_and_the_admin_the_name_beside_it(self):
        self.assertEqual(self.thread()["client"], self.client_obj.code)
        self.assertIn(CLIENT_NAME, self.thread(self.admin)["client"])
        raw = self.get(self.ops, THREAD, [self.second.pk]).content.decode("utf-8")
        for marker in IDENTITY_MARKERS + (CLIENT_NAME, CLIENT_PHONE, CLIENT_EMAIL):
            self.assertNotIn(marker, raw, marker)

    def test_the_raw_address_is_the_admins_alone(self):
        InboundMessage.objects.filter(pk=self.second.pk).update(sender_display="Mr Boss <boss@acme-secret.example>")
        self.assertEqual(self.thread()["entries"][1]["raw"], "")
        self.assertIn("acme-secret", self.thread(self.admin)["entries"][1]["raw"])

    def test_a_reply_that_did_not_go_says_so_and_why_without_the_address_for_the_operation(self):
        self.reply("k1", "Not delivered", status="failed", error_message=f"550 {CLIENT_EMAIL} refused")
        failed = [e for e in self.thread()["entries"] if e["kind"] == "out"][0]
        self.assertTrue(failed["failed"])
        self.assertNotIn("acme-secret", failed["error"])
        admin_failed = [e for e in self.thread(self.admin)["entries"] if e["kind"] == "out"][0]
        self.assertIn("acme-secret", admin_failed["error"])

    def test_a_reply_says_who_sent_it_and_what_it_carried(self):
        from .models import OutboundAttachment

        sent = self.reply("k1", "With a file", by=self.ops)
        OutboundAttachment.objects.create(message=sent, file=ContentFile(b"r", name="reply.pdf"), original_name="reply.pdf", size=3)
        out = [e for e in self.thread()["entries"] if e["kind"] == "out"][0]
        self.assertEqual((out["by"], out["body"], out["failed"], out["error"]), (self.ops.short_name, "With a file", False, ""))
        self.assertEqual([f["name"] for f in out["files"]], ["reply.pdf"])

    def test_a_letter_this_person_may_not_read_is_a_404_and_a_row_in_the_audit_log(self):
        blocked = self.letter("Rate talk", "RATE WORDS", key="k10", is_rate_blocked=True)
        on_sales_line = self.letter("Sales line", "SALES WORDS", key="k11", owner=self.sales)
        for letter, word in ((blocked, "RATE WORDS"), (on_sales_line, "SALES WORDS")):
            before = AuditLog.objects.filter(action="security.denied", actor=self.ops).count()
            answer = self.get(self.ops, THREAD, [letter.pk])
            self.assertEqual((answer.status_code, _json(answer)), (404, {"ok": False, "error": "not_found"}), word)
            self.assertNotIn(word.encode(), answer.content)
            self.assertEqual(AuditLog.objects.filter(action="security.denied", actor=self.ops).count(), before + 1, word)
        self.assertEqual(self.get(self.admin, THREAD, [blocked.pk]).status_code, 200)
        self.assertEqual(self.get(self.sales, THREAD, [self.second.pk]).status_code, 404)

    def test_a_whatsapp_message_is_not_a_mail_conversation_and_a_missing_one_is_a_404(self):
        chat = InboundMessage.objects.create(client=self.client_obj, channel=Channel.WHATSAPP, body="chat", sender_identity=CLIENT_PHONE)
        self.assertEqual(self.get(self.ops, THREAD, [chat.pk]).status_code, 404)
        self.assertEqual(self.get(self.ops, THREAD, [999999]).status_code, 404)

    def test_the_letters_this_person_may_not_read_are_not_in_a_conversation_they_may(self):
        self.letter("Re: Quote for the lease", "SECRET RATE REPLY", key="k1", is_rate_blocked=True)
        thread = self.thread()
        self.assertEqual(thread["count"], 2)
        self.assertNotIn("SECRET RATE REPLY", json.dumps(thread))
        self.assertTrue(self.thread(self.admin)["blocked"])
        self.assertEqual(self.thread(self.admin)["count"], 3)


class MailSeenTests(_Mail):
    def test_looking_changes_nothing(self):
        before = MailRead.objects.count()
        self.get(self.ops, THREAD, [self.second.pk])
        self.get(self.ops, THREAD, [self.first.pk])
        self.assertEqual(MailRead.objects.count(), before)
        self.assertEqual([e["unseen"] for e in self.thread()["entries"]], [True, True])

    def test_saying_the_conversation_was_read_marks_every_letter_in_it_and_the_badge_falls(self):
        answer = self.post(self.ops, SEEN, [self.second.pk])
        self.assertEqual((answer.status_code, _json(answer)), (200, {"ok": True, "marked": 2, "unseen": 1}))
        self.assertEqual([e["unseen"] for e in self.thread()["entries"]], [False, False])
        self.assertEqual(services.unseen_conversation_count(self.ops), 1)
        # Again is nothing new, and another person has read nothing.
        self.assertEqual(_json(self.post(self.ops, SEEN, [self.first.pk]))["marked"], 0)
        self.assertEqual([e["unseen"] for e in self.thread(self.admin)["entries"]], [True, True])

    def test_it_is_a_post_by_those_who_may_read_the_conversation_and_nobody_else(self):
        self.assertEqual(self.get(self.ops, SEEN, [self.second.pk]).status_code, 405)
        self.assertEqual(self.post(self.tr, SEEN, [self.second.pk]).status_code, 403)
        self.assertEqual(self.post(None, SEEN, [self.second.pk]).status_code, 401)
        # A letter of another line is a 404, and nothing is marked.
        sales_letter = self.letter("Sales only", "mine", key="k12", owner=self.sales)
        before = MailRead.objects.count()
        self.assertEqual(self.post(self.ops, SEEN, [sales_letter.pk]).status_code, 404)
        self.assertEqual(MailRead.objects.count(), before)

    def test_the_classic_page_still_marks_it_read_when_it_is_opened(self):
        browser = DjangoClient()
        browser.force_login(self.ops)
        self.assertEqual(browser.get(reverse("dashboard:ops_mail_thread", args=[self.second.pk]) + "?classic=1").status_code, 200)
        self.assertEqual(MailRead.objects.filter(user=self.ops).count(), 2)


class MailHandOnTests(_Mail):
    """The classic mailbox pages go on to the new app with the operation's switch, keeping the list's filters."""

    def setUp(self):
        super().setUp()
        from unittest import mock

        # As if ``npm run build`` had run: a checkout that never built the app must not change what these say.
        built = mock.patch("dashboard.newui.spa.built_assets", return_value={"js": "x.js", "css": []})
        built.start()
        self.addCleanup(built.stop)

    def turn_on(self, roles=(), users=()):
        conf = AppSettings.load()
        conf.new_ui = {**(conf.new_ui or {}), "operation": {"roles": list(roles), "users": list(users)}}
        conf.save()

    def test_the_list_and_a_conversation_go_on_with_the_filters(self):
        self.turn_on(roles=["operation"])
        answer = self.get(self.ops, "dashboard:ops_inbox")
        self.assertEqual((answer.status_code, answer["Location"]), (302, "/app/inbox"))
        self.assertEqual(self.get(self.ops, "dashboard:ops_inbox", state="mine", q="lease")["Location"], "/app/inbox?state=mine&q=lease")
        answer = self.get(self.ops, "dashboard:ops_mail_thread", [self.second.pk], state="unclaimed", q="a b")
        self.assertEqual(answer["Location"], f"/app/inbox/thread/{self.second.pk}?state=unclaimed&q=a+b")

    def test_only_a_state_that_is_one_and_a_short_search_go_along(self):
        self.turn_on(roles=["operation"])
        self.assertEqual(self.get(self.ops, "dashboard:ops_inbox", state="evil")["Location"], "/app/inbox")
        self.assertEqual(self.get(self.ops, "dashboard:ops_inbox", q="x" * 201)["Location"], "/app/inbox")
        self.assertEqual(self.get(self.ops, "dashboard:ops_inbox", state="mine&x=1")["Location"], "/app/inbox")
        self.assertEqual(self.get(self.ops, "dashboard:ops_inbox", q="a&x=1")["Location"], "/app/inbox?q=a%26x%3D1")

    def test_the_operation_without_the_switch_and_the_classic_name_keep_the_classic_pages(self):
        self.assertEqual(self.get(self.ops, "dashboard:ops_inbox").status_code, 200)
        self.assertEqual(self.get(self.ops, "dashboard:ops_mail_thread", [self.second.pk]).status_code, 200)
        self.turn_on(roles=["operation"])
        self.assertEqual(self.get(self.ops, "dashboard:ops_inbox", classic=1).status_code, 200)
        self.assertEqual(self.get(self.ops, "dashboard:ops_mail_thread", [self.second.pk], classic=1).status_code, 200)

    def test_the_admin_is_on_by_default_and_the_sales_stay_on_the_classic_page_even_when_named(self):
        self.assertEqual(self.get(self.admin, "dashboard:ops_inbox")["Location"], "/app/inbox")
        self.assertEqual(self.get(self.sales, "dashboard:ops_inbox").status_code, 200)
        # The screen is the operation's: the Sales have no pages of their own in the new app yet.
        self.turn_on(users=[self.sales.pk])
        self.assertEqual(self.get(self.sales, "dashboard:ops_inbox").status_code, 200)

    def test_a_conversation_that_is_not_theirs_is_still_not_found_and_not_handed_on_to_open(self):
        self.turn_on(roles=["operation"])
        sales_letter = self.letter("Sales only", "mine", key="k13", owner=self.sales)
        # The hand-on is only an address: the new page asks the door, which answers 404 for it.
        self.assertEqual(self.get(self.ops, "dashboard:ops_mail_thread", [sales_letter.pk]).status_code, 302)
        self.assertEqual(self.get(self.ops, THREAD, [sales_letter.pk]).status_code, 404)
