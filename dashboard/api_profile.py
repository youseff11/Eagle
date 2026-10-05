"""``/api/v1/me/`` - what a person does to their own profile: the picture and the password.

Anyone signed in changes their own and nobody else's: there is no id in the address, the row is ``request.user``. What may be
put in the picture slot is ``avatars.py``'s; who may look at it is ``files.may_open``'s.

A password is changed by whoever has the current one. Somebody who walks up to a screen left signed in must not be able to
find it out by guessing, so wrong guesses are counted and shut the door for a while (the clear-outs' own rule,
``services.RESET_WRONG_LIMIT``), and a new password is held to the project's validators. The password rides in this request and
nowhere else: it is not answered, not logged, and the audit row says only that it changed.
"""

from datetime import timedelta

from django.contrib.auth import logout, update_session_auth_hash
from django.contrib.auth.forms import SetPasswordForm
from django.db import transaction
from django.http import JsonResponse
from django.utils import timezone

from . import api_forms, avatars, identity, services
from .api_v1 import BadBody, _error, _object, endpoint
from .models import AuditLog, User

#: The longest password read (a real one is far shorter; the rest is a body that wants memory).
MAX_PASSWORD = 200
PASSWORD_BOXES = ("old_password", "new_password1", "new_password2")


def _is_text(value):
    """A box that holds a usable password: text, short, no NUL, and something the database can store (no lone surrogate)."""
    if not isinstance(value, str) or len(value) > MAX_PASSWORD or chr(0) in value:
        return False
    try:
        value.encode("utf-8")
    except UnicodeEncodeError:
        return False
    return True


@endpoint("POST")
def avatar_set(request):
    """Put a picture there (multipart: ``file``), instead of the one there. Only a JPEG of a sane size; the metadata is cut."""
    data = avatars.accepted(request.FILES.get("file"))
    if data is None:
        return _error(400, "bad_file")
    avatars.replace(request.user, data)
    services.log(request.user, "profile.avatar", request.user.username, "set")
    return JsonResponse({"ok": True, "avatar": avatars.url_of(request.user)})


@endpoint("POST")
def avatar_remove(request):
    """Take the picture off. Asking when there is none is not an error: the page may be a step behind."""
    if avatars.remove(request.user):
        services.log(request.user, "profile.avatar", request.user.username, "removed")
    return JsonResponse({"ok": True, "avatar": None})


@endpoint("POST")
def password_change(request):
    """Change the signed-in person's own password: ``{old_password, new_password1, new_password2}``.

    The current password is asked for again (a session left open on a desk is not consent). Five wrong ones in a quarter of an
    hour (counted with the clear-outs' own, ``services.WRONG_PASSWORD_ACTIONS``) shut the door to this person whatever is typed
    next, and sign out the session that was guessing, so a stolen cookie dies at the first guess past the limit. The new one must
    pass the project's validators and be typed twice. The session that changed it stays signed in under a new key (so a copy of
    the old cookie is no good any more) and every other session of this person is signed out.

    The count, the check and the write happen under a lock on the person's row, so a burst of requests at once cannot all be
    checked before any of them is counted, and only the ``password`` column is written: the row the request loaded at its start
    is not the row now (an admin may have switched the person off in between).
    """
    try:
        body = _object(request)
    except BadBody:
        return _error(400, "bad_body")
    values = {name: body.get(name, "") for name in PASSWORD_BOXES}
    if any(not _is_text(text) for text in values.values()):
        return _error(400, "bad_body")

    since = timezone.now() - timedelta(minutes=services.RESET_LOCK_MINUTES)
    with transaction.atomic():
        user = User.objects.select_for_update().get(pk=request.user.pk)
        wrong = AuditLog.objects.filter(actor=user, action__in=services.WRONG_PASSWORD_ACTIONS, created_at__gte=since).count()
        if wrong >= services.RESET_WRONG_LIMIT:
            # One row for the whole window, not one for every try made while shut.
            if not AuditLog.objects.filter(actor=user, action=identity.PASSWORD_LOCKED, created_at__gte=since).exists():
                identity.audit(request, user, identity.PASSWORD_LOCKED, user.username, "too many wrong passwords")
            logout(request)
            return JsonResponse({"ok": False, "error": "too_many_attempts"}, status=429)
        if not values["old_password"] or not user.check_password(values["old_password"]):
            identity.audit(request, user, identity.PASSWORD_REFUSED, user.username, "wrong current password")
            return _error(400, "wrong_password")
        form = SetPasswordForm(user, {"new_password1": values["new_password1"], "new_password2": values["new_password2"]})
        if not form.is_valid():
            return api_forms.invalid(form)
        form.save(commit=False)
        user.save(update_fields=["password"])
        identity.audit(request, user, identity.PASSWORD_CHANGE, user.username, "changed")
    update_session_auth_hash(request, user)
    return JsonResponse({"ok": True})
