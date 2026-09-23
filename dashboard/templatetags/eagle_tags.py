"""Template helpers for the Eagle dashboard."""

from django import template
from django.utils.html import escape, strip_tags
from django.utils.safestring import mark_safe

register = template.Library()


# ---------------------------------------------------------------------------
# Icons — thin wrapper over the inline SVG sprite in partials/icons.html
# ---------------------------------------------------------------------------

@register.simple_tag
def icon(name, cls=""):
    classes = f"ic {cls}".strip()
    return mark_safe(
        f'<svg class="{escape(classes)}" aria-hidden="true" focusable="false">'
        f'<use href="#i-{escape(name)}"></use></svg>'
    )


# ---------------------------------------------------------------------------
# Labels
# ---------------------------------------------------------------------------

#: status -> (css modifier, arabic label, english label)
STATUS_MAP = {
    "new": ("new", "جديدة", "New"),
    "awaiting_lead": ("wait", "بانتظار التيم ليدر", "Awaiting team leader"),
    "lead_accepted": ("info", "التيم ليدر استلم", "Team leader accepted"),
    "awaiting_translator": ("wait", "بانتظار المترجم", "Awaiting translator"),
    "in_progress": ("work", "شغل جاري", "In progress"),
    "under_review": ("review", "تحت المراجعة", "Under review"),
    "reviewed": ("ok", "تمت المراجعة", "Reviewed"),
    "delivered": ("done", "تم التسليم", "Delivered"),
    "cancelled": ("dead", "ملغاة", "Cancelled"),
}

ROLE_MAP = {
    "admin": ("أدمن", "Admin"),
    "operation": ("أوبريشن", "Operation"),
    "team_lead": ("تيم ليدر", "Team leader"),
    "translator": ("مترجم", "Translator"),
    "hr": ("موارد بشرية", "HR"),
    "reviewer": ("مراجع", "Reviewer"),
    "accounting": ("حسابات", "Accounting"),
}

PRIORITY_MAP = {
    "low": ("منخفضة", "Low"),
    "normal": ("عادية", "Normal"),
    "high": ("عالية", "High"),
    "urgent": ("عاجلة", "Urgent"),
}

KIND_MAP = {
    "like": ("بيحب", "Likes"),
    "dislike": ("بيكره", "Dislikes"),
    "rule": ("قاعدة", "Rule"),
}

DAY_STATUS_MAP = {
    "present": ("ok", "حاضر", "Present"),
    "leave": ("info", "إجازة", "Leave"),
    "excused": ("wait", "غياب بعذر", "Excused"),
    "unexcused": ("dead", "غياب بدون إذن", "Unexcused"),
    "weekly_off": ("", "راحة أسبوعية", "Weekly off"),
    "holiday": ("", "أجازة رسمية", "Public holiday"),
}

WORK_MODE_MAP = {
    "office": ("من المكتب", "Office"),
    "remote": ("عن بُعد", "Remote"),
    "hybrid": ("هجين", "Hybrid"),
}

CANDIDATE_STATUS_MAP = {
    "new": ("new", "جديد", "New"),
    "screening": ("wait", "فرز", "Screening"),
    "interview": ("info", "مقابلة", "Interview"),
    "test": ("work", "اختبار", "Test"),
    "final_review": ("review", "مراجعة نهائية", "Final review"),
    "owner_approval": ("wait", "مستني المالك", "Owner approval"),
    "approved": ("ok", "متوافق عليه", "Approved"),
    "hired": ("ok", "اتعيّن", "Hired"),
    "rejected": ("dead", "مرفوض", "Rejected"),
}

EMPLOYMENT_STATUS_MAP = {
    "probation": ("wait", "تحت الاختبار", "Probation"),
    "active": ("ok", "مثبّت", "Confirmed"),
    "notice": ("review", "في فترة إشعار", "Notice"),
    "left": ("dead", "ساب الشركة", "Left"),
}

LEAVE_STATUS_MAP = {
    "pending": ("wait", "مستني", "Waiting"),
    "manager_ok": ("info", "المدير وافق", "Manager approved"),
    "approved": ("ok", "اتوافق عليه", "Approved"),
    "rejected": ("dead", "مرفوض", "Rejected"),
    "cancelled": ("", "اتسحب", "Withdrawn"),
}

PROBATION_MAP = {
    "pending": ("wait", "مستني", "Pending"),
    "confirmed": ("ok", "اتثبّت", "Confirmed"),
    "extended": ("review", "اتمدّت", "Extended"),
    "terminated": ("dead", "انتهى", "Terminated"),
}

#: The three words every performance number is described with, so the same
#: score never reads "fair" on one screen and "good" on the next.
BAND_MAP = {
    "good": ("ok", "كويس", "Good"),
    "fair": ("wait", "متوسط", "Fair"),
    "poor": ("dead", "ضعيف", "Poor"),
    "unknown": ("", "مابتتقاسش", "Not measured"),
}

EMPLOYMENT_MAP = {
    "full_time": ("دوام كامل", "Full time"),
    "part_time": ("دوام جزئي", "Part time"),
    "freelance": ("مستقل", "Freelancer"),
}


@register.simple_tag
def status_badge(status):
    css, ar, en = STATUS_MAP.get(status, ("new", status, status))
    return mark_safe(
        f'<span class="badge badge--{css}"><i class="badge__dot"></i>'
        f'<span data-ar="{escape(ar)}" data-en="{escape(en)}">{escape(ar)}</span></span>'
    )


@register.simple_tag
def priority_badge(priority):
    ar, en = PRIORITY_MAP.get(priority, (priority, priority))
    return mark_safe(
        f'<span class="badge badge--prio-{escape(priority)}" '
        f'data-ar="{escape(ar)}" data-en="{escape(en)}">{escape(ar)}</span>'
    )


#: task origin -> (css modifier, icon, arabic label, english label)
ORIGIN_MAP = {
    "whatsapp": ("wa", "message", "واتساب", "WhatsApp"),
    "email": ("mail", "mail", "ميل", "Email"),
}


@register.simple_tag
def origin_badge(origin):
    """Where the task's request came in. Nothing for a task typed by hand."""
    if origin not in ORIGIN_MAP:
        return ""
    css, name, ar, en = ORIGIN_MAP[origin]
    return mark_safe(
        f'<span class="badge badge--origin badge--{css}">{icon(name, "ic--sm")}'
        f'<span data-ar="{escape(ar)}" data-en="{escape(en)}">{escape(ar)}</span></span>'
    )


@register.simple_tag
def day_status_badge(status):
    css, ar, en = DAY_STATUS_MAP.get(status, ("", status, status))
    modifier = f" badge--{css}" if css else ""
    return mark_safe(
        f'<span class="badge{modifier}" data-ar="{escape(ar)}" '
        f'data-en="{escape(en)}">{escape(ar)}</span>'
    )


@register.simple_tag
def candidate_badge(status):
    css, ar, en = CANDIDATE_STATUS_MAP.get(status, ("", status, status))
    modifier = f" badge--{css}" if css else ""
    return mark_safe(
        f'<span class="badge{modifier}" data-ar="{escape(ar)}" '
        f'data-en="{escape(en)}">{escape(ar)}</span>'
    )


@register.simple_tag
def employment_status_badge(status):
    css, ar, en = EMPLOYMENT_STATUS_MAP.get(status, ("", status, status))
    modifier = f" badge--{css}" if css else ""
    return mark_safe(
        f'<span class="badge{modifier}" data-ar="{escape(ar)}" '
        f'data-en="{escape(en)}">{escape(ar)}</span>'
    )


def _mapped_badge(table, value, default_css=""):
    css, ar, en = table.get(value, (default_css, value, value))
    modifier = f" badge--{css}" if css else ""
    return mark_safe(
        f'<span class="badge{modifier}" data-ar="{escape(ar)}" '
        f'data-en="{escape(en)}">{escape(ar)}</span>'
    )


@register.simple_tag
def leave_badge(status):
    return _mapped_badge(LEAVE_STATUS_MAP, status)


@register.simple_tag
def probation_badge(outcome):
    return _mapped_badge(PROBATION_MAP, outcome)


@register.simple_tag
def band_badge(band):
    """A performance band. "unknown" is a real answer, not a failure."""
    return _mapped_badge(BAND_MAP, band)


@register.simple_tag
def score_bar(score, band=""):
    """A score as a bar, because four numbers in a column read as noise.

    ``None`` draws an empty track rather than a full-width nothing, so a
    missing indicator looks missing instead of looking like zero.
    """
    if score is None:
        return mark_safe(
            '<div class="meter meter--empty" role="img" aria-label="not measured">'
            '<i style="width:0"></i></div>'
        )
    width = max(0, min(100, int(score)))
    css = escape(band or "")
    return mark_safe(
        f'<div class="meter meter--{css}" role="img" aria-label="{width}%">'
        f'<i style="width:{width}%"></i></div>'
    )


@register.simple_tag
def work_mode_badge(mode):
    """Blank is a real answer here: a day nobody has assigned a mode to."""
    if not mode:
        return mark_safe('<span class="muted">—</span>')
    ar, en = WORK_MODE_MAP.get(mode, (mode, mode))
    return mark_safe(
        f'<span class="chip" data-ar="{escape(ar)}" data-en="{escape(en)}">{escape(ar)}</span>'
    )


@register.simple_tag
def employment_badge(kind):
    ar, en = EMPLOYMENT_MAP.get(kind, (kind, kind))
    return mark_safe(
        f'<span class="chip" data-ar="{escape(ar)}" data-en="{escape(en)}">{escape(ar)}</span>'
    )


@register.filter
def dict_get(mapping, key):
    """``{{ labels|dict_get:value }}`` — Django has no subscript syntax."""
    try:
        return mapping.get(key, key)
    except AttributeError:
        return key


@register.filter
def minutes_hm(value):
    """126 -> ``2:06``. Templates keep asking for it, so it lives here once."""
    try:
        total = int(value or 0)
    except (TypeError, ValueError):
        return "0:00"
    sign = "-" if total < 0 else ""
    total = abs(total)
    return f"{sign}{total // 60}:{total % 60:02d}"


@register.simple_tag
def role_badge(role):
    ar, en = ROLE_MAP.get(role, (role, role))
    return mark_safe(
        f'<span class="chip" data-ar="{escape(ar)}" data-en="{escape(en)}">{escape(ar)}</span>'
    )


@register.simple_tag
def bi(ar, en, cls=""):
    """Render a bilingual inline span."""
    return mark_safe(
        f'<span class="{escape(cls)}" data-ar="{escape(ar)}" data-en="{escape(en)}">{escape(ar)}</span>'
    )


@register.filter
def kind_ar(kind):
    return KIND_MAP.get(kind, (kind, kind))[0]


@register.filter
def kind_en(kind):
    return KIND_MAP.get(kind, (kind, kind))[1]


@register.filter
def label_for(client, user):
    """Client identity masked according to the viewer's role."""
    if client is None:
        return "—"
    return client.label_for(user)


def _rating(value):
    """Compact rating readout: a star glyph plus the number out of five."""
    try:
        number = float(value)
    except (TypeError, ValueError):
        number = 0.0
    return mark_safe(
        '<span class="rating" title="%.3f / 5">'
        '<svg class="ic ic--sm ic--fill" aria-hidden="true"><use href="#i-star"></use></svg>'
        "<b>%.2f</b><i>/5</i></span>" % (number, number)
    )


# Registered both ways so `{% stars_html x %}` and `{{ x|stars_html }}` both work.
register.simple_tag(_rating, name="stars_html")
register.filter("stars_html", _rating)


#: state -> (dot modifier, arabic, english). "free" and "on" are the same
#: condition worded for two different boards: the team screen asks who can take
#: work, the staff screen asks who is signed in.
PRESENCE_STATES = {
    "on":    ("on", "نشط", "Online"),
    "free":  ("on", "فاضي", "Free"),
    "busy":  ("busy", "مشغول", "Busy"),
    "shift": ("shift", "في الشيفت — مش فاتح", "On shift — not open"),
    "off":   ("off", "أوفلاين", "Offline"),
}


@register.simple_tag
def presence_cell(person, state="off", dot_only=False, free_word="on"):
    """One status cell, rendered whole by the server.

    The live poller in app.js repaints these, but it must not be what makes
    them legible: a column that is blank until JavaScript lands is worse than
    one that is a few seconds stale.

    ``free_word`` is the word this board uses for "available" — the team screen
    asks who can take work ("فاضي"), the staff screen who is signed in ("نشط").
    It rides on the cell so the poller keeps saying the right one after the
    person has been through busy or offline.
    """
    modifier, ar, en = PRESENCE_STATES.get(state, PRESENCE_STATES["off"])
    seen = last_seen_label(person)
    classes = "presence presence--dot" if dot_only else "presence"
    label = "" if dot_only else (
        f'<small class="presence__state" data-ar="{escape(ar)}" data-en="{escape(en)}">'
        f"{escape(ar)}</small>"
    )
    return mark_safe(
        f'<span class="{classes}" data-presence="{person.pk}" '
        f'data-state="{escape(state)}" data-free="{escape(free_word)}" '
        f'title="{escape(strip_tags(seen))}">'
        f'<span class="dot dot--{escape(modifier)}"></span>'
        f'{label}<small class="presence__seen">{seen}</small></span>'
    )


@register.filter
def last_seen_label(user):
    """When this person last had Eagle open, in words.

    Django's humanize is not installed and its wording is English-only, so the
    two languages are built here and swapped by the same data-ar/data-en pass
    that handles the rest of the UI.
    """
    from django.utils import timezone

    seen = getattr(user, "last_seen", None)
    if not seen:
        return mark_safe(
            '<span data-ar="عمره ما دخل" data-en="Never signed in">عمره ما دخل</span>'
        )

    seconds = int((timezone.now() - seen).total_seconds())
    if seconds < 60:
        ar, en = "دلوقتي", "just now"
    elif seconds < 3600:
        minutes = seconds // 60
        ar, en = f"من {minutes} دقيقة", f"{minutes} min ago"
    elif seconds < 86400:
        hours = seconds // 3600
        ar, en = f"من {hours} ساعة", f"{hours}h ago"
    elif seconds < 86400 * 7:
        days = seconds // 86400
        ar, en = f"من {days} يوم", f"{days}d ago"
    else:
        stamp = timezone.localtime(seen).strftime("%Y-%m-%d %H:%M")
        ar = en = stamp

    return mark_safe(
        f'<span data-ar="{escape(ar)}" data-en="{escape(en)}">{escape(ar)}</span>'
    )


@register.filter
def get_item(mapping, key):
    try:
        return mapping.get(key)
    except AttributeError:
        return None


# ---------------------------------------------------------------------------
# Deadlines
# ---------------------------------------------------------------------------

@register.simple_tag
def deadline_boxes(value=None, name="deadline", scope=""):
    """The days / hours / minutes boxes, outside a Django form.

    Some panels ask for a deadline with no form behind them - the ones on
    the task page. They borrow the widget rather than hand-rolling the same
    three inputs, so the markup, the prefilling and the "blank means leave
    it alone" rule stay in one place.

    ``scope`` prefixes the element ids, for the page that draws the same
    deadline twice: the field names have to match, the ids must not.
    """
    from ..forms import DeadlineInput

    return DeadlineInput(scope=scope).render(name, value)


# ---------------------------------------------------------------------------
# The left-hand navigation
# ---------------------------------------------------------------------------

@register.simple_tag
def remoji(kind, size="md"):
    """A reaction in colour - the r-* symbols in the sprite, drawn to look like
    WhatsApp's set. Not ``icon``: its .ic class would strip their fills."""
    safe = escape(str(kind))
    return mark_safe(
        f'<svg class="remoji remoji--{escape(size)}" aria-hidden="true">'
        f'<use href="#r-{safe}"></use></svg>'
    )


@register.simple_tag
def react_total(reactions):
    """How many people reacted to one message, across every kind."""
    return sum(r.get("count", 0) for r in reactions or [])


@register.filter
def is_image_file(attachment):
    """True when the attachment can be drawn as a picture - see services.is_image."""
    from ..services import is_image

    return is_image(attachment)


@register.filter
def client_text(text):
    """A client's message without the "[document]" / "[image]" placeholder lines."""
    from ..services import clean_client_text

    return clean_client_text(text)


@register.simple_tag
def nav_search(user):
    """What the search box at the top of the nav can find - see ``nav.search_index``."""
    from .. import nav

    if not getattr(user, "is_authenticated", False):
        return []
    return nav.search_index(user)


@register.simple_tag
def nav_groups(user, url_name=""):
    """The sidebar's groups for this person — see ``dashboard/nav.py``.

    A tag rather than a context processor: the nav is thirty reversed urls
    and only one template wants them, so the login page and the public
    pages should not be paying for it on every request.
    """
    from .. import nav

    if not getattr(user, "is_authenticated", False):
        return []
    return nav.sidebar(user, url_name or "")


# ---------------------------------------------------------------------------
# Deadlines
# ---------------------------------------------------------------------------

@register.filter
def deadline_for(task, user):
    """The deadline this reader works to — see ``Task.deadline_for``.

    A filter and not a plain attribute because the answer depends on who is
    looking: a translator is shown the date their team leader gave them,
    never the one the client was promised.
    """
    return task.deadline_for(user)


@register.filter
def deadline_state_for(task, user):
    """``ok`` / ``soon`` / ``late`` / ``done`` for that same date."""
    return task.deadline_state(user)
