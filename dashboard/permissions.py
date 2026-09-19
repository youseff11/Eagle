"""Role based access helpers."""

from functools import wraps

from django.contrib.auth.views import redirect_to_login
from django.core.exceptions import PermissionDenied
from django.http import JsonResponse

from .models import Role


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

    return wrapper


admin_only = role_required(Role.ADMIN)
#: Section 24: accounting runs the month. The owner still sets the rules.
accounting_only = role_required(Role.ACCOUNTING)
operation_only = role_required(Role.OPERATION)
lead_only = role_required(Role.TEAM_LEAD)
translator_only = role_required(Role.TRANSLATOR)
