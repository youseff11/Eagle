"""Reading the company mailbox over IMAP.

The whole point of the mail page is that a client can write an ordinary e-mail
and have it land in the operation's queue. That only happens if something
actually opens the mailbox, so this is the piece of the feature that does it —
called from ``manage.py fetch_emails`` (and therefore from ``run_worker``), and
from the "جيب الميلات دلوقتي" button on the mail page.

Standard library only: ``imaplib`` + ``email``, the same as the rest of the
project's integrations.

Two rules worth keeping:

* **The address decides, not the display name.** ``resolve_client`` matches on
  the e-mail address; a display name is decoration and can say anything.
* **Our own address is skipped.** A mailbox that also receives what we send
  (a Gmail alias, a group address, a bounce) would otherwise feed our own
  replies back in as client messages, and every one of those becomes a
  notification somebody has to read.
"""

import email
import email.utils
import imaplib
import re
import socket
import ssl
import time
from email.header import decode_header, make_header

from django.core.files.base import ContentFile
from django.utils import timezone

from .models import AppSettings

#: Nothing bigger than this is stored. A 40MB mailshot must not be able to
#: fill the media volume, and no translation job arrives that way.
MAX_ATTACHMENT_BYTES = 25 * 1024 * 1024


class MailboxError(Exception):
    def __init__(self, message_ar, message_en=""):
        super().__init__(message_ar)
        self.message_ar = message_ar
        self.message_en = message_en or message_ar


def _decode(value):
    """MIME-encoded header -> plain text, never raising."""
    if not value:
        return ""
    try:
        return str(make_header(decode_header(value)))
    except Exception:  # noqa: BLE001 - a malformed header must not stop the run
        return str(value)


def _html_to_text(html):
    """Good-enough plain text from an HTML-only e-mail.

    Not a parser and not trying to be: scripts and styles out, tags out,
    entities in. An e-mail with no text/plain part is otherwise stored as an
    empty message, which reads on the page as though the client sent nothing.
    """
    import html as html_module

    text = re.sub(r"(?is)<(script|style)[^>]*>.*?</\1>", " ", html or "")
    text = re.sub(r"(?i)<br\s*/?>", "\n", text)
    text = re.sub(r"(?i)</p\s*>", "\n\n", text)
    text = re.sub(r"(?s)<[^>]+>", " ", text)
    text = html_module.unescape(text)
    text = re.sub(r"[ \t\r\f\v]+", " ", text)
    text = re.sub(r"\n\s*\n\s*\n+", "\n\n", text)
    return text.strip()


def _part_text(part):
    raw = part.get_payload(decode=True) or b""
    return raw.decode(part.get_content_charset() or "utf-8", errors="ignore")


def parse_message(message):
    """One ``email.message.Message`` -> the kwargs ``ingest_message`` wants."""
    display, address = email.utils.parseaddr(message.get("From", ""))
    subject = _decode(message.get("Subject", ""))

    plain, html, attachments = "", "", []
    for part in message.walk():
        if part.get_content_maintype() == "multipart":
            continue
        disposition = str(part.get("Content-Disposition") or "").lower()
        filename = part.get_filename()
        content_type = part.get_content_type()

        is_attachment = "attachment" in disposition or bool(filename)
        if not is_attachment and content_type == "text/plain":
            plain += _part_text(part)
            continue
        if not is_attachment and content_type == "text/html":
            html += _part_text(part)
            continue
        if not is_attachment:
            continue

        raw = part.get_payload(decode=True) or b""
        if not raw or len(raw) > MAX_ATTACHMENT_BYTES:
            continue
        name = _decode(filename) or "attachment.bin"
        # A path separator in a filename from outside is never wanted.
        name = name.replace("\\", "/").rsplit("/", 1)[-1][:180] or "attachment.bin"
        attachments.append({
            "file": ContentFile(raw, name=name),
            "name": name,
            "size": len(raw),
            "mime": content_type,
        })

    body = plain.strip() or _html_to_text(html)

    received_at = None
    date_header = message.get("Date")
    if date_header:
        try:
            parsed = email.utils.parsedate_to_datetime(date_header)
            if parsed is not None:
                received_at = (
                    parsed if timezone.is_aware(parsed)
                    else timezone.make_aware(parsed, timezone.get_default_timezone())
                )
        except Exception:  # noqa: BLE001 - a bad Date is not worth dropping mail for
            received_at = None

    return {
        "channel": "email",
        "subject": subject[:250],
        "body": body,
        "sender_identity": address,
        "sender_display": (display or "")[:190],
        "external_id": (message.get("Message-ID") or "")[:190],
        "reply_to_external": (message.get("In-Reply-To") or "")[:190],
        # The whole chain of letters this one answers. Not stored — it is only
        # read once, to put the letter in the right conversation (threads.py).
        "references": str(message.get("References") or ""),
        "received_at": received_at,
        # The files are the job. Leaving this key out built the list above and
        # threw it away, so every attached contract arrived as a bare subject
        # line - caught by MailboxParsingTests, which is what they are for.
        "attachments": attachments,
    }


def fetch(limit=25, keep_unread=False, conf=None):
    """Pull unseen mail into the inbox. Returns the number of new messages.

    Raises :class:`MailboxError` with a readable Arabic message — the button on
    the page shows it as-is, and a stack trace is no use to the person holding
    the mouse.
    """
    from . import services

    conf = conf or AppSettings.load()
    if not (conf.imap_host and conf.imap_user and conf.imap_password):
        raise MailboxError(
            "إعدادات IMAP ناقصة — املاها في الإعدادات.",
            "IMAP is not configured — fill it in under Settings.",
        )

    own = (conf.imap_user or "").strip().lower()
    created = 0
    box = None
    try:
        box = imaplib.IMAP4_SSL(conf.imap_host, conf.imap_port or 993)
        box.login(conf.imap_user, conf.imap_password)
        status, _ = box.select(conf.imap_folder or "INBOX")
        if status != "OK":
            raise MailboxError(
                f"مفيش فولدر اسمه «{conf.imap_folder or 'INBOX'}».",
                f"No such mailbox: {conf.imap_folder or 'INBOX'}.",
            )

        status, data = box.search(None, "UNSEEN")
        if status != "OK":
            raise MailboxError("البحث في البريد فشل.", "The IMAP search failed.")

        # Oldest first, so the inbox reads in the order the client wrote.
        ids = data[0].split()[: max(1, int(limit or 25))]
        for num in ids:
            fetch_type = "(BODY.PEEK[])" if keep_unread else "(RFC822)"
            status, payload = box.fetch(num, fetch_type)
            if status != "OK" or not payload or not payload[0]:
                continue
            parsed = parse_message(email.message_from_bytes(payload[0][1]))
            if parsed["sender_identity"].strip().lower() == own:
                continue          # our own mail, coming back around
            services.ingest_message(**parsed)
            created += 1
    except MailboxError:
        raise
    except imaplib.IMAP4.error as exc:
        raise MailboxError(
            f"الدخول على البريد فشل: {exc}", f"IMAP login failed: {exc}"
        )
    except OSError as exc:
        raise MailboxError(
            f"مش قادر أوصل لسيرفر البريد: {exc}",
            f"Could not reach the mail server: {exc}",
        )
    finally:
        if box is not None:
            try:
                box.close()
            except Exception:  # noqa: BLE001 - already closing
                pass
            try:
                box.logout()
            except Exception:  # noqa: BLE001
                pass
    return created


def fetch_and_record(limit=25, keep_unread=False):
    """:func:`fetch`, with the outcome written onto the settings row.

    ``(created, error_ar)``. Never raises: both callers want to report, and a
    background loop that dies on a flaky mailbox stops fetching mail for good.
    """
    conf = AppSettings.load()
    try:
        created = fetch(limit=limit, keep_unread=keep_unread, conf=conf)
    except MailboxError as exc:
        AppSettings.objects.filter(pk=conf.pk).update(
            mail_last_fetch_at=timezone.now(),
            mail_last_count=0,
            mail_last_error=exc.message_ar[:300],
        )
        AppSettings._cached = None
        return 0, exc.message_ar
    except Exception as exc:  # noqa: BLE001 - the loop must survive anything
        message = f"جلب البريد فشل: {exc}"
        AppSettings.objects.filter(pk=conf.pk).update(
            mail_last_fetch_at=timezone.now(),
            mail_last_count=0,
            mail_last_error=message[:300],
        )
        AppSettings._cached = None
        return 0, message

    AppSettings.objects.filter(pk=conf.pk).update(
        mail_last_fetch_at=timezone.now(),
        mail_last_count=created,
        mail_last_error="",
    )
    AppSettings._cached = None
    return created, ""


# ---------------------------------------------------------------------------
# Push: IMAP IDLE
# ---------------------------------------------------------------------------
#
# Polling every few minutes means a client's "very urgent" sits unseen for
# minutes. IMAP IDLE (RFC 2177) turns that around: one connection stays open,
# and the mail server itself says "* 12 EXISTS" the moment a letter lands.
# ``run_worker`` keeps one of these open in a thread and fetches on the spot.
#
# Written on a raw TLS socket rather than on imaplib: imaplib reads through a
# buffered file object that is unusable after its first timeout, and an IDLE
# that cannot time out cannot be refreshed. The watcher only ever needs five
# commands — LOGIN, CAPABILITY, SELECT, IDLE/DONE, LOGOUT — and never reads a
# message; the fetch itself stays in :func:`fetch`, unchanged.

#: How long one IDLE is held before it is renewed. RFC 2177 allows 29
#: minutes, but a cloud NAT drops a silent TCP connection much sooner (AWS:
#: 350 s), after which the push would never arrive. Four minutes keeps the
#: line warm with room to spare.
IDLE_RENEW_SECONDS = 240

#: A command that is answered at all is answered well inside this.
COMMAND_TIMEOUT = 30


class IdleUnsupported(MailboxError):
    """The server has no IDLE; the worker falls back to polling."""


def _quote(value):
    """An IMAP quoted string. App passwords are ASCII; that is all LOGIN takes."""
    return '"' + str(value).replace("\\", "\\\\").replace('"', '\\"') + '"'


class IdleWatcher:
    """One logged-in, selected IMAP connection that waits for new mail.

    ``sock`` is for the tests: anything with ``sendall``/``recv``/``settimeout``
    /``close`` can stand in for the TLS socket.
    """

    def __init__(self, conf, sock=None):
        self._buffer = b""
        self._counter = 0
        if sock is None:
            raw = socket.create_connection(
                (conf.imap_host, conf.imap_port or 993), timeout=COMMAND_TIMEOUT
            )
            sock = ssl.create_default_context().wrap_socket(
                raw, server_hostname=conf.imap_host
            )
        self.sock = sock
        try:
            greeting = self._line(COMMAND_TIMEOUT)
            if not greeting.startswith(b"* OK"):
                raise MailboxError("سيرفر البريد رفض الاتصال.", "The mail server refused us.")
            self._command(f"LOGIN {_quote(conf.imap_user)} {_quote(conf.imap_password)}")
            capabilities = b" ".join(self._command("CAPABILITY")).upper()
            if b" IDLE" not in capabilities:
                raise IdleUnsupported(
                    "سيرفر البريد مبيدعمش IDLE.", "The mail server does not support IDLE."
                )
            self._command(f"SELECT {_quote(conf.imap_folder or 'INBOX')}")
        except Exception:
            self.close()
            raise

    # -- the wire ----------------------------------------------------------

    def _line(self, timeout):
        """The next line from the server, or ``socket.timeout`` after ``timeout``."""
        self.sock.settimeout(timeout)
        while b"\r\n" not in self._buffer:
            chunk = self.sock.recv(65536)
            if not chunk:
                raise ConnectionError("the mail server closed the connection")
            self._buffer += chunk
        line, self._buffer = self._buffer.split(b"\r\n", 1)
        return line

    def _send(self, text):
        self.sock.sendall(text.encode("utf-8") + b"\r\n")

    def _tag(self):
        self._counter += 1
        return f"E{self._counter:04d}"

    def _finish(self, tag):
        """Read up to the tagged answer; return the untagged lines before it."""
        untagged = []
        prefix = tag.encode() + b" "
        while True:
            line = self._line(COMMAND_TIMEOUT)
            if line.startswith(prefix):
                if not line[len(prefix):].upper().startswith(b"OK"):
                    raise MailboxError(
                        f"سيرفر البريد رفض الأمر: {line.decode(errors='ignore')[:120]}",
                        f"The mail server said: {line.decode(errors='ignore')[:120]}",
                    )
                return untagged
            untagged.append(line)

    def _command(self, text):
        tag = self._tag()
        self._send(f"{tag} {text}")
        return self._finish(tag)

    # -- the point ---------------------------------------------------------

    def wait(self, seconds=IDLE_RENEW_SECONDS):
        """IDLE for up to ``seconds``. True when the server announced new mail.

        Only ``EXISTS`` counts. Marking a letter read makes the server send a
        ``FETCH (FLAGS …)`` line too — reacting to that would have every fetch
        trigger the next one, forever.
        """
        tag = self._tag()
        self._send(f"{tag} IDLE")
        while True:
            line = self._line(COMMAND_TIMEOUT)
            if line.startswith(b"+"):
                break
            if line.startswith(tag.encode() + b" "):
                raise IdleUnsupported(
                    "سيرفر البريد رفض IDLE.", "The mail server refused IDLE."
                )

        arrived = False
        deadline = time.monotonic() + seconds
        try:
            while True:
                left = deadline - time.monotonic()
                if left <= 0:
                    break
                line = self._line(left)
                if line.startswith(b"*") and line.upper().endswith(b" EXISTS"):
                    arrived = True
                    break
        except socket.timeout:
            pass

        self._send("DONE")
        self._finish(tag)
        return arrived

    def close(self):
        try:
            self._send(f"{self._tag()} LOGOUT")
        except Exception:  # noqa: BLE001 - already going away
            pass
        try:
            self.sock.close()
        except Exception:  # noqa: BLE001
            pass


def watch(on_mail, stop, log=print, poll_seconds=20, renew_seconds=IDLE_RENEW_SECONDS):
    """Call ``on_mail()`` the moment new mail lands, until ``stop`` is set.

    Runs forever in ``run_worker``'s mail thread. Every (re)connection also
    calls ``on_mail()`` once, so a letter that arrived while the line was down
    is picked up then, not at the next push. Any failure reconnects with a
    growing pause — a flaky mailbox must never end the watch — and a server
    without IDLE is simply polled every ``poll_seconds`` instead.
    """
    from django.db import close_old_connections

    pause = 5
    while not stop.is_set():
        watcher = None
        try:
            # This thread holds its own database connection, idle for minutes
            # at a time between letters; a stale one must be dropped first.
            close_old_connections()
            conf = AppSettings.load()
            close_old_connections()
            if not (conf.imap_host and conf.imap_user and conf.imap_password):
                stop.wait(60)
                continue

            watcher = IdleWatcher(conf)
            log("mail push: connected, waiting for new mail")
            on_mail()
            pause = 5
            while not stop.is_set():
                if watcher.wait(renew_seconds):
                    on_mail()
        except IdleUnsupported as exc:
            log(f"mail push: {exc.message_en} Polling every {poll_seconds}s instead.")
            while not stop.is_set():
                try:
                    on_mail()
                except Exception as err:  # noqa: BLE001 - keep polling
                    log(f"mail poll: {type(err).__name__}: {err}")
                stop.wait(poll_seconds)
        except Exception as exc:  # noqa: BLE001 - reconnect, whatever it was
            log(f"mail push: {type(exc).__name__}: {exc} — reconnecting in {pause}s")
            stop.wait(pause)
            pause = min(pause * 2, 300)
        finally:
            if watcher is not None:
                watcher.close()
