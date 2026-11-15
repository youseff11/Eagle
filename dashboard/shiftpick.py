"""Choosing a person's company shift from their file: one rule for the HR page and the admin panel.

The employee file (``views.hr_employee_shift``) and the admin's staff page (``api_admin.user_shift``) both put somebody on a
company shift for some weekdays, or on none, or on a shift that does not exist yet. They ask the same questions in the same
order, so a refusal means the same thing on both and neither can leave a half-made shift behind.
"""

from django.db import transaction
from django.db.models import Count

from . import attendance, clock, services
from .forms import NewShiftForm, ShiftForm, ShiftTemplateForm
from .models import Role, ScheduleOverride, Shift, ShiftTemplate, User, Vacancy, span_minutes

#: The most weekdays a shift choice may name (there are seven; a longer list is not one).
MAX_DAYS = 14
#: The longest name or time typed for a new shift.
MAX_SHIFT_TEXT = 60

#: ``raw`` value for "a shift nobody has made yet": the three fields under it make it.
NEW = "new"

#: Why a choice was refused. ``""`` is "it went through".
BAD_NEW_SHIFT = "bad_new_shift"
NO_SUCH_SHIFT = "no_such_shift"
NO_DAYS = "no_days"


def choose(person, raw, weekdays, *, new_name="", new_start="", new_end="", actor=None):
    """Put ``person`` on the shift ``raw`` names for ``weekdays``. Returns ``(problem, template)``.

    ``raw`` is a shift's id, ``"new"`` (make one from the three ``new_`` fields) or empty (no shift at all). A refusal
    changes nothing, and a new shift is made only after every other check has passed.
    """
    raw = str(raw or "")
    # ``isdecimal``, not ``isdigit``: "²" is a digit that ``int`` cannot read, and that was a 500.
    template = ShiftTemplate.objects.filter(pk=raw, is_active=True).first() if raw.isdecimal() else None
    weekdays = [day for day in weekdays if str(day).isdecimal() and 0 <= int(day) <= 6]
    fresh = None
    if raw == NEW:
        fresh = NewShiftForm({"name_ar": new_name, "start_time": new_start, "end_time": new_end})
    if fresh is not None and not fresh.is_valid():
        return BAD_NEW_SHIFT, None
    if raw and raw != NEW and template is None:
        return NO_SUCH_SHIFT, None
    if raw and not weekdays:
        return NO_DAYS, None
    if fresh is not None:
        template, _created = attendance.shift_for_hours(
            fresh.cleaned_data["start_time"], fresh.cleaned_data["end_time"], fresh.cleaned_data["name_ar"], actor=actor,
        )
    attendance.assign_shift(person, template, weekdays, actor=actor)
    return "", template


# -- the second shift and the leader over each (15/11/2026) -----------------
# A translator who works two shifts the same day has a leader for each. The first shift's leader is ``User.team_lead`` (what
# everything that asks "who leads this translator" already reads); the second shift's rows carry their own (``Shift.team_lead``).

#: Left out of the body: that part of the file is not changed.
KEEP = object()

NO_SUCH_LEAD = "no_such_lead"
LEAD_NOT_TRANSLATOR = "lead_not_translator"
NO_FIRST_SHIFT = "no_first_shift"
SHIFTS_OVERLAP = "shifts_overlap"


def _lead_from(raw):
    """``raw`` (an id, or empty for none) -> ``(problem, leader or None)``."""
    raw = str(raw or "")
    if not raw:
        return "", None
    lead = User.objects.filter(pk=raw, role=Role.TEAM_LEAD, is_active=True, deleted_at__isnull=True).first() if raw.isdecimal() else None
    return ("", lead) if lead is not None else (NO_SUCH_LEAD, None)


def _spans(rows):
    """The minutes of the week each roster row covers, as ``(start, end)``; an overnight shift runs into the next day."""
    spans = []
    for row in rows:
        start, end = row.start, row.end
        if start and end:
            begin = row.weekday * 1440 + start.hour * 60 + start.minute
            spans.append((begin, begin + span_minutes(start, end)))
    return spans


def roster_overlaps(person):
    """Whether this person's second shift covers any minute their first shift already covers.

    Measured on the whole week, so a first shift from 5 PM to 1 AM and a second from midnight the next day overlap.
    """
    rows = list(Shift.objects.filter(user=person, is_active=True).select_related("template"))
    first = _spans(row for row in rows if row.slot == Shift.FIRST)
    second = _spans(row for row in rows if row.slot == Shift.SECOND)
    week = 7 * 1440
    return any(
        begin < other_end + turn and other_begin + turn < end
        for begin, end in second for other_begin, other_end in first for turn in (-week, 0, week)
    )


def choose_all(person, choice, *, lead=KEEP, second=KEEP, actor=None):
    """The whole shift card in one go: the first shift (``choose``), its leader and the second shift (``choose_more``).

    Returns ``(problem, template)``. One transaction, and a refusal anywhere - the second shift landing on the first's hours
    included, whichever of the two moved - rolls all of it back, a shift made from the "new" boxes too.
    """
    template, days, new_name, new_start, new_end = choice
    with transaction.atomic():
        problem, chosen = choose(person, template, days, new_name=new_name, new_start=new_start, new_end=new_end, actor=actor)
        if not problem:
            problem = choose_more(person, lead=lead, second=second, actor=actor)
        if not problem and roster_overlaps(person):
            problem = SHIFTS_OVERLAP
        if problem:
            transaction.set_rollback(True)
            return problem, None
    return "", chosen


def choose_more(person, *, lead=KEEP, second=KEEP, actor=None):
    """The first shift's leader and the second shift (``{"template", "weekdays", "team_lead"}``) from the file. Returns a problem or ``""``.

    Either may be ``KEEP``. Everything is checked before anything is written. A leader is for a translator only
    (``User.team_lead`` means nothing for anyone else); a second shift may be anybody's. Run inside ``choose_all``, which
    rolls back on a refusal and checks the two shifts do not overlap.
    """
    first_lead = second_template = second_lead = None
    second_days = []
    if lead is not KEEP:
        if lead and not person.is_translator:
            return LEAD_NOT_TRANSLATOR
        problem, first_lead = _lead_from(lead)
        if problem:
            return problem
    if second is not KEEP:
        raw = str(second["template"] or "")
        if raw:
            second_template = ShiftTemplate.objects.filter(pk=raw, is_active=True).first() if raw.isdecimal() else None
            if second_template is None:
                return NO_SUCH_SHIFT
            second_days = sorted({int(day) for day in second["weekdays"] if str(day).isdecimal() and 0 <= int(day) <= 6})
            if not second_days:
                return NO_DAYS
            if not Shift.objects.filter(user=person, slot=Shift.FIRST, is_active=True).exists():
                return NO_FIRST_SHIFT
            if second["team_lead"] and not person.is_translator:
                return LEAD_NOT_TRANSLATOR
            problem, second_lead = _lead_from(second["team_lead"])
            if problem:
                return problem
    if lead is not KEEP and person.team_lead_id != (first_lead.pk if first_lead else None):
        before = person.team_lead
        person.team_lead = first_lead
        person.save(update_fields=["team_lead"])
        services.log(actor, "employee.team_lead", person.username, f"{before.username if before else '-'} -> {first_lead.username if first_lead else '-'}")
    if second is not KEEP:
        attendance.assign_shift(person, second_template, second_days, actor=actor, slot=Shift.SECOND, team_lead=second_lead)
    return ""


def time_json(value):
    """A time of day in both languages (Cairo, twelve hours), or ``None``."""
    return {"ar": clock.fmt12(value, "ar"), "en": clock.fmt12(value, "en")} if value else None


def picker_json(person):
    """What the "which shift" card draws: the company's shifts, the one most of the roster points at, the working days."""
    current = attendance.current_template(person)
    first = person.shifts.filter(is_active=True, slot=Shift.FIRST)
    working = set(first.values_list("weekday", flat=True)) or set(attendance.DEFAULT_WORKDAYS)
    days = []
    for day in attendance.WEEK_ORDER:
        ar, en = attendance.WEEKDAY_NAMES[day]
        days.append({"num": day, "ar": ar, "en": en, "checked": day in working})
    second_rows = list(person.shifts.filter(is_active=True, slot=Shift.SECOND))
    second = attendance.current_template(person, slot=Shift.SECOND)
    leads = person.is_translator
    return {
        "current": current.pk if current else None,
        "has_custom": person.shifts.filter(template__isnull=True).exists(),
        "templates": picker_json_templates(),
        "days": days,
        # The second shift the same day, and the leader over each shift (a translator's only).
        "second": {
            "current": second.pk if second else None,
            "days": sorted({row.weekday for row in second_rows}),
            "lead": next((row.team_lead_id for row in second_rows if row.team_lead_id), None) if leads else None,
        },
        "lead": person.team_lead_id if leads else None,
        "leads": [
            {"id": one.pk, "name": one.short_name}
            for one in User.objects.filter(role=Role.TEAM_LEAD, is_active=True, deleted_at__isnull=True).order_by("first_name", "username")
        ] if leads else None,
    }


def picker_json_templates():
    """The company's active shifts, with their hours in both languages: what a shift is picked from."""
    return [
        {"id": template.pk, "label": template.label, "start": time_json(template.start_time), "end": time_json(template.end_time)}
        for template in ShiftTemplate.objects.filter(is_active=True)
    ]


def read_choice(body):
    """``(template, weekdays, new_name, new_start, new_end)`` from a request body, or ``None`` when it is not shaped like a choice.

    A template is an id (or ``"new"`` or empty), the weekdays a short list of numbers, the three new-shift boxes short text. The
    same reading for the admin's door and HR's, so neither accepts what the other would refuse.
    """
    template, days = body.get("template", ""), body.get("weekdays", [])
    if isinstance(template, int) and not isinstance(template, bool):
        template = str(template)
    texts = [body.get(name, "") for name in ("new_name", "new_start", "new_end")]
    if (
        not isinstance(template, str) or not isinstance(days, list) or len(days) > MAX_DAYS
        or any(isinstance(day, bool) or not isinstance(day, (int, str)) for day in days)
        or any(not isinstance(text, str) or len(text) > MAX_SHIFT_TEXT for text in texts)
    ):
        return None
    return template, [str(day) for day in days], texts[0], texts[1], texts[2]


def _id_text(value):
    """An id as a body sends it (a number, digits, or empty/``null`` for none) -> text, or ``None`` when it is not one."""
    if value is None:
        return ""
    if isinstance(value, int) and not isinstance(value, bool):
        return str(value)
    if isinstance(value, str) and len(value) <= 20:
        return value
    return None


def read_more(body):
    """``(lead, second)`` from a request body - each ``KEEP`` when the body does not name it - or ``None`` when shaped wrong.

    ``team_lead``: the first shift's leader (an id, or empty for none). ``second``: ``null`` takes the second shift off, or
    ``{"template", "weekdays", "team_lead"}``.
    """
    lead = second = KEEP
    if "team_lead" in body:
        lead = _id_text(body["team_lead"])
        if lead is None:
            return None
    if "second" in body:
        raw = body["second"]
        if raw is None:
            second = {"template": "", "weekdays": [], "team_lead": ""}
        elif not isinstance(raw, dict):
            return None
        else:
            template, lead_two, days = _id_text(raw.get("template")), _id_text(raw.get("team_lead")), raw.get("weekdays", [])
            if (
                template is None or lead_two is None or not isinstance(days, list) or len(days) > MAX_DAYS
                or any(isinstance(day, bool) or not isinstance(day, (int, str)) for day in days)
            ):
                return None
            second = {"template": template, "weekdays": [str(day) for day in days], "team_lead": lead_two}
    return lead, second


def shift_usage(templates):
    """Attach who leans on each company shift, so a page can say why one cannot be deleted instead of letting the database refuse it."""
    people = dict(
        Shift.objects.filter(template__isnull=False).order_by()
        .values_list("template").annotate(n=Count("user", distinct=True))
    )
    overrides = dict(
        ScheduleOverride.objects.filter(template__isnull=False).order_by()
        .values_list("template").annotate(n=Count("id"))
    )
    vacancies = dict(
        Vacancy.shifts.through.objects.values_list("shifttemplate_id")
        .annotate(n=Count("vacancy_id"))
    )
    rows = list(templates)
    for row in rows:
        row.people_n = people.get(row.pk, 0)
        row.overrides_n = overrides.get(row.pk, 0)
        row.vacancies_n = vacancies.get(row.pk, 0)
        row.in_use = bool(row.people_n or row.overrides_n or row.vacancies_n)
        row.hours_txt = f"{row.minutes / 60:g}"
    return rows


def new_template_form(name="", name_ar="", start="", end=""):
    """A company shift of four boxes (a name, its Arabic name, from, to) as a ``ShiftTemplateForm`` ready to validate and save.

    The form also needs the rest of a shift (its break, its place in the list, switched on). The box on the schedules page has
    only the four, so without the rest the form refused every shift it was given, and a shift it did save would have been
    closed. Both the classic page and the new door use this one, so neither can drift from the other.
    """
    order = (ShiftTemplate.objects.order_by("-sort_order").values_list("sort_order", flat=True).first() or 0) + 1
    return ShiftTemplateForm({
        "name": str(name or "").strip()[:60], "name_ar": str(name_ar or "").strip()[:60],
        "start_time": str(start or "").strip()[:8], "end_time": str(end or "").strip()[:8],
        "break_minutes": "0", "sort_order": str(order), "is_active": True,
    })


def typed_shift_form(weekday, start, end):
    """A roster row of typed times (a weekday, from, to) as a ``ShiftForm`` ready to validate and save.

    The box that adds one only has those three boxes; the form also needs the rest of a row (no template, the person's own work
    mode, the shift's own length, switched on), and without them it refused every row without saying so. A shift that starts and
    ends together is no shift. Both the classic staff page and the admin panel's use this, so neither can drift from the other.
    """
    form = ShiftForm({
        "weekday": str(weekday) if isinstance(weekday, (int, str)) and not isinstance(weekday, bool) else "",
        "template": "", "start_time": str(start or "").strip()[:8], "end_time": str(end or "").strip()[:8],
        "work_mode": "", "required_minutes": "0", "is_active": True,
    })
    if form.is_valid():
        start_at, end_at = form.cleaned_data["start_time"], form.cleaned_data["end_time"]
        if not start_at or not end_at:
            form.add_error("end_time" if start_at else "start_time", "اكتب وقت البداية ووقت النهاية.")
        elif start_at == end_at:
            form.add_error("end_time", "بداية الشيفت ونهايته نفس الوقت.")
    return form
