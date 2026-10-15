"""``/api/v1/b2c/`` - the B2C field visits (15/10/2026).

The rules are ``b2c.py``; the B2C company sheets themselves are the B2B doors (``api_b2b``, a sheet says its team). These
doors read and check the body and say what happened; a refusal is ``{"ok": false, "error": code, "message": words}`` and
nothing was written. A visit that is not the person's is a 404 written down (``identity.hidden``). A visit names a company
and its address, so a list of them is a row in the audit log, as a page of client names is.
"""

from datetime import datetime

from django.db.models import Q
from django.http import JsonResponse
from django.shortcuts import get_object_or_404
from django.utils import timezone

from . import b2c, b2c_board, clock, identity
from .api_v1 import BadBody, _error, _object, _text, endpoint
from .b2b import Refused
from .models import AppSettings, FieldVisit, Lead, LeadPriority
from .permissions import api_gate

#: The most visits one list answers with (a month of a team of field people).
MAX_LIST = 1500


def _refused(refusal, status=400):
    return JsonResponse({"ok": False, "error": refusal.code, "message": refusal.ar, "message_en": refusal.en}, status=status)


def _stamp(value):
    return clock.fmt12(value, "en", "%d/%m/%Y") if value else ""


def _person(user):
    return {"id": user.pk, "name": user.get_full_name() or user.username} if user else None


def _number(value):
    return None if value is None else float(value)


def _visit_json(visit, user):
    lead = visit.lead
    return {
        "id": visit.pk,
        "code": visit.code,
        "status": visit.status,
        "lead": {
            "id": lead.pk,
            "company_name": lead.company_name,
            "governorate": lead.governorate,
            "address": lead.address,
            "sheet": lead.sheet_id,
            "has_place": lead.latitude is not None,
            "map_link": b2c.map_link(lead.latitude, lead.longitude),
        },
        "person": _person(visit.person),
        "planned_at": _stamp(visit.planned_at),
        "planned_day": timezone.localtime(visit.planned_at).date().isoformat() if visit.planned_at else "",
        "purpose": visit.purpose,
        "check_in_at": _stamp(visit.check_in_at),
        "check_in_distance": visit.check_in_distance,
        "check_in_accuracy": visit.check_in_accuracy,
        "check_in_map": b2c.map_link(visit.check_in_lat, visit.check_in_lng),
        "check_out_at": _stamp(visit.check_out_at),
        "check_out_distance": visit.check_out_distance,
        "check_out_accuracy": visit.check_out_accuracy,
        "check_out_map": b2c.map_link(visit.check_out_lat, visit.check_out_lng),
        "minutes": visit.minutes,
        "no_location_reason": visit.no_location_reason,
        "outcome": visit.outcome,
        "met": visit.met,
        "interest": visit.interest,
        "summary": visit.summary,
        "next_step": visit.next_step,
        "next_step_on": visit.next_step_on.isoformat() if visit.next_step_on else "",
        "flags": list(visit.flags or []),
        "escalated": visit.escalated,
        "escalation_note": visit.escalation_note,
        "decided_by": _person(visit.decided_by),
        "decided_at": _stamp(visit.decided_at),
        "decision_note": visit.decision_note,
        "mine": visit.person_id == user.pk,
        "can_decide": visit.status == FieldVisit.Status.PENDING and b2c._may_decide(user, visit),
        "can_escalate": visit.status == FieldVisit.Status.PENDING and not visit.escalated and not user.is_admin_role
        and b2c._may_decide(user, visit),
        # The objection (part 4): once, by the person, to a turned-down visit; the owner decides it for good.
        "appeal_note": visit.appeal_note,
        "appealed_from": visit.appealed_from,
        "appealed_at": _stamp(visit.appealed_at),
        "can_appeal": visit.person_id == user.pk and visit.status == FieldVisit.Status.REJECTED and visit.appealed_at is None,
    }


def _visit_or_404(request, visit_id):
    visit = get_object_or_404(FieldVisit.objects.select_related("lead", "person", "decided_by"), pk=visit_id)
    if not b2c.may_see(request.user, visit):
        identity.hidden(request, "field visit")
    return visit


def _month(value):
    if not value:
        return b2c.month_first()
    try:
        return datetime.strptime(value, "%Y-%m").date().replace(day=1)
    except ValueError:
        raise BadBody from None


def _choices():
    return {
        "outcomes": [{"value": value, "label": label} for value, label in FieldVisit.Outcome.choices],
        "interests": [{"value": value, "label": label} for value, label in LeadPriority.choices],
        "flags": [{"value": key, "ar": ar, "en": en} for key, (ar, en) in b2c.FLAGS.items()],
    }


@endpoint("GET")
@api_gate(b2c.has_visit_door)
def visits(request):
    """``?month=YYYY-MM`` - the month's visits (a field person's own, the team's for the manager and the owner), the board
    of each person against the target, and what the page needs to say the rules."""
    try:
        first = _month(request.GET.get("month", ""))
    except BadBody:
        return _error(400, "bad_month")
    user = request.user
    board = b2c.board(user, first)
    days = b2c.month_days(first)
    start = timezone.make_aware(datetime.combine(first, datetime.min.time()))
    end = timezone.make_aware(datetime.combine(days[-1], datetime.max.time()))
    rows = b2c.visits_for(user).filter(
        # The month's, and whatever is still open or waiting whenever it was planned: nothing waits out of sight.
        (
            Q(check_in_at__range=(start, end))
            | Q(check_in_at__isnull=True, planned_at__range=(start, end))
            | Q(check_in_at__isnull=True, planned_at__isnull=True, created_at__range=(start, end))
            | Q(status__in=(FieldVisit.Status.PLANNED, FieldVisit.Status.CHECKED_IN, FieldVisit.Status.PENDING))
        )
    )[:MAX_LIST]
    rows = list(rows)
    if rows:
        identity.audit(request, user, identity.IDENTITY_LIST, "b2c visits", f"{len(rows)} visits")
    conf = AppSettings.load()
    return JsonResponse({
        "ok": True,
        "month": f"{first:%Y-%m}",
        "can_manage": b2c.manages(user),
        "field": user.is_field_sales,
        "rules": {
            "target": conf.b2c_visit_target, "work_days": conf.b2c_work_days,
            "radius_m": conf.b2c_visit_radius_m, "accuracy_m": conf.b2c_gps_accuracy_m,
        },
        "board": board,
        "visits": [_visit_json(visit, user) for visit in rows],
        **_choices(),
    })


@endpoint("GET")
@api_gate(b2c.has_visit_door)
def leads(request):
    """``?q=`` - the B2C companies a visit may be made to (a field person's own; the field team's for the manager)."""
    found = b2c.visit_leads(request.user, request.GET.get("q", ""))
    if found:
        identity.audit(request, request.user, identity.IDENTITY_LIST, "b2c visit companies", f"{len(found)} companies")
    return JsonResponse({
        "ok": True,
        "items": [
            {
                "id": lead.pk, "company_name": lead.company_name, "governorate": lead.governorate, "address": lead.address,
                "has_place": lead.latitude is not None, "person": _person(lead.sheet.assigned_to),
            }
            for lead in found
        ],
    })


def _planned_at(value):
    """A planned time from the page (``YYYY-MM-DDTHH:MM``, Cairo), or ``None``."""
    if value in ("", None):
        return None
    if not isinstance(value, str) or len(value) > 25:
        raise BadBody
    try:
        moment = datetime.fromisoformat(value)
    except ValueError:
        raise BadBody from None
    return timezone.make_aware(moment) if timezone.is_naive(moment) else moment


@endpoint("POST")
@api_gate(b2c.has_visit_door)
def visit_new(request):
    """``{"lead": <id>, "planned_at", "purpose"}`` - a visit to a company on a field person's B2C sheet."""
    try:
        body = _object(request)
        raw = body.get("lead")
        if not isinstance(raw, int) or isinstance(raw, bool):
            raise BadBody
        planned_at = _planned_at(body.get("planned_at"))
        purpose = _text(body, "purpose", b2c.MAX_TEXT)
    except BadBody:
        return _error(400, "bad_request")
    lead = Lead.objects.select_related("sheet", "sheet__assigned_to").filter(pk=raw).first()
    if lead is None or not b2c.visit_leads_q(request.user).filter(pk=lead.pk).exists():
        identity.hidden(request, "b2c lead")
    try:
        visit = b2c.plan(lead, lead.sheet.assigned_to, request.user, planned_at=planned_at, purpose=purpose)
    except Refused as refusal:
        return _refused(refusal)
    return JsonResponse({"ok": True, "visit": _visit_json(visit, request.user)})


def _place(body):
    """``(lat, lng, accuracy, reason)`` of one press; numbers or nothing, anything else ``BadBody``."""
    values = []
    for name in ("lat", "lng", "accuracy"):
        value = body.get(name)
        if value is not None and (isinstance(value, bool) or not isinstance(value, (int, float))):
            raise BadBody
        values.append(value)
    return (*values, _text(body, "reason", b2c.MAX_TEXT))


@endpoint("POST")
@api_gate(b2c.has_visit_door)
def visit_check_in(request, visit_id):
    """``{"lat", "lng", "accuracy"}`` read by the phone once at the press, or ``{"reason"}`` when it gave none."""
    visit = _visit_or_404(request, visit_id)
    try:
        lat, lng, accuracy, reason = _place(_object(request))
    except BadBody:
        return _error(400, "bad_request")
    try:
        visit = b2c.check_in(visit, request.user, lat=lat, lng=lng, accuracy=accuracy, reason=reason)
    except Refused as refusal:
        return _refused(refusal)
    return JsonResponse({"ok": True, "visit": _visit_json(_visit_or_404(request, visit.pk), request.user)})


@endpoint("POST")
@api_gate(b2c.has_visit_door)
def visit_check_out(request, visit_id):
    """The second press and the report: ``{"lat", "lng", "accuracy" | "reason", "outcome", "met", "interest", "summary",
    "next_step", "next_step_on"}``."""
    visit = _visit_or_404(request, visit_id)
    try:
        body = _object(request)
        lat, lng, accuracy, reason = _place(body)
        report = {
            "outcome": _text(body, "outcome", 20),
            "met": _text(body, "met", 160),
            "interest": _text(body, "interest", 10),
            "summary": _text(body, "summary", b2c.MAX_SUMMARY),
            "next_step": _text(body, "next_step", b2c.MAX_TEXT),
            "next_step_on": b2c.parse_day(body.get("next_step_on")),
        }
    except (BadBody, ValueError):
        return _error(400, "bad_request")
    try:
        visit = b2c.check_out(visit, request.user, report, lat=lat, lng=lng, accuracy=accuracy, reason=reason)
    except Refused as refusal:
        return _refused(refusal)
    return JsonResponse({"ok": True, "visit": _visit_json(_visit_or_404(request, visit.pk), request.user)})


@endpoint("POST")
@api_gate(b2c.has_visit_door)
def visit_cancel(request, visit_id):
    visit = _visit_or_404(request, visit_id)
    try:
        b2c.cancel(visit, request.user)
    except Refused as refusal:
        return _refused(refusal)
    return JsonResponse({"ok": True})


@endpoint("POST")
@api_gate(b2c.has_visit_door)
def visit_decide(request, visit_id):
    """``{"verified": true|false, "note"}`` - the manager's decision (the owner's, for a visit handed to them)."""
    visit = _visit_or_404(request, visit_id)
    try:
        body = _object(request)
        verified = body.get("verified")
        if not isinstance(verified, bool):
            raise BadBody
        note = _text(body, "note", b2c.MAX_NOTE)
    except BadBody:
        return _error(400, "bad_request")
    try:
        visit = b2c.decide(visit, request.user, verified, note)
    except Refused as refusal:
        return _refused(refusal, status=403 if refusal.code == "not_yours" else 400)
    return JsonResponse({"ok": True, "visit": _visit_json(_visit_or_404(request, visit.pk), request.user)})


@endpoint("POST")
@api_gate(b2c.manages)
def visits_verify_clean(request):
    """``{"ids": [...]}`` - verify the ones among them that have nothing to look at; the answer says how many."""
    try:
        ids = _object(request).get("ids")
        if not isinstance(ids, list) or len(ids) > 500 or not all(isinstance(i, int) and not isinstance(i, bool) for i in ids):
            raise BadBody
    except BadBody:
        return _error(400, "bad_request")
    return JsonResponse({"ok": True, "verified": b2c.verify_clean(request.user, ids)})


@endpoint("POST")
@api_gate(b2c.has_visit_door)
def visit_appeal(request, visit_id):
    """``{"note"}`` - the field person objects to a turned-down visit, once; the owner decides it for good."""
    visit = _visit_or_404(request, visit_id)
    try:
        note = _text(_object(request), "note", b2c.MAX_NOTE)
    except BadBody:
        return _error(400, "bad_request")
    try:
        visit = b2c.appeal(visit, request.user, note)
    except Refused as refusal:
        return _refused(refusal, status=403 if refusal.code == "not_yours" else 400)
    return JsonResponse({"ok": True, "visit": _visit_json(_visit_or_404(request, visit.pk), request.user)})


@endpoint("POST")
@api_gate(b2c.manages)
def visit_escalate(request, visit_id):
    """``{"note"}`` - the manager hands a doubtful visit to the owner."""
    visit = _visit_or_404(request, visit_id)
    try:
        note = _text(_object(request), "note", b2c.MAX_NOTE)
    except BadBody:
        return _error(400, "bad_request")
    try:
        visit = b2c.escalate(visit, request.user, note)
    except Refused as refusal:
        return _refused(refusal, status=403 if refusal.code == "not_yours" else 400)
    return JsonResponse({"ok": True, "visit": _visit_json(_visit_or_404(request, visit.pk), request.user)})


# ---------------------------------------------------------------------------
# The B2C numbers (part 2): b2c_board.py
# ---------------------------------------------------------------------------

def _board_query(request):
    """``(start, end, filters)`` from ``?from&to&person&source&governorate``. ``BadBody`` for a period that is not one, or
    a person the reader may not read."""
    from .api_b2b import _period

    start, end = _period(request)
    person = None
    raw = request.GET.get("person", "")
    if raw:
        if not raw.isdigit():
            raise BadBody
        person = next((one for one in b2c_board.team(request.user) if one.pk == int(raw)), None)
        if person is None:
            raise BadBody
    source = request.GET.get("source", "")[:120]
    governorate = request.GET.get("governorate", "")[:80]
    return start, end, b2c_board.Filters(person, source, governorate)


def _board_answer(request):
    start, end, filters = _board_query(request)
    answer = b2c_board.board(request.user, start, end, filters)
    named = len(answer["untouched"]) + len(answer["overdue"]) + len(answer["rejected"])
    if named:
        # The lists name companies: one row in the log, as a page of client names is.
        identity.audit(request, request.user, identity.IDENTITY_LIST, "b2c board", f"{named} companies")
    return start, end, filters, answer


@endpoint("GET")
@api_gate(b2c_board.has_door)
def board(request):
    """The B2C numbers for a period: a Sales person's own, the team's for the B2C manager and the owner (``b2c_board``)."""
    try:
        start, end, filters, answer = _board_answer(request)
    except BadBody:
        return _error(400, "bad_filter")
    return JsonResponse({
        "ok": True,
        "from": start.isoformat(),
        "to": end.isoformat(),
        "team": b2c.manages(request.user),
        "filters": b2c_board.choices(request.user, filters),
        **answer,
    })


@endpoint("GET")
@api_gate(b2c_board.has_door)
def board_export(request):
    """The board's table as a CSV file Excel opens (UTF-8 with its mark): one row per person and the team's total. Names
    of the Sales people only, never a company's."""
    import csv
    import io

    from django.http import HttpResponse

    from . import services

    try:
        start, end, filters = _board_query(request)
    except BadBody:
        return _error(400, "bad_filter")
    answer = b2c_board.board(request.user, start, end, filters)
    out = io.StringIO()
    writer = csv.writer(out)
    writer.writerows(b2c_board.export_rows(answer, request.user.ui_lang))
    services.log(request.user, "b2c.export", "b2c board", f"{start}..{end} {len(answer['rows'])} rows")
    response = HttpResponse("\ufeff" + out.getvalue(), content_type="text/csv; charset=utf-8")
    response["Content-Disposition"] = f'attachment; filename="b2c-{start}-{end}.csv"'
    return response
