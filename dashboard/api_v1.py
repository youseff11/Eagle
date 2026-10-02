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

from django.core.exceptions import PermissionDenied, SuspiciousOperation, TooManyFilesSent
from django.http import Http404, JsonResponse, QueryDict
from django.utils import timezone
from django.views.decorators.csrf import ensure_csrf_cookie

from . import api, audio, clock, identity, newui, services
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
                except TooManyFilesSent:
                    # Django counts the parts of a form as it reads it, and stops at 100: a refusal like the others.
                    response = _error(400, "too_many_files")
                except SuspiciousOperation as refusal:
                    # A body Django refuses to read (too many fields, too big): nothing was written.
                    log.warning("api v1: %s refused a form: %s", view.__name__, refusal)
                    response = _error(400, "bad_request")
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
        # ``can_create_group``: this person may open an internal work group (``User.can_create_team_group``).
        "chats": {"types": types, "can_create_group": user.can_create_team_group},
        # The longest message this person may write, for what goes to one client, to a client group and inside.
        "limits": {
            "to_client": limit_for(user, "client"),
            "to_client_group": limit_for(user, "client_group"),
            "inside": limit_for(user, "inside"),
            "files": {"count": MAX_FILES, "bytes": MAX_FILE_BYTES, "total_bytes": MAX_FILES_TOTAL_BYTES},
            "voice": {"seconds": audio.MAX_SECONDS, "bytes": MAX_VOICE_BYTES},
        },
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
# Chats, writing (phase 5, chat slice 3b: text and replies)
#
# Three doors, one rule: what may be written where is decided by the functions
# the classic pages already use (``api.send_to_client``, ``api.chat_send``,
# ``_group_or_404``, ``ChatRoom.can_open``, ``lines``), never by a second copy.
# A message that stays inside (a colleague, a work group) never reaches the
# relay; one that goes to a client leaves only through ``send_client_message``.
#
# The answer is the same for all three. HTTP 200 means "it is in the thread":
# ``delivered`` says whether it also got where it was going, ``error`` says why
# not, and ``messages`` / ``client`` are the thread as this person sees it now,
# so a failed delivery is on screen and nothing is fetched twice. A refusal
# (nothing was written) is a 4xx with a short code.
#
# Sending does NOT mark anything read. The classic page says "answering is
# reading" for the whole thread, which for a client is the blue ticks on their
# phone for words nobody on this side has seen; here the page says what it
# showed (``.../read/`` with ``upto``) and the send stays a send.
# ---------------------------------------------------------------------------

#: The longest message. WhatsApp cuts a text at 4000 characters without a word (``whatsapp.send_text``), so the
#: thread would show the client words that never reached them: anything that goes to a client is refused above it.
#: What stays inside has more room, but not unlimited: the thread sends every body to every member at every refresh.
MAX_CLIENT_TEXT = 4000
MAX_INTERNAL_TEXT = 10000


def _wrote_something(request):
    """Whether the form carries anything to send: words, a file or a recording."""
    return bool((request.POST.get("body") or "").strip() or request.FILES.getlist("files") or request.FILES.get("voice"))


#: Files in one message: how many, how big each, how big all together. WhatsApp has limits of its own per kind of
#: file (it says so when it refuses one); these are the ones this server will store and send. They are checked once
#: the request has been read, so they keep a big upload from being kept and sent, not from being received: that
#: is for the host and the proxy in front of it.
#:
#: The size is the most that anything on the way will take: WhatsApp takes a document of up to 100 MB, and the proxy
#: in front of the site (Cloudflare, on the plans most sites are on) takes a request of up to 100 MB. A message's files
#: are one request, so the total is the same number as one file's, a little under 100 MB to leave room for the form's
#: own words. A file held by WhatsApp's own limits (a photo over 5 MB, a video over 16 MB) is refused by WhatsApp with
#: its reason, and shows as failed. Storage is Bunny's and costs nothing to speak of; memory is the host's: sending a
#: file to a client holds it in memory about twice (read back from storage, and the upload's own body).
MAX_FILES = 10
MAX_FILE_BYTES = 95 * 1024 * 1024
MAX_FILES_TOTAL_BYTES = 95 * 1024 * 1024
#: A recording is at most ``audio.MAX_SECONDS`` of speech. The ceiling is ``audio``'s own: it is checked there, for
#: every door that takes a recording, and again here so that a too big one is refused before anything is written.
MAX_VOICE_BYTES = audio.MAX_UPLOAD_BYTES


def _files_problem(request):
    """The short code for what is wrong with the files of this form, or ``""``."""
    files = request.FILES.getlist("files")
    voice = request.FILES.get("voice")
    if len(files) > MAX_FILES:
        return "too_many_files"
    if voice is not None and voice.size == 0:
        return "empty_file"
    if voice is not None and voice.size > MAX_VOICE_BYTES:
        return "file_too_big"
    sizes = [item.size for item in files] + ([voice.size] if voice is not None else [])
    if any(size > MAX_FILE_BYTES for size in sizes):
        return "file_too_big"
    if sum(sizes) > MAX_FILES_TOTAL_BYTES:
        return "files_too_big"
    return ""


def limit_for(user, kind):
    """The longest text ``user`` may write: ``client`` (to one client), ``client_group`` or ``inside``.

    A client group puts the sender's role in front of the words (``services.client_prefix``) and WhatsApp counts
    the whole: the prefix comes off the limit, or the last characters of a message that passed would be cut.
    """
    if kind == "client":
        return MAX_CLIENT_TEXT
    if kind == "client_group":
        return MAX_CLIENT_TEXT - len(services.client_prefix(user))
    return MAX_INTERNAL_TEXT


def _too_long(request, kind):
    return len((request.POST.get("body") or "").strip()) > limit_for(request.user, kind)


def _sent_to_room(request, room):
    """Write into ``room`` through the one classic function that does it, and describe the result."""
    response = api.chat_send(request, room.pk)
    try:
        detail = json.loads(response.content)
    except ValueError:
        detail = {}
    if response.status_code != 200:
        # Refused before anything was saved (nothing to send, or files that need a task).
        answer = {"ok": False, "error": detail.get("error") or "empty"}
        for key in ("message", "message_en", "choices"):
            if key in detail:
                answer[key] = detail[key]
        return JsonResponse(answer, status=400)
    relay_error = detail.get("relay_error") or ""
    return JsonResponse({
        "ok": True,
        "delivered": not relay_error,
        "error": relay_error,
        "messages": [api._thread_entry_json(e, request.user) for e in services.group_thread(room, request.user)],
        "client": api._group_json(room, request.user),
    })


def _file_tasks_answer(tasks):
    """The tasks files could be for, as the picker above the box lists them. One is preselected, several must be chosen."""
    return JsonResponse({
        "ok": True,
        "tasks": [{"code": task.code, "title": task.title} for task in tasks],
    })


@endpoint("GET")
def group_file_tasks(request, room_id):
    """Which task the files sent in this work group or colleague's room could be for (``services.file_task_choices``)."""
    room = api._group_or_404(request, room_id)
    return _file_tasks_answer(services.file_task_choices(request.user, room))


@endpoint("GET")
def staff_file_tasks(request, user_id):
    """The same for a colleague, before anybody has written to them: nothing is opened by asking."""
    other = User.objects.filter(pk=user_id, is_active=True).exclude(pk=request.user.pk).first()
    if other is None:
        raise Http404
    return _file_tasks_answer(services.file_task_choices_with(request.user, other))


@endpoint("POST")
def group_send(request, room_id):
    """Write in a client group, a work group or a colleague's room you are already in."""
    room = api._group_or_404(request, room_id)
    if _too_long(request, "client_group" if room.kind == RoomKind.CLIENT else "inside"):
        return _error(400, "too_long")
    if problem := _files_problem(request):
        return _error(400, problem)
    return _sent_to_room(request, room)


@endpoint("POST")
def staff_send(request, user_id):
    """Write to a colleague. The room is found from the pair - and opened here, by a write, if it is new."""
    other = User.objects.filter(pk=user_id, is_active=True).exclude(pk=request.user.pk).first()
    if other is None:
        raise Http404
    # Nothing to send is refused before a room is created for it.
    if not _wrote_something(request):
        return _error(400, "empty")
    if _too_long(request, "inside"):
        return _error(400, "too_long")
    if problem := _files_problem(request):
        return _error(400, problem)
    # The first message opens the room, and so does its question: files asked which task they are for must be
    # answered before a room is made for them, or a refusal leaves an empty room behind.
    if request.FILES.getlist("files") and not ChatRoom.objects.filter(
        kind=RoomKind.STAFF, pair_key=services.staff_pair_key(request.user.pk, other.pk)
    ).exists():
        _task, pick_error, choices = services.pick_file_task_with(request.user, other, request.POST.get("task", ""))
        if pick_error:
            return api.pick_refusal(pick_error, choices)
    return _sent_to_room(request, services.staff_room(request.user, other))


@endpoint("POST")
@api_role_required(Role.OPERATION, Role.SALES)
def client_send(request, client_code):
    """Answer a client, on WhatsApp, from the line this person answers from."""
    client = api._client_or_404(request, client_code)
    # Asked here, before the form is looked at, so that a code off this person's line answers like an unknown
    # one whatever they sent (an empty form would otherwise say "empty" only for the codes that are theirs).
    # ``send_to_client`` asks it again: it is the rule of the send, whoever calls it.
    if not api.may_answer(client, request.user):
        identity.hidden(request, "client")
    if not _wrote_something(request):
        return _error(400, "empty")
    if _too_long(request, "client"):
        return _error(400, "too_long")
    if problem := _files_problem(request):
        return _error(400, problem)
    ok, outbound, error = api.send_to_client(request, client)
    if outbound is None:
        return _error(400, "empty")
    return JsonResponse({
        "ok": True,
        "delivered": ok,
        "error": error,
        "messages": [api._thread_entry_json(e, request.user) for e in services.client_thread(client, request.user)],
        "client": api._conversation_json(client, request.user),
    })


# ---------------------------------------------------------------------------
# Chats, step 3d: reactions and forwarding
#
# Two doors over the functions the classic page calls (``services.toggle_reaction``, ``services.forward_messages``):
# who may see what, which words may travel and where, are decided there and nowhere else. Both take a JSON object.
# A reaction never leaves the building (it is an internal mark, nothing is sent to a client); a forward to a client
# does, through ``send_client_message``, and to a group that reaches one, through the relay.
#
# What a refusal means is the same as for a send: a 4xx is "nothing was written". A forward that got somewhere and
# then failed (the client's phone refused the third message, a group's relay broke) is a 200 with ``delivered`` false
# and the reason, so that the page does not offer to send again what has already arrived.
# ---------------------------------------------------------------------------

#: The most messages (or files) one forward may carry, and the longest code a body may name.
MAX_FORWARD_ITEMS = 100
MAX_CODE = 40
#: The longest note that goes with a forward (``services.forward_messages`` cuts at the same number).
MAX_FORWARD_NOTE = 2000

REACTION_KINDS = frozenset(key for key, *_rest in services.REACTIONS)


class BadBody(ValueError):
    """The body of the request is not the JSON object the door reads."""


def _object(request):
    if not (request.content_type or "").startswith("application/json"):
        raise BadBody
    try:
        body = json.loads(request.body or b"{}")
    except (ValueError, RecursionError, UnicodeDecodeError):
        raise BadBody from None
    if not isinstance(body, dict):
        raise BadBody
    return body


def _text(body, name, limit):
    """A string field, cut of its edges; anything else, or longer than ``limit``, is ``BadBody``."""
    value = body.get(name, "")
    if not isinstance(value, str) or len(value) > limit:
        raise BadBody
    return value.strip()


def _list(body, name, clean):
    """A short list of distinct values, in the order given, each one passed through ``clean``."""
    raw = body.get(name, [])
    if not isinstance(raw, list) or len(raw) > MAX_FORWARD_ITEMS:
        raise BadBody
    values = []
    for item in raw:
        value = clean(item)
        if value not in values:
            values.append(value)
    return values


def _code(value):
    if not isinstance(value, str) or not 0 < len(value.strip()) <= MAX_CODE:
        raise BadBody
    return value.strip()


@endpoint("POST")
def chat_react(request):
    """Give one of the six reactions to a message, change it, or take it back (the same one again).

    ``{"source": "CL-0001" | "g12" | "u5", "uid": "in-5", "kind": "like"}``. The message is looked up inside the
    conversation it is said to belong to, by the same function the classic page uses, so an id from somewhere
    this person may not look finds nothing: the answer is the same 404 as for an id that does not exist.
    """
    try:
        body = _object(request)
        source, uid, kind = _text(body, "source", MAX_CODE), _text(body, "uid", MAX_CODE), _text(body, "kind", MAX_CODE)
    except BadBody:
        return _error(400, "bad_request")
    if kind not in REACTION_KINDS:
        return _error(400, "bad_kind")
    done, _words, reactions = services.toggle_reaction(request.user, source, uid, kind)
    if not done:
        return _error(404, "not_found")
    return JsonResponse({"ok": True, "uid": uid, "reactions": reactions})


@endpoint("POST")
def chat_forward(request):
    """Forward some messages (``uids``) and/or files of one conversation to another.

    ``{"source": "CL-0001", "target": "g12", "uids": ["in-5", "out-9"], "files": [3], "note": "..."}``. Every rule
    (who may forward to a client, that a client's files never go to another client, that a client's own words
    reach only rooms where everyone may read them) is ``services.forward_messages``'s.
    """
    try:
        body = _object(request)
        source, target = _code(body.get("source")), _code(body.get("target"))
        note = _text(body, "note", MAX_FORWARD_NOTE)
        uids = _list(body, "uids", _code)
        files = _list(body, "files", _clean_id)
    except (BadBody, BadIds):
        return _error(400, "bad_request")
    if not uids and not files:
        return _error(400, "empty")
    done, words, _url, written = services.forward_messages(
        request.user, source, target, uids=uids, attachment_ids=files, note=note
    )
    # The words of a refusal are ours; the words of a failed delivery came from a library that quotes the
    # recipient back, and a person who may not know the client does not get their number from this.
    words = identity.for_viewer(words, request.user)
    if not written:
        return JsonResponse({"ok": False, "error": "refused", "message": words}, status=400)
    return JsonResponse({"ok": True, "delivered": done, "message": words, "code": target})


# ---------------------------------------------------------------------------
# Chats, step 3e (part 1): work groups - who is in one, opening one, adding to one
#
# The rules stay where the classic page keeps them: ``services.create_team_group`` (who may open a group, what it
# is called, who is told) and ``api.group_add_members`` (a work group or a client room, a task's own people, no
# translator in a room that reaches a client). These doors read a JSON body, put it where those functions look for
# it (``request.POST``) and say what they answered the way the other doors do: 4xx is "nothing happened", with the
# reason in ``message``.
# ---------------------------------------------------------------------------

#: The most people one request may name, and how many a list offers (the classic page's own limit).
MAX_MEMBERS = 100
PEOPLE_LISTED = 200


def _person_json(person):
    return {"id": person.pk, "name": person.short_name, "initials": person.initials, "role": person.role}


def _as_form(request, **lists):
    """Make ``request.POST`` what the classic function reads, from values this module has already checked."""
    form = QueryDict(mutable=True)
    for name, values in lists.items():
        form.setlist(name, [str(value) for value in values] if isinstance(values, list) else [str(values)])
    request.POST = form
    return request


def _member_ids(body):
    """The ``members`` of a JSON body: a short list of distinct database ids."""
    raw = body.get("members", [])
    if not isinstance(raw, list) or len(raw) > MAX_MEMBERS:
        raise BadBody
    ids = []
    for item in raw:
        value = _clean_id(item)
        if value not in ids:
            ids.append(value)
    return ids


def _classic_answer(response, viewer, keep=()):
    """What a classic JSON door said, as this layer says it.

    ``ok`` with the reason it gives in ``message`` (a partial refusal), or a 4xx with the reason: 403 stays 403,
    anything else is "refused". The words go through ``identity.for_viewer`` like every other text of ours that a
    library may have quoted a client's address into. ``keep`` names fields of the classic answer to pass on.
    """
    try:
        detail = json.loads(response.content)
    except ValueError:
        detail = {}
    words = identity.for_viewer(str(detail.get("error") or ""), viewer)
    if response.status_code == 200 and detail.get("ok"):
        return JsonResponse({"ok": True, "message": words, **{name: detail[name] for name in keep if name in detail}})
    forbidden = response.status_code == 403
    return JsonResponse(
        {"ok": False, "error": "forbidden" if forbidden else "refused", "message": words},
        status=403 if forbidden else 400,
    )


@endpoint("GET")
def people(request):
    """The people a work group can be opened with. Only for those who may open one (as the classic page's list)."""
    if not request.user.can_create_team_group:
        raise PermissionDenied("people for a work group")
    rows = User.objects.filter(is_active=True).exclude(pk=request.user.pk).order_by("role", "username")[:PEOPLE_LISTED]
    return JsonResponse({"ok": True, "people": [_person_json(person) for person in rows]})


@endpoint("POST")
def group_create(request):
    """Open an internal work group: ``{"title": "...", "members": [ids]}``. Nothing in it reaches a client."""
    try:
        body = _object(request)
        title = _text(body, "title", 120)
        members = _member_ids(body)
    except (BadBody, BadIds):
        return _error(400, "bad_request")
    if not request.user.can_create_team_group:
        raise PermissionDenied("create a work group")
    answer = _classic_answer(api.team_group_create(_as_form(request, title=title, members=members)), request.user, keep=("room",))
    if answer.status_code == 200:
        room = json.loads(answer.content)["room"]
        return JsonResponse({"ok": True, "room": room, "code": f"g{room}"})
    return answer


@endpoint("GET")
def group_members(request, room_id):
    """Who is in a group, whether this person may add to it, and who they could add.

    Read through the same gate as the group's messages (``api._group_or_404``): a room this person may not open
    is a 404. The list of people to add is only given to somebody who may add them.
    """
    room = api._group_or_404(request, room_id)
    members = list(room.members.all())
    may_add = services.may_add_members(request.user, room)
    addable = []
    if may_add:
        rows = User.objects.filter(is_active=True).exclude(pk__in=[member.pk for member in members])
        if room.kind == RoomKind.CLIENT:
            # A translator is never seated in a room that reaches a client: not offered, so not refused.
            rows = rows.exclude(role=Role.TRANSLATOR)
        addable = [_person_json(person) for person in rows.order_by("role", "username")[:PEOPLE_LISTED]]
    return JsonResponse({
        "ok": True,
        "members": [_person_json(person) for person in members],
        "can_add": may_add,
        "addable": addable,
    })


@endpoint("POST")
def group_add(request, room_id):
    """Add people to a group: ``{"members": [ids]}``. ``ok`` when somebody was added; ``message`` says who was not."""
    try:
        members = _member_ids(_object(request))
    except (BadBody, BadIds):
        return _error(400, "bad_request")
    if not members:
        return _error(400, "empty")
    return _classic_answer(api.group_add_members(_as_form(request, members=members), room_id), request.user, keep=("added",))


# ---------------------------------------------------------------------------
# Chats, step 3e (part 2): the translator's "task done" from a work group
#
# ``services.handin_tasks_for`` says which of a translator's tasks they may hand files in to from this group;
# ``services.hand_in_from_chat`` (through the classic door) checks every file again - theirs, in a work group the
# task's leader is in, no voice note, none already on another task - tags the messages with the task and runs
# "finished" as if pressed on the task page. These doors only carry the question and the answer.
# ---------------------------------------------------------------------------

@endpoint("GET")
def group_handin_tasks(request, room_id):
    """The tasks this person could hand files in to from this group; empty for anybody but a translator in a work group."""
    room = api._group_or_404(request, room_id)
    tasks = services.handin_tasks_for(request.user, room)
    return JsonResponse({"ok": True, "tasks": [{"code": task.code, "title": task.title} for task in tasks]})


@endpoint("POST")
def task_hand_in(request, code):
    """``{"files": [chat attachment ids]}``: these are the translation of ``code``, it is done and goes to review."""
    try:
        files = _list(_object(request), "files", _clean_id)
    except (BadBody, BadIds):
        return _error(400, "bad_request")
    if not files:
        return _error(400, "empty")
    answer = _classic_answer(api.hand_in_from_chat(_as_form(request, files=files), code), request.user, keep=("url",))
    if answer.status_code == 200:
        return JsonResponse({"ok": True, "code": code})
    return answer


# ---------------------------------------------------------------------------
# Chats, step 3e (part 3): "received" under a client's message
#
# The one thing under a client's message that sends something: «استلمت» tells the client their message arrived (on
# the channel it came in on) and marks it claimed. ``api.confirm_message`` decides everything - the roles, that the
# message is on this person's line and not hidden by the rate rule - and ``services.confirm_receipt`` does it; this
# door carries the question. Turning a message into a task is not a door at all: it is a link to the task form.
# ---------------------------------------------------------------------------

@endpoint("POST")
def message_confirm(request, message_id):
    """Tell the client the message arrived. ``ok`` once the receipt is out and the message is claimed."""
    return _classic_answer(api.confirm_message(request, message_id), request.user, keep=("claimed_by",))


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
