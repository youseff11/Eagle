"""The left-hand navigation, written down once as data.

It used to be 250 lines of near-identical ``<a>`` tags with a permission
check wrapped around each run of them, and it drifted the way that shape
always drifts. By 23/09/2026 it had two sections both headed "الأدمن" and
two headed "الحسابات"; three links hanging loose in the middle with no
heading over them at all; "كشف الشهر" and "المخالفات" listed twice for an
admin; and a "جروبات العملاء" link still pointing at a feature that had
been taken out of the product weeks earlier. None of that is visible when
you are editing one more ``<a>`` tag in the middle of two hundred.

As a list it is all checkable, and ``NavTests`` checks it: every url
reverses, no page is listed twice, no heading is used twice, no group is
empty, and nothing is left outside a heading.

Shape:
    sidebar(user, url_name) -> [ {key, ar, en, open, items: [ {...} ]} ]

Each item carries its own ``href`` (already reversed) and whether it is
the page being looked at, so the template only loops. ``also`` lists the
other url names that count as "you are here" - a task page lights up the
tasks link, a mail conversation lights up the mailbox.
"""

from dataclasses import dataclass

from django.urls import reverse


@dataclass(frozen=True)
class Item:
    url: str
    ar: str
    en: str
    icon: str
    #: Key of the heartbeat counter shown as a pill on the right, if any.
    counter: str = ""
    #: Other url names that mean "this item is where you are".
    also: tuple = ()

    def here(self, url_name):
        return url_name == self.url or url_name in self.also


def _group(key, ar, en, items):
    return {"key": key, "ar": ar, "en": en, "items": [i for i in items if i]}


def groups_for(user):
    """Every group this person may see, in order, before the empties go.

    Kept apart from the rendering so a test can read the structure without
    a request, a template or a reverse().
    """
    ops = user.is_operation or user.is_admin_role
    admin = user.is_admin_role
    out = []

    # -- the work itself, whichever work this person does -----------------
    work = []
    if ops:
        work += [
            Item("ops_inbox", "ميلات واردة", "Incoming mail", "mail",
                 counter="inbox", also=("ops_mail_thread",)),
            Item("ops_chats", "الشاتات", "Chats", "message", counter="chats",
                 also=("ops_chat_detail", "ops_group_chat", "ops_staff_chat")),
            Item("ops_tasks", "التاسكات", "Tasks", "layers", counter="new_tasks",
                 also=("ops_task_new", "task_detail", "task_requirement",
                       "task_word_count")),
            Item("ops_team", "حالة الفرق", "Team status", "users"),
        ]
    if user.is_team_lead:
        work += [
            Item("lead_home", "تاسكاتي", "My tasks", "target", counter="open",
                 also=("task_detail", "task_requirement", "task_word_count")),
            Item("lead_translators", "حالة المترجمين", "Translator status", "users"),
            Item("ops_chats", "الشاتات", "Chats", "message", counter="chats",
                 also=("ops_chat_detail", "ops_group_chat", "ops_staff_chat")),
        ]
    if user.is_translator:
        work += [
            Item("translator_home", "شغلي", "My work", "pen", counter="open",
                 also=("task_detail", "task_requirement", "task_word_count")),
            Item("ops_chats", "الشاتات", "Chats", "message", counter="chats",
                 also=("ops_chat_detail", "ops_group_chat", "ops_staff_chat")),
        ]
    out.append(_group("work", "الشغل", "Work", work))

    # -- clients ----------------------------------------------------------
    out.append(_group("clients", "العملاء", "Clients", [
        Item("client_list", "أكواد العملاء", "Client codes", "tag",
             also=("client_detail",)) if not user.is_translator else None,
        Item("admin_clients", "بيانات العملاء", "Client records", "contact",
             also=("admin_client_new", "admin_client_edit")) if admin else None,
    ]))

    # -- hiring -----------------------------------------------------------
    out.append(_group("hiring", "التوظيف", "Recruitment", [
        Item("hr_recruitment", "لوحة التوظيف", "Recruitment board",
             "chart") if user.can_recruit else None,
        Item("hr_vacancies", "الوظائف", "Vacancies", "building",
             also=("hr_vacancy",)) if user.can_recruit else None,
        Item("hr_candidates", "المرشحين", "Candidates", "contact",
             also=("hr_candidate", "hr_hire", "hr_interview_score"))
        if user.can_recruit else None,
        # A reviewer has this one page and nothing else in the whole
        # section, which is why it lives here instead of under a heading
        # of its own with a single line beneath it.
        Item("reviewer_tests", "اختبارات المرشحين", "Candidate tests",
             "check-circle", also=("hr_test_score",)) if user.is_reviewer else None,
        Item("hr_questions", "بنك الأسئلة", "Question bank",
             "list-checks") if user.can_recruit else None,
        Item("hr_approvals", "موافقات التعيين", "Hiring approvals",
             "user-check") if user.can_approve_hiring else None,
        Item("hr_recruitment_settings", "إعدادات التوظيف", "Recruitment settings",
             "sliders") if user.can_recruit else None,
    ]))

    # -- the people already hired -----------------------------------------
    out.append(_group("people", "الموظفين", "People", [
        Item("hr_employees", "ملفات الموظفين", "Employee files", "users",
             also=("hr_employee",)) if user.can_recruit else None,
        Item("hr_probation", "فترة الاختبار", "Probation",
             "eye") if user.can_recruit else None,
        Item("hr_performance", "الأداء", "Performance",
             "target") if user.can_recruit else None,
        Item("hr_complaints", "شكاوى العملاء", "Complaints",
             "thumbs-down") if user.can_recruit else None,
        Item("hr_salary_requests", "طلبات تغيير الراتب", "Salary requests",
             "refresh") if user.can_recruit else None,
        Item("hr_salary_plans", "خطط الرواتب", "Salary plans",
             "layers") if user.can_approve_hiring else None,
    ]))

    # -- attendance, for whoever runs it ----------------------------------
    shift = user.can_manage_attendance
    out.append(_group("workforce", "إدارة الحضور", "Workforce", [
        Item("hr_attendance", "لوحة الحضور", "Attendance board", "users",
             also=("hr_attendance_day",)) if shift else None,
        Item("hr_schedules", "جداول العمل", "Schedules", "calendar") if shift else None,
        # Used to hang under no heading at all, between two sections.
        Item("hr_leave", "طلبات الإجازة", "Leave requests", "hand") if shift else None,
        Item("hr_overtime", "الأوفرتايم", "Overtime", "clock") if shift else None,
        Item("hr_report", "التقرير الشهري", "Monthly report", "chart") if shift else None,
        Item("hr_offices", "مواقع المكاتب", "Offices", "map-pin") if shift else None,
        Item("hr_devices", "أجهزة الحضور", "Devices", "shield-check") if shift else None,
    ]))

    # -- money -------------------------------------------------------------
    money = user.is_accounting or admin
    out.append(_group("accounts", "الحسابات", "Accounts", [
        Item("accounts_overview", "كشف الشهر", "Monthly payroll", "calendar",
             also=("accounts_line", "accounts_salary")) if money else None,
        Item("accounts_attendance", "الحضور والإنتاج", "Attendance & output",
             "timer") if admin else None,
        Item("accounts_violations", "المخالفات والخصومات", "Violations",
             "alert") if money else None,
        Item("accounts_rules", "قواعد الحساب", "Payroll rules",
             "list-checks") if admin else None,
    ]))

    # -- running the place --------------------------------------------------
    out.append(_group("admin", "الأدمن", "Admin", [
        Item("admin_overview", "نظرة عامة", "Overview", "chart") if admin else None,
        Item("admin_users", "المستخدمين والشيفتات", "Users & shifts", "lock",
             also=("admin_user_new", "admin_user_edit")) if admin else None,
        Item("admin_settings", "الإعدادات و AI", "Settings & AI",
             "sliders") if admin else None,
        Item("admin_simulate", "محاكاة رسالة", "Simulate message",
             "beaker") if admin else None,
        Item("admin_audit", "سجل النشاط", "Audit log", "history") if admin else None,
    ]))

    # -- this person's own things ------------------------------------------
    out.append(_group("mine", "بتاعي", "Mine", [
        Item("my_attendance", "حضوري", "My attendance",
             "timer") if user.attendance_enabled else None,
        Item("my_leave", "إجازاتي", "My leave",
             "calendar") if user.attendance_enabled else None,
        Item("translator_payroll", "مستحقاتي", "My payroll",
             "folder") if user.is_translator else None,
        Item("notifications", "التنبيهات", "Notifications", "bell"),
    ]))

    return [g for g in out if g["items"]]


def sidebar(user, url_name=""):
    """The nav as the template wants it: hrefs resolved, one group open.

    Exactly one group starts open — the one holding the page you are on.
    On a page that is in no group (there are a few), the first group opens
    instead, because a nav that is entirely shut is a nav you have to
    click twice to use.
    """
    groups = groups_for(user)
    for group in groups:
        items = []
        for item in group["items"]:
            items.append({
                "href": reverse(f"dashboard:{item.url}"),
                "ar": item.ar,
                "en": item.en,
                "icon": item.icon,
                "counter": item.counter,
                "here": item.here(url_name),
            })
        group["items"] = items
        group["open"] = any(i["here"] for i in items)

    if groups and not any(g["open"] for g in groups):
        groups[0]["open"] = True
    return groups
