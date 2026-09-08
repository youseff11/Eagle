"""Outgoing e-mail for client deliveries.

Uses an explicit SMTP connection built from :class:`AppSettings` instead of the
project-level e-mail settings, so the admin panel is the single place where
credentials live. Falls back to the IMAP credentials when the SMTP ones are
left blank (Gmail uses the same app password for both).
"""

from django.core.mail import EmailMessage, get_connection


class MailError(Exception):
    def __init__(self, message_ar, message_en=""):
        super().__init__(message_ar)
        self.message_ar = message_ar
        self.message_en = message_en or message_ar


def _credentials(conf):
    host = (conf.smtp_host or "").strip()
    if not host and conf.imap_host:
        # imap.gmail.com -> smtp.gmail.com
        host = conf.imap_host.strip().replace("imap.", "smtp.", 1)
    user = (conf.smtp_user or conf.imap_user or "").strip()
    password = conf.smtp_password or conf.imap_password
    return host, user, password


def is_configured(conf):
    host, user, password = _credentials(conf)
    return bool(host and user and password)


def send_delivery(conf, to, subject, body, attachments):
    """``attachments`` is a list of ``(filename, bytes, mime)`` tuples."""
    host, user, password = _credentials(conf)
    if not (host and user and password):
        raise MailError(
            "إعدادات الإيميل ناقصة — املا بيانات SMTP في الإعدادات.",
            "SMTP is not configured — fill it in under Settings.",
        )
    if not to:
        raise MailError("العميل ده مفيش عنده إيميل مسجل.", "This client has no e-mail on file.")

    try:
        connection = get_connection(
            backend="django.core.mail.backends.smtp.EmailBackend",
            host=host, port=conf.smtp_port or 587,
            username=user, password=password,
            use_tls=bool(conf.smtp_use_tls), fail_silently=False,
        )
        message = EmailMessage(
            subject=subject, body=body,
            from_email=(conf.smtp_from or user), to=[to],
            connection=connection,
        )
        for filename, content, mime in attachments:
            message.attach(filename, content, mime or "application/octet-stream")
        message.send()
    except MailError:
        raise
    except Exception as exc:  # noqa: BLE001 - surfaced to the operator
        raise MailError(
            f"إرسال الإيميل فشل: {exc}", f"Sending the e-mail failed: {exc}"
        )
    return True


def check_connection(conf, test_address=""):
    report = {"ok": False, "host": "", "user": "", "sent": False, "error_ar": "", "error_en": ""}
    host, user, password = _credentials(conf)
    report["host"], report["user"] = host, user
    if not (host and user and password):
        report["error_ar"] = "إعدادات SMTP ناقصة."
        report["error_en"] = "SMTP settings are incomplete."
        return report
    try:
        connection = get_connection(
            backend="django.core.mail.backends.smtp.EmailBackend",
            host=host, port=conf.smtp_port or 587,
            username=user, password=password,
            use_tls=bool(conf.smtp_use_tls), fail_silently=False,
        )
        connection.open()
        connection.close()
        report["ok"] = True
        if test_address:
            send_delivery(conf, test_address, "Eagle — رسالة اختبار",
                          "الاتصال بالإيميل شغال.", [])
            report["sent"] = True
    except MailError as exc:
        report["error_ar"] = exc.message_ar
        report["error_en"] = exc.message_en
    except Exception as exc:  # noqa: BLE001
        report["error_ar"] = f"الاتصال فشل: {exc}"
        report["error_en"] = f"Connection failed: {exc}"
    return report
