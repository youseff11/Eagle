"""``/api/v1/hr/`` - HR's side of attendance: the board, one day and its corrections, the monthly report.

The classic pages are ``views.hr_*`` and they are guarded by ``can_manage_attendance`` (the HR role, the admin, and anybody
the admin gave the flag to), so the doors ask that same question (``permissions.api_gate``) and not a list of roles.

Rules that matter on these pages:

* A punch is never edited: the day is corrected, the correction needs a reason, and every changed field leaves a row in the
  trail (``attendance.apply_edit``). The form decides what is valid (``api_forms``), exactly as on the classic page.
* A correction carries only the boxes that were changed. The classic page posts the whole form and a time shown to the minute
  is not the same moment as a punch kept to the second, so a box nobody touched must not count as an edit.
* A GET changes nothing. The one exception is the clock's own: the board settles the days nobody checked out of
  (``attendance.expire_open_days``), as the classic board and every heartbeat do. It is idempotent and not the request's doing.
"""

from datetime import timedelta

from django.db import transaction
from django.http import JsonResponse
from django.shortcuts import get_object_or_404
from django.utils import timezone

from . import api_forms, attendance, clock, employees, payroll, services, shiftpick
from .api_forms import named
from .api_v1 import BadBody, _day_status_json, _error, _object, _stamp, _two, endpoint
from .forms import AttendanceEditForm, OfficeLocationForm, ScheduleOverrideForm, ShiftForm, ShiftTemplateForm
from .models import (
    DAY_WORK_MODES, ApprovalStatus, AuthorizedDevice, DayStatus, LeaveRequest, LeaveStatus, OffSitePolicy, OfficeLocation, OvertimeClaim,
    PayrollSettings, PunchKind, Role, ScheduleOverride, Shift, ShiftTemplate, User, WorkDay,
)
from .permissions import api_gate
from .templatetags.eagle_tags import DAY_STATUS_MAP, EMPLOYMENT_MAP, ROLE_MAP, WORK_MODE_MAP

#: The classic board lists this many rows at most (a month of a big team would otherwise be thousands).
MAX_BOARD_ROWS = 600

can_manage = api_gate(lambda user: user.can_manage_attendance)

PUNCH_KINDS = {
    PunchKind.CHECK_IN: ("حضور", "Check in"),
    PunchKind.CHECK_OUT: ("انصراف", "Check out"),
    PunchKind.BREAK_START: ("بداية بريك", "Break start"),
    PunchKind.BREAK_END: ("نهاية بريك", "Break end"),
    PunchKind.EXTRA_START: ("بداية اكسترا تايم", "Extra time start"),
}

#: The correction form's words, as the classic page prints them (the form's own labels are English model names).
EDIT_TEXT = {
    "status": ("الحالة", "Status"),
    "work_mode": ("نظام العمل", "Work mode"),
    "check_in": ("حضور", "Check in"),
    "check_out": ("انصراف", "Check out"),
    "break_minutes": ("بريك (دقيقة)", "Break (minutes)"),
    "absence_reason": ("سبب الغياب", "Absence reason"),
    "note": ("ملاحظة", "Note"),
    "reason": ("سبب التعديل (مطلوب)", "Reason for the change (required)"),
}
EDIT_HINT = {
    "reason": (
        "التعديل من غير سبب مش بيتحفظ — السبب هو اللي بيخلي الرقم دليل.",
        "A change with no reason is not saved: the reason is what makes the figure evidence.",
    ),
}


def person_json(person):
    return {"id": person.pk, "name": person.short_name}


def _mode_json(mode):
    return _two(WORK_MODE_MAP, mode) if mode else None


def _digits(raw):
    """A query value that must be an id: digits only (and short enough to be one), else ``None``."""
    return int(raw) if raw and raw.isascii() and raw.isdecimal() and len(raw) < 18 else None


def _board_row(row):
    return {
        "id": row.pk,
        "user": person_json(row.user),
        "date": row.date.isoformat(),
        "work_mode": _mode_json(row.work_mode),
        "schedule": row.schedule_label,
        "check_in": _stamp(row.check_in, ""),
        "check_out": _stamp(row.check_out, ""),
        "is_open": row.is_open,
        "work_minutes": row.work_minutes,
        "status": _day_status_json(row.status),
        "late_minutes": row.late_minutes,
        "early_leave_minutes": row.early_leave_minutes,
        "short_minutes": row.short_minutes,
        "overtime_minutes": row.overtime_minutes,
        "off_site": row.off_site,
        "extra_started_at": _stamp(row.extra_started_at, ""),
        "checkout_missed": row.checkout_missed,
        "needs_review": row.needs_review,
    }


# ---------------------------------------------------------------------------
# The board
# ---------------------------------------------------------------------------

@endpoint("GET")
@can_manage
def board(request):
    """Everybody's attendance for a day, a week or a month, with the classic filters.

    ``?view=day|week|month&date=YYYY-MM-DD&user=&role=&mode=&status=&day_mode=&shift=&flagged=1``.
    """
    query = request.GET
    mode = query.get("view") or "day"
    if mode not in ("day", "week", "month"):
        mode = "day"
    mode, anchor, first_day, last_day = payroll.board_range(mode, query.get("date") or "")
    attendance.expire_open_days()

    people = User.objects.filter(is_active=True, attendance_enabled=True)
    if query.get("role"):
        people = people.filter(role=query["role"])
    if query.get("user"):
        who = _digits(query["user"])
        if who is None:
            return _error(400, "bad_user")
        people = people.filter(pk=who)
    if query.get("mode"):
        people = people.filter(work_mode=query["mode"])

    rows = (
        WorkDay.objects.filter(user__in=people, date__range=(first_day, last_day))
        .select_related("user").order_by("-date", "user__username")
    )
    if query.get("status"):
        rows = rows.filter(status=query["status"])
    if query.get("day_mode"):
        rows = rows.filter(work_mode=query["day_mode"])
    if query.get("shift"):
        rows = rows.filter(schedule_label=query["shift"])
    if query.get("flagged") == "1":
        rows = rows.filter(needs_review=True)
    rows = list(rows[: MAX_BOARD_ROWS + 1])
    truncated = len(rows) > MAX_BOARD_ROWS
    rows = rows[:MAX_BOARD_ROWS]

    # Who was rostered today and has no row at all: the people a status table would otherwise draw invisible.
    missing = []
    if mode == "day":
        recorded = {one.user_id for one in rows}
        for person in people:
            if person.pk in recorded:
                continue
            plan = attendance.plan_for(person, anchor)
            if plan.working:
                missing.append({"user": person_json(person), "schedule": plan.label})

    everyone = User.objects.filter(is_active=True, attendance_enabled=True)
    return JsonResponse({
        "ok": True,
        "view": mode,
        "date": anchor.isoformat(),
        "first_day": first_day.isoformat(),
        "last_day": last_day.isoformat(),
        "flagged_count": WorkDay.objects.filter(needs_review=True).count(),
        "totals": {
            "present": sum(1 for one in rows if one.status == DayStatus.PRESENT),
            "late": sum(1 for one in rows if one.late_minutes),
            "off_site": sum(1 for one in rows if one.off_site),
            "open": sum(1 for one in rows if one.is_open),
            "minutes": sum(one.work_minutes for one in rows),
            "overtime": sum(one.overtime_minutes for one in rows),
        },
        "truncated": truncated,
        "rows": [_board_row(one) for one in rows],
        "missing": missing,
        "options": {
            "people": [person_json(one) for one in everyone],
            "roles": [_two(ROLE_MAP, value) for value, _label in Role.choices],
            "day_modes": [_two(WORK_MODE_MAP, value) for value, _label in DAY_WORK_MODES],
            "statuses": [_day_status_json(value) for value, _label in DayStatus.choices],
            "shifts": [one.label for one in ShiftTemplate.objects.all()],
        },
    })


# ---------------------------------------------------------------------------
# One day
# ---------------------------------------------------------------------------

def _day_form(row):
    fields = api_forms.describe(AttendanceEditForm(instance=row))
    return named(
        fields, EDIT_TEXT, EDIT_HINT,
        choices={
            "status": {value: (ar, en) for value, (_tone, ar, en) in DAY_STATUS_MAP.items()},
            "work_mode": {value: pair for value, pair in WORK_MODE_MAP.items()},
        },
    )


@endpoint("GET")
@can_manage
def day(request, pk):
    """One day: its punches exactly as they arrived, the trail of corrections, the frozen schedule and the form."""
    row = get_object_or_404(WorkDay.objects.select_related("user"), pk=pk)
    conf = PayrollSettings.load()
    return JsonResponse({
        "ok": True,
        "day": {
            **_board_row(row),
            "review_reason": row.review_reason,
            "scheduled_start": _stamp(row.scheduled_start, ""),
            "scheduled_end": _stamp(row.scheduled_end, ""),
            "scheduled_minutes": row.scheduled_minutes,
            "grace_minutes": row.grace_minutes,
        },
        "events": [
            {
                "kind": _two(PUNCH_KINDS, one.kind),
                "at": _stamp(one.at, "%Y-%m-%d"),
                "within_geofence": one.within_geofence,
                "distance_m": one.distance_m,
                "accuracy_m": one.accuracy_m,
                "office": one.office.label if one.office_id else "",
                "device": one.device.label if one.device_id else "",
                "ip": one.ip or "",
            }
            for one in row.events.select_related("office", "device").all()
        ],
        "edits": [
            {
                "actor": one.actor.short_name if one.actor_id else None,
                "field": one.field,
                "old": one.old_value,
                "new": one.new_value,
                "reason": one.reason,
                "at": _stamp(one.created_at, "%Y-%m-%d"),
            }
            for one in row.edits.select_related("actor").all()
        ],
        "conf": {"grace_minutes": conf.grace_minutes},
        "form": _day_form(row),
    })


@endpoint("POST")
@can_manage
def day_save(request, pk):
    """Correct a day (``{"values": {...}}``, only the boxes that changed, and ``reason``). A reason is not optional."""
    row = get_object_or_404(WorkDay.objects.select_related("user"), pk=pk)
    try:
        values = _object(request).get("values", {})
        data = api_forms.form_data(AttendanceEditForm, values, instance=row)
    except (BadBody, api_forms.BadValues):
        return _error(400, "bad_body")
    form = AttendanceEditForm(data, instance=row)
    if not form.is_valid():
        return api_forms.invalid(form)
    # ModelForm has already written onto ``row``: the "before" values have to come from a clean read of it.
    fresh = WorkDay.objects.select_related("user").get(pk=row.pk)
    changes = {name: form.cleaned_data[name] for name in form.Meta.fields if name in values}
    try:
        written = attendance.apply_edit(fresh, request.user, changes, form.cleaned_data["reason"])
    except attendance.PunchRefused as refused:
        return JsonResponse({"ok": False, "error": refused.code, "message": refused.ar, "message_en": refused.en}, status=409)
    return JsonResponse({"ok": True, "written": [one.field for one in written]})


@endpoint("POST")
@can_manage
def day_clear(request, pk):
    """HR has looked at a flagged day and is satisfied with it (``{"reason": "..."}``, optional)."""
    row = get_object_or_404(WorkDay.objects.select_related("user"), pk=pk)
    try:
        reason = _object(request).get("reason", "")
    except BadBody:
        return _error(400, "bad_body")
    if not isinstance(reason, str) or len(reason) > 250 or "\x00" in reason:
        return _error(400, "bad_body")
    try:
        attendance.clear_review(row, request.user, reason)
    except attendance.PunchRefused as refused:
        return JsonResponse({"ok": False, "error": refused.code, "message": refused.ar, "message_en": refused.en}, status=409)
    return JsonResponse({"ok": True})


# ---------------------------------------------------------------------------
# The monthly report
# ---------------------------------------------------------------------------

REPORT_KEYS = (
    "scheduled_days", "present_days", "office_days", "remote_days", "leave_days", "excused_days", "absent_days", "late_days",
    "late_minutes", "early_leave_minutes", "short_minutes", "work_minutes", "break_minutes", "overtime_minutes", "needs_review",
)


@endpoint("GET")
@can_manage
def report(request):
    """Section 12 for one person and one month: ``?period=2026-09&user=<id>`` (this month and the first person when left out)."""
    raw = request.GET.get("period", "")
    if raw:
        parsed = payroll.parse_period(raw)
        if parsed is None:
            return _error(400, "bad_period")
    else:
        today = timezone.localdate()
        parsed = (today.year, today.month)
    year, month = parsed
    people = User.objects.filter(is_active=True, attendance_enabled=True)
    if request.GET.get("user"):
        who = _digits(request.GET["user"])
        if who is None:
            return _error(400, "bad_user")
        person = people.filter(pk=who).first()
    else:
        person = people.first()
    summary = None
    if person is not None:
        first_day, last_day = payroll.month_bounds(year, month)
        figures = attendance.month_summary(person, first_day, last_day)
        summary = {key: figures[key] for key in REPORT_KEYS}
        summary["days"] = [
            {
                "date": one.date.isoformat(),
                "status": _day_status_json(one.status),
                "work_mode": _mode_json(one.work_mode),
                "check_in": _stamp(one.check_in, ""),
                "check_out": _stamp(one.check_out, ""),
                "break_minutes": one.break_minutes,
                "work_minutes": one.work_minutes,
                "late_minutes": one.late_minutes,
                "short_minutes": one.short_minutes,
                "overtime_minutes": one.overtime_minutes,
            }
            for one in figures["days"]
        ]
    return JsonResponse({
        "ok": True,
        "year": year,
        "month": month,
        "periods": [{"year": a, "month": b} for a, b in payroll.period_choices()],
        "people": [person_json(one) for one in people],
        "person": person_json(person) if person else None,
        "summary": summary,
    })


# ---------------------------------------------------------------------------
# Schedules: a person's standing roster, the one-off days that override it
# ---------------------------------------------------------------------------

#: The forms' words, as the classic pages print them.
SHIFT_TEXT = {
    "weekday": ("اليوم", "Weekday"),
    "template": ("شيفت جاهز", "Shift template"),
    "start_time": ("من", "From"),
    "end_time": ("إلى", "To"),
    "work_mode": ("نظام العمل", "Work mode"),
    "required_minutes": ("ساعات مطلوبة (دقيقة)", "Required minutes"),
}
SHIFT_HINT = {
    "required_minutes": (
        "سيبها صفر عشان تاخد طول الشيفت. الـPart-Time بيتحسب من هنا، مش من افتراض 8 ساعات.",
        "Leave at zero to use the shift's own length. A part-timer is measured from here, not from an assumed eight hours.",
    ),
}
OVERRIDE_TEXT = {
    "date": ("اليوم", "Date"),
    "is_day_off": ("أجازة", "Day off"),
    "template": ("شيفت جاهز", "Shift template"),
    "start_time": ("من", "From"),
    "end_time": ("إلى", "To"),
    "work_mode": ("نظام العمل", "Work mode"),
    "required_minutes": ("ساعات مطلوبة (دقيقة)", "Required minutes"),
    "reason": ("السبب", "Reason"),
}
TEMPLATE_TEXT = {
    "name": ("الاسم بالإنجليزي", "English name"),
    "name_ar": ("الاسم", "Name"),
    "start_time": ("من", "From"),
    "end_time": ("إلى", "To"),
    "break_minutes": ("بريك الشيفت (دقيقة)", "Shift break (minutes)"),
    "sort_order": ("الترتيب", "Order"),
    "is_active": ("شغال", "Active"),
}
TEMPLATE_HINT = {
    "name_ar": ("اختياري — لو سيبته فاضي بيتسمّى بمواعيده.", "Optional - left blank it is named by its hours."),
    "break_minutes": ("صفر = بريك الشركة.", "0 uses the company break."),
}
#: A work mode left blank on a roster row follows the person's own.
MODE_CHOICES = {**WORK_MODE_MAP, "": ("زي نظام الموظف", "Same as the person")}
WEEKDAY_CHOICES = {"": ("— اختار —", "— Choose —"), **{str(number): pair for number, pair in attendance.WEEKDAY_NAMES.items()}}


def _without(fields, *names):
    return [one for one in fields if one["name"] not in names]


def _only(fields, *names):
    return [one for one in fields if one["name"] in names]


def _weekday_json(number):
    ar, en = attendance.WEEKDAY_NAMES[number]
    return {"value": number, "ar": ar, "en": en}


def _roster_json(shift):
    return {
        "id": shift.pk,
        "weekday": _weekday_json(shift.weekday),
        "template": shift.template.label if shift.template_id else None,
        "start": _stamp(shift.start, ""),
        "end": _stamp(shift.end, ""),
        "crosses_midnight": shift.crosses_midnight,
        "minutes": shift.minutes,
        "work_mode": _mode_json(shift.work_mode),
        "is_active": shift.is_active,
    }


def _override_json(row):
    return {
        "id": row.pk,
        "date": row.date.isoformat(),
        "is_day_off": row.is_day_off,
        "label": "" if row.is_day_off else row.label,
        "work_mode": _mode_json(row.work_mode),
        "reason": row.reason,
    }


def _plan_json(plan):
    return {
        "date": plan.date.isoformat(),
        "working": plan.working,
        "label": plan.label if plan.working else "",
        "start": _stamp(plan.start, "") if plan.working else None,
        "end": _stamp(plan.end, "") if plan.working else None,
        "mode": _mode_json(plan.mode) if plan.working else None,
        "source": plan.source,
    }


def _schedule_forms():
    return {
        "shift_form": named(
            _without(api_forms.describe(ShiftForm()), "is_active"), SHIFT_TEXT, SHIFT_HINT,
            choices={"weekday": WEEKDAY_CHOICES, "work_mode": MODE_CHOICES},
        ),
        "override_form": named(
            api_forms.describe(ScheduleOverrideForm()), OVERRIDE_TEXT,
            choices={"work_mode": MODE_CHOICES},
        ),
        "template_form": named(
            _only(api_forms.describe(ShiftTemplateForm()), "name", "name_ar", "start_time", "end_time"), TEMPLATE_TEXT, TEMPLATE_HINT,
        ),
    }


def _template_json(row):
    return {
        "id": row.pk,
        "label": row.label,
        "is_active": row.is_active,
        "start": _stamp(row.start_time, ""),
        "end": _stamp(row.end_time, ""),
    }


@endpoint("GET")
@can_manage
def schedules(request):
    """A person's standing roster, the days that override it, the next fortnight as the rules resolve it, and the forms.

    ``?user=<id>`` (the first active person when left out). The roster lists every row, switched off ones too, with a flag:
    a row saved switched off counts for nothing, and the person looking at the roster needs to see that.
    """
    people = User.objects.filter(is_active=True)
    if request.GET.get("user"):
        who = _digits(request.GET["user"])
        if who is None:
            return _error(400, "bad_user")
        person = people.filter(pk=who).first()
    else:
        person = people.first()
    today = timezone.localdate()
    body = {
        "ok": True,
        "people": [person_json(one) for one in people],
        "person": None,
        "shifts": [],
        "overrides": [],
        "preview": [],
        "templates": [_template_json(one) for one in ShiftTemplate.objects.all()],
        **_schedule_forms(),
    }
    if person is not None:
        body["person"] = {
            **person_json(person),
            "employment": _two(EMPLOYMENT_MAP, person.employment_type),
            "work_mode": _mode_json(person.work_mode),
            "schedule_kind": person.get_schedule_kind_display(),
        }
        body["shifts"] = [_roster_json(one) for one in person.shifts.select_related("template").all()]
        body["overrides"] = [
            _override_json(one)
            for one in person.schedule_overrides.select_related("template").filter(date__gte=today - timedelta(days=30))
        ]
        body["preview"] = [_plan_json(attendance.plan_for(person, today + timedelta(days=offset))) for offset in range(14)]
    return JsonResponse(body)


def _person_and_values(request):
    """``(person, values, None)`` from ``{"user": id, "values": {...}}``; ``(None, None, the answer to give)`` when the body is not that."""
    try:
        body = _object(request)
        who = body.get("user")
        values = body.get("values", {})
        if isinstance(who, bool) or not isinstance(who, int) or not 0 < who < 2 ** 63 or not isinstance(values, dict):
            raise BadBody
    except BadBody:
        return None, None, _error(400, "bad_body")
    return get_object_or_404(User, pk=who, is_active=True), values, None


@endpoint("POST")
@can_manage
def shift_add(request):
    """Add a day to a person's roster (``{"user": id, "values": {...}}``). A row added here is switched on."""
    person, values, refused = _person_and_values(request)
    if refused:
        return refused
    try:
        data = api_forms.form_data(ShiftForm, values)
    except api_forms.BadValues:
        return _error(400, "bad_body")
    # The box has no "switched on" tick; a form that is not sent one reads it as off, and a row that is off counts for nothing.
    data["is_active"] = True
    form = ShiftForm(data)
    if not form.is_valid():
        return api_forms.invalid(form)
    row = form.save(commit=False)
    row.user = person
    row.save()
    services.log(request.user, "schedule.shift.add", f"{person.username} {row.weekday}")
    return JsonResponse({"ok": True, "id": row.pk})


@endpoint("POST")
@can_manage
def override_add(request):
    """Move one date for a person (``{"user": id, "values": {...}}``); a second save for the same date replaces the first."""
    person, values, refused = _person_and_values(request)
    if refused:
        return refused
    try:
        data = api_forms.form_data(ScheduleOverrideForm, values)
    except api_forms.BadValues:
        return _error(400, "bad_body")
    form = ScheduleOverrideForm(data)
    if not form.is_valid():
        return api_forms.invalid(form)
    row = form.save(commit=False)
    row.user = person
    row.created_by = request.user
    with transaction.atomic():
        ScheduleOverride.objects.filter(user=person, date=row.date).delete()
        row.save()
    services.log(request.user, "schedule.override", f"{person.username} {row.date}")
    return JsonResponse({"ok": True, "id": row.pk})


@endpoint("POST")
@can_manage
def shift_delete(request, pk):
    row = get_object_or_404(Shift, pk=pk)
    person = row.user_id
    row.delete()
    services.log(request.user, "schedule.shift.delete", str(pk))
    return JsonResponse({"ok": True, "user": person})


@endpoint("POST")
@can_manage
def override_delete(request, pk):
    row = get_object_or_404(ScheduleOverride, pk=pk)
    person = row.user_id
    row.delete()
    services.log(request.user, "schedule.override.delete", str(pk))
    return JsonResponse({"ok": True, "user": person})


@endpoint("POST")
@can_manage
def template_add(request):
    """Add a company shift from the four boxes on the schedules page (``{"values": {name, name_ar, start_time, end_time}}``)."""
    try:
        values = _object(request).get("values", {})
        if not isinstance(values, dict) or set(values) - {"name", "name_ar", "start_time", "end_time"}:
            raise BadBody
        if any(not isinstance(one, str) or len(one) > 60 or "\x00" in one for one in values.values()):
            raise BadBody
    except BadBody:
        return _error(400, "bad_body")
    form = shiftpick.new_template_form(values.get("name"), values.get("name_ar"), values.get("start_time"), values.get("end_time"))
    if not form.is_valid():
        return api_forms.invalid(form)
    row = form.save()
    services.log(request.user, "schedule.template.add", row.name)
    return JsonResponse({"ok": True, "id": row.pk})


# ---------------------------------------------------------------------------
# The company's shifts
# ---------------------------------------------------------------------------

def _usage_json(row):
    return {
        "id": row.pk,
        "label": row.label,
        "name": row.name,
        "name_ar": row.name_ar,
        "is_active": row.is_active,
        "start": _stamp(row.start_time, ""),
        "end": _stamp(row.end_time, ""),
        "crosses_midnight": row.crosses_midnight,
        "hours": row.hours_txt,
        "people": row.people_n,
        "overrides": row.overrides_n,
        "vacancies": row.vacancies_n,
        "in_use": row.in_use,
    }


def _shifts_form(editing):
    return named(api_forms.describe(ShiftTemplateForm(instance=editing)), TEMPLATE_TEXT, TEMPLATE_HINT)


@endpoint("GET")
@can_manage
def shifts(request):
    """The company's shifts with who leans on each, and the form (blank, or the shift ``?edit=<id>`` names)."""
    raw = request.GET.get("edit") or ""
    editing = ShiftTemplate.objects.filter(pk=raw).first() if raw.isascii() and raw.isdecimal() and len(raw) < 18 else None
    return JsonResponse({
        "ok": True,
        "rows": [_usage_json(one) for one in shiftpick.shift_usage(ShiftTemplate.objects.all())],
        "editing": editing.pk if editing else None,
        "form": _shifts_form(editing),
    })


def _id_and_values(request):
    """``(id or None, values, None)`` from ``{"id": 3, "values": {...}}``; ``(None, None, the answer to give)`` when the body is not that."""
    try:
        body = _object(request)
        which = body.get("id")
        values = body.get("values", {})
        if which is not None and (isinstance(which, bool) or not isinstance(which, int) or not 0 < which < 2 ** 63):
            raise BadBody
        if not isinstance(values, dict):
            raise BadBody
    except BadBody:
        return None, None, _error(400, "bad_body")
    return which, values, None


@endpoint("POST")
@can_manage
def shift_save(request):
    """Add a company shift, or change one (``{"id": 3, "values": {...}}``): its hours, its break, its place, closed or open."""
    which, values, refused = _id_and_values(request)
    if refused:
        return refused
    editing = get_object_or_404(ShiftTemplate, pk=which) if which is not None else None
    try:
        data = api_forms.form_data(ShiftTemplateForm, values, instance=editing)
    except api_forms.BadValues:
        return _error(400, "bad_body")
    form = ShiftTemplateForm(data, instance=editing)
    if not form.is_valid():
        return api_forms.invalid(form)
    row = form.save()
    services.log(request.user, "schedule.template.save", row.name, clock.window12(row.start_time, row.end_time))
    return JsonResponse({"ok": True, "id": row.pk})


@endpoint("POST")
@can_manage
def shift_template_delete(request, pk):
    """Delete a company shift nobody is on. One somebody leans on is closed from its form instead: 409 ``in_use``."""
    row = get_object_or_404(ShiftTemplate, pk=pk)
    if shiftpick.shift_usage([row])[0].in_use:
        return JsonResponse({
            "ok": False, "error": "in_use",
            "message": "الشيفت ده عليه موظفين أو جداول أو وظايف — اقفله من التعديل بدل ما تمسحه.",
            "message_en": "People, schedules or vacancies are on this shift - close it from its form instead of deleting it.",
        }, status=409)
    name = row.name
    row.delete()
    services.log(request.user, "schedule.template.delete", name)
    return JsonResponse({"ok": True})


# ---------------------------------------------------------------------------
# Where a punch may be made from
# ---------------------------------------------------------------------------

OFFICE_TEXT = {
    "name": ("الاسم", "Name"),
    "name_ar": ("بالعربي", "Arabic"),
    "latitude": ("Latitude", "Latitude"),
    "longitude": ("Longitude", "Longitude"),
    "radius_meters": ("النطاق بالمتر", "Radius (metres)"),
    "is_active": ("شغال", "Active"),
}
OFFICE_HINT = {
    "radius_meters": (
        "الموظف اللي شغال من الشركة لازم يسجّل جوه المسافة دي من المكتب.",
        "Somebody working from the office has to punch within this distance of it.",
    ),
}


def _office_json(office):
    return {
        "id": office.pk,
        "label": office.label,
        "latitude": str(office.latitude),
        "longitude": str(office.longitude),
        "radius_meters": office.radius_meters,
        "is_active": office.is_active,
    }


@endpoint("GET")
@can_manage
def offices(request):
    """The places a punch may be made from, the form (blank, or the office ``?edit=<id>`` names) and the off-site policy."""
    raw = request.GET.get("edit") or ""
    editing = OfficeLocation.objects.filter(pk=raw).first() if raw.isascii() and raw.isdecimal() and len(raw) < 18 else None
    conf = PayrollSettings.load()
    return JsonResponse({
        "ok": True,
        "offices": [_office_json(one) for one in OfficeLocation.objects.all()],
        "editing": editing.pk if editing else None,
        "form": named(api_forms.describe(OfficeLocationForm(instance=editing)), OFFICE_TEXT, OFFICE_HINT),
        "policy": "reject" if conf.off_site_policy == OffSitePolicy.REJECT else "flag",
    })


@endpoint("POST")
@can_manage
def office_save(request):
    """Add an office, or change one (``{"id": 3, "values": {...}}``)."""
    which, values, refused = _id_and_values(request)
    if refused:
        return refused
    editing = get_object_or_404(OfficeLocation, pk=which) if which is not None else None
    try:
        data = api_forms.form_data(OfficeLocationForm, values, instance=editing)
    except api_forms.BadValues:
        return _error(400, "bad_body")
    form = OfficeLocationForm(data, instance=editing)
    if not form.is_valid():
        return api_forms.invalid(form)
    office = form.save()
    services.log(
        request.user, "attendance.office.edit" if editing else "attendance.office.add",
        office.name, f"{office.latitude},{office.longitude} r={office.radius_meters}m",
    )
    return JsonResponse({"ok": True, "id": office.pk})


@endpoint("POST")
@can_manage
def office_delete(request, pk):
    deleted, _detail = OfficeLocation.objects.filter(pk=pk).delete()
    if deleted:
        services.log(request.user, "attendance.office.delete", str(pk))
    return JsonResponse({"ok": True, "deleted": 1 if deleted else 0})


# ---------------------------------------------------------------------------
# The browsers people punch from
# ---------------------------------------------------------------------------

MAX_DECIDED = 60
#: How much of a browser's token or name a page may show: enough to tell two apart, never the whole token.
FINGERPRINT_SHOWN = 12
AGENT_SHOWN = 60


def _device_json(device):
    return {
        "id": device.pk,
        "user": device.user.short_name,
        "name": (device.label or device.fingerprint)[:FINGERPRINT_SHOWN],
        "fingerprint": device.fingerprint[:FINGERPRINT_SHOWN],
        "browser": (device.user_agent or "")[:AGENT_SHOWN],
        "status": device.status,
        "decided_by": device.approved_by.short_name if device.approved_by_id else None,
        "first_seen": _stamp(device.first_seen, "%Y-%m-%d"),
        "last_seen": _stamp(device.last_seen, "%Y-%m-%d"),
    }


@endpoint("GET")
@can_manage
def devices(request):
    """The browsers waiting for approval and the ones decided lately. A token is shown by its first characters only."""
    return JsonResponse({
        "ok": True,
        "pending": [
            _device_json(one) for one in AuthorizedDevice.objects.filter(status=ApprovalStatus.PENDING).select_related("user", "approved_by")
        ],
        "decided": [
            _device_json(one)
            for one in AuthorizedDevice.objects.exclude(status=ApprovalStatus.PENDING).select_related("user", "approved_by")[:MAX_DECIDED]
        ],
    })


def _own_refusal():
    """Whoever holds the attendance right does not decide their own overtime or browser: the owner does."""
    return JsonResponse({
        "ok": False, "error": "own_record",
        "message": "مينفعش تقرر في حاجة بتاعتك أنت. المالك هو اللي بيقرر.",
        "message_en": "Nobody decides their own record except the owner.",
    }, status=409)


@endpoint("POST")
@can_manage
def device_decide(request, pk, action):
    """Approve or reject a browser. A decision can be changed: an approved browser can be turned away."""
    if action not in ("approve", "reject"):
        return _error(404, "not_found")
    device = get_object_or_404(AuthorizedDevice.objects.select_related("user"), pk=pk)
    if device.user_id == request.user.pk and not request.user.is_admin_role:
        return _own_refusal()
    if action == "approve":
        device.approve(request.user)
    else:
        device.reject(request.user)
    services.log(request.user, f"attendance.device.{action}", device.user.username)
    return JsonResponse({"ok": True})


# ---------------------------------------------------------------------------
# Overtime: the engine works out the time was worked, a person decides whether it is paid
# ---------------------------------------------------------------------------

def _claim_json(claim):
    return {
        "id": claim.pk,
        "user": claim.user.short_name,
        "date": claim.date.isoformat(),
        "hours": claim.hours_display,
        "hourly_rate": str(claim.hourly_rate),
        "amount": str(claim.amount),
        "status": claim.status,
        "decided_by": claim.approved_by.short_name if claim.approved_by_id else None,
    }


@endpoint("GET")
@can_manage
def overtime(request):
    """Extra hours waiting for a decision, and the ones decided lately. Money is text."""
    return JsonResponse({
        "ok": True,
        "pending": [
            _claim_json(one) for one in OvertimeClaim.objects.filter(status=ApprovalStatus.PENDING).select_related("user", "approved_by")
        ],
        "decided": [
            _claim_json(one)
            for one in OvertimeClaim.objects.exclude(status=ApprovalStatus.PENDING).select_related("user", "approved_by")[:MAX_DECIDED]
        ],
    })


@endpoint("POST")
@can_manage
def overtime_decide(request, pk, action):
    """Approve or reject a claim that is waiting. One that has been decided is not decided again from here: 409."""
    if action not in ("approve", "reject"):
        return _error(404, "not_found")
    with transaction.atomic():
        claim = get_object_or_404(OvertimeClaim.objects.select_for_update().select_related("user"), pk=pk)
        if claim.user_id == request.user.pk and not request.user.is_admin_role:
            return _own_refusal()
        if claim.status != ApprovalStatus.PENDING:
            return JsonResponse({
                "ok": False, "error": "already_decided",
                "message": "اتقرر في الطلب ده قبل كده.", "message_en": "This claim has already been decided.",
            }, status=409)
        if action == "approve" and not WorkDay.objects.filter(
            user=claim.user, date=claim.date, status=DayStatus.PRESENT, overtime_minutes__gte=claim.minutes,
        ).exists():
            # The day was corrected after the claim was drafted: there is no longer that much overtime to pay for.
            return JsonResponse({
                "ok": False, "error": "stale_claim",
                "message": "اليوم اتعدّل ومبقاش فيه أوفرتايم بالمدة دي. ارفض الطلب أو سيبه يتحسب من جديد.",
                "message_en": "The day was corrected and no longer has that much overtime. Reject the claim or let it be drafted again.",
            }, status=409)
        if action == "approve":
            claim.approve(request.user)
        else:
            claim.reject(request.user)
    services.log(request.user, f"attendance.overtime.{action}", f"{claim.user.username} {claim.date}")
    return JsonResponse({"ok": True})


# ---------------------------------------------------------------------------
# Leave: the queue
# ---------------------------------------------------------------------------

#: The record lists this many rows at most: the classic page's number.
MAX_LEAVE_ROWS = 200


@endpoint("GET")
@can_manage
def leave_queue(request):
    """What waits for a decision, and the record, filtered by ``?user=<id>&status=``.

    The decision itself is ``api_leave.decide``: the engine says who may move a request along at which step, and each waiting
    row says whether this person may (``can_decide``) so the page offers the buttons only where they would work.
    """
    from .api_leave import request_json, status_json  # late: api_leave imports this module

    rows = LeaveRequest.objects.select_related("user", "manager", "hr_decision_by")
    if request.GET.get("status"):
        rows = rows.filter(status=request.GET["status"])
    if request.GET.get("user"):
        who = _digits(request.GET["user"])
        if who is None:
            return _error(400, "bad_user")
        rows = rows.filter(user_id=who)
    waiting = LeaveRequest.objects.filter(
        status__in=(LeaveStatus.PENDING, LeaveStatus.MANAGER_OK)
    ).select_related("user", "manager")
    user = request.user
    return JsonResponse({
        "ok": True,
        "waiting": [
            {
                **request_json(one),
                "user": person_json(one.user),
                "manager": one.manager.short_name if one.manager_id and one.status == LeaveStatus.PENDING else None,
                "can_decide": employees.can_decide_leave(one, user),
            }
            for one in waiting
        ],
        "rows": [
            {
                **request_json(one),
                "user": person_json(one.user),
                "decided_by": one.hr_decision_by.short_name if one.hr_decision_by_id else None,
                "applied": one.applied_at is not None,
            }
            for one in rows[:MAX_LEAVE_ROWS]
        ],
        "options": {
            "people": [person_json(one) for one in User.objects.filter(is_active=True)],
            "statuses": [status_json(value) for value, _label in LeaveStatus.choices],
        },
    })
