"""The alias list, read from Google Workspace itself (30/09/2026).

Before this the admin kept ``AppSettings.mail_aliases`` by hand: add an alias
in the Google Admin console, then type it again on the settings page. Now the
dashboard asks Google for the aliases on the company mailbox (``imap_user``)
and writes the list itself - an alias added there shows up in the staff
page's list, and one deleted there leaves it, along with whoever held it.

How it talks to Google, on the standard library like everything else here:

* The admin pastes an OAuth client (a "Web application" client in Google
  Cloud, Admin SDK API enabled) on the settings page and clicks "connect".
  Google asks them to sign in as the Workspace admin and approve one
  read-only scope; the refresh token it hands back is kept on the settings
  row. Nothing is ever written to Google.
* :func:`sync` trades the refresh token for an access token and lists the
  aliases. It runs after every mail fetch (at most every
  ``SYNC_EVERY_SECONDS``), when the staff page opens (at most every
  ``STAFF_PAGE_EVERY_SECONDS``), and from the "sync now" button.

A failed sync changes nothing: the list stays what it was and the error is
shown on the settings page. The list is only ever replaced by an answer
Google actually gave.
"""

import json
import secrets
import urllib.error
import urllib.parse
import urllib.request
from datetime import timedelta

from django.utils import timezone

from . import net
from .models import AppSettings, AuditLog, User

SCOPE = "https://www.googleapis.com/auth/admin.directory.user.alias.readonly"
AUTH_URL = "https://accounts.google.com/o/oauth2/v2/auth"
TOKEN_URL = "https://oauth2.googleapis.com/token"
ALIASES_URL = "https://admin.googleapis.com/admin/directory/v1/users/{user}/aliases"

#: After a mail fetch. The fetch runs every few minutes; Google does not need
#: asking that often.
SYNC_EVERY_SECONDS = 10 * 60
#: When the staff page opens - the moment the admin is about to pick an
#: address, often right after adding it in Google.
STAFF_PAGE_EVERY_SECONDS = 60

TIMEOUT = 15


class SyncError(Exception):
    """A failure worth showing the admin, already in Arabic."""


# ---------------------------------------------------------------------------
# Connecting (OAuth)
# ---------------------------------------------------------------------------

def is_configured(conf):
    return bool(conf.google_client_id and conf.google_client_secret)


def is_connected(conf):
    return bool(is_configured(conf) and conf.google_refresh_token)


def new_state():
    return secrets.token_urlsafe(24)


def auth_url(conf, redirect_uri, state):
    """Where the "connect" button sends the admin."""
    params = {
        "client_id": conf.google_client_id.strip(),
        "redirect_uri": redirect_uri,
        "response_type": "code",
        "scope": SCOPE,
        # offline + consent: Google only hands out a refresh token on a
        # consent screen, and a reconnect has to get a fresh one.
        "access_type": "offline",
        "prompt": "consent",
        "include_granted_scopes": "false",
        "state": state,
    }
    if conf.imap_user:
        params["login_hint"] = conf.imap_user.strip()
    return AUTH_URL + "?" + urllib.parse.urlencode(params)


def _post_form(url, fields):
    body = urllib.parse.urlencode(fields).encode()
    request = urllib.request.Request(
        url, data=body, method="POST",
        headers={"Content-Type": "application/x-www-form-urlencoded"},
    )
    return _call(request)


def _call(request):
    try:
        with net.urlopen(request, timeout=TIMEOUT) as response:
            return json.loads(response.read().decode() or "{}")
    except urllib.error.HTTPError as exc:
        try:
            payload = json.loads(exc.read().decode() or "{}")
        except ValueError:
            payload = {}
        raise SyncError(_explain(exc.code, payload)) from None
    except (urllib.error.URLError, TimeoutError, OSError) as exc:
        raise SyncError(f"مقدرناش نوصل لـ Google: {exc}") from None
    except ValueError:
        raise SyncError("Google رد برد مش مفهوم.") from None


def _explain(status, payload):
    """Google's error, in words the admin can act on."""
    error = payload.get("error")
    if isinstance(error, dict):
        code = str(error.get("status") or "")
        text = str(error.get("message") or "")
    else:
        code = str(error or "")
        text = str(payload.get("error_description") or "")
    if code == "invalid_grant":
        return "الربط مع Google اتلغى أو انتهى - اضغط «اربط Google» تاني."
    if code in ("invalid_client", "unauthorized_client"):
        return "Client ID أو Client Secret غلط."
    if status == 403 and ("has not been used" in text or "disabled" in text.lower()):
        return "Admin SDK API مش متفعّل في مشروع Google Cloud."
    if status == 403:
        return "الحساب اللي اتربط مش أدمن على Workspace، أو مش موافق على الصلاحية."
    if status == 404:
        return "Google مش لاقي المستخدم ده - راجع خانة IMAP User."
    return f"Google رد بخطأ {status}: {(text or code)[:160]}"


def exchange_code(conf, code, redirect_uri):
    """The code from Google's redirect -> a refresh token, saved on ``conf``."""
    answer = _post_form(TOKEN_URL, {
        "code": code,
        "client_id": conf.google_client_id.strip(),
        "client_secret": conf.google_client_secret.strip(),
        "redirect_uri": redirect_uri,
        "grant_type": "authorization_code",
    })
    token = answer.get("refresh_token")
    if not token:
        raise SyncError("Google مارجّعش refresh token - اشيل صلاحية التطبيق من حسابك واربط تاني.")
    AppSettings.objects.filter(pk=conf.pk).update(google_refresh_token=token)
    AppSettings._cached = None
    conf.google_refresh_token = token
    return token


def disconnect(conf):
    AppSettings.objects.filter(pk=conf.pk).update(google_refresh_token="", google_sync_error="")
    AppSettings._cached = None


# ---------------------------------------------------------------------------
# Reading the aliases
# ---------------------------------------------------------------------------

def _access_token(conf):
    answer = _post_form(TOKEN_URL, {
        "client_id": conf.google_client_id.strip(),
        "client_secret": conf.google_client_secret.strip(),
        "refresh_token": conf.google_refresh_token.strip(),
        "grant_type": "refresh_token",
    })
    token = answer.get("access_token")
    if not token:
        raise SyncError("Google مارجّعش access token.")
    return token


def fetch_aliases(conf):
    """The aliases on the company mailbox, lower-case, as Google has them."""
    mailbox = (conf.imap_user or "").strip()
    if "@" not in mailbox:
        raise SyncError("اكتب IMAP User الأول (ميل الشركة).")
    request = urllib.request.Request(
        ALIASES_URL.format(user=urllib.parse.quote(mailbox)),
        headers={"Authorization": f"Bearer {_access_token(conf)}"},
    )
    answer = _call(request)
    # An empty mailbox answers {"kind": ...} with no "aliases" key. Anything
    # without "kind" is not the answer we asked for - never wipe on that.
    if "kind" not in answer:
        raise SyncError("Google رد برد مش متوقع.")
    out = []
    for row in answer.get("aliases") or []:
        address = str(row.get("alias") or "").strip().lower()
        if address and "@" in address and address not in out:
            out.append(address)
    return out


def apply(conf, google_aliases):
    """Write Google's list onto ``conf`` and release addresses that are gone.

    ``(added, removed, released)``: addresses new to the list, addresses that
    left it, and the people who held one of those. Hidden addresses
    (``mail_aliases_hidden`` - hr@, accounts@) are never offered.
    """
    hidden = set(conf.hidden_alias_list)
    before = conf.alias_list
    after = sorted(a for a in google_aliases if a not in hidden)
    added = [a for a in after if a not in before]
    removed = [a for a in before if a not in after]

    if before != after:
        AppSettings.objects.filter(pk=conf.pk).update(mail_aliases="\n".join(after))
        conf.mail_aliases = "\n".join(after)

    # Whoever holds an address Google no longer has would never receive on
    # it again - better their mail goes to the admin than into a hole. Only
    # addresses on the mailbox's own domain: nothing else came from Google.
    domain = (conf.imap_user or "").strip().lower().rpartition("@")[2]
    alive = set(google_aliases)
    released = []
    if domain:
        for person in User.objects.filter(mail_alias__iendswith="@" + domain):
            if person.mail_alias.strip().lower() not in alive:
                released.append((person, person.mail_alias))
        for person, address in released:
            User.objects.filter(pk=person.pk).update(mail_alias="")
            AuditLog.objects.create(
                actor=None, action="user.mail_alias", target=person.username,
                detail=f"{address} -> - (اتشال من Google)",
            )
    if added or removed:
        AuditLog.objects.create(
            actor=None, action="settings.mail_aliases_sync", target="google",
            detail=f"+{', '.join(added) or '-'} / -{', '.join(removed) or '-'}",
        )
    return added, removed, [p for p, _ in released]


def sync(conf=None, *, every=SYNC_EVERY_SECONDS, force=False):
    """Ask Google and apply the answer. Never raises.

    ``(ran, error_ar, result)`` - ``ran`` is False when not connected or
    synced recently; ``result`` is :func:`apply`'s tuple when it ran cleanly.
    """
    conf = conf or AppSettings.load()
    if not is_connected(conf):
        return False, "", None
    now = timezone.now()
    if not force and conf.google_sync_at and now - conf.google_sync_at < timedelta(seconds=every):
        return False, "", None
    # Stamp first: a slow Google and two workers must not both go asking.
    AppSettings.objects.filter(pk=conf.pk).update(google_sync_at=now)
    conf.google_sync_at = now
    try:
        result = apply(conf, fetch_aliases(conf))
    except SyncError as exc:
        error = str(exc)[:300]
    except Exception as exc:  # noqa: BLE001 - callers are the mail loop and page views
        error = f"مزامنة العناوين فشلت: {exc}"[:300]
    else:
        AppSettings.objects.filter(pk=conf.pk).update(google_sync_error="")
        conf.google_sync_error = ""
        AppSettings._cached = None
        return True, "", result
    AppSettings.objects.filter(pk=conf.pk).update(google_sync_error=error)
    conf.google_sync_error = error
    AppSettings._cached = None
    return True, error, None
