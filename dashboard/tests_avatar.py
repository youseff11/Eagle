"""A person's own profile picture: put there and taken off by them, seen by the staff, trusted on its bytes.

The doors are ``/api/v1/me/avatar/`` and ``/api/v1/me/avatar/remove/``; the picture is opened from ``/files/`` like every
stored file (``files.may_open``), and its address rides in ``/api/v1/me/``. What may be stored is ``avatars.py``'s: a small
JPEG, rewritten without its metadata.
"""

import tempfile
from unittest import mock

from django.conf import settings
from django.core.files.base import ContentFile
from django.core.files.storage import default_storage
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase, override_settings
from django.urls import reverse

from . import avatars, files
from .models import AuditLog, Role, User


def segment(marker, payload=b""):
    return b"\xff" + bytes([marker]) + (len(payload) + 2).to_bytes(2, "big") + payload


def jpeg(width=64, height=48, extra=b"", trailer=b"", scan=b"\x12\x34\x56"):
    """The segments of a JPEG in the order a real one has them (header, tables, frame, scan, end), as bytes.

    ``extra`` goes between the first segment and the tables, where a camera puts its Exif; ``trailer`` after the end marker.
    """
    frame = bytes([8]) + height.to_bytes(2, "big") + width.to_bytes(2, "big") + bytes([1, 1, 0x11, 0])
    return (
        b"\xff\xd8"
        + segment(0xE0, b"JFIF\x00\x01\x01\x00\x00\x01\x00\x01\x00\x00")
        + extra
        + segment(0xDB, bytes(65))
        + segment(0xC0, frame)
        + segment(0xDA, bytes([1, 1, 0, 0, 63, 0]))
        + scan
        + b"\xff\xd9"
        + trailer
    )


#: What a camera and a careless editor leave in a photo: where it was taken, who made it.
EXIF = segment(0xE1, b"Exif\x00\x00GPS-LAT-30.0444") + segment(0xFE, b"made by Yousef")
JPEG = jpeg()
PNG = b"\x89PNG\r\n\x1a\n" + bytes(64)
WEBP = b"RIFF\x00\x00\x00\x00WEBP" + bytes(64)


class CleanJpegTests(TestCase):
    """The rule on its own, with no request around it."""

    def test_a_jpeg_comes_back_without_its_metadata_and_with_its_size(self):
        data, size = avatars.clean_jpeg(jpeg(80, 60, extra=EXIF))
        self.assertEqual(size, (80, 60))
        self.assertNotIn(b"GPS-LAT", data)
        self.assertNotIn(b"Yousef", data)
        self.assertNotIn(b"Exif", data)
        # Everything else stays: the header, the tables, the frame, the scan and the end.
        self.assertEqual(data, jpeg(80, 60))

    def test_what_follows_the_end_of_the_image_is_cut_off(self):
        data, _size = avatars.clean_jpeg(jpeg(trailer=b"PK\x03\x04 a second file"))
        self.assertTrue(data.endswith(b"\xff\xd9"))
        self.assertNotIn(b"PK\x03\x04", data)

    def test_everything_that_is_not_a_well_formed_jpeg_is_none(self):
        self.assertIsNone(avatars.clean_jpeg(b""))
        self.assertIsNone(avatars.clean_jpeg(PNG))
        self.assertIsNone(avatars.clean_jpeg(WEBP))
        self.assertIsNone(avatars.clean_jpeg(b"\xff\xd8\xff"))
        self.assertIsNone(avatars.clean_jpeg(b"\xff\xd8\xffnot a segment"))
        # No end marker; a scan before any frame; two frames; a segment that claims more than is there; no scan at all.
        self.assertIsNone(avatars.clean_jpeg(jpeg()[:-2]))
        no_frame = b"\xff\xd8" + segment(0xE0, b"JFIF") + segment(0xDA, bytes(6)) + b"\x12\xff\xd9"
        self.assertIsNone(avatars.clean_jpeg(no_frame))
        frame = bytes([8, 0, 8, 0, 8, 1, 1, 0x11, 0])
        two_frames = b"\xff\xd8" + segment(0xC0, frame) + segment(0xC0, frame) + segment(0xDA, bytes(6)) + b"\x12\xff\xd9"
        self.assertIsNone(avatars.clean_jpeg(two_frames))
        self.assertIsNone(avatars.clean_jpeg(b"\xff\xd8" + b"\xff\xe0\x00\xff" + b"JFIF"))
        self.assertIsNone(avatars.clean_jpeg(b"\xff\xd8" + segment(0xE0, b"JFIF") + b"\xff\xd9"))

    def test_a_trailer_that_has_an_end_marker_of_its_own_is_cut_off_whole(self):
        # An archive or a second picture after the first one: its own end marker must not pull it into the stored file.
        trailer = b"PK\x03\x04 SECRET-PAYLOAD " + jpeg(extra=EXIF) + b"\xff\xd9"
        data, _size = avatars.clean_jpeg(jpeg(trailer=trailer))
        self.assertEqual(data, JPEG)
        self.assertNotIn(b"SECRET-PAYLOAD", data)

    def test_a_comment_or_exif_after_the_scan_is_dropped_too(self):
        # A progressive file may put a segment between its scans and its end: metadata is dropped wherever it sits.
        late = JPEG[:-2] + segment(0xFE, b"GPS-LAT-30.0444") + segment(0xE1, b"Exif\x00\x00late") + b"\xff\xd9"
        data, _size = avatars.clean_jpeg(late)
        self.assertEqual(data, JPEG)

    def test_every_scan_of_a_progressive_file_is_kept(self):
        scan = segment(0xDA, bytes([1, 1, 0, 0, 63, 0]))
        two = JPEG[:-2] + scan + b"\x78\x9a" + b"\xff\xd9"
        data, size = avatars.clean_jpeg(two)
        self.assertEqual((data, size), (two, (64, 48)))

    def test_stuffed_zeros_and_restart_markers_inside_a_scan_are_not_the_end(self):
        busy = jpeg(scan=b"\x12\xff\x00\x34\xff\xd0\x56\xff\xd7\x78")
        data, size = avatars.clean_jpeg(busy)
        self.assertEqual((data, size), (busy, (64, 48)))

    def test_fill_bytes_before_a_marker_are_allowed(self):
        data = jpeg()
        padded = data[:2] + b"\xff\xff\xff" + data[2:]
        self.assertEqual(avatars.clean_jpeg(padded)[1], (64, 48))


class AvatarTests(TestCase):
    def setUp(self):
        folder = tempfile.TemporaryDirectory()
        self.addCleanup(folder.cleanup)
        # The local disk, whatever the settings the tests run under say: a test must never write to the real storage zone.
        override = override_settings(
            MEDIA_ROOT=folder.name,
            STORAGES={**settings.STORAGES, "default": {"BACKEND": "dashboard.storages.ProtectedFileSystemStorage"}},
        )
        override.enable()
        self.addCleanup(override.disable)
        self.translator = User.objects.create_user("person_translator", password="pw", role=Role.TRANSLATOR)
        self.ops = User.objects.create_user("person_ops", password="pw", role=Role.OPERATION)
        self.set_url = reverse("dashboard:v1_me_avatar")
        self.remove_url = reverse("dashboard:v1_me_avatar_remove")

    def put(self, user, data=JPEG, name="me.jpg"):
        self.client.force_login(user)
        # The old file is deleted once the change is committed: a test's own transaction never commits, so it is run here.
        with self.captureOnCommitCallbacks(execute=True):
            return self.client.post(self.set_url, {"file": SimpleUploadedFile(name, data)})

    def take_off(self):
        with self.captureOnCommitCallbacks(execute=True):
            return self.client.post(self.remove_url)

    def address(self, user):
        user.refresh_from_db()
        return user.avatar.url

    def stored_bytes(self, user):
        user.refresh_from_db()
        with default_storage.open(user.avatar.name, "rb") as handle:
            return handle.read()

    def stored_files(self, path="avatars"):
        """How many files are in the storage under ``path``, whoever they belong to."""
        directories, names = default_storage.listdir(path)
        return len(names) + sum(self.stored_files(f"{path}/{directory}") for directory in directories)

    def me(self, user):
        self.client.force_login(user)
        return self.client.get(reverse("dashboard:v1_me")).json()["user"]

    # -- putting one there ---------------------------------------------------

    def test_a_person_with_no_picture_has_none_in_me(self):
        self.assertIsNone(self.me(self.translator)["avatar"])

    def test_the_picture_is_stored_and_its_address_rides_in_me(self):
        response = self.put(self.translator)
        self.assertEqual(response.status_code, 200)
        self.translator.refresh_from_db()
        self.assertTrue(self.translator.avatar)
        self.assertTrue(default_storage.exists(self.translator.avatar.name))
        address = self.me(self.translator)["avatar"]
        self.assertEqual(address, response.json()["avatar"])
        self.assertTrue(address.startswith("/files/avatars/"), address)

    def test_the_stored_name_says_nothing_and_always_ends_in_jpg(self):
        # A picture named like a page, like a program, like a person: the stored name is random and its extension is ours.
        for name in ("me.html", "me.png", "Yousef Osama.exe", "../../etc/passwd", "me"):
            self.put(self.translator, JPEG, name)
            self.translator.refresh_from_db()
            stored = self.translator.avatar.name
            self.assertTrue(stored.startswith("avatars/"), stored)
            self.assertTrue(stored.endswith(".jpg"), (name, stored))
            for word in ("Yousef", "person_translator", "passwd", "html"):
                self.assertNotIn(word, stored)

    def test_the_stored_file_has_no_metadata_and_nothing_after_the_picture(self):
        self.put(self.translator, jpeg(extra=EXIF, trailer=b"PK\x03\x04 hidden archive"))
        kept = self.stored_bytes(self.translator)
        for secret in (b"GPS-LAT", b"Yousef", b"Exif", b"PK\x03\x04", b"hidden archive"):
            self.assertNotIn(secret, kept)
        self.assertEqual(kept, jpeg())

    def test_what_the_bytes_say_is_not_a_picture_is_refused_and_nothing_changes(self):
        self.put(self.translator)
        self.translator.refresh_from_db()
        before = self.translator.avatar.name
        for data, name in (
            (PNG, "me.jpg"),
            (WEBP, "me.jpg"),
            (b"<html><script>alert(1)</script></html>", "me.jpg"),
            (b'<svg xmlns="http://www.w3.org/2000/svg"><script>1</script></svg>', "me.svg"),
            (b"GIF89a" + bytes(32), "me.gif"),
            (b"%PDF-1.4 " + bytes(32), "me.jpg"),
            (b"plain words", "me.jpg"),
            (jpeg()[:-2], "cut-short.jpg"),
            (b"", "me.jpg"),
        ):
            response = self.put(self.translator, data, name)
            self.assertEqual((response.status_code, response.json()["error"]), (400, "bad_file"), name)
        self.client.force_login(self.translator)
        self.assertEqual(self.client.post(self.set_url).status_code, 400)
        self.translator.refresh_from_db()
        self.assertEqual(self.translator.avatar.name, before)

    def test_a_header_that_declares_a_huge_picture_is_refused_whatever_its_size_in_bytes(self):
        # A few hundred bytes that a browser would be asked to open as a wall: refused for the colleagues' sake.
        for width, height in ((5000, 5000), (avatars.MAX_SIDE + 1, 100), (100, avatars.MAX_SIDE + 1), (0, 100), (100, 0), (65535, 65535)):
            response = self.put(self.translator, jpeg(width, height))
            self.assertEqual((response.status_code, response.json()["error"]), (400, "bad_file"), (width, height))
        self.assertEqual(self.put(self.translator, jpeg(avatars.MAX_SIDE, avatars.MAX_SIDE)).status_code, 200)

    def test_a_picture_over_the_ceiling_in_bytes_is_refused(self):
        with mock.patch.object(avatars, "MAX_BYTES", 40):
            response = self.put(self.translator, JPEG)
        self.assertEqual((response.status_code, response.json()["error"]), (400, "bad_file"))
        self.translator.refresh_from_db()
        self.assertFalse(self.translator.avatar)

    def test_a_new_picture_deletes_the_one_it_replaces(self):
        self.put(self.translator, JPEG)
        self.translator.refresh_from_db()
        old = self.translator.avatar.name
        self.put(self.translator, jpeg(32, 32), "again.jpg")
        self.translator.refresh_from_db()
        self.assertNotEqual(self.translator.avatar.name, old)
        self.assertFalse(default_storage.exists(old))
        self.assertTrue(default_storage.exists(self.translator.avatar.name))
        self.assertEqual(self.stored_files(), 1)

    def test_two_requests_at_once_leave_no_file_nothing_points_at(self):
        # Both requests loaded the person before either wrote: each sees the first picture as the old one. The second must
        # delete what the first stored, not the picture they both started from (which is already gone).
        self.put(self.translator, JPEG)
        first = User.objects.get(pk=self.translator.pk)
        second = User.objects.get(pk=self.translator.pk)
        start = first.avatar.name
        with self.captureOnCommitCallbacks(execute=True):
            avatars.replace(first, jpeg(40, 40))
        after_first = User.objects.get(pk=self.translator.pk).avatar.name
        with self.captureOnCommitCallbacks(execute=True):
            avatars.replace(second, jpeg(50, 50))
        after_second = User.objects.get(pk=self.translator.pk).avatar.name
        self.assertFalse(default_storage.exists(start))
        self.assertFalse(default_storage.exists(after_first))
        self.assertTrue(default_storage.exists(after_second))
        self.assertEqual(self.stored_files(), 1)

    # -- taking it off -------------------------------------------------------

    def test_removing_deletes_the_file_and_the_address(self):
        self.put(self.translator)
        self.translator.refresh_from_db()
        stored = self.translator.avatar.name
        response = self.take_off()
        self.assertEqual((response.status_code, response.json()), (200, {"ok": True, "avatar": None}))
        self.translator.refresh_from_db()
        self.assertFalse(self.translator.avatar)
        self.assertFalse(default_storage.exists(stored))
        self.assertIsNone(self.me(self.translator)["avatar"])

    def test_removing_when_there_is_none_is_not_an_error(self):
        self.client.force_login(self.translator)
        self.assertEqual(self.client.post(self.remove_url).status_code, 200)
        self.assertFalse(AuditLog.objects.filter(action="profile.avatar").exists())

    def test_what_was_done_is_written_down(self):
        self.put(self.translator)
        self.take_off()
        rows = list(AuditLog.objects.filter(action="profile.avatar").order_by("id").values_list("actor", "target", "detail"))
        self.assertEqual(rows, [(self.translator.pk, "person_translator", "set"), (self.translator.pk, "person_translator", "removed")])

    # -- whose it is ---------------------------------------------------------

    def test_a_person_can_only_change_their_own(self):
        self.client.force_login(self.translator)
        # Nothing in the address and no field of the body names another person: a body that tries to is ignored.
        self.client.post(self.set_url, {"file": SimpleUploadedFile("me.jpg", JPEG), "user": self.ops.pk, "id": self.ops.pk})
        self.ops.refresh_from_db()
        self.translator.refresh_from_db()
        self.assertFalse(self.ops.avatar)
        self.assertTrue(self.translator.avatar)
        # And taking one off touches only theirs.
        self.put(self.ops)
        self.client.force_login(self.translator)
        self.take_off()
        self.ops.refresh_from_db()
        self.assertTrue(self.ops.avatar)

    def test_every_role_has_the_door(self):
        for role in Role.values:
            person = User.objects.create_user(f"staff_{role}", password="pw", role=role)
            self.assertEqual(self.put(person).status_code, 200, role)

    def test_a_signed_out_request_is_a_401_and_the_wrong_method_a_405(self):
        for url in (self.set_url, self.remove_url):
            self.assertEqual(self.client.post(url).status_code, 401, url)
        self.client.force_login(self.translator)
        for url in (self.set_url, self.remove_url):
            self.assertEqual(self.client.get(url).status_code, 405, url)

    # -- who may look at it --------------------------------------------------

    def test_colleagues_of_any_role_open_it_as_a_picture_in_the_page(self):
        self.put(self.translator)
        address = self.address(self.translator)
        for role in Role.values:
            viewer = User.objects.create_user(f"viewer_{role}", password="pw", role=role)
            self.client.force_login(viewer)
            response = self.client.get(address)
            self.assertEqual(response.status_code, 200, role)
            self.assertEqual(response["Content-Type"], "image/jpeg")
            self.assertTrue(response["Content-Disposition"].startswith("inline"), role)
            self.assertEqual(response["X-Content-Type-Options"], "nosniff")

    def test_nobody_signed_out_opens_it(self):
        self.put(self.translator)
        address = self.address(self.translator)
        self.client.logout()
        response = self.client.get(address)
        self.assertEqual(response.status_code, 302)
        self.assertIn("/login", response["Location"])

    def test_an_inactive_account_is_refused_by_the_rule_itself(self):
        self.put(self.translator)
        self.ops.is_active = False
        self.ops.save()
        self.assertEqual(files.may_open(self.ops, self.translator.avatar.name), (False, None))
        self.assertEqual(files.may_open(None, self.translator.avatar.name), (False, None))

    def test_the_old_address_is_closed_once_the_picture_is_taken_off(self):
        self.put(self.translator)
        address = self.address(self.translator)
        self.take_off()
        self.client.force_login(self.ops)
        self.assertEqual(self.client.get(address).status_code, 404)

    def test_the_door_is_for_stored_pictures_only_not_for_whatever_a_row_points_at(self):
        # If a row ever pointed at somebody's document, the colleagues' door must not open it for the whole staff.
        stored = default_storage.save("inbound/2026/10/0123456789abcdef.pdf", ContentFile(b"%PDF-1.4 a client's file"))
        User.objects.filter(pk=self.ops.pk).update(avatar=stored)
        self.ops.refresh_from_db()
        self.assertEqual(files.may_open(self.translator, stored), (False, None))
        self.client.force_login(self.translator)
        self.assertEqual(self.client.get(files.URL_PREFIX + stored).status_code, 404)

    def test_a_face_on_every_page_is_not_counted_as_files_carried_out(self):
        self.put(self.translator)
        self.client.force_login(self.ops)
        with mock.patch("dashboard.identity.count_file_open", return_value=False) as counted:
            response = self.client.get(self.address(self.translator))
        self.assertEqual(response.status_code, 200)
        counted.assert_not_called()

    def test_another_kind_of_file_still_counts(self):
        # The exemption is the avatar's own and nothing else: the same patched counter stops any other file (an admin may
        # open one nobody owns, so it reaches the counter).
        admin = User.objects.create_user("person_admin", password="pw", role=Role.ADMIN)
        stored = default_storage.save("chat/2026/10/abc.pdf", ContentFile(b"%PDF-1.4"))
        self.client.force_login(admin)
        with mock.patch("dashboard.identity.count_file_open", return_value=False) as counted:
            self.assertEqual(self.client.get(files.URL_PREFIX + stored).status_code, 429)
        counted.assert_called_once()
