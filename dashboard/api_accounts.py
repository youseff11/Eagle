"""``/api/v1/accounts/`` - the money screens: the month's sheet, a payslip, attendance and output, violations, salaries, the rules.

The pages are ``views.accounts_*``. Accounting and the admin run the month; the translator reads their own payslip; the rules
are the admin's alone. Every number comes from the same functions the classic pages ask (``payroll.*``), and every write goes
through the classic forms (``api_forms``) or functions, so what they refuse is refused here and what the classic pages wrote
down is written down here.

Rules that matter on these pages:

* Nothing moves money on its own. A deduction is approved by a person, the two monthly bonuses are released by the admin, a
  locked month is never computed again.
* Money is text (``"1500.00"``): a float would round it.
* A GET changes nothing. The classic attendance sheet refreshed the words from the job log as it opened; here that is its own
  POST that the page makes and then asks again.
* A free-text reason on a deduction that is tied to a task goes through ``identity.mask_client``: the people who record
  deductions need not know the client.
"""

from django.http import JsonResponse
from django.shortcuts import get_object_or_404
from django.utils import timezone
from django.utils.dateparse import parse_date

from . import api_forms, attendance, clock, identity, payroll, services
from .api_v1 import BadBody, _day_status_json, _error, _object, _two, endpoint
from .forms import PayrollSettingsForm, ProductionTierForm, SalaryRecordForm, ViolationForm, WorkDayForm
from .models import (
    LEAVE_STATUSES, ApprovalStatus, PayrollLine, PayrollPeriod, PayrollSettings, PeriodStatus, ProductionTier, Role,
    SalaryRecord, Task, TierScale, User, Violation, WordCountState, WorkDay,
)
from .payroll_texts import SECTIONS as RULE_SECTIONS
from .payroll_texts import TEXTS as RULE_TEXTS
from .permissions import api_role_required
from .templatetags.eagle_tags import VIOLATION_KIND_MAP

#: How many rows each card lists: the classic pages' own numbers.
MAX_PENDING = 50
MAX_UNSETTLED = 30
MAX_DECIDED = 60
MAX_SALARY_MONTHS = 24

PERIOD_STATUS = {
    PeriodStatus.DRAFT: ("مسودة", "Draft"),
    PeriodStatus.APPROVED: ("معتمد", "Approved"),
    PeriodStatus.LOCKED: ("مقفول", "Locked"),
}


def _money(value):
    return str(value)


def _month(request):
    """``(year, month)`` from ``?period=2026-09``; this month when it is left out; ``None`` for a value that is not one."""
    raw = request.GET.get("period", "")
    if not raw:
        today = timezone.localdate()
        return today.year, today.month
    return payroll.parse_period(raw)


def _periods():
    return [{"year": year, "month": month} for year, month in payroll.period_choices()]


def _period_json(period):
    if period is None:
        return None
    ar, en = PERIOD_STATUS.get(period.status, (period.status, period.status))
    return {"id": period.pk, "label": period.label, "status": {"value": period.status, "ar": ar, "en": en}}


def _person_json(person):
    return {"id": person.pk, "name": person.short_name, "username": person.username, "initials": person.initials}


def _moment(value):
    """A time of day in both languages (Cairo, twelve hours), or ``None``."""
    return {"ar": clock.fmt12(value, "ar"), "en": clock.fmt12(value, "en")} if value else None


def _violation_json(row, viewer):
    client = row.task.client if row.task_id else None
    return {
        "id": row.pk,
        "user": row.user.short_name,
        "date": row.date.isoformat(),
        "kind": _two(VIOLATION_KIND_MAP, row.kind),
        "task": row.task.code if row.task_id else None,
        "reason": identity.mask_client(row.reason, client, viewer),
        "penalty_days": _money(row.penalty_days),
        "penalty_amount": _money(row.penalty_amount),
        "escalated": row.escalated,
        "status": row.status,
        "decided_by": row.approved_by.short_name if row.approved_by_id else None,
    }


# ---------------------------------------------------------------------------
# The month's sheet
# ---------------------------------------------------------------------------

def _line_row(line, conf):
    return {
        "id": line.pk,
        "user": _person_json(line.user),
        "base_salary": _money(line.base_salary),
        "worked_days": line.worked_days,
        "working_days": line.working_days,
        "leave_days": line.leave_days,
        "extra_leave_days": line.extra_leave_days,
        "unexcused_days": line.unexcused_days,
        "total_words": line.total_words,
        "below_alert": line.below_alert_threshold,
        "production_bonus": _money(line.production_bonus),
        "bonus_total": _money(line.bonus_total),
        "pending_bonus": _money(line.pending_bonus_for(conf)),
        "deductions": _money(line.deductions),
        "net": _money(line.net),
    }


@endpoint("GET")
@api_role_required(Role.ACCOUNTING)
def overview(request):
    """The month: its lines and totals, what waits for approval, and what to settle before locking it."""
    user = request.user
    parsed = _month(request)
    if parsed is None:
        return _error(400, "bad_period")
    year, month = parsed
    period = PayrollPeriod.objects.filter(year=year, month=month).first()
    lines = list(period.lines.select_related("user")) if period else []
    conf = PayrollSettings.load()
    totals = payroll.month_totals(period) if period else None
    first_day, last_day = payroll.month_bounds(year, month)
    return JsonResponse({
        "ok": True,
        "year": year,
        "month": month,
        "periods": _periods(),
        "period": _period_json(period),
        "totals": {
            "net": _money(totals["net"]), "words": totals["words"], "deductions": _money(totals["deductions"]),
            "alerts": totals["alerts"],
        } if totals else None,
        "lines": [_line_row(line, conf) for line in lines],
        "pending_violations": [
            _violation_json(row, user)
            for row in Violation.objects.filter(status=ApprovalStatus.PENDING).select_related("user", "task__client")[:MAX_PENDING]
        ],
        "missing_salary": [
            _person_json(person)
            for person in User.objects.filter(role=Role.TRANSLATOR, is_active=True, salary_records__isnull=True)
        ],
        # A job whose word count nobody has settled would walk into the month as a number that is missing or unchecked.
        "unsettled_tasks": [
            {"code": task.code, "translator": task.translator.short_name if task.translator_id else None}
            for task in Task.objects.filter(
                translated_at__date__range=(first_day, last_day),
                word_count_state__in=(WordCountState.EMPTY, WordCountState.REVIEW, WordCountState.MANUAL_NEEDED),
            ).select_related("translator")[:MAX_UNSETTLED]
        ],
        # The classic page lets the admin alone open a payslip's detail and open a task from here.
        "can": {"line": user.is_admin_role, "task": user.is_admin_role},
    })


@endpoint("POST")
@api_role_required(Role.ACCOUNTING)
def recalculate(request):
    """Run the month (``{"period": "2026-09"}``). A locked month is left exactly as it was paid."""
    try:
        raw = _object(request).get("period", "")
    except BadBody:
        return _error(400, "bad_body")
    parsed = payroll.parse_period(raw) if isinstance(raw, str) else None
    today = timezone.localdate()
    if parsed is None or parsed > (today.year, today.month):
        return _error(400, "bad_period")
    period = payroll.compute_period(*parsed, actor=request.user)
    if period.is_locked:
        return JsonResponse({"ok": False, "error": "period_locked", "message": "الشهر مقفول - مش بيتحسب تاني."}, status=409)
    return JsonResponse({"ok": True, "period": _period_json(period)})


@endpoint("POST")
@api_role_required(Role.ACCOUNTING)
def period_approve(request, pk):
    """Approve a month, or lock it (``{"lock": true}``). A locked month cannot be changed again."""
    period = get_object_or_404(PayrollPeriod, pk=pk)
    try:
        body = _object(request)
    except BadBody:
        return _error(400, "bad_body")
    lock = body.get("lock", False)
    if not isinstance(lock, bool):
        return _error(400, "bad_body")
    if period.is_locked:
        return JsonResponse({"ok": False, "error": "period_locked", "message": "الشهر مقفول بالفعل."}, status=409)
    payroll.approve_period(period, request.user, lock=lock)
    return JsonResponse({"ok": True, "period": _period_json(period)})


# ---------------------------------------------------------------------------
# One payslip
# ---------------------------------------------------------------------------

def _line_full(line, conf):
    out = _line_row(line, conf)
    out.update({
        "period": _period_json(line.period),
        "label": line.period.label,
        "day_value": _money(line.day_value),
        "target_words": line.target_words,
        "under_target_days": line.under_target_days,
        "overtime_bonus": _money(line.overtime_bonus),
        "overtime_minutes": line.overtime_minutes,
        "discipline_bonus": _money(line.discipline_bonus),
        "discipline_bonus_earned": line.discipline_bonus_earned,
        "target_bonus": _money(line.target_bonus),
        "target_bonus_earned": line.target_bonus_earned,
        "bonuses_approved": line.bonuses_approved,
        "gross": _money(line.gross),
        "scheduled_days": line.scheduled_days,
        "office_days": line.office_days,
        "remote_days": line.remote_days,
        "late_days": line.late_days,
        "late_minutes": line.late_minutes,
        "early_leave_minutes": line.early_leave_minutes,
        "short_minutes": line.short_minutes,
        "work_minutes": line.work_minutes,
    })
    return out


def _breakdown_rows(rows, status):
    """The deduction rows a line froze, with the kind as people read it."""
    out = []
    for row in rows or []:
        out.append({
            "date": row.get("date", ""),
            "kind": _two(VIOLATION_KIND_MAP, row.get("kind", "")),
            "reason": row.get("reason", ""),
            "days": row.get("days", "0"),
            "amount": row.get("amount", "0"),
            "status": status,
        })
    return out


@endpoint("GET")
def line(request, pk):
    """A month's payslip, in full: the admin's to read, and a translator's own. Anybody else gets a 404 and a row in the log.

    That is the classic page's rule exactly - it does not open for Accounting, who read the same numbers on the month's sheet
    but not the day-by-day detail. (An open question for the owner; see the notes.)
    """
    user = request.user
    row = get_object_or_404(PayrollLine.objects.select_related("user", "period"), pk=pk)
    if not (user.is_admin_role or row.user_id == user.pk):
        identity.hidden(request, "payslip")
    conf = PayrollSettings.load()
    breakdown = row.breakdown or {}
    return JsonResponse({
        "ok": True,
        "line": _line_full(row, conf),
        "days": [
            {
                "date": day.get("date", ""),
                "status": _day_status_json(day.get("status", "")),
                "secondary": bool(day.get("secondary")),
                "difficult": bool(day.get("difficult")),
                "words": day.get("words", 0),
                "target": day.get("target", 0),
                "bonus": day.get("bonus", "0"),
            }
            for day in breakdown.get("days", [])
        ],
        "deductions": _breakdown_rows(payroll.shown_breakdown(breakdown.get("deductions"), row.user, user), "applied")
        + _breakdown_rows(payroll.shown_breakdown(breakdown.get("pending"), row.user, user), "pending"),
        "conf": {
            "monthly_leave_allowance": conf.monthly_leave_allowance,
            "discipline_bonus": _money(conf.discipline_bonus),
            "target_bonus": _money(conf.target_bonus),
        },
        "can": {
            "salary": user.is_admin_role,
            "release": user.is_admin_role and not row.bonuses_approved and row.pending_bonus > 0 and not row.period.is_locked,
        },
    })


@endpoint("POST")
@api_role_required(Role.ADMIN)
def line_bonus(request, pk):
    """Release the two monthly bonuses of one line. The admin's: the system proposes, the manager releases."""
    row = get_object_or_404(PayrollLine.objects.select_related("period", "user"), pk=pk)
    if row.period.is_locked:
        return JsonResponse({"ok": False, "error": "period_locked", "message": "الشهر مقفول."}, status=409)
    if row.bonuses_approved:
        return JsonResponse({"ok": False, "error": "already_released", "message": "المكافآت اتصرفت قبل كده."}, status=409)
    payroll.approve_bonuses(row, request.user)
    return JsonResponse({"ok": True})


# ---------------------------------------------------------------------------
# Attendance and output
# ---------------------------------------------------------------------------

def _translators():
    return User.objects.filter(role=Role.TRANSLATOR, is_active=True)


@endpoint("GET")
@api_role_required(Role.ACCOUNTING)
def attendance_sheet(request):
    """One translator's month, day by day: ``?period=2026-09&user=<id>`` (the first translator when no one is named)."""
    parsed = _month(request)
    if parsed is None:
        return _error(400, "bad_period")
    year, month = parsed
    people = _translators()
    raw = request.GET.get("user", "")
    if raw and not (raw.isascii() and raw.isdecimal() and len(raw) <= 18):
        return _error(400, "bad_user")
    person = people.filter(pk=int(raw)).first() if raw else people.first()
    first_day, last_day = payroll.month_bounds(year, month)
    conf = PayrollSettings.load()
    days = []
    if person is not None:
        days = list(WorkDay.objects.filter(user=person, date__range=(first_day, last_day)).order_by("date"))
    return JsonResponse({
        "ok": True,
        "year": year,
        "month": month,
        "periods": _periods(),
        "people": [{"id": one.pk, "name": one.short_name} for one in people],
        "person": _person_json(person) if person else None,
        "days": [
            {
                "id": day.pk,
                "date": day.date.isoformat(),
                "status": _day_status_json(day.status),
                "check_in": _moment(day.check_in),
                "check_out": _moment(day.check_out),
                "late_minutes": day.late_minutes,
                "words": day.words,
                "under_floor": day.is_under_target(conf),
                "absence_reason": day.absence_reason,
                "note": day.note,
            }
            for day in days
        ],
        "words": sum(day.words for day in days if day.is_working_day),
        "leave_used": sum(1 for day in days if day.status in LEAVE_STATUSES),
        "conf": {
            "monthly_leave_allowance": conf.monthly_leave_allowance,
            "monthly_target_words": conf.monthly_target_words,
            "daily_target_words": conf.daily_target_words,
        },
        "form": api_forms.describe(WorkDayForm()),
    })


def _person_and_month(request):
    """``(person, year, month, None)`` from a body ``{"user": id, "period": "2026-09"}``, else ``(None, 0, 0, the answer)``."""
    try:
        body = _object(request)
    except BadBody:
        return None, 0, 0, _error(400, "bad_body")
    who = body.get("user")
    if isinstance(who, bool) or not isinstance(who, int) or not 0 < who < 2 ** 63:
        return None, 0, 0, _error(400, "bad_body")
    raw = body.get("period", "")
    parsed = payroll.parse_period(raw) if isinstance(raw, str) else None
    if parsed is None:
        return None, 0, 0, _error(400, "bad_period")
    person = get_object_or_404(_translators(), pk=who)
    return person, parsed[0], parsed[1], None


@endpoint("POST")
@api_role_required(Role.ACCOUNTING)
def attendance_refresh(request):
    """Re-derive the month's words from the job log (what the classic sheet did as it opened)."""
    person, year, month, refused = _person_and_month(request)
    if refused is not None:
        return refused
    first_day, last_day = payroll.month_bounds(year, month)
    payroll.refresh_words(person, first_day, last_day)
    return JsonResponse({"ok": True})


@endpoint("POST")
@api_role_required(Role.ACCOUNTING)
def attendance_save(request):
    """Record a day (``{"user": id, "values": {...}}``): a second save for the same date edits the first, as it always did.

    The form is the classic one and starts blank, so the whole row is what is sent - a box left empty empties it, exactly as
    on the classic sheet.
    """
    try:
        body = _object(request)
        who = body.get("user")
        if isinstance(who, bool) or not isinstance(who, int) or not 0 < who < 2 ** 63:
            raise BadBody
        values = body.get("values", {})
        if not isinstance(values, dict):
            raise BadBody
        person = get_object_or_404(_translators(), pk=who)
        # A day that is already there is what the boxes are laid over: a note saved on a day with real punches must not
        # empty them. Only a new day starts blank.
        raw_date = values.get("date")
        day_at = parse_date(raw_date) if isinstance(raw_date, str) and len(raw_date) <= 10 else None
        existing = WorkDay.objects.filter(user=person, date=day_at).first() if day_at else None
        data = api_forms.form_data(WorkDayForm, values, instance=existing)
    except (BadBody, api_forms.BadValues, ValueError):
        return _error(400, "bad_body")
    form = WorkDayForm(data, instance=existing) if existing is not None else WorkDayForm(data)
    if not form.is_valid():
        return api_forms.invalid(form)
    day = form.save(commit=False)
    day.user = person
    day.save()
    # Hours typed here still have to agree with the attendance engine, or the payroll sheet and the monthly report would
    # tell two stories.
    attendance.recompute(day)
    services.log(request.user, "workday.save", f"{person.username} {day.date}")
    return JsonResponse({"ok": True, "id": day.pk})


# ---------------------------------------------------------------------------
# Violations and deductions
# ---------------------------------------------------------------------------

@endpoint("GET")
@api_role_required(Role.ACCOUNTING)
def violations(request):
    """What waits for a decision, what was decided lately, the defaults, and the form that proposes a deduction."""
    user = request.user
    conf = PayrollSettings.load()
    return JsonResponse({
        "ok": True,
        "pending": [
            _violation_json(row, user)
            for row in Violation.objects.filter(status=ApprovalStatus.PENDING).select_related("user", "task__client")[:MAX_PENDING]
        ],
        "decided": [
            _violation_json(row, user)
            for row in Violation.objects.exclude(status=ApprovalStatus.PENDING)
            .select_related("user", "task__client", "approved_by")[:MAX_DECIDED]
        ],
        "conf": {
            "quality_penalty_days": _money(conf.quality_penalty_days),
            "unexcused_penalty_days": _money(conf.unexcused_penalty_days),
            "low_output_penalty_days": _money(conf.low_output_penalty_days),
            "extra_leave_penalty_days": _money(conf.extra_leave_penalty_days),
            "target_miss_penalty": _money(conf.target_miss_penalty),
        },
        "form": api_forms.describe(ViolationForm()),
    })


@endpoint("POST")
@api_role_required(Role.ACCOUNTING)
def violation_create(request):
    """Propose a deduction. It is worth nothing until a person approves it."""
    form, refused = api_forms.filled(request, ViolationForm)
    if refused is not None:
        return refused
    row = form.save(commit=False)
    row.created_by = request.user
    row.save()
    services.log(request.user, "violation.create", f"{row.user.username} {row.kind}")
    return JsonResponse({"ok": True, "id": row.pk})


@endpoint("POST")
@api_role_required(Role.ACCOUNTING)
def violation_decide(request, pk, action):
    """Approve or reject a deduction that is waiting. One that has been decided is not decided again from here."""
    if action not in ("approve", "reject"):
        return _error(404, "not_found")
    row = get_object_or_404(Violation.objects.select_related("user"), pk=pk)
    if row.status != ApprovalStatus.PENDING:
        return JsonResponse({"ok": False, "error": "already_decided", "message": "اتقرر فيها قبل كده."}, status=409)
    if action == "approve":
        row.approve(request.user)
    else:
        row.reject(request.user)
    services.log(request.user, f"violation.{action}", f"{row.user.username} {row.date}")
    return JsonResponse({"ok": True})


# ---------------------------------------------------------------------------
# Salaries
# ---------------------------------------------------------------------------

@endpoint("GET")
@api_role_required(Role.ACCOUNTING)
def salary(request, pk):
    """A person's salary history (append-only) and the months computed on it."""
    person = get_object_or_404(User, pk=pk)
    return JsonResponse({
        "ok": True,
        "person": _person_json(person),
        "records": [
            {
                "id": row.pk,
                "effective_from": row.effective_from.isoformat(),
                "amount": _money(row.amount),
                "note": row.note,
                "by": row.created_by.short_name if row.created_by_id else None,
            }
            for row in person.salary_records.select_related("created_by")
        ],
        "lines": [
            {"id": line.pk, "label": line.period.label, "base_salary": _money(line.base_salary), "words": line.total_words, "net": _money(line.net)}
            for line in person.payroll_lines.select_related("period")[:MAX_SALARY_MONTHS]
        ],
        "can": {"line": request.user.is_admin_role, "set": request.user.is_admin_role},
        "form": api_forms.describe(SalaryRecordForm()),
    })


@endpoint("POST")
@api_role_required(Role.ADMIN)
def salary_save(request, pk):
    """Add a salary. History is append-only: an old month keeps the salary it was paid on.

    The owner's alone, like every other salary change (``employees.decide_salary_change``): accounting reads a salary and pays
    it, HR asks for a change, and the owner decides. A salary typed here moves the next run of every month that is not locked.
    """
    person = get_object_or_404(User, pk=pk)
    form, refused = api_forms.filled(request, SalaryRecordForm)
    if refused is not None:
        return refused
    row = form.save(commit=False)
    row.user = person
    row.created_by = request.user
    row.save()
    services.log(request.user, "salary.set", person.username, str(row.amount))
    return JsonResponse({"ok": True, "id": row.pk})


# ---------------------------------------------------------------------------
# The rules
# ---------------------------------------------------------------------------

def _rule_fields(form):
    out = []
    for field in api_forms.describe(form):
        texts = RULE_TEXTS.get(field["name"], {})
        if "label" in texts:
            field["label_ar"], field["label_en"] = texts["label"]
        if "hint" in texts:
            field["hint_ar"], field["hint_en"] = texts["hint"]
        out.append(field)
    return out


def _tier_json(tier):
    return {
        "id": tier.pk,
        "min_words": tier.min_words,
        "max_words": tier.max_words,
        "bonus": _money(tier.bonus),
    }


@endpoint("GET")
@api_role_required(Role.ADMIN)
def rules(request):
    """Every number the payroll runs on, the daily bonus bands, and a check that the target can be reached."""
    conf = PayrollSettings.load()
    return JsonResponse({
        "ok": True,
        "fields": _rule_fields(PayrollSettingsForm(instance=conf)),
        "sections": [
            {
                "key": section["key"], "icon": section["icon"], "ar": section["ar"], "en": section["en"],
                "fields": list(section["fields"]),
                **({"note_ar": section["note"][0], "note_en": section["note"][1]} if "note" in section else {}),
            }
            for section in RULE_SECTIONS
        ],
        "tiers": {
            "primary": [_tier_json(tier) for tier in ProductionTier.objects.filter(scale=TierScale.PRIMARY)],
            "secondary": [_tier_json(tier) for tier in ProductionTier.objects.filter(scale=TierScale.SECONDARY)],
        },
        "tier_form": api_forms.describe(ProductionTierForm()),
        "check": {
            "working_days": conf.working_days_per_month,
            "daily_target_words": conf.daily_target_words,
            "monthly_target_words": conf.monthly_target_words,
        },
    })


@endpoint("POST")
@api_role_required(Role.ADMIN)
def rules_save(request):
    """Save the boxes that were changed. The form decides what is valid; the log gets the names of the boxes, not the numbers."""
    conf = PayrollSettings.load()
    form, refused = api_forms.filled(request, PayrollSettingsForm, conf)
    if refused is not None:
        return refused
    form.save()
    sent = _object(request).get("values", {})
    services.log(request.user, "payroll.rules.update", "", ", ".join(name for name in form.changed_data if name in sent)[:500])
    return JsonResponse({"ok": True})


@endpoint("POST")
@api_role_required(Role.ADMIN)
def tier_add(request):
    form, refused = api_forms.filled(request, ProductionTierForm)
    if refused is not None:
        return refused
    tier = form.save()
    services.log(request.user, "payroll.tier.add")
    return JsonResponse({"ok": True, "id": tier.pk})


@endpoint("POST")
@api_role_required(Role.ADMIN)
def tier_delete(request, pk):
    deleted, _rows = ProductionTier.objects.filter(pk=pk).delete()
    services.log(request.user, "payroll.tier.delete", str(pk))
    return JsonResponse({"ok": True, "deleted": deleted})
