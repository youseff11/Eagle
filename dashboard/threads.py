"""Grouping e-mails into conversations, the way a mail client does.

A client never sends one e-mail. They send the job, then "please share", then
"word count please", then "dear dont delay" — and a mailbox that lists each of
those as its own letter makes the operation read the same job four times over.
Gmail shows one conversation; so does /ops/inbox/.

Two ways a letter joins a conversation, in this order:

1. **The headers.** ``In-Reply-To`` / ``References`` name the Message-IDs the
   client is answering. If one of them is a letter we already have, this is
   the same conversation — whatever the subject says now.
2. **The subject.** Replies we sent from Gmail itself are not in our database,
   so the client's answer to one of them points at a Message-ID we never saw.
   The subject still gives it away: ``Re: Legal Arabic Translation`` from the
   same client is the ``Legal Arabic Translation`` conversation, as long as
   that conversation has moved in the last :data:`SUBJECT_WINDOW`.

Everything here is plain functions over a model class, never the model itself,
so migration 0016 can run the same rules over the historical model to group
the mail that arrived before this existed.
"""

import re
import uuid
from datetime import timedelta

from django.utils import timezone

#: Same client, same subject, but nothing said for this long: a new job that
#: happens to reuse an old subject ("Translation request"), not a reply.
SUBJECT_WINDOW = timedelta(days=30)

#: How far back in one client's mail the subject match looks.
_SUBJECT_SCAN = 300

#: ``Re:``, ``Fwd:``, ``RE[2]:``, ``AW:`` (German Outlook), ``رد:`` … repeated
#: any number of times. What is left is the subject the client first wrote.
_PREFIX = re.compile(
    r"^\s*(?:(?:re|fw|fwd|aw|wg|sv|vs|tr|rv|antw|رد|توجيه|إعادة توجيه|اعادة توجيه)"
    r"\s*(?:\[\d+\]|\(\d+\))?\s*[:：]\s*)+",
    re.IGNORECASE,
)
_SPACES = re.compile(r"\s+")
_MESSAGE_ID = re.compile(r"<[^<>\s]+>")

#: ``InboundMessage.external_id`` is cut at this length, so a lookup has to be.
_ID_LENGTH = 190


def normalize_subject(subject):
    """``"Re: Fwd:  Legal  Arabic"`` -> ``"legal arabic"``. Never raises."""
    text = _PREFIX.sub("", subject or "")
    return _SPACES.sub(" ", text).strip().casefold()


def message_ids(*headers):
    """Every ``<id@host>`` named in ``In-Reply-To`` / ``References``.

    A header that carries an id without the angle brackets (some mailers do)
    is taken whole. Order is kept, repeats are dropped.
    """
    found = []
    for header in headers:
        header = (header or "").strip()
        if not header:
            continue
        ids = _MESSAGE_ID.findall(header) or [header.split()[0]]
        for item in ids:
            item = item[:_ID_LENGTH]
            if item not in found:
                found.append(item)
    return found


def new_key():
    return uuid.uuid4().hex


def find_thread_key(model, *, channel, client_id=None, sender="", subject="",
                    refs=(), when=None, exclude_pk=None):
    """The conversation a new letter belongs to, or ``""`` for a new one.

    ``model`` is ``InboundMessage`` — the live one, or the historical one a
    migration hands over. Only letters that already have a key are candidates,
    which is what lets the backfill walk the mail oldest first.
    """
    candidates = model.objects.filter(channel=channel).exclude(thread_key="")
    if exclude_pk:
        candidates = candidates.exclude(pk=exclude_pk)

    refs = [ref for ref in refs if ref]
    if refs:
        hit = (
            candidates.filter(external_id__in=refs)
            .order_by("-received_at")
            .values_list("thread_key", flat=True)
            .first()
        )
        if hit:
            return hit

    wanted = normalize_subject(subject)
    if not wanted:
        # "(no subject)" is not a conversation; every one of them would merge.
        return ""

    # The address decides who wrote it, the same rule as resolve_client.
    if client_id:
        same_sender = candidates.filter(client_id=client_id)
    elif sender:
        same_sender = candidates.filter(sender_identity__iexact=sender)
    else:
        return ""

    since = (when or timezone.now()) - SUBJECT_WINDOW
    recent = (
        same_sender.filter(received_at__gte=since)
        .order_by("-received_at")
        .values_list("thread_key", "subject")[:_SUBJECT_SCAN]
    )
    for key, other_subject in recent:
        if normalize_subject(other_subject) == wanted:
            return key
    return ""
