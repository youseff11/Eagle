"""The B2B sheet in the Sales team's own shape (12/10/2026): their Google Sheet's status list, the priority and the deal value,
a cell edited on the sheet that saves that cell alone, and their sheet uploaded as it is."""

import importlib
from datetime import timedelta
from decimal import Decimal

from django.apps import apps
from django.test import SimpleTestCase
from django.utils import timezone

from . import b2b_import
from . import services
from .models import AuditLog, Channel, Client, Lead, LeadActivity, LeadNote, OutboundMessage
from .tests_b2b import PHONE, _B2b, _json

#: The test company's WhatsApp number as WhatsApp sends it.
PHONE_DIGITS = "447700900123"

#: The Sales team's Google Sheet as a CSV, its own headers and words (the NAME column is empty there).
TEAM_SHEET = (
    "الشركة,الشخص المسؤول,رقم الهاتف,البريد الإلكتروني,الحالة,الأولوية,قيمة الصفقة,النشاط,ملاحظات,NAME,الدوله \n"
    ",,,,,,,,,,\n"
    "BASH,,96522213775,,تم التواصل,متوسطة,,Tourism,,,الكويت\n"
    "Tathkarah travels,,96522206222,,تم التواصل,متوسطة,\"1,500 $\",Tourism,قالي هيتواصلوا,,الكويت\n"
    "Captain Tours,,966590070360,,whatsapp,عالية,,Tourism,,Somebody,الكويت\n"
    "Khaitan,,24737021,,متابعة,,,Tourism,مفيش واتساب ولا ايميل,,الكويت\n"
    "Odd Co,,123,,E,urgent,a lot,,,,الكويت\n"
)


class TeamSheetReadTests(SimpleTestCase):
    def test_the_team_sheet_is_read_with_its_status_priority_deal_and_notes(self):
        rows, mapped = b2b_import.to_rows(b2b_import.read_text(TEAM_SHEET))
        self.assertEqual(mapped["status"], "الحالة")
        self.assertEqual(mapped["country"], "الدوله")
        self.assertEqual(len(rows), 5)
        bash, tathkarah, captain, khaitan, odd = rows
        self.assertEqual((bash["status"], bash["priority"], bash["industry"], bash["country"]), ("contacted", "medium", "Tourism", "الكويت"))
        self.assertEqual((tathkarah["deal_value"], tathkarah["notes"]), ("1500", "قالي هيتواصلوا"))
        self.assertEqual((captain["status"], captain["priority"]), ("whatsapp", "high"))
        # NAME is not the contact person: the first column named for it keeps it.
        self.assertEqual(captain["contact_person"], "")
        self.assertEqual(khaitan["status"], "follow_up")
        # A word the sheet does not know is left out: the row comes in «New client», with no priority and no value.
        self.assertNotIn("status", odd)
        self.assertNotIn("priority", odd)
        self.assertNotIn("deal_value", odd)


class CellTests(_B2b):
    def save(self, body, user=None):
        return self.post(user or self.sales, "v1_b2b_lead_save", body, self.lead.pk)

    def test_one_cell_saves_that_cell_and_nothing_else(self):
        Lead.objects.filter(pk=self.lead.pk).update(deal_value=Decimal("9"), priority="low")
        answer = self.save({"phone": "+965 2221 3775"})
        self.assertEqual(answer.status_code, 200, answer.content)
        self.lead.refresh_from_db()
        self.assertEqual(
            (self.lead.phone, self.lead.deal_value, self.lead.priority, self.lead.company_name, self.lead.email, self.lead.status),
            ("+965 2221 3775", Decimal("9"), "low", "Lingua GmbH", "anna@lingua.test", "new"),
        )
        self.assertFalse(self.lead.activities.exists())

    def test_the_status_cell_is_a_stage_change(self):
        self.assertEqual(self.save({"status": "won"}).status_code, 200)
        self.lead.refresh_from_db()
        self.assertEqual(self.lead.status, "won")
        self.assertEqual(self.lead.activities.get(kind=LeadActivity.Kind.STATUS).status, "won")

    def test_priority_and_deal_value(self):
        body = _json(self.save({"priority": "high", "deal_value": "1,500.50"}))
        self.assertEqual((body["lead"]["priority"], body["lead"]["deal_value"]), ("high", "1500.5"))
        self.lead.refresh_from_db()
        self.assertEqual((self.lead.priority, self.lead.deal_value), ("high", Decimal("1500.50")))
        self.assertEqual(_json(self.save({"deal_value": 2000}))["lead"]["deal_value"], "2000")
        cleared = _json(self.save({"priority": "", "deal_value": ""}))["lead"]
        self.assertEqual((cleared["priority"], cleared["deal_value"]), ("", ""))

    def test_a_cell_that_is_not_one_writes_nothing(self):
        Lead.objects.filter(pk=self.lead.pk).update(deal_value=Decimal("10"))
        for body in (
            {"priority": "urgent"}, {"deal_value": "-5"}, {"deal_value": "1.234"}, {"deal_value": "abc"}, {"deal_value": True},
            {"deal_value": "1e3"}, {"deal_value": "NaN"}, {"deal_value": "9999999999999"}, {"status": ""}, {"status": "meeting"},
            {"phone": 5}, {"next_follow_up": "soon"},
        ):
            self.assertEqual(self.save(body).status_code, 400, body)
        self.lead.refresh_from_db()
        self.assertEqual((self.lead.deal_value, self.lead.status, self.lead.priority), (Decimal("10"), "new", ""))

    def test_the_company_cell_may_not_be_emptied(self):
        self.assertEqual(_json(self.save({"company_name": "  "}))["error"], "no_company")
        self.lead.refresh_from_db()
        self.assertEqual(self.lead.company_name, "Lingua GmbH")

    def test_a_cell_on_a_sheet_that_is_not_ones_own_is_a_404(self):
        self.assertEqual(self.save({"priority": "high"}, user=self.other).status_code, 404)
        self.lead.refresh_from_db()
        self.assertEqual(self.lead.priority, "")

    def test_a_save_that_carries_notes_writes_nothing(self):
        # A note is added on its own door, never written over by a save from a page out of date.
        self.assertEqual(self.save({"priority": "high", "notes": "old block"}).status_code, 400)
        self.lead.refresh_from_db()
        self.assertEqual((self.lead.priority, self.lead.note_items.count()), ("", 0))

    def test_the_sheet_says_the_priorities_and_its_rows_carry_them(self):
        Lead.objects.filter(pk=self.lead.pk).update(priority="medium", deal_value=Decimal("250.00"))
        body = _json(self.get(self.sales, "v1_b2b_sheet", self.sheet.pk))
        self.assertEqual([one["value"] for one in body["priorities"]], ["high", "medium", "low"])
        self.assertEqual(
            [one["value"] for one in body["statuses"]],
            ["new", "contacted", "follow_up", "won", "lost", "whatsapp", "visit", "no_answer", "call"],
        )
        row = body["leads"][0]
        self.assertEqual((row["priority"], row["deal_value"]), ("medium", "250"))


class UploadTests(_B2b):
    def test_uploaded_rows_keep_their_status_priority_deal_and_notes(self):
        rows = [
            {"company_name": "BASH", "status": "contacted", "priority": "medium", "deal_value": "1500", "notes": "call back"},
            {"company_name": "Plain"},
        ]
        answer = self.post(self.sales, "v1_b2b_rows_add", {"rows": rows}, self.sheet.pk)
        self.assertEqual(answer.status_code, 200, answer.content)
        bash, plain = Lead.objects.get(company_name="BASH"), Lead.objects.get(company_name="Plain")
        self.assertEqual((bash.status, bash.priority, bash.deal_value), ("contacted", "medium", Decimal("1500")))
        note = bash.note_items.get()
        self.assertEqual((note.text, note.by), ("call back", self.sales))
        self.assertEqual((plain.status, plain.priority, plain.deal_value, plain.note_items.count()), ("new", "", None, 0))

    def test_an_uploaded_row_with_a_wrong_value_adds_nothing(self):
        for bad in ({"status": "meeting"}, {"priority": "top"}, {"deal_value": "-1"}):
            answer = self.post(self.sales, "v1_b2b_rows_add", {"rows": [{"company_name": "X", **bad}]}, self.sheet.pk)
            self.assertEqual(answer.status_code, 400, bad)
        self.assertFalse(Lead.objects.filter(company_name="X").exists())


class OldStagesTests(_B2b):
    def test_the_old_stages_become_the_sheets_words(self):
        migration = importlib.import_module("dashboard.migrations.0070_lead_sheet_columns")
        old = {"email_sent": "contacted", "follow_up_1": "follow_up", "follow_up_2": "follow_up", "meeting": "visit",
               "proposal": "follow_up", "negotiation": "follow_up", "won": "won", "lost": "lost", "new": "new"}
        made = {}
        for stage in old:
            lead = Lead.objects.create(sheet=self.sheet, company_name=f"Co {stage}")
            Lead.objects.filter(pk=lead.pk).update(status=stage)
            activity = LeadActivity.objects.create(lead=lead, kind=LeadActivity.Kind.STATUS, status=stage)
            LeadActivity.objects.filter(pk=activity.pk).update(status=stage)
            made[stage] = (lead.pk, activity.pk)
        migration.to_sheet_words(apps, None)
        for stage, (lead_id, activity_id) in made.items():
            self.assertEqual(Lead.objects.get(pk=lead_id).status, old[stage], stage)
            self.assertEqual(LeadActivity.objects.get(pk=activity_id).status, old[stage], stage)


class SeveralPhonesTests(_B2b):
    """A company with more than one number (12/10/2026): one a line in the phone cell."""

    def setUp(self):
        super().setUp()
        Lead.objects.filter(pk=self.lead.pk).update(whatsapp="")
        self.lead.refresh_from_db()
        self.lead.phone = "+965 2221 3775\n+965 9988 7766 / 24737021"
        self.lead.save()

    def test_every_number_is_read_and_kept_as_a_key(self):
        self.assertEqual(self.lead.all_phones, ["+96522213775", "+96599887766", "24737021"])
        self.assertEqual(self.lead.phone_key, "522213775")
        self.assertIn(" 599887766 ", self.lead.phone_keys)
        body = _json(self.get(self.sales, "v1_b2b_sheet", self.sheet.pk))
        self.assertEqual(body["leads"][0]["phones"], ["+96522213775", "+96599887766", "24737021"])

    def test_the_cell_takes_several_numbers(self):
        answer = self.post(self.sales, "v1_b2b_lead_save", {"phone": "0100 111 2222\n0122 333 4444"}, self.lead.pk)
        self.assertEqual(answer.status_code, 200, answer.content)
        self.lead.refresh_from_db()
        self.assertEqual(self.lead.all_phones, ["01001112222", "01223334444"])
        self.assertEqual(self.post(self.sales, "v1_b2b_lead_save", {"phone": "1" * 251}, self.lead.pk).status_code, 400)

    def test_whatsapp_goes_to_the_number_chosen_and_the_client_keeps_the_others(self):
        answer = self.post(self.sales, "v1_b2b_lead_whatsapp", {"number": "+965 9988 7766"}, self.lead.pk)
        self.assertEqual(answer.status_code, 200, answer.content)
        self.assertEqual(self.template.call_args.args[0], "96599887766")
        client = Client.objects.get(code=_json(answer)["chat"])
        self.assertEqual(client.phone, "96599887766")
        self.assertEqual(client.extra_phones.split("\n"), ["+96522213775", "24737021"])

    def test_without_a_choice_the_first_number_and_a_stranger_number_is_refused(self):
        self.assertEqual(self.post(self.sales, "v1_b2b_lead_whatsapp", {}, self.lead.pk).status_code, 200)
        self.assertEqual(self.template.call_args.args[0], "96522213775")
        answer = self.post(self.sales, "v1_b2b_lead_whatsapp", {"number": "+20 100 000 0000"}, self.lead.pk)
        self.assertEqual(_json(answer)["error"], "not_its_number")
        self.assertEqual(self.template.call_count, 1)

    def test_an_answer_from_the_second_number_marks_the_row(self):
        services.ingest_message(
            channel=Channel.WHATSAPP, body="hello", sender_identity="96599887766", external_id="wamid.two", owner=self.sales,
        )
        self.lead.refresh_from_db()
        self.assertIsNotNone(self.lead.replied_at)
        # And it is the company already on the sheet: no row of its own on the sheet of companies that wrote first.
        self.assertEqual(Lead.objects.count(), 1)

    def test_old_rows_get_the_keys_of_every_number(self):
        migration = importlib.import_module("dashboard.migrations.0071_lead_several_phones")
        Lead.objects.filter(pk=self.lead.pk).update(phone_keys="", phone_key="", whatsapp="+44 7700 900123")
        migration.keys_for_every_number(apps, None)
        self.lead.refresh_from_db()
        self.assertEqual(self.lead.phone_keys, " 700900123 522213775 599887766 24737021 ")
        self.assertEqual(self.lead.phone_key, "700900123")


class NoteTests(_B2b):
    """Each note on its own, with the day it was written and who wrote it (12/10/2026)."""

    def add(self, text, user=None):
        return self.post(user or self.sales, "v1_b2b_lead_note_add", {"text": text}, self.lead.pk)

    def test_the_doors_are_under_api_v1(self):
        from django.urls import reverse

        self.assertEqual(reverse("dashboard:v1_b2b_lead_note_add", args=[5]), "/api/v1/b2b/leads/5/notes/")
        self.assertEqual(reverse("dashboard:v1_b2b_lead_note_delete", args=[9]), "/api/v1/b2b/notes/9/delete/")
        self.assertEqual(reverse("dashboard:v1_b2b_lead_send", args=[5]), "/api/v1/b2b/leads/5/send/")

    def test_notes_are_added_one_by_one_each_dated_and_signed(self):
        self.assertEqual(self.add("  first call, no answer ").status_code, 200)
        body = _json(self.add("sent the rate sheet", user=self.manager))
        notes = body["lead"]["notes"]
        self.assertEqual([n["text"] for n in notes], ["first call, no answer", "sent the rate sheet"])
        self.assertEqual([n["by"]["name"] for n in notes], ["Seller", "Manager"])
        today = timezone.localtime().strftime("%d/%m/%Y")
        self.assertEqual({n["day"] for n in notes}, {today})
        self.assertTrue(AuditLog.objects.filter(action="b2b.note", detail__startswith="note ").exists())
        # The sheet answers the notes too.
        sheet = _json(self.get(self.sales, "v1_b2b_sheet", self.sheet.pk))
        self.assertEqual(len(sheet["leads"][0]["notes"]), 2)

    def test_an_empty_or_too_long_note_or_a_stranger_writes_nothing(self):
        self.assertEqual(_json(self.add("   "))["error"], "empty")
        self.assertEqual(self.add("x" * 4001).status_code, 400)
        self.assertEqual(self.add("hello", user=self.other).status_code, 404)
        self.assertEqual(self.add("hello", user=self.ops).status_code, 403)
        self.assertFalse(LeadNote.objects.exists())

    def test_a_note_is_taken_off_by_its_writer_or_the_manager_only(self):
        mine = LeadNote.objects.create(lead=self.lead, text="mine", by=self.sales)
        theirs = LeadNote.objects.create(lead=self.lead, text="the manager's", by=self.manager)
        answer = self.post(self.sales, "v1_b2b_lead_note_delete", {}, theirs.pk)
        self.assertEqual((answer.status_code, _json(answer)["error"]), (403, "not_yours"))
        self.assertEqual(self.post(self.other, "v1_b2b_lead_note_delete", {}, mine.pk).status_code, 404)
        self.assertEqual(self.post(self.sales, "v1_b2b_lead_note_delete", {}, mine.pk).status_code, 200)
        self.assertEqual(self.post(self.manager, "v1_b2b_lead_note_delete", {}, theirs.pk).status_code, 200)
        self.assertFalse(LeadNote.objects.exists())

    def test_the_old_block_of_notes_becomes_dated_notes(self):
        from django.db import connection

        migration = importlib.import_module("dashboard.migrations.0072_lead_notes_dated")

        class OldLead:
            def __init__(self, pk, notes, updated_at):
                self.pk, self.notes, self.updated_at = pk, notes, updated_at

        class OldLeads:
            def __init__(self, rows):
                self.rows = rows

            def exclude(self, **kw):
                return self

            def only(self, *names):
                return self.rows

        class FakeApps:
            def get_model(self, app, name):
                if name == "LeadNote":
                    return LeadNote
                fake = type("Lead", (), {})
                fake.objects = OldLeads([OldLead(self_lead.pk, "first\n\n  second  ", stamp)])
                return fake

        self_lead, stamp = self.lead, timezone.now() - timedelta(days=3)
        migration.notes_to_rows(FakeApps(), connection.schema_editor)
        notes = list(self.lead.note_items.all())
        self.assertEqual([n.text for n in notes], ["first", "second"])
        self.assertEqual({n.at for n in notes}, {stamp})
        self.assertEqual({n.by for n in notes}, {None})


class SeveralWhatsappTests(_B2b):
    def test_the_whatsapp_cell_takes_several_numbers_and_they_come_first(self):
        answer = self.post(self.sales, "v1_b2b_lead_save", {"whatsapp": "+44 7700 900123\n+44 7700 900456", "phone": "+44 20 1234 5678"}, self.lead.pk)
        self.assertEqual(answer.status_code, 200, answer.content)
        self.assertEqual(_json(answer)["lead"]["phones"], ["+447700900123", "+447700900456", "+442012345678"])


class SendTests(_B2b):
    """A message written on the sheet to a number or the address, marked on the row by itself (12/10/2026)."""

    def send(self, body, user=None):
        return self.post(user or self.sales, "v1_b2b_lead_send", body, self.lead.pk)

    def their_message(self, sender=PHONE_DIGITS):
        services.ingest_message(channel=Channel.WHATSAPP, body="hi", sender_identity=sender, external_id="wamid.in.s", owner=self.sales)

    def test_a_written_whatsapp_goes_when_they_wrote_in_the_last_day_and_marks_the_row(self):
        self.their_message()
        answer = self.send({"channel": "whatsapp", "to": PHONE, "body": "Thanks, here are our rates"})
        self.assertEqual(answer.status_code, 200, answer.content)
        self.text.assert_called_once()
        self.assertEqual(self.text.call_args.kwargs.get("from_id"), "900002")
        sent = OutboundMessage.objects.get(channel=Channel.WHATSAPP)
        self.assertEqual((sent.owner, sent.body, sent.status), (self.sales, "Thanks, here are our rates", "sent"))
        self.lead.refresh_from_db()
        self.assertIsNotNone(self.lead.whatsapp_at)
        self.assertEqual(self.lead.activities.filter(kind="whatsapp", incoming=False).count(), 1)
        self.assertEqual(_json(answer)["lead"]["whatsapp_at"] != "", True)

    def test_without_their_message_whatsapp_carries_only_the_opening_one(self):
        answer = self.send({"channel": "whatsapp", "to": PHONE, "body": "hello"})
        self.assertEqual(_json(answer)["error"], "window_closed")
        self.text.assert_not_called()
        self.template.assert_not_called()
        self.assertFalse(OutboundMessage.objects.exists())

    def test_the_window_is_the_number_they_wrote_from(self):
        Lead.objects.filter(pk=self.lead.pk).update(phone="+44 7700 900456")
        self.lead.refresh_from_db()
        self.lead.save()
        self.their_message()
        answer = self.send({"channel": "whatsapp", "to": "+44 7700 900456", "body": "hello"})
        self.assertEqual(_json(answer)["error"], "window_closed")
        self.text.assert_not_called()

    def test_a_stranger_number_an_empty_message_and_another_persons_sheet_are_refused(self):
        self.their_message()
        self.assertEqual(_json(self.send({"channel": "whatsapp", "to": "+20 100 000 0000", "body": "x"}))["error"], "not_its_number")
        self.assertEqual(_json(self.send({"channel": "whatsapp", "to": PHONE, "body": "  "}))["error"], "empty")
        self.assertEqual(_json(self.send({"channel": "whatsapp", "to": PHONE, "body": "x"}, user=self.manager))["error"], "not_yours")
        self.assertEqual(self.send({"channel": "fax", "body": "x"}).status_code, 400)
        self.text.assert_not_called()

    def test_an_email_goes_from_the_persons_address_and_marks_the_row(self):
        answer = self.send({"channel": "email", "subject": "Rates", "body": "Dear Anna"})
        self.assertEqual(answer.status_code, 200, answer.content)
        self.assertEqual(self.mail.call_args.kwargs["from_email"], "seller@eagle.test")
        self.lead.refresh_from_db()
        self.assertIsNotNone(self.lead.email_at)
        self.assertEqual(self.lead.status, "contacted")
