"""A person's profile picture: what may be put there, and putting it there and taking it off.

The staff see each other's pictures (the chats, the staff list), so what is stored is held to a short list of rules, each
enforced here and not in the page:

1. **Only a JPEG, and the bytes decide.** The page always sends one (it cuts a square and draws it again, ``avatarImage.ts``);
   the extension and the type a browser sends are the uploader's word, the first bytes are the file's own. A PNG, a WebP, a
   GIF, an SVG (a document that can carry script: ``files.opens_inline``) or a page of script renamed ``me.jpg`` is refused,
   and the stored name always ends ``.jpg``.
2. **Small, in pixels and in bytes.** A few hundred pixels is what is drawn; the ceiling (``MAX_SIDE``) is read from the
   file's own header, because a file of a few kilobytes can declare a picture the size of a wall and every colleague's browser
   would try to open it. ``MAX_BYTES`` holds the file itself.
3. **Only the pixels are kept.** The server does not trust the page to have stripped what a photo carries (where it was
   taken, which phone): it rewrites the file without its metadata segments and without anything after the end of the image.
4. **One picture per person, and the old one goes.** A new picture or a removal deletes the stored file once the change is
   committed, so nothing of a picture somebody took down stays behind in the storage and a change that was rolled back does
   not lose the picture it kept. The row is locked while it is swapped, so two requests at once cannot leave a file that
   nothing points at.
"""

import logging

from django.core.files.base import ContentFile
from django.db import transaction

logger = logging.getLogger("dashboard")

#: Far above a 256-pixel square (tens of kilobytes), far below what would be a way to fill the disk.
MAX_BYTES = 2 * 1024 * 1024
#: The longest side the header may declare. The page sends 256; this leaves room and no more.
MAX_SIDE = 1024

#: The markers that start a frame (the picture's size lives there): baseline, extended, progressive, lossless, arithmetic.
_FRAME = frozenset({0xC0, 0xC1, 0xC2, 0xC3, 0xC5, 0xC6, 0xC7, 0xC9, 0xCA, 0xCB, 0xCD, 0xCE, 0xCF})
#: What a JPEG may carry besides the pixels: application data (Exif, GPS, thumbnails, XMP) and comments. Both are dropped.
_METADATA = frozenset(range(0xE1, 0xF0)) | {0xFE}
_START_OF_SCAN = 0xDA
_END_OF_IMAGE = 0xD9
#: What may follow a 0xFF inside the data of a scan without ending it: a stuffed zero, a fill byte, a restart marker.
_INSIDE_A_SCAN = frozenset({0x00, 0xFF} | set(range(0xD0, 0xD8)))


def clean_jpeg(data):
    """``(bytes, (width, height))`` for a well-formed JPEG without its metadata, or ``None`` for anything else.

    Walks every segment: keeps the ones the picture needs, drops the metadata wherever it sits (a progressive file may put a
    comment between two scans), copies the scans whole, and stops at the first real end-of-image marker, so what comes after
    it (an archive appended to a picture is a known way to carry a second file) is cut off.
    """
    if data[:3] != b"\xff\xd8\xff":
        return None
    out = bytearray(b"\xff\xd8")
    size = None
    scanned = False
    at, end = 2, len(data)
    while at < end:
        if data[at] != 0xFF:
            return None
        while at < end and data[at] == 0xFF:  # fill bytes may come before a marker
            at += 1
        if at >= end:
            return None
        marker = data[at]
        at += 1
        if marker == _END_OF_IMAGE:
            if not scanned:
                return None
            out += bytes([0xFF, marker])
            return bytes(out), size
        # A marker with no length (start, restart, temporary) outside the scan data is not a picture.
        if marker in (0x00, 0x01, 0xD8) or 0xD0 <= marker <= 0xD7:
            return None
        if at + 2 > end:
            return None
        length = int.from_bytes(data[at:at + 2], "big")
        if length < 2 or at + length > end:
            return None
        segment = data[at:at + length]
        if marker in _FRAME:
            if size is not None or length < 8:
                return None
            size = (int.from_bytes(segment[5:7], "big"), int.from_bytes(segment[3:5], "big"))
        if marker not in _METADATA:
            out += bytes([0xFF, marker]) + segment
        at += length
        if marker == _START_OF_SCAN:
            if size is None:
                return None
            scanned = True
            # The scan itself: a 0xFF in it is always followed by 0x00 or a restart marker; anything else is the next marker.
            first = at
            while at + 1 < end and not (data[at] == 0xFF and data[at + 1] not in _INSIDE_A_SCAN):
                at += 1
            out += data[first:at]
    return None


def accepted(upload):
    """The picture to store (a clean JPEG, as bytes) for ``upload``, or ``None`` when it is not one this app keeps.

    ``None`` for: nothing sent, empty, over ``MAX_BYTES``, not a JPEG, broken, or a header that declares more than ``MAX_SIDE``.
    """
    if upload is None or upload.size == 0 or upload.size > MAX_BYTES:
        return None
    upload.seek(0)
    found = clean_jpeg(upload.read(MAX_BYTES + 1))
    if found is None:
        return None
    data, (width, height) = found
    if not (0 < width <= MAX_SIDE and 0 < height <= MAX_SIDE):
        return None
    return data


def url_of(user):
    """The address the page draws the picture from (``/files/...``, never the host behind it), or ``None``."""
    return user.avatar.url if user.avatar else None


def _delete_after_commit(storage, name):
    """Delete a stored file once the row no longer points at it: a rolled-back change must not lose the picture it kept."""

    def run():
        try:
            storage.delete(name)
        except Exception:  # noqa: BLE001 - a picture that stays behind is not worth failing the person's request
            logger.warning("avatar %s was not deleted from the storage", name, exc_info=True)

    transaction.on_commit(run)


def remove(user):
    """Take the picture off and delete the stored file. Nothing to do when there is none."""
    storage = user._meta.get_field("avatar").storage
    with transaction.atomic():
        locked = user._meta.model._default_manager.select_for_update().get(pk=user.pk)
        old = locked.avatar.name if locked.avatar else ""
        if not old:
            return False
        user.avatar = None
        user.save(update_fields=["avatar"])
        _delete_after_commit(storage, old)
    return True


def replace(user, data):
    """Store ``data`` (from ``accepted``) as the person's picture under a random name, then delete the one it replaces.

    The old name is read from the locked row, not from the copy the request loaded: two requests at once each see the
    other's picture as the old one, and the second deletes what the first stored.
    """
    with transaction.atomic():
        locked = user._meta.model._default_manager.select_for_update().get(pk=user.pk)
        old = locked.avatar.name if locked.avatar else ""
        user.avatar.save("avatar.jpg", ContentFile(data), save=False)
        try:
            user.save(update_fields=["avatar"])
        except Exception:
            user.avatar.storage.delete(user.avatar.name)
            raise
        if old and old != user.avatar.name:
            _delete_after_commit(user.avatar.storage, old)
