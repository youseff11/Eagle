"""How many words was that file.

Payroll pays by production, so the number behind a task cannot be whatever
somebody types. This module reads it out of the files themselves.

Only the standard library is used, because the server runs Django and nothing
else. Every office format here is a zip of XML, so ``zipfile`` plus a careful
tag strip is enough.

**PDF is deliberately not attempted.** A text PDF can be half-read by inflating
its content streams, but subset fonts with custom encodings turn that into
plausible-looking nonsense, and a scan needs OCR. A wrong number that looks
right is worse than no number, so a PDF is reported as unsupported and the
count stays a human's to enter.

The trap worth knowing about: Word splits one word across several ``<w:r>``
runs whenever formatting or spell-check state changes, so "Hello" can be
stored as ``<w:t>Hel</w:t><w:t>lo</w:t>``. Replacing tags with a space would
count that as two words. Separators are therefore inserted for the boundaries
that really are boundaries - paragraph, cell, line break, tab - and every other
tag is removed, not spaced.
"""

import io
import re
import zipfile

#: A word is a run of letters or digits, optionally carrying separators that
#: sit *inside* a word rather than between two: the thousands comma in "3,200",
#: the decimal point in "1.25", the apostrophe in "don't", the hyphens in
#: "state-of-the-art". Anything with whitespace around it still splits, so the
#: Arabic comma between two words keeps them two.
#:
#: This was measured, not guessed. On a real Arabic document the bare
#: ``[^\W_]+`` pattern returned 826 where a whitespace split gives 795 -
#: nearly 4% high, because every "3,000" counted twice. With the joiners it
#: returns 801, inside a percent. The bonus bands sit at 3,000 and 3,800, so a
#: systematic 4% would push days across them for no reason anyone could explain.
WORD_RE = re.compile(r"[^\W_]+(?:[.,'\u2019\-/][^\W_]+)*", re.UNICODE)
TAG_RE = re.compile(r"<[^>]+>")

#: Reading a 60 MB file inside a web request would block it; a translation job
#: that large is not a word-count problem.
MAX_BYTES = 25 * 1024 * 1024

TEXT_SUFFIXES = (".txt", ".md", ".csv", ".tsv", ".json", ".srt", ".vtt")
MARKUP_SUFFIXES = (".html", ".htm", ".xml")


class Method:
    DOCX = "docx"
    XLSX = "xlsx"
    PPTX = "pptx"
    ODF = "odf"
    TEXT = "text"
    UNSUPPORTED = "unsupported"
    TOO_LARGE = "too_large"
    ERROR = "error"


#: Which members of each zip carry translatable text, and which closing tags
#: are real boundaries between words.
ZIP_FORMATS = {
    Method.DOCX: (
        (r"word/document\.xml", r"word/header\d*\.xml", r"word/footer\d*\.xml",
         r"word/footnotes\.xml", r"word/endnotes\.xml"),
        ("</w:p>", "</w:tc>", "<w:br/>", "<w:tab/>", "<w:cr/>"),
    ),
    Method.XLSX: (
        (r"xl/sharedStrings\.xml", r"xl/worksheets/sheet\d+\.xml"),
        ("</si>", "</c>", "</t>"),
    ),
    Method.PPTX: (
        (r"ppt/slides/slide\d+\.xml", r"ppt/notesSlides/notesSlide\d+\.xml"),
        ("</a:p>", "<a:br/>"),
    ),
    Method.ODF: ((r"content\.xml",), ("</text:p>", "</text:h>", "</table:table-cell>")),
}

SUFFIX_METHOD = {
    ".docx": Method.DOCX, ".docm": Method.DOCX,
    ".xlsx": Method.XLSX, ".xlsm": Method.XLSX,
    ".pptx": Method.PPTX,
    ".odt": Method.ODF, ".ods": Method.ODF, ".odp": Method.ODF,
}


def method_for(filename):
    name = (filename or "").lower()
    for suffix, method in SUFFIX_METHOD.items():
        if name.endswith(suffix):
            return method
    if name.endswith(TEXT_SUFFIXES) or name.endswith(MARKUP_SUFFIXES):
        return Method.TEXT
    return Method.UNSUPPORTED


def _untag(xml, breaks):
    """Insert the real boundaries, then remove every tag without a space."""
    for token in breaks:
        xml = xml.replace(token, "\n")
    # Self-closing breaks and tabs carry attributes in real documents.
    xml = re.sub(r"<w:(?:br|tab|cr)\b[^>]*/>", "\n", xml)
    xml = re.sub(r"<a:br\b[^>]*/>", "\n", xml)
    return TAG_RE.sub("", xml)


def _zip_text(raw, members, breaks):
    chunks = []
    with zipfile.ZipFile(io.BytesIO(raw)) as archive:
        names = archive.namelist()
        for pattern in members:
            for name in sorted(n for n in names if re.fullmatch(pattern, n)):
                chunks.append(_untag(archive.read(name).decode("utf-8", "ignore"), breaks))
    return "\n".join(chunks)


def extract(raw, filename):
    """Return ``(method, text)``. An unreadable file yields empty text."""
    if raw is None:
        return Method.ERROR, ""
    if len(raw) > MAX_BYTES:
        return Method.TOO_LARGE, ""

    method = method_for(filename)
    try:
        if method in ZIP_FORMATS:
            members, breaks = ZIP_FORMATS[method]
            return method, _zip_text(raw, members, breaks)
        if method == Method.TEXT:
            text = raw.decode("utf-8", "ignore")
            if (filename or "").lower().endswith(MARKUP_SUFFIXES):
                # Here a tag really is a boundary: markup separates words.
                text = TAG_RE.sub(" ", text)
            return method, text
    except Exception:
        # A corrupt or password-protected file is not a reason to fail the
        # upload it arrived with.
        return Method.ERROR, ""
    return Method.UNSUPPORTED, ""


def count_text(text):
    return len(WORD_RE.findall(text or ""))


def count_bytes(raw, filename):
    method, text = extract(raw, filename)
    return method, count_text(text)


def count_file(django_file, filename=""):
    """Count one stored attachment. Never raises."""
    name = filename or getattr(django_file, "name", "")
    if method_for(name) == Method.UNSUPPORTED:
        # Do not pull a PDF down from the CDN just to learn it cannot be read.
        return Method.UNSUPPORTED, 0
    try:
        django_file.open("rb")
        raw = django_file.read()
    except Exception:
        return Method.ERROR, 0
    finally:
        try:
            django_file.close()
        except Exception:
            pass
    return count_bytes(raw, name)


# ---------------------------------------------------------------------------
# Task level: the client's file on one side, the translator's on the other
# ---------------------------------------------------------------------------

def _sum_attachments(attachments):
    """Return ``(words, method, names)`` across a set of attachments.

    The method reported is the worst one that mattered: if any readable file
    was counted the result is that format, but an unsupported file among them
    is surfaced so nobody reads a partial total as a complete one.
    """
    total = 0
    methods = set()
    counted, skipped = [], []
    for attachment in attachments:
        name = attachment.original_name or attachment.file.name.rsplit("/", 1)[-1]
        method, words = count_file(attachment.file, name)
        methods.add(method)
        if method in (Method.UNSUPPORTED, Method.ERROR, Method.TOO_LARGE) or words == 0:
            skipped.append(name)
            continue
        total += words
        counted.append(name)
    if not counted:
        method = Method.UNSUPPORTED if methods else Method.ERROR
    else:
        method = Method.TEXT if methods == {Method.TEXT} else sorted(methods - {
            Method.UNSUPPORTED, Method.ERROR, Method.TOO_LARGE
        })[0]
    return total, method, counted, skipped


def source_attachments(task):
    """The files the client sent, through the messages this task came from."""
    from .models import MessageAttachment

    return MessageAttachment.objects.filter(message__task=task).select_related("message")


def translated_attachments(task):
    """The files the translator handed over, wherever they put them.

    Tagged onto the message for a task running under the current shape, or in
    the task's own old room for one that predates it. Both answer, so a job
    caught half-way across the change still counts.
    """
    from django.db.models import Q

    from .models import ChatAttachment

    if not task.translator_id:
        return []
    return (
        ChatAttachment.objects
        .filter(
            (Q(message__task=task) | Q(message__room__task=task))
            & Q(message__sender_id=task.translator_id)
        )
        .order_by("-id")[:10]
    )


def recount_task(task, save=True):
    """Read both sides, then decide whether the number can stand on its own.

    The source file is what payroll uses: the client sent it, so the person
    whose bonus depends on it cannot inflate it. The translated file is counted
    anyway and shown next to it, because the gap between them is the signal -
    a translation that is half or double its source is either unfinished or
    padded, and that is a question for a human, not a rule.
    """
    from .models import PayrollSettings, WordCountState

    conf = PayrollSettings.load()
    source_words, source_method, source_files, source_skipped = _sum_attachments(
        source_attachments(task)
    )
    translated_words, translated_method, translated_files, translated_skipped = (
        _sum_attachments(translated_attachments(task))
    )

    task.source_words = source_words
    task.translated_words = translated_words
    task.source_word_method = source_method
    task.translated_word_method = translated_method

    notes = []
    if source_skipped:
        notes.append("مصدر مش مقروء: " + ", ".join(source_skipped[:3]))
    if translated_skipped:
        notes.append("ترجمة مش مقروءة: " + ", ".join(translated_skipped[:3]))

    if not source_words and not translated_words:
        state = WordCountState.MANUAL_NEEDED
        notes.insert(0, "مفيش ملف يتقرا - اكتب العدد بإيدك")
    elif not source_words or not translated_words:
        # Only one side readable: usable, but there is nothing to check it
        # against, so it does not get to walk into payroll unseen.
        state = WordCountState.REVIEW
        task.word_count = source_words or translated_words
        notes.insert(0, "جهة واحدة بس اتقرت - محتاجة تأكيد")
    else:
        gap = abs(translated_words - source_words) / source_words * 100
        if gap > conf.word_count_gap_percent:
            state = WordCountState.REVIEW
            notes.insert(0, f"الفرق بين المصدر والترجمة {gap:.0f}%")
        else:
            state = WordCountState.AUTO
            task.word_count = source_words

    task.word_count_state = state
    task.word_count_note = " · ".join(notes)[:250]
    if save:
        task.save(update_fields=[
            "word_count", "source_words", "translated_words",
            "source_word_method", "translated_word_method",
            "word_count_state", "word_count_note", "updated_at",
        ])
    return task


def confirm_task(task, user, words=None, use="source"):
    """A human settles it. ``words`` wins; otherwise pick a counted side."""
    from .models import AuditLog, WordCountState

    if words is not None:
        task.word_count = max(0, int(words))
        source = "manual"
    else:
        task.word_count = (
            task.translated_words if use == "translated" else task.source_words
        )
        source = use
    task.word_count_state = WordCountState.CONFIRMED
    task.save(update_fields=["word_count", "word_count_state", "updated_at"])
    AuditLog.objects.create(
        actor=user, action="task.word_count.confirm", target=task.code,
        detail=f"{task.word_count} ({source})",
    )
    return task
