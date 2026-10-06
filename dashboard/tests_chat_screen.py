"""The chats screen in the new app, step 3a (reading): what its endpoints answer, and who may see what.

The lists and the thread reads already existed (``tests_api_v1``, ``tests_chat_lists``). What this step added is
the colleague's conversation (``/api/v1/staff/<id>/messages/``), the unread count in ``/api/v1/me/``, and the
screen's entry in the switch.
"""

from unittest import mock

from django.test import Client as DjangoClient
from django.test import RequestFactory
from django.urls import reverse

from . import newui, services
from .models import (
    AppSettings, AuditLog, Channel, ChatMessage, ChatRead, ChatRoom, Client, InboundMessage, Role, RoomKind, User,
)
from .tests_chat_lists import _Data, _json


class _Staff(_Data):
    def setUp(self):
        super().setUp()
        self.private = services.staff_room(self.ops, self.lead)
        self.secret = ChatMessage.objects.create(room=self.private, sender=self.ops, body="A PRIVATE WORD")
        ChatMessage.objects.create(room=self.private, sender=self.lead, body="and a private answer")

    def staff(self, viewer, other, **kw):
        browser = DjangoClient()
        browser.force_login(viewer)
        return browser.get(reverse("dashboard:v1_staff_messages", args=[other.pk]), kw)


class StaffMessagesTests(_Staff):
    def test_each_of_the_two_reads_their_own_side(self):
        mine = _json(self.staff(self.ops, self.lead))
        theirs = _json(self.staff(self.lead, self.ops))
        self.assertEqual([m["body"] for m in mine["messages"]], ["A PRIVATE WORD", "and a private answer"])
        self.assertEqual([m["mine"] for m in mine["messages"]], [True, False])
        self.assertEqual([m["mine"] for m in theirs["messages"]], [False, True])
        self.assertEqual(mine["client"]["room"], self.private.pk)
        self.assertEqual(mine["client"]["label"], self.lead.short_name)

    def test_nobody_else_can_reach_it_by_any_id_not_even_the_admin(self):
        for viewer in (self.admin, self.hr, self.tr, self.sales):
            for other in self.everyone + [User.objects.get(pk=self.ops.pk)]:
                if other.pk == viewer.pk:
                    continue
                answer = self.staff(viewer, other)
                self.assertNotIn(b"PRIVATE WORD", answer.content, (viewer.username, other.username))
                self.assertNotIn(b"private answer", answer.content, (viewer.username, other.username))

    def test_the_id_names_the_colleague_never_a_room(self):
        # Asking for the room's own number as if it were a person's finds nobody or somebody else's chat.
        answer = self.staff(self.hr, User(pk=self.private.pk))
        self.assertNotIn(b"PRIVATE WORD", answer.content)

    def test_no_room_is_an_empty_chat_and_a_get_does_not_open_one(self):
        before = ChatRoom.objects.count()
        answer = self.staff(self.hr, self.sales)
        body = _json(answer)
        self.assertEqual(answer.status_code, 200)
        self.assertEqual(body["messages"], [])
        self.assertEqual(body["client"]["room"], 0)
        self.assertEqual(body["client"]["label"], self.sales.short_name)
        self.assertEqual(ChatRoom.objects.count(), before)
        self.assertFalse(ChatRoom.objects.filter(kind=RoomKind.STAFF, members=self.hr, pair_key__contains=f"{self.sales.pk}").exists())

    def test_yourself_somebody_unknown_and_somebody_deactivated_are_not_found(self):
        self.assertEqual(self.staff(self.ops, self.ops).status_code, 404)
        browser = DjangoClient()
        browser.force_login(self.ops)
        self.assertEqual(browser.get(reverse("dashboard:v1_staff_messages", args=[999999])).status_code, 404)
        User.objects.filter(pk=self.lead.pk).update(is_active=False)
        self.assertEqual(self.staff(self.ops, User.objects.get(pk=self.lead.pk)).status_code, 404)

    def test_only_a_get_is_answered_and_only_to_somebody_signed_in(self):
        anonymous = DjangoClient().get(reverse("dashboard:v1_staff_messages", args=[self.lead.pk]))
        self.assertEqual(anonymous.status_code, 401)
        self.assertEqual(_json(anonymous), {"ok": False, "error": "auth"})
        browser = DjangoClient()
        browser.force_login(self.ops)
        self.assertEqual(browser.post(reverse("dashboard:v1_staff_messages", args=[self.lead.pk])).status_code, 405)

    def test_the_answer_is_private_and_not_stored(self):
        self.assertEqual(self.staff(self.ops, self.lead)["Cache-Control"], "private, no-store")

    def test_a_get_does_not_mark_the_chat_read(self):
        from .models import ChatRead

        self.staff(self.lead, self.ops, read=1)
        self.assertFalse(ChatRead.objects.filter(user=self.lead, room=self.private).exists())


class UnreadChatsInMeTests(_Staff):
    def me(self, user):
        browser = DjangoClient()
        browser.force_login(user)
        return _json(browser.get(reverse("dashboard:v1_me")))

    def test_it_is_the_count_the_classic_badge_shows(self):
        self.add_clients(3)
        for user in self.everyone:
            self.assertEqual(self.me(user)["unread_chats"], services.unread_chat_total(user), user.username)
        self.assertGreater(self.me(self.ops)["unread_chats"], 0)

    def test_a_message_raises_it_and_reading_the_chat_lowers_it_again(self):
        before = self.me(self.ops)["unread_chats"]
        ChatMessage.objects.create(room=self.private, sender=self.lead, body="one more")
        self.assertEqual(self.me(self.ops)["unread_chats"], before + 1)
        browser = DjangoClient()
        browser.force_login(self.ops)
        browser.post(reverse("dashboard:v1_group_read", args=[self.private.pk]))
        # Everything else in the chat was already read, and now so is the new line.
        self.assertEqual(self.me(self.ops)["unread_chats"], 0)

    def test_the_clients_tab_counts_conversations_waiting_not_messages(self):
        first = Client.objects.create(name="First Co", phone="+201005550001")
        second = Client.objects.create(name="Second Co", phone="+201005550002")
        for client, words in ((first, "one"), (first, "two"), (first, "three"), (second, "only")):
            InboundMessage.objects.create(client=client, channel=Channel.WHATSAPP, body=words)
        body = self.me(self.ops)
        # Four messages in two conversations: the tab says two, the sidebar's badge says four (and the staff chat's own lines).
        self.assertEqual(body["unread_client_chats"], 2)
        self.assertEqual(services.unread_by_client(self.ops), {first.pk: 3, second.pk: 1})
        self.assertEqual(body["unread_chats"], services.unread_chat_total(self.ops))
        # Reading one conversation takes it off the count, and another message from it puts it back.
        with mock.patch("dashboard.services.send_read_receipt"):
            browser = DjangoClient()
            browser.force_login(self.ops)
            browser.post(reverse("dashboard:v1_client_read", args=[first.code]), {}, content_type="application/json")
        self.assertEqual(self.me(self.ops)["unread_client_chats"], 1)
        InboundMessage.objects.create(client=first, channel=Channel.WHATSAPP, body="back again")
        self.assertEqual(self.me(self.ops)["unread_client_chats"], 2)

    def test_it_is_nothing_for_a_role_without_the_client_tab_and_the_tabs_put_colleagues_in_the_middle(self):
        InboundMessage.objects.create(client=Client.objects.create(name="Any Co", phone="+201005550003"), channel=Channel.WHATSAPP, body="hi")
        self.assertEqual(self.me(self.tr)["unread_client_chats"], 0)
        self.assertEqual(self.me(self.tr)["chats"]["types"], ["groups", "staff"])
        self.assertEqual(self.me(self.ops)["chats"]["types"], ["clients", "staff", "groups"])
        self.assertEqual(self.me(self.admin)["chats"]["types"], ["clients", "staff", "groups"])


class ChatsScreenSwitchTests(_Staff):
    def turn_on(self, roles=(), users=()):
        conf = AppSettings.load()
        conf.save()

    def test_every_role_that_has_the_chats_page_can_be_switched_on(self):
        self.turn_on(roles=["operation", "team_lead", "translator", "hr", "reviewer", "accounting", "sales"])
        for user in (self.ops, self.lead, self.tr, self.sales, self.hr):
            self.assertIn("chats", newui.enabled_keys(user), user.username)

class ChatsHandOnTests(_Staff):
    """The classic chat pages hand a switched-on person to the same conversation in the new app."""

    def setUp(self):
        super().setUp()
        # As if ``npm run build`` had run: a checkout that never built the app must not change what these say.
        built = mock.patch("dashboard.spa.built_assets", return_value={"js": "x.js", "css": []})
        built.start()
        self.addCleanup(built.stop)
        self.some_client = Client.objects.create(name="Handed On Client", phone="+201000000093")
        self.team = ChatRoom.objects.create(kind=RoomKind.TEAM, title="Work", created_by=self.lead)
        self.team.members.add(self.ops, self.lead, self.tr)

    def turn_on(self, roles=(), users=()):
        conf = AppSettings.load()
        conf.save()

    def get(self, user, path):
        browser = DjangoClient()
        browser.force_login(user)
        return browser.get(path)

    def places(self):
        """Every classic way into the chats, and where it leads in the new app."""
        return [
            ("/ops/chats/", "/app/chats"),
            ("/ops/chats/?type=groups", "/app/chats?type=groups"),
            ("/ops/chats/?type=staff", "/app/chats?type=staff"),
            (f"/ops/chats/{self.some_client.code}/", f"/app/chats/{self.some_client.code}"),
            (f"/ops/chats/g/{self.team.pk}/", f"/app/chats/g{self.team.pk}"),
            (f"/ops/chats/u/{self.lead.pk}/", f"/app/chats/u{self.lead.pk}"),
        ]

    def test_a_switched_on_person_lands_on_the_same_conversation_in_the_new_app(self):
        self.turn_on(roles=["operation", "translator"])
        for user in (self.ops, self.tr):
            for classic, new in self.places():
                answer = self.get(user, classic)
                self.assertEqual((answer.status_code, answer.get("Location")), (302, new), (user.username, classic))

    def test_the_admin_who_is_on_by_default_is_handed_on_too(self):
        for classic, new in self.places():
            self.assertEqual(self.get(self.admin, classic).get("Location"), new, classic)

    def test_handing_on_opens_nothing_and_reads_nothing(self):
        # The classic page marked a conversation read on opening, and made a colleague's room. Now the
        # new app does that, once the person sees it - the redirect itself must leave no trace.
        self.turn_on(roles=["operation"])
        InboundMessage.objects.create(
            client=self.some_client, channel=Channel.WHATSAPP, body="unread words", external_id="wamid.in.h",
        )
        rooms, reads = ChatRoom.objects.count(), ChatRead.objects.count()
        before = services.unread_chat_total(self.ops)
        self.get(self.ops, f"/ops/chats/{self.some_client.code}/")
        self.get(self.ops, f"/ops/chats/u/{self.tr.pk}/")
        self.assertEqual((ChatRoom.objects.count(), ChatRead.objects.count()), (rooms, reads))
        self.assertEqual(services.unread_chat_total(self.ops), before)

    def test_a_conversation_that_is_not_theirs_is_still_refused_where_it_lands(self):
        # The redirect decides nothing about who may read what: the new app's endpoint does, and says no.
        self.turn_on(roles=["translator"])
        self.assertEqual(self.get(self.tr, f"/ops/chats/g/{self.private.pk}/").get("Location"), f"/app/chats/g{self.private.pk}")
        browser = DjangoClient()
        browser.force_login(self.tr)
        answer = browser.get(reverse("dashboard:v1_group_messages", args=[self.private.pk]))
        self.assertEqual(answer.status_code, 404)
        self.assertNotIn(b"PRIVATE WORD", answer.content)


class ReadUpToTests(_Staff):
    """Saying "read" means "read what I was shown", not "read whatever is there by now".

    The new page fetches a thread and says "read" a moment later (a GET, then a POST). A message that arrived in
    between has been on nobody's screen; for a client, "read" is also the blue ticks on their phone.
    """

    def setUp(self):
        super().setUp()
        self.group, _ = services.create_team_group(self.lead, "Read me", [self.ops, self.tr])
        self.first, self.second, self.third = [
            ChatMessage.objects.create(room=self.group, sender=self.lead, body=f"line {n}") for n in (1, 2, 3)
        ]
        self.client_obj = Client.objects.create(name="Reader Co", phone="+201005550000")
        self.inbound = [
            InboundMessage.objects.create(
                client=self.client_obj, channel=Channel.WHATSAPP, body=f"from client {n}", external_id=f"wamid.{n}",
            )
            for n in (1, 2, 3)
        ]

    def post(self, user, name, args, **body):
        browser = DjangoClient()
        browser.force_login(user)
        return browser.post(reverse(f"dashboard:{name}", args=args), body, content_type="application/json")

    def cursor(self, user, **target):
        row = ChatRead.objects.filter(user=user, **target).first()
        return row.last_read_id if row else 0

    def test_a_room_is_read_only_as_far_as_the_page_showed(self):
        answer = self.post(self.ops, "v1_group_read", [self.group.pk], upto=self.second.pk)
        self.assertEqual(_json(answer), {"ok": True, "moved": True})
        self.assertEqual(self.cursor(self.ops, room=self.group), self.second.pk)
        self.assertEqual(services.unread_by_room(self.ops, [self.group.pk]), {self.group.pk: 1})

    def test_without_upto_everything_there_is_is_read_as_before(self):
        self.post(self.ops, "v1_group_read", [self.group.pk])
        self.assertEqual(self.cursor(self.ops, room=self.group), self.third.pk)
        self.assertEqual(services.unread_by_room(self.ops, [self.group.pk]), {})

    def test_an_upto_beyond_the_newest_is_the_newest(self):
        self.post(self.ops, "v1_group_read", [self.group.pk], upto=self.third.pk + 1000)
        self.assertEqual(self.cursor(self.ops, room=self.group), self.third.pk)

    def test_a_cursor_never_moves_back(self):
        self.post(self.ops, "v1_group_read", [self.group.pk], upto=self.third.pk)
        answer = self.post(self.ops, "v1_group_read", [self.group.pk], upto=self.first.pk)
        self.assertEqual(_json(answer)["moved"], False)
        self.assertEqual(self.cursor(self.ops, room=self.group), self.third.pk)

    def test_a_client_is_read_and_told_only_as_far_as_the_page_showed(self):
        with mock.patch("dashboard.services.send_read_receipt") as receipt:
            answer = self.post(self.ops, "v1_client_read", [self.client_obj.code], upto=self.inbound[1].pk)
        self.assertEqual(_json(answer), {"ok": True, "moved": True})
        self.assertEqual(self.cursor(self.ops, client=self.client_obj), self.inbound[1].pk)
        # The phone is told the second message was seen - not the third, which nobody has seen.
        receipt.assert_called_once_with("wamid.2")
        self.assertEqual(services.unread_by_client(self.ops, [self.client_obj.pk]), {self.client_obj.pk: 1})

    def test_a_client_read_without_upto_still_tells_the_phone_about_the_newest(self):
        with mock.patch("dashboard.services.send_read_receipt") as receipt:
            self.post(self.ops, "v1_client_read", [self.client_obj.code])
        receipt.assert_called_once_with("wamid.3")
        self.assertEqual(self.cursor(self.ops, client=self.client_obj), self.inbound[2].pk)

    def test_a_message_the_operation_may_not_read_is_never_what_it_reads_up_to(self):
        blocked = InboundMessage.objects.create(
            client=self.client_obj, channel=Channel.WHATSAPP, body="a rate", external_id="wamid.blocked",
            is_rate_blocked=True,
        )
        with mock.patch("dashboard.services.send_read_receipt") as receipt:
            self.post(self.ops, "v1_client_read", [self.client_obj.code], upto=blocked.pk)
        receipt.assert_called_once_with("wamid.3")
        self.assertEqual(self.cursor(self.ops, client=self.client_obj), self.inbound[2].pk)

    def test_an_upto_that_is_not_a_message_id_is_refused_and_nothing_moves(self):
        for bad in (0, -1, "x", 10 ** 30, True, [1], 1.5, {"a": 1}):
            with mock.patch("dashboard.services.send_read_receipt") as receipt:
                for name, args in (("v1_group_read", [self.group.pk]), ("v1_client_read", [self.client_obj.code])):
                    answer = self.post(self.ops, name, args, upto=bad)
                    self.assertEqual(answer.status_code, 400, (name, bad))
                    self.assertEqual(_json(answer), {"ok": False, "error": "bad_upto"})
            receipt.assert_not_called()
        self.assertEqual(self.cursor(self.ops, room=self.group), 0)
        self.assertEqual(self.cursor(self.ops, client=self.client_obj), 0)

    def test_a_form_post_carries_upto_too(self):
        browser = DjangoClient()
        browser.force_login(self.ops)
        browser.post(reverse("dashboard:v1_group_read", args=[self.group.pk]), {"upto": str(self.first.pk)})
        self.assertEqual(self.cursor(self.ops, room=self.group), self.first.pk)

    def test_who_may_read_is_still_decided_before_anything_moves(self):
        # A translator has no client conversation: refused, and nothing is written.
        answer = self.post(self.tr, "v1_client_read", [self.client_obj.code], upto=self.inbound[0].pk)
        self.assertEqual(answer.status_code, 403)
        self.assertEqual(self.cursor(self.tr, client=self.client_obj), 0)


class OrphanStaffRoomTests(_Staff):
    def test_a_room_that_lost_this_persons_seat_is_an_empty_chat_not_a_refusal_on_every_refresh(self):
        # The room and its members are written in two steps; a drop in between leaves a room nobody sits in.
        a = User.objects.create_user("person_orphan_a", password="pw", role=Role.OPERATION)
        b = User.objects.create_user("person_orphan_b", password="pw", role=Role.OPERATION)
        room = ChatRoom.objects.create(kind=RoomKind.STAFF, pair_key=services.staff_pair_key(a.pk, b.pk))
        denied = AuditLog.objects.filter(action="security.denied").count()
        for _ in range(3):
            answer = self.staff(a, b)
            self.assertEqual(answer.status_code, 200)
            self.assertEqual(_json(answer)["messages"], [])
        self.assertEqual(AuditLog.objects.filter(action="security.denied").count(), denied)
        self.assertEqual(room.members.count(), 0, "a GET writes nothing: the seat is put back by opening the chat")

