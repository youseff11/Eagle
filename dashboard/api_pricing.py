"""``/api/v1/b2b/price-list/`` - the price list, its versions, the discount limits and the discounts waiting (part 4,
15/10/2026). The rules are ``pricing.py``.

Every Sales person reads the list in force (the price is what they quote from); the owner saves a new version and sets the
limits; whoever may approve a waiting discount (the team's manager up to their limit, the owner beyond) sees it here and
decides it. A waiting discount names its company, so the list of them is a row in the audit log.
"""

from django.http import JsonResponse
from django.shortcuts import get_object_or_404

from . import b2b, clock, identity, pricing
from .api_v1 import BadBody, _error, _object, _text, endpoint
from .models import AppSettings, PriceList, Quotation
from .permissions import api_gate


def _refused(refusal, status=400):
    return JsonResponse({"ok": False, "error": refusal.code, "message": refusal.ar, "message_en": refusal.en}, status=status)


def _stamp(value):
    return clock.fmt12(value, "en", "%d/%m/%Y") if value else ""


def _version_json(version):
    if version is None:
        return None
    return {
        "id": version.pk, "version": version.version, "note": version.note, "created_at": _stamp(version.created_at),
        "items": [
            {"service": item.service, "unit": item.unit, "currency": item.currency, "pair": item.pair, "rate": f"{item.rate.normalize():f}"}
            for item in version.items.all()
        ],
    }


def _waiting_json(quote):
    return {
        "id": quote.pk, "code": quote.code, "company_name": quote.lead.company_name, "sheet": quote.lead.sheet_id,
        "person": (quote.owner.get_full_name() or quote.owner.username) if quote.owner_id else "",
        "quantity": quote.quantity, "unit": quote.unit, "rate": f"{quote.rate.normalize():f}",
        "discount_percent": f"{quote.discount_percent.normalize():f}", "total": f"{quote.total:.2f}", "currency": quote.currency,
        "list_rate": f"{quote.list_rate.normalize():f}" if quote.list_rate is not None else "",
        "version": quote.price_list.version if quote.price_list_id else None,
        "effective_discount": f"{quote.effective_discount:.2f}",
    }


@endpoint("GET")
@api_gate(b2b.has_door)
def price_list(request):
    """``?version=N`` - a version of the list (the one in force when not said), the versions there are, the limits, and
    the discounts this person may approve."""
    raw = request.GET.get("version", "")
    version = get_object_or_404(PriceList, version=int(raw)) if raw.isdigit() else pricing.current()
    conf = AppSettings.load()
    waiting = pricing.waiting_for(request.user) if (request.user.is_admin_role or request.user.is_sales_manager) else []
    if waiting:
        identity.audit(request, request.user, identity.IDENTITY_LIST, "discounts waiting", f"{len(waiting)} quotations")
    current = pricing.current()
    return JsonResponse({
        "ok": True,
        "can_edit": request.user.is_admin_role,
        "list": _version_json(version),
        "current": current.version if current else None,
        "versions": [{"version": one.version, "created_at": _stamp(one.created_at), "note": one.note} for one in PriceList.objects.all()[:100]],
        "limits": {"sales": f"{conf.discount_limit_sales:.2f}", "manager": f"{conf.discount_limit_manager:.2f}",
                   "mine": f"{pricing.limit_of(request.user, conf):.2f}"},
        "waiting": [_waiting_json(quote) for quote in waiting],
        "services": [{"value": v, "label": label} for v, label in Quotation.Service.choices],
        "units": [{"value": v, "label": label} for v, label in Quotation.Unit.choices],
        "currencies": [v for v, _label in Quotation.Currency.choices],
    })


@endpoint("POST")
@api_gate(lambda user: user.is_admin_role)
def price_list_save(request):
    """``{"note", "items": [...]}`` - a new version of the list (the owner's)."""
    try:
        body = _object(request)
        note = _text(body, "note", 250)
    except BadBody:
        return _error(400, "bad_request")
    try:
        version = pricing.save_version(request.user, body.get("items"), note)
    except b2b.Refused as refusal:
        return _refused(refusal)
    return JsonResponse({"ok": True, "list": _version_json(version)})


@endpoint("POST")
@api_gate(lambda user: user.is_admin_role)
def limits_save(request):
    """``{"sales": "10", "manager": "20"}`` - how far under the list each may go (the owner's)."""
    try:
        body = _object(request)
        sales, manager = pricing.save_limits(request.user, body.get("sales"), body.get("manager"))
    except BadBody:
        return _error(400, "bad_request")
    except b2b.Refused as refusal:
        return _refused(refusal)
    return JsonResponse({"ok": True, "limits": {"sales": f"{sales:.2f}", "manager": f"{manager:.2f}"}})


@endpoint("POST")
@api_gate(b2b.has_door)
def discount_decide(request, quote_id):
    """``{"approved": true|false, "note"}`` - a waiting discount approved or turned down."""
    quote = get_object_or_404(Quotation.objects.select_related("lead", "lead__sheet", "owner"), pk=quote_id)
    if not b2b.may_read(request.user, quote.lead.sheet):
        identity.hidden(request, "quotation")
    try:
        body = _object(request)
        approved = body.get("approved")
        if not isinstance(approved, bool):
            raise BadBody
        note = _text(body, "note", 250)
    except BadBody:
        return _error(400, "bad_request")
    try:
        quote = pricing.decide(quote, request.user, approved, note)
    except b2b.Refused as refusal:
        return _refused(refusal, status=403 if refusal.code == "not_yours" else 400)
    return JsonResponse({"ok": True, "state": quote.discount_state})
