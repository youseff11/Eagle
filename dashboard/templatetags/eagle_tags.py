"""Template helpers for the Eagle dashboard."""

from django import template
from django.utils.html import escape
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


@register.filter
def get_item(mapping, key):
    try:
        return mapping.get(key)
    except AttributeError:
        return None
