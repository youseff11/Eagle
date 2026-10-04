"""The ``icon`` tag the remaining Django pages draw with, and the ``(ar, en)`` label tables the JSON endpoints use.

The name stays: the tables are imported from here all over. The classic interface's badges, filters and menu tags went
with its templates.
"""

import re

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
    "hr": ("موارد بشرية", "HR"),
    "reviewer": ("مراجع", "Reviewer"),
    "accounting": ("حسابات", "Accounting"),
    "sales": ("مبيعات", "Sales"),
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

#: What a payslip calls a violation (``ViolationKind``), and what it says about its approval (``ApprovalStatus``).
VIOLATION_KIND_MAP = {
    "discipline": ("قواعد داخلية", "Internal rules"),
    "quality": ("خطأ في الترجمة", "Translation error"),
    "low_output": ("إنتاجية منخفضة", "Low productivity"),
    "unexcused": ("غياب بدون إذن", "Absence without permission"),
    "extra_leave": ("إجازة فوق الرصيد", "Leave beyond the balance"),
    "target_miss": ("الهدف الشهري ماتحققش", "Monthly target missed"),
    "manual": ("تعديل يدوي", "Manual adjustment"),
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


#: task origin -> (css modifier, icon, arabic label, english label)
ORIGIN_MAP = {
    "whatsapp": ("wa", "message", "واتساب", "WhatsApp"),
    "email": ("mail", "mail", "ميل", "Email"),
}


#: What a mail client leaves in the plain-text body where a picture sat:
#: Gmail writes "[image: scan.jpg]", Outlook "[cid:image001.png@01DA...]".
#: The picture itself arrived as an attachment and is shown as one, so the
#: placeholder is only noise on top of it.
_MAIL_IMAGE_TAG = re.compile(
    r"^[ \t]*\[(?:image|cid)\s*:[^\]\n]*\][ \t]*\r?\n?", re.IGNORECASE | re.MULTILINE
)


@register.filter
def strip_image_tags(text):
    """Drop the "[image: x.jpg]" lines a mail client puts in the text body."""
    return _MAIL_IMAGE_TAG.sub("", str(text or "")).strip()
