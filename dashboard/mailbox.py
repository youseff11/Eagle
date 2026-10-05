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
* **A robot is not a client.** Mail from a ``noreply`` address - Google's
  security alerts, Facebook's notices, a bounce - is skipped, not stored.
  Every one of them used to become a coded "client" nobody could ever answer,
  and the client list filled with them (``is_automated_sender``).
"""

import email
import email.utils
import imaplib
import json
import logging
import re
import socket
import ssl
import time
from email.header import decode_header, make_header

from django.core.files.base import ContentFile
from django.utils import timezone

from . import lines
from .models import AppSettings, InboundMessage, User

logger = logging.getLogger("dashboard")

#: The local part of an address that is a machine writing, not a person:
#: ``no-reply@``, ``noreply-accounts@``, ``googlecommunityteam-noreply@``,
#: ``donotreply@``, ``mailer-daemon@``. Written as one pattern so the client
#: list can ask the database the same question the fetch asks here.
AUTOMATED_SENDER_PATTERN = r"^([^@]*[-_.+])?(no[-_.]?reply|do[-_.]?not[-_.]?reply|mailer-daemon|postmaster)"
_AUTOMATED_SENDER = re.compile(AUTOMATED_SENDER_PATTERN, re.IGNORECASE)


def is_automated_sender(address):
    """True for an address nobody can write back to - a robot, not a client."""
    return bool(_AUTOMATED_SENDER.search((address or "").strip()))


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
        # Who it was sent to. A Sales person's own alias among them makes the
        # letter theirs (lines.py). Delivered-To / X-Original-To are where a
        # forwarded alias usually still shows once To has been rewritten.
        "recipients": lines.addresses_in(
            message.get("To", ""), message.get("Cc", ""),
            message.get("Delivered-To", ""), message.get("X-Original-To", ""),
        ),
    }


#: The folder token for "the server's own Spam folder". Gmail names it
#: ``[Gmail]/Spam`` in English and something else in other languages; what
#: never changes is the ``\\Junk`` flag the server puts on it in its LIST answer,
#: which is what is looked for.
JUNK = "\\Junk"

_LIST_LINE = re.compile(
    rb'^(?:\*\s+LIST\s+)?\((?P<flags>[^)]*)\)\s+(?:"(?:[^"\\]|\\.)*"|NIL)\s+(?P<name>.+?)\s*$',
    re.IGNORECASE,
)


def junk_folder_in(lines):
    """The name of the folder a LIST answer flags ``\\Junk``, or ``""``.

    ``lines`` is what ``imaplib`` returns for LIST, or the untagged lines of one
    read off the wire. A name the server sent as a literal arrives as a tuple
    and is skipped: no real mailbox names its Spam folder that way.
    """
    for raw in lines or ():
        if not isinstance(raw, (bytes, bytearray)):
            continue
        found = _LIST_LINE.match(bytes(raw))
        if not found or b"\\JUNK" not in found.group("flags").upper().split():
            continue
        name = found.group("name").decode("utf-8", "ignore")
        if len(name) >= 2 and name.startswith('"') and name.endswith('"'):
            name = name[1:-1].replace('\\"', '"').replace("\\\\", "\\")
        return name
    return ""


def junk_folder(box):
    """The Spam folder of the mailbox ``box`` is logged in to, or ``""``."""
    status, data = box.list()
    return junk_folder_in(data) if status == "OK" else ""


#: How old the oldest letter of the last fetch was when it was read, in seconds:
#: the mail server's own receipt time against ours, or ``None``. The worker
#: prints it, so a slow push can be told from a slow server.
last_letter_age = None


def _parse_state(text):
    try:
        data = json.loads(text or "{}")
    except ValueError:
        return {}
    return data if isinstance(data, dict) else {}


def _save_uid_state(conf, state):
    """Write each folder's progress, never moving one backwards (another fetch may have got further)."""
    if not state:
        return
    stored = _parse_state(
        AppSettings.objects.filter(pk=conf.pk).values_list("mail_uid_state", flat=True).first()
    )
    for name, entry in state.items():
        other = stored.get(name)
        if (
            isinstance(other, dict) and other.get("validity") == entry["validity"]
            and other.get("last", 0) > entry["last"]
        ):
            continue
        stored[name] = entry
    AppSettings.objects.filter(pk=conf.pk).update(mail_uid_state=json.dumps(stored))
    AppSettings._cached = None


def _uids(box, *criteria):
    status, data = box.uid("SEARCH", *criteria)
    if status != "OK":
        raise MailboxError("البحث في البريد فشل.", "The IMAP search failed.")
    return sorted(int(n) for n in (data[0] or b"").split())


def _untagged_number(box, code):
    """A number the server announced when the folder was selected (UIDVALIDITY, UIDNEXT), or 0."""
    try:
        return int(box.response(code)[1][0])
    except (TypeError, ValueError, IndexError):
        return 0


def _read_selected(box, name, state, limit, keep_unread, ours, services):
    """Record the letters of the folder ``box`` has selected that are new to us; how many there were.

    New is decided by UID, not by the unread flag. A letter somebody opened in
    Gmail before the worker got to it is already read, and was never seen by
    this program: going by the flag lost it for good. The first look at a
    folder, or after the server rebuilt it (its UIDVALIDITY changes), has no
    memory to go on, so there the unread ones are the new ones.
    """
    global last_letter_age

    validity = _untagged_number(box, "UIDVALIDITY")
    known = state.get(name)
    if validity and isinstance(known, dict) and known.get("validity") == validity:
        last = int(known.get("last", 0))
        # ``last+1:*`` always answers with the newest letter, even an old one.
        uids = [u for u in _uids(box, "UID", f"{last + 1}:*") if u > last][: max(1, int(limit or 25))]
    else:
        uids = _uids(box, "UNSEEN")
        uidnext = _untagged_number(box, "UIDNEXT")
        last = uidnext - 1 if uidnext else max(_uids(box, "ALL"), default=0)

    fetch_type = "(BODY.PEEK[] INTERNALDATE)" if keep_unread else "(RFC822 INTERNALDATE)"
    created = 0
    # Oldest first, so the inbox reads in the order the client wrote.
    for uid in uids:
        status, payload = box.uid("FETCH", str(uid), fetch_type)
        if status == "OK" and payload and isinstance(payload[0], tuple):
            when = imaplib.Internaldate2tuple(payload[0][0])
            if when:
                age = max(0.0, time.time() - time.mktime(when))
                last_letter_age = age if last_letter_age is None else max(last_letter_age, age)
            try:
                parsed = parse_message(email.message_from_bytes(payload[0][1]))
                sender = parsed["sender_identity"].strip().lower()
                external = parsed.get("external_id")
                if sender in ours or is_automated_sender(parsed["sender_identity"]):
                    pass          # our own mail coming back around, or a robot's notice
                elif external and InboundMessage.objects.filter(external_id=external).exists():
                    pass          # already recorded (the page's button got there first)
                else:
                    services.ingest_message(**parsed)
                    created += 1
            except Exception:  # noqa: BLE001 - one bad letter must not hold up the ones behind it
                logger.exception("mail: could not record letter uid %s of %s", uid, name)
        last = max(last, uid)
    if validity:
        state[name] = {"validity": validity, "last": last}
    return created


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
    # A Sales person's alias sends from the same mailbox, so their letters
    # can come back around too - they are ours, not a client's.
    ours = {own} | set(
        a.strip().lower() for a in
        User.objects.exclude(mail_alias="").values_list("mail_alias", flat=True)
    )
    global last_letter_age
    last_letter_age = None
    state = _parse_state(getattr(conf, "mail_uid_state", ""))
    progress = json.dumps(state, sort_keys=True)
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

        created += _read_selected(
            box, conf.imap_folder or "INBOX", state, limit, keep_unread, ours, services
        )

        # Gmail files a real client's first letter under Spam now and then, and
        # nobody looks there. When the admin asks for it that folder is read the
        # same way - after the inbox, and never at the inbox's expense.
        if getattr(conf, "imap_read_spam", False):
            try:
                junk = junk_folder(box)
                if junk and box.select(_quote(junk))[0] == "OK":
                    created += _read_selected(box, junk, state, limit, keep_unread, ours, services)
            except (imaplib.IMAP4.error, MailboxError):
                pass
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
        if json.dumps(state, sort_keys=True) != progress:
            try:
                _save_uid_state(conf, state)
            except Exception:  # noqa: BLE001 - only a convenience: Message-ID stops a letter being stored twice
                logger.exception("mail: could not save how far each folder was read")
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

    Also refreshes the alias list from Google (``galiases.sync``, at most every
    ten minutes) - the scheduled fetch is the one loop that is always running,
    and a failed sync is recorded on its own, never as a failed fetch.
    """
    result = _fetch_and_record(limit=limit, keep_unread=keep_unread)
    try:
        from . import galiases

        galiases.sync()
    except Exception:  # noqa: BLE001 - sync() never raises; belt and braces
        pass
    return result


def _fetch_and_record(limit=25, keep_unread=False):
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
# that cannot time out cannot be refreshed. The watcher only ever needs six
# commands — LOGIN, CAPABILITY, LIST (only to find the Spam folder), SELECT,
# IDLE/DONE, LOGOUT — and never reads a message; the fetch itself stays in
# :func:`fetch`.

#: How long one IDLE is held before it is renewed. RFC 2177 allows 29
#: minutes, but a cloud NAT drops a silent TCP connection much sooner (AWS:
#: 350 s), after which the push would never arrive. Four minutes keeps the
#: line warm with room to spare.
IDLE_RENEW_SECONDS = 240

#: A command that is answered at all is answered well inside this.
COMMAND_TIMEOUT = 30


class IdleUnsupported(MailboxError):
    """The server has no IDLE; the worker falls back to polling."""


class NoJunkFolder(MailboxError):
    """The mailbox has no folder flagged ``\\Junk``: there is no Spam to watch."""


def _quote(value):
    """An IMAP quoted string. App passwords are ASCII; that is all LOGIN takes."""
    return '"' + str(value).replace("\\", "\\\\").replace('"', '\\"') + '"'


class IdleWatcher:
    """One logged-in, selected IMAP connection that waits for new mail.

    ``sock`` is for the tests: anything with ``sendall``/``recv``/``settimeout``
    /``close`` can stand in for the TLS socket.
    """

    def __init__(self, conf, sock=None, folder=None):
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
            wanted = folder or conf.imap_folder or "INBOX"
            if wanted == JUNK:
                wanted = junk_folder_in(self._command('LIST "" "*"'))
                if not wanted:
                    raise NoJunkFolder(
                        "الميل مفيهوش فولدر سبام.", "This mailbox has no Spam folder."
                    )
            self._command(f"SELECT {_quote(wanted)}")
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
        # A letter that lands while the IDLE is being closed is announced in the
        # lines before the tagged answer. Throwing them away would leave it
        # waiting for the next poll, minutes away.
        for line in self._finish(tag):
            if line.startswith(b"*") and line.upper().endswith(b" EXISTS"):
                arrived = True
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


def _wants_spam():
    """Whether the admin has asked for the Spam folder to be read, asked fresh."""
    from django.db import close_old_connections

    close_old_connections()
    try:
        return bool(AppSettings.load().imap_read_spam)
    finally:
        close_old_connections()


def watch(on_mail, stop, log=print, poll_seconds=20, renew_seconds=IDLE_RENEW_SECONDS, folder=None):
    """Call ``on_mail()`` the moment new mail lands, until ``stop`` is set.

    Runs forever in ``run_worker``'s mail thread. Every (re)connection also
    calls ``on_mail()`` once, so a letter that arrived while the line was down
    is picked up then, not at the next push. Any failure reconnects with a
    growing pause — a flaky mailbox must never end the watch — and a server
    without IDLE is simply polled every ``poll_seconds`` instead.

    ``folder=JUNK`` is the second watcher, on the Spam folder. It sleeps while
    the admin has not asked for Spam (``AppSettings.imap_read_spam``) and, on a
    server without IDLE, leaves the polling to the first watcher.
    """
    from django.db import close_old_connections

    pause = 5
    where = "" if folder is None else " (spam)"
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
            if folder is not None and not conf.imap_read_spam:
                stop.wait(60)
                continue

            watcher = IdleWatcher(conf) if folder is None else IdleWatcher(conf, folder=folder)
            log(f"mail push{where}: connected, waiting for new mail")
            on_mail()
            pause = 5
            while not stop.is_set():
                if watcher.wait(renew_seconds):
                    log(f"mail push{where}: new mail announced")
                    on_mail()
                if folder is not None and not _wants_spam():
                    break
        except IdleUnsupported as exc:
            if folder is not None:
                stop.wait(3600)       # the inbox watcher polls both folders
                continue
            log(f"mail push: {exc.message_en} Polling every {poll_seconds}s instead.")
            while not stop.is_set():
                try:
                    on_mail()
                except Exception as err:  # noqa: BLE001 - keep polling
                    log(f"mail poll: {type(err).__name__}: {err}")
                stop.wait(poll_seconds)
        except NoJunkFolder:
            log("mail push (spam): this mailbox has no Spam folder.")
            stop.wait(900)
        except Exception as exc:  # noqa: BLE001 - reconnect, whatever it was
            log(f"mail push{where}: {type(exc).__name__}: {exc} — reconnecting in {pause}s")
            stop.wait(pause)
            pause = min(pause * 2, 300)
        finally:
            if watcher is not None:
                watcher.close()
