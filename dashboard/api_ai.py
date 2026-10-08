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

The one write is the leader's: they accept some of the notes, or all (``accept``), and each accepted note takes stars off the
translator (``ai.accept_notes``). Nothing is rewritten, and a note costs once.

A GET changes nothing. A task that is not the person's to review is a 404 and a row in the audit log, not a 403 that
would say the code exists.
"""

from django.http import Http404, JsonResponse
from django.shortcuts import get_object_or_404

from . import ai, api, identity, services
from .api_v1 import BadBody, _error, _object, _stamp, endpoint
from .models import AICheckResult, AppSettings, Role, Task, User
from .permissions import api_role_required

#: Most serious first, as the classic box lists them; a note with no severity is a medium one.
SEVERITY_RANK = {"high": 0, "medium": 1, "low": 2}
SEVERITIES = tuple(SEVERITY_RANK)
#: Most notes a panel or a card lists: a check that found more than this is a check to read in the files.
MAX_ISSUES = 50


def _both(ar, en):
    """The two spellings of a text, each falling back to the other (a check from before the English one has only one)."""
    return {"ar": ar or en or "", "en": en or ar or ""}


def _issue_json(issue, task, viewer, position=None, accepted=()):
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
        # The leader accepted it already: it took stars off the translator and is not accepted twice.
        "accepted": position in accepted,
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
    accepted = set((check.accepted or []) if check else [])
    return [_issue_json(one, task, viewer, place, accepted) for place, one in issues[:MAX_ISSUES]]


def _may_review(task, user):
    """The two who read the box: the admin, and the leader of this task."""
    return user.is_admin_role or task.team_lead_id == user.id


def _checked(task, check):
    """The translator a check judged: the one it names (nobody, when it names none)."""
    return check.translator if check is not None and check.translator_id else None


def _entry(task, check, user, conf):
    """One check as the box draws it, with what accepting its notes would cost and whom: the same for every translator of a shared task."""
    translator = _checked(task, check)
    return {
        # Can the leader accept notes: there are some left that were not accepted, and somebody is there to lose the stars for them.
        "can_accept": bool(
            check is not None and check.status == check.Status.ISSUES and translator is not None
            and any(isinstance(one, dict) and place not in (check.accepted or []) for place, one in enumerate(check.issues or []))
        ),
        # What accepting costs, so the button can say it before it is pressed: stars for each note, and whose.
        "accept_cost": {
            "each": f"{conf.penalty_value.normalize():f}",
            "translator": translator.short_name if translator is not None else None,
        },
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
    }


@endpoint("GET")
@api_role_required(Role.TEAM_LEAD)
def task_notes(request, code):
    """The latest check on a task, for the box at the top of its page: ``check`` is ``None`` when none has run yet.

    A task shared between translators is checked once for each of them (07/10/2026), on their own files and their own share of the
    source. The top-level fields are the newest check, as they always were; ``checks`` lists the newest of each translator (only when
    more than one translator has been checked), and the box draws one section for each.
    """
    user = request.user
    task = get_object_or_404(Task.objects.select_related("client"), code=code)
    if not task.can_view(user) or not _may_review(task, user):
        identity.hidden(request, "task")
    conf = AppSettings.load()
    # A translator's own check of their own work is theirs: it does not stand in front of the automatic one in this box.
    reviewed = [one for one in task.ai_checks.select_related("translator").order_by("-created_at", "-id") if not ai.is_self_check(one)]
    check = reviewed[0] if reviewed else None
    running = task.ai_checks.filter(status=AICheckResult.Status.RUNNING).exists()
    newest = {}
    for one in reviewed:
        who = _checked(task, one)
        newest.setdefault(who.pk if who is not None else None, one)
    body = {
        "ok": True,
        "task": {"code": task.code, "title": task.title_for(user)},
        # Can a check be asked for again: the switch is on and the key is there (the classic endpoint says so itself
        # when it is not), and one is not already running.
        "can_recheck": bool(conf.ai_check_enabled and conf.claude_api_key) and not running,
        **_entry(task, check, user, conf),
    }
    if len(newest) > 1:
        body["checks"] = [
            {"translator": {"id": who.pk, "name": who.short_name} if who is not None else None, **_entry(task, one, user, conf)}
            for one in newest.values() for who in [_checked(task, one)]
        ]
    return JsonResponse(body)


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


#: What a refused ``accept_notes`` says, by its word.
ACCEPT_REFUSALS = {"no_notes": 400, "nothing_accepted": 400, "no_translator": 409, "already": 409, "stale_check": 409}


@endpoint("POST")
@api_role_required(Role.TEAM_LEAD)
def accept(request, code):
    """Accept notes: ``{"issues": [ids]}`` or ``{"all": true}``, with the ``check`` the box showed. Each takes stars off the translator.

    The ids are the ``id`` of each note in the box. Only the task's leader and the admin; a task that is not theirs is a 404 and a
    row in the audit log, like the box itself. A note already accepted is not accepted again (``already`` when nothing is left).
    """
    user = request.user
    task = get_object_or_404(Task.objects.select_related("client", "translator"), code=code)
    if not task.can_view(user) or not _may_review(task, user):
        identity.hidden(request, "task")
    if not task.ai_checks.exists():
        return _error(400, "no_notes")
    try:
        body = _object(request)
    except BadBody:
        return _error(400, "bad_body")
    # The ids are places in one check: the one the leader was reading. A newer check (the translator handed in again, somebody asked
    # for it anew) has other notes under the same places, so what was ticked is not accepted on it. On a task shared between translators
    # each has a check of their own, and "newer" means newer for the same translator.
    asked = body.get("check")
    if isinstance(asked, bool) or not isinstance(asked, int):
        return _error(400, "bad_body")
    check = task.ai_checks.filter(pk=asked).first()
    if check is None or ai.is_self_check(check):
        return _error(409, "stale_check")
    newest = next(
        (one for one in task.ai_checks.filter(translator_id=check.translator_id).order_by("-created_at", "-id") if not ai.is_self_check(one)),
        None,
    )
    if newest is None or newest.pk != check.pk:
        return _error(409, "stale_check")
    if body.get("all") is True:
        indexes = [place for place, one in enumerate(check.issues or []) if isinstance(one, dict)][:ai.MAX_ACCEPTED]
    else:
        indexes = ai.accepted_indexes(check, body.get("issues"))
        if indexes is None:
            return _error(400, "bad_body")
    taken, problem = ai.accept_notes(check, user, indexes)
    if problem:
        return _error(ACCEPT_REFUSALS.get(problem, 400), problem)
    return JsonResponse({"ok": True, "taken": f"{taken.normalize():f}"})
