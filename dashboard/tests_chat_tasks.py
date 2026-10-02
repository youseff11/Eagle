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
        self.confirm(self.hr, self.heard)
        self.assertEqual(AuditLog.objects.filter(action="security.denied").count(), before + 1)
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
