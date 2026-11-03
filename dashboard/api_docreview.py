"""``/api/v1/ai-review/`` - the team leader's chats with the AI about his own documents (``doc_review``).

A leader (or the admin) opens a session, sends files and writes to the AI, and reads its answers on the same page; he keeps as many
sessions as he likes. Nothing is tied to a task, a client or a translator, so there is nothing to mask and no stars ride on an answer.
The sessions are the person's own: another person's is a 404, and the admin reads only the ones they started themselves.

A GET changes nothing and reads no file. The one write that carries files is the send.
"""

from django.http import Http404, JsonResponse

from . import doc_review, services
from .api_v1 import _error, _stamp, endpoint
from .models import AIReviewSession, Role
from .permissions import api_role_required

#: Most sessions the list shows.
LIST_LIMIT = 100


def _session_json(session, pending):
    return {"id": session.pk, "title": session.title, "at": _stamp(session.updated_at, "%m-%d"), "pending": pending}


def _file_json(row):
    return {
        "id": row.pk,
        "url": row.file.url,
        "name": row.original_name or row.file.name.rsplit("/", 1)[-1],
        "size": row.pretty_size,
        "image": services.is_image(row),
        "label": row.label,
    }


def _message_json(line):
    return {
        "id": line.pk,
        "role": line.role,
        "body": line.body,
        "status": line.status,
        "at": _stamp(line.created_at, ""),
        "files": [_file_json(row) for row in line.files.all()],
    }


def _detail_json(session):
    messages = session.messages.prefetch_related("files")
    return {
        "ok": True,
        "session": _session_json(session, doc_review.pending(session)),
        "messages": [_message_json(line) for line in messages],
    }


def _own(request, pk):
    """The person's own session, or a 404."""
    session = AIReviewSession.objects.filter(pk=pk, owner=request.user).first()
    if session is None:
        raise Http404
    return session


def _refused(refused):
    return JsonResponse({"ok": False, "error": refused.text, "code": refused.code}, status=403 if refused.code == "forbidden" else 400)


@endpoint("GET")
@api_role_required(Role.TEAM_LEAD)
def board(request):
    """The page's start: whether the check is there at all, the limits, and the person's sessions, the newest first."""
    user = request.user
    doc_review.reap(user)
    busy = doc_review.pending_sessions(user)
    sessions = AIReviewSession.objects.filter(owner=user)[:LIST_LIMIT]
    return JsonResponse({
        "ok": True,
        "available": doc_review.available(),
        "limits": {
            "files": doc_review.MAX_FILES, "megabytes": doc_review.MAX_FILE_BYTES // (1024 * 1024),
            "message_megabytes": doc_review.MAX_MESSAGE_BYTES // (1024 * 1024), "text": doc_review.MAX_TEXT,
        },
        "sessions": [_session_json(one, one.pk in busy) for one in sessions],
    })


@endpoint("GET")
@api_role_required(Role.TEAM_LEAD)
def detail(request, pk):
    """One session with its talk, oldest first, and whether an answer is still being written. Asked again by the page while ``pending``."""
    doc_review.reap(request.user)
    return JsonResponse(_detail_json(_own(request, pk)))


@endpoint("POST")
@api_role_required(Role.TEAM_LEAD)
def send(request):
    """A line to the AI: ``text`` and/or ``files`` (several), with ``labels`` (one per file: ``source``, ``translation`` or empty), and
    ``session`` to go on in one of the person's sessions (left out, a new one is opened). The answer comes later: the page follows the
    session. A refusal is a 400 (a 403 for who may not ask) with the reason in the leader's words (``error``) and its ``code``."""
    session = None
    raw = request.POST.get("session", "").strip()
    if raw:
        if not raw.isdigit():
            return _error(400, "bad_session")
        session = _own(request, int(raw))
    try:
        session, _answer = doc_review.send(
            request.user, session, request.POST.get("text", ""), request.FILES.getlist("files"), request.POST.getlist("labels"),
        )
    except doc_review.Problem as refused:
        return _refused(refused)
    return JsonResponse(_detail_json(session))


@endpoint("POST")
@api_role_required(Role.TEAM_LEAD)
def retry(request, pk):
    """Ask again for the answer that failed, with the files that are kept. Answers with the session, like a send."""
    session = _own(request, pk)
    try:
        doc_review.retry(request.user, session)
    except doc_review.Problem as refused:
        return _refused(refused)
    return JsonResponse(_detail_json(session))


@endpoint("POST")
@api_role_required(Role.TEAM_LEAD)
def remove(request, pk):
    """Delete one of the person's sessions with its files. One the AI is still answering in cannot go (409)."""
    session = _own(request, pk)
    try:
        doc_review.remove(session)
    except doc_review.Problem:
        return _error(409, "running")
    return JsonResponse({"ok": True})
