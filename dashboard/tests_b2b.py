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
from unittest import mock

from django.test import Client as DjangoClient
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from . import b2b, identity, services, whatsapp
from .forms import StaffEditForm
from .tests_reset_staff import _Staff
from .models import (
    AuditLog, Channel, Client, InboundMessage, Lead, LeadActivity, LeadSheet, OutboundMessage, Role, User,
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
            self.assertEqual({p["id"] for p in body["sales"]}, {self.manager.pk, self.sales.pk, self.other.pk})

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
        self.assertEqual(self.lead.activities.get().kind, "email")

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

    def test_the_manager_is_offered_the_other_sheets_and_a_sales_person_none(self):
        offered = _json(self.get(self.manager, "v1_b2b_sheet", self.sheet.pk))["sheets"]
        self.assertEqual([s["title"] for s in offered], ["Spain"])
        self.assertEqual(_json(self.get(self.sales, "v1_b2b_sheet", self.sheet.pk))["sheets"], [])
