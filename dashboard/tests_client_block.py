"""Blocking a client (``/api/v1/clients/<code>/block/``, ``services.set_client_blocked``).

The admin, the operation and Sales, each on a client of a line they work (the rule a reply is held to). A blocked client is not heard: a WhatsApp message or a letter from them is dropped on arrival (nothing
stored, nobody rung, the webhook still answers 200), and nothing is sent to them from the chat, a forward, a group's relay
or the mail page. Unblocking lets the next message in. Both are written to the audit log.
"""

import json

from django.urls import reverse

from . import services
from .models import AuditLog, Channel, ChatMessage, Client, InboundMessage, Notification, OutboundMessage
from .tests_chat_lists import _json
from .tests_chat_send import PHONE, _Send


class _Block(_Send):
    def block(self, user, blocked=True, code=None):
        return self.browser(user).post(
            reverse("dashboard:v1_client_block", args=[code or self.client_obj.code]),
            json.dumps({"blocked": blocked}), content_type="application/json",
        )

    def blocked(self):
        self.client_obj.refresh_from_db()
        return self.client_obj.is_blocked

    def hook(self, sender=PHONE, wamid="wamid.blocked.1", text="hello again"):
        payload = {"entry": [{"changes": [{"value": {
            "metadata": {"phone_number_id": ""},
            "contacts": [{"wa_id": sender, "profile": {"name": "Client"}}],
            "messages": [{"from": sender, "id": wamid, "type": "text", "text": {"body": text}}],
        }}]}]}
        return self.browser(None).post("/webhooks/whatsapp/", data=json.dumps(payload), content_type="application/json")


class BlockDoorTests(_Block):
    def test_the_admin_blocks_and_unblocks_and_both_are_written_down(self):
        answer = self.block(self.admin)
        self.assertEqual((answer.status_code, _json(answer)["blocked"]), (200, True))
        self.assertTrue(self.blocked())
        self.assertEqual(self.client_obj.blocked_by_id, self.admin.pk)
        answer = self.block(self.admin, blocked=False)
        self.assertEqual((answer.status_code, _json(answer)["blocked"]), (200, False))
        self.assertFalse(self.blocked())
        self.assertIsNone(self.client_obj.blocked_by_id)
        self.assertEqual(
            list(AuditLog.objects.filter(target=self.client_obj.code, action__startswith="client.").order_by("id").values_list("action", flat=True)),
            ["client.block", "client.unblock"],
        )

    def test_the_operation_blocks_a_company_line_client_and_sales_their_own(self):
        self.assertEqual(self.block(self.ops).status_code, 200)
        self.assertTrue(self.blocked())
        self.assertEqual(self.block(self.ops, blocked=False).status_code, 200)
        self.assertFalse(self.blocked())
        answer = self.block(self.sales, code=self.sales_client.code)
        self.assertEqual((answer.status_code, _json(answer)["blocked"]), (200, True))
        self.sales_client.refresh_from_db()
        self.assertEqual(self.sales_client.blocked_by_id, self.sales.pk)
        self.assertTrue(AuditLog.objects.filter(actor=self.sales, action="client.block", target=self.sales_client.code).exists())

    def test_a_client_off_this_persons_line_answers_like_an_unknown_one(self):
        # The company line's client is not this Sales person's, a Sales line's client is not the operation's,
        # and another Sales person's client is not theirs either.
        self.assertEqual(self.block(self.sales).status_code, 404)
        self.assertEqual(self.block(self.ops, code=self.sales_client.code).status_code, 404)
        self.assertEqual(self.block(self.sales2, code=self.sales_client.code).status_code, 404)
        self.assertFalse(self.blocked())
        self.sales_client.refresh_from_db()
        self.assertFalse(self.sales_client.is_blocked)

    def test_nobody_else_may_block(self):
        for user in (self.lead, self.tr, self.hr):
            self.assertEqual(self.block(user).status_code, 403, user.role)
        self.assertEqual(self.block(None).status_code, 401)
        self.assertFalse(self.blocked())

    def test_a_bad_body_and_an_unknown_code_are_refused(self):
        door = reverse("dashboard:v1_client_block", args=[self.client_obj.code])
        for body in ({}, {"blocked": "yes"}, {"blocked": 1}):
            self.assertEqual(self.browser(self.admin).post(door, json.dumps(body), content_type="application/json").status_code, 400, body)
        self.assertEqual(self.block(self.admin, code="CL-9999").status_code, 404)
        self.assertFalse(self.blocked())

    def test_the_rows_say_it_to_whoever_sees_the_chat(self):
        self.block(self.admin)
        for user in (self.admin, self.ops):
            rows = {r["code"]: r for r in _json(self.browser(user).get(reverse("dashboard:v1_chats"), {"type": "clients"}))["items"]}
            self.assertTrue(rows[self.client_obj.code]["blocked"], user.role)
            thread = _json(self.browser(user).get(reverse("dashboard:v1_client_messages", args=[self.client_obj.code])))
            self.assertTrue(thread["client"]["blocked"], user.role)


class BlockedInboundTests(_Block):
    def test_a_whatsapp_message_from_a_blocked_client_is_dropped_and_rings_nobody(self):
        self.block(self.admin)
        before = InboundMessage.objects.count()
        answer = self.hook()
        # Meta is still told 200, or it would send the message again forever.
        self.assertEqual((answer.status_code, _json(answer)["created"]), (200, []))
        self.assertEqual(InboundMessage.objects.count(), before)
        self.assertFalse(Notification.objects.filter(title_en="New client message").exists())

    def test_a_letter_from_a_blocked_client_is_dropped_too(self):
        self.block(self.admin)
        found = services.ingest_message(channel=Channel.EMAIL, body="hi", subject="Order", sender_identity="zeb@example.test")
        self.assertIsNone(found)
        self.assertFalse(InboundMessage.objects.filter(channel=Channel.EMAIL).exists())

    def test_a_blocked_client_does_not_reach_a_group_either(self):
        self.block(self.admin)
        before = ChatMessage.objects.filter(room=self.group).count()
        with self.captureOnCommitCallbacks(execute=True):
            self.hook()
        self.assertEqual(ChatMessage.objects.filter(room=self.group).count(), before)

    def test_another_client_is_heard_as_before(self):
        self.block(self.admin)
        other = Client.objects.create(name="Someone Else", phone="+201000000055")
        answer = self.hook(sender="201000000055", wamid="wamid.other.1")
        self.assertEqual(len(_json(answer)["created"]), 1)
        self.assertTrue(InboundMessage.objects.filter(client=other, external_id="wamid.other.1").exists())

    def test_after_unblocking_the_next_message_arrives(self):
        self.block(self.admin)
        self.hook(wamid="wamid.while.1")
        self.block(self.admin, blocked=False)
        self.hook(wamid="wamid.after.1")
        self.assertFalse(InboundMessage.objects.filter(external_id="wamid.while.1").exists())
        self.assertTrue(InboundMessage.objects.filter(external_id="wamid.after.1", client=self.client_obj).exists())


class BlockedOutboundTests(_Block):
    def test_the_chat_refuses_to_send_and_nothing_leaves(self):
        self.block(self.admin)
        for user in (self.admin, self.ops):
            answer = self.to_client(user, body="are you there")
            self.assertEqual((answer.status_code, _json(answer)["error"]), (409, "blocked"), user.role)
        self.nothing_left_the_building()
        self.assertFalse(OutboundMessage.objects.filter(client=self.client_obj).exists())

    def test_a_group_that_reaches_the_client_does_not_relay_to_them(self):
        self.block(self.admin)
        self.to_group(self.ops, body="hello from the group")
        self.nothing_left_the_building()
        said = ChatMessage.objects.filter(room=self.group, body="hello from the group").get()
        self.assertEqual(said.relay_status, "failed")

    def test_every_road_out_is_shut_by_the_send_itself(self):
        self.block(self.admin)
        self.client_obj.refresh_from_db()
        ok, outbound, error = services.send_client_message(self.client_obj, self.ops, body="x", force_channel=Channel.EMAIL)
        self.assertEqual((ok, outbound, error), (False, None, services.BLOCKED_AR))
        self.nothing_left_the_building()

    def test_unblocked_the_chat_sends_again(self):
        self.block(self.admin)
        self.block(self.admin, blocked=False)
        self.assertEqual(self.to_client(self.ops, body="welcome back").status_code, 200)
        self.text.assert_called_once()
