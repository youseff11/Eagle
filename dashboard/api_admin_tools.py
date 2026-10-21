"""``/api/v1/admin/`` - the admin panel's tools: the three clear-outs (tasks, mail, staff). The message simulator went on 21/10/2026.

The tasks and mail pages are ``views.admin_reset_tasks`` and ``admin_reset_mail`` (the classic ones, gone now); the staff one was
only ever here. They do it through the same functions (``services.reset_all_tasks``, ``reset_all_mail``,
``reset_all_staff``), so the guards stay where they were: the admin role, the admin's *own* password typed again, and one
transaction.

The clear-outs delete real data and cannot be undone, so nothing here makes them easier:

* a GET only counts what would go and changes nothing;
* the run needs the password *and* ``confirm: true`` - an absent, false or any other value for ``confirm`` is a 400 and
  nothing is touched, whatever the password;
* a wrong password is a refusal with its reason, written down as the classic page wrote it, and nothing is touched; after
  five wrong ones in a quarter of an hour the clear-outs are shut to that admin (429), and a right password is no way in
  until the window has passed (``services.reset_password_problem``, shared with the classic pages);
* the backup of what was deleted comes back as the file the browser saves. It is not stored on the server, and the
  password is in this request and nowhere else: not answered, not logged.
"""

import logging

from django.http import HttpResponse, JsonResponse
from django.utils import timezone

from . import identity, services
from .api_v1 import BadBody, _error, _object, endpoint
from .models import Role
from .permissions import api_role_required

log = logging.getLogger("dashboard")

#: The longest password the clear-outs read (a real one is far shorter; the rest is a body that wants memory).
MAX_PASSWORD = 200


# ---------------------------------------------------------------------------
# The three clear-outs
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


@endpoint("GET")
@api_role_required(Role.ADMIN)
def reset_staff_counts(request):
    """What clearing the staff would take with it, and what is in the way. Changes nothing."""
    return JsonResponse({"ok": True, "counts": services.staff_reset_counts()})


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


@endpoint("POST")
@api_role_required(Role.ADMIN)
def reset_staff_run(request):
    """Delete every employee who is not an admin: the admin's own password and the explicit yes. Answers with the backup."""
    password, refused = _password_and_yes(request)
    if refused is not None:
        return refused
    ok, problem, backup, deleted, removed = services.reset_all_staff(request.user, password)
    if not ok:
        return _refusal(problem)
    _record_export(request, "staff-backup", deleted)
    return _backup(backup, "staff", {"X-Eagle-Deleted": deleted, "X-Eagle-Files": removed})
