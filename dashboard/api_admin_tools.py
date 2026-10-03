"""``/api/v1/admin/`` - the admin panel's tools: simulate a client's message, and the two clear-outs.

The pages are ``views.admin_simulate``, ``admin_reset_tasks`` and ``admin_reset_mail``. They do what those pages do through
the same functions (``services.ingest_message``, ``reset_all_tasks``, ``reset_all_mail``), so the guards stay where they
were: the admin role, the admin's *own* password typed again, and one transaction.

The two clear-outs delete real data and cannot be undone, so nothing here makes them easier:

* a GET only counts what would go and changes nothing;
* the run needs the password *and* ``confirm: true`` - an absent, false or any other value for ``confirm`` is a 400 and
  nothing is touched, whatever the password;
* a wrong password is a refusal with its reason, written down as the classic page wrote it, and nothing is touched;
* the backup of what was deleted comes back as the file the browser saves. It is not stored on the server, and the
  password is in this request and nowhere else: not answered, not logged.
"""

from django.http import HttpResponse, JsonResponse
from django.utils import timezone
from django.utils.text import Truncator

from . import api_forms, identity, services
from .api_v1 import BadBody, _error, _object, endpoint
from .forms import SimulateMessageForm
from .models import InboundMessage, Role
from .permissions import api_role_required

#: How many recent messages the simulator lists, and how much of each it quotes: the classic page's own numbers.
MAX_RECENT = 20
RECENT_BODY = 60
#: The longest password the clear-outs read (a real one is far shorter; the rest is a body that wants memory).
MAX_PASSWORD = 200


# ---------------------------------------------------------------------------
# Simulating a client's message
# ---------------------------------------------------------------------------

@endpoint("GET")
@api_role_required(Role.ADMIN)
def simulate(request):
    """The simulator's form choices and the latest messages (their client's code, a start of the words, whether held back)."""
    recent = InboundMessage.objects.select_related("client")[:MAX_RECENT]
    return JsonResponse({
        "ok": True,
        "channels": [{"value": value, "label": label} for value, label in SimulateMessageForm.CHANNELS],
        "recent": [
            {
                "id": message.pk,
                "code": message.client_code,
                "body": Truncator(message.body).chars(RECENT_BODY),
                "blocked": message.is_rate_blocked,
            }
            for message in recent
        ],
    })


@endpoint("POST")
@api_role_required(Role.ADMIN)
def simulate_send(request):
    """Make a message arrive as if a client sent it (multipart: the fields, and ``files``). The classic function does the rest."""
    form = SimulateMessageForm(request.POST, request.FILES)
    if not form.is_valid():
        return api_forms.invalid(form)
    uploads = request.FILES.getlist("files")
    message = services.ingest_message(
        channel=form.cleaned_data["channel"],
        body=form.cleaned_data["body"],
        subject=form.cleaned_data["subject"],
        sender_identity=form.cleaned_data["sender_identity"],
        attachments=[{"file": upload, "name": upload.name, "size": upload.size} for upload in uploads],
    )
    return JsonResponse({"ok": True, "id": message.pk, "code": message.client_code, "blocked": message.is_rate_blocked})


# ---------------------------------------------------------------------------
# The two clear-outs
# ---------------------------------------------------------------------------

@endpoint("GET")
@api_role_required(Role.ADMIN)
def reset_tasks_counts(request):
    """What resetting the tasks would take with it. Changes nothing."""
    return JsonResponse({"ok": True, "counts": services.task_reset_counts()})


@endpoint("GET")
@api_role_required(Role.ADMIN)
def reset_mail_counts(request):
    """What clearing the mail would take with it, and what stays because tasks stand on it. Changes nothing."""
    return JsonResponse({"ok": True, "counts": services.mail_reset_counts()})


def _password_and_yes(request):
    """``(password, None)`` when the body is the shape and carries the explicit yes, else ``(None, the answer to give)``."""
    try:
        body = _object(request)
    except BadBody:
        return None, _error(400, "bad_body")
    password = body.get("password", "")
    if not isinstance(password, str) or len(password) > MAX_PASSWORD or "\x00" in password:
        return None, _error(400, "bad_body")
    if body.get("confirm") is not True:
        return None, _error(400, "confirm_required")
    return password, None


def _refusal(problem):
    return JsonResponse({"ok": False, "error": "refused", "message": problem}, status=400)


def _backup(backup, name, headers):
    """The backup as the file the browser saves. Dated in Egypt time, like every time Eagle shows."""
    stamp = timezone.localtime().strftime("%Y%m%d-%H%M")
    response = HttpResponse(backup, content_type="application/json; charset=utf-8")
    response["Content-Disposition"] = f'attachment; filename="eagle-{name}-backup-{stamp}.json"'
    for key, value in headers.items():
        response[key] = str(value)
    return response


@endpoint("POST")
@api_role_required(Role.ADMIN)
def reset_tasks_run(request):
    """Delete every task and start the numbering over: the admin's own password and the explicit yes. Answers with the backup."""
    password, refused = _password_and_yes(request)
    if refused is not None:
        return refused
    ok, problem, backup, deleted = services.reset_all_tasks(request.user, password)
    if not ok:
        return _refusal(problem)
    identity.record_export(request, "tasks-backup", deleted)
    return _backup(backup, "tasks", {"X-Eagle-Deleted": deleted})


@endpoint("POST")
@api_role_required(Role.ADMIN)
def reset_mail_run(request):
    """Delete the mail no task stands on: the admin's own password and the explicit yes. Answers with the backup."""
    password, refused = _password_and_yes(request)
    if refused is not None:
        return refused
    ok, problem, backup, deleted, removed = services.reset_all_mail(request.user, password)
    if not ok:
        return _refusal(problem)
    identity.record_export(request, "mail-backup", deleted)
    return _backup(backup, "mail", {"X-Eagle-Deleted": deleted, "X-Eagle-Files": removed})
