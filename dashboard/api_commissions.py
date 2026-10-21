"""``/api/v1/commissions/`` - the Sales commissions, per deal (part 3 of 15/10/2026, per deal since 21/10/2026). The rules
are ``commissions.py``.

The owner reads every deal and is the only one who writes: the rates, a deal's value, invoice and people, approving, paid.
A Sales person reads the deals they have a line on, with their own line; a Sales manager their team's lines too. A refusal
is ``{"ok": false, "error": code, "message": words}`` and nothing was written. A deal or a line that is not the reader's is
a 404 written down. A deal shows the company it was closed with (the owner and the Sales people may read a client's
identity); an invoice shows its code and the client's code.
"""

from decimal import Decimal

from django.http import JsonResponse
from django.shortcuts import get_object_or_404

from . import clock, commissions, identity
from .api_v1 import BadBody, _error, _object, _text, endpoint
from .models import AppSettings, Commission, Deal, Invoice, Role, User
from .permissions import api_gate

MAX_LIST = 500
STAGES = ("waiting", "due", "approved", "paid", "cancelled")


def _refused(refusal, status=400):
    return JsonResponse({"ok": False, "error": refusal.code, "message": refusal.ar, "message_en": refusal.en}, status=status)


def _stamp(value):
    return clock.fmt12(value, "en", "%d/%m/%Y") if value else ""


def _person(user):
    return {"id": user.pk, "name": user.get_full_name() or user.username} if user else None


def _text_of(value):
    return None if value is None else f"{value:.2f}"


def _invoice_json(invoice):
    if invoice is None:
        return None
    return {
        "id": invoice.pk, "code": invoice.code, "status": invoice.status, "amount": f"{invoice.amount:.2f}",
        "currency": invoice.currency, "client_code": invoice.client.code,
    }


def _quotation_json(quote):
    if quote is None:
        return None
    return {
        "code": quote.code, "status": quote.status, "service": quote.get_service_display(), "unit": quote.get_unit_display(),
        "quantity": quote.quantity, "rate": f"{quote.rate:.2f}", "discount": f"{quote.discount_percent:.2f}",
        "total": f"{quote.total:.2f}", "currency": quote.currency, "source_lang": quote.source_lang,
        "target_lang": quote.target_lang, "deadline": quote.deadline.strftime("%d/%m/%Y") if quote.deadline else "",
        "payment_terms": quote.payment_terms,
    }


def _company_json(deal):
    """What the deal was about, from the company's row (gone when the row was deleted: the name is kept on the deal)."""
    lead = deal.lead
    out = {"name": deal.company or (lead.company_name if lead else ""), "sheet": ""}
    if lead is None:
        return out
    out.update({
        "sheet": lead.sheet.title, "contact_person": lead.contact_person, "position": lead.position,
        "country": lead.country, "governorate": lead.governorate, "industry": lead.industry, "services": lead.services,
        "languages": lead.languages, "source": lead.source,
        "customer_type": lead.get_customer_type_display() if lead.customer_type else "",
        "sheet_value": _text_of(lead.deal_value),
    })
    return out


def _line_json(line, conf, egp):
    figure = commissions.figures(line, conf, egp)
    return {
        "id": line.pk,
        "code": line.code,
        "person": _person(line.person),
        # The rate it is counted at, and whether it is this line's own (or the person's, or the company's).
        "rate": _text_of(figure["rate"]),
        "own_rate": line.rate is not None,
        "status": line.status,
        "amount": _text_of(figure["amount"]),
        "currency": figure["currency"],
        "amount_egp": _text_of(figure["amount_egp"]),
        "approved_by": _person(line.approved_by),
        "approved_at": _stamp(line.approved_at),
        "paid_at": _stamp(line.paid_at),
        "note": line.note,
    }


def _stage(deal, lines):
    """Where the deal stands, by the lines the reader reads: cancelled; paid (all paid); approved (all approved or paid);
    due (the client paid the invoice and a line waits for approval); waiting (for the client to pay)."""
    if deal.status == Deal.Status.CANCELLED:
        return "cancelled"
    live = [line for line in lines if line.status != Commission.Status.CANCELLED]
    if live and all(line.status == Commission.Status.PAID for line in live):
        return "paid"
    if live and all(line.status in commissions.DECIDED for line in live):
        return "approved"
    return "due" if commissions.is_paid(deal) else "waiting"


def _deal_json(deal, conf):
    lines = deal.shown
    egp = commissions.egp_rate_of(deal)
    return {
        "id": deal.pk,
        "code": deal.code,
        "market": deal.market,
        "status": deal.status,
        "stage": _stage(deal, lines),
        "company": _company_json(deal),
        "client_code": deal.client.code if deal.client else "",
        "owner": _person(deal.owner),
        "won_at": _stamp(deal.won_at),
        "won_by": _person(deal.won_by),
        "value": _text_of(deal.value),
        "currency": deal.currency,
        "value_by_hand": deal.value_by_hand,
        "egp_rate": None if egp is None else f"{egp:.4f}",
        "quotation": _quotation_json(deal.quotation),
        "invoice": _invoice_json(deal.invoice),
        "paid": commissions.is_paid(deal),
        "note": deal.note,
        "lines": [_line_json(line, conf, egp) for line in lines],
    }


def _totals(deals):
    """In EGP, per where they stand: waiting (the client has not paid), due, approved, paid. ``unknown`` counts lines whose
    EGP figure cannot be known yet (no value, rate or exchange rate)."""
    out = {"waiting": "0.00", "due": "0.00", "approved": "0.00", "paid": "0.00", "unknown": 0}
    sums = {key: Decimal(0) for key in ("waiting", "due", "approved", "paid")}
    for deal in deals:
        if deal["status"] == Deal.Status.CANCELLED:
            continue
        for row in deal["lines"]:
            if row["status"] == Commission.Status.CANCELLED:
                continue
            key = {"approved": "approved", "paid": "paid"}.get(row["status"]) or ("due" if deal["paid"] else "waiting")
            if row["amount_egp"] is None:
                out["unknown"] += 1
            else:
                sums[key] += Decimal(row["amount_egp"])
    out.update({key: f"{value:.2f}" for key, value in sums.items()})
    return out


@endpoint("GET")
@api_gate(commissions.has_door)
def lines(request):
    """``?stage=`` - the deals the reader reads, newest first, with their lines; the totals in EGP; and - for the owner -
    the rates, the Sales people and the invoices on no deal."""
    user = request.user
    conf = AppSettings.load()
    every = [_deal_json(deal, conf) for deal in commissions.deals_for(user)[:MAX_LIST]]
    stage = request.GET.get("stage", "")
    shown = [deal for deal in every if deal["stage"] == stage] if stage in STAGES else every
    owner = user.is_admin_role
    return JsonResponse({
        "ok": True,
        "can_manage": owner,
        "deals": shown,
        "totals": _totals(every),
        "currencies": list(commissions.CURRENCIES),
        "company_rate": _text_of(conf.commission_rate) if owner else None,
        "people": [
            {**_person(person), "rate": _text_of(person.commission_rate), "track": person.sales_track}
            for person in User.objects.filter(role=Role.SALES, is_active=True).order_by("first_name", "username")
        ] if owner else [],
        "uncovered": [_invoice_json(invoice) for invoice in commissions.uncovered_invoices()] if owner else [],
    })


def _owner_door(view):
    return api_gate(lambda user: user.is_admin_role)(view)


def _line_or_404(request, line_id):
    line = get_object_or_404(Commission.objects.select_related("deal", "person"), pk=line_id)
    if not commissions.lines_for(request.user).filter(pk=line.pk).exists():
        identity.hidden(request, "commission")
    return line


def _answer(request, deal_id):
    """The deal as it stands now, as the reader reads it."""
    fresh = commissions.deals_for(request.user).get(pk=deal_id)
    return JsonResponse({"ok": True, "deal": _deal_json(fresh, AppSettings.load())})


def _rate_of(request):
    value = _object(request).get("rate")
    if value is not None and (isinstance(value, bool) or not isinstance(value, (str, int, float))):
        raise BadBody
    return value


@endpoint("POST")
@_owner_door
def company_rate(request):
    """``{"rate": "5"}`` (or empty) - the company's rate."""
    try:
        rate = commissions.set_company_rate(request.user, _rate_of(request))
    except BadBody:
        return _error(400, "bad_request")
    except commissions.Refused as refusal:
        return _refused(refusal)
    return JsonResponse({"ok": True, "rate": _text_of(rate)})


@endpoint("POST")
@_owner_door
def person_rate(request, user_id):
    """``{"rate"}`` - one Sales person's own rate; empty = the company's."""
    person = get_object_or_404(User, pk=user_id)
    try:
        rate = commissions.set_person_rate(request.user, person, _rate_of(request))
    except BadBody:
        return _error(400, "bad_request")
    except commissions.Refused as refusal:
        return _refused(refusal)
    return JsonResponse({"ok": True, "rate": _text_of(rate)})


def _number(value):
    if value is not None and (isinstance(value, bool) or not isinstance(value, (str, int, float))):
        raise BadBody
    return value


@endpoint("POST")
@_owner_door
def deal(request, deal_id):
    """``{"value", "currency", "invoice": <id>|null, "people": [{"person": <id>, "rate": "5"|""}, ...], "note"}`` - only
    the keys sent change: the deal's value and currency, its invoice, and who earned a commission on it at what percent."""
    row = get_object_or_404(Deal, pk=deal_id)
    changes = {}
    try:
        body = _object(request)
        if "value" in body:
            changes["value"] = _number(body["value"])
        if "currency" in body:
            changes["currency"] = _text(body, "currency", 3).upper()
        if "note" in body:
            changes["note"] = _text(body, "note", 250)
        if "invoice" in body:
            raw = body["invoice"]
            if raw is None:
                changes["invoice"] = None
            elif isinstance(raw, int) and not isinstance(raw, bool):
                changes["invoice"] = get_object_or_404(Invoice, pk=raw)
            else:
                raise BadBody
        if "people" in body:
            raw = body["people"]
            if not isinstance(raw, list):
                raise BadBody
            people = []
            for item in raw[: commissions.MAX_PEOPLE + 1]:
                if not isinstance(item, dict) or not isinstance(item.get("person"), int) or isinstance(item.get("person"), bool):
                    raise BadBody
                person = User.objects.filter(pk=item["person"], role=Role.SALES, is_active=True).first()
                if person is None:
                    return _refused(commissions.Refused("not_sales", "العمولة للـSales بس.", "Commissions are for Sales people only."))
                people.append((person, _number(item.get("rate"))))
            changes["people"] = people
    except BadBody:
        return _error(400, "bad_request")
    try:
        commissions.set_deal(request.user, row, **changes)
    except commissions.Refused as refusal:
        return _refused(refusal)
    return _answer(request, row.pk)


@endpoint("POST")
@_owner_door
def deal_cancel(request, deal_id):
    row = get_object_or_404(Deal, pk=deal_id)
    try:
        commissions.cancel_deal(request.user, row)
    except commissions.Refused as refusal:
        return _refused(refusal)
    return _answer(request, row.pk)


@endpoint("POST")
@_owner_door
def invoice_deal(request, invoice_id):
    """An invoice on no deal becomes one; its people are set next with the deal's own door."""
    invoice = get_object_or_404(Invoice, pk=invoice_id)
    try:
        made = commissions.deal_from_invoice(request.user, invoice)
    except commissions.Refused as refusal:
        return _refused(refusal)
    return _answer(request, made.pk)


@endpoint("POST")
@_owner_door
def approve(request, line_id):
    line = _line_or_404(request, line_id)
    try:
        note = _text(_object(request), "note", 250)
        line = commissions.approve(request.user, line, note)
    except BadBody:
        return _error(400, "bad_request")
    except commissions.Refused as refusal:
        return _refused(refusal)
    return _answer(request, line.deal_id)


@endpoint("POST")
@_owner_door
def paid(request, line_id):
    line = _line_or_404(request, line_id)
    try:
        line = commissions.mark_paid(request.user, line)
    except commissions.Refused as refusal:
        return _refused(refusal)
    return _answer(request, line.deal_id)


@endpoint("POST")
@_owner_door
def take_back(request, line_id):
    line = _line_or_404(request, line_id)
    try:
        line = commissions.take_back(request.user, line)
    except commissions.Refused as refusal:
        return _refused(refusal)
    return _answer(request, line.deal_id)
