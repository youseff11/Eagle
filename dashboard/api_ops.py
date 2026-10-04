"""``/api/v1/`` - the operation's screen (phase 5, screen 4): the task list, the team board, the task page.

The same layer, the same rules as ``api_v1``: JSON for everything, a GET changes nothing, a refusal is a 403 and
what you may not open is a 404 with a row in the audit log, every answer is ``private, no-store``. The operation's
pages answer to ``Role.OPERATION`` and the admin, as the classic pages do (``role_required``). What is written is
written where it always was - the classic endpoints (assign, hand over, deliver, deadline, cancel) - and the pages
that were redirects with a flash message (the word count, a requirement) and the task form get a door of their own,
so a front end can read what happened.
"""

from django.http import JsonResponse
from django.shortcuts import get_object_or_404

from . import api, identity, services, taskstart, wordcount
from .api_v1 import (
    BadBody, BadIds, _clean_id, _error, _kind_json, _list, _object, _origin_json, _stamp, _status_json, _task_file_json,
    _text, _two, endpoint,
)
from .forms import QUICK_LANGUAGES, RequirementForm, TaskForm, language_choices
from .models import (
    ACTIVE_TASK_STATUSES, AppSettings, ChatAttachment, Client, Priority, Role, RoomKind, Task, TaskStatus, User,
)
from .permissions import api_role_required
from .templatetags.eagle_tags import PRIORITY_MAP

#: The most rows a list answers with: the classic page's own limit.
MAX_TASKS = 200
#: A word count nobody means (a database column holds less, and a typo of a few digits more would be paid for).
MAX_WORDS = 10_000_000
#: How long a requirement may be: a note about a client, not a document.
MAX_REQUIREMENT = 2000


# ---------------------------------------------------------------------------
# The task list
# ---------------------------------------------------------------------------

def _task_counters():
    """The four numbers over the list: what the classic page counts, by the same rules."""
    return {
        "new": Task.objects.filter(status=TaskStatus.NEW).count(),
        "open": Task.objects.filter(status__in=ACTIVE_TASK_STATUSES).count(),
        "review": Task.objects.filter(status=TaskStatus.UNDER_REVIEW).count(),
        "ready": Task.objects.filter(status=TaskStatus.REVIEWED).count(),
    }


def _list_row(task, user, warning_minutes):
    """One row of the list as the classic table draws it.

    The date is the client's, because the operation answers for the promise (``deadline_for``); the client is
    ``label_for`` (a code for the operation, the name for the admin who may know it).
    """
    due = task.deadline_for(user)
    return {
        "code": task.code,
        "title": task.title_for(user),
        "origin": _origin_json(task.origin),
        "priority": _two(PRIORITY_MAP, task.priority),
        "client": task.client.label_for(user) if task.client_id else "-",
        "status": _status_json(task.status),
        "team_lead": task.team_lead.short_name if task.team_lead_id else None,
        "translator": task.translator.short_name if task.translator_id else None,
        "due": _stamp(due, "%m-%d"),
        "due_state": task.deadline_state(user, warning_minutes),
    }


@endpoint("GET")
@api_role_required(Role.OPERATION)
def tasks(request):
    """The tasks, newest first: ``?status=open`` or one status; nothing for all (the newest 200).

    ``counters`` are over every task, not over the page, as on the classic page. A status that is not one is a 400,
    not an empty list: a typo would otherwise look like "no tasks".
    """
    user = request.user
    status = request.GET.get("status", "")
    if status and status != "open" and status not in TaskStatus.values:
        return _error(400, "bad_status")
    rows = Task.objects.select_related("client", "team_lead", "translator")
    if status == "open":
        rows = rows.filter(status__in=ACTIVE_TASK_STATUSES)
    elif status:
        rows = rows.filter(status=status)
    warning = AppSettings.load().deadline_warning_minutes
    return JsonResponse({
        "ok": True,
        "status": status,
        "counters": _task_counters(),
        "statuses": [_status_json(value) for value, _label in TaskStatus.choices],
        "tasks": [_list_row(task, user, warning) for task in rows[:MAX_TASKS]],
    })


# ---------------------------------------------------------------------------
# The team board
# ---------------------------------------------------------------------------

def _seen_json(person):
    seconds = person.seconds_since_seen
    return {
        "ar": api._seen_label(seconds, person.last_seen, "ar"),
        "en": api._seen_label(seconds, person.last_seen, "en"),
    }


@endpoint("GET")
@api_role_required(Role.OPERATION)
def team(request):
    """The team leaders and who works under each: who is free, who is busy, who is offline, and with what.

    ``services.team_overview`` is the classic page's own function, so the two cannot disagree about who is free.
    A person's task codes are the two the classic table shows. Nobody here is a client; nothing in the answer reads
    one but the task code.
    """
    rows = services.team_overview()
    members = [m for row in rows for m in row["members"]]
    # One question for everybody's open tasks, instead of one per person.
    tasks_of = {}
    for task in (
        Task.objects.filter(status__in=ACTIVE_TASK_STATUSES, translator__in=members).order_by("deadline", "code")
    ):
        tasks_of.setdefault(task.translator_id, []).append(task.code)

    def member_json(member):
        busy = member.pk in tasks_of
        if not member.is_online:
            state = "shift" if member.on_shift else "off"
        else:
            state = "busy" if busy else "free"
        return {
            "id": member.pk,
            "name": member.short_name,
            "initials": member.initials,
            "languages": member.languages,
            "state": state,
            "seen": _seen_json(member),
            "rating": float(member.rating),
            "tasks": tasks_of.get(member.pk, [])[:2],
        }

    return JsonResponse({
        "ok": True,
        "leads": [
            {
                "id": row["lead"].pk,
                "name": row["lead"].short_name,
                "initials": row["lead"].initials,
                "online": row["online"],
                "rating": float(row["lead"].rating),
                "tasks": row["lead_tasks"],
                "counts": {"free": len(row["free"]), "busy": len(row["busy"]), "offline": len(row["offline"])},
                "members": [member_json(m) for m in row["members"]],
            }
            for row in rows
        ],
    })


# ---------------------------------------------------------------------------
# One task, as the operation reads it
# ---------------------------------------------------------------------------

def _leads_json():
    """The team leaders a new task can be sent to, with who is here and how loaded each is."""
    return [
        {"id": lead.pk, "name": lead.short_name, "online": lead.is_online, "tasks": lead.active_task_count}
        for lead in User.objects.filter(role=Role.TEAM_LEAD, is_active=True).prefetch_related("shifts")
    ]


def _deliverables_json(task):
    """The files the operation may send to the client, the translator's own ticked.

    A voice note is talk, not a translation: offered and ticked as final, a private word to the leader would be
    one click from the client's phone (``views.task_detail`` leaves them out the same way).
    """
    rows = (
        ChatAttachment.objects.filter(services.task_files_filter(task))
        .select_related("message", "message__sender").order_by("-id")[:40]
    )
    out = []
    for attachment in rows:
        if attachment.is_audio:
            continue
        sender = attachment.message.sender
        out.append({
            "id": attachment.pk,
            "name": attachment.original_name or attachment.file.name.rsplit("/", 1)[-1],
            "size": attachment.pretty_size,
            "sender": sender.short_name if sender else None,
            "final": bool(task.translator_id and sender and sender.pk == task.translator_id),
        })
    return out


def _requirement_json(requirement, client, viewer):
    """A thing the client likes, dislikes or insists on. The words are typed by people who write the client's name in
    them, so whoever may not know it reads the code in its place (``identity.mask_client``)."""
    return {
        "id": requirement.pk,
        "kind": _kind_json(requirement.kind),
        "author": requirement.author.short_name if requirement.author_id else None,
        "text": identity.mask_client(requirement.text, client, viewer),
    }


def _lead_json(task, user):
    """What the task's team leader (and the admin) may do on it, or ``None`` for everybody else.

    Giving it to a translator and changing that translator's date are the classic endpoints
    (``api.assign_translator``, ``api.set_translator_deadline``), which check the team and the status again; the
    translators offered are the leader's own (the admin: the task's leader's), each with whether they are free now.
    A request for more time waits for this person's yes or no (``services.decide_extension``).
    """
    if not (user.is_team_lead or user.is_admin_role):
        return None
    if user.is_team_lead and not user.is_admin_role and task.team_lead_id != user.id:
        return None
    can_assign = task.status in (TaskStatus.LEAD_ACCEPTED, TaskStatus.AWAITING_TRANSLATOR)
    translators = []
    lead_id = user.pk if user.is_team_lead and not user.is_admin_role else task.team_lead_id
    if can_assign and lead_id:
        for person in User.objects.filter(role=Role.TRANSLATOR, is_active=True, team_lead_id=lead_id).prefetch_related("shifts"):
            translators.append({
                "id": person.pk,
                "name": person.short_name,
                "state": "off" if not person.is_online else "busy" if person.is_busy else "free",
                "rating": float(person.rating),
            })
    state = services.extension_state(task, user)
    pending = state.get("extension_pending") if state.get("extension_can_decide") else None
    return {
        "can_assign": can_assign,
        "translators": translators,
        "can_set_translator_deadline": bool(task.translator_id),
        "can_review": task.status == TaskStatus.UNDER_REVIEW,
        "client_due": _stamp(task.deadline, "%Y-%m-%d"),
        "extension": {
            "id": pending.pk,
            "length": pending.pretty_length,
            "reason": identity.mask_client(pending.reason or "", task.client, user),
            "new_due": _stamp(state.get("extension_new_due"), "%Y-%m-%d"),
        } if pending else None,
    }


@endpoint("GET")
@api_role_required(Role.OPERATION, Role.TEAM_LEAD)
def task(request, code):
    """One task as the operation reads it: the page ``/tasks/<code>/`` without the translator's tools.

    The team leader of the task reads the same page (``Task.can_view``: a task that is not theirs is a 404 and a row
    in the audit log) with the operation's own tools left out - taking it over, delivering it, cancelling it, the
    client's own messages and the way to the client's conversation - and their own added: ``lead`` says what they may
    do (give it to a translator, change that translator's date, answer a request for more time, finish the review).
    The admin gets both sets, as on the classic page.

    Everything the operation does on the page is here to be drawn - who the task can go to, whether it waits for
    somebody to take it over, what would be sent to the client and over which channel - and everything it does is
    a classic endpoint that checks it again. The client is ``label_for`` (a code for the operation); the client's
    own messages are the ones this person may read (``visible_to``: their line, the rate rule), and the words of a
    failed delivery lose any number or address (``for_viewer``) before anybody who may not know it reads them.
    """
    task = get_object_or_404(
        Task.objects.select_related("client", "team_lead", "translator", "created_by", "handover_ack_by"), code=code,
    )
    user = request.user
    if not task.can_view(user):
        identity.hidden(request, "task")
    conf = AppSettings.load()
    due = task.deadline_for(user)
    pending = task.pending_assignment
    # The operation's tools are the operation's and the admin's: a leader reads the task, and does not take it over,
    # deliver it, cancel it or talk to the client from here.
    ops = user.is_operation or user.is_admin_role
    new = task.status == TaskStatus.NEW and ops
    waiting = task.status == TaskStatus.REVIEWED and not task.handover_ack_at and ops
    taken = task.status == TaskStatus.REVIEWED and bool(task.handover_ack_at) and ops
    group = task.rooms.filter(kind=RoomKind.GROUP).first()

    return JsonResponse({
        "ok": True,
        "task": {
            "code": task.code,
            "title": task.title_for(user),
            "status": _status_json(task.status),
            "priority": _two(PRIORITY_MAP, task.priority),
            "origin": _origin_json(task.origin),
            "client": task.client.label_for(user) if task.client_id else "-",
            "client_code": task.client.code if task.client_id else "",
            "source_lang": task.source_lang,
            "target_lang": task.target_lang,
            "due": _stamp(due, "%Y-%m-%d"),
            "due_state": task.deadline_state(user, conf.deadline_warning_minutes),
            # What the translator was given: the leader keeps the difference to review in.
            "translator_due": _stamp(task.translator_deadline, "%m-%d"),
            # Typed by the operation, who writes the client's name in it: whoever may not know it reads the code.
            "description": identity.mask_client(services.clean_client_text(task.description), task.client, user),
            "people": {
                "operation": task.created_by.short_name if task.created_by_id else None,
                "team_lead": task.team_lead.short_name if task.team_lead_id else None,
                "translator": task.translator.short_name if task.translator_id else None,
            },
            "waiting_for": (
                {"name": pending.assignee.short_name, "seconds_left": pending.seconds_left} if pending else None
            ),
            "files": {
                "original": [_task_file_json(a) for a in services.task_source_files(task)],
                "translation": [
                    dict(_task_file_json(a), at=_stamp(a.message.created_at, "%m-%d"))
                    for a in services.translator_files(task)
                ],
            },
            "chat": services.task_chat_link(task, user),
            "client_chat_url": f"/ops/chats/{task.client.code}/" if task.client_id and ops else None,
            "can": {
                "assign_lead": new,
                "take_over": waiting,
                "deliver": taken,
                "cancel": not task.is_done and ops,
                "add_member": user.is_admin_role and group is not None,
                # The same material, a new job: the operation's own (it makes tasks).
                "new_request": ops,
                # The client's date is promised by the operation; the leader's own is the translator's (``lead``).
                "set_deadline": ops,
                # The people who see both the client's file and the translator's, never the translator.
                "set_words": ops or task.team_lead_id == user.id,
            },
            "lead": _lead_json(task, user),
            "leads": _leads_json() if new else [],
            "handover": {
                "by": task.handover_ack_by.short_name if task.handover_ack_by_id else None,
                "at": _stamp(task.handover_ack_at, "%m-%d"),
            } if taken else None,
            "deliver": {
                "files": _deliverables_json(task),
                "channel": services.client_channel(task.client),
                "reachable": bool(task.client.all_phones or task.client.all_emails),
            } if taken else None,
            "group_candidates": [
                {"id": person.pk, "name": person.short_name, "role": person.role}
                for person in User.objects.filter(is_active=True, role__in=(Role.OPERATION, Role.TEAM_LEAD))
                .exclude(pk__in=group.members.values("pk"))
            ] if user.is_admin_role and group is not None else [],
            "words": {
                "state": task.word_count_state,
                "value": task.word_count if task.word_count_state == "confirmed" else None,
            },
            "requirements": [_requirement_json(r, task.client, user) for r in task.client.requirements.select_related("author")],
            "deliveries": [
                {
                    "id": d.pk, "at": _stamp(d.created_at, "%m-%d"), "channel": d.channel, "files": d.file_count,
                    "by": d.created_by.short_name if d.created_by_id else None, "status": d.status,
                    "error": identity.for_viewer(d.error_message, user),
                }
                for d in task.deliveries.select_related("created_by")[:5]
            ],
            "messages": [
                {
                    "id": m.pk, "channel": m.channel, "at": _stamp(m.received_at, "%m-%d"),
                    "body": services.clean_client_text(m.body)[:220],
                    "files": [_task_file_json(a) for a in m.attachments.all()],
                }
                for m in services.task_inbounds(task).prefetch_related("attachments").order_by("received_at", "id")
                if m.visible_to(user)
            ] if ops else [],
            "history": [
                {
                    "id": a.pk, "name": a.assignee.short_name, "initials": a.assignee.initials, "role": a.target_role,
                    "at": _stamp(a.assigned_at, "%m-%d"), "status": a.status,
                }
                for a in task.assignments.select_related("assignee")[:20]
            ],
        },
    })


@endpoint("POST")
@api_role_required(Role.OPERATION, Role.TEAM_LEAD)
def task_words(request, code):
    """Settle the word count by hand - the only way it is set. ``{"words": 3000}``.

    The translator uploads the file their own bonus is measured from, so they are the one role that cannot settle
    the number (this door is the operation's and the admin's). A number that is not a whole count is a 400 and
    nothing is written: the classic page flashed "type a number" and went back.
    """
    task = get_object_or_404(Task, code=code)
    # The operation, the admin and the task's own team leader (``can_view``: a leader's own tasks only).
    if not task.can_view(request.user):
        identity.hidden(request, "task")
    try:
        body = _object(request)
    except BadBody:
        return _error(400, "bad_request")
    words = body.get("words")
    if isinstance(words, bool) or not isinstance(words, int) or not 0 <= words <= MAX_WORDS:
        return _error(400, "bad_words")
    wordcount.confirm_task(task, request.user, words=words)
    return JsonResponse({"ok": True, "words": task.word_count, "state": task.word_count_state})


@endpoint("POST")
@api_role_required(Role.OPERATION, Role.TEAM_LEAD)
def task_requirement(request, code):
    """Add a thing the client likes, dislikes or insists on. ``{"kind": "rule", "text": "..."}``.

    The same form the classic page posts (``RequirementForm``), and the same audit row; what is new is that the
    answer is the row, so a page can show it without a reload.
    """
    task = get_object_or_404(Task.objects.select_related("client"), code=code)
    if not task.can_view(request.user):
        identity.hidden(request, "task")
    try:
        body = _object(request)
        kind, text = _text(body, "kind", 20), _text(body, "text", MAX_REQUIREMENT)
    except BadBody:
        return _error(400, "bad_request")
    form = RequirementForm({"kind": kind, "text": text})
    if not form.is_valid():
        return JsonResponse({"ok": False, "error": "bad_requirement", "fields": sorted(form.errors)}, status=400)
    row = form.save(commit=False)
    row.client = task.client
    row.author = request.user
    row.save()
    services.log(request.user, "client.requirement", task.client.code, row.text[:80])
    return JsonResponse({"ok": True, "requirement": _requirement_json(row, task.client, request.user)})


# ---------------------------------------------------------------------------
# Starting a task
# ---------------------------------------------------------------------------

#: How many ids an address may carry (messages, files): a run of a client's messages, not a dump.
MAX_START_IDS = 200


def _start_ids(request, *names):
    """The ids named in the address (repeated or comma-joined), as the strings ``taskstart`` reads; ``None`` if too many."""
    raw = []
    for name in names:
        raw += request.GET.getlist(name)
    if sum(len(value) for value in raw) > 2000 or len(raw) > MAX_START_IDS:
        return None
    if len(taskstart.ids(raw)) > MAX_START_IDS:
        return None
    return raw


def _start_json(start, user):
    """What the form shows beside its boxes: the messages the task is made from, the files that will go, the rules."""
    message = start.message
    client = message.client if message else start.from_task.client if start.from_task else None
    return {
        "from_task": {"code": start.from_task.code, "title": start.from_task.title_for(user)} if start.from_task else None,
        "client_code": message.client.code if message else (start.from_task.client.code if start.from_task else ""),
        "messages": [
            {
                "id": m.pk, "channel": m.channel, "at": _stamp(m.received_at, "%d/%m"), "subject": m.subject,
                "body": services.clean_client_text(m.body),
                "files": [_task_file_json(a) for a in m.attachments.all()],
            }
            for m in start.messages
        ],
        "picked": [_task_file_json(a) for a in start.picked],
        "initial": {
            "client": start.initial.get("client"),
            # Typed by the client first (their subject, their opening words) or by a colleague who knew their name: the same
            # words the task page shows, masked the same way, so the form does not hand over what the page keeps back.
            "title": identity.mask_client(start.initial.get("title", ""), client, user),
            "description": identity.mask_client(start.initial.get("description", ""), client, user),
            "source_lang": start.initial.get("source_lang", ""),
        },
        "requirements": [
            _requirement_json(r, client, user) for r in client.requirements.select_related("author")
        ] if client is not None else [],
    }


@endpoint("GET")
@api_role_required(Role.OPERATION)
def task_start(request):
    """What the new-task form starts from: ``?message=``, ``?messages=1,2``, ``?files=3``, ``?from=TSK-00001``.

    Resolved by ``taskstart`` - the classic form's own rules - so a message this person may not read, one of
    another client, or a file that is not on those messages finds nothing and is not offered. Nothing is written.
    The clients are listed as ``label_for`` gives them: a code for the operation.
    """
    user = request.user
    messages = _start_ids(request, "message", "messages")
    files = _start_ids(request, "files")
    if messages is None or files is None:
        return _error(400, "too_many")
    source = request.GET.get("from", "")
    if len(source) > 40 or "\x00" in source:
        return _error(400, "bad_request")
    start = taskstart.resolve(user, message_ids=messages, file_ids=files, from_code=source)
    return JsonResponse({
        "ok": True,
        **_start_json(start, user),
        "clients": [
            {"id": c.pk, "code": c.code, "label": c.label_for(user)}
            for c in Client.objects.filter(is_active=True).order_by("code")
        ],
        "languages": language_choices(),
        "quick_languages": list(QUICK_LANGUAGES),
        "priorities": [_two(PRIORITY_MAP, value) for value, _label in Priority.choices],
    })


#: The boxes the form reads, and the kind of value each takes.
_FORM_TEXT = ("title", "description", "source_lang", "target_lang", "priority")


@endpoint("POST")
@api_role_required(Role.OPERATION)
def task_create(request):
    """Make a task: the form's boxes as JSON, and what it is made from (``messages``, ``files``, ``from``).

    ``{"client": 5, "title": "...", "description": "", "source_lang": "en", "target_lang": "ar", "priority":
    "normal", "deadline": {"days": "3", "hours": "", "minutes": ""}, "word_count": 1200, "is_difficult": false,
    "is_secondary_language": false, "messages": [7], "files": [9], "from": "TSK-00001"}``.

    The boxes go through ``TaskForm`` - the same validation, the same words for what is wrong - so a refusal is a
    400 with the boxes that were wrong (``fields``) and nothing is written. A task made from a client's messages is
    that client's: a form that names another client is refused (``client_mismatch``), which the classic form let by.
    """
    try:
        body = _object(request)
        data = {name: _text(body, name, 20000 if name == "description" else 400) for name in _FORM_TEXT}
        messages = _list(body, "messages", _clean_id)
        files = _list(body, "files", _clean_id)
        source = _text(body, "from", 40)
        client = body.get("client")
        words = body.get("word_count")
        if isinstance(client, bool) or not isinstance(client, int):
            raise BadBody
        if words is not None and (isinstance(words, bool) or not isinstance(words, int) or not 0 <= words <= MAX_WORDS):
            raise BadBody
        deadline = body.get("deadline") or {}
        if not isinstance(deadline, dict):
            raise BadBody
        for part in ("days", "hours", "minutes"):
            value = deadline.get(part, "")
            if isinstance(value, bool) or not isinstance(value, (str, int)) or len(str(value)) > 6:
                raise BadBody
            data[f"deadline_{part}"] = str(value).strip()
    except (BadBody, BadIds):
        return _error(400, "bad_request")
    data["client"] = str(client)
    # The form insists on the box; left empty here it is 0, "not counted yet" - the count is set later, by a person,
    # on the task page, and a task made without one is what a task always was.
    data["word_count"] = str(words or 0)
    for flag in ("is_difficult", "is_secondary_language"):
        if body.get(flag) is True:
            data[flag] = "on"

    form = TaskForm(data)
    if not form.is_valid():
        return JsonResponse({
            "ok": False, "error": "invalid",
            "fields": {name: [str(problem) for problem in problems] for name, problems in form.errors.items()},
        }, status=400)
    start = taskstart.resolve(request.user, message_ids=messages, file_ids=files, from_code=source)
    if start.messages and start.messages[0].client_id != form.cleaned_data["client"].pk:
        return _error(400, "client_mismatch")
    task = taskstart.create(request.user, form.cleaned_data, start)
    return JsonResponse({"ok": True, "code": task.code})
