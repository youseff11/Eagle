"""Optional AI review of a finished translation.

The check is advisory only: it reports what looks wrong and where, it never
rewrites the translation. It is disabled unless the admin turns it on and
stores a Claude API key in the admin panel.
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


def _call_claude(conf, prompt, documents=None):
    content = prompt
    if documents:
        content = list(documents) + [{"type": "text", "text": prompt}]
    payload = {
        "model": conf.claude_model or "claude-sonnet-4-5",
        # Every issue now carries two quotes and an explanation.
        "max_tokens": 8000,
        "system": SYSTEM_PROMPT,
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
        body = json.loads(response.read().decode("utf-8"))
    parts = [block.get("text", "") for block in body.get("content", []) if block.get("type") == "text"]
    return "".join(parts).strip()


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
