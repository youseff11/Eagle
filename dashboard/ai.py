"""Optional AI review of a finished translation.

The check is advisory only: it reports what looks wrong and where, it never
rewrites the translation. It is disabled unless the admin turns it on and
stores a Claude API key in the admin panel.
"""

import json
import re
import urllib.error
import urllib.request
import zipfile

from .models import AICheckResult, AppSettings

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
    with urllib.request.urlopen(request, timeout=120) as response:
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
    if not translated_text.strip():
        return AICheckResult.objects.create(
            task=task, requested_by=user, status=AICheckResult.Status.ERROR,
            error_message="No translated text to review.",
        )

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
        return AICheckResult.objects.create(
            task=task, requested_by=user, status=AICheckResult.Status.ERROR,
            error_message=f"HTTP {exc.code}: {detail}", model_used=conf.claude_model,
        )
    except Exception as exc:  # noqa: BLE001 - surfaced to the UI
        return AICheckResult.objects.create(
            task=task, requested_by=user, status=AICheckResult.Status.ERROR,
            error_message=str(exc)[:500], model_used=conf.claude_model,
        )

    issues = data.get("issues") or []
    summary = data.get("summary_ar") or data.get("summary_en") or ""
    if data.get("summary_en") and data.get("summary_ar"):
        summary = f"{data['summary_ar']}\n{data['summary_en']}"

    return AICheckResult.objects.create(
        task=task, requested_by=user,
        status=AICheckResult.Status.ISSUES if issues else AICheckResult.Status.CLEAN,
        summary=summary, issues=issues, model_used=conf.claude_model,
    )
