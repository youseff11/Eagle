"""``/api/v1/admin/users/`` - what only the admin does to a person: the account form, a new person, the typed roster rows.

The people are listed and opened on the employee files (``api_people``: the register and a person's file); these doors are
the admin's half of that screen. The form is the classic form (``StaffCreateForm``, ``StaffEditForm``): this layer asks it what
its fields are and gives it the request's values as its input (``api_forms``), so every rule - who may hold a mail address,
who may be given client identity, which role a leader can have - stays where it was. What the classic page wrote down is
written down here too: a created person, a saved file, a changed mail address, a changed role or identity grant.

Only the admin is answered. A GET changes nothing.
"""

from django.http import JsonResponse
from django.shortcuts import get_object_or_404

from . import api_forms, avatars, galiases, identity, services, shiftpick
from .api_v1 import BadBody, _error, _object, _stamp, _two, endpoint
from .forms import StaffCreateForm, StaffEditForm
from .models import Role, Shift, User
from .permissions import api_role_required
from .templatetags.eagle_tags import ROLE_MAP

#: How many rating penalties a person's file lists: the classic page's own number.
MAX_EVENTS = 20


def _person_head(person):
    return {
        "id": person.pk,
        "username": person.username,
        "name": person.short_name,
        "initials": person.initials,
        "avatar": avatars.url_of(person),
        "role": _two(ROLE_MAP, person.role),
    }


@endpoint("GET")
@api_role_required(Role.ADMIN)
def user_new(request):
    """The form for a new person: its fields and what each may be. A password is typed here and never read back."""
    return JsonResponse({"ok": True, "form": api_forms.describe(StaffCreateForm())})


@endpoint("GET")
@api_role_required(Role.ADMIN)
def user(request, pk):
    """The admin's half of a person's file: the form (with the addresses to pick from) and their rating penalties.

    The roster rows are the other half's (``api_people.employee``): the page draws them once and the admin's buttons write them.

    A GET changes nothing: the classic page asked Google for the address list as it opened; here that is its own POST
    (``aliases_sync``) that the page makes and then asks again.
    """
    person = get_object_or_404(User.objects.select_related("team_lead"), pk=pk)
    return JsonResponse({
        "ok": True,
        "user": _person_head(person),
        "form": api_forms.describe(StaffEditForm(instance=person)),
        "events": [
            {"delta": str(event.delta), "reason": event.reason_ar, "at": _stamp(event.created_at, "%m-%d")}
            for event in person.rating_events.all()[:MAX_EVENTS]
        ],
    })


@endpoint("POST")
@api_role_required(Role.ADMIN)
def user_create(request):
    """Make a person. The password rides in this request and nowhere else: it is not logged, not answered, not stored raw."""
    form, refused = api_forms.filled(request, StaffCreateForm)
    if refused is not None:
        return refused
    person = form.save()
    services.log(request.user, "user.create", person.username)
    identity.record_access_change(request, request.user, person, {})
    return JsonResponse({"ok": True, "id": person.pk})


@endpoint("POST")
@api_role_required(Role.ADMIN)
def user_save(request, pk):
    """Save a person's file as the classic page does, and write down a changed role, identity grant or mail address."""
    person = get_object_or_404(User, pk=pk)
    # Read before the form binds: a ModelForm writes the posted values onto the instance while it validates.
    before = identity.access_snapshot(person)
    alias_before = person.mail_alias
    form, refused = api_forms.filled(request, StaffEditForm, person)
    if refused is not None:
        return refused
    form.save()
    # Which boxes, not what is in them: an attendance flag, a team leader or a rating moves what a person may do or is paid.
    services.log(request.user, "user.update", person.username, ", ".join(form.changed_data))
    if person.mail_alias != alias_before:
        # Whose inbox a client's letters land in is worth a line of its own.
        services.log(request.user, "user.mail_alias", person.username, f"{alias_before or '-'} -> {person.mail_alias or '-'}")
    identity.record_access_change(request, request.user, person, before)
    return JsonResponse({"ok": True})


@endpoint("POST")
@api_role_required(Role.ADMIN)
def aliases_sync(request):
    """Ask Google for the company mailbox's addresses (at most once a minute): the page does this as the file opens."""
    ran, _problem, _result = galiases.sync(every=galiases.STAFF_PAGE_EVERY_SECONDS)
    return JsonResponse({"ok": True, "ran": bool(ran)})


@endpoint("POST")
@api_role_required(Role.ADMIN)
def shift_add(request, pk):
    """One roster row of typed times: a weekday, from, to (``shiftpick.typed_shift_form``, the classic box's rule too)."""
    person = get_object_or_404(User, pk=pk)
    if not person.follows_company_rules:
        return _error(400, "owner")
    try:
        body = _object(request)
    except BadBody:
        return _error(400, "bad_body")
    start, end, day = body.get("start_time"), body.get("end_time"), body.get("weekday")
    if not (isinstance(start, str) and isinstance(end, str) and start.strip() and end.strip()):
        return _error(400, "times_required")
    form = shiftpick.typed_shift_form(day, start, end)
    if not form.is_valid():
        return api_forms.invalid(form)
    shift = form.save(commit=False)
    shift.user = person
    shift.save()
    return JsonResponse({"ok": True, "id": shift.pk})


@endpoint("POST")
@api_role_required(Role.ADMIN)
def shift_delete(request, pk, shift_id):
    deleted, _rows = Shift.objects.filter(pk=shift_id, user_id=pk).delete()
    return JsonResponse({"ok": True, "deleted": deleted})
