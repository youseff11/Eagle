"""The pages that are still pages: sign-in, the public legal pages, the file door, the Google round trip.

Everything else the person sees is the React app (``spa.py``) over the JSON endpoints (``api_*.py``). The old interface's
addresses are kept as redirects in ``legacy.py``.
"""

from django.contrib.auth import login as auth_login, logout as auth_logout
from django.contrib.auth.decorators import login_required
from django.contrib.auth.forms import AuthenticationForm
from django.http import Http404, HttpResponse, JsonResponse
from django.shortcuts import redirect, render
from django.urls import reverse
from django.utils.http import url_has_allowed_host_and_scheme
from django.views.decorators.http import require_POST, require_safe

from . import galiases, identity, services
from .models import AppSettings
from .permissions import admin_only, user_may_open

# ---------------------------------------------------------------------------
# Auth
# ---------------------------------------------------------------------------

def login_view(request):
    if request.user.is_authenticated:
        return redirect("dashboard:home")
    form = AuthenticationForm(request, data=request.POST or None)
    if request.method == "POST" and form.is_valid():
        auth_login(request, form.get_user())
        nxt = request.POST.get("next") or request.GET.get("next") or ""
        # Safe to redirect to is not the same question as allowed to open. A
        # translator arriving from a link to /panel/ used to sign in fine and
        # land on a bare 403; now the door they cannot open simply drops them
        # at their own one.
        if (
            nxt
            and url_has_allowed_host_and_scheme(
                nxt,
                allowed_hosts={request.get_host()},
                require_https=request.is_secure(),
            )
            and user_may_open(request.user, nxt)
        ):
            return redirect(nxt)
        return redirect("dashboard:home")

    form.fields["username"].widget.attrs.update({
        "class": "input", "dir": "ltr", "autocomplete": "username",
        "autofocus": True, "placeholder": "username",
    })
    form.fields["password"].widget.attrs.update({
        "class": "input", "dir": "ltr", "autocomplete": "current-password",
        "placeholder": "••••••••",
    })
    return render(request, "auth/login.html", {"form": form, "next": request.GET.get("next", "")})


@require_POST
def logout_view(request):
    auth_logout(request)
    return redirect("dashboard:login")


@require_safe
def healthz(request):
    """Liveness probe for the host. No login, no database, no data.

    It answers "the process is up" and nothing more, so a Neon hiccup does not
    make the host restart a healthy server.
    """
    return HttpResponse("ok", content_type="text/plain")


@login_required
def home(request):
    """Each role's own landing page: the app's, which picks the person's own screen (``HomePage``)."""
    return redirect("/app/")


@login_required
def serve_file(request, name):
    """Every stored file the dashboard links to is opened here.

    The person must be allowed to read the conversation, task or record the
    file belongs to (``files.may_open``) - the same rule as the page that
    listed it, so a URL copied out of one account opens nothing in another.
    A refusal is a logged 404: a 403 would confirm the file exists.
    """
    from urllib.parse import quote

    from django.core.files.storage import default_storage
    from django.http import HttpResponse

    from . import files

    name = name.replace("\\", "/").lstrip("/")
    if not name or ".." in name.split("/"):
        raise Http404
    allowed, owner = files.may_open(request.user, name)
    if not allowed:
        identity.hidden(request, "file")
    # A face drawn on every page is not a file somebody is carrying out: it does not count toward the hour's limit.
    if not (owner and owner[0] == "avatar") and not identity.count_file_open(request):
        return HttpResponse("Too many files opened this hour.", status=429)
    if request.GET.get("preview") == "1":
        from django.core.cache import cache

        cached = cache.get(f"eagle:preview:{name}")
        if cached is not None:
            return JsonResponse({"ok": True, **cached})
    try:
        with default_storage.open(name, "rb") as handle:
            data = handle.read()
    except Exception:  # noqa: BLE001 - a missing blob is a 404, not a 500
        raise Http404
    # The document card's two helpers: the text of a Word file's first page,
    # and the thumbnail Word saved inside it. Same file, same permission.
    wanted = request.GET.get("preview", "")
    if wanted == "1":
        return JsonResponse({"ok": True, **files.document_preview(name, data)})
    if wanted == "full":
        text, truncated = files.document_full_text(name, data)
        response = JsonResponse({"ok": True, "text": text, "truncated": truncated})
        response["Cache-Control"] = "private, no-store"
        return response
    if wanted == "thumb":
        thumb, thumb_kind = files.document_thumbnail(name, data)
        if not thumb:
            raise Http404
        response = HttpResponse(thumb, content_type=thumb_kind)
        response["Cache-Control"] = "private, max-age=86400"
        return response

    kind = files.content_type(name)
    response = HttpResponse(data, content_type=kind)
    shown = files.download_name(request.user, name, owner)
    # A file opened inline runs as our own site, with the viewer's session, if the browser takes it for a
    # document (an SVG, HTML, any XML type, script). Only the types known to be inert open in the page;
    # everything else is a download - see ``files.opens_inline``.
    disposition = "inline" if (files.opens_inline(kind) and request.GET.get("dl") != "1") else "attachment"
    response["Content-Disposition"] = f"{disposition}; filename*=UTF-8''{quote(shown)}"
    # Private: a shared proxy or Cloudflare must never keep a client's file.
    response["Cache-Control"] = "private, max-age=3600"
    response["X-Content-Type-Options"] = "nosniff"
    return response


def csrf_failure(request, reason=""):
    """``CSRF_FAILURE_VIEW``: JSON for ``/api/v1/``, Django's own page for the rest.

    A front end that POSTs without the token gets an answer it can read; a
    person whose form expired, and the pages' own scripts, get what they always
    did.
    """
    if request.path.startswith("/api/v1/"):
        return JsonResponse({"ok": False, "error": "csrf"}, status=403)
    from django.views.csrf import csrf_failure as django_csrf_failure

    return django_csrf_failure(request, reason=reason)


def permission_denied(request, exception=None):
    """The project's 403 page (``handler403``) - and the refusal's audit row.

    Every ``PermissionDenied`` raised anywhere lands here, so logging it here
    logs each one exactly once, whichever guard or view raised it.
    """
    identity.record_denied(request, str(exception or "")[:200] or "permission denied")
    return render(request, "403.html", status=403)


# ---------------------------------------------------------------------------
# Public legal pages
#
# These are open to everyone — no login. Meta requires a reachable privacy
# policy and data-deletion page before a WhatsApp app can be published, and
# the pages carry the registered legal name for business verification.
# ---------------------------------------------------------------------------

def privacy(request):
    return render(request, "public/privacy.html", {"page": "privacy"})


def terms(request):
    return render(request, "public/terms.html", {"page": "terms"})


def data_deletion(request):
    return render(request, "public/data_deletion.html", {"page": "deletion"})


# -- the alias list from Google Workspace (galiases.py) -----------------------
#
# The two steps of Google's sign-in are a round trip through Google's own page, so they are views and not JSON doors. Sync and
# disconnect are doors (``api_admin_settings``). The app does not draw Django's flash messages, so a step that fails says why
# in ``AppSettings.google_sync_error``, which the settings page shows next to the link's status.

GOOGLE_STATE_KEY = "google_alias_state"
SETTINGS = "/app/admin/settings"


def _failed(message):
    conf = AppSettings.load()
    AppSettings.objects.filter(pk=conf.pk).update(google_sync_error=message[:300])
    return redirect(SETTINGS)


@admin_only
def google_connect(request):
    conf = AppSettings.load()
    if not galiases.is_configured(conf):
        return _failed("اكتب Client ID وClient Secret واحفظ الأول.")
    state = galiases.new_state()
    request.session[GOOGLE_STATE_KEY] = state
    redirect_uri = request.build_absolute_uri(reverse("dashboard:google_callback"))
    return redirect(galiases.auth_url(conf, redirect_uri, state))


@admin_only
def google_callback(request):
    expected = request.session.pop(GOOGLE_STATE_KEY, None)
    if not expected or request.GET.get("state") != expected:
        return _failed("الربط مع Google مااكتملش - جرّب تاني.")
    if request.GET.get("error") or not request.GET.get("code"):
        return _failed("Google مااداش الصلاحية.")
    conf = AppSettings.load()
    redirect_uri = request.build_absolute_uri(reverse("dashboard:google_callback"))
    try:
        galiases.exchange_code(conf, request.GET["code"], redirect_uri)
    except galiases.SyncError as exc:
        return _failed(str(exc))
    services.log(request.user, "settings.google_connect")
    # A first sync right away: it records its own error, or clears the last one.
    galiases.sync(conf, force=True)
    return redirect(SETTINGS)
