"""Muting a conversation and taking back a message (``/api/v1/chats/mute/`` and ``.../unsend/``).

Mute is one person's own: nothing changes for anybody else. It silences the notification and the sound a new message
makes, keeps the conversation in the list with its own unread number, and leaves it out of the sidebar badge. A mention
still gets through.

Unsend is for what stayed inside - a work group or a colleague's chat - and only for its sender. What was relayed to a
client (a client group, a client's own chat), what is work on a task, and what carries a client's words or files is final:
nothing on the client's phone can be deleted from here, and the thread must not say it was.
"""

import json

from django.core.files.base import ContentFile
from django.urls import reverse

from . import services
from .models import (
    AuditLog, Channel, ChatAttachment, ChatMessage, ChatMute, ChatReaction, InboundMessage, Notification, Role, Task, User,
)
from .tests_chat_lists import _json
from .tests_chat_send import PHONE, _Send


class _Doors(_Send):
    def post(self, name, user, body):
        return self.browser(user).post(reverse(f"dashboard:{name}"), json.dumps(body), content_type="application/json")

    def mute(self, user, source, muted=True):
        return self.post("v1_chat_mute", user, {"source": source, "muted": muted})

    def unsend(self, user, source, uid):
        return self.post("v1_chat_unsend", user, {"source": source, "uid": uid})

    def thread(self, user, room):
        answer = self.browser(user).get(reverse("dashboard:v1_group_messages", args=[room.pk]))
        return {m["uid"]: m for m in _json(answer)["messages"]}

    def rows(self, user, kind="groups"):
        answer = self.browser(user).get(reverse("dashboard:v1_chats"), {"type": kind})
        return {r["code"]: r for r in _json(answer)["items"]}

    def say(self, user, room, body, **extra):
        return ChatMessage.objects.create(room=room, sender=user, body=body, **extra)


class MuteTests(_Doors):
    def test_a_room_a_colleagues_chat_and_a_client_can_each_be_muted_and_un_muted(self):
        for source in (f"g{self.team.pk}", f"u{self.lead.pk}", self.client_obj.code):
            answer = self.mute(self.ops, source)
            self.assertEqual((answer.status_code, _json(answer)["muted"]), (200, True), source)
        self.assertEqual(ChatMute.objects.filter(user=self.ops).count(), 3)
        # Twice is the same as once.
        self.mute(self.ops, f"g{self.team.pk}")
        self.assertEqual(ChatMute.objects.filter(user=self.ops).count(), 3)
        self.mute(self.ops, f"g{self.team.pk}", muted=False)
        self.assertEqual(ChatMute.objects.filter(user=self.ops).count(), 2)

    def test_it_is_this_persons_alone(self):
        self.mute(self.ops, f"g{self.team.pk}")
        self.assertFalse(ChatMute.objects.filter(user=self.lead).exists())
        self.assertFalse(self.rows(self.lead)[f"g{self.team.pk}"]["muted"])
        self.assertTrue(self.rows(self.ops)[f"g{self.team.pk}"]["muted"])

    def test_a_conversation_this_person_may_not_open_cannot_be_muted(self):
        # The translator is in the work group but never in a client's, and a colleague's private line is not theirs.
        self.assertEqual(self.mute(self.tr, self.client_obj.code).status_code, 404)
        self.assertEqual(self.mute(self.tr, f"g{self.private.pk}").status_code, 404)
        self.assertEqual(self.mute(self.hr, f"g{self.team.pk}").status_code, 404)
        self.assertEqual(self.mute(self.ops, "g999999").status_code, 404)
        self.assertEqual(ChatMute.objects.count(), 0)

    def test_a_bad_body_is_refused(self):
        for body in ({"source": "g1"}, {"source": "g1", "muted": "yes"}, {"muted": True}, {"source": 5, "muted": True}):
            self.assertEqual(self.post("v1_chat_mute", self.ops, body).status_code, 400, body)
        self.assertEqual(self.browser(None).post(reverse("dashboard:v1_chat_mute"), "{}", content_type="application/json").status_code, 401)

    def test_a_muted_group_makes_no_notification_for_the_one_who_muted_it_and_still_does_for_the_rest(self):
        self.mute(self.tr, f"g{self.team.pk}")
        self.to_group(self.ops, self.team, body="hello team")
        self.assertFalse(Notification.objects.filter(user=self.tr).exists())
        self.assertTrue(Notification.objects.filter(user=self.lead, title_en="New chat message").exists())

    def test_a_mention_still_reaches_the_one_who_muted(self):
        self.mute(self.tr, f"g{self.team.pk}")
        self.browser(self.ops).post(
            reverse("dashboard:v1_group_send", args=[self.team.pk]),
            {"body": f"@{self.tr.short_name} look", "mentions": str(self.tr.pk)},
        )
        self.assertTrue(Notification.objects.filter(user=self.tr, title_en__endswith="mentioned you").exists())

    def test_a_muted_clients_new_message_does_not_ring_the_one_who_muted_it(self):
        other = User.objects.create_user("person_operation_b", password="pw", role=Role.OPERATION)
        self.mute(self.ops, self.client_obj.code)
        services.ingest_message(channel=Channel.WHATSAPP, body="a new one", sender_identity=PHONE, external_id="wamid.new.1")
        self.assertTrue(InboundMessage.objects.filter(external_id="wamid.new.1").exists())
        self.assertFalse(Notification.objects.filter(user=self.ops, title_en="New client message").exists())
        # The colleague who did not mute it is rung as before.
        self.assertTrue(Notification.objects.filter(user=other, title_en="New client message").exists())

    def test_a_muted_conversation_keeps_its_number_in_the_list_but_not_in_the_badge(self):
        self.say(self.lead, self.team, "one")
        self.say(self.lead, self.team, "two")
        self.say(self.lead, self.private, "private one")
        total, tabs = services.unread_chat_breakdown(self.ops)
        self.mute(self.ops, f"g{self.team.pk}")
        quiet_total, quiet_tabs = services.unread_chat_breakdown(self.ops)
        self.assertEqual((total - quiet_total, tabs["groups"] - quiet_tabs["groups"]), (2, 1))
        self.assertEqual(quiet_tabs["staff"], tabs["staff"])
        self.assertEqual(self.rows(self.ops)[f"g{self.team.pk}"]["unread"], 2)

    def test_the_thread_header_row_says_it_too(self):
        self.mute(self.ops, f"g{self.team.pk}")
        answer = self.browser(self.ops).get(reverse("dashboard:v1_group_messages", args=[self.team.pk]))
        self.assertTrue(_json(answer)["client"]["muted"])


class UnsendTests(_Doors):
    def uid(self, room, message):
        return f"g{room.pk}-{message.pk}"

    def test_the_sender_takes_back_a_message_of_a_work_group_and_it_is_gone_for_everybody(self):
        mine = self.say(self.ops, self.team, "a secret remark")
        ChatReaction.objects.create(user=self.lead, kind="like", message=mine)
        answer = self.unsend(self.ops, f"g{self.team.pk}", self.uid(self.team, mine))
        self.assertEqual((answer.status_code, _json(answer)["ok"]), (200, True))
        mine.refresh_from_db()
        self.assertEqual((mine.body, mine.is_unsent), ("", True))
        self.assertFalse(ChatReaction.objects.filter(message=mine).exists())
        for viewer in (self.ops, self.lead, self.tr):
            entry = self.thread(viewer, self.team)[self.uid(self.team, mine)]
            self.assertEqual(
                (entry["unsent"], entry["body"], entry["files"], entry["reactions"], entry["can_unsend"]), (True, "", [], [], False),
            )
        raw = self.browser(self.lead).get(reverse("dashboard:v1_group_messages", args=[self.team.pk])).content.decode()
        self.assertNotIn("secret remark", raw)

    def test_a_colleagues_chat_works_the_same(self):
        mine = self.say(self.ops, self.private, "between us")
        self.assertEqual(self.unsend(self.ops, f"u{self.lead.pk}", self.uid(self.private, mine)).status_code, 200)
        mine.refresh_from_db()
        self.assertTrue(mine.is_unsent)

    def test_the_files_go_too_and_a_stored_file_a_forward_still_holds_stays(self):
        mine = self.say(self.ops, self.team, "with files")
        kept = ChatAttachment.objects.create(message=mine, file=ContentFile(b"x", name="kept.txt"), original_name="kept.txt")
        alone = ChatAttachment.objects.create(message=mine, file=ContentFile(b"y", name="alone.txt"), original_name="alone.txt")
        elsewhere = self.say(self.lead, self.private, "forwarded copy", forwarded=True)
        ChatAttachment.objects.create(message=elsewhere, file=kept.file.name, original_name="kept.txt")
        storage, alone_name, kept_name = alone.file.storage, alone.file.name, kept.file.name
        self.addCleanup(lambda: storage.exists(kept_name) and storage.delete(kept_name))
        self.unsend(self.ops, f"g{self.team.pk}", self.uid(self.team, mine))
        self.assertFalse(ChatAttachment.objects.filter(message=mine).exists())
        self.assertFalse(storage.exists(alone_name))
        self.assertTrue(storage.exists(kept_name))
        # The copy somebody forwarded keeps its words and its file.
        self.assertEqual(ChatAttachment.objects.filter(message=elsewhere).count(), 1)

    def test_somebody_elses_message_cannot_be_taken_back_and_nothing_changes(self):
        theirs = self.say(self.lead, self.team, "the leader said")
        answer = self.unsend(self.ops, f"g{self.team.pk}", self.uid(self.team, theirs))
        self.assertEqual((answer.status_code, _json(answer)["error"]), (403, "not_allowed"))
        theirs.refresh_from_db()
        self.assertEqual((theirs.body, theirs.unsent_at), ("the leader said", None))
        # Not even the admin takes back what somebody else wrote.
        self.assertEqual(self.unsend(self.admin, f"g{self.team.pk}", self.uid(self.team, theirs)).status_code, 403)

    def test_what_reached_or_could_reach_a_client_is_final(self):
        relayed = self.say(self.ops, self.group, "to the client group")
        answer = self.unsend(self.ops, f"g{self.group.pk}", self.uid(self.group, relayed))
        self.assertEqual((answer.status_code, _json(answer)["error"]), (403, "not_allowed"))
        relayed.refresh_from_db()
        self.assertEqual((relayed.body, relayed.unsent_at), ("to the client group", None))
        self.assertFalse(self.thread(self.ops, self.group)[self.uid(self.group, relayed)]["can_unsend"])

    def test_work_on_a_task_and_a_clients_words_are_final(self):
        task = Task.objects.create(client=self.client_obj, title="Job", created_by=self.ops)
        work = self.say(self.ops, self.team, "handed in", task=task)
        words = self.say(self.ops, self.team, "client words", origin_client=self.client_obj)
        filed = self.say(self.ops, self.team, "a client's file")
        ChatAttachment.objects.create(
            message=filed, file=ContentFile(b"z", name="theirs.txt"), original_name="theirs.txt", origin_client=self.client_obj,
        )
        self.addCleanup(lambda: filed.attachments.first().file.storage.delete(filed.attachments.first().file.name))
        for message in (work, words, filed):
            answer = self.unsend(self.ops, f"g{self.team.pk}", self.uid(self.team, message))
            self.assertEqual(answer.status_code, 403, message.body)
            message.refresh_from_db()
            self.assertIsNone(message.unsent_at)

    def test_a_system_line_is_not_a_message_to_take_back(self):
        line = ChatMessage.objects.create(room=self.team, sender=self.ops, body="x", is_system=True)
        self.assertEqual(self.unsend(self.ops, f"g{self.team.pk}", self.uid(self.team, line)).status_code, 404)

    def test_taking_back_twice_and_a_wrong_conversation_find_nothing_to_do(self):
        mine = self.say(self.ops, self.team, "once")
        self.unsend(self.ops, f"g{self.team.pk}", self.uid(self.team, mine))
        self.assertEqual(self.unsend(self.ops, f"g{self.team.pk}", self.uid(self.team, mine)).status_code, 403)
        other = self.say(self.ops, self.team, "in the right room")
        # The uid names the room it is in: another room's code does not reach it.
        self.assertEqual(self.unsend(self.ops, f"g{self.private.pk}", self.uid(self.team, other)).status_code, 404)
        self.assertEqual(self.unsend(self.hr, f"g{self.team.pk}", self.uid(self.team, other)).status_code, 404)
        self.assertEqual(self.unsend(self.ops, self.client_obj.code, "in-1").status_code, 404)
        other.refresh_from_db()
        self.assertEqual(other.body, "in the right room")

    def test_it_is_written_to_the_audit_log_without_the_words(self):
        mine = self.say(self.ops, self.team, "do not log this sentence")
        self.unsend(self.ops, f"g{self.team.pk}", self.uid(self.team, mine))
        entry = AuditLog.objects.get(action="chat.unsend")
        self.assertEqual((entry.actor_id, entry.target), (self.ops.pk, self.uid(self.team, mine)))
        self.assertNotIn("sentence", f"{entry.target}{entry.detail}")

    def test_a_reply_that_quotes_it_shows_no_words_and_it_cannot_be_replied_to_afterwards(self):
        mine = self.say(self.ops, self.team, "the original")
        reply = self.say(self.lead, self.team, "my answer", reply_to=mine)
        self.unsend(self.ops, f"g{self.team.pk}", self.uid(self.team, mine))
        self.assertEqual(self.thread(self.lead, self.team)[self.uid(self.team, reply)]["quote"], "")
        self.browser(self.lead).post(
            reverse("dashboard:v1_group_send", args=[self.team.pk]), {"body": "late", "reply_uid": self.uid(self.team, mine)},
        )
        self.assertIsNone(ChatMessage.objects.get(room=self.team, body="late").reply_to_id)

    def test_the_list_snippet_says_it_was_deleted_when_it_was_the_last_message(self):
        mine = self.say(self.ops, self.team, "last words")
        self.unsend(self.ops, f"g{self.team.pk}", self.uid(self.team, mine))
        self.assertEqual(self.rows(self.lead)[f"g{self.team.pk}"]["text"], services.UNSENT_SNIPPET_AR)

    def test_a_forward_of_a_taken_back_message_carries_nothing(self):
        mine = self.say(self.ops, self.team, "to be forwarded")
        self.unsend(self.ops, f"g{self.team.pk}", self.uid(self.team, mine))
        answer = self.post(
            "v1_chat_forward", self.ops,
            {"source": f"g{self.team.pk}", "target": f"u{self.lead.pk}", "uids": [self.uid(self.team, mine)], "files": [], "note": ""},
        )
        self.assertEqual(answer.status_code, 400)

    def test_the_sender_sees_the_button_and_nobody_else_does(self):
        mine = self.say(self.ops, self.team, "mine")
        self.assertTrue(self.thread(self.ops, self.team)[self.uid(self.team, mine)]["can_unsend"])
        self.assertFalse(self.thread(self.lead, self.team)[self.uid(self.team, mine)]["can_unsend"])
