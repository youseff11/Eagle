"""``/api/v1/announce/`` - technical support tells every employee something, when it wants to.

A notification to everybody who works here, written by the support account (and the owner). It is the one way a person of
the support role reaches the whole company at once: the bell and the sound of each employee, nothing else. It does not open
a chat, carries no file and no address, and is written to the audit log with who sent it and to how many.

* a GET says how many people it would reach and lists the latest announcements, so a person sees what was already said;
* a POST sends one: ``{"title": "...", "body": "...", "level": "info"|"warning", "sound": false}``. The same words from the
  same person inside a minute are a double press and are refused (409), not sent twice.
"""

from django.contrib.auth.forms import SetPasswordForm
from django.http import Http404, JsonResponse

from . import api_forms, api_profile, avatars, clock, identity, impersonation, services
from .api_v1 import BadBody, _error, _object, _text, endpoint
from .models import AuditLog, Role
from .permissions import api_role_required

#: How many of the latest announcements the page lists.
RECENT = 10

_PROBLEMS = {"empty": (400, "empty"), "too_long": (400, "too_long"), "level": (400, "bad_request"), "repeat": (409, "repeat")}


def _recent():
    rows = AuditLog.objects.filter(action=services.ANNOUNCE_ACTION).select_related("actor")[:RECENT]
    out = []
    for row in rows:
        body, _, reached = (row.detail or "").rpartition("\n")
        out.append({
            "id": row.pk,
            "title": row.target,
            "body": body,
            "reached": int(reached) if reached.isdigit() else 0,
            "by": row.actor.short_name if row.actor_id else None,
            "at": {"ar": clock.fmt12(row.created_at, "ar", "%d/%m"), "en": clock.fmt12(row.created_at, "en", "%d/%m")},
        })
    return out


@endpoint("GET", "POST")
@api_role_required(Role.SUPPORT)
def announce(request):
    user = request.user
    if request.method == "GET":
        return JsonResponse({
            "ok": True,
            "reach": services.announce_recipients(user).count(),
            "limits": {"title": services.ANNOUNCE_TITLE_MAX, "body": services.ANNOUNCE_BODY_MAX},
            "recent": _recent(),
        })
    try:
        body = _object(request)
        title = _text(body, "title", services.ANNOUNCE_TITLE_MAX)
        text = _text(body, "body", services.ANNOUNCE_BODY_MAX)
        level = _text(body, "level", 20) or "info"
    except BadBody:
        return _error(400, "bad_request")
    reached, problem = services.announce(user, title=title, body=text, level=level, sound=body.get("sound") is True)
    if problem:
        return _error(*_PROBLEMS[problem])
    return JsonResponse({"ok": True, "reached": reached})


# ---------------------------------------------------------------------------
# «حسابات الموظفين»: open an employee's account, set their password (02/11/2026, impersonation.py)
# ---------------------------------------------------------------------------

def _account(person):
    return {
        "id": person.pk,
        "username": person.username,
        "name": person.get_full_name() or person.username,
        "initials": person.initials,
        "avatar": avatars.url_of(person),
        "role": person.role,
    }


def _person(pk):
    """An account support may open, or a 404 (the owner and support itself are not on the list)."""
    person = impersonation.accounts().filter(pk=pk).first()
    if person is None:
        raise Http404
    return person


@endpoint("GET")
@api_role_required(Role.SUPPORT)
def accounts(request):
    rows = impersonation.accounts().exclude(pk=request.user.pk)
    return JsonResponse({"ok": True, "accounts": [_account(person) for person in rows]})


@endpoint("POST")
@api_role_required(Role.SUPPORT)
def account_enter(request, pk):
    """Open this person's account on this session: the next page drawn is theirs until «ارجع لحسابي»."""
    person = _person(pk)
    if not impersonation.may_open(request.user, person):
        return _error(404, "not_found")
    impersonation.enter(request, person)
    return JsonResponse({"ok": True})


@endpoint("POST")
def account_leave(request):
    """Back to the support person's own account. Nothing to go back from is not an error: the page may be a step behind."""
    impersonation.leave(request)
    return JsonResponse({"ok": True})


@endpoint("POST")
@api_role_required(Role.SUPPORT)
def account_password(request, pk):
    """Give this person a new password: ``{new_password1, new_password2}``, held to the project's validators.

    The old one is not asked (the person forgot it). Every session the person has open is signed out by the change itself.
    The password is not answered and not logged; the audit row says only who set it for whom.
    """
    person = _person(pk)
    try:
        body = _object(request)
    except BadBody:
        return _error(400, "bad_body")
    values = {name: body.get(name, "") for name in ("new_password1", "new_password2")}
    if any(not api_profile._is_text(text) for text in values.values()):
        return _error(400, "bad_body")
    form = SetPasswordForm(person, values)
    if not form.is_valid():
        return api_forms.invalid(form)
    form.save(commit=False)
    person.save(update_fields=["password"])
    identity.audit(request, request.user, impersonation.PASSWORD_SET, person.username, "set by technical support")
    return JsonResponse({"ok": True})
