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


admin_only = role_required(Role.ADMIN)
operation_only = role_required(Role.OPERATION)
lead_only = role_required(Role.TEAM_LEAD)
translator_only = role_required(Role.TRANSLATOR)
