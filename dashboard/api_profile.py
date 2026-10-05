"""``/api/v1/me/`` - what a person does to their own profile: the picture and the password.

Anyone signed in changes their own and nobody else's: there is no id in the address, the row is ``request.user``. What may be
put in the picture slot is ``avatars.py``'s; who may look at it is ``files.may_open``'s.

A password is changed by whoever has the current one. Somebody who walks up to a screen left signed in must not be able to
find it out by guessing, so wrong guesses are counted and shut the door for a while (the clear-outs' own rule,
``services.RESET_WRONG_LIMIT``), and a new password is held to the project's validators. The password rides in this request and
nowhere else: it is not answered, not logged, and the audit row says only that it changed.
"""

from datetime import timedelta

from django.contrib.auth import update_session_auth_hash
from django.contrib.auth.forms import SetPasswordForm
from django.http import JsonResponse
from django.utils import timezone

from . import api_forms, avatars, services
from .api_v1 import BadBody, _error, _object, endpoint
from .models import AuditLog

#: The longest password read (a real one is far shorter; the rest is a body that wants memory).
MAX_PASSWORD = 200
PASSWORD_BOXES = ("old_password", "new_password1", "new_password2")
PASSWORD_REFUSED = "profile.password_refused"


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

    The current password is asked for again (a session left open on a desk is not consent), five wrong ones in a quarter of an
    hour shut the door to this person (429) whatever is typed next, and the new one must pass the project's validators and be
    typed twice. The session that changed it stays signed in; every other one of this person's sessions is signed out.
    """
    user = request.user
    try:
        body = _object(request)
    except BadBody:
        return _error(400, "bad_body")
    values = {name: body.get(name, "") for name in PASSWORD_BOXES}
    if any(not isinstance(text, str) or len(text) > MAX_PASSWORD or chr(0) in text for text in values.values()):
        return _error(400, "bad_body")

    since = timezone.now() - timedelta(minutes=services.RESET_LOCK_MINUTES)
    if AuditLog.objects.filter(actor=user, action=PASSWORD_REFUSED, created_at__gte=since).count() >= services.RESET_WRONG_LIMIT:
        # Not counted: somebody who waits is not pushed further away.
        services.log(user, "profile.password_locked", user.username, "too many wrong passwords")
        return JsonResponse({"ok": False, "error": "too_many_attempts"}, status=429)
    if not values["old_password"] or not user.check_password(values["old_password"]):
        services.log(user, PASSWORD_REFUSED, user.username, "wrong current password")
        return _error(400, "wrong_password")

    form = SetPasswordForm(user, {"new_password1": values["new_password1"], "new_password2": values["new_password2"]})
    if not form.is_valid():
        return api_forms.invalid(form)
    form.save()
    update_session_auth_hash(request, user)
    services.log(user, "profile.password", user.username, "changed")
    return JsonResponse({"ok": True})
