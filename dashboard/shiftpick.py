"""Choosing a person's company shift from their file: one rule for the HR page and the admin panel.

The employee file (``views.hr_employee_shift``) and the admin's staff page (``api_admin.user_shift``) both put somebody on a
company shift for some weekdays, or on none, or on a shift that does not exist yet. They ask the same questions in the same
order, so a refusal means the same thing on both and neither can leave a half-made shift behind.
"""

from . import attendance
from .forms import NewShiftForm, ShiftForm
from .models import ShiftTemplate

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
