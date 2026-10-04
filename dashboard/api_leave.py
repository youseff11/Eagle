"""``/api/v1/leave/`` - leave: a person's own balance and requests, asking for time off, withdrawing a request, and the decision.

The pages are ``views.my_leave`` (open to everybody signed in: it is only ever their own) and ``views.hr_leave`` (the queue, in
``api_hr``). The rules are ``employees.*`` - the balance, a request's checks, who may move a request along and what an approval
writes onto the attendance sheet - so what the classic page refused is refused here, in the same words.

* A request is the person's own. Nothing in the request names anybody else, and a request that is not theirs is not there.
* A decision is the manager's or HR's (or the admin's). Anybody else is told the request does not exist, and it is written
  down: a request's number should not tell a stranger whether it is there.
* Money-free, but not harmless: an approval writes real days onto the attendance sheet, and ``employees.decide_leave`` is the
  only place that does it.
"""

from django.http import JsonResponse
from django.shortcuts import get_object_or_404
from django.utils import timezone

from . import api_forms, employees, identity, services
from .api_forms import named
from .api_v1 import BadBody, _error, _object, _stamp, endpoint
from .forms import LeaveRequestForm
from .models import LeaveKind, LeaveRequest, LeaveStatus, PayrollSettings
from .templatetags.eagle_tags import LEAVE_STATUS_MAP

#: How many of a person's own requests the page lists: the classic page's number.
MAX_OWN = 40

LEAVE_KIND_MAP = {
    LeaveKind.ANNUAL: ("إجازة اعتيادية", "Annual leave"),
    LeaveKind.EMERGENCY: ("إجازة عارضة", "Emergency leave"),
    LeaveKind.PERMISSION: ("إذن (ساعات)", "Permission (hours)"),
    LeaveKind.UNPAID: ("إجازة بدون مرتب", "Unpaid leave"),
    LeaveKind.OTHER: ("أخرى", "Other"),
}

LEAVE_TEXT = {
    "kind": ("النوع", "Kind"),
    "start_date": ("من", "From"),
    "end_date": ("إلى", "To"),
    "start_time": ("من الساعة (للإذن)", "From (permission)"),
    "end_time": ("للساعة", "To"),
    "reason": ("السبب", "Reason"),
}


def _pair(table, value):
    ar, en = table.get(value, (value, value))
    return {"value": value, "ar": ar, "en": en}


def kind_json(value):
    return _pair(LEAVE_KIND_MAP, value)


def status_json(value):
    tone, ar, en = LEAVE_STATUS_MAP.get(value, ("", value, value))
    return {"value": value, "tone": tone, "ar": ar, "en": en}


def request_json(row):
    """One request as the lists draw it. A permission has no end date and no days: it has a window inside one day."""
    permission = row.is_permission
    return {
        "id": row.pk,
        "kind": kind_json(row.kind),
        "is_permission": permission,
        "start_date": row.start_date.isoformat(),
        "end_date": None if permission else row.end_date.isoformat(),
        "days": 0 if permission else row.day_count,
        "minutes": row.minutes if permission else 0,
        "start_time": _stamp(row.start_time, "") if permission else None,
        "end_time": _stamp(row.end_time, "") if permission else None,
        "status": status_json(row.status),
        "is_open": row.is_open,
        "reason": row.reason,
        "decision_note": row.decision_note,
    }


def refusal(refused, status=409):
    """The answer for a rule the engine refused: its own words in both languages, nothing written."""
    return JsonResponse({"ok": False, "error": "refused", "message": refused.ar, "message_en": refused.en}, status=status)


def _leave_form():
    return named(
        api_forms.describe(LeaveRequestForm()), LEAVE_TEXT,
        choices={"kind": {value: pair for value, pair in LEAVE_KIND_MAP.items()}},
    )


@endpoint("GET")
def mine(request):
    """This person's balance for the month, their latest requests, and the form that asks for time off."""
    person = request.user
    today = timezone.localdate()
    conf = PayrollSettings.load()
    return JsonResponse({
        "ok": True,
        "balance": employees.leave_balance(person, today.year, today.month, conf),
        "rows": [request_json(one) for one in person.leave_requests.all()[:MAX_OWN]],
        "form": _leave_form(),
        "needs_manager": conf.leave_needs_manager,
    })


@endpoint("POST")
def ask(request):
    """Ask for time off (``{"values": {...}}``): the classic form decides what is valid, the engine what is allowed."""
    form, refused = api_forms.filled(request, LeaveRequestForm)
    if refused:
        return refused
    try:
        row = employees.request_leave(
            request.user,
            kind=form.cleaned_data["kind"],
            start_date=form.cleaned_data["start_date"],
            end_date=form.cleaned_data["end_date"],
            start_time=form.cleaned_data.get("start_time"),
            end_time=form.cleaned_data.get("end_time"),
            reason=form.cleaned_data.get("reason", ""),
            actor=request.user,
        )
    except employees.LifecycleError as refusal_:
        return refusal(refusal_)
    return JsonResponse({"ok": True, "id": row.pk})


@endpoint("POST")
def cancel(request, pk):
    """Withdraw your own request while nobody has acted on it."""
    row = get_object_or_404(LeaveRequest, pk=pk, user=request.user)
    if not row.is_open:
        return JsonResponse({
            "ok": False, "error": "already_decided",
            "message": "الطلب اتقرر فيه بالفعل.", "message_en": "This request has already been decided.",
        }, status=409)
    row.status = LeaveStatus.CANCELLED
    row.save(update_fields=["status"])
    services.log(request.user, "leave.cancel", str(pk))
    return JsonResponse({"ok": True})


@endpoint("POST")
def decide(request, pk, action):
    """Approve or reject (``{"note": "..."}``, optional). The manager's step and HR's step both land here."""
    if action not in ("approve", "reject"):
        return _error(404, "not_found")
    try:
        note = _object(request).get("note", "")
    except BadBody:
        return _error(400, "bad_body")
    if not isinstance(note, str) or len(note) > 250 or "\x00" in note:
        return _error(400, "bad_body")
    row = get_object_or_404(LeaveRequest.objects.select_related("user"), pk=pk)
    user = request.user
    # Somebody who is neither the request's manager nor HR nor the admin has no business with it, and is not told it exists.
    if not (user.is_admin_role or user.can_manage_attendance or row.manager_id == user.pk):
        identity.hidden(request, "leave request")
    try:
        employees.decide_leave(row, user, approve=(action == "approve"), note=note)
    except employees.LifecycleError as refused:
        return refusal(refused)
    return JsonResponse({"ok": True})
