"""Choosing a person's company shift from their file: one rule for the HR page and the admin panel.

The employee file (``views.hr_employee_shift``) and the admin's staff page (``api_admin.user_shift``) both put somebody on a
company shift for some weekdays, or on none, or on a shift that does not exist yet. They ask the same questions in the same
order, so a refusal means the same thing on both and neither can leave a half-made shift behind.
"""

from . import attendance
from .forms import NewShiftForm
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
    template = ShiftTemplate.objects.filter(pk=raw, is_active=True).first() if raw.isdigit() else None
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
