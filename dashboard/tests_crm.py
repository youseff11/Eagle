"""CRM (``crm.py``, ``api_crm.py``): the real-estate branch's sales team and its sheets (09/11/2026).

Held here:

* CRM is a role of its own, apart from the translation side: nobody on the translation side (Sales, the Sales manager, the
  operation) opens a CRM door, and a CRM person opens no B2B / B2C sheet and is in no client group;
* the manager mark is its own (``crm_manager``), meaningful on a CRM person only, and the Sales manager's mark is not it;
* the manager makes a sheet for one of the team and reads all of them; anybody else on the team reads their own only, and
  another's sheet is a 404; the holder sets the status, the manager also writes the rows;
* a sheet has the owner's five statuses and nothing else;
* the WhatsApp button opens the chat on the holder's own number when the person already talks to it, and otherwise says a
  template is needed, writing nothing; a translation client's code typed by hand is a 404 to a CRM person;
* the owner gives a CRM person a WhatsApp number, and the conversations on it are that person's and the owner's.
"""

import json
from datetime import timedelta

from django.test import Client as DjangoClient
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from . import b2b, crm, lines, newui
from .forms import StaffEditForm
from .models import (
    WA_LINE_ROLES, AuditLog, ChatRoom, Client, CrmContact, CrmSheet, CrmStatus, InboundMessage, LeadSheet, Role, RoomKind, User,
)

NUMBER = "111222333444"


def _json(response):
    return json.loads(response.content.decode("utf-8"))


class _Crm(TestCase):
    def setUp(self):
        make = lambda name, role, **kw: User.objects.create_user(name, password="pw", role=role, first_name=name.title(), **kw)
        self.admin = make("owner", Role.ADMIN)
        self.boss = make("crmboss", Role.CRM, crm_manager=True)
        self.agent = make("agent", Role.CRM, wa_phone_number_id=NUMBER)
        self.other = make("other", Role.CRM)
        self.sales = make("seller", Role.SALES)
        self.sales_boss = make("salesboss", Role.SALES, is_sales_manager=True)
        self.ops = make("ops", Role.OPERATION)
        self.sheet = CrmSheet.objects.create(title="New Cairo", assigned_to=self.agent, created_by=self.boss)
        self.row = CrmContact.objects.create(sheet=self.sheet, name="Ahmed", phone="01001234567")

    def browser(self, user):
        browser = DjangoClient()
        browser.force_login(user)
        return browser

    def get(self, user, name, *args):
        return self.browser(user).get(reverse(f"dashboard:{name}", args=args))

    def post(self, user, name, body, *args):
        return self.browser(user).post(reverse(f"dashboard:{name}", args=args), json.dumps(body), content_type="application/json")


class RoleTests(_Crm):
    def test_crm_is_a_role_with_its_own_manager_mark(self):
        self.assertIn(Role.CRM, Role.values)
        self.assertTrue(self.boss.runs_crm)
        self.assertFalse(self.agent.runs_crm)
        self.assertTrue(self.admin.runs_crm)
        # The Sales manager's mark is not the CRM manager's, and the CRM manager runs nothing of the Sales side.
        self.assertFalse(self.sales_boss.runs_crm)
        self.assertFalse(self.boss.manages_sales)
        self.assertFalse(self.boss.is_sales)

    def test_the_mark_falls_away_off_the_crm_role(self):
        self.boss.role = Role.SALES
        self.boss.save()
        self.boss.refresh_from_db()
        self.assertFalse(self.boss.crm_manager)

    def test_the_staff_form_refuses_the_mark_on_another_role(self):
        form = StaffEditForm(instance=self.sales, data={"role": Role.SALES, "crm_manager": True, "first_name": "S"})
        form.is_valid()
        self.assertIn("crm_manager", form.errors)

    def test_a_crm_person_keeps_a_whatsapp_number_and_works_only_their_own_line(self):
        self.assertIn(Role.CRM, WA_LINE_ROLES)
        self.agent.refresh_from_db()
        self.assertEqual(self.agent.wa_phone_number_id, NUMBER)
        self.assertTrue(self.agent.handles_clients)
        mine = Client.objects.create(name="Lead", phone="+201001234567")
        company = Client.objects.create(name="Translation client", phone="+201009999999")
        InboundMessage.objects.create(client=mine, channel="whatsapp", body="hi", sender_identity="+201001234567", owner=self.agent)
        InboundMessage.objects.create(client=company, channel="whatsapp", body="hi", sender_identity="+201009999999")
        seen = set(InboundMessage.objects.filter(lines.line_q(self.agent)).values_list("client_id", flat=True))
        self.assertEqual(seen, {mine.pk})
        self.assertFalse(lines.sees(self.agent, None, "whatsapp"))

    def test_the_screens_are_the_crm_ones_and_none_of_the_translation_side(self):
        keys = newui.enabled_keys(self.agent)
        self.assertIn("crm", keys)
        self.assertIn("chats", keys)
        self.assertIn("attendance", keys)
        for gone in ("sales", "operation", "lead", "translator_home", "support"):
            self.assertNotIn(gone, keys)
        self.assertNotIn("crm", newui.enabled_keys(self.sales))
        # The owner reads them from their own panel (a line of the admin screen), not as a desk of their own.
        self.assertNotIn("crm", newui.enabled_keys(self.admin))
        self.assertTrue(newui.SCREENS["crm"].allows(self.admin))

    def test_a_crm_person_is_never_in_a_client_group(self):
        room = ChatRoom.objects.create(kind=RoomKind.CLIENT, title="Client group")
        room.members.add(self.agent)
        self.assertFalse(room.can_access(self.agent))
        self.assertFalse(self.agent.joins_client_rooms)
        self.assertTrue(self.sales.joins_client_rooms)

    def test_a_crm_person_has_no_b2b_door(self):
        self.assertFalse(b2b.has_door(self.agent))
        self.assertFalse(b2b.has_door(self.boss))


class DoorTests(_Crm):
    def test_nobody_on_the_translation_side_opens_a_crm_door(self):
        for person in (self.sales, self.sales_boss, self.ops):
            with self.subTest(person=person.username):
                self.assertEqual(self.get(person, "v1_crm_sheets").status_code, 403)
                self.assertEqual(self.get(person, "v1_crm_sheet", self.sheet.pk).status_code, 403)
                self.assertEqual(self.post(person, "v1_crm_row_save", {"status": "interested"}, self.row.pk).status_code, 403)
        self.row.refresh_from_db()
        self.assertEqual(self.row.status, "")

    def test_the_crm_team_opens_no_b2b_sheet(self):
        sheet = LeadSheet.objects.create(title="Germany", assigned_to=self.sales, created_by=self.sales_boss)
        self.assertEqual(self.get(self.boss, "v1_b2b_sheets").status_code, 403)
        self.assertEqual(self.get(self.agent, "v1_b2b_sheet", sheet.pk).status_code, 403)

    def test_the_manager_reads_every_sheet_and_anybody_else_their_own(self):
        theirs = CrmSheet.objects.create(title="Zayed", assigned_to=self.other, created_by=self.boss)
        boss = _json(self.get(self.boss, "v1_crm_sheets"))
        self.assertTrue(boss["can_manage"])
        self.assertEqual({one["id"] for one in boss["sheets"]}, {self.sheet.pk, theirs.pk})
        self.assertEqual({one["id"] for one in boss["holders"]}, {self.boss.pk, self.agent.pk, self.other.pk})
        agent = _json(self.get(self.agent, "v1_crm_sheets"))
        self.assertFalse(agent["can_manage"])
        self.assertEqual([one["id"] for one in agent["sheets"]], [self.sheet.pk])
        self.assertEqual(agent["holders"], [])
        before = AuditLog.objects.count()
        self.assertEqual(self.get(self.agent, "v1_crm_sheet", theirs.pk).status_code, 404)
        self.assertGreater(AuditLog.objects.count(), before)

    def test_the_sheet_carries_the_four_columns_and_the_owners_five_statuses(self):
        data = _json(self.get(self.agent, "v1_crm_sheet", self.sheet.pk))
        self.assertEqual(set(data["rows"][0]), {"id", "name", "phone", "status", "chat"})
        self.assertEqual([one["ar"] for one in data["statuses"]], ["مهتم", "غير مهتم", "طلب عرض سعر", "تم التواصل", "مردش"])
        self.assertTrue(data["can_contact"])
        self.assertFalse(_json(self.get(self.boss, "v1_crm_sheet", self.sheet.pk))["can_contact"])


class WriteTests(_Crm):
    def test_the_manager_makes_a_sheet_for_one_of_the_team_who_is_told(self):
        answer = self.post(self.boss, "v1_crm_sheet_create", {"title": "Sheikh Zayed", "assigned_to": self.other.pk})
        self.assertEqual(answer.status_code, 200, answer.content)
        sheet = CrmSheet.objects.get(pk=_json(answer)["sheet"]["id"])
        self.assertEqual((sheet.assigned_to, sheet.created_by), (self.other, self.boss))
        self.assertTrue(self.other.notifications.filter(url=f"/app/crm/{sheet.pk}").exists())

    def test_a_sheet_goes_to_the_crm_team_only_and_is_made_by_the_manager_only(self):
        self.assertEqual(_json(self.post(self.boss, "v1_crm_sheet_create", {"title": "X", "assigned_to": self.sales.pk}))["error"], "bad_holder")
        self.assertEqual(_json(self.post(self.agent, "v1_crm_sheet_create", {"title": "X", "assigned_to": self.agent.pk}))["error"], "not_manager")
        self.assertEqual(CrmSheet.objects.count(), 1)

    def test_the_manager_adds_rows_and_hands_the_sheet_on(self):
        answer = self.post(self.boss, "v1_crm_rows_add", {"rows": [{"name": "Mona", "phone": "01112223334"}, {"name": "", "phone": ""}]}, self.sheet.pk)
        self.assertEqual(answer.status_code, 200, answer.content)
        self.assertEqual(self.sheet.contacts.count(), 2)
        self.assertEqual(self.post(self.boss, "v1_crm_sheet_save", {"assigned_to": self.other.pk}, self.sheet.pk).status_code, 200)
        self.sheet.refresh_from_db()
        self.assertEqual(self.sheet.assigned_to, self.other)
        self.assertEqual(self.get(self.agent, "v1_crm_sheet", self.sheet.pk).status_code, 404)

    def test_the_holder_sets_the_status_and_nothing_else(self):
        answer = self.post(self.agent, "v1_crm_row_save", {"status": CrmStatus.QUOTE_REQUESTED}, self.row.pk)
        self.assertEqual(answer.status_code, 200, answer.content)
        self.row.refresh_from_db()
        self.assertEqual(self.row.status, CrmStatus.QUOTE_REQUESTED)
        self.assertEqual(_json(self.post(self.agent, "v1_crm_row_save", {"status": "won"}, self.row.pk))["error"], "bad_status")
        self.assertEqual(_json(self.post(self.agent, "v1_crm_row_save", {"name": "Someone"}, self.row.pk))["error"], "not_manager")
        self.assertEqual(_json(self.post(self.agent, "v1_crm_rows_add", {"rows": [{"name": "Z"}]}, self.sheet.pk))["error"], "not_manager")
        self.assertEqual(self.post(self.agent, "v1_crm_row_delete", {}, self.row.pk).status_code, 400)
        self.row.refresh_from_db()
        self.assertEqual(self.row.name, "Ahmed")
        counts = _json(self.get(self.agent, "v1_crm_sheets"))["sheets"][0]["counts"]
        self.assertEqual((counts["rows"], counts["quote_requested"], counts["interested"]), (1, 1, 0))

    def test_another_crm_person_cannot_touch_the_row(self):
        self.assertEqual(self.post(self.other, "v1_crm_row_save", {"status": "interested"}, self.row.pk).status_code, 404)
        self.row.refresh_from_db()
        self.assertEqual(self.row.status, "")

    def test_a_new_phone_drops_the_chat_the_old_one_opened(self):
        client = Client.objects.create(name="Ahmed", phone="+201001234567")
        self.row.client = client
        self.row.save()
        self.post(self.boss, "v1_crm_row_save", {"phone": "01009998887"}, self.row.pk)
        self.row.refresh_from_db()
        self.assertIsNone(self.row.client)


class WhatsappTests(_Crm):
    def press(self, user=None):
        return self.post(user or self.agent, "v1_crm_row_whatsapp", {}, self.row.pk)

    def test_with_no_conversation_it_says_a_template_is_needed_and_writes_nothing(self):
        clients = Client.objects.count()
        answer = self.press()
        self.assertEqual(answer.status_code, 400)
        self.assertEqual(_json(answer)["error"], "needs_template")
        self.assertEqual(Client.objects.count(), clients)

    def test_it_opens_the_chat_of_someone_who_wrote_to_the_holders_number(self):
        client = Client.objects.create(name="Ahmed", phone="+201001234567")
        InboundMessage.objects.create(client=client, channel="whatsapp", body="hello", sender_identity="+201001234567", owner=self.agent)
        answer = self.press()
        self.assertEqual(answer.status_code, 200, answer.content)
        self.assertEqual(_json(answer)["chat"], client.code)
        self.row.refresh_from_db()
        self.assertEqual(self.row.client, client)
        # And the chat door opens it to them.
        self.assertEqual(self.get(self.agent, "v1_client_messages", client.code).status_code, 200)

    def test_someone_who_wrote_to_the_company_number_is_not_the_holders(self):
        client = Client.objects.create(name="Ahmed", phone="+201001234567")
        InboundMessage.objects.create(client=client, channel="whatsapp", body="hello", sender_identity="+201001234567")
        self.assertEqual(_json(self.press())["error"], "needs_template")

    def test_only_the_holder_with_a_number_presses_it(self):
        self.assertEqual(_json(self.press(self.boss))["error"], "not_yours")
        self.agent.wa_phone_number_id = ""
        self.agent.save()
        self.assertEqual(_json(self.press())["error"], "no_line")

    def test_a_translation_clients_code_is_a_404_to_crm(self):
        client = Client.objects.create(name="Translation client", phone="+201009999999")
        InboundMessage.objects.create(client=client, channel="whatsapp", body="x", sender_identity="+201009999999")
        self.assertEqual(self.get(self.agent, "v1_client_messages", client.code).status_code, 404)
        self.assertEqual(self.get(self.boss, "v1_client_messages", client.code).status_code, 404)
        self.assertFalse(crm.may_open_client(self.agent, client))
        # Sales, as before, is not changed by this.
        self.assertNotEqual(self.get(self.ops, "v1_client_messages", client.code).status_code, 404)

    def test_the_translation_follow_up_template_is_never_offered_to_crm(self):
        from . import followup

        client = Client.objects.create(name="Ahmed", phone="+201001234567")
        message = InboundMessage.objects.create(client=client, channel="whatsapp", body="hello", sender_identity="+201001234567", owner=self.agent)
        # Two days ago: the window is closed, so a Sales person would be offered it here.
        InboundMessage.objects.filter(pk=message.pk).update(received_at=timezone.now() - timedelta(days=2))
        self.assertIsNone(followup.offer(client, self.agent))
        with self.assertRaises(followup.Refused):
            followup.send(client, self.agent, "ar")


class SupportMakesCrmAccountsTests(_Crm):
    """Technical support makes the CRM team's accounts and works in them, as it does for every other employee."""

    def setUp(self):
        super().setUp()
        self.support = User.objects.create_user("tech", password="pw", role=Role.SUPPORT, first_name="Tech")

    def test_the_new_employee_form_offers_crm_to_support(self):
        form = _json(self.get(self.support, "v1_admin_user_new"))["form"]
        role = next(field for field in form if field["name"] == "role")
        values = {choice["value"] for choice in role["choices"]}
        self.assertIn(Role.CRM, values)
        self.assertNotIn(Role.ADMIN, values)

    def test_support_makes_a_crm_account(self):
        body = {"values": {"username": "crm_new", "first_name": "Hala", "last_name": "Estate", "role": "crm",
                           "password1": "Mx7-quiet-harbour-41", "password2": "Mx7-quiet-harbour-41"}}
        answer = self.post(self.support, "v1_admin_user_create", body)
        self.assertEqual(answer.status_code, 200, answer.content)
        made = User.objects.get(username="crm_new")
        self.assertEqual(made.role, Role.CRM)
        self.assertTrue(made.check_password("Mx7-quiet-harbour-41"))
        self.assertIn("crm", newui.enabled_keys(made))

    def test_support_may_open_a_crm_account(self):
        from . import impersonation

        self.assertIn(self.agent, impersonation.accounts())
        self.assertTrue(impersonation.may_open(self.support, self.agent))
