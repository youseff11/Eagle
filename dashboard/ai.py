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

SYSTEM_PROMPT = (
    "You are a senior translation quality reviewer for a translation agency. "
    "You NEVER rewrite, correct or produce a corrected translation. "
    "You only report problems you can point to.\n"
    "Given a SOURCE text and its TRANSLATION, list concrete issues: mistranslations, "
    "omissions, additions, untranslated segments, numbers/dates/names that do not match, "
    "terminology inconsistency, grammar and spelling errors, formatting problems, and any "
    "violation of the client requirements provided.\n"
    "Reply with STRICT JSON only, no markdown fences, using this shape:\n"
    '{"summary_en": "...", "summary_ar": "...", "issues": [{"location": "where it is '
    '(quote a short snippet or a line/paragraph reference)", "issue_en": "what is wrong", '
    '"issue_ar": "الوصف بالعربي", "severity": "low|medium|high"}]}\n'
    "If nothing is wrong, return an empty issues array. Never include a corrected version."
)


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

def _call_claude(conf, prompt):
    payload = {
        "model": conf.claude_model or "claude-sonnet-4-5",
        "max_tokens": 3000,
        "system": SYSTEM_PROMPT,
        "messages": [{"role": "user", "content": prompt}],
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
    with net.urlopen(request, timeout=120) as response:
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


def _review(conf, task, source_text, translated_text, requirements):
    """Call the model and return the fields to store. Never raises.

    Split out of :func:`run_check` so the same call can either create a row
    (somebody pressed the button) or fill one that is already there (the
    automatic check, which writes its row before it starts).
    """
    if not translated_text.strip():
        return {
            "status": AICheckResult.Status.ERROR,
            "error_message": "No translated text to review.",
        }

    prompt = (
        f"Task: {task.code} — {task.title}\n"
        f"Source language: {task.source_lang or 'unknown'}\n"
        f"Target language: {task.target_lang or 'unknown'}\n"
        f"Client requirements:\n{requirements or 'none'}\n\n"
        f"=== SOURCE ===\n{source_text[:MAX_CHARS] or '(not provided)'}\n\n"
        f"=== TRANSLATION ===\n{translated_text[:MAX_CHARS]}\n"
    )

    try:
        raw = _call_claude(conf, prompt)
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

    issues = data.get("issues") or []
    summary = data.get("summary_ar") or data.get("summary_en") or ""
    if data.get("summary_en") and data.get("summary_ar"):
        summary = f"{data['summary_ar']}\n{data['summary_en']}"

    return {
        "status": AICheckResult.Status.ISSUES if issues else AICheckResult.Status.CLEAN,
        "summary": summary,
        "issues": issues,
        "model_used": conf.claude_model,
        "error_message": "",
    }


def run_check(task, user, source_text, translated_text, requirements=""):
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

    fields = _review(conf, task, source_text, translated_text, requirements)
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


def requirements_text(task):
    return "\n".join(
        f"- [{r.get_kind_display()}] {r.text}"
        for r in task.client.requirements.all()[:30]
    )


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
        fields = _review(
            AppSettings.load(), task, source, translated, requirements_text(task)
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
            level="warning", url=f"/tasks/{task.code}/", task=task,
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
            level="warning", url=f"/tasks/{task.code}/", sound=True, task=task,
        )
    else:
        services.notify(
            task.team_lead,
            title_ar="الـAI مالقاش مشاكل",
            title_en="The AI found nothing",
            body_ar=f"فحص {task.code} عدّى نضيف - المراجعة البشرية لسه مطلوبة.",
            body_en=f"{task.code} came back clean - your own review still stands.",
            level="info", url=f"/tasks/{task.code}/", task=task,
        )
