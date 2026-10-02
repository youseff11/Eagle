"""Voice notes — what WhatsApp accepts, and how a browser recording gets there.

Browsers do not agree on a recording format. Firefox hands us ``audio/ogg``
(Opus), Safari and recent Chrome hand us ``audio/mp4`` (AAC) — WhatsApp takes
both as they are. An older Chrome only records ``audio/webm``, which WhatsApp
rejects, so that one is re-wrapped as Ogg/Opus with ffmpeg before it goes out.

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

#: A real recording converts in a few seconds; longer than this is not a recording.
FFMPEG_TIMEOUT = 30

#: Longer than this and the ops person is recording a meeting, not a reply.
MAX_SECONDS = 300

#: The most bytes of a recording that is taken at all, by any door. Five minutes of speech is a few megabytes in any
#: format a browser records; one far bigger is not a recording, and it would be handed to ffmpeg to re-encode.
MAX_UPLOAD_BYTES = 15 * 1024 * 1024

#: The most ffmpeg may write: five minutes at 32 kbit/s is about 1.2 MB.
MAX_OUTPUT_BYTES = 4_000_000


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
    """Re-encode a browser recording to mono Ogg/Opus — the WhatsApp voice format."""
    if not looks_like_recording(content):
        raise AudioError(
            "الملف ده مش تسجيل صوت من المتصفح.",
            "That is not a recording a browser made.",
        )
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
                binary, "-nostdin", "-hide_banner", "-loglevel", "error", "-y",
                # What arrives is bytes a person chose: a playlist inside it could make ffmpeg fetch a URL. It may
                # open the file it is told to read (a plain file: nothing else) and no network scheme at all.
                "-protocol_whitelist", "file",
                "-i", source,
                # Sound only, with no tags, subtitles or data tracks; and bounded in what it may write.
                "-vn", "-sn", "-dn", "-map_metadata", "-1",
                "-t", str(MAX_SECONDS + 10), "-fs", str(MAX_OUTPUT_BYTES),
                "-threads", "1",
                "-ac", "1", "-ar", "48000",
                "-c:a", "libopus", "-b:a", "32k",
                destination,
            ],
            stdin=subprocess.DEVNULL, capture_output=True, timeout=FFMPEG_TIMEOUT,
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


def looks_like_recording(content):
    """Does this start like what a browser records: WebM/Matroska, Ogg, or MP4?

    ffmpeg chooses how to read a file by what is in it, not by its name, and it can read hundreds of formats,
    among them playlists and lists of files that name other files. A recording is one of three, and each starts
    with something that says so: ``1A 45 DF A3`` (EBML), ``OggS``, or ``ftyp`` four bytes in. Anything else is
    refused before ffmpeg sees it.
    """
    head = bytes(content[:12])
    return head.startswith(b"\x1a\x45\xdf\xa3") or head.startswith(b"OggS") or head[4:8] == b"ftyp"


def prepare(content, filename="", mime=""):
    """Return ``(content, filename, mime)`` ready to hand to WhatsApp."""
    if len(content) > MAX_UPLOAD_BYTES:
        raise AudioError(
            "التسجيل كبير قوي. سجّل رسالة أقصر.",
            f"The recording is bigger than {MAX_UPLOAD_BYTES} bytes.",
        )
    mime = base_mime(mime)
    if is_whatsapp_ready(mime):
        return content, filename or "voice", mime

    stem = os.path.splitext(filename or "voice")[0] or "voice"
    return to_opus(content), stem + TARGET_EXTENSION, TARGET_MIME
