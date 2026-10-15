"""``/api/v1/commissions/`` - the Sales commissions (part 3, 15/10/2026). The rules are ``commissions.py``.

The owner reads every line and is the only one who writes: the rates, the split, approving, paid. A Sales person reads
their own lines; a Sales manager their team's too. A refusal is ``{"ok": false, "error": code, "message": words}`` and
nothing was written. A line that is not the reader's is a 404 written down. An invoice is shown by its code and the
client's code, never the client's name.
"""

from decimal import Decimal, InvalidOperation

from django.http import JsonResponse
from django.shortcuts import get_object_or_404

from . import clock, commissions, identity
from .api_v1 import BadBody, _error, _object, _text, endpoint
from .models import AppSettings, Commission, Invoice, Role, User
from .permissions import api_gate

MAX_LIST = 1000


def _refused(refusal, status=400):
    return JsonResponse({"ok": False, "error": refusal.code, "message": refusal.ar, "message_en": refusal.en}, status=status)


def _stamp(value):
    return clock.fmt12(value, "en", "%d/%m/%Y") if value else ""


def _person(user):
    return {"id": user.pk, "name": user.get_full_name() or user.username} if user else None


def _text_of(value):
    return None if value is None else f"{value:.2f}"


def _invoice_json(invoice):
    return {
        "id": invoice.pk, "code": invoice.code, "status": invoice.status, "amount": f"{invoice.amount:.2f}",
        "currency": invoice.currency, "client_code": invoice.client.code,
    }


def _line_json(line, conf):
    figure = commissions.figures(line, conf)
    return {
        "id": line.pk,
        "code": line.code,
        "invoice": _invoice_json(line.invoice),
        "person": _person(line.person),
        "share": f"{line.share:.2f}",
        # The rate it is counted at, and whether it is this line's own (or the person's, or the company's).
        "rate": _text_of(figure["rate"]),
        "own_rate": line.rate is not None,
        "status": line.status,
        "amount": _text_of(figure["amount"]),
        "currency": figure["currency"],
        "amount_egp": _text_of(figure["amount_egp"]),
        "due": commissions.is_due(line),
        "approved_by": _person(line.approved_by),
        "approved_at": _stamp(line.approved_at),
        "paid_at": _stamp(line.paid_at),
        "note": line.note,
    }


def _line_or_404(request, line_id):
    line = get_object_or_404(Commission.objects.select_related("invoice", "invoice__client", "person"), pk=line_id)
    if not commissions.lines_for(request.user).filter(pk=line.pk).exists():
        identity.hidden(request, "commission")
    return line


def _totals(rows):
    """In EGP, per where they stand: due (paid invoice, not approved yet), approved, paid. ``unknown`` counts lines whose
    EGP figure cannot be known yet (no rate, no exchange rate)."""
    out = {"waiting": "0.00", "due": "0.00", "approved": "0.00", "paid": "0.00", "unknown": 0}
    sums = {key: Decimal(0) for key in ("waiting", "due", "approved", "paid")}
    for row in rows:
        if row["status"] == Commission.Status.CANCELLED:
            continue
        key = {"approved": "approved", "paid": "paid"}.get(row["status"]) or ("due" if row["due"] else "waiting")
        if row["amount_egp"] is None:
            out["unknown"] += 1
        else:
            sums[key] += Decimal(row["amount_egp"])
    out.update({key: f"{value:.2f}" for key, value in sums.items()})
    return out


@endpoint("GET")
@api_gate(commissions.has_door)
def lines(request):
    """``?status=`` - the lines the reader reads, newest first, their totals in EGP, and - for the owner - the rates and
    the invoices nobody has a line on yet."""
    user = request.user
    conf = AppSettings.load()
    rows = commissions.lines_for(user)
    status = request.GET.get("status", "")
    if status in Commission.Status.values:
        rows = rows.filter(status=status)
    answer = [_line_json(line, conf) for line in rows[:MAX_LIST]]
    owner = user.is_admin_role
    return JsonResponse({
        "ok": True,
        "can_manage": owner,
        "lines": answer,
        "totals": _totals(answer),
        "company_rate": _text_of(conf.commission_rate) if owner else None,
        "people": [
            {**_person(person), "rate": _text_of(person.commission_rate), "track": person.sales_track}
            for person in User.objects.filter(role=Role.SALES, is_active=True).order_by("first_name", "username")
        ] if owner else [],
        "uncovered": [_invoice_json(invoice) for invoice in commissions.uncovered_invoices()] if owner else [],
    })


def _owner_door(view):
    return api_gate(lambda user: user.is_admin_role)(view)


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


@endpoint("POST")
@_owner_door
def line_rate(request, line_id):
    """``{"rate"}`` - this line's own rate; empty = the person's or the company's."""
    line = _line_or_404(request, line_id)
    try:
        line = commissions.set_line_rate(request.user, line, _rate_of(request))
    except BadBody:
        return _error(400, "bad_request")
    except commissions.Refused as refusal:
        return _refused(refusal)
    return JsonResponse({"ok": True, "line": _line_json(_line_or_404(request, line.pk), AppSettings.load())})


@endpoint("POST")
@_owner_door
def split(request, invoice_id):
    """``{"shares": [{"person": <id>, "share": "50"}, ...]}`` - who worked the deal and each one's part (adding up to 100)."""
    invoice = get_object_or_404(Invoice, pk=invoice_id)
    try:
        raw = _object(request).get("shares")
        if not isinstance(raw, list) or not raw:
            raise BadBody
        shares = []
        for item in raw[: commissions.MAX_PEOPLE + 1]:
            if not isinstance(item, dict) or not isinstance(item.get("person"), int) or isinstance(item.get("person"), bool):
                raise BadBody
            person = User.objects.filter(pk=item["person"], role=Role.SALES, is_active=True).first()
            if person is None:
                return _refused(commissions.Refused("not_sales", "العمولة للـSales بس.", "Commissions are for Sales people only."))
            try:
                share = Decimal(str(item.get("share", "")).strip())
            except InvalidOperation:
                share = None
            shares.append((person, share))
    except BadBody:
        return _error(400, "bad_request")
    try:
        made = commissions.set_split(request.user, invoice, shares)
    except commissions.Refused as refusal:
        return _refused(refusal)
    conf = AppSettings.load()
    return JsonResponse({"ok": True, "lines": [_line_json(line, conf) for line in made]})


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
    return JsonResponse({"ok": True, "line": _line_json(_line_or_404(request, line.pk), AppSettings.load())})


@endpoint("POST")
@_owner_door
def paid(request, line_id):
    line = _line_or_404(request, line_id)
    try:
        line = commissions.mark_paid(request.user, line)
    except commissions.Refused as refusal:
        return _refused(refusal)
    return JsonResponse({"ok": True, "line": _line_json(_line_or_404(request, line.pk), AppSettings.load())})


@endpoint("POST")
@_owner_door
def take_back(request, line_id):
    line = _line_or_404(request, line_id)
    try:
        line = commissions.take_back(request.user, line)
    except commissions.Refused as refusal:
        return _refused(refusal)
    return JsonResponse({"ok": True, "line": _line_json(_line_or_404(request, line.pk), AppSettings.load())})
