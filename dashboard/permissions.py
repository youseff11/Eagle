"""Role based access helpers."""

from functools import wraps
from urllib.parse import urlparse

from django.contrib.auth.views import redirect_to_login
from django.core.exceptions import PermissionDenied
from django.http import JsonResponse
from django.urls import Resolver404, resolve

from .models import Role


def _refused(request, why):
    """Write down a refusal that is *answered* here rather than raised.

    A raised ``PermissionDenied`` is logged once, by ``views.permission_denied``
    (the project's 403 handler) - so only the JSON answer below calls this.

    Imported late: ``identity`` reads the audit model, and this module is
    imported by everything, including code that runs before apps are ready.
    """
    from . import identity

    identity.record_denied(request, why)


def role_required(*roles):
    """Allow only the given roles (the admin role always passes)."""

    def decorator(view):
        @wraps(view)
        def wrapper(request, *args, **kwargs):
            user = request.user
            if not user.is_authenticated:
                return redirect_to_login(request.get_full_path())
            if user.is_admin_role or user.role in roles:
                return view(request, *args, **kwargs)
            raise PermissionDenied("Your role cannot open this page.")

        # Published for user_may_open. Set after @wraps, which copies the
        # wrapped function's __dict__ over the wrapper's.
        wrapper.eagle_allows = lambda u: u.is_admin_role or u.role in roles
        return wrapper

    return decorator


def api_role_required(*roles):
    """Same as :func:`role_required` but answers JSON."""

    def decorator(view):
        @wraps(view)
        def wrapper(request, *args, **kwargs):
            user = request.user
            if not user.is_authenticated:
                return JsonResponse({"ok": False, "error": "auth"}, status=401)
            if user.is_admin_role or user.role in roles:
                return view(request, *args, **kwargs)
            _refused(request, f"api_role_required {view.__name__}")
            return JsonResponse({"ok": False, "error": "forbidden"}, status=403)

        return wrapper

    return decorator


def _gate(check, message):
    """Build a decorator from a predicate on the user.

    The three recruitment gates differ only in which property they read, so
    they are made here rather than written out three times.
    """

    def decorator(view):
        @wraps(view)
        def wrapper(request, *args, **kwargs):
            user = request.user
            if not user.is_authenticated:
                return redirect_to_login(request.get_full_path())
            if check(user):
                return view(request, *args, **kwargs)
            raise PermissionDenied(message)

        wrapper.eagle_allows = check
        return wrapper

    return decorator


#: Section 24. The owner passes every one of these; nobody else passes them all.
recruit_required = _gate(
    lambda u: u.can_recruit, "Only HR and the owner can open recruitment."
)
reviewer_required = _gate(
    lambda u: u.can_review_tests, "Only a reviewer can mark a candidate's test."
)
owner_required = _gate(
    lambda u: u.can_approve_hiring, "Only the owner decides a hire."
)
#: The /clients/ pages. Opening them is not seeing the identity - that is
#: ``can_see_client_identity``, checked again inside the view.
client_codes_required = _gate(
    lambda u: u.can_open_client_codes, "Your role cannot open the client pages."
)


def hr_required(view):
    """Attendance rights. Eagle has no HR *role* - it is a flag on the person,
    so an operations lead can be given the board without being made an admin."""

    @wraps(view)
    def wrapper(request, *args, **kwargs):
        user = request.user
        if not user.is_authenticated:
            return redirect_to_login(request.get_full_path())
        if user.can_manage_attendance:
            return view(request, *args, **kwargs)
        raise PermissionDenied("Your role cannot open the attendance board.")

    wrapper.eagle_allows = lambda u: u.can_manage_attendance
    return wrapper


def user_may_open(user, url):
    """Would this person's own guard let them open ``url``?

    Django's ``?next=`` handling asks only whether the URL is *safe to redirect
    to* - never whether the person may open it. So a translator who arrived at
    ``/login/?next=/panel/`` (from a bookmark, an open tab, a shared link) was
    signed in correctly and then thrown straight onto a bare 403 page. The
    session was fine; the destination was not theirs.

    The answer is read off the view's own decorator, so there is no second copy
    of the rules here to drift out of step with the guards.

    A view with no guard is open to anyone signed in. A view behind two guards
    publishes only the outer one - the worst case there is the old behaviour,
    never a page opening that should not.
    """
    if not user.is_authenticated:
        return False
    try:
        match = resolve(urlparse(url).path)
    except Resolver404:
        return False
    allows = getattr(match.func, "eagle_allows", None)
    return True if allows is None else bool(allows(user))


admin_only = role_required(Role.ADMIN)
#: Section 24: accounting runs the month. The owner still sets the rules.
accounting_only = role_required(Role.ACCOUNTING)
operation_only = role_required(Role.OPERATION)
lead_only = role_required(Role.TEAM_LEAD)
translator_only = role_required(Role.TRANSLATOR)
