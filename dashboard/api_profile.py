"""``/api/v1/me/avatar/`` - a person's own profile picture.

Anyone signed in changes or removes their own and nobody else's: there is no id in the address, the row is
``request.user``. What may be put there is ``avatars.py``'s; who may look at it is ``files.may_open``'s.
"""

from django.http import JsonResponse

from . import avatars, services
from .api_v1 import _error, endpoint


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
