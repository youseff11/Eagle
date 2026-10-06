"""Which screens each person has in the app.

A person has the screens of their role (the admin, the ones the admin oversees). The screens decide what the menu carries and
where a person lands; they do not decide who may see the data: each screen's endpoints ask the questions the rest of the
site asks (``Screen.allows`` here, then the same ``identity`` / ``lines`` / ``ChatRoom.can_open`` rules), so a person who types
an address by hand sees nothing that is not theirs.
"""

from dataclasses import dataclass

from .models import Role


@dataclass(frozen=True)
class Screen:
    key: str
    ar: str
    en: str
    #: Where the screen lives under /app/.
    path: str
    #: The roles this screen is for. The admin may always open it.
    roles: tuple
    #: Whether the admin's menu carries this screen. Off for a screen that is another role's own desk (the translator's work,
    #: the leader's tasks, the Sales line): the admin reaches what is behind them through the pages they do have.
    admin_menu: bool = True
    #: A capability (a ``User`` property) that opens the screen to a person of another role, when the screen's pages answer to
    #: it: the attendance pages of the HR screen answer to ``can_manage_attendance``, which an operation person can be given.
    capability: str = ""

    def allows(self, user):
        """May this person open the screen at all."""
        return bool(
            getattr(user, "is_authenticated", False)
            and (
                user.is_admin_role
                or user.role in self.roles
                or (self.capability and getattr(user, self.capability, False))
            )
        )


SCREENS = {
    screen.key: screen
    for screen in (
        # The admin's own panel, and the pages of every role the admin oversees.
        Screen(
            "admin", "لوحة الأدمن (كل صفحاتها)", "The admin panel (all of its pages)",
            path="/admin", roles=(),
        ),
        # The money screens: the month's sheet, a payslip, attendance and output, violations, salaries, and (the admin's alone) the
        # payroll rules.
        Screen(
            "accounts", "الحسابات (كشف الشهر، المخالفات والخصومات، الحضور والإنتاج، الرواتب، قواعد الحساب)",
            "Accounts (the month, violations, attendance and output, salaries, payroll rules)",
            path="/accounts", roles=(Role.ACCOUNTING,),
        ),
        # Human resources: attendance and schedules, leave, recruitment, the people already hired, and the places and rules HR
        # keeps. A person who was only given the attendance flag (``attendance_manager``) has the attendance pages of it.
        Screen(
            "hr", "الموارد البشرية (الحضور والجداول، الإجازات، التوظيف، ملفات الموظفين، الإعدادات)",
            "Human resources (attendance and schedules, leave, recruitment, employee files, settings)",
            path="/hr/recruitment", roles=(Role.HR,), capability="can_manage_attendance",
        ),
        Screen(
            "translator_home", "شغل المترجم", "The translator's desk",
            path="/translator", roles=(Role.TRANSLATOR,), admin_menu=False,
        ),
        Screen(
            "operation", "شاشة الأوبريشن (التاسكات والفرق)", "The operation's screen (tasks and teams)",
            path="/tasks", roles=(Role.OPERATION,),
        ),
        Screen(
            "lead", "شاشة التيم ليدر (تاسكاتي، حالة المترجمين، أكواد العملاء، صفحة التاسك)",
            "The team leader's screen (my tasks, translator status, client codes, the task page)",
            path="/lead", roles=(Role.TEAM_LEAD,), admin_menu=False,
        ),
        Screen(
            "sales", "شاشة المبيعات (ميلاتي، رقمي وإيميلي، أكواد العملاء)", "The Sales screen (my mail, my number and mail, client codes)",
            path="/line", roles=(Role.SALES,), admin_menu=False,
        ),
        # The reviewer's one page: the candidate tests waiting to be marked, and the page that marks one. The reviewer is blind to
        # who the candidate is, so this screen carries a code and the work and nothing else. A team leader or the owner may
        # mark a test too; they reach it from the candidate's file and their own menu.
        Screen(
            "reviewer", "اختبارات المرشحين (للمراجع)", "Candidate tests (the reviewer)",
            path="/reviewer/tests", roles=(Role.REVIEWER,), admin_menu=False,
            capability="can_review_tests",
        ),
        Screen(
            "attendance", "الحضور والانصراف (الكارت وشاشة التسجيل)", "Attendance (the card and the check-in screen)",
            path="/attendance",
            roles=(
                Role.OPERATION, Role.TEAM_LEAD, Role.TRANSLATOR, Role.HR, Role.REVIEWER,
                Role.ACCOUNTING, Role.SALES,
            ),
            # The owner does not clock in.
            admin_menu=False,
        ),
        # A person's own leave: the balance, the requests, asking for time off. Every role has one (the page is only ever the
        # person's own).
        Screen(
            "leave", "إجازاتي", "My leave",
            path="/leave",
            roles=(
                Role.OPERATION, Role.TEAM_LEAD, Role.TRANSLATOR, Role.HR, Role.REVIEWER,
                Role.ACCOUNTING, Role.SALES,
            ),
            admin_menu=False,
        ),
        # Who delivered the most this month: the honour board is every employee's to look at. A person's own figures page
        # (quality, attendance, complaints) is HR's and the admin's: the board links to it only for them.
        Screen(
            "performance", "لوحة الأداء (ترتيب المترجمين بالإنتاجية)", "The performance board (translators ranked by productivity)",
            path="/hr/performance",
            roles=(
                Role.OPERATION, Role.TEAM_LEAD, Role.TRANSLATOR, Role.HR, Role.REVIEWER,
                Role.ACCOUNTING, Role.SALES,
            ),
            admin_menu=False,
        ),
        Screen(
            "chats", "الشات", "Chats",
            path="/chats",
            roles=(
                Role.OPERATION, Role.TEAM_LEAD, Role.TRANSLATOR, Role.HR, Role.REVIEWER,
                Role.ACCOUNTING, Role.SALES, Role.SUPPORT,
            ),
        ),
        # Technical support: the task list and the pages of a task read as the operation reads them, with every tool left out, and who
        # is free (the team board). No attendance, no leave, no pay: its person is not on the company's rules.
        Screen(
            "support", "الدعم الفني (التاسكات وحالة الفرق)", "Technical support (the tasks and the team board)",
            path="/tasks", roles=(Role.SUPPORT,), admin_menu=False,
        ),
    )
}


def enabled_keys(user):
    """The screens in this person's menu, in registry order: their role's, or (the admin's) the ones the admin oversees."""
    if not getattr(user, "is_authenticated", False):
        return []
    if user.is_admin_role:
        return [key for key, screen in SCREENS.items() if screen.admin_menu]
    return [key for key, screen in SCREENS.items() if screen.allows(user)]
