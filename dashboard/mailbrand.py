"""The branded letter a Sales person's e-mails go out in (29/09/2026).

Only Sales: the owner wants the company's face - logo, the person's name and
title, their number and address - on the letters that sell, and nothing
changed on the operation's day-to-day mail. Plain text stays in every letter
for clients that do not show HTML; this is the alternative next to it.

The logo travels inside the letter (``cid:``), not as a link: Outlook and
many company mail servers hide linked images until the reader clicks, and a
signature with a broken square where the logo should be is worse than none.
"""

from pathlib import Path

from django.conf import settings
from django.template.loader import render_to_string
from django.utils.html import escape, linebreaks
from django.utils.safestring import mark_safe

LOGO_CID = "eagle-logo"
LOGO_PATH = Path(settings.BASE_DIR) / "static" / "img" / "mail-logo.png"
BRAND = "EagleLingua"
TAGLINE = "Global Translation Services"


def applies_to(user):
    """Whose letters are dressed. The Sales role, and only it."""
    return bool(user is not None and getattr(user, "is_sales", False))


def _logo():
    try:
        return LOGO_PATH.read_bytes()
    except OSError:
        return b""


def sales_letter(user, body, subject, conf, from_address=""):
    """``(html, inline_images)`` for a letter this Sales person sends.

    ``inline_images`` is a list of ``(content_id, bytes, mime)``; empty when
    the logo file is missing, in which case the letter says so by leaving
    the image out rather than failing the send.
    """
    website = (conf.sales_mail_website or "").strip()
    website_url = website if website.startswith(("http://", "https://")) else f"https://{website}"
    footer_lines = [
        line.strip() for line in (conf.sales_mail_footer or "").splitlines() if line.strip()
    ]
    logo = _logo()
    html = render_to_string("mail/sales_letter.html", {
        "subject": subject,
        # Escaped first, then broken into paragraphs: what the person typed is
        # text, never markup that lands in a client's mailbox.
        "body_html": mark_safe(linebreaks(escape(body or ""))),  # noqa: S308 - escaped above
        "name": user.get_full_name() or user.username,
        "title": (user.job_title or "").strip(),
        "phone": (user.phone or user.wa_display_number or "").strip(),
        "address": (from_address or user.mail_alias or "").strip(),
        "website": website.removeprefix("https://").removeprefix("http://").rstrip("/"),
        "website_url": website_url,
        "footer_lines": footer_lines,
        "brand": BRAND,
        "tagline": TAGLINE,
        "logo_cid": LOGO_CID if logo else "",
    })
    images = [(LOGO_CID, logo, "image/png")] if logo else []
    return html, images
