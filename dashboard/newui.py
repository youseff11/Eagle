"""Which screens each person has in the app, and how the classic pages hand a person on to them.

The whole site is the React app now (phase 5 is done); the classic pages are kept only until they are deleted (phase 6),
and every one that has a screen in the app sends the person there. There is no per-screen switch any more: a person
has the screens of their role (the admin, all of them), and a classic address they open or are linked to lands on the
new page for the same thing.

The screens decide *where a person is sent*. They do not decide who may see the data: each screen's endpoints ask the
very questions the classic page asked (``Screen.allows`` here, then the same ``identity`` / ``lines`` /
``ChatRoom.can_open`` rules the page uses), so a person who types an address by hand sees nothing the classic page would
not have shown them.

The one case the classic page is still served: the app has not been built (a bare 503 with no way back would be worse),
which is how a checkout that never ran ``npm run build`` keeps working.
"""

from dataclasses import dataclass

from . import spa
from .models import Role


@dataclass(frozen=True)
class Screen:
    key: str
    ar: str
    en: str
    #: Where the classic page is (a url name) and where the new one lives under /app/.
    classic: str
    path: str
    #: The roles this screen is for. The admin may always open it.
    roles: tuple
    #: Whether the classic page hands a person on to the new one.
    redirects: bool = True
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
            classic="admin_overview", path="/admin", roles=(),
        ),
        # The money screens: the month's sheet, a payslip, attendance and output, violations, salaries, and (the admin's alone) the
        # payroll rules.
        Screen(
            "accounts", "الحسابات (كشف الشهر، المخالفات والخصومات، الحضور والإنتاج، الرواتب، قواعد الحساب)",
            "Accounts (the month, violations, attendance and output, salaries, payroll rules)",
            classic="accounts_overview", path="/accounts", roles=(Role.ACCOUNTING,),
        ),
        # Human resources: attendance and schedules, leave, recruitment, the people already hired, and the places and rules HR
        # keeps. A person who was only given the attendance flag (``attendance_manager``) has the attendance pages of it.
        Screen(
            "hr", "الموارد البشرية (الحضور والجداول، الإجازات، التوظيف، ملفات الموظفين، الإعدادات)",
            "Human resources (attendance and schedules, leave, recruitment, employee files, settings)",
            classic="hr_recruitment", path="/hr/recruitment", roles=(Role.HR,), capability="can_manage_attendance",
        ),
        Screen(
            "translator_home", "شغل المترجم", "The translator's desk",
            classic="translator_home", path="/translator", roles=(Role.TRANSLATOR,), admin_menu=False,
        ),
        Screen(
            "operation", "شاشة الأوبريشن (التاسكات والفرق)", "The operation's screen (tasks and teams)",
            classic="ops_tasks", path="/tasks", roles=(Role.OPERATION,),
        ),
        Screen(
            "lead", "شاشة التيم ليدر (تاسكاتي، حالة المترجمين، أكواد العملاء، صفحة التاسك)",
            "The team leader's screen (my tasks, translator status, client codes, the task page)",
            classic="lead_home", path="/lead", roles=(Role.TEAM_LEAD,), admin_menu=False,
        ),
        Screen(
            "sales", "شاشة المبيعات (ميلاتي، رقمي وإيميلي، أكواد العملاء)", "The Sales screen (my mail, my number and mail, client codes)",
            classic="sales_line", path="/line", roles=(Role.SALES,), admin_menu=False,
        ),
        # The reviewer's one page: the candidate tests waiting to be marked, and the page that marks one. The reviewer is blind to
        # who the candidate is, so this screen carries a code and the work and nothing else. A team leader or the owner may
        # mark a test too; they reach it from the candidate's file and their own menu.
        Screen(
            "reviewer", "اختبارات المرشحين (للمراجع)", "Candidate tests (the reviewer)",
            classic="reviewer_tests", path="/reviewer/tests", roles=(Role.REVIEWER,), admin_menu=False,
            capability="can_review_tests",
        ),
        Screen(
            "attendance", "الحضور والانصراف (الكارت وشاشة التسجيل)", "Attendance (the card and the check-in screen)",
            classic="my_attendance", path="/attendance",
            roles=(
                Role.OPERATION, Role.TEAM_LEAD, Role.TRANSLATOR, Role.HR, Role.REVIEWER,
                Role.ACCOUNTING, Role.SALES,
            ),
        ),
        # A person's own leave: the balance, the requests, asking for time off. Every role has one (the page is only ever the
        # person's own).
        Screen(
            "leave", "إجازاتي", "My leave",
            classic="my_leave", path="/leave",
            roles=(
                Role.OPERATION, Role.TEAM_LEAD, Role.TRANSLATOR, Role.HR, Role.REVIEWER,
                Role.ACCOUNTING, Role.SALES,
            ),
            admin_menu=False,
        ),
        Screen(
            "chats", "الشات", "Chats",
            classic="ops_chats", path="/chats",
            roles=(
                Role.OPERATION, Role.TEAM_LEAD, Role.TRANSLATOR, Role.HR, Role.REVIEWER,
                Role.ACCOUNTING, Role.SALES,
            ),
        ),
    )
}


def app_url(key):
    return "/app" + SCREENS[key].path


def enabled(user, key):
    """Is the app's version of this screen the one this person is sent to: whenever they may open it."""
    screen = SCREENS.get(key)
    return screen is not None and screen.allows(user)


def enabled_keys(user):
    """The screens in this person's menu, in registry order: their role's, or (the admin's) the ones the admin oversees."""
    if not getattr(user, "is_authenticated", False):
        return []
    if user.is_admin_role:
        return [key for key, screen in SCREENS.items() if screen.admin_menu]
    return [key for key, screen in SCREENS.items() if screen.allows(user)]


def gate_in_app(user):
    """Does the app draw this person's check-in screen and shift reminders itself. Yes, for everybody who has one."""
    return enabled(user, "attendance")


def hand_on(request, key):
    """Should this request for a classic page be sent to the app instead.

    Whenever the person may open the screen, unless:

    * the screen does not hand anybody on (``Screen.redirects``);
    * the app has not been built: a person would be sent to a bare 503 with no way back, away from the classic pages that
      still work.

    An assignment waiting for an answer (its 60-second clock running), the check-in screen and a ringing call are drawn by
    the app over whatever page the person is on, so none of them is a reason to stay on a classic page any more.
    """
    user = request.user
    if not SCREENS[key].redirects or not enabled(user, key):
        return False
    return spa.built_assets() is not None
