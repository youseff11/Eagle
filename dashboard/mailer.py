"""Outgoing e-mail for client deliveries.

Uses an explicit SMTP connection built from :class:`AppSettings` instead of the
project-level e-mail settings, so the admin panel is the single place where
credentials live. Falls back to the IMAP credentials when the SMTP ones are
left blank (Gmail uses the same app password for both).
"""

from email.mime.image import MIMEImage

from django.core.mail import EmailMessage, EmailMultiAlternatives, get_connection


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


def new_message_id(conf):
    """A Message-ID for a letter we are about to send, on our sender's domain.

    Made here rather than left to Django so it can be stored first: the
    client's answer names it in ``In-Reply-To``, and that is what puts their
    answer back in the right conversation on /ops/inbox/.
    """
    import email.utils

    _host, user, _password = _credentials(conf)
    sender = email.utils.parseaddr(conf.smtp_from or user or "")[1]
    domain = sender.rpartition("@")[2] or "eagel-operation.com"
    return email.utils.make_msgid(domain=domain)


def build_message(conf, to, subject, body, attachments, headers=None, from_email="",
                  html_body="", inline_images=(), connection=None):
    """The letter itself, before it is sent - separate so a test can read it.

    With ``html_body`` it is text *and* HTML (``multipart/alternative``), and
    ``inline_images`` - ``(content_id, bytes, mime)`` - ride inside it for the
    HTML to show as ``cid:`` (``mailbrand.py``). Without, it is the plain
    letter it always was.
    """
    _host, user, _password = _credentials(conf)
    extra = {k: v for k, v in (headers or {}).items() if v}
    if from_email:
        extra["Reply-To"] = from_email
    kwargs = {
        "subject": subject, "body": body,
        "from_email": (from_email or conf.smtp_from or user), "to": [to],
        "connection": connection, "headers": extra or None,
    }
    if html_body:
        message = EmailMultiAlternatives(**kwargs)
        message.attach_alternative(html_body, "text/html")
        if inline_images:
            # "related" so the images belong to the HTML and are not listed
            # as files the client has to download.
            message.mixed_subtype = "related"
            for content_id, content, mime in inline_images:
                image = MIMEImage(content, _subtype=(mime or "image/png").split("/")[-1])
                image.add_header("Content-ID", f"<{content_id}>")
                image.add_header("Content-Disposition", "inline", filename=f"{content_id}.png")
                message.attach(image)
    else:
        message = EmailMessage(**kwargs)
    for filename, content, mime in attachments:
        message.attach(filename, content, mime or "application/octet-stream")
    return message


def send_delivery(conf, to, subject, body, attachments, headers=None, from_email="",
                  html_body="", inline_images=()):
    """``attachments`` is a list of ``(filename, bytes, mime)`` tuples.

    ``headers`` is for threading — ``Message-ID``, ``In-Reply-To`` and
    ``References`` — so a reply lands inside the client's own conversation in
    their mailbox instead of arriving as a new letter.

    ``from_email`` is a Sales person's own address on the company mailbox
    (``lines.py``): the letter goes out from it and the client's answer comes
    back to it. The login stays the company's. With Gmail the address must
    be added under "Send mail as" first, or Gmail puts the account's own
    address back in From - Reply-To still carries theirs either way.
    """
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
        message = build_message(
            conf, to, subject, body, attachments, headers=headers,
            from_email=from_email, html_body=html_body,
            inline_images=inline_images, connection=connection,
        )
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
