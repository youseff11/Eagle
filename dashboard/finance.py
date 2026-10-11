"""Finance: client invoices, their payments, and what a project cost and earned (B2B part 5, 11/10/2026).

The requirements' section 20, decided with the owner:

* Accounting handles the client's invoices (and the owner can do everything Accounting can). An invoice is drafted by itself
  the moment a task made from an accepted quotation is delivered, at the quotation's price; Accounting checks it, sends it by
  e-mail from the company mailbox (the client's answer goes to the Sales person who sold it), and writes down each payment.
  A delivered task with no quotation behind it is invoiced by hand from the invoices page.
* A project's cost is its translators' shares, each at that translator's agreed price of 250 words (``User.cost_per_250``),
  worked out on delivery and kept as it was; Accounting adds anything else by hand (a reviewer, DTP...). Costs are in EGP.
* Profit = the invoice in EGP (its amount x the exchange rate Accounting writes on it) - the costs. Anything not known (no
  exchange rate, a translator with no agreed price) makes it "not measured" (``None``), never a made-up figure.
* Overdue (sent, not fully paid, past its due date) is worked out, not stored, and Accounting and the owner are told once.

Who sees what: Accounting and the owner everything here. The Sales person a company belongs to (and the Sales manager) see
where its invoices stand from the quotation - code, status, amount, paid - and nothing of the costs. Nobody else has a door.
The client's name and address are shown only to who may see the client's identity (``identity.can_see``); sending does not
need them shown: the server finds the address.
"""

from datetime import timedelta
from decimal import ROUND_HALF_UP, Decimal

from django.db import transaction
from django.db.models import Sum
from django.utils import timezone

from .models import (
    HOME_CURRENCY, Channel, Invoice, InvoicePayment, ProjectCost, Quotation, Role, Task, TaskStatus, User,
)

CENT = Decimal("0.01")
#: How long a client has to pay when nothing else was agreed.
DEFAULT_DUE_DAYS = 14
#: The largest amount an invoice, a payment or a cost takes, and the largest exchange rate.
MAX_AMOUNT = Decimal("100000000")
MAX_RATE = Decimal("100000")
#: The currencies an invoice is written in: the quotation's.
CURRENCIES = tuple(value for value, _label in Quotation.Currency.choices)


class Refused(Exception):
    """Nothing was done, and why: a short code for the page and the reason in both languages."""

    def __init__(self, code, ar, en):
        super().__init__(code)
        self.code, self.ar, self.en = code, ar, en


def handles(user):
    """Accounting and the owner: the people who make, send and collect invoices."""
    return bool(getattr(user, "is_authenticated", False) and (user.is_admin_role or user.is_accounting))


def money(value):
    return Decimal(value).quantize(CENT, rounding=ROUND_HALF_UP)


# ---------------------------------------------------------------------------
# Where an invoice stands
# ---------------------------------------------------------------------------

def paid(invoice):
    return invoice.payments.aggregate(total=Sum("amount"))["total"] or Decimal("0")


def is_overdue(invoice, today=None):
    """Sent (or part paid), and past its due date."""
    today = today or timezone.localdate()
    return (
        invoice.status in (Invoice.Status.SENT, Invoice.Status.PARTIAL)
        and invoice.due_date is not None and invoice.due_date < today
    )


def _settle_status(invoice):
    """Partly paid or paid, from what was received. A draft or a cancelled invoice is left as it is."""
    if invoice.status in (Invoice.Status.DRAFT, Invoice.Status.CANCELLED):
        return
    received = paid(invoice)
    if received >= invoice.amount:
        invoice.status = Invoice.Status.PAID
    elif received > 0:
        invoice.status = Invoice.Status.PARTIAL
    else:
        invoice.status = Invoice.Status.SENT
    invoice.save(update_fields=["status", "updated_at"])


# ---------------------------------------------------------------------------
# A project's costs
# ---------------------------------------------------------------------------

def share_cost(words, rate):
    """``words`` at ``rate`` for 250 of them, to the piastre; ``None`` when either is not known."""
    if rate is None or not words:
        return None
    return money(Decimal(words) * Decimal(rate) / Decimal(250))


def translator_shares(task):
    """``[(person, words)]``: each translator who did a share of the task and the words of it (the leader's figure), or -
    a task never split - its one translator and the task's words."""
    shares = list(task.translator_parts(accepted_only=True).select_related("assignee"))
    if shares:
        alone = len(shares) == 1
        return [(share.assignee, share.words or (task.word_count if alone else 0)) for share in shares]
    if task.translator_id:
        return [(task.translator, task.word_count)]
    return []


def price_translators(task, by=None):
    """Write the translators' costs of a delivered task, once: each share at its translator's agreed price of 250 words, as
    the price stood that day. Lines worked out before are left as they are (Accounting may have corrected them)."""
    if task.costs.filter(kind=ProjectCost.Kind.TRANSLATOR, automatic=True).exists():
        return []
    made = []
    for person, words in translator_shares(task):
        rate = person.cost_per_250 if person is not None else None
        made.append(ProjectCost.objects.create(
            task=task, kind=ProjectCost.Kind.TRANSLATOR, person=person, words=words or None, rate_per_250=rate,
            amount=share_cost(words, rate), automatic=True, by=by,
        ))
    return made


def costs_total(task):
    """``(total, complete)``: the costs written so far in EGP, and whether every one of them is known."""
    rows = list(task.costs.all()) if task is not None else []
    known = [row.amount for row in rows if row.amount is not None]
    return sum(known, Decimal("0")), bool(rows) and len(known) == len(rows)


def profit(invoice):
    """``{"price_egp", "costs", "profit", "margin"}`` - each ``None`` when it cannot be known: no exchange rate, no costs
    written, or a cost not priced yet. A cancelled invoice earned nothing to measure."""
    out = {"price_egp": None, "costs": None, "profit": None, "margin": None}
    if invoice.status == Invoice.Status.CANCELLED:
        return out
    if invoice.egp_rate:
        out["price_egp"] = money(invoice.amount * invoice.egp_rate)
    total, complete = costs_total(invoice.task)
    if complete:
        out["costs"] = total
    if out["price_egp"] is not None and out["costs"] is not None:
        out["profit"] = out["price_egp"] - out["costs"]
        if out["price_egp"]:
            out["margin"] = int((out["profit"] * 100 / out["price_egp"]).to_integral_value(rounding=ROUND_HALF_UP))
    return out


def add_cost(task, user, kind, amount, description="", person=None):
    """A cost Accounting writes by hand (EGP)."""
    from . import services

    if not handles(user):
        raise Refused("forbidden", "التكاليف للحسابات بس.", "Costs are Accounting's.")
    if kind not in ProjectCost.Kind.values:
        raise Refused("bad_kind", "اختار نوع التكلفة.", "Choose the kind of cost.")
    if amount is None or not Decimal(0) <= amount <= MAX_AMOUNT:
        raise Refused("bad_amount", "المبلغ مش مظبوط.", "That amount is not right.")
    row = ProjectCost.objects.create(task=task, kind=kind, amount=money(amount), description=description, person=person, by=user)
    services.log(user, "finance.cost_add", task.code, f"{kind} {row.amount} {HOME_CURRENCY}")
    return row


def save_cost(cost, user, amount, description):
    """Correct a cost: its amount (a translator's with no agreed price gets one here) and what it is."""
    from . import services

    if not handles(user):
        raise Refused("forbidden", "التكاليف للحسابات بس.", "Costs are Accounting's.")
    if amount is not None and not Decimal(0) <= amount <= MAX_AMOUNT:
        raise Refused("bad_amount", "المبلغ مش مظبوط.", "That amount is not right.")
    before = cost.amount
    cost.amount = money(amount) if amount is not None else None
    cost.description = description
    cost.save(update_fields=["amount", "description"])
    services.log(user, "finance.cost_save", cost.task.code, f"{before} -> {cost.amount}")
    return cost


def delete_cost(cost, user):
    from . import services

    if not handles(user):
        raise Refused("forbidden", "التكاليف للحسابات بس.", "Costs are Accounting's.")
    services.log(user, "finance.cost_delete", cost.task.code, f"{cost.kind} {cost.amount}")
    cost.delete()


# ---------------------------------------------------------------------------
# Making an invoice
# ---------------------------------------------------------------------------

def last_rate(currency):
    """The exchange rate the newest invoice in this currency was written with: what a new one starts from (1 for EGP)."""
    if currency == HOME_CURRENCY:
        return Decimal("1")
    return (
        Invoice.objects.filter(currency=currency, egp_rate__isnull=False)
        .order_by("-created_at", "-id").values_list("egp_rate", flat=True).first()
    )


def _tell_accounting(invoice, made_by_hand=False):
    """Accounting and the owner hear of a new draft: its code, the client's code and the amount - not the client's name."""
    from . import services

    if made_by_hand:
        return
    for person in User.objects.filter(role__in=(Role.ACCOUNTING, Role.ADMIN), is_active=True):
        services.notify(
            person,
            title_ar="فاتورة جديدة مستنية تتبعت",
            title_en="A new invoice is waiting to be sent",
            body_ar=f"{invoice.code} للعميل {invoice.client.code}: {invoice.amount} {invoice.currency}. التاسك {invoice.task.code} اتسلّمت.",
            body_en=f"{invoice.code} for client {invoice.client.code}: {invoice.amount} {invoice.currency}. Task {invoice.task.code} was delivered.",
            level="info", url=f"/app/accounts/invoices/{invoice.pk}",
        )


def draft_for_delivered(task, by=None):
    """A task was delivered: price its translators and, when it was made from an accepted quotation, draft its invoice at
    the quotation's price. Once per task; the invoice of a task invoiced already is not made again."""
    price_translators(task, by=by)
    quote = task.quotations.filter(status=Quotation.Status.ACCEPTED).select_related("lead").first()
    if quote is None or task.invoices.exclude(status=Invoice.Status.CANCELLED).exists():
        return None
    invoice = Invoice.objects.create(
        client=task.client, task=task, quotation=quote, owner=quote.owner, amount=quote.total, currency=quote.currency,
        egp_rate=last_rate(quote.currency), due_date=timezone.localdate() + timedelta(days=DEFAULT_DUE_DAYS),
        payment_terms=quote.payment_terms, created_by=by,
    )
    from . import services

    services.log(by, "finance.invoice_draft", invoice.code, f"{task.code} {invoice.amount} {invoice.currency} (automatic)")
    _tell_accounting(invoice)
    return invoice


def invoice_by_hand(task, user, amount, currency):
    """Accounting invoices a delivered task with no quotation behind it (a client who came by WhatsApp, say)."""
    from . import services

    if not handles(user):
        raise Refused("forbidden", "الفواتير للحسابات بس.", "Invoices are Accounting's.")
    if task.status != TaskStatus.DELIVERED:
        raise Refused("not_delivered", "الفاتورة بتتعمل لتاسك اتسلّمت.", "An invoice is made for a delivered task.")
    if currency not in CURRENCIES:
        raise Refused("bad_currency", "اختار العملة.", "Choose the currency.")
    if amount is None or not Decimal(0) < amount <= MAX_AMOUNT:
        raise Refused("bad_amount", "المبلغ لازم يبقى أكبر من صفر.", "The amount must be more than zero.")
    with transaction.atomic():
        Task.objects.select_for_update().filter(pk=task.pk).first()
        if task.invoices.exclude(status=Invoice.Status.CANCELLED).exists():
            raise Refused("invoiced", "التاسك دي ليها فاتورة بالفعل.", "This task has an invoice already.")
        price_translators(task, by=user)
        invoice = Invoice.objects.create(
            client=task.client, task=task, amount=money(amount), currency=currency, egp_rate=last_rate(currency),
            due_date=timezone.localdate() + timedelta(days=DEFAULT_DUE_DAYS), created_by=user,
        )
    services.log(user, "finance.invoice_draft", invoice.code, f"{task.code} {invoice.amount} {invoice.currency}")
    return invoice


def uninvoiced_tasks(limit=100):
    """Delivered tasks with no invoice (or only cancelled ones): what Accounting may still invoice by hand. Newest first."""
    invoiced = Invoice.objects.exclude(status=Invoice.Status.CANCELLED).exclude(task__isnull=True).values("task_id")
    return (
        Task.objects.filter(status=TaskStatus.DELIVERED).exclude(pk__in=invoiced)
        .select_related("client").order_by("-delivered_at", "-id")[:limit]
    )


# ---------------------------------------------------------------------------
# Changing, sending, collecting
# ---------------------------------------------------------------------------

def save_invoice(invoice, user, values):
    """Accounting corrects an invoice. The amount and the currency only while it is a draft (the client has not seen it);
    the exchange rate, the due date, the terms and the words any time until it is cancelled."""
    from . import services

    if not handles(user):
        raise Refused("forbidden", "الفواتير للحسابات بس.", "Invoices are Accounting's.")
    if invoice.status == Invoice.Status.CANCELLED:
        raise Refused("cancelled", "الفاتورة دي اتلغت.", "This invoice was cancelled.")
    draft = invoice.status == Invoice.Status.DRAFT
    if not draft and (values["amount"] != invoice.amount or values["currency"] != invoice.currency):
        raise Refused("not_draft", "المبلغ والعملة مابيتغيّروش بعد ما الفاتورة اتبعتت.", "The amount and currency do not change once the invoice was sent.")
    if not Decimal(0) < values["amount"] <= MAX_AMOUNT:
        raise Refused("bad_amount", "المبلغ لازم يبقى أكبر من صفر.", "The amount must be more than zero.")
    if values["currency"] not in CURRENCIES:
        raise Refused("bad_currency", "اختار العملة.", "Choose the currency.")
    rate = values["egp_rate"]
    if rate is not None and not Decimal(0) < rate <= MAX_RATE:
        raise Refused("bad_rate", "سعر الصرف مش مظبوط.", "That exchange rate is not right.")
    if values["currency"] == HOME_CURRENCY:
        rate = Decimal("1")
    before = (invoice.amount, invoice.egp_rate)
    invoice.amount, invoice.currency, invoice.egp_rate = money(values["amount"]), values["currency"], rate
    invoice.due_date, invoice.payment_terms, invoice.notes = values["due_date"], values["payment_terms"], values["notes"]
    invoice.save()
    services.log(user, "finance.invoice_save", invoice.code, f"{before[0]}/{before[1]} -> {invoice.amount}/{invoice.egp_rate}")
    _settle_status(invoice)
    return invoice


def invoice_letter(invoice):
    """``(subject, body)``: English, like the client's side of a B2B conversation."""
    client = invoice.client
    lead = invoice.quotation.lead if invoice.quotation_id else None
    name = ((lead.contact_person if lead else "") or client.name or "").strip().split(" ")[0] or "there"
    lines = [
        f"Dear {name},",
        "",
        f"Please find below invoice {invoice.code} from EagleLingua" + (f" for {invoice.task.code}" if invoice.task_id else "") + ".",
        "",
        f"Amount due: {invoice.amount:,.2f} {invoice.currency}",
        f"Invoice date: {invoice.issue_date:%d %B %Y}",
    ]
    if invoice.quotation_id:
        lines.append(f"Quotation: {invoice.quotation.code}")
    if invoice.due_date:
        lines.append(f"Due by: {invoice.due_date:%d %B %Y}")
    if invoice.payment_terms:
        lines.append(f"Payment terms: {invoice.payment_terms}")
    if invoice.notes.strip():
        lines += ["", invoice.notes.strip()]
    lines += ["", "Thank you for your business.", "", "EagleLingua Accounts"]
    return f"Invoice {invoice.code} - EagleLingua", "\n".join(lines)


def send_invoice(invoice, user):
    """E-mail a draft to the client from the company mailbox. The client's answer goes to the Sales person who sold it
    (``Reply-To``). The letter is not put in the client's conversation: the operation reads the company line, and an
    invoice is not theirs to read. ``Refused`` when it may not or the letter did not leave (it stays a draft)."""
    from . import mailer, services
    from .identity import scrub_contacts
    from .models import AppSettings

    if not handles(user):
        raise Refused("forbidden", "الفواتير للحسابات بس.", "Invoices are Accounting's.")
    address = invoice.client.reply_target(Channel.EMAIL) or invoice.client.email
    if not address:
        raise Refused("no_email", "العميل مالوش إيميل متسجّل. الـSales أو الأدمن يضيفه.", "The client has no e-mail on file. The Sales person or the admin adds it.")
    if not invoice.egp_rate:
        raise Refused("no_rate", "اكتب سعر الصرف الأول.", "Write the exchange rate first.")
    with transaction.atomic():
        locked = Invoice.objects.select_for_update().filter(pk=invoice.pk).first()
        if locked is None or locked.status != Invoice.Status.DRAFT:
            raise Refused("not_draft", "الفاتورة دي اتبعتت قبل كده.", "This invoice was sent already.")
        locked.status = Invoice.Status.SENT
        locked.sent_at = timezone.now()
        locked.save(update_fields=["status", "sent_at", "updated_at"])
    invoice.refresh_from_db()
    subject, body = invoice_letter(invoice)
    headers = {}
    reply_to = (invoice.owner.mail_alias or "").strip() if invoice.owner_id else ""
    if reply_to:
        headers["Reply-To"] = reply_to
    try:
        mailer.send_delivery(AppSettings.load(), address, subject=subject, body=body, attachments=[], headers=headers)
    except mailer.MailError as exc:
        Invoice.objects.filter(pk=invoice.pk).update(status=Invoice.Status.DRAFT, sent_at=None)
        services.log(user, "finance.invoice_send_failed", invoice.code, (exc.message_en or "")[:200])
        raise Refused("send_failed", scrub_contacts(exc.message_ar) or "الإيميل ماتبعتش.", "The e-mail was not sent.") from None
    services.log(user, "finance.invoice_sent", invoice.code, f"{invoice.amount} {invoice.currency}")
    return invoice


def record_payment(invoice, user, amount, paid_on, method="", note=""):
    """Money received. Never more than is left to pay; the invoice turns partly paid or paid by itself."""
    from . import services

    if not handles(user):
        raise Refused("forbidden", "الفواتير للحسابات بس.", "Invoices are Accounting's.")
    with transaction.atomic():
        locked = Invoice.objects.select_for_update().filter(pk=invoice.pk).first()
        if locked is None or locked.status not in (Invoice.Status.SENT, Invoice.Status.PARTIAL):
            raise Refused("not_open", "الدفع بيتسجّل على فاتورة اتبعتت ولسه ماتدفعتش كلها.", "A payment is recorded on a sent invoice not fully paid.")
        left = locked.amount - paid(locked)
        if amount is None or not Decimal(0) < amount <= left:
            raise Refused("bad_amount", f"المبلغ لازم يبقى أكبر من صفر ومايزيدش عن الباقي ({left:,.2f} {locked.currency}).",
                          f"The amount must be more than zero and no more than what is left ({left:,.2f} {locked.currency}).")
        if paid_on > timezone.localdate():
            raise Refused("future", "تاريخ الدفع لسه ماجاش.", "That payment date is in the future.")
        row = InvoicePayment.objects.create(invoice=locked, amount=money(amount), paid_on=paid_on, method=method, note=note, by=user)
        _settle_status(locked)
    services.log(user, "finance.payment", invoice.code, f"{row.amount} {invoice.currency}")
    invoice.refresh_from_db()
    return row


def delete_payment(payment, user):
    """Take back a payment written by mistake; the invoice's status follows."""
    from . import services

    if not handles(user):
        raise Refused("forbidden", "الفواتير للحسابات بس.", "Invoices are Accounting's.")
    invoice = payment.invoice
    with transaction.atomic():
        Invoice.objects.select_for_update().filter(pk=invoice.pk).first()
        services.log(user, "finance.payment_delete", invoice.code, f"{payment.amount} {invoice.currency}")
        payment.delete()
        invoice.refresh_from_db()
        _settle_status(invoice)
    return invoice


def cancel_invoice(invoice, user):
    """Cancel an invoice nothing was paid on. The task may then be invoiced again."""
    from . import services

    if not handles(user):
        raise Refused("forbidden", "الفواتير للحسابات بس.", "Invoices are Accounting's.")
    if invoice.status == Invoice.Status.CANCELLED:
        raise Refused("cancelled", "الفاتورة دي اتلغت قبل كده.", "This invoice was cancelled already.")
    if invoice.payments.exists():
        raise Refused("has_payments", "فيه فلوس اتسجّلت على الفاتورة دي. امسح الدفع الأول لو كان غلط.", "Money was recorded on this invoice. Remove the payment first if it was a mistake.")
    invoice.status = Invoice.Status.CANCELLED
    invoice.save(update_fields=["status", "updated_at"])
    services.log(user, "finance.invoice_cancel", invoice.code, "")
    return invoice


# ---------------------------------------------------------------------------
# Overdue (the requirements' section 24: "Invoice overdue -> alert Finance and authorized management")
# ---------------------------------------------------------------------------

def sweep_overdue(today=None):
    """Tell Accounting and the owner, once per invoice, that it is overdue. Returns how many."""
    from . import services

    today = today or timezone.localdate()
    told = 0
    rows = Invoice.objects.filter(
        status__in=(Invoice.Status.SENT, Invoice.Status.PARTIAL), due_date__lt=today, overdue_alerted_at__isnull=True,
    ).select_related("client")
    people = list(User.objects.filter(role__in=(Role.ACCOUNTING, Role.ADMIN), is_active=True))
    for invoice in rows:
        if not Invoice.objects.filter(pk=invoice.pk, overdue_alerted_at__isnull=True).update(overdue_alerted_at=timezone.now()):
            continue
        left = invoice.amount - paid(invoice)
        for person in people:
            services.notify(
                person,
                title_ar="فاتورة متأخرة",
                title_en="Invoice overdue",
                body_ar=f"{invoice.code} للعميل {invoice.client.code}: باقي {left:,.2f} {invoice.currency}، وكان ميعادها {invoice.due_date:%d/%m/%Y}.",
                body_en=f"{invoice.code} for client {invoice.client.code}: {left:,.2f} {invoice.currency} left, due {invoice.due_date:%d/%m/%Y}.",
                level="warning", url=f"/app/accounts/invoices/{invoice.pk}",
            )
        told += 1
    return told


def invoice_brief(invoice):
    """Where an invoice stands, in a word, for the Sales person who sold it: no costs, no profit."""
    received = paid(invoice)
    return {
        "code": invoice.code,
        "status": invoice.status,
        "overdue": is_overdue(invoice),
        "amount": f"{invoice.amount:.2f}",
        "paid": f"{received:.2f}",
        "currency": invoice.currency,
    }
