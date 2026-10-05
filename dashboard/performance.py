"""Performance: four indicators from data the system already had to collect.

Section 20 asks for productivity, quality, deadlines and attendance, and then
one overall figure. The temptation with a page like this is to invent numbers
that look authoritative. This module refuses to: every indicator is built out
of rows somebody already created for another reason - jobs delivered, marks a
reviewer gave, punches, complaints logged - and an indicator with nothing
behind it comes back as ``None`` and prints "not measured" rather than a
confident zero.

That distinction is the whole design. A translator with no delivered jobs this
month has no deadline score, not a deadline score of nought; the difference
matters when the number sits next to somebody's name in a review.

Each indicator is a percentage. The overall is their weighted mean, using the
weights on ``PayrollSettings`` - and only over the indicators that actually
have a value, so a missing one dilutes nothing.
"""

from django.db.models import Avg, Count, Q, Sum

from . import attendance, payroll
from .models import (
    ApprovalStatus,
    ClientComplaint,
    DayStatus,
    PayrollSettings,
    RatingEvent,
    Task,
    Violation,
    ViolationKind,
    WorkDay,
)

#: Below this a score is worth saying out loud on a dashboard.
POOR = 60
GOOD = 85


def _pct(value, ceiling=100):
    """Clamp to a sane percentage and round to a whole number."""
    if value is None:
        return None
    return max(0, min(ceiling, int(round(value))))


def effective_targets(person, conf=None):
    """The word targets this person is actually measured against."""
    conf = conf or PayrollSettings.load()
    plan = getattr(person, "salary_plan", None)
    monthly = conf.monthly_target_words
    if plan is not None and plan.monthly_target_words is not None:
        monthly = plan.monthly_target_words
    return {"monthly_words": monthly or 0}


# ---------------------------------------------------------------------------
# The four indicators
# ---------------------------------------------------------------------------

def productivity(person, first_day, last_day, conf=None, words=None):
    """Words delivered against the target for the month.

    Capped at 120 rather than 100: beating the target is worth seeing, but a
    single enormous month should not let somebody coast on the average.

    ``words`` is for a caller that has already added up many people's (the
    board, the history): the figure and the score still come from this one
    place, so a number never differs between the board and the person's page.
    """
    conf = conf or PayrollSettings.load()
    target = effective_targets(person, conf)["monthly_words"]
    if words is None:
        words = WorkDay.objects.filter(
            user=person, date__range=(first_day, last_day), status=DayStatus.PRESENT
        ).aggregate(total=Sum("words"))["total"] or 0

    if not target:
        return {"score": None, "words": words, "target": 0, "reason": "no target set"}
    return {
        "score": _pct(words / target * 100, ceiling=120),
        "words": words,
        "target": target,
    }


def deadlines(person, first_day, last_day):
    """The share of finished jobs that were finished in time.

    Measured on ``translated_at`` against the deadline, because that is the
    moment the translator's part ended - holding them to a delivery the
    operations side made two days later would be measuring somebody else.

    And against *their* deadline - the one the team leader handed them -
    rather than the client's. The leader keeps the difference back for
    review, and marking somebody late against a date nobody ever told them
    about is scoring them on a secret.
    """
    from django.db.models.functions import Coalesce

    rows = Task.objects.filter(
        translator=person, translated_at__date__range=(first_day, last_day)
    ).annotate(due=Coalesce("translator_deadline", "deadline")).exclude(due=None)
    total = rows.count()
    if not total:
        return {"score": None, "total": 0, "late": 0, "reason": "no dated jobs"}
    late = sum(1 for task in rows if task.translated_at > task.due)
    return {
        "score": _pct((total - late) / total * 100),
        "total": total,
        "late": late,
    }


def quality(person, first_day, last_day):
    """What the reviewer, the clients and the rating log say together.

    The reviewer's marks are the spine; complaints and approved quality
    violations take bites out of it. With no marks at all the score falls
    back to what is left after those bites - and with nothing at all, to
    ``None``.
    """
    marked = Task.objects.filter(
        translator=person, translated_at__date__range=(first_day, last_day)
    ).exclude(review_score=None)
    stats = marked.aggregate(avg=Avg("review_score"), n=Count("id"))
    reviewer_avg = stats["avg"]

    complaints = list(ClientComplaint.objects.filter(
        translator=person, happened_on__range=(first_day, last_day)
    ))
    penalty = sum(row.weight for row in complaints)

    quality_violations = Violation.objects.filter(
        user=person, date__range=(first_day, last_day),
        kind=ViolationKind.QUALITY, status=ApprovalStatus.APPROVED,
    ).count()
    penalty += quality_violations * 15

    rating_drop = RatingEvent.objects.filter(
        user=person, created_at__date__range=(first_day, last_day), delta__lt=0
    ).count()

    if reviewer_avg is None and not complaints and not quality_violations:
        return {
            "score": None, "reviewer_avg": None, "reviewed": 0,
            "complaints": 0, "violations": 0, "rating_drops": rating_drop,
            "reason": "nothing marked yet",
        }

    base = float(reviewer_avg) * 10 if reviewer_avg is not None else 100.0
    return {
        "score": _pct(base - penalty),
        "reviewer_avg": round(float(reviewer_avg), 1) if reviewer_avg is not None else None,
        "reviewed": stats["n"] or 0,
        "complaints": len(complaints),
        "violations": quality_violations,
        "rating_drops": rating_drop,
    }


def attendance_score(person, first_day, last_day):
    """Days attended against days rostered, minus a nick for lateness."""
    if not person.attendance_enabled:
        return {"score": None, "reason": "attendance is off for this account"}

    summary = attendance.month_summary(person, first_day, last_day)
    scheduled = summary["scheduled_days"]
    if not scheduled:
        return {"score": None, "summary": summary, "reason": "no roster"}

    present = summary["present_days"] + summary["leave_days"]
    base = present / scheduled * 100
    # Lateness is a smaller thing than absence and is priced that way.
    base -= min(20, summary["late_days"] * 3)
    return {
        "score": _pct(base),
        "summary": summary,
        "present": present,
        "scheduled": scheduled,
        "late_days": summary["late_days"],
    }


# ---------------------------------------------------------------------------
# Putting them together
# ---------------------------------------------------------------------------

def weights(conf=None):
    conf = conf or PayrollSettings.load()
    return {
        "productivity": conf.weight_productivity,
        "quality": conf.weight_quality,
        "deadline": conf.weight_deadline,
        "attendance": conf.weight_attendance,
    }


def overall(parts, conf=None):
    """The weighted mean of the indicators that have a value.

    Re-normalising over only the present indicators is deliberate. If nobody
    has marked a single job, quality is unknown, and the honest reading of
    the rest is "what we can see", not "what we can see, dragged toward zero
    by what we cannot".
    """
    table = weights(conf)
    total_weight, total = 0, 0.0
    for key, weight in table.items():
        score = (parts.get(key) or {}).get("score")
        if score is None or not weight:
            continue
        total_weight += weight
        total += score * weight
    if not total_weight:
        return None
    return _pct(total / total_weight)


def for_month(person, year, month, conf=None):
    """Everything section 20 asks for, for one person and one month."""
    conf = conf or PayrollSettings.load()
    first_day, last_day = payroll.month_bounds(year, month)

    delivered = Task.objects.filter(
        translator=person, translated_at__date__range=(first_day, last_day)
    )
    revisions = delivered.aggregate(
        n=Count("id"), returned=Count("id", filter=Q(revision_count__gt=0)),
        total_revisions=Sum("revision_count"),
    )
    projects = revisions["n"] or 0

    parts = {
        "productivity": productivity(person, first_day, last_day, conf),
        "quality": quality(person, first_day, last_day),
        "deadline": deadlines(person, first_day, last_day),
        "attendance": attendance_score(person, first_day, last_day),
    }
    return {
        "person": person,
        "year": year,
        "month": month,
        "first_day": first_day,
        "last_day": last_day,
        "parts": parts,
        "weights": weights(conf),
        "overall": overall(parts, conf),
        "projects": projects,
        "returned_projects": revisions["returned"] or 0,
        "revision_rate": (
            _pct((revisions["returned"] or 0) / projects * 100) if projects else None
        ),
        "total_revisions": revisions["total_revisions"] or 0,
    }


def band(score):
    """A word for a number, so the screens all use the same three."""
    if score is None:
        return "unknown"
    if score >= GOOD:
        return "good"
    if score >= POOR:
        return "fair"
    return "poor"


def team_month(people, year, month, conf=None):
    """The same figures for a list of people, newest month first on screen."""
    conf = conf or PayrollSettings.load()
    return [for_month(person, year, month, conf) for person in people]


# ---------------------------------------------------------------------------
# The board: who delivered the most this month
# ---------------------------------------------------------------------------

#: How many stand on the podium.
PODIUM = 3


def board(people, year, month, conf=None):
    """Everybody's productivity for one month, best first: ``{"podium": [...], "rest": [...]}``, a few queries however many people.

    One row per person: ``person``, ``words``, ``target``, ``score`` (the productivity indicator, the same figure the person's own
    page shows: it is that function's) and ``projects`` delivered. They are ranked by that score, then by words, then by name; a
    person who has delivered nothing has no rank (an order among zeros would be an invented one), and a person with no target has no
    score at all (``None``: not measured, never a zero), so neither stands on the podium. ``rest`` is everyone else: the ranked
    first, then the unranked in name order.

    ``people`` should come with ``select_related("salary_plan")``: a plan can carry its own target.
    """
    conf = conf or PayrollSettings.load()
    first_day, last_day = payroll.month_bounds(year, month)
    people = list(people)
    ids = [person.pk for person in people]
    words = {
        row["user"]: row["total"] or 0
        for row in WorkDay.objects.filter(user__in=ids, date__range=(first_day, last_day), status=DayStatus.PRESENT)
        .values("user").annotate(total=Sum("words"))
    }
    projects = {
        row["translator"]: row["n"]
        for row in Task.objects.filter(translator__in=ids, translated_at__date__range=(first_day, last_day))
        .values("translator").annotate(n=Count("id"))
    }
    rows = []
    for person in people:
        part = productivity(person, first_day, last_day, conf, words=words.get(person.pk, 0))
        rows.append({
            "person": person, "words": part["words"], "target": part["target"], "score": part["score"],
            "projects": projects.get(person.pk, 0), "rank": None,
        })
    by_name = lambda row: ((row["person"].short_name or "").lower(), row["person"].pk)
    ranked = sorted((row for row in rows if row["score"] is not None and row["words"] > 0), key=lambda row: (-row["score"], -row["words"], *by_name(row)))
    for place, row in enumerate(ranked, start=1):
        row["rank"] = place
    unranked = sorted((row for row in rows if row["rank"] is None), key=by_name)
    return {"podium": ranked[:PODIUM], "rest": ranked[PODIUM:] + unranked}


def history(person, year, month, count=6, conf=None):
    """One person's productivity for the ``count`` months ending at ``year``-``month``, newest first: two queries.

    Each month's score is ``productivity`` over that month's words, against the target the person has now.
    """
    from django.db.models.functions import TruncMonth

    conf = conf or PayrollSettings.load()
    months = []
    here = (year, month)
    for _ in range(count):
        months.append(here)
        here = (here[0], here[1] - 1) if here[1] > 1 else (here[0] - 1, 12)
    oldest = payroll.month_bounds(*months[-1])[0]
    newest = payroll.month_bounds(year, month)[1]
    words = {
        (row["month"].year, row["month"].month): row["total"] or 0
        for row in WorkDay.objects.filter(user=person, date__range=(oldest, newest), status=DayStatus.PRESENT)
        .annotate(month=TruncMonth("date")).values("month").annotate(total=Sum("words"))
    }
    projects = {
        (row["month"].year, row["month"].month): row["n"]
        for row in Task.objects.filter(translator=person, translated_at__date__range=(oldest, newest))
        .annotate(month=TruncMonth("translated_at")).values("month").annotate(n=Count("id"))
    }
    out = []
    for when in months:
        first_day, last_day = payroll.month_bounds(*when)
        part = productivity(person, first_day, last_day, conf, words=words.get(when, 0))
        out.append({
            "year": when[0], "month": when[1], "words": part["words"], "target": part["target"], "score": part["score"],
            "projects": projects.get(when, 0),
        })
    return out
