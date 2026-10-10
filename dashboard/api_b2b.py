"""``/api/v1/b2b/`` - the B2B company sheets (10/10/2026).

The rules are ``b2b.py``: who reads a sheet, who makes and hands them over, who contacts a company from its row. These doors
read and check the body and say what happened; a refusal is ``{"ok": false, "error": code, "message": words}`` and nothing
was written.

A sheet another Sales person holds is a 404 written down (``identity.hidden``), like a client code that is not one's own: a
403 would say the sheet is there. A person with no door at all (the operation, the translators...) is a written-down 403.
Opening a sheet or a row draws companies and their people, so it is a row in the audit log, as a page of client names is;
the list of sheets carries titles and counts only.
"""

import json
from datetime import date, datetime
from decimal import Decimal, InvalidOperation

from django.db import transaction
from django.db.models import Count, Q
from django.http import JsonResponse
from django.shortcuts import get_object_or_404
from django.utils import timezone

from . import b2b, clock, identity, services
from .api_v1 import BadBody, _error, _object, _text, endpoint
from .models import Lead, LeadActivity, LeadSheet, LeadStatus, Quotation
from .permissions import api_gate

#: The longest title and note of a sheet.
MAX_TITLE = 160
MAX_SHEET_NOTE = 2000
#: The largest JSON body these doors read: a paste of 500 rows of 13 columns.
MAX_PASTE_BODY = 2 * 1024 * 1024
#: The most activities a row's timeline answers with.
MAX_TIMELINE = 200


def _refused(refusal, status=400):
    return JsonResponse({"ok": False, "error": refusal.code, "message": refusal.ar, "message_en": refusal.en}, status=status)


def _stamp(value):
    return clock.fmt12(value, "en", "%d/%m/%Y") if value else ""


def _person(user):
    return {"id": user.pk, "name": user.get_full_name() or user.username} if user else None


def _sheet_or_404(request, sheet_id):
    sheet = get_object_or_404(LeadSheet.objects.select_related("assigned_to", "created_by"), pk=sheet_id)
    if not b2b.may_read(request.user, sheet):
        identity.hidden(request, "lead sheet")
    return sheet


def _lead_or_404(request, lead_id):
    lead = get_object_or_404(Lead.objects.select_related("sheet", "sheet__assigned_to", "client"), pk=lead_id)
    if not b2b.may_read(request.user, lead.sheet):
        identity.hidden(request, "lead")
    return lead


def _sheet_json(sheet, user, rows=None, contacted=None):
    return {
        "id": sheet.pk,
        "title": sheet.title,
        "note": sheet.note,
        "assigned_to": _person(sheet.assigned_to),
        "created_by": _person(sheet.created_by),
        "created_at": _stamp(sheet.created_at),
        "rows": rows if rows is not None else sheet.leads.count(),
        "contacted": contacted if contacted is not None else sheet.leads.filter(_contacted_q()).count(),
        "can_manage": user.manages_sales,
        "can_contact": b2b.may_contact(user, sheet),
    }


def _contacted_q():
    return Q(whatsapp_at__isnull=False) | Q(email_at__isnull=False) | Q(call_at__isnull=False)


def _lead_json(lead, today=None):
    state = b2b.follow_up_state(lead, today)
    return {
        "id": lead.pk,
        **{name: getattr(lead, name) for name, *_rest in b2b.COLUMNS},
        "status": lead.status,
        "next_follow_up": lead.next_follow_up.isoformat() if lead.next_follow_up else "",
        "notes": lead.notes,
        "client_code": lead.client.code if lead.client_id else "",
        "whatsapp_at": _stamp(lead.whatsapp_at),
        "email_at": _stamp(lead.email_at),
        "call_at": _stamp(lead.call_at),
        "last_contact_at": _stamp(lead.last_contact_at),
        "replied_at": _stamp(lead.replied_at),
        "last_outreach_at": _stamp(lead.last_outreach_at),
        # "" (none), "upcoming", "today", "overdue" or "done" (reached out on or after the day): ``b2b.follow_up_state``.
        "follow_up": state,
        "overdue": state == b2b.FOLLOW_UP_OVERDUE,
        "quote": _quote_brief(lead),
    }


def _quote_brief(lead):
    """The row's newest quotation, in a word: its code, where it stands and its total."""
    newest = next(iter(lead.quotations.all()), None)
    if newest is None:
        return None
    return {"code": newest.code, "status": newest.status, "total": f"{newest.total:.2f}", "currency": newest.currency}


def _activity_json(row):
    return {
        "id": row.pk,
        "kind": row.kind,
        "automatic": row.automatic,
        "incoming": row.incoming,
        "status": row.status,
        "quotation": row.quotation.code if row.quotation_id else "",
        "at": _stamp(row.at),
        "by": _person(row.by),
        "outcome": row.outcome,
        "duration_minutes": row.duration_minutes,
        "notes": row.notes,
    }


def _choices():
    return {
        "columns": [{"name": name, "ar": ar, "en": en, "max": limit} for name, limit, ar, en in b2b.COLUMNS],
        "statuses": [{"value": value, "label": label} for value, label in LeadStatus.choices],
        "outcomes": [{"value": value, "label": label} for value, label in LeadActivity.Outcome.choices],
    }


# ---------------------------------------------------------------------------
# Sheets
# ---------------------------------------------------------------------------

@endpoint("GET")
@api_gate(b2b.has_door)
def sheets(request):
    """The sheets this person reads, newest first, and - for the manager and the owner - who a sheet may be given to."""
    user = request.user
    rows = b2b.sheets_for(user).annotate(
        row_count=Count("leads", distinct=True),
        contacted_count=Count("leads", filter=Q(leads__whatsapp_at__isnull=False) | Q(leads__email_at__isnull=False)
                              | Q(leads__call_at__isnull=False), distinct=True),
    )
    return JsonResponse({
        "ok": True,
        "can_manage": user.manages_sales,
        "sales": [_person(p) for p in b2b.sales_people()] if user.manages_sales else [],
        "sheets": [_sheet_json(s, user, s.row_count, s.contacted_count) for s in rows],
    })


def _sheet_fields(body):
    """``(title, note, assigned_to)`` from the body. ``BadBody`` for a body of the wrong shape, ``Refused`` for a value."""
    title = _text(body, "title", MAX_TITLE)
    note = _text(body, "note", MAX_SHEET_NOTE)
    raw = body.get("assigned_to")
    if not title:
        raise b2b.Refused("no_title", "اكتب اسم للشيت.", "Give the sheet a name.")
    if not isinstance(raw, int) or isinstance(raw, bool):
        raise b2b.Refused("no_sales", "اختار الـSales اللي هياخد الشيت.", "Choose the Sales person who gets the sheet.")
    person = b2b.sales_people().filter(pk=raw).first()
    if person is None:
        raise b2b.Refused("no_sales", "اختار الـSales اللي هياخد الشيت.", "Choose the Sales person who gets the sheet.")
    return title, note, person


def _notify_assigned(sheet, actor):
    if sheet.assigned_to_id == actor.pk:
        return
    services.notify(
        sheet.assigned_to,
        title_ar="شيت شركات جديد ليك",
        title_en="A company sheet for you",
        body_ar=f"«{sheet.title}» من {actor.get_full_name() or actor.username}. املاه واتواصل مع الشركات من الصفحة.",
        body_en=f"“{sheet.title}” from {actor.get_full_name() or actor.username}. Fill it in and contact the companies from it.",
        level="info", url=f"/app/leads/{sheet.pk}",
    )


@endpoint("POST")
@api_gate(lambda user: user.manages_sales)
def sheet_create(request):
    """``{"title", "note", "assigned_to": <id>}`` - the manager makes a sheet for one Sales person."""
    try:
        title, note, person = _sheet_fields(_object(request))
    except BadBody:
        return _error(400, "bad_request")
    except b2b.Refused as refusal:
        return _refused(refusal)
    sheet = LeadSheet.objects.create(title=title, note=note, assigned_to=person, created_by=request.user)
    services.log(request.user, "b2b.sheet_create", f"sheet {sheet.pk}", f"{title} -> {person.username}")
    _notify_assigned(sheet, request.user)
    return JsonResponse({"ok": True, "sheet": _sheet_json(sheet, request.user)})


@endpoint("POST")
@api_gate(b2b.has_door)
def sheet_save(request, sheet_id):
    """The manager renames a sheet, rewrites its note or hands it to another Sales person."""
    sheet = _sheet_or_404(request, sheet_id)
    if not request.user.manages_sales:
        return _error(403, "forbidden")
    try:
        title, note, person = _sheet_fields(_object(request))
    except BadBody:
        return _error(400, "bad_request")
    except b2b.Refused as refusal:
        return _refused(refusal)
    before = sheet.assigned_to
    sheet.title, sheet.note, sheet.assigned_to = title, note, person
    sheet.save(update_fields=["title", "note", "assigned_to"])
    if before.pk != person.pk:
        services.log(request.user, "b2b.sheet_reassign", f"sheet {sheet.pk}", f"{before.username} -> {person.username}")
        _notify_assigned(sheet, request.user)
    return JsonResponse({"ok": True, "sheet": _sheet_json(sheet, request.user)})


@endpoint("POST")
@api_gate(b2b.has_door)
def sheet_delete(request, sheet_id):
    """The manager deletes a sheet - only one nobody has contacted a company from: the history of a contact is kept."""
    sheet = _sheet_or_404(request, sheet_id)
    if not request.user.manages_sales:
        return _error(403, "forbidden")
    if sheet.leads.filter(_contacted_q()).exists():
        return _refused(b2b.Refused(
            "contacted", "فيه شركات في الشيت ده اتواصلنا معاها، فمش هيتمسح. غيّر حالتها بدل المسح.",
            "Some companies on this sheet were contacted, so it is kept. Change their status instead.",
        ))
    services.log(request.user, "b2b.sheet_delete", f"sheet {sheet.pk}", sheet.title)
    sheet.delete()
    return JsonResponse({"ok": True})


@endpoint("GET")
@api_gate(b2b.has_door)
def sheet(request, sheet_id):
    """One sheet and all of its rows."""
    sheet = _sheet_or_404(request, sheet_id)
    leads = list(sheet.leads.select_related("client").prefetch_related("quotations"))
    contacted = sum(1 for lead in leads if lead.contacted)
    # The companies and their people are drawn here: one row in the log for the sheet, as for a page of client names.
    if leads:
        identity.audit(request, request.user, identity.IDENTITY_LIST, f"sheet {sheet.pk}", f"{len(leads)} companies")
    today = timezone.localdate()
    manager = request.user.manages_sales
    return JsonResponse({
        "ok": True,
        "sheet": _sheet_json(sheet, request.user, len(leads), contacted),
        "sales": [_person(p) for p in b2b.sales_people()] if manager else [],
        # Where the manager may move a company to: the other sheets.
        "sheets": [
            {"id": other.pk, "title": other.title, "assigned_to": _person(other.assigned_to)}
            for other in b2b.sheets_for(request.user).exclude(pk=sheet.pk).filter(assigned_to__in=b2b.sales_people())
        ] if manager else [],
        "leads": [_lead_json(lead, today) for lead in leads],
        **_choices(),
    })


@endpoint("GET")
@api_gate(b2b.has_door)
def follow_ups(request):
    """The follow-ups due today or late: a Sales person's own, the team's for the manager and the owner. Companies and their
    people are drawn, so it is a row in the log when there are any."""
    today = timezone.localdate()
    rows = b2b.follow_ups_for(request.user, today)
    if rows:
        identity.audit(request, request.user, identity.IDENTITY_LIST, "b2b follow-ups", f"{len(rows)} companies")
    return JsonResponse({
        "ok": True,
        "today": today.isoformat(),
        "items": [
            {
                **_lead_json(lead, today),
                "sheet": {"id": lead.sheet_id, "title": lead.sheet.title},
                "sales": _person(lead.sheet.assigned_to),
            }
            for lead in rows
        ],
    })


# ---------------------------------------------------------------------------
# Rows
# ---------------------------------------------------------------------------

def _row_values(item):
    """The columns of one row from the body: every value a string within its column's length, the company named."""
    if not isinstance(item, dict):
        raise BadBody
    return {name: _text(item, name, limit) for name, limit in b2b.COLUMN_LIMITS.items()}


def _parse_date(value):
    if value in ("", None):
        return None
    if not isinstance(value, str):
        raise BadBody
    try:
        return date.fromisoformat(value)
    except ValueError:
        raise BadBody from None


@endpoint("POST")
@api_gate(b2b.has_door)
def rows_add(request, sheet_id):
    """``{"rows": [{column: value, ...}, ...]}`` - one row typed, or a block pasted from a spreadsheet. Rows with no company
    name are skipped (an empty line at the end of a paste), and the answer says how many went in."""
    sheet = _sheet_or_404(request, sheet_id)
    if int(request.META.get("CONTENT_LENGTH") or 0) > MAX_PASTE_BODY:
        return _error(400, "too_big")
    try:
        if not (request.content_type or "").startswith("application/json"):
            raise BadBody
        body = json.loads(request.body or b"{}")
        if not isinstance(body, dict):
            raise BadBody
        raw = body.get("rows")
        if not isinstance(raw, list) or not 0 < len(raw) <= b2b.MAX_PASTE_ROWS:
            raise BadBody
        rows = [_row_values(item) for item in raw]
    except (BadBody, ValueError, RecursionError, UnicodeDecodeError):
        return _error(400, "bad_request")
    rows = [values for values in rows if values["company_name"]]
    if not rows:
        return _refused(b2b.Refused("no_company", "كل صف لازم يبقى فيه اسم الشركة.", "Every row needs a company name."))
    with transaction.atomic():
        LeadSheet.objects.select_for_update().filter(pk=sheet.pk).first()
        if sheet.leads.count() + len(rows) > b2b.MAX_SHEET_ROWS:
            return _refused(b2b.Refused(
                "sheet_full", f"الشيت مايشيلش أكتر من {b2b.MAX_SHEET_ROWS} شركة. اعمل شيت تاني.",
                f"A sheet holds at most {b2b.MAX_SHEET_ROWS} companies. Make another sheet.",
            ))
        made = [Lead(sheet=sheet, created_by=request.user, **values) for values in rows]
        for lead in made:
            lead.save()
    services.log(request.user, "b2b.rows_add", f"sheet {sheet.pk}", f"{len(made)} row(s)")
    return JsonResponse({"ok": True, "added": len(made), "leads": [_lead_json(lead) for lead in made]})


@endpoint("GET")
@api_gate(b2b.has_door)
def lead(request, lead_id):
    """One row and its timeline: the messages that reached the company, the calls."""
    lead = _lead_or_404(request, lead_id)
    identity.audit(request, request.user, identity.IDENTITY_VIEW, f"lead {lead.pk}", "b2b sheet row")
    return JsonResponse({
        "ok": True,
        "lead": _lead_json(lead),
        "activities": [_activity_json(a) for a in lead.activities.select_related("by", "quotation")[:MAX_TIMELINE]],
        "can_contact": b2b.may_contact(request.user, lead.sheet),
    })


@endpoint("POST")
@api_gate(b2b.has_door)
def lead_save(request, lead_id):
    """The row's columns, its status, its next follow-up and its notes. What the system stamps (the contact times) is not
    a field here."""
    lead = _lead_or_404(request, lead_id)
    try:
        body = _object(request)
        values = _row_values(body)
        status = _text(body, "status", 20) or LeadStatus.NEW
        notes = _text(body, "notes", b2b.MAX_NOTES)
        follow_up = _parse_date(body.get("next_follow_up", ""))
    except BadBody:
        return _error(400, "bad_request")
    if status not in LeadStatus.values:
        return _error(400, "bad_request")
    if not values["company_name"]:
        return _refused(b2b.Refused("no_company", "اكتب اسم الشركة.", "Write the company name."))
    before = lead.status
    for name, value in values.items():
        setattr(lead, name, value)
    lead.status, lead.notes, lead.next_follow_up = status, notes, follow_up
    lead.save()
    # On the timeline and in the log: what the Sales numbers count meetings, proposals, won and lost by.
    b2b.note_status(lead, before, status, request.user)
    return JsonResponse({"ok": True, "lead": _lead_json(lead)})


def _period(request):
    """``(start, end)`` from ``?from=YYYY-MM-DD&to=YYYY-MM-DD``; this month so far when they are not given. ``BadBody``
    for a date that is not one, an end before the start, or more than ``b2b.MAX_KPI_DAYS`` days."""
    today = timezone.localdate()
    try:
        start = date.fromisoformat(request.GET["from"]) if request.GET.get("from") else today.replace(day=1)
        end = date.fromisoformat(request.GET["to"]) if request.GET.get("to") else today
    except ValueError:
        raise BadBody from None
    if end < start or (end - start).days >= b2b.MAX_KPI_DAYS:
        raise BadBody
    return start, end


@endpoint("GET")
@api_gate(b2b.has_door)
def kpis(request):
    """The Sales numbers for a period: a Sales person's own, every Sales person's for the manager and the owner, and the
    team's total. Counts and rates only - no company is named here."""
    try:
        start, end = _period(request)
    except BadBody:
        return _error(400, "bad_period")
    rows, total = b2b.kpis(request.user, start, end)
    return JsonResponse({
        "ok": True,
        "from": start.isoformat(),
        "to": end.isoformat(),
        "team": request.user.manages_sales,
        "rows": rows,
        "total": total,
    })


@endpoint("POST")
@api_gate(b2b.has_door)
def lead_move(request, lead_id):
    """``{"sheet": <id>}`` - the manager moves a company to another sheet, and so to that sheet's Sales person."""
    lead = _lead_or_404(request, lead_id)
    try:
        target = _object(request).get("sheet")
    except BadBody:
        return _error(400, "bad_request")
    if not isinstance(target, int) or isinstance(target, bool):
        return _error(400, "bad_request")
    sheet = b2b.sheets_for(request.user).filter(pk=target).first()
    if sheet is None:
        return _error(404, "not_found")
    try:
        b2b.move_lead(lead, sheet, request.user)
    except b2b.Refused as refusal:
        return _refused(refusal, status=403 if refusal.code == "not_manager" else 400)
    return JsonResponse({"ok": True, "lead": _lead_json(lead)})


@endpoint("POST")
@api_gate(b2b.has_door)
def lead_delete(request, lead_id):
    """Take a row off - only one nobody contacted: a company we have talked to keeps its history (mark it Lost)."""
    lead = _lead_or_404(request, lead_id)
    if lead.contacted:
        return _refused(b2b.Refused(
            "contacted", "الشركة دي اتواصلنا معاها، فمش هتتمسح. غيّر حالتها لـLost.",
            "This company was contacted, so it is kept. Set its status to Lost.",
        ))
    services.log(request.user, "b2b.lead_delete", f"lead {lead.pk}", lead.company_name[:120])
    lead.delete()
    return JsonResponse({"ok": True})


# ---------------------------------------------------------------------------
# Contacting from the row
# ---------------------------------------------------------------------------

@endpoint("POST")
@api_gate(b2b.has_door)
def lead_whatsapp(request, lead_id):
    """The WhatsApp button: send the opening template when one is needed, and say which conversation to open."""
    lead = _lead_or_404(request, lead_id)
    try:
        client, sent = b2b.start_whatsapp(lead, request.user)
    except b2b.Refused as refusal:
        return _refused(refusal)
    lead.refresh_from_db()
    return JsonResponse({"ok": True, "sent": sent, "chat": client.code, "lead": _lead_json(lead)})


@endpoint("POST")
@api_gate(b2b.has_door)
def lead_email(request, lead_id):
    """``{"subject", "body"}`` - the e-mail button: a letter from this person's own address."""
    lead = _lead_or_404(request, lead_id)
    try:
        body = _object(request)
        subject = _text(body, "subject", b2b.MAX_SUBJECT)
        letter = _text(body, "body", b2b.MAX_LETTER)
    except BadBody:
        return _error(400, "bad_request")
    try:
        b2b.send_email(lead, request.user, subject, letter)
    except b2b.Refused as refusal:
        return _refused(refusal)
    lead.refresh_from_db()
    return JsonResponse({"ok": True, "lead": _lead_json(lead)})


#: The longest call one may write down, in minutes.
MAX_CALL_MINUTES = 600


@endpoint("POST")
@api_gate(b2b.has_door)
def lead_call(request, lead_id):
    """``{"outcome", "notes", "duration_minutes", "at": "YYYY-MM-DDTHH:MM" (Cairo, optional), "next_follow_up"}``."""
    lead = _lead_or_404(request, lead_id)
    try:
        body = _object(request)
        outcome = _text(body, "outcome", 20)
        notes = _text(body, "notes", b2b.MAX_NOTES)
        follow_up = _parse_date(body.get("next_follow_up", ""))
        duration = body.get("duration_minutes")
        if duration in ("", None):
            duration = None
        elif not isinstance(duration, int) or isinstance(duration, bool) or not 0 <= duration <= MAX_CALL_MINUTES:
            raise BadBody
        at = _text(body, "at", 20)
        if at:
            try:
                at = datetime.fromisoformat(at)
            except ValueError:
                raise BadBody from None
            # Typed on the page in Cairo time, as every time on the site is.
            if timezone.is_naive(at):
                at = timezone.make_aware(at)
        else:
            at = None
    except BadBody:
        return _error(400, "bad_request")
    try:
        b2b.log_call(lead, request.user, outcome=outcome, notes=notes, duration=duration, at=at, next_follow_up=follow_up)
    except b2b.Refused as refusal:
        return _refused(refusal)
    lead.refresh_from_db()
    return JsonResponse({"ok": True, "lead": _lead_json(lead)})


# ---------------------------------------------------------------------------
# Quotations (part 4)
# ---------------------------------------------------------------------------

#: The longest payment terms and words to the company a quotation keeps.
MAX_TERMS = 250
MAX_QUOTE_NOTES = 4000


def _quote_or_404(request, quote_id):
    quote = get_object_or_404(Quotation.objects.select_related("lead", "lead__sheet", "lead__client", "task"), pk=quote_id)
    if not b2b.may_read(request.user, quote.lead.sheet):
        identity.hidden(request, "quotation")
    return quote


def _quote_json(quote):
    return {
        "id": quote.pk,
        "code": quote.code,
        "status": quote.status,
        "source_lang": quote.source_lang,
        "target_lang": quote.target_lang,
        "service": quote.service,
        "unit": quote.unit,
        "quantity": quote.quantity,
        "rate": f"{quote.rate.normalize():f}",
        "discount_percent": f"{quote.discount_percent.normalize():f}",
        "total": f"{quote.total:.2f}",
        "currency": quote.currency,
        "deadline": quote.deadline.isoformat() if quote.deadline else "",
        "payment_terms": quote.payment_terms,
        "notes": quote.notes,
        "created_at": _stamp(quote.created_at),
        "sent_at": _stamp(quote.sent_at),
        "decided_at": _stamp(quote.decided_at),
        "task": quote.task.code if quote.task_id else "",
    }


def _quote_choices():
    from .forms import language_choices

    return {
        "services": [{"value": v, "label": label} for v, label in Quotation.Service.choices],
        "units": [{"value": v, "label": label} for v, label in Quotation.Unit.choices],
        "currencies": [v for v, _label in Quotation.Currency.choices],
        "languages": language_choices(),
    }


def _decimal(body, name):
    """A price or a percentage: a JSON number or a string of one; ``BadBody`` for anything else."""
    raw = body.get(name)
    if isinstance(raw, bool) or not isinstance(raw, (int, float, str)) or len(str(raw)) > 20:
        raise BadBody
    try:
        value = Decimal(str(raw).strip())
    except InvalidOperation:
        raise BadBody from None
    if not value.is_finite():
        raise BadBody
    return value


def _quote_values(body):
    """The quotation's figures from the body, of the right types. Their sense (more than zero, a deadline to come) is
    ``b2b.save_quotation``'s to judge."""
    quantity = body.get("quantity")
    if isinstance(quantity, bool) or not isinstance(quantity, int):
        raise BadBody
    values = {
        "source_lang": _text(body, "source_lang", 40),
        "target_lang": _text(body, "target_lang", 40),
        "service": _text(body, "service", 16),
        "unit": _text(body, "unit", 10),
        "quantity": quantity,
        "rate": _decimal(body, "rate"),
        "discount_percent": _decimal(body, "discount_percent") if body.get("discount_percent") not in (None, "") else Decimal(0),
        "currency": _text(body, "currency", 3),
        "deadline": _parse_date(body.get("deadline", "")),
        "payment_terms": _text(body, "payment_terms", MAX_TERMS),
        "notes": _text(body, "notes", MAX_QUOTE_NOTES),
    }
    if values["service"] not in Quotation.Service.values or values["unit"] not in Quotation.Unit.values:
        raise BadBody
    if values["currency"] not in Quotation.Currency.values:
        raise BadBody
    if values["rate"].as_tuple().exponent < -4 or values["discount_percent"].as_tuple().exponent < -2:
        raise BadBody
    return values


@endpoint("GET")
@api_gate(b2b.has_door)
def quotations(request, lead_id):
    """A company's quotations, newest first, and what the form offers."""
    lead = _lead_or_404(request, lead_id)
    return JsonResponse({
        "ok": True,
        "lead": {"id": lead.pk, "company_name": lead.company_name, "contact_person": lead.contact_person, "email": lead.email},
        "quotations": [_quote_json(q) for q in lead.quotations.select_related("task")],
        "can_make": b2b.may_contact(request.user, lead.sheet),
        "can_decide": b2b.may_decide(request.user, lead),
        **_quote_choices(),
    })


def _quote_answer(quote):
    quote.refresh_from_db()
    return JsonResponse({"ok": True, "quotation": _quote_json(quote)})


@endpoint("POST")
@api_gate(b2b.has_door)
def quotation_create(request, lead_id):
    """A new draft quotation for the company: its figures as JSON."""
    lead = _lead_or_404(request, lead_id)
    try:
        values = _quote_values(_object(request))
    except BadBody:
        return _error(400, "bad_request")
    try:
        quote = b2b.save_quotation(lead, request.user, values)
    except b2b.Refused as refusal:
        return _refused(refusal)
    return _quote_answer(quote)


@endpoint("POST")
@api_gate(b2b.has_door)
def quotation_save(request, quote_id):
    """Change a draft's figures. A sent quotation is not changed (``not_draft``): a copy is."""
    quote = _quote_or_404(request, quote_id)
    try:
        values = _quote_values(_object(request))
    except BadBody:
        return _error(400, "bad_request")
    try:
        b2b.save_quotation(quote.lead, request.user, values, quote)
    except b2b.Refused as refusal:
        return _refused(refusal)
    return _quote_answer(quote)


@endpoint("POST")
@api_gate(b2b.has_door)
def quotation_send(request, quote_id):
    """Send a draft to the company by e-mail, from the person's own address."""
    quote = _quote_or_404(request, quote_id)
    try:
        b2b.send_quotation(quote, request.user)
    except b2b.Refused as refusal:
        return _refused(refusal)
    return _quote_answer(quote)


@endpoint("POST")
@api_gate(b2b.has_door)
def quotation_copy(request, quote_id):
    """A new draft with the same figures (how a sent price is changed)."""
    quote = _quote_or_404(request, quote_id)
    try:
        copy = b2b.copy_quotation(quote, request.user)
    except b2b.Refused as refusal:
        return _refused(refusal)
    return _quote_answer(copy)


@endpoint("POST")
@api_gate(b2b.has_door)
def quotation_decide(request, quote_id):
    """``{"accepted": true|false}`` - the company's answer to a sent quotation."""
    quote = _quote_or_404(request, quote_id)
    try:
        accepted = _object(request).get("accepted")
    except BadBody:
        return _error(400, "bad_request")
    if not isinstance(accepted, bool):
        return _error(400, "bad_request")
    try:
        b2b.decide_quotation(quote, request.user, accepted)
    except b2b.Refused as refusal:
        return _refused(refusal)
    return _quote_answer(quote)


@endpoint("POST")
@api_gate(b2b.has_door)
def quotation_delete(request, quote_id):
    """Take a draft away; a sent quotation is kept."""
    quote = _quote_or_404(request, quote_id)
    try:
        b2b.delete_quotation(quote, request.user)
    except b2b.Refused as refusal:
        return _refused(refusal)
    return JsonResponse({"ok": True})

