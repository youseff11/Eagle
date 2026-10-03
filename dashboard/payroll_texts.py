"""The payroll rules page's words: which section each box sits in, and the labels and hints the classic page writes for it.

The rules form (``forms.PayrollSettingsForm``) has forty boxes and the classic page lays them out by hand. The new page is drawn
from this table instead, so the order and the words are in one place, and a test holds that every box of the form is in exactly
one section (a box added to the form cannot go missing from the page).
"""

#: The sections of the page in order: key, icon, title in both languages, an optional note, and the boxes in it.
SECTIONS = (
    {"key": "month", "icon": "calendar", "ar": "الشهر واليوم", "en": "The month and the day", "fields": (
        "daily_hours", "working_days_per_month", "monthly_leave_allowance", "daily_target_words",
        "secondary_daily_target_words", "monthly_target_words", "monthly_alert_words",
    )},
    {"key": "deductions", "icon": "alert", "ar": "الخصومات", "en": "Deductions", "fields": (
        "extra_leave_penalty_days", "unexcused_penalty_days", "quality_penalty_days", "low_output_penalty_days",
        "unexcused_escalation_count", "target_miss_penalty",
    )},
    {"key": "bonuses", "icon": "star", "ar": "المكافآت", "en": "Bonuses", "fields": (
        "discipline_bonus", "target_bonus", "bonuses_need_approval",
    )},
    {
        "key": "attendance", "icon": "timer", "ar": "الحضور والانصراف", "en": "Attendance",
        "note": (
            "فترة السماح شغالة كلها أو ولا حاجة: جوه الفترة = حاضر من غير تأخير، وبرّاها بدقيقة = التأخير كله بيتحسب مش الزيادة بس. مثال العقد: بداية 09:00 وسماح 10 دقايق — 09:06 حاضر، و09:14 تأخير 14 دقيقة.",
            "The grace window is all or nothing: inside it the day is simply present, and one minute past it the whole delay counts, not the excess. The contract's example: a 09:00 start with ten minutes of grace makes 09:06 present and 09:14 late by fourteen minutes.",
        ),
        "fields": (
            "grace_minutes", "early_leave_grace_minutes", "break_minutes_allowed", "geofence_radius_m", "off_site_policy",
            "unknown_device_policy", "break_counts_as_work", "checkout_needs_location", "device_check_enabled",
        ),
    },
    {"key": "overtime", "icon": "clock", "ar": "الأوفرتايم", "en": "Overtime", "fields": (
        "overtime_min_minutes", "overtime_hourly_rate", "overtime_multiplier", "overtime_enabled", "overtime_needs_approval",
    )},
    {"key": "alerts", "icon": "bell", "ar": "التنبيهات", "en": "Alerts", "fields": (
        "missing_checkin_after_minutes", "missing_checkout_after_minutes", "checkin_prompt_before_minutes",
        "short_hours_alert_minutes",
    )},
    {"key": "leave", "icon": "calendar", "ar": "الإجازات والأذونات", "en": "Leave and permissions", "fields": (
        "permission_max_minutes", "leave_needs_manager",
    )},
    {
        "key": "performance", "icon": "chart", "ar": "أوزان تقييم الأداء", "en": "Performance weights",
        "note": (
            "دي نِسَب مش مجموع لازم يوصل 100. المتوسط بيتحسب على المؤشرات اللي ليها بيانات بس، فالمؤشر اللي لسه مفيهوش شغل مبيجرّش التقييم لتحت. وزن بصفر = المؤشر ده مش داخل الحساب خالص.",
            "These are ratios, not a total that must reach 100. The mean is taken over the indicators that have data, so an unmeasured one drags nothing down. A weight of zero drops the indicator entirely.",
        ),
        "fields": ("weight_productivity", "weight_quality", "weight_deadline", "weight_attendance"),
    },
)

#: Label and hint of each box, as ``(arabic, english)``.
TEXTS = {
    'daily_hours': {"label": ('ساعات اليوم', 'Hours a day')},
    'working_days_per_month': {"label": ('أيام العمل في الشهر', 'Working days a month'), "hint": ('قيمة اليوم = الراتب ÷ الرقم ده.', 'A day is worth the salary divided by this.')},
    'monthly_leave_allowance': {"label": ('رصيد الإجازات الشهري', 'Monthly leave balance')},
    'daily_target_words': {"label": ('الحد اليومي (لغة أساسية)', 'Daily floor (primary)')},
    'secondary_daily_target_words': {"label": ('الحد اليومي (لغة تانية)', 'Daily floor (secondary)')},
    'monthly_target_words': {"label": ('التارجت الشهري', 'Monthly target')},
    'monthly_alert_words': {"label": ('حد التنبيه الشهري', 'Monthly alert line')},
    'extra_leave_penalty_days': {"label": ('يوم إجازة زيادة (بالأيام)', 'Extra leave day (in days)')},
    'unexcused_penalty_days': {"label": ('غياب بدون إذن (بالأيام)', 'Unexcused absence (in days)')},
    'quality_penalty_days': {"label": ('خطأ ترجمة (بالأيام)', 'Translation error (in days)')},
    'low_output_penalty_days': {"label": ('انخفاض إنتاجية (بالأيام)', 'Low productivity (in days)')},
    'unexcused_escalation_count': {"label": ('الغياب رقم كام يتصعّد للمدير', 'Which absence escalates')},
    'target_miss_penalty': {"label": ('خصم عدم تحقيق التارجت (جنيه)', 'Missed target penalty')},
    'discipline_bonus': {"label": ('مكافأة الانضباط', 'Discipline bonus')},
    'target_bonus': {"label": ('مكافأة تحقيق التارجت', 'Target bonus')},
    'bonuses_need_approval': {"label": ('المكافأتين محتاجين اعتماد المدير قبل الصرف', 'The two bonuses need the manager to release them')},
    'grace_minutes': {"label": ('فترة السماح (دقيقة)', 'Grace period (minutes)')},
    'early_leave_grace_minutes': {"label": ('سماح الانصراف المبكر (دقيقة)', 'Early-leave grace (minutes)')},
    'break_minutes_allowed': {"label": ('البريك المسموح (دقيقة)', 'Break allowance (minutes)'), "hint": ('الشيفت ممكن يكون ليه بريك مختلف، وساعتها بتاعه هو اللي بيتطبق.', 'A shift may grant its own allowance, and then that one applies.')},
    'geofence_radius_m': {"label": ('نطاق المكتب الافتراضي (متر)', 'Default office radius (m)')},
    'off_site_policy': {"label": ('لو سجّل من بره النطاق', 'If punched off site')},
    'unknown_device_policy': {"label": ('لو الجهاز مش معتمد', 'If the device is unknown')},
    'break_counts_as_work': {"label": ('البريك بيتحسب من ساعات العمل', 'The break counts as worked time')},
    'checkout_needs_location': {"label": ('اطلب الموقع عند الانصراف كمان', 'Ask for the location at check-out too')},
    'device_check_enabled': {"label": ('فحص الجهاز شغال', 'Device check is on')},
    'overtime_min_minutes': {"label": ('أقل مدة تتحسب (دقيقة)', 'Minimum that counts (minutes)')},
    'overtime_hourly_rate': {"label": ('سعر الساعة', 'Hourly rate'), "hint": ('صفر = قيمة اليوم ÷ ساعات اليوم.', 'Zero derives it from the day value divided by the daily hours.')},
    'overtime_multiplier': {"label": ('المضاعف', 'Multiplier'), "hint": ('1.5 = الساعة بساعة ونص. الأوفرتايم بيتحسب بس من بعد زرار «اكسترا تايم».', '1.5 = time and a half. Only time after the Extra time button counts.')},
    'overtime_enabled': {"label": ('الأوفرتايم شغال', 'Overtime is on')},
    'overtime_needs_approval': {"label": ('محتاج اعتماد المدير قبل الصرف', 'Needs the manager to release it')},
    'missing_checkin_after_minutes': {"label": ('تنبيه عدم تسجيل حضور بعد (دقيقة)', 'No check-in after (minutes)')},
    'missing_checkout_after_minutes': {"label": ('مهلة الانصراف بعد نهاية الشيفت (دقيقة)', 'Check-out window after the shift (minutes)'), "hint": ('بعدها من غير انصراف اليوم كله مش بيتحسب (غياب) ويتحوّل للـHR.', 'Past it with no check-out the whole day does not count (absence) and goes to HR.')},
    'checkin_prompt_before_minutes': {"label": ('شاشة الحضور تظهر قبل الشيفت بـ (دقيقة)', 'Check-in screen opens before the shift (minutes)')},
    'short_hours_alert_minutes': {"label": ('نقص الساعات يبدأ من (دقيقة)', 'Short hours from (minutes)')},
    'permission_max_minutes': {"label": ('أطول إذن مرة واحدة (دقيقة)', 'Longest single permission (minutes)')},
    'leave_needs_manager': {"label": ('الطلب يعدّي على التيم ليدر قبل الـHR', 'The team leader approves before HR')},
    'weight_productivity': {"label": ('الإنتاجية', 'Productivity')},
    'weight_quality': {"label": ('الجودة', 'Quality')},
    'weight_deadline': {"label": ('المواعيد', 'Deadlines')},
    'weight_attendance': {"label": ('الحضور', 'Attendance')},
}
