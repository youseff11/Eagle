"""``/api/v1/finance/`` - client invoices, payments and project costs (B2B part 5, 11/10/2026).

The rules are ``finance.py``; these doors read and check the body and say what happened. Accounting and the owner only
(``finance.handles``): anybody else is a written-down 403. A refusal is ``{"ok": false, "error": code, "message": words}``
and nothing was written.

The client's name and address appear only for who may see the client's identity (``identity.can_see``: the owner, and the
Accounting person the owner granted it to), and showing them is a row in the audit log, as on the client pages. Everybody
else here reads the client's code.
"""

from datetime import date
from decimal import Decimal, InvalidOperation

from django.db.models import Sum
from django.http import JsonResponse
from django.shortcuts import get_object_or_404
from django.utils import timezone

from . import finance, identity
from .api_v1 import BadBody, _error, _object, _text, endpoint
from .clock import fmt12
from .models import HOME_CURRENCY, Invoice, InvoicePayment, ProjectCost, Task
from .permissions import api_gate

#: The longest words a client reads under an invoice, terms, a payment's method and note, and a cost's description.
MAX_NOTES = 4000
MAX_TERMS = 250
MAX_METHOD = 80
MAX_NOTE = 250
MAX_DESCRIPTION = 200
#: The most invoices one list answers with.
MAX_LIST = 300


def _refused(refusal, status=400):
    return JsonResponse({"ok": False, "error": refusal.code, "message": refusal.ar, "message_en": refusal.en}, status=status)


def _stamp(value):
    return fmt12(value, "en", "%d/%m/%Y") if value else ""


def _day(value):
    return value.isoformat() if value else ""


def _amount(value):
    return None if value is None else f"{value:.2f}"


def _decimal(body, name, *, optional=False):
    raw = body.get(name)
    if optional and raw in (None, ""):
        return None
    if isinstance(raw, bool) or not isinstance(raw, (int, float, str)) or len(str(raw)) > 20:
        raise BadBody
    try:
        value = Decimal(str(raw).strip())
    except InvalidOperation:
        raise BadBody from None
    if not value.is_finite() or value.as_tuple().exponent < -4:
        raise BadBody
    return value


def _date(body, name, *, optional=True):
    raw = body.get(name, "")
    if raw in ("", None):
        if optional:
            return None
        raise BadBody
    if not isinstance(raw, str):
        raise BadBody
    try:
        return date.fromisoformat(raw)
    except ValueError:
        raise BadBody from None


def _client_json(request, client, *, record=False):
    """The client's code, and - for who may see it - the name and the address. Showing them is written down."""
    out = {"code": client.code}
    if identity.can_see(request.user):
        out.update({"name": client.name, "company": client.company, "email": client.email})
        if record:
            identity.record_identity_view(request, client, "invoice")
    return out


def _invoice_row(invoice):
    received = invoice.paid_total if hasattr(invoice, "paid_total") else finance.paid(invoice)
    received = received or Decimal("0")
    return {
        "id": invoice.pk,
        "code": invoice.code,
        "client_code": invoice.client.code,
        "task": invoice.task.code if invoice.task_id else "",
        "quotation": invoice.quotation.code if invoice.quotation_id else "",
        "amount": _amount(invoice.amount),
        "paid": _amount(received),
        "left": _amount(invoice.amount - received),
        "currency": invoice.currency,
        "status": invoice.status,
        "overdue": finance.is_overdue(invoice),
        "issue_date": _day(invoice.issue_date),
        "due_date": _day(invoice.due_date),
        "sent_at": _stamp(invoice.sent_at),
        "sales": (invoice.owner.get_full_name() or invoice.owner.username) if invoice.owner_id else "",
    }


def _profit_json(invoice):
    numbers = finance.profit(invoice)
    return {
        "price_egp": _amount(numbers["price_egp"]),
        "costs": _amount(numbers["costs"]),
        "profit": _amount(numbers["profit"]),
        "margin": numbers["margin"],
        "currency": HOME_CURRENCY,
    }


def _cost_json(cost):
    return {
        "id": cost.pk,
        "kind": cost.kind,
        "person": (cost.person.get_full_name() or cost.person.username) if cost.person_id else "",
        "description": cost.description,
        "words": cost.words,
        "rate_per_250": _amount(cost.rate_per_250),
        "amount": _amount(cost.amount),
        "automatic": cost.automatic,
    }


def _invoice_json(request, invoice, *, record=False):
    return {
        **_invoice_row(invoice),
        "client": _client_json(request, invoice.client, record=record),
        "egp_rate": f"{invoice.egp_rate.normalize():f}" if invoice.egp_rate else "",
        "payment_terms": invoice.payment_terms,
        "notes": invoice.notes,
        "payments": [
            {
                "id": p.pk, "amount": _amount(p.amount), "paid_on": _day(p.paid_on), "method": p.method, "note": p.note,
                "by": (p.by.get_full_name() or p.by.username) if p.by_id else "",
            }
            for p in invoice.payments.select_related("by")
        ],
        "costs": [_cost_json(c) for c in invoice.task.costs.select_related("person")] if invoice.task_id else [],
        "profit": _profit_json(invoice),
    }


def _invoice_or_404(invoice_id):
    return get_object_or_404(
        Invoice.objects.select_related("client", "task", "quotation", "quotation__lead", "owner"), pk=invoice_id,
    )


def _answer(request, invoice):
    invoice = _invoice_or_404(invoice.pk)
    return JsonResponse({"ok": True, "invoice": _invoice_json(request, invoice)})


# ---------------------------------------------------------------------------
# Reading
# ---------------------------------------------------------------------------

#: The lists the page filters by.
FILTERS = ("all", "draft", "open", "overdue", "paid", "cancelled")


@endpoint("GET")
@api_gate(finance.handles)
def invoices(request):
    """The invoices, newest first, ``?show=`` narrowing them; and the delivered tasks still to invoice by hand."""
    show = request.GET.get("show", "all")
    if show not in FILTERS:
        return _error(400, "bad_filter")
    rows = Invoice.objects.select_related("client", "task", "quotation", "owner").annotate(paid_total=Sum("payments__amount"))
    if show == "draft":
        rows = rows.filter(status=Invoice.Status.DRAFT)
    elif show in ("open", "overdue"):
        rows = rows.filter(status__in=(Invoice.Status.SENT, Invoice.Status.PARTIAL))
    elif show == "paid":
        rows = rows.filter(status=Invoice.Status.PAID)
    elif show == "cancelled":
        rows = rows.filter(status=Invoice.Status.CANCELLED)
    items = [_invoice_row(row) for row in rows[:MAX_LIST]]
    if show == "overdue":
        items = [row for row in items if row["overdue"]]
    # What is still owed, per currency: dollars and pounds are never added together.
    owed = {}
    for row in Invoice.objects.filter(status__in=(Invoice.Status.SENT, Invoice.Status.PARTIAL)).annotate(paid_total=Sum("payments__amount")):
        owed[row.currency] = owed.get(row.currency, Decimal("0")) + row.amount - (row.paid_total or Decimal("0"))
    return JsonResponse({
        "ok": True,
        "show": show,
        "invoices": items,
        "owed": {currency: _amount(amount) for currency, amount in sorted(owed.items())},
        "uninvoiced": [
            {
                "code": task.code, "client_code": task.client.code, "title": task.title_for(request.user),
                "delivered_at": _stamp(task.delivered_at), "words": task.word_count,
            }
            for task in finance.uninvoiced_tasks()
        ],
        "currencies": list(finance.CURRENCIES),
    })


@endpoint("GET")
@api_gate(finance.handles)
def invoice(request, invoice_id):
    """One invoice: the client (named for who may see it), what was paid, what the project cost and earned."""
    row = _invoice_or_404(invoice_id)
    return JsonResponse({
        "ok": True,
        "invoice": _invoice_json(request, row, record=True),
        "cost_kinds": [{"value": v, "label": label} for v, label in ProjectCost.Kind.choices],
        "currencies": list(finance.CURRENCIES),
    })


# ---------------------------------------------------------------------------
# Writing
# ---------------------------------------------------------------------------

def _run(request, invoice, action):
    try:
        action()
    except finance.Refused as refusal:
        return _refused(refusal)
    return _answer(request, invoice)


@endpoint("POST")
@api_gate(finance.handles)
def invoice_create(request, code):
    """``{"amount", "currency"}`` - invoice a delivered task with no quotation behind it."""
    task = get_object_or_404(Task.objects.select_related("client"), code=code)
    try:
        body = _object(request)
        amount = _decimal(body, "amount")
        currency = _text(body, "currency", 3)
    except BadBody:
        return _error(400, "bad_request")
    try:
        made = finance.invoice_by_hand(task, request.user, amount, currency)
    except finance.Refused as refusal:
        return _refused(refusal)
    return _answer(request, made)


@endpoint("POST")
@api_gate(finance.handles)
def invoice_save(request, invoice_id):
    """``{"amount", "currency", "egp_rate", "due_date", "payment_terms", "notes"}``."""
    row = _invoice_or_404(invoice_id)
    try:
        body = _object(request)
        values = {
            "amount": _decimal(body, "amount"),
            "currency": _text(body, "currency", 3),
            "egp_rate": _decimal(body, "egp_rate", optional=True),
            "due_date": _date(body, "due_date"),
            "payment_terms": _text(body, "payment_terms", MAX_TERMS),
            "notes": _text(body, "notes", MAX_NOTES),
        }
    except BadBody:
        return _error(400, "bad_request")
    return _run(request, row, lambda: finance.save_invoice(row, request.user, values))


@endpoint("POST")
@api_gate(finance.handles)
def invoice_send(request, invoice_id):
    row = _invoice_or_404(invoice_id)
    return _run(request, row, lambda: finance.send_invoice(row, request.user))


@endpoint("POST")
@api_gate(finance.handles)
def invoice_cancel(request, invoice_id):
    row = _invoice_or_404(invoice_id)
    return _run(request, row, lambda: finance.cancel_invoice(row, request.user))


@endpoint("POST")
@api_gate(finance.handles)
def payment_add(request, invoice_id):
    """``{"amount", "paid_on": "YYYY-MM-DD", "method", "note"}``."""
    row = _invoice_or_404(invoice_id)
    try:
        body = _object(request)
        amount = _decimal(body, "amount")
        paid_on = _date(body, "paid_on", optional=True) or timezone.localdate()
        method = _text(body, "method", MAX_METHOD)
        note = _text(body, "note", MAX_NOTE)
    except BadBody:
        return _error(400, "bad_request")
    return _run(request, row, lambda: finance.record_payment(row, request.user, amount, paid_on, method, note))


@endpoint("POST")
@api_gate(finance.handles)
def payment_delete(request, payment_id):
    payment = get_object_or_404(InvoicePayment.objects.select_related("invoice"), pk=payment_id)
    row = payment.invoice
    return _run(request, row, lambda: finance.delete_payment(payment, request.user))


@endpoint("POST")
@api_gate(finance.handles)
def cost_add(request, invoice_id):
    """``{"kind", "amount", "description"}`` - a cost of the invoice's project, in EGP."""
    row = _invoice_or_404(invoice_id)
    if not row.task_id:
        return _refused(finance.Refused("no_task", "الفاتورة دي مالهاش تاسك.", "This invoice has no task."))
    try:
        body = _object(request)
        kind = _text(body, "kind", 12)
        amount = _decimal(body, "amount")
        description = _text(body, "description", MAX_DESCRIPTION)
    except BadBody:
        return _error(400, "bad_request")
    return _run(request, row, lambda: finance.add_cost(row.task, request.user, kind, amount, description))


@endpoint("POST")
@api_gate(finance.handles)
def cost_save(request, cost_id):
    """``{"amount", "description"}`` - correct a cost (an empty amount = not known yet)."""
    cost = get_object_or_404(ProjectCost.objects.select_related("task"), pk=cost_id)
    row = cost.task.invoices.order_by("-created_at").first()
    try:
        body = _object(request)
        amount = _decimal(body, "amount", optional=True)
        description = _text(body, "description", MAX_DESCRIPTION)
    except BadBody:
        return _error(400, "bad_request")
    try:
        finance.save_cost(cost, request.user, amount, description)
    except finance.Refused as refusal:
        return _refused(refusal)
    return _answer(request, row) if row is not None else JsonResponse({"ok": True})


@endpoint("POST")
@api_gate(finance.handles)
def cost_delete(request, cost_id):
    cost = get_object_or_404(ProjectCost.objects.select_related("task"), pk=cost_id)
    row = cost.task.invoices.order_by("-created_at").first()
    try:
        finance.delete_cost(cost, request.user)
    except finance.Refused as refusal:
        return _refused(refusal)
    return _answer(request, row) if row is not None else JsonResponse({"ok": True})

