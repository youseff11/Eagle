"""``/api/v1/announce/`` - technical support tells every employee something, when it wants to.

A notification to everybody who works here, written by the support account (and the owner). It is the one way a person of
the support role reaches the whole company at once: the bell and the sound of each employee, nothing else. It does not open
a chat, carries no file and no address, and is written to the audit log with who sent it and to how many.

* a GET says how many people it would reach and lists the latest announcements, so a person sees what was already said;
* a POST sends one: ``{"title": "...", "body": "...", "level": "info"|"warning", "sound": false}``. The same words from the
  same person inside a minute are a double press and are refused (409), not sent twice.
"""

from django.http import JsonResponse

from . import clock, services
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
