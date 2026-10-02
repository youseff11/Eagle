"""What the end-of-chat review of slices 3d and 3e found, pinned (privacy and security reviews, 2026-10-02).

* a client's own words forwarded into a room are read, afterwards, only by those who may read them;
* an id with a digit ``int()`` cannot read, a NUL, a huge body: refused, never a server error;
* no more than a handful of messages go out to a client in one forward;
* the notice of a forward names the room as the person it goes to sees it.
"""

import json

from django.urls import reverse

from . import services
from .models import ChatAttachment, ChatMessage, InboundMessage, Notification
from .tests_chat_lists import _json
from .tests_chat_react_forward import _Doors


class NotAnIdTests(_Doors):
    def test_a_unicode_digit_in_an_id_is_not_found_and_is_never_a_server_error(self):
        for uid in ("in-²", "in-①", "g1-²", "out-" + "٣" * 30):
            answer = self.react(self.ops, self.client_obj.code, uid)
            self.assertEqual(answer.status_code, 404, uid)
            answer = self.forward(self.ops, self.client_obj.code, f"u{self.lead.pk}", uids=[uid])
            self.assertEqual(answer.status_code, 400, uid)
        self.assertFalse(ChatMessage.objects.filter(forwarded=True).exists())

    def test_the_classic_door_does_not_fail_on_one_either(self):
        answer = self.browser(self.ops).post(
            reverse("dashboard:api_chat_forward"),
            {"source": self.client_obj.code, "target": f"u{self.lead.pk}", "uids": "in-²", "files": "²,1"},
        )
        self.assertEqual(answer.status_code, 400)


class BodyShapeTests(_Doors):
    def test_a_nul_in_any_text_is_refused_before_it_reaches_the_database(self):
        for body in (
            {"source": self.client_obj.code, "uid": "in-1\x00", "kind": "like"},
            {"source": "CL\x00", "uid": "in-1", "kind": "like"},
        ):
            answer = self.post("v1_chat_react", self.ops, body)
            self.assertEqual((answer.status_code, _json(answer)["error"]), (400, "bad_request"), body)
        answer = self.forward(self.ops, f"g{self.team.pk}", f"u{self.lead.pk}", uids=["g1-1"], note="a\x00b")
        self.assertEqual((answer.status_code, _json(answer)["error"]), (400, "bad_request"))
        # The codes that name a conversation and a message are read the same way.
        for source, target, uids in (
            (f"g{self.team.pk}\x00", f"u{self.lead.pk}", ["g1-1"]),
            (f"g{self.team.pk}", f"u{self.lead.pk}\x00", ["g1-1"]),
            (f"g{self.team.pk}", f"u{self.lead.pk}", ["g1-1\x00"]),
        ):
            answer = self.forward(self.ops, source, target, uids=uids)
            self.assertEqual((answer.status_code, _json(answer)["error"]), (400, "bad_request"), (source, target, uids))
        answer = self.post("v1_group_create", self.ops, {"title": "x\x00y", "members": [self.lead.pk]})
        self.assertEqual((answer.status_code, _json(answer)["error"]), (400, "bad_request"))

    def test_a_body_bigger_than_these_doors_ever_need_is_refused_unread(self):
        from . import api_v1

        huge = json.dumps({"source": "x" * (api_v1.MAX_JSON_BODY + 10), "uid": "in-1", "kind": "like"})
        for name, args in (("v1_chat_react", []), ("v1_chat_forward", []), ("v1_group_create", []), ("v1_group_add", [self.team.pk])):
            answer = self.browser(self.ops).post(reverse(f"dashboard:{name}", args=args), huge, content_type="application/json")
            self.assertEqual((answer.status_code, _json(answer)["error"]), (400, "bad_request"), name)


class WhatGoesOutToAClientTests(_Doors):
    def team_messages(self, count):
        return [ChatMessage.objects.create(room=self.team, sender=self.lead, body=f"thing {n}") for n in range(count)]

    def test_no_more_than_the_cap_goes_to_a_client_in_one_forward(self):
        from . import api_v1

        cap = api_v1.MAX_RELAYED_ITEMS
        made = self.team_messages(cap + 1)
        uids = [f"g{self.team.pk}-{m.pk}" for m in made]
        answer = self.forward(self.ops, f"g{self.team.pk}", self.client_obj.code, uids=uids)
        body = _json(answer)
        self.assertEqual((answer.status_code, body["error"]), (400, "refused"))
        self.assertIn(str(cap), body["message"])
        self.nothing_left_the_building()
        self.assertEqual(self.forward(self.ops, f"g{self.team.pk}", self.client_obj.code, uids=uids[:cap]).status_code, 200)
        self.assertEqual(self.text.call_count, cap)

    def test_nor_to_a_group_that_reaches_one(self):
        from . import api_v1

        made = self.team_messages(api_v1.MAX_RELAYED_ITEMS + 1)
        answer = self.forward(self.ops, f"g{self.team.pk}", f"g{self.group.pk}", uids=[f"g{self.team.pk}-{m.pk}" for m in made])
        self.assertEqual((answer.status_code, _json(answer)["error"]), (400, "refused"))
        self.nothing_left_the_building()
        self.assertFalse(self.group.messages.filter(forwarded=True).exists())

    def test_a_room_that_reaches_nobody_takes_as_many_as_the_door_allows(self):
        made = self.team_messages(30)
        answer = self.forward(self.ops, f"g{self.team.pk}", f"u{self.lead.pk}", uids=[f"g{self.team.pk}-{m.pk}" for m in made])
        self.assertEqual(answer.status_code, 200)
        self.assertEqual(self.private.messages.filter(forwarded=True).count(), 30)

    def test_the_classic_door_is_not_capped(self):
        made = self.team_messages(25)
        self.browser(self.ops).post(
            reverse("dashboard:api_chat_forward"),
            {"source": f"g{self.team.pk}", "target": self.client_obj.code, "uids": [f"g{self.team.pk}-{m.pk}" for m in made]},
        )
        self.assertEqual(self.text.call_count, 25)


class NoticeTests(_Doors):
    def test_a_forward_into_a_colleagues_chat_names_it_as_the_colleague_sees_it(self):
        self.forward(self.ops, f"g{self.team.pk}", f"u{self.lead.pk}", uids=[f"g{self.team.pk}-{self.talk_team.pk}"])
        note = Notification.objects.get(user=self.lead, title_en="Forwarded messages")
        self.assertIn(self.ops.short_name, note.body_en)
        self.assertNotIn(f"in {self.lead.short_name}", note.body_en)


class ForwardedClientWordsAreReadByTheOperationOnlyTests(_Doors):
    """A client's own words may be forwarded only into a room where everybody may read them - and the rule is a rule
    about who reads, so it holds when they are read, not only when they were written."""

    WORDS = "I am Ahmed, call 0100 123 4567"

    def setUp(self):
        super().setUp()
        InboundMessage.objects.filter(pk=self.heard.pk).update(body=self.WORDS)
        # A work group of two people who may read a client's words, and the client's words forwarded into it.
        self.inner, _error = services.create_team_group(self.ops, "Operation only", [self.ops2])
        answer = self.forward(self.ops, self.client_obj.code, f"g{self.inner.pk}", uids=[f"in-{self.heard.pk}"])
        self.assertEqual(answer.status_code, 200, answer.content)
        self.row = self.inner.messages.get(forwarded=True)

    def thread(self, user):
        return self.browser(user).get(reverse("dashboard:v1_group_messages", args=[self.inner.pk]))

    def forwarded_words(self, user):
        answer = self.thread(user)
        return answer, [m["body"] for m in _json(answer)["messages"] if m["forwarded"]]

    def test_those_who_were_in_the_room_read_it(self):
        for user in (self.ops, self.ops2, self.admin):
            _answer, bodies = self.forwarded_words(user)
            self.assertEqual(bodies, [self.WORDS], user.username)

    def test_somebody_added_afterwards_does_not(self):
        for latecomer in (self.tr, self.lead, self.hr, self.sales):
            self.inner.members.add(latecomer)
            answer, bodies = self.forwarded_words(latecomer)
            self.assertEqual(answer.status_code, 200, latecomer.username)
            self.assertEqual(bodies, [""], latecomer.username)
            self.assertNotIn(b"Ahmed", answer.content, latecomer.username)
            self.assertNotIn(b"0100", answer.content, latecomer.username)

    def test_nor_in_the_list_preview(self):
        self.inner.members.add(self.lead)
        rows = _json(self.browser(self.lead).get(reverse("dashboard:v1_chats") + "?type=groups"))["items"]
        row = next(r for r in rows if r["code"] == f"g{self.inner.pk}")
        self.assertNotIn("Ahmed", row["text"])
        self.assertNotIn("0100", row["text"])
        # The operation reads it there too.
        rows = _json(self.browser(self.ops2).get(reverse("dashboard:v1_chats") + "?type=groups"))["items"]
        self.assertIn("Ahmed", next(r for r in rows if r["code"] == f"g{self.inner.pk}")["text"])

    def test_nor_in_a_quote_of_it(self):
        self.inner.members.add(self.lead)
        ChatMessage.objects.create(room=self.inner, sender=self.ops, body="re that", reply_to=self.row)
        self.assertNotIn(b"Ahmed", self.thread(self.lead).content)
        self.assertIn(b"Ahmed", self.thread(self.ops2).content)

    def test_nor_through_the_older_room_endpoint(self):
        self.inner.members.add(self.lead)
        answer = self.browser(self.lead).get(reverse("dashboard:v1_room_messages", args=[self.inner.pk]))
        self.assertNotIn(b"Ahmed", answer.content)
        self.assertNotIn(b"0100", answer.content)

    def test_a_files_only_forward_keeps_its_files_for_everybody(self):
        # The files go to a translator; only the words stay behind.
        self.inner.members.add(self.tr)
        message = ChatMessage.objects.create(
            room=self.inner, sender=self.ops, body="", forwarded=True, origin_client_id=self.client_obj.pk,
        )
        ChatAttachment.objects.create(
            message=message, file="chat/doc.pdf", original_name="doc.pdf", size=1, origin_client_id=self.client_obj.pk,
        )
        self.assertIn(b"doc.pdf", self.thread(self.tr).content)

    def test_what_a_colleague_wrote_in_the_room_is_untouched(self):
        self.inner.members.add(self.tr)
        ChatMessage.objects.create(room=self.inner, sender=self.ops, body="plain internal words")
        self.assertIn(b"plain internal words", self.thread(self.tr).content)
