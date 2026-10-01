"""The chats screen in the new app, step 3b (writing: text and replies): ``/api/v1/{clients,groups,staff}/.../send/``.

The three doors are thin: what may be written where is still decided by the functions the classic pages
use, so most of what is pinned here is the *contract* around them and the places a wrapper could go wrong:

* who may write to a client, to a client group, to a work group, to a colleague - every role;
* a message that stays inside (a colleague, a work group) never reaches the relay or WhatsApp, whatever the
  room's own bookkeeping says;
* a delivery that failed is in the thread with its reason, not lost and not a bare error;
* nothing is written for a refusal, and no client name or number comes back to somebody who may not have it;
* sending does not mark the thread read (for a client that is a read receipt on their phone).
"""

import json
from datetime import timedelta
from unittest import mock

from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import Client as DjangoClient
from django.urls import reverse
from django.utils import timezone

from . import api_v1, identity, mailer, services, whatsapp
from .models import (
    AuditLog, Channel, ChatMessage, ChatRead, ChatRoom, Client, InboundMessage, Notification, OutboundMessage, Role,
    RoomKind, User,
)
from .tests_chat_lists import _Data, _json

NAME = "Zebulon Quartermaine"
PHONE = "+201234567890"


class _Send(_Data):
    def setUp(self):
        super().setUp()
        make = lambda name, role: User.objects.create_user(name, password="pw", role=role)
        self.reviewer = make("person_reviewer", Role.REVIEWER)
        self.accounting = make("person_accounting", Role.ACCOUNTING)
        self.everyone = self.everyone + [self.reviewer, self.accounting]
        # Each Sales person answers from a number of their own.
        for number, person in enumerate((self.sales, self.sales2, self.boss_sales), start=1):
            User.objects.filter(pk=person.pk).update(wa_phone_number_id=f"10000{number}")

        self.client_obj = Client.objects.create(name=NAME, phone=PHONE, email="zeb@example.test")
        self.heard = InboundMessage.objects.create(
            client=self.client_obj, channel=Channel.WHATSAPP, body="Please quote this", external_id="wamid.in.1",
        )
        # A client who has only ever written to the first Sales person's own number.
        self.sales_client = Client.objects.create(name="Only Sales Knows", phone="+201000000077")
        self.sales_heard = InboundMessage.objects.create(
            client=self.sales_client, channel=Channel.WHATSAPP, body="to the sales number", external_id="wamid.in.s",
            owner=self.sales,
        )
        # A client group and a work group, and a private line between two colleagues.
        self.group = ChatRoom.objects.create(
            kind=RoomKind.CLIENT, client=self.client_obj, title="With the client", created_by=self.ops,
        )
        self.group.members.add(self.ops, self.lead)
        self.team = ChatRoom.objects.create(kind=RoomKind.TEAM, title="Work", created_by=self.lead)
        self.team.members.add(self.ops, self.lead, self.tr)
        self.private = services.staff_room(self.ops, self.lead)

        patch = lambda target, **kw: mock.patch(target, **kw)
        self.text = patch("dashboard.whatsapp.send_text", return_value="wamid.out.1").start()
        self.file = patch("dashboard.whatsapp.send_file", return_value="wamid.out.2").start()
        self.addCleanup(mock.patch.stopall)

    # -- the doors ----------------------------------------------------------------
    def browser(self, user, **kw):
        browser = DjangoClient(**kw)
        if user is not None:
            browser.force_login(user)
        return browser

    def to_client(self, user, code=None, **data):
        return self.browser(user).post(reverse("dashboard:v1_client_send", args=[code or self.client_obj.code]), data)

    def to_group(self, user, room=None, **data):
        return self.browser(user).post(reverse("dashboard:v1_group_send", args=[(room or self.group).pk]), data)

    def to_staff(self, user, other, **data):
        return self.browser(user).post(reverse("dashboard:v1_staff_send", args=[other.pk]), data)

    def nothing_left_the_building(self):
        self.text.assert_not_called()
        self.file.assert_not_called()


class ClientSendTests(_Send):
    def test_the_operation_answers_on_whatsapp_and_gets_the_thread_back(self):
        answer = self.to_client(self.ops, body="  We can do it.  ")
        body = _json(answer)
        self.assertEqual(answer.status_code, 200)
        self.assertTrue(body["ok"])
        self.assertTrue(body["delivered"])
        self.assertEqual(body["error"], "")
        self.text.assert_called_once()
        self.assertEqual(self.text.call_args.args[:2], (PHONE, "We can do it."))
        sent = OutboundMessage.objects.get(client=self.client_obj)
        self.assertEqual((sent.created_by_id, sent.channel, sent.status), (self.ops.pk, Channel.WHATSAPP, OutboundMessage.Status.SENT))
        # The thread comes back as this person sees it (ours is an "out" bubble) and so does the row for the list.
        ours = [m for m in body["messages"] if m["kind"] == "out"]
        self.assertEqual([m["body"] for m in ours], ["We can do it."])
        self.assertEqual(ours[0]["status"], "sent")
        self.assertEqual(body["client"]["code"], self.client_obj.code)

    def test_it_is_exactly_what_the_classic_page_writes_for_every_role_that_may(self):
        # The classic endpoint is the specification: same row, same line, same words - for each person on a
        # conversation of their own line (the company's for the operation, their number for a Sales person).
        for client, heard, people in (
            (self.client_obj, self.heard, (self.admin, self.ops, self.boss_sales)),
            (self.sales_client, self.sales_heard, (self.admin, self.sales, self.boss_sales)),
        ):
            for user in people:
                OutboundMessage.objects.all().delete()
                self.browser(user).post(
                    reverse("dashboard:api_client_chat_send", args=[client.code]),
                    {"body": "same words", "reply_uid": f"in-{heard.pk}"},
                )
                old = OutboundMessage.objects.get()
                OutboundMessage.objects.all().delete()
                answer = self.to_client(user, code=client.code, body="same words", reply_uid=f"in-{heard.pk}")
                self.assertEqual(answer.status_code, 200, (client.code, user.username))
                new = OutboundMessage.objects.get()
                fields = ("channel", "to_identity", "body", "status", "owner_id", "reply_to_wamid", "reply_preview", "kind")
                self.assertEqual([getattr(new, f) for f in fields], [getattr(old, f) for f in fields], user.username)

    def test_a_reply_quotes_the_message_it_names_and_only_the_first_part_of_it(self):
        InboundMessage.objects.filter(pk=self.heard.pk).update(body="q" * 400)
        self.to_client(self.ops, body="answer", reply_uid=f"in-{self.heard.pk}")
        sent = OutboundMessage.objects.get()
        self.assertEqual(sent.reply_to_wamid, "wamid.in.1")
        self.assertEqual(sent.reply_preview, "q" * 160)
        self.assertEqual(self.text.call_args.kwargs["context_id"], "wamid.in.1")

    def test_a_reply_can_quote_our_own_earlier_message(self):
        self.to_client(self.ops, body="first")
        first = OutboundMessage.objects.get()
        first.provider_id = "wamid.ours"
        first.save(update_fields=["provider_id"])
        self.to_client(self.ops, body="second", reply_uid=f"out-{first.pk}")
        second = OutboundMessage.objects.exclude(pk=first.pk).get()
        self.assertEqual((second.reply_to_wamid, second.reply_preview), ("wamid.ours", "first"))

    def test_a_reply_to_somebody_elses_message_quotes_nothing(self):
        other = Client.objects.create(name="Somebody Else", phone="+201000000009")
        foreign_in = InboundMessage.objects.create(
            client=other, channel=Channel.WHATSAPP, body="OTHER CLIENT WORDS", external_id="wamid.other.in",
        )
        foreign_out = OutboundMessage.objects.create(
            client=other, kind=OutboundMessage.Kind.CHAT, channel=Channel.WHATSAPP, body="OTHER OUT",
            provider_id="wamid.other.out", status=OutboundMessage.Status.SENT,
        )
        for uid in (f"in-{foreign_in.pk}", f"out-{foreign_out.pk}", "in-999999", "in-x", "garbage", "", "in-", "-5"):
            OutboundMessage.objects.filter(client=self.client_obj).delete()
            answer = self.to_client(self.ops, body="plain", reply_uid=uid)
            self.assertEqual(answer.status_code, 200, uid)
            sent = OutboundMessage.objects.get(client=self.client_obj)
            self.assertEqual((sent.reply_to_wamid, sent.reply_preview), ("", ""), uid)
            self.assertNotIn(b"OTHER", answer.content, uid)

    def test_a_letter_of_ours_is_not_a_message_to_quote_on_the_whatsapp_line(self):
        letter = OutboundMessage.objects.create(
            client=self.client_obj, kind=OutboundMessage.Kind.CHAT, channel=Channel.EMAIL, body="a letter",
            provider_id="<message-id@example.test>", status=OutboundMessage.Status.SENT,
        )
        self.to_client(self.ops, body="plain", reply_uid=f"out-{letter.pk}")
        sent = OutboundMessage.objects.exclude(pk=letter.pk).get()
        self.assertEqual((sent.reply_to_wamid, sent.reply_preview), ("", ""))

    def test_a_message_the_rate_rule_hides_cannot_be_quoted_by_the_operation(self):
        hidden = InboundMessage.objects.create(
            client=self.client_obj, channel=Channel.WHATSAPP, body="a rate is mentioned", external_id="wamid.rate",
            is_rate_blocked=True,
        )
        self.to_client(self.ops, body="x", reply_uid=f"in-{hidden.pk}")
        self.assertEqual(OutboundMessage.objects.get().reply_to_wamid, "")

    def test_a_break_nobody_foresaw_leaves_a_failed_row_never_a_sent_one(self):
        # A timeout while reading Meta's answer: the row is made before the call and starts as "sent".
        self.text.side_effect = TimeoutError("read timed out: postgres://user:secret@host/db")
        answer = self.to_client(self.ops, body="did it go?")
        body = _json(answer)
        self.assertEqual(answer.status_code, 200)
        self.assertTrue(body["ok"])
        self.assertFalse(body["delivered"])
        self.assertEqual(body["error"], services.SEND_UNSURE_AR)
        sent = OutboundMessage.objects.get()
        self.assertEqual((sent.status, sent.error_message), (OutboundMessage.Status.FAILED, services.SEND_UNSURE_AR))
        shown = [(m["status"], m["error"]) for m in body["messages"] if m["kind"] == "out"]
        self.assertEqual(shown, [("failed", services.SEND_UNSURE_AR)])
        self.assertNotIn(b"secret", answer.content)

    def test_the_words_of_a_failure_never_carry_an_address_or_a_number(self):
        self.text.side_effect = whatsapp.WhatsAppError(
            "واتساب رجّع خطأ (400): +201234567890 مش مسجل", "WhatsApp returned an error (400): +201234567890 is not registered",
        )
        answer = self.to_client(self.ops, body="hello")
        self.assertNotIn(b"201234567890", answer.content)
        self.assertNotIn("201234567890", OutboundMessage.objects.get().error_message)
        self.assertIn("[...]", _json(answer)["error"])

    def test_the_reply_goes_by_whatsapp_even_when_the_client_last_wrote_by_email(self):
        # This door is the WhatsApp line: a letter that happened to arrive last must not turn the answer into one.
        InboundMessage.objects.create(
            client=self.client_obj, channel=Channel.EMAIL, body="by mail", subject="Mail",
            received_at=self.heard.received_at + timedelta(minutes=5),
        )
        answer = self.to_client(self.ops, body="on whatsapp")
        self.assertEqual(answer.status_code, 200)
        self.text.assert_called_once()
        self.assertEqual(OutboundMessage.objects.get().channel, Channel.WHATSAPP)

    def test_a_failed_delivery_is_in_the_thread_with_its_reason(self):
        self.text.side_effect = whatsapp.WhatsAppError("ميتا رفضت الرسالة", "Meta refused it")
        answer = self.to_client(self.ops, body="will not arrive")
        body = _json(answer)
        self.assertEqual(answer.status_code, 200)
        self.assertTrue(body["ok"])
        self.assertFalse(body["delivered"])
        self.assertEqual(body["error"], "ميتا رفضت الرسالة")
        failed = [m for m in body["messages"] if m["kind"] == "out"]
        self.assertEqual([(m["body"], m["status"], m["error"]) for m in failed], [("will not arrive", "failed", "ميتا رفضت الرسالة")])
        self.assertEqual(OutboundMessage.objects.get().status, OutboundMessage.Status.FAILED)

    def test_only_the_roles_that_answer_clients_may_and_nothing_is_written_for_the_rest(self):
        # A client of the company's line: the operation and the admin (a superuser reads as one). A Sales person
        # has no conversation with them on their own number, so for them it is as if the code did not exist.
        allowed = {self.admin, self.ops, self.boss_sales}
        handles_clients = allowed | {self.sales, self.sales2}
        for user in self.everyone:
            OutboundMessage.objects.all().delete()
            self.text.reset_mock()
            answer = self.to_client(user, body="hello")
            if user in allowed:
                self.assertEqual(answer.status_code, 200, user.username)
                self.assertEqual(OutboundMessage.objects.count(), 1, user.username)
            else:
                self.assertEqual(answer.status_code, 404 if user in handles_clients else 403, user.username)
                self.assertEqual(OutboundMessage.objects.count(), 0, user.username)
                self.nothing_left_the_building()
                self.assertNotIn(NAME.encode(), answer.content)
                self.assertNotIn(PHONE.encode(), answer.content)

    def test_a_client_who_wrote_to_another_line_is_not_there_for_the_operation_or_another_sales_person(self):
        # Nobody can write from the company number to a client who only ever wrote to a Sales number, nor from
        # their own number to one of a colleague's: the code is not a way in, and it is not an oracle either.
        for user in (self.ops, self.sales2):
            answer = self.to_client(user, code=self.sales_client.code, body="intruding")
            unknown = self.to_client(user, code="CL-9999", body="intruding")
            self.assertEqual(answer.status_code, 404, user.username)
            self.assertEqual(answer.content, unknown.content, user.username)
        self.assertEqual(OutboundMessage.objects.count(), 0)
        self.nothing_left_the_building()
        # The one whose line it is, and the admin, may.
        for user in (self.sales, self.admin):
            self.assertEqual(self.to_client(user, code=self.sales_client.code, body="mine").status_code, 200, user.username)
        # And the refusal is written down.
        self.assertTrue(AuditLog.objects.filter(action=identity.ACCESS_DENIED, actor=self.ops).exists())

    def test_a_message_the_rate_rule_hides_is_not_a_conversation_the_operation_has(self):
        # Only a rate-blocked message from this client on the company line: the operation reads none of it.
        client = Client.objects.create(name="Rates Only", phone="+201000000055")
        InboundMessage.objects.create(client=client, channel=Channel.WHATSAPP, body="a rate", is_rate_blocked=True)
        self.assertEqual(self.to_client(self.ops, code=client.code, body="x").status_code, 404)
        self.assertEqual(self.to_client(self.admin, code=client.code, body="x").status_code, 200)

    def test_a_conversation_made_only_of_what_we_sent_on_their_line_can_be_answered(self):
        client = Client.objects.create(name="Delivered To", phone="+201000000044")
        OutboundMessage.objects.create(
            client=client, kind=OutboundMessage.Kind.CHAT, channel=Channel.WHATSAPP, body="we wrote first",
            status=OutboundMessage.Status.SENT,
        )
        self.assertEqual(self.to_client(self.ops, code=client.code, body="x").status_code, 200)
        self.assertEqual(self.to_client(self.sales, code=client.code, body="x").status_code, 404)

    def test_a_refusal_is_written_to_the_audit_log(self):
        before = AuditLog.objects.filter(action=identity.ACCESS_DENIED, actor=self.tr).count()
        self.to_client(self.tr, body="hello")
        self.assertEqual(AuditLog.objects.filter(action=identity.ACCESS_DENIED, actor=self.tr).count(), before + 1)

    def test_nobody_signed_out_and_no_other_method(self):
        anonymous = self.browser(None).post(reverse("dashboard:v1_client_send", args=[self.client_obj.code]), {"body": "x"})
        self.assertEqual((anonymous.status_code, _json(anonymous)), (401, {"ok": False, "error": "auth"}))
        got = self.browser(self.ops).get(reverse("dashboard:v1_client_send", args=[self.client_obj.code]))
        self.assertEqual(got.status_code, 405)
        self.assertEqual(OutboundMessage.objects.count(), 0)
        self.nothing_left_the_building()

    def test_a_post_without_the_csrf_token_is_refused_and_writes_nothing(self):
        browser = self.browser(self.ops, enforce_csrf_checks=True)
        answer = browser.post(reverse("dashboard:v1_client_send", args=[self.client_obj.code]), {"body": "forged"})
        self.assertEqual(answer.status_code, 403)
        self.assertEqual(OutboundMessage.objects.count(), 0)
        self.nothing_left_the_building()

    def test_a_text_longer_than_whatsapp_carries_is_refused_not_cut_without_a_word(self):
        limit = api_v1.MAX_CLIENT_TEXT
        too_long = self.to_client(self.ops, body="x" * (limit + 1))
        self.assertEqual((too_long.status_code, _json(too_long)), (400, {"ok": False, "error": "too_long"}))
        self.assertEqual(OutboundMessage.objects.count(), 0)
        self.nothing_left_the_building()
        # The spaces around it do not count, and the limit itself is allowed.
        self.assertEqual(self.to_client(self.ops, body="  " + "x" * limit + "  ").status_code, 200)
        self.assertEqual(len(self.text.call_args.args[1]), limit)

    def test_nothing_to_send_is_refused_before_anything_is_written(self):
        for data in ({}, {"body": ""}, {"body": "   \n  "}, {"reply_uid": f"in-{self.heard.pk}"}):
            answer = self.to_client(self.ops, **data)
            self.assertEqual((answer.status_code, _json(answer)), (400, {"ok": False, "error": "empty"}), data)
        self.assertEqual(OutboundMessage.objects.count(), 0)
        self.nothing_left_the_building()

    def test_an_unknown_client_is_not_found_and_writes_nothing(self):
        answer = self.to_client(self.ops, code="CL-9999", body="hello")
        self.assertEqual(answer.status_code, 404)
        self.assertEqual(OutboundMessage.objects.count(), 0)

    def test_the_answer_names_the_client_by_code_for_the_operation_never_by_name_or_number(self):
        answer = self.to_client(self.ops, body="hello")
        self.assertNotIn(NAME.encode(), answer.content)
        self.assertNotIn(PHONE.encode(), answer.content)
        self.assertNotIn(b"zeb@example.test", answer.content)
        self.assertEqual(_json(answer)["client"]["label"], self.client_obj.code)

    def test_sending_does_not_mark_the_conversation_read_nor_tell_the_clients_phone_so(self):
        with mock.patch("dashboard.services.send_read_receipt") as receipt:
            answer = self.to_client(self.ops, body="hello")
        self.assertEqual(answer.status_code, 200)
        receipt.assert_not_called()
        self.assertFalse(ChatRead.objects.filter(user=self.ops).exists())

    def test_the_answer_is_private_and_not_stored(self):
        self.assertEqual(self.to_client(self.ops, body="hello")["Cache-Control"], "private, no-store")

    def test_the_thread_it_returns_is_the_one_a_get_gives(self):
        answer = _json(self.to_client(self.ops, body="hello"))
        again = _json(self.browser(self.ops).get(reverse("dashboard:v1_client_messages", args=[self.client_obj.code])))
        self.assertEqual(answer["messages"], again["messages"])
        self.assertEqual(answer["client"], again["client"])


class GroupSendTests(_Send):
    def test_a_work_group_message_stays_inside_whatever_the_room_says(self):
        with mock.patch("dashboard.services.relay_chat_message") as relay, \
                mock.patch("dashboard.services.send_client_message") as to_client:
            answer = self.to_group(self.lead, self.team, body="internal only")
        body = _json(answer)
        self.assertEqual(answer.status_code, 200)
        self.assertTrue(body["ok"] and body["delivered"])
        relay.assert_not_called()
        to_client.assert_not_called()
        self.nothing_left_the_building()
        self.assertEqual(list(ChatMessage.objects.filter(room=self.team).values_list("body", "sender_id")), [("internal only", self.lead.pk)])
        self.assertEqual([m["body"] for m in body["messages"]], ["internal only"])

    def test_a_colleagues_message_stays_inside_and_lands_in_the_room_of_the_pair(self):
        with mock.patch("dashboard.services.relay_chat_message") as relay, \
                mock.patch("dashboard.services.send_client_message") as to_client:
            answer = self.to_staff(self.ops, self.lead, body="between us")
        self.assertEqual(answer.status_code, 200)
        relay.assert_not_called()
        to_client.assert_not_called()
        self.nothing_left_the_building()
        self.assertEqual(ChatMessage.objects.get(body="between us").room_id, self.private.pk)
        self.assertEqual(_json(answer)["client"]["room"], self.private.pk)

    def test_the_first_message_to_a_colleague_opens_the_room_for_both_of_them(self):
        before = ChatRoom.objects.count()
        answer = self.to_staff(self.hr, self.sales, body="hello there")
        self.assertEqual(answer.status_code, 200)
        self.assertEqual(ChatRoom.objects.count(), before + 1)
        room = ChatRoom.objects.get(kind=RoomKind.STAFF, pair_key=services.staff_pair_key(self.hr.pk, self.sales.pk))
        self.assertEqual({u.pk for u in room.members.all()}, {self.hr.pk, self.sales.pk})
        self.assertEqual(ChatMessage.objects.get(room=room).body, "hello there")
        # And the other side sees it in the same room.
        theirs = _json(self.browser(self.sales).get(reverse("dashboard:v1_staff_messages", args=[self.hr.pk])))
        self.assertEqual([m["body"] for m in theirs["messages"]], ["hello there"])

    def test_nobody_can_write_into_a_private_line_they_are_not_in_not_even_the_admin(self):
        before = ChatMessage.objects.filter(room=self.private).count()
        # The id of the room is not a way in: the door takes a colleague, and finds the room of the pair.
        for user in (self.admin, self.hr, self.sales, self.tr):
            answer = self.to_group(user, self.private, body="let me in")
            self.assertEqual(answer.status_code, 404, user.username)
            self.to_staff(user, self.lead, body="to the leader")
            self.to_staff(user, self.ops, body="to the operation")
        self.assertEqual(ChatMessage.objects.filter(room=self.private).count(), before)
        self.assertFalse(ChatMessage.objects.filter(room=self.private, body__in=("let me in", "to the leader", "to the operation")).exists())

    def test_a_colleague_must_be_somebody_else_who_is_there_and_nothing_is_written_for_nobody(self):
        rooms = ChatRoom.objects.count()
        self.assertEqual(self.to_staff(self.ops, self.ops, body="to myself").status_code, 404)
        self.assertEqual(self.browser(self.ops).post(reverse("dashboard:v1_staff_send", args=[999999]), {"body": "x"}).status_code, 404)
        User.objects.filter(pk=self.sales.pk).update(is_active=False)
        self.assertEqual(self.to_staff(self.ops, User.objects.get(pk=self.sales.pk), body="to nobody").status_code, 404)
        self.assertEqual(ChatRoom.objects.count(), rooms)
        self.assertFalse(ChatMessage.objects.filter(body__in=("to myself", "x", "to nobody")).exists())

    def test_nothing_to_send_does_not_even_open_a_room(self):
        rooms = ChatRoom.objects.count()
        for data in ({}, {"body": " "}):
            answer = self.to_staff(self.hr, self.sales, **data)
            self.assertEqual((answer.status_code, _json(answer)), (400, {"ok": False, "error": "empty"}))
        self.assertEqual(ChatRoom.objects.count(), rooms)

    def test_a_client_group_message_goes_to_the_client_through_the_relay_and_only_once(self):
        with mock.patch("dashboard.services.relay_chat_message", return_value=(True, "")) as relay:
            answer = self.to_group(self.ops, body="for the client")
        body = _json(answer)
        self.assertTrue(body["ok"] and body["delivered"])
        relay.assert_called_once()
        self.assertEqual(relay.call_args.args[0].body, "for the client")
        self.assertEqual(relay.call_args.args[0].room_id, self.group.pk)

    def test_a_client_group_message_that_does_not_arrive_stays_in_the_thread_marked_failed(self):
        self.text.side_effect = whatsapp.WhatsAppError("مفيش نافذة", "No window")
        answer = self.to_group(self.ops, body="will not arrive")
        body = _json(answer)
        self.assertEqual(answer.status_code, 200)
        self.assertTrue(body["ok"])
        self.assertFalse(body["delivered"])
        self.assertEqual(body["error"], "مفيش نافذة")
        message = ChatMessage.objects.get(body="will not arrive")
        self.assertEqual((message.relay_status, message.relay_error), ("failed", "مفيش نافذة"))
        self.assertIn("will not arrive", [m["body"] for m in body["messages"]])

    def test_a_letter_the_client_group_could_not_send_does_not_tell_the_room_the_clients_address(self):
        # The client's last word was an e-mail, so the group answers by e-mail; SMTP refuses and quotes the address.
        InboundMessage.objects.create(
            client=self.client_obj, channel=Channel.EMAIL, subject="Mail", body="by mail",
            received_at=self.heard.received_at + timedelta(minutes=5),
        )
        refusal = mailer.MailError(
            "إرسال الإيميل فشل: {'zeb@example.test': (550, b'5.1.1 no such user')}",
            "Sending the e-mail failed: {'zeb@example.test': (550, b'5.1.1 no such user')}",
        )
        with mock.patch("dashboard.mailer.send_delivery", side_effect=refusal):
            answer = self.to_group(self.lead, body="from the leader")
        body = _json(answer)
        self.assertFalse(body["delivered"])
        self.assertNotIn(b"zeb@example.test", answer.content)
        message = ChatMessage.objects.get(body="from the leader")
        self.assertEqual(message.relay_status, "failed")
        self.assertNotIn("zeb@example.test", message.relay_error)
        # Nor in what the room reads afterwards.
        for viewer in (self.lead, self.ops, self.admin):
            later = self.browser(viewer).get(reverse("dashboard:v1_group_messages", args=[self.group.pk]))
            self.assertNotIn(b"zeb@example.test", later.content, viewer.username)

    def test_a_relay_that_breaks_in_an_unforeseen_way_says_so_in_general_terms(self):
        with mock.patch("dashboard.services.send_client_message", side_effect=RuntimeError("secret postgres://u:pw@h/db")):
            answer = self.to_group(self.ops, body="for the client")
        body = _json(answer)
        self.assertFalse(body["delivered"])
        self.assertEqual(body["error"], services.RELAY_FAILED_AR)
        self.assertNotIn(b"secret", answer.content)
        self.assertEqual(ChatMessage.objects.get(body="for the client").relay_error, services.RELAY_FAILED_AR)

    def test_whatever_the_sender_reports_is_scrubbed_again_before_it_is_stored_on_the_room(self):
        # The room keeps what it is told: a second hand on the way in, whatever the first one did.
        told = "refused for zeb@example.test and +201234567890"
        with mock.patch("dashboard.services.send_client_message", return_value=(False, None, told)):
            answer = self.to_group(self.ops, body="for the client")
        message = ChatMessage.objects.get(body="for the client")
        self.assertNotIn("zeb@example.test", message.relay_error)
        self.assertNotIn("201234567890", message.relay_error)
        self.assertNotIn(b"zeb@example.test", answer.content)

    def test_a_colleagues_notice_opens_the_chat_with_whoever_wrote_and_reads_name_then_words(self):
        self.to_staff(self.ops, self.lead, body="ready when you are")
        notice = Notification.objects.get(user=self.lead, body_en__contains="ready when you are")
        self.assertEqual(notice.url, f"/ops/chats/u/{self.ops.pk}/")
        self.assertEqual(notice.body_en, f"{self.ops.short_name}: ready when you are")
        self.assertNotIn("—", notice.body_ar)
        # And the link works: it is the chat, not a page that is not there.
        self.assertEqual(self.browser(self.lead).get(notice.url).status_code, 200)

    def test_a_work_groups_notice_still_names_the_group(self):
        self.to_group(self.lead, self.team, body="news")
        notice = Notification.objects.get(user=self.ops, body_en__contains="news")
        self.assertEqual(notice.url, f"/ops/chats/g/{self.team.pk}/")
        self.assertIn("Work", notice.body_en)

    def test_who_may_write_in_a_client_group_and_in_a_work_group_for_every_role(self):
        for room, members_ok, relayed in ((self.group, {self.ops, self.lead, self.admin, self.boss_sales}, True), (self.team, {self.ops, self.lead, self.tr, self.admin, self.boss_sales}, False)):
            for user in self.everyone:
                ChatMessage.objects.filter(room=room).delete()
                self.text.reset_mock()
                with mock.patch("dashboard.services.relay_chat_message", return_value=(True, "")) as relay:
                    answer = self.to_group(user, room, body="a line")
                label = (room.title, user.username)
                if user in members_ok:
                    self.assertEqual(answer.status_code, 200, label)
                    self.assertEqual(ChatMessage.objects.filter(room=room).count(), 1, label)
                    self.assertEqual(relay.call_count, 1 if relayed else 0, label)
                else:
                    # Not theirs: a 404 (a 403 would say the room exists), nothing written, nothing relayed.
                    self.assertEqual(answer.status_code, 404, label)
                    self.assertEqual(ChatMessage.objects.filter(room=room).count(), 0, label)
                    relay.assert_not_called()

    def test_a_task_room_is_not_a_way_in_through_this_door(self):
        # The group door is for client groups, work groups and colleagues: a task's own room has its own.
        room = ChatRoom.objects.create(kind=RoomKind.OPS_LEAD, created_by=self.ops)
        room.members.add(self.ops, self.lead)
        answer = self.to_group(self.ops, room, body="into the task room")
        self.assertEqual(answer.status_code, 404)
        self.assertFalse(ChatMessage.objects.filter(room=room).exists())

    def test_a_translator_seated_in_a_client_group_by_hand_cannot_write_in_it(self):
        self.group.members.add(self.tr)
        answer = self.to_group(self.tr, body="can I?")
        self.assertEqual(answer.status_code, 404)
        self.assertFalse(ChatMessage.objects.filter(room=self.group).exists())

    def test_a_refusal_is_written_to_the_audit_log(self):
        before = AuditLog.objects.filter(action=identity.ACCESS_DENIED, actor=self.hr).count()
        self.to_group(self.hr, self.team, body="x")
        self.assertEqual(AuditLog.objects.filter(action=identity.ACCESS_DENIED, actor=self.hr).count(), before + 1)

    def test_a_reply_quotes_a_message_of_the_same_room_and_never_of_another(self):
        mine = ChatMessage.objects.create(room=self.team, sender=self.ops, body="the first line")
        elsewhere = ChatMessage.objects.create(room=self.private, sender=self.ops, body="A PRIVATE WORD")
        self.to_group(self.lead, self.team, body="in reply", reply_uid=f"g{self.team.pk}-{mine.pk}")
        self.assertEqual(ChatMessage.objects.get(body="in reply").reply_to_id, mine.pk)
        answer = self.to_group(self.lead, self.team, body="in reply to a stranger", reply_uid=f"g{self.private.pk}-{elsewhere.pk}")
        self.assertIsNone(ChatMessage.objects.get(body="in reply to a stranger").reply_to_id)
        self.assertNotIn(b"PRIVATE WORD", answer.content)

    def test_a_reply_to_a_system_line_quotes_nothing(self):
        services.system_message(self.team, key="note", body_ar="ملاحظة", body_en="A note")
        note = ChatMessage.objects.get(room=self.team, is_system=True)
        self.to_group(self.lead, self.team, body="reply to the note", reply_uid=f"g{self.team.pk}-{note.pk}")
        self.assertIsNone(ChatMessage.objects.get(body="reply to the note").reply_to_id)

    def test_the_others_in_the_room_are_told_and_the_sender_is_not(self):
        self.to_group(self.lead, self.team, body="news")
        self.assertTrue(Notification.objects.filter(user=self.ops, body_en__contains="news").exists())
        self.assertTrue(Notification.objects.filter(user=self.tr, body_en__contains="news").exists())
        self.assertFalse(Notification.objects.filter(user=self.lead, body_en__contains="news").exists())

    def test_a_translator_in_a_client_group_row_is_never_told_what_the_operation_said_to_the_client(self):
        # A seat that survived from before the rule: the room still lists them, the room no longer opens for them.
        self.group.members.add(self.tr)
        self.to_group(self.ops, body="THE CLIENT'S RATE")
        self.assertFalse(Notification.objects.filter(user=self.tr, body_en__contains="RATE").exists())

    def test_sending_does_not_mark_the_room_read(self):
        ChatMessage.objects.create(room=self.team, sender=self.ops, body="not seen yet")
        self.to_group(self.lead, self.team, body="mine")
        self.assertFalse(ChatRead.objects.filter(user=self.lead, room=self.team).exists())

    def test_the_answer_names_no_client_to_somebody_in_a_client_group_who_may_not_know_them(self):
        with mock.patch("dashboard.services.relay_chat_message", return_value=(True, "")):
            answer = self.to_group(self.lead, body="from the leader")
        self.assertEqual(answer.status_code, 200)
        self.assertNotIn(NAME.encode(), answer.content)
        self.assertNotIn(PHONE.encode(), answer.content)

    def test_the_thread_it_returns_is_the_one_a_get_gives(self):
        answer = _json(self.to_group(self.lead, self.team, body="hello"))
        again = _json(self.browser(self.lead).get(reverse("dashboard:v1_group_messages", args=[self.team.pk])))
        self.assertEqual(answer["messages"], again["messages"])
        self.assertEqual(answer["client"], again["client"])
        staff = _json(self.to_staff(self.ops, self.lead, body="hi"))
        again = _json(self.browser(self.ops).get(reverse("dashboard:v1_staff_messages", args=[self.lead.pk])))
        self.assertEqual(staff["messages"], again["messages"])
        self.assertEqual(staff["client"], again["client"])

    def test_the_wrong_method_and_nobody_signed_in(self):
        url = reverse("dashboard:v1_group_send", args=[self.team.pk])
        self.assertEqual(self.browser(None).post(url, {"body": "x"}).status_code, 401)
        self.assertEqual(self.browser(self.lead).get(url).status_code, 405)
        browser = self.browser(self.lead, enforce_csrf_checks=True)
        self.assertEqual(browser.post(url, {"body": "forged"}).status_code, 403)
        self.assertFalse(ChatMessage.objects.filter(room=self.team).exists())

    def test_a_long_text_is_refused_for_a_client_group_at_the_clients_limit_and_inside_at_a_larger_one(self):
        with mock.patch("dashboard.services.relay_chat_message", return_value=(True, "")) as relay:
            reaching = self.to_group(self.ops, body="x" * (api_v1.MAX_CLIENT_TEXT + 1))
        self.assertEqual((reaching.status_code, _json(reaching)["error"]), (400, "too_long"))
        relay.assert_not_called()
        self.assertFalse(ChatMessage.objects.filter(room=self.group, body__startswith="xxx").exists())
        # Inside, the same length is fine, up to a larger one.
        self.assertEqual(self.to_group(self.lead, self.team, body="x" * (api_v1.MAX_CLIENT_TEXT + 1)).status_code, 200)
        self.assertEqual(self.to_group(self.lead, self.team, body="y" * api_v1.MAX_INTERNAL_TEXT).status_code, 200)
        over = self.to_group(self.lead, self.team, body="z" * (api_v1.MAX_INTERNAL_TEXT + 1))
        self.assertEqual((over.status_code, _json(over)["error"]), (400, "too_long"))
        staff = self.to_staff(self.hr, self.sales, body="z" * (api_v1.MAX_INTERNAL_TEXT + 1))
        self.assertEqual((staff.status_code, _json(staff)["error"]), (400, "too_long"))
        self.assertFalse(ChatMessage.objects.filter(body__startswith="zzz").exists())
        # No room was opened for a message that was refused.
        self.assertFalse(ChatRoom.objects.filter(pair_key=services.staff_pair_key(self.hr.pk, self.sales.pk)).exists())

    def test_the_thread_says_who_wrote_by_id_as_well_as_by_name(self):
        client_side = _json(self.to_client(self.ops, body="from the operation"))
        ours = [m for m in client_side["messages"] if m["kind"] == "out"]
        self.assertEqual([m["sender_id"] for m in ours], [self.ops.pk])
        inbound = [m for m in client_side["messages"] if m["kind"] == "in"]
        self.assertEqual({m["sender_id"] for m in inbound}, {0})
        room_side = _json(self.to_group(self.lead, self.team, body="from the leader"))
        self.assertEqual([m["sender_id"] for m in room_side["messages"]], [self.lead.pk])

    def test_nothing_to_send_to_a_group_is_refused(self):
        answer = self.to_group(self.lead, self.team, body="  ")
        self.assertEqual((answer.status_code, _json(answer)["error"]), (400, "empty"))
        self.assertFalse(ChatMessage.objects.filter(room=self.team).exists())


class ScrubContactsTests(_Send):
    """``identity.scrub_contacts``: what an error may say once it is stored where a whole room reads it."""

    def test_an_address_and_a_number_are_taken_out_wherever_they_stand(self):
        for text in (
            "refused: {'zeb@example.test': (550, b'5.1.1')}",
            "mailbox user.name+tag@mail.co.uk is full",
            "cannot deliver to +20 123 456 7890 now",
            "to 201234567890 failed",
            "no such account (+201234567890)",
        ):
            out = identity.scrub_contacts(text)
            self.assertIn(identity.MASKED, out, text)
            self.assertNotRegex(out, r"@|\d{9}|\+20", text)

    def test_what_is_not_a_contact_is_left_alone(self):
        for text in (
            "error 131047 (re-engagement)", "sent at 2026-10-01 7:48 PM", "status 550", "الرسالة اتحفظت بس مروحتش للعميل.", "",
        ):
            self.assertEqual(identity.scrub_contacts(text), text)
        self.assertEqual(identity.scrub_contacts(None), "")


class ErrorWordsTests(_Send):
    """What a failure says is read by whoever opens the thread: the contacts in it stay with the people who may know them."""

    TOLD = "Recipient 201234567890 and zeb@example.test undeliverable"

    def test_a_row_written_before_the_scrub_is_read_without_the_contacts_by_those_who_may_not_know_them(self):
        OutboundMessage.objects.create(
            client=self.client_obj, kind=OutboundMessage.Kind.CHAT, channel=Channel.WHATSAPP, body="old send",
            status=OutboundMessage.Status.FAILED, error_message=self.TOLD,
        )
        mine = _json(self.browser(self.ops).get(reverse("dashboard:v1_client_messages", args=[self.client_obj.code])))
        self.assertNotIn("zeb@example.test", json.dumps(mine))
        self.assertNotIn("201234567890", json.dumps(mine))
        failed = [m for m in mine["messages"] if m["kind"] == "out"]
        self.assertIn("undeliverable", failed[0]["error"])
        # The admin may know the client, and reads what was said as it was.
        theirs = _json(self.browser(self.admin).get(reverse("dashboard:v1_client_messages", args=[self.client_obj.code])))
        self.assertIn("zeb@example.test", [m for m in theirs["messages"] if m["kind"] == "out"][0]["error"])

    def test_a_room_message_that_could_not_be_relayed_is_read_the_same_way(self):
        ChatMessage.objects.create(
            room=self.group, sender=self.ops, body="for the client", relay_status="failed", relay_error=self.TOLD,
        )
        for viewer in (self.lead, self.ops):
            answer = self.browser(viewer).get(reverse("dashboard:v1_group_messages", args=[self.group.pk]))
            self.assertNotIn(b"zeb@example.test", answer.content, viewer.username)
            self.assertNotIn(b"201234567890", answer.content, viewer.username)
        raw = self.browser(self.admin).get(reverse("dashboard:v1_group_messages", args=[self.group.pk]))
        self.assertIn(b"zeb@example.test", raw.content)

    def test_the_classic_message_json_is_read_the_same_way(self):
        # api._message_json is what the task page and the old room page draw from.
        message = ChatMessage.objects.create(
            room=self.group, sender=self.ops, body="x", relay_status="failed", relay_error=self.TOLD,
        )
        from . import api

        self.assertNotIn("zeb@example.test", api._message_json(message, self.lead)["relay_error"])
        self.assertIn("zeb@example.test", api._message_json(message, self.admin)["relay_error"])

    def test_what_meta_says_about_a_message_that_failed_later_is_scrubbed_when_it_is_stored(self):
        sent = OutboundMessage.objects.create(
            client=self.client_obj, kind=OutboundMessage.Kind.CHAT, channel=Channel.WHATSAPP, body="ok",
            provider_id="wamid.late", status=OutboundMessage.Status.SENT,
        )
        in_room = ChatMessage.objects.create(room=self.group, sender=self.ops, body="ok", relay_wamid="wamid.late")
        self.assertEqual(services.record_whatsapp_status("wamid.late", "failed", self.TOLD), 2)
        sent.refresh_from_db()
        in_room.refresh_from_db()
        for stored in (sent.error_message, in_room.relay_error):
            self.assertNotIn("zeb@example.test", stored)
            self.assertNotIn("201234567890", stored)
            self.assertIn("undeliverable", stored)

    def test_a_task_delivery_that_is_refused_does_not_hand_the_operation_the_address(self):
        task = services.create_task(client=self.client_obj, title="A job", created_by=self.ops)
        task.status = "reviewed"
        task.handover_ack_at = timezone.now()
        task.save()
        InboundMessage.objects.create(
            client=self.client_obj, channel=Channel.EMAIL, subject="Mail", body="by mail",
            received_at=self.heard.received_at + timedelta(minutes=5),
        )
        refusal = mailer.MailError(
            "إرسال الإيميل فشل: {'zeb@example.test': (550, b'no such user')}",
            "Sending the e-mail failed: {'zeb@example.test': (550, b'no such user')}",
        )
        with mock.patch("dashboard.mailer.send_delivery", side_effect=refusal), \
                mock.patch("dashboard.whatsapp.send_text", side_effect=refusal):
            ok, delivery, error = services.deliver_to_client(task, self.ops, [], "here you are")
        self.assertFalse(ok)
        self.assertNotIn("zeb@example.test", error)
        self.assertNotIn("zeb@example.test", delivery.error_message)
        notice = Notification.objects.get(user=self.ops, title_en="Delivery failed")
        self.assertNotIn("zeb@example.test", notice.body_ar + notice.body_en)


class BreakBeforeTheSendTests(_Send):
    """A row is made before the send and starts as "sent": a break anywhere after it must not leave it so."""

    def test_a_file_that_cannot_be_read_back_leaves_a_failed_row(self):
        upload = SimpleUploadedFile("brief.txt", b"words", content_type="text/plain")
        with mock.patch("dashboard.services._read_attachment", side_effect=RuntimeError("storage is down")):
            answer = self.to_client(self.ops, body="with a file", files=upload)
        body = _json(answer)
        self.assertEqual(answer.status_code, 200)
        self.assertFalse(body["delivered"])
        self.assertEqual(body["error"], services.SEND_UNSURE_AR)
        sent = OutboundMessage.objects.get()
        self.assertEqual((sent.status, sent.error_message), (OutboundMessage.Status.FAILED, services.SEND_UNSURE_AR))
        self.assertNotIn(b"storage is down", answer.content)
        self.nothing_left_the_building()

    def test_a_file_that_cannot_be_stored_leaves_a_failed_row_too(self):
        upload = SimpleUploadedFile("brief.txt", b"words", content_type="text/plain")
        with mock.patch("dashboard.models.OutboundAttachment.objects.create", side_effect=OSError("disk full")):
            answer = self.to_client(self.ops, body="with a file", files=upload)
        self.assertEqual(answer.status_code, 200)
        self.assertEqual(OutboundMessage.objects.get().status, OutboundMessage.Status.FAILED)

    def test_when_the_text_went_and_the_file_did_not_the_row_keeps_what_meta_gave_the_text(self):
        self.file.side_effect = whatsapp.WhatsAppError("الملف مارضيش", "The file was refused")
        upload = SimpleUploadedFile("brief.txt", b"words", content_type="text/plain")
        answer = self.to_client(self.ops, body="the text went", files=upload)
        self.assertFalse(_json(answer)["delivered"])
        sent = OutboundMessage.objects.get()
        self.assertEqual(sent.status, OutboundMessage.Status.FAILED)
        self.assertEqual(sent.provider_id, "wamid.out.1")

    def test_a_room_with_no_client_behind_it_marks_the_message_failed_not_only_the_answer(self):
        room = ChatRoom.objects.create(kind=RoomKind.CLIENT, title="Nobody", created_by=self.ops)
        room.members.add(self.ops)
        body = _json(self.to_group(self.ops, room, body="into the void"))
        self.assertFalse(body["delivered"])
        message = ChatMessage.objects.get(body="into the void")
        self.assertEqual(message.relay_status, "failed")
        self.assertTrue(message.relay_error)
        self.assertIn("into the void", [m["body"] for m in body["messages"]])


class LimitWithThePrefixTests(_Send):
    def test_a_client_group_counts_the_role_that_goes_in_front_of_the_words(self):
        for user in (self.lead, self.ops):
            ChatMessage.objects.filter(room=self.group).delete()
            self.text.reset_mock()
            room_limit = api_v1.MAX_CLIENT_TEXT - len(services.client_prefix(user))
            self.assertLess(room_limit, api_v1.MAX_CLIENT_TEXT)
            over = self.to_group(user, body="x" * (room_limit + 1))
            self.assertEqual((over.status_code, _json(over)["error"]), (400, "too_long"), user.username)
            self.assertFalse(ChatMessage.objects.filter(room=self.group).exists())
            self.assertEqual(self.to_group(user, body="x" * room_limit).status_code, 200, user.username)
            # What WhatsApp is given is whole: not a character of it is cut.
            self.assertEqual(len(self.text.call_args.args[1]), api_v1.MAX_CLIENT_TEXT, user.username)

    def test_me_says_the_limits_for_this_person(self):
        for user in (self.ops, self.lead, self.admin):
            limits = _json(self.browser(user).get(reverse("dashboard:v1_me")))["limits"]
            self.assertEqual(limits, {
                "to_client": api_v1.MAX_CLIENT_TEXT,
                "to_client_group": api_v1.MAX_CLIENT_TEXT - len(services.client_prefix(user)),
                "inside": api_v1.MAX_INTERNAL_TEXT,
            }, user.username)


class AdminStartsAConversationTests(_Send):
    def test_the_admin_may_write_to_a_client_with_no_message_yet_and_no_refusal_is_written_down(self):
        fresh = Client.objects.create(name="Brand New", phone="+201000000033")
        # Everyone else who answers clients has no conversation to answer yet.
        self.assertEqual(self.to_client(self.ops, code=fresh.code, body="welcome").status_code, 404)
        before = AuditLog.objects.filter(action=identity.ACCESS_DENIED, actor=self.admin).count()
        self.assertEqual(self.to_client(self.admin, code=fresh.code, body="welcome").status_code, 200)
        self.assertEqual(AuditLog.objects.filter(action=identity.ACCESS_DENIED, actor=self.admin).count(), before)
        # What the admin wrote on the company line is a conversation of that line: the operation may now answer it.
        self.assertEqual(self.to_client(self.ops, code=fresh.code, body="and welcome from us").status_code, 200)
