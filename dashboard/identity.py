"""Client identity masking - the one place the policy is written down.

EagleLingua separates the client's commercial identity from the work done for
them. The real company name, the contact person, the numbers and addresses
belong to the admin and to the Sales / Accounting people the admin granted
them to by name. Operation, team leaders and translators run the whole job on
the client code (``CL-0002``) and the task code, and nothing they can type -
a search box, a URL, a query parameter - may turn a code back into a name.

Three rules hold that in place, and each one is enforced here on the server,
never only by hiding a field in a template:

1. **Who may see it** is ``User.can_see_client_identity`` - nothing else.
2. **Searching is part of seeing.** A search that matches on a name, a phone
   number or an address answers "which code is this company?" even when the
   result row shows only the code. So identity fields join a search only for
   someone who may see them (``client_search``).
3. **Every look is written down**, and so is every refusal
   (``record_identity_view`` / ``record_denied``), with who, what, when and
   from where.
"""

from django.db.models import Q

from .models import AuditLog


# The audit actions this module writes. Named once so the audit page and the
# tests read the same strings.
IDENTITY_VIEW = "client.identity.view"
IDENTITY_LIST = "client.identity.list"
IDENTITY_SEARCH = "client.identity.search"
ACCESS_DENIED = "security.denied"
ROLE_CHANGE = "user.role_change"
ACCESS_GRANT = "user.identity_access"
DATA_EXPORT = "data.export"
BULK_FILES = "security.bulk_files"

SECURITY_ACTIONS = (
    IDENTITY_VIEW, IDENTITY_LIST, IDENTITY_SEARCH, ACCESS_DENIED,
    ROLE_CHANGE, ACCESS_GRANT, DATA_EXPORT, BULK_FILES,
)


def can_see(user):
    return bool(user is not None and getattr(user, "can_see_client_identity", False))


# ---------------------------------------------------------------------------
# Where a request came from
# ---------------------------------------------------------------------------

def client_ip(request):
    """The caller's address. PythonAnywhere and Cloudflare sit in front, so
    the first hop in ``X-Forwarded-For`` is the browser; without the header
    it is ``REMOTE_ADDR``. A value that is not an address is dropped rather
    than stored, because the column is typed."""
    import ipaddress

    if request is None:
        return None
    raw = (request.META.get("HTTP_X_FORWARDED_FOR") or "").split(",")[0].strip()
    raw = raw or (request.META.get("REMOTE_ADDR") or "").strip()
    try:
        return str(ipaddress.ip_address(raw))
    except ValueError:
        return None


def audit(request, actor, action, target="", detail=""):
    """One audit row, with the request's address and path when there is one."""
    return AuditLog.objects.create(
        actor=actor if getattr(actor, "pk", None) else None,
        action=action,
        target=str(target or "")[:160],
        detail=str(detail or ""),
        ip=client_ip(request),
        path=(request.get_full_path() if request is not None else "")[:250],
    )


# ---------------------------------------------------------------------------
# Reads
# ---------------------------------------------------------------------------

def record_identity_view(request, client, where=""):
    """Log that ``request.user`` was shown ``client``'s real identity."""
    if not can_see(request.user):
        return None
    return audit(request, request.user, IDENTITY_VIEW, client.code, where)


def record_identity_list(request, codes, query=""):
    """A page that drew many clients' names at once - one row, not one per client."""
    if not can_see(request.user) or not codes:
        return None
    detail = f"{len(codes)} clients"
    if query:
        detail += f" · q={query[:80]}"
    return audit(request, request.user, IDENTITY_LIST, ",".join(codes[:20]), detail)


def record_denied(request, reason=""):
    """A signed-in person was refused something. Anonymous refusals are the
    login page's business, not the audit log's."""
    user = getattr(request, "user", None)
    if user is None or not user.is_authenticated:
        return None
    return audit(request, user, ACCESS_DENIED, getattr(user, "role", ""), reason[:300])


def hidden(request, what=""):
    """Refuse a record the person may not open, as a 404, and log it.

    A 404 rather than a 403 on purpose: a 403 would confirm that the code
    they typed exists. The log is where the attempt is still seen.
    """
    from django.http import Http404

    record_denied(request, f"hidden {what} {request.path}".strip())
    raise Http404


# ---------------------------------------------------------------------------
# Changes to who may see what
# ---------------------------------------------------------------------------

#: The fields whose change moves what a person may see. Snapshotted before a
#: save and compared after, so the log carries the before and the after.
ACCESS_FIELDS = ("role", "client_identity_access", "is_active", "is_superuser")


def access_snapshot(user):
    if user is None or not getattr(user, "pk", None):
        return {}
    return {name: getattr(user, name, None) for name in ACCESS_FIELDS}


def record_access_change(request, actor, user, before):
    """Log what changed in ``user``'s access, one row per kind of change.

    A role change and an identity grant are logged under their own actions
    so the audit page can list "who was given client identity" on its own.
    Returns the rows written (empty when nothing that matters changed).
    """
    after = access_snapshot(user)
    rows = []
    if before.get("role") != after.get("role"):
        rows.append(audit(
            request, actor, ROLE_CHANGE, user.username,
            f"{before.get('role') or '-'} -> {after.get('role')}",
        ))
    was = bool(before.get("client_identity_access"))
    now = bool(after.get("client_identity_access"))
    if was != now:
        rows.append(audit(
            request, actor, ACCESS_GRANT, user.username,
            "granted" if now else "revoked",
        ))
    for name in ("is_active", "is_superuser"):
        if name in before and before.get(name) != after.get(name):
            rows.append(audit(
                request, actor, ROLE_CHANGE, user.username,
                f"{name}: {before.get(name)} -> {after.get(name)}",
            ))
    return rows


# ---------------------------------------------------------------------------
# Bulk reads
# ---------------------------------------------------------------------------

#: Files one person may open in an hour before the next is refused. Far above
#: a working day's reading - a chat page loads its images once and the browser
#: keeps them - and far below what a script walking the store would need.
FILES_PER_HOUR_WARN = 200
FILES_PER_HOUR_LIMIT = 600


def record_export(request, what, count):
    """A download of many records at once - always one audit row."""
    return audit(request, request.user, DATA_EXPORT, what, f"{count} records")


def count_file_open(request):
    """Count one file opened; False when this person is over the hour's limit.

    The warning is written to the log once, when the count first crosses it;
    every refusal over the limit is written too. The admin is counted and
    warned about like anyone else, but never refused.
    """
    from django.core.cache import cache
    from django.utils import timezone

    user = request.user
    bucket = timezone.now().strftime("%Y%m%d%H")
    key = f"eagle:files:{user.pk}:{bucket}"
    try:
        count = cache.incr(key)
    except ValueError:
        cache.set(key, 1, 3700)
        count = 1
    if count == FILES_PER_HOUR_WARN:
        audit(request, user, BULK_FILES, user.username, f"{count} files this hour")
    if count > FILES_PER_HOUR_LIMIT and not user.is_admin_role:
        if count == FILES_PER_HOUR_LIMIT + 1 or count % 50 == 0:
            audit(request, user, BULK_FILES, user.username, f"refused at {count} files this hour")
        return False
    return True


# ---------------------------------------------------------------------------
# Search
# ---------------------------------------------------------------------------

def client_search(user, query, prefix=""):
    """The ``Q`` a client search may use for this person.

    ``prefix`` is the path to the client from the model being searched
    (``"client__"`` from a task, ``""`` on ``Client`` itself). The code is
    always searchable; the identity fields only for someone who may see them.
    """
    query = (query or "").strip()
    match = Q(**{f"{prefix}code__icontains": query})
    if can_see(user):
        for field in ("name", "company", "phone", "extra_phones", "email", "extra_emails"):
            match |= Q(**{f"{prefix}{field}__icontains": query})
    return match
