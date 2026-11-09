"""The team leader hears about their translators' attendance (09/11/2026).

A check-in and a check-out reach the leader the moment they happen, with
the time and any lateness or shortfall; the sweep tells the leader, once a
day each, when a translator has not checked in, was absent for the whole
shift, has not checked out, or lost the day to a forgotten check-out.
"""

from datetime import datetime, timedelta

from django.test import TestCase
from django.utils import timezone

from . import attendance
from .models import (
    DayStatus, Notification, PayrollSettings, PunchKind, Role, Shift, ShiftTemplate, User, WorkDay,
)


class LeadHearsAttendanceTests(TestCase):
    def setUp(self):
        self.conf = PayrollSettings.load()
        ShiftTemplate.seed_defaults()
        self.morning = ShiftTemplate.objects.get(name="Shift 1")      # 09:00-17:00
        self.lead = User.objects.create_user("lead1", password="x", role=Role.TEAM_LEAD)
        self.other_lead = User.objects.create_user("lead2", password="x", role=Role.TEAM_LEAD)
        self.hr = User.objects.create_user(
            "hrx", password="x", role=Role.OPERATION, attendance_manager=True
        )
        self.person = User.objects.create_user(
            "mona", password="x", role=Role.TRANSLATOR, team_lead=self.lead,
        )
        # Joined before the days the tests walk through.
        User.objects.filter(pk=self.person.pk).update(date_joined=self.at(8, day=1))
        self.person.refresh_from_db()
        Shift.objects.create(user=self.person, weekday=0, template=self.morning)

    def at(self, hour, minute=0, day=21):
        """2026-09-21 is a Monday."""
        return timezone.make_aware(datetime(2026, 9, day, hour, minute))

    def notes(self, user, key):
        return Notification.objects.filter(user=user, url__contains=f"attendance.lead.{key}:")

    # -- the punches ----------------------------------------------------------
    def test_check_in_and_out_reach_the_leader_with_the_times(self):
        attendance.punch(self.person, PunchKind.CHECK_IN, at=self.at(9, 2))
        came = self.notes(self.lead, "check_in").get()
        self.assertEqual(came.title_en, "Checked in — mona")
        self.assertIn("9:02 AM", came.body_ar)
        self.assertIn("9:00 AM", came.body_ar)
        self.assertEqual(came.level, "info")
        self.assertTrue(came.url.startswith("/lead/translators/#"))

        attendance.punch(self.person, PunchKind.CHECK_OUT, at=self.at(17, 5))
        left = self.notes(self.lead, "check_out").get()
        self.assertEqual(left.title_en, "Checked out — mona")
        self.assertIn("5:05 PM", left.body_ar)

        # Nobody else gets the leader's copy: not the translator, not another leader, not HR.
        for user in (self.person, self.other_lead, self.hr):
            self.assertFalse(
                Notification.objects.filter(user=user, url__contains="attendance.lead.").exists()
            )

    def test_a_late_check_in_tells_the_leader_how_late_and_rings(self):
        attendance.punch(self.person, PunchKind.CHECK_IN, at=self.at(9, 25))
        came = self.notes(self.lead, "check_in").get()
        self.assertEqual(came.title_en, "Late check-in — mona")
        self.assertIn("متأخر 25 دقيقة", came.body_ar)
        self.assertEqual(came.level, "warning")
        self.assertTrue(came.sound)

    def test_an_early_check_out_tells_the_leader_the_shortfall(self):
        attendance.punch(self.person, PunchKind.CHECK_IN, at=self.at(9, 0))
        attendance.punch(self.person, PunchKind.CHECK_OUT, at=self.at(15, 0))
        left = self.notes(self.lead, "check_out").get()
        self.assertEqual(left.title_en, "Left early — mona")
        self.assertIn("ناقص 120 دقيقة", left.body_ar)

    def test_a_translator_with_no_leader_punches_as_before(self):
        User.objects.filter(pk=self.person.pk).update(team_lead=None)
        self.person.refresh_from_db()
        attendance.punch(self.person, PunchKind.CHECK_IN, at=self.at(9, 0))
        self.assertFalse(Notification.objects.filter(url__contains="attendance.lead.").exists())

    def test_a_leader_who_left_is_not_told(self):
        User.objects.filter(pk=self.lead.pk).update(is_active=False)
        self.person.refresh_from_db()
        attendance.punch(self.person, PunchKind.CHECK_IN, at=self.at(9, 0))
        self.assertFalse(self.notes(self.lead, "check_in").exists())

    # -- the sweep --------------------------------------------------------------
    def test_no_check_in_during_the_shift_rings_the_leader_once(self):
        late = self.at(9, 0) + timedelta(minutes=self.conf.missing_checkin_after_minutes + 1)
        attendance.sweep_alerts(now=late)
        attendance.sweep_alerts(now=late + timedelta(minutes=5))
        note = self.notes(self.lead, "no_checkin").get()
        self.assertIn("9:00 AM", note.body_ar)
        self.assertEqual(note.level, "warning")
        self.assertTrue(note.sound)
        # Not absent yet: the shift is still on.
        self.assertFalse(self.notes(self.lead, "absent").exists())

    def test_a_whole_shift_without_a_check_in_is_an_absence_for_the_leader(self):
        attendance.sweep_alerts(now=self.at(17, 30))
        attendance.sweep_alerts(now=self.at(18, 0))
        note = self.notes(self.lead, "absent").get()
        self.assertEqual(note.title_en, "Absent — mona")
        self.assertIn("2026-09-21", note.body_ar)
        self.assertEqual(note.level, "danger")

    def test_a_day_on_leave_is_not_an_absence(self):
        WorkDay.objects.create(user=self.person, date=self.at(9).date(), status=DayStatus.LEAVE)
        attendance.sweep_alerts(now=self.at(17, 30))
        self.assertFalse(self.notes(self.lead, "absent").exists())

    def test_a_day_before_the_translator_joined_is_not_an_absence(self):
        User.objects.filter(pk=self.person.pk).update(date_joined=self.at(12, day=22))
        self.person.refresh_from_db()
        attendance.sweep_alerts(now=self.at(17, 30))
        self.assertFalse(self.notes(self.lead, "absent").exists())

    def test_a_day_off_is_not_an_absence(self):
        # 2026-09-22 is a Tuesday: no shift on the roster.
        # The sweep also looks back at Monday, which had a shift and is missed:
        # only Monday is an absence.
        attendance.sweep_alerts(now=self.at(18, 0, day=22))
        self.assertEqual(
            [n.url.rsplit(":", 1)[1] for n in self.notes(self.lead, "absent")], ["2026-09-21"]
        )

    def test_no_check_out_then_the_lost_day_both_reach_the_leader(self):
        attendance.punch(self.person, PunchKind.CHECK_IN, at=self.at(9, 0))

        attendance.sweep_alerts(now=self.at(17, 10))
        attendance.sweep_alerts(now=self.at(17, 20))
        reminder = self.notes(self.lead, "no_checkout").get()
        self.assertIn("5:00 PM", reminder.body_ar)
        self.assertFalse(self.notes(self.lead, "checkout_missed").exists())

        attendance.sweep_alerts(now=self.at(17, 0) + timedelta(
            minutes=self.conf.missing_checkout_after_minutes + 1
        ))
        lost = self.notes(self.lead, "checkout_missed").get()
        self.assertEqual(lost.level, "danger")
        self.assertIn("مش محسوب", lost.body_ar)
        # A day with a check-in is never called an absence.
        self.assertFalse(self.notes(self.lead, "absent").exists())

    def test_a_checked_out_day_raises_nothing_more_for_the_leader(self):
        attendance.punch(self.person, PunchKind.CHECK_IN, at=self.at(9, 0))
        attendance.punch(self.person, PunchKind.CHECK_OUT, at=self.at(17, 0))
        attendance.sweep_alerts(now=self.at(19, 0))
        keys = {
            note.url.split("#", 1)[1].split(":", 1)[0]
            for note in Notification.objects.filter(user=self.lead)
        }
        self.assertEqual(keys, {"attendance.lead.check_in", "attendance.lead.check_out"})
