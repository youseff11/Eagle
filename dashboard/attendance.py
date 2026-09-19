"""The attendance engine: punches in, a priced day out.

What this module is for, and what it deliberately is not for
-----------------------------------------------------------
It proves that somebody started and finished a working day. It reads their
location at the moment they punch and at no other moment; it never polls a
position, never opens a camera, never takes a screenshot. How much work came
out of the day is the operations side's question and is answered from the job
log, not from here.

Three ideas carry the whole file
--------------------------------
**A punch has to find its day.** A shift that runs 17:00 to 01:00 is one
shift, so the check-out at 00:40 belongs to *yesterday's* row. Every entry
point therefore starts at :func:`resolve_work_date`, which looks at yesterday
and today, builds each candidate's real window as two datetimes, and picks the
one the punch falls in.

**The roster is read once and then frozen.** The moment a day opens, the shift
that governs it is copied onto the row: start, end, length, grace, label.
Moving somebody to a later shift next month cannot turn last Tuesday into
lateness, because nothing downstream ever re-reads today's roster for a past
day.

**Every threshold is data.** Grace, break allowance, geofence radius, the
overtime floor and its rate - all of it lives in ``PayrollSettings`` and is
edited from /accounts/rules/. Nothing in here decides a number on its own.

The lateness rule is the contract's, not the obvious one
--------------------------------------------------------
Arrive inside the grace window and the day is simply Present with no lateness
at all. Step one minute past it and the *whole* delay counts, not the part
beyond the window. The spec's own example: with a 09:00 start and ten minutes
of grace, 09:06 is Present and 09:14 is late by fourteen minutes, not four.
:func:`late_after_grace` is that sentence, and it has a test.
"""

from datetime import datetime, timedelta
from decimal import Decimal
from math import asin, cos, radians, sin, sqrt

from django.db import transaction
from django.db.models import Q
from django.utils import timezone

from . import services
from .models import (
    ApprovalStatus,
    AttendanceEdit,
    AttendanceEvent,
    AuthorizedDevice,
    DayStatus,
    Notification,
    OfficeLocation,
    OffSitePolicy,
    OvertimeClaim,
    PayrollSettings,
    PunchKind,
    Role,
    ScheduleOverride,
    Shift,
    User,
    WorkMode,
    WorkDay,
    span_minutes,
)

#: How long before a shift starts somebody may already punch in, and how long
#: after it ends they may still punch out. Only used to decide which *day* a
#: punch belongs to - never to refuse one.
EARLY_WINDOW_MINUTES = 6 * 60
LATE_WINDOW_MINUTES = 8 * 60


class PunchRefused(Exception):
    """A punch the policy will not record. Carries a bilingual reason."""

    def __init__(self, code, ar, en):
        super().__init__(en)
        self.code = code
        self.ar = ar
        self.en = en


# ---------------------------------------------------------------------------
# Pure helpers - no database, no settings, so they are trivially testable
# ---------------------------------------------------------------------------

def haversine_m(lat1, lon1, lat2, lon2):
    """Great-circle distance in metres between two decimal degree points."""
    radius = 6371008.8  # mean Earth radius, metres
    p1, p2 = radians(float(lat1)), radians(float(lat2))
    d_lat = p2 - p1
    d_lon = radians(float(lon2)) - radians(float(lon1))
    a = sin(d_lat / 2) ** 2 + cos(p1) * cos(p2) * sin(d_lon / 2) ** 2
    return int(round(2 * radius * asin(sqrt(a))))


def late_after_grace(scheduled_start, arrived, grace_minutes):
    """Minutes of lateness under the contract's all-or-nothing grace rule.

    Inside the window: zero. Past it: the entire delay, not the excess.
    """
    delay = int((arrived - scheduled_start).total_seconds() // 60)
    if delay <= grace_minutes:
        return 0
    return delay


def early_leave_minutes(scheduled_end, left, grace_minutes):
    """The same shape as lateness, applied to the other edge of the day."""
    early = int((scheduled_end - left).total_seconds() // 60)
    if early <= grace_minutes:
        return 0
    return early


def shift_window(day, start_time, end_time, tz=None):
    """Turn a date plus two clock times into the two datetimes they mean.

    An end at or before the start is the next morning, which is the single
    place the overnight shift is handled - everything else just subtracts.
    """
    tz = tz or timezone.get_current_timezone()
    start = timezone.make_aware(datetime.combine(day, start_time), tz)
    end = timezone.make_aware(datetime.combine(day, end_time), tz)
    if end <= start:
        end += timedelta(days=1)
    return start, end


# ---------------------------------------------------------------------------
# The roster: what was this person supposed to do on this date?
# ---------------------------------------------------------------------------

class PlannedDay:
    """The roster's answer for one person on one date, already resolved."""

    __slots__ = ("date", "working", "start", "end", "minutes", "mode", "label",
                 "source", "shift")

    def __init__(self, date, working=False, start=None, end=None, minutes=0,
                 mode="", label="", source="none", shift=None):
        self.date = date
        self.working = working
        self.start = start
        self.end = end
        self.minutes = minutes
        self.mode = mode
        self.label = label
        self.source = source
        self.shift = shift

    def __repr__(self):  # pragma: no cover - debugging only
        return f"<PlannedDay {self.date} {self.label} {self.source}>"


def plan_for(user, day):
    """Resolve the roster for one date: override first, then the weekday row.

    A `ScheduleOverride` wins outright - that is what "change the 20th without
    touching the standing schedule" means. With no override and no roster row,
    the day is simply off.
    """
    override = ScheduleOverride.objects.filter(user=user, date=day).select_related("template").first()
    if override is not None:
        if override.is_day_off or not (override.start and override.end):
            return PlannedDay(day, working=False, source="override",
                              label=override.reason or "day off")
        start, end = shift_window(day, override.start, override.end)
        return PlannedDay(
            day, working=True, start=start, end=end,
            minutes=override.minutes or span_minutes(override.start, override.end),
            mode=override.mode_for(user), label=override.label, source="override",
        )

    row = (
        Shift.objects.filter(user=user, weekday=day.weekday(), is_active=True)
        .select_related("template").order_by("start_time", "id").first()
    )
    if row is None or not (row.start and row.end):
        return PlannedDay(day, working=False, source="roster")
    start, end = shift_window(day, row.start, row.end)
    return PlannedDay(
        day, working=True, start=start, end=end, minutes=row.minutes,
        mode=row.mode_for(user), label=row.label, source="roster", shift=row,
    )


def resolve_work_date(user, at=None):
    """Which working day a punch made at ``at`` belongs to.

    Yesterday is tried before today on purpose: at 00:40 the open row is
    yesterday's overnight shift, and that is the row the check-out is for.
    """
    at = at or timezone.now()
    local = timezone.localtime(at)
    today = local.date()
    yesterday = today - timedelta(days=1)

    candidates = []
    for day in (yesterday, today):
        plan = plan_for(user, day)
        if not plan.working:
            continue
        opens = plan.start - timedelta(minutes=EARLY_WINDOW_MINUTES)
        closes = plan.end + timedelta(minutes=LATE_WINDOW_MINUTES)
        if opens <= at <= closes:
            candidates.append(plan)

    if not candidates:
        # Not rostered right now. An open day still claims the punch, so
        # somebody who checked in off-schedule can still check out.
        open_day = WorkDay.objects.filter(
            user=user, check_in__isnull=False, check_out__isnull=True,
            date__in=(yesterday, today),
        ).order_by("-date").first()
        if open_day is not None:
            return open_day.date, plan_for(user, open_day.date)
        return today, plan_for(user, today)

    # More than one window can contain the moment where shifts abut. The day
    # already open wins; otherwise the one whose start is nearest.
    open_dates = set(
        WorkDay.objects.filter(
            user=user, check_in__isnull=False, check_out__isnull=True,
            date__in=[p.date for p in candidates],
        ).values_list("date", flat=True)
    )
    for plan in candidates:
        if plan.date in open_dates:
            return plan.date, plan
    best = min(candidates, key=lambda p: abs((at - p.start).total_seconds()))
    return best.date, best


# ---------------------------------------------------------------------------
# Location and device checks
# ---------------------------------------------------------------------------

def nearest_office(latitude, longitude):
    """The closest active office and the distance to it, or ``(None, None)``."""
    best, best_distance = None, None
    for office in OfficeLocation.objects.filter(is_active=True):
        distance = haversine_m(latitude, longitude, office.latitude, office.longitude)
        if best_distance is None or distance < best_distance:
            best, best_distance = office, distance
    return best, best_distance


def check_location(conf, latitude, longitude, accuracy_m=None):
    """Return ``(office, distance_m, inside)`` for a punch's coordinates.

    ``inside`` is ``None`` when there was nothing to check against - no
    coordinates, or no office configured. A missing geofence must not read as
    a failed one, or every punch would arrive flagged on day one.
    """
    if latitude is None or longitude is None:
        return None, None, None
    office, distance = nearest_office(latitude, longitude)
    if office is None:
        return None, None, None
    # The radius is generous already; the phone's own error is added on top so
    # a poor fix is not scored as absence.
    allowance = office.radius_meters or conf.geofence_radius_m
    return office, distance, distance <= allowance + int(accuracy_m or 0)


def touch_device(user, conf, fingerprint, user_agent=""):
    """Find or register the browser this punch came from.

    A token nobody has seen before is recorded as ``pending`` and HR is told.
    Recognising a new phone is a decision, so the row is created either way -
    what the policy decides is whether the punch it came with is held up.
    """
    if not (conf.device_check_enabled and fingerprint):
        return None, True
    device, created = AuthorizedDevice.objects.get_or_create(
        user=user, fingerprint=fingerprint[:64],
        defaults={"user_agent": user_agent[:250], "status": ApprovalStatus.PENDING},
    )
    if created:
        # The first browser somebody ever uses is the one they were given the
        # account on - holding that up would lock out every new joiner.
        if not AuthorizedDevice.objects.filter(user=user).exclude(pk=device.pk).exists():
            device.status = ApprovalStatus.APPROVED
            device.label = "first device"
            device.save(update_fields=["status", "label"])
        else:
            _notify_hr(
                title_ar="جهاز جديد في الحضور",
                title_en="New device used for attendance",
                body_ar=f"{user.short_name} سجّل حضور من جهاز مش متسجل قبل كده.",
                body_en=f"{user.short_name} punched from a browser nobody has approved yet.",
                level="warning", url="/hr/devices/",
            )
    else:
        device.last_seen = timezone.now()
        if user_agent and not device.user_agent:
            device.user_agent = user_agent[:250]
        device.save(update_fields=["last_seen", "user_agent"])
    return device, device.status == ApprovalStatus.APPROVED


# ---------------------------------------------------------------------------
# Punching
# ---------------------------------------------------------------------------

def _open_day(user, day, plan, at, conf):
    """Get or create the row for a date, freezing the roster onto it."""
    row, created = WorkDay.objects.get_or_create(
        user=user, date=day,
        defaults={"status": DayStatus.PRESENT, "self_recorded": True},
    )
    if created or not row.scheduled_start:
        # The freeze. Written once, when the day opens, and never refreshed
        # from the roster afterwards.
        row.scheduled_start = plan.start
        row.scheduled_end = plan.end
        row.scheduled_minutes = plan.minutes
        row.grace_minutes = conf.grace_minutes
        row.schedule_label = plan.label[:60]
        row.work_mode = plan.mode or (user.work_mode if not user.is_hybrid else WorkMode.OFFICE)
        row.save(update_fields=[
            "scheduled_start", "scheduled_end", "scheduled_minutes",
            "grace_minutes", "schedule_label", "work_mode",
        ])
    return row


def _flag(row, reason_ar):
    if not row.needs_review:
        row.needs_review = True
        row.review_reason = reason_ar[:160]


def hr_people():
    """Everybody who is allowed to act on attendance: HR flag or admin."""
    return User.objects.filter(is_active=True).filter(
        Q(attendance_manager=True) | Q(role=Role.ADMIN) | Q(is_superuser=True)
    ).distinct()


def _notify_hr(**kwargs):
    for person in hr_people():
        services.notify(person, **kwargs)


@transaction.atomic
def punch(user, kind, *, at=None, latitude=None, longitude=None, accuracy_m=None,
          fingerprint="", ip=None, user_agent="", source="web", note=""):
    """Record one punch and return ``(work_day, event)``.

    Raises :class:`PunchRefused` when the policy says no - an unfinished day,
    a second check-in, or a check that the settings ask to enforce rather than
    flag. Anything the settings ask to *flag* is recorded and marked instead,
    because a person standing outside the office with a bad GPS fix still
    arrived at work.
    """
    at = at or timezone.now()
    conf = PayrollSettings.load()

    if not user.attendance_enabled:
        raise PunchRefused(
            "disabled", "الحضور مقفول للحساب ده.", "Attendance is switched off for this account."
        )

    day, plan = resolve_work_date(user, at)
    row = _open_day(user, day, plan, at, conf)

    # -- order of operations ------------------------------------------------
    if kind == PunchKind.CHECK_IN and row.check_in:
        raise PunchRefused("already_in", "سجّلت حضور بالفعل النهارده.", "You are already checked in.")
    if kind != PunchKind.CHECK_IN and not row.check_in:
        raise PunchRefused("not_in", "لازم تسجل حضور الأول.", "Check in first.")
    if kind != PunchKind.CHECK_IN and row.check_out:
        raise PunchRefused("closed", "اليوم اتقفل خلاص.", "This day is already closed.")
    if kind == PunchKind.BREAK_START and row.on_break:
        raise PunchRefused("on_break", "أنت في بريك بالفعل.", "You are already on a break.")
    if kind == PunchKind.BREAK_END and not row.on_break:
        raise PunchRefused("no_break", "مفيش بريك شغال.", "No break is running.")
    if kind == PunchKind.CHECK_OUT and row.on_break:
        raise PunchRefused(
            "break_open", "اقفل البريك الأول.", "End the break before checking out."
        )

    # -- the device ---------------------------------------------------------
    device, device_ok = touch_device(user, conf, fingerprint, user_agent)
    if kind == PunchKind.CHECK_IN and device is not None and not device_ok:
        if conf.unknown_device_policy == OffSitePolicy.REJECT:
            raise PunchRefused(
                "device", "الجهاز ده لسه مش معتمد — كلّم الـHR.",
                "This device is not approved yet - ask HR.",
            )
        _flag(row, "حضور من جهاز مش معتمد")

    # -- the location -------------------------------------------------------
    # Read at the punch and nowhere else. A remote day is not asked for one at
    # all, which is the privacy rule expressed as code rather than as a promise.
    office = distance = inside = None
    wants_location = row.is_office_day and kind in (PunchKind.CHECK_IN, PunchKind.CHECK_OUT)
    if kind == PunchKind.CHECK_OUT and not conf.checkout_needs_location:
        wants_location = False
    if wants_location:
        office, distance, inside = check_location(conf, latitude, longitude, accuracy_m)
        if inside is False:
            if conf.off_site_policy == OffSitePolicy.REJECT:
                raise PunchRefused(
                    "off_site",
                    f"أنت بره نطاق المكتب ({distance} متر).",
                    f"You are outside the office radius ({distance} m).",
                )
            row.off_site = True
            _flag(row, f"حضور من بره النطاق ({distance} متر)")
            _notify_hr(
                title_ar="حضور من خارج نطاق المكتب",
                title_en="Punch from outside the office",
                body_ar=f"{user.short_name} سجّل من {distance} متر من {office.label if office else 'المكتب'}.",
                body_en=f"{user.short_name} punched {distance} m from the office.",
                level="warning", url="/hr/attendance/",
            )
        elif inside is None and latitude is None:
            _flag(row, "حضور من غير تحديد موقع")

    event = AttendanceEvent.objects.create(
        work_day=row, user=user, kind=kind, at=at,
        latitude=latitude, longitude=longitude,
        accuracy_m=accuracy_m, distance_m=distance, office=office,
        within_geofence=inside, ip=ip, user_agent=(user_agent or "")[:250],
        device=device, source=source, note=note[:160],
    )

    if kind == PunchKind.CHECK_IN:
        row.check_in = at
        row.status = DayStatus.PRESENT
        row.self_recorded = True
    elif kind == PunchKind.CHECK_OUT:
        row.check_out = at

    recompute(row, conf=conf, save=False)
    row.save()
    return row, event


# ---------------------------------------------------------------------------
# Working the day out
# ---------------------------------------------------------------------------

def break_minutes_of(row, events=None):
    """Sum the closed breaks on a day. An unclosed break counts for nothing.

    It cannot: a break with no end has no length. The check-out path refuses
    to close a day with one open, so this can only be a day still running.
    """
    if events is None:
        events = list(row.events.all()) if row.pk else []
    total = 0
    started = None
    for event in sorted(events, key=lambda e: (e.at, e.pk or 0)):
        if event.kind == PunchKind.BREAK_START:
            started = event.at
        elif event.kind == PunchKind.BREAK_END and started is not None:
            total += max(0, int((event.at - started).total_seconds() // 60))
            started = None
    return total


def recompute(row, conf=None, save=True, keep_break=False):
    """Re-derive every figure on a day from its punches and its frozen shift.

    Safe to call as often as you like: it reads the row and writes the row,
    and it never consults today's roster for a day that is already open.

    ``keep_break`` is for the one case where the punches are not the last
    word - HR has just corrected the break length by hand, and overwriting
    that from the events would undo the correction the moment it was made.
    """
    conf = conf or PayrollSettings.load()

    # Breaks and hours come straight off the punches. A day with no break
    # punches keeps whatever figure was typed on it.
    events = list(row.events.all()) if row.pk else []
    if not keep_break and any(
        event.kind in (PunchKind.BREAK_START, PunchKind.BREAK_END) for event in events
    ):
        row.break_minutes = break_minutes_of(row, events)

    if row.check_in and row.check_out:
        span = max(0, int((row.check_out - row.check_in).total_seconds() // 60))
        worked = span if conf.break_counts_as_work else max(0, span - row.break_minutes)
        row.work_minutes = min(worked, 32000)
    else:
        row.work_minutes = 0

    if row.status != DayStatus.PRESENT:
        row.late_minutes = 0
        row.early_leave_minutes = 0
        row.short_minutes = 0
        row.overtime_minutes = 0
        if save:
            row.save()
        return row

    if not row.scheduled_start:
        # A day with no frozen schedule has nothing to be measured against, so
        # whatever a person typed on the accounts sheet is left exactly alone.
        # Recomputing it to zero would silently erase their work.
        if save:
            row.save()
        return row

    row.late_minutes = (
        late_after_grace(row.scheduled_start, row.check_in, row.grace_minutes)
        if row.check_in else 0
    )
    row.early_leave_minutes = (
        early_leave_minutes(row.scheduled_end, row.check_out, conf.early_leave_grace_minutes)
        if (row.scheduled_end and row.check_out) else 0
    )

    row.short_minutes = 0
    row.overtime_minutes = 0
    if row.scheduled_minutes and row.check_out:
        # An approved permission is time HR agreed the person would be away,
        # so it is not a shortfall. Without this line a granted permission
        # still reads as short hours and can price a deduction, which is the
        # fastest way to make people stop asking for one.
        owed = max(0, row.scheduled_minutes - row.excused_minutes)
        difference = row.work_minutes - owed
        if difference < 0:
            row.short_minutes = -difference
        elif conf.overtime_enabled and difference >= conf.overtime_min_minutes:
            row.overtime_minutes = difference

    if save:
        row.save()
    return row


# ---------------------------------------------------------------------------
# HR corrections - section 9
# ---------------------------------------------------------------------------

TRACKED_FIELDS = (
    "status", "check_in", "check_out", "work_mode", "break_minutes",
    "words", "is_secondary_language", "difficult_file", "absence_reason", "note",
)


def _readable(value):
    if value is None or value == "":
        return ""
    if hasattr(value, "tzinfo") and value.tzinfo is not None:
        return timezone.localtime(value).strftime("%Y-%m-%d %H:%M")
    return str(value)


@transaction.atomic
def apply_edit(row, actor, changes, reason):
    """Write HR's corrections and the trail that explains them.

    Refuses without a reason, because section 9 does: an attendance figure
    that can be changed without saying why is not evidence of anything.
    """
    reason = (reason or "").strip()
    if not reason:
        raise PunchRefused(
            "no_reason", "لازم تكتب سبب التعديل.", "A reason for the change is required."
        )

    written = []
    for field, new in changes.items():
        if field not in TRACKED_FIELDS:
            continue
        old = getattr(row, field)
        if old == new:
            continue
        setattr(row, field, new)
        written.append(AttendanceEdit(
            work_day=row, actor=actor, field=field,
            old_value=_readable(old)[:160], new_value=_readable(new)[:160],
            reason=reason[:250],
        ))

    if not written:
        return []

    if row.check_in or row.check_out:
        row.self_recorded = False
    recompute(
        row, save=False,
        keep_break=any(edit.field == "break_minutes" for edit in written),
    )
    row.save()
    AttendanceEdit.objects.bulk_create(written)
    services.log(
        actor, "attendance.edit", f"{row.user.username} {row.date}",
        f"{', '.join(e.field for e in written)} — {reason}",
    )
    return written


def clear_review(row, actor, reason=""):
    """HR has looked at a flagged day and is satisfied with it."""
    if not row.needs_review:
        return row
    row.needs_review = False
    row.review_reason = ""
    row.save(update_fields=["needs_review", "review_reason"])
    AttendanceEdit.objects.create(
        work_day=row, actor=actor, field="needs_review",
        old_value="True", new_value="False", reason=(reason or "reviewed")[:250],
    )
    services.log(actor, "attendance.review", f"{row.user.username} {row.date}")
    return row


# ---------------------------------------------------------------------------
# Overtime claims - the mirror of a deduction
# ---------------------------------------------------------------------------

def raise_overtime(user, first_day, last_day, conf=None, day_value=Decimal("0.00")):
    """Draft one pending claim per day that ran long. Idempotent by date.

    Approved and rejected claims are left exactly as they are: recomputing a
    month a dozen times must not resurrect a claim a manager already refused,
    nor quietly re-price one they already signed.
    """
    conf = conf or PayrollSettings.load()
    if not conf.overtime_enabled:
        return []

    rate = conf.overtime_rate(day_value)
    claims = []
    days = WorkDay.objects.filter(
        user=user, date__range=(first_day, last_day),
        status=DayStatus.PRESENT, overtime_minutes__gt=0,
    )
    for day in days:
        if day.overtime_minutes < conf.overtime_min_minutes:
            continue
        amount = (rate * Decimal(day.overtime_minutes) / Decimal(60)).quantize(Decimal("0.01"))
        claims.append(_overtime_draft(user, day, rate, amount, conf))
    return claims


def _overtime_draft(user, day, rate, amount, conf):
    existing = OvertimeClaim.objects.filter(user=user, date=day.date).first()
    if existing is not None:
        if existing.status != ApprovalStatus.PENDING:
            return existing
        existing.minutes = day.overtime_minutes
        existing.hourly_rate = rate
        existing.amount = amount
        existing.save(update_fields=["minutes", "hourly_rate", "amount"])
        return existing
    return OvertimeClaim.objects.create(
        user=user, date=day.date, minutes=day.overtime_minutes,
        hourly_rate=rate, amount=amount,
        reason=f"{day.overtime_minutes} minutes over a {day.scheduled_minutes}-minute day",
        status=(
            ApprovalStatus.PENDING if conf.overtime_needs_approval
            else ApprovalStatus.APPROVED
        ),
    )


# ---------------------------------------------------------------------------
# Alerts - section 10
# ---------------------------------------------------------------------------

def sweep_alerts(now=None):
    """Nudge on the five things a missed punch looks like. Run from a cron.

    Every alert is raised at most once per person per day: the notification
    itself is the record, so the sweep asks whether one already exists rather
    than keeping a flag of its own.
    """
    now = now or timezone.now()
    conf = PayrollSettings.load()
    local = timezone.localtime(now)
    raised = 0

    for user in User.objects.filter(is_active=True, attendance_enabled=True):
        for day in (local.date() - timedelta(days=1), local.date()):
            plan = plan_for(user, day)
            if not plan.working:
                continue
            row = WorkDay.objects.filter(user=user, date=day).first()

            # 1. No check-in, and the shift started a while ago.
            if (row is None or not row.check_in) and now > plan.start + timedelta(
                minutes=conf.missing_checkin_after_minutes
            ) and now < plan.end:
                if (row is None or row.status == DayStatus.PRESENT):
                    raised += _alert_once(
                        user, day, "attendance.no_checkin",
                        title_ar="مسجلتش حضور",
                        title_en="No check-in recorded",
                        body_ar=f"شيفت {plan.label} بدأ ولسه مفيش تسجيل حضور.",
                        body_en=f"Shift {plan.label} started and no check-in was recorded.",
                        level="warning",
                    )
                continue

            if row is None:
                continue

            # 2. Late arrival.
            if row.late_minutes:
                raised += _alert_once(
                    user, day, "attendance.late",
                    title_ar="تسجيل حضور متأخر",
                    title_en="Late check-in",
                    body_ar=f"تأخير {row.late_minutes} دقيقة يوم {day}.",
                    body_en=f"{row.late_minutes} minutes late on {day}.",
                    level="warning", hr_too=True,
                )

            # 3. Still open well after the shift ended.
            if row.check_in and not row.check_out and now > plan.end + timedelta(
                minutes=conf.missing_checkout_after_minutes
            ):
                raised += _alert_once(
                    user, day, "attendance.no_checkout",
                    title_ar="مسجلتش انصراف",
                    title_en="No check-out recorded",
                    body_ar=f"يوم {day} لسه مفتوح من غير انصراف.",
                    body_en=f"{day} is still open with no check-out.",
                    level="danger", hr_too=True,
                )

            # 4. A punch that failed its location check.
            if row.off_site:
                raised += _alert_once(
                    user, day, "attendance.off_site",
                    title_ar="حضور من خارج نطاق المكتب",
                    title_en="Punch outside the office",
                    body_ar=f"يوم {day} اتسجل من بره النطاق المسموح.",
                    body_en=f"{day} was punched from outside the allowed radius.",
                    level="warning", hr_too=True, to_user=False,
                )

            # 5. The day came up short.
            if row.check_out and row.short_minutes >= conf.short_hours_alert_minutes:
                raised += _alert_once(
                    user, day, "attendance.short_hours",
                    title_ar="نقص في ساعات العمل",
                    title_en="Short hours",
                    body_ar=f"يوم {day} ناقص {row.short_minutes} دقيقة عن المجدول.",
                    body_en=f"{day} is {row.short_minutes} minutes short of the schedule.",
                    level="warning", hr_too=True,
                )
    return raised


def _alert_once(user, day, key, *, title_ar, title_en, body_ar, body_en,
                level="info", hr_too=False, to_user=True):
    """Send an alert unless the identical one already went out for that day."""
    marker = f"{key}:{user.pk}:{day.isoformat()}"
    if Notification.objects.filter(url=f"/hr/attendance/#{marker}").exists():
        return 0
    if to_user:
        services.notify(
            user, title_ar=title_ar, title_en=title_en,
            body_ar=body_ar, body_en=body_en, level=level,
            url=f"/hr/attendance/#{marker}",
        )
    if hr_too:
        _notify_hr(
            title_ar=f"{title_ar} — {user.short_name}",
            title_en=f"{title_en} — {user.short_name}",
            body_ar=body_ar, body_en=body_en, level=level,
            url=f"/hr/attendance/#{marker}",
        )
    return 1


# ---------------------------------------------------------------------------
# Reporting - section 12
# ---------------------------------------------------------------------------

def month_summary(user, first_day, last_day):
    """The monthly figures section 12 asks for, for one person."""
    days = list(WorkDay.objects.filter(user=user, date__range=(first_day, last_day)))
    by_date = {d.date: d for d in days}

    scheduled = 0
    cursor = first_day
    while cursor <= last_day:
        if plan_for(user, cursor).working:
            scheduled += 1
        cursor += timedelta(days=1)

    present = [d for d in days if d.status == DayStatus.PRESENT]
    late = [d for d in present if d.late_minutes]
    return {
        "scheduled_days": scheduled,
        "present_days": len(present),
        "office_days": sum(1 for d in present if d.is_office_day),
        "remote_days": sum(1 for d in present if d.is_remote_day),
        "leave_days": sum(1 for d in days if d.status == DayStatus.LEAVE),
        "excused_days": sum(1 for d in days if d.status == DayStatus.EXCUSED),
        "absent_days": sum(1 for d in days if d.status == DayStatus.UNEXCUSED),
        "late_days": len(late),
        "late_minutes": sum(d.late_minutes for d in late),
        "early_leave_minutes": sum(d.early_leave_minutes for d in present),
        "short_minutes": sum(d.short_minutes for d in present),
        "work_minutes": sum(d.work_minutes for d in present),
        "break_minutes": sum(d.break_minutes for d in present),
        "overtime_minutes": sum(d.overtime_minutes for d in present),
        "needs_review": sum(1 for d in days if d.needs_review),
        "days": days,
        "by_date": by_date,
    }
