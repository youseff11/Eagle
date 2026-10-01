"""``/api/v1/`` - the JSON the React front end talks to.

A thin, versioned layer over the endpoints the pages already use, not a second
copy of them. Who may read what is decided in one place - ``ChatRoom.can_open``,
``identity``, ``lines`` - and the chat reads below call the same functions the
current pages call, so a rule tightened there tightens here with no second edit.
What this module adds is the contract a single-page app needs and the old pages
never did:

* every answer is JSON, errors included: 401 when nobody is signed in (not a
  redirect to an HTML login page), 404 for what you may not open (a 403 would
  confirm it exists, and ``identity.hidden`` has already written it down),
  403 for a refused action, 405 for the wrong method;
* ``/me/`` hands the page its CSRF cookie, so a front end that was never
  rendered by a Django template can still POST;
* pages of a list are cursors (``before=<id>``), not offsets;
* a GET changes nothing. The old fetch endpoints mark a conversation read when
  asked with ``?read=1`` - and reading a client's conversation sends their phone
  a read receipt - which a link on another site could trigger with the logged-in
  person's own cookie. Here ``read`` is ignored on GET, and reading is a POST
  (CSRF-protected) of its own.

Nothing here returns a client's name, number or address, because nothing here
reads one: names go through ``Client.label_for`` inside the functions reused.
New resources are added screen by screen (phase 5), each with a test that runs
every role against it.
"""

import json
import logging
from functools import wraps

from django.core.exceptions import PermissionDenied
from django.http import Http404, JsonResponse
from django.utils import timezone
from django.views.decorators.csrf import ensure_csrf_cookie

from . import api, clock, identity, newui, services
from .models import AppSettings, ChatRoom, Notification, Role, RoomKind, TaskStatus, User
from .permissions import api_role_required
from .templatetags.eagle_tags import ORIGIN_MAP, PRIORITY_MAP, STATUS_MAP

log = logging.getLogger("dashboard")

VERSION = 1

#: Cursor pages: how many by default, and the most one call may ask for.
PAGE = 20
MAX_PAGE = 50

#: The sidebar lists ``api.client_chat_list`` can serve.
CHAT_TYPES = ("clients", "groups", "staff")

#: Most ids one mark-read call may carry, and the largest id a database column
#: of ours can hold (a bigger one is an error to Postgres, not "no match").
MAX_IDS = 200
MAX_ID = 2 ** 63 - 1

#: How often a page should send ``{"t": "ping"}`` on the socket. The server
#: ignores pings closer than ``consumers.PING_GAP``; the edge drops an idle
#: connection at about 100 seconds.
PING_SECONDS = 25


def _error(status, code):
    return JsonResponse({"ok": False, "error": code}, status=status)


def endpoint(*methods):
    """Method check, sign-in check, and JSON for anything raised below.

    ``PermissionDenied`` is logged here because the project's 403 handler
    (``views.permission_denied``), which logs it everywhere else, would answer
    with an HTML page. So would an unexpected error, and a front end cannot
    parse that: it is logged with its traceback and answered as JSON, without
    the exception text. Every answer is ``private, no-store`` - it is one
    person's data, and no cache in between may hand it to anyone else.
    """

    def decorator(view):
        @wraps(view)
        def wrapper(request, *args, **kwargs):
            if request.method not in methods:
                response = _error(405, "method_not_allowed")
                response["Allow"] = ", ".join(methods)
            elif not request.user.is_authenticated:
                response = _error(401, "auth")
            else:
                try:
                    response = view(request, *args, **kwargs)
                except Http404:
                    response = _error(404, "not_found")
                except PermissionDenied as refusal:
                    identity.record_denied(request, str(refusal)[:200] or "permission denied")
                    response = _error(403, "forbidden")
                except Exception:  # noqa: BLE001 - see the docstring
                    log.exception("api v1: %s failed", view.__name__)
                    response = _error(500, "server")
            response["Cache-Control"] = "private, no-store"
            return response

        return wrapper

    return decorator


def not_found(request, *args, **kwargs):
    """Anything else under ``/api/v1/``: JSON, never the HTML 404 page."""
    response = _error(404, "not_found")
    response["Cache-Control"] = "private, no-store"
    return response


class BadIds(ValueError):
    """The ``ids`` a client sent are not a short list of database ids."""


def _clean_id(value):
    if isinstance(value, (bool, float)):
        raise BadIds
    try:
        number = int(value)
    except (TypeError, ValueError, OverflowError):
        raise BadIds from None
    if not 1 <= number <= MAX_ID:
        raise BadIds
    return number


def _selection(request):
    """``(ids, everything)`` from a form or a JSON body, or ``BadIds``.

    Marking everything has to be asked for (``all``); an empty or unreadable
    ``ids`` is an error, never a silent "all" - a front end that sends an empty
    selection by mistake must not clear a person's whole inbox.
    """
    if (request.content_type or "").startswith("application/json"):
        try:
            body = json.loads(request.body or b"{}")
        except (ValueError, RecursionError, UnicodeDecodeError):
            raise BadIds from None
        if not isinstance(body, dict):
            raise BadIds
        raw_ids, everything = body.get("ids"), body.get("all") is True
    else:
        raw_ids = request.POST.getlist("ids") if "ids" in request.POST else None
        everything = request.POST.get("all") in ("1", "true", "True")
    if raw_ids is None:
        if not everything:
            raise BadIds
        return [], True
    if everything or not isinstance(raw_ids, list) or not raw_ids or len(raw_ids) > MAX_IDS:
        raise BadIds
    return [_clean_id(value) for value in raw_ids], False


def _unread(user):
    return Notification.objects.filter(user=user, is_read=False).count()


def _upto(request):
    """The newest message the page says it showed (``upto`` in a JSON or form body), or ``None``.

    Absent means "everything there is" as before; a value that is not a message id is ``BadIds``.
    """
    if (request.content_type or "").startswith("application/json"):
        try:
            body = json.loads(request.body or b"{}")
        except (ValueError, RecursionError, UnicodeDecodeError):
            raise BadIds from None
        if not isinstance(body, dict):
            raise BadIds
        raw = body.get("upto")
    else:
        raw = request.POST.get("upto")
    if raw is None or raw == "":
        return None
    return _clean_id(raw)


# ---------------------------------------------------------------------------
# Who am I
# ---------------------------------------------------------------------------

@ensure_csrf_cookie
@endpoint("GET")
def me(request):
    """The signed-in person, and what the front end needs to start.

    Only their own record. ``chats.types`` lists the sidebar lists that exist
    for this role, so the page draws tabs the server will actually fill: the
    client directory is only for the roles that own the client inbox.
    """
    user = request.user
    types = ["clients"] if user.handles_clients else []
    types += ["groups", "staff"]
    return JsonResponse({
        "ok": True,
        "version": VERSION,
        "user": {
            "id": user.pk,
            "username": user.username,
            "name": user.get_full_name() or user.username,
            "short_name": user.short_name,
            "initials": user.initials,
            "role": user.role,
            "is_admin": user.is_admin_role,
            "lang": user.ui_lang,
            "theme": user.ui_theme,
        },
        "chats": {"types": types},
        # The ported screens that are switched on for this person (newui.py):
        # the menu lists exactly these, and the home page hands them on.
        "screens": newui.enabled_keys(user),
        "unread_notifications": _unread(user),
        # The chats entry's badge: messages waiting in any of the three lists.
        "unread_chats": services.unread_chat_total(user),
        "realtime": {"path": "/ws/events/", "ping_seconds": PING_SECONDS},
        "server_time": clock.fmt12(timezone.now(), "en"),
    })


# ---------------------------------------------------------------------------
# Notifications
# ---------------------------------------------------------------------------

@endpoint("GET")
def notifications(request):
    """This person's own notifications, newest first, a cursor page at a time."""
    limit = min(max(api._int(request.GET.get("limit"), PAGE), 1), MAX_PAGE)
    before = api._int(request.GET.get("before"), 0)
    rows = Notification.objects.filter(user=request.user).order_by("-id")
    if before:
        rows = rows.filter(id__lt=before)
    page = list(rows[:limit + 1])
    more = len(page) > limit
    page = page[:limit]
    return JsonResponse({
        "ok": True,
        "items": [
            dict(
                api._notification_json(n), read=n.is_read,
                date=timezone.localtime(n.created_at).strftime("%Y-%m-%d"),
            )
            for n in page
        ],
        "next_before": page[-1].id if more else None,
        "unread": _unread(request.user),
    })


@endpoint("POST")
def notifications_read(request):
    """Mark some of this person's notifications read: ``ids=[...]`` or ``all=true``."""
    try:
        ids, everything = _selection(request)
    except BadIds:
        return _error(400, "bad_ids")
    rows = Notification.objects.filter(user=request.user, is_read=False)
    if not everything:
        rows = rows.filter(id__in=ids)
    updated = rows.update(is_read=True)
    return JsonResponse({"ok": True, "updated": updated, "unread": _unread(request.user)})


# ---------------------------------------------------------------------------
# Chats (read side; sending joins in phase 5 with the chat screen)
# ---------------------------------------------------------------------------

@endpoint("GET")
def chats(request):
    """The chats sidebar: ``?type=clients|groups|staff`` and ``?q=`` to search.

    The same function the sidebar polls today, so the same rule applies: the
    client directory only to the roles that own the client inbox, and
    groups and staff chats only ever this person's own.
    """
    if request.GET.get("type", "clients") not in CHAT_TYPES:
        return _error(400, "bad_type")
    return api.client_chat_list(request)


@endpoint("GET")
def room_messages(request, room_id):
    """A task room's messages after ``?after=<id>`` (``api.chat_fetch``)."""
    return api.chat_fetch(request, room_id)


def _without_read(request):
    """The request with ``?read=1`` taken off, so a GET cannot mark anything read."""
    query = request.GET.copy()
    query.pop("read", None)
    request.GET = query
    return request


@endpoint("GET")
def group_messages(request, room_id):
    """A client group, work group or staff chat (``api.group_chat_fetch``)."""
    return api.group_chat_fetch(_without_read(request), room_id)


@endpoint("GET")
def client_messages(request, client_code):
    """One client's conversation, for the roles that answer clients."""
    return api.client_chat_fetch(_without_read(request), client_code)


@endpoint("GET")
def staff_messages(request, user_id):
    """This person's one-to-one chat with a colleague - always their own side of it.

    The room is found from the *pair* (the signed-in person and the colleague), never from an id the
    browser chose, so there is no way to name somebody else's chat; and it is read through the same
    function the group pages use, which refuses anyone who is not in it (not even the admin: a private
    line a third person reads is not a private line). Nobody has written yet: an empty conversation,
    and the room is NOT opened - a GET changes nothing.
    """
    other = User.objects.filter(pk=user_id, is_active=True).exclude(pk=request.user.pk).first()
    if other is None:
        raise Http404
    room = ChatRoom.objects.filter(
        kind=RoomKind.STAFF, pair_key=services.staff_pair_key(request.user.pk, other.pk)
    ).first()
    # A room that exists but has lost this person's seat (the room and its members are written in two
    # steps) is, to them, a chat nobody has written in: not a refusal on every refresh. Opening the chat
    # on the classic page, or sending the first line, puts the seat back; a GET writes nothing.
    if room is not None and room.members.filter(pk=request.user.pk).exists():
        return api.group_chat_fetch(_without_read(request), room.pk)
    return JsonResponse({
        "ok": True,
        "client": {
            "code": f"u{other.pk}", "group": False, "staff": True, "room": 0,
            "url": f"/ops/chats/u/{other.pk}/", "label": other.short_name, "initials": other.initials,
            "client_code": "", "text": "", "outgoing": False, "status": "", "receipt": "",
            "time": "", "date": "", "channel": "", "window_open": False, "minutes_left": 0, "unread": 0,
        },
        "messages": [],
    })


@endpoint("POST")
def group_read(request, room_id):
    """This person has the group on screen and has read it up to the newest message."""
    try:
        upto = _upto(request)
    except BadIds:
        return _error(400, "bad_upto")
    room = api._group_or_404(request, room_id)
    return JsonResponse({"ok": True, "moved": services.mark_room_read(request.user, room, upto=upto)})


@endpoint("POST")
@api_role_required(Role.OPERATION, Role.SALES)
def client_read(request, client_code):
    """The same for a client's conversation.

    When it moves, the client's phone gets WhatsApp's read receipt (a decision
    of 23/09/2026) - which is why this is a POST: only a person actually looking
    at the conversation may send it.
    """
    try:
        upto = _upto(request)
    except BadIds:
        return _error(400, "bad_upto")
    client = api._client_or_404(request, client_code)
    return JsonResponse({"ok": True, "moved": services.mark_client_read(request.user, client, upto=upto)})


# ---------------------------------------------------------------------------
# The translator's desk (phase 5, first screen)
# ---------------------------------------------------------------------------

def _two(table, value):
    """``{"ar", "en"}`` for a value in one of eagle_tags' ``(ar, en)`` tables."""
    ar, en = table.get(value, (value, value))
    return {"value": value, "ar": ar, "en": en}


def _status_json(status):
    tone, ar, en = STATUS_MAP.get(status, ("new", status, status))
    return {"value": status, "tone": tone, "ar": ar, "en": en}


def _desk_task_json(task, user, warning_minutes):
    """One open task as the translator's own page shows it.

    The date is ``deadline_for(user)``: a translator's own, which their leader
    set and which is often earlier than the client's, never the client's. The
    client is ``label_for(user)``: a code, never a name. The server writes the
    time too (Cairo, twelve hours, in both languages), so the page does no
    time arithmetic of its own.
    """
    due = task.deadline_for(user)
    origin = ORIGIN_MAP.get(task.origin)
    return {
        "code": task.code,
        "title": task.title,
        "status": _status_json(task.status),
        "priority": _two(PRIORITY_MAP, task.priority),
        "origin": {"value": task.origin, "icon": origin[1], "ar": origin[2], "en": origin[3]} if origin else None,
        "client": task.client.label_for(user) if task.client_id else "—",
        "source_lang": task.source_lang,
        "target_lang": task.target_lang,
        "due": {
            "ar": clock.fmt12(due, "ar", "%Y-%m-%d"),
            "en": clock.fmt12(due, "en", "%Y-%m-%d"),
        } if due else None,
        "due_state": task.deadline_state(user, warning_minutes),
        "can_ask_more_time": task.status == TaskStatus.IN_PROGRESS,
        "url": f"/tasks/{task.code}/",
    }


@endpoint("GET")
@api_role_required(Role.TRANSLATOR)
def translator_home(request):
    """The translator's own desk: their open tasks, what they closed lately, their rating history.

    Built from ``services.translator_desk``, the function the classic page
    reads, so the two cannot disagree about whose work this is. The admin may
    ask too (the classic page lets them), and sees their own desk.
    """
    user = request.user
    desk = services.translator_desk(user)
    warning = AppSettings.load().deadline_warning_minutes
    return JsonResponse({
        "ok": True,
        "rating": float(user.rating),
        "open": [_desk_task_json(task, user, warning) for task in desk["open_tasks"]],
        "done": [
            {"code": task.code, "status": _status_json(task.status), "url": f"/tasks/{task.code}/"}
            for task in desk["done_tasks"]
        ],
        "rating_events": [
            {"delta": str(event.delta), "reason_ar": event.reason_ar, "reason_en": event.reason_en}
            for event in desk["rating_events"]
        ],
    })
