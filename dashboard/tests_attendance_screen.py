"""The attendance screen in the new app: the person's own card, and who draws the check-in screen.

What is pinned here is what the doors *say*: the card is only ever the caller's own, a GET writes nothing a plain
read would not (the settling of forgotten days is the clock's, as on the classic page), and - the part that costs a
day's pay when it is wrong - exactly one interface draws the check-in screen and the shift reminders for a person at
any moment. The punch itself is the classic endpoint and keeps its own tests (``tests.py``: AttendanceTests,
AttendanceRulesTests).
"""

import json
from datetime import datetime, timedelta
from unittest import mock

from django.test import Client as DjangoClient
from django.urls import reverse
from django.utils import timezone

from . import attendance
from .models import (
    AppSettings, AuditLog, AuthorizedDevice, Notification, PunchKind, Role, Shift, ShiftTemplate, User, WorkDay,
    WorkMode,
)
from .tests_api_v1 import _json, _Site

CARD = "dashboard:v1_attendance"


def aware(day, hour, minute=0):
    """2026-09-21 is a Monday: Shift 1 runs 09:00-17:00 that day."""
    return timezone.make_aware(datetime(2026, 9, day, hour, minute))


class _Att(_Site):
    def setUp(self):
        super().setUp()
        ShiftTemplate.seed_defaults()
        self.morning = ShiftTemplate.objects.get(name="Shift 1")
        built = mock.patch("dashboard.newui.spa.built_assets", return_value={"js": "x.js", "css": []})
        built.start()
        self.addCleanup(built.stop)
        # A person on the morning shift on Mondays, who works remotely: no position is asked for.
        self.worker = User.objects.create_user("person_on_shift", password="pw", role=Role.TRANSLATOR, work_mode=WorkMode.REMOTE)
        Shift.objects.create(user=self.worker, weekday=0, template=self.morning)

    def freeze(self, day, hour, minute=0):
        patch = mock.patch("django.utils.timezone.now", return_value=aware(day, hour, minute))
        patch.start()
        self.addCleanup(patch.stop)

    def turn_on(self, roles=(), users=()):
        conf = AppSettings.load()
        conf.new_ui = {**(conf.new_ui or {}), "attendance": {"roles": list(roles), "users": list(users)}}
        conf.save()

    def card(self, user):
        browser = DjangoClient()
        if user is not None:
            browser.force_login(user)
        return browser.get(reverse(CARD))

    def page(self, user, name, args=None, /, **query):
        browser = DjangoClient()
        browser.force_login(user)
        return browser.get(reverse(name, args=args), query)

    def beat(self, user):
        return _json(self.page(user, "dashboard:api_heartbeat"))


class CardDoorTests(_Att):
    def test_everybody_signed_in_has_a_card_and_the_anonymous_have_none(self):
        for user in self.everyone:
            answer = self.card(user)
            self.assertEqual(answer.status_code, 200, user.username)
            self.assertEqual(answer["Cache-Control"], "private, no-store")
        self.assertEqual(self.card(None).status_code, 401)
        browser = DjangoClient()
        browser.force_login(self.ops)
        self.assertEqual(browser.post(reverse(CARD)).status_code, 405)

    def test_a_day_with_nothing_on_it_is_an_empty_card_and_a_get_writes_nothing(self):
        self.freeze(21, 8, 0)
        before = (WorkDay.objects.count(), AuthorizedDevice.objects.count(), Notification.objects.count(), AuditLog.objects.count())
        body = _json(self.card(self.worker))
        self.assertTrue(body["ok"])
        self.assertEqual(body["work_date"], "2026-09-21")
        self.assertEqual(body["day"]["state"], "none")
        self.assertEqual((body["day"]["check_in"], body["day"]["check_out"], body["day"]["hours"]), (None, None, "0:00"))
        self.assertEqual(before, (WorkDay.objects.count(), AuthorizedDevice.objects.count(), Notification.objects.count(), AuditLog.objects.count()))

    def test_the_shift_of_the_day_is_in_both_languages_with_its_end_as_a_moment(self):
        self.freeze(21, 8, 0)
        body = _json(self.card(self.worker))
        plan = body["plan"]
        self.assertTrue(plan["working"])
        self.assertEqual((plan["start"]["ar"], plan["start"]["en"]), ("9:00 ص", "9:00 AM"))
        self.assertEqual((plan["end"]["ar"], plan["end"]["en"]), ("5:00 م", "5:00 PM"))
        self.assertEqual(plan["mode"]["value"], "remote")
        self.assertEqual(datetime.fromisoformat(body["day"]["shift_end"]), aware(21, 17))
        self.assertFalse(body["needs_location"])

    def test_a_day_off_says_so(self):
        # A Tuesday: no row in the roster.
        self.freeze(22, 10, 0)
        body = _json(self.card(self.worker))
        self.assertFalse(body["plan"]["working"])
        self.assertEqual((body["plan"]["start"], body["plan"]["end"], body["day"]["shift_end"]), (None, None, None))

    def test_checking_in_shows_on_the_card_with_the_time_and_how_late(self):
        self.freeze(21, 9, 14)
        attendance.punch(self.worker, PunchKind.CHECK_IN)
        day = _json(self.card(self.worker))["day"]
        self.assertEqual(day["state"], "open")
        self.assertEqual((day["check_in"]["ar"], day["check_in"]["en"]), ("9:14 ص", "9:14 AM"))
        self.assertEqual(day["late_minutes"], 14)
        self.assertIsNone(day["check_out"])

    def test_a_break_and_extra_time_and_the_check_out_are_shown_as_they_happen(self):
        self.freeze(21, 9, 0)
        attendance.punch(self.worker, PunchKind.CHECK_IN)
        with mock.patch("django.utils.timezone.now", return_value=aware(21, 12, 0)):
            attendance.punch(self.worker, PunchKind.BREAK_START)
            self.assertTrue(_json(self.card(self.worker))["day"]["on_break"])
        with mock.patch("django.utils.timezone.now", return_value=aware(21, 12, 30)):
            attendance.punch(self.worker, PunchKind.BREAK_END)
            day = _json(self.card(self.worker))["day"]
        self.assertEqual((day["on_break"], day["break_minutes"]), (False, 30))
        with mock.patch("django.utils.timezone.now", return_value=aware(21, 17, 5)):
            attendance.punch(self.worker, PunchKind.EXTRA_START)
            day = _json(self.card(self.worker))["day"]
        self.assertTrue(day["extra_running"])
        self.assertEqual(day["extra_started_at"]["en"], "5:05 PM")
        with mock.patch("django.utils.timezone.now", return_value=aware(21, 18, 0)):
            attendance.punch(self.worker, PunchKind.CHECK_OUT)
            day = _json(self.card(self.worker))["day"]
        self.assertEqual((day["state"], day["check_out"]["en"]), ("closed", "6:00 PM"))

    def test_an_office_day_asks_for_a_location_and_a_remote_day_does_not(self):
        self.freeze(21, 8, 0)
        office = User.objects.create_user("person_in_office", password="pw", role=Role.TRANSLATOR, work_mode=WorkMode.OFFICE)
        Shift.objects.create(user=office, weekday=0, template=self.morning)
        self.assertTrue(_json(self.card(office))["needs_location"])
        self.assertFalse(_json(self.card(self.worker))["needs_location"])

    def test_it_is_only_ever_the_callers_own(self):
        self.freeze(21, 9, 5)
        attendance.punch(self.worker, PunchKind.CHECK_IN)
        other = User.objects.create_user("person_other", password="pw", role=Role.TRANSLATOR)
        for user in (other, self.ops, self.admin):
            body = _json(self.card(user))
            self.assertEqual(body["day"]["state"], "none", user.username)
            self.assertEqual(body["recent"], [], user.username)
            self.assertEqual(body["devices"], [], user.username)
        self.assertEqual(len(_json(self.card(self.worker))["recent"]), 1)

    def test_the_last_fortnight_is_newest_first_and_no_longer_than_fourteen_days(self):
        self.freeze(30, 12, 0)
        for offset in range(20):
            WorkDay.objects.create(user=self.worker, date=aware(30, 0).date() - timedelta(days=offset), status="present")
        # A day in the future is not part of the past.
        WorkDay.objects.create(user=self.worker, date=aware(30, 0).date() + timedelta(days=3), status="present")
        recent = _json(self.card(self.worker))["recent"]
        self.assertEqual(len(recent), 14)
        self.assertEqual(recent[0]["date"], "2026-09-30")
        self.assertEqual(recent[-1]["date"], "2026-09-17")

    def test_a_past_day_carries_its_status_lateness_overtime_and_a_missed_check_out(self):
        self.freeze(30, 12, 0)
        WorkDay.objects.create(
            user=self.worker, date=aware(28, 0).date(), status="present", late_minutes=12, overtime_minutes=45,
            work_mode="remote", schedule_label="9:00 ص - 5:00 م",
        )
        WorkDay.objects.create(user=self.worker, date=aware(27, 0).date(), status="unexcused", checkout_missed=True)
        recent = {one["date"]: one for one in _json(self.card(self.worker))["recent"]}
        good = recent["2026-09-28"]
        self.assertEqual((good["status"]["value"], good["status"]["tone"], good["late_minutes"], good["overtime_minutes"]), ("present", "ok", 12, 45))
        self.assertEqual(good["mode"]["value"], "remote")
        self.assertEqual(good["schedule"], "9:00 ص - 5:00 م")
        bad = recent["2026-09-27"]
        self.assertEqual((bad["status"]["value"], bad["checkout_missed"], bad["mode"]), ("unexcused", True, None))

    def test_the_month_is_the_same_numbers_the_classic_page_counts(self):
        from . import payroll

        self.freeze(21, 9, 14)
        attendance.punch(self.worker, PunchKind.CHECK_IN)
        body = _json(self.card(self.worker))
        expected = attendance.month_summary(self.worker, *payroll.month_bounds(2026, 9))
        for key in body["summary"]:
            self.assertEqual(body["summary"][key], expected[key], key)
        self.assertEqual(set(body["summary"]), {"scheduled_days", "present_days", "office_days", "remote_days", "late_days", "late_minutes", "short_minutes", "overtime_minutes"})
        self.assertEqual((body["summary"]["present_days"], body["summary"]["late_days"], body["summary"]["late_minutes"]), (1, 1, 14))

    def test_the_two_numbers_the_page_quotes_come_from_the_settings(self):
        from .models import PayrollSettings

        conf = PayrollSettings.load()
        conf.grace_minutes = 7
        conf.missing_checkout_after_minutes = 33
        conf.save()
        self.freeze(21, 8, 0)
        self.assertEqual(_json(self.card(self.worker))["conf"], {"grace_minutes": 7, "missing_checkout_after_minutes": 33})

    def test_a_day_whose_check_out_never_came_is_settled_before_it_is_drawn(self):
        self.freeze(21, 9, 0)
        attendance.punch(self.worker, PunchKind.CHECK_IN)
        # Long after the shift, and the window to check out has closed.
        with mock.patch("django.utils.timezone.now", return_value=aware(22, 12, 0)):
            recent = _json(self.card(self.worker))["recent"]
        self.assertEqual((recent[0]["date"], recent[0]["status"]["value"], recent[0]["checkout_missed"]), ("2026-09-21", "unexcused", True))

    def test_only_the_first_ten_characters_of_a_browsers_token_are_said_and_only_its_own_label(self):
        AuthorizedDevice.objects.create(user=self.worker, fingerprint="abcdef0123456789abcdef0123456789", status="approved")
        AuthorizedDevice.objects.create(user=self.worker, fingerprint="ffffffffffffffffffffffff", label="Office laptop", status="pending")
        AuthorizedDevice.objects.create(user=self.ops, fingerprint="0000someoneelses0000", status="approved")
        answer = self.card(self.worker)
        devices = {one["label"]: one["status"] for one in _json(answer)["devices"]}
        self.assertEqual(devices, {"abcdef0123": "approved", "Office laptop": "pending"})
        text = answer.content.decode("utf-8")
        self.assertNotIn("abcdef0123456789abcdef", text)
        self.assertNotIn("someoneelses", text)

    def test_no_position_and_no_tracking_is_in_the_answer(self):
        self.freeze(21, 9, 5)
        attendance.punch(self.worker, PunchKind.CHECK_IN, latitude=30.04, longitude=31.23)
        text = self.card(self.worker).content.decode("utf-8").lower()
        for word in ("latitude", "longitude", "lat\"", "lng", "accuracy", "geofence", "ip_address"):
            self.assertNotIn(word, text, word)


class ScreenSwitchTests(_Att):
    def test_the_screen_is_in_the_registry_for_every_role_that_clocks_in(self):
        from . import newui

        screen = newui.SCREENS["attendance"]
        self.assertEqual((screen.classic, screen.path, screen.redirects), ("my_attendance", "/attendance", True))
        self.assertEqual(set(screen.roles), {Role.OPERATION, Role.TEAM_LEAD, Role.TRANSLATOR, Role.HR, Role.REVIEWER, Role.ACCOUNTING, Role.SALES})
        self.assertEqual(newui.app_url("attendance"), "/app/attendance")

class CardHandOnTests(_Att):
    def test_the_classic_card_goes_on_once_the_screen_is_on(self):
        self.turn_on(roles=["translator"])
        answer = self.page(self.worker, "dashboard:my_attendance")
        self.assertEqual((answer.status_code, answer["Location"]), (302, "/app/attendance"))

    def test_the_card_is_handed_on_even_while_the_check_in_screen_is_up(self):
        self.freeze(21, 9, 5)
        self.turn_on(roles=["translator"])
        self.assertEqual(self.page(self.worker, "dashboard:my_attendance")["Location"], "/app/attendance")

    def test_the_admin_is_handed_on_by_default(self):
        self.assertEqual(self.page(self.admin, "dashboard:my_attendance")["Location"], "/app/attendance")

    def test_the_card_is_not_handed_on_to_a_build_that_does_not_exist(self):
        self.turn_on(roles=["translator"])
        with mock.patch("dashboard.newui.spa.built_assets", return_value=None):
            self.assertEqual(self.page(self.worker, "dashboard:my_attendance").status_code, 200)


class WhoDrawsTheGateTests(_Att):
    """Exactly one interface draws the check-in screen for a person: sending them to the other one is a loop."""

    def gate_up(self):
        self.freeze(21, 9, 5)

    def test_with_the_screen_on_the_other_screens_are_handed_on_and_the_app_stays_open(self):
        self.gate_up()
        conf = AppSettings.load()
        conf.new_ui = {"translator_home": {"roles": ["translator"], "users": []}, "attendance": {"roles": ["translator"], "users": []}}
        conf.save()
        self.assertEqual(self.page(self.worker, "dashboard:translator_home")["Location"], "/app/translator")
        browser = DjangoClient()
        browser.force_login(self.worker)
        self.assertEqual(browser.get("/app/").status_code, 200)

    def test_the_shell_carries_what_the_screen_asks_so_it_is_there_on_the_first_paint(self):
        self.gate_up()
        self.turn_on(roles=["translator"])
        browser = DjangoClient()
        browser.force_login(self.worker)
        html = browser.get("/app/").content.decode("utf-8")
        start = html.index('id="app-config"')
        config = json.loads(html[html.index(">", start) + 1: html.index("</script>", start)])
        self.assertEqual(config["gate"]["kind"], "check_in")
        self.assertEqual(config["gate"]["date"], "2026-09-21")

    def test_the_shell_says_nothing_when_nothing_is_asked(self):
        self.freeze(21, 8, 0)
        browser = DjangoClient()
        browser.force_login(self.worker)
        html = browser.get("/app/").content.decode("utf-8")
        start = html.index('id="app-config"')
        config = json.loads(html[html.index(">", start) + 1: html.index("</script>", start)])
        self.assertIn("gate", config)
        self.assertIsNone(config["gate"])

    def test_the_heartbeat_says_the_app_draws_it_and_what_it_asks(self):
        self.gate_up()
        beat = self.beat(self.worker)
        self.assertTrue(beat["attendance_screen"])
        self.assertEqual(beat["attendance"]["kind"], "check_in")

    def test_a_person_with_no_gate_is_handed_on_whatever_the_attendance_switch_says(self):
        self.freeze(21, 8, 0)
        conf = AppSettings.load()
        conf.new_ui = {"translator_home": {"roles": ["translator"], "users": []}, "attendance": {"roles": [], "users": []}}
        conf.save()
        self.assertEqual(self.page(self.worker, "dashboard:translator_home")["Location"], "/app/translator")

    def test_somebody_who_does_not_clock_in_never_has_a_gate_in_either_interface(self):
        self.gate_up()
        self.turn_on(roles=["translator"])
        self.worker.attendance_enabled = False
        self.worker.save()
        self.assertIsNone(self.beat(self.worker)["attendance"])
        browser = DjangoClient()
        browser.force_login(self.worker)
        self.assertEqual(browser.get("/app/").status_code, 200)


class PunchStaysTheClassicEndpointTests(_Att):
    def test_the_punch_is_still_the_classic_one_and_refuses_in_the_same_words(self):
        self.freeze(21, 9, 0)
        browser = DjangoClient()
        browser.force_login(self.worker)
        # Ending a break that never started is a refusal with a reason in both languages, not an HTTP error.
        answer = browser.post("/api/attendance/punch/", {"action": "break_end"})
        body = answer.json()
        self.assertEqual(answer.status_code, 200)
        self.assertFalse(body["ok"])
        self.assertTrue(body["ar"] and body["en"] and body["error"])
        ok = browser.post("/api/attendance/punch/", {"action": "check_in", "device": "tok-123"})
        self.assertTrue(ok.json()["ok"])
        self.assertTrue(AuthorizedDevice.objects.filter(user=self.worker, fingerprint="tok-123").exists())
        self.assertEqual(_json(self.card(self.worker))["day"]["state"], "open")

    def test_the_time_a_punch_answers_with_is_the_english_form_the_page_turns_into_arabic(self):
        self.freeze(21, 9, 5)
        browser = DjangoClient()
        browser.force_login(self.worker)
        body = browser.post("/api/attendance/punch/", {"action": "check_in"}).json()
        self.assertEqual(body["at"], "9:05 AM")
        self.assertIn("day", body)
