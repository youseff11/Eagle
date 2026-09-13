"""Voice notes — what WhatsApp accepts, and how a browser recording gets there.

Browsers do not agree on a recording format. Firefox hands us ``audio/ogg``
(Opus), Safari hands us ``audio/mp4`` (AAC) — WhatsApp takes both as they are.
Chrome only records ``audio/webm``, which WhatsApp rejects, so that one is
re-wrapped as Ogg/Opus with ffmpeg before it goes out.

Everything here is stdlib only; ffmpeg is looked up on PATH and its absence is
reported in plain language instead of blowing up a send.
"""

import os
import shutil
import subprocess
import tempfile

#: Audio mime types the WhatsApp Cloud API accepts as-is.
WHATSAPP_AUDIO = frozenset({
    "audio/aac", "audio/amr", "audio/mp4", "audio/mpeg", "audio/ogg",
})

#: What a recording becomes when it has to be converted.
TARGET_MIME = "audio/ogg"
TARGET_EXTENSION = ".ogg"

#: File extensions we treat as playable audio (used for rows saved before the
#: mime column existed, and as a fallback when a mime is missing).
AUDIO_EXTENSIONS = frozenset({
    ".aac", ".amr", ".m4a", ".mp3", ".oga", ".ogg", ".opus", ".wav", ".weba",
})

FFMPEG_TIMEOUT = 90

#: Longer than this and the ops person is recording a meeting, not a reply.
MAX_SECONDS = 300


class AudioError(Exception):
    """Raised when a recording cannot be turned into something WhatsApp takes."""

    def __init__(self, message_ar, message_en=""):
        super().__init__(message_ar)
        self.message_ar = message_ar
        self.message_en = message_en or message_ar


# ---------------------------------------------------------------------------
# Small helpers
# ---------------------------------------------------------------------------

def base_mime(value):
    """``audio/webm;codecs=opus`` -> ``audio/webm``."""
    return (value or "").split(";")[0].strip().lower()


def is_audio_name(name):
    return os.path.splitext(name or "")[1].lower() in AUDIO_EXTENSIONS


def is_audio(mime="", name=""):
    """True when the browser can play this in an ``<audio>`` element."""
    return base_mime(mime).startswith("audio/") or is_audio_name(name)


def is_whatsapp_ready(mime):
    return base_mime(mime) in WHATSAPP_AUDIO


def ffmpeg_path():
    """The ffmpeg binary, or an empty string when it is not installed."""
    return shutil.which("ffmpeg") or ""


def pretty_duration(seconds):
    try:
        total = int(seconds or 0)
    except (TypeError, ValueError):
        total = 0
    return f"{total // 60}:{total % 60:02d}"


# ---------------------------------------------------------------------------
# Conversion
# ---------------------------------------------------------------------------

def to_opus(content):
    """Re-encode any recording to mono Ogg/Opus — the WhatsApp voice format."""
    binary = ffmpeg_path()
    if not binary:
        raise AudioError(
            "المتصفح ده بيسجّل بصيغة واتساب مش بيقبلها، والسيرفر مفيهوش ffmpeg "
            "عشان يحوّلها. نصيحة: سجّل من فايرفوكس، أو نصّب ffmpeg على السيرفر.",
            "The browser records a format WhatsApp rejects and ffmpeg is not "
            "installed on the server to convert it.",
        )

    source = destination = ""
    try:
        # ffmpeg needs to seek inside a WebM/Matroska file, and a MediaRecorder
        # stream is not seekable, so both ends go through real files.
        handle, source = tempfile.mkstemp(suffix=".src")
        with os.fdopen(handle, "wb") as fh:
            fh.write(content)
        handle, destination = tempfile.mkstemp(suffix=TARGET_EXTENSION)
        os.close(handle)

        result = subprocess.run(
            [
                binary, "-hide_banner", "-loglevel", "error", "-y",
                "-i", source,
                "-vn", "-ac", "1", "-ar", "48000",
                "-c:a", "libopus", "-b:a", "32k",
                destination,
            ],
            capture_output=True, timeout=FFMPEG_TIMEOUT,
        )
        if result.returncode != 0:
            detail = (result.stderr or b"").decode("utf-8", errors="ignore")[:300]
            raise AudioError(
                "تحويل الرسالة الصوتية فشل.",
                f"Audio conversion failed: {detail}",
            )
        with open(destination, "rb") as fh:
            converted = fh.read()
    except subprocess.TimeoutExpired:
        raise AudioError(
            "تحويل الرسالة الصوتية خد وقت طويل جدًا — جرّب تسجيل أقصر.",
            "Audio conversion timed out — try a shorter recording.",
        )
    except OSError as exc:
        raise AudioError(
            "مش قادر أشتغل على ملف الصوت على السيرفر.",
            f"Could not process the audio file: {exc}",
        )
    finally:
        for path in (source, destination):
            if path:
                try:
                    os.remove(path)
                except OSError:
                    pass

    if not converted:
        raise AudioError("التحويل طلّع ملف فاضي.", "Conversion produced an empty file.")
    return converted


def prepare(content, filename="", mime=""):
    """Return ``(content, filename, mime)`` ready to hand to WhatsApp."""
    mime = base_mime(mime)
    if is_whatsapp_ready(mime):
        return content, filename or "voice", mime

    stem = os.path.splitext(filename or "voice")[0] or "voice"
    return to_opus(content), stem + TARGET_EXTENSION, TARGET_MIME
