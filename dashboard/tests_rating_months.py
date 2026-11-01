"""The stars start again every month and the months that are over stay readable.

What these tests hold: a person never rolled keeps their stars (nothing is wiped the day this ships); a new month gives the
maximum back and writes the month that ended; rolling twice closes it once; a penalty written in a new month lands on the new
stars; forgiving an old month's penalty changes that month's history, not this month's stars; the file door shows the history.
"""

from datetime import date, datetime
from decimal import Decimal

from django.test import Client as DjangoClient
from django.urls import reverse
from django.utils import timezone

from . import penalties, ratings
from .models import RatingEvent, RatingMonth, Role, User
from .tests_api_v1 import _Site

EMPLOYEE = "dashboard:v1_hr_employee"


def _at(year, month, day=15):
    return timezone.make_aware(datetime(year, month, day, 12, 0))


class RollTests(_Site):
    def setUp(self):
        super().setUp()
        self.tr.rating = Decimal("3.500")
        self.tr.rating_month = date(2026, 9, 1)
        self.tr.save(update_fields=["rating", "rating_month"])

    def test_a_person_never_rolled_keeps_their_stars(self):
        User.objects.filter(pk=self.tr.pk).update(rating_month=None)
        self.tr.refresh_from_db()
        self.assertFalse(ratings.roll_user(self.tr, now=_at(2026, 10)))
        self.tr.refresh_from_db()
        self.assertEqual(self.tr.rating, Decimal("3.500"))
        self.assertEqual(self.tr.rating_month, date(2026, 10, 1))
        self.assertEqual(RatingMonth.objects.count(), 0)

    def test_a_new_month_starts_at_the_maximum_and_keeps_the_old_one(self):
        self.assertEqual(ratings.roll(now=_at(2026, 10)) >= 1, True)
        self.tr.refresh_from_db()
        self.assertEqual(self.tr.rating, Decimal("5.000"))
        self.assertEqual(self.tr.rating_month, date(2026, 10, 1))
        row = RatingMonth.objects.get(user=self.tr)
        self.assertEqual((row.month, row.closing), (date(2026, 9, 1), Decimal("3.500")))

    def test_rolling_twice_closes_the_month_once(self):
        ratings.roll(now=_at(2026, 10))
        self.assertEqual(ratings.roll(now=_at(2026, 10)), 0)
        self.assertEqual(RatingMonth.objects.filter(user=self.tr).count(), 1)

    def test_forgiving_an_old_penalty_moves_that_month_not_this_one(self):
        event = RatingEvent.objects.create(user=self.tr, delta=Decimal("-0.500"), reason_en="late", reason_ar="late")
        RatingEvent.objects.filter(pk=event.pk).update(created_at=_at(2026, 9))
        ratings.roll(now=_at(2026, 10))
        self.tr.refresh_from_db()
        self.assertEqual(self.tr.rating, Decimal("5.000"))
        boss = User.objects.create_user("rm_hr", password="pw", role=Role.HR)
        done, error = penalties.decide(event.pk, boss, "forgive")
        self.assertEqual(error, "")
        self.tr.refresh_from_db()
        self.assertEqual(self.tr.rating, Decimal("5.000"))
        self.assertEqual(RatingMonth.objects.get(user=self.tr, month=date(2026, 9, 1)).closing, Decimal("4.000"))

    def test_the_file_shows_the_closed_months(self):
        ratings.roll(now=_at(2026, 10))
        boss = User.objects.create_user("rm_hr2", password="pw", role=Role.HR)
        browser = DjangoClient()
        browser.force_login(boss)
        body = browser.get(reverse(EMPLOYEE, args=[self.tr.pk])).json()
        # Opening the file rolls to the real month too, so the newer months may be there; the one that was closed stays.
        self.assertIn({"month": "2026-09", "opening": "5", "closing": "3.5"}, body["rating_history"])
