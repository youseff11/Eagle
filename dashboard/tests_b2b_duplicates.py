"""The same company twice on a sheet (15/10/2026): «الصفوف المكررة» finds the rows that share a number, an address or a name,
and deleting the copies moves what they held to the row that stays."""

from datetime import timedelta
from decimal import Decimal

from django.urls import reverse
from django.utils import timezone

from . import b2b
from .models import AuditLog, Client, Lead, LeadActivity, LeadNote, LeadSheet, Quotation
from .tests_b2b import _B2b, _json


class DuplicateTests(_B2b):
    def add(self, name, sheet=None, **values):
        return Lead.objects.create(sheet=sheet or self.sheet, company_name=name, **values)

    def groups(self, user=None, sheet=None):
        answer = self.get(user or self.sales, "v1_b2b_duplicates", (sheet or self.sheet).pk)
        self.assertEqual(answer.status_code, 200, answer.content)
        return _json(answer)["groups"]

    def remove(self, keep, remove, user=None, sheet=None):
        return self.post(user or self.sales, "v1_b2b_duplicates_remove", {"keep": keep, "remove": remove}, (sheet or self.sheet).pk)

    def test_the_doors_are_under_api_v1(self):
        # A test of a door that is not there passes blind: these are the addresses the page calls.
        self.assertEqual(reverse("dashboard:v1_b2b_duplicates", args=[4]), "/api/v1/b2b/sheets/4/duplicates/")
        self.assertEqual(reverse("dashboard:v1_b2b_duplicates_remove", args=[4]), "/api/v1/b2b/sheets/4/duplicates/remove/")

    def test_same_number_address_or_name_are_one_company(self):
        # self.lead: "Lingua GmbH", anna@lingua.test, +44 7700 900123.
        by_phone = self.add("Other name", phone="00447700900123")
        by_email = self.add("Third", email="ANNA@Lingua.test ")
        by_name = self.add("lingua  gmbh.")
        alone = self.add("Somebody else", phone="+20 100 000 0000", email="x@y.test")
        groups = self.groups()
        self.assertEqual(len(groups), 1)
        self.assertEqual(groups[0]["ids"], [self.lead.pk, by_phone.pk, by_email.pk, by_name.pk])
        self.assertEqual(groups[0]["why"], ["phone", "email", "name"])
        self.assertNotIn(alone.pk, groups[0]["ids"])

    def test_a_chain_is_one_group_and_names_differ_in_spaces_only(self):
        a = self.add("Frutos MirandaTraductores", phone="34696531093")
        b = self.add("Frutos Miranda Traductores", email="info@frutos.test")
        c = self.add("Frutos Group", email="INFO@frutos.test")
        groups = [g for g in self.groups() if a.pk in g["ids"]]
        self.assertEqual(groups[0]["ids"], [a.pk, b.pk, c.pk])
        self.assertEqual(groups[0]["why"], ["email", "name"])

    def test_a_short_number_another_sheet_and_an_empty_cell_are_not_a_match(self):
        self.add("A", phone="123")
        self.add("B", phone="123")
        self.add("", email="")
        self.add(" ", email="")
        other = LeadSheet.objects.create(title="Spain", assigned_to=self.sales, created_by=self.manager)
        self.add("Lingua GmbH", sheet=other)
        self.assertEqual(self.groups(), [])

    def test_the_row_suggested_to_stay_is_the_one_worked(self):
        copy = self.add("Lingua GmbH")
        self.assertEqual(self.groups()[0]["keep"], self.lead.pk)
        Lead.objects.filter(pk=copy.pk).update(call_at=timezone.now())
        self.assertEqual(self.groups()[0]["keep"], copy.pk)

    def test_deleting_the_copies_moves_what_they_held(self):
        early = timezone.now() - timedelta(days=5)
        client = Client.objects.create(name="Anna", phone="+447700900123")
        copy = self.add(
            "Lingua GmbH", phone="+49 30 1234567", website="lingua.test", priority="high", deal_value=Decimal("1500"),
            status="follow_up", call_at=early, last_contact_at=early, client=client,
        )
        self.lead.whatsapp_at = self.lead.call_at = timezone.now()
        self.lead.last_contact_at = timezone.now()
        self.lead.save()
        note = LeadNote.objects.create(lead=copy, text="called twice", by=self.sales)
        activity = LeadActivity.objects.create(lead=copy, kind=LeadActivity.Kind.CALL, by=self.sales, at=early)
        quote = Quotation.objects.create(lead=copy, owner=self.sales, source_lang="EN", target_lang="AR", quantity=1, rate=Decimal("80"), total=Decimal("80"))

        answer = self.remove(self.lead.pk, [copy.pk])
        self.assertEqual(answer.status_code, 200, answer.content)
        self.assertEqual(_json(answer)["removed"], 1)
        self.assertFalse(Lead.objects.filter(pk=copy.pk).exists())
        self.lead.refresh_from_db()
        for row in (note, activity, quote):
            row.refresh_from_db()
            self.assertEqual(row.lead_id, self.lead.pk)
        # An empty cell takes the copy's; a full one keeps its own; a number it lacked is added and matched on.
        self.assertEqual((self.lead.website, self.lead.priority, self.lead.deal_value), ("lingua.test", "high", Decimal("1500")))
        self.assertEqual((self.lead.email, self.lead.status), ("anna@lingua.test", "follow_up"))
        self.assertEqual(self.lead.phone, "+49301234567")
        self.assertIn(" 301234567 ", self.lead.phone_keys)
        self.assertEqual(self.lead.client_id, client.pk)
        # Both called: the first call is the copy's, earlier; the last contact is the row's own, later.
        self.assertEqual(self.lead.call_at, early)
        self.assertGreater(self.lead.last_contact_at, early)
        self.assertEqual(self.groups(), [])
        logged = AuditLog.objects.get(action="b2b.duplicates_merge")
        self.assertNotIn("Lingua", logged.detail + logged.target)

    def test_a_row_that_is_not_a_copy_is_refused_and_nothing_goes(self):
        copy = self.add("Lingua GmbH")
        stranger = self.add("Somebody else")
        answer = self.remove(self.lead.pk, [copy.pk, stranger.pk])
        self.assertEqual((answer.status_code, _json(answer)["error"]), (400, "not_duplicates"))
        self.assertEqual(Lead.objects.filter(pk__in=[copy.pk, stranger.pk]).count(), 2)
        # The row that stays named among the ones to go is not deleted; nothing else named is refused.
        self.assertEqual(_json(self.remove(self.lead.pk, [self.lead.pk]))["error"], "nothing")
        self.assertTrue(Lead.objects.filter(pk=self.lead.pk).exists())

    def test_a_copy_on_another_sheet_is_refused(self):
        other = LeadSheet.objects.create(title="Spain", assigned_to=self.sales, created_by=self.manager)
        there = self.add("Lingua GmbH", sheet=other)
        self.add("Lingua GmbH", sheet=other)
        answer = self.remove(self.lead.pk, [there.pk])
        self.assertEqual(_json(answer)["error"], "not_duplicates")
        self.assertTrue(Lead.objects.filter(pk=there.pk).exists())

    def test_who_may(self):
        copy = self.add("Lingua GmbH")
        # Another Sales person's sheet answers like one that is not there; the operation has no door.
        self.assertEqual(self.get(self.other, "v1_b2b_duplicates", self.sheet.pk).status_code, 404)
        self.assertEqual(self.remove(self.lead.pk, [copy.pk], user=self.other).status_code, 404)
        self.assertEqual(self.get(self.ops, "v1_b2b_duplicates", self.sheet.pk).status_code, 403)
        self.assertTrue(Lead.objects.filter(pk=copy.pk).exists())
        # The manager reads every sheet and may clean it.
        self.assertEqual(len(self.groups(user=self.manager)), 1)
        self.assertEqual(self.remove(self.lead.pk, [copy.pk], user=self.manager).status_code, 200)

    def test_a_bad_body(self):
        for body in ({"keep": "1", "remove": []}, {"keep": 1, "remove": "2"}, {"keep": 1, "remove": [True]}, {"keep": True, "remove": [2]}):
            answer = self.post(self.sales, "v1_b2b_duplicates_remove", body, self.sheet.pk)
            self.assertEqual(answer.status_code, 400, body)

    def test_join_numbers_stops_at_the_column(self):
        self.assertEqual(b2b._join_numbers("+201000000001", "+201000000001\n+201000000002", 250), "+201000000001\n+201000000002")
        self.assertEqual(b2b._join_numbers("+201000000001", "+201000000002", 14), "+201000000001")
