"""``/files/<path>`` answers a ``Range``: a voice note can be measured and moved through.

Without it a browser cannot reliably read the end of a voice note, so the length it shows can be a guess, and the bar
of the player cannot take it to a place in the middle. The answer is the same file, from the same door, under the same
permission - only a part of it - so the rules around the door are tested here too.
"""

from unittest import mock

from django.core.cache import cache
from django.core.files.base import ContentFile
from django.test import TestCase
from django.utils import timezone

from . import files, services
from .models import Role, User

SOUND = bytes(range(100))


class ByteRangeTests(TestCase):
    def test_a_first_and_a_last_byte(self):
        self.assertEqual(files.byte_range("bytes=10-19", 100), (10, 19))

    def test_an_open_end_is_the_end_of_the_file(self):
        self.assertEqual(files.byte_range("bytes=10-", 100), (10, 99))
        self.assertEqual(files.byte_range("bytes=0-", 100), (0, 99))

    def test_a_last_byte_past_the_end_is_the_end(self):
        self.assertEqual(files.byte_range("bytes=90-5000", 100), (90, 99))

    def test_a_suffix_is_that_many_bytes_from_the_end(self):
        self.assertEqual(files.byte_range("bytes=-30", 100), (70, 99))
        self.assertEqual(files.byte_range("bytes=-500", 100), (0, 99))

    def test_a_place_past_the_end_cannot_be_given(self):
        self.assertEqual(files.byte_range("bytes=100-", 100), files.UNSATISFIABLE)
        self.assertEqual(files.byte_range("bytes=250-300", 100), files.UNSATISFIABLE)
        self.assertEqual(files.byte_range("bytes=-0", 100), files.UNSATISFIABLE)
        self.assertEqual(files.byte_range("bytes=0-", 0), files.UNSATISFIABLE)

    def test_a_number_of_thousands_of_digits_is_a_place_past_the_end_not_an_error(self):
        # Python will not turn more than 4300 digits into an integer; a header can be that long.
        huge = "9" * 5000
        self.assertEqual(files.byte_range(f"bytes={huge}-", 100), files.UNSATISFIABLE)
        self.assertEqual(files.byte_range(f"bytes={huge}-{huge}", 100), files.UNSATISFIABLE)
        self.assertEqual(files.byte_range(f"bytes=0-{huge}", 100), (0, 99))
        self.assertEqual(files.byte_range(f"bytes=-{huge}", 100), (0, 99))
        self.assertEqual(files.byte_range("bytes=0-" + "9" * 19, 100), (0, 99))

    def test_what_is_not_one_clear_range_is_the_whole_file(self):
        for header in (
            "", None, "bytes=", "bytes=-", "bytes=a-b", "bytes=5", "bytes=9-3", "items=0-5",
            "bytes=0-5,10-15", "bytes=-5-9", "bytes=١-٣", "bytes= - ",
        ):
            self.assertIsNone(files.byte_range(header, 100), header)


class RangedFileTests(TestCase):
    """The door itself, as a person who may open the file reaches it."""

    def setUp(self):
        cache.clear()
        self.ops = User.objects.create_user("person_operation", password="pw", role=Role.OPERATION)
        self.translator = User.objects.create_user("person_translator", password="pw", role=Role.TRANSLATOR)

    def tearDown(self):
        cache.clear()

    def note(self, name="note.ogg", phone="+201000000888"):
        message = services.ingest_message(
            channel="whatsapp", body="a voice note", sender_identity=phone,
            attachments=[{
                "file": ContentFile(SOUND, name=name), "name": name, "size": len(SOUND),
                "mime": "audio/ogg", "is_voice": True,
            }],
        )
        url = message.attachments.get().file.url
        self.assertTrue(url.startswith("/files/"), url)
        return url

    def test_a_range_gets_that_part_of_the_file_and_says_where_it_is(self):
        url = self.note()
        self.client.force_login(self.ops)
        response = self.client.get(url, HTTP_RANGE="bytes=10-19")
        self.assertEqual(response.status_code, 206)
        self.assertEqual(response.content, SOUND[10:20])
        self.assertEqual(response["Content-Range"], "bytes 10-19/100")
        self.assertEqual(response["Content-Length"], "10")
        self.assertEqual(response["Content-Type"], "audio/ogg")
        self.assertEqual(response["Accept-Ranges"], "bytes")

    def test_the_end_of_the_file_is_asked_for_by_its_last_bytes(self):
        url = self.note()
        self.client.force_login(self.ops)
        response = self.client.get(url, HTTP_RANGE="bytes=-8")
        self.assertEqual(response.status_code, 206)
        self.assertEqual(response.content, SOUND[-8:])
        self.assertEqual(response["Content-Range"], "bytes 92-99/100")

    def test_an_open_range_is_the_rest_of_the_file(self):
        url = self.note()
        self.client.force_login(self.ops)
        response = self.client.get(url, HTTP_RANGE="bytes=40-")
        self.assertEqual(response.status_code, 206)
        self.assertEqual(response.content, SOUND[40:])
        self.assertEqual(response["Content-Range"], "bytes 40-99/100")

    def test_no_range_is_the_whole_file_and_says_a_range_can_be_asked(self):
        url = self.note()
        self.client.force_login(self.ops)
        response = self.client.get(url)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.content, SOUND)
        self.assertEqual(response["Accept-Ranges"], "bytes")
        self.assertNotIn("Content-Range", response)

    def test_a_range_that_does_not_read_is_answered_with_the_whole_file(self):
        url = self.note()
        self.client.force_login(self.ops)
        for header in ("bytes=0-5,10-15", "bytes=abc", "pages=1-2"):
            response = self.client.get(url, HTTP_RANGE=header)
            self.assertEqual(response.status_code, 200, header)
            self.assertEqual(response.content, SOUND, header)

    def test_a_place_past_the_end_is_refused_with_the_length_of_the_file(self):
        url = self.note()
        self.client.force_login(self.ops)
        response = self.client.get(url, HTTP_RANGE="bytes=500-")
        self.assertEqual(response.status_code, 416)
        self.assertEqual(response["Content-Range"], "bytes */100")
        self.assertEqual(response["Cache-Control"], "private, no-store")
        self.assertEqual(response.content, b"")

    def test_a_header_with_thousands_of_digits_is_answered_not_an_error(self):
        url = self.note()
        self.client.force_login(self.ops)
        huge = "9" * 5000
        self.assertEqual(self.client.get(url, HTTP_RANGE=f"bytes={huge}-").status_code, 416)
        self.assertEqual(self.client.get(url, HTTP_RANGE=f"bytes=0-{huge}").status_code, 206)
        self.assertEqual(self.client.get(url, HTTP_RANGE=f"bytes=-{huge}").content, SOUND)

    def test_a_person_who_may_not_open_the_file_gets_nothing_of_it_by_range_either(self):
        from .models import AuditLog

        url = self.note()
        self.client.force_login(self.translator)
        for header in ("bytes=0-", "bytes=10-19", "bytes=-8", "bytes=500-"):
            before = AuditLog.objects.count()
            response = self.client.get(url, HTTP_RANGE=header)
            self.assertEqual(response.status_code, 404, header)
            self.assertNotIn("Content-Range", response, header)
        # The refusal is written down, once, however many times it is asked for in a row (``record_denied``).
        self.assertGreaterEqual(AuditLog.objects.count(), 1)
        self.assertTrue(AuditLog.objects.filter(detail__contains="hidden file").exists())

    def test_the_preview_helpers_do_not_take_a_range(self):
        # ``?preview=full`` and the thumbnail are answers of our own, not the file: a range does not cut them.
        url = self.note("letter.txt")
        self.client.force_login(self.ops)
        response = self.client.get(url + "?preview=full", HTTP_RANGE="bytes=0-4")
        self.assertEqual(response.status_code, 200)
        self.assertIn("text", response.json())


class RangedFilesAreCountedByFileTests(TestCase):
    """The hour's limit counts files opened; a player's pieces of one file are one."""

    def setUp(self):
        cache.clear()
        self.ops = User.objects.create_user("person_operation", password="pw", role=Role.OPERATION)
        self.urls = [self.note(f"note{index}.ogg", f"+2010000009{index:02d}") for index in range(4)]
        self.client.force_login(self.ops)

    def tearDown(self):
        cache.clear()

    def note(self, name, phone):
        message = services.ingest_message(
            channel="whatsapp", body="a voice note", sender_identity=phone,
            attachments=[{"file": ContentFile(SOUND, name=name), "name": name, "size": len(SOUND), "mime": "audio/ogg"}],
        )
        return message.attachments.get().file.url

    def opened(self):
        return cache.get(f"eagle:files:{self.ops.pk}:{timezone.now().strftime('%Y%m%d%H')}", 0)

    def test_the_pieces_a_player_asks_for_of_one_note_are_one_file_opened(self):
        for header in ("bytes=0-", "bytes=-20", "bytes=50-", "bytes=0-", "bytes=70-"):
            self.assertEqual(self.client.get(self.urls[0], HTTP_RANGE=header).status_code, 206)
        self.assertEqual(self.opened(), 1)

    def test_each_other_note_is_another_file(self):
        for url in self.urls:
            self.client.get(url, HTTP_RANGE="bytes=0-")
            self.client.get(url, HTTP_RANGE="bytes=50-")
        self.assertEqual(self.opened(), 4)

    def test_a_file_opened_whole_is_still_counted_every_time(self):
        for _ in range(3):
            self.client.get(self.urls[0])
        self.assertEqual(self.opened(), 3)

    def test_the_free_pieces_of_a_file_are_few_and_the_rest_count_as_opens(self):
        # Each piece reads the whole file from storage to cut it, so asking for the same one over and over is not seeking.
        with mock.patch("dashboard.identity.RANGE_PIECES_PER_FILE", 3):
            for _ in range(4):
                self.assertEqual(self.client.get(self.urls[0], HTTP_RANGE="bytes=0-0").status_code, 206)
            # The first opened it; the next three were free.
            self.assertEqual(self.opened(), 1)
            for _ in range(4):
                self.client.get(self.urls[0], HTTP_RANGE="bytes=0-0")
            # From the fourth piece on every one counts - the free pieces do not start again after one that counted.
            self.assertEqual(self.opened(), 5)

    def test_the_pieces_past_the_free_ones_are_held_by_the_hours_limit(self):
        with mock.patch("dashboard.identity.RANGE_PIECES_PER_FILE", 2), mock.patch("dashboard.identity.FILES_PER_HOUR_LIMIT", 4):
            statuses = [self.client.get(self.urls[0], HTTP_RANGE="bytes=0-0").status_code for _ in range(10)]
        self.assertEqual(statuses[:3], [206, 206, 206])
        # 1 opened it, 2 were free, the 4th to the 6th count to 4 (the limit), the rest are refused.
        self.assertEqual(statuses[3:6], [206, 206, 206])
        self.assertEqual(statuses[6:], [429, 429, 429, 429])

    def test_a_range_is_no_way_past_the_limit(self):
        with mock.patch("dashboard.identity.FILES_PER_HOUR_LIMIT", 2):
            self.assertEqual(self.client.get(self.urls[0], HTTP_RANGE="bytes=1-").status_code, 206)
            self.assertEqual(self.client.get(self.urls[1], HTTP_RANGE="bytes=1-").status_code, 206)
            # Over the limit: the third file is refused, and asking again, by range, does not open it.
            for _ in range(3):
                self.assertEqual(self.client.get(self.urls[2], HTTP_RANGE="bytes=1-").status_code, 429)
            self.assertEqual(self.client.get(self.urls[3], HTTP_RANGE="bytes=1-").status_code, 429)
            # What was already let through stays open for the player to move in.
            self.assertEqual(self.client.get(self.urls[0], HTTP_RANGE="bytes=50-").status_code, 206)
