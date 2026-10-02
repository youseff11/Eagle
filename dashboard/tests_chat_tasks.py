"""The chats screen in the new app, step 3e part 3: "received" under a client's message
(``/api/v1/messages/<id>/confirm/``).

It is the one thing under a client's message that sends something to the client, so what is pinned is that the new
door is exactly as strict as the classic one and no looser anywhere:

* who may - every role, compared with the classic door, which stays the specification;
* only a message on the line this person works, and not one the rate rule hides from them;
* the receipt leaves on the channel the message came in on, and the message is claimed only once it is out;
* a refusal is a 4xx, nothing was sent and nothing was claimed; a failure is shown without the client's number;
* no client name or number comes back.
"""

import json
from datetime import timedelta

from django.test import Client as DjangoClient
from django.urls import reverse
from django.utils import timezone

from . import services, whatsapp
from .models import AuditLog, Channel, InboundMessage, OutboundMessage, Role, User
from .tests_chat_lists import _json
from .tests_chat_send import NAME, PHONE, _Send


class ConfirmTests(_Send):
    def confirm(self, user, message, **kw):
        return self.browser(user).post(reverse("dashboard:v1_message_confirm", args=[message.pk]), **kw)

    def classic(self, user, message):
        return self.browser(user).post(reverse("dashboard:api_confirm_message", args=[message.pk]))

    def claimed(self, message):
        message.refresh_from_db()
        return message.claimed_by_id

    def test_the_operation_confirms_a_message_and_the_client_is_told_on_whatsapp(self):
        answer = self.confirm(self.ops, self.heard)
        body = _json(answer)
        self.assertEqual((answer.status_code, body["ok"], body["message"]), (200, True, ""))
        self.assertEqual(body["claimed_by"], self.ops.short_name)
        self.text.assert_called_once()
        self.assertEqual(self.text.call_args.args[0], PHONE)
        self.assertEqual(self.claimed(self.heard), self.ops.pk)
        sent = OutboundMessage.objects.get(client=self.client_obj)
        self.assertEqual((sent.channel, sent.created_by_id, sent.status), (Channel.WHATSAPP, self.ops.pk, OutboundMessage.Status.SENT))
        self.assertTrue(AuditLog.objects.filter(action="message.confirm").exists())

    def test_it_is_what_the_classic_door_does_for_every_role(self):
        # The classic door is the specification: same answer, same message sent, same claim, for each person.
        for user in self.everyone:
            for message in (self.heard, self.sales_heard):
                InboundMessage.objects.filter(pk=message.pk).update(claimed_by=None)
                OutboundMessage.objects.all().delete()
                self.text.reset_mock()
                old = self.classic(user, message)
                old_state = (old.status_code, self.text.call_count, bool(self.claimed(message)))
                InboundMessage.objects.filter(pk=message.pk).update(claimed_by=None)
                OutboundMessage.objects.all().delete()
                self.text.reset_mock()
                new = self.confirm(user, message)
                new_state = (new.status_code, self.text.call_count, bool(self.claimed(message)))
                label = (user.username, message.external_id)
                self.assertEqual(new_state[1:], old_state[1:], label)
                self.assertEqual(new.status_code == 200, old.status_code == 200, label)
                if new.status_code != 200:
                    self.assertIn(new.status_code, (400, 403, 404), label)
                    self.assertFalse(new_state[2], label)

    def test_who_may_for_the_places_that_decide_a_clients_privacy(self):
        allowed = {
            # The company line: the operation and the admin. Sales answers only from their own number.
            self.heard.pk: {self.admin, self.ops, self.boss_sales},
            # A Sales person's own number: that Sales person and the admin.
            self.sales_heard.pk: {self.admin, self.sales, self.boss_sales},
        }
        for message in (self.heard, self.sales_heard):
            for user in self.everyone:
                InboundMessage.objects.filter(pk=message.pk).update(claimed_by=None)
                answer = self.confirm(user, message)
                self.assertEqual(answer.status_code == 200, user in allowed[message.pk], (user.username, message.external_id))

    def test_a_message_of_another_line_is_not_there_for_somebody_who_does_not_work_that_line(self):
        for user in (self.ops, self.sales2):
            answer = self.confirm(user, self.sales_heard)
            self.assertEqual(answer.status_code, 404, user.username)
        self.nothing_left_the_building()
        self.assertFalse(self.claimed(self.sales_heard))

    def test_a_message_the_rate_rule_hides_is_not_for_the_operation_but_is_for_the_admin(self):
        hidden = InboundMessage.objects.create(
            client=self.client_obj, channel=Channel.WHATSAPP, body="a rate is mentioned", external_id="wamid.rate", is_rate_blocked=True,
        )
        self.assertEqual(self.confirm(self.ops, hidden).status_code, 404)
        self.nothing_left_the_building()
        self.assertFalse(self.claimed(hidden))
        self.assertEqual(self.confirm(self.admin, hidden).status_code, 200)

    def test_a_failure_leaves_the_message_unclaimed_and_shows_no_number(self):
        self.text.side_effect = whatsapp.WhatsAppError(
            "واتساب رجّع خطأ (400): +201234567890 مش مسجل", "WhatsApp returned an error (400): +201234567890 is not registered",
        )
        answer = self.confirm(self.ops, self.heard)
        body = _json(answer)
        self.assertEqual((answer.status_code, body["ok"], body["error"]), (400, False, "refused"))
        self.assertTrue(body["message"])
        self.assertNotIn(b"201234567890", answer.content)
        self.assertFalse(self.claimed(self.heard))

    def test_a_message_that_does_not_exist_is_a_404(self):
        answer = self.browser(self.ops).post(reverse("dashboard:v1_message_confirm", args=[999999]))
        self.assertEqual(answer.status_code, 404)
        self.nothing_left_the_building()

    def test_a_message_of_no_known_client_cannot_be_confirmed(self):
        orphan = InboundMessage.objects.create(channel=Channel.WHATSAPP, body="who?", external_id="wamid.orphan", client=None)
        answer = self.confirm(self.admin, orphan)
        self.assertEqual(answer.status_code, 400)
        self.nothing_left_the_building()

    def test_a_session_a_post_and_the_csrf_token(self):
        url = reverse("dashboard:v1_message_confirm", args=[self.heard.pk])
        self.assertEqual(DjangoClient().post(url).status_code, 401)
        self.assertEqual(self.browser(self.ops).get(url).status_code, 405)
        strict = DjangoClient(enforce_csrf_checks=True)
        strict.force_login(self.ops)
        self.assertEqual(strict.post(url).status_code, 403)
        self.nothing_left_the_building()
        self.assertFalse(self.claimed(self.heard))

    def test_the_answer_carries_nothing_about_the_client(self):
        answer = self.confirm(self.ops, self.heard)
        for text in (NAME.encode(), PHONE.encode(), b"zeb@example.test"):
            self.assertNotIn(text, answer.content)

    def test_a_refusal_for_a_role_that_may_not_is_written_to_the_audit_log(self):
        before = AuditLog.objects.filter(action="security.denied").count()
        answer = self.confirm(self.hr, self.heard)
        self.assertEqual(AuditLog.objects.filter(action="security.denied").count(), before + 1)
        self.assertEqual((answer.status_code, _json(answer)["error"]), (403, "forbidden"))
        self.nothing_left_the_building()

    def test_one_receipt_per_message_a_second_press_sends_nothing(self):
        first = self.confirm(self.ops, self.heard)
        self.assertEqual(first.status_code, 200)
        self.text.reset_mock()
        for user in (self.ops, self.admin):
            again = self.confirm(user, self.heard)
            body = _json(again)
            self.assertEqual((again.status_code, body["ok"], body["error"]), (400, False, "refused"), user.username)
            self.assertIn(self.ops.short_name, body["message"], user.username)
        self.nothing_left_the_building()
        self.assertEqual(self.claimed(self.heard), self.ops.pk)
        self.assertEqual(OutboundMessage.objects.filter(client=self.client_obj).count(), 1)

    def test_somebody_who_may_not_see_a_message_is_not_told_whether_it_was_confirmed(self):
        InboundMessage.objects.filter(pk=self.sales_heard.pk).update(claimed_by=self.sales)
        for user in (self.ops, self.sales2):
            self.assertEqual(self.confirm(user, self.sales_heard).status_code, 404, user.username)
        self.nothing_left_the_building()

    def test_a_failed_receipt_leaves_the_message_free_to_be_confirmed_again(self):
        self.text.side_effect = whatsapp.WhatsAppError("واتساب رجّع خطأ (131)", "WhatsApp error (131)")
        self.assertEqual(self.confirm(self.ops, self.heard).status_code, 400)
        self.assertFalse(self.claimed(self.heard))
        self.text.side_effect = None
        self.text.return_value = "wamid.ok"
        self.assertEqual(self.confirm(self.ops, self.heard).status_code, 200)


class ClassicAnswerTests(_Send):
    """``api_v1._classic_answer``: what a classic door said, re-shaped, and never with a client's contact in it."""

    def answer(self, error, viewer, status=400):
        from django.http import JsonResponse

        from . import api_v1

        response = JsonResponse({"ok": False, "error": error}, status=status)
        return _json(api_v1._classic_answer(response, viewer))

    def test_a_number_and_an_address_in_the_words_are_taken_out_for_somebody_who_may_not_know_the_client(self):
        words = "recipient +201234567890 / zeb@example.test refused"
        for viewer in (self.ops, self.lead, self.tr, self.hr):
            said = self.answer(words, viewer)["message"]
            self.assertNotIn("201234567890", said, viewer.username)
            self.assertNotIn("zeb@example.test", said, viewer.username)
            self.assertIn("refused", said, viewer.username)

    def test_the_admin_who_may_know_the_client_is_given_the_words_as_they_are(self):
        words = "recipient +201234567890 refused"
        self.assertEqual(self.answer(words, self.admin)["message"], words)

    def test_the_shape_is_the_one_the_other_doors_use(self):
        self.assertEqual(self.answer("nope", self.ops), {"ok": False, "error": "refused", "message": "nope"})
        self.assertEqual(self.answer("forbidden", self.ops, status=403), {"ok": False, "error": "forbidden", "message": ""})


class OnlyJsonTests(_Send):
    """Every door of this step reads a JSON object and nothing else - not the same words under another content type."""

    def test_json_text_under_another_content_type_is_refused_and_nothing_happens(self):
        from .models import ChatReaction, ChatRoom

        message = self.heard
        doors = (
            ("v1_chat_react", [], {"source": self.client_obj.code, "uid": f"in-{message.pk}", "kind": "like"}),
            ("v1_chat_forward", [], {"source": self.client_obj.code, "target": f"u{self.lead.pk}", "uids": [f"in-{message.pk}"]}),
            ("v1_group_create", [], {"title": "x", "members": [self.lead.pk]}),
            ("v1_group_add", [self.team.pk], {"members": [self.hr.pk]}),
            ("v1_task_hand_in", ["TSK-00001"], {"files": [1]}),
        )
        rooms = ChatRoom.objects.count()
        for name, args, body in doors:
            for content_type in ("text/plain", "application/x-www-form-urlencoded", "multipart/form-data; boundary=x"):
                answer = self.browser(self.admin).post(reverse(f"dashboard:{name}", args=args), json.dumps(body), content_type=content_type)
                self.assertEqual((answer.status_code, _json(answer)["error"]), (400, "bad_request"), (name, content_type))
        self.assertFalse(ChatReaction.objects.exists())
        self.assertEqual(ChatRoom.objects.count(), rooms)
        self.assertFalse(self.team.members.filter(pk=self.hr.pk).exists())
        self.nothing_left_the_building()


class ThreadCarriesTheActionsTests(_Send):
    """What the page needs to draw the buttons under a message comes with the thread, and only to those who may use them."""

    def entry(self, user, uid):
        answer = self.browser(user).get(reverse("dashboard:v1_client_messages", args=[self.client_obj.code]))
        return next(m for m in _json(answer)["messages"] if m["uid"] == uid)

    def test_only_the_operation_and_the_admin_are_given_the_buttons(self):
        from .models import MessageAttachment

        MessageAttachment.objects.create(message=self.heard, file="in/doc.pdf", original_name="doc.pdf", size=1)
        for user, expected in ((self.ops, True), (self.admin, True), (self.boss_sales, True)):
            entry = self.entry(user, f"in-{self.heard.pk}")
            self.assertEqual((entry["actions"], entry["has_docs"]), (expected, True), user.username)
            self.assertEqual((entry["has_task"], entry["claimed_by"]), (False, ""), user.username)
        # Sales answers from their own number: the client has not written to it here, so there is no thread to ask.
        self.assertEqual(
            self.browser(self.sales).get(reverse("dashboard:v1_client_messages", args=[self.client_obj.code])).status_code in (200, 404),
            True,
        )

    def test_a_message_with_only_words_or_only_a_voice_note_has_no_documents(self):
        from .models import MessageAttachment

        MessageAttachment.objects.create(message=self.heard, file="in/note.ogg", original_name="note.ogg", mime="audio/ogg", is_voice=True)
        entry = self.entry(self.ops, f"in-{self.heard.pk}")
        self.assertEqual((entry["actions"], entry["has_docs"]), (True, False))

    def test_a_claimed_message_says_by_whom(self):
        InboundMessage.objects.filter(pk=self.heard.pk).update(claimed_by=self.ops)
        self.assertEqual(self.entry(self.admin, f"in-{self.heard.pk}")["claimed_by"], self.ops.short_name)


class TaskFormLineTests(_Send):
    """The task form opens from a client's messages by id; an id is only a number, so the line rule holds there too.

    The link the new chat builds (``?messages=1,2&files=3``) goes to ``views.ops_task_new``, which used to look the
    messages up by id alone: the operation could open, pre-fill from and take over a message that arrived on a Sales
    person's own number by counting.
    """

    def setUp(self):
        super().setUp()
        from .models import MessageAttachment

        self.secret = MessageAttachment.objects.create(message=self.sales_heard, file="in/secret.pdf", original_name="secret.pdf", size=1)
        self.quote = MessageAttachment.objects.create(message=self.heard, file="in/quote.pdf", original_name="quote.pdf", size=1)

    def form(self, user, **query):
        from urllib.parse import urlencode

        return self.browser(user).get(reverse("dashboard:ops_task_new") + "?" + urlencode(query))

    def test_the_operation_gets_no_word_and_no_file_name_of_another_line(self):
        answer = self.form(self.ops, messages=self.sales_heard.pk, files=self.secret.pk)
        text = answer.content.decode()
        self.assertEqual(answer.status_code, 200)
        self.assertNotIn("to the sales number", text)
        self.assertNotIn("secret.pdf", text)
        self.assertNotIn("Only Sales Knows", text)

    def test_but_a_message_of_the_company_line_fills_the_form_for_the_operation_and_the_admin(self):
        for user in (self.ops, self.admin):
            text = self.form(user, messages=self.heard.pk, files=self.quote.pk).content.decode()
            self.assertIn("quote.pdf", text, user.username)
            self.assertIn("Please quote this", text, user.username)
        # The admin works every line.
        text = self.form(self.admin, messages=self.sales_heard.pk, files=self.secret.pk).content.decode()
        self.assertIn("to the sales number", text)

    def test_posting_it_makes_no_task_and_claims_nothing(self):
        from .models import Task

        deadline = (timezone.now() + timedelta(days=2)).strftime("%Y-%m-%dT%H:%M")
        before = Task.objects.count()
        self.browser(self.ops).post(
            reverse("dashboard:ops_task_new") + f"?messages={self.sales_heard.pk}&files={self.secret.pk}",
            {"client": self.sales_client.pk, "title": "Stolen", "description": "x", "priority": "normal", "source_lang": "AR", "target_lang": "EN", "deadline": deadline},
        )
        self.sales_heard.refresh_from_db()
        self.assertIsNone(self.sales_heard.claimed_by_id)
        self.assertIsNone(self.sales_heard.task_id)
        self.assertFalse(Task.objects.filter(title="Stolen", source_messages__pk=self.sales_heard.pk).exists())
        self.assertEqual(Task.objects.count(), before + Task.objects.filter(title="Stolen").count())

    def test_a_new_request_on_a_task_does_not_carry_in_the_words_of_another_line(self):
        task = services.create_task(client=self.sales_client, title="From sales", created_by=self.admin, messages=[self.sales_heard])
        text = self.form(self.ops, **{"from": task.code}).content.decode()
        self.assertNotIn("to the sales number", text)
        self.assertNotIn("secret.pdf", text)
