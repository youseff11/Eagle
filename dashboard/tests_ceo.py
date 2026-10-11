"""The CEO board (``ceo.py``, ``api_ceo.py``): the whole company for a period, for the owner only.

Held here: only the owner has the door; money in different currencies is never added together; a figure that needs what
nobody wrote (an exchange rate, a cost's price) or has nothing to measure is ``None``, never zero; cancelled invoices are not
revenue; the clients' names drawn are written down in the audit log.
"""

import json
from datetime import timedelta
from decimal import Decimal

from django.test import Client as DjangoClient
from django.urls import reverse
from django.utils import timezone


from .models import AuditLog, Invoice, InvoicePayment, Quotation, Task, TaskStatus
from .tests_finance import _Finance


def _json(response):
    return json.loads(response.content.decode("utf-8"))


class _Board(_Finance):
    def board(self, user=None, **period):
        browser = DjangoClient()
        browser.force_login(user or self.admin)
        today = timezone.localdate()
        period = period or {"from": (today - timedelta(days=10)).isoformat(), "to": today.isoformat()}
        return browser.get(reverse("dashboard:v1_admin_ceo"), period)

    def invoiced(self, rate=Decimal("50")):
        invoice = self.deliver()
        Invoice.objects.filter(pk=invoice.pk).update(egp_rate=rate)
        invoice.refresh_from_db()
        return invoice


class DoorTests(_Board):
    def test_the_owner_alone(self):
        self.assertEqual(reverse("dashboard:v1_admin_ceo"), "/api/v1/admin/ceo/")
        for user in (self.accounting, self.sales, self.manager, self.ops, self.tr):
            self.assertEqual(self.board(user).status_code, 403, user.username)
        self.assertEqual(self.board().status_code, 200)

    def test_a_bad_period_is_refused(self):
        self.assertEqual(_json(self.board(**{"from": "soon"}))["error"], "bad_period")


class MoneyTests(_Board):
    def test_revenue_costs_and_profit_in_egp(self):
        self.invoiced()
        money = _json(self.board())["money"]
        self.assertEqual(
            (money["invoiced"], money["revenue_egp"], money["costs_egp"], money["profit_egp"], money["margin"]),
            ({"USD": "80.00"}, "4000.00", "200.00", "3800.00", 95),
        )

    def test_a_missing_rate_or_cost_makes_it_not_measured(self):
        self.invoiced(rate=None)
        money = _json(self.board())["money"]
        self.assertEqual((money["revenue_egp"], money["profit_egp"], money["margin"]), (None, None, None))
        self.assertEqual(money["invoiced"], {"USD": "80.00"})

    def test_currencies_are_never_added_together_and_cancelled_is_not_revenue(self):
        self.invoiced()
        other = Task.objects.create(client=self.client_obj, title="b", created_by=self.ops, status=TaskStatus.DELIVERED)
        Invoice.objects.create(client=self.client_obj, task=other, amount=Decimal("100"), currency="EUR", egp_rate=Decimal("55"))
        Invoice.objects.create(client=self.client_obj, amount=Decimal("999"), currency="GBP", status=Invoice.Status.CANCELLED)
        money = _json(self.board())["money"]
        self.assertEqual(money["invoiced"], {"EUR": "100.00", "USD": "80.00"})
        self.assertEqual(money["invoices"], 2)

    def test_received_owed_and_overdue(self):
        invoice = self.invoiced()
        Invoice.objects.filter(pk=invoice.pk).update(status=Invoice.Status.PARTIAL, due_date=timezone.localdate() - timedelta(days=2))
        InvoicePayment.objects.create(invoice=invoice, amount=Decimal("30"))
        money = _json(self.board())["money"]
        self.assertEqual((money["received"], money["owed"], money["overdue"], money["overdue_count"]),
                         ({"USD": "30.00"}, {"USD": "50.00"}, {"USD": "50.00"}, 1))

    def test_by_project_and_by_client_with_the_name_written_down(self):
        invoice = self.invoiced()
        body = _json(self.board())
        self.assertEqual(body["by_project"][0]["invoice"], invoice.code)
        self.assertEqual((body["by_project"][0]["profit_egp"], body["by_project"][0]["margin"]), ("3800.00", 95))
        client = body["by_client"][0]
        self.assertEqual((client["code"], client["name"], client["revenue_egp"]), (self.client_obj.code, "Lingua GmbH", "4000.00"))
        self.assertTrue(AuditLog.objects.filter(actor=self.admin, action="client.identity.list", detail__contains="ceo board").exists())


class WorkTests(_Board):
    def test_nothing_to_measure_is_none_not_zero(self):
        projects = _json(self.board())["projects"]
        self.assertEqual((projects["delivered"], projects["rework_rate"], projects["review_score"]), (0, None, None))

    def test_running_late_delivered_rework_and_score(self):
        Task.objects.create(client=self.client_obj, title="late", created_by=self.ops, status=TaskStatus.IN_PROGRESS,
                            deadline=timezone.now() - timedelta(hours=1), translator=self.tr2)
        Task.objects.filter(pk=self.task.pk).update(revision_count=1, review_score=4)
        self.task.refresh_from_db()
        self.deliver()
        Task.objects.create(client=self.client_obj, title="clean", created_by=self.ops, status=TaskStatus.DELIVERED,
                            delivered_at=timezone.now(), review_score=5)
        projects = _json(self.board())["projects"]
        self.assertEqual(
            (projects["active"], projects["late"], projects["delivered"], projects["rework_rate"], projects["review_score"]),
            (1, 1, 2, 50, 4.5),
        )

    def test_the_busiest_translator_comes_first(self):
        Task.objects.create(client=self.client_obj, title="busy", created_by=self.ops, status=TaskStatus.IN_PROGRESS,
                            translator=self.tr2, word_count=700)
        workload = _json(self.board())["workload"]
        self.assertEqual((workload["translators"][0]["id"], workload["translators"][0]["tasks"], workload["translators"][0]["words"]), (self.tr2.pk, 1, 700))
        self.assertEqual(workload["free"], 1)


class SalesTests(_Board):
    def test_today_and_the_period_and_each_sales_person(self):
        Quotation.objects.filter(pk=self.quote.pk).update(decided_at=timezone.now())
        sales = _json(self.board())["sales"]
        self.assertEqual((sales["today"]["won"], sales["today"]["won_value"]), (1, {"USD": "80.00"}))
        self.assertIn(self.sales.pk, [row["person"]["id"] for row in sales["people"]])
        self.assertIn("quotes_accepted", sales["period"])


