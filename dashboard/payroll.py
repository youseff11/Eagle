"""The accounts engine: turn attendance plus jobs into a translator's month.

Two rules shape everything in here.

**Production is read, never typed.** A translator's word count comes from the
tasks they actually delivered (``Task.word_count`` on the day the translation
landed). ``WorkDay.words`` is a refreshed cache of that sum, so the payroll and
the job log can never disagree.

**Nothing that costs money is automatic.** Every deduction is raised as a
``Violation`` in the pending state and only reaches the net once a manager
approves it. The two bonuses go the other way: the system decides they were
earned, and approval releases the money.

The daily bonus band is open on the left: a day pays a tier when
``min_words < words <= max_words``. Hitting the daily target exactly is the
job, not a bonus - 3,000 words pays nothing extra, 3,001 enters the first
tier. Beating the monthly target is what the 250 target bonus is for.
"""

from calendar import monthrange
from datetime import date, datetime, time
from decimal import Decimal, ROUND_HALF_UP

from django.db.models import Sum
from django.utils import timezone

from . import attendance
from .models import (
    ApprovalStatus,
    AuditLog,
    DayStatus,
    LEAVE_STATUSES,
    OvertimeClaim,
    PayrollLine,
    PayrollPeriod,
    PayrollSettings,
    PeriodStatus,
    ProductionTier,
    Role,
    SalaryRecord,
    Task,
    TaskStatus,
    User,
    Violation,
    ViolationKind,
    WorkDay,
)

MONEY = Decimal("0.01")


def money(value):
    return Decimal(value).quantize(MONEY, rounding=ROUND_HALF_UP)


def month_bounds(year, month):
    last = monthrange(year, month)[1]
    return date(year, month, 1), date(year, month, last)


# ---------------------------------------------------------------------------
# Production - read from the jobs, not from the translator
# ---------------------------------------------------------------------------

#: A cancelled job produced nothing. Everything from "translated" onwards did.
COUNTED_TASK_STATUSES = (
    TaskStatus.UNDER_REVIEW,
    TaskStatus.REVIEWED,
    TaskStatus.DELIVERED,
)


def tasks_for(user, first_day, last_day):
    """Jobs whose translation landed inside the window."""
    start = timezone.make_aware(datetime.combine(first_day, time.min))
    end = timezone.make_aware(datetime.combine(last_day, time.max))
    return Task.objects.filter(
        translator=user,
        status__in=COUNTED_TASK_STATUSES,
        translated_at__range=(start, end),
    )


def refresh_words(user, first_day, last_day):
    """Re-derive every ``WorkDay.words`` in the window from the job log.

    A day with jobs but no attendance row gets one: the translation is proof
    the person worked, and a missing row would silently drop their production.
    """
    by_day = {}
    for task in tasks_for(user, first_day, last_day).only(
        "word_count", "translated_at", "delivered_at", "is_difficult",
        "is_secondary_language",
    ):
        day = task.production_date
        if day is None:
            continue
        bucket = by_day.setdefault(day, {"words": 0, "difficult": False, "secondary": False})
        bucket["words"] += task.word_count or 0
        bucket["difficult"] = bucket["difficult"] or task.is_difficult
        bucket["secondary"] = bucket["secondary"] or task.is_secondary_language

    existing = {row.date: row for row in WorkDay.objects.filter(
        user=user, date__range=(first_day, last_day)
    )}

    touched = []
    for day, bucket in by_day.items():
        row = existing.get(day)
        if row is None:
            row = WorkDay(user=user, date=day, status=DayStatus.PRESENT)
        row.words = bucket["words"]
        row.words_from_jobs = True
        # The manager's own flags on the day win; the jobs can only set them.
        row.difficult_file = row.difficult_file or bucket["difficult"]
        row.is_secondary_language = row.is_secondary_language or bucket["secondary"]
        row.save()
        touched.append(row)

    # A day the jobs used to fill and no longer do really did produce nothing -
    # a task was cancelled, reassigned or corrected away. A day the admin typed
    # in by hand is not touched; nothing in the job log claims to know better.
    for day, row in existing.items():
        if day not in by_day and row.words and row.words_from_jobs:
            row.words = 0
            row.save(update_fields=["words"])
    return touched


# ---------------------------------------------------------------------------
# Violations the engine raises by itself (always pending)
# ---------------------------------------------------------------------------

def _draft(user, day, kind, key, reason, days=Decimal("0.00"), amount=Decimal("0.00"),
           escalated=False, actor=None):
    """Create - or refresh - one pending draft. Approved rows are left alone.

    ``auto_key`` makes the write idempotent: recomputing a month a dozen times
    must not leave a dozen identical deductions waiting for the manager.
    """
    existing = Violation.objects.filter(user=user, auto_key=key).first()
    if existing is not None:
        if existing.status != ApprovalStatus.PENDING:
            return existing
        existing.date = day
        existing.penalty_days = days
        existing.penalty_amount = amount
        existing.reason = reason
        existing.escalated = escalated
        existing.save(update_fields=[
            "date", "penalty_days", "penalty_amount", "reason", "escalated"
        ])
        return existing
    return Violation.objects.create(
        user=user, date=day, kind=kind, auto_key=key, reason=reason,
        penalty_days=days, penalty_amount=amount, escalated=escalated,
        created_by=actor,
    )


def raise_drafts(user, year, month, days, conf, actor=None):
    """Turn what the month shows into deductions waiting for a decision."""
    first_day, last_day = month_bounds(year, month)
    stamp = f"{year}-{month:02d}"
    drafts = []

    # 1. Absence without permission. The escalation count is per month.
    unexcused = [d for d in days if d.status == DayStatus.UNEXCUSED]
    for index, day in enumerate(sorted(unexcused, key=lambda d: d.date), start=1):
        escalated = index >= conf.unexcused_escalation_count
        reason = f"absence without permission ({index})"
        if escalated:
            reason += " - escalated to the owner"
        drafts.append(_draft(
            user, day.date, ViolationKind.UNEXCUSED, f"unexcused:{day.date:%Y-%m-%d}",
            reason, days=conf.unexcused_penalty_days, escalated=escalated, actor=actor,
        ))

    # 2. Leave beyond the monthly balance: a day plus a quarter, each.
    leave_days = [d for d in days if d.status in LEAVE_STATUSES]
    extra = max(0, len(leave_days) - conf.monthly_leave_allowance)
    for day in sorted(leave_days, key=lambda d: d.date)[len(leave_days) - extra:]:
        drafts.append(_draft(
            user, day.date, ViolationKind.EXTRA_LEAVE, f"extra_leave:{day.date:%Y-%m-%d}",
            "leave day beyond the monthly balance",
            days=conf.extra_leave_penalty_days, actor=actor,
        ))

    # 3. Low productivity on an ordinary file. A difficult file is exempt, and
    #    that exemption is the project manager's call, not the engine's.
    for day in days:
        if day.is_under_target(conf):
            drafts.append(_draft(
                user, day.date, ViolationKind.LOW_OUTPUT, f"low_output:{day.date:%Y-%m-%d}",
                f"{day.words} words against a floor of {day.target(conf)}",
                days=conf.low_output_penalty_days, actor=actor,
            ))

    # 4. The month as a whole falling under the alert line.
    total_words = sum(d.words for d in days if d.is_working_day)
    if total_words < conf.monthly_alert_words:
        drafts.append(_draft(
            user, last_day, ViolationKind.TARGET_MISS, f"target_miss:{stamp}",
            f"{total_words} words against an alert line of {conf.monthly_alert_words}",
            amount=conf.target_miss_penalty, actor=actor,
        ))
    else:
        # The month recovered on a later recalculation - drop the stale draft.
        Violation.objects.filter(
            user=user, auto_key=f"target_miss:{stamp}", status=ApprovalStatus.PENDING
        ).delete()

    return [d for d in drafts if d is not None]


# ---------------------------------------------------------------------------
# The month itself
# ---------------------------------------------------------------------------

def compute_line(user, year, month, conf=None, tiers=None, save_to=None, actor=None):
    """Work out one translator's month and, when given a period, store it."""
    conf = conf or PayrollSettings.load()
    tiers = tiers if tiers is not None else list(ProductionTier.objects.all())
    first_day, last_day = month_bounds(year, month)

    refresh_words(user, first_day, last_day)
    days = list(WorkDay.objects.filter(user=user, date__range=(first_day, last_day)).order_by("date"))

    # The salary in force during the month, not today's salary.
    base = SalaryRecord.amount_on(user, last_day)
    working_days = conf.working_days_per_month or 1
    day_value = money(base / Decimal(working_days))

    worked = [d for d in days if d.is_working_day]
    leave_days = [d for d in days if d.status in LEAVE_STATUSES]
    unexcused_days = [d for d in days if d.status == DayStatus.UNEXCUSED]
    extra_leave = max(0, len(leave_days) - conf.monthly_leave_allowance)

    total_words = sum(d.words for d in worked)
    under_target = [d for d in worked if d.is_under_target(conf)]

    # -- what attendance says about the month -------------------------------
    # Read off the day rows, which carry the shift they were *worked under*.
    # Nothing here re-reads today's roster, so a schedule change next month
    # cannot rewrite a month already recorded.
    summary = attendance.month_summary(user, first_day, last_day)

    # Overtime is the mirror image of a deduction: the engine works out that
    # the time was worked, and the manager's approval is what pays for it.
    attendance.raise_overtime(user, first_day, last_day, conf=conf, day_value=day_value)
    overtime_rows = []
    overtime_bonus = Decimal("0.00")
    for claim in OvertimeClaim.objects.filter(user=user, date__range=(first_day, last_day)):
        if claim.status == ApprovalStatus.APPROVED:
            overtime_bonus += Decimal(claim.amount)
        overtime_rows.append({
            "date": claim.date.isoformat(),
            "minutes": claim.minutes,
            "rate": str(claim.hourly_rate),
            "amount": str(money(claim.amount)),
            "status": claim.status,
        })

    # -- the daily production bonus ----------------------------------------
    production_bonus = Decimal("0.00")
    day_rows = []
    for day in days:
        bonus = day.bonus(tiers=tiers)
        production_bonus += bonus
        day_rows.append({
            "date": day.date.isoformat(),
            "status": day.status,
            "words": day.words,
            "target": day.target(conf),
            "secondary": day.is_secondary_language,
            "difficult": day.difficult_file,
            "bonus": str(money(bonus)),
        })

    raise_drafts(user, year, month, days, conf, actor=actor)

    # -- deductions: only what a manager has approved ------------------------
    approved = Violation.objects.filter(
        user=user, date__range=(first_day, last_day), status=ApprovalStatus.APPROVED
    )
    deduction_rows = []
    deductions = Decimal("0.00")
    for row in approved:
        amount = money(Decimal(row.penalty_days) * day_value + Decimal(row.penalty_amount))
        deductions += amount
        deduction_rows.append({
            "date": row.date.isoformat(),
            "kind": row.kind,
            "reason": row.reason,
            "days": str(row.penalty_days),
            "amount": str(amount),
        })

    pending_rows = [
        {
            "date": row.date.isoformat(),
            "kind": row.kind,
            "reason": row.reason,
            "days": str(row.penalty_days),
            "amount": str(money(
                Decimal(row.penalty_days) * day_value + Decimal(row.penalty_amount)
            )),
        }
        for row in Violation.objects.filter(
            user=user, date__range=(first_day, last_day), status=ApprovalStatus.PENDING
        )
    ]

    # -- the two monthly bonuses -------------------------------------------
    # Taking the leave the contract grants is not an absence. What breaks the
    # discipline bonus is going over the balance, staying away without
    # permission, or an approved rule or quality violation.
    blocking = approved.filter(
        kind__in=(ViolationKind.DISCIPLINE, ViolationKind.QUALITY, ViolationKind.UNEXCUSED)
    ).exists()
    discipline_earned = not unexcused_days and extra_leave == 0 and not blocking
    target_earned = total_words >= conf.monthly_target_words

    approved_bonuses = not conf.bonuses_need_approval
    discipline_bonus = conf.discipline_bonus if (discipline_earned and approved_bonuses) else Decimal("0.00")
    target_bonus = conf.target_bonus if (target_earned and approved_bonuses) else Decimal("0.00")

    gross = money(base + production_bonus + overtime_bonus + discipline_bonus + target_bonus)
    net = money(gross - deductions)

    line = PayrollLine(
        user=user,
        base_salary=money(base),
        working_days=working_days,
        day_value=day_value,
        worked_days=len(worked),
        leave_days=len(leave_days),
        unexcused_days=len(unexcused_days),
        extra_leave_days=extra_leave,
        total_words=total_words,
        target_words=conf.monthly_target_words,
        under_target_days=len(under_target),
        scheduled_days=summary["scheduled_days"],
        office_days=summary["office_days"],
        remote_days=summary["remote_days"],
        late_days=summary["late_days"],
        late_minutes=summary["late_minutes"],
        early_leave_minutes=summary["early_leave_minutes"],
        short_minutes=summary["short_minutes"],
        work_minutes=summary["work_minutes"],
        overtime_minutes=summary["overtime_minutes"],
        production_bonus=money(production_bonus),
        overtime_bonus=money(overtime_bonus),
        discipline_bonus=money(discipline_bonus),
        target_bonus=money(target_bonus),
        deductions=money(deductions),
        gross=gross,
        net=net,
        discipline_bonus_earned=discipline_earned,
        target_bonus_earned=target_earned,
        bonuses_approved=approved_bonuses,
        below_alert_threshold=total_words < conf.monthly_alert_words,
        breakdown={
            "days": day_rows,
            "deductions": deduction_rows,
            "pending": pending_rows,
            "overtime": overtime_rows,
            "attendance": {
                key: summary[key] for key in (
                    "scheduled_days", "present_days", "office_days", "remote_days",
                    "leave_days", "excused_days", "absent_days", "late_days",
                    "late_minutes", "early_leave_minutes", "short_minutes",
                    "work_minutes", "break_minutes", "overtime_minutes",
                    "needs_review",
                )
            },
            "rules": {
                "daily_target": conf.daily_target_words,
                "secondary_daily_target": conf.secondary_daily_target_words,
                "monthly_target": conf.monthly_target_words,
                "monthly_alert": conf.monthly_alert_words,
                "leave_allowance": conf.monthly_leave_allowance,
                "working_days": working_days,
                "discipline_bonus": str(conf.discipline_bonus),
                "target_bonus": str(conf.target_bonus),
            },
        },
    )

    if save_to is not None:
        stored, _ = PayrollLine.objects.update_or_create(
            period=save_to, user=user,
            defaults={
                field.name: getattr(line, field.name)
                for field in PayrollLine._meta.fields
                if field.name not in ("id", "period", "user", "computed_at")
            },
        )
        return stored
    line.period = None
    return line


def compute_period(year, month, actor=None, users=None):
    """Recompute every translator's line for a month. A locked month is left
    exactly as it was paid."""
    period, _ = PayrollPeriod.objects.get_or_create(year=year, month=month)
    if period.is_locked:
        return period

    conf = PayrollSettings.load()
    tiers = list(ProductionTier.objects.all())
    people = users if users is not None else User.objects.filter(
        role=Role.TRANSLATOR, is_active=True
    )
    for person in people:
        compute_line(person, year, month, conf=conf, tiers=tiers, save_to=period, actor=actor)

    period.computed_at = timezone.now()
    period.save(update_fields=["computed_at"])
    AuditLog.objects.create(
        actor=actor, action="payroll.compute", target=period.label,
        detail=f"{period.lines.count()} lines",
    )
    return period


def approve_bonuses(line, by):
    """Release the two monthly bonuses the engine says were earned."""
    conf = PayrollSettings.load()
    line.discipline_bonus = conf.discipline_bonus if line.discipline_bonus_earned else Decimal("0.00")
    line.target_bonus = conf.target_bonus if line.target_bonus_earned else Decimal("0.00")
    line.bonuses_approved = True
    line.gross = money(
        line.base_salary + line.production_bonus + line.discipline_bonus + line.target_bonus
    )
    line.net = money(line.gross - line.deductions)
    line.save(update_fields=[
        "discipline_bonus", "target_bonus", "bonuses_approved", "gross", "net",
    ])
    AuditLog.objects.create(
        actor=by, action="payroll.bonus.approve",
        target=f"{line.user} {line.period.label}",
        detail=f"discipline={line.discipline_bonus} target={line.target_bonus}",
    )
    return line


def approve_period(period, by, lock=False):
    period.status = PeriodStatus.LOCKED if lock else PeriodStatus.APPROVED
    period.approved_by = by
    period.approved_at = timezone.now()
    period.save(update_fields=["status", "approved_by", "approved_at"])
    AuditLog.objects.create(
        actor=by, action="payroll.period." + period.status, target=period.label,
    )
    return period


def month_totals(period):
    """Headline figures for the period screen."""
    lines = period.lines.all()
    return {
        "lines": lines.count(),
        "words": lines.aggregate(total=Sum("total_words"))["total"] or 0,
        "gross": sum((line.gross for line in lines), Decimal("0.00")),
        "deductions": sum((line.deductions for line in lines), Decimal("0.00")),
        "net": sum((line.net for line in lines), Decimal("0.00")),
        "pending": sum((line.pending_bonus for line in lines), Decimal("0.00")),
        "alerts": lines.filter(below_alert_threshold=True).count(),
    }
