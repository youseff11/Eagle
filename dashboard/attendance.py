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

from . import clock, services
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
    ShiftTemplate,
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

#: How long extra time runs before the person is reminded, in their
#: notifications, that it only ends with a check-out.
EXTRA_REMINDER_MINUTES = 60


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


#: Saturday first, Friday off - the Egyptian week, and the default the
#: employee file ticks when somebody has no roster yet.
WEEK_ORDER = (5, 6, 0, 1, 2, 3, 4)
DEFAULT_WORKDAYS = (5, 6, 0, 1, 2, 3)
WEEKDAY_NAMES = {
    0: ("الاتنين", "Monday"), 1: ("التلات", "Tuesday"), 2: ("الأربع", "Wednesday"),
    3: ("الخميس", "Thursday"), 4: ("الجمعة", "Friday"), 5: ("السبت", "Saturday"),
    6: ("الحد", "Sunday"),
}


def current_template(user):
    """The shift most of this person's roster rows point at, or ``None``."""
    counts = {}
    for row in Shift.objects.filter(user=user, is_active=True, template__isnull=False):
        counts[row.template_id] = counts.get(row.template_id, 0) + 1
    if not counts:
        return None
    return ShiftTemplate.objects.filter(pk=max(counts, key=counts.get)).first()


def shift_for_hours(start, end, name_ar="", actor=None):
    """The company shift with these hours, making it when there is none yet.

    This is the "a shift that does not exist yet" path on the employee file.
    An active shift with the same hours is reused, so typing 5 to 1 a second
    time does not leave two shifts that look identical in every picker.
    """
    existing = ShiftTemplate.objects.filter(
        is_active=True, start_time=start, end_time=end
    ).first()
    if existing is not None:
        return existing, False
    label = (name_ar or "").strip()[:60] or clock.window12(start, end)
    order = (ShiftTemplate.objects.order_by("-sort_order").values_list("sort_order", flat=True)
             .first() or 0) + 1
    template = ShiftTemplate.objects.create(
        name=label, name_ar=label, start_time=start, end_time=end, sort_order=order,
    )
    services.log(actor, "schedule.template.add", template.name, clock.window12(start, end))
    return template, True


@transaction.atomic
def assign_shift(user, template, weekdays, actor=None):
    """Put somebody on one company shift for the chosen weekdays.

    Replaces their standing roster in one go - which is what "this person is
    on shift 2" means. Days already recorded keep the shift they were worked
    under (the schedule is frozen onto each day), so nothing in the past moves.
    ``template=None`` clears the roster.
    """
    days = sorted({int(d) for d in weekdays if str(d).isdecimal() and 0 <= int(d) <= 6})
    Shift.objects.filter(user=user).delete()
    rows = []
    if template is not None:
        rows = Shift.objects.bulk_create([
            Shift(user=user, weekday=day, template=template) for day in days
        ])
    services.log(
        actor, "schedule.assign", user.username,
        f"{template.name if template else '-'} {','.join(str(d) for d in days)}",
    )
    return rows


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
            status=DayStatus.PRESENT, date__in=(yesterday, today),
        ).order_by("-date").first()
        if open_day is not None:
            return open_day.date, plan_for(user, open_day.date)
        return today, plan_for(user, today)

    # More than one window can contain the moment where shifts abut. The day
    # already open wins; otherwise the one whose start is nearest.
    open_dates = set(
        WorkDay.objects.filter(
            user=user, check_in__isnull=False, check_out__isnull=True,
            status=DayStatus.PRESENT, date__in=[p.date for p in candidates],
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


#: The most a phone's own error may add to the office's radius. A browser reports 5 to 50 metres from GPS and a few hundred from
#: a network fix; a figure above this is a guess or a lie, and it is not allowed to widen the circle.
MAX_ACCURACY_M = 150


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
    return office, distance, distance <= allowance + min(int(accuracy_m or 0), MAX_ACCURACY_M)


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


def punch(user, kind, *, at=None, **details):
    """Record one punch and return ``(work_day, event)``.

    A check-out (or any punch) that arrives after the day's check-out
    deadline finds the day already lost: it is settled as not counted first,
    outside the punch's own transaction so the refusal cannot roll it back,
    and the punch is refused with the reason.
    """
    at = at or timezone.now()
    if kind != PunchKind.CHECK_IN and user.attendance_enabled:
        day, _plan = resolve_work_date(user, at)
        row = WorkDay.objects.filter(user=user, date=day).first()
        if row is not None and expire_if_forgotten(row, now=at):
            raise PunchRefused(
                "checkout_missed",
                "عدّى ميعاد الانصراف ومسجلتش — اليوم ده مش محسوب واتحوّل للـHR.",
                "The check-out deadline passed - this day does not count and went to HR.",
            )
    return _punch(user, kind, at=at, **details)


@transaction.atomic
def _punch(user, kind, *, at=None, latitude=None, longitude=None, accuracy_m=None,
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
    if kind == PunchKind.EXTRA_START:
        _extra_allowed(row, at)

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
    elif kind == PunchKind.EXTRA_START:
        row.extra_started_at = at

    recompute(row, conf=conf, save=False)
    row.save()

    # Late past the grace window: HR hears about it now, and so does the
    # person - told in so many words that it went to HR.
    if kind == PunchKind.CHECK_IN and row.late_minutes:
        _late_alert(user, row)
    if kind == PunchKind.EXTRA_START:
        _extra_started_alert(user, row)
    if kind == PunchKind.CHECK_OUT and row.overtime_minutes:
        _claim_extra(row, conf)
    return row, event


def _extra_allowed(row, at):
    """Extra time starts after the shift ends, once, and not during a break."""
    if not row.scheduled_end:
        raise PunchRefused(
            "extra_no_shift",
            "مفيش شيفت متسجل ليك النهارده — الاكسترا تايم محتاج شيفت.",
            "No shift is set for you today - extra time needs one.",
        )
    if row.extra_started_at:
        raise PunchRefused(
            "extra_running", "الاكسترا تايم شغال بالفعل.", "Extra time is already running."
        )
    if row.on_break:
        raise PunchRefused(
            "break_open", "اقفل البريك الأول.", "End the break first."
        )
    if at < row.scheduled_end:
        end_ar, end_en = clock.both(row.scheduled_end)
        raise PunchRefused(
            "extra_early",
            f"الاكسترا تايم بيبدأ بعد نهاية الشيفت ({end_ar}).",
            f"Extra time starts after the shift ends ({end_en}).",
        )


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


def extra_minutes_of(row):
    """Minutes from the extra-time punch (never before the shift end) to out."""
    if not (row.extra_started_at and row.check_out):
        return 0
    begin = row.extra_started_at
    if row.scheduled_end and row.scheduled_end > begin:
        begin = row.scheduled_end
    return max(0, int((row.check_out - begin).total_seconds() // 60))


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
    extra = extra_minutes_of(row)
    if conf.overtime_enabled and extra >= conf.overtime_min_minutes:
        # Only time after the "extra time" button is overtime. Staying late
        # without pressing it is not, because HR can only review what it was
        # told about.
        row.overtime_minutes = extra
    if row.scheduled_minutes and row.check_out:
        # An approved permission is time HR agreed the person would be away,
        # so it is not a shortfall. Without this line a granted permission
        # still reads as short hours and can price a deduction, which is the
        # fastest way to make people stop asking for one.
        owed = max(0, row.scheduled_minutes - max(row.excused_minutes, approved_permission_minutes(row.user_id, row.date)))
        # The extra hour is paid as extra; it does not also fill a late start.
        regular = row.work_minutes - extra
        if regular < owed:
            row.short_minutes = owed - regular

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
        return clock.fmt12(value, "ar", "%Y-%m-%d")
    return str(value)


@transaction.atomic
def approved_permission_minutes(user_id, day):
    """Minutes of permission HR approved for this person on this date: the day may not have a row when it is approved."""
    from .models import LeaveKind, LeaveRequest, LeaveStatus

    total = sum(
        request.minutes
        for request in LeaveRequest.objects.filter(
            user_id=user_id, kind=LeaveKind.PERMISSION, status=LeaveStatus.APPROVED, start_date=day,
        )
    )
    return min(total, 32000)


def _own_record(row, actor):
    """Whoever corrects attendance does not correct their own: the owner does."""
    if actor is not None and row.user_id == getattr(actor, "pk", None) and not actor.is_admin_role:
        raise PunchRefused(
            "own_day", "مينفعش تعدّل يومك أنت. المالك هو اللي بيعدّل.", "Nobody corrects their own day except the owner.",
        )


def apply_edit(row, actor, changes, reason):
    """Write HR's corrections and the trail that explains them.

    Refuses without a reason, because section 9 does: an attendance figure
    that can be changed without saying why is not evidence of anything.
    """
    _own_record(row, actor)
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
    if row.checkout_missed and row.status == DayStatus.PRESENT and row.check_out:
        # HR restored a day lost to a forgotten check-out.
        row.checkout_missed = False
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
    _own_record(row, actor)
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
    # A claim still waiting for a day that no longer ran long (the day was corrected) is not a claim any more: approving it
    # would pay for time the corrected record says was not worked.
    OvertimeClaim.objects.filter(
        user=user, date__range=(first_day, last_day), status=ApprovalStatus.PENDING,
    ).exclude(pk__in=[claim.pk for claim in claims]).delete()
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

            # 2. Late arrival. Normally already sent at the punch itself.
            if row.late_minutes:
                raised += _late_alert(user, row)

            # 3. The shift is over and the day is still open: remind first,
            #    and once the deadline passes the day stops counting.
            if expire_if_forgotten(row, now=now, conf=conf):
                raised += 1
                continue
            if row.is_open and row.scheduled_end and not row.extra_started_at \
                    and now >= row.scheduled_end:
                raised += _checkout_reminder(user, row, conf)
            elif row.extra_running and now >= row.extra_started_at + timedelta(
                minutes=EXTRA_REMINDER_MINUTES
            ):
                raised += _extra_reminder(user, row, conf)

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
# Late arrival, a forgotten check-out, extra time
# ---------------------------------------------------------------------------

#: What a day lost to a forgotten check-out says on the HR board.
MISSED_CHECKOUT_REASON = "مسجلش انصراف في الميعاد — اليوم مش محسوب"


def _late_alert(user, row):
    """Past the grace window: HR is told, and the person is told HR was told.

    Sent once per day. The punch sends it the moment it happens; the sweep
    only catches a day that somehow reached it without one.
    """
    start_ar, start_en = clock.both(row.scheduled_start)
    in_ar, in_en = clock.both(row.check_in)
    minutes = row.late_minutes
    marker_day = row.date
    sent = _alert_once(
        user, marker_day, "attendance.late",
        title_ar="التأخير اتحوّل للـHR",
        title_en="Your lateness went to HR",
        body_ar=(
            f"سجّلت حضور {in_ar} والشيفت بيبدأ {start_ar} — "
            f"تأخير {minutes} دقيقة بعد فترة السماح، واتحوّل للـHR."
        ),
        body_en=(
            f"You checked in at {in_en}; the shift starts at {start_en}. "
            f"{minutes} minutes late past the grace window - sent to HR."
        ),
        level="warning",
    )
    if sent:
        _notify_hr(
            title_ar=f"تأخير — {user.short_name}",
            title_en=f"Late — {user.short_name}",
            body_ar=(
                f"{user.short_name} سجّل حضور {in_ar} والشيفت {start_ar}: "
                f"تأخير {minutes} دقيقة يوم {row.date}."
            ),
            body_en=(
                f"{user.short_name} checked in at {in_en} for a {start_en} shift: "
                f"{minutes} minutes late on {row.date}."
            ),
            level="warning", url=f"/hr/attendance/{row.pk}/",
        )
    return sent


def checkout_deadline(row, conf=None):
    """The last moment a check-out still counts for this day, or ``None``.

    The shift end plus ``missing_checkout_after_minutes``. Somebody on extra
    time has told us they are staying, so their day stays open until the
    punch window itself closes. A day with no frozen shift has no deadline -
    there is nothing to measure "forgot" against.
    """
    if not row.scheduled_end:
        return None
    if row.extra_started_at:
        return row.scheduled_end + timedelta(minutes=LATE_WINDOW_MINUTES)
    conf = conf or PayrollSettings.load()
    return row.scheduled_end + timedelta(minutes=conf.missing_checkout_after_minutes)


def expire_if_forgotten(row, now=None, conf=None):
    """Settle a day whose check-out never came. Returns True when it did.

    The rule the owner set: forget to check out and the whole day does not
    count. The day becomes an unexcused absence - which, like every other
    deduction, still waits for a person to approve it - and it is flagged so
    HR sees why. HR can restore it from the day page, with a reason.
    """
    if not row.is_open:
        return False
    now = now or timezone.now()
    conf = conf or PayrollSettings.load()
    deadline = checkout_deadline(row, conf)
    if deadline is None or now <= deadline:
        return False

    row.status = DayStatus.UNEXCUSED
    row.checkout_missed = True
    row.needs_review = True
    row.review_reason = MISSED_CHECKOUT_REASON
    recompute(row, conf=conf, save=False)
    row.save()
    AttendanceEdit.objects.create(
        work_day=row, actor=None, field="status",
        old_value=DayStatus.PRESENT, new_value=DayStatus.UNEXCUSED,
        reason="system: no check-out by the deadline",
    )
    end_ar, end_en = clock.both(deadline)
    _alert_once(
        row.user, row.date, "attendance.checkout_missed",
        title_ar="اليوم مش محسوب — مسجلتش انصراف",
        title_en="Day not counted - no check-out",
        body_ar=f"يوم {row.date} اتقفل من غير انصراف لحد {end_ar}، فمش محسوب واتحوّل للـHR.",
        body_en=f"{row.date} had no check-out by {end_en}, so it does not count and went to HR.",
        level="danger", hr_too=True,
    )
    return True


def expire_open_days(now=None, user=None, conf=None):
    """Run :func:`expire_if_forgotten` over every day that could be due."""
    now = now or timezone.now()
    conf = conf or PayrollSettings.load()
    rows = WorkDay.objects.filter(
        status=DayStatus.PRESENT, check_in__isnull=False, check_out__isnull=True,
        scheduled_end__lt=now - timedelta(minutes=conf.missing_checkout_after_minutes),
    ).select_related("user")
    if user is not None:
        rows = rows.filter(user=user)
    return sum(1 for row in rows if expire_if_forgotten(row, now=now, conf=conf))


def _checkout_reminder(user, row, conf):
    deadline = checkout_deadline(row, conf)
    end_ar, end_en = clock.both(deadline)
    return _alert_once(
        user, row.date, "attendance.checkout_reminder",
        title_ar="الشيفت خلص — سجّل انصراف",
        title_en="Your shift is over - check out",
        body_ar=(
            f"سجّل انصراف قبل {end_ar}، ولو هتكمّل دوس «اكسترا تايم». "
            "لو نسيت تسجل انصراف اليوم كله مش هيتحسب."
        ),
        body_en=(
            f"Check out before {end_en}, or press Extra time if you are staying. "
            "Forget to check out and the whole day does not count."
        ),
        level="warning",
    )


def _extra_watchers(user):
    """Who is told when somebody goes into extra time: their team leader and
    every admin. The person themselves is never in the list.
    """
    people = {}
    lead = user.team_lead
    if lead is not None and lead.is_active:
        people[lead.pk] = lead
    for admin in User.objects.filter(is_active=True).filter(
        Q(role=Role.ADMIN) | Q(is_superuser=True)
    ):
        people[admin.pk] = admin
    people.pop(user.pk, None)
    return list(people.values())


def _watch_url(person, row):
    """Where the notification lands: the day for HR and admins, the team page
    for a leader, who has no right to the HR board.
    """
    return f"/hr/attendance/{row.pk}/" if person.can_manage_attendance else "/lead/translators/"


def _extra_started_alert(user, row):
    """Extra time began: the team leader and the admins hear about it now."""
    began_ar, began_en = clock.both(row.extra_started_at)
    end_ar, end_en = clock.both(row.scheduled_end)
    for person in _extra_watchers(user):
        services.notify(
            person,
            title_ar=f"اكسترا تايم بدأ — {user.short_name}",
            title_en=f"Extra time started — {user.short_name}",
            body_ar=(
                f"{user.short_name} بدأ اكسترا تايم {began_ar} والشيفت خلص {end_ar}. "
                "الساعة بتتحسب بساعة ونص، ولازم يسجّل انصراف لما يخلص."
            ),
            body_en=(
                f"{user.short_name} started extra time at {began_en}; the shift ended at "
                f"{end_en}. Paid at time and a half; they must check out when they finish."
            ),
            level="info", url=_watch_url(person, row),
        )


def _extra_finished_alert(row):
    """The day closed after extra time: the team leader is told how long.

    HR and the admins already get the claim itself from ``_claim_extra``; a
    leader who is neither is the one person left out of that.
    """
    lead = row.user.team_lead
    if lead is None or not lead.is_active or lead.can_manage_attendance:
        return
    out_ar, out_en = clock.both(row.check_out)
    services.notify(
        lead,
        title_ar=f"اكسترا تايم خلص — {row.user.short_name}",
        title_en=f"Extra time finished — {row.user.short_name}",
        body_ar=(
            f"{row.user.short_name} سجّل انصراف {out_ar} بعد "
            f"{row.overtime_minutes} دقيقة اكسترا تايم."
        ),
        body_en=(
            f"{row.user.short_name} checked out at {out_en} after "
            f"{row.overtime_minutes} minutes of extra time."
        ),
        level="info", url=_watch_url(lead, row),
    )


def _extra_reminder(user, row, conf):
    """Extra time has run a while with no check-out: tell the person, once.

    The screen only reaches somebody with the site open; this one waits in
    their notifications for whoever closed the tab and walked out.
    """
    since_ar, since_en = clock.both(row.extra_started_at)
    end_ar, end_en = clock.both(checkout_deadline(row, conf))
    return _alert_once(
        user, row.date, "attendance.extra_reminder",
        title_ar="الاكسترا تايم شغال — سجّل انصراف لما تخلص",
        title_en="Extra time is running - check out when you finish",
        body_ar=(
            f"بدأت اكسترا تايم {since_ar}. لما تخلص سجّل انصراف قبل {end_ar}، "
            "ولو مسجلتش اليوم كله مش هيتحسب."
        ),
        body_en=(
            f"Your extra time began at {since_en}. Check out before {end_en} when you "
            "finish, or the whole day does not count."
        ),
        level="warning",
    )


def _claim_extra(row, conf):
    """Price the extra time as a claim HR has to approve, and tell HR.

    ``raise_overtime`` does the same thing when the month is computed; doing
    it at the check-out as well puts the claim in HR's queue the same day.
    """
    if not (conf.overtime_enabled and row.overtime_minutes):
        return None
    from . import payroll  # payroll imports this module at the top
    from .models import SalaryRecord

    rules = payroll.rules_for(row.user, conf)
    base = SalaryRecord.amount_on(row.user, row.date)
    day_value = payroll.money(base / Decimal(rules.working_days_per_month or 1))
    rate = rules.overtime_rate(day_value)
    amount = (rate * Decimal(row.overtime_minutes) / Decimal(60)).quantize(Decimal("0.01"))
    claim = _overtime_draft(row.user, row, rate, amount, rules)
    _alert_once(
        row.user, row.date, "attendance.extra",
        title_ar=f"اكسترا تايم للمراجعة — {row.user.short_name}",
        title_en=f"Extra time to review — {row.user.short_name}",
        body_ar=f"{row.overtime_minutes} دقيقة اكسترا تايم يوم {row.date} مستنية مراجعتك.",
        body_en=f"{row.overtime_minutes} minutes of extra time on {row.date} wait for review.",
        level="info", hr_too=True, to_user=False,
    )
    _extra_finished_alert(row)
    return claim


# ---------------------------------------------------------------------------
# The check-in screen
# ---------------------------------------------------------------------------

def gate_for(user, now=None, conf=None):
    """What the screen should ask this person right now, or ``None``.

    ``check_in``: a shift is on (or about to be) and nobody has checked in -
    the screen opens by itself and stays until they do. ``check_out``: the
    shift has ended, the day is still open and no extra time was started - a
    reminder that a forgotten check-out costs the whole day.

    Also settles this person's own forgotten days on the way, so the rule
    holds even on a server where the sweep is not scheduled.
    """
    if not (getattr(user, "is_authenticated", False) and user.attendance_enabled):
        return None
    # Most page loads and every heartbeat come through here, so somebody with
    # no roster and nothing open costs three cheap queries and nothing more.
    if not (
        Shift.objects.filter(user=user, is_active=True).exists()
        or ScheduleOverride.objects.filter(user=user).exists()
        or WorkDay.objects.filter(
            user=user, check_in__isnull=False, check_out__isnull=True,
            status=DayStatus.PRESENT,
        ).exists()
    ):
        return None
    now = now or timezone.now()
    conf = conf or PayrollSettings.load()
    expire_open_days(now, user=user, conf=conf)

    day, plan = resolve_work_date(user, now)
    row = WorkDay.objects.filter(user=user, date=day).first()
    if row is not None and row.status != DayStatus.PRESENT:
        return None

    if plan.working and (row is None or not row.check_in):
        opens = plan.start - timedelta(minutes=conf.checkin_prompt_before_minutes)
        if not (opens <= now < plan.end):
            return None
        grace_until = plan.start + timedelta(minutes=conf.grace_minutes)
        return {
            "kind": "check_in",
            "date": day.isoformat(),
            "shift": plan.label,
            "start": dict(zip(("ar", "en"), clock.both(plan.start))),
            "end": dict(zip(("ar", "en"), clock.both(plan.end))),
            "grace_until": dict(zip(("ar", "en"), clock.both(grace_until))),
            "grace": conf.grace_minutes,
            "late_now": late_after_grace(plan.start, now, conf.grace_minutes),
            "needs_location": plan.mode == WorkMode.OFFICE,
            "checkout_after": conf.missing_checkout_after_minutes,
        }

    if (row is not None and row.is_open and row.scheduled_end
            and not row.extra_started_at and now >= row.scheduled_end):
        deadline = checkout_deadline(row, conf)
        return {
            "kind": "check_out",
            "date": day.isoformat(),
            "shift": row.schedule_label,
            "end": dict(zip(("ar", "en"), clock.both(row.scheduled_end))),
            "deadline": dict(zip(("ar", "en"), clock.both(deadline))),
            "needs_location": row.is_office_day and conf.checkout_needs_location,
        }

    # Extra time is running: the person said they were staying, so the only
    # way the day ends well is a check-out. The screen can be put off while
    # they work - the browser brings it back - but the day is not counted
    # without that check-out.
    if row is not None and row.extra_running and row.scheduled_end:
        return {
            "kind": "extra",
            "date": day.isoformat(),
            "shift": row.schedule_label,
            "end": dict(zip(("ar", "en"), clock.both(row.scheduled_end))),
            "extra_since": dict(zip(("ar", "en"), clock.both(row.extra_started_at))),
            "deadline": dict(zip(("ar", "en"), clock.both(checkout_deadline(row, conf)))),
            "needs_location": row.is_office_day and conf.checkout_needs_location,
        }
    return None


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
