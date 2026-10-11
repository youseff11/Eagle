"""Finance (``finance.py``, ``api_finance.py``): client invoices, their payments, and what a project cost and earned.

Held here:

* a task made from an accepted quotation drafts its invoice by itself when it is delivered, at the quotation's price, and
  prices its translators at their agreed price of 250 words (kept as it was that day); Accounting and the owner are told,
  with the client's code and never the name;
* only Accounting and the owner have a door; the Sales person sees where the invoice stands from the quotation, nothing of
  the costs;
* an invoice is sent once, by e-mail from the company mailbox, the answer going to the Sales person who sold it; it is not
  put in the client's conversation (the operation reads the company line);
* payments turn it partly paid and paid, never past what is owed; overdue is told once;
* profit is "not measured" (``None``) until everything it needs is known: the exchange rate, every cost.
"""

import json
from datetime import timedelta
from decimal import Decimal
from unittest import mock

from django.test import Client as DjangoClient
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from . import finance, mailer, services
from .forms import StaffEditForm
from .models import (
    Assignment, AssignmentStatus, AuditLog, Client, Invoice, Lead, LeadSheet, Notification, OutboundMessage, ProjectCost,
    Quotation, Role, Task, TaskStatus, User,
)


def _json(response):
    return json.loads(response.content.decode("utf-8"))


class _Finance(TestCase):
    def setUp(self):
        make = lambda name, role, **kw: User.objects.create_user(name, password="pw", role=role, first_name=name.title(), **kw)
        self.admin = make("owner", Role.ADMIN)
        self.accounting = make("acc", Role.ACCOUNTING)
        self.sales = make("seller", Role.SALES, mail_alias="seller@eagle.test")
        self.manager = make("manager", Role.SALES, is_sales_manager=True)
        self.ops = make("ops", Role.OPERATION)
        self.tr = make("tr", Role.TRANSLATOR, cost_per_250=Decimal("50"))
        self.tr2 = make("tr2", Role.TRANSLATOR)
        self.client_obj = Client.objects.create(name="Anna Schmidt", company="Lingua GmbH", email="anna@lingua.test", phone="+447700900123")
        sheet = LeadSheet.objects.create(title="Germany", assigned_to=self.sales, created_by=self.manager)
        self.lead = Lead.objects.create(sheet=sheet, company_name="Lingua GmbH", contact_person="Anna Schmidt",
                                        email="anna@lingua.test", client=self.client_obj)
        self.task = Task.objects.create(client=self.client_obj, title="QT job", created_by=self.ops, word_count=1000,
                                        translator=self.tr, status=TaskStatus.REVIEWED, handover_ack_at=timezone.now())
        self.quote = Quotation.objects.create(
            lead=self.lead, owner=self.sales, created_by=self.sales, source_lang="EN", target_lang="AR", quantity=1000,
            rate=Decimal("0.08"), total=Decimal("80.00"), currency="USD", status=Quotation.Status.ACCEPTED, task=self.task,
            payment_terms="50% upfront",
        )
        self.mail = mock.patch("dashboard.mailer.send_delivery").start()
        self.addCleanup(mock.patch.stopall)

    def deliver(self):
        self.assertTrue(services.mark_delivered(self.task, self.ops))
        return Invoice.objects.get(task=self.task)

    def browser(self, user):
        browser = DjangoClient()
        browser.force_login(user)
        return browser

    def get(self, user, name, *args, **query):
        return self.browser(user).get(reverse(f"dashboard:{name}", args=args), query)

    def post(self, user, name, body, *args):
        return self.browser(user).post(reverse(f"dashboard:{name}", args=args), json.dumps(body), content_type="application/json")


class DraftOnDeliveryTests(_Finance):
    def test_delivering_drafts_the_invoice_at_the_quotations_price(self):
        invoice = self.deliver()
        self.assertEqual((invoice.status, invoice.amount, invoice.currency, invoice.owner), ("draft", Decimal("80.00"), "USD", self.sales))
        self.assertEqual((invoice.quotation, invoice.client, invoice.payment_terms), (self.quote, self.client_obj, "50% upfront"))
        self.assertEqual(invoice.due_date, timezone.localdate() + timedelta(days=finance.DEFAULT_DUE_DAYS))
        self.assertTrue(invoice.code.startswith("INV-"))

    def test_the_translator_is_priced_at_the_agreed_price_and_it_is_kept(self):
        self.deliver()
        cost = self.task.costs.get()
        self.assertEqual((cost.person, cost.words, cost.rate_per_250, cost.amount, cost.automatic), (self.tr, 1000, Decimal("50.00"), Decimal("200.00"), True))
        # A price agreed later does not rewrite what this project cost.
        User.objects.filter(pk=self.tr.pk).update(cost_per_250=Decimal("90"))
        finance.price_translators(Task.objects.get(pk=self.task.pk))
        self.assertEqual(self.task.costs.get().amount, Decimal("200.00"))

    def test_each_translator_of_a_split_task_is_priced_on_their_own_share(self):
        Task.objects.filter(pk=self.task.pk).update(translator=self.tr)
        for person, words in ((self.tr, 600), (self.tr2, 400)):
            Assignment.objects.create(task=self.task, assignee=person, target_role=Role.TRANSLATOR, status=AssignmentStatus.ACCEPTED,
                                      words=words, expires_at=timezone.now() + timedelta(days=1), done_at=timezone.now())
        self.task.refresh_from_db()
        self.deliver()
        costs = {c.person_id: c for c in self.task.costs.all()}
        self.assertEqual(costs[self.tr.pk].amount, Decimal("120.00"))
        # No agreed price: not known, never a made-up zero.
        self.assertIsNone(costs[self.tr2.pk].amount)

    def test_accounting_and_the_owner_are_told_without_the_clients_name(self):
        invoice = self.deliver()
        for person in (self.accounting, self.admin):
            note = person.notifications.get(url=f"/app/accounts/invoices/{invoice.pk}")
            words = note.body_ar + note.body_en
            self.assertIn(self.client_obj.code, words)
            for secret in ("Anna", "Lingua", "anna@"):
                self.assertNotIn(secret, words)
        self.assertFalse(self.sales.notifications.filter(url__contains="invoices").exists())

    def test_a_task_with_no_quotation_drafts_nothing_but_is_priced(self):
        Quotation.objects.update(task=None)
        self.assertTrue(services.mark_delivered(self.task, self.ops))
        self.assertFalse(Invoice.objects.exists())
        self.assertEqual(self.task.costs.count(), 1)
        self.assertIn(self.task.code, [t.code for t in finance.uninvoiced_tasks()])

    def test_a_drafting_that_breaks_does_not_undo_the_delivery(self):
        with mock.patch("dashboard.finance.draft_for_delivered", side_effect=RuntimeError("boom")):
            self.assertTrue(services.mark_delivered(self.task, self.ops))
        self.task.refresh_from_db()
        self.assertEqual(self.task.status, TaskStatus.DELIVERED)


class DoorTests(_Finance):
    def test_the_doors_are_under_api_v1(self):
        self.assertEqual(reverse("dashboard:v1_finance_invoices"), "/api/v1/finance/invoices/")
        self.assertEqual(reverse("dashboard:v1_finance_invoice_send", args=[3]), "/api/v1/finance/invoices/3/send/")

    def test_only_accounting_and_the_owner_have_a_door(self):
        invoice = self.deliver()
        for user in (self.sales, self.manager, self.ops, self.tr):
            self.assertEqual(self.get(user, "v1_finance_invoices").status_code, 403, user.username)
            self.assertEqual(self.get(user, "v1_finance_invoice", invoice.pk).status_code, 403, user.username)
            self.assertEqual(self.post(user, "v1_finance_invoice_send", {}, invoice.pk).status_code, 403, user.username)
        for user in (self.accounting, self.admin):
            self.assertEqual(self.get(user, "v1_finance_invoice", invoice.pk).status_code, 200, user.username)
        self.mail.assert_not_called()

    def test_accounting_reads_the_code_and_the_name_only_when_granted(self):
        invoice = self.deliver()
        raw = self.get(self.accounting, "v1_finance_invoice", invoice.pk).content.decode()
        for secret in ("Anna", "Lingua", "anna@"):
            self.assertNotIn(secret, raw)
        User.objects.filter(pk=self.accounting.pk).update(client_identity_access=True)
        body = _json(self.get(self.accounting, "v1_finance_invoice", invoice.pk))
        self.assertEqual(body["invoice"]["client"]["email"], "anna@lingua.test")
        self.assertTrue(AuditLog.objects.filter(actor=self.accounting, action="client.identity.view").exists())

    def test_the_sales_person_sees_where_it_stands_from_the_quotation_and_no_costs(self):
        self.deliver()
        body = _json(self.browser(self.sales).get(reverse("dashboard:v1_b2b_quotations", args=[self.lead.pk])))
        brief = body["quotations"][0]["invoice"]
        self.assertEqual((brief["status"], brief["amount"], brief["paid"]), ("draft", "80.00", "0.00"))
        raw = json.dumps(body)
        for secret in ("200.00", "cost", "profit", "egp"):
            self.assertNotIn(secret, raw)


class SendAndCollectTests(_Finance):
    def setUp(self):
        super().setUp()
        self.invoice = self.deliver()
        self.post(self.accounting, "v1_finance_invoice_save", {"amount": "80", "currency": "USD", "egp_rate": "50", "due_date": "", "payment_terms": "", "notes": "Bank: X"}, self.invoice.pk)

    def send(self):
        return self.post(self.accounting, "v1_finance_invoice_send", {}, self.invoice.pk)

    def test_it_is_mailed_from_the_company_mailbox_with_the_answer_to_the_sales_person(self):
        answer = self.send()
        self.assertEqual(answer.status_code, 200, answer.content)
        args, kwargs = self.mail.call_args
        self.assertEqual(args[1], "anna@lingua.test")
        self.assertEqual(kwargs.get("from_email", ""), "")
        self.assertEqual(kwargs["headers"], {"Reply-To": "seller@eagle.test"})
        self.assertIn("Amount due: 80.00 USD", kwargs["body"])
        self.assertIn("Bank: X", kwargs["body"])
        # Not in the client's conversation: the operation reads the company line.
        self.assertFalse(OutboundMessage.objects.exists())
        self.invoice.refresh_from_db()
        self.assertEqual(self.invoice.status, "sent")

    def test_it_is_sent_once_and_its_amount_is_fixed_once_sent(self):
        self.send()
        self.assertEqual(_json(self.send())["error"], "not_draft")
        answer = self.post(self.accounting, "v1_finance_invoice_save", {"amount": "99", "currency": "USD", "egp_rate": "50", "due_date": "", "payment_terms": "", "notes": ""}, self.invoice.pk)
        self.assertEqual(_json(answer)["error"], "not_draft")
        self.assertEqual(self.mail.call_count, 1)

    def test_a_letter_that_did_not_leave_leaves_a_draft(self):
        self.mail.side_effect = mailer.MailError("x", "x")
        self.assertEqual(_json(self.send())["error"], "send_failed")
        self.invoice.refresh_from_db()
        self.assertEqual((self.invoice.status, self.invoice.sent_at), ("draft", None))

    def test_no_exchange_rate_no_send(self):
        Invoice.objects.filter(pk=self.invoice.pk).update(egp_rate=None)
        self.assertEqual(_json(self.send())["error"], "no_rate")
        self.mail.assert_not_called()

    def test_payments_make_it_partly_paid_then_paid_and_never_more(self):
        self.send()
        pay = lambda amount: self.post(self.accounting, "v1_finance_payment_add", {"amount": amount, "paid_on": "", "method": "Wise", "note": ""}, self.invoice.pk)
        self.assertEqual(_json(pay("30"))["invoice"]["status"], "partial")
        self.assertEqual(_json(pay("60"))["error"], "bad_amount")
        body = _json(pay("50"))["invoice"]
        self.assertEqual((body["status"], body["paid"], body["left"]), ("paid", "80.00", "0.00"))
        self.assertEqual(_json(pay("1"))["error"], "not_open")
        # A payment written by mistake is taken back, and the status follows.
        payment = self.invoice.payments.order_by("-id").first()
        self.assertEqual(_json(self.post(self.accounting, "v1_finance_payment_delete", {}, payment.pk))["invoice"]["status"], "partial")

    def test_no_payment_on_a_draft_and_no_cancel_once_paid(self):
        answer = self.post(self.accounting, "v1_finance_payment_add", {"amount": "10", "paid_on": "", "method": "", "note": ""}, self.invoice.pk)
        self.assertEqual(_json(answer)["error"], "not_open")
        self.send()
        self.post(self.accounting, "v1_finance_payment_add", {"amount": "10", "paid_on": "", "method": "", "note": ""}, self.invoice.pk)
        self.assertEqual(_json(self.post(self.accounting, "v1_finance_invoice_cancel", {}, self.invoice.pk))["error"], "has_payments")

    def test_a_cancelled_invoice_lets_the_task_be_invoiced_again(self):
        self.post(self.accounting, "v1_finance_invoice_cancel", {}, self.invoice.pk)
        self.assertIn(self.task.code, [t.code for t in finance.uninvoiced_tasks()])
        answer = self.post(self.accounting, "v1_finance_invoice_create", {"amount": "75", "currency": "USD"}, self.task.code)
        self.assertEqual(answer.status_code, 200, answer.content)
        self.assertEqual(_json(self.post(self.accounting, "v1_finance_invoice_create", {"amount": "75", "currency": "USD"}, self.task.code))["error"], "invoiced")

    def test_overdue_is_told_once(self):
        self.send()
        Invoice.objects.filter(pk=self.invoice.pk).update(due_date=timezone.localdate() - timedelta(days=1))
        self.assertEqual(finance.sweep_overdue(), 1)
        self.assertEqual(finance.sweep_overdue(), 0)
        url = f"/app/accounts/invoices/{self.invoice.pk}"
        self.assertEqual(Notification.objects.filter(url=url, title_en="Invoice overdue").count(), 2)
        rows = _json(self.get(self.accounting, "v1_finance_invoices", show="overdue"))["invoices"]
        self.assertEqual([r["code"] for r in rows], [self.invoice.code])


class ProfitTests(_Finance):
    def setUp(self):
        super().setUp()
        self.invoice = self.deliver()

    def profit(self):
        return _json(self.get(self.accounting, "v1_finance_invoice", self.invoice.pk))["invoice"]["profit"]

    def test_profit_is_the_price_in_egp_less_the_costs(self):
        self.post(self.accounting, "v1_finance_invoice_save", {"amount": "80", "currency": "USD", "egp_rate": "50", "due_date": "", "payment_terms": "", "notes": ""}, self.invoice.pk)
        self.post(self.accounting, "v1_finance_cost_add", {"kind": "reviewer", "amount": "300", "description": "review"}, self.invoice.pk)
        self.assertEqual(self.profit(), {"price_egp": "4000.00", "costs": "500.00", "profit": "3500.00", "margin": 88, "currency": "EGP"})

    def test_not_measured_without_a_rate_or_with_a_cost_not_known(self):
        Invoice.objects.filter(pk=self.invoice.pk).update(egp_rate=None)
        self.assertIsNone(self.profit()["profit"])
        Invoice.objects.filter(pk=self.invoice.pk).update(egp_rate=Decimal("50"))
        ProjectCost.objects.create(task=self.task, kind="dtp", amount=None)
        body = self.profit()
        self.assertEqual((body["costs"], body["profit"], body["margin"]), (None, None, None))

    def test_an_egp_invoice_is_at_one(self):
        self.post(self.accounting, "v1_finance_invoice_save", {"amount": "4000", "currency": "EGP", "egp_rate": "7", "due_date": "", "payment_terms": "", "notes": ""}, self.invoice.pk)
        self.invoice.refresh_from_db()
        self.assertEqual(self.invoice.egp_rate, Decimal("1"))

    def test_a_cost_with_no_price_is_given_one(self):
        cost = ProjectCost.objects.create(task=self.task, kind="translator", person=self.tr2, words=400, amount=None, automatic=True)
        answer = self.post(self.accounting, "v1_finance_cost_save", {"amount": "90", "description": ""}, cost.pk)
        self.assertEqual(answer.status_code, 200, answer.content)
        cost.refresh_from_db()
        self.assertEqual(cost.amount, Decimal("90.00"))
        self.assertTrue(AuditLog.objects.filter(action="finance.cost_save").exists())

    def test_the_next_invoice_in_a_currency_starts_from_the_last_rate(self):
        Invoice.objects.filter(pk=self.invoice.pk).update(egp_rate=Decimal("48.5"))
        self.assertEqual(finance.last_rate("USD"), Decimal("48.5"))
        self.assertEqual(finance.last_rate("EGP"), Decimal("1"))
        self.assertIsNone(finance.last_rate("GBP"))

    def test_bad_figures_are_refused(self):
        for body in ({"kind": "reviewer", "amount": "-5", "description": ""}, {"kind": "magic", "amount": "5", "description": ""}):
            self.assertEqual(self.post(self.accounting, "v1_finance_cost_add", body, self.invoice.pk).status_code, 400, body)
        for amount in ("abc", "NaN", "1.123456"):
            self.assertEqual(self.post(self.accounting, "v1_finance_cost_add", {"kind": "dtp", "amount": amount, "description": ""}, self.invoice.pk).status_code, 400)


class CostRateFieldTests(TestCase):
    def test_the_agreed_price_is_a_translators_only(self):
        person = User.objects.create_user("x", password="pw", role=Role.TRANSLATOR, cost_per_250=Decimal("40"))
        person.role = Role.OPERATION
        person.save()
        person.refresh_from_db()
        self.assertIsNone(person.cost_per_250)
        form = StaffEditForm(instance=person)
        self.assertIn("cost_per_250", form.fields)
        data = {name: form.initial.get(name, "") for name in form.fields}
        data.update(role=Role.OPERATION, cost_per_250="40", is_active="on", rating="0", languages="")
        bound = StaffEditForm(data, instance=person)
        self.assertFalse(bound.is_valid())
        self.assertIn("cost_per_250", bound.errors)
