"""Optional AI review of a finished translation.

The check is advisory only: it reports what looks wrong and where, it never
rewrites the translation. It is disabled unless the admin turns it on and
stores a Claude API key in the admin panel.

The one thing it writes is a *copy*: when the team leader accepts some of the
notes (or all of them), :func:`start_revision` makes a second file with only
those corrections applied. The translator's own file is never touched, and
nothing is applied that the leader did not accept.
"""

import json
import logging
import re
import threading
import urllib.error
import urllib.request
import zipfile

from . import net
from .models import AICheckResult, AppSettings

logger = logging.getLogger(__name__)

API_URL = "https://api.anthropic.com/v1/messages"
API_VERSION = "2023-06-01"
MAX_CHARS = 24000

#: Files the model reads itself, as they are - a PDF (text or scanned) or a
#: picture of a page. No PDF library on our side: Django stays the only
#: dependency, and the model reads a scan that no text extractor could.
DOCUMENT_TYPES = {".pdf": "application/pdf"}
IMAGE_TYPES = {
    ".png": "image/png", ".jpg": "image/jpeg", ".jpeg": "image/jpeg",
    ".webp": "image/webp", ".gif": "image/gif",
}
#: What goes into one request. The API takes up to 32 MB and 100 PDF pages;
#: base64 adds a third, so the raw files stop well short of that.
MAX_DOCUMENT_BYTES = 18 * 1024 * 1024
MAX_DOCUMENTS = 6

#: The review is a side-by-side comparison of meaning (28/09/2026): walk the
#: source, find where each part landed in the translation, and say where the
#: two do not say the same thing - quoting both. Still never a rewritten
#: translation: ``correct_meaning`` explains what the source says, the
#: translator writes the fix.
SYSTEM_PROMPT = (
    "You are a senior bilingual translation reviewer for a translation agency.\n"
    "Your job is to check whether the TRANSLATION says what the SOURCE says.\n"
    "Method: go through the SOURCE from start to end, segment by segment "
    "(sentence, table cell, heading, list item). For each segment find its "
    "counterpart in the TRANSLATION and compare the MEANING, not the wording. "
    "Then check the other way, for anything in the translation that is not in the source.\n"
    "Report every place where they differ: wrong meaning (mistranslation), a part left "
    "out (omission), something added (addition), text left untranslated, numbers, dates, "
    "amounts, names, IDs or units that do not match, wrong or inconsistent terminology, "
    "grammar or spelling errors in the translation, broken formatting, and any breach "
    "of the client requirements given.\n"
    "Do not report style preferences where the meaning is right.\n"
    "You NEVER produce a corrected or rewritten translation. For each issue you quote "
    "the source and the translation exactly as they are, and explain in plain words "
    "what the source actually means.\n"
    "If the SOURCE is missing, say so in the summary and set source_seen to false; "
    "then only check the translation on its own.\n"
    "Reply with STRICT JSON only, no markdown fences, in this shape:\n"
    '{"verdict": "accurate|minor_issues|major_issues", "source_seen": true, '
    '"summary_ar": "حكم عام في سطرين بالعربي", "summary_en": "two-line verdict", '
    '"issues": [{"category": "mistranslation|omission|addition|untranslated|number|name|'
    'terminology|grammar|formatting|requirement", "severity": "low|medium|high", '
    '"location": "page/paragraph/row", '
    '"source_excerpt": "the source words, quoted exactly", '
    '"translation_excerpt": "what the translation says there, quoted exactly (empty if omitted)", '
    '"issue_ar": "إيه الغلط بالعربي", "issue_en": "what is wrong", '
    '"correct_meaning_ar": "المعنى الصحيح في الأصل بالعربي - شرح مش ترجمة بديلة"}]}\n'
    "Severity: high = the meaning, a number, a name or a legal/medical fact is wrong or "
    "missing; medium = misleading or clearly wrong wording; low = grammar, spelling, "
    "formatting. If the translation is accurate, return an empty issues array."
)

#: Human words for the categories the model reports.
CATEGORY_LABELS = {
    "mistranslation": ("ترجمة غلط", "Mistranslation"),
    "omission": ("حاجة ناقصة", "Omission"),
    "addition": ("حاجة زيادة", "Addition"),
    "untranslated": ("متترجمتش", "Untranslated"),
    "number": ("رقم/تاريخ", "Number/date"),
    "name": ("اسم", "Name"),
    "terminology": ("مصطلح", "Terminology"),
    "grammar": ("لغة/إملاء", "Grammar"),
    "formatting": ("تنسيق", "Formatting"),
    "requirement": ("طلب العميل", "Client requirement"),
}
VERDICT_LABELS = {
    "accurate": "الترجمة مطابقة للأصل.",
    "minor_issues": "الترجمة مطابقة في المعظم، وفيها ملاحظات بسيطة.",
    "major_issues": "فيه أخطاء في المعنى لازم تتصلح قبل التسليم.",
}
SOURCE_MISSING_AR = "تنبيه: الملف الأصلي ماوصلش للفحص، فالـAI راجع الترجمة لوحدها من غير مقارنة."


# ---------------------------------------------------------------------------
# Text extraction
# ---------------------------------------------------------------------------

_TAG_RE = re.compile(r"<[^>]+>")


def extract_text(django_file, name=""):
    """Best-effort plain-text extraction from an uploaded attachment."""
    name = (name or getattr(django_file, "name", "")).lower()
    try:
        django_file.open("rb")
        raw = django_file.read()
    except Exception:
        return ""
    finally:
        try:
            django_file.close()
        except Exception:
            pass

    if name.endswith(".docx"):
        return _docx_text(raw)
    if name.endswith((".txt", ".md", ".csv", ".tsv", ".json", ".srt", ".vtt", ".html", ".htm")):
        text = raw.decode("utf-8", errors="ignore")
        if name.endswith((".html", ".htm")):
            text = _TAG_RE.sub(" ", text)
        return text
    return ""


def _docx_text(raw):
    import io

    try:
        with zipfile.ZipFile(io.BytesIO(raw)) as archive:
            xml = archive.read("word/document.xml").decode("utf-8", errors="ignore")
    except Exception:
        return ""
    xml = xml.replace("</w:p>", "\n")
    xml = re.sub(r"<w:tab[^>]*/>", "\t", xml)
    return _TAG_RE.sub("", xml)


# ---------------------------------------------------------------------------
# Claude call
# ---------------------------------------------------------------------------

def media_type_of(name):
    """The API media type for a file the model can read itself, or ``""``."""
    lowered = (name or "").lower()
    for suffix, kind in list(DOCUMENT_TYPES.items()) + list(IMAGE_TYPES.items()):
        if lowered.endswith(suffix):
            return kind
    return ""


def read_document(django_file, name=""):
    """``{"name", "media_type", "data"}`` for a PDF or an image, else ``None``."""
    name = name or getattr(django_file, "name", "")
    kind = media_type_of(name)
    if not kind:
        return None
    try:
        django_file.open("rb")
        data = django_file.read()
    except Exception:
        return None
    finally:
        try:
            django_file.close()
        except Exception:
            pass
    if not data:
        return None
    return {"name": name.rsplit("/", 1)[-1], "media_type": kind, "data": data}


def _document_blocks(label, documents):
    """Content blocks for the files, each introduced by what it is."""
    import base64

    blocks = []
    for doc in documents:
        encoded = base64.standard_b64encode(doc["data"]).decode("ascii")
        blocks.append({"type": "text", "text": f"=== {label} FILE: {doc['name']} ==="})
        if doc["media_type"] == "application/pdf":
            blocks.append({
                "type": "document",
                "source": {"type": "base64", "media_type": "application/pdf", "data": encoded},
                "title": f"{label}: {doc['name']}"[:200],
            })
        else:
            blocks.append({
                "type": "image",
                "source": {"type": "base64", "media_type": doc["media_type"], "data": encoded},
            })
    return blocks


def _fit(source_docs, translated_docs):
    """Keep the files inside one request: the translation first, then the
    source, newest kept, and a note of what was left out."""
    kept_src, kept_tr, dropped, total = [], [], [], 0
    for doc, bucket in [(d, kept_tr) for d in translated_docs] + [(d, kept_src) for d in source_docs]:
        size = len(doc["data"])
        if len(kept_src) + len(kept_tr) >= MAX_DOCUMENTS or total + size > MAX_DOCUMENT_BYTES:
            dropped.append(doc["name"])
            continue
        bucket.append(doc)
        total += size
    return kept_src, kept_tr, dropped


def _post(conf, system, prompt, documents, max_tokens):
    """One call to the messages API; the decoded answer."""
    content = prompt
    if documents:
        content = list(documents) + [{"type": "text", "text": prompt}]
    payload = {
        "model": conf.claude_model or "claude-sonnet-4-5",
        "max_tokens": max_tokens,
        "system": system,
        "messages": [{"role": "user", "content": content}],
    }
    request = urllib.request.Request(
        API_URL,
        data=json.dumps(payload).encode("utf-8"),
        headers={
            "content-type": "application/json",
            "x-api-key": conf.claude_api_key,
            "anthropic-version": API_VERSION,
        },
        method="POST",
    )
    # A long PDF takes the model a while to read.
    with net.urlopen(request, timeout=240 if documents else 120) as response:
        return json.loads(response.read().decode("utf-8"))


def _text_of(body):
    parts = [block.get("text", "") for block in body.get("content", []) if block.get("type") == "text"]
    return "".join(parts).strip()


def _call_claude(conf, prompt, documents=None):
    # Every issue now carries two quotes and an explanation.
    return _text_of(_post(conf, SYSTEM_PROMPT, prompt, documents, 8000))


def _parse(text):
    cleaned = text.strip()
    if cleaned.startswith("```"):
        cleaned = re.sub(r"^```[a-zA-Z]*\s*", "", cleaned)
        cleaned = re.sub(r"\s*```$", "", cleaned)
    start, end = cleaned.find("{"), cleaned.rfind("}")
    if start == -1 or end == -1:
        raise ValueError("model did not return JSON")
    return json.loads(cleaned[start:end + 1])


def _review(conf, task, source_text, translated_text, requirements,
            source_docs=(), translated_docs=()):
    """Call the model and return the fields to store. Never raises.

    Split out of :func:`run_check` so the same call can either create a row
    (somebody pressed the button) or fill one that is already there (the
    automatic check, which writes its row before it starts).

    ``source_docs`` / ``translated_docs`` are PDFs and page images
    (``read_document``) the model reads itself - text the server could not
    pull out of them (28/09/2026).
    """
    source_docs, translated_docs, dropped = _fit(source_docs or [], translated_docs or [])
    if not translated_text.strip() and not translated_docs:
        return {
            "status": AICheckResult.Status.ERROR,
            "error_message": "No translated text to review.",
        }

    attached = ""
    if source_docs or translated_docs:
        attached = (
            "The SOURCE and TRANSLATION files attached above are part of the "
            "material - read them as you would the text below.\n"
        )
    if dropped:
        attached += "Not attached (too large): " + ", ".join(dropped) + "\n"
    prompt = (
        f"Task: {task.code} — {task.title}\n"
        f"Source language: {task.source_lang or 'unknown'}\n"
        f"Target language: {task.target_lang or 'unknown'}\n"
        f"Client requirements:\n{requirements or 'none'}\n\n"
        f"{attached}"
        f"=== SOURCE ===\n{source_text[:MAX_CHARS] or ('(see the SOURCE files above)' if source_docs else '(not provided)')}\n\n"
        f"=== TRANSLATION ===\n{translated_text[:MAX_CHARS] or '(see the TRANSLATION files above)'}\n"
    )
    documents = (
        _document_blocks("SOURCE", source_docs)
        + _document_blocks("TRANSLATION", translated_docs)
    )

    try:
        raw = _call_claude(conf, prompt, documents)
        data = _parse(raw)
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="ignore")[:500]
        return {
            "status": AICheckResult.Status.ERROR,
            "error_message": f"HTTP {exc.code}: {detail}",
            "model_used": conf.claude_model,
        }
    except Exception as exc:  # noqa: BLE001 - surfaced to the UI
        return {
            "status": AICheckResult.Status.ERROR,
            "error_message": str(exc)[:500],
            "model_used": conf.claude_model,
        }

    issues = [i for i in (data.get("issues") or []) if isinstance(i, dict)]
    for issue in issues:
        labels = CATEGORY_LABELS.get(issue.get("category") or "")
        if labels:
            issue["category_ar"], issue["category_en"] = labels
    lines = []
    source_seen = data.get("source_seen")
    if source_seen is False or (not source_text.strip() and not source_docs):
        lines.append(SOURCE_MISSING_AR)
    verdict = VERDICT_LABELS.get(data.get("verdict") or "")
    if verdict:
        lines.append(verdict)
    if data.get("summary_ar"):
        lines.append(data["summary_ar"])
    if data.get("summary_en"):
        lines.append(data["summary_en"])
    summary = "\n".join(lines)

    return {
        "status": AICheckResult.Status.ISSUES if issues else AICheckResult.Status.CLEAN,
        "summary": summary,
        "issues": issues,
        "model_used": conf.claude_model,
        "error_message": "",
    }


def run_check(task, user, source_text, translated_text, requirements="",
              source_docs=(), translated_docs=()):
    """Run the review and persist an :class:`AICheckResult`."""
    conf = AppSettings.load()

    if not conf.ai_check_enabled:
        return AICheckResult.objects.create(
            task=task, requested_by=user, status=AICheckResult.Status.ERROR,
            error_message="AI check is disabled by the admin.",
        )
    if not conf.claude_api_key:
        return AICheckResult.objects.create(
            task=task, requested_by=user, status=AICheckResult.Status.ERROR,
            error_message="No Claude API key configured in the admin panel.",
        )

    fields = _review(conf, task, source_text, translated_text, requirements,
                     source_docs, translated_docs)
    return AICheckResult.objects.create(task=task, requested_by=user, **fields)


# ---------------------------------------------------------------------------
# The automatic check
#
# It runs when the translator hands the job over, not when somebody remembers
# to press a button - a quality gate nobody has to trigger is a quality gate.
# ---------------------------------------------------------------------------

def collect_texts(task):
    """Source and translation text for a task, read out of its own files.

    The translation is what the translator last put in the group; the source is
    what the client sent. Both are best-effort - a PDF or a scan reads as
    nothing, and the check then reports that instead of guessing.
    """
    from django.db.models import Q

    from . import wordcount
    from .models import ChatAttachment

    translated = ""
    if task.translator_id:
        # Wherever the translator put them: tagged onto the message for a task
        # running under the new shape, or in the task's own old room for one
        # that predates it.
        latest = ChatAttachment.objects.filter(
            (Q(message__task=task) | Q(message__room__task=task))
            & Q(message__sender=task.translator)
        ).order_by("-id")[:3]
        translated = "\n\n".join(
            extract_text(a.file, a.original_name) for a in latest
        ).strip()

    source = "\n\n".join(
        extract_text(a.file, a.original_name)
        for a in wordcount.source_attachments(task)
    ).strip()
    return source, translated


def _translated_rows(task):
    from django.db.models import Q

    from .models import ChatAttachment

    if not task.translator_id:
        return []
    return list(ChatAttachment.objects.filter(
        (Q(message__task=task) | Q(message__room__task=task))
        & Q(message__sender=task.translator)
    ).order_by("-id")[:3])


def collect_documents(task):
    """The PDFs and page images among the task's files, for the model to read.

    ``(source_docs, translated_docs)``. The same files ``collect_texts`` looks
    at; a Word or text file is read there as text, and a PDF or a picture is
    handed over whole here.
    """
    from . import wordcount

    translated = [
        doc for doc in (read_document(a.file, a.original_name) for a in _translated_rows(task))
        if doc
    ]
    source = [
        doc for doc in (
            read_document(a.file, a.original_name)
            for a in wordcount.source_attachments(task)
        )
        if doc
    ]
    return source, translated


def requirements_text(task):
    return "\n".join(
        f"- [{r.get_kind_display()}] {r.text}"
        for r in task.client.requirements.all()[:30]
    )


def is_old_format(result):
    """A check written before the side-by-side comparison (28/09/2026).

    Its notes carry no quotes of the source and the translation, and its
    summary no verdict - the ones worth running again.
    """
    if result is None or result.status not in (
        AICheckResult.Status.ISSUES, AICheckResult.Status.CLEAN,
    ):
        return False
    issues = [i for i in (result.issues or []) if isinstance(i, dict)]
    if issues:
        return not any("source_excerpt" in i or "translation_excerpt" in i for i in issues)
    summary = result.summary or ""
    markers = list(VERDICT_LABELS.values()) + [SOURCE_MISSING_AR]
    return not any(summary.startswith(m) for m in markers)


def recheck_now(task, notify_lead=False):
    """Run the check again, here and now, and return the new row.

    For the management command: no thread, so the command waits for it and
    can say how it went. ``None`` when the check is switched off, has no
    key, or one is already running on this task.
    """
    conf = AppSettings.load()
    if not conf.ai_check_enabled or not conf.claude_api_key:
        return None
    if task.ai_checks.filter(status=AICheckResult.Status.RUNNING).exists():
        return None
    row = AICheckResult.objects.create(
        task=task, requested_by=None, status=AICheckResult.Status.RUNNING,
        model_used=conf.claude_model,
    )
    return finish_check(row.pk, notify_lead=notify_lead)


def start_background_check(task):
    """Queue the automatic review and run it off the request thread.

    Returns the queued row, or ``None`` when there is nothing to run: the admin
    switched the check off, no key is stored, or one is already in flight.

    The row is written *before* the thread starts. The call can take a minute
    against an outside API, and the translator pressing "finished" must not sit
    through it - but a task page opened meanwhile still has to say what is
    happening, and a process recycled mid-call has to leave evidence rather
    than silence. ``run_ai_checks`` finishes whatever a dead process left.
    """
    conf = AppSettings.load()
    if not conf.ai_check_enabled or not conf.claude_api_key:
        return None
    if task.ai_checks.filter(status=AICheckResult.Status.RUNNING).exists():
        return None

    result = AICheckResult.objects.create(
        task=task, requested_by=None, status=AICheckResult.Status.RUNNING,
        model_used=conf.claude_model,
    )
    threading.Thread(
        target=finish_check, args=(result.pk,), daemon=True,
        name=f"ai-check-{task.code}",
    ).start()
    return result


def finish_check(result_pk, notify_lead=True):
    """Do the work for a row left in ``running``. Safe to call from anywhere."""
    from django.db import close_old_connections

    close_old_connections()
    try:
        result = AICheckResult.objects.select_related(
            "task", "task__client", "task__team_lead"
        ).get(pk=result_pk)
        task = result.task
        source, translated = collect_texts(task)
        source_docs, translated_docs = collect_documents(task)
        fields = _review(
            AppSettings.load(), task, source, translated, requirements_text(task),
            source_docs, translated_docs,
        )
        for name, value in fields.items():
            setattr(result, name, value)
        result.save()
        if notify_lead:
            _tell_the_team_leader(result)
        return result
    except Exception:  # noqa: BLE001 - a background thread must never escape
        logger.exception("AI check %s failed", result_pk)
        AICheckResult.objects.filter(pk=result_pk).update(
            status=AICheckResult.Status.ERROR,
            error_message="The check did not finish.",
        )
        return None
    finally:
        close_old_connections()


def _tell_the_team_leader(result):
    """The notes go to the person who has to act on them, unasked."""
    from . import services

    task = result.task
    if task.team_lead_id is None:
        return
    if result.status == AICheckResult.Status.ERROR:
        services.notify(
            task.team_lead,
            title_ar="فحص الـAI مخلصش",
            title_en="The AI check did not finish",
            body_ar=f"التاسك {task.code} - راجعها بنفسك.",
            body_en=f"Task {task.code} - review it yourself.",
            level="warning", url=f"/tasks/{task.code}/#aiNotes", task=task,
        )
        return
    count = result.issue_count
    if count:
        services.notify(
            task.team_lead,
            title_ar="ملاحظات الـAI جاهزة",
            title_en="AI notes are ready",
            body_ar=f"{count} ملاحظة على {task.code}.",
            body_en=f"{count} note(s) on {task.code}.",
            level="warning", url=f"/tasks/{task.code}/#aiNotes", sound=True, task=task,
        )
    else:
        services.notify(
            task.team_lead,
            title_ar="الـAI مالقاش مشاكل",
            title_en="The AI found nothing",
            body_ar=f"فحص {task.code} عدّى نضيف - المراجعة البشرية لسه مطلوبة.",
            body_en=f"{task.code} came back clean - your own review still stands.",
            level="info", url=f"/tasks/{task.code}/#aiNotes", task=task,
        )


# ---------------------------------------------------------------------------
# The revised copy
#
# The team leader reads the notes and accepts the ones that are right - some,
# or all. The model then applies exactly those to a copy of the translation and
# the copy is written as a new Word file. It is a copy: the translator's file
# stays as they handed it in, and a note nobody accepted is never applied.
# ---------------------------------------------------------------------------

REVISE_PROMPT = (
    "You are a senior bilingual translator correcting a translation for a translation agency.\n"
    "You are given the TRANSLATION and a numbered list of ACCEPTED CORRECTIONS that the team leader approved.\n"
    "Apply exactly those corrections to the translation and nothing else. Do not fix, improve, restyle or reorder "
    "anything that is not in the list, even if you notice other problems.\n"
    "Each correction quotes the translation words it is about and explains what the source means. Find those words "
    "in the translation and change only what that correction needs.\n"
    "Return the whole corrected translation as plain text, in the translation's own language, keeping its "
    "paragraph breaks, headings, numbering and tables as lines of text. No explanation, no markdown, no code "
    "fences, no notes before or after."
)
REVISE_MAX_TOKENS = 16000
#: The most corrections one revision may carry: a check never reports more than the box lists.
MAX_ACCEPTED = 50
#: Copies one check may have made, failed ones included.
MAX_REVISIONS_PER_CHECK = 10

_XML_BAD = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\ufffe\uffff]")
_RTL_LETTERS = re.compile(r"[\u0590-\u08ff\ufb1d-\ufdff\ufe70-\ufeff]")
_LETTERS = re.compile(r"[^\W\d_]", re.UNICODE)

_DOCX_TYPES = (
    '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
    '<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">'
    '<Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>'
    '<Default Extension="xml" ContentType="application/xml"/>'
    '<Override PartName="/word/document.xml" '
    'ContentType="application/vnd.openxmlformats-officedocument.wordprocessingml.document.main+xml"/>'
    "</Types>"
)
_DOCX_RELS = (
    '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
    '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
    '<Relationship Id="rId1" '
    'Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" '
    'Target="word/document.xml"/>'
    "</Relationships>"
)


def _is_rtl(text):
    """Mostly Arabic or Hebrew letters: the file is laid out right to left."""
    letters = len(_LETTERS.findall(text))
    return bool(letters) and len(_RTL_LETTERS.findall(text)) * 2 > letters


def build_docx(text):
    """A Word file (``bytes``) holding ``text``, one paragraph per line. No library: a .docx is a zip of three small parts."""
    import io
    from xml.sax.saxutils import escape

    rtl = _is_rtl(text)
    paragraph_props = "<w:pPr><w:bidi/></w:pPr>" if rtl else ""
    run_props = "<w:rPr><w:rtl/></w:rPr>" if rtl else ""
    paragraphs = []
    for line in _XML_BAD.sub("", text).replace("\r\n", "\n").replace("\r", "\n").split("\n"):
        line = escape(line.replace("\t", "    "))
        paragraphs.append(
            f'<w:p>{paragraph_props}<w:r>{run_props}<w:t xml:space="preserve">{line}</w:t></w:r></w:p>'
        )
    document = (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        '<w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main">'
        f'<w:body>{"".join(paragraphs)}</w:body></w:document>'
    )
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as archive:
        archive.writestr("[Content_Types].xml", _DOCX_TYPES)
        archive.writestr("_rels/.rels", _DOCX_RELS)
        archive.writestr("word/document.xml", document)
    return buffer.getvalue()


def accepted_indexes(check, raw):
    """The positions in ``check.issues`` that ``raw`` names, sorted and unique, or ``None`` when any is not a note."""
    issues = check.issues or []
    if not isinstance(raw, (list, tuple)) or len(raw) > MAX_ACCEPTED * 2:
        return None
    seen = set()
    for value in raw:
        if isinstance(value, bool) or not isinstance(value, int) or not 0 <= value < len(issues):
            return None
        if not isinstance(issues[value], dict):
            return None
        seen.add(value)
    return sorted(seen)


def _corrections_text(issues):
    lines = []
    for number, issue in enumerate(issues, start=1):
        lines.append(f"{number}. [{issue.get('severity') or 'medium'}] {issue.get('location') or ''}".rstrip())
        for label, key in (
            ("Translation says", "translation_excerpt"), ("Source says", "source_excerpt"),
            ("What is wrong", "issue_en"), ("What is wrong (ar)", "issue_ar"),
            ("What the source means (ar)", "correct_meaning_ar"),
        ):
            value = issue.get(key) or (issue.get("issue") if key == "issue_en" else "")
            if value:
                lines.append(f"   {label}: {value}")
    return "\n".join(lines)


def _call_reviser(conf, prompt, documents=None):
    """``(text, stop_reason)``: the model's corrected translation and whether it ran out of room writing it."""
    body = _post(conf, REVISE_PROMPT, prompt, documents, REVISE_MAX_TOKENS)
    return _text_of(body), body.get("stop_reason") or ""


def _revise(conf, task, translated_text, translated_docs, issues):
    """``(text, error)``: the translation with the accepted corrections applied. Never raises."""
    _src, translated_docs, dropped = _fit([], translated_docs or [])
    if not translated_text.strip() and not translated_docs:
        return "", "No translated text to correct."
    if len(translated_text) > MAX_CHARS:
        # Cutting it would hand back a file with the end of the translation missing.
        return "", "The translation is too long to be corrected in one go."
    if dropped:
        return "", "The translation file is too large to be read: " + ", ".join(dropped)
    attached = (
        "The TRANSLATION files attached above are the translation - read them as you would the text below.\n"
        if translated_docs else ""
    )
    prompt = (
        f"Task: {task.code}\n"
        f"Source language: {task.source_lang or 'unknown'}\n"
        f"Target language: {task.target_lang or 'unknown'}\n\n"
        f"=== ACCEPTED CORRECTIONS ===\n{_corrections_text(issues)}\n\n"
        f"{attached}"
        f"=== TRANSLATION ===\n{translated_text or '(see the TRANSLATION files above)'}\n"
    )
    documents = _document_blocks("TRANSLATION", translated_docs)
    try:
        text, stop = _call_reviser(conf, prompt, documents)
    except urllib.error.HTTPError as exc:
        return "", f"HTTP {exc.code}: {exc.read().decode('utf-8', errors='ignore')[:500]}"
    except Exception as exc:  # noqa: BLE001 - surfaced to the UI
        return "", str(exc)[:500]
    text = re.sub(r"^```[a-zA-Z]*\s*|\s*```$", "", text.strip())
    if stop == "max_tokens":
        return "", "The corrected translation was cut short: it is too long for one go."
    if not text.strip():
        return "", "The model returned nothing."
    return text, ""


def start_revision(check, user, indexes):
    """Queue the corrected copy and run it off the request thread. ``(row, "")`` or ``(None, error)``.

    Errors: ``off`` (the check is switched off or has no key), ``no_notes`` (this check found none), ``nothing_accepted``,
    ``running`` (a copy of this check is being made already), ``limit`` (this check has had its share of copies).
    """
    from .models import AIRevision

    conf = AppSettings.load()
    if not conf.ai_check_enabled or not conf.claude_api_key:
        return None, "off"
    if check.status != AICheckResult.Status.ISSUES:
        return None, "no_notes"
    if not indexes:
        return None, "nothing_accepted"
    from datetime import timedelta

    from django.db import transaction
    from django.utils import timezone

    # The check's row is locked while this decides, so two presses (a double click) make one copy, not two.
    with transaction.atomic():
        AICheckResult.objects.select_for_update().filter(pk=check.pk).first()
        # A copy whose process died stays "running" for ever: after a while it is written down as failed and stops blocking.
        check.revisions.filter(
            status=AIRevision.Status.RUNNING,
            created_at__lt=timezone.now() - timedelta(minutes=AIRevision.STALE_MINUTES),
        ).update(status=AIRevision.Status.ERROR, error_message="The file was not made.")
        if check.revisions.filter(status=AIRevision.Status.RUNNING).exists():
            return None, "running"
        # Every copy is a paid call with the whole translation: a check that has had this many is run again instead.
        if check.revisions.count() >= MAX_REVISIONS_PER_CHECK:
            return None, "limit"
        row = AIRevision.objects.create(
            result=check, requested_by=user, accepted=list(indexes),
            status=AIRevision.Status.RUNNING, model_used=conf.claude_model,
        )
    threading.Thread(
        target=finish_revision, args=(row.pk,), daemon=True, name=f"ai-revision-{check.task.code}",
    ).start()
    return row, ""


def finish_revision(row_pk):
    """Make the file for a row left in ``running``. Safe to call from anywhere; never raises."""
    from django.core.files.base import ContentFile
    from django.db import close_old_connections

    from .models import AIRevision

    close_old_connections()
    try:
        row = AIRevision.objects.select_related("result", "result__task", "requested_by").get(pk=row_pk)
        task = row.result.task
        issues = [row.result.issues[i] for i in row.accepted if i < len(row.result.issues)]
        _source, translated = collect_texts(task)
        _source_docs, translated_docs = collect_documents(task)
        text, problem = _revise(AppSettings.load(), task, translated, translated_docs, issues)
        if problem:
            row.status = AIRevision.Status.ERROR
            row.error_message = problem
            row.save(update_fields=["status", "error_message"])
        else:
            data = build_docx(text)
            row.original_name = f"{task.code}-revised.docx"
            row.file.save(row.original_name, ContentFile(data), save=False)
            row.size = len(data)
            row.status = AIRevision.Status.DONE
            row.save(update_fields=["file", "original_name", "size", "status"])
        _tell_who_asked(row)
        return row
    except Exception:  # noqa: BLE001 - a background thread must never escape
        logger.exception("AI revision %s failed", row_pk)
        AIRevision.objects.filter(pk=row_pk).update(
            status=AIRevision.Status.ERROR, error_message="The file was not made.",
        )
        return None
    finally:
        close_old_connections()


def _tell_who_asked(row):
    from . import services

    who, task = row.requested_by, row.result.task
    if who is None:
        return
    if row.status == row.Status.DONE:
        services.notify(
            who,
            title_ar="ملف التعديلات جاهز",
            title_en="The corrected file is ready",
            body_ar=f"اتعمل ملف جديد على {task.code} بالتعديلات اللي قبلتها ({len(row.accepted)}).",
            body_en=f"A new file for {task.code} with the {len(row.accepted)} correction(s) you accepted.",
            level="success", url=f"/tasks/{task.code}/#aiNotes", task=task,
        )
    else:
        services.notify(
            who,
            title_ar="ملف التعديلات مااتعملش",
            title_en="The corrected file was not made",
            body_ar=f"ماقدرناش نعمل ملف التعديلات على {task.code}. جرّب تاني أو عدّلها بنفسك.",
            body_en=f"The corrected file for {task.code} could not be made. Try again or correct it yourself.",
            level="warning", url=f"/tasks/{task.code}/#aiNotes", task=task,
        )
