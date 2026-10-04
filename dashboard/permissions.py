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


def api_gate(check):
    """``check(user)`` decides, a refusal is a logged 403 and nobody signed in is a 401.

    Some doors are not guarded by role alone (attendance rights are a flag a person can be given, recruitment is HR and the
    owner), so a door asks the very question the screen asks instead of a list of roles.
    """

    def decorator(view):
        @wraps(view)
        def wrapper(request, *args, **kwargs):
            user = request.user
            if not user.is_authenticated:
                return JsonResponse({"ok": False, "error": "auth"}, status=401)
            if check(user):
                return view(request, *args, **kwargs)
            _refused(request, f"api_gate {view.__name__}")
            return JsonResponse({"ok": False, "error": "forbidden"}, status=403)

        return wrapper

    return decorator


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
