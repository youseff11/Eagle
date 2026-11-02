"""Technical support opens an employee's account and sees their screen as they see it (02/11/2026).

The owner's rule: support picks a person on «حسابات الموظفين» and the app is that person's - the menu, the pages, the chats,
the badges - until support presses «ارجع لحسابي». It may act there as the person does (the owner's answer, 02/11/2026: a
message, a hand-in, a change), with one exception: attendance. A check-in, check-out, break or extra time is a record of the
person being at work, so it is never punched in their name (``SupportMiddleware``). The person themselves is not touched
either: no ``last_login``, no presence (the heartbeat skips them), no check-in screen.

Who may be opened: a working employee (active, not deleted), never the owner (an admin) and never another support account.
Each entry and each way out is written to the audit log with the support person's name, and so is every other audit row
written while looking (``identity.audit`` adds who was really there).

The session is switched by hand, not with ``login()``: that would fire ``user_logged_in`` and stamp the person's last login.
"""

from django.contrib.auth import BACKEND_SESSION_KEY, HASH_SESSION_KEY, SESSION_KEY, logout
from django.http import JsonResponse
from django.middleware.csrf import rotate_token
from django.urls import reverse

from .models import Role, User

#: Where the session keeps who is really looking.
SESSION_BY = "eagle_impersonator"
ENTER = "support.account_enter"
LEAVE = "support.account_leave"
PASSWORD_SET = "support.password_set"

#: The doors that stay shut while support is inside: a punch is the person being at work, not support.
SHUT = ("dashboard:api_attendance_punch",)


def may_act(actor):
    """May this person open others' accounts and set their passwords: technical support (and the owner, as every door)."""
    return bool(
        getattr(actor, "is_authenticated", False) and actor.is_active and not actor.is_deleted
        and (actor.is_support or actor.is_admin_role)
    )


def accounts():
    """The accounts support may open: the working staff, without the owner and without support itself."""
    return (
        User.objects.filter(is_active=True, deleted_at__isnull=True, is_superuser=False)
        .exclude(role__in=(Role.ADMIN, Role.SUPPORT))
        .order_by("role", "first_name", "username")
    )


def may_open(actor, person):
    return may_act(actor) and person.pk != actor.pk and accounts().filter(pk=person.pk).exists()


def by(request):
    """The support person looking through this session, or ``None`` (set by ``SupportMiddleware``)."""
    return getattr(request, "impersonator", None)


def _switch(request, user, backend):
    """Make ``user`` the one signed in on this session: a fresh key, nothing of the old session carried over."""
    request.session.flush()
    request.session[SESSION_KEY] = user._meta.pk.value_to_string(user)
    request.session[BACKEND_SESSION_KEY] = backend
    request.session[HASH_SESSION_KEY] = user.get_session_auth_hash()
    request.user = user
    rotate_token(request)


def enter(request, person):
    from . import identity

    actor = request.user
    backend = request.session.get(BACKEND_SESSION_KEY) or "django.contrib.auth.backends.ModelBackend"
    identity.audit(request, actor, ENTER, person.username, f"opened {person.username}'s account")
    _switch(request, person, backend)
    request.session[SESSION_BY] = actor.pk
    request.impersonator = actor


def leave(request):
    """Back to the support person's own account. ``False`` when this session is nobody's view."""
    from . import identity

    actor = by(request)
    if actor is None:
        return False
    person = request.user
    backend = request.session.get(BACKEND_SESSION_KEY) or "django.contrib.auth.backends.ModelBackend"
    _switch(request, actor, backend)
    request.impersonator = None
    identity.audit(request, actor, LEAVE, person.username, f"left {person.username}'s account")
    return True


class SupportMiddleware:
    """Knows who is really there, and keeps the attendance punch shut to them.

    A session whose support person is gone (switched off, deleted, another role now) or whose person may no longer be opened
    (became an admin, was switched off) is signed out on the spot, not left looking.
    """

    def __init__(self, get_response):
        self.get_response = get_response
        self._shut = None

    def _shut_paths(self):
        if self._shut is None:
            self._shut = {reverse(name) for name in SHUT}
        return self._shut

    def __call__(self, request):
        request.impersonator = None
        actor_id = request.session.get(SESSION_BY) if hasattr(request, "session") else None
        if actor_id is not None:
            actor = User.objects.filter(pk=actor_id).first()
            if actor is None or not request.user.is_authenticated or not may_open(actor, request.user):
                logout(request)
            else:
                request.impersonator = actor
                if request.path_info in self._shut_paths():
                    # The punch's own refusal shape (``ok: false`` with words), so the card says it instead of failing.
                    response = JsonResponse({
                        "ok": False, "error": "support_inside",
                        "ar": "الحضور مابيتسجّلش من الدعم الفني: الموظف بيسجّله بنفسه.",
                        "en": "Attendance is not punched by technical support: the employee punches it themselves.",
                    })
                    response["Cache-Control"] = "private, no-store"
                    return response
        return self.get_response(request)
