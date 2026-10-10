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
            # The manager hands the sheets out and holds none: not on the list.
            self.assertEqual({p["id"] for p in body["sales"]}, {self.sales.pk, self.other.pk})

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

    def test_a_sheet_never_goes_to_a_sales_manager(self):
        second = User.objects.create_user("manager2", password="pw", role=Role.SALES, is_sales_manager=True)
        for person in (self.manager, second):
            answer = self.post(self.manager, "v1_b2b_sheet_create", {"title": "Mine", "assigned_to": person.pk})
            self.assertEqual((answer.status_code, _json(answer)["error"]), (400, "no_sales"), person.username)
            answer = self.post(self.admin, "v1_b2b_sheet_save", {"title": "Germany", "assigned_to": person.pk}, self.sheet.pk)
            self.assertEqual((answer.status_code, _json(answer)["error"]), (400, "no_sales"), person.username)
        self.assertFalse(LeadSheet.objects.filter(title="Mine").exists())
        self.sheet.refresh_from_db()
        self.assertEqual(self.sheet.assigned_to, self.sales)
        listed = {p["id"] for p in _json(self.get(self.manager, "v1_b2b_sheet", self.sheet.pk))["sales"]}
        self.assertNotIn(self.manager.pk, listed)
        self.assertNotIn(second.pk, listed)

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


class RowTests(_B2b):
    def test_a_pasted_block_adds_its_rows_and_skips_the_empty_ones(self):
        rows = [{"company_name": "Alpha Ltd", "whatsapp": "+33 6 12 34 56 78"}, {"company_name": ""}, {"company_name": "Beta"}]
        answer = self.post(self.sales, "v1_b2b_rows_add", {"rows": rows}, self.sheet.pk)
        self.assertEqual((answer.status_code, _json(answer)["added"]), (200, 2))
        alpha = Lead.objects.get(company_name="Alpha Ltd")
        self.assertEqual(alpha.phone_key, Client.phone_key("+33612345678"))
        self.assertEqual(alpha.created_by, self.sales)

    def test_a_row_of_the_wrong_shape_writes_nothing(self):
        for body in ({"rows": []}, {"rows": "x"}, {"rows": [{"company_name": 5}]}, {"rows": [{"company_name": "a" * 161}]}, {"rows": [1]}):
            answer = self.post(self.sales, "v1_b2b_rows_add", body, self.sheet.pk)
            self.assertEqual(answer.status_code, 400, body)
        self.assertEqual(self.sheet.leads.count(), 1)

    def test_a_row_is_corrected_and_its_status_change_is_written_down(self):
        values = {name: getattr(self.lead, name) for name, *_r in b2b.COLUMNS}
        values.update(status="meeting", next_follow_up="2026-10-20", notes="call Tuesday", whatsapp="+44 7700 900999")
        answer = self.post(self.sales, "v1_b2b_lead_save", values, self.lead.pk)
        self.assertEqual(answer.status_code, 200)
        self.lead.refresh_from_db()
        self.assertEqual((self.lead.status, str(self.lead.next_follow_up)), ("meeting", "2026-10-20"))
        self.assertEqual(self.lead.phone_key, Client.phone_key("+447700900999"))
        self.assertTrue(AuditLog.objects.filter(action="b2b.lead_status", detail="new -> meeting").exists())
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
            "447700900123", b2b.INTRO_TEMPLATE, "en", ["Anna", "Seller", "German to Arabic"], from_id="900002",
        )
        client = Client.objects.get(code=body["chat"])
        self.assertEqual((client.company, client.name, client.email), ("Lingua GmbH", "Anna Schmidt", "anna@lingua.test"))
        sent = OutboundMessage.objects.get(client=client)
        self.assertEqual((sent.status, sent.owner, sent.channel, sent.provider_id), ("sent", self.sales, "whatsapp", "wamid.intro.1"))
        self.assertIn("this is Seller from EagleLingua", sent.body)
        self.lead.refresh_from_db()
        self.assertEqual(self.lead.client, client)
        self.assertIsNotNone(self.lead.whatsapp_at)
        self.assertEqual(self.lead.last_contact_at, self.lead.whatsapp_at)
        activity = self.lead.activities.get()
        self.assertEqual((activity.kind, activity.automatic, activity.outbound), ("whatsapp", True, sent))
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
        spec = b2b.INTRO_SPEC
        count = spec["body"].count("{{")
        self.assertEqual(len(spec["example"]), count)
        self.assertEqual(len(b2b.intro_params(self.lead, self.sales)), count)
        self.assertFalse(spec["body"].lstrip().startswith("{{"))
        self.assertFalse(spec["body"].rstrip().rstrip(".?!").endswith("}}"))
        from .management.commands.wa_templates import TEMPLATES

        self.assertIs(TEMPLATES[b2b.INTRO_TEMPLATE], spec)



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
        self.assertEqual(self.lead.activities.count(), 1)

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
        # The first letter moved it to «Email sent», and that is on the timeline too.
        stage = self.lead.activities.get(kind="status")
        self.assertEqual((stage.status, stage.automatic, stage.owner), ("email_sent", True, self.sales))

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
        self.assertEqual({a["kind"] for a in body["activities"]}, {"call", "whatsapp"})
        self.assertFalse(body["can_contact"])


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

    def test_the_first_letter_moves_a_new_company_to_email_sent(self):
        self.post(self.sales, "v1_b2b_lead_email", {"subject": "s", "body": "b"}, self.lead.pk)
        self.lead.refresh_from_db()
        self.assertEqual(self.lead.status, "email_sent")
        self.assertTrue(AuditLog.objects.filter(action="b2b.lead_status", detail__contains="automatic").exists())
        # A company further on the way stays where it is.
        Lead.objects.filter(pk=self.lead.pk).update(status="negotiation")
        self.post(self.sales, "v1_b2b_lead_email", {"subject": "s2", "body": "b2"}, self.lead.pk)
        self.lead.refresh_from_db()
        self.assertEqual(self.lead.status, "negotiation")

    def test_a_whatsapp_does_not_move_the_status(self):
        self.post(self.sales, "v1_b2b_lead_whatsapp", {}, self.lead.pk)
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

    def test_no_company_is_moved_to_a_sheet_a_manager_holds(self):
        # A sheet from before the rule, held by the manager: not offered, and refused when named by hand.
        held = LeadSheet.objects.create(title="Held", assigned_to=self.manager)
        offered = [s["title"] for s in _json(self.get(self.manager, "v1_b2b_sheet", self.sheet.pk))["sheets"]]
        self.assertNotIn("Held", offered)
        answer = self.post(self.manager, "v1_b2b_lead_move", {"sheet": held.pk}, self.lead.pk)
        self.assertEqual((answer.status_code, _json(answer)["error"]), (400, "no_sales"))
        self.lead.refresh_from_db()
        self.assertEqual(self.lead.sheet, self.sheet)

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
        values.update(status=status, notes="", next_follow_up="")
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

    def test_stages_are_counted_once_per_company_and_the_conversion_rate(self):
        self.save_status(self.lead, "meeting")
        self.save_status(self.lead, "proposal")
        self.save_status(self.lead, "meeting")
        self.save_status(self.lead, "won")
        theirs = Lead.objects.create(sheet=LeadSheet.objects.create(title="Spain", assigned_to=self.other), company_name="Iberia")
        self.save_status(theirs, "lost")
        mine = self.row(self.manager, self.sales)
        self.assertEqual((mine["meetings"], mine["proposals"], mine["won"], mine["lost"], mine["conversion_rate"]), (1, 1, 1, 0, 100))
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
        self.save_status(self.lead, "negotiation")
        stage = self.lead.activities.get(kind="status")
        self.assertEqual((stage.status, stage.owner, stage.by), ("negotiation", self.sales, self.manager))
        self.save_status(self.lead, "negotiation")
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

    def test_sending_mails_it_from_the_persons_address_and_moves_the_company_to_proposal(self):
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
        self.assertEqual(self.lead.status, "proposal")
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
        Lead.objects.filter(pk=self.lead.pk).update(status="negotiation")
        self.send(self.made())
        self.lead.refresh_from_db()
        self.assertEqual(self.lead.status, "negotiation")

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
        self.assertEqual((self.quote.status, self.lead.status), ("rejected", "proposal"))
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
