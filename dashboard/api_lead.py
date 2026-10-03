"""``/api/v1/`` - the team leader's screen (phase 5, screen 7): their tasks, and who of their team is free.

The pages are ``views.lead_home`` and ``views.lead_translators``, and the answers come from the same functions
(``services.translator_board`` is the one that says who is free, so the two pages cannot disagree about it - on the classic
home page the count and the board used the two slightly different rules; here both read the board). Everything is the
leader's *own*: their tasks (``Task.team_lead``), their team (``User.team_lead``). Nothing in a request names anybody else.

The leader's page of one task is not here: it is ``api_ops.task`` (the same projection the operation reads, with the
leader's tools added for the people who may use them), and everything the leader does on it is a classic endpoint that
checks it again - assigning a translator, the translator's deadline, the answer to a request for more time, the review.

The client is a code for a leader (``label_for``): the only thing a team leader ever knows of a client.
"""

from django.http import JsonResponse

from . import services
from .api_ops import MAX_TASKS, _list_row, _seen_json
from .api_v1 import _status_json, _stamp, endpoint
from .models import ACTIVE_TASK_STATUSES, AppSettings, Role, Task, TaskStatus
from .permissions import api_role_required

#: How many closed tasks the home page lists: the classic page's own number.
MAX_CLOSED = 20
#: How many tasks waiting for a translator the board lists.
MAX_WAITING = 20


def _person_json(person):
    return {
        "id": person.pk,
        "name": person.short_name,
        "initials": person.initials,
        "languages": person.languages,
        "rating": float(person.rating),
    }


@endpoint("GET")
@api_role_required(Role.TEAM_LEAD)
def home(request):
    """The leader's board: the four numbers, the open tasks, the team, and what was closed lately."""
    user = request.user
    warning = AppSettings.load().deadline_warning_minutes
    mine = Task.objects.filter(team_lead=user).select_related("client", "translator", "team_lead")
    rows = services.translator_board(user)
    return JsonResponse({
        "ok": True,
        "counters": {
            "open": mine.filter(status__in=ACTIVE_TASK_STATUSES).count(),
            "free": sum(1 for row in rows if row["state"] == "free"),
            "busy": sum(1 for row in rows if row["state"] == "busy"),
            # Not here: on a shift without Eagle open, and away. The classic page counts both as offline.
            "offline": sum(1 for row in rows if row["state"] in ("shift", "off")),
        },
        "tasks": [_list_row(task, user, warning) for task in mine.filter(status__in=ACTIVE_TASK_STATUSES)[:MAX_TASKS]],
        "team": [
            {**_person_json(row["person"]), "state": row["state"], "seen": _seen_json(row["person"])} for row in rows
        ],
        "closed": [
            {"code": task.code, "status": _status_json(task.status)}
            for task in mine.filter(status__in=[TaskStatus.DELIVERED, TaskStatus.CANCELLED])[:MAX_CLOSED]
        ],
    })


@endpoint("GET")
@api_role_required(Role.TEAM_LEAD)
def translators(request):
    """Who is free and who is busy: the leader's assignment board, with the evidence behind each state.

    "Free" means Eagle is open now, with no running task and no offer awaiting an answer. A person's tasks are the
    first three (the load says how many more), and the tasks that wait for somebody are listed above the board.
    """
    user = request.user
    warning = AppSettings.load().deadline_warning_minutes
    rows = services.translator_board(user)
    waiting = (
        Task.objects.filter(team_lead=user, status=TaskStatus.LEAD_ACCEPTED)
        .select_related("client").order_by("deadline", "code")[:MAX_WAITING]
    )
    return JsonResponse({
        "ok": True,
        "counters": {
            "free": sum(1 for row in rows if row["state"] == "free"),
            "busy": sum(1 for row in rows if row["state"] == "busy"),
            "shift": sum(1 for row in rows if row["state"] == "shift"),
            "offline": sum(1 for row in rows if row["state"] == "off"),
            "open": sum(row["load"] for row in rows),
        },
        "waiting": [
            {
                "code": task.code,
                "due": _stamp(task.deadline, "%m-%d"),
                "due_state": task.deadline_state(user, warning),
            }
            for task in waiting
        ],
        "team": [
            {
                **_person_json(row["person"]),
                "state": row["state"],
                "awaiting_answer": row["awaiting_answer"],
                "load": row["load"],
                "load_percent": row["load_percent"],
                "words": row["words"],
                "tasks": [task.code for task in row["tasks"][:3]],
                "next_due": _stamp(row["next_deadline"], "%m-%d"),
                "next_due_state": row["tasks"][0].deadline_state(user, warning) if row["tasks"] else "none",
            }
            for row in rows
        ],
    })
