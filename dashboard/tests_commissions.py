"""Sales commissions per deal (``commissions.py``, ``/api/v1/commissions/``): the owner's decisions of 15/10/2026 and his
change of 21/10/2026.

Held here: a company moved to «تم التعاقد» is a deal on the page by itself, with its details and the one who closed it; its
value starts from the accepted quotation, else the row's deal value, and the owner corrects it; each person on a deal has
their own percent of the value (the line's, else the person's, else the company's); it is due only when the deal's invoice
is paid in full; the owner alone writes; approving writes the figures down; a cancelled invoice leaves the deal; both
teams; a Sales person reads their own lines, a manager their team's.
"""

import json
from datetime import timedelta
from decimal import Decimal
from unittest import mock

from django.db import connection
from django.test import Client as DjangoClient
from django.test import TestCase
from django.test.utils import CaptureQueriesContext
from django.urls import reverse
from django.utils import timezone

from . import b2b, commissions, finance
from .models import (
    AppSettings, AuditLog, Client, Commission, Deal, Invoice, InvoicePayment, Lead, LeadSheet, LeadStatus, Market, Quotation,
    Role, SalesTrack, User,
)


def _json(response):
    return json.loads(response.content.decode("utf-8"))


class _Commissions(TestCase):
    def setUp(self):
        make = lambda name, role, **kw: User.objects.create_user(name, password="pw", role=role, first_name=name.title(), **kw)
        self.admin = make("owner", Role.ADMIN)
        self.accounting = make("acc", Role.ACCOUNTING)
        self.b2b = make("abroad", Role.SALES)
        self.b2b_manager = make("b2bboss", Role.SALES, is_sales_manager=True)
        self.b2c = make("walker", Role.SALES, sales_track=SalesTrack.B2C_FIELD)
        self.b2c_manager = make("b2cboss", Role.SALES, is_sales_manager=True, sales_track=SalesTrack.B2C_ONLINE)
        self.ops = make("ops", Role.OPERATION)
        self.client_obj = Client.objects.create(name="Anna", company="Lingua GmbH", email="anna@lingua.test")
        self.sheet = LeadSheet.objects.create(title="Germany", assigned_to=self.b2b, created_by=self.b2b_manager)
        self.lead = Lead.objects.create(
            sheet=self.sheet, company_name="Lingua GmbH", contact_person="Anna", country="Germany", services="Legal",
            client=self.client_obj,
        )
        conf = AppSettings.load()
        conf.commission_rate = Decimal("5")
        conf.save()
        # The deal of the setup: an accepted quotation of 10,000 USD, its invoice at 50 pounds a dollar.
        self.quote = self.make_quote(self.lead, Decimal("10000"), "USD")
        self.deal = self.win(self.lead, self.b2b)
        self.line = self.deal.lines.get()
        self.invoice = self.make_invoice(self.b2b, Decimal("10000"), "USD", Decimal("50"), quote=self.quote)
        commissions.deal_for_invoice(self.invoice)
        self.deal.refresh_from_db()

    def make_quote(self, lead, total, currency="USD"):
        return Quotation.objects.create(
            lead=lead, owner=lead.sheet.assigned_to, created_by=lead.sheet.assigned_to, source_lang="German",
            target_lang="Arabic", quantity=1000, rate=total / 1000, total=total, currency=currency,
            status=Quotation.Status.ACCEPTED, decided_at=timezone.now(),
        )

    def win(self, lead, by):
        before = lead.status
        lead.status = LeadStatus.WON
        lead.save()
        b2b.note_status(lead, before, LeadStatus.WON, by)
        return Deal.objects.get(lead=lead, status=Deal.Status.OPEN)

    def make_invoice(self, owner, amount, currency="EGP", rate=Decimal("1"), quote=None):
        return Invoice.objects.create(
            client=self.client_obj, owner=owner, amount=amount, currency=currency, egp_rate=rate, status=Invoice.Status.SENT,
            due_date=timezone.localdate() + timedelta(days=14), quotation=quote,
        )

    def b2c_deal(self, value="2000"):
        sheet = LeadSheet.objects.create(title="Cairo", assigned_to=self.b2c, market=Market.B2C)
        lead = Lead.objects.create(sheet=sheet, company_name="Nile Co", deal_value=Decimal(value), governorate="Cairo")
        return self.win(lead, self.b2c)

    def pay(self, invoice, amount=None):
        finance.record_payment(invoice, self.accounting, amount or invoice.amount, timezone.localdate())
        invoice.refresh_from_db()

    def browser(self, user):
        browser = DjangoClient()
        browser.force_login(user)
        return browser

    def get(self, user, **query):
        return self.browser(user).get(reverse("dashboard:v1_commissions"), query)

    def post(self, user, name, body, *args):
        return self.browser(user).post(reverse(f"dashboard:{name}", args=args), json.dumps(body), content_type="application/json")

    def deal_answer(self, deal=None, user=None):
        deal = deal or self.deal
        return next(one for one in _json(self.get(user or self.admin))["deals"] if one["id"] == deal.pk)

    def line_answer(self, line=None):
        line = line or self.line
        return next(one for one in self.deal_answer(line.deal)["lines"] if one["id"] == line.pk)

    def set_deal(self, body, deal=None):
        return _json(self.post(self.admin, "v1_commissions_deal", body, (deal or self.deal).pk))


class DoorTests(_Commissions):
    def test_the_doors_are_under_api_v1(self):
        self.assertEqual(reverse("dashboard:v1_commissions"), "/api/v1/commissions/")
        self.assertEqual(reverse("dashboard:v1_commissions_rate"), "/api/v1/commissions/rate/")
        self.assertEqual(reverse("dashboard:v1_commissions_person_rate", args=[3]), "/api/v1/commissions/people/3/rate/")
        self.assertEqual(reverse("dashboard:v1_commissions_deal", args=[3]), "/api/v1/commissions/deals/3/")
        self.assertEqual(reverse("dashboard:v1_commissions_deal_cancel", args=[3]), "/api/v1/commissions/deals/3/cancel/")
        self.assertEqual(reverse("dashboard:v1_commissions_invoice_deal", args=[3]), "/api/v1/commissions/invoices/3/deal/")
        self.assertEqual(reverse("dashboard:v1_commissions_approve", args=[3]), "/api/v1/commissions/3/approve/")
        self.assertEqual(reverse("dashboard:v1_commissions_paid", args=[3]), "/api/v1/commissions/3/paid/")
        self.assertEqual(reverse("dashboard:v1_commissions_take_back", args=[3]), "/api/v1/commissions/3/take-back/")

    def test_who_reads_what(self):
        self.b2c_deal()
        ids = lambda user: {line["person"]["id"] for deal in _json(self.get(user))["deals"] for line in deal["lines"]}
        self.assertEqual(ids(self.admin), {self.b2b.pk, self.b2c.pk})
        self.assertEqual(ids(self.b2b), {self.b2b.pk})
        self.assertEqual(ids(self.b2c), {self.b2c.pk})
        # A manager reads their own team's, not the other team's.
        self.assertEqual(ids(self.b2b_manager), {self.b2b.pk})
        self.assertEqual(ids(self.b2c_manager), {self.b2c.pk})
        for user in (self.ops, self.accounting):
            self.assertEqual(self.get(user).status_code, 403, user)

    def test_a_sales_person_reads_their_own_line_of_a_shared_deal(self):
        self.set_deal({"people": [{"person": self.b2b.pk, "rate": "6"}, {"person": self.b2c.pk, "rate": "4"}]})
        mine = self.deal_answer(user=self.b2c)
        self.assertEqual([line["person"]["id"] for line in mine["lines"]], [self.b2c.pk])
        self.assertEqual(len(self.deal_answer()["lines"]), 2)

    def test_only_the_owner_sees_the_rates_and_writes(self):
        answer = _json(self.get(self.b2b))
        self.assertIsNone(answer["company_rate"])
        self.assertEqual((answer["people"], answer["uncovered"]), ([], []))
        self.assertFalse(answer["can_manage"])
        self.pay(self.invoice)
        for user in (self.b2b, self.b2b_manager, self.accounting):
            self.assertEqual(self.post(user, "v1_commissions_approve", {}, self.line.pk).status_code, 403, user)
            self.assertEqual(self.post(user, "v1_commissions_rate", {"rate": "50"}).status_code, 403, user)
            self.assertEqual(self.post(user, "v1_commissions_deal", {"value": "1"}, self.deal.pk).status_code, 403, user)
            self.assertEqual(self.post(user, "v1_commissions_deal_cancel", {}, self.deal.pk).status_code, 403, user)
        self.line.refresh_from_db()
        self.deal.refresh_from_db()
        self.assertEqual((self.line.status, self.deal.value, self.deal.status), (Commission.Status.PENDING, Decimal("10000"), "open"))

    def test_an_unknown_line_or_deal_is_a_404(self):
        self.assertEqual(self.post(self.admin, "v1_commissions_approve", {}, 999999).status_code, 404)
        self.assertEqual(self.post(self.admin, "v1_commissions_deal", {"value": "5"}, 999999).status_code, 404)


class DealTests(_Commissions):
    def test_a_company_moved_to_contracted_is_a_deal_with_its_details(self):
        deal = self.deal_answer()
        self.assertEqual((deal["code"], deal["market"], deal["owner"]["id"]), (self.deal.code, "b2b", self.b2b.pk))
        self.assertEqual((deal["value"], deal["currency"], deal["value_by_hand"]), ("10000.00", "USD", False))
        self.assertEqual(deal["company"]["name"], "Lingua GmbH")
        self.assertEqual((deal["company"]["contact_person"], deal["company"]["country"], deal["company"]["services"]), ("Anna", "Germany", "Legal"))
        self.assertEqual((deal["quotation"]["code"], deal["quotation"]["total"]), (self.quote.code, "10000.00"))
        self.assertEqual(deal["invoice"]["code"], self.invoice.code)
        # The one who closed it has the line, at the company's rate.
        self.assertEqual([(line["person"]["id"], line["rate"], line["own_rate"]) for line in deal["lines"]], [(self.b2b.pk, "5.00", False)])
        self.assertTrue(self.admin.notifications.filter(title_ar="صفقة جديدة").exists())
        self.assertTrue(AuditLog.objects.filter(action="commission.deal", target=self.deal.code).exists())

    def test_the_cell_door_makes_the_deal(self):
        other = Lead.objects.create(sheet=self.sheet, company_name="Second GmbH", deal_value=Decimal("3000"))
        answer = _json(self.post(self.b2b, "v1_b2b_lead_save", {"status": "won"}, other.pk))
        self.assertTrue(answer["won_now"])
        deal = Deal.objects.get(lead=other)
        # No quotation: the row's deal value, in pounds.
        self.assertEqual((deal.value, deal.currency, deal.owner_id), (Decimal("3000.00"), "EGP", self.b2b.pk))

    def test_an_accepted_quotation_makes_the_deal(self):
        other = Lead.objects.create(sheet=self.sheet, company_name="Third GmbH")
        quote = self.make_quote(other, Decimal("800"), "EUR")
        Quotation.objects.filter(pk=quote.pk).update(status=Quotation.Status.SENT)
        self.assertTrue(_json(self.post(self.b2b, "v1_b2b_quotation_decide", {"accepted": True}, quote.pk))["ok"])
        deal = Deal.objects.get(lead=other)
        self.assertEqual((deal.value, deal.currency, deal.quotation_id), (Decimal("800.00"), "EUR", quote.pk))

    def test_one_open_deal_a_company(self):
        b2b.note_status(self.lead, LeadStatus.CONTACTED, LeadStatus.WON, self.b2b)
        self.assertEqual(Deal.objects.filter(lead=self.lead).count(), 1)
        # Cancelled by the owner (moved by mistake) and moved again: a new deal.
        commissions.cancel_deal(self.admin, self.deal)
        b2b.note_status(self.lead, LeadStatus.CONTACTED, LeadStatus.WON, self.b2b)
        self.assertEqual(Deal.objects.filter(lead=self.lead, status="open").count(), 1)

    def test_a_deal_that_fails_does_not_stop_the_move(self):
        other = Lead.objects.create(sheet=self.sheet, company_name="Broken GmbH")
        with mock.patch.object(commissions, "_deal_from_lead", side_effect=ZeroDivisionError),                 mock.patch.object(commissions.logger, "exception") as written:
            answer = _json(self.post(self.b2b, "v1_b2b_lead_save", {"status": "won"}, other.pk))
        self.assertEqual(answer["lead"]["status"], "won")
        self.assertTrue(written.called)
        self.assertFalse(Deal.objects.filter(lead=other).exists())

    def test_no_value_known_is_not_a_zero(self):
        other = Lead.objects.create(sheet=self.sheet, company_name="Empty GmbH")
        deal = self.win(other, self.b2b)
        answer = self.deal_answer(deal)
        self.assertEqual((answer["value"], answer["lines"][0]["amount"]), (None, None))

    def test_the_owner_corrects_the_value_and_the_invoice_keeps_it(self):
        other = Lead.objects.create(sheet=self.sheet, company_name="Fourth GmbH")
        quote = self.make_quote(other, Decimal("500"), "USD")
        deal = self.win(other, self.b2b)
        self.assertTrue(self.set_deal({"value": "450", "currency": "USD"}, deal)["ok"])
        invoice = self.make_invoice(self.b2b, Decimal("500"), "USD", Decimal("50"), quote=quote)
        commissions.deal_for_invoice(invoice)
        deal.refresh_from_db()
        self.assertEqual((deal.value, deal.value_by_hand, deal.invoice_id), (Decimal("450.00"), True, invoice.pk))

    def test_the_invoice_fills_a_value_nobody_wrote(self):
        other = Lead.objects.create(sheet=self.sheet, company_name="Fifth GmbH")
        quote = self.make_quote(other, Decimal("500"), "USD")
        deal = self.win(other, self.b2b)
        invoice = self.make_invoice(self.b2b, Decimal("520"), "USD", Decimal("50"), quote=quote)
        commissions.deal_for_invoice(invoice)
        deal.refresh_from_db()
        self.assertEqual((deal.value, deal.invoice_id), (Decimal("520.00"), invoice.pk))

    def test_a_bad_value_or_currency(self):
        for bad in ("0", "-5", "abc", "1.555"):
            self.assertEqual(self.set_deal({"value": bad})["error"], "bad_value", bad)
        self.assertEqual(self.set_deal({"currency": "XYZ"})["error"], "bad_currency")

    def test_cancelling_a_deal(self):
        answer = _json(self.post(self.admin, "v1_commissions_deal_cancel", {}, self.deal.pk))
        self.assertEqual((answer["deal"]["status"], answer["deal"]["stage"]), ("cancelled", "cancelled"))
        self.line.refresh_from_db()
        self.assertEqual(self.line.status, Commission.Status.CANCELLED)
        self.assertEqual(self.set_deal({"value": "5"})["error"], "cancelled")


class RateTests(_Commissions):
    def test_the_deal_value_at_the_company_rate(self):
        line = self.line_answer()
        # 5% of the whole 10,000 USD, and in pounds at the invoice's rate.
        self.assertEqual((line["rate"], line["amount"], line["currency"], line["amount_egp"]), ("5.00", "500.00", "USD", "25000.00"))
        self.assertFalse(line["own_rate"])

    def test_the_persons_rate_then_the_lines_own_win(self):
        self.assertTrue(_json(self.post(self.admin, "v1_commissions_person_rate", {"rate": "7"}, self.b2b.pk))["ok"])
        self.assertEqual(self.line_answer()["amount"], "700.00")
        self.assertTrue(self.set_deal({"people": [{"person": self.b2b.pk, "rate": "10"}]})["ok"])
        self.assertEqual(self.line_answer()["amount"], "1000.00")
        self.assertTrue(self.line_answer()["own_rate"])
        self.assertTrue(AuditLog.objects.filter(action="commission.person_rate").exists())
        self.assertTrue(AuditLog.objects.filter(action="commission.deal_set", target=self.deal.code).exists())

    def test_no_rate_is_not_a_zero(self):
        self.post(self.admin, "v1_commissions_rate", {"rate": ""})
        line = self.line_answer()
        self.assertEqual((line["rate"], line["amount"]), (None, None))
        self.pay(self.invoice)
        self.assertEqual(_json(self.post(self.admin, "v1_commissions_approve", {}, self.line.pk))["error"], "no_rate")

    def test_a_rate_is_a_percent(self):
        for bad in ("101", "-1", "abc", "5.555"):
            self.assertEqual(_json(self.post(self.admin, "v1_commissions_rate", {"rate": bad}))["error"], "bad_rate", bad)
            self.assertEqual(self.set_deal({"people": [{"person": self.b2b.pk, "rate": bad}]})["error"], "bad_rate", bad)

    def test_a_pound_deal_needs_no_exchange_rate(self):
        line = self.b2c_deal("2000").lines.get()
        answer = self.line_answer(line)
        self.assertEqual((answer["amount"], answer["currency"], answer["amount_egp"]), ("100.00", "EGP", "100.00"))


class PeopleTests(_Commissions):
    def test_several_people_each_their_own_percent(self):
        answer = self.set_deal({"people": [{"person": self.b2b.pk, "rate": "6"}, {"person": self.b2c.pk, "rate": "2.5"}]})
        amounts = {line["person"]["id"]: line["amount"] for line in answer["deal"]["lines"]}
        # Each one's percent of the whole 10,000: no split of one rate.
        self.assertEqual(amounts, {self.b2b.pk: "600.00", self.b2c.pk: "250.00"})

    def test_a_person_taken_off_loses_the_line(self):
        self.set_deal({"people": [{"person": self.b2b.pk, "rate": "6"}, {"person": self.b2c.pk, "rate": "4"}]})
        self.set_deal({"people": [{"person": self.b2c.pk, "rate": "4"}]})
        self.assertEqual(list(self.deal.lines.values_list("person_id", flat=True)), [self.b2c.pk])
        self.assertNotIn(self.deal.pk, [one["id"] for one in _json(self.get(self.b2b))["deals"]])

    def test_only_sales_people_once_each_and_not_over_the_whole(self):
        self.assertEqual(self.set_deal({"people": [{"person": self.ops.pk, "rate": "5"}]})["error"], "not_sales")
        self.assertEqual(self.set_deal({"people": [{"person": self.b2b.pk}, {"person": self.b2b.pk}]})["error"], "twice")
        self.assertEqual(self.set_deal({"people": []})["error"], "no_people")
        over = [{"person": self.b2b.pk, "rate": "60"}, {"person": self.b2c.pk, "rate": "50"}]
        self.assertEqual(self.set_deal({"people": over})["error"], "over_whole")
        self.assertEqual(list(self.deal.lines.values_list("person_id", flat=True)), [self.b2b.pk])

    def test_nothing_changes_after_an_approval(self):
        self.pay(self.invoice)
        commissions.approve(self.admin, self.line)
        self.assertEqual(self.set_deal({"people": [{"person": self.b2c.pk, "rate": "5"}]})["error"], "decided")
        self.assertEqual(self.set_deal({"value": "1"})["error"], "decided")
        self.assertEqual(_json(self.post(self.admin, "v1_commissions_deal_cancel", {}, self.deal.pk))["error"], "decided")


class DueTests(_Commissions):
    def approve(self, note=""):
        return _json(self.post(self.admin, "v1_commissions_approve", {"note": note}, self.line.pk))

    def test_due_only_when_the_invoice_is_paid_in_full(self):
        self.assertEqual(self.approve()["error"], "not_paid")
        self.pay(self.invoice, Decimal("4000"))
        self.assertEqual(self.invoice.status, Invoice.Status.PARTIAL)
        self.assertEqual(self.approve()["error"], "not_paid")
        self.assertEqual(self.deal_answer()["stage"], "waiting")
        self.pay(self.invoice, Decimal("6000"))
        self.assertEqual(self.deal_answer()["stage"], "due")
        answer = self.approve()
        self.assertEqual(answer["deal"]["lines"][0]["status"], "approved")
        self.assertEqual(answer["deal"]["stage"], "approved")

    def test_a_deal_with_no_invoice_is_not_due(self):
        deal = self.b2c_deal()
        answer = _json(self.post(self.admin, "v1_commissions_approve", {}, deal.lines.get().pk))
        self.assertEqual(answer["error"], "no_invoice")

    def test_the_owner_links_the_invoice(self):
        deal = self.b2c_deal()
        hand = self.make_invoice(None, Decimal("2000"))
        self.assertIn(hand.pk, [one["id"] for one in _json(self.get(self.admin))["uncovered"]])
        # An invoice on another deal is not taken.
        self.assertEqual(self.set_deal({"invoice": self.invoice.pk}, deal)["error"], "invoice_taken")
        self.assertTrue(self.set_deal({"invoice": hand.pk}, deal)["ok"])
        self.assertNotIn(hand.pk, [one["id"] for one in _json(self.get(self.admin))["uncovered"]])
        self.pay(hand)
        self.assertEqual(_json(self.post(self.admin, "v1_commissions_approve", {}, deal.lines.get().pk))["deal"]["stage"], "approved")

    def test_approving_writes_the_figures_down(self):
        self.pay(self.invoice)
        self.approve()
        self.post(self.admin, "v1_commissions_rate", {"rate": "20"})
        self.line.refresh_from_db()
        self.assertEqual((self.line.rate, self.line.base, self.line.amount, self.line.amount_egp), (Decimal("5.00"), Decimal("10000.00"), Decimal("500.00"), Decimal("25000.00")))
        self.assertEqual(self.line_answer()["amount"], "500.00")

    def test_paid_after_approved_and_the_person_is_told(self):
        self.assertEqual(_json(self.post(self.admin, "v1_commissions_paid", {}, self.line.pk))["error"], "not_approved")
        self.pay(self.invoice)
        self.approve()
        answer = _json(self.post(self.admin, "v1_commissions_paid", {}, self.line.pk))
        self.assertEqual((answer["deal"]["lines"][0]["status"], answer["deal"]["stage"]), ("paid", "paid"))
        self.assertTrue(self.b2b.notifications.filter(title_ar="عمولة اتصرفت").exists())
        # A paid line is not taken back.
        self.assertEqual(_json(self.post(self.admin, "v1_commissions_take_back", {}, self.line.pk))["error"], "not_approved")

    def test_a_payment_removed_stops_the_payout(self):
        self.pay(self.invoice)
        self.approve()
        finance.delete_payment(InvoicePayment.objects.get(invoice=self.invoice), self.accounting)
        self.assertEqual(_json(self.post(self.admin, "v1_commissions_paid", {}, self.line.pk))["error"], "not_paid")

    def test_taking_back_an_approval(self):
        self.pay(self.invoice)
        self.approve()
        answer = _json(self.post(self.admin, "v1_commissions_take_back", {}, self.line.pk))
        self.assertEqual(answer["deal"]["lines"][0]["status"], "pending")
        self.line.refresh_from_db()
        self.assertIsNone(self.line.amount)

    def test_the_totals_by_where_they_stand(self):
        totals = _json(self.get(self.admin))["totals"]
        self.assertEqual((totals["waiting"], totals["due"]), ("25000.00", "0.00"))
        self.pay(self.invoice)
        self.assertEqual(_json(self.get(self.admin))["totals"]["due"], "25000.00")
        self.approve()
        self.assertEqual(_json(self.get(self.admin))["totals"]["approved"], "25000.00")

    def test_the_stage_filter(self):
        self.b2c_deal()
        self.pay(self.invoice)
        codes = lambda stage: [one["code"] for one in _json(self.get(self.admin, stage=stage))["deals"]]
        self.assertEqual(codes("due"), [self.deal.code])
        self.assertEqual(len(codes("waiting")), 1)
        self.assertEqual(len(codes("")), 2)


class InvoiceHookTests(_Commissions):
    def test_a_cancelled_invoice_leaves_the_deal(self):
        finance.cancel_invoice(self.invoice, self.accounting)
        self.deal.refresh_from_db()
        self.line.refresh_from_db()
        self.assertIsNone(self.deal.invoice_id)
        self.assertEqual((self.deal.status, self.line.status), ("open", Commission.Status.PENDING))
        self.assertNotIn(self.invoice.pk, [one["id"] for one in _json(self.get(self.admin))["uncovered"]])

    def test_an_invoice_with_no_deal_becomes_one(self):
        hand = self.make_invoice(None, Decimal("100"))
        answer = _json(self.post(self.admin, "v1_commissions_invoice_deal", {}, hand.pk))
        self.assertEqual((answer["deal"]["value"], answer["deal"]["invoice"]["id"], answer["deal"]["lines"]), ("100.00", hand.pk, []))
        self.assertEqual(_json(self.post(self.admin, "v1_commissions_invoice_deal", {}, hand.pk))["error"], "has_deal")

    def test_an_invoice_of_a_sales_person_with_no_deal_gets_one(self):
        invoice = self.make_invoice(self.b2c, Decimal("700"))
        deal = commissions.deal_for_invoice(invoice)
        self.assertEqual((deal.value, deal.owner_id, list(deal.lines.values_list("person_id", flat=True))), (Decimal("700.00"), self.b2c.pk, [self.b2c.pk]))

    def test_the_locks_join_nothing(self):
        # Postgres refuses FOR UPDATE on an outer join, and SQLite drops the lock: the shape is held here (LockedRowTests).
        selects = lambda seen, table: [
            one["sql"] for one in seen.captured_queries if f'FROM "{table}"' in one["sql"] and one["sql"].startswith("SELECT")
        ]
        self.pay(self.invoice)
        with CaptureQueriesContext(connection) as seen:
            commissions.approve(self.admin, self.line)
            commissions.mark_paid(self.admin, self.line)
        self.assertTrue(selects(seen, "dashboard_commission"))
        for sql in selects(seen, "dashboard_commission"):
            self.assertNotIn("JOIN", sql)
        other = self.b2c_deal()
        with CaptureQueriesContext(connection) as seen:
            commissions.set_deal(self.admin, other, value="10")
            commissions.cancel_deal(self.admin, other)
        self.assertTrue(selects(seen, "dashboard_deal"))
        for sql in selects(seen, "dashboard_deal"):
            self.assertNotIn("JOIN", sql)


class RuleTests(_Commissions):
    """The rules hold by themselves, whatever door calls them."""

    def test_only_the_owner_whoever_calls(self):
        self.pay(self.invoice)
        for user in (self.b2b, self.b2b_manager, self.accounting):
            with self.assertRaises(commissions.Refused):
                commissions.approve(user, self.line)
            with self.assertRaises(commissions.Refused):
                commissions.set_company_rate(user, "50")
            with self.assertRaises(commissions.Refused):
                commissions.set_deal(user, self.deal, value="1")

    def test_people_are_sales_people_whoever_calls(self):
        with self.assertRaises(commissions.Refused) as refused:
            commissions.set_deal(self.admin, self.deal, people=[(self.ops, "5")])
        self.assertEqual(refused.exception.code, "not_sales")

    def test_an_approved_line_keeps_its_pounds_when_the_exchange_rate_moves(self):
        self.pay(self.invoice)
        commissions.approve(self.admin, self.line)
        Invoice.objects.filter(pk=self.invoice.pk).update(egp_rate=Decimal("60"))
        self.assertEqual(self.line_answer()["amount_egp"], "25000.00")
