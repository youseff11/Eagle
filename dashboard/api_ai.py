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

A GET changes nothing. A task that is not the person's to review is a 404 and a row in the audit log, not a 403 that
would say the code exists.
"""

from django.http import Http404, JsonResponse
from django.shortcuts import get_object_or_404

from . import ai, api, identity, services
from .api_v1 import _stamp, endpoint
from .models import AppSettings, Role, Task, User
from .permissions import api_role_required

#: Most serious first, as the classic box lists them; a note with no severity is a medium one.
SEVERITY_RANK = {"high": 0, "medium": 1, "low": 2}
SEVERITIES = tuple(SEVERITY_RANK)
#: Most notes a panel or a card lists: a check that found more than this is a check to read in the files.
MAX_ISSUES = 50


def _both(ar, en):
    """The two spellings of a text, each falling back to the other (a check from before the English one has only one)."""
    return {"ar": ar or en or "", "en": en or ar or ""}


def _issue_json(issue, task, viewer):
    """One note, as the box and the panel draw it. Every free text passes through the mask for this reader."""

    def words(value):
        return identity.mask_client(value if isinstance(value, str) else "", task.client, viewer)

    severity = issue.get("severity")
    # The chat's panel used to read ``issue``, which only a check from before 28/09/2026 has: the new format says it twice, once
    # in each language (``issue_ar`` / ``issue_en``). All three are read, so a check of either age says something.
    ar = words(issue.get("issue_ar") or issue.get("issue"))
    en = words(issue.get("issue_en") or issue.get("issue"))
    category = (issue.get("category_ar"), issue.get("category_en"))
    return {
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
    issues = [one for one in ((check.issues or []) if check else []) if isinstance(one, dict)]
    issues.sort(key=lambda one: SEVERITY_RANK.get(one.get("severity"), 1))
    return [_issue_json(one, task, viewer) for one in issues[:MAX_ISSUES]]


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
    return JsonResponse({
        "ok": True,
        "task": {"code": task.code, "title": task.title_for(user)},
        # Can a check be asked for again: the switch is on and the key is there (the classic endpoint says so itself
        # when it is not), and one is not already running.
        "can_recheck": bool(conf.ai_check_enabled and conf.claude_api_key) and not running,
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
