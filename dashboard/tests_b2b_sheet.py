"""The B2B sheet in the Sales team's own shape (12/10/2026): their Google Sheet's status list, the priority and the deal value,
a cell edited on the sheet that saves that cell alone, and their sheet uploaded as it is."""

import importlib
from decimal import Decimal

from django.apps import apps
from django.test import SimpleTestCase

from . import b2b_import
from .models import Lead, LeadActivity
from .tests_b2b import _B2b, _json

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
        Lead.objects.filter(pk=self.lead.pk).update(notes="keep me", priority="low")
        answer = self.save({"phone": "+965 2221 3775"})
        self.assertEqual(answer.status_code, 200, answer.content)
        self.lead.refresh_from_db()
        self.assertEqual(
            (self.lead.phone, self.lead.notes, self.lead.priority, self.lead.company_name, self.lead.email, self.lead.status),
            ("+965 2221 3775", "keep me", "low", "Lingua GmbH", "anna@lingua.test", "new"),
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
        self.assertEqual(self.save({"notes": "x"}, user=self.other).status_code, 404)
        self.lead.refresh_from_db()
        self.assertEqual(self.lead.notes, "")

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
        self.assertEqual((bash.status, bash.priority, bash.deal_value, bash.notes), ("contacted", "medium", Decimal("1500"), "call back"))
        self.assertEqual((plain.status, plain.priority, plain.deal_value, plain.notes), ("new", "", None, ""))

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
