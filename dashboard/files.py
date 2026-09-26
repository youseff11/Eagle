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


def identity_terms(client):
    """The regex pieces that identify this client in a file name."""
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
        if len(local) >= 3:
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


def mask_name(name, client):
    """``name`` with the client's identity replaced by their code."""
    name = str(name or "")
    if client is None or not name:
        return name
    for pattern in identity_terms(client):
        name = re.sub(pattern, client.code, name, flags=re.IGNORECASE)
    return name


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
    return task.assignments.filter(assignee=user).exists()


def _inbound_open_to(user, attachment):
    message = attachment.message
    if user.is_admin_role:
        return True
    if user.is_operation:
        return message.visible_to(user)
    tasks = [message.task] if message.task_id else []
    tasks += list(attachment.tasks.all())
    if any(_task_open_to(user, task) for task in tasks):
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
    if user.is_admin_role or user.is_operation:
        return True
    task = attachment.message.task if attachment.message.task_id else None
    return _task_open_to(user, task)


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

    found = []
    found += [("inbound", r) for r in _rows(MessageAttachment, name, "message", "message__task")]
    found += [("chat", r) for r in _rows(ChatAttachment, name, "message", "message__room")]
    found += [("outbound", r) for r in _rows(OutboundAttachment, name, "message", "message__task")]
    found += [("cv", r) for r in Candidate.objects.filter(cv=name)[:5]]
    found += [("answer", r) for r in CandidateAnswer.objects.filter(file=name)[:5]]
    found += [("test", r) for r in CandidateTest.objects.filter(assignment=name)[:5]]
    found += [("test", r) for r in CandidateTest.objects.filter(submission=name)[:5]]
    found += [("contract", r) for r in User.objects.filter(contract=name)[:5]]
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
        if kind in ("cv", "answer") and user.can_recruit:
            return True, (kind, row)
        if kind == "test" and (user.can_recruit or user.can_review_tests):
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
    shown = getattr(row, "original_name", "") or fallback
    if kind == "inbound" and user.is_admin_role and getattr(row, "raw_name", ""):
        return row.raw_name
    if user.can_see_client_identity:
        return shown
    return mask_name(shown, client_of(kind, row))


def content_type(name):
    guessed, _ = mimetypes.guess_type(name)
    return guessed or "application/octet-stream"


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
