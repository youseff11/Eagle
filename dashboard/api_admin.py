"""``/api/v1/`` - the admin panel (phase 5, screen 8): the overview.

The page is ``views.admin_overview``, and the answers are the same questions it asks. Only the admin is answered: anybody else
is a 403 and a row in the audit log (``api_role_required``). A GET changes nothing here; the one thing the overview writes is
«سلّم للعميل» (``deliver``), and cancelling a late task goes through the task page's own door. The audit log is still written
(``AuditLog``) but has no page since 21/10/2026: the owner did not use it.

Two things are shown to the admin that nobody else may read, as on the classic overview: the address a hidden letter came
from, and the words of a letter the operation is kept from (``is_rate_blocked``). Nothing here is a secret of the
settings page (a token, a password): that page has its own door, which has to be written so that no secret can ride in it.
"""

from django.db import transaction
from django.db.models import Count, Q
from django.http import Http404, JsonResponse
from django.shortcuts import get_object_or_404
from django.utils import timezone
from django.utils.text import Truncator

from . import services
from .api_mail import _file_json
from .api_v1 import _origin_json, _stamp, _status_json, endpoint
from .models import (
    ACTIVE_TASK_STATUSES, Assignment, AssignmentStatus, Client, InboundMessage, Role, Task, TaskStatus,
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


#: Why «سلّم للعميل» did not send, in the admin's words (the page shows the sentence as it is).
NOT_REVIEWED_AR = "التاسك مش مستنية التسليم للعميل دلوقتي."
NO_FINAL_FILES_AR = "مفيش ملف نهائي على التاسك. افتحها واختار الملفات من صفحتها."


@endpoint("POST")
@api_role_required(Role.ADMIN)
def deliver(request, code):
    """«سلّم للعميل» beside a task awaiting delivery: the admin takes it over (when nobody has) and sends it in one press.

    The same two steps as the task page (``acknowledge_handover``, then ``deliver_to_client``), after the page's own «تأكيد».
    The files are the server's choice - the final ones the task page ticks (``final_files``: the leader's corrected version,
    else the translator's) - never ids from the browser. With no final file nothing is taken over and nothing is sent: an empty
    delivery would put the task's title on the client's phone, so the task page is where the files are picked.
    """
    task = get_object_or_404(Task.objects.select_related("client", "team_lead"), code=code)
    user = request.user
    if task.status != TaskStatus.REVIEWED:
        return JsonResponse({"ok": False, "error": NOT_REVIEWED_AR}, status=400)
    files = services.final_files(task)
    if not files:
        return JsonResponse({"ok": False, "error": NO_FINAL_FILES_AR}, status=400)
    if not services.acknowledge_handover(task, user):
        return JsonResponse({"ok": False, "error": NOT_REVIEWED_AR}, status=400)
    ok, delivery, error = services.deliver_to_client(task, user, attachment_ids=[attachment.pk for attachment in files])
    if not ok:
        return JsonResponse({"ok": False, "error": error}, status=400)
    return JsonResponse({"ok": True, "status": delivery.status, "channel": delivery.channel, "files": delivery.file_count})


@endpoint("POST")
@api_role_required(Role.ADMIN)
def delivered_whatsapp(request, code):
    """«تم التسليم واتساب» beside «سلّم للعميل»: the admin already sent it to the client by hand, so the task is closed as delivered.

    Nothing is sent and nothing is asked of the browser; the task only stops waiting. It closes through ``mark_delivered`` like
    every delivery (the translators are priced, the invoice drafted, the room and the people told), with the way it went named
    in the room and in the audit log. Only a task awaiting delivery, as for «سلّم للعميل».
    """
    with transaction.atomic():
        # The bare row is locked (no select_related: Postgres refuses FOR UPDATE on the outer join of a nullable key).
        locked = Task.objects.select_for_update().filter(code=code).first()
        if locked is None:
            raise Http404
        task = Task.objects.select_related("client", "team_lead").get(pk=locked.pk)
        if task.status != TaskStatus.REVIEWED:
            return JsonResponse({"ok": False, "error": NOT_REVIEWED_AR}, status=400)
        if not services.mark_delivered(task, request.user, via="whatsapp"):
            return JsonResponse({"ok": False, "error": NOT_REVIEWED_AR}, status=400)
    return JsonResponse({"ok": True, "status": task.status, "channel": "whatsapp", "files": 0})
