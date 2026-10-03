"""``/api/v1/`` - the person's own attendance card (phase 5, screen 5): today, the last fortnight, the month, the devices.

Everybody signed in has a card of their own (``views.my_attendance`` is open to every role), and it is only ever
theirs: nothing in the request names anybody. What is written is written where it always was - the punch endpoint
(``api.attendance_punch``: check in, break, extra time, check out), which keeps its own refusals and tests. The
check-in screen and the shift reminders are not a page: they come with the heartbeat (``api.heartbeat``), and
``attendance.gate_for`` decides when they open.

One thing this GET does that a plain read does not: it settles the person's own forgotten days first
(``attendance.expire_open_days``), as the classic page and every heartbeat do, so that the card never shows as open a
day the rules have already counted as missed. It is the clock's doing, not the request's, and it is idempotent.

Nothing here reads a position or a screen. The location goes with a punch, at the moment the button is pressed, and
is never asked for twice (section 14 of the attendance spec: no continuous tracking, no camera, no screenshots).
"""

from django.http import JsonResponse
from django.utils import timezone

from . import attendance, payroll
from .api_v1 import _stamp, endpoint
from .models import PayrollSettings, WorkDay, WorkMode
from .templatetags.eagle_tags import DAY_STATUS_MAP, WORK_MODE_MAP

#: How many past days the card lists, as the classic page does.
RECENT_DAYS = 14
#: How many devices it names.
MAX_DEVICES = 6


def _mode_json(mode):
    """How a day is worked (office, remote, hybrid) in both languages; ``None`` for a day nobody has set one for."""
    if not mode:
        return None
    ar, en = WORK_MODE_MAP.get(mode, (mode, mode))
    return {"value": mode, "ar": ar, "en": en}


def _status_json(status):
    tone, ar, en = DAY_STATUS_MAP.get(status, ("", status, status))
    return {"value": status, "tone": tone, "ar": ar, "en": en}


def _day_json(row, plan):
    """Today as the buttons need it: what has been punched, and what the day is doing."""
    if row is None:
        return {
            "state": "none", "check_in": None, "check_out": None, "extra_started_at": None, "extra_running": False,
            "break_minutes": 0, "on_break": False, "hours": "0:00", "late_minutes": 0, "needs_review": False,
            "review_reason": "", "checkout_missed": False,
            # The end of the shift as a moment, so the page can tell when "extra time" is offered (the server decides
            # whether it is accepted: ``attendance.punch``).
            "shift_end": plan.end.isoformat() if plan.working and plan.end else None,
        }
    return {
        "state": "closed" if row.check_out else ("open" if row.check_in else "none"),
        "check_in": _stamp(row.check_in, ""),
        "check_out": _stamp(row.check_out, ""),
        "extra_started_at": _stamp(row.extra_started_at, ""),
        "extra_running": row.extra_running,
        "break_minutes": row.break_minutes,
        "on_break": row.on_break,
        "hours": row.hours_display,
        "late_minutes": row.late_minutes,
        "needs_review": row.needs_review,
        "review_reason": row.review_reason,
        "checkout_missed": row.checkout_missed,
        "shift_end": (
            row.scheduled_end.isoformat() if row.scheduled_end
            else plan.end.isoformat() if plan.working and plan.end else None
        ),
    }


@endpoint("GET")
def card(request):
    """The person's own card: today, the last fortnight, this month's figures and their devices."""
    user = request.user
    today = timezone.localdate()
    attendance.expire_open_days(user=user)
    plan = attendance.plan_for(user, today)
    day, _resolved = attendance.resolve_work_date(user)
    row = WorkDay.objects.filter(user=user, date=day).first()
    conf = PayrollSettings.load()
    summary = attendance.month_summary(user, *payroll.month_bounds(today.year, today.month))
    recent = WorkDay.objects.filter(user=user, date__lte=today).order_by("-date")[:RECENT_DAYS]
    return JsonResponse({
        "ok": True,
        "enabled": user.attendance_enabled,
        "work_date": day.isoformat(),
        "plan": {
            "working": plan.working,
            "label": plan.label,
            "mode": _mode_json(plan.mode),
            "start": _stamp(plan.start, "") if plan.working else None,
            "end": _stamp(plan.end, "") if plan.working else None,
        },
        # A position is read for an office day only, and only for check-in and check-out.
        "needs_location": row.is_office_day if row is not None else plan.mode == WorkMode.OFFICE,
        "day": _day_json(row, plan),
        "conf": {"grace_minutes": conf.grace_minutes, "missing_checkout_after_minutes": conf.missing_checkout_after_minutes},
        "summary": {
            key: summary[key]
            for key in ("scheduled_days", "present_days", "office_days", "remote_days", "late_days", "late_minutes",
                        "short_minutes", "overtime_minutes")
        },
        "recent": [
            {
                "date": one.date.isoformat(),
                "mode": _mode_json(one.work_mode),
                "schedule": one.schedule_label,
                "check_in": _stamp(one.check_in, ""),
                "check_out": _stamp(one.check_out, ""),
                "hours": one.hours_display,
                "status": _status_json(one.status),
                "late_minutes": one.late_minutes,
                "overtime_minutes": one.overtime_minutes,
                "checkout_missed": one.checkout_missed,
            }
            for one in recent
        ],
        # The first ten characters of the browser's own token are all that is said of it, as on the classic card.
        "devices": [
            {"label": device.label or device.fingerprint[:10], "status": device.status}
            for device in user.devices.all()[:MAX_DEVICES]
        ],
    })
