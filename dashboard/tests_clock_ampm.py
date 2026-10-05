"""A time reads AM or PM in Arabic too: Arabic markers inside right-to-left text turn ``9:00 ص - 5:00 م`` into another time on screen."""

from datetime import date, datetime, time

from django.test import SimpleTestCase
from django.utils import timezone

from . import clock


class ArabicSaysAmPmTests(SimpleTestCase):
    def test_both_languages_write_the_same_markers(self):
        for lang in ("ar", "en"):
            self.assertEqual(clock.fmt12(time(9, 5), lang), "9:05 AM")
            self.assertEqual(clock.fmt12(time(17, 30), lang), "5:30 PM")
            self.assertEqual(clock.fmt12(time(0, 0), lang), "12:00 AM")
            self.assertEqual(clock.fmt12(time(12, 0), lang), "12:00 PM")

    def test_a_shift_window_and_the_bilingual_pair_carry_no_arabic_marker(self):
        self.assertEqual(clock.window12(time(9), time(17), "ar"), "9:00 AM - 5:00 PM")
        self.assertEqual(clock.both(time(17, 30)), ("5:30 PM", "5:30 PM"))
        self.assertEqual(clock.window12(None, time(17)), "—")

    def test_an_aware_moment_is_cairo_time_and_a_date_goes_in_front(self):
        moment = timezone.make_aware(datetime(2026, 10, 6, 17, 5))
        self.assertEqual(clock.fmt12(moment, "ar", "%m-%d"), "10-06 5:05 PM")

    def test_nothing_and_a_date_alone_are_left_as_they_were(self):
        self.assertEqual(clock.fmt12(None), "")
        self.assertEqual(clock.fmt12(""), "")
        self.assertEqual(clock.fmt12(date(2026, 10, 6)), "2026-10-06")
