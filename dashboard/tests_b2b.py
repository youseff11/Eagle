"""B2B company sheets (``b2b.py``, ``api_b2b.py``): the Sales manager makes a sheet for a Sales person, who fills it and
contacts each company from its row.

Held here:

* who: the sheet's Sales person reads and writes it and is the only one who contacts from it; the Sales manager and the owner
  read and write all of them and are the only ones who make, hand over and delete sheets; another Sales person gets a
  written-down 404, and every other role a written-down 403;
* the WhatsApp button sends the approved opening template from the person's own number, makes the client, and marks the
  row; a second press, or a company whose window is open, sends nothing; a refused send marks nothing;
* any message the Sales person sends the company later (the chats, the mail) marks the row by itself - and only theirs, on
  their own line: the company line or another Sales person does not count;
* a call is written by hand; a contacted company is never deleted; the owner's staff reset takes the sheets with it.
"""

import json
from datetime import timedelta
from decimal import Decimal
from unittest import mock

from django.test import Client as DjangoClient
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from . import b2b, identity, services, whatsapp
from .forms import StaffEditForm
from .tests_reset_staff import _Staff
from .models import (
    AuditLog, Channel, Client, InboundMessage, Lead, LeadActivity, LeadSheet, OutboundMessage, Quotation, Role, Task, User,
)

PHONE = "+44 7700 900123"


def _json(response):
    return json.loads(response.content.decode("utf-8"))


class _B2b(TestCase):
    def setUp(self):
        make = lambda name, role, **kw: User.objects.create_user(name, password="pw", role=role, first_name=name.title(), **kw)
        self.admin = make("owner", Role.ADMIN)
        self.manager = make("manager", Role.SALES, is_sales_manager=True, wa_phone_number_id="900001", mail_alias="manager@eagle.test")
        self.sales = make("seller", Role.SALES, wa_phone_number_id="900002", mail_alias="seller@eagle.test")
        self.other = make("other", Role.SALES, wa_phone_number_id="900003", mail_alias="other@eagle.test")
        self.ops = make("ops", Role.OPERATION)
        self.tr = make("tr", Role.TRANSLATOR)
        self.sheet = LeadSheet.objects.create(title="Germany", assigned_to=self.sales, created_by=self.manager)
        self.lead = Lead.objects.create(
            sheet=self.sheet, company_name="Lingua GmbH", country="Germany", contact_person="Anna Schmidt",
            email="anna@lingua.test", whatsapp=PHONE, languages="German to Arabic",
        )
        self.template = mock.patch("dashboard.whatsapp.send_template", return_value="wamid.intro.1").start()
        self.text = mock.patch("dashboard.whatsapp.send_text", return_value="wamid.text.1").start()
        self.mail = mock.patch("dashboard.mailer.send_delivery").start()
        self.addCleanup(mock.patch.stopall)

    def browser(self, user):
        browser = DjangoClient()
        browser.force_login(user)
        return browser

    def get(self, user, name, *args):
        return self.browser(user).get(reverse(f"dashboard:{name}", args=args))

    def post(self, user, name, body, *args):
        return self.browser(user).post(reverse(f"dashboard:{name}", args=args), json.dumps(body), content_type="application/json")


class DoorTests(_B2b):
    def test_the_doors_are_under_api_v1(self):
        # A test of a door that is not there passes blind: each name is the address the page calls.
        self.assertEqual(reverse("dashboard:v1_b2b_sheets"), "/api/v1/b2b/sheets/")
        self.assertEqual(reverse("dashboard:v1_b2b_lead_whatsapp", args=[7]), "/api/v1/b2b/leads/7/whatsapp/")
        self.assertEqual(reverse("dashboard:v1_b2b_rows_add", args=[3]), "/api/v1/b2b/sheets/3/rows/")

    def test_roles_without_a_door_are_a_written_403(self):
        for user in (self.ops, self.tr):
            answer = self.get(user, "v1_b2b_sheets")
            self.assertEqual((answer.status_code, _json(answer)["error"]), (403, "forbidden"), user.username)
            answer = self.get(user, "v1_b2b_sheet", self.sheet.pk)
            self.assertEqual(answer.status_code, 403)
        self.assertTrue(AuditLog.objects.filter(actor=self.ops, action=identity.ACCESS_DENIED).exists())

    def test_a_sales_person_lists_their_own_sheets_only(self):
        LeadSheet.objects.create(title="Spain", assigned_to=self.other, created_by=self.manager)
        mine = [s["title"] for s in _json(self.get(self.sales, "v1_b2b_sheets"))["sheets"]]
        self.assertEqual(mine, ["Germany"])
        body = _json(self.get(self.sales, "v1_b2b_sheets"))
        self.assertFalse(body["can_manage"])
        self.assertEqual(body["sales"], [])
        for user in (self.manager, self.admin):
            body = _json(self.get(user, "v1_b2b_sheets"))
            self.assertEqual({s["title"] for s in body["sheets"]}, {"Germany", "Spain"}, user.username)
            self.assertTrue(body["can_manage"])
            # The manager hands the sheets out and may keep one (13/10/2026): on the list; the owner never.
            self.assertEqual({p["id"] for p in body["sales"]}, {self.sales.pk, self.other.pk, self.manager.pk})

    def test_another_sales_persons_sheet_is_a_written_404(self):
        for name, args in (("v1_b2b_sheet", [self.sheet.pk]), ("v1_b2b_lead", [self.lead.pk])):
            answer = self.get(self.other, name, *args)
            self.assertEqual(answer.status_code, 404, name)
            self.assertNotIn("Lingua", answer.content.decode())
        self.assertEqual(self.post(self.other, "v1_b2b_lead_save", {"company_name": "x"}, self.lead.pk).status_code, 404)
        self.assertEqual(self.post(self.other, "v1_b2b_lead_whatsapp", {}, self.lead.pk).status_code, 404)
        self.assertTrue(AuditLog.objects.filter(actor=self.other, action=identity.ACCESS_DENIED, detail__contains="hidden").exists())
        self.template.assert_not_called()

    def test_opening_a_sheet_or_a_row_is_written_down(self):
        self.get(self.sales, "v1_b2b_sheet", self.sheet.pk)
        self.get(self.manager, "v1_b2b_lead", self.lead.pk)
        self.assertTrue(AuditLog.objects.filter(actor=self.sales, action="client.identity.list", target=f"sheet {self.sheet.pk}").exists())
        self.assertTrue(AuditLog.objects.filter(actor=self.manager, action="client.identity.view", target=f"lead {self.lead.pk}").exists())


class SheetTests(_B2b):
    def test_the_manager_makes_a_sheet_and_the_sales_person_is_told(self):
        answer = self.post(self.manager, "v1_b2b_sheet_create", {"title": "France", "note": "agencies", "assigned_to": self.other.pk})
        self.assertEqual(answer.status_code, 200)
        sheet = LeadSheet.objects.get(title="France")
        self.assertEqual((sheet.assigned_to, sheet.created_by), (self.other, self.manager))
        self.assertTrue(self.other.notifications.filter(url=f"/app/leads/{sheet.pk}").exists())

    def test_a_plain_sales_person_cannot_make_or_hand_over_a_sheet(self):
        answer = self.post(self.sales, "v1_b2b_sheet_create", {"title": "Mine", "assigned_to": self.sales.pk})
        self.assertEqual(answer.status_code, 403)
        answer = self.post(self.sales, "v1_b2b_sheet_save", {"title": "Germany", "assigned_to": self.other.pk}, self.sheet.pk)
        self.assertEqual(answer.status_code, 403)
        self.assertEqual(self.post(self.sales, "v1_b2b_sheet_delete", {}, self.sheet.pk).status_code, 403)
        self.sheet.refresh_from_db()
        self.assertEqual(self.sheet.assigned_to, self.sales)
        self.assertFalse(LeadSheet.objects.filter(title="Mine").exists())

    def test_a_sheet_goes_only_to_a_sales_person_still_working(self):
        self.other.is_active = False
        self.other.save()
        for person in (self.ops, self.other):
            answer = self.post(self.manager, "v1_b2b_sheet_create", {"title": "X", "assigned_to": person.pk})
            self.assertEqual((answer.status_code, _json(answer)["error"]), (400, "no_sales"), person.username)
        answer = self.post(self.manager, "v1_b2b_sheet_create", {"title": "", "assigned_to": self.sales.pk})
        self.assertEqual(_json(answer)["error"], "no_title")
        self.assertFalse(LeadSheet.objects.filter(title="X").exists())

    def test_the_manager_makes_a_sheet_for_themselves(self):
        # The owner's rule of 13/10/2026: the Sales manager may hold a sheet (it was "never" from 10/10).
        listed = {p["id"] for p in _json(self.get(self.manager, "v1_b2b_sheets"))["sales"]}
        self.assertIn(self.manager.pk, listed)
        answer = self.post(self.manager, "v1_b2b_sheet_create", {"title": "Mine", "assigned_to": self.manager.pk})
        self.assertEqual(answer.status_code, 200, answer.content)
        mine = LeadSheet.objects.get(title="Mine")
        self.assertEqual((mine.assigned_to, mine.created_by), (self.manager, self.manager))
        # Nobody is told of a sheet they made for themselves.
        self.assertFalse(self.manager.notifications.filter(url=f"/app/leads/{mine.pk}").exists())
        self.assertTrue(_json(self.get(self.manager, "v1_b2b_sheet", mine.pk))["sheet"]["can_contact"])
        # The owner may hand one to another manager too.
        second = User.objects.create_user("manager2", password="pw", role=Role.SALES, is_sales_manager=True)
        answer = self.post(self.admin, "v1_b2b_sheet_save", {"title": "Germany", "assigned_to": second.pk}, self.sheet.pk)
        self.assertEqual(answer.status_code, 200, answer.content)
        self.sheet.refresh_from_db()
        self.assertEqual(self.sheet.assigned_to, second)

    def test_the_owner_never_holds_a_sheet(self):
        answer = self.post(self.admin, "v1_b2b_sheet_create", {"title": "Mine", "assigned_to": self.admin.pk})
        self.assertEqual((answer.status_code, _json(answer)["error"]), (400, "no_sales"))
        self.assertNotIn(self.admin.pk, {p["id"] for p in _json(self.get(self.admin, "v1_b2b_sheets"))["sales"]})

    def test_handing_a_sheet_over_moves_who_contacts_from_it(self):
        answer = self.post(self.manager, "v1_b2b_sheet_save", {"title": "Germany", "note": "", "assigned_to": self.other.pk}, self.sheet.pk)
        self.assertEqual(answer.status_code, 200)
        self.assertEqual(self.get(self.sales, "v1_b2b_sheet", self.sheet.pk).status_code, 404)
        self.assertTrue(_json(self.get(self.other, "v1_b2b_sheet", self.sheet.pk))["sheet"]["can_contact"])
        self.assertTrue(AuditLog.objects.filter(action="b2b.sheet_reassign").exists())

    def test_a_sheet_with_a_contacted_company_is_kept(self):
        self.post(self.sales, "v1_b2b_lead_call", {"outcome": "no_answer"}, self.lead.pk)
        answer = self.post(self.manager, "v1_b2b_sheet_delete", {}, self.sheet.pk)
        self.assertEqual((answer.status_code, _json(answer)["error"]), (400, "contacted"))
        self.assertTrue(LeadSheet.objects.filter(pk=self.sheet.pk).exists())
        empty = LeadSheet.objects.create(title="Empty", assigned_to=self.sales)
        self.assertEqual(self.post(self.manager, "v1_b2b_sheet_delete", {}, empty.pk).status_code, 200)
        self.assertFalse(LeadSheet.objects.filter(pk=empty.pk).exists())

    def test_a_sheet_nobody_contacted_goes_with_its_companies_and_is_written_down(self):
        # The list page's own button (11/10/2026) calls this door, for the owner as for the Sales manager.
        Lead.objects.create(sheet=self.sheet, company_name="Second GmbH")
        answer = self.post(self.admin, "v1_b2b_sheet_delete", {}, self.sheet.pk)
        self.assertEqual(answer.status_code, 200)
        self.assertFalse(LeadSheet.objects.filter(pk=self.sheet.pk).exists())
        self.assertFalse(Lead.objects.filter(company_name__in=["Lingua GmbH", "Second GmbH"]).exists())
        self.assertTrue(AuditLog.objects.filter(actor=self.admin, action="b2b.sheet_delete", detail="Germany").exists())
        self.assertNotIn("Germany", [s["title"] for s in _json(self.get(self.manager, "v1_b2b_sheets"))["sheets"]])


class RowTests(_B2b):
    def test_a_pasted_block_adds_its_rows_and_skips_the_empty_ones(self):
        rows = [{"company_name": "Alpha Ltd", "whatsapp": "+33 6 12 34 56 78"}, {"company_name": ""}, {"company_name": "Beta"}]
        answer = self.post(self.sales, "v1_b2b_rows_add", {"rows": rows}, self.sheet.pk)
        self.assertEqual((answer.status_code, _json(answer)["added"]), (200, 2))
        alpha = Lead.objects.get(company_name="Alpha Ltd")
        self.assertEqual(alpha.phone_key, Client.phone_key("+33612345678"))
        self.assertEqual(alpha.created_by, self.sales)

    def test_a_block_of_500_goes_in_at_once_with_its_keys_and_notes(self):
        # 13/10/2026: an upload of thousands goes in parts of 500; each part is one insert, not a save a row.
        from django.db import connection
        from django.test.utils import CaptureQueriesContext

        rows = [
            {"company_name": f"Firm {i}", "whatsapp": f"+44 7700 9{i:05d}", "email": f"Info{i}@Firm.test", "notes": "met" if i % 2 else ""}
            for i in range(500)
        ]
        browser = self.browser(self.sales)
        with CaptureQueriesContext(connection) as queries:
            answer = browser.post(reverse("dashboard:v1_b2b_rows_add", args=[self.sheet.pk]), json.dumps({"rows": rows}), content_type="application/json")
        self.assertEqual((answer.status_code, _json(answer)["added"]), (200, 500))
        self.assertLess(len(queries), 40)
        last = Lead.objects.get(company_name="Firm 499")
        self.assertEqual((last.phone_key, last.phone_keys, last.email_key), (Client.phone_key("+447700900499"), f" {Client.phone_key('+447700900499')} ", "info499@firm.test"))
        self.assertEqual((last.created_by, list(last.note_items.values_list("text", "by"))), (self.sales, [("met", self.sales.pk)]))
        self.assertEqual(Lead.objects.get(company_name="Firm 0").note_items.count(), 0)
        self.assertEqual(self.sheet.leads.count(), 501)

    def test_a_sheet_holds_5000_companies(self):
        Lead.objects.bulk_create([Lead(sheet=self.sheet, company_name=f"Firm {i}") for i in range(b2b.MAX_SHEET_ROWS - 2)])
        two = [{"company_name": "One more"}, {"company_name": "Two more"}]
        answer = self.post(self.sales, "v1_b2b_rows_add", {"rows": two}, self.sheet.pk)
        self.assertEqual((answer.status_code, _json(answer)["error"]), (400, "sheet_full"))
        self.assertEqual(self.sheet.leads.count(), 4999)
        answer = self.post(self.sales, "v1_b2b_rows_add", {"rows": two[:1]}, self.sheet.pk)
        self.assertEqual((answer.status_code, self.sheet.leads.count()), (200, 5000))

    def test_a_row_of_the_wrong_shape_writes_nothing(self):
        for body in ({"rows": []}, {"rows": "x"}, {"rows": [{"company_name": 5}]}, {"rows": [{"company_name": "a" * 161}]}, {"rows": [1]}):
            answer = self.post(self.sales, "v1_b2b_rows_add", body, self.sheet.pk)
            self.assertEqual(answer.status_code, 400, body)
        self.assertEqual(self.sheet.leads.count(), 1)

    def test_a_row_is_corrected_and_its_status_change_is_written_down(self):
        values = {name: getattr(self.lead, name) for name, *_r in b2b.COLUMNS}
        values.update(status="visit", next_follow_up="2026-10-20", whatsapp="+44 7700 900999")
        answer = self.post(self.sales, "v1_b2b_lead_save", values, self.lead.pk)
        self.assertEqual(answer.status_code, 200)
        self.lead.refresh_from_db()
        self.assertEqual((self.lead.status, str(self.lead.next_follow_up)), ("visit", "2026-10-20"))
        self.assertEqual(self.lead.phone_key, Client.phone_key("+447700900999"))
        self.assertTrue(AuditLog.objects.filter(action="b2b.lead_status", detail="new -> visit").exists())
        for old in ("meeting", "proposal", "negotiation", "email_sent"):
            values["status"] = old
            self.assertEqual(self.post(self.sales, "v1_b2b_lead_save", values, self.lead.pk).status_code, 400, old)
        values["status"] = "made_up"
        self.assertEqual(self.post(self.sales, "v1_b2b_lead_save", values, self.lead.pk).status_code, 400)

    def test_the_system_stamps_are_not_fields(self):
        values = {name: getattr(self.lead, name) for name, *_r in b2b.COLUMNS}
        values.update(whatsapp_at="2026-01-01", last_contact_at="2026-01-01", client="CL-0001")
        self.post(self.sales, "v1_b2b_lead_save", values, self.lead.pk)
        self.lead.refresh_from_db()
        self.assertIsNone(self.lead.whatsapp_at)
        self.assertIsNone(self.lead.client_id)

    def test_a_contacted_company_is_never_deleted(self):
        self.post(self.sales, "v1_b2b_lead_call", {"outcome": "interested"}, self.lead.pk)
        answer = self.post(self.manager, "v1_b2b_lead_delete", {}, self.lead.pk)
        self.assertEqual((answer.status_code, _json(answer)["error"]), (400, "contacted"))
        fresh = Lead.objects.create(sheet=self.sheet, company_name="Gamma")
        self.assertEqual(self.post(self.sales, "v1_b2b_lead_delete", {}, fresh.pk).status_code, 200)
        self.assertFalse(Lead.objects.filter(pk=fresh.pk).exists())


class WhatsappTests(_B2b):
    def press(self, user=None):
        return self.post(user or self.sales, "v1_b2b_lead_whatsapp", {}, self.lead.pk)

    def test_the_button_sends_the_opening_template_from_the_persons_own_number(self):
        answer = self.press()
        self.assertEqual(answer.status_code, 200)
        body = _json(answer)
        self.assertTrue(body["sent"])
        self.template.assert_called_once_with(
            "447700900123", b2b.INTRO_TEMPLATE, "en", ["Lingua GmbH team", "Seller"], from_id="900002",
        )
        client = Client.objects.get(code=body["chat"])
        self.assertEqual((client.company, client.name, client.email), ("Lingua GmbH", "Anna Schmidt", "anna@lingua.test"))
        sent = OutboundMessage.objects.get(client=client)
        self.assertEqual((sent.status, sent.owner, sent.channel, sent.provider_id), ("sent", self.sales, "whatsapp", "wamid.intro.1"))
        self.assertIn("this is Seller from EagleLingua", sent.body)
        # 14/10/2026: the letter greets the company, not the contact person on the row.
        self.assertTrue(sent.body.startswith("Hello Lingua GmbH team, "))
        self.assertNotIn("Anna", sent.body)
        # The row's own pair ("German to Arabic") is not named: the letter offers every language.
        self.assertIn("a certified translation company", sent.body)
        self.assertIn("projects in all languages", sent.body)
        self.assertNotIn("German", sent.body)
        self.lead.refresh_from_db()
        self.assertEqual(self.lead.client, client)
        self.assertIsNotNone(self.lead.whatsapp_at)
        self.assertEqual(self.lead.last_contact_at, self.lead.whatsapp_at)
        activity = self.lead.activities.get(kind="whatsapp")
        self.assertEqual((activity.kind, activity.automatic, activity.outbound), ("whatsapp", True, sent))
        # The first WhatsApp made the new company «Contacted» (12/10/2026), and that is on the timeline too.
        self.assertEqual(self.lead.status, "contacted")
        self.assertEqual(self.lead.activities.get(kind="status").status, "contacted")
        self.assertEqual(body["lead"]["whatsapp_at"] != "", True)

    def test_a_second_press_sends_nothing_until_a_day_has_passed(self):
        self.press()
        again = self.press()
        self.assertEqual((again.status_code, _json(again)["sent"]), (200, False))
        self.assertEqual(self.template.call_count, 1)
        OutboundMessage.objects.update(created_at=timezone.now() - timedelta(hours=25))
        self.assertTrue(_json(self.press())["sent"])
        self.assertEqual(self.template.call_count, 2)

    def test_a_company_that_wrote_within_a_day_gets_no_template(self):
        client = Client.objects.create(name="Anna", phone="+447700900123")
        InboundMessage.objects.create(client=client, channel=Channel.WHATSAPP, body="hi", external_id="wamid.in.9", owner=self.sales)
        body = _json(self.press())
        self.assertEqual((body["sent"], body["chat"]), (False, client.code))
        self.template.assert_not_called()
        self.lead.refresh_from_db()
        # Nothing reached them yet: the row is linked, not marked.
        self.assertEqual((self.lead.client, self.lead.whatsapp_at), (client, None))

    def test_the_manager_sends_from_their_own_sheet_on_their_own_number(self):
        mine = LeadSheet.objects.create(title="Mine", assigned_to=self.manager, created_by=self.manager)
        Lead.objects.filter(pk=self.lead.pk).update(sheet=mine)
        self.assertTrue(_json(self.press(self.manager))["sent"])
        self.assertEqual(self.template.call_args.kwargs, {"from_id": "900001"})
        # The plain Sales person it used to belong to no longer writes to it.
        self.assertEqual(self.press(self.sales).status_code, 404)

    def test_a_window_open_on_another_line_is_not_this_persons(self):
        client = Client.objects.create(name="Anna", phone="+447700900123")
        InboundMessage.objects.create(client=client, channel=Channel.WHATSAPP, body="hi", external_id="wamid.in.8")
        self.assertTrue(_json(self.press())["sent"])

    def test_only_the_sheets_own_sales_person_contacts_from_it(self):
        for user in (self.manager, self.admin):
            answer = self.press(user)
            self.assertEqual((answer.status_code, _json(answer)["error"]), (400, "not_yours"), user.username)
        self.template.assert_not_called()
        self.assertFalse(OutboundMessage.objects.exists())

    def test_no_number_of_ones_own_says_so_and_sends_nothing(self):
        User.objects.filter(pk=self.sales.pk).update(wa_phone_number_id="")
        answer = self.press()
        self.assertEqual(_json(answer)["error"], "no_line")
        Lead.objects.filter(pk=self.lead.pk).update(whatsapp="12", phone="")
        self.assertEqual(_json(self.press())["error"], "no_number")
        self.template.assert_not_called()

    def test_a_refused_send_is_kept_as_failed_and_marks_nothing(self):
        self.template.side_effect = whatsapp.WhatsAppError("الرقم +447700900123 مرفوض", "number refused")
        answer = self.press()
        self.assertEqual((answer.status_code, _json(answer)["error"]), (400, "send_failed"))
        self.assertNotIn("447700900123", _json(answer)["message"])
        failed = OutboundMessage.objects.get()
        self.assertEqual(failed.status, "failed")
        self.lead.refresh_from_db()
        self.assertIsNone(self.lead.whatsapp_at)
        self.assertFalse(LeadActivity.objects.exists())

    def test_the_opening_template_follows_the_three_rules(self):
        from .management.commands.wa_templates import TEMPLATES

        self.assertEqual(set(b2b.INTRO_TEMPLATES), {"en", "ar"})
        for language, (name, spec) in b2b.INTRO_TEMPLATES.items():
            self.assertEqual(spec["language"], language)
            count = spec["body"].count("{{")
            self.assertEqual(len(spec["example"]), count, name)
            self.assertEqual(len(b2b.intro_params(self.lead, self.sales, language)), count, name)
            self.assertFalse(spec["body"].lstrip().startswith("{{"), name)
            self.assertFalse(spec["body"].rstrip().rstrip(".?!؟").endswith("}}"), name)
            self.assertIs(TEMPLATES[name], spec)

    def test_an_arab_number_gets_the_arabic_letter(self):
        Lead.objects.filter(pk=self.lead.pk).update(whatsapp="+20 100 123 4567")
        self.assertTrue(_json(self.press())["sent"])
        self.template.assert_called_once_with(
            "201001234567", b2b.INTRO_TEMPLATE_AR, "ar", ["فريق Lingua GmbH", "Seller"], from_id="900002",
        )
        sent = OutboundMessage.objects.get()
        self.assertTrue(sent.body.startswith("أهلًا فريق Lingua GmbH، معاك Seller من EagleLingua"))
        self.assertNotIn("Anna", sent.body)
        self.assertNotIn("{{", sent.body)
        self.assertTrue(AuditLog.objects.filter(action="b2b.whatsapp", detail__endswith=b2b.INTRO_TEMPLATE_AR).exists())

    def test_the_greeting_is_the_company_on_one_line_or_a_plain_hello_without_one(self):
        self.lead.company_name = "  Lingua\n\tGmbH     Berlin "
        self.assertEqual(b2b.intro_params(self.lead, self.sales, "en")[0], "Lingua GmbH Berlin team")
        self.assertEqual(b2b.intro_params(self.lead, self.sales, "ar")[0], "فريق Lingua GmbH Berlin")
        self.lead.company_name = " "
        self.assertEqual(b2b.intro_params(self.lead, self.sales, "en")[0], "there")
        self.assertEqual(b2b.intro_params(self.lead, self.sales, "ar")[0], "حضرتك")

    def test_the_letter_language_follows_the_dialling_code(self):
        for number, language in (
            ("+20 100 123 4567", "ar"), ("00966 50 123 4567", "ar"), ("+971501234567", "ar"), ("+212 6 12 34 56 78", "ar"),
            ("+44 7700 900123", "en"), ("+49 151 2345678", "en"), ("+972 50 123 4567", "en"), ("+1 202 555 0100", "en"), ("", "en"),
        ):
            self.assertEqual(b2b.intro_language(number), language, number)

    def test_a_local_egyptian_number_goes_with_its_code_and_gets_the_arabic_letter(self):
        # 14/10/2026: "010..." on a row went to Meta as it was; Meta put Egypt in front and it arrived, in English.
        Lead.objects.filter(pk=self.lead.pk).update(whatsapp="010 0123 4567", country="", company_name="")
        self.assertTrue(_json(self.press())["sent"])
        self.template.assert_called_once_with(
            "201001234567", b2b.INTRO_TEMPLATE_AR, "ar", ["حضرتك", "Seller"], from_id="900002",
        )
        self.assertEqual(OutboundMessage.objects.get().to_identity, "201001234567")

    def test_a_local_number_takes_the_code_of_the_rows_country(self):
        Lead.objects.filter(pk=self.lead.pk).update(whatsapp="050 123 4567", country="السعودية")
        self.assertTrue(_json(self.press())["sent"])
        self.assertEqual(self.template.call_args.args[:3], ("966501234567", b2b.INTRO_TEMPLATE_AR, "ar"))

    def test_a_local_number_of_an_unknown_country_is_refused_and_nothing_goes(self):
        Lead.objects.filter(pk=self.lead.pk).update(whatsapp="0501234567", country="")
        answer = self.press()
        self.assertEqual((answer.status_code, _json(answer)["error"]), (400, "no_country_code"))
        self.template.assert_not_called()
        self.assertFalse(OutboundMessage.objects.exists())
        self.assertFalse(Client.objects.exists())

    def test_numbers_are_made_international_before_the_letter_is_picked(self):
        for number, country, international in (
            ("01001234567", "", "201001234567"), ("01501234567", "Spain", "201501234567"),
            ("01001234567", "مصر", "201001234567"), ("0501234567", "Saudi Arabia", "966501234567"),
            ("0501234567", "الإمارات", "971501234567"), ("07700 900123", "UK", "447700900123"),
            ("0501234567", "", ""), ("0612345678", "Spain", ""),
            ("+20 100 123 4567", "Germany", "201001234567"), ("00966 50 123 4567", "", "966501234567"),
            ("+٢٠ ١٠٠ ١٢٣ ٤٥٦٧", "", "201001234567"), ("447700900123", "", "447700900123"),
        ):
            self.assertEqual(b2b.international_number(number, country), international, (number, country))



class TemplatePayloadTests(TestCase):
    def test_the_template_payload(self):
        with mock.patch("dashboard.whatsapp._send", return_value="wamid.x") as send:
            whatsapp.send_template("+44 1", "b2b_intro_en", "en", ["a", "b"], from_id="77")
        payload = send.call_args.args[0]
        self.assertEqual(payload["type"], "template")
        self.assertEqual(payload["to"], "441")
        self.assertEqual(payload["template"]["language"], {"code": "en"})
        self.assertEqual(payload["template"]["components"][0]["parameters"], [{"type": "text", "text": "a"}, {"type": "text", "text": "b"}])
        self.assertEqual(send.call_args.kwargs, {"from_id": "77"})

    def test_the_number_meta_gets_has_no_dial_out_zeros_and_plain_digits(self):
        for written, sent in (("00966 50 123 4567", "966501234567"), ("+٤٤ ٧٧٠٠", "447700"), ("+44 (7700) 900-123", "447700900123")):
            self.assertEqual(whatsapp.normalize_number(written), sent, written)


class MarkedByItselfTests(_B2b):
    """A message the Sales person sends later from the chats or the mail page marks the row, without the button."""

    def setUp(self):
        super().setUp()
        self.client_obj = Client.objects.create(name="Anna", phone="+447700900123", email="anna@lingua.test")
        InboundMessage.objects.create(
            client=self.client_obj, channel=Channel.WHATSAPP, body="hello", external_id="wamid.in.1", owner=self.sales,
        )

    def test_a_chat_answer_on_ones_own_line_marks_the_row(self):
        ok, _out, _err = services.send_client_message(self.client_obj, self.sales, "Thanks Anna", force_channel=Channel.WHATSAPP)
        self.assertTrue(ok)
        self.lead.refresh_from_db()
        self.assertEqual(self.lead.client, self.client_obj)
        self.assertIsNotNone(self.lead.whatsapp_at)
        # A second message the same day moves the last contact, not the timeline.
        services.send_client_message(self.client_obj, self.sales, "One more", force_channel=Channel.WHATSAPP)
        self.assertEqual(self.lead.activities.filter(kind="whatsapp").count(), 1)

    def test_the_company_line_and_another_sales_person_do_not_count(self):
        InboundMessage.objects.create(client=self.client_obj, channel=Channel.WHATSAPP, body="hi", external_id="wamid.in.2")
        self.assertTrue(services.send_client_message(self.client_obj, self.ops, "from the company", force_channel=Channel.WHATSAPP)[0])
        # The other Sales person writes to the same company from their own number: it marks their row, not this one.
        theirs = Lead.objects.create(sheet=LeadSheet.objects.create(title="Other", assigned_to=self.other), company_name="Lingua copy", whatsapp=PHONE)
        self.assertTrue(services.send_client_message(self.client_obj, self.other, "from the other seller", force_channel=Channel.WHATSAPP)[0])
        theirs.refresh_from_db()
        self.assertIsNotNone(theirs.whatsapp_at)
        self.lead.refresh_from_db()
        self.assertIsNone(self.lead.whatsapp_at)
        self.assertFalse(self.lead.activities.exists())

    def test_a_failed_send_does_not_count(self):
        self.text.side_effect = whatsapp.WhatsAppError("x", "x")
        self.assertFalse(services.send_client_message(self.client_obj, self.sales, "x", force_channel=Channel.WHATSAPP)[0])
        self.lead.refresh_from_db()
        self.assertIsNone(self.lead.whatsapp_at)

    def test_a_mark_that_breaks_does_not_fail_the_send(self):
        with mock.patch("dashboard.b2b.note_outbound", side_effect=RuntimeError("boom")):
            ok, out, _err = services.send_client_message(self.client_obj, self.sales, "x", force_channel=Channel.WHATSAPP)
        self.assertTrue(ok)
        self.assertEqual(out.status, "sent")


class EmailTests(_B2b):
    def test_the_email_button_sends_from_the_persons_own_address_and_marks_the_row(self):
        answer = self.post(self.sales, "v1_b2b_lead_email", {"subject": "Partnership", "body": "Dear Anna"}, self.lead.pk)
        self.assertEqual(answer.status_code, 200, answer.content)
        self.assertEqual(self.mail.call_args.args[1], "anna@lingua.test")
        self.assertEqual(self.mail.call_args.kwargs["from_email"], "seller@eagle.test")
        self.lead.refresh_from_db()
        self.assertIsNotNone(self.lead.email_at)
        self.assertEqual(self.lead.client.email, "anna@lingua.test")
        self.assertEqual(self.lead.activities.get(kind="email").owner, self.sales)
        # The first letter moved it to «Contacted», and that is on the timeline too.
        stage = self.lead.activities.get(kind="status")
        self.assertEqual((stage.status, stage.automatic, stage.owner), ("contacted", True, self.sales))

    def test_a_letter_needs_an_address_a_subject_and_words(self):
        self.assertEqual(_json(self.post(self.sales, "v1_b2b_lead_email", {"subject": "", "body": "x"}, self.lead.pk))["error"], "empty")
        Lead.objects.filter(pk=self.lead.pk).update(email="not an address")
        self.assertEqual(_json(self.post(self.sales, "v1_b2b_lead_email", {"subject": "s", "body": "x"}, self.lead.pk))["error"], "no_email")
        self.mail.assert_not_called()

    def test_the_manager_does_not_write_from_someone_elses_sheet(self):
        answer = self.post(self.manager, "v1_b2b_lead_email", {"subject": "s", "body": "x"}, self.lead.pk)
        self.assertEqual(_json(answer)["error"], "not_yours")
        self.mail.assert_not_called()


class CallTests(_B2b):
    def test_a_call_is_written_by_hand_with_its_outcome_and_next_follow_up(self):
        body = {"outcome": "quotation", "notes": "wants rates", "duration_minutes": 12, "at": "2026-10-09T14:30", "next_follow_up": "2026-10-15"}
        answer = self.post(self.sales, "v1_b2b_lead_call", body, self.lead.pk)
        self.assertEqual(answer.status_code, 200, answer.content)
        self.lead.refresh_from_db()
        self.assertEqual(str(self.lead.next_follow_up), "2026-10-15")
        self.assertIsNotNone(self.lead.call_at)
        call = self.lead.activities.get()
        self.assertEqual((call.kind, call.automatic, call.outcome, call.duration_minutes, call.by), ("call", False, "quotation", 12, self.sales))
        self.assertEqual(timezone.localtime(call.at).strftime("%H:%M"), "14:30")

    def test_a_call_needs_an_outcome_and_a_time_that_has_come(self):
        self.assertEqual(_json(self.post(self.sales, "v1_b2b_lead_call", {"outcome": ""}, self.lead.pk))["error"], "bad_outcome")
        later = (timezone.localtime() + timedelta(days=1)).strftime("%Y-%m-%dT%H:%M")
        self.assertEqual(_json(self.post(self.sales, "v1_b2b_lead_call", {"outcome": "interested", "at": later}, self.lead.pk))["error"], "future")
        for bad in ({"outcome": "interested", "duration_minutes": -1}, {"outcome": "interested", "duration_minutes": "5"}, {"outcome": "interested", "at": "soon"}):
            self.assertEqual(self.post(self.sales, "v1_b2b_lead_call", bad, self.lead.pk).status_code, 400, bad)
        self.assertFalse(LeadActivity.objects.exists())

    def test_the_timeline_lists_what_happened(self):
        self.post(self.sales, "v1_b2b_lead_call", {"outcome": "no_answer"}, self.lead.pk)
        self.post(self.sales, "v1_b2b_lead_whatsapp", {}, self.lead.pk)
        body = _json(self.get(self.manager, "v1_b2b_lead", self.lead.pk))
        self.assertEqual({a["kind"] for a in body["activities"]}, {"call", "whatsapp", "status"})
        self.assertFalse(body["can_contact"])


class CallOutcomeOnTheSheetTests(_B2b):
    """19/10/2026, the owner's four asks: the outcome chosen in «سجّل مكالمة» shows on the row (it showed only in the
    timeline); «تم التعاقد» is an outcome and moves the row to Contracted; «طلب عرض سعر» counts in «عروض اتبعتت»; a stage
    set by hand that says we talked to the company («call», «whatsapp»...) is not «لسه ماتواصلناش»."""

    def call(self, outcome, lead=None, at=None):
        body = {"outcome": outcome}
        if at:
            body["at"] = at
        answer = self.post(self.sales, "v1_b2b_lead_call", body, (lead or self.lead).pk)
        self.assertEqual(answer.status_code, 200, answer.content)
        return _json(answer)

    def kpi_row(self):
        today = timezone.localdate()
        period = {"from": (today - timedelta(days=30)).isoformat(), "to": today.isoformat()}
        body = _json(self.browser(self.sales).get(reverse("dashboard:v1_b2b_kpis"), period))
        return next(row for row in body["rows"] if row["person"]["id"] == self.sales.pk)

    def test_the_sheet_shows_each_rows_last_call_outcome(self):
        quiet = Lead.objects.create(sheet=self.sheet, company_name="Quiet AG")
        earlier = (timezone.localtime() - timedelta(hours=2)).strftime("%Y-%m-%dT%H:%M")
        self.assertEqual(self.call("quotation")["lead"]["call_outcome"], "quotation")
        # Written later but made earlier: the last call is the one made last, not the one written last.
        self.call("no_answer", at=earlier)
        rows = {row["id"]: row for row in _json(self.get(self.sales, "v1_b2b_sheet", self.sheet.pk))["leads"]}
        self.assertEqual((rows[self.lead.pk]["call_outcome"], rows[quiet.pk]["call_outcome"]), ("quotation", ""))
        self.lead.next_follow_up = timezone.localdate()
        self.lead.save()
        items = _json(self.get(self.sales, "v1_b2b_follow_ups"))["items"]
        self.assertEqual([item["call_outcome"] for item in items], ["quotation"])

    def test_contracted_is_an_outcome_and_moves_the_row_to_contracted(self):
        sheet = _json(self.get(self.sales, "v1_b2b_sheet", self.sheet.pk))
        self.assertIn("contracted", [choice["value"] for choice in sheet["outcomes"]])
        self.assertEqual(self.call("contracted")["lead"]["status"], "won")
        self.call("contracted")
        self.lead.refresh_from_db()
        self.assertEqual(self.lead.status, "won")
        stages = self.lead.activities.filter(kind=LeadActivity.Kind.STATUS)
        self.assertEqual([(a.status, a.by, a.automatic) for a in stages], [("won", self.sales, False)])
        self.assertEqual(self.kpi_row()["won"], 1)

    # 20/10/2026: a company added in «شركة جديدة» already at «تم التعاقد» was on the sheet and not in «تم التعاقد».
    def test_a_company_typed_in_at_contracted_counts_as_won(self):
        self.assertEqual(self.kpi_row()["won"], 0)
        answer = self.post(self.sales, "v1_b2b_rows_add", {"rows": [{"company_name": "Signed AG", "status": "won"}], "typed": True}, self.sheet.pk)
        self.assertEqual(answer.status_code, 200, answer.content)
        signed = Lead.objects.get(company_name="Signed AG")
        stages = signed.activities.filter(kind=LeadActivity.Kind.STATUS)
        self.assertEqual([(a.status, a.by, a.owner, a.automatic) for a in stages], [("won", self.sales, self.sales, False)])
        self.assertEqual(self.kpi_row()["won"], 1)
        # A company typed in new is no stage moved.
        self.post(self.sales, "v1_b2b_rows_add", {"rows": [{"company_name": "Fresh AG"}], "typed": True}, self.sheet.pk)
        self.assertFalse(Lead.objects.get(company_name="Fresh AG").activities.exists())

    # 20/10/2026: «لما حالة تتغير لـ تم التعاقد حط تسقيف واحتفال»: the answer says when this write is the move.
    def test_the_answer_says_when_the_write_moved_the_company_to_contracted(self):
        save = lambda status: _json(self.post(self.sales, "v1_b2b_lead_save", {"status": status}, self.lead.pk))["won_now"]
        self.assertFalse(save("contacted"))
        self.assertTrue(save("won"))
        self.assertFalse(save("won"))  # already there: no second party
        self.assertFalse(save("lost"))
        self.assertTrue(self.call("contracted")["won_now"])
        self.assertFalse(self.call("contracted")["won_now"])
        added = lambda status: _json(self.post(self.sales, "v1_b2b_rows_add", {"rows": [{"company_name": f"{status} AG", "status": status}], "typed": True}, self.sheet.pk))["won_now"]
        self.assertTrue(added("won"))
        self.assertFalse(added("contacted"))
        # A block uploaded is no party: its stages are old.
        self.assertFalse(_json(self.post(self.sales, "v1_b2b_rows_add", {"rows": [{"company_name": "Up AG", "status": "won"}]}, self.sheet.pk))["won_now"])

    def test_an_accepted_quotation_says_it_moved_the_company_to_contracted(self):
        sent = lambda: Quotation.objects.create(
            lead=self.lead, owner=self.sales, created_by=self.sales, source_lang="German", target_lang="Arabic", quantity=1000,
            rate=Decimal("0.1"), status=Quotation.Status.SENT, sent_at=timezone.now(),
        )
        answer = _json(self.post(self.sales, "v1_b2b_quotation_decide", {"accepted": True}, sent().pk))
        self.assertEqual((answer["won_now"], answer["company"]), (True, self.lead.company_name))
        again = _json(self.post(self.sales, "v1_b2b_quotation_decide", {"accepted": True}, sent().pk))
        self.assertEqual((again["won_now"], "company" in again), (False, False))

    def test_an_uploaded_block_keeps_its_stages_without_counting_them(self):
        rows = [{"company_name": "Old AG", "status": "won"}, {"company_name": "Older AG", "status": "won"}]
        self.assertEqual(self.post(self.sales, "v1_b2b_rows_add", {"rows": rows}, self.sheet.pk).status_code, 200)
        # Marked typed, a block is still an upload: an old sheet's contracts are not this month's.
        self.post(self.sales, "v1_b2b_rows_add", {"rows": [{"company_name": "Oldest AG", "status": "won"}, {"company_name": "Last AG"}], "typed": True}, self.sheet.pk)
        self.assertEqual(Lead.objects.filter(status="won").count(), 3)
        self.assertFalse(LeadActivity.objects.filter(kind=LeadActivity.Kind.STATUS).exists())
        self.assertEqual(self.kpi_row()["won"], 0)

    def test_any_other_outcome_leaves_the_stage(self):
        for outcome in ("interested", "follow_up", "quotation", "no_answer", "not_interested"):
            self.call(outcome)
        self.lead.refresh_from_db()
        self.assertEqual(self.lead.status, "new")

    def test_a_quotation_requested_call_counts_in_quotations_sent_once_per_company(self):
        other = Lead.objects.create(sheet=self.sheet, company_name="Other AG")
        self.call("quotation")
        self.call("quotation")
        self.call("interested", lead=other)
        self.assertEqual(self.kpi_row()["quotations"], 1)
        self.call("quotation", lead=other)
        self.assertEqual(self.kpi_row()["quotations"], 2)
        # Its quotation sent in the same period: the company is not counted twice.
        Quotation.objects.create(
            lead=self.lead, owner=self.sales, created_by=self.sales, source_lang="German", target_lang="Arabic", quantity=1000,
            rate=Decimal("0.1"), status=Quotation.Status.SENT, sent_at=timezone.now(),
        )
        self.assertEqual(self.kpi_row()["quotations"], 2)

    def test_a_stage_set_by_hand_is_a_company_we_talked_to(self):
        Lead.objects.create(sheet=self.sheet, company_name="Untouched AG")
        values = {name: getattr(self.lead, name) for name, *_r in b2b.COLUMNS}
        values.update(status="call", next_follow_up="")
        answer = _json(self.post(self.sales, "v1_b2b_lead_save", values, self.lead.pk))
        self.assertTrue(answer["lead"]["reached"])
        sheet = _json(self.get(self.sales, "v1_b2b_sheet", self.sheet.pk))
        self.assertEqual(sheet["sheet"]["contacted"], 1)
        self.assertEqual({row["company_name"]: row["reached"] for row in sheet["leads"]}, {"Lingua GmbH": True, "Untouched AG": False})
        listed = _json(self.get(self.sales, "v1_b2b_sheets"))["sheets"]
        self.assertEqual([(s["id"], s["contacted"]) for s in listed], [(self.sheet.pk, 1)])
        row = self.kpi_row()
        self.assertEqual((row["contacted"], row["untouched"]), (1, 1))
        # Nothing went from the sheet, so the row is still the Sales person's to delete.
        self.assertEqual(self.post(self.sales, "v1_b2b_lead_delete", {}, self.lead.pk).status_code, 200)


class SalesManagerMarkTests(TestCase):
    def test_the_mark_is_a_sales_persons_only(self):
        person = User.objects.create_user("x", password="pw", role=Role.SALES, is_sales_manager=True)
        self.assertTrue(person.manages_sales)
        person.role = Role.OPERATION
        person.save()
        person.refresh_from_db()
        self.assertFalse(person.is_sales_manager)
        self.assertFalse(person.manages_sales)

    def test_the_staff_form_refuses_it_on_another_role(self):
        person = User.objects.create_user("y", password="pw", role=Role.OPERATION)
        form = StaffEditForm(instance=person)
        self.assertIn("is_sales_manager", form.fields)
        data = {name: form.initial.get(name, "") for name in form.fields}
        data.update(role=Role.OPERATION, is_sales_manager="on", is_active="on", rating="0", languages="")
        bound = StaffEditForm(data, instance=person)
        self.assertFalse(bound.is_valid())
        self.assertIn("is_sales_manager", bound.errors)


class ResetStaffTests(_Staff):
    def test_the_staff_reset_takes_the_sheets_into_its_backup(self):
        sheet = LeadSheet.objects.create(title="Gone", assigned_to=self.sales)
        Lead.objects.create(sheet=sheet, company_name="Delta")
        answer = self.run_reset()
        self.assertEqual(answer.status_code, 200)
        backup = answer.content.decode("utf-8")
        self.assertIn("dashboard.leadsheet", backup)
        self.assertIn("Delta", backup)
        self.assertFalse(LeadSheet.objects.exists())


# ---------------------------------------------------------------------------
# Part 2: the company's answer, the follow-ups, the reminder, moving a company
# ---------------------------------------------------------------------------

class InboundTests(_B2b):
    def ingest(self, owner=None, sender=PHONE, channel=Channel.WHATSAPP, **kw):
        return services.ingest_message(
            channel=channel, body="Yes, interested", sender_identity=sender, external_id=kw.pop("external_id", "wamid.in.77"),
            owner=owner, **kw,
        )

    def test_an_answer_on_the_sales_persons_line_marks_the_row(self):
        self.post(self.sales, "v1_b2b_lead_whatsapp", {}, self.lead.pk)
        self.lead.refresh_from_db()
        sent_at = self.lead.last_outreach_at
        message = self.ingest(owner=self.sales)
        self.lead.refresh_from_db()
        self.assertEqual(self.lead.replied_at, message.received_at)
        self.assertEqual(self.lead.last_contact_at, message.received_at)
        # The company writing is not us reaching out.
        self.assertEqual(self.lead.last_outreach_at, sent_at)
        answer = self.lead.activities.get(incoming=True)
        self.assertEqual((answer.kind, answer.automatic, answer.notes), ("whatsapp", True, ""))

    def test_a_row_nobody_pressed_is_found_by_its_number(self):
        self.ingest(owner=self.sales)
        self.lead.refresh_from_db()
        self.assertIsNotNone(self.lead.replied_at)
        self.assertIsNotNone(self.lead.client_id)
        self.assertIsNone(self.lead.whatsapp_at)

    def test_the_company_line_and_another_sales_persons_line_do_not_count(self):
        self.ingest(owner=None)
        self.ingest(owner=self.other, external_id="wamid.in.78")
        self.lead.refresh_from_db()
        self.assertIsNone(self.lead.replied_at)
        self.assertFalse(self.lead.activities.exists())

    def test_a_letter_to_the_sales_persons_address_marks_the_row(self):
        self.ingest(channel=Channel.EMAIL, sender="anna@lingua.test", external_id="<m1@lingua.test>",
                    subject="Re: partnership", recipients=["seller@eagle.test"])
        self.lead.refresh_from_db()
        self.assertIsNotNone(self.lead.replied_at)
        self.assertEqual(self.lead.activities.get().kind, "email")

    def test_a_mark_that_breaks_does_not_cost_the_message(self):
        with mock.patch("dashboard.b2b.note_inbound", side_effect=RuntimeError("boom")):
            message = self.ingest(owner=self.sales)
        self.assertTrue(InboundMessage.objects.filter(pk=message.pk).exists())

    def test_the_first_letter_moves_a_new_company_to_contacted(self):
        self.post(self.sales, "v1_b2b_lead_email", {"subject": "s", "body": "b"}, self.lead.pk)
        self.lead.refresh_from_db()
        self.assertEqual(self.lead.status, "contacted")
        self.assertTrue(AuditLog.objects.filter(action="b2b.lead_status", detail="new -> contacted (automatic)").exists())
        # A company further on the way stays where it is.
        Lead.objects.filter(pk=self.lead.pk).update(status="visit")
        self.post(self.sales, "v1_b2b_lead_email", {"subject": "s2", "body": "b2"}, self.lead.pk)
        self.lead.refresh_from_db()
        self.assertEqual(self.lead.status, "visit")

    def test_their_answer_does_not_move_the_status(self):
        # Their writing is not us contacting them: the first WhatsApp or letter of ours does it (WhatsappTests, above).
        self.ingest(owner=self.sales)
        self.lead.refresh_from_db()
        self.assertEqual(self.lead.status, "new")

    def test_a_call_does_not_move_the_status(self):
        self.post(self.sales, "v1_b2b_lead_call", {"outcome": "interested"}, self.lead.pk)
        self.lead.refresh_from_db()
        self.assertEqual(self.lead.status, "new")


class FollowUpStateTests(_B2b):
    def at(self, **kw):
        Lead.objects.filter(pk=self.lead.pk).update(**kw)
        self.lead.refresh_from_db()
        return b2b.follow_up_state(self.lead)

    def test_the_four_states(self):
        today = timezone.localdate()
        self.assertEqual(self.at(next_follow_up=None), "")
        self.assertEqual(self.at(next_follow_up=today + timedelta(days=2)), "upcoming")
        self.assertEqual(self.at(next_follow_up=today), "today")
        self.assertEqual(self.at(next_follow_up=today - timedelta(days=1)), "overdue")
        self.assertEqual(self.at(status="won"), "")
        self.assertEqual(self.at(status="lost"), "")

    def test_reaching_out_on_or_after_the_day_is_done_and_before_it_is_not(self):
        today = timezone.localdate()
        self.assertEqual(self.at(next_follow_up=today - timedelta(days=1), last_outreach_at=timezone.now() - timedelta(days=3)), "overdue")
        self.assertEqual(self.at(last_outreach_at=timezone.now()), "done")

    def test_the_company_answering_is_not_us_following_up(self):
        Lead.objects.filter(pk=self.lead.pk).update(next_follow_up=timezone.localdate() - timedelta(days=1))
        services.ingest_message(channel=Channel.WHATSAPP, body="hi", sender_identity=PHONE, external_id="wamid.in.5", owner=self.sales)
        self.lead.refresh_from_db()
        self.assertEqual(b2b.follow_up_state(self.lead), "overdue")
        # A call today is.
        self.post(self.sales, "v1_b2b_lead_call", {"outcome": "follow_up"}, self.lead.pk)
        self.lead.refresh_from_db()
        self.assertEqual(b2b.follow_up_state(self.lead), "done")

    def test_the_row_says_its_state(self):
        Lead.objects.filter(pk=self.lead.pk).update(next_follow_up=timezone.localdate() - timedelta(days=2))
        row = _json(self.get(self.sales, "v1_b2b_sheet", self.sheet.pk))["leads"][0]
        self.assertEqual((row["follow_up"], row["overdue"]), ("overdue", True))


class FollowUpListTests(_B2b):
    def setUp(self):
        super().setUp()
        today = timezone.localdate()
        Lead.objects.filter(pk=self.lead.pk).update(next_follow_up=today - timedelta(days=1))
        theirs = LeadSheet.objects.create(title="Spain", assigned_to=self.other)
        self.theirs = Lead.objects.create(sheet=theirs, company_name="Iberia SL", next_follow_up=today)
        Lead.objects.create(sheet=theirs, company_name="Later SL", next_follow_up=today + timedelta(days=3))
        Lead.objects.create(sheet=theirs, company_name="Won SL", next_follow_up=today - timedelta(days=3), status="won")

    def names(self, user):
        return [row["company_name"] for row in _json(self.get(user, "v1_b2b_follow_ups"))["items"]]

    def test_a_sales_person_sees_their_own_and_the_manager_the_teams(self):
        self.assertEqual(self.names(self.sales), ["Lingua GmbH"])
        self.assertEqual(self.names(self.other), ["Iberia SL"])
        self.assertEqual(self.names(self.manager), ["Lingua GmbH", "Iberia SL"])
        self.assertEqual(self.names(self.admin), ["Lingua GmbH", "Iberia SL"])
        row = _json(self.get(self.manager, "v1_b2b_follow_ups"))["items"][1]
        self.assertEqual((row["sales"]["id"], row["sheet"]["title"], row["follow_up"]), (self.other.pk, "Spain", "today"))

    def test_no_door_for_anybody_else_and_the_list_is_written_down(self):
        self.assertEqual(self.get(self.ops, "v1_b2b_follow_ups").status_code, 403)
        self.get(self.sales, "v1_b2b_follow_ups")
        self.assertTrue(AuditLog.objects.filter(actor=self.sales, action="client.identity.list", target="b2b follow-ups").exists())

    def test_a_done_follow_up_leaves_the_list(self):
        self.post(self.sales, "v1_b2b_lead_call", {"outcome": "interested"}, self.lead.pk)
        self.assertEqual(self.names(self.sales), [])


class DigestTests(_B2b):
    def setUp(self):
        super().setUp()
        Lead.objects.filter(pk=self.lead.pk).update(next_follow_up=timezone.localdate() - timedelta(days=1))
        Lead.objects.create(sheet=self.sheet, company_name="Today GmbH", next_follow_up=timezone.localdate())

    def at_hour(self, hour):
        return timezone.localtime().replace(hour=hour, minute=5)

    def reminders(self, user):
        return user.notifications.filter(url=b2b.digest_marker(timezone.localdate()))

    def test_one_reminder_a_day_from_nine_with_the_counts(self):
        self.assertIsNone(b2b.daily_digest(self.sales, now=self.at_hour(8)))
        note = b2b.daily_digest(self.sales, now=self.at_hour(9))
        self.assertIsNotNone(note)
        self.assertEqual(note.body_ar, "عندك متابعات: 1 النهارده و1 متأخرة. افتح «شيتات الشركات».")
        self.assertEqual(note.level, "warning")
        self.assertIsNone(b2b.daily_digest(self.sales, now=self.at_hour(15)))
        self.assertEqual(self.reminders(self.sales).count(), 1)
        # The words carry counts, never a company.
        self.assertNotIn("Lingua", note.body_ar + note.body_en)

    def test_nothing_when_nothing_is_due_and_nothing_for_another_role(self):
        Lead.objects.update(next_follow_up=None)
        self.assertIsNone(b2b.daily_digest(self.sales, now=self.at_hour(10)))
        self.assertIsNone(b2b.daily_digest(self.ops, now=self.at_hour(10)))

    def test_the_sweep_reminds_every_sales_person_who_has_some(self):
        from django.core.management import call_command

        with mock.patch("dashboard.b2b.timezone.now", return_value=self.at_hour(10)):
            call_command("sweep", stdout=mock.MagicMock())
        self.assertEqual(self.reminders(self.sales).count(), 1)
        self.assertEqual(self.reminders(self.other).count(), 0)

    def test_the_heartbeat_reminds_a_sales_person_whose_page_is_open(self):
        from django.core.cache import cache

        cache.clear()
        with mock.patch("dashboard.b2b.timezone.now", return_value=self.at_hour(11)):
            services.heartbeat(self.sales)
            services.heartbeat(self.sales)
        self.assertEqual(self.reminders(self.sales).count(), 1)


class MoveTests(_B2b):
    def setUp(self):
        super().setUp()
        self.spain = LeadSheet.objects.create(title="Spain", assigned_to=self.other)

    def test_the_manager_moves_a_company_to_another_sales_person(self):
        answer = self.post(self.manager, "v1_b2b_lead_move", {"sheet": self.spain.pk}, self.lead.pk)
        self.assertEqual(answer.status_code, 200, answer.content)
        self.lead.refresh_from_db()
        self.assertEqual(self.lead.sheet, self.spain)
        self.assertTrue(self.other.notifications.filter(url=f"/app/leads/{self.spain.pk}").exists())
        self.assertTrue(AuditLog.objects.filter(action="b2b.lead_move").exists())
        # The new Sales person contacts from it now, the old one no longer reads it.
        self.assertTrue(_json(self.get(self.other, "v1_b2b_lead", self.lead.pk))["can_contact"])
        self.assertEqual(self.get(self.sales, "v1_b2b_lead", self.lead.pk).status_code, 404)

    def test_a_sales_person_does_not_move_companies(self):
        answer = self.post(self.sales, "v1_b2b_lead_move", {"sheet": self.spain.pk}, self.lead.pk)
        # The other sheet is not theirs to name: it is not found, and nothing moves.
        self.assertEqual(answer.status_code, 404)
        mine = LeadSheet.objects.create(title="Mine too", assigned_to=self.sales)
        answer = self.post(self.sales, "v1_b2b_lead_move", {"sheet": mine.pk}, self.lead.pk)
        self.assertEqual((answer.status_code, _json(answer)["error"]), (403, "not_manager"))
        self.lead.refresh_from_db()
        self.assertEqual(self.lead.sheet, self.sheet)

    def test_a_bad_target_moves_nothing(self):
        for body in ({"sheet": 99999}, {"sheet": "x"}, {}, {"sheet": True}):
            answer = self.post(self.manager, "v1_b2b_lead_move", body, self.lead.pk)
            self.assertIn(answer.status_code, (400, 404), body)
        answer = self.post(self.manager, "v1_b2b_lead_move", {"sheet": self.sheet.pk}, self.lead.pk)
        self.assertEqual(_json(answer)["error"], "same_sheet")
        self.lead.refresh_from_db()
        self.assertEqual(self.lead.sheet, self.sheet)

    def test_a_company_moves_to_the_managers_own_sheet_and_never_to_a_closed_account(self):
        held = LeadSheet.objects.create(title="Held", assigned_to=self.manager)
        offered = [s["title"] for s in _json(self.get(self.manager, "v1_b2b_sheet", self.sheet.pk))["sheets"]]
        self.assertIn("Held", offered)
        User.objects.filter(pk=self.other.pk).update(is_active=False)
        self.assertNotIn("Spain", [s["title"] for s in _json(self.get(self.manager, "v1_b2b_sheet", self.sheet.pk))["sheets"]])
        answer = self.post(self.manager, "v1_b2b_lead_move", {"sheet": self.spain.pk}, self.lead.pk)
        self.assertEqual((answer.status_code, _json(answer)["error"]), (400, "no_sales"))
        self.lead.refresh_from_db()
        self.assertEqual(self.lead.sheet, self.sheet)
        answer = self.post(self.manager, "v1_b2b_lead_move", {"sheet": held.pk}, self.lead.pk)
        self.assertEqual(answer.status_code, 200, answer.content)
        self.lead.refresh_from_db()
        self.assertEqual(self.lead.sheet, held)

    def test_the_manager_is_offered_the_other_sheets_and_a_sales_person_none(self):
        offered = _json(self.get(self.manager, "v1_b2b_sheet", self.sheet.pk))["sheets"]
        self.assertEqual([s["title"] for s in offered], ["Spain"])
        self.assertEqual(_json(self.get(self.sales, "v1_b2b_sheet", self.sheet.pk))["sheets"], [])


# ---------------------------------------------------------------------------
# Part 3: the Sales numbers
# ---------------------------------------------------------------------------

class KpiTests(_B2b):
    def setUp(self):
        super().setUp()
        self.today = timezone.localdate()
        self.period = {"from": (self.today - timedelta(days=30)).isoformat(), "to": self.today.isoformat()}

    def numbers(self, user, **period):
        browser = self.browser(user)
        return browser.get(reverse("dashboard:v1_b2b_kpis"), period or self.period)

    def row(self, user, person=None):
        body = _json(self.numbers(user))
        person = person or user
        return next(row for row in body["rows"] if row["person"]["id"] == person.pk)

    def save_status(self, lead, status):
        values = {name: getattr(lead, name) for name, *_r in b2b.COLUMNS}
        values.update(status=status, next_follow_up="")
        self.assertEqual(self.post(self.manager, "v1_b2b_lead_save", values, lead.pk).status_code, 200)

    def test_the_door_is_under_api_v1_and_closed_to_other_roles(self):
        self.assertEqual(reverse("dashboard:v1_b2b_kpis"), "/api/v1/b2b/kpis/")
        self.assertEqual(self.numbers(self.ops).status_code, 403)
        self.assertEqual(self.numbers(self.tr).status_code, 403)

    def test_what_the_sales_person_did_is_counted(self):
        self.post(self.sales, "v1_b2b_lead_whatsapp", {}, self.lead.pk)
        self.post(self.sales, "v1_b2b_lead_email", {"subject": "s", "body": "b"}, self.lead.pk)
        self.post(self.sales, "v1_b2b_lead_call", {"outcome": "interested"}, self.lead.pk)
        services.ingest_message(channel=Channel.WHATSAPP, body="ok", sender_identity=PHONE, external_id="wamid.k1", owner=self.sales)
        Lead.objects.create(sheet=self.sheet, company_name="Untouched AG")
        row = self.row(self.sales)
        expected = {"new_leads": 2, "contacted": 1, "whatsapp": 1, "emails": 1, "calls": 1, "replies": 1, "holding": 2, "untouched": 1}
        self.assertEqual({name: row[name] for name in expected}, expected)

    def test_contacted_and_whatsapp_agree_when_whatsapp_is_the_only_channel(self):
        # 15/10/2026: «contacted» 286 next to «WhatsApp» 256 - companies counted against messages.
        copy = Lead.objects.create(sheet=self.sheet, company_name="Lingua GmbH (copy)", whatsapp=PHONE)
        self.post(self.sales, "v1_b2b_lead_whatsapp", {}, self.lead.pk)
        self.lead.refresh_from_db()
        copy.refresh_from_db()
        self.assertIsNotNone(copy.whatsapp_at)
        for n in (2, 3):
            reply = OutboundMessage.objects.create(
                client=self.lead.client, kind=OutboundMessage.Kind.CHAT, created_by=self.sales, owner=self.sales,
                channel=Channel.WHATSAPP, to_identity=PHONE, body="hello", status=OutboundMessage.Status.SENT,
                provider_id=f"wamid.reply.{n}",
            )
            b2b.note_outbound(reply)
        # A row whose message failed after its unmarking ran (or before it existed) is not reached by it either.
        stale = Lead.objects.create(sheet=self.sheet, company_name="Stale SARL", whatsapp="+33 6 12 34 56 78")
        gone = OutboundMessage.objects.create(
            client=self.lead.client, kind=OutboundMessage.Kind.CHAT, created_by=self.sales, owner=self.sales,
            channel=Channel.WHATSAPP, to_identity="+33 6 12 34 56 78", status=OutboundMessage.Status.FAILED,
        )
        LeadActivity.objects.create(lead=stale, kind=LeadActivity.Kind.WHATSAPP, automatic=True, at=timezone.now(), outbound=gone, owner=self.sales)
        row = self.row(self.sales)
        self.assertEqual((row["contacted"], row["whatsapp"]), (2, 2))
        self.assertEqual(self.row(self.manager, self.sales)["whatsapp"], 2)

    def test_stages_are_counted_once_per_company_and_the_conversion_rate(self):
        self.save_status(self.lead, "visit")
        self.save_status(self.lead, "follow_up")
        self.save_status(self.lead, "visit")
        self.save_status(self.lead, "won")
        theirs = Lead.objects.create(sheet=LeadSheet.objects.create(title="Spain", assigned_to=self.other), company_name="Iberia")
        self.save_status(theirs, "lost")
        mine = self.row(self.manager, self.sales)
        self.assertEqual((mine["visits"], mine["won"], mine["lost"], mine["conversion_rate"]), (1, 1, 0, 100))
        self.assertNotIn("proposals", mine)
        theirs_row = self.row(self.manager, self.other)
        # Measured, and nothing won: 0%, not "not measured".
        self.assertEqual((theirs_row["lost"], theirs_row["conversion_rate"]), (1, 0))
        total = _json(self.numbers(self.manager))["total"]
        self.assertEqual((total["won"], total["lost"], total["conversion_rate"]), (1, 1, 50))

    def test_no_data_is_not_measured_never_zero_percent(self):
        row = self.row(self.sales)
        self.assertIsNone(row["conversion_rate"])
        self.assertIsNone(row["follow_up_rate"])
        self.assertEqual(row["calls"], 0)

    def test_follow_ups_on_time_late_and_missed(self):
        yesterday = self.today - timedelta(days=1)
        on_time = Lead.objects.create(sheet=self.sheet, company_name="On time", next_follow_up=self.today)
        late = Lead.objects.create(sheet=self.sheet, company_name="Late", next_follow_up=yesterday)
        Lead.objects.create(sheet=self.sheet, company_name="Missed", next_follow_up=yesterday)
        self.post(self.sales, "v1_b2b_lead_call", {"outcome": "follow_up"}, on_time.pk)
        self.post(self.sales, "v1_b2b_lead_call", {"outcome": "follow_up"}, late.pk)
        # A second call the same day does the same follow-up no more.
        self.post(self.sales, "v1_b2b_lead_call", {"outcome": "follow_up"}, late.pk)
        row = self.row(self.sales)
        self.assertEqual(
            (row["follow_ups_on_time"], row["follow_ups_late"], row["follow_ups_missed"], row["overdue_now"], row["follow_up_rate"]),
            (1, 1, 1, 1, 33),
        )

    def test_a_reply_does_not_do_a_follow_up(self):
        Lead.objects.filter(pk=self.lead.pk).update(next_follow_up=self.today)
        services.ingest_message(channel=Channel.WHATSAPP, body="hi", sender_identity=PHONE, external_id="wamid.k2", owner=self.sales)
        self.assertEqual(self.row(self.sales)["follow_ups_on_time"], 0)

    def test_a_sales_person_reads_their_own_row_and_the_manager_the_team(self):
        body = _json(self.numbers(self.sales))
        self.assertEqual(([r["person"]["id"] for r in body["rows"]], body["team"]), ([self.sales.pk], False))
        for user in (self.manager, self.admin):
            body = _json(self.numbers(user))
            ids = {r["person"]["id"] for r in body["rows"]}
            self.assertEqual(ids, {self.sales.pk, self.other.pk}, user.username)
            self.assertTrue(body["team"])

    def test_a_moved_company_keeps_its_history_with_who_worked_it(self):
        self.post(self.sales, "v1_b2b_lead_call", {"outcome": "interested"}, self.lead.pk)
        spain = LeadSheet.objects.create(title="Spain", assigned_to=self.other)
        self.post(self.manager, "v1_b2b_lead_move", {"sheet": spain.pk}, self.lead.pk)
        self.assertEqual(self.row(self.manager, self.sales)["calls"], 1)
        self.assertEqual(self.row(self.manager, self.other)["calls"], 0)
        self.assertEqual(self.row(self.manager, self.other)["holding"], 1)

    def test_what_happened_outside_the_period_is_not_counted(self):
        self.post(self.sales, "v1_b2b_lead_call", {"outcome": "interested"}, self.lead.pk)
        LeadActivity.objects.update(at=timezone.now() - timedelta(days=40))
        self.assertEqual(self.row(self.sales)["calls"], 0)

    def test_a_bad_period_is_refused(self):
        tomorrow = (self.today + timedelta(days=1)).isoformat()
        for period in ({"from": tomorrow, "to": self.today.isoformat()}, {"from": "soon"},
                       {"from": (self.today - timedelta(days=400)).isoformat(), "to": self.today.isoformat()}):
            answer = self.numbers(self.sales, **period)
            self.assertEqual((answer.status_code, _json(answer)["error"]), (400, "bad_period"), period)

    def test_this_month_when_no_period_is_given(self):
        body = _json(self.browser(self.sales).get(reverse("dashboard:v1_b2b_kpis")))
        self.assertEqual((body["from"], body["to"]), (self.today.replace(day=1).isoformat(), self.today.isoformat()))

    def test_no_company_is_named(self):
        self.post(self.sales, "v1_b2b_lead_call", {"outcome": "interested"}, self.lead.pk)
        text = self.numbers(self.manager).content.decode()
        for word in ("Lingua", "Anna", "lingua.test", "7700"):
            self.assertNotIn(word, text)

    def test_a_stage_change_is_on_the_timeline_for_who_holds_the_company(self):
        self.save_status(self.lead, "no_answer")
        stage = self.lead.activities.get(kind="status")
        self.assertEqual((stage.status, stage.owner, stage.by), ("no_answer", self.sales, self.manager))
        self.save_status(self.lead, "no_answer")
        self.assertEqual(self.lead.activities.filter(kind="status").count(), 1)


# ---------------------------------------------------------------------------
# Part 4: quotations, and the task the operation makes from an accepted one
# ---------------------------------------------------------------------------

class _Quotes(_B2b):
    FIGURES = {
        "source_lang": "english", "target_lang": "Arabic", "service": "translation", "unit": "words", "quantity": 1000,
        "rate": "0.08", "discount_percent": "10", "currency": "USD", "deadline": "", "payment_terms": "50% upfront",
        "notes": "Includes one revision.",
    }

    def make(self, user=None, **over):
        return self.post(user or self.sales, "v1_b2b_quotation_create", {**self.FIGURES, **over}, self.lead.pk)

    def made(self, **over):
        answer = self.make(**over)
        self.assertEqual(answer.status_code, 200, answer.content)
        return Quotation.objects.get(pk=_json(answer)["quotation"]["id"])

    def send(self, quote, user=None):
        return self.post(user or self.sales, "v1_b2b_quotation_send", {}, quote.pk)

    def decide(self, quote, accepted, user=None):
        return self.post(user or self.sales, "v1_b2b_quotation_decide", {"accepted": accepted}, quote.pk)


class QuotationTests(_Quotes):
    def test_the_doors_are_under_api_v1(self):
        self.assertEqual(reverse("dashboard:v1_b2b_quotations", args=[4]), "/api/v1/b2b/leads/4/quotations/")
        self.assertEqual(reverse("dashboard:v1_b2b_quotation_send", args=[9]), "/api/v1/b2b/quotations/9/send/")

    def test_a_draft_is_made_with_its_total_and_the_languages_as_codes(self):
        quote = self.made()
        self.assertEqual((quote.status, quote.total, quote.source_lang, quote.target_lang), ("draft", Decimal("72.00"), "EN", "AR"))
        self.assertEqual((quote.owner, quote.created_by), (self.sales, self.sales))
        self.assertTrue(quote.code.startswith("QT-"))
        self.assertEqual(self.lead.activities.get(kind="quotation").notes, "created")
        self.assertTrue(AuditLog.objects.filter(action="b2b.quote_create", target=quote.code).exists())

    def test_only_the_sheets_sales_person_makes_quotations(self):
        for user in (self.manager, self.admin):
            self.assertEqual(_json(self.make(user))["error"], "not_yours", user.username)
        self.assertEqual(self.make(self.other).status_code, 404)
        self.assertEqual(self.make(self.ops).status_code, 403)
        self.assertFalse(Quotation.objects.exists())

    def test_figures_that_make_no_sense_are_refused(self):
        for over, code in (
            ({"target_lang": "en"}, "same_language"), ({"rate": "0"}, "bad_rate"), ({"quantity": 0}, "bad_quantity"),
            ({"discount_percent": "100"}, "bad_discount"), ({"deadline": "2020-01-01"}, "past_deadline"),
        ):
            answer = self.make(**over)
            self.assertEqual((answer.status_code, _json(answer)["error"]), (400, code), over)
        for over in ({"currency": "XYZ"}, {"rate": "0.00001"}, {"quantity": "5"}, {"rate": "abc"}, {"service": "magic"}, {"rate": "NaN"}):
            self.assertEqual(self.make(**over).status_code, 400, over)
        self.assertFalse(Quotation.objects.exists())

    def test_sending_mails_it_from_the_persons_address_and_the_company_is_contacted(self):
        quote = self.made()
        answer = self.send(quote)
        self.assertEqual(answer.status_code, 200, answer.content)
        quote.refresh_from_db()
        self.assertEqual(quote.status, "sent")
        self.assertIsNotNone(quote.outbound)
        args, kwargs = self.mail.call_args
        self.assertEqual((args[1], kwargs["from_email"]), ("anna@lingua.test", "seller@eagle.test"))
        self.assertIn(quote.code, kwargs["subject"])
        self.assertIn("Total: 72.00 USD", kwargs["body"])
        self.assertIn("Dear Anna", kwargs["body"])
        self.lead.refresh_from_db()
        # The letter is the first contact, so the company is «Contacted»; the sheet has no stage for a quotation.
        self.assertEqual(self.lead.status, "contacted")
        self.assertIsNotNone(self.lead.email_at)
        self.assertEqual(set(self.lead.activities.filter(kind="quotation").values_list("notes", flat=True)), {"created", "sent"})

    def test_a_sent_quotation_is_never_changed_or_sent_again_or_deleted(self):
        quote = self.made()
        self.send(quote)
        self.assertEqual(_json(self.post(self.sales, "v1_b2b_quotation_save", {**self.FIGURES, "rate": "1"}, quote.pk))["error"], "not_draft")
        self.assertEqual(_json(self.send(quote))["error"], "not_draft")
        self.assertEqual(_json(self.post(self.sales, "v1_b2b_quotation_delete", {}, quote.pk))["error"], "not_draft")
        quote.refresh_from_db()
        self.assertEqual(quote.total, Decimal("72.00"))
        self.assertEqual(self.mail.call_count, 1)

    def test_a_letter_that_did_not_leave_leaves_a_draft(self):
        quote = self.made()
        self.mail.side_effect = __import__("dashboard.mailer", fromlist=["MailError"]).MailError("x", "x")
        answer = self.send(quote)
        self.assertEqual(_json(answer)["error"], "send_failed")
        quote.refresh_from_db()
        self.assertEqual((quote.status, quote.sent_at), ("draft", None))

    def test_a_company_further_on_keeps_its_stage(self):
        Lead.objects.filter(pk=self.lead.pk).update(status="visit")
        self.send(self.made())
        self.lead.refresh_from_db()
        self.assertEqual(self.lead.status, "visit")

    def test_a_copy_is_a_new_draft_and_the_sent_one_stays(self):
        quote = self.made()
        self.send(quote)
        answer = self.post(self.sales, "v1_b2b_quotation_copy", {}, quote.pk)
        copy = Quotation.objects.get(pk=_json(answer)["quotation"]["id"])
        self.assertNotEqual(copy.code, quote.code)
        self.assertEqual((copy.status, copy.total, copy.notes), ("draft", quote.total, quote.notes))
        quote.refresh_from_db()
        self.assertEqual(quote.status, "sent")

    def test_a_draft_is_changed_and_deleted(self):
        quote = self.made()
        answer = self.post(self.sales, "v1_b2b_quotation_save", {**self.FIGURES, "quantity": 2000, "discount_percent": "0"}, quote.pk)
        self.assertEqual(_json(answer)["quotation"]["total"], "160.00")
        self.assertEqual(self.post(self.sales, "v1_b2b_quotation_delete", {}, quote.pk).status_code, 200)
        self.assertFalse(Quotation.objects.exists())

    def test_the_row_carries_its_newest_quotation(self):
        self.send(self.made())
        row = _json(self.get(self.sales, "v1_b2b_sheet", self.sheet.pk))["leads"][0]
        self.assertEqual((row["quote"]["status"], row["quote"]["total"], row["quote"]["currency"]), ("sent", "72.00", "USD"))

    def test_another_sales_person_reads_no_quotation(self):
        quote = self.made()
        self.assertEqual(self.get(self.other, "v1_b2b_quotations", self.lead.pk).status_code, 404)
        self.assertEqual(self.post(self.other, "v1_b2b_quotation_copy", {}, quote.pk).status_code, 404)
        self.assertEqual(self.post(self.ops, "v1_b2b_quotation_send", {}, quote.pk).status_code, 403)


class QuotationAnswerTests(_Quotes):
    def setUp(self):
        super().setUp()
        self.quote = self.made(deadline=(timezone.localdate() + timedelta(days=5)).isoformat())
        self.send(self.quote)

    def test_accepted_makes_the_company_won_and_tells_the_operation_without_name_or_price(self):
        answer = self.decide(self.quote, True)
        self.assertEqual(answer.status_code, 200, answer.content)
        self.quote.refresh_from_db()
        self.assertEqual((self.quote.status, self.quote.decided_by), ("accepted", self.sales))
        self.lead.refresh_from_db()
        self.assertEqual(self.lead.status, "won")
        self.assertTrue(self.lead.activities.filter(kind="status", status="won").exists())
        url = f"/app/tasks/new?quote={self.quote.code}"
        for person in (self.ops, self.admin):
            note = person.notifications.get(url=url)
            words = note.body_ar + note.body_en + note.title_ar + note.title_en
            for secret in ("Lingua", "Anna", "72", "USD", "anna@"):
                self.assertNotIn(secret, words, person.username)
            self.assertIn(self.lead.client.code, words)
        self.assertFalse(self.tr.notifications.exists())

    def test_turned_down_is_written_down_and_the_stage_stays(self):
        self.decide(self.quote, False)
        self.quote.refresh_from_db()
        self.lead.refresh_from_db()
        self.assertEqual((self.quote.status, self.lead.status), ("rejected", "contacted"))
        self.assertFalse(self.ops.notifications.exists())

    def test_the_manager_may_record_the_answer_and_nobody_answers_twice_or_a_draft(self):
        self.assertEqual(self.decide(self.quote, True, self.manager).status_code, 200)
        self.assertEqual(_json(self.decide(self.quote, False))["error"], "not_sent")
        draft = self.made()
        self.assertEqual(_json(self.decide(draft, True))["error"], "not_sent")
        self.assertEqual(self.decide(self.quote, True, self.other).status_code, 404)
        self.assertEqual(self.post(self.sales, "v1_b2b_quotation_decide", {"accepted": "yes"}, self.quote.pk).status_code, 400)


class TaskFromQuotationTests(_Quotes):
    def setUp(self):
        super().setUp()
        self.quote = self.made(deadline=(timezone.localdate() + timedelta(days=5)).isoformat())
        self.send(self.quote)
        self.decide(self.quote, True)
        self.quote.refresh_from_db()
        self.lead.refresh_from_db()

    def form(self, user=None, code=None):
        return self.browser(user or self.ops).get(reverse("dashboard:v1_task_start"), {"quote": code or self.quote.code})

    def create(self, **over):
        body = {"client": self.lead.client_id, "title": "Job", "description": "", "source_lang": "EN", "target_lang": "AR",
                "priority": "normal", "quote": self.quote.code, "word_count": 1000, **over}
        return self.browser(self.ops).post(reverse("dashboard:v1_task_create"), json.dumps(body), content_type="application/json")

    def test_the_form_is_filled_from_the_quotation_without_the_company_or_the_price(self):
        answer = self.form()
        body = _json(answer)
        self.assertEqual(body["quote"], {"code": self.quote.code})
        self.lead.refresh_from_db()
        initial = body["initial"]
        self.assertEqual(
            (initial["client"], initial["source_lang"], initial["target_lang"], initial["word_count"], initial["deadline_days"]),
            (self.lead.client_id, "EN", "AR", 1000, 5),
        )
        raw = answer.content.decode()
        for secret in ("Lingua", "Anna", "72.00", "0.08", "50% upfront", "one revision"):
            self.assertNotIn(secret, raw)

    def test_only_an_accepted_quotation_without_a_task_fills_the_form_and_only_for_the_operation(self):
        self.assertEqual(self.form(self.sales).status_code, 403)
        draft = self.made()
        self.assertIsNone(_json(self.form(code=draft.code))["quote"])
        self.assertIsNone(_json(self.form(code="QT-9999"))["quote"])

    def test_the_task_made_from_it_is_the_operations_and_is_linked_once(self):
        answer = self.create()
        self.assertEqual(answer.status_code, 200, answer.content)
        task = Task.objects.get(code=_json(answer)["code"])
        self.assertEqual((task.created_by, task.client_id), (self.ops, self.lead.client_id))
        self.quote.refresh_from_db()
        self.assertEqual(self.quote.task, task)
        # Taken: the form no longer fills from it, and a second task does not take it over.
        self.assertIsNone(_json(self.form())["quote"])
        second = Task.objects.get(code=_json(self.create())["code"])
        self.quote.refresh_from_db()
        self.assertEqual(self.quote.task, task)
        self.assertNotEqual(second, task)

    def test_two_tasks_at_once_link_the_quotation_to_the_first_only(self):
        # Two people pressing at the same moment both got the form filled; the quotation goes to whoever was first.
        first = Task.objects.create(client=self.lead.client, title="a", created_by=self.ops)
        second = Task.objects.create(client=self.lead.client, title="b", created_by=self.ops)
        self.assertTrue(b2b.link_task(self.quote, first))
        self.assertFalse(b2b.link_task(self.quote, second))
        self.quote.refresh_from_db()
        self.assertEqual(self.quote.task, first)

    def test_another_client_named_in_the_form_is_refused(self):
        other = Client.objects.create(name="Someone else", phone="+201111111111")
        answer = self.create(client=other.pk)
        self.assertEqual((answer.status_code, _json(answer)["error"]), (400, "client_mismatch"))
        self.quote.refresh_from_db()
        self.assertIsNone(self.quote.task)

    def test_the_numbers_count_quotations_and_revenue_per_currency(self):
        euro = self.made(currency="EUR", rate="0.10", discount_percent="0")
        self.send(euro)
        self.decide(euro, True)
        period = {"from": (timezone.localdate() - timedelta(days=3)).isoformat(), "to": timezone.localdate().isoformat()}
        body = _json(self.browser(self.manager).get(reverse("dashboard:v1_b2b_kpis"), period))
        row = next(r for r in body["rows"] if r["person"]["id"] == self.sales.pk)
        self.assertEqual((row["quotations"], row["quotes_accepted"]), (2, 2))
        self.assertEqual(row["revenue"], {"EUR": "100.00", "USD": "72.00"})
        self.assertEqual(body["total"]["revenue"], {"EUR": "100.00", "USD": "72.00"})


class DailyLimitTests(_B2b):
    """The opening message's daily limit for each WhatsApp number (``AppSettings.b2b_whatsapp_daily_limit``).

    Meta restricted the account for spam on 17/10/2026 after about 500 opening messages in three days; the review request
    promised 50 a day from each number.
    """

    def setUp(self):
        super().setUp()
        from .models import AppSettings

        self.settings = AppSettings
        # The row is made on first read: an update before it changes nothing.
        AppSettings.load()
        AppSettings.objects.update(b2b_whatsapp_daily_limit=2)

    def company(self, n):
        return Lead.objects.create(sheet=self.sheet, company_name=f"Company {n}", country="Germany", whatsapp=f"+44 7700 91{n:04d}")

    def press(self, lead, user=None):
        return self.post(user or self.sales, "v1_b2b_lead_whatsapp", {}, lead.pk)

    def test_it_is_fifty_unless_the_admin_changes_it(self):
        self.settings.objects.all().delete()
        self.assertEqual(self.settings.load().b2b_whatsapp_daily_limit, 50)

    def test_the_number_stops_at_the_limit_and_the_refused_press_leaves_nothing(self):
        for n in (1, 2):
            self.assertTrue(_json(self.press(self.company(n)))["sent"])
        third = self.company(3)
        answer = self.press(third)
        self.assertEqual((answer.status_code, _json(answer)["error"]), (400, "daily_limit"))
        self.assertIn("2 رسالة تعارف النهارده", _json(answer)["message"])
        self.assertEqual(self.template.call_count, 2)
        # Nothing of the refused press is kept: no client made for the company, no message, the row not marked.
        third.refresh_from_db()
        self.assertEqual((third.client, third.whatsapp_at), (None, None))
        self.assertEqual(OutboundMessage.objects.count(), 2)
        self.assertEqual(set(OutboundMessage.objects.values_list("template", flat=True)), {b2b.INTRO_TEMPLATE})

    def test_each_number_has_its_own_day(self):
        for n in (1, 2):
            self.press(self.company(n))
        theirs = LeadSheet.objects.create(title="Theirs", assigned_to=self.other, created_by=self.manager)
        lead = Lead.objects.create(sheet=theirs, company_name="Elsewhere", country="Germany", whatsapp="+44 7700 919999")
        self.assertTrue(_json(self.press(lead, self.other))["sent"])
        self.assertEqual(self.template.call_args.kwargs, {"from_id": "900003"})

    def test_failed_yesterdays_and_other_messages_do_not_count(self):
        self.template.side_effect = whatsapp.WhatsAppError("مرفوض", "refused")
        for n in (1, 2):
            self.assertEqual(_json(self.press(self.company(n)))["error"], "send_failed")
        self.template.side_effect = None
        self.assertTrue(_json(self.press(self.company(3)))["sent"])
        OutboundMessage.objects.filter(status="sent").update(created_at=timezone.now() - timedelta(days=1))
        # A message written in the chat is not an opening message.
        client = Client.objects.create(name="Someone", phone="+201000000000")
        OutboundMessage.objects.create(client=client, kind="chat", owner=self.sales, channel=Channel.WHATSAPP, status="sent")
        OutboundMessage.objects.create(client=client, kind="chat", owner=self.sales, channel=Channel.WHATSAPP, status="sent")
        for n in (4, 5):
            self.assertTrue(_json(self.press(self.company(n)))["sent"], n)
        self.assertEqual(_json(self.press(self.company(6)))["error"], "daily_limit")

    def test_the_day_is_cairos(self):
        for n in (1, 2):
            self.press(self.company(n))
        # Sent just before Cairo's midnight: yesterday, though it may still be the same day in UTC.
        midnight = timezone.localtime().replace(hour=0, minute=0, second=0, microsecond=0)
        OutboundMessage.objects.update(created_at=midnight - timedelta(minutes=1))
        self.assertTrue(_json(self.press(self.company(3)))["sent"])
        # And sent at one past Cairo's midnight is today, though in UTC it is still yesterday evening.
        OutboundMessage.objects.update(created_at=midnight + timedelta(hours=1))
        self.assertEqual(_json(self.press(self.company(4)))["error"], "daily_limit")

    def test_zero_switches_the_opening_message_off(self):
        self.settings.objects.update(b2b_whatsapp_daily_limit=0)
        answer = self.press(self.company(1))
        self.assertEqual((answer.status_code, _json(answer)["error"]), (400, "intros_off"))
        self.template.assert_not_called()

    def test_a_company_that_wrote_today_still_opens_its_chat(self):
        self.settings.objects.update(b2b_whatsapp_daily_limit=0)
        client = Client.objects.create(name="Anna", phone="+447700900123")
        InboundMessage.objects.create(client=client, channel=Channel.WHATSAPP, body="hi", external_id="wamid.in.limit", owner=self.sales)
        body = _json(self.press(self.lead))
        self.assertEqual((body["ok"], body["sent"], body["chat"]), (True, False, client.code))
        self.template.assert_not_called()

    def test_the_admin_sets_it_on_the_settings_page_and_nobody_else_can(self):
        page = _json(self.get(self.admin, "v1_admin_settings"))
        self.assertIn("b2b_whatsapp_daily_limit", [field["name"] for field in page["fields"]])
        b2b_section = next(section for section in page["sections"] if section["key"] == "b2b")
        self.assertIn("b2b_whatsapp_daily_limit", b2b_section["groups"][0]["fields"])
        save = reverse("dashboard:v1_admin_settings_save")
        answer = self.browser(self.admin).post(save, json.dumps({"values": {"b2b_whatsapp_daily_limit": 30}}), content_type="application/json")
        self.assertEqual(answer.status_code, 200, answer.content)
        self.assertEqual(self.settings.load().b2b_whatsapp_daily_limit, 30)
        for person in (self.manager, self.sales, self.ops):
            answer = self.browser(person).post(save, json.dumps({"values": {"b2b_whatsapp_daily_limit": 500}}), content_type="application/json")
            self.assertEqual(answer.status_code, 403, person.username)
        self.assertEqual(self.settings.load().b2b_whatsapp_daily_limit, 30)
