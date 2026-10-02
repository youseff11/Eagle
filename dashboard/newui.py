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
from .models import AppSettings, Assignment, AssignmentStatus, Role, User


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
        Screen(
            "translator_home", "شغل المترجم", "The translator's desk",
            classic="translator_home", path="/translator", roles=(Role.TRANSLATOR,),
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
        return {"roles": list(DEFAULT["roles"]), "users": []}
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


def hand_on(request, key):
    """Should this request for a classic page be sent to the new app instead.

    Only when the screen is switched on for this person *and* nothing stands in the way:

    * the screen does not hand anybody on yet (``Screen.redirects``);
    * they asked for the classic page by name (``?classic=1``);
    * the new app has not been built: a switched-on person would be sent to a bare
      503 with no way back, away from the classic pages that still work;
    * the check-in screen, or a check-out or extra-time reminder, is due. Those are
      shown only by the classic interface, and a forgotten check-out costs the day, so
      the person stays there until they have dealt with it;
    * an assignment is waiting for an answer. Its 60-second clock is already running,
      and every page load on the way to the screen that shows it comes out of it.
    """
    user = request.user
    if not SCREENS[key].redirects or wants_classic(request) or not enabled(user, key):
        return False
    if spa.built_assets() is None:
        return False
    if attendance.gate_for(user):
        return False
    return not Assignment.objects.filter(assignee=user, status=AssignmentStatus.PENDING).exists()


def pilot_candidates(key):
    """The people the admin may pick one by one for this screen."""
    screen = SCREENS[key]
    return User.objects.filter(is_active=True, role__in=screen.roles).order_by("username")
