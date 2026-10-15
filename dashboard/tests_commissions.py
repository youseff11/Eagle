"""Sales commissions (``commissions.py``, ``/api/v1/commissions/``), the owner's six decisions of 15/10/2026.

Held here: the rate is the line's, else the person's, else the company's; it is counted on the whole invoice; it is due only
when the invoice is paid in full; a split adds up to 100; the owner alone writes; approving writes the figures down; a
cancelled invoice cancels its lines; both teams; a Sales person reads their own, a manager their team's.
"""

import json
from datetime import timedelta
from decimal import Decimal

from django.db import connection
from django.test import Client as DjangoClient
from django.test import TestCase
from django.test.utils import CaptureQueriesContext
from django.urls import reverse
from django.utils import timezone

from . import commissions, finance
from .models import AppSettings, AuditLog, Client, Commission, Invoice, InvoicePayment, Role, SalesTrack, User


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
        self.invoice = self.make_invoice(self.b2b, Decimal("10000"), "USD", Decimal("50"))
        self.line = commissions.ensure_default(self.invoice)
        conf = AppSettings.load()
        conf.commission_rate = Decimal("5")
        conf.save()

    def make_invoice(self, owner, amount, currency="EGP", rate=Decimal("1")):
        return Invoice.objects.create(
            client=self.client_obj, owner=owner, amount=amount, currency=currency, egp_rate=rate, status=Invoice.Status.SENT,
            due_date=timezone.localdate() + timedelta(days=14),
        )

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


class DoorTests(_Commissions):
    def test_the_doors_are_under_api_v1(self):
        self.assertEqual(reverse("dashboard:v1_commissions"), "/api/v1/commissions/")
        self.assertEqual(reverse("dashboard:v1_commissions_rate"), "/api/v1/commissions/rate/")
        self.assertEqual(reverse("dashboard:v1_commissions_person_rate", args=[3]), "/api/v1/commissions/people/3/rate/")
        self.assertEqual(reverse("dashboard:v1_commissions_split", args=[3]), "/api/v1/commissions/invoices/3/split/")
        self.assertEqual(reverse("dashboard:v1_commissions_approve", args=[3]), "/api/v1/commissions/3/approve/")
        self.assertEqual(reverse("dashboard:v1_commissions_paid", args=[3]), "/api/v1/commissions/3/paid/")
        self.assertEqual(reverse("dashboard:v1_commissions_take_back", args=[3]), "/api/v1/commissions/3/take-back/")
        self.assertEqual(reverse("dashboard:v1_commissions_line_rate", args=[3]), "/api/v1/commissions/3/rate/")

    def test_who_reads_what(self):
        b2c_invoice = self.make_invoice(self.b2c, Decimal("2000"))
        commissions.ensure_default(b2c_invoice)
        ids = lambda user: {line["person"]["id"] for line in _json(self.get(user))["lines"]}
        self.assertEqual(ids(self.admin), {self.b2b.pk, self.b2c.pk})
        self.assertEqual(ids(self.b2b), {self.b2b.pk})
        self.assertEqual(ids(self.b2c), {self.b2c.pk})
        # A manager reads their own team's, not the other team's.
        self.assertEqual(ids(self.b2b_manager), {self.b2b.pk})
        self.assertEqual(ids(self.b2c_manager), {self.b2c.pk})
        for user in (self.ops, self.accounting):
            self.assertEqual(self.get(user).status_code, 403, user)

    def test_only_the_owner_sees_the_rates_and_writes(self):
        answer = _json(self.get(self.b2b))
        self.assertIsNone(answer["company_rate"])
        self.assertEqual(answer["people"], [])
        self.assertFalse(answer["can_manage"])
        self.pay(self.invoice)
        for user in (self.b2b, self.b2b_manager, self.accounting):
            self.assertEqual(self.post(user, "v1_commissions_approve", {}, self.line.pk).status_code, 403, user)
            self.assertEqual(self.post(user, "v1_commissions_rate", {"rate": "50"}).status_code, 403, user)
        self.line.refresh_from_db()
        self.assertEqual(self.line.status, Commission.Status.PENDING)

    def test_another_persons_line_is_a_404(self):
        b2c_line = commissions.ensure_default(self.make_invoice(self.b2c, Decimal("2000")))
        self.assertTrue(_json(self.get(self.b2b)))
        self.assertEqual(self.post(self.admin, "v1_commissions_approve", {}, 999999).status_code, 404)
        self.assertTrue(b2c_line)


class RateTests(_Commissions):
    def line_answer(self):
        return next(line for line in _json(self.get(self.admin))["lines"] if line["id"] == self.line.pk)

    def test_the_whole_invoice_at_the_company_rate(self):
        line = self.line_answer()
        # 5% of the whole 10,000 USD, and in pounds at the invoice's rate.
        self.assertEqual((line["rate"], line["amount"], line["currency"], line["amount_egp"]), ("5.00", "500.00", "USD", "25000.00"))
        self.assertFalse(line["own_rate"])

    def test_the_persons_rate_then_the_lines_own_win(self):
        self.assertTrue(_json(self.post(self.admin, "v1_commissions_person_rate", {"rate": "7"}, self.b2b.pk))["ok"])
        self.assertEqual(self.line_answer()["amount"], "700.00")
        self.assertTrue(_json(self.post(self.admin, "v1_commissions_line_rate", {"rate": "10"}, self.line.pk))["ok"])
        self.assertEqual(self.line_answer()["amount"], "1000.00")
        self.assertTrue(self.line_answer()["own_rate"])
        self.assertTrue(AuditLog.objects.filter(action="commission.person_rate").exists())

    def test_no_rate_is_not_a_zero(self):
        self.post(self.admin, "v1_commissions_rate", {"rate": ""})
        line = self.line_answer()
        self.assertEqual((line["rate"], line["amount"]), (None, None))
        self.pay(self.invoice)
        self.assertEqual(_json(self.post(self.admin, "v1_commissions_approve", {}, self.line.pk))["error"], "no_rate")

    def test_a_rate_is_a_percent(self):
        for bad in ("101", "-1", "abc", "5.555"):
            self.assertEqual(_json(self.post(self.admin, "v1_commissions_rate", {"rate": bad}))["error"], "bad_rate", bad)


class DueTests(_Commissions):
    def approve(self, note=""):
        return _json(self.post(self.admin, "v1_commissions_approve", {"note": note}, self.line.pk))

    def test_due_only_when_the_invoice_is_paid_in_full(self):
        self.assertEqual(self.approve()["error"], "not_paid")
        self.pay(self.invoice, Decimal("4000"))
        self.assertEqual(self.invoice.status, Invoice.Status.PARTIAL)
        self.assertEqual(self.approve()["error"], "not_paid")
        self.pay(self.invoice, Decimal("6000"))
        answer = self.approve()
        self.assertEqual(answer["line"]["status"], "approved")

    def test_approving_writes_the_figures_down(self):
        self.pay(self.invoice)
        self.approve()
        self.post(self.admin, "v1_commissions_rate", {"rate": "20"})
        self.line.refresh_from_db()
        self.assertEqual((self.line.rate, self.line.amount, self.line.amount_egp), (Decimal("5.00"), Decimal("500.00"), Decimal("25000.00")))
        line = next(one for one in _json(self.get(self.admin))["lines"] if one["id"] == self.line.pk)
        self.assertEqual(line["amount"], "500.00")

    def test_paid_after_approved_and_the_person_is_told(self):
        self.assertEqual(_json(self.post(self.admin, "v1_commissions_paid", {}, self.line.pk))["error"], "not_approved")
        self.pay(self.invoice)
        self.approve()
        answer = _json(self.post(self.admin, "v1_commissions_paid", {}, self.line.pk))
        self.assertEqual(answer["line"]["status"], "paid")
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
        self.assertEqual(answer["line"]["status"], "pending")
        self.line.refresh_from_db()
        self.assertIsNone(self.line.amount)

    def test_the_totals_by_where_they_stand(self):
        totals = _json(self.get(self.admin))["totals"]
        self.assertEqual((totals["waiting"], totals["due"]), ("25000.00", "0.00"))
        self.pay(self.invoice)
        self.assertEqual(_json(self.get(self.admin))["totals"]["due"], "25000.00")
        self.approve()
        self.assertEqual(_json(self.get(self.admin))["totals"]["approved"], "25000.00")


class SplitTests(_Commissions):
    def split(self, shares):
        return _json(self.post(self.admin, "v1_commissions_split", {"shares": shares}, self.invoice.pk))

    def test_a_split_adds_up_to_100(self):
        self.assertEqual(self.split([{"person": self.b2b.pk, "share": "60"}, {"person": self.b2c.pk, "share": "30"}])["error"], "not_whole")
        answer = self.split([{"person": self.b2b.pk, "share": "60"}, {"person": self.b2c.pk, "share": "40"}])
        amounts = {line["person"]["id"]: line["amount"] for line in answer["lines"]}
        self.assertEqual(amounts, {self.b2b.pk: "300.00", self.b2c.pk: "200.00"})

    def test_only_sales_people_once_each(self):
        self.assertEqual(self.split([{"person": self.ops.pk, "share": "100"}])["error"], "not_sales")
        answer = self.split([{"person": self.b2b.pk, "share": "50"}, {"person": self.b2b.pk, "share": "50"}])
        self.assertEqual(answer["error"], "twice")

    def test_no_split_after_an_approval(self):
        self.pay(self.invoice)
        commissions.approve(self.admin, self.line)
        self.assertEqual(self.split([{"person": self.b2c.pk, "share": "100"}])["error"], "decided")

    def test_an_invoice_with_no_sales_person_is_offered_and_split(self):
        hand = Invoice.objects.create(client=self.client_obj, amount=Decimal("100"), currency="EGP", egp_rate=Decimal("1"))
        self.assertIn(hand.pk, [one["id"] for one in _json(self.get(self.admin))["uncovered"]])
        answer = _json(self.post(self.admin, "v1_commissions_split", {"shares": [{"person": self.b2c.pk, "share": "100"}]}, hand.pk))
        self.assertTrue(answer["ok"])
        self.assertNotIn(hand.pk, [one["id"] for one in _json(self.get(self.admin))["uncovered"]])


class InvoiceHookTests(_Commissions):
    def test_one_line_per_person_per_invoice(self):
        self.assertIsNone(commissions.ensure_default(self.invoice))
        self.assertEqual(Commission.objects.filter(invoice=self.invoice).count(), 1)

    def test_a_cancelled_invoice_cancels_its_lines(self):
        finance.cancel_invoice(self.invoice, self.accounting)
        self.line.refresh_from_db()
        self.assertEqual(self.line.status, Commission.Status.CANCELLED)
        self.assertNotIn(self.invoice.pk, [one["id"] for one in _json(self.get(self.admin))["uncovered"]])

    def test_the_locks_join_nothing(self):
        self.pay(self.invoice)
        with CaptureQueriesContext(connection) as seen:
            commissions.approve(self.admin, self.line)
            commissions.mark_paid(self.admin, self.line)
        locked = [one["sql"] for one in seen.captured_queries if 'FROM "dashboard_commission"' in one["sql"] and one["sql"].startswith("SELECT")]
        self.assertTrue(locked)
        for sql in locked:
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

    def test_a_split_is_for_sales_people_whoever_calls(self):
        with self.assertRaises(commissions.Refused) as refused:
            commissions.set_split(self.admin, self.invoice, [(self.ops, Decimal("100"))])
        self.assertEqual(refused.exception.code, "not_sales")

    def test_an_approved_line_keeps_its_pounds_when_the_exchange_rate_moves(self):
        self.pay(self.invoice)
        commissions.approve(self.admin, self.line)
        Invoice.objects.filter(pk=self.invoice.pk).update(egp_rate=Decimal("60"))
        line = next(one for one in _json(self.get(self.admin))["lines"] if one["id"] == self.line.pk)
        self.assertEqual(line["amount_egp"], "25000.00")
