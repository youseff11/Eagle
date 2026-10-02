"""The chats screen in the new app, step 3d: reactions and forwarding (``/api/v1/chats/react/`` and ``.../forward/``).

Both doors are thin wrappers over what the classic page already calls (``services.toggle_reaction``,
``services.forward_messages``), so what is pinned here is the contract around them and the places a wrapper
can go wrong:

* who may react to, or forward from and to, what - every role, compared with the classic endpoint, which stays
  the specification, and then spelled out for the cases that decide a client's privacy;
* a message of another line (a Sales person's own number) cannot be reached by an id: not reacted to, not read
  back by forwarding it, not carried off as a file - the thread never lists it, so neither may an id;
* a 4xx is "nothing was written" - not even the note that goes with a forward; a forward that got somewhere and
  then failed is a 200 that says so, so the page does not offer to send again what has arrived;
* nothing is sent to a client by a reaction, and what a forward sends goes through the same send as everything else;
* the body is a small JSON object and nothing else.
"""

import json
from unittest import mock

from django.test import Client as DjangoClient
from django.urls import reverse

from . import services, whatsapp
from .models import (
    AuditLog, Channel, ChatMessage, ChatReaction, Client, InboundMessage, MessageAttachment, OutboundMessage, Role, User,
)
from .tests_chat_lists import _json
from .tests_chat_send import PHONE, _Send


class _Doors(_Send):
    def setUp(self):
        super().setUp()
        self.talk_team = ChatMessage.objects.create(room=self.team, sender=self.lead, body="team talk")
        self.talk_group = ChatMessage.objects.create(room=self.group, sender=self.ops, body="to the client group")
        self.talk_private = ChatMessage.objects.create(room=self.private, sender=self.lead, body="private line")
        sent = {"kind": OutboundMessage.Kind.CHAT, "channel": Channel.WHATSAPP, "status": OutboundMessage.Status.SENT}
        self.ours = OutboundMessage.objects.create(
            client=self.client_obj, body="we answered", created_by=self.ops, provider_id="wamid.ours", **sent,
        )
        self.sales_out = OutboundMessage.objects.create(
            client=self.client_obj, body="SALES LINE ONLY", created_by=self.sales, owner=self.sales,
            provider_id="wamid.salesout", **sent,
        )
        self.sales_file = MessageAttachment.objects.create(
            message=self.sales_heard, file="in/secret.pdf", original_name="secret.pdf", size=1,
        )
        self.company_file = MessageAttachment.objects.create(
            message=self.heard, file="in/quote.pdf", original_name="quote.pdf", size=1,
        )
        self.text.reset_mock()
        # A second person of the operation: a client's own words may travel to them.
        self.ops2 = User.objects.create_user("person_operation_b", password="pw", role=Role.OPERATION)

    # -- the doors ----------------------------------------------------------------
    def post(self, name, user, body=None, raw=None, content_type="application/json"):
        data = raw if raw is not None else json.dumps(body if body is not None else {})
        return self.browser(user).post(reverse(f"dashboard:{name}"), data, content_type=content_type)

    def react(self, user, source, uid, kind="like", **kw):
        return self.post("v1_chat_react", user, {"source": source, "uid": uid, "kind": kind}, **kw)

    def forward(self, user, source, target, uids=(), files=(), note="", **kw):
        body = {"source": source, "target": target, "uids": list(uids), "files": list(files), "note": note}
        return self.post("v1_chat_forward", user, body, **kw)

    def unseen(self, text):
        return not ChatMessage.objects.filter(body__contains=text).exists()


# ---------------------------------------------------------------------------------------------------------------------
# Reactions
# ---------------------------------------------------------------------------------------------------------------------

class ReactTests(_Doors):
    def cases(self):
        """Every kind of place a message can be: (name, source code, uid)."""
        return [
            ("client heard", self.client_obj.code, f"in-{self.heard.pk}"),
            ("client, ours", self.client_obj.code, f"out-{self.ours.pk}"),
            ("client, sales line out", self.client_obj.code, f"out-{self.sales_out.pk}"),
            ("sales client heard", self.sales_client.code, f"in-{self.sales_heard.pk}"),
            ("client group", f"g{self.group.pk}", f"g{self.group.pk}-{self.talk_group.pk}"),
            ("work group", f"g{self.team.pk}", f"g{self.team.pk}-{self.talk_team.pk}"),
            ("private line", f"u{self.lead.pk}", f"g{self.private.pk}-{self.talk_private.pk}"),
            ("private line, the other side", f"u{self.ops.pk}", f"g{self.private.pk}-{self.talk_private.pk}"),
        ]

    def test_giving_changing_and_taking_back_a_reaction(self):
        source, uid = self.client_obj.code, f"in-{self.heard.pk}"
        answer = self.react(self.ops, source, uid, "like")
        body = _json(answer)
        self.assertEqual(answer.status_code, 200)
        self.assertTrue(body["ok"])
        self.assertEqual(body["uid"], uid)
        self.assertEqual([(r["kind"], r["count"], r["mine"], r["who"]) for r in body["reactions"]],
                         [("like", 1, True, [self.ops.short_name])])
        # A different one replaces it: still one reaction of this person's.
        body = _json(self.react(self.ops, source, uid, "love"))
        self.assertEqual([(r["kind"], r["mine"]) for r in body["reactions"]], [("love", True)])
        self.assertEqual(ChatReaction.objects.filter(user=self.ops).count(), 1)
        # The same one again takes it back.
        body = _json(self.react(self.ops, source, uid, "love"))
        self.assertEqual(body["reactions"], [])
        self.assertEqual(ChatReaction.objects.count(), 0)

    def test_other_people_reactions_are_counted_and_not_mine(self):
        source, uid = self.client_obj.code, f"in-{self.heard.pk}"
        self.react(self.admin, source, uid, "like")
        body = _json(self.react(self.ops, source, uid, "like"))
        (entry,) = body["reactions"]
        self.assertEqual((entry["kind"], entry["count"], entry["mine"]), ("like", 2, True))
        self.assertEqual(sorted(entry["who"]), sorted([self.admin.short_name, self.ops.short_name]))
        # And from the other side the same row says "mine" for the other person.
        (theirs,) = _json(self.react(self.admin, source, uid, "like"))["reactions"]
        self.assertEqual((theirs["count"], theirs["mine"]), (1, False))

    def test_it_is_what_the_classic_endpoint_decides_for_every_role_and_every_place(self):
        # The classic endpoint is the specification: it answers 200 when the reaction was made, 400 when not.
        for name, source, uid in self.cases():
            for user in self.everyone:
                ChatReaction.objects.all().delete()
                old = self.browser(user).post(
                    reverse("dashboard:api_chat_react"), {"source": source, "uid": uid, "kind": "like"},
                )
                made_by_classic = old.status_code == 200
                ChatReaction.objects.all().delete()
                new = self.react(user, source, uid)
                self.assertEqual(new.status_code == 200, made_by_classic, (name, user.username))
                self.assertEqual(ChatReaction.objects.filter(user=user).exists(), made_by_classic, (name, user.username))
                if not made_by_classic:
                    self.assertEqual(new.status_code, 404, (name, user.username))
                    self.assertEqual(_json(new), {"ok": False, "error": "not_found"}, (name, user.username))

    def test_who_may_react_where_for_the_places_that_decide_a_clients_privacy(self):
        allowed = {
            # The operation and the admin answer clients; nobody else has a client conversation to react in.
            "client heard": {self.admin, self.ops, self.boss_sales},
            "client, ours": {self.admin, self.ops, self.boss_sales},
            "sales client heard": {self.admin, self.boss_sales},
            # A room: its members (and the admin, who may open any room but a private line).
            # A client group is for the people who talk to clients: the team leader seated in it by hand is refused.
            "client group": {self.admin, self.ops, self.boss_sales},
            "work group": {self.admin, self.ops, self.lead, self.tr, self.boss_sales},
            # A private line is read through the pair: each of the two reaches it by naming the other, and nobody
            # else does, not even the admin.
            "private line": {self.ops},
            "private line, the other side": {self.lead},
        }
        for name, source, uid in self.cases():
            if name == "client, sales line out":
                continue
            for user in self.everyone:
                answer = self.react(user, source, uid)
                self.assertEqual(answer.status_code == 200, user in allowed[name], (name, user.username))

    def test_a_message_of_another_line_cannot_be_reached_by_its_id(self):
        # The thread never lists the Sales person's own messages to the operation, so an id must not open them.
        for uid, source in (
            (f"out-{self.sales_out.pk}", self.client_obj.code),
            (f"in-{self.sales_heard.pk}", self.sales_client.code),
        ):
            answer = self.react(self.ops, source, uid)
            self.assertEqual(answer.status_code, 404, uid)
            self.assertFalse(ChatReaction.objects.exists(), uid)
        # The admin sees every line, and so may react to it.
        self.assertEqual(self.react(self.admin, self.client_obj.code, f"out-{self.sales_out.pk}").status_code, 200)

    def test_a_letter_of_ours_is_not_a_message_of_the_conversation(self):
        letter = OutboundMessage.objects.create(
            client=self.client_obj, kind=OutboundMessage.Kind.CHAT, channel=Channel.EMAIL, body="a letter",
            provider_id="<id@example.test>", status=OutboundMessage.Status.SENT,
        )
        self.assertEqual(self.react(self.admin, self.client_obj.code, f"out-{letter.pk}").status_code, 404)

    def test_an_id_from_another_conversation_finds_nothing(self):
        other = Client.objects.create(name="Somebody Else", phone="+201000000009")
        foreign = InboundMessage.objects.create(
            client=other, channel=Channel.WHATSAPP, body="OTHER", external_id="wamid.other.in",
        )
        stray = ChatMessage.objects.create(room=self.team, sender=self.lead, body="elsewhere")
        for source, uid in (
            (self.client_obj.code, f"in-{foreign.pk}"),
            (f"g{self.group.pk}", f"g{self.team.pk}-{stray.pk}"),
            (f"g{self.team.pk}", f"g{self.group.pk}-{self.talk_group.pk}"),
            (f"g{self.group.pk}", f"in-{self.heard.pk}"),
        ):
            answer = self.react(self.admin, source, uid)
            self.assertEqual(answer.status_code, 404, (source, uid))
        self.assertFalse(ChatReaction.objects.exists())

    def test_a_system_line_cannot_be_reacted_to(self):
        note = ChatMessage.objects.create(room=self.team, sender=None, body="Nour added Sam.", is_system=True)
        self.assertEqual(self.react(self.lead, f"g{self.team.pk}", f"g{self.team.pk}-{note.pk}").status_code, 404)

    def test_only_the_six_kinds_and_nothing_is_written_for_another(self):
        source, uid = self.client_obj.code, f"in-{self.heard.pk}"
        for kind in ("", "LIKE", "thumbs-up", "heart", "like;drop", "x" * 40):
            answer = self.react(self.ops, source, uid, kind)
            self.assertEqual((answer.status_code, _json(answer)["error"]), (400, "bad_kind"), repr(kind))
        self.assertFalse(ChatReaction.objects.exists())
        for kind in ("like", "love", "laugh", "wow", "sad", "done", " like "):
            ChatReaction.objects.all().delete()
            self.assertEqual(self.react(self.ops, source, uid, kind).status_code, 200, kind)
            self.assertEqual(ChatReaction.objects.get().kind, kind.strip())

    def test_the_body_is_a_json_object(self):
        source, uid = self.client_obj.code, f"in-{self.heard.pk}"
        form = "source=%s&uid=%s&kind=like" % (source, uid)
        for name, data, content_type in (
            ("a form", form, "application/x-www-form-urlencoded"),
            ("a list", "[1]", "application/json"),
            ("a string", '"like"', "application/json"),
            ("garbage", "{not json", "application/json"),
            ("numbers", json.dumps({"source": 5, "uid": 6, "kind": 7}), "application/json"),
            ("a nested value", json.dumps({"source": [source], "uid": uid, "kind": "like"}), "application/json"),
            ("a huge code", json.dumps({"source": "x" * 5000, "uid": uid, "kind": "like"}), "application/json"),
            ("a huge kind", json.dumps({"source": source, "uid": uid, "kind": "x" * 41}), "application/json"),
        ):
            answer = self.post("v1_chat_react", self.ops, raw=data, content_type=content_type)
            self.assertEqual((answer.status_code, _json(answer)["error"]), (400, "bad_request"), name)
        self.assertFalse(ChatReaction.objects.exists())

    def test_it_needs_a_session_a_post_and_the_csrf_token(self):
        url = reverse("dashboard:v1_chat_react")
        self.assertEqual(DjangoClient().post(url, "{}", content_type="application/json").status_code, 401)
        self.assertEqual(self.browser(self.ops).get(url).status_code, 405)
        strict = DjangoClient(enforce_csrf_checks=True)
        strict.force_login(self.ops)
        answer = strict.post(url, json.dumps({"source": self.client_obj.code, "uid": f"in-{self.heard.pk}", "kind": "like"}),
                             content_type="application/json")
        self.assertEqual(answer.status_code, 403)
        self.assertFalse(ChatReaction.objects.exists())

    def test_a_reaction_is_never_sent_to_anyone(self):
        for _name, source, uid in self.cases():
            self.react(self.admin, source, uid)
        self.nothing_left_the_building()
        self.assertFalse(OutboundMessage.objects.exclude(pk__in=[self.ours.pk, self.sales_out.pk]).exists())

    def test_the_answer_carries_no_name_or_number_of_the_client(self):
        answer = self.react(self.ops, self.client_obj.code, f"in-{self.heard.pk}")
        self.assertNotIn(b"Zebulon", answer.content)
        self.assertNotIn(PHONE.encode(), answer.content)

    def test_a_refusal_is_not_a_reason_to_write_to_the_audit_log_on_every_try(self):
        before = AuditLog.objects.count()
        for _ in range(3):
            self.react(self.sales, self.client_obj.code, f"in-{self.heard.pk}")
        self.assertEqual(AuditLog.objects.count(), before)


class ReactionRingsTheRoomTests(_Doors):
    """The page does not poll while the socket is open, so a reaction in a room has to ring it."""

    def test_a_reaction_to_a_room_message_rings_that_room_when_given_changed_and_taken_back(self):
        with mock.patch("dashboard.signals.realtime.push_room") as ring:
            self.react(self.lead, f"g{self.team.pk}", f"g{self.team.pk}-{self.talk_team.pk}", "like")
            self.assertEqual([c.args for c in ring.call_args_list], [(self.team.pk,)])
            self.react(self.lead, f"g{self.team.pk}", f"g{self.team.pk}-{self.talk_team.pk}", "love")
            self.assertEqual(ring.call_count, 2)
            self.react(self.lead, f"g{self.team.pk}", f"g{self.team.pk}-{self.talk_team.pk}", "love")
            self.assertEqual([c.args for c in ring.call_args_list], [(self.team.pk,)] * 3)

    def test_a_reaction_to_a_clients_own_message_has_no_room_to_ring(self):
        with mock.patch("dashboard.signals.realtime.push_room") as ring:
            self.react(self.ops, self.client_obj.code, f"in-{self.heard.pk}")
            self.react(self.ops, self.client_obj.code, f"out-{self.ours.pk}")
        ring.assert_not_called()

    def test_deleting_a_message_with_reactions_does_not_trip_over_them(self):
        ChatReaction.objects.create(user=self.lead, message=self.talk_team, kind="like")
        with mock.patch("dashboard.signals.realtime.push_room"):
            self.talk_team.delete()
        self.assertFalse(ChatReaction.objects.exists())


# ---------------------------------------------------------------------------------------------------------------------
# Forwarding
# ---------------------------------------------------------------------------------------------------------------------

class ForwardTests(_Doors):
    def test_a_message_goes_to_a_colleague_and_the_answer_says_where(self):
        answer = self.forward(self.ops, f"g{self.team.pk}", f"u{self.lead.pk}", uids=[f"g{self.team.pk}-{self.talk_team.pk}"],
                              note="have a look")
        body = _json(answer)
        self.assertEqual(answer.status_code, 200)
        self.assertEqual((body["ok"], body["delivered"], body["message"], body["code"]), (True, True, "", f"u{self.lead.pk}"))
        rows = list(self.private.messages.filter(is_system=False).order_by("id"))
        self.assertEqual([(m.body, m.forwarded) for m in rows], [("private line", False), ("have a look", False), ("team talk", True)])
        self.nothing_left_the_building()

    def test_a_clients_file_reaches_the_translator_without_the_clients_words(self):
        InboundMessage.objects.filter(pk=self.heard.pk).update(body="I am Ahmed, 0100 123 4567")
        answer = self.forward(self.ops, self.client_obj.code, f"u{self.tr.pk}", uids=[f"in-{self.heard.pk}"])
        self.assertEqual(answer.status_code, 200)
        room = services.staff_room(self.ops, self.tr)
        (forwarded,) = room.messages.filter(forwarded=True)
        self.assertEqual(forwarded.body, "")
        self.assertEqual([a.original_name for a in forwarded.attachments.all()], ["quote.pdf"])
        self.assertNotIn(b"Ahmed", answer.content)

    def test_words_that_cannot_travel_are_a_refusal_and_not_even_the_note_is_left_behind(self):
        # Only text, to a translator: nothing may go. The note that was to go with it must not stay in the room.
        words = InboundMessage.objects.create(
            client=self.client_obj, channel=Channel.WHATSAPP, body="call me on the number", external_id="wamid.in.2",
        )
        InboundMessage.objects.filter(pk=self.heard.pk).delete()
        answer = self.forward(self.ops, self.client_obj.code, f"u{self.tr.pk}", uids=[f"in-{words.pk}"], note="NOTE-LEFT-BEHIND")
        body = _json(answer)
        self.assertEqual((answer.status_code, body["ok"], body["error"]), (400, False, "refused"))
        self.assertTrue(body["message"])
        self.assertTrue(self.unseen("NOTE-LEFT-BEHIND"))
        self.assertTrue(self.unseen("call me on the number"))

    def test_a_clients_text_goes_only_where_everybody_may_read_it(self):
        for other, expected_body in ((self.ops2, "Please quote this"), (self.tr, ""), (self.lead, "")):
            ChatMessage.objects.filter(forwarded=True).delete()
            answer = self.forward(self.ops, self.client_obj.code, f"u{other.pk}", uids=[f"in-{self.heard.pk}"])
            self.assertEqual(answer.status_code, 200, other.username)
            room = services.staff_room(self.ops, other)
            (forwarded,) = room.messages.filter(forwarded=True)
            self.assertEqual(forwarded.body, expected_body, other.username)

    def test_to_a_client_it_is_sent_the_same_way_as_everything_else_and_only_their_own_things(self):
        answer = self.forward(self.ops, f"g{self.team.pk}", self.client_obj.code, uids=[f"g{self.team.pk}-{self.talk_team.pk}"],
                              note="Here it is")
        body = _json(answer)
        self.assertEqual((answer.status_code, body["delivered"], body["code"]), (200, True, self.client_obj.code))
        self.assertEqual([c.args[:2] for c in self.text.call_args_list], [(PHONE, "Here it is"), (PHONE, "team talk")])
        # Another client's thing never goes to this one.
        self.text.reset_mock()
        answer = self.forward(self.ops, self.sales_client.code, self.client_obj.code, uids=[f"in-{self.sales_heard.pk}"])
        self.assertEqual(answer.status_code, 400)
        self.assertFalse(self.text.called)

    def test_only_the_operation_and_the_admin_forward_into_a_clients_conversation(self):
        for user in (self.lead, self.tr, self.hr, self.sales, self.sales2):
            self.text.reset_mock()
            answer = self.forward(user, f"g{self.team.pk}", self.client_obj.code, uids=[f"g{self.team.pk}-{self.talk_team.pk}"])
            self.assertEqual(answer.status_code, 400, user.username)
            self.assertFalse(self.text.called, user.username)

    def test_a_forward_that_got_there_and_failed_is_a_200_that_says_so(self):
        # Into a group that reaches the client; the client's phone refuses what the relay sends on.
        self.text.side_effect = whatsapp.WhatsAppError("واتساب رجّع خطأ (400)", "WhatsApp returned an error (400)")
        answer = self.forward(self.ops, f"g{self.team.pk}", f"g{self.group.pk}", uids=[f"g{self.team.pk}-{self.talk_team.pk}"])
        body = _json(answer)
        self.assertEqual(answer.status_code, 200)
        self.assertEqual((body["ok"], body["delivered"]), (True, False))
        self.assertIn("مروحتش للعميل", body["message"])
        self.assertTrue(self.group.messages.filter(forwarded=True, body="team talk").exists())

    def test_a_client_who_got_the_first_of_two_is_not_told_nothing_was_sent(self):
        second = ChatMessage.objects.create(room=self.team, sender=self.lead, body="second thing")
        self.text.side_effect = ["wamid.1", whatsapp.WhatsAppError("واتساب رجّع خطأ (131)", "WhatsApp error (131)")]
        answer = self.forward(
            self.ops, f"g{self.team.pk}", self.client_obj.code,
            uids=[f"g{self.team.pk}-{self.talk_team.pk}", f"g{self.team.pk}-{second.pk}"],
        )
        body = _json(answer)
        self.assertEqual((answer.status_code, body["ok"], body["delivered"]), (200, True, False))
        self.assertTrue(body["message"])
        self.assertEqual(self.text.call_count, 2)

    def test_a_failure_before_anything_reached_the_client_is_a_refusal(self):
        self.text.side_effect = whatsapp.WhatsAppError("واتساب رجّع خطأ (131)", "WhatsApp error (131)")
        answer = self.forward(self.ops, f"g{self.team.pk}", self.client_obj.code, uids=[f"g{self.team.pk}-{self.talk_team.pk}"])
        self.assertEqual((answer.status_code, _json(answer)["error"]), (400, "refused"))

    def test_the_words_of_a_failure_carry_no_number_for_someone_who_may_not_know_it(self):
        self.text.side_effect = whatsapp.WhatsAppError(
            "واتساب رجّع خطأ (400): +201234567890 مش مسجل", "WhatsApp returned an error (400): +201234567890 is not registered",
        )
        answer = self.forward(self.ops, f"g{self.team.pk}", f"g{self.group.pk}", uids=[f"g{self.team.pk}-{self.talk_team.pk}"])
        self.assertNotIn(b"201234567890", answer.content)
        self.assertFalse(ChatMessage.objects.filter(relay_error__contains="201234567890").exists())

    def test_a_message_of_another_line_cannot_be_read_back_by_forwarding_it(self):
        # The id of the Sales person's own message to the same client: the thread does not list it to the
        # operation, so forwarding it to a colleague of the operation (who may read a client's words) would be
        # reading it.
        answer = self.forward(self.ops, self.client_obj.code, f"u{self.ops2.pk}", uids=[f"out-{self.sales_out.pk}"])
        self.assertEqual((answer.status_code, _json(answer)["error"]), (400, "refused"))
        self.assertTrue(self.unseen("SALES LINE ONLY"))
        self.assertNotIn(b"SALES LINE ONLY", answer.content)
        # The admin sees every line and may.
        self.assertEqual(self.forward(self.admin, self.client_obj.code, f"u{self.ops2.pk}", uids=[f"out-{self.sales_out.pk}"]).status_code, 200)
        self.assertFalse(self.unseen("SALES LINE ONLY"))

    def test_a_file_of_another_line_cannot_be_carried_off_by_its_id(self):
        answer = self.forward(self.ops, self.sales_client.code, f"u{self.tr.pk}", files=[self.sales_file.pk])
        self.assertEqual((answer.status_code, _json(answer)["error"]), (400, "refused"))
        self.assertFalse(ChatMessage.objects.filter(forwarded=True).exists())
        # The company line's own file goes, and the admin may take the Sales person's.
        self.assertEqual(self.forward(self.ops, self.client_obj.code, f"u{self.tr.pk}", files=[self.company_file.pk]).status_code, 200)
        self.assertEqual(self.forward(self.admin, self.sales_client.code, f"u{self.tr.pk}", files=[self.sales_file.pk]).status_code, 200)

    def test_a_file_of_a_message_the_rate_rule_hides_is_not_for_the_operation(self):
        hidden = InboundMessage.objects.create(
            client=self.client_obj, channel=Channel.WHATSAPP, body="a rate", external_id="wamid.rate", is_rate_blocked=True,
        )
        rated = MessageAttachment.objects.create(message=hidden, file="in/rates.pdf", original_name="rates.pdf", size=1)
        self.assertEqual(self.forward(self.ops, self.client_obj.code, f"u{self.tr.pk}", files=[rated.pk]).status_code, 400)
        self.assertEqual(self.forward(self.admin, self.client_obj.code, f"u{self.tr.pk}", files=[rated.pk]).status_code, 200)

    def test_what_may_be_forwarded_from_where_is_what_the_classic_endpoint_decides(self):
        sources = (
            (self.client_obj.code, f"in-{self.heard.pk}"),
            (self.sales_client.code, f"in-{self.sales_heard.pk}"),
            (f"g{self.group.pk}", f"g{self.group.pk}-{self.talk_group.pk}"),
            (f"g{self.team.pk}", f"g{self.team.pk}-{self.talk_team.pk}"),
            (f"u{self.lead.pk}", f"g{self.private.pk}-{self.talk_private.pk}"),
        )
        for source, uid in sources:
            for user in self.everyone:
                for target in (f"u{self.hr.pk}", f"g{self.team.pk}"):
                    ChatMessage.objects.filter(forwarded=True).delete()
                    old = self.browser(user).post(
                        reverse("dashboard:api_chat_forward"), {"source": source, "target": target, "uids": uid},
                    )
                    classic = ChatMessage.objects.filter(forwarded=True).count()
                    ChatMessage.objects.filter(forwarded=True).delete()
                    new = self.forward(user, source, target, uids=[uid])
                    self.assertEqual(ChatMessage.objects.filter(forwarded=True).count(), classic, (source, user.username, target))
                    self.assertEqual(new.status_code == 200, old.status_code == 200, (source, user.username, target))

    def test_a_conversation_that_is_not_yours_is_not_a_place_to_forward_from_or_to(self):
        uid = f"g{self.team.pk}-{self.talk_team.pk}"
        # A room the person is not in, as the source.
        self.assertEqual(self.forward(self.sales, f"g{self.team.pk}", f"u{self.lead.pk}", uids=[uid]).status_code, 400)
        self.assertEqual(
            self.forward(self.sales, f"u{self.lead.pk}", f"u{self.hr.pk}", uids=[f"g{self.private.pk}-{self.talk_private.pk}"]).status_code,
            400,
        )
        self.assertFalse(ChatMessage.objects.filter(forwarded=True).exists())
        # And as the target: a room the person is not in, oneself, somebody who is gone, a code that is none.
        for target in (f"g{self.private.pk}", f"u{self.lead.pk}", "u999999", "g999999", "CL-9999", "nonsense"):
            answer = self.forward(self.lead, f"g{self.team.pk}", target, uids=[uid])
            expected = 200 if target == f"g{self.private.pk}" else 400
            self.assertEqual(answer.status_code, expected, target)
        self.assertEqual(
            ChatMessage.objects.filter(forwarded=True).count(), 1,
            "only the forward that was allowed left anything behind",
        )

    def test_the_same_message_named_twice_goes_once(self):
        uid = f"g{self.team.pk}-{self.talk_team.pk}"
        self.forward(self.ops, f"g{self.team.pk}", f"u{self.lead.pk}", uids=[uid, uid, uid])
        self.assertEqual(self.private.messages.filter(forwarded=True).count(), 1)

    def test_forwarding_does_not_write_anything_to_the_source(self):
        before = ChatMessage.objects.filter(room=self.team).count()
        self.forward(self.ops, f"g{self.team.pk}", f"u{self.lead.pk}", uids=[f"g{self.team.pk}-{self.talk_team.pk}"])
        self.assertEqual(ChatMessage.objects.filter(room=self.team).count(), before)

    def test_the_body_is_a_small_json_object_and_nothing_is_written_for_a_bad_one(self):
        good = {"source": f"g{self.team.pk}", "target": f"u{self.lead.pk}", "uids": [f"g{self.team.pk}-{self.talk_team.pk}"]}
        cases = {
            "a form": ("source=a&target=b&uids=c", "application/x-www-form-urlencoded"),
            "a list": ("[]", "application/json"),
            "garbage": ("{", "application/json"),
            "uids not a list": (json.dumps({**good, "uids": "g1-1"}), "application/json"),
            "a uid that is a number": (json.dumps({**good, "uids": [5]}), "application/json"),
            "a uid that is huge": (json.dumps({**good, "uids": ["g" * 41]}), "application/json"),
            "too many uids": (json.dumps({**good, "uids": [f"in-{n}" for n in range(1, 102)]}), "application/json"),
            "files not a list": (json.dumps({**good, "files": 3}), "application/json"),
            "a file that is not an id": (json.dumps({**good, "uids": [], "files": ["x"]}), "application/json"),
            "a file that is a float": (json.dumps({**good, "uids": [], "files": [1.5]}), "application/json"),
            "a file that is a bool": (json.dumps({**good, "uids": [], "files": [True]}), "application/json"),
            "a file id too big": (json.dumps({**good, "uids": [], "files": [2 ** 70]}), "application/json"),
            "a note that is a list": (json.dumps({**good, "note": ["x"]}), "application/json"),
            "a note that is too long": (json.dumps({**good, "note": "n" * 2001}), "application/json"),
            "a target that is a number": (json.dumps({**good, "target": 5}), "application/json"),
            "no target": (json.dumps({"source": good["source"], "uids": good["uids"]}), "application/json"),
        }
        for name, (data, content_type) in cases.items():
            answer = self.post("v1_chat_forward", self.ops, raw=data, content_type=content_type)
            self.assertEqual((answer.status_code, _json(answer)["error"]), (400, "bad_request"), name)
        self.assertFalse(ChatMessage.objects.filter(forwarded=True).exists())

    def test_nothing_picked_is_nothing_to_forward(self):
        answer = self.forward(self.ops, f"g{self.team.pk}", f"u{self.lead.pk}", note="just a note")
        self.assertEqual((answer.status_code, _json(answer)["error"]), (400, "empty"))
        self.assertTrue(self.unseen("just a note"))

    def test_it_needs_a_session_a_post_and_the_csrf_token(self):
        url = reverse("dashboard:v1_chat_forward")
        self.assertEqual(DjangoClient().post(url, "{}", content_type="application/json").status_code, 401)
        self.assertEqual(self.browser(self.ops).get(url).status_code, 405)
        strict = DjangoClient(enforce_csrf_checks=True)
        strict.force_login(self.ops)
        body = {"source": f"g{self.team.pk}", "target": f"u{self.lead.pk}", "uids": [f"g{self.team.pk}-{self.talk_team.pk}"]}
        self.assertEqual(strict.post(url, json.dumps(body), content_type="application/json").status_code, 403)
        self.assertFalse(ChatMessage.objects.filter(forwarded=True).exists())

    def test_the_answer_never_carries_the_clients_name_or_number(self):
        answer = self.forward(self.ops, self.client_obj.code, f"u{self.tr.pk}", uids=[f"in-{self.heard.pk}"], note="fyi")
        self.assertNotIn(b"Zebulon", answer.content)
        self.assertNotIn(PHONE.encode(), answer.content)

    def test_the_people_in_the_room_are_told_and_only_those_who_may_open_it(self):
        from .models import Notification

        self.forward(self.ops, f"g{self.team.pk}", f"u{self.tr.pk}", uids=[f"g{self.team.pk}-{self.talk_team.pk}"])
        self.assertTrue(Notification.objects.filter(user=self.tr, title_en="Forwarded messages").exists())
        self.assertFalse(Notification.objects.filter(user=self.ops, title_en="Forwarded messages").exists())
