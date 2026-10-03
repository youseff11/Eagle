"""``/api/v1/`` - the client pages: the list of codes, one client, and a requirement added to one.

The same rules as the classic pages (``views.client_list``, ``views.client_detail``). The code is what everybody sees;
the name, the company, the numbers and the addresses only whoever may know the client (``identity.can_see``: the admin,
and the Accounting person the admin named). So the search leaves the identity fields out for everybody else - a search
that matched a typed name and answered with the code would hand the name over as surely as printing it - and opening
the identity, in a list or on a client, is a row in the audit log, as it is on the classic pages. A GET changes
nothing; a requirement is the one write, and it is checked where the classic page checks it.

The operation, the Sales and the admin use these doors; the other roles that open the classic pages (the team
leader, Accounting) are not moved to the new app yet, so they have no door here. A Sales person reads what the
classic page shows them - the code and who the client is (Sales may always know), the requirements, the follow-up
numbers and the newest tasks - and writes nothing: requirements are the work-doers' (``_may_edit``).
"""

from django.db.models import Count
from django.http import JsonResponse
from django.shortcuts import get_object_or_404
from django.urls import reverse

from . import identity, services
from .api_ops import MAX_REQUIREMENT, _requirement_json
from .api_v1 import BadBody, _error, _object, _origin_json, _stamp, _status_json, _text, endpoint
from .forms import RequirementForm
from .models import ACTIVE_TASK_STATUSES, Client, Role, TaskStatus
from .permissions import api_role_required

#: The most clients a list answers with, and the most tasks one client shows: the classic pages' own limits.
MAX_CLIENTS = 200
MAX_CLIENT_TASKS = 30
#: The longest search: a word or two.
MAX_QUERY = 200


@endpoint("GET")
@api_role_required(Role.OPERATION, Role.SALES)
def clients(request):
    """The client codes, ``?q=`` narrowing them. The identity columns are there only for who may see them."""
    user = request.user
    query = request.GET.get("q", "").strip()
    if len(query) > MAX_QUERY or "\x00" in query:
        return _error(400, "bad_filter")
    rows = Client.objects.all()
    if query:
        rows = rows.filter(identity.client_search(user, query))
    rows = list(rows.annotate(task_count=Count("tasks", distinct=True), requirement_count=Count("requirements", distinct=True))[:MAX_CLIENTS])
    sees = identity.can_see(user)
    if sees:
        identity.record_identity_list(request, [row.code for row in rows], query)
    return JsonResponse({
        "ok": True,
        "q": query,
        "sees_identity": sees,
        "clients": [
            {
                "code": row.code,
                "tasks": row.task_count,
                "requirements": row.requirement_count,
                # Absent, not empty, for whoever may not know: an empty name would say "there is none".
                **({"name": row.name, "company": row.company, "phone": row.phone} if sees else {}),
            }
            for row in rows
        ],
    })


def _may_edit(user):
    """Requirements are instructions for the work: the people doing it write them (the classic page's rule)."""
    return user.is_admin_role or user.is_operation or user.is_team_lead


@endpoint("GET")
@api_role_required(Role.OPERATION, Role.SALES)
def client(request, code):
    """One client: the requirements, the tasks (the newest thirty) and - for whoever may - who the client is."""
    user = request.user
    row = get_object_or_404(Client, code=code)
    sees = identity.can_see(user)
    if sees:
        identity.record_identity_view(request, row, "client_detail")
    tasks = row.tasks.all()
    # Counts and dates only, for the people who follow a client without running it: after a client is won Sales
    # follows them and does not run them - no files, no conversation, no money (the admin sees it on this page too).
    activity = None
    if user.is_admin_role or user.is_sales:
        activity = {
            "total": tasks.count(),
            "active": tasks.filter(status__in=ACTIVE_TASK_STATUSES).count(),
            "delivered": tasks.filter(status=TaskStatus.DELIVERED).count(),
            "last": _stamp(tasks.order_by("-created_at").values_list("created_at", flat=True).first(), "%Y-%m-%d"),
        }
    out = {
        "ok": True,
        "client": {"code": row.code},
        "sees_identity": sees,
        "may_edit": _may_edit(user),
        "activity": activity,
        "requirements": [
            {**_requirement_json(r, row, user), "at": _stamp(r.created_at, "%Y-%m-%d")}
            for r in row.requirements.select_related("author")
        ],
        "tasks": [
            {
                "code": task.code,
                "title": task.title,
                "origin": _origin_json(task.origin),
                "status": _status_json(task.status),
            }
            for task in tasks[:MAX_CLIENT_TASKS]
        ],
    }
    if sees:
        out["client"].update({
            "name": row.name, "company": row.company, "phones": row.all_phones, "emails": row.all_emails,
            # What the admin wrote about them for the admin alone.
            "admin_notes": row.admin_notes if user.is_admin_role else "",
        })
    if user.is_admin_role:
        # The edit form is the classic page's still: a link out of the new app, to the one place that writes the identity.
        out["edit_url"] = reverse("dashboard:admin_client_edit", args=[row.code])
    return JsonResponse(out)


@endpoint("POST")
@api_role_required(Role.OPERATION)
def client_requirement(request, code):
    """Add a thing the client likes, dislikes or insists on. ``{"kind": "rule", "text": "..."}``.

    The same form and the same audit row as the classic page; the answer is the row, so a page shows it without a reload.
    """
    row = get_object_or_404(Client, code=code)
    if not _may_edit(request.user):
        return _error(403, "forbidden")
    try:
        body = _object(request)
        kind, text = _text(body, "kind", 20), _text(body, "text", MAX_REQUIREMENT)
    except BadBody:
        return _error(400, "bad_request")
    form = RequirementForm({"kind": kind, "text": text})
    if not form.is_valid():
        return JsonResponse({"ok": False, "error": "bad_requirement", "fields": sorted(form.errors)}, status=400)
    made = form.save(commit=False)
    made.client = row
    made.author = request.user
    made.save()
    services.log(request.user, "client.requirement", row.code, made.text[:80])
    return JsonResponse({"ok": True, "requirement": {**_requirement_json(made, row, request.user), "at": _stamp(made.created_at, "%Y-%m-%d")}})
