"""B2C: the companies inside Egypt, and the field visits to them (15/10/2026, the B2C requirements).

The B2C team works on company sheets like the B2B team (``b2b.py``: the grid, the upload, the messages from the Sales
person's own line, the follow-ups, the quotations), with three things of its own:

* its own stages, the requirements' pipeline (``models.B2C_STATUSES``): a company is never «Lost» without the reason, and
  never left «Waiting for the customer» or «Follow-up later» without the day of the next follow-up (``check_stage``);
* where the company is: its governorate, its address and its place on the map (``parse_location``);
* the visits, for the field Sales people (``User.sales_track == b2c_field``). The person presses «I arrived» at the company
  and «I am done» on leaving; each press reads the phone's location ONCE, at the press - nothing follows the person in
  between, and nothing is read on any other page. The server writes the time and how far the press is from the company,
  and what the manager has to look at (``FLAGS``). A visit is never verified by itself: the Sales manager verifies it, or
  turns it down with a reason, or hands a doubtful one to the owner (``decide``, ``escalate``).

Who: the online and field Sales people hold B2C sheets (a sheet is given to its own team only, ``b2b.sheet_holders``); a
field person sees and makes their own visits; the B2C Sales manager (a manager on the B2C team) and the owner see every
visit and decide them. Nobody decides their own visit.
"""

import re
from datetime import date, datetime, time as dtime, timedelta
from decimal import Decimal, InvalidOperation

from django.db import transaction
from django.db.models import Q
from django.utils import timezone

from . import attendance
from .b2b import CLOSED_STATUSES, Refused, manages_market
from .models import (
    AppSettings, FieldVisit, Lead, LeadActivity, LeadPriority, LeadStatus, LeaveKind, LeaveRequest, LeaveStatus, LostReason,
    Market, Role, STATUSES_OF, SalesTrack, User,
)

# ---------------------------------------------------------------------------
# Who
# ---------------------------------------------------------------------------


def manages(user):
    """Runs the B2C team: the owner, and a Sales manager on the B2C team."""
    return manages_market(user, Market.B2C)


def has_visit_door(user):
    """The visits page is the field Sales people's and the B2C manager's (and the owner's)."""
    return bool(getattr(user, "is_authenticated", False) and (manages(user) or user.is_field_sales))


def visits_for(user):
    rows = FieldVisit.objects.select_related("lead", "lead__sheet", "person", "decided_by")
    if manages(user):
        return rows.filter(lead__sheet__market=Market.B2C) if not user.is_admin_role else rows
    if user.is_field_sales:
        return rows.filter(person=user)
    return rows.none()


def may_see(user, visit):
    return manages(user) or visit.person_id == user.pk


def field_people():
    """The field Sales people still working: whose visits are counted against the month's target."""
    return User.objects.filter(role=Role.SALES, is_active=True, sales_track=SalesTrack.B2C_FIELD).order_by("first_name", "username")


# ---------------------------------------------------------------------------
# The stages of a B2C company
# ---------------------------------------------------------------------------

#: The stages that wait on a day: the company is not left without the next step (the requirements' sections 4 and 7).
NEEDS_DAY = (LeadStatus.WAITING, LeadStatus.LATER)


def check_stage(lead, status, lost_reason, next_follow_up):
    """``Refused`` when the stage may not be written on this row as it would stand. A stage of the other team's list is
    refused on any sheet; on a B2C sheet «Lost» needs its reason and «Waiting» / «Follow-up later» their day."""
    if status not in STATUSES_OF[lead.sheet.market]:
        raise Refused("bad_status", "الحالة دي مش من حالات الشيت ده.", "That stage is not one of this sheet's.")
    if lead.sheet.market != Market.B2C:
        return
    if status == LeadStatus.LOST and lost_reason not in LostReason.values:
        raise Refused("lost_reason", "اختار سبب الخسارة الأول.", "Choose why the company was lost first.")
    if status in NEEDS_DAY and next_follow_up is None:
        raise Refused(
            "needs_follow_up", "الحالة دي محتاجة ميعاد المتابعة الجاية. حدده الأول.",
            "This stage needs the day of the next follow-up. Set it first.",
        )


# ---------------------------------------------------------------------------
# Where the company is
# ---------------------------------------------------------------------------

_NUMBER = r"(-?\d{1,3}(?:\.\d+)?)"
#: The ways a place is written: "30.0444, 31.2357" typed, and the long Google Maps links (".../@30.04,31.23,17z",
#: "?q=30.04,31.23", "!3d30.04!4d31.23", "query=30.04%2C31.23", "ll=").
_PAIR = re.compile(rf"^\s*{_NUMBER}\s*[,،\s]\s*{_NUMBER}\s*$")
_IN_LINK = (
    re.compile(rf"!3d{_NUMBER}!4d{_NUMBER}"),
    re.compile(rf"@{_NUMBER},{_NUMBER}"),
    re.compile(rf"[?&](?:q|query|ll|destination|center)=(?:loc:)?{_NUMBER}(?:,|%2C)\s*{_NUMBER}", re.IGNORECASE),
)
SHORT_LINK = re.compile(r"(?:maps\.app\.goo\.gl|goo\.gl/maps)", re.IGNORECASE)
SIX = Decimal("0.000001")


def _coords(lat, lng):
    try:
        lat, lng = Decimal(str(lat)), Decimal(str(lng))
    except (InvalidOperation, ValueError):
        return None
    if not (lat.is_finite() and lng.is_finite()) or not (-90 <= lat <= 90 and -180 <= lng <= 180):
        return None
    return lat.quantize(SIX), lng.quantize(SIX)


def parse_location(text):
    """``(lat, lng)`` from what was typed or pasted, ``None`` for nothing; ``Refused`` for anything that is not a place."""
    text = (text or "").strip()
    if not text:
        return None
    found = _PAIR.match(text)
    if not found:
        for pattern in _IN_LINK:
            found = pattern.search(text)
            if found:
                break
    place = _coords(*found.groups()) if found else None
    if place is None:
        if SHORT_LINK.search(text):
            raise Refused(
                "short_link",
                "اللينك المختصر مابيقولش المكان. افتح اللينك في Google Maps وانسخ الإحداثيات (اضغط على المكان) أو اللينك الطويل.",
                "A short link does not say where the place is. Open it in Google Maps and copy the coordinates (press the place) or the long link.",
            )
        raise Refused(
            "bad_location", "ده مش مكان. الصق لينك Google Maps أو الإحداثيات زي 30.0444, 31.2357.",
            "That is not a place. Paste a Google Maps link or coordinates like 30.0444, 31.2357.",
        )
    return place


def location_text(lat, lng):
    if lat is None or lng is None:
        return ""
    return f"{lat.normalize():f}, {lng.normalize():f}"


def map_link(lat, lng):
    """The place on Google Maps, for whoever checks a visit. Built from two numbers only."""
    if lat is None or lng is None:
        return ""
    return f"https://www.google.com/maps?q={lat:f},{lng:f}"


# ---------------------------------------------------------------------------
# The visits
# ---------------------------------------------------------------------------

#: What the manager has to look at, worked out by the server; a visit with any of them is never verified in a batch.
FLAGS = {
    "far": ("المكان بعيد عن الشركة", "Away from the company"),
    "weak_gps": ("اللوكيشن مش دقيق", "The location was not precise"),
    "no_gps": ("مفيش لوكيشن", "No location"),
    "no_place": ("الشركة مالهاش لوكيشن نقارن بيه", "The company has no location to compare with"),
    "same_day": ("زيارة تانية لنفس الشركة في نفس اليوم", "Another visit to the same company that day"),
    "no_checkout": ("ماضغطش «خلصت» يومها", "«I am done» was never pressed that day"),
}
MAX_TEXT = 250
MAX_SUMMARY = 4000
MAX_NOTE = 500


def _press(lead, lat, lng, accuracy, conf):
    """``(lat, lng, accuracy, distance, flags)`` for one press: the place the phone gave, how sure it was, and how far it is
    from the company (``None`` when either is not known)."""
    place = _coords(lat, lng) if lat is not None and lng is not None else None
    flags = []
    if place is None:
        return None, None, None, None, ["no_gps"]
    try:
        accuracy = max(0, min(int(accuracy), 100000)) if accuracy is not None else None
    except (TypeError, ValueError):
        accuracy = None
    if accuracy is None or accuracy > conf.b2c_gps_accuracy_m:
        flags.append("weak_gps")
    distance = None
    if lead.latitude is not None and lead.longitude is not None:
        distance = attendance.haversine_m(place[0], place[1], lead.latitude, lead.longitude)
        if distance > conf.b2c_visit_radius_m:
            flags.append("far")
    else:
        flags.append("no_place")
    return place[0], place[1], accuracy, distance, flags


def _merge(visit, flags):
    visit.flags = [flag for flag in FLAGS if flag in set(visit.flags or []) | set(flags)]


def plan(lead, person, actor, *, planned_at=None, purpose=""):
    """A visit to ``lead`` for ``person``, a field Sales person whose B2C sheet it is on. The person plans their own; the
    manager may plan one for them."""
    from . import services

    if lead.sheet.market != Market.B2C:
        raise Refused("not_b2c", "الزيارات لشيتات B2C بس.", "Visits are for B2C sheets only.")
    if not (person.is_field_sales and person.is_active and lead.sheet.assigned_to_id == person.pk):
        raise Refused(
            "not_field", "الشركة دي مش في شيت Sales ميداني.", "This company is not on a field Sales person's sheet.",
        )
    if actor.pk != person.pk and not manages(actor):
        raise Refused("not_yours", "الزيارة بيعملها صاحب الشيت.", "Only the sheet's Sales person makes its visits.")
    visit = FieldVisit.objects.create(
        lead=lead, person=person, planned_at=planned_at, purpose=(purpose or "")[:MAX_TEXT], created_by=actor,
    )
    services.log(actor, "b2c.visit_plan", f"visit {visit.code}", f"lead {lead.pk} -> {person.username}")
    return visit


def _locked(visit):
    """The visit's row, locked, alone (no join: ``select_for_update`` with a join on a nullable key fails on Postgres)."""
    return FieldVisit.objects.select_for_update().get(pk=visit.pk)


def check_in(visit, user, *, lat=None, lng=None, accuracy=None, reason=""):
    """«I arrived»: the server's time, the one reading of the place, and how far it is from the company. A phone that gave
    no place needs the person's reason. One visit open at a time: two at once cannot both be true."""
    from . import services

    conf = AppSettings.load()
    with transaction.atomic():
        # The person's own row is locked first, so two presses at once cannot open two visits.
        User.objects.select_for_update().filter(pk=user.pk).first()
        row = _locked(visit)
        if row.person_id != user.pk:
            raise Refused("not_yours", "الزيارة دي مش بتاعتك.", "This visit is not yours.")
        if row.status != FieldVisit.Status.PLANNED:
            raise Refused("not_planned", "الزيارة دي اتبدأت قبل كده.", "This visit was started already.")
        if FieldVisit.objects.filter(person=user, status=FieldVisit.Status.CHECKED_IN).exists():
            raise Refused(
                "one_open", "عندك زيارة مفتوحة. اضغط «خلصت» فيها الأول.", "You have a visit open. Press «I am done» on it first.",
            )
        lead = Lead.objects.get(pk=row.lead_id)
        place_lat, place_lng, sure, distance, flags = _press(lead, lat, lng, accuracy, conf)
        reason = (reason or "").strip()[:MAX_TEXT]
        if place_lat is None and not reason:
            raise Refused(
                "no_location", "الموبايل ماادّاش لوكيشن. اكتب السبب عشان المانجر يراجعها.",
                "The phone gave no location. Write why, for the manager to review.",
            )
        now = timezone.now()
        if FieldVisit.objects.filter(
            person=user, lead_id=row.lead_id, check_in_at__date=timezone.localdate(now),
        ).exclude(pk=row.pk).exclude(status=FieldVisit.Status.REJECTED).exists():
            flags.append("same_day")
        row.check_in_at = now
        row.check_in_lat, row.check_in_lng, row.check_in_accuracy, row.check_in_distance = place_lat, place_lng, sure, distance
        if reason:
            row.no_location_reason = reason
        _merge(row, flags)
        row.status = FieldVisit.Status.CHECKED_IN
        row.save()
    services.log(user, "b2c.visit_check_in", f"visit {row.code}", f"distance {distance} accuracy {sure} flags {','.join(row.flags)}")
    return row


#: What the report must say before the visit goes to the manager.
REPORT_FIELDS = ("outcome", "summary")


def check_out(visit, user, report, *, lat=None, lng=None, accuracy=None, reason=""):
    """«I am done»: the second reading of the place and the report; the visit then waits for the manager. The report's
    next step becomes the company's next follow-up, and the visit is a line on the company's timeline."""
    from . import b2b, services

    conf = AppSettings.load()
    if report.get("outcome") not in FieldVisit.Outcome.values:
        raise Refused("no_outcome", "اختار نتيجة الزيارة.", "Choose how the visit went.")
    if not (report.get("summary") or "").strip():
        raise Refused("no_summary", "اكتب ملخص المقابلة.", "Write what was said.")
    if report.get("interest") not in ("", None, *LeadPriority.values):
        raise Refused("bad_interest", "مستوى الاهتمام مش مفهوم.", "The interest level is not one of the list.")
    with transaction.atomic():
        row = _locked(visit)
        if row.person_id != user.pk:
            raise Refused("not_yours", "الزيارة دي مش بتاعتك.", "This visit is not yours.")
        if row.status != FieldVisit.Status.CHECKED_IN:
            raise Refused("not_open", "الزيارة دي مش مفتوحة.", "This visit is not open.")
        lead = Lead.objects.select_related("sheet").get(pk=row.lead_id)
        place_lat, place_lng, sure, distance, flags = _press(lead, lat, lng, accuracy, conf)
        reason = (reason or "").strip()[:MAX_TEXT]
        if place_lat is None and not reason and not row.no_location_reason:
            raise Refused(
                "no_location", "الموبايل ماادّاش لوكيشن. اكتب السبب عشان المانجر يراجعها.",
                "The phone gave no location. Write why, for the manager to review.",
            )
        now = timezone.now()
        row.check_out_at = now
        row.check_out_lat, row.check_out_lng, row.check_out_accuracy, row.check_out_distance = place_lat, place_lng, sure, distance
        if reason:
            row.no_location_reason = (f"{row.no_location_reason} / {reason}" if row.no_location_reason else reason)[:MAX_TEXT]
        _merge(row, flags)
        row.outcome = report["outcome"]
        row.met = (report.get("met") or "").strip()[:160]
        row.interest = report.get("interest") or ""
        row.summary = report["summary"].strip()[:MAX_SUMMARY]
        row.next_step = (report.get("next_step") or "").strip()[:MAX_TEXT]
        row.next_step_on = report.get("next_step_on")
        row.status = FieldVisit.Status.PENDING
        row.save()
        b2b._record(
            lead, LeadActivity.Kind.VISIT, user, at=now,
            notes=f"{row.code}: {row.get_outcome_display()} - {row.summary}"[:4000],
        )
        changed = []
        if row.next_step_on and lead.status not in CLOSED_STATUSES:
            lead.next_follow_up = row.next_step_on
            changed.append("next_follow_up")
        if row.interest:
            lead.priority = row.interest
            changed.append("priority")
        if changed:
            lead.save(update_fields=changed + ["updated_at"])
    services.log(user, "b2c.visit_check_out", f"visit {row.code}", f"minutes {row.minutes} flags {','.join(row.flags)}")
    return row


def cancel(visit, user):
    """A planned visit that will not happen is taken off, by its person or the manager; once started it stays."""
    from . import services

    if not (visit.person_id == user.pk or manages(user)):
        raise Refused("not_yours", "الزيارة دي مش بتاعتك.", "This visit is not yours.")
    with transaction.atomic():
        row = _locked(visit)
        if row.status != FieldVisit.Status.PLANNED:
            raise Refused("started", "الزيارة اتبدأت، فمش هتتمسح.", "The visit was started, so it stays.")
        code = row.code
        row.delete()
    services.log(user, "b2c.visit_cancel", f"visit {code}", "")


def _may_decide(user, visit):
    """The B2C manager, never on their own visit; a visit handed to the owner is the owner's alone."""
    if visit.person_id == user.pk:
        return False
    if visit.escalated:
        return user.is_admin_role
    return manages(user)


def decide(visit, user, verified, note=""):
    """Verified, or turned down. Turning down needs the reason; verifying a flagged visit needs the reason it is fine. A
    company with no place yet takes the check-in of its first verified visit, when the phone was sure of it."""
    from . import services

    note = (note or "").strip()[:MAX_NOTE]
    with transaction.atomic():
        row = _locked(visit)
        if not _may_decide(user, row):
            raise Refused("not_yours", "مش من حقك تقرر في الزيارة دي.", "This visit is not yours to decide.")
        if row.status != FieldVisit.Status.PENDING:
            raise Refused("not_pending", "الزيارة دي مش مستنية قرار.", "This visit is not waiting for a decision.")
        if not verified and not note:
            raise Refused("needs_reason", "اكتب سبب الرفض.", "Write why it is turned down.")
        if verified and row.flags and not note:
            raise Refused(
                "needs_reason", "الزيارة دي عليها ملاحظات. اكتب ليه هتعتمدها.", "This visit is flagged. Write why it is fine.",
            )
        row.status = FieldVisit.Status.VERIFIED if verified else FieldVisit.Status.REJECTED
        row.decided_by, row.decided_at, row.decision_note = user, timezone.now(), note
        row.save(update_fields=["status", "decided_by", "decided_at", "decision_note"])
        placed = False
        if verified and row.check_in_lat is not None and "weak_gps" not in row.flags:
            placed = bool(Lead.objects.filter(pk=row.lead_id, latitude__isnull=True).update(
                latitude=row.check_in_lat, longitude=row.check_in_lng,
            ))
    services.log(user, "b2c.visit_verify" if verified else "b2c.visit_reject", f"visit {row.code}", note[:200])
    if placed:
        services.log(user, "b2c.place_from_visit", f"lead {row.lead_id}", f"visit {row.code}")
    if not verified:
        services.notify(
            row.person,
            title_ar="زيارة اترفضت",
            title_en="A visit was turned down",
            body_ar=f"الزيارة {row.code} اترفضت: {note}",
            body_en=f"Visit {row.code} was turned down: {note}",
            level="warning", url="/app/b2c/visits",
        )
    return row


def verify_clean(user, ids):
    """Verify, in one go, the waiting visits among ``ids`` that have nothing to look at (no flag, not handed to the owner,
    not the person's own). Returns how many were verified; the rest are left for one by one."""
    from . import services

    done = 0
    for visit in visits_for(user).filter(pk__in=ids[:500], status=FieldVisit.Status.PENDING, escalated=False):
        if visit.flags or not _may_decide(user, visit):
            continue
        try:
            decide(visit, user, True)
        except Refused:
            continue
        done += 1
    if done:
        services.log(user, "b2c.visit_verify_clean", "visits", f"{done} verified")
    return done


def appeal(visit, user, note):
    """The field person objects to a turned-down visit (part 4, the requirements' section 6): once, with why. The visit
    waits again, handed to the owner, whose decision is the last one."""
    from . import services

    note = (note or "").strip()[:MAX_NOTE]
    if not note:
        raise Refused("needs_reason", "اكتب سبب اعتراضك.", "Write why you object.")
    with transaction.atomic():
        row = _locked(visit)
        if row.person_id != user.pk:
            raise Refused("not_yours", "الزيارة دي مش بتاعتك.", "This visit is not yours.")
        if row.status != FieldVisit.Status.REJECTED:
            raise Refused("not_rejected", "الاعتراض على زيارة اترفضت بس.", "Only a turned-down visit is objected to.")
        if row.appealed_at is not None:
            raise Refused("appealed", "اعترضت على الزيارة دي قبل كده، والقرار بقى نهائي.", "You objected to this visit already; the decision is final.")
        row.appealed_from = row.decision_note
        row.appeal_note, row.appealed_at = note, timezone.now()
        row.status = FieldVisit.Status.PENDING
        row.escalated = True
        row.escalation_note = note
        row.decided_by, row.decided_at, row.decision_note = None, None, ""
        row.save()
    services.log(user, "b2c.visit_appeal", f"visit {row.code}", note[:200])
    for owner in User.objects.filter(role=Role.ADMIN, is_active=True):
        services.notify(
            owner,
            title_ar="اعتراض على زيارة اترفضت",
            title_en="An objection to a turned-down visit",
            body_ar=f"الزيارة {row.code} اعترض عليها صاحبها: {note}",
            body_en=f"Visit {row.code} was objected to by its Sales person: {note}",
            level="warning", url="/app/b2c/visits",
        )
    return row


def escalate(visit, user, note):
    """The manager hands a doubtful visit to the owner, with why; only the owner decides it then."""
    from . import services

    note = (note or "").strip()[:MAX_NOTE]
    if not note:
        raise Refused("needs_reason", "اكتب ليه هتحوّلها للمالك.", "Write why it goes to the owner.")
    with transaction.atomic():
        row = _locked(visit)
        if row.escalated or not _may_decide(user, row) or user.is_admin_role:
            raise Refused("not_yours", "التحويل للمالك من المانجر بس.", "Only the manager hands a visit to the owner.")
        if row.status != FieldVisit.Status.PENDING:
            raise Refused("not_pending", "الزيارة دي مش مستنية قرار.", "This visit is not waiting for a decision.")
        row.escalated, row.escalation_note = True, note
        row.save(update_fields=["escalated", "escalation_note"])
    services.log(user, "b2c.visit_escalate", f"visit {row.code}", note[:200])
    for owner in User.objects.filter(role=Role.ADMIN, is_active=True):
        services.notify(
            owner,
            title_ar="زيارة محتاجة قرارك",
            title_en="A visit needs your decision",
            body_ar=f"المانجر حوّلك الزيارة {row.code}: {note}",
            body_en=f"The manager handed you visit {row.code}: {note}",
            level="warning", url="/app/b2c/visits",
        )
    return row


def sweep(now=None):
    """A visit left open past its day («I am done» never pressed) goes to the manager as it is, marked: the next day's
    work is not held up by it, and nothing is guessed about when the person left. Returns how many."""
    from . import services

    now = now or timezone.now()
    start_of_today = timezone.make_aware(datetime.combine(timezone.localdate(now), dtime.min))
    count = 0
    for visit in FieldVisit.objects.filter(status=FieldVisit.Status.CHECKED_IN, check_in_at__lt=start_of_today):
        with transaction.atomic():
            row = _locked(visit)
            if row.status != FieldVisit.Status.CHECKED_IN:
                continue
            _merge(row, ["no_checkout"])
            row.status = FieldVisit.Status.PENDING
            row.save(update_fields=["flags", "status"])
        services.log(None, "b2c.visit_no_checkout", f"visit {row.code}", "")
        services.notify(
            row.person,
            title_ar="زيارة اتقفلت من غير «خلصت»",
            title_en="A visit was closed without «I am done»",
            body_ar=f"الزيارة {row.code} راحت للمانجر يراجعها لأنك ماضغطتش «خلصت» يومها.",
            body_en=f"Visit {row.code} went to the manager to review: «I am done» was not pressed that day.",
            level="warning", url="/app/b2c/visits",
        )
        count += 1
    return count


# ---------------------------------------------------------------------------
# The month's target (the requirements' section 5): 220 verified visits over 22 working days, less approved leave
# ---------------------------------------------------------------------------

def month_first(value=None):
    value = value or timezone.localdate()
    return value.replace(day=1)


def month_days(first):
    nxt = (first.replace(day=28) + timedelta(days=4)).replace(day=1)
    return [first + timedelta(days=n) for n in range((nxt - first).days)]


#: The weekly day off the leave days are not counted on (Friday, in Egypt).
WEEKLY_OFF = 4


def leave_days(person, first):
    """Working days of the month the person is on approved leave (whole days; a permission of hours is not a day off)."""
    return len(leave_dates(person, first))


def leave_dates(person, first):
    """The days themselves (``leave_days``)."""
    days = set(month_days(first))
    off = set()
    for leave in LeaveRequest.objects.filter(
        user=person, status=LeaveStatus.APPROVED, start_date__lte=max(days), end_date__gte=first,
    ).exclude(kind=LeaveKind.PERMISSION):
        day = max(leave.start_date, first)
        while day <= min(leave.end_date, max(days)):
            if day.weekday() != WEEKLY_OFF:
                off.add(day)
            day += timedelta(days=1)
    return off


def due_target(person, first, conf=None):
    """``(target, leave)``: the visits the person owes this month, less their approved leave in proportion."""
    conf = conf or AppSettings.load()
    work = max(1, conf.b2c_work_days)
    leave = min(work, leave_days(person, first))
    return round(conf.b2c_visit_target * (work - leave) / work), leave


def due_for_period(person, start, end, conf=None):
    """The visits the person owes for the days ``start``..``end``: each month's target (``due_target``) spread over the
    days of it they work (not Friday, not on approved leave), and the days of the period counted. A whole month is its
    target."""
    conf = conf or AppSettings.load()
    total = 0.0
    first = start.replace(day=1)
    while first <= end:
        off = leave_dates(person, first)
        working = [day for day in month_days(first) if day.weekday() != WEEKLY_OFF and day not in off]
        inside = [day for day in working if start <= day <= end]
        if working:
            total += due_target(person, first, conf)[0] * len(inside) / len(working)
        first = (first.replace(day=28) + timedelta(days=4)).replace(day=1)
    return round(total)


def _rate(part, whole):
    return None if not whole else round(100 * part / whole)


def board(user, first):
    """One row per field Sales person for the month: what they owe and where their visits stand. The person's own row for
    them; every field person's (and anybody who made a visit that month) for the manager and the owner."""
    conf = AppSettings.load()
    days = month_days(first)
    start = timezone.make_aware(datetime.combine(first, dtime.min))
    end = timezone.make_aware(datetime.combine(days[-1] + timedelta(days=1), dtime.min))
    month = FieldVisit.objects.filter(
        Q(check_in_at__gte=start, check_in_at__lt=end)
        | Q(check_in_at__isnull=True, planned_at__gte=start, planned_at__lt=end)
        | Q(check_in_at__isnull=True, planned_at__isnull=True, created_at__gte=start, created_at__lt=end)
    )
    if manages(user):
        people = list(User.objects.filter(
            Q(pk__in=field_people().values("pk")) | Q(pk__in=month.values("person_id"))
        ).distinct().order_by("first_name", "username"))
    elif user.is_field_sales:
        people = [user]
    else:
        people = []
    rows = []
    for person in people:
        mine = month.filter(person=person)
        counts = {status: mine.filter(status=status).count() for status in FieldVisit.Status.values}
        target, leave = due_target(person, first, conf)
        verified = counts[FieldVisit.Status.VERIFIED]
        submitted = verified + counts[FieldVisit.Status.REJECTED] + counts[FieldVisit.Status.PENDING]
        rows.append({
            "person": {"id": person.pk, "name": person.get_full_name() or person.username, "active": person.is_active},
            "target": target,
            "leave_days": leave,
            "planned": counts[FieldVisit.Status.PLANNED],
            "open": counts[FieldVisit.Status.CHECKED_IN],
            "pending": counts[FieldVisit.Status.PENDING],
            "verified": verified,
            "rejected": counts[FieldVisit.Status.REJECTED],
            "submitted": submitted,
            "remaining": max(0, target - verified),
            # Each rate with what it is made of beside it (the requirements' section 9), and None when nothing to divide.
            "achievement": _rate(verified, target),
            "verification_rate": _rate(verified, submitted),
        })
    return rows


# ---------------------------------------------------------------------------
# The companies a visit can be to
# ---------------------------------------------------------------------------

MAX_PICK = 20


def visit_leads_q(user):
    """The B2C companies a visit may be made to: the field person's own; any on a field person's sheet for the manager."""
    rows = Lead.objects.filter(sheet__market=Market.B2C).select_related("sheet", "sheet__assigned_to")
    if manages(user):
        return rows.filter(sheet__assigned_to__sales_track=SalesTrack.B2C_FIELD, sheet__assigned_to__is_active=True)
    if user.is_field_sales:
        return rows.filter(sheet__assigned_to=user)
    return rows.none()


def visit_leads(user, words=""):
    """The companies the visit form offers: ``visit_leads_q``, by what was typed, without the closed ones."""
    rows = visit_leads_q(user)
    words = (words or "").strip()[:100]
    if words:
        rows = rows.filter(
            Q(company_name__icontains=words) | Q(contact_person__icontains=words) | Q(governorate__icontains=words)
            | Q(address__icontains=words) | Q(phone__icontains=words)
        )
    return list(rows.exclude(status__in=CLOSED_STATUSES).order_by("company_name", "id")[:MAX_PICK])


def parse_day(value):
    if value in ("", None):
        return None
    if not isinstance(value, str):
        raise ValueError
    return date.fromisoformat(value)
