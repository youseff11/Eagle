"""``/api/v1/hr/`` - the people already hired: the register, a person's file, probation, performance, client complaints, and pay.

The pages are ``views.hr_employees``, ``hr_employee``, ``hr_probation``, ``hr_performance``, ``hr_complaints``,
``hr_salary_requests`` and ``hr_salary_plans``. Who may open each is the question its classic page asks: recruitment rights
(HR and the admin) for the register, the file, performance, complaints and salary requests; attendance rights for probation and
for the file's shift and work-mode cards; the owner alone for deciding a salary change and for the salary plans.

Rules that matter on these pages:

* HR cannot edit a salary. It asks (``employees.request_salary_change``), the owner decides, and approval is what writes the
  salary record accounting then sees. Money is text.
* A complaint is about work, not about who the client is: the client is shown by code, a task by code, and free text goes
  through ``identity.mask_client`` - HR may not know a client's identity.
* A GET changes nothing. Deciding a review or a request that has been decided is refused by the engine, in its own words.
"""

from django.db.models import Count
from django.http import JsonResponse
from django.shortcuts import get_object_or_404
from django.utils import timezone

from . import api_forms, attendance, avatars, employees, identity, payroll, performance, services, shiftpick
from .api_forms import named
from .api_hr import _digits, _mode_json, _roster_json, can_manage, person_json
from .api_leave import request_json as leave_json
from .api_ops import _seen_json
from .api_v1 import BadBody, _error, _object, _stamp, _two, endpoint
from .forms import ClientComplaintForm, ProbationDecisionForm, SalaryChangeRequestForm, SalaryPlanForm
from .models import (
    ACTIVE_TASK_STATUSES, ApprovalStatus, ClientComplaint, ComplaintSeverity, Department, EmploymentStatus, OffSitePolicy, OfficeLocation,
    PayrollSettings, ProbationOutcome, ProbationReview, ProbationStage, Role, SalaryChangeRequest, SalaryPlan, SalaryRecord, Task, User,
    WorkMode, rule_followers,
)
from .permissions import api_gate, api_role_required
from .templatetags.eagle_tags import (
    BAND_MAP, EMPLOYMENT_MAP, EMPLOYMENT_STATUS_MAP, PROBATION_MAP, ROLE_MAP, WORK_MODE_MAP,
)

can_recruit = api_gate(lambda user: user.can_recruit)
is_owner = api_gate(lambda user: user.can_approve_hiring)

#: How many rows the lists show: the classic pages' own numbers.
MAX_REVIEWS = 200
MAX_COMPLAINTS = 150
MAX_DECIDED = 40
MAX_FILE_ROWS = 6

STAGE_MAP = {
    ProbationStage.DAY_30: ("مراجعة 30 يوم", "30-day review"),
    ProbationStage.DAY_60: ("مراجعة 60 يوم", "60-day review"),
    ProbationStage.FINAL: ("المراجعة النهائية", "Final review"),
}
OUTCOME_MAP = {
    ProbationOutcome.CONFIRMED: ("تثبيت", "Confirm"),
    ProbationOutcome.EXTENDED: ("تمديد", "Extend"),
    ProbationOutcome.TERMINATED: ("إنهاء", "End"),
}
SEVERITY_MAP = {
    ComplaintSeverity.LOW: ("low", "بسيطة", "Minor"),
    ComplaintSeverity.MEDIUM: ("wait", "محتاجة انتباه", "Attention"),
    ComplaintSeverity.HIGH: ("dead", "خطيرة", "Serious"),
}
#: Why a performance indicator has no number: the engine's English words, in both languages.
REASON_MAP = {
    "no target set": ("مفيش تارجت متحدد", "No target is set"),
    "no dated jobs": ("مفيش تاسكات ليها ميعاد", "No jobs with a deadline"),
    "nothing marked yet": ("لسه ماتقيّمش حاجة", "Nothing has been marked yet"),
    "attendance is off for this account": ("الحضور مقفول للحساب ده", "Attendance is off for this account"),
    "no roster": ("مفيش جدول", "No roster"),
}


def _badge(table, value):
    tone, ar, en = table.get(value, ("", value, value))
    return {"value": value, "tone": tone, "ar": ar, "en": en}


def _reason(text):
    ar, en = REASON_MAP.get(text, (text, text))
    return {"ar": ar, "en": en}


def _label(department):
    return department.label if department else None


# ---------------------------------------------------------------------------
# The register and a person's file
# ---------------------------------------------------------------------------

def _busy_people():
    """The ids of the translators and team leaders who hold a task being worked: ``User.is_busy`` for all of them at once."""
    active = Task.objects.filter(status__in=ACTIVE_TASK_STATUSES)
    translators = set(active.filter(translator__isnull=False).values_list("translator_id", flat=True))
    leaders = set(active.filter(team_lead__isnull=False).values_list("team_lead_id", flat=True))
    return translators, leaders


def _state(person, translators, leaders):
    """The dot beside a person: disabled, free, busy, rostered but not open, or away (the staff table's own rule)."""
    if not person.is_active:
        return "disabled"
    if not person.is_online:
        return "shift" if person.on_shift else "off"
    busy = (person.is_translator and person.pk in translators) or (person.is_team_lead and person.pk in leaders)
    return "busy" if busy else "free"


@endpoint("GET")
@can_recruit
def register(request):
    """Everybody on the staff, one row each: ``?department=<id>&status=``.

    The register is the one list of people: HR's columns (code, department, kind of work, status) and the staff table's (leader,
    whether they are here, shifts, rating). HR sees the people who work here; the admin sees everybody, the switched-off too, and
    alone is told the sign-in name and the address a person receives mail for.
    """
    admin = request.user.is_admin_role
    rows = User.objects.select_related("department", "team_lead").prefetch_related("shifts")
    if not admin:
        rows = rows.filter(is_active=True)
    if request.GET.get("department"):
        which = _digits(request.GET["department"])
        if which is None:
            return _error(400, "bad_department")
        rows = rows.filter(department_id=which)
    if request.GET.get("status"):
        rows = rows.filter(employment_status=request.GET["status"])
    translators, leaders = _busy_people()
    return JsonResponse({
        "ok": True,
        "rows": [
            {
                "id": one.pk,
                "code": one.employee_code or "",
                "name": one.short_name,
                "initials": one.initials,
                "avatar": avatars.url_of(one),
                "role": _two(ROLE_MAP, one.role),
                "department": _label(one.department),
                "team_lead": one.team_lead.short_name if one.team_lead_id else None,
                "employment": _two(EMPLOYMENT_MAP, one.employment_type),
                "joining_date": one.joining_date.isoformat() if one.joining_date else None,
                "status": _badge(EMPLOYMENT_STATUS_MAP, one.employment_status),
                "state": _state(one, translators, leaders),
                "seen": _seen_json(one),
                # The owner has no roster and no rating: there is nothing to count, which is not a nought.
                "shifts": len(one.shifts.all()) if one.follows_company_rules else None,
                "rating": float(one.rating) if one.follows_company_rules else None,
                **({"username": one.username, "mail_alias": one.mail_alias} if admin else {}),
            }
            for one in rows
        ],
        "options": {
            "departments": [{"id": one.pk, "label": one.label} for one in Department.objects.filter(is_active=True)],
            "statuses": [_badge(EMPLOYMENT_STATUS_MAP, value) for value, _label_ in EmploymentStatus.choices],
        },
    })


def _work_mode_card(person):
    """What the "home or office" card needs: the places a punch is checked against, and what a roster day that names its own mode means."""
    conf = PayrollSettings.load()
    return {
        "work_mode": _mode_json(person.work_mode),
        "is_hybrid": person.work_mode == WorkMode.HYBRID,
        "offices": [{"label": one.label, "radius_meters": one.radius_meters} for one in OfficeLocation.objects.filter(is_active=True)],
        # A roster day that names its own mode beats the person's, so saying "home" here does not loosen a day pinned to the office.
        "pinned_days": person.shifts.filter(is_active=True).exclude(work_mode="").count(),
        "policy_reject": conf.off_site_policy == OffSitePolicy.REJECT,
    }


@endpoint("GET")
@can_recruit
def employee(request, pk):
    """One person's file: details, this month's attendance, the roster, probation, leave, pay plan and salary history.

    The shift and work-mode cards are attendance rights (``can_manage_attendance``); the pay plan is the admin's to assign.
    """
    person = get_object_or_404(User.objects.select_related("department", "team_lead"), pk=pk)
    viewer = request.user
    today = timezone.localdate()
    summary = None
    if person.attendance_enabled:
        figures = attendance.month_summary(person, *payroll.month_bounds(today.year, today.month))
        summary = {
            key: figures[key]
            for key in ("scheduled_days", "present_days", "office_days", "remote_days", "leave_days", "absent_days", "late_days",
                        "work_minutes", "overtime_minutes")
        }
    application = getattr(person, "candidate_record", None)
    plan = person.salary_plan
    # The owner's file is who they are and nothing of the company's rules: no attendance, roster, leave, probation or pay.
    bound = person.follows_company_rules
    return JsonResponse({
        "ok": True,
        "person": {
            **person_json(person),
            "exempt": not bound,
            "initials": person.initials,
            "avatar": avatars.url_of(person),
            "role": _two(ROLE_MAP, person.role),
            "status": _badge(EMPLOYMENT_STATUS_MAP, person.employment_status),
            "code": person.employee_code or "",
            "job_title": person.job_title,
            "department": _label(person.department),
            "manager": person.team_lead.short_name if person.team_lead_id else None,
            "languages": person.languages,
            "joining_date": person.joining_date.isoformat() if person.joining_date else None,
            "employment": _two(EMPLOYMENT_MAP, person.employment_type),
            "work_mode": _mode_json(person.work_mode),
            "probation_start": person.probation_start.isoformat() if person.probation_start else None,
            "probation_end": person.probation_end.isoformat() if person.probation_end else None,
            "phone": person.phone,
            "attendance_enabled": person.attendance_enabled,
        },
        "summary": summary,
        "shifts": [_roster_json(one) for one in person.shifts.select_related("template").all()] if bound else [],
        "picker": shiftpick.picker_json(person) if bound and viewer.can_manage_attendance else None,
        "work_mode_card": _work_mode_card(person) if bound and viewer.can_manage_attendance else None,
        "probation": [
            {
                "stage": {"value": one.stage, "ar": STAGE_MAP[one.stage][0], "en": STAGE_MAP[one.stage][1]},
                "due_date": one.due_date.isoformat(),
                "outcome": _badge(PROBATION_MAP, one.outcome),
            }
            for one in person.probation_reviews.all()
        ] if bound else [],
        "leave": [leave_json(one) for one in person.leave_requests.all()[:MAX_FILE_ROWS]] if bound else [],
        "plan": {
            "current": {"id": plan.pk, "name": plan.name, "overrides": plan.overrides()} if plan and bound else None,
            "options": [{"id": one.pk, "name": one.name} for one in SalaryPlan.objects.filter(is_active=True)] if bound and viewer.is_admin_role else [],
        },
        "application": {"code": application.code, "applied_on": application.applied_at.date().isoformat()} if application else None,
        "salary": [{"effective_from": one.effective_from.isoformat(), "amount": str(one.amount)} for one in person.salary_records.all()[:MAX_FILE_ROWS]] if bound else [],
        "can": {"edit": viewer.is_admin_role, "shift": bound and viewer.can_manage_attendance, "plan": bound and viewer.is_admin_role},
    })


@endpoint("POST")
@can_manage
def employee_shift(request, pk):
    """Put a person on one of the company's shifts for some weekdays, on none, or on a new one (``shiftpick``)."""
    person = get_object_or_404(User, pk=pk)
    if not person.follows_company_rules:
        return _error(400, "owner")
    try:
        choice = shiftpick.read_choice(_object(request))
    except BadBody:
        return _error(400, "bad_body")
    if choice is None:
        return _error(400, "bad_body")
    template, days, new_name, new_start, new_end = choice
    problem, chosen = shiftpick.choose(
        person, template, days, new_name=new_name, new_start=new_start, new_end=new_end, actor=request.user,
    )
    if problem:
        return _error(400, problem)
    return JsonResponse({"ok": True, "label": chosen.label if chosen else ""})


@endpoint("POST")
@can_manage
def employee_workmode(request, pk):
    """Home or office (``{"work_mode": "office"|"remote"}``); hybrid is kept for somebody already on it, never offered fresh."""
    person = get_object_or_404(User, pk=pk)
    if not person.follows_company_rules:
        return _error(400, "owner")
    try:
        mode = _object(request).get("work_mode", "")
    except BadBody:
        return _error(400, "bad_body")
    allowed = {WorkMode.OFFICE, WorkMode.REMOTE}
    if person.work_mode == WorkMode.HYBRID:
        allowed.add(WorkMode.HYBRID)
    if not isinstance(mode, str) or mode not in allowed:
        return _error(400, "bad_mode")
    if mode != person.work_mode:
        before = person.work_mode
        person.work_mode = mode
        person.save(update_fields=["work_mode"])
        services.log(request.user, "employee.work_mode", person.username, f"{before} -> {mode}")
    return JsonResponse({"ok": True})


@endpoint("POST")
@api_role_required(Role.ADMIN)
def employee_plan(request, pk):
    """Give a person a salary plan, or take it off so they are on the company's rules (``{"plan": id | null}``). The admin's alone."""
    person = get_object_or_404(User, pk=pk)
    if not person.follows_company_rules:
        return _error(400, "owner")
    try:
        which = _object(request).get("plan")
    except BadBody:
        return _error(400, "bad_body")
    if which is not None and (isinstance(which, bool) or not isinstance(which, int) or not 0 < which < 2 ** 63):
        return _error(400, "bad_body")
    plan = get_object_or_404(SalaryPlan, pk=which) if which is not None else None
    person.salary_plan = plan
    person.save(update_fields=["salary_plan"])
    services.log(request.user, "salary.plan.assign", person.username, plan.name if plan else "company rules")
    return JsonResponse({"ok": True})


# ---------------------------------------------------------------------------
# Probation
# ---------------------------------------------------------------------------

def _review_json(review):
    return {
        "id": review.pk,
        "user": person_json(review.user),
        "stage": {"value": review.stage, "ar": STAGE_MAP[review.stage][0], "en": STAGE_MAP[review.stage][1]},
        "due_date": review.due_date.isoformat(),
        "overdue": review.is_overdue,
        "outcome": _badge(PROBATION_MAP, review.outcome),
        "score": review.score,
        "decided": review.is_decided,
        "reviewer": review.reviewer.short_name if review.reviewer_id else None,
    }


@endpoint("GET")
@can_manage
def probation(request):
    """The three reviews each person on probation has: ``?state=due`` (come due and undecided), ``all``, or the open ones."""
    today = timezone.localdate()
    rows = rule_followers(ProbationReview.objects.select_related("user", "reviewer").filter(user__is_active=True), prefix="user__")
    state = request.GET.get("state") or ""
    if state == "due":
        rows = rows.filter(outcome=ProbationOutcome.PENDING, due_date__lte=today)
    elif state != "all":
        rows = rows.filter(outcome=ProbationOutcome.PENDING)
    on_probation = rule_followers(User.objects.filter(is_active=True, employment_status=EmploymentStatus.PROBATION)).select_related("department").annotate(
        review_count=Count("probation_reviews")
    )
    form = named(
        api_forms.describe(ProbationDecisionForm()),
        {
            "outcome": ("النتيجة", "Outcome"),
            "score": ("التقييم من 10", "Score out of 10"),
            "extend_days": ("تمديد (يوم)", "Extend (days)"),
            "notes": ("الملاحظات", "Notes"),
        },
        choices={"outcome": OUTCOME_MAP},
    )
    return JsonResponse({
        "ok": True,
        "state": state if state in ("due", "all") else "open",
        "rows": [_review_json(one) for one in rows[:MAX_REVIEWS]],
        "form": form,
        "on_probation": [
            {**person_json(one), "department": _label(one.department), "probation_end": one.probation_end.isoformat() if one.probation_end else None, "has_reviews": one.review_count > 0}
            for one in on_probation
        ],
        "due_count": ProbationReview.objects.filter(outcome=ProbationOutcome.PENDING, due_date__lte=today, user__is_active=True).count(),
    })


@endpoint("POST")
@can_manage
def probation_decide(request, pk):
    """Record a review's verdict (``{"values": {outcome, score, extend_days, notes}}``). Only the final review changes anybody's status."""
    review = get_object_or_404(ProbationReview.objects.select_related("user"), pk=pk)
    form, refused = api_forms.filled(request, ProbationDecisionForm)
    if refused:
        return refused
    try:
        employees.decide_probation(
            review, request.user,
            outcome=form.cleaned_data["outcome"],
            score=form.cleaned_data.get("score"),
            notes=form.cleaned_data.get("notes", ""),
            extend_days=form.cleaned_data.get("extend_days") or 0,
        )
    except employees.LifecycleError as refusal_:
        return JsonResponse({"ok": False, "error": "refused", "message": refusal_.ar, "message_en": refusal_.en}, status=409)
    return JsonResponse({"ok": True})


@endpoint("POST")
@can_manage
def probation_open(request, pk):
    """Start the three reviews for somebody hired before this existed. Doing it twice makes no more."""
    person = get_object_or_404(User, pk=pk)
    try:
        created = employees.open_probation(person, actor=request.user)
    except employees.LifecycleError as refusal_:
        return JsonResponse({"ok": False, "error": "refused", "message": refusal_.ar, "message_en": refusal_.en}, status=409)
    return JsonResponse({"ok": True, "created": len(created)})


# ---------------------------------------------------------------------------
# Performance
# ---------------------------------------------------------------------------

def _part(part, keys):
    """One indicator: its score, its band, the figures that explain it, and why there is no score when there is none."""
    body = {"score": part.get("score"), "band": _badge(BAND_MAP, performance.band(part.get("score")))}
    for key in keys:
        body[key] = part.get(key)
    if part.get("reason"):
        body["reason"] = _reason(part["reason"])
    return body


def _period_of(request):
    """``(year, month)`` from ``?period=2026-9`` (this month when there is none), or ``None`` for one that is not a month."""
    raw = request.GET.get("period", "")
    if raw:
        return payroll.parse_period(raw)
    today = timezone.localdate()
    return today.year, today.month


def _board_row(row, sees_target):
    """One translator on the board: who, how much, and how that stands against the target (no score: not measured).

    The target is a figure of their pay plan: only those who run the people (HR, the admin) read it; everybody else reads
    the words and the percentage the board is for.
    """
    person = row["person"]
    return {
        "rank": row["rank"],
        "id": person.pk,
        "name": person.short_name,
        "initials": person.initials,
        "avatar": avatars.url_of(person),
        "words": row["words"],
        "target": row["target"] if sees_target else None,
        "score": row["score"],
        "band": _badge(BAND_MAP, performance.band(row["score"])),
        "projects": row["projects"],
    }


@endpoint("GET")
def performance_board(request):
    """Who delivered the most in a month: ``?period=2026-9`` (this month). The best three apart, then everybody else.

    Every signed-in employee reads it (the owner's decision: it is the company's honour board); a person's own page of figures
    (``performance_report``) stays HR's and the admin's. Only translators have words to count; a person with nothing delivered,
    or with no target, is listed but not ranked.
    """
    parsed = _period_of(request)
    if parsed is None:
        return _error(400, "bad_period")
    year, month = parsed
    people = User.objects.filter(is_active=True, role=Role.TRANSLATOR).select_related("salary_plan")
    ranked = performance.board(people, year, month)
    return JsonResponse({
        "ok": True,
        "year": year,
        "month": month,
        "periods": [{"year": a, "month": b} for a, b in payroll.period_choices()],
        "podium": [_board_row(row, request.user.can_recruit) for row in ranked["podium"]],
        "rest": [_board_row(row, request.user.can_recruit) for row in ranked["rest"]],
    })


@endpoint("GET")
@can_recruit
def performance_report(request):
    """Section 20 for one translator and one month: ``?period=2026-9&user=<id>`` (this month, the first translator)."""
    parsed = _period_of(request)
    if parsed is None:
        return _error(400, "bad_period")
    year, month = parsed
    people = User.objects.filter(is_active=True, role=Role.TRANSLATOR)
    if request.GET.get("user"):
        who = _digits(request.GET["user"])
        if who is None:
            return _error(400, "bad_user")
        person = people.filter(pk=who).first()
    else:
        person = people.first()
    report = None
    record = []
    if person is not None:
        # His months, newest first: what he delivered and how that stood against his target.
        record = [dict(row, band=_badge(BAND_MAP, performance.band(row["score"]))) for row in performance.history(person, year, month)]
        figures = performance.for_month(person, year, month)
        parts = figures["parts"]
        report = {
            "weights": figures["weights"],
            "parts": {
                "productivity": _part(parts["productivity"], ("words", "target")),
                "quality": _part(parts["quality"], ("reviewer_avg", "reviewed", "complaints", "violations")),
                "deadline": _part(parts["deadline"], ("late", "total")),
                "attendance": _part(parts["attendance"], ("present", "scheduled", "late_days")),
            },
            "overall": figures["overall"],
            "band": _badge(BAND_MAP, performance.band(figures["overall"])),
            "projects": figures["projects"],
            "returned_projects": figures["returned_projects"],
            "revision_rate": figures["revision_rate"],
        }
    return JsonResponse({
        "ok": True,
        "year": year,
        "month": month,
        "periods": [{"year": a, "month": b} for a, b in payroll.period_choices()],
        "people": [person_json(one) for one in people],
        "person": person_json(person) if person else None,
        "report": report,
        "history": record,
    })


# ---------------------------------------------------------------------------
# Client complaints
# ---------------------------------------------------------------------------

COMPLAINT_TEXT = {
    "summary": ("الملخص", "Summary"),
    "client": ("العميل", "Client"),
    "task": ("التاسك", "Task"),
    "translator": ("المترجم", "Translator"),
    "severity": ("الدرجة", "Severity"),
    "happened_on": ("اليوم", "Date"),
    "detail": ("التفاصيل", "Detail"),
}
COMPLAINT_HINT = {
    "task": (
        "اختار التاسك والمترجم يتحط لوحده. الشكوى بتأثر على مؤشر الجودة في صفحة الأداء.",
        "Pick the task and the translator fills itself in. A complaint moves the quality indicator on the performance page.",
    ),
}


def _complaint_json(row, viewer):
    # The client box is optional and logging by task is the way the form tells people to: the words are about that task's client.
    client = row.client or (row.task.client if row.task_id else None)
    return {
        "id": row.pk,
        "date": row.happened_on.isoformat() if row.happened_on else None,
        "summary": identity.mask_client(row.summary, client, viewer),
        "detail": identity.mask_client(row.detail, client, viewer),
        "translator": row.translator.short_name if row.translator_id else None,
        "task": row.task.code if row.task_id else None,
        "severity": _badge({key: pair for key, pair in SEVERITY_MAP.items()}, row.severity),
        "resolved": row.resolved,
    }


@endpoint("GET")
@can_recruit
def complaints(request):
    """The complaints logged against translators' work, the form that logs one, and the translators to filter by (``?translator=<id>``)."""
    rows = ClientComplaint.objects.select_related("client", "task__client", "translator")
    if request.GET.get("translator"):
        who = _digits(request.GET["translator"])
        if who is None:
            return _error(400, "bad_translator")
        rows = rows.filter(translator_id=who)
    form = named(
        api_forms.describe(ClientComplaintForm()), COMPLAINT_TEXT, COMPLAINT_HINT,
        choices={"severity": {key: (ar, en) for key, (_tone, ar, en) in SEVERITY_MAP.items()}},
    )
    return JsonResponse({
        "ok": True,
        "rows": [_complaint_json(one, request.user) for one in rows[:MAX_COMPLAINTS]],
        "people": [person_json(one) for one in User.objects.filter(is_active=True, role=Role.TRANSLATOR)],
        "form": form,
    })


@endpoint("POST")
@can_recruit
def complaint_create(request):
    """Log a complaint (``{"values": {...}}``). Whoever logs it is written on it; the task's translator fills itself in."""
    form, refused = api_forms.filled(request, ClientComplaintForm)
    if refused:
        return refused
    row = form.save(commit=False)
    row.logged_by = request.user
    row.save()
    services.log(request.user, "complaint.log", row.translator.username if row.translator else "", row.summary[:80])
    return JsonResponse({"ok": True, "id": row.pk})


@endpoint("POST")
@can_recruit
def complaint_resolve(request, pk):
    """Close a complaint, or open it again."""
    row = get_object_or_404(ClientComplaint, pk=pk)
    row.resolved = not row.resolved
    row.save(update_fields=["resolved"])
    services.log(request.user, "complaint.resolve", str(pk))
    return JsonResponse({"ok": True, "resolved": row.resolved})


# ---------------------------------------------------------------------------
# Salary change requests: HR asks, the owner decides
# ---------------------------------------------------------------------------

REQUEST_TEXT = {
    "new_amount": ("الراتب الجديد", "New salary"),
    "effective_from": ("ساري من", "Effective from"),
    "reason": ("السبب", "Reason"),
}


def _salary_request_json(row):
    return {
        "id": row.pk,
        "user": person_json(row.user),
        "current_amount": str(row.current_amount),
        "new_amount": str(row.new_amount),
        "delta": str(row.delta),
        "effective_from": row.effective_from.isoformat(),
        "reason": row.reason,
        "status": row.status,
        "requested_by": row.requested_by.short_name if row.requested_by_id else None,
        "decided_by": row.decided_by.short_name if row.decided_by_id else None,
    }


@endpoint("GET")
@can_recruit
def salary_requests(request):
    """What waits for the owner, the decisions so far, and the form that asks for a change for the person ``?user=<id>`` names."""
    people = rule_followers(User.objects.filter(is_active=True))
    person = None
    if request.GET.get("user"):
        who = _digits(request.GET["user"])
        if who is None:
            return _error(400, "bad_user")
        person = people.filter(pk=who).first()
    today = timezone.localdate()
    form = SalaryChangeRequestForm(initial={"effective_from": today})
    return JsonResponse({
        "ok": True,
        "people": [person_json(one) for one in people],
        "person": person_json(person) if person else None,
        "current": str(SalaryRecord.amount_on(person, today)) if person else None,
        "form": named(api_forms.describe(form), REQUEST_TEXT),
        "pending": [
            _salary_request_json(one)
            for one in SalaryChangeRequest.objects.filter(status=ApprovalStatus.PENDING).select_related("user", "requested_by")
        ],
        "decided": [
            _salary_request_json(one)
            for one in SalaryChangeRequest.objects.exclude(status=ApprovalStatus.PENDING).select_related("user", "decided_by")[:MAX_DECIDED]
        ],
        "can": {"decide": request.user.can_approve_hiring},
    })


@endpoint("POST")
@can_recruit
def salary_request_create(request):
    """Ask the owner for a change (``{"user": id, "values": {new_amount, effective_from, reason}}``). Nothing moves until they approve."""
    try:
        body = _object(request)
        who = body.get("user")
        values = body.get("values", {})
        if isinstance(who, bool) or not isinstance(who, int) or not 0 < who < 2 ** 63 or not isinstance(values, dict):
            raise BadBody
        # The page draws the date box as today and sends only what was typed: "from today" is a request that arrives without it.
        data = api_forms.form_data(
            SalaryChangeRequestForm, values, form_kwargs={"initial": {"effective_from": timezone.localdate()}},
        )
    except (BadBody, api_forms.BadValues):
        return _error(400, "bad_body")
    person = get_object_or_404(User, pk=who, is_active=True)
    form = SalaryChangeRequestForm(data)
    if not form.is_valid():
        return api_forms.invalid(form)
    try:
        row = employees.request_salary_change(
            person,
            new_amount=form.cleaned_data["new_amount"],
            effective_from=form.cleaned_data["effective_from"],
            reason=form.cleaned_data.get("reason", ""),
            actor=request.user,
        )
    except employees.LifecycleError as refused:
        return JsonResponse({"ok": False, "error": "refused", "message": refused.ar, "message_en": refused.en}, status=409)
    return JsonResponse({"ok": True, "id": row.pk})


@endpoint("POST")
@is_owner
def salary_request_decide(request, pk, action):
    """Approve or reject (``{"note": "..."}``). The owner's alone; approval is what writes the salary record."""
    if action not in ("approve", "reject"):
        return _error(404, "not_found")
    try:
        note = _object(request).get("note", "")
    except BadBody:
        return _error(400, "bad_body")
    if not isinstance(note, str) or len(note) > 250 or "\x00" in note:
        return _error(400, "bad_body")
    row = get_object_or_404(SalaryChangeRequest.objects.select_related("user"), pk=pk)
    try:
        employees.decide_salary_change(row, request.user, approve=(action == "approve"), note=note)
    except employees.LifecycleError as refused:
        return JsonResponse({"ok": False, "error": "refused", "message": refused.ar, "message_en": refused.en}, status=409)
    return JsonResponse({"ok": True})


# ---------------------------------------------------------------------------
# Salary plans: the owner's, they move money
# ---------------------------------------------------------------------------

PLAN_TEXT = {
    "name": ("الاسم", "Name"),
    "note": ("ملاحظة", "Note"),
    "daily_target_words": ("التارجت اليومي", "Daily quota"),
    "secondary_daily_target_words": ("التارجت اليومي (لغة تانية)", "Daily quota (second language)"),
    "monthly_target_words": ("التارجت الشهري", "Monthly quota"),
    "extra_word_rate": ("سعر الكلمة الزيادة", "Rate per extra word"),
    "fixed_allowance": ("بدل ثابت شهري", "Fixed allowance"),
    "discipline_bonus": ("مكافأة الانضباط", "Discipline bonus"),
    "target_bonus": ("مكافأة التارجت", "Target bonus"),
    "target_miss_penalty": ("خصم عدم تحقيق التارجت", "Target-miss penalty"),
    "working_days_per_month": ("أيام العمل", "Working days"),
    "monthly_leave_allowance": ("رصيد الإجازات", "Leave allowance"),
    "overtime_hourly_rate": ("سعر ساعة الأوفرتايم", "Overtime rate"),
    "is_active": ("شغالة", "Active"),
}
PLAN_HINT = {
    "extra_word_rate": ("سيبه فاضي عشان يفضل على شرائح البونص.", "Blank keeps the bonus bands."),
}
#: The company's own numbers a plan falls back to, shown beside the matching box.
PLAN_COMPANY = ("daily_target_words", "monthly_target_words", "discipline_bonus", "target_bonus", "working_days_per_month", "monthly_leave_allowance")


def _plan_hints(conf):
    """The help lines under the plan's boxes: what a blank one falls back to is the company's number, said beside the box."""
    hints = dict(PLAN_HINT)
    for name in PLAN_COMPANY:
        hints[name] = (f"الشركة: {getattr(conf, name)}", f"Company: {getattr(conf, name)}")
    return hints


def _plan_json(plan):
    return {
        "id": plan.pk,
        "name": plan.name,
        "note": plan.note,
        "is_active": plan.is_active,
        "overrides": plan.overrides(),
        "extra_word_rate": str(plan.extra_word_rate) if plan.extra_word_rate is not None else None,
        "fixed_allowance": str(plan.fixed_allowance),
        "members": plan.member_count,
    }


@endpoint("GET")
@api_role_required(Role.ADMIN)
def salary_plans(request):
    """The plans with who is on each, the form (blank, or the plan ``?edit=<id>`` names) and the company's own numbers."""
    raw = request.GET.get("edit") or ""
    editing = SalaryPlan.objects.filter(pk=raw).first() if raw.isascii() and raw.isdecimal() and len(raw) < 18 else None
    conf = PayrollSettings.load()
    return JsonResponse({
        "ok": True,
        "rows": [_plan_json(one) for one in SalaryPlan.objects.annotate(member_count=Count("members"))],
        "editing": editing.pk if editing else None,
        "form": named(api_forms.describe(SalaryPlanForm(instance=editing)), PLAN_TEXT, _plan_hints(conf)),
        "unassigned": User.objects.filter(is_active=True, role=Role.TRANSLATOR, salary_plan__isnull=True).count(),
    })


@endpoint("POST")
@api_role_required(Role.ADMIN)
def salary_plan_save(request):
    """Add a plan, or change one (``{"id": 3, "values": {...}}``). Every number is optional; a blank one keeps the company's."""
    try:
        body = _object(request)
        which = body.get("id")
        values = body.get("values", {})
        if which is not None and (isinstance(which, bool) or not isinstance(which, int) or not 0 < which < 2 ** 63):
            raise BadBody
        if not isinstance(values, dict):
            raise BadBody
    except BadBody:
        return _error(400, "bad_body")
    editing = get_object_or_404(SalaryPlan, pk=which) if which is not None else None
    try:
        data = api_forms.form_data(SalaryPlanForm, values, instance=editing)
    except api_forms.BadValues:
        return _error(400, "bad_body")
    form = SalaryPlanForm(data, instance=editing)
    if not form.is_valid():
        return api_forms.invalid(form)
    row = form.save(commit=False)
    if not row.pk:
        row.created_by = request.user
    row.save()
    services.log(request.user, "salary.plan.save", row.name)
    return JsonResponse({"ok": True, "id": row.pk})
