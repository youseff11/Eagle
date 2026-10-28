"""``/api/v1/ai-review/`` - the team leader's own documents, sent to the AI to be checked (``doc_review``).

A leader (or the admin) uploads the source and the translation, one file or several of each, and reads the notes back on the same
page. Nothing is tied to a task, a client or a translator, so there is nothing to mask and no stars ride on a note. The checks are the
person's own: another person's is a 404, and the admin reads only the ones they sent themselves. The files are not kept, only their
names.

A GET changes nothing and reads no file. The one write that carries files is the send, which reads each file once.
"""

from django.http import Http404, JsonResponse

from . import api_ai, doc_review
from .api_v1 import _error, _stamp, endpoint
from .models import DocumentCheck, Role
from .permissions import api_role_required

#: Most past checks the list shows.
LIST_LIMIT = 30


def _row_json(row):
    return {
        "id": row.pk,
        "status": row.status,
        "count": row.issue_count,
        "at": _stamp(row.created_at, "%m-%d"),
        "source_names": row.source_names or [],
        "target_names": row.target_names or [],
    }


@endpoint("GET")
@api_role_required(Role.TEAM_LEAD)
def board(request):
    """The page's start: whether the check is there at all, the limits, and the person's recent checks."""
    user = request.user
    doc_review.close_stale()
    rows = DocumentCheck.objects.filter(created_by=user)[:LIST_LIMIT]
    return JsonResponse({
        "ok": True,
        "available": doc_review.available(),
        "running": doc_review.running(user) is not None,
        "limits": {"files": doc_review.MAX_FILES, "megabytes": doc_review.MAX_FILE_BYTES // (1024 * 1024)},
        "checks": [_row_json(row) for row in rows],
    })


@endpoint("GET")
@api_role_required(Role.TEAM_LEAD)
def detail(request, pk):
    """One check with its notes, most serious first. A check that is not the person's is a 404."""
    user = request.user
    doc_review.close_stale()
    row = DocumentCheck.objects.filter(pk=pk, created_by=user).first()
    if row is None:
        raise Http404
    return JsonResponse({
        "ok": True,
        "check": {
            **_row_json(row),
            "source_lang": row.source_lang,
            "target_lang": row.target_lang,
            "instructions": row.instructions,
            "skipped": row.skipped or [],
            "summary": row.summary or "",
            "error": row.error_message if row.status == DocumentCheck.Status.ERROR else "",
        },
        "issues": _issues(row, user),
    })


def _issues(row, user):
    issues = [(place, one) for place, one in enumerate(row.issues or []) if isinstance(one, dict)]
    issues.sort(key=lambda pair: api_ai.SEVERITY_RANK.get(pair[1].get("severity"), 1))
    return [api_ai._issue_json(one, None, user, place) for place, one in issues[:api_ai.MAX_ISSUES]]


def _files(request, field):
    """``(name, bytes)`` for each file sent under ``field``; the sizes are checked before anything is read."""
    sent = request.FILES.getlist(field)
    if len(sent) > doc_review.MAX_FILES:
        raise doc_review.Problem("too_many_files")
    if any(one.size > doc_review.MAX_FILE_BYTES for one in sent):
        raise doc_review.Problem("too_big")
    return [(one.name, one.read()) for one in sent]


@endpoint("POST")
@api_role_required(Role.TEAM_LEAD)
def send(request):
    """Send the files: ``source`` and ``target`` (files, several of each), and ``source_lang``, ``target_lang`` and ``instructions`` (text,
    all optional). The answer comes at once and the notes later: the page follows the check. A refusal is a 400 (a 403 for who may not
    ask) with the reason in the leader's words (``error``) and its ``code``."""
    try:
        row = doc_review.start(
            request.user, _files(request, "source"), _files(request, "target"),
            request.POST.get("source_lang", ""), request.POST.get("target_lang", ""), request.POST.get("instructions", ""),
        )
    except doc_review.Problem as refused:
        return JsonResponse({"ok": False, "error": refused.text, "code": refused.code}, status=403 if refused.code == "forbidden" else 400)
    return JsonResponse({"ok": True, "id": row.pk})


@endpoint("POST")
@api_role_required(Role.TEAM_LEAD)
def remove(request, pk):
    """Take one of the person's checks off their page. A check still running cannot go (its answer would have nowhere to land)."""
    row = DocumentCheck.objects.filter(pk=pk, created_by=request.user).first()
    if row is None:
        raise Http404
    if row.status == DocumentCheck.Status.RUNNING:
        return _error(409, "running")
    row.delete()
    return JsonResponse({"ok": True})
