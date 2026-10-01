"""The chat lists (``/api/v1/chats/``): a fixed handful of queries, and the same rows as before.

Every row used to ask the database half a dozen questions of its own - the last thing said, on which
line, the 24-hour window, the channel - so a list of a hundred clients was some seven hundred
queries, asked again at every refresh. ``chatlists`` now asks them once for the whole list.

Two things are pinned here. The cost does not grow with the list. And every row of every list, for
every role, is exactly what the single-row functions (``api._conversation_json`` and
``api._group_json`` without facts, which still serve a single conversation) say: they are the
specification, and this is what keeps the bulk fetch from drifting from it - the rows that matter
most are the ones that decide who may read what (``lines.line_q``, the rate-block rule).
"""

import json
from datetime import timedelta

from django.db import connection
from django.test import Client as DjangoClient
from django.test import TestCase
from django.test.utils import CaptureQueriesContext
from django.urls import reverse
from django.utils import timezone

from . import api, services
from .models import (
    AppSettings, Channel, ChatAttachment, ChatMessage, ChatRead, ChatRoom, Client, InboundMessage, MessageAttachment,
    OutboundAttachment, OutboundMessage, Role, RoomKind, User,
)


def _json(response):
    return json.loads(response.content.decode("utf-8"))


class _Data(TestCase):
    """One of each role, and as many clients, groups and staff chats as a test asks for."""

    def setUp(self):
        make = lambda name, role, **kw: User.objects.create_user(name, password="pw", role=role, **kw)
        self.admin = make("person_admin", Role.ADMIN)
        self.ops = make("person_operation", Role.OPERATION)
        self.lead = make("person_leader", Role.TEAM_LEAD)
        self.tr = make("person_translator", Role.TRANSLATOR, team_lead=self.lead)
        self.sales = make("person_salesman", Role.SALES)
        # A second Sales person with a number of their own, and a superuser whose role is still "sales":
        # ``line_q`` reads them as an admin (every line), ``reply_line`` as a Sales person (their own).
        self.sales2 = make("person_salesman_b", Role.SALES)
        boss = make("person_boss_sales", Role.SALES)
        User.objects.filter(pk=boss.pk).update(is_superuser=True)
        self.boss_sales = User.objects.get(pk=boss.pk)
        self.hr = make("person_hr_staff", Role.HR)
        # The operation has an address of its own on the company mailbox.
        User.objects.filter(pk=self.ops.pk).update(mail_alias="ops@example.test")
        self.ops = User.objects.get(pk=self.ops.pk)
        self.everyone = [
            self.admin, self.ops, self.lead, self.tr, self.sales, self.sales2, self.boss_sales, self.hr,
        ]
        self.clients = []
        self.team_groups = 0

    # -- the data ---------------------------------------------------------------
    def add_clients(self, count):
        now = timezone.now()
        for index in range(len(self.clients), len(self.clients) + count):
            self.add_client(index, now)

    def add_client(self, index, now):
        client = Client.objects.create(
            name=f"Client {index}", phone=f"+2010000{index:05d}", email=f"c{index}@example.test",
        )
        self.clients.append(client)

        def said(body, minutes, **extra):
            return InboundMessage.objects.create(
                client=client, channel=extra.pop("channel", Channel.WHATSAPP), body=body,
                received_at=now - timedelta(minutes=minutes), **extra,
            )

        company = said(f"hello {index}", index + 3)
        newest = {"received_at": now + timedelta(minutes=3)}  # after everything we sent: it is the row's text
        if index % 6 == 5:  # only a photo
            InboundMessage.objects.filter(pk=company.pk).update(body="", **newest)
            MessageAttachment.objects.create(message=company, file="in/photo.jpg", original_name="photo.jpg")
        if index % 7 == 3:  # only a voice note
            InboundMessage.objects.filter(pk=company.pk).update(body="", **newest)
            MessageAttachment.objects.create(
                message=company, file="in/note.ogg", original_name="note.ogg", mime="audio/ogg", is_voice=True,
            )
        if index % 2:  # the client also wrote to a Sales person's own number, more recently
            said(f"to sales {index}", index + 1, owner=self.sales)
        if index % 3 == 1:  # and to the other Sales person's
            said(f"to the other sales {index}", index + 2, owner=self.sales2)
        if index % 3 == 0:  # a message the rate rule hides from everybody but the admin
            said("a rate is mentioned", -1, is_rate_blocked=True)
        if index % 4 == 0:  # and an e-mail, which is not part of this list but is how they last wrote - lately
            said("by e-mail", -4, channel=Channel.EMAIL, subject="Mail")
        if index % 8 == 0:  # a letter to the operation's own address
            said("to the operation's address", index, channel=Channel.EMAIL, owner=self.ops, subject="Own mail")

        sent = OutboundMessage.objects.create(
            client=client, kind=OutboundMessage.Kind.CHAT, channel=Channel.WHATSAPP, body=f"reply {index}",
            status=OutboundMessage.Status.SENT, wa_receipt="read" if index % 3 == 0 else "",
            owner=self.sales if index % 5 == 1 else None,
        )
        if index % 9 == 4:  # only a file
            OutboundMessage.objects.filter(pk=sent.pk).update(body="")
            OutboundAttachment.objects.create(message=sent, file="out/a.pdf", original_name="a.pdf")
        if index % 9 == 8:  # a file the row can only count
            OutboundMessage.objects.filter(pk=sent.pk).update(body="", files=[{"name": "a.pdf"}])
        if index % 7 == 2:  # the client had the last word
            said(f"thank you {index}", -2)
        if index % 4 == 2:  # an e-mail reply of ours, the newest thing we sent - the WhatsApp row must not show it
            mail = OutboundMessage.objects.create(
                client=client, kind=OutboundMessage.Kind.CHAT, channel=Channel.EMAIL, body="a mail reply",
                status=OutboundMessage.Status.SENT,
            )
            OutboundMessage.objects.filter(pk=mail.pk).update(created_at=now + timedelta(minutes=5))

        # A group with the client, and a few messages in it.
        room = ChatRoom.objects.create(
            kind=RoomKind.CLIENT, client=client, title=f"Group {index}", created_by=self.ops,
        )
        room.members.add(self.ops, self.lead)
        for number in range(2):
            ChatMessage.objects.create(
                room=room, sender=self.ops, body=f"in the group {index}.{number}",
                relay_receipt="read" if index % 3 == 0 else "", relay_status="sent",
            )
        if index % 4 == 1:  # the last word was a colleague's
            ChatMessage.objects.create(room=room, sender=self.lead, body="from the leader")
        if index % 5 == 2:  # the last message is a file
            file_only = ChatMessage.objects.create(room=room, sender=self.ops, body="")
            ChatAttachment.objects.create(message=file_only, file="chat/p.png", original_name="p.png")
        if index % 6 == 1:  # a system line after it
            services.system_message(room, key="note", body_ar="ملاحظة", body_en="A note")
        if index % 8 == 7:  # a room nobody has spoken in
            empty = ChatRoom.objects.create(kind=RoomKind.CLIENT, client=client, title="Quiet", created_by=self.ops)
            empty.members.add(self.ops)

    def add_a_client_who_went_quiet(self):
        """Wrote to the company number a day and a half ago, and to a Sales number an hour ago:
        the operation's 24 hours are over, the Sales person's - and the admin's, who answers on
        whichever number was written to last - are not."""
        now = timezone.now()
        client = Client.objects.create(name="Quiet client", phone="+201099999999")
        self.clients.append(client)
        InboundMessage.objects.create(
            client=client, channel=Channel.WHATSAPP, body="long ago", received_at=now - timedelta(hours=36),
        )
        InboundMessage.objects.create(
            client=client, channel=Channel.WHATSAPP, body="to sales", owner=self.sales,
            received_at=now - timedelta(hours=1),
        )
        return client

    def add_a_task_room(self, which=0):
        task = services.create_task(
            client=self.clients[which], title=f"A task {which}", created_by=self.ops,
            deadline=timezone.now() + timedelta(hours=4),
        )
        room = services.ensure_room(task, RoomKind.CLIENT)
        if which % 2:
            # The older shape: the room knows its task and finds the client through it.
            ChatRoom.objects.filter(pk=room.pk).update(client=None)
        room.members.add(self.ops, self.lead)
        ChatMessage.objects.create(room=room, sender=self.ops, body="about the task")
        return task

    def add_a_task_team_room_with_source_files(self):
        """A work room for a task, with a mirrored client message of two photos of which the task kept one.

        The row names what is in the message ("a photo" or "2 photos"), so it must count the files the room
        shows - the task's own - not everything the client sent (``ChatMessage.relay_files``).
        """
        client = self.clients[0]
        inbound = InboundMessage.objects.create(client=client, channel=Channel.WHATSAPP, body="two photos")
        one = MessageAttachment.objects.create(message=inbound, file="in/one.jpg", original_name="one.jpg")
        MessageAttachment.objects.create(message=inbound, file="in/two.jpg", original_name="two.jpg")
        task = services.create_task(
            client=client, title="With files", created_by=self.ops, deadline=timezone.now() + timedelta(hours=4),
        )
        from .models import Task

        Task.objects.filter(pk=task.pk).update(team_lead=self.lead)
        task = Task.objects.get(pk=task.pk)
        task.source_files.add(one)
        room = ChatRoom.objects.create(kind=RoomKind.TEAM, task=task, title="Task team", created_by=self.lead)
        room.members.add(self.lead, self.tr)
        ChatMessage.objects.create(room=room, sender=self.ops, body="", inbound=inbound, task=task)
        return room

    def add_team_groups_and_staff(self, count):
        for index in range(count):
            person = User.objects.create_user(f"person_staff_{self.team_groups}", password="pw", role=Role.OPERATION)
            self.team_groups += 1
            room, _ = services.create_team_group(self.lead, f"Team {index}", [person, self.tr])
            ChatMessage.objects.create(room=room, sender=person, body=f"an answer {index}")
            last = ChatMessage.objects.create(room=room, sender=self.lead, body=f"team talk {index}")
            # One reader, or all of them: the leader's message is "seen" only when everybody has read it.
            ChatRead.objects.create(user=person, room=room, last_read_id=last.pk)
            if index % 2:
                ChatRead.objects.create(user=self.tr, room=room, last_read_id=last.pk)
            staff = services.staff_room(self.ops, person)
            ChatMessage.objects.create(room=staff, sender=person, body=f"a private word {index}")
            # The leader's own last word to a colleague, read by them or not, and a chat that ends on a system line.
            with_lead = services.staff_room(self.lead, person)
            mine = ChatMessage.objects.create(room=with_lead, sender=self.lead, body=f"a word from the leader {index}")
            if index % 2:
                ChatRead.objects.create(user=person, room=with_lead, last_read_id=mine.pk)
            ended = services.staff_room(self.sales, person)
            ChatMessage.objects.create(room=ended, sender=self.sales, body=f"a word from sales {index}")
            ChatMessage.objects.create(room=ended, is_system=True, body="the chat was opened")

    def assertRows(self, got, want, label):
        """Row by row, so a difference says which row and which field."""
        self.assertEqual(set(got), set(want), f"{label}: not the same rows")
        for code in sorted(got):
            self.assertEqual(got[code], want[code], f"{label}: {code}")

    # -- asking -----------------------------------------------------------------
    def ask(self, user, kind):
        browser = DjangoClient()
        browser.force_login(user)
        browser.get(reverse("dashboard:v1_chats"), {"type": kind})  # warm the session
        with CaptureQueriesContext(connection) as queries:
            answer = browser.get(reverse("dashboard:v1_chats"), {"type": kind})
        self.assertEqual(answer.status_code, 200, (user.username, kind))
        return _json(answer), len(queries)


class ListsCostTheSameHoweverLongTests(_Data):
    def test_the_number_of_queries_does_not_grow_with_the_list(self):
        self.add_clients(3)
        self.add_team_groups_and_staff(2)
        self.add_a_task_room()
        small = {
            (u.username, k): self.ask(u, k)
            for u in self.everyone for k in ("clients", "groups", "staff")
        }
        self.add_clients(14)
        self.add_team_groups_and_staff(6)
        for which in (1, 2, 3):  # rooms that belong to a task: their client is found through the task
            self.add_a_task_room(which)
        for (name, kind), (body_small, cost_small) in small.items():
            user = User.objects.get(username=name)
            body_large, cost_large = self.ask(user, kind)
            self.assertEqual(cost_large, cost_small, f"{name} {kind}")
            if kind != "staff" and name in ("person_operation", "person_admin"):
                self.assertGreater(len(body_large["items"]), len(body_small["items"]), f"{name} {kind}")

    def test_a_long_list_stays_within_a_small_ceiling(self):
        self.add_clients(30)
        self.add_team_groups_and_staff(4)
        for user in (self.admin, self.ops, self.sales):
            body, cost = self.ask(user, "clients")
            self.assertLessEqual(cost, 16, f"{user.username} clients")
        for user in (self.admin, self.ops, self.lead):
            body, cost = self.ask(user, "groups")
            self.assertLessEqual(cost, 16, f"{user.username} groups ({len(body['items'])} rows)")


class EveryRowIsWhatTheSingleRowPathSaysTests(_Data):
    """The bulk fetch against its specification, for every role."""

    def setUp(self):
        super().setUp()
        self.add_clients(26)
        self.quiet = self.add_a_client_who_went_quiet()
        self.add_a_task_room()
        self.team_with_files = self.add_a_task_team_room_with_source_files()
        self.add_team_groups_and_staff(4)

    def unassigned_mail(self, to_admin_only):
        conf = AppSettings.load()
        conf.mail_unassigned_admin_only = to_admin_only
        conf.save()

    def test_every_client_row_of_every_role(self):
        # Under both settings of the mail rule: it changes which letters are whose, and so the channel.
        seen_rows = 0
        for to_admin_only in (False, True):
            self.unassigned_mail(to_admin_only)
            for user in self.everyone:
                body, _ = self.ask(user, "clients")
                got = {item["code"]: item for item in body["items"]}
                clients = list(services.client_conversations(user)[:100]) if user.handles_clients else []
                unread = services.unread_by_client(user, [c.pk for c in clients])
                want = {c.code: api._conversation_json(c, user, unread.get(c.pk, 0)) for c in clients}
                self.assertRows(got, want, f"{user.username} / mail to admin only: {to_admin_only}")
                seen_rows += len(got)
        self.assertGreater(seen_rows, 80)

    def test_every_group_row_of_every_role(self):
        seen_rows = 0
        for user in self.everyone:
            body, _ = self.ask(user, "groups")
            got = {item["code"]: item for item in body["items"]}
            rooms = list(services.groups_for(user)[:100])
            unread = services.unread_by_room(user, [r.id for r in rooms])
            want = {f"g{r.id}": api._group_json(r, user, unread.get(r.id, 0)) for r in rooms}
            self.assertRows(got, want, user.username)
            seen_rows += len(got)
        self.assertGreater(seen_rows, 40)

    def test_the_data_really_exercises_the_branches_the_comparison_is_about(self):
        # A comparison of two empty things is a pass for nothing: look at what was compared.
        admin_clients = self.ask(self.admin, "clients")[0]["items"]
        ops_clients = self.ask(self.ops, "clients")[0]["items"]
        sales_clients = self.ask(self.sales, "clients")[0]["items"]
        texts = {item["text"] for item in admin_clients}
        for expected in ("صورة", "رسالة صوتية", "1 ملف"):
            self.assertTrue(any(expected in text for text in texts), expected)
        self.assertTrue(any(item["outgoing"] for item in ops_clients))
        self.assertTrue(any(not item["outgoing"] for item in ops_clients))
        self.assertIn("read", {item["receipt"] for item in ops_clients})
        # The window is the viewer's own line: it differs between who answers from which number.
        windows = lambda items: {item["code"]: (item["window_open"], item["minutes_left"]) for item in items}
        self.assertNotEqual(windows(ops_clients), windows(admin_clients))
        self.assertTrue(any(open_ for open_, _ in windows(admin_clients).values()))
        quiet = self.quiet.code
        self.assertFalse(windows(ops_clients)[quiet][0], "the operation answers from the company's number")
        self.assertTrue(windows(admin_clients)[quiet][0], "the admin from the one written to last")
        self.assertTrue(windows(sales_clients)[quiet][0], "a Sales person from their own")
        self.assertTrue(sales_clients)
        sales2_clients = self.ask(self.sales2, "clients")[0]["items"]
        self.assertTrue(sales2_clients)
        self.assertNotEqual(
            {item["code"] for item in sales_clients}, {item["code"] for item in sales2_clients},
            "two Sales people each have their own numbers",
        )
        self.assertEqual(
            {item["code"] for item in sales2_clients} - {item["code"] for item in admin_clients}, set()
        )
        # A superuser whose role is "sales" is shown every line's messages but answers from their own number.
        boss = {item["code"]: item for item in self.ask(self.boss_sales, "clients")[0]["items"]}
        self.assertEqual(set(boss), {item["code"] for item in admin_clients})
        self.assertNotEqual(windows(list(boss.values())), windows(admin_clients))
        self.assertEqual(
            {item["code"] for item in sales_clients} - {item["code"] for item in admin_clients}, set()
        )
        self.assertIn(Channel.EMAIL, {item["channel"] for item in admin_clients})
        self.assertIn(Channel.WHATSAPP, {item["channel"] for item in admin_clients})

        groups = self.ask(self.ops, "groups")[0]["items"]
        lead_groups = self.ask(self.lead, "groups")[0]["items"]
        # The work room's row counts what the room shows - the one photo the task kept, not both.
        counted = next(item for item in lead_groups if item["code"] == f"g{self.team_with_files.pk}")
        self.assertEqual(counted["text"], "صورة")
        self.assertIn("read", {item["receipt"] for item in groups})
        self.assertTrue(any(item["text"] == "" for item in groups), "an empty room")
        self.assertTrue(any(item["reaches_client"] for item in groups))
        self.assertTrue(any(item["team"] for item in lead_groups))
        self.assertIn("read", {item["receipt"] for item in lead_groups if item["team"]})
        self.assertIn("", {item["receipt"] for item in lead_groups if item["team"] and item["outgoing"]})

    def test_what_a_role_may_not_read_is_not_in_its_rows_at_all(self):
        # The rate-blocked message is the newest on every third client, and the operation never sees it.
        ops = {item["code"]: item for item in self.ask(self.ops, "clients")[0]["items"]}
        admin = {item["code"]: item for item in self.ask(self.admin, "clients")[0]["items"]}
        self.assertNotIn("a rate is mentioned", json.dumps(ops))
        self.assertIn("a rate is mentioned", json.dumps(admin))
        # And a Sales person's own number is theirs: the operation's rows never carry what was said on it.
        self.assertNotIn("to sales", json.dumps(ops))
        self.assertIn("to sales", json.dumps(self.ask(self.sales, "clients")[0]))

    def test_the_classic_chat_pages_sidebar_says_the_same(self):
        from . import views

        compared = 0
        for user in self.everyone:
            for row in views._chat_sidebar(user, "", "clients"):
                self.assertEqual(row["preview"], services.conversation_preview(row["client"], user), user.username)
                compared += 1
            for row in views._chat_sidebar(user, "", "groups"):
                self.assertEqual(row["preview"], services.group_preview(row["room"], user), user.username)
                compared += 1
        self.assertGreater(compared, 60)

    def test_every_staff_row_of_every_role(self):
        for user in self.everyone:
            rows = services.staff_conversations(user)
            for row in rows:
                room = row["room"]
                if room is None:
                    self.assertEqual(row["preview"], {"text": "", "at": None, "outgoing": False})
                    continue
                last = room.messages.order_by("-id").first()
                want = (
                    services._room_last_preview(room, user, last) if last is not None
                    else {"text": "", "at": None, "outgoing": False}
                )
                self.assertEqual(row["preview"], want, (user.username, room.pk))
        spoken = [r for r in services.staff_conversations(self.ops) if r["room"] is not None]
        self.assertGreaterEqual(len(spoken), 4)
        # The chats that end on the viewer's own word (ticks, read or not) and on a system line were compared too.
        lead_rows = [r for r in services.staff_conversations(self.lead) if r["room"] is not None]
        self.assertIn("read", {r["preview"]["receipt"] for r in lead_rows})
        self.assertIn("", {r["preview"]["receipt"] for r in lead_rows if r["preview"]["outgoing"]})
        sales_rows = [r for r in services.staff_conversations(self.sales) if r["room"] is not None]
        self.assertTrue(any(r["room"].messages.order_by("-id").first().is_system for r in sales_rows))

    def test_a_staff_chat_nobody_has_written_in_has_no_time(self):
        quiet = User.objects.create_user("person_quiet", password="pw", role=Role.OPERATION)
        services.staff_room(self.ops, quiet)
        row = next(r for r in services.staff_conversations(self.ops) if r["person"] == quiet)
        self.assertIsNone(row["preview"]["at"])

    def test_a_translator_gets_no_client_row_and_no_client_group(self):
        self.assertEqual(self.ask(self.tr, "clients")[0]["items"], [])
        rows = self.ask(self.tr, "groups")[0]["items"]
        self.assertTrue(rows)
        self.assertFalse(any(item["reaches_client"] for item in rows))


class NewestFirstTests(_Data):
    """The lists are in the order of the moments, not of the text of the times ("9:30 AM" sorts after "10:30 AM")."""

    def at(self, hour, minute):
        day = timezone.localtime().replace(hour=0, minute=0, second=0, microsecond=0)
        return day.replace(hour=hour, minute=minute)

    def test_clients_are_listed_newest_first_across_the_morning_and_the_evening(self):
        order = []
        for hour, minute in ((9, 30), (22, 15), (10, 30), (11, 15), (0, 45), (12, 5)):
            client = Client.objects.create(name=f"At {hour}:{minute}", phone=f"+201{hour:02d}{minute:02d}00000")
            InboundMessage.objects.create(
                client=client, channel=Channel.WHATSAPP, body="hello", received_at=self.at(hour, minute),
            )
            order.append((self.at(hour, minute), client.code))
        want = [code for _when, code in sorted(order, reverse=True)]
        body, _ = self.ask(self.ops, "clients")
        self.assertEqual([item["code"] for item in body["items"]], want)

    def test_groups_are_listed_newest_first_too(self):
        order = []
        for hour, minute in ((9, 30), (22, 15), (10, 30), (11, 15)):
            client = Client.objects.create(name=f"Group {hour}:{minute}", phone=f"+202{hour:02d}{minute:02d}00000")
            room = ChatRoom.objects.create(kind=RoomKind.CLIENT, client=client, title=f"G{hour}:{minute}", created_by=self.ops)
            room.members.add(self.ops)
            message = ChatMessage.objects.create(room=room, sender=self.lead, body="hello")
            ChatMessage.objects.filter(pk=message.pk).update(created_at=self.at(hour, minute))
            order.append((self.at(hour, minute), f"g{room.pk}"))
        want = [code for _when, code in sorted(order, reverse=True)]
        body, _ = self.ask(self.ops, "groups")
        self.assertEqual([item["code"] for item in body["items"]], want)

    def test_a_row_with_nothing_yet_goes_last(self):
        client = Client.objects.create(name="Quiet", phone="+201555000000")
        InboundMessage.objects.create(client=client, channel=Channel.WHATSAPP, body="hi", received_at=self.at(8, 0))
        InboundMessage.objects.filter(client=client).update(is_rate_blocked=True)  # the operation may not see it
        loud = Client.objects.create(name="Loud", phone="+201555000001")
        InboundMessage.objects.create(client=loud, channel=Channel.WHATSAPP, body="hi", received_at=self.at(7, 0))
        body, _ = self.ask(self.ops, "clients")
        self.assertEqual([item["code"] for item in body["items"]], [loud.code])

