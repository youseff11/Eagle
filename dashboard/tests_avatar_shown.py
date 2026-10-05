"""The staff see each other's profile pictures: in the chats, the people lists and the staff panel - and a client never does.

The address of a picture (``/files/avatars/...``) rides in the JSON the staff's own pages read: the colleague rows, the people
of a work group, the sender of a message, the admin's list. Nothing that leaves for a client carries one: a client is told the
role of whoever answers ("[الأوبريشن] ...") and nothing else about them.
"""

import tempfile
from unittest import mock

from django.conf import settings
from django.test import Client as DjangoClient
from django.test import TestCase, override_settings
from django.urls import reverse

from . import avatars, services
from .models import ChatMessage, ChatRoom, Client, Role, RoomKind, User
from .tests_avatar import jpeg


class _Faces(TestCase):
    def setUp(self):
        folder = tempfile.TemporaryDirectory()
        self.addCleanup(folder.cleanup)
        override = override_settings(
            MEDIA_ROOT=folder.name,
            STORAGES={**settings.STORAGES, "default": {"BACKEND": "dashboard.storages.ProtectedFileSystemStorage"}},
        )
        override.enable()
        self.addCleanup(override.disable)
        make = lambda name, role, **kw: User.objects.create_user(name, password="pw", role=role, **kw)
        self.admin = make("person_admin", Role.ADMIN)
        self.ops = make("person_operation", Role.OPERATION)
        self.lead = make("person_leader", Role.TEAM_LEAD)
        self.tr = make("person_translator", Role.TRANSLATOR, team_lead=self.lead)
        self.plain = make("person_no_picture", Role.HR)
        for person in (self.admin, self.ops, self.lead, self.tr):
            avatars.replace(person, jpeg(32 + person.pk, 32))
            person.refresh_from_db()

    def face(self, person):
        person.refresh_from_db()
        return person.avatar.url

    def get(self, user, name, *args, **query):
        browser = DjangoClient()
        browser.force_login(user)
        return browser.get(reverse(name, args=args), query)

    def json(self, user, name, *args, **query):
        response = self.get(user, name, *args, **query)
        self.assertEqual(response.status_code, 200, (name, response.content[:200]))
        return response.json()


class ChatListTests(_Faces):
    def test_a_colleague_row_carries_their_picture_and_none_when_they_have_none(self):
        for viewer in (self.ops, self.tr, self.lead, self.admin):
            rows = {row["code"]: row for row in self.json(viewer, "dashboard:v1_chats", type="staff")["items"]}
            others = [person for person in (self.ops, self.lead, self.tr, self.admin) if person.pk != viewer.pk]
            for person in others:
                self.assertEqual(rows[f"u{person.pk}"]["avatar"], self.face(person), (viewer.role, person.role))
            self.assertIsNone(rows[f"u{self.plain.pk}"]["avatar"])

    def test_a_group_and_a_client_row_have_no_face_of_a_person(self):
        group = services.lead_translator_group(self.lead, self.tr)
        ChatMessage.objects.create(room=group, sender=self.lead, body="hello")
        rows = self.json(self.lead, "dashboard:v1_chats", type="groups")["items"]
        self.assertTrue(rows)
        for row in rows:
            self.assertFalse(row.get("avatar"), row["code"])

    def test_a_chat_with_a_colleague_nobody_has_written_to_yet_still_carries_their_picture(self):
        body = self.json(self.ops, "dashboard:v1_staff_messages", self.lead.pk)
        self.assertEqual(body["messages"], [])
        self.assertEqual(body["client"]["avatar"], self.face(self.lead))

    def test_the_open_chat_with_a_colleague_carries_their_picture_in_its_head_and_each_sender_in_its_messages(self):
        room = services.staff_room(self.ops, self.lead)
        ChatMessage.objects.create(room=room, sender=self.lead, body="from the leader")
        ChatMessage.objects.create(room=room, sender=self.ops, body="from operation")
        body = self.json(self.ops, "dashboard:v1_staff_messages", self.lead.pk)
        self.assertEqual(body["client"]["avatar"], self.face(self.lead))
        faces = {entry["sender"]: entry["sender_avatar"] for entry in body["messages"]}
        self.assertEqual(faces, {self.lead.short_name: self.face(self.lead), self.ops.short_name: self.face(self.ops)})


class GroupTests(_Faces):
    def test_a_work_groups_messages_carry_each_senders_picture(self):
        group = services.lead_translator_group(self.lead, self.tr)
        ChatMessage.objects.create(room=group, sender=self.lead, body="one")
        ChatMessage.objects.create(room=group, sender=self.tr, body="two")
        for viewer in (self.lead, self.tr):
            body = self.json(viewer, "dashboard:v1_group_messages", group.pk)
            faces = {entry["sender"]: entry["sender_avatar"] for entry in body["messages"]}
            self.assertEqual(faces, {self.lead.short_name: self.face(self.lead), self.tr.short_name: self.face(self.tr)})

    def test_a_system_line_or_a_message_with_no_sender_has_no_picture(self):
        group = services.lead_translator_group(self.lead, self.tr)
        ChatMessage.objects.create(room=group, sender=None, body="a note", is_system=False)
        body = self.json(self.lead, "dashboard:v1_group_messages", group.pk)
        self.assertEqual([entry["sender_avatar"] for entry in body["messages"]], [None])

    def test_the_people_a_group_can_be_opened_with_carry_their_picture(self):
        people = {person["id"]: person for person in self.json(self.ops, "dashboard:v1_people")["people"]}
        self.assertEqual(people[self.lead.pk]["avatar"], self.face(self.lead))
        self.assertIsNone(people[self.plain.pk]["avatar"])

    def test_the_members_of_a_group_and_the_ones_to_add_carry_their_picture(self):
        group = services.lead_translator_group(self.lead, self.tr)
        body = self.json(self.lead, "dashboard:v1_group_members", group.pk)
        self.assertEqual({person["id"]: person["avatar"] for person in body["members"]}, {self.lead.pk: self.face(self.lead), self.tr.pk: self.face(self.tr)})
        self.assertTrue(body["addable"])
        for person in body["addable"]:
            self.assertIn("avatar", person)


class AdminPanelTests(_Faces):
    def test_the_staff_list_and_a_persons_file_carry_their_picture(self):
        rows = {row["id"]: row for row in self.json(self.admin, "dashboard:v1_hr_register")["rows"]}
        self.assertEqual(rows[self.tr.pk]["avatar"], self.face(self.tr))
        self.assertIsNone(rows[self.plain.pk]["avatar"])
        self.assertEqual(self.json(self.admin, "dashboard:v1_hr_employee", self.tr.pk)["person"]["avatar"], self.face(self.tr))
        self.assertEqual(self.json(self.admin, "dashboard:v1_admin_user", self.tr.pk)["user"]["avatar"], self.face(self.tr))

    def test_the_employee_files_are_still_for_hr_and_the_admin_alone(self):
        for viewer in (self.ops, self.lead, self.tr):
            for name, args in (("dashboard:v1_hr_register", ()), ("dashboard:v1_hr_employee", (self.tr.pk,))):
                response = self.get(viewer, name, *args)
                self.assertEqual(response.status_code, 403, (viewer.role, name))
                self.assertNotIn(b"avatars/", response.content)


class NeverToAClientTests(_Faces):
    """Where a client is on the other end, the picture is not."""

    def setUp(self):
        super().setUp()
        self.customer = Client.objects.create(name="Zebulon Trading", phone="+201000000999")
        self.room = ChatRoom.objects.create(kind=RoomKind.CLIENT, client=self.customer, title="Client group", created_by=self.ops)
        self.room.members.add(self.ops, self.admin)

    def test_what_is_relayed_to_the_client_is_the_role_and_the_words_and_no_address_of_a_picture(self):
        message = ChatMessage.objects.create(room=self.room, sender=self.ops, body="We are on it")
        with mock.patch("dashboard.services.send_client_message", return_value=(True, None, "")) as sent:
            ok, _error = services.relay_chat_message(message)
        self.assertTrue(ok)
        sent.assert_called_once()
        body = sent.call_args.kwargs["body"]
        self.assertTrue(body.endswith("We are on it"))
        self.assertTrue(body.startswith("["), body)
        # The role stands in for the person: no name, no picture, no file of theirs among what goes with it.
        for secret in (self.ops.short_name, self.ops.username, "avatars/", self.face(self.ops)):
            self.assertNotIn(secret, body)
        self.assertEqual(sent.call_args.kwargs["extra_files"], [])
        self.assertNotIn("avatars/", repr(sent.call_args))

    def test_the_staff_see_a_colleague_in_a_client_room_and_the_clients_own_line_has_no_face(self):
        ChatMessage.objects.create(room=self.room, sender=self.ops, body="answer")
        inbound = services.ingest_message(channel="whatsapp", body="hello from the client", sender_identity="+201000000999")
        ChatMessage.objects.create(room=self.room, sender=None, body="hello from the client", inbound=inbound)
        body = self.json(self.ops, "dashboard:v1_group_messages", self.room.pk)
        faces = {entry["body"]: entry["sender_avatar"] for entry in body["messages"]}
        self.assertEqual(faces["answer"], self.face(self.ops))
        self.assertIsNone(faces["hello from the client"])

    def test_a_translator_cannot_open_a_client_room_so_never_reads_a_face_in_one(self):
        ChatMessage.objects.create(room=self.room, sender=self.ops, body="answer")
        response = self.get(self.tr, "dashboard:v1_group_messages", self.room.pk)
        self.assertEqual(response.status_code, 404)
        self.assertNotIn(b"avatars/", response.content)
