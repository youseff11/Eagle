"""Employee lifecycle: probation, leave, and moving somebody's salary.

The three have nothing to do with each other except the rule they share,
which is the rule the whole of Eagle is built on: **the engine works out what
is true, and a person decides what happens about it.**

* Probation reviews exist as dated rows from the day somebody is hired, so a
  missed review is visible rather than forgotten. The engine never confirms
  or ends anybody - it only says a review is due.
* An approved leave writes itself onto the attendance sheet. That is the
  point: a leave the payroll cannot see is a leave that turns into an
  unexcused absence and a deduction three weeks later.
* A salary moves only when the owner approves a request. HR cannot reach
  ``SalaryRecord`` at all; this module is the whole of the path.
"""

from datetime import timedelta
from decimal import Decimal

from django.db import transaction
from django.db.models import Q
from django.utils import timezone

from . import attendance, services
from .models import (
    ApprovalStatus,
    DayStatus,
    Notification,
    EmploymentStatus,
    LEAVE_STATUSES,
    LeaveKind,
    LeaveRequest,
    LeaveStatus,
    PayrollSettings,
    ProbationOutcome,
    ProbationReview,
    ProbationStage,
    RecruitmentSettings,
    Role,
    SalaryChangeRequest,
    SalaryRecord,
    User,
    WorkDay,
)

class LifecycleError(Exception):
    """Something the rules will not do. Carries a bilingual reason."""

    def __init__(self, ar, en):
        super().__init__(en)
        self.ar = ar
        self.en = en


def hr_people():
    return User.objects.filter(is_active=True).filter(
        Q(role=Role.HR) | Q(role=Role.ADMIN) | Q(is_superuser=True)
    ).distinct()


def _notify_hr(**kwargs):
    for person in hr_people():
        services.notify(person, **kwargs)


def _notify_owner(**kwargs):
    for person in User.objects.filter(is_active=True, role=Role.ADMIN):
        services.notify(person, **kwargs)


# ---------------------------------------------------------------------------
# Probation - section 19
# ---------------------------------------------------------------------------

#: How far into the probation each review falls. The last one is pinned to
#: the probation's own end date rather than a fixed offset, so shortening or
#: extending the period moves it with them.
STAGE_OFFSETS = (
    (ProbationStage.DAY_30, 30),
    (ProbationStage.DAY_60, 60),
)


@transaction.atomic
def open_probation(person, actor=None, start=None, end=None):
    """Create the three reviews for somebody who has just been hired.

    Idempotent: calling it twice does not produce six reviews, and it never
    touches a review somebody has already decided.
    """
    conf = RecruitmentSettings.load()
    start = start or person.probation_start or person.joining_date or timezone.localdate()
    end = end or person.probation_end or (start + timedelta(days=conf.probation_days or 90))

    rows = []
    for stage, offset in STAGE_OFFSETS:
        due = start + timedelta(days=offset)
        # A probation shorter than the offset would put a review after it
        # ends, which reads as a mistake. Clamp it to the end instead.
        rows.append((stage, min(due, end)))
    rows.append((ProbationStage.FINAL, end))

    created = []
    for stage, due in rows:
        review, made = ProbationReview.objects.get_or_create(
            user=person, stage=stage, defaults={"due_date": due}
        )
        if made:
            created.append(review)
        elif not review.is_decided and review.due_date != due:
            review.due_date = due
            review.save(update_fields=["due_date"])

    if created:
        services.log(
            actor, "probation.open", person.username,
            f"{len(created)} reviews, {start} to {end}",
        )
    return created


@transaction.atomic
def decide_probation(review, actor, outcome, score=None, notes="", extend_days=0):
    """Record a review's verdict and apply what it means to the person.

    Only the final review changes anybody's status. A thirty-day review that
    says "extended" moves the end date and the final review with it; it does
    not confirm or end anyone, because that is not what a thirty-day review
    is for.
    """
    if outcome not in ProbationOutcome.values or outcome == ProbationOutcome.PENDING:
        raise LifecycleError("النتيجة مش مظبوطة.", "That is not a decision.")
    if review.is_decided:
        raise LifecycleError(
            "المراجعة دي اتقرر فيها بالفعل.", "This review has already been decided."
        )

    person = review.user
    review.outcome = outcome
    review.score = score
    review.notes = notes[:2000]
    review.reviewer = actor
    review.decided_at = timezone.now()

    if outcome == ProbationOutcome.EXTENDED:
        days = int(extend_days or 30)
        new_end = (person.probation_end or timezone.localdate()) + timedelta(days=days)
        review.extended_to = new_end
        person.probation_end = new_end
        person.save(update_fields=["probation_end"])
        # The final review follows the period it belongs to.
        final = ProbationReview.objects.filter(
            user=person, stage=ProbationStage.FINAL, outcome=ProbationOutcome.PENDING
        ).first()
        if final is not None:
            final.due_date = new_end
            final.save(update_fields=["due_date"])

    elif outcome == ProbationOutcome.CONFIRMED and review.stage == ProbationStage.FINAL:
        person.employment_status = EmploymentStatus.ACTIVE
        person.save(update_fields=["employment_status"])

    elif outcome == ProbationOutcome.TERMINATED:
        # Ending somebody is the one outcome that closes the account, and it
        # closes it rather than deleting anything - their months still have
        # to be readable afterwards.
        person.employment_status = EmploymentStatus.LEFT
        person.is_active = False
        person.save(update_fields=["employment_status", "is_active"])

    review.save()
    services.log(
        actor, f"probation.{outcome}", person.username,
        f"{review.stage} {notes}".strip(),
    )
    services.notify(
        person,
        title_ar="مراجعة فترة الاختبار",
        title_en="Probation review",
        body_ar=f"اتسجلت نتيجة مراجعة {review.get_stage_display()}.",
        body_en=f"Your {review.get_stage_display()} has been recorded.",
        level="info",
    )
    return review


def probation_sweep(now=None):
    """Tell HR about reviews that have come due. Once each."""
    now = now or timezone.localdate()
    raised = 0
    due = ProbationReview.objects.filter(
        outcome=ProbationOutcome.PENDING, due_date__lte=now, user__is_active=True
    ).select_related("user")
    for review in due:
        marker = f"probation:{review.pk}"
        if Notification.objects.filter(url=f"/hr/probation/#{marker}").exists():
            continue
        _notify_hr(
            title_ar="مراجعة فترة اختبار مستحقة",
            title_en="Probation review due",
            body_ar=f"{review.user.short_name} — {review.get_stage_display()} استحقت يوم {review.due_date}.",
            body_en=f"{review.user.short_name}: the {review.get_stage_display()} was due on {review.due_date}.",
            level="warning", url=f"/hr/probation/#{marker}",
        )
        raised += 1
    return raised


# ---------------------------------------------------------------------------
# Leave - section 22
# ---------------------------------------------------------------------------

def leave_balance(person, year, month, conf=None):
    """How much of the month's allowance is already spoken for.

    Counts the days the attendance sheet already shows as leave, plus days
    sitting in requests nobody has decided yet - because a balance that
    ignores pending requests lets two of them be approved into the same
    empty allowance.
    """
    from . import payroll

    conf = conf or PayrollSettings.load()
    allowance = effective_leave_allowance(person, conf)
    first_day, last_day = payroll.month_bounds(year, month)

    taken = WorkDay.objects.filter(
        user=person, date__range=(first_day, last_day), status__in=LEAVE_STATUSES
    ).count()

    pending = 0
    for row in LeaveRequest.objects.filter(
        user=person, status__in=(LeaveStatus.PENDING, LeaveStatus.MANAGER_OK)
    ).exclude(kind=LeaveKind.PERMISSION):
        pending += sum(1 for day in row.dates() if first_day <= day <= last_day)

    return {
        "allowance": allowance,
        "taken": taken,
        "pending": pending,
        "left": max(0, allowance - taken - pending),
        "over": max(0, taken + pending - allowance),
    }


def effective_leave_allowance(person, conf=None):
    """The person's plan wins; otherwise the company's number."""
    conf = conf or PayrollSettings.load()
    plan = getattr(person, "salary_plan", None)
    if plan is not None and plan.monthly_leave_allowance is not None:
        return plan.monthly_leave_allowance
    return conf.monthly_leave_allowance


@transaction.atomic
def request_leave(person, *, kind, start_date, end_date=None, start_time=None,
                  end_time=None, reason="", actor=None):
    """Raise a request. Validation here, decisions elsewhere."""
    conf = PayrollSettings.load()
    end_date = end_date or start_date

    if end_date < start_date:
        raise LifecycleError(
            "تاريخ النهاية قبل البداية.", "The end date is before the start date."
        )

    minutes = 0
    if kind == LeaveKind.PERMISSION:
        if not (start_time and end_time):
            raise LifecycleError(
                "الإذن محتاج وقت بداية ونهاية.", "A permission needs a start and an end time."
            )
        end_date = start_date
        minutes = (
            (end_time.hour * 60 + end_time.minute) - (start_time.hour * 60 + start_time.minute)
        )
        if minutes <= 0:
            raise LifecycleError(
                "وقت النهاية لازم يكون بعد البداية.", "The end time must be after the start."
            )
        if minutes > (conf.permission_max_minutes or 240):
            raise LifecycleError(
                f"أطول إذن مسموح {conf.permission_max_minutes} دقيقة.",
                f"The longest permission is {conf.permission_max_minutes} minutes.",
            )

    # Two permissions on one day are fine - two leaves over the same days are
    # not, and would each be written onto the attendance sheet.
    if kind != LeaveKind.PERMISSION:
        clash = LeaveRequest.objects.filter(
            user=person,
            status__in=(
                LeaveStatus.PENDING, LeaveStatus.MANAGER_OK, LeaveStatus.APPROVED,
            ),
            start_date__lte=end_date, end_date__gte=start_date,
        ).exclude(kind=LeaveKind.PERMISSION)
        if clash.exists():
            raise LifecycleError(
                "فيه طلب تاني على نفس الأيام.", "Another request already covers those days."
            )

    row = LeaveRequest.objects.create(
        user=person, kind=kind, start_date=start_date, end_date=end_date,
        start_time=start_time, end_time=end_time, minutes=minutes,
        reason=reason[:250],
        manager=person.team_lead,
        status=(
            LeaveStatus.PENDING if conf.leave_needs_manager else LeaveStatus.MANAGER_OK
        ),
    )

    # Whoever has to act first is the one who gets told.
    if conf.leave_needs_manager and person.team_lead_id:
        services.notify(
            person.team_lead,
            title_ar="طلب إجازة مستني موافقتك",
            title_en="Leave request awaiting you",
            body_ar=f"{person.short_name} طلب {row.get_kind_display()} من {row.start_date}.",
            body_en=f"{person.short_name} requested {row.get_kind_display()} from {row.start_date}.",
            level="info", url="/hr/leave/",
        )
    else:
        _notify_hr(
            title_ar="طلب إجازة جديد",
            title_en="New leave request",
            body_ar=f"{person.short_name} طلب {row.get_kind_display()} من {row.start_date}.",
            body_en=f"{person.short_name} requested {row.get_kind_display()} from {row.start_date}.",
            level="info", url="/hr/leave/",
        )
    services.log(actor or person, "leave.request", person.username, f"{kind} {start_date}")
    return row


def can_decide_leave(request_row, user):
    """Who is allowed to move this request along, at this moment."""
    if user.is_admin_role:
        return True
    if request_row.status == LeaveStatus.PENDING:
        return request_row.manager_id == user.id or user.can_manage_attendance
    if request_row.status == LeaveStatus.MANAGER_OK:
        return user.can_manage_attendance
    return False


@transaction.atomic
def decide_leave(request_row, actor, approve, note=""):
    """Move a request one step. Two steps exist only if the settings say so."""
    if not request_row.is_open:
        raise LifecycleError(
            "الطلب ده اتقرر فيه بالفعل.", "This request has already been decided."
        )
    if not can_decide_leave(request_row, actor):
        raise LifecycleError(
            "مش من صلاحيتك تقرر في الطلب ده.", "You cannot decide this request."
        )

    now = timezone.now()
    was = request_row.status
    request_row.decision_note = note[:250]

    if not approve:
        request_row.status = LeaveStatus.REJECTED
        if was == LeaveStatus.PENDING:
            request_row.manager_decided_at = now
        request_row.hr_decision_by = actor
        request_row.hr_decided_at = now
        request_row.save()
        services.notify(
            request_row.user,
            title_ar="طلب الإجازة اترفض",
            title_en="Leave request rejected",
            body_ar=note or "الطلب اترفض.",
            body_en=note or "Your request was rejected.",
            level="warning", url="/leave/",
        )
        services.log(actor, "leave.reject", request_row.user.username, note)
        return request_row

    # -- the manager's step -------------------------------------------------
    if was == LeaveStatus.PENDING and not actor.can_manage_attendance:
        request_row.status = LeaveStatus.MANAGER_OK
        request_row.manager_decided_at = now
        request_row.save()
        _notify_hr(
            title_ar="طلب إجازة وافق عليه المدير",
            title_en="Leave approved by the manager",
            body_ar=f"{request_row.user.short_name} — مستني اعتماد الـHR.",
            body_en=f"{request_row.user.short_name} is waiting for HR.",
            level="info", url="/hr/leave/",
        )
        services.log(actor, "leave.manager_ok", request_row.user.username)
        return request_row

    # -- HR's step, which is also what writes the days ----------------------
    request_row.status = LeaveStatus.APPROVED
    request_row.hr_decision_by = actor
    request_row.hr_decided_at = now
    if request_row.manager_decided_at is None:
        request_row.manager_decided_at = now
    request_row.save()

    written, skipped = apply_leave(request_row, actor)
    services.notify(
        request_row.user,
        title_ar="طلب الإجازة اتوافق عليه",
        title_en="Leave approved",
        body_ar=f"{request_row.get_kind_display()} من {request_row.start_date}.",
        body_en=f"{request_row.get_kind_display()} from {request_row.start_date}.",
        level="success", url="/leave/",
    )
    services.log(
        actor, "leave.approve", request_row.user.username,
        f"{written} days written, {len(skipped)} skipped",
    )
    if skipped:
        _notify_hr(
            title_ar="أيام إجازة مااتكتبتش",
            title_en="Some leave days were not written",
            body_ar=(
                f"{request_row.user.short_name}: فيه أيام مسجّل عليها حضور فعلي "
                f"({', '.join(str(d) for d in skipped[:5])}) — راجعها بإيدك."
            ),
            body_en=(
                f"{request_row.user.short_name} already has attendance on "
                f"{', '.join(str(d) for d in skipped[:5])} - check those by hand."
            ),
            level="warning", url="/hr/attendance/",
        )
    return request_row


@transaction.atomic
def apply_leave(request_row, actor=None):
    """Write an approved request onto the attendance sheet.

    Returns ``(days_written, skipped_dates)``. A day the person actually
    punched is never overwritten - that is evidence, and silently replacing
    it with "on leave" would destroy the one record that says otherwise.
    HR is told about those days instead.
    """
    if request_row.applied_at:
        return 0, []

    person = request_row.user
    written, skipped = 0, []

    if request_row.is_permission:
        # A permission is minutes off one day, not a day off. It lands on the
        # day itself so the shortfall it causes stops being a shortfall.
        day, _ = WorkDay.objects.get_or_create(
            user=person, date=request_row.start_date,
            defaults={"status": DayStatus.PRESENT},
        )
        day.excused_minutes = min(32000, day.excused_minutes + request_row.minutes)
        day.note = (day.note or "")[:200]
        attendance.recompute(day)
        written = 1
    else:
        status = request_row.day_status
        for date in request_row.dates():
            day = WorkDay.objects.filter(user=person, date=date).first()
            if day is not None and day.check_in:
                skipped.append(date)
                continue
            plan = attendance.plan_for(person, date)
            if not plan.working:
                # A day off does not consume leave, so it is left alone.
                continue
            if day is None:
                day = WorkDay(user=person, date=date)
            day.status = status
            day.absence_reason = (
                request_row.reason or request_row.get_kind_display()
            )[:200]
            day.save()
            written += 1

    request_row.applied_at = timezone.now()
    request_row.save(update_fields=["applied_at"])
    return written, skipped


# ---------------------------------------------------------------------------
# Salary changes - section 23
# ---------------------------------------------------------------------------

@transaction.atomic
def request_salary_change(person, *, new_amount, effective_from, reason="", actor=None):
    """HR's ask. It is the only way a salary can start moving."""
    new_amount = Decimal(new_amount)
    if new_amount < 0:
        raise LifecycleError("الراتب مايكونش بالسالب.", "A salary cannot be negative.")

    current = SalaryRecord.amount_on(person, effective_from)
    if new_amount == current:
        raise LifecycleError(
            "الرقم ده هو الراتب الحالي.", "That is already the current salary."
        )
    if SalaryChangeRequest.objects.filter(
        user=person, status=ApprovalStatus.PENDING
    ).exists():
        raise LifecycleError(
            "فيه طلب تاني لسه مستني للموظف ده.",
            "This person already has a request waiting.",
        )

    row = SalaryChangeRequest.objects.create(
        user=person, current_amount=current, new_amount=new_amount,
        effective_from=effective_from, reason=reason[:250], requested_by=actor,
    )
    _notify_owner(
        title_ar="طلب تغيير راتب",
        title_en="Salary change requested",
        body_ar=f"{person.short_name}: {current} ← {new_amount}",
        body_en=f"{person.short_name}: {current} to {new_amount}",
        level="warning", url="/hr/salary-requests/",
    )
    services.log(
        actor, "salary.request", person.username, f"{current} -> {new_amount} {reason}".strip()
    )
    return row


@transaction.atomic
def decide_salary_change(row, actor, approve, note=""):
    """The owner's call. Approving is what writes the history record."""
    if not actor.can_approve_hiring:
        raise LifecycleError(
            "تغيير الرواتب للمالك بس.", "Only the owner decides a salary change."
        )
    if not row.is_pending:
        raise LifecycleError(
            "الطلب ده اتقرر فيه بالفعل.", "This request has already been decided."
        )

    row.status = ApprovalStatus.APPROVED if approve else ApprovalStatus.REJECTED
    row.decided_by = actor
    row.decided_at = timezone.now()
    row.decision_note = note[:250]

    if approve:
        row.salary_record = SalaryRecord.objects.create(
            user=row.user, amount=row.new_amount,
            effective_from=row.effective_from,
            note=(row.reason or "salary change")[:200], created_by=actor,
        )
    row.save()
    services.log(
        actor, "salary." + ("approve" if approve else "reject"),
        row.user.username, f"{row.current_amount} -> {row.new_amount}",
    )
    _notify_hr(
        title_ar="قرار في طلب تغيير راتب",
        title_en="Salary request decided",
        body_ar=f"{row.user.short_name}: {'اتوافق عليه' if approve else 'اترفض'}",
        body_en=f"{row.user.short_name}: {'approved' if approve else 'rejected'}",
        level="info", url="/hr/salary-requests/",
    )
    return row


# ---------------------------------------------------------------------------
# The sweep entry point
# ---------------------------------------------------------------------------

def sweep(now=None):
    """Everything in this module that is time-based rather than click-based."""
    return {"probation": probation_sweep(now)}
