"""Only the people who talk to clients are ever in a room with one (the operation, Sales, the admin); nobody else is quoted the client's words.

The owner's rule (2026-10-02): a client is never in a group with a team leader or a translator, and HR,
accounting and reviewers have no part in it either. Before that only the translator was refused.

Found while reviewing the new ``/api/v1/`` layer, and true of the classic pages too:

* a translator seated in a client room by hand (a team leader adding members, or a
  row from before the rule) could read it, was counted its unread messages, saw its
  title and last line in the chats list, and was sent a notification quoting what the
  client wrote;
* the same for anybody whose seat outlived the task (a team leader taken off it, HR);
* a group's 24-hour window came from whichever line the client wrote to last, which
  told the operation when the client had spoken to a Sales number.

The single gate is ``ChatRoom.can_access`` (+ ``can_open`` for a room that belongs to
a task); every page, endpoint, list, badge and notification asks it.
"""

import json
from datetime import timedelta
from io import StringIO
from unittest import mock

from django.core.management import call_command

from django.test import Client as DjangoClient
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from . import services
from .models import (
    Channel, ChatMessage, ChatRoom, Client, InboundMessage, Notification, Role, RoomKind, User,
)

CLIENT_NAME = "ACME Secret Ltd"
CLIENT_PHONE = "+201001234567"
WORDS = "CLIENT WORDS ABOUT THE PRICE"


def _json(response):
    return json.loads(response.content.decode("utf-8"))


class _Site(TestCase):
    """One of each role that matters, one client, a task in progress and the rooms around it."""

    def setUp(self):
        make = lambda name, role, **kw: User.objects.create_user(name, password="pw", role=role, **kw)
        self.admin = make("person_admin", Role.ADMIN)
        self.ops = make("person_operation", Role.OPERATION)
        self.lead = make("person_leader", Role.TEAM_LEAD)
        self.tr = make("person_translator", Role.TRANSLATOR, team_lead=self.lead)
        self.hr = make("person_hr_staff", Role.HR)
        self.sales = make("person_salesman", Role.SALES)

        self.client_obj = Client.objects.create(name=CLIENT_NAME, phone=CLIENT_PHONE)
        inbound = services.ingest_message(
            channel="whatsapp", body="hello there", sender_identity=CLIENT_PHONE
        )
        self.task = services.create_task(
            client=self.client_obj, title="Doc", created_by=self.ops,
            deadline=timezone.now() + timedelta(hours=3), messages=[inbound],
        )
        first = services.assign_to_lead(self.task, self.lead, self.ops)
        services.accept_assignment(first, self.lead)
        second = services.assign_to_translator(self.task, self.tr, self.lead)
        services.accept_assignment(second, self.tr)

        self.task_client_room = services.ensure_room(self.task, RoomKind.CLIENT)
        self.work_group = services.lead_translator_group(self.lead, self.tr)
        self.client_group = ChatRoom.objects.create(
            kind=RoomKind.CLIENT, client=self.client_obj, title="Client group",
            created_by=self.ops,
        )
        self.client_group.members.add(self.ops)
        # A second person of the operation: somebody who may open every client room, and is told what the client wrote.
        self.ops2 = make("person_operation_b", Role.OPERATION)
        self.task_client_room.members.add(self.ops2)
        self.client_group.members.add(self.ops2)
        for room, who in ((self.task_client_room, self.ops), (self.work_group, self.lead),
                          (self.client_group, self.ops)):
            ChatMessage.objects.create(room=room, sender=who, body="Please look at this")

    def browser(self, user):
        browser = DjangoClient()
        browser.force_login(user)
        return browser

    def get(self, user, name, args=None, **query):
        return self.browser(user).get(reverse(f"dashboard:{name}", args=args), query)

    def seat_translator(self):
        self.task_client_room.members.add(self.tr)
        self.client_group.members.add(self.tr)


class TheGateTests(_Site):
    def test_a_translator_is_refused_every_client_room_with_or_without_a_seat(self):
        for room in (self.task_client_room, self.client_group):
            self.assertFalse(room.can_access(self.tr))
            room.members.add(self.tr)
            self.assertFalse(room.can_access(self.tr))
            self.assertFalse(room.can_open(self.tr))

    def test_the_people_who_belong_there_still_get_in(self):
        # The control: without it the refusals above could be a room nobody can open.
        for user in (self.admin, self.ops, self.ops2):
            self.assertTrue(self.client_group.can_access(user), user.username)
        self.assertTrue(self.task_client_room.can_open(self.ops))
        # A Sales person talks to clients too: seated, they get in.
        self.client_group.members.add(self.sales)
        self.assertTrue(self.client_group.can_access(self.sales))

    def test_nobody_who_does_not_talk_to_clients_is_ever_in_a_room_with_one_seat_or_no_seat(self):
        accounting = User.objects.create_user("person_accounting", password="pw", role=Role.ACCOUNTING)
        reviewer = User.objects.create_user("person_reviewer", password="pw", role=Role.REVIEWER)
        for room in (self.task_client_room, self.client_group):
            for user in (self.lead, self.tr, self.hr, accounting, reviewer):
                self.assertFalse(room.can_access(user), (room.pk, user.username, "no seat"))
                room.members.add(user)
                self.assertFalse(room.can_access(user), (room.pk, user.username, "seated"))
                self.assertFalse(room.can_open(user), (room.pk, user.username, "seated"))

    def test_the_task_page_lists_no_client_room_for_somebody_who_does_not_talk_to_clients(self):
        for user in (self.lead, self.hr):
            self.task_client_room.members.add(user)
            self.assertNotIn(self.task_client_room, services.rooms_for(self.task, user), user.username)
        # The control: the operation, seated, has it.
        self.assertIn(self.task_client_room, services.rooms_for(self.task, self.ops))

    def test_the_client_group_setting_does_not_open_a_client_room_to_somebody_who_may_not_be_in_one(self):
        from .models import AppSettings

        AppSettings.objects.filter(pk=AppSettings.load().pk).update(group_creator_roles="team_lead,hr,operation")
        self.assertFalse(services.may_add_members(self.lead, self.client_group))
        self.assertFalse(services.may_add_members(self.hr, self.client_group))
        self.assertTrue(services.may_add_members(self.ops, self.client_group))

    def test_the_task_room_never_seats_the_team_leader(self):
        self.assertTrue(self.task_client_room.members.filter(pk=self.ops.pk).exists())
        self.assertFalse(self.task_client_room.members.filter(pk=self.lead.pk).exists())
        self.assertFalse(self.task_client_room.members.filter(pk=self.tr.pk).exists())

    def test_whoever_was_left_in_it_from_before_the_rule_is_taken_out(self):
        self.task_client_room.members.add(self.lead, self.hr, self.tr)
        services.ensure_room(self.task, RoomKind.CLIENT)
        self.assertEqual(
            {m.pk for m in self.task_client_room.members.all()}, {self.ops.pk, self.ops2.pk},
        )

    def test_a_translator_keeps_the_work_group_with_the_leader(self):
        self.assertTrue(self.work_group.can_access(self.tr))

    def test_a_superuser_whose_role_is_still_translator_is_refused_too(self):
        # ``User.save`` turns a NEW superuser into an admin; Django's own admin can make an
        # existing translator one afterwards. By role still a translator, by flag an admin.
        boss = User.objects.create_user("person_superuser", password="pw", role=Role.TRANSLATOR)
        User.objects.filter(pk=boss.pk).update(is_superuser=True)
        boss = User.objects.get(pk=boss.pk)
        self.assertTrue(boss.is_translator and boss.is_admin_role)
        self.assertFalse(self.client_group.can_access(boss))
        self.assertNotIn(self.client_group.pk, services.listed_room_ids(boss))
        self.assertNotIn(self.client_group, services.groups_for(boss))

    def test_a_person_taken_off_the_task_cannot_open_its_room(self):
        # A Sales person talks to clients, so the seat opens the room - until the task is closed to them.
        stale = User.objects.create_user("person_stale_sales", password="pw", role=Role.SALES)
        self.task_client_room.members.add(stale)
        self.assertTrue(self.task_client_room.can_access(stale))
        self.assertFalse(self.task_client_room.can_open(stale))


class WhatTheTranslatorIsShownTests(_Site):
    def test_the_message_endpoints_answer_404_not_the_messages(self):
        self.seat_translator()
        for name, room in (("v1_room_messages", self.task_client_room),
                           ("v1_group_messages", self.client_group)):
            answer = self.get(self.tr, name, [room.pk])
            self.assertEqual(answer.status_code, 404, name)
            self.assertNotIn(b"Please look at this", answer.content)

    def test_the_lists_and_the_badge_leave_the_client_rooms_out(self):
        self.seat_translator()
        ChatMessage.objects.create(room=self.client_group, sender=self.ops, body="what the client wrote")
        listed = services.listed_room_ids(self.tr)
        self.assertNotIn(self.client_group.pk, listed)
        self.assertNotIn(self.task_client_room.pk, listed)
        self.assertNotIn(self.client_group, services.groups_for(self.tr))
        self.assertNotIn(self.task_client_room, services.rooms_for(self.task, self.tr))
        body = self.get(self.tr, "v1_chats", type="groups").content
        self.assertNotIn(b"what the client wrote", body)
        self.assertNotIn(b"Client group", body)

    def test_the_work_group_is_still_listed(self):
        self.seat_translator()
        self.assertIn(self.work_group.pk, services.listed_room_ids(self.tr))
        self.assertIn(self.work_group, services.groups_for(self.tr))

    def test_every_listed_room_is_one_the_person_may_open(self):
        stale = User.objects.create_user("person_stale_leader", password="pw", role=Role.TEAM_LEAD)
        for room in ChatRoom.objects.all():
            room.members.add(self.tr, self.hr, stale)
        listed_somewhere = 0
        for user in (self.admin, self.ops, self.lead, self.tr, self.hr, stale):
            for room in services.groups_for(user):
                listed_somewhere += 1
                self.assertTrue(room.can_open(user), f"{user.username} is listed room {room.pk}")
            for room_id in services.listed_room_ids(user):
                room = ChatRoom.objects.get(pk=room_id)
                if room.kind != RoomKind.STAFF:
                    self.assertTrue(room.can_open(user), f"{user.username} is counted room {room.pk}")
        self.assertGreater(listed_somewhere, 3)

    def test_the_people_who_may_open_the_task_room_still_see_it(self):
        for user in (self.admin, self.ops):
            self.assertIn(self.task_client_room.pk, {r.pk for r in services.groups_for(user)}, user.username)


class NobodyIsQuotedTheClientUnlessTheyMayOpenTheRoomTests(_Site):
    def quoting(self, user):
        return [
            n for n in Notification.objects.filter(user=user)
            if "CLIENT WORDS" in (n.body_en + n.body_ar)
        ]

    def client_writes(self):
        with self.captureOnCommitCallbacks(execute=True):
            services.ingest_message(channel="whatsapp", body=WORDS, sender_identity=CLIENT_PHONE)

    def test_a_member_who_may_open_the_room_is_told(self):
        # The control: without it the tests below pass because nobody is told anything. (The operation and the admin
        # already had the ping from the inbox; a Sales person seated in the room is the one who would otherwise miss it.)
        self.client_group.members.add(self.sales)
        self.client_writes()
        self.assertTrue(self.quoting(self.sales))

    def test_a_team_leader_who_is_seated_in_a_client_room_is_told_nothing(self):
        for room in (self.task_client_room, self.client_group):
            room.members.add(self.lead, self.hr)
        self.client_writes()
        self.assertEqual(self.quoting(self.lead), [])
        self.assertEqual(self.quoting(self.hr), [])

    def test_a_translator_seated_in_a_client_room_or_group_is_told_nothing(self):
        self.seat_translator()
        self.client_writes()
        self.assertEqual(self.quoting(self.tr), [])
        self.assertNotIn(b"CLIENT WORDS", self.get(self.tr, "v1_notifications").content)

    def test_a_team_lead_taken_off_the_task_is_told_nothing(self):
        other = User.objects.create_user("person_other_leader", password="pw", role=Role.TEAM_LEAD)
        self.task_client_room.members.add(other)
        self.client_writes()
        self.assertEqual(self.quoting(other), [])

    def test_an_operation_reply_does_not_notify_a_seated_translator(self):
        self.task_client_room.members.add(self.tr)
        with mock.patch("dashboard.services.relay_chat_message", return_value=(True, "")):
            answer = self.browser(self.ops).post(
                reverse("dashboard:v1_group_send", args=[self.task_client_room.pk]),
                {"body": "OPS REPLY FOR THE CLIENT"},
            )
        self.assertEqual(answer.status_code, 200)
        self.assertFalse(Notification.objects.filter(user=self.tr, body_en__contains="OPS REPLY").exists())
        # And the colleague of the operation, who may open the room, is told.
        self.assertTrue(Notification.objects.filter(user=self.ops2, body_en__contains="OPS REPLY").exists())


class AddingMembersTests(_Site):
    def add(self, *people):
        return self.browser(self.ops).post(
            reverse("dashboard:v1_group_add", args=[self.client_group.pk]),
            json.dumps({"members": [p.pk for p in people]}), content_type="application/json",
        )

    def test_a_translator_cannot_be_given_a_seat_in_a_client_group(self):
        answer = self.add(self.tr)
        self.assertFalse(self.client_group.members.filter(pk=self.tr.pk).exists())
        self.assertFalse(_json(answer)["ok"])
        self.assertTrue(_json(answer)["message"])

    def test_the_others_are_still_added_in_the_same_call(self):
        answer = self.add(self.tr, self.sales)
        self.assertTrue(self.client_group.members.filter(pk=self.sales.pk).exists())
        self.assertFalse(self.client_group.members.filter(pk=self.tr.pk).exists())
        self.assertEqual(_json(answer)["added"], [self.sales.short_name])

    def test_only_those_who_talk_to_clients_can_be_given_a_seat_and_the_answer_says_so(self):
        accounting = User.objects.create_user("person_accounting", password="pw", role=Role.ACCOUNTING)
        reviewer = User.objects.create_user("person_reviewer", password="pw", role=Role.REVIEWER)
        for person in (self.lead, self.hr, accounting, reviewer):
            answer = self.add(person)
            body = _json(answer)
            self.assertFalse(body["ok"], person.username)
            self.assertIn("أوبريشن", body["message"], person.username)
            self.assertIn("Sales", body["message"], person.username)
            self.assertFalse(self.client_group.members.filter(pk=person.pk).exists(), person.username)
        # The ones who do talk to clients are added.
        self.assertTrue(_json(self.add(self.sales))["ok"])


class ForwardingTests(_Site):
    """Forwarding into a room tells its members - with the room's title and a link in.

    Found by the privacy review: the notice went to every seat, whoever could open the room.
    """

    def forward_into(self, room):
        staff = services.staff_room(self.ops, self.lead)
        message = ChatMessage.objects.create(room=staff, sender=self.ops, body="Please forward me")
        with mock.patch("dashboard.services.relay_chat_message", return_value=(True, "")):
            ok, error, _url = services.forward_to_chat(
                self.ops, f"u{self.lead.pk}", f"g{room.pk}", uids=[f"g{staff.pk}-{message.pk}"],
            )
        self.assertTrue(ok, error)

    def told(self, user):
        return Notification.objects.filter(user=user, title_en="Forwarded messages").exists()

    def test_a_task_room_notice_goes_to_those_who_may_open_it_only(self):
        stale = User.objects.create_user("person_stale_leader", password="pw", role=Role.TEAM_LEAD)
        self.task_client_room.members.add(self.tr, stale)
        self.forward_into(self.task_client_room)
        self.assertTrue(self.told(self.ops2))  # the control: somebody is told
        self.assertFalse(self.told(self.tr))
        self.assertFalse(self.told(stale))

    def test_a_client_group_notice_never_reaches_a_seated_translator(self):
        self.client_group.members.add(self.tr, self.lead, self.sales)
        self.forward_into(self.client_group)
        self.assertTrue(self.told(self.sales))
        self.assertTrue(self.told(self.ops2))
        self.assertFalse(self.told(self.tr))
        self.assertFalse(self.told(self.lead))


class SeatedTranslatorCannotWriteTests(_Site):
    def test_a_post_into_a_client_room_is_refused_and_nothing_reaches_the_client(self):
        self.seat_translator()
        for name, room in (("v1_group_send", self.task_client_room), ("v1_group_send", self.client_group)):
            before = room.messages.count()
            with mock.patch("dashboard.services.relay_chat_message", return_value=(True, "")) as relay:
                answer = self.browser(self.tr).post(
                    reverse(f"dashboard:{name}", args=[room.pk]), {"body": "TRANSLATOR WORDS"},
                )
            self.assertEqual(answer.status_code, 404, name)
            relay.assert_not_called()
            self.assertEqual(room.messages.count(), before, name)


class StaleSeatsTests(_Site):
    def test_a_seat_that_outlived_the_task_is_not_listed_and_not_counted(self):
        stale = User.objects.create_user("person_stale_leader", password="pw", role=Role.TEAM_LEAD)
        self.task_client_room.members.add(stale)
        ChatMessage.objects.create(room=self.task_client_room, sender=self.ops, body="the client wrote")
        self.assertNotIn(self.task_client_room, services.groups_for(stale))
        self.assertNotIn(self.task_client_room.pk, services.listed_room_ids(stale))
        self.assertEqual(services.unread_chat_total(stale), 0)

    def test_an_inactive_person_cannot_open_a_room(self):
        User.objects.filter(pk=self.lead.pk).update(is_active=False)
        self.assertFalse(self.task_client_room.can_open(User.objects.get(pk=self.lead.pk)))


class TheWindowIsTheViewersOwnLineTests(_Site):
    def test_a_client_who_wrote_to_a_sales_number_does_not_open_the_operations_window(self):
        # Real rows, no mock: the client wrote to the company number 30 hours ago and to
        # a Sales person's own number just now.
        InboundMessage.objects.filter(client=self.client_obj).update(
            received_at=timezone.now() - timedelta(hours=30)
        )
        InboundMessage.objects.create(
            client=self.client_obj, channel=Channel.WHATSAPP, body="to the sales number",
            owner=self.sales, received_at=timezone.now(),
        )
        self.assertTrue(self.client_obj.reply_window_open)  # the control: some line is open
        body = _json(self.get(self.ops, "v1_chats", type="groups"))
        row = next(item for item in body["items"] if item["room"] == self.client_group.pk)
        self.assertFalse(row["window_open"])
        self.assertEqual(row["minutes_left"], 0)


class ClientRoomTranslatorsCommandTests(_Site):
    """``manage.py client_room_translators``: find the old seats, and clean up only when told to."""

    def seat(self):
        self.task_client_room.members.add(self.tr)
        self.mine = services.notify(
            self.tr, title_ar="x", title_en="New message from the client",
            body_en="Client CL-0001: the words",
            url=f"/tasks/{self.task.code}/?room={self.task_client_room.pk}",
        )
        self.unrelated = services.notify(self.tr, title_ar="x", title_en="Task assigned", url="/tasks/TSK-1/")

    def run_command(self, *flags):
        out = StringIO()
        call_command("client_room_translators", *flags, stdout=out)
        return out.getvalue()

    def test_a_report_changes_nothing(self):
        self.seat()
        text = self.run_command()
        self.assertIn("person_translator", text)
        self.assertIn("Nothing changed", text)
        self.assertTrue(self.task_client_room.members.filter(pk=self.tr.pk).exists())
        self.assertTrue(Notification.objects.filter(pk=self.mine.pk).exists())

    def test_remove_takes_the_seat_away_and_keeps_the_notifications(self):
        self.seat()
        self.run_command("--remove")
        self.assertFalse(self.task_client_room.members.filter(pk=self.tr.pk).exists())
        self.assertTrue(Notification.objects.filter(pk=self.mine.pk).exists())

    def test_purge_deletes_only_the_notifications_about_that_room(self):
        self.seat()
        self.run_command("--purge-notifications")
        self.assertFalse(Notification.objects.filter(pk=self.mine.pk).exists())
        self.assertTrue(Notification.objects.filter(pk=self.unrelated.pk).exists())

    def test_nobody_seated_says_so(self):
        self.assertIn("No translator is seated", self.run_command())

