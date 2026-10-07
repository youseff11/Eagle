"""Mentioning a colleague in a work group (``ChatMessage.mentions``, ``services.mention_targets``).

The page sends the words and the ids of the people it picked from the list after an "@": a name is not unique, so the
words alone cannot say which Mohamed was meant. The server pings a person only when all of this holds - their id was
sent, they are in the room and may open it, they are not the sender, and "@name" is still in the words. Nothing is
ever mentioned in a client's room (what is typed there is relayed word for word, and an "@name" would put a
colleague's name in front of the client) nor in a chat of two.
"""

import json

from django.urls import reverse

from . import services
from .models import ChatMessage, Notification, Role, User
from .tests_chat_lists import _json
from .tests_chat_send import _Send

PINGED = "mentioned you"


class _Mentions(_Send):
    def pinged(self, user):
        return Notification.objects.filter(user=user, title_en__endswith=PINGED)

    def ordinary(self, user):
        return Notification.objects.filter(user=user, title_en="New chat message")

    def say(self, user, body, ids, room=None):
        data = {"body": body}
        if isinstance(ids, (list, tuple)):
            data["mentions"] = ",".join(str(one) for one in ids)
        elif ids is not None:
            data["mentions"] = str(ids)
        return self.to_group(user, room or self.team, **data)

    def thread(self, user, room=None):
        answer = self.browser(user).get(reverse("dashboard:v1_group_messages", args=[(room or self.team).pk]))
        return _json(answer)["messages"]

    def last(self, room=None):
        return (room or self.team).messages.order_by("-id").first()


class PingTests(_Mentions):
    def test_the_one_named_is_pinged_by_name_with_the_sound_and_the_rest_get_the_ordinary_line(self):
        answer = self.say(self.ops, f"@{self.tr.short_name} please look", self.tr.pk)
        self.assertEqual(answer.status_code, 200)

        ping = self.pinged(self.tr).get()
        self.assertEqual(ping.title_en, f"{self.ops.short_name} mentioned you")
        self.assertTrue(ping.sound)
        self.assertIn("please look", ping.body_en)
        self.assertEqual(ping.url, f"/ops/chats/g/{self.team.pk}/")
        # One line each: the one named is not also told the ordinary way.
        self.assertFalse(self.ordinary(self.tr).exists())
        self.assertTrue(self.ordinary(self.lead).exists())
        self.assertFalse(self.pinged(self.lead).exists())
        # And the sender is told nothing.
        self.assertFalse(Notification.objects.filter(user=self.ops).exists())

    def test_several_people_are_each_pinged_once(self):
        self.say(self.ops, f"@{self.tr.short_name} and @{self.lead.short_name}", [self.tr.pk, self.lead.pk])
        self.assertEqual(self.pinged(self.tr).count(), 1)
        self.assertEqual(self.pinged(self.lead).count(), 1)
        self.assertEqual(set(self.last().mentions.values_list("pk", flat=True)), {self.tr.pk, self.lead.pk})

    def test_the_thread_says_whom_a_message_pinged_and_whether_it_pinged_the_one_looking(self):
        self.say(self.ops, f"@{self.tr.short_name} look", self.tr.pk)
        for viewer, expect_me in ((self.tr, True), (self.lead, False), (self.ops, False)):
            message = self.thread(viewer)[-1]
            self.assertEqual(message["mentions"], [{"id": self.tr.pk, "name": self.tr.short_name}], viewer.username)
            self.assertEqual(message["mentions_me"], expect_me, viewer.username)

    def test_the_answer_to_the_send_carries_it_too(self):
        answer = self.say(self.ops, f"@{self.tr.short_name} look", self.tr.pk)
        message = _json(answer)["messages"][-1]
        self.assertEqual([one["id"] for one in message["mentions"]], [self.tr.pk])

    def test_a_message_with_no_mention_has_none(self):
        self.say(self.ops, "no one in particular", None)
        message = self.thread(self.tr)[-1]
        self.assertEqual((message["mentions"], message["mentions_me"]), ([], False))
        self.assertFalse(self.pinged(self.tr).exists())


class WhoIsPingedTests(_Mentions):
    def test_the_name_in_the_words_without_the_id_pings_nobody(self):
        # The id comes from the list the page showed; words alone cannot say which person of that name was meant.
        self.say(self.ops, f"@{self.tr.short_name} look", None)
        self.assertFalse(self.pinged(self.tr).exists())
        self.assertEqual(self.last().mentions.count(), 0)
        self.assertTrue(self.ordinary(self.tr).exists())

    def test_the_id_without_the_name_in_the_words_pings_nobody(self):
        # Taking the "@name" out of a message takes the ping with it.
        self.say(self.ops, "never mind", self.tr.pk)
        self.assertFalse(self.pinged(self.tr).exists())
        self.assertEqual(self.last().mentions.count(), 0)
        self.assertTrue(self.ordinary(self.tr).exists())

    def test_a_name_is_a_whole_word_and_not_the_start_of_a_longer_one(self):
        self.say(self.ops, f"@{self.tr.short_name}han look", self.tr.pk)
        self.assertFalse(self.pinged(self.tr).exists())
        self.say(self.ops, f"look@{self.tr.short_name}", self.tr.pk)
        self.assertFalse(self.pinged(self.tr).exists())
        self.say(self.ops, f"hi @{self.tr.short_name}, look", self.tr.pk)
        self.assertEqual(self.pinged(self.tr).count(), 1)

    def test_somebody_who_is_not_in_the_group_is_never_pinged_whatever_id_is_sent(self):
        self.say(self.ops, f"@{self.hr.short_name} look", self.hr.pk)
        self.assertFalse(Notification.objects.filter(user=self.hr).exists())
        self.assertEqual(self.last().mentions.count(), 0)

    def test_the_admin_can_open_every_room_but_is_only_pinged_in_the_ones_they_are_in(self):
        self.assertTrue(self.team.can_open(self.admin))
        self.assertFalse(self.team.members.filter(pk=self.admin.pk).exists())
        self.say(self.ops, f"@{self.admin.short_name} look", self.admin.pk)
        self.assertFalse(Notification.objects.filter(user=self.admin).exists())
        self.assertEqual(self.last().mentions.count(), 0)
        self.team.members.add(self.admin)
        self.say(self.ops, f"@{self.admin.short_name} look", self.admin.pk)
        self.assertEqual(self.pinged(self.admin).count(), 1)

    def test_a_member_who_may_no_longer_open_the_room_is_not_pinged(self):
        User.objects.filter(pk=self.tr.pk).update(is_active=False)
        self.say(self.ops, f"@{self.tr.short_name} look", self.tr.pk)
        self.assertFalse(Notification.objects.filter(user=self.tr).exists())
        self.assertEqual(self.last().mentions.count(), 0)

    def test_you_cannot_mention_yourself(self):
        self.say(self.ops, f"@{self.ops.short_name} note to self", self.ops.pk)
        self.assertFalse(Notification.objects.filter(user=self.ops).exists())
        self.assertEqual(self.last().mentions.count(), 0)

    def test_two_people_of_one_name_are_told_apart_by_the_id(self):
        twin_a = User.objects.create_user("twin_a", password="pw", role=Role.TRANSLATOR, first_name="Mona", last_name="Twin")
        twin_b = User.objects.create_user("twin_b", password="pw", role=Role.TRANSLATOR, first_name="Mona", last_name="Twin")
        self.team.members.add(twin_a, twin_b)
        self.assertEqual(twin_a.short_name, twin_b.short_name)
        self.say(self.ops, "@Mona Twin look", twin_b.pk)
        self.assertTrue(self.pinged(twin_b).exists())
        self.assertFalse(self.pinged(twin_a).exists())
        self.assertEqual([one.pk for one in self.last().mentions.all()], [twin_b.pk])

    def test_what_is_not_an_id_is_ignored_and_what_is_a_list_of_them_is_read(self):
        for junk in ("abc", "", " , ,", "-1", "1.5", "١٢", f"{self.tr.pk}x", "0"):
            self.say(self.ops, f"@{self.tr.short_name} look", junk)
        self.assertFalse(self.pinged(self.tr).exists())
        # A list with junk in it still delivers the ids that are ids.
        self.say(self.ops, f"@{self.tr.short_name} look", f"abc, {self.tr.pk} ,-5")
        self.assertEqual(self.pinged(self.tr).count(), 1)

    def test_at_most_twenty_people_are_pinged_by_one_message(self):
        crowd = [User.objects.create_user(f"crowd_{n}", password="pw", role=Role.TRANSLATOR) for n in range(services.MAX_MENTIONS + 4)]
        self.team.members.add(*crowd)
        words = " ".join(f"@{person.short_name}" for person in crowd)
        self.say(self.ops, words, [person.pk for person in crowd])
        self.assertEqual(self.last().mentions.count(), services.MAX_MENTIONS)


class WhereNobodyIsMentionedTests(_Mentions):
    def test_a_client_group_relays_the_words_and_names_nobody(self):
        # Sales may open a client's room (the team leader may not), so it is this rule - and not the gate - that stops it.
        self.group.members.add(self.sales)
        self.assertTrue(self.group.can_open(self.sales))
        self.say(self.ops, f"@{self.sales.short_name} look", self.sales.pk, room=self.group)
        message = self.last(self.group)
        self.assertEqual(message.mentions.count(), 0)
        self.assertFalse(self.pinged(self.sales).exists())
        # What reaches the client is what was typed, and a mention would have been a colleague's name on their phone.
        self.assertEqual([one["mentions"] for one in self.thread(self.ops, self.group)[-1:]], [[]])
        self.assertEqual([one["mentions_me"] for one in self.thread(self.sales, self.group)[-1:]], [False])

    def test_a_chat_with_one_colleague_has_nobody_to_pick(self):
        self.to_staff(self.ops, self.lead, body=f"@{self.lead.short_name} hi", mentions=str(self.lead.pk))
        message = ChatMessage.objects.filter(room=self.private).order_by("-id").first()
        self.assertIsNotNone(message)
        self.assertEqual(message.mentions.count(), 0)
        self.assertFalse(self.pinged(self.lead).exists())

    def test_the_service_agrees_with_the_doors(self):
        body = f"@{self.lead.short_name} look"
        self.assertEqual(services.mention_targets(self.group, self.ops, body, str(self.lead.pk)), [])
        self.assertEqual(services.mention_targets(self.private, self.ops, body, str(self.lead.pk)), [])
        self.assertEqual(services.mention_targets(self.team, self.ops, body, str(self.lead.pk)), [self.lead])
        self.assertEqual(services.mention_targets(self.team, self.ops, "", str(self.lead.pk)), [])


class TakenBackTests(_Mentions):
    def test_taking_a_message_back_takes_its_mentions_with_it(self):
        self.say(self.ops, f"@{self.tr.short_name} look", self.tr.pk)
        message = self.last()
        answer = self.browser(self.ops).post(
            reverse("dashboard:v1_chat_unsend"),
            json.dumps({"source": f"g{self.team.pk}", "uid": f"g{self.team.pk}-{message.pk}"}),
            content_type="application/json",
        )
        self.assertEqual(answer.status_code, 200)
        message.refresh_from_db()
        self.assertEqual(message.mentions.count(), 0)
        shown = self.thread(self.tr)[-1]
        self.assertEqual((shown["mentions"], shown["mentions_me"], shown["unsent"]), ([], False, True))
