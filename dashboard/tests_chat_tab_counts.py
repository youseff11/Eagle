"""The number on each tab of the chats: how many conversations of that tab have something unread (not how many messages)."""

from django.db import connection
from django.test import Client as DjangoClient
from django.test.utils import CaptureQueriesContext
from django.urls import reverse

from . import services
from .models import ChatMessage, ChatRoom, RoomKind
from .tests_api_v1 import _Site, _json


class TabCountTests(_Site):
    def setUp(self):
        super().setUp()
        # The fixture's own messages are all read: what is counted below is only what these tests write.
        for person in self.everyone:
            for room in ChatRoom.objects.filter(members=person):
                services.mark_room_read(person, room)
            if person.handles_clients:
                services.mark_client_read(person, self.client_obj, receipt=False)

    def tabs(self, user):
        return services.unread_chat_breakdown(user)[1]

    def say(self, room, who, body="hello"):
        return ChatMessage.objects.create(room=room, sender=who, body=body)

    def test_a_colleague_writing_counts_on_the_colleagues_tab_once_however_many_messages(self):
        room = services.staff_room(self.lead, self.ops)
        for index in range(3):
            self.say(room, self.lead, f"m{index}")
        tabs = self.tabs(self.ops)
        self.assertEqual((tabs["staff"], tabs["groups"]), (1, 0))
        # Messages are what the sidebar badge counts; the tab counts conversations.
        self.assertEqual(services.unread_chat_breakdown(self.ops)[0], 3)

    def test_two_colleagues_are_two(self):
        self.say(services.staff_room(self.lead, self.ops), self.lead)
        self.say(services.staff_room(self.hr, self.ops), self.hr)
        self.assertEqual(self.tabs(self.ops)["staff"], 2)

    def test_a_work_group_counts_on_the_groups_tab(self):
        group = services.lead_translator_group(self.lead, self.tr)
        self.say(group, self.lead)
        self.say(group, self.lead)
        tabs = self.tabs(self.tr)
        self.assertEqual((tabs["groups"], tabs["staff"], tabs["clients"]), (1, 0, 0))

    def test_reading_it_takes_it_off(self):
        room = services.staff_room(self.lead, self.ops)
        self.say(room, self.lead)
        self.assertEqual(self.tabs(self.ops)["staff"], 1)
        services.mark_room_read(self.ops, room)
        self.assertEqual(self.tabs(self.ops)["staff"], 0)

    def test_what_one_wrote_oneself_is_not_unread(self):
        room = services.staff_room(self.lead, self.ops)
        self.say(room, self.ops)
        self.assertEqual(self.tabs(self.ops)["staff"], 0)

    def test_a_client_who_wrote_counts_on_the_clients_tab(self):
        services.ingest_message(channel="whatsapp", body="a new one", sender_identity=self.client_obj.phone)
        tabs = self.tabs(self.ops)
        self.assertEqual(tabs["clients"], 1)
        self.assertEqual(services.unread_chat_counts(self.ops)[1], 1)

    def test_a_client_room_counts_with_the_groups_for_the_people_who_talk_to_clients(self):
        self.say(self.client_group, self.sales, "in the client group")
        self.client_group.members.add(self.sales)
        self.say(self.client_group, self.sales, "again")
        tabs = self.tabs(self.ops)
        self.assertEqual((tabs["groups"], tabs["staff"]), (1, 0))

    def test_it_is_in_the_me_answer_beside_the_old_numbers(self):
        self.say(services.staff_room(self.lead, self.ops), self.lead)
        self.say(services.lead_translator_group(self.lead, self.tr), self.lead)
        browser = DjangoClient()
        browser.force_login(self.ops)
        me = _json(browser.get(reverse("dashboard:v1_me")))
        self.assertEqual(me["unread_chat_tabs"], {"clients": 0, "groups": 0, "staff": 1})
        self.assertEqual(me["unread_client_chats"], 0)
        self.assertGreaterEqual(me["unread_chats"], 1)

    def test_it_costs_the_same_however_many_conversations(self):
        def cost():
            with CaptureQueriesContext(connection) as queries:
                self.tabs(self.ops)
            return len(queries)

        few = cost()
        for index in range(5):
            from .models import User

            person = User.objects.create_user(f"person_extra_{index}", password="pw", role="hr")
            self.say(services.staff_room(person, self.ops), person)
        self.assertEqual(cost(), few)
        self.assertEqual(self.tabs(self.ops)["staff"], 5)
