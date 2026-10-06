"""Stored files: where they live, who may open them, what they are called.

Section 12 of the B2B masking requirements: masking holds for files too.
Three rules, each enforced on the server:

1. **The storage path says nothing.** A new upload is stored as
   ``inbound/2026/09/5f0c2e9ab1d34c7e.pdf`` - a random name, never the one the
   client gave it - so a URL copied into a chat, a log or a browser history
   carries no company name (``storage_name``).
2. **Opening a file is a request like any other.** Every file URL the
   dashboard draws is ``/files/<path>``, answered by ``views.serve_file``,
   which asks ``may_open`` whether *this* person may read *this* file - the
   same rules the page that listed it used - and refuses with a logged 404.
   The CDN address is never handed to a browser again, so the Bunny pull
   zone can be locked with Token Authentication without breaking anything.
3. **The name shown is masked.** A client file's display name has the
   client's own name, company, e-mail domain and number replaced by their
   code before anyone but the admin reads it (``mask_name``). The name the
   client really used is kept in ``raw_name`` for the admin.
"""

import mimetypes
import posixpath
import re
import uuid

from django.utils import timezone


#: The prefix every protected URL starts with. ``Core/urls.py`` routes it.
URL_PREFIX = "/files/"


# ---------------------------------------------------------------------------
# 1. Storage names
# ---------------------------------------------------------------------------

def _extension(filename):
    ext = posixpath.splitext(str(filename or ""))[1].lower()
    # Only a plain, short extension survives - anything else is dropped
    # rather than trusted into a path.
    return ext if re.fullmatch(r"\.[a-z0-9]{1,8}", ext) else ""


def storage_name(prefix, instance, filename):
    """``<prefix>/YYYY/MM/<random><.ext>`` - and the real name kept on the row.

    ``upload_to`` is the last moment the name the file arrived with is still
    known, so it is copied onto the instance here when nobody set it: the
    dashboard keeps showing a sensible name while the path shows nothing.
    """
    if hasattr(instance, "original_name") and not getattr(instance, "original_name", ""):
        instance.original_name = str(filename or "")[:250]
    return f"{prefix}/{timezone.now():%Y/%m}/{uuid.uuid4().hex[:16]}{_extension(filename)}"


# ---------------------------------------------------------------------------
# 3. Masked names
# ---------------------------------------------------------------------------

#: Between the pieces of a name a file name may put a space, an underscore,
#: a dash or a dot: "ABC Translation", "abc_translation", "ABC-Translation".
_GAP = r"[\s_\-.]*"
_WORD = re.compile(r"[^\W_]+", re.UNICODE)
#: Domains everybody uses say nothing about who the client is.
_PUBLIC_MAIL = {
    "gmail", "yahoo", "hotmail", "outlook", "live", "icloud", "msn", "aol",
    "protonmail", "proton", "yandex", "mail",
}


def _phrase_pattern(text):
    words = _WORD.findall(text or "")
    if not words:
        return ""
    return _GAP.join(re.escape(word) for word in words)


def identity_terms(client, for_text=False):
    """The regex pieces that identify this client in a file name (or, with ``for_text``, in free words).

    In free words the part of an address before the ``@`` is taken only when it looks like a person's name (``john.smith``) or is
    long: ``info`` or ``sales`` would eat ordinary words.
    """
    if client is None:
        return []
    patterns = []
    for value in (client.name, client.company):
        value = (value or "").strip()
        # One or two letters would eat ordinary words.
        if len(value) >= 3:
            patterns.append(_phrase_pattern(value))
    for address in client.all_emails:
        local, _, domain = address.partition("@")
        stem = domain.split(".")[0] if domain else ""
        if len(local) >= 3 and (not for_text or len(local) >= 6 or re.search(r"[._-]", local)):
            patterns.append(_phrase_pattern(local))
        if len(stem) >= 3 and stem.lower() not in _PUBLIC_MAIL:
            patterns.append(_phrase_pattern(stem))
    for number in client.all_phones:
        digits = "".join(ch for ch in number if ch.isdigit())
        if len(digits) >= 7:
            # The last seven digits, however they were spaced.
            patterns.append(r"[\s\-.]*".join(digits[-7:]))
    # Longest first, so "ABC Translation Services" goes before "ABC".
    return sorted({p for p in patterns if p}, key=len, reverse=True)


def mask_name(name, client, for_text=False):
    """``name`` with the client's identity replaced by their code."""
    name = str(name or "")
    if client is None or not name:
        return name
    for pattern in identity_terms(client, for_text=for_text):
        name = re.sub(pattern, client.code, name, flags=re.IGNORECASE)
    return name


def remask_names(client):
    """Mask every stored file name of ``client`` against the identity they have now.

    A name is masked when a file arrives, against what is known of the client then. A client who wrote with no profile name
    ("Acme Holdings PO 2291.pdf") has nothing to mask against, so the name is stored as sent; when the admin later writes the
    client's name down, the names already stored have to follow, or a translator reads the company in a file name the
    download then calls by the code.
    """
    from .models import ChatAttachment, MessageAttachment, OutboundAttachment

    changed = 0
    for rows, start in (
        (MessageAttachment.objects.filter(message__client=client), lambda a: a.raw_name or a.original_name),
        (OutboundAttachment.objects.filter(message__client=client), lambda a: a.original_name),
        (ChatAttachment.objects.filter(origin_client=client), lambda a: a.original_name),
        (ChatAttachment.objects.filter(message__room__client=client, origin_client__isnull=True), lambda a: a.original_name),
    ):
        for attachment in rows:
            masked = mask_name(start(attachment), client)[:250]
            if masked != attachment.original_name:
                attachment.original_name = masked
                attachment.save(update_fields=["original_name"])
                changed += 1
    return changed


# ---------------------------------------------------------------------------
# 2. Who may open what
# ---------------------------------------------------------------------------

def _task_open_to(user, task):
    """The task rule, plus the person an assignment is waiting on.

    Someone offered a job reads its files *before* accepting it - that is
    what the preview is for - and until they accept they are not the task's
    leader or translator yet, so ``can_view`` alone would say no.
    """
    if task is None:
        return False
    if task.can_view(user):
        return True
    # Only an offer still waiting for an answer: one that was declined, timed out or replaced is not a key to the job.
    from .models import AssignmentStatus

    return task.assignments.filter(assignee=user, status=AssignmentStatus.PENDING).exists()


def _ticked_for(task, attachment):
    """Is this attachment one of the files picked for the task? A task with none picked leaves the letter's files open to it
    (the older tasks, made before the operation chose)."""
    picked = {one.pk for one in task.source_files.all()}
    return not picked or attachment.pk in picked


def _inbound_open_to(user, attachment):
    message = attachment.message
    if user.is_admin_role:
        return True
    # The operation on the company line, a Sales person on their own -
    # visible_to holds both rules (lines.py).
    if user.is_operation or user.is_sales:
        if message.visible_to(user):
            return True
        if user.is_operation:
            return False
    tasks = [message.task] if message.task_id else []
    tasks += list(attachment.tasks.all())
    # The files the operation ticked for a job are the job's; the rest of the client's letter is not, whoever works the job.
    if any(_task_open_to(user, task) and _ticked_for(task, attachment) for task in tasks):
        return True
    # Relayed into a room the person is in (``ChatMessage.inbound``).
    for mirror in message.mirrors.select_related("room", "room__task"):
        room = mirror.room
        if room.can_access(user) and (not room.task_id or room.task.can_view(user)):
            return True
    return False


def _chat_open_to(user, attachment):
    room = attachment.message.room
    if not room.can_access(user):
        return False
    return not room.task_id or room.task.can_view(user)


def _outbound_open_to(user, attachment):
    if user.is_admin_role:
        return True
    # What was sent from a Sales line is that line's; the company's is the
    # operation's; from somebody's own address, theirs. Same split as the
    # conversations (lines.py).
    from . import lines

    sent = attachment.message
    if user.is_sales and sent.owner_id == user.pk:
        return True
    if user.is_operation and lines.sees(user, sent.owner_id, sent.channel):
        return True
    task = attachment.message.task if attachment.message.task_id else None
    return _task_open_to(user, task)


def _revision_open_to(user, revision):
    """The AI's corrected copy: the admin, and the leader of the task it was made for (``api_ai.revise``). Nobody else - not the
    translator whose work it corrects, not the operation."""
    if user.is_admin_role:
        return True
    task = revision.result.task
    return user.is_team_lead and task.team_lead_id == user.pk and task.can_view(user)


def _rows(model, name, *related):
    return list(model.objects.filter(file=name).select_related(*related)[:20])


def owner_of(name):
    """Every row that stores ``name``, as ``(kind, row)`` pairs.

    More than one on purpose: a forward points a chat attachment at the very
    file an inbound attachment already stores, and either row may be the one
    that lets this person in.
    """
    from .models import (
        Candidate, CandidateAnswer, CandidateTest, ChatAttachment,
        MessageAttachment, OutboundAttachment, User,
    )

    # A picture is a picture: the only row that can own a name under ``avatars/`` is a person's, so the eight other tables
    # (this is the hottest file on every page of the chats) are not asked.
    if name.startswith("avatars/"):
        return [("avatar", r) for r in User.objects.filter(avatar=name)[:1]]

    # Under ``revisions/`` only the AI's corrected copies are stored.
    if name.startswith("revisions/"):
        from .models import AIRevision

        return [("revision", r) for r in _rows(AIRevision, name, "result", "result__task")[:1]]

    found = []
    found += [("inbound", r) for r in _rows(MessageAttachment, name, "message", "message__task")]
    found += [("chat", r) for r in _rows(ChatAttachment, name, "message", "message__room")]
    found += [("outbound", r) for r in _rows(OutboundAttachment, name, "message", "message__task")]
    found += [("cv", r) for r in Candidate.objects.filter(cv=name)[:5]]
    found += [("answer", r) for r in CandidateAnswer.objects.filter(file=name)[:5]]
    found += [("test", r) for r in CandidateTest.objects.filter(assignment=name)[:5]]
    found += [("test", r) for r in CandidateTest.objects.filter(submission=name)[:5]]
    found += [("contract", r) for r in User.objects.filter(contract=name)[:5]]
    found += [("avatar", r) for r in User.objects.filter(avatar=name)[:5]]
    return found


def may_open(user, name):
    """``(True, (kind, row))`` when this person may read the stored file."""
    if user is None or not user.is_authenticated or not user.is_active:
        return False, None
    rows = owner_of(name)
    for kind, row in rows:
        if kind == "inbound" and _inbound_open_to(user, row):
            return True, (kind, row)
        if kind == "chat" and _chat_open_to(user, row):
            return True, (kind, row)
        if kind == "outbound" and _outbound_open_to(user, row):
            return True, (kind, row)
        if kind == "revision" and _revision_open_to(user, row):
            return True, (kind, row)
        if kind in ("cv", "answer") and user.can_recruit:
            return True, (kind, row)
        if kind == "test" and (user.can_recruit or (user.can_review_tests and row.reviewer_id in (None, user.pk))):
            # A reviewer opens their own tests and the ones nobody has taken: another reviewer's is not there for them.
            return True, (kind, row)
        if kind == "avatar" and name.startswith("avatars/"):
            # A colleague's face is for the colleagues: any signed-in person of the staff (a client has no account here, and
            # no payload that reaches one carries an address of this kind). The inactive were refused above. Only a file
            # stored as a picture: a row that points anywhere else (a client's document) opens nothing through this door.
            return True, (kind, row)
        if kind == "contract" and (
            user.is_admin_role or user.is_hr or row.pk == user.pk
        ):
            return True, (kind, row)
    # A file no row owns is nobody's but the admin's.
    if user.is_admin_role and not rows:
        return True, None
    return False, None


def client_of(kind, row):
    if kind == "inbound":
        return row.message.client
    if kind == "chat":
        return row.origin_client or row.message.room.relay_client
    if kind == "outbound":
        return row.message.client
    return None


def download_name(user, name, owner):
    """The file name the browser saves: the real one for who may see it."""
    fallback = posixpath.basename(name)
    if owner is None:
        return fallback
    kind, row = owner
    if kind == "test" and not user.can_recruit:
        # A reviewer is blind: the name a test file was uploaded under is the candidate's or HR's own.
        return "test" + posixpath.splitext(fallback)[1][:9]
    # Recruitment files are stored under a random name; the name they came with is on the row, for HR and the owner.
    if kind == "cv":
        return row.cv_name or fallback
    if kind == "answer":
        return row.file_name or fallback
    if kind == "test":
        return (row.submission_name if row.submission and row.submission.name == name else row.assignment_name) or fallback
    shown = getattr(row, "original_name", "") or fallback
    if kind == "inbound" and user.is_admin_role and getattr(row, "raw_name", ""):
        return row.raw_name
    if user.can_see_client_identity:
        return shown
    return mask_name(shown, client_of(kind, row))


def content_type(name):
    guessed, _ = mimetypes.guess_type(name)
    return guessed or "application/octet-stream"


#: What may open inside the page, by the type the extension says. Everything else is a download.
#:
#: The extension is the uploader's choice, and a browser decides what a type means: an XML type of any kind
#: (``application/xslt+xml``, ``application/mathml+xml``, ``image/svg+xml`` ...) is parsed as a document that can carry
#: script, and script that runs on our own site runs with the viewer's session. A list of the types known to be
#: dangerous is never complete; a list of the ones known to be inert is.
INLINE_TYPES = frozenset({
    "image/png", "image/jpeg", "image/gif", "image/webp", "application/pdf", "text/plain",
})
INLINE_FAMILIES = ("audio/", "video/")


def opens_inline(kind):
    """May a file of this content type be shown inside the page rather than downloaded?"""
    kind = (kind or "").split(";")[0].strip().lower()
    return kind in INLINE_TYPES or kind.startswith(INLINE_FAMILIES)


# ---------------------------------------------------------------------------
# 4. Previews - a document shown by its look, not only by its name
# ---------------------------------------------------------------------------
#
# Images and PDFs are drawn in the browser (an <img>, and pdf.js for a PDF's
# first page). A Word file cannot be drawn by a browser, so the server reads
# what it can out of the .docx itself - no converter, no new dependency: the
# thumbnail Word saves inside the file when there is one, and the opening
# paragraphs as text always.

WORD_SUFFIXES = (".docx", ".docm", ".dotx")
_THUMBS = ("docProps/thumbnail.jpeg", "docProps/thumbnail.jpg", "docProps/thumbnail.png")
PREVIEW_CHARS = 900


def _docx_parts(data):
    import io
    import zipfile

    try:
        archive = zipfile.ZipFile(io.BytesIO(data))
    except Exception:  # noqa: BLE001 - not a zip: an old .doc or a broken file
        return "", None
    with archive:
        names = set(archive.namelist())
        thumb = next((n for n in _THUMBS if n in names), None)
        thumb_bytes = archive.read(thumb) if thumb else None
        try:
            xml = archive.read("word/document.xml").decode("utf-8", errors="ignore")
        except KeyError:
            return "", thumb_bytes
    xml = xml.replace("</w:p>", "\n")
    xml = re.sub(r"<w:tab[^>]*/>", "\t", xml)
    xml = re.sub(r"<w:br[^>]*/>", "\n", xml)
    text = re.sub(r"<[^>]+>", "", xml)
    import html

    text = html.unescape(text)
    lines = [line.strip() for line in text.split("\n")]
    text = "\n".join(line for line in lines if line)
    return text[:PREVIEW_CHARS], thumb_bytes


def document_preview(name, data):
    """``{"text", "thumb"}`` for a Word file, read once and cached a day."""
    from django.core.cache import cache

    key = f"eagle:preview:{name}"
    found = cache.get(key)
    if found is not None:
        return found
    text, thumb = ("", None)
    if name.lower().endswith(WORD_SUFFIXES):
        text, thumb = _docx_parts(data)
    found = {"text": text, "thumb": bool(thumb)}
    cache.set(key, found, 86400)
    return found


def document_thumbnail(name, data):
    """The picture Word saved of the first page, as ``(bytes, type)``."""
    if not name.lower().endswith(WORD_SUFFIXES):
        return None, ""
    _text, thumb = _docx_parts(data)
    if not thumb:
        return None, ""
    kind = "image/png" if thumb[:4] == b"\x89PNG" else "image/jpeg"
    return thumb, kind
