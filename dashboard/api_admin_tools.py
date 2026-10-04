"""``/api/v1/admin/`` - the admin panel's tools: simulate a client's message, and the two clear-outs.

The pages are ``views.admin_simulate``, ``admin_reset_tasks`` and ``admin_reset_mail``. They do what those pages do through
the same functions (``services.ingest_message``, ``reset_all_tasks``, ``reset_all_mail``), so the guards stay where they
were: the admin role, the admin's *own* password typed again, and one transaction.

The two clear-outs delete real data and cannot be undone, so nothing here makes them easier:

* a GET only counts what would go and changes nothing;
* the run needs the password *and* ``confirm: true`` - an absent, false or any other value for ``confirm`` is a 400 and
  nothing is touched, whatever the password;
* a wrong password is a refusal with its reason, written down as the classic page wrote it, and nothing is touched; after
  five wrong ones in a quarter of an hour both clear-outs are shut to that admin (429), and a right password is no way in
  until the window has passed (``services.reset_password_problem``, shared with the classic pages);
* the backup of what was deleted comes back as the file the browser saves. It is not stored on the server, and the
  password is in this request and nowhere else: not answered, not logged.
"""

import logging

from django.http import HttpResponse, JsonResponse
from django.utils import timezone
from django.utils.text import Truncator

from . import api_forms, identity, services
from .api_v1 import BadBody, _error, _object, endpoint
from .forms import SimulateMessageForm
from .models import AppSettings, InboundMessage, Role
from .permissions import api_role_required

log = logging.getLogger("dashboard")

#: How many recent messages the simulator lists, and how much of each it quotes: the classic page's own numbers.
MAX_RECENT = 20
RECENT_BODY = 60
#: The longest password the clear-outs read (a real one is far shorter; the rest is a body that wants memory).
MAX_PASSWORD = 200
#: One file of a simulated message: far above any real document, below what would be a way to fill the disk.
MAX_SIMULATED_FILE_BYTES = 20 * 1024 * 1024


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
    # The switch on the settings page ("Allow message simulation") is what turns this door off; it is read here, not just drawn.
    if not AppSettings.load().simulation_enabled:
        return JsonResponse({
            "ok": False, "error": "simulation_off",
            "message": "المحاكاة مقفولة من الإعدادات.", "message_en": "Simulation is switched off in the settings.",
        }, status=409)
    form = SimulateMessageForm(request.POST, request.FILES)
    if not form.is_valid():
        return api_forms.invalid(form)
    uploads = request.FILES.getlist("files")
    if any(upload.size > MAX_SIMULATED_FILE_BYTES for upload in uploads):
        return _error(400, "file_too_big")
    message = services.ingest_message(
        channel=form.cleaned_data["channel"],
        body=form.cleaned_data["body"],
        subject=form.cleaned_data["subject"],
        sender_identity=form.cleaned_data["sender_identity"],
        attachments=[{"file": upload, "name": upload.name, "size": upload.size} for upload in uploads],
    )
    # The code and the channel, never the words: the log is read by people who may not know the client.
    services.log(request.user, "admin.simulate", message.client_code or "", form.cleaned_data["channel"])
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
    """A refusal with its reason in words. Too many wrong passwords is its own answer (429), so a page can say it is shut."""
    if problem == services.RESET_LOCKED_MESSAGE:
        return JsonResponse({"ok": False, "error": "too_many_attempts", "message": problem}, status=429)
    return JsonResponse({"ok": False, "error": "refused", "message": problem}, status=400)


def _record_export(request, what, count):
    """Write down the download. By now the data is gone and the backup is the only copy: a failure to write this row must
    never cost the admin the file, so it is logged and the answer goes out."""
    try:
        identity.record_export(request, what, count)
    except Exception:  # noqa: BLE001 - see the docstring
        log.exception("api v1: the audit row for %s could not be written", what)


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
    _record_export(request, "tasks-backup", deleted)
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
    _record_export(request, "mail-backup", deleted)
    return _backup(backup, "mail", {"X-Eagle-Deleted": deleted, "X-Eagle-Files": removed})
