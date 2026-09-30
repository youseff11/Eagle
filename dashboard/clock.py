"""Egypt time on a twelve-hour clock - the one way Eagle writes a time of day.

Every time a person reads is Cairo time (``settings.TIME_ZONE``) and runs to
12, not 24: 17:30 is ``5:30 م`` in Arabic and ``5:30 PM`` in English. The
templates reach this through the ``clock12`` filter, the JSON views through
:func:`fmt12`, and the notifications through :func:`both`.

Form inputs are the exception and stay 24-hour: ``<input type="time">`` and
the datetime parser need ``HH:MM``.
"""

from datetime import datetime, time

from django.utils import timezone

SUFFIX = {
    "ar": ("ص", "م"),
    "en": ("AM", "PM"),
}


def local(value):
    """An aware datetime in Cairo time; anything else unchanged."""
    if isinstance(value, datetime) and timezone.is_aware(value):
        return timezone.localtime(value)
    return value


def fmt12(value, lang="ar", date_format=""):
    """``17:05`` -> ``5:05 م``. ``date_format`` puts a date in front.

    ``date_format`` is strftime-style (``%Y-%m-%d``, ``%m-%d``, ``%d/%m``).
    ``None`` and ``""`` come back as ``""`` so a ``|default`` still works.
    """
    if value in (None, ""):
        return ""
    value = local(value)
    if not isinstance(value, (datetime, time)):
        return str(value)
    hour = value.hour % 12 or 12
    suffix = SUFFIX.get(lang, SUFFIX["ar"])[0 if value.hour < 12 else 1]
    text = f"{hour}:{value.minute:02d} {suffix}"
    if date_format and isinstance(value, datetime):
        text = f"{value.strftime(date_format)} {text}"
    return text


def fmt12_html(value, date_format=""):
    """The template form: the number, then a suffix the language switch flips.

    ``2026-10-01 5:05 <span data-ar="م" data-en="PM">م</span>`` - the page's
    own data-ar / data-en swap turns it into PM for an English reader.

    The whole time is wrapped in an isolated left-to-right ``<bdi>``. Without
    it the Arabic suffix joins the neighbouring number's run, and inside a
    left-to-right ``.mono`` cell ``5:00 م - 1:00 ص`` is drawn
    ``5:00 ص 1:00 - م``: each AM/PM lands beside the wrong time.
    """
    if value in (None, ""):
        return ""
    value = local(value)
    if not isinstance(value, (datetime, time)):
        return str(value)
    hour = value.hour % 12 or 12
    ar, en = (SUFFIX["ar"][0], SUFFIX["en"][0]) if value.hour < 12 else (SUFFIX["ar"][1], SUFFIX["en"][1])
    text = f'{hour}:{value.minute:02d} <span data-ar="{ar}" data-en="{en}">{ar}</span>'
    if date_format and isinstance(value, datetime):
        text = f"{value.strftime(date_format)} {text}"
    return f'<bdi dir="ltr">{text}</bdi>'


def both(value, date_format=""):
    """The Arabic and English spellings together - for bilingual messages."""
    return fmt12(value, "ar", date_format), fmt12(value, "en", date_format)


def window12(start, end, lang="ar"):
    """``9:00 ص - 5:00 م`` for a shift, or ``—`` when either end is missing."""
    if not (start and end):
        return "—"
    return f"{fmt12(start, lang)} - {fmt12(end, lang)}"
