"""Egypt time on a twelve-hour clock - the one way Eagle writes a time of day.

Every time a person reads is Cairo time (``settings.TIME_ZONE``) and runs to
12, not 24: 17:30 is ``5:30 م`` in Arabic and ``5:30 PM`` in English. The
JSON doors reach this through :func:`fmt12`, and the notifications through
:func:`both`.

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


def both(value, date_format=""):
    """The Arabic and English spellings together - for bilingual messages."""
    return fmt12(value, "ar", date_format), fmt12(value, "en", date_format)


def window12(start, end, lang="ar"):
    """``9:00 ص - 5:00 م`` for a shift, or ``—`` when either end is missing."""
    if not (start and end):
        return "—"
    return f"{fmt12(start, lang)} - {fmt12(end, lang)}"
