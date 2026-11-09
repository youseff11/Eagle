"""``/api/v1/crm/`` - the CRM sheets of the real-estate branch (09/11/2026).

The rules are ``crm.py``. A refusal is ``{"ok": false, "error": code, "message": words}`` and nothing was written. A sheet
another CRM person holds is a 404 written down (``identity.hidden``): a 403 would say the sheet is there. Anybody off the CRM
team (the whole translation side) is a written-down 403 at every door.
"""

from django.http import JsonResponse
from django.shortcuts import get_object_or_404

from . import clock, crm, identity, services
from .api_v1 import BadBody, _error, _object, endpoint
from .models import CrmContact, CrmSheet, CrmStatus
from .permissions import api_gate


def _refused(refusal, status=400):
    return JsonResponse({"ok": False, "error": refusal.code, "message": refusal.ar, "message_en": refusal.en}, status=status)


def _person(user):
    return {"id": user.pk, "name": user.get_full_name() or user.username} if user else None


def _sheet_or_404(request, sheet_id):
    sheet = get_object_or_404(CrmSheet.objects.select_related("assigned_to", "created_by"), pk=sheet_id)
    if not crm.may_read(request.user, sheet):
        identity.hidden(request, "crm sheet")
    return sheet


def _row_or_404(request, row_id):
    row = get_object_or_404(CrmContact.objects.select_related("sheet"), pk=row_id)
    if not crm.may_read(request.user, row.sheet):
        identity.hidden(request, "crm row")
    return row


def _sheet_json(sheet, numbers):
    return {
        "id": sheet.pk,
        "title": sheet.title,
        "assigned_to": _person(sheet.assigned_to),
        "created_by": _person(sheet.created_by),
        "created_at": clock.fmt12(sheet.created_at, "en", "%d/%m/%Y"),
        "counts": numbers,
    }


def _row_json(row):
    return {"id": row.id, "name": row.name, "phone": row.phone, "status": row.status, "chat": row.client.code if row.client_id else ""}


def _statuses():
    words = {
        CrmStatus.INTERESTED: ("مهتم", "Interested"),
        CrmStatus.NOT_INTERESTED: ("غير مهتم", "Not interested"),
        CrmStatus.QUOTE_REQUESTED: ("طلب عرض سعر", "Asked for a price"),
        CrmStatus.CONTACTED: ("تم التواصل", "Contacted"),
        CrmStatus.NO_ANSWER: ("مردش", "No answer"),
    }
    return [{"value": value, "ar": words[value][0], "en": words[value][1]} for value in CrmStatus.values]


@endpoint("GET")
@api_gate(crm.has_door)
def sheets(request):
    """The sheets this person reads, newest first, with their counts; for the manager and the owner, who a sheet may go to."""
    user = request.user
    rows = list(crm.sheets_for(user).select_related("assigned_to", "created_by"))
    numbers = crm.counts([sheet.pk for sheet in rows])
    return JsonResponse({
        "ok": True,
        "can_manage": user.runs_crm,
        "holders": [_person(person) for person in crm.holders()] if user.runs_crm else [],
        "statuses": _statuses(),
        "sheets": [_sheet_json(sheet, numbers[sheet.pk]) for sheet in rows],
    })


def _holder_id(body):
    raw = body.get("assigned_to")
    if raw is None:
        return None
    if not isinstance(raw, int) or isinstance(raw, bool):
        raise BadBody
    return raw


def _title(body):
    raw = body.get("title")
    if raw is not None and not isinstance(raw, str):
        raise BadBody
    return raw


@endpoint("POST")
@api_gate(crm.has_door)
def sheet_create(request):
    """``{"title", "assigned_to": <id>}`` - the manager makes a sheet for one of the team, or for themself."""
    try:
        body = _object(request)
        sheet = crm.create_sheet(request.user, _title(body), _holder_id(body))
    except BadBody:
        return _error(400, "bad_request")
    except crm.Refused as refusal:
        return _refused(refusal)
    if sheet.assigned_to_id != request.user.pk:
        services.notify(
            sheet.assigned_to,
            title_ar="شيت CRM جديد ليك", title_en="A CRM sheet for you",
            body_ar=f"«{sheet.title}» من {request.user.get_full_name() or request.user.username}.",
            body_en=f"“{sheet.title}” from {request.user.get_full_name() or request.user.username}.",
            level="info", url=f"/app/crm/{sheet.pk}",
        )
    return JsonResponse({"ok": True, "sheet": _sheet_json(sheet, crm.counts([sheet.pk])[sheet.pk])})


@endpoint("GET")
@api_gate(crm.has_door)
def sheet(request, sheet_id):
    """One sheet and its rows."""
    user = request.user
    one = _sheet_or_404(request, sheet_id)
    rows = list(one.contacts.select_related("client"))
    return JsonResponse({
        "ok": True,
        "sheet": _sheet_json(one, crm.counts([one.pk])[one.pk]),
        "rows": [_row_json(row) for row in rows],
        "statuses": _statuses(),
        "can_manage": user.runs_crm,
        "can_contact": crm.may_contact(user, one),
        "holders": [_person(person) for person in crm.holders()] if user.runs_crm else [],
    })


@endpoint("POST")
@api_gate(crm.has_door)
def sheet_save(request, sheet_id):
    """``{"title"?, "assigned_to"?}`` - the manager renames the sheet or hands it to someone else."""
    one = _sheet_or_404(request, sheet_id)
    before = one.assigned_to_id
    try:
        body = _object(request)
        crm.update_sheet(request.user, one, title=_title(body), holder_id=_holder_id(body))
    except BadBody:
        return _error(400, "bad_request")
    except crm.Refused as refusal:
        return _refused(refusal)
    if one.assigned_to_id != before and one.assigned_to_id != request.user.pk:
        services.notify(
            one.assigned_to,
            title_ar="شيت CRM جديد ليك", title_en="A CRM sheet for you",
            body_ar=f"«{one.title}» اتحوّل ليك.", body_en=f"“{one.title}” was handed to you.",
            level="info", url=f"/app/crm/{one.pk}",
        )
    return JsonResponse({"ok": True, "sheet": _sheet_json(one, crm.counts([one.pk])[one.pk])})


@endpoint("POST")
@api_gate(crm.has_door)
def sheet_delete(request, sheet_id):
    one = _sheet_or_404(request, sheet_id)
    try:
        crm.delete_sheet(request.user, one)
    except crm.Refused as refusal:
        return _refused(refusal)
    return JsonResponse({"ok": True})


@endpoint("POST")
@api_gate(crm.has_door)
def rows_add(request, sheet_id):
    """``{"rows": [{"name", "phone", "status"?}...]}`` - the manager adds one row or a pasted list."""
    one = _sheet_or_404(request, sheet_id)
    try:
        body = _object(request)
        made = crm.add_rows(request.user, one, body.get("rows"))
    except BadBody:
        return _error(400, "bad_request")
    except crm.Refused as refusal:
        return _refused(refusal)
    return JsonResponse({"ok": True, "rows": [_row_json(row) for row in made]})


@endpoint("POST")
@api_gate(crm.has_door)
def row_save(request, row_id):
    """``{"status"?, "name"?, "phone"?}`` - the holder sets the status; the manager also corrects the name and the phone."""
    row = _row_or_404(request, row_id)
    try:
        body = _object(request)
        values = {key: body[key] for key in ("status", "name", "phone") if key in body}
        if any(not isinstance(value, str) for value in values.values()):
            raise BadBody
        crm.update_row(request.user, row, values)
    except BadBody:
        return _error(400, "bad_request")
    except crm.Refused as refusal:
        return _refused(refusal)
    return JsonResponse({"ok": True, "row": _row_json(row)})


@endpoint("POST")
@api_gate(crm.has_door)
def row_delete(request, row_id):
    row = _row_or_404(request, row_id)
    try:
        crm.delete_row(request.user, row)
    except crm.Refused as refusal:
        return _refused(refusal)
    return JsonResponse({"ok": True})


@endpoint("POST")
@api_gate(crm.has_door)
def row_whatsapp(request, row_id):
    """The WhatsApp button: which chat to open on this person's own number (``crm.start_whatsapp``); nothing is sent."""
    row = _row_or_404(request, row_id)
    try:
        client = crm.start_whatsapp(row, request.user)
    except crm.Refused as refusal:
        return _refused(refusal)
    return JsonResponse({"ok": True, "chat": client.code, "row": _row_json(row)})
