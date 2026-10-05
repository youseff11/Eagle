"""The old interface's addresses, kept as redirects to the same thing in the app.

The classic pages are gone (phase 6). What is not gone is every link that points at one: the notifications already stored carry
``/tasks/TSK-00012/`` and ``/ops/chats/u/4/``, the messages that were sent carry them too, and people have bookmarks. Each
address answers with a redirect to the page of the app that replaced it, carrying what the page reads of the query (and nothing
else: an address cannot bring markup, or another site, into the one the redirect names).

Who may open the page is decided there, by the endpoints behind it, not here: a person sent to a page that is not theirs is told
it is not available, and the refusal is written to the audit log (by the endpoint, or here for an old address that the app would turn away
without asking anything). The URL names are the old ones, so a ``reverse`` that still
names one lands on its redirect. A form's address (a POST that is not a page) is not here: nothing sends to one any more.
"""

import re
from urllib.parse import urlencode

from django.contrib.auth.decorators import login_required
from django.shortcuts import redirect
from django.urls import path
from django.utils import timezone

from . import identity, newui, payroll
from .models import Role, TaskStatus

#: A task, client, conversation or candidate code in an address: letters, digits and dashes, short.
CODE = re.compile(r"[A-Za-z0-9-]{1,40}")
#: Ids in a list (``?messages=3,4``): digits, commas, spaces.
IDS = re.compile(r"[0-9, ]{1,400}")


def _month(request):
    """The month an address names, as ``(year, month)``: ``?period=2026-09`` or ``?year=&month=``, else this month."""
    today = timezone.localdate()
    period = request.GET.get("period") or ""
    if "-" in period:
        raw_year, _, raw_month = period.partition("-")
    else:
        raw_year = request.GET.get("year") or today.year
        raw_month = request.GET.get("month") or today.month
    try:
        year, month = int(raw_year), int(raw_month)
    except (TypeError, ValueError):
        return today.year, today.month
    if not 1 <= month <= 12 or not 2000 <= year <= 2100:
        return today.year, today.month
    return year, month


def _plain(*names):
    """The named query parameters, each as it came when it is short and printable (the page checks every value again).

    ``period`` is the month: it goes as the one ``period=2026-9`` the app reads, from ``period`` or from ``year`` and ``month``,
    and only when the address named one.
    """

    def pairs(request):
        out = []
        for name in names:
            if name == "period":
                if any(key in request.GET for key in ("period", "year", "month")):
                    year, month = _month(request)
                    out.append(("period", f"{year}-{month}"))
                continue
            value = request.GET.get(name, "")
            if value and len(value) <= 80 and value.isprintable():
                out.append((name, value))
        return out

    return pairs


def _digits(*names):
    """The named parameters that hold a person's id: ascii digits and nothing else."""

    def pairs(request):
        out = []
        for name in names:
            value = request.GET.get(name, "")
            if value.isascii() and value.isdecimal() and len(value) <= 18:
                out.append((name, value))
        return out

    return pairs


def _both(first, second):
    return lambda request: first(request) + second(request)


def _search(request):
    query = request.GET.get("q", "").strip()
    return [("q", query)] if query and len(query) <= 200 and "\x00" not in query else []


def _inbox(request):
    state = request.GET.get("state", "")
    return ([("state", state)] if state in ("unclaimed", "mine", "notask") else []) + _search(request)


def _tasks(request):
    status = request.GET.get("status", "")
    return [("status", status)] if status == "open" or status in TaskStatus.values else []


def _start(request):
    """The new-task form's address: the messages, the files and the task it repeats, each only when it is plainly an id or a code."""
    out = []
    for name in ("message", "messages", "files"):
        for value in request.GET.getlist(name):
            if IDS.fullmatch(value):
                out.append((name, value.replace(" ", "")))
    source = request.GET.get("from", "")
    if CODE.fullmatch(source):
        out.append(("from", source))
    return out


def _chats(request):
    kind = request.GET.get("type")
    return [("type", kind)] if kind in ("clients", "groups", "staff") else []


def _robots(request):
    return [("show", "robots")] if request.GET.get("show") == "robots" else []


def _audit(request):
    only = request.GET.get("only")
    return [("only", only)] if only in ("security", "denied") else []


def _payslip(request):
    period = request.GET.get("period", "")
    return [("period", period)] if payroll.parse_period(period) else []


#: The screens whose pages are the whole of an address prefix. A payslip (``/accounts/lines/<id>``) is also the translator's own,
#: so it is not gated by the accounts screen.
SCREEN_OF = {"/admin": "admin", "/hr": "hr", "/reviewer": "reviewer", "/accounts": "accounts"}


#: The roles each page was for, where no screen says it (``SCREEN_OF``) and ``only`` does not (it also moves the redirect). Used to
#: write down a refusal and to answer the sign-in; the redirect itself is the same for everybody. The admin is always allowed.
ROLES_OF = {
    "/inbox": (Role.OPERATION, Role.SALES), "/inbox/thread/{pk}": (Role.OPERATION, Role.SALES),
    "/team": (Role.OPERATION,), "/tasks": (Role.OPERATION,), "/tasks/new": (Role.OPERATION,),
    "/clients": (Role.OPERATION, Role.TEAM_LEAD, Role.SALES), "/clients/{code}": (Role.OPERATION, Role.TEAM_LEAD, Role.SALES),
    # A task has a page for whoever works on it; Sales, HR, accounting and the reviewer have none.
    "/tasks/{code}": (Role.OPERATION, Role.TEAM_LEAD, Role.TRANSLATOR),
    # The employee files answer to recruitment rights (HR and the admin), not to the attendance flag the ``hr`` screen also admits;
    # a new person is the admin's alone.
    "/hr/employees": (Role.HR,), "/hr/employees/{pk}": (Role.HR,), "/hr/employees/new": (),
}


def _go(target, pairs=None, only=None):
    """A view that sends a signed-in person to ``/app`` + ``target`` (a format string over the address' own arguments).

    ``only`` names the people the page was for (a test on the user): anybody else lands on the app's home, which is theirs.
    The view also publishes who the page is for (``eagle_allows``), which is how the sign-in leaves a person who followed a link to
    somebody else's page on their own home instead of on a refusal. A person it was not for is written down in the audit log, as
    the classic page's 403 was: the app draws the refusal in the browser without asking anything, so this is the one place that
    sees an old address opened by the wrong person.
    """
    own = target.startswith("/accounts/lines/")
    screen = None if own else newui.SCREENS.get(next((key for prefix, key in SCREEN_OF.items() if target == prefix or target.startswith(prefix + "/")), ""))

    roles = ROLES_OF.get(target)

    def allows(user):
        if roles is not None and not (user.is_admin_role or user.role in roles):
            return False
        return (only is None or bool(only(user))) and (screen is None or screen.allows(user))

    @login_required
    def view(request, **kwargs):
        if not allows(request.user):
            identity.record_denied(request, f"legacy address {request.path}")
        # A code goes into the address only when it looks like one; anything else lands on the home page.
        if (only is not None and not only(request.user)) or not CODE.fullmatch(kwargs.get("code", "x")):
            return redirect("/app/")
        found = pairs(request) if pairs is not None else []
        return redirect("/app" + target.format(**kwargs) + ("?" + urlencode(found) if found else ""))

    view.eagle_allows = allows
    return view


_lead = lambda user: user.is_team_lead  # noqa: E731
_translator = lambda user: user.is_translator  # noqa: E731

#: (old address, old URL name, where it lands under ``/app``, which of its query goes along, who it was for)
PAGES = (
    ("ops/inbox/", "ops_inbox", "/inbox", _inbox, None),
    ("ops/inbox/thread/<int:pk>/", "ops_mail_thread", "/inbox/thread/{pk}", _inbox, None),
    ("ops/chats/", "ops_chats", "/chats", _chats, None),
    ("ops/chats/g/<int:room_id>/", "ops_group_chat", "/chats/g{room_id}", None, None),
    # Before the client-code route: "u" would otherwise read as a client code.
    ("ops/chats/u/<int:user_id>/", "ops_staff_chat", "/chats/u{user_id}", None, None),
    ("ops/chats/<str:code>/", "ops_chat_detail", "/chats/{code}", None, None),
    ("ops/tasks/", "ops_tasks", "/tasks", _tasks, None),
    ("tasks/<str:code>/", "task_detail", "/tasks/{code}", None, None),
    ("ops/tasks/new/", "ops_task_new", "/tasks/new", _start, None),
    ("ops/team/", "ops_team", "/team", None, None),
    ("lead/", "lead_home", "/lead", None, _lead),
    ("lead/translators/", "lead_translators", "/lead/translators", None, _lead),
    ("translator/", "translator_home", "/translator", None, _translator),
    ("translator/payroll/", "translator_payroll", "/payroll", _payslip, _translator),
    ("assignments/<int:pk>/", "assignment_preview", "/assignments/{pk}", None, _translator),
    ("clients/", "client_list", "/clients", _search, None),
    ("clients/<str:code>/", "client_detail", "/clients/{code}", None, None),
    ("notifications/", "notifications", "/notifications", None, None),
    ("attendance/", "my_attendance", "/attendance", None, None),
    ("leave/", "my_leave", "/leave", None, None),
    ("sales/line/", "sales_line", "/line", None, lambda user: user.is_sales),
    # -- the admin panel ------------------------------------------------------
    ("panel/", "admin_overview", "/admin", None, None),
    ("panel/settings/", "admin_settings", "/admin/settings", None, None),
    ("panel/users/", "admin_users", "/hr/employees", None, None),
    ("panel/users/new/", "admin_user_new", "/hr/employees/new", None, None),
    ("panel/users/<int:pk>/", "admin_user_edit", "/hr/employees/{pk}", None, None),
    ("panel/clients/", "admin_clients", "/admin/clients", _both(_robots, _search), None),
    ("panel/clients/new/", "admin_client_new", "/admin/clients/new", None, None),
    ("panel/clients/<str:code>/edit/", "admin_client_edit", "/admin/clients/{code}/edit", None, None),
    ("panel/simulate/", "admin_simulate", "/admin/simulate", None, None),
    ("panel/audit/", "admin_audit", "/admin/audit", _audit, None),
    ("panel/reset-tasks/", "admin_reset_tasks", "/admin/reset-tasks", None, None),
    ("panel/reset-mail/", "admin_reset_mail", "/admin/reset-mail", None, None),
    # -- accounts -------------------------------------------------------------
    ("accounts/", "accounts_overview", "/accounts", _plain("period"), None),
    ("accounts/line/<int:pk>/", "accounts_line", "/accounts/lines/{pk}", None, None),
    ("accounts/attendance/", "accounts_attendance", "/accounts/attendance", _both(_plain("period"), _digits("user")), None),
    ("accounts/violations/", "accounts_violations", "/accounts/violations", None, None),
    ("accounts/rules/", "accounts_rules", "/accounts/rules", None, None),
    ("accounts/salary/<int:pk>/", "accounts_salary", "/accounts/salary/{pk}", None, None),
    # -- human resources ------------------------------------------------------
    (
        "hr/attendance/", "hr_attendance", "/hr/attendance",
        _plain("view", "date", "user", "role", "mode", "status", "day_mode", "shift", "flagged"), None,
    ),
    ("hr/attendance/<int:pk>/", "hr_attendance_day", "/hr/attendance/{pk}", None, None),
    ("hr/report/", "hr_report", "/hr/report", _plain("period", "user"), None),
    ("hr/schedules/", "hr_schedules", "/hr/schedules", _plain("user"), None),
    ("hr/shifts/", "hr_shifts", "/hr/shifts", _plain("edit"), None),
    ("hr/offices/", "hr_offices", "/hr/offices", _plain("edit"), None),
    ("hr/devices/", "hr_devices", "/hr/devices", None, None),
    ("hr/overtime/", "hr_overtime", "/hr/overtime", None, None),
    ("hr/recruitment/", "hr_recruitment", "/hr/recruitment", None, None),
    ("hr/recruitment/settings/", "hr_recruitment_settings", "/hr/recruitment/settings", None, None),
    ("hr/vacancies/", "hr_vacancies", "/hr/vacancies", _plain("status"), None),
    ("hr/vacancies/<str:code>/", "hr_vacancy", "/hr/vacancies/{code}", None, None),
    ("hr/questions/", "hr_questions", "/hr/questions", _plain("department", "edit"), None),
    ("hr/candidates/", "hr_candidates", "/hr/candidates", _plain("status", "source", "vacancy", "q"), None),
    ("hr/candidates/<str:code>/", "hr_candidate", "/hr/candidates/{code}", None, None),
    ("hr/candidates/<str:code>/hire/", "hr_hire", "/hr/candidates/{code}/hire", None, None),
    ("hr/interviews/<int:pk>/score/", "hr_interview_score", "/hr/interviews/{pk}", None, None),
    ("reviewer/tests/", "reviewer_tests", "/reviewer/tests", None, None),
    ("hr/tests/<int:pk>/score/", "hr_test_score", "/reviewer/tests/{pk}", None, None),
    ("hr/approvals/", "hr_approvals", "/hr/approvals", None, None),
    ("hr/employees/", "hr_employees", "/hr/employees", _plain("department", "status"), None),
    ("hr/employees/<int:pk>/", "hr_employee", "/hr/employees/{pk}", None, None),
    ("hr/leave/", "hr_leave", "/hr/leave", _plain("user", "status"), None),
    ("hr/probation/", "hr_probation", "/hr/probation", _plain("state"), None),
    ("hr/performance/", "hr_performance", "/hr/performance", _plain("period", "user"), None),
    ("hr/complaints/", "hr_complaints", "/hr/complaints", _plain("translator"), None),
    ("hr/salary-plans/", "hr_salary_plans", "/hr/salary-plans", _plain("edit"), None),
    ("hr/salary-requests/", "hr_salary_requests", "/hr/salary-requests", _plain("user"), None),
)

urlpatterns = [path(route, _go(target, pairs, only), name=name) for route, name, target, pairs, only in PAGES]
