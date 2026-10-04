"""``/api/v1/admin/clients/`` - the admin panel's client records: the list, the identity form, and deleting junk clients.

The pages are ``views.admin_clients``, ``client_form`` and ``admin_clients_delete``. This is the one place the whole
identity of a client is on a page - name, company, every number and address - so opening it is written down, as every
other door that shows it does (``identity.record_identity_*``): a list is one row, a client's form is one row. The
list is asked for when it opens and when a search is sent, not on a clock.

Deleting is the classic two steps and the classic function (``services.delete_clients``): first what would go, which
changes nothing, then the yes, which has to carry ``confirm: true``. The blockers are worked out again at the yes.

Only the admin is answered.
"""

from django.http import JsonResponse
from django.shortcuts import get_object_or_404

from . import api_admin_tools as tools
from . import api_forms, files, identity, services
from .api_v1 import BadBody, _error, _object, endpoint
from .forms import ClientForm
from .models import Client, Role
from .permissions import api_role_required

#: How many clients the list shows: the classic page's own number.
MAX_CLIENTS = 300
#: The longest search: a word or two.
MAX_QUERY = 200
#: The most clients one delete may name (it cannot be more than the list showed).
MAX_DELETE = MAX_CLIENTS


def _row(client):
    phones, emails = client.all_phones, client.all_emails
    return {
        "id": client.pk,
        "code": client.code,
        "name": client.name,
        "company": client.company,
        "phone": phones[0] if phones else "",
        "more_phones": max(len(phones) - 1, 0),
        "email": emails[0] if emails else "",
        "more_emails": max(len(emails) - 1, 0),
        "active": client.is_active,
    }


@endpoint("GET")
@api_role_required(Role.ADMIN)
def clients(request):
    """Every client with the real details: ``?q=`` searches, ``?show=robots`` lists only the no-reply addresses."""
    query = request.GET.get("q", "").strip()
    show = request.GET.get("show", "")
    if show not in ("", "robots") or len(query) > MAX_QUERY or "\x00" in query:
        return _error(400, "bad_filter")
    rows = services.automated_clients() if show else Client.objects.all()
    if query:
        rows = rows.filter(identity.client_search(request.user, query))
    shown = list(rows[:MAX_CLIENTS])
    identity.record_identity_list(request, [client.code for client in shown], query)
    return JsonResponse({
        "ok": True,
        "q": query,
        "show": show,
        "shown": rows.count(),
        "all_count": Client.objects.count(),
        "robots_count": services.automated_clients().count(),
        "clients": [_row(client) for client in shown],
    })


def _ids(request):
    """The ids a delete names: a short list of whole numbers, as ``(ids, body)``."""
    body = _object(request)
    raw = body.get("ids")
    if not isinstance(raw, list) or not raw or len(raw) > MAX_DELETE:
        raise BadBody
    ids = []
    for item in raw:
        if isinstance(item, bool) or not isinstance(item, int) or not 0 < item < 2 ** 63:
            raise BadBody
        if item not in ids:
            ids.append(item)
    return ids, body


def _plan_row(row):
    client = row["client"]
    contacts = client.all_emails or client.all_phones
    return {
        "id": client.pk,
        "code": client.code,
        "name": client.name,
        "contact": contacts[0] if contacts else "",
        "letters": row["letters"],
        "files": row["files"],
        "replies": row["replies"],
        "rooms": row["rooms"],
        "blocked": row["blocked"],
    }


@endpoint("POST")
@api_role_required(Role.ADMIN)
def delete_plan(request):
    """What deleting these clients would take with it, and which cannot go at all. Changes nothing."""
    try:
        ids, _body = _ids(request)
    except BadBody:
        return _error(400, "bad_body")
    chosen = Client.objects.filter(pk__in=ids)
    if not chosen.exists():
        return _error(404, "no_clients")
    plan = services.client_delete_plan(chosen)
    identity.record_identity_list(request, [row["client"].code for row in plan], "delete plan")
    return JsonResponse({
        "ok": True,
        "deletable": [_plan_row(row) for row in plan if not row["blocked"]],
        "blocked": [_plan_row(row) for row in plan if row["blocked"]],
    })


@endpoint("POST")
@api_role_required(Role.ADMIN)
def delete(request):
    """Delete the named clients that nothing depends on: the owner's own password, the explicit yes, and the backup comes back.

    Like the two clear-outs, and for the same reason: nothing else in the product is this final. The answer is the backup of
    the rows that went, saved by the browser before anything else, because by then it is the only copy.
    """
    try:
        ids, _body = _ids(request)
    except BadBody:
        return _error(400, "bad_body")
    password, refused = tools._password_and_yes(request)
    if refused is not None:
        return refused
    ok, problem, backup, deleted, blocked, removed = services.delete_clients_safely(request.user, ids, password)
    if not ok:
        if problem in (services.RESET_LOCKED_MESSAGE, "الباسورد غلط."):
            return tools._refusal(problem)
        return JsonResponse({"ok": False, "error": "refused", "message": problem, "blocked": blocked}, status=409)
    tools._record_export(request, "clients-backup", len(deleted))
    return tools._backup(backup, "clients", {"X-Eagle-Deleted": len(deleted), "X-Eagle-Blocked": len(blocked), "X-Eagle-Files": removed})


@endpoint("GET")
@api_role_required(Role.ADMIN)
def client_new(request):
    return JsonResponse({"ok": True, "code": "", "form": api_forms.describe(ClientForm())})


@endpoint("GET")
@api_role_required(Role.ADMIN)
def client(request, code):
    """One client's identity form."""
    row = get_object_or_404(Client, code=code)
    identity.record_identity_view(request, row, "admin_client_edit")
    return JsonResponse({"ok": True, "code": row.code, "form": api_forms.describe(ClientForm(instance=row))})


@endpoint("POST")
@api_role_required(Role.ADMIN)
def client_create(request):
    form, refused = api_forms.filled(request, ClientForm)
    if refused is not None:
        return refused
    row = form.save()
    # The code only: this log is read by people who may not see a client's identity.
    services.log(request.user, "client.create", row.code)
    return JsonResponse({"ok": True, "code": row.code})


@endpoint("POST")
@api_role_required(Role.ADMIN)
def client_save(request, code):
    row = get_object_or_404(Client, code=code)
    form, refused = api_forms.filled(request, ClientForm, row)
    if refused is not None:
        return refused
    form.save()
    # The names of the files this client already sent were masked against what was known then.
    files.remask_names(row)
    # Which boxes, not what is in them: a number added to a client changes where that client's messages land.
    services.log(request.user, "client.update", row.code, ", ".join(form.changed_data))
    return JsonResponse({"ok": True, "code": row.code})
