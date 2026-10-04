"""Which people see the React version of a screen, and which the classic one.

The move to React is one screen at a time (phase 5), and a screen is switched
over for some people before it is switched over for all of them: the admin
first, then one willing person, then a role. This is the switch. It lives in
``AppSettings.new_ui`` so turning a screen back to the classic page is a click
in the settings, not a deploy.

The switch decides *which page a person is sent to*. It does not decide who may
see the data: the new screen's endpoint asks the very questions the classic
page asks (``Screen.allows`` here, then the same ``identity`` / ``lines`` /
``ChatRoom.can_open`` rules the page uses), so a person who has the switch and
not the right cannot reach what they may not see, and a person who types the new
address by hand while the switch is off sees nothing the classic page would not
have shown them.

The classic page stays reachable with ``?classic=1``, whatever the switch says.
Without that an admin who switched a broken screen on for themselves could not
open the page that works.
"""

from dataclasses import dataclass

from . import attendance, spa
from .models import AppSettings, Role, User


@dataclass(frozen=True)
class Screen:
    key: str
    ar: str
    en: str
    #: Where the classic page is (a url name) and where the new one lives under /app/.
    classic: str
    path: str
    #: The roles this screen is for. The admin may always be switched on as well.
    roles: tuple
    #: Whether the classic page hands a switched-on person to the new one. A screen that cannot do
    #: everything the classic page does yet is shown in the new app's menu only: nobody is sent to it.
    redirects: bool = True
    #: Whether the admin is switched on by default, before anybody has touched the setting. Off for a screen that is
    #: another role's way into pages the admin already has (the Sales' mail and client codes are the operation's
    #: pages in the new app): the admin would otherwise find the same lines in the menu twice.
    admin_default: bool = True

    def allows(self, user):
        """May this person open the screen at all, whatever the switch says."""
        return bool(
            getattr(user, "is_authenticated", False)
            and (user.is_admin_role or user.role in self.roles)
        )

    @property
    def eligible_roles(self):
        """Role values (plain strings) the switch may name: the admin, then this screen's own."""
        return (Role.ADMIN.value,) + tuple(r.value for r in self.roles if r != Role.ADMIN)


SCREENS = {
    screen.key: screen
    for screen in (
        # The admin's own panel. Nobody else has one, so there is no role to switch on, and the admin is not on it until
        # they say so. The settings page is in it, and holds these very switches: the classic one stays reachable with
        # ``?classic=1`` for the day the new one breaks.
        Screen(
            "admin", "لوحة الأدمن (كل صفحاتها)", "The admin panel (all of its pages)",
            classic="admin_overview", path="/admin", roles=(), admin_default=False,
        ),
        # The money screens: the month's sheet, a payslip, attendance and output, violations, salaries, and (the admin's alone) the
        # payroll rules. Accounting runs the month; the admin is not on it until they say so.
        Screen(
            "accounts", "الحسابات (كشف الشهر، المخالفات والخصومات، الحضور والإنتاج، الرواتب، قواعد الحساب)",
            "Accounts (the month, violations, attendance and output, salaries, payroll rules)",
            classic="accounts_overview", path="/accounts", roles=(Role.ACCOUNTING,), admin_default=False,
        ),
        # Human resources: attendance and schedules, leave, recruitment, the people already hired, and the places and rules HR
        # keeps. HR runs it; the admin is not on it until they say so. A person who was only given the attendance flag
        # (``attendance_manager``) keeps the classic pages: the switch is for the HR role.
        Screen(
            "hr", "الموارد البشرية (الحضور والجداول، الإجازات، التوظيف، ملفات الموظفين، الإعدادات)",
            "Human resources (attendance and schedules, leave, recruitment, employee files, settings)",
            classic="hr_recruitment", path="/hr/recruitment", roles=(Role.HR,), admin_default=False,
        ),
        # The reviewer's one page: the candidate tests waiting to be marked, and the page that marks one. The reviewer is blind to
        # who the candidate is, so this screen carries a code and the work and nothing else. A team leader or the owner may
        # mark a test too; they reach it from the candidate's file and are not on this switch.
        Screen(
            "reviewer", "اختبارات المرشحين (للمراجع)", "Candidate tests (the reviewer)",
            classic="reviewer_tests", path="/reviewer/tests", roles=(Role.REVIEWER,), admin_default=False,
        ),
        Screen(
            "translator_home", "شغل المترجم", "The translator's desk",
            classic="translator_home", path="/translator", roles=(Role.TRANSLATOR,),
        ),
        Screen(
            "operation", "شاشة الأوبريشن (التاسكات والفرق)", "The operation's screen (tasks and teams)",
            classic="ops_tasks", path="/tasks", roles=(Role.OPERATION,),
        ),
        Screen(
            "lead", "شاشة التيم ليدر (تاسكاتي، حالة المترجمين، أكواد العملاء، صفحة التاسك)",
            "The team leader's screen (my tasks, translator status, client codes, the task page)",
            classic="lead_home", path="/lead", roles=(Role.TEAM_LEAD,), admin_default=False,
        ),
        Screen(
            "sales", "شاشة المبيعات (ميلاتي، رقمي وإيميلي، أكواد العملاء)", "The Sales screen (my mail, my number and mail, client codes)",
            classic="sales_line", path="/line", roles=(Role.SALES,), admin_default=False,
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
        # person's own). The admin is not on it until they say so.
        Screen(
            "leave", "إجازاتي", "My leave",
            classic="my_leave", path="/leave",
            roles=(
                Role.OPERATION, Role.TEAM_LEAD, Role.TRANSLATOR, Role.HR, Role.REVIEWER,
                Role.ACCOUNTING, Role.SALES,
            ),
            admin_default=False,
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

#: What a screen with no setting yet looks like: the admin's alone.
DEFAULT = {"roles": [Role.ADMIN.value], "users": []}


def default_for(key):
    """``DEFAULT`` for one screen: the admin's alone, or nobody's when the screen is not the admin's to begin with."""
    return {"roles": list(DEFAULT["roles"]) if SCREENS[key].admin_default else [], "users": []}

#: ``?classic=1`` on a classic page: show it, do not hand the person on.
CLASSIC_PARAM = "classic"


def app_url(key):
    return "/app" + SCREENS[key].path


def config(conf, key):
    """The switch for one screen as ``{"roles": [...], "users": [ids]}``, cleaned.

    The column is JSON that a person can edit by hand, so nothing in it is
    trusted: unknown roles and anything that is not an id are dropped, and a
    screen that is missing or unreadable is the default, never "everyone".
    """
    screen = SCREENS[key]
    raw = (conf.new_ui or {}) if isinstance(conf.new_ui, dict) else {}
    entry = raw.get(key)
    if not isinstance(entry, dict) or not isinstance(entry.get("roles"), list):
        return default_for(key)
    known = set(screen.eligible_roles)
    roles = [r for r in entry["roles"] if isinstance(r, str) and r in known]
    people = entry.get("users")
    users = [
        u for u in (people if isinstance(people, list) else [])
        if isinstance(u, int) and not isinstance(u, bool) and u > 0
    ]
    return {"roles": roles, "users": users}


def enabled(user, key, conf=None):
    """Is the React version of this screen the one this person is sent to."""
    screen = SCREENS.get(key)
    if screen is None or not screen.allows(user):
        return False
    setting = config(conf or AppSettings.load(), key)
    if user.pk in setting["users"] or user.role in setting["roles"]:
        return True
    return user.is_admin_role and Role.ADMIN.value in setting["roles"]


def enabled_keys(user):
    """The screens that are on for this person, in registry order."""
    if not getattr(user, "is_authenticated", False):
        return []
    conf = AppSettings.load()
    return [key for key in SCREENS if enabled(user, key, conf)]


def wants_classic(request):
    return request.GET.get(CLASSIC_PARAM) == "1"


def gate_in_app(user):
    """Does the new app draw this person's check-in screen and shift reminders itself.

    Yes once their ``attendance`` screen is switched on. Until then only the classic pages draw them, so whoever owes
    one is kept there (``hand_on``, ``spa.shell`` and the heartbeat all ask this one question, which is what keeps
    them from sending a person back and forth between the two interfaces).
    """
    return enabled(user, "attendance")


def hand_on(request, key):
    """Should this request for a classic page be sent to the new app instead.

    Only when the screen is switched on for this person *and* nothing stands in the way:

    * the screen does not hand anybody on yet (``Screen.redirects``);
    * they asked for the classic page by name (``?classic=1``);
    * the new app has not been built: a switched-on person would be sent to a bare
      503 with no way back, away from the classic pages that still work;
    * the check-in screen, or a check-out or extra-time reminder, is due and the person's
      ``attendance`` screen is not switched on. Then only the classic interface shows it, and a
      forgotten check-out costs the day, so they stay there until they have dealt with it. With
      the screen on the new app draws it over whatever page they are on (``AttendanceGate``).

    An assignment waiting for an answer (its 60-second clock running) used to keep a person on the
    classic page, which was the only one that could show the accept screen. The new app shows it
    itself now, over whatever page the person is on, so it is no longer a reason to stay.
    """
    user = request.user
    if not SCREENS[key].redirects or wants_classic(request) or not enabled(user, key):
        return False
    if spa.built_assets() is None:
        return False
    return key == "attendance" or gate_in_app(user) or not attendance.gate_for(user)


def pilot_candidates(key):
    """The people the admin may pick one by one for this screen."""
    screen = SCREENS[key]
    return User.objects.filter(is_active=True, role__in=screen.roles).order_by("username")
