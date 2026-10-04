"""``/api/v1/`` - the admin panel (phase 5, screen 8): the overview and the audit log, both read only.

The pages are ``views.admin_overview`` and ``views.admin_audit``, and the answers are the same questions they ask. Only the
admin is answered: anybody else is a 403 and a row in the audit log (``api_role_required``). A GET changes nothing here -
not even an audit row, because an admin reading the log must not write into it every time a board refreshes.

Two things are shown to the admin that nobody else may read, as on the classic overview: the address a hidden letter came
from, and the words of a letter the operation is kept from (``is_rate_blocked``). Nothing here is a secret of the
settings page (a token, a password): that page has its own door, which has to be written so that no secret can ride in it.
"""

from django.db.models import Count, Q
from django.http import JsonResponse
from django.utils import timezone
from django.utils.text import Truncator

from . import identity
from .api_mail import _file_json
from .api_v1 import _error, _origin_json, _stamp, _status_json, endpoint
from .models import (
    ACTIVE_TASK_STATUSES, Assignment, AssignmentStatus, AuditLog, Client, InboundMessage, Role, Task, TaskStatus,
)
from .permissions import api_role_required
from .templatetags.eagle_tags import strip_image_tags

#: How many rows each card of the overview lists: the classic page's own numbers.
MAX_BLOCKED = 20
MAX_PENDING = 20
MAX_LATE = 20
MAX_RECENT = 15
#: How much of a hidden letter the card quotes.
BLOCKED_BODY = 200
#: How many entries the log lists, newest first.
MAX_AUDIT = 200
#: How much of a log entry's detail is sent: a sentence, not a document.
AUDIT_DETAIL = 300

#: The filters of the log. Anything else is a 400, not a full log that looks like "the filter found everything".
AUDIT_FILTERS = ("", "security", "denied")


def _counters():
    """The four numbers over the overview, in one question to the database."""
    counts = Task.objects.aggregate(
        new=Count("pk", filter=Q(status=TaskStatus.NEW)),
        open=Count("pk", filter=Q(status__in=ACTIVE_TASK_STATUSES)),
        delivered=Count("pk", filter=Q(status=TaskStatus.DELIVERED)),
    )
    return {**counts, "clients": Client.objects.count()}


def _blocked_json(letter):
    """A letter hidden from the operation: its client's code, when, its words, who sent it and why it was held."""
    return {
        "id": letter.pk,
        "code": letter.client_code,
        "channel": letter.channel,
        "at": _stamp(letter.received_at, "%m-%d"),
        "body": Truncator(strip_image_tags(letter.body)).chars(BLOCKED_BODY),
        "sender": letter.sender_identity,
        "keyword": letter.blocked_keyword,
        "files": [_file_json(attachment) for attachment in letter.attachments.all()],
    }


@endpoint("GET")
@api_role_required(Role.ADMIN)
def overview(request):
    """The admin's board: the numbers, the letters held back, hand-offs waiting, late tasks, the newest tasks."""
    now = timezone.now()
    blocked = (
        InboundMessage.objects.filter(is_rate_blocked=True)
        .select_related("client").prefetch_related("attachments")[:MAX_BLOCKED]
    )
    pending = (
        Assignment.objects.filter(status=AssignmentStatus.PENDING).select_related("task", "assignee")[:MAX_PENDING]
    )
    late = (
        Task.objects.filter(status__in=ACTIVE_TASK_STATUSES, deadline__lt=now)
        .select_related("translator")[:MAX_LATE]
    )
    recent = Task.objects.all()[:MAX_RECENT]
    return JsonResponse({
        "ok": True,
        "counters": _counters(),
        "blocked": [_blocked_json(letter) for letter in blocked],
        "pending": [
            {
                "id": assignment.pk,
                "task": assignment.task.code,
                "assignee": assignment.assignee.short_name,
                "seconds_left": assignment.seconds_left,
            }
            for assignment in pending
        ],
        "late": [
            {
                "code": task.code,
                "translator": task.translator.short_name if task.translator_id else None,
                "deadline": _stamp(task.deadline, "%m-%d"),
            }
            for task in late
        ],
        "recent": [
            {
                "code": task.code,
                "title": Truncator(task.title).chars(80),
                "origin": _origin_json(task.origin),
                "status": _status_json(task.status),
            }
            for task in recent
        ],
    })


@endpoint("GET")
@api_role_required(Role.ADMIN)
def audit(request):
    """The log, newest first: ``?only=security`` (who saw an identity, was refused, was given access) or ``?only=denied``.

    Two hundred rows a time: ``more`` says there are older ones, and ``?before=<id of the oldest row shown>`` is the next page.
    """
    only = request.GET.get("only", "")
    if only not in AUDIT_FILTERS:
        return _error(400, "bad_filter")
    rows = AuditLog.objects.select_related("actor").order_by("-pk")
    before = request.GET.get("before", "")
    if before:
        if not before.isdecimal() or len(before) > 12:
            return _error(400, "bad_cursor")
        rows = rows
    if only == "security":
        rows = rows.filter(action__in=identity.SECURITY_ACTIONS)
    elif only == "denied":
        rows = rows.filter(action=identity.ACCESS_DENIED)
    page = list(rows[:MAX_AUDIT + 1])
    return JsonResponse({
        "ok": True,
        "only": only,
        "more": len(page) > MAX_AUDIT,
        "rows": [
            {
                "id": entry.pk,
                "at": _stamp(entry.created_at, "%Y-%m-%d"),
                "actor": entry.actor.short_name if entry.actor_id else None,
                "action": entry.action,
                "target": entry.target,
                "detail": Truncator(entry.detail).chars(AUDIT_DETAIL),
                "ip": entry.ip or "",
                "path": entry.path,
            }
            for entry in page[:MAX_AUDIT]
        ],
    })
