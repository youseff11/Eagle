"""The CEO board (B2B part 6, 11/10/2026): the whole company on one page, for the owner. The requirements' section 21.

Built from what the other parts already count, never counted twice: the Sales numbers are ``b2b.kpis``, the money is
``finance`` (invoices, payments, costs). What this module adds is putting them side by side for a period, and the few
figures nobody counted yet - the projects running and late, the translators' load, quality and rework, and the money
by client and by project.

The rules every figure keeps (CLAUDE.md): a figure with nothing to measure is ``None`` ("not measured"), never zero; money
in different currencies is never added together - per currency, and in EGP only through each invoice's own exchange rate,
and an EGP figure that needs a rate nobody wrote is ``None``.
"""

from datetime import datetime, time as dtime, timedelta
from decimal import Decimal

from django.db.models import Avg, Sum
from django.utils import timezone

from . import b2b, finance
from .models import (
    ACTIVE_TASK_STATUSES, ClientComplaint, Invoice, InvoicePayment, Quotation, Role, Task, TaskStatus, User,
    translator_holdings,
)

#: The longest rows the per-client and per-project tables carry, and the translators' load list.
MAX_CLIENTS = 30
MAX_PROJECTS = 30
MAX_TRANSLATORS = 60


def _span(start, end):
    return (
        timezone.make_aware(datetime.combine(start, dtime.min)),
        timezone.make_aware(datetime.combine(end + timedelta(days=1), dtime.min)),
    )


def _per_currency(pairs):
    out = {}
    for currency, amount in pairs:
        out[currency] = out.get(currency, Decimal("0")) + (amount or Decimal("0"))
    return {currency: f"{amount:.2f}" for currency, amount in sorted(out.items())}


def _egp(invoices):
    """The invoices' total in EGP, through each one's own exchange rate; ``None`` when one of them has none."""
    total = Decimal("0")
    for invoice in invoices:
        if not invoice.egp_rate:
            return None
        total += invoice.amount * invoice.egp_rate
    return finance.money(total)


def _costs(invoices):
    """The direct costs of the invoices' projects (EGP); ``None`` when a project has a cost not priced, or none written."""
    total = Decimal("0")
    for invoice in invoices:
        known, complete = finance.costs_total(invoice.task)
        if not complete:
            return None
        total += known
    return finance.money(total)


def _rate(part, whole):
    return None if not whole else round(100 * part / whole)


def _money(value):
    return None if value is None else f"{value:.2f}"


def sales_block(user, start, end):
    """Section 21's Sales lines: today and the period - accepted quotations' value per currency, new leads, quotations,
    won and lost - and the Sales people side by side (``b2b.kpis``, as the Sales manager reads them)."""
    today = timezone.localdate()
    day_from, day_to = _span(today, today)
    accepted_today = Quotation.objects.filter(status=Quotation.Status.ACCEPTED, decided_at__gte=day_from, decided_at__lt=day_to)
    rows, total = b2b.kpis(user, start, end)
    return {
        "today": {
            "won_value": _per_currency(accepted_today.values_list("currency", "total")),
            "won": accepted_today.values("lead").distinct().count(),
        },
        "period": total,
        "people": rows,
    }


def projects_block(start, end):
    """The work: running, late, delivered in the period, and the quality and rework of what was delivered."""
    now = timezone.now()
    span_from, span_to = _span(start, end)
    active = Task.objects.filter(status__in=ACTIVE_TASK_STATUSES)
    delivered = Task.objects.filter(status=TaskStatus.DELIVERED, delivered_at__gte=span_from, delivered_at__lt=span_to)
    done = delivered.count()
    scored = delivered.filter(review_score__isnull=False)
    complaints = ClientComplaint.objects.filter(created_at__gte=span_from, created_at__lt=span_to)
    average = scored.aggregate(avg=Avg("review_score"))["avg"]
    return {
        "active": active.count(),
        "late": active.filter(deadline__lt=now).count(),
        "delivered": done,
        "words_delivered": delivered.aggregate(words=Sum("word_count"))["words"] or 0,
        # Of what was delivered in the period: the share sent back for a revision at least once, and the review score.
        "rework_rate": _rate(delivered.filter(revision_count__gt=0).count(), done),
        "review_score": None if average is None else round(average, 1),
        "complaints": complaints.count(),
        "complaints_open": complaints.filter(resolved=False).count(),
    }


def workload_block():
    """Each translator still working: the tasks they hold now and the words in them, the busiest first."""
    people = list(User.objects.filter(role=Role.TRANSLATOR, is_active=True).order_by("first_name", "username"))
    holding = translator_holdings([person.pk for person in people])
    rows = []
    for person in people:
        tasks = holding.get(person.pk, [])
        rows.append({
            "id": person.pk,
            "name": person.get_full_name() or person.username,
            "tasks": len(tasks),
            "words": sum(task.word_count or 0 for task in tasks),
        })
    rows.sort(key=lambda row: (-row["tasks"], -row["words"], row["name"]))
    return {"translators": rows[:MAX_TRANSLATORS], "free": sum(1 for row in rows if row["tasks"] == 0)}


def money_block(start, end):
    """Invoiced, received and owed (per currency), and the period's revenue, direct costs and gross profit in EGP. The
    revenue is what was invoiced in the period (by the invoice's date), its costs those of the same projects."""
    issued = list(
        Invoice.objects.exclude(status=Invoice.Status.CANCELLED).filter(issue_date__gte=start, issue_date__lte=end)
        .select_related("task", "client")
    )
    received = InvoicePayment.objects.filter(paid_on__gte=start, paid_on__lte=end).exclude(invoice__status=Invoice.Status.CANCELLED)
    open_rows = list(
        Invoice.objects.filter(status__in=(Invoice.Status.SENT, Invoice.Status.PARTIAL))
        .annotate(paid_total=Sum("payments__amount"))
    )
    overdue = [row for row in open_rows if finance.is_overdue(row)]
    revenue = _egp(issued)
    costs = _costs(issued)
    profit = None if revenue is None or costs is None else revenue - costs
    return {
        "invoiced": _per_currency((row.currency, row.amount) for row in issued),
        "received": _per_currency(received.values_list("invoice__currency", "amount")),
        "owed": _per_currency((row.currency, row.amount - (row.paid_total or 0)) for row in open_rows),
        "overdue": _per_currency((row.currency, row.amount - (row.paid_total or 0)) for row in overdue),
        "overdue_count": len(overdue),
        "drafts": Invoice.objects.filter(status=Invoice.Status.DRAFT).count(),
        "revenue_egp": _money(revenue),
        "costs_egp": _money(costs),
        "profit_egp": _money(profit),
        "margin": None if profit is None or not revenue else round(100 * profit / revenue),
        "invoices": len(issued),
        "_issued": issued,
    }


def _project_row(invoice):
    numbers = finance.profit(invoice)
    return {
        "invoice": invoice.code,
        "invoice_id": invoice.pk,
        "task": invoice.task.code if invoice.task_id else "",
        "client": invoice.client.code,
        "amount": f"{invoice.amount:.2f}",
        "currency": invoice.currency,
        "price_egp": _money(numbers["price_egp"]),
        "profit_egp": _money(numbers["profit"]),
        "margin": numbers["margin"],
    }


def by_project(issued):
    """The period's invoiced projects, the most profitable first; the ones whose profit is not known yet last."""
    rows = [_project_row(invoice) for invoice in issued]
    rows.sort(key=lambda row: (row["profit_egp"] is None, -(Decimal(row["profit_egp"]) if row["profit_egp"] else 0)))
    return rows[:MAX_PROJECTS]


def by_client(issued, viewer):
    """The period's invoices by client: how many, the total per currency, and - when every invoice of theirs is known -
    the revenue and profit in EGP. The name beside the code only for who may see it."""
    from . import identity

    groups = {}
    for invoice in issued:
        groups.setdefault(invoice.client_id, []).append(invoice)
    rows = []
    for invoices in groups.values():
        client = invoices[0].client
        revenue = _egp(invoices)
        costs = _costs(invoices)
        row = {
            "code": client.code,
            "invoices": len(invoices),
            "invoiced": _per_currency((i.currency, i.amount) for i in invoices),
            "revenue_egp": _money(revenue),
            "profit_egp": _money(None if revenue is None or costs is None else revenue - costs),
        }
        if identity.can_see(viewer):
            row["name"] = client.company or client.name
        rows.append(row)
    rows.sort(key=lambda row: (row["revenue_egp"] is None, -(Decimal(row["revenue_egp"]) if row["revenue_egp"] else 0)))
    return rows[:MAX_CLIENTS]


def board(user, start, end):
    """The whole board for the days ``start``..``end`` (Cairo, both included)."""
    money = money_block(start, end)
    issued = money.pop("_issued")
    return {
        "sales": sales_block(user, start, end),
        "projects": projects_block(start, end),
        "workload": workload_block(),
        "money": money,
        "by_project": by_project(issued),
        "by_client": by_client(issued, user),
    }

