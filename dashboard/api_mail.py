"""``/api/v1/`` - the mailbox: the list of conversations, one conversation, and the mark that it was read.

The same rules as the classic pages (``views.ops_inbox``, ``views.ops_mail_thread``) because the same functions
decide them: ``services.inbox_threads`` and ``services.thread_messages`` only ever return letters this person may
read (their line, the rate rule), so a letter that is not theirs is not in the answer and an id that names one is a
404. The operation and the Sales people use it - each on their own line - and the admin sees all.

Two things differ from the pages on purpose. A GET changes nothing: the classic page marked the whole conversation
read as it was opened, which a link on another site could have done with the person's own cookie; here that is a POST
the page makes when it has shown the letters. And an address is shown only to whoever may know it (the admin).

What is *done* to a conversation - the reply, fetching the mail, "received" - is the classic endpoints, unchanged.
"""

from django.http import JsonResponse
from django.shortcuts import get_object_or_404
from django.utils.text import Truncator

from . import identity, services
from .api_v1 import _error, _stamp, endpoint
from .models import AppSettings, Channel, InboundMessage, Role
from .permissions import api_role_required
from .templatetags.eagle_tags import strip_image_tags

#: The filters of the list. Anything else is a 400, not an empty list that looks like "no mail".
STATES = ("", "unclaimed", "mine", "notask")
#: The longest search: a word or two, not a document.
MAX_QUERY = 200
#: The longest line a row quotes of a letter.
SNIPPET = 120


def _snippet(text):
    return Truncator(strip_image_tags(text)).chars(SNIPPET)


def _words(letter, text, user):
    """What the client wrote, as ``user`` may read it: the client's name (the way it is spelled anywhere in the words) and every
    address and number taken out for whoever may not know the client, the rest as written. The operation reads the letter to do
    the work; a signature is not part of the work."""
    return identity.mask_client(text, letter.client if letter.client_id else None, user)


def _file_json(attachment):
    """A file of a letter: a link, a name, a size, and for a voice note how long it is."""
    return {
        "id": attachment.pk,
        "url": attachment.file.url,
        "name": attachment.original_name or attachment.file.name.rsplit("/", 1)[-1],
        "size": attachment.pretty_size,
        "image": services.is_image(attachment),
        "audio": attachment.is_audio,
        "length": attachment.pretty_duration if attachment.is_audio else "",
    }


def _sender(letter, user):
    """Who a letter is from: the client as ``label_for`` gives it; for the admin alone, the address when there is no client."""
    if letter.client_id:
        return {"label": letter.client.label_for(user), "code": letter.client.code, "address": ""}
    if user.is_admin_role and letter.sender_identity:
        return {"label": letter.sender_identity, "code": "", "address": letter.sender_identity}
    return {"label": "", "code": "", "address": ""}


def _row_json(thread, user):
    last = thread.latest
    sender = _sender(last, user)
    return {
        "key": thread.key,
        # The letter the row opens: any letter's id opens the conversation it is in.
        "id": last.pk,
        "from": sender["label"],
        "code": sender["code"],
        "count": thread.count,
        "at": _stamp(last.received_at, "%Y-%m-%d"),
        "subject": _words(last, thread.subject, user),
        "snippet": _snippet(_words(last, last.body, user)),
        "unread": thread.is_unread,
        "blocked": thread.is_blocked,
        "answered": thread.answered,
        "tasks": [task.code for task in thread.tasks],
        "files": thread.attachment_count,
        "claimers": thread.claimers,
    }


@endpoint("GET")
@api_role_required(Role.OPERATION, Role.SALES)
def threads(request):
    """The conversations, newest first: ``?state=unclaimed|mine|notask`` and ``?q=`` (the newest 100).

    The two numbers over the list answer two questions: ``unseen`` is the badge (conversations this person has not
    opened, and it falls as they read), ``unclaimed`` does not move until somebody presses "received".
    """
    user = request.user
    state = request.GET.get("state", "")
    query = request.GET.get("q", "").strip()
    if state not in STATES or len(query) > MAX_QUERY or "\x00" in query:
        return _error(400, "bad_filter")
    conf = AppSettings.load()
    return JsonResponse({
        "ok": True,
        "state": state,
        "q": query,
        "threads": [_row_json(thread, user) for thread in services.inbox_threads(user, state, query, limit=100)],
        "unseen": services.unseen_conversation_count(user),
        "unclaimed": services.unclaimed_conversation_count(user),
        # Letters hidden from the operation by the rate rule: the admin is told how many.
        "blocked": InboundMessage.objects.filter(channel=Channel.EMAIL, is_rate_blocked=True).count() if user.is_admin_role else 0,
        "mail": {
            "configured": bool(conf.imap_host and conf.imap_user and conf.imap_password),
            "last_fetch": _stamp(conf.mail_last_fetch_at, "%Y-%m-%d"),
            "last_count": conf.mail_last_count,
            "last_error": identity.for_viewer(conf.mail_last_error, user),
        },
    })


def _anchor(request, pk):
    """The letter ``pk`` names, if this person may read it - and the conversation it is in."""
    anchor = get_object_or_404(InboundMessage.objects.select_related("client"), pk=pk, channel=Channel.EMAIL)
    if not anchor.visible_to(request.user):
        identity.hidden(request, "mail")
    letters = services.thread_messages(request.user, anchor)
    if not letters:
        identity.hidden(request, "mail")
    return anchor, letters


@endpoint("GET")
@api_role_required(Role.OPERATION, Role.SALES)
def thread(request, pk):
    """One conversation, every letter and every reply of ours in it, oldest first.

    Any letter's id opens the conversation it belongs to, so a notification that points at the newest letter lands
    on the whole exchange. The newest entry, and the letter the link named, start open. ``unseen`` says which
    letters this person had not opened *before* now; opening them is ``thread_seen``, a POST of its own.
    """
    user = request.user
    anchor, letters = _anchor(request, pk)
    seen = services.seen_letter_ids(user, letters)
    mail = services.MailThread(anchor.thread_key or f"m{anchor.pk}", letters, services.thread_replies(anchor.thread_key, user), seen)
    entries = mail.entries
    out = []
    for index, entry in enumerate(entries):
        item = entry["item"]
        opened = index == len(entries) - 1 or (entry["kind"] == "in" and item.pk == anchor.pk)
        if entry["kind"] == "out":
            out.append({
                "kind": "out",
                "id": item.pk,
                "by": item.created_by.short_name if item.created_by_id else None,
                "at": _stamp(item.created_at, "%Y-%m-%d"),
                "body": item.body,
                "files": [
                    {
                        "id": u.pk, "url": u.file.url, "name": u.original_name or u.file.name.rsplit("/", 1)[-1],
                        "size": u.pretty_size, "image": False, "audio": False, "length": "",
                    }
                    for u in item.uploads.all()
                ],
                "failed": item.status == "failed",
                # The library's words quote the address back; whoever may not know it does not read it.
                "error": identity.for_viewer(item.error_message, user) if item.status == "failed" else "",
                "open": opened,
            })
            continue
        sender = _sender(item, user)
        documents = [a for a in item.attachments.all() if not a.is_audio]
        out.append({
            "kind": "in",
            "id": item.pk,
            "from": sender["label"],
            "code": sender["code"],
            "at": _stamp(item.received_at, "%Y-%m-%d"),
            "snippet": _snippet(_words(item, item.body, user)),
            "body": strip_image_tags(_words(item, item.body, user)),
            "unseen": item.pk not in seen,
            "blocked": item.is_rate_blocked,
            "task": item.task.code if item.task_id else None,
            "claimed_by": item.claimed_by.short_name if item.claimed_by_id else None,
            "files": [_file_json(a) for a in item.attachments.all()],
            # "Received" and "convert to a task" stand for work on a file the client sent.
            "can_confirm": bool(documents and item.client_id),
            "can_convert": bool(documents and not item.task_id and not user.is_sales),
            "documents": [a.pk for a in documents],
            # The raw address, for the admin alone.
            "raw": f"{item.sender_identity} {item.sender_display}".strip() if user.is_admin_role and item.sender_identity else "",
            "open": opened,
        })
    return JsonResponse({
        "ok": True,
        "thread": {
            "id": anchor.pk,
            "subject": identity.mask_client(mail.subject, mail.client, user),
            "count": mail.count,
            "client": mail.client.label_for(user) if mail.client else None,
            "can_reply": mail.client is not None,
            "tasks": [task.code for task in mail.tasks],
            "blocked": mail.is_blocked,
            "entries": out,
        },
    })


@endpoint("POST")
@api_role_required(Role.OPERATION, Role.SALES)
def thread_seen(request, pk):
    """This person has opened the conversation: the badge falls. The page says so once it has shown the letters.

    ``unseen`` is what the badge now counts, so a page can show it without asking again.
    """
    _anchor_row, letters = _anchor(request, pk)
    fresh = services.mark_letters_seen(request.user, letters)
    return JsonResponse({"ok": True, "marked": len(fresh), "unseen": services.unseen_conversation_count(request.user)})
