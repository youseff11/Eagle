"""The page that carries the React app: ``/app/`` and everything under it.

Django renders this one HTML page and the browser does the rest. It carries only
what has to be there before any script runs: the language and theme (so nothing
flashes), the icon sprite, and where the built files are. It carries no data
about the person or about any client - the app asks ``/api/v1/`` for that, and
the API applies the permissions.

The built files come from Vite (``frontend/``, built into ``static/app/``) and are
found through its manifest, so their hashed names never have to be written here.
Until the app has been built the page says so instead of failing.

The check-in screen is not part of the new app and may not be skipped: when it is
due, the person is sent to the classic interface, where it opens by itself. The
check-out and extra-time reminders can be put off there, so they do not send anyone
away; they are not shown here yet.

The page carries a Content-Security-Policy. The app has no inline script or style, so
the policy is strict: scripts and styles from this site (and the font stylesheet from
Google, as in the classic pages), connections to this site and its own WebSocket,
no framing, no plugins, no ``<base>``. The one inline thing is the icon sprite's
``style="display:none"``, allowed as a style *attribute* only. The point is the
CSRF cookie, which the app must be able to read: a policy that stops a script from
running at all is worth more than one more careful escape.
"""

import json
from pathlib import Path

from django.conf import settings
from django.contrib.auth.decorators import login_required
from django.http import HttpResponse
from django.shortcuts import redirect, render
from django.templatetags.static import static
from django.views.decorators.cache import never_cache
from django.views.decorators.csrf import ensure_csrf_cookie
from django.views.decorators.http import require_safe

from . import attendance
from .models import AppSettings

#: Where ``npm run build`` writes its manifest (frontend/vite.config.ts).
MANIFEST_PATH = Path(settings.BASE_DIR) / "static" / "app" / "manifest.json"
#: The manifest entry for the app's script (``build.rollupOptions.input``).
ENTRY_KEY = "src/main.tsx"


def built_assets():
    """``{"js": url, "css": [urls]}`` for the built app, or ``None`` if it is not built.

    The URLs go through ``static()``, so in production they carry the hashed names
    that ``collectstatic`` made and a stylesheet can never be stale at the edge.
    """
    try:
        manifest = json.loads(MANIFEST_PATH.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    if not isinstance(manifest, dict):
        return None
    entry = manifest.get(ENTRY_KEY)
    if not isinstance(entry, dict):
        entry = next(
            (item for item in manifest.values() if isinstance(item, dict) and item.get("isEntry")),
            None,
        )
    if not entry or not entry.get("file"):
        return None
    return {
        "js": static("app/" + entry["file"]),
        "css": [static("app/" + name) for name in entry.get("css", [])],
    }


def _config(request):
    """What the page tells the app before it can ask: language, theme, poll interval.

    The cookie is read the way the classic pages read it (``context_processors.eagle``)
    but only the two known values are let through, because this goes into JSON.
    """
    lang = request.COOKIES.get("eagle_lang")
    theme = request.COOKIES.get("eagle_theme")
    # A cookie that is not one of the two known values is not a choice: the saved
    # preference decides, as if the cookie were not there.
    lang = lang if lang in ("ar", "en") else request.user.ui_lang
    theme = theme if theme in ("dark", "light") else request.user.ui_theme
    return {
        "lang": "en" if lang == "en" else "ar",
        "theme": "light" if theme == "light" else "dark",
        "pollMs": AppSettings.load().poll_ms,
    }


def content_security_policy(request):
    """The policy for the app's page. ``request.get_host()`` is checked against ALLOWED_HOSTS."""
    socket = f"{'wss' if request.is_secure() else 'ws'}://{request.get_host()}"
    return "; ".join([
        "default-src 'self'",
        "script-src 'self'",
        "style-src 'self' https://fonts.googleapis.com",
        # templates/partials/icons.html: <svg style="display:none">.
        "style-src-attr 'unsafe-inline'",
        "font-src https://fonts.gstatic.com",
        "img-src 'self' data:",
        f"connect-src 'self' {socket}",
        "frame-ancestors 'none'",
        "base-uri 'none'",
        "object-src 'none'",
        "form-action 'self'",
    ])


@login_required
@never_cache
@ensure_csrf_cookie
@require_safe
def shell(request, path=""):
    gate = attendance.gate_for(request.user)
    if gate and gate.get("kind") == "check_in":
        return redirect("dashboard:home")
    assets = built_assets()
    if assets is None:
        return HttpResponse(
            "الواجهة الجديدة لسه متبنتش. شغّل: cd frontend && npm ci && npm run build\n"
            "The new interface has not been built. Run: cd frontend && npm ci && npm run build\n",
            status=503,
            content_type="text/plain; charset=utf-8",
        )
    response = render(request, "app/shell.html", {"assets": assets, "app_config": _config(request)})
    response["Content-Security-Policy"] = content_security_policy(request)
    return response
