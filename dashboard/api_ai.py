"""``/api/v1/`` - the AI's notes on a translation: the box at the top of a task page, and the panel in a chat.

The notes are *suggestions for the review*, and that decides who may read them. The team leader of the task and the
admin read the whole box on the task page; the team leader alone reads the short panel beside the chat with the
translator who handed the work over (``services.ai_suggestions_for``). The translator keeps the smaller check card they
always had (``api_v1.translator_task``), and nobody else sees either: an automated critique of somebody's work is not
a public correction, so it is never written into a room.

What the AI quotes comes from the client's own files, so its words can carry the client's name. Whoever may not know the
client reads them as ``identity.mask_client`` leaves them (the name becomes the code, contacts are taken out), and the
error of a check that did not finish goes through ``identity.for_viewer``. Nothing here changes a translation or runs a
check: running one again is the classic endpoint (``api.ai_recheck``), which keeps its own refusals.

The one write is the leader's: they accept some of the notes, or all, and a second file is made with those corrections applied
(``revise``, ``ai.start_revision``). The translator's file is never touched, and the copy is opened by the task's leader and the
admin only (``files.may_open``).

A GET changes nothing. A task that is not the person's to review is a 404 and a row in the audit log, not a 403 that
would say the code exists.
"""

from django.http import Http404, JsonResponse
from django.shortcuts import get_object_or_404

from . import ai, api, identity, services
from .api_v1 import BadBody, _error, _object, _stamp, endpoint
from .models import AIRevision, AppSettings, Role, Task, User
from .permissions import api_role_required

#: Most serious first, as the classic box lists them; a note with no severity is a medium one.
SEVERITY_RANK = {"high": 0, "medium": 1, "low": 2}
SEVERITIES = tuple(SEVERITY_RANK)
#: Most notes a panel or a card lists: a check that found more than this is a check to read in the files.
MAX_ISSUES = 50
#: Most corrected copies the box lists for one check.
MAX_REVISIONS = 5


def _both(ar, en):
    """The two spellings of a text, each falling back to the other (a check from before the English one has only one)."""
    return {"ar": ar or en or "", "en": en or ar or ""}


def _issue_json(issue, task, viewer, position=None):
    """One note, as the box and the panel draw it. Every free text passes through the mask for this reader.

    ``id`` is the note's place in the check (the list is shown most serious first, so the place on the screen is not it): what
    the leader sends back to say which notes they accept.
    """

    def words(value):
        return identity.mask_client(value if isinstance(value, str) else "", task.client, viewer)

    severity = issue.get("severity")
    # The chat's panel used to read ``issue``, which only a check from before 28/09/2026 has: the new format says it twice, once
    # in each language (``issue_ar`` / ``issue_en``). All three are read, so a check of either age says something.
    ar = words(issue.get("issue_ar") or issue.get("issue"))
    en = words(issue.get("issue_en") or issue.get("issue"))
    category = (issue.get("category_ar"), issue.get("category_en"))
    return {
        "id": position,
        "severity": severity if severity in SEVERITIES else "medium",
        "location": words(issue.get("location")),
        "category": _both(words(category[0]), words(category[1])) if any(category) else None,
        "source": words(issue.get("source_excerpt")),
        "translation": words(issue.get("translation_excerpt")),
        # A note from a check that quoted the two texts and one that did not: only the first can say what is missing.
        "compared": "source_excerpt" in issue or "translation_excerpt" in issue,
        "text": _both(ar, en),
        "meaning": words(issue.get("correct_meaning_ar")),
    }


def _issues_json(check, task, viewer):
    issues = [(place, one) for place, one in enumerate((check.issues or []) if check else []) if isinstance(one, dict)]
    issues.sort(key=lambda pair: SEVERITY_RANK.get(pair[1].get("severity"), 1))
    return [_issue_json(one, task, viewer, place) for place, one in issues[:MAX_ISSUES]]


def _revision_json(row, viewer):
    done = row.status == AIRevision.Status.DONE and bool(row.file)
    # A copy that has been "running" for ever lost its process: it is shown as failed, so the box does not wait for a file that will
    # not come (the next press writes it down as such).
    status = AIRevision.Status.ERROR if row.is_stale else row.status
    return {
        "id": row.pk,
        "status": status,
        "accepted": list(row.accepted or []),
        "at": _stamp(row.created_at, "%m-%d"),
        "error": identity.for_viewer(row.error_message or "The file was not made.", viewer) if status == AIRevision.Status.ERROR else "",
        "file": {"url": row.file.url, "name": row.original_name, "size": row.size} if done else None,
    }


def _may_review(task, user):
    """The two who read the box: the admin, and the leader of this task."""
    return user.is_admin_role or task.team_lead_id == user.id


@endpoint("GET")
@api_role_required(Role.TEAM_LEAD)
def task_notes(request, code):
    """The latest check on a task, for the box at the top of its page: ``check`` is ``None`` when none has run yet."""
    user = request.user
    task = get_object_or_404(Task.objects.select_related("client"), code=code)
    if not task.can_view(user) or not _may_review(task, user):
        identity.hidden(request, "task")
    conf = AppSettings.load()
    check = task.ai_checks.order_by("-created_at", "-id").first()
    running = check is not None and check.status == check.Status.RUNNING
    revisions = list(check.revisions.all()[:MAX_REVISIONS]) if check is not None else []
    return JsonResponse({
        "ok": True,
        "task": {"code": task.code, "title": task.title_for(user)},
        # Can a check be asked for again: the switch is on and the key is there (the classic endpoint says so itself
        # when it is not), and one is not already running.
        "can_recheck": bool(conf.ai_check_enabled and conf.claude_api_key) and not running,
        # Can the leader accept notes and have a corrected copy made: there are notes, the switch is on, and none is being made.
        "can_revise": bool(
            conf.ai_check_enabled and conf.claude_api_key and check is not None and check.status == check.Status.ISSUES
            and not any(row.status == AIRevision.Status.RUNNING and not row.is_stale for row in revisions)
        ),
        "revisions": [_revision_json(row, user) for row in revisions],
        "check": None if check is None else {
            "id": check.pk,
            "status": check.status,
            "count": check.issue_count,
            "at": _stamp(check.created_at, "%m-%d"),
            # Nobody asked for it: it ran by itself when the translator handed the work over.
            "automatic": check.requested_by_id is None,
            # A check from before the side-by-side comparison: worth running again.
            "old": ai.is_old_format(check),
            "summary": identity.mask_client(check.summary or "", task.client, user),
            "error": identity.for_viewer(check.error_message or "", user) if check.status == check.Status.ERROR else "",
        },
        "issues": _issues_json(check, task, user),
    })


def _panel_json(notes, user):
    """What ``services.ai_suggestions_for`` found, as the panel draws it; ``None`` when there is nothing to show."""
    if notes is None:
        return {"ok": True, "notes": None}
    task, check = notes["task"], notes["result"]
    return {
        "ok": True,
        "notes": {
            "task": {"code": task.code, "title": task.title_for(user)},
            "count": check.issue_count,
            "issues": _issues_json(check, task, user),
        },
    }


@endpoint("GET")
@api_role_required(Role.TEAM_LEAD)
def group_notes(request, room_id):
    """The panel beside a leader's work group with one translator: the notes on what that translator handed over.

    The same room the group's thread door opens (``api._group_or_404``: a room that is not theirs is a 404 and a row in the
    audit log) and the same conditions the classic page uses: a leader's own work group, with exactly one translator in it.
    """
    user = request.user
    room = api._group_or_404(request, room_id)
    translators = [member for member in room.members.all() if member.is_translator]
    if not (room.is_team_group and user.is_team_lead and len(translators) == 1):
        return JsonResponse({"ok": True, "notes": None})
    return JsonResponse(_panel_json(services.ai_suggestions_for(user, translators[0]), user))


@endpoint("GET")
@api_role_required(Role.TEAM_LEAD)
def staff_notes(request, user_id):
    """The panel beside a leader's one-to-one chat with a colleague: the notes on what that colleague handed over.

    Asked about a person, not a room (the room need not exist yet, and a GET opens none). A colleague who is not an active
    user, or is the leader themself, is a 404 as on the chat's own door.
    """
    user = request.user
    other = User.objects.filter(pk=user_id, is_active=True).exclude(pk=user.pk).first()
    if other is None:
        raise Http404
    return JsonResponse(_panel_json(services.ai_suggestions_for(user, other), user))


#: What a refused ``start_revision`` says, by its word.
REVISE_REFUSALS = {"off": 400, "no_notes": 400, "nothing_accepted": 400, "running": 409, "limit": 409, "stale_check": 409}


@endpoint("POST")
@api_role_required(Role.TEAM_LEAD)
def revise(request, code):
    """Accept notes and have a corrected copy of the translation made: ``{"issues": [ids]}`` or ``{"all": true}`` (and the ``check`` the box showed).

    The ids are the ``id`` of each note in the box. The copy is made in the background (the box follows it) and is a new file:
    the translator's own is never changed. Only the task's leader and the admin; a task that is not theirs is a 404 and a row in
    the audit log, like the box itself.
    """
    user = request.user
    task = get_object_or_404(Task.objects.select_related("client"), code=code)
    if not task.can_view(user) or not _may_review(task, user):
        identity.hidden(request, "task")
    check = task.ai_checks.order_by("-created_at", "-id").first()
    if check is None:
        return _error(400, "no_notes")
    try:
        body = _object(request)
    except BadBody:
        return _error(400, "bad_body")
    # The ids are places in one check: the one the leader was reading. A newer check (the translator handed in again, somebody asked
    # for it anew) has other notes under the same places, so what was ticked is not applied to it.
    asked = body.get("check")
    if isinstance(asked, bool) or not isinstance(asked, int):
        return _error(400, "bad_body")
    if asked != check.pk:
        return _error(409, "stale_check")
    if body.get("all") is True:
        indexes = [place for place, one in enumerate(check.issues or []) if isinstance(one, dict)][:ai.MAX_ACCEPTED]
    else:
        indexes = ai.accepted_indexes(check, body.get("issues"))
        if indexes is None:
            return _error(400, "bad_body")
    row, problem = ai.start_revision(check, user, indexes)
    if problem:
        return _error(REVISE_REFUSALS.get(problem, 400), problem)
    services.log(user, "task.ai_revision", task.code, f"{len(indexes)} note(s)")
    return JsonResponse({"ok": True, "revision": _revision_json(row, user)})
