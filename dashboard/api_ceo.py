"""``/api/v1/admin/ceo/`` - the CEO board (B2B part 6): the whole company for a period, for the owner only.

The figures are ``ceo.board``'s. ``?from=YYYY-MM-DD&to=YYYY-MM-DD``, this month so far when not given, at most a year. The
clients' names appear beside their codes (the owner may see them), and the board drawing them is a row in the audit log, as
a page of client names is.
"""

from django.http import JsonResponse

from . import ceo, identity
from .api_b2b import _period
from .api_v1 import BadBody, _error, endpoint
from .models import Role
from .permissions import api_role_required


@endpoint("GET")
@api_role_required(Role.ADMIN)
def board(request):
    try:
        start, end = _period(request)
    except BadBody:
        return _error(400, "bad_period")
    numbers = ceo.board(request.user, start, end)
    named = [row["code"] for row in numbers["by_client"] if "name" in row]
    if named:
        identity.record_identity_list(request, named, "ceo board")
    return JsonResponse({"ok": True, "from": start.isoformat(), "to": end.isoformat(), **numbers})
