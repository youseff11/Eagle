"""Choosing a person's company shift from their file: one rule for the HR page and the admin panel.

The employee file (``views.hr_employee_shift``) and the admin's staff page (``api_admin.user_shift``) both put somebody on a
company shift for some weekdays, or on none, or on a shift that does not exist yet. They ask the same questions in the same
order, so a refusal means the same thing on both and neither can leave a half-made shift behind.
"""

from django.db.models import Count

from . import attendance, clock
from .forms import NewShiftForm, ShiftForm, ShiftTemplateForm
from .models import ScheduleOverride, Shift, ShiftTemplate, Vacancy

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


def _time_json(value):
    """A time of day in both languages (Cairo, twelve hours), or ``None``."""
    return {"ar": clock.fmt12(value, "ar"), "en": clock.fmt12(value, "en")} if value else None


def picker_json(person):
    """What the "which shift" card draws: the company's shifts, the one most of the roster points at, the working days."""
    current = attendance.current_template(person)
    working = set(person.shifts.filter(is_active=True).values_list("weekday", flat=True)) or set(attendance.DEFAULT_WORKDAYS)
    days = []
    for day in attendance.WEEK_ORDER:
        ar, en = attendance.WEEKDAY_NAMES[day]
        days.append({"num": day, "ar": ar, "en": en, "checked": day in working})
    return {
        "current": current.pk if current else None,
        "has_custom": person.shifts.filter(template__isnull=True).exists(),
        "templates": [
            {"id": template.pk, "label": template.label, "start": _time_json(template.start_time), "end": _time_json(template.end_time)}
            for template in ShiftTemplate.objects.filter(is_active=True)
        ],
        "days": days,
    }


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
