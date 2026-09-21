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
