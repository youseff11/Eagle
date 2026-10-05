"""HR's attendance side in the new app: the board, one day and its corrections, the monthly report.

Who may open it is the question the classic pages ask (``can_manage_attendance``: the HR role, the admin, and whoever the admin
gave the flag), not a list of roles. What these tests hold: a day is corrected only with a reason and the trail records it, a
box nobody touched is not an edit, the form decides what is valid, a GET changes nothing, and the new pages are reached only
by who the HR switch is on for.
"""

import json
from datetime import date, datetime, time, timedelta
from unittest import mock

from django.db import connection
from django.test import Client as DjangoClient
from django.test.utils import CaptureQueriesContext
from django.urls import reverse
from django.utils import timezone

from . import attendance, identity, newui, payroll
from .models import (
    AppSettings, AttendanceEdit, AttendanceEvent, AuditLog, PunchKind, ShiftTemplate, User, WorkDay,
)
from .tests_admin_screen import _Admin
from .tests_api_v1 import _json

BOARD = "dashboard:v1_hr_board"
DAY = "dashboard:v1_hr_day"
SAVE = "dashboard:v1_hr_day_save"
CLEAR = "dashboard:v1_hr_day_clear"
REPORT = "dashboard:v1_hr_report"


class _Hr(_Admin):
    def setUp(self):
        super().setUp()
        self.today = timezone.localdate()
        self.flagged = User.objects.create_user("person_flagged", password="pw", role="operation", attendance_manager=True)

    def post(self, user, name, body, args=None):
        browser = DjangoClient()
        if user is not None:
            browser.force_login(user)
        return browser.post(reverse(name, args=args), json.dumps(body), content_type="application/json")

    def switch(self, roles=(), users=()):
        conf = AppSettings.load()
        conf.save()

    def day(self, person=None, when=None, **over):
        values = {"status": "present", "work_mode": "office", "schedule_label": "9 AM - 5 PM"}
        values.update(over)
        return WorkDay.objects.create(user=person or self.tr, date=when or self.today, **values)

    def stamp(self, hour, minute=0, second=0, micro=0, when=None):
        day = when or self.today
        return timezone.make_aware(datetime.combine(day, time(hour, minute, second, micro)))


class DoorMatrixTests(_Hr):
    def setUp(self):
        super().setUp()
        self.row = self.day()

    def doors(self):
        return [
            ("GET", BOARD, None), ("GET", DAY, [self.row.pk]), ("POST", SAVE, [self.row.pk]),
            ("POST", CLEAR, [self.row.pk]), ("GET", REPORT, None),
        ]

    def call(self, user, method, name, args):
        browser = DjangoClient()
        if user is not None:
            browser.force_login(user)
        url = reverse(name, args=args)
        return browser.get(url) if method == "GET" else browser.post(url, "{}", content_type="application/json")

    def test_hr_the_admin_and_the_flag_holder_are_answered_and_nobody_else(self):
        for method, name, args in self.doors():
            for user in (self.hr, self.admin, self.flagged):
                self.assertNotIn(self.call(user, method, name, args).status_code, (401, 403), f"{name} {user.username}")
            for user in (self.ops, self.lead, self.tr, self.reviewer, self.accounting, self.sales):
                self.assertEqual(self.call(user, method, name, args).status_code, 403, f"{name} {user.username}")
            self.assertEqual(self.call(None, method, name, args).status_code, 401, name)

    def test_a_refusal_is_written_down_and_changes_nothing(self):
        before = AuditLog.objects.filter(action=identity.ACCESS_DENIED).count()
        answer = self.call(self.tr, "POST", SAVE, [self.row.pk])
        self.assertEqual((answer.status_code, _json(answer)["error"]), (403, "forbidden"))
        self.assertEqual(AuditLog.objects.filter(action=identity.ACCESS_DENIED).count(), before + 1)
        self.assertFalse(AttendanceEdit.objects.exists())

    def test_the_wrong_method_is_refused(self):
        for name, args, wrong in ((BOARD, None, "post"), (DAY, [self.row.pk], "post"), (REPORT, None, "post"),
                                  (SAVE, [self.row.pk], "get"), (CLEAR, [self.row.pk], "get")):
            browser = DjangoClient()
            browser.force_login(self.hr)
            answer = getattr(browser, wrong)(reverse(name, args=args))
            self.assertEqual(answer.status_code, 405, name)

    def test_every_answer_is_private(self):
        browser = DjangoClient()
        browser.force_login(self.hr)
        self.assertIn("no-store", browser.get(reverse(BOARD))["Cache-Control"])

    def test_a_day_that_is_not_there_is_not_there(self):
        self.assertEqual(self.get(self.hr, DAY, [999999]).status_code, 404)
        self.assertEqual(self.post(self.hr, SAVE, {"values": {}}, [999999]).status_code, 404)
        self.assertEqual(self.post(self.hr, CLEAR, {}, [999999]).status_code, 404)


class BoardTests(_Hr):
    def get_board(self, **query):
        browser = DjangoClient()
        browser.force_login(self.hr)
        return browser.get(reverse(BOARD), query)

    def test_a_day_is_listed_with_what_the_classic_board_prints(self):
        row = self.day(
            check_in=self.stamp(9, 20), late_minutes=20, work_minutes=450, short_minutes=30, overtime_minutes=15,
            needs_review=True, review_reason="Odd place",
        )
        body = _json(self.get_board())
        self.assertEqual((body["view"], body["date"], body["first_day"], body["last_day"]), ("day",) + (self.today.isoformat(),) * 3)
        entry = body["rows"][0]
        self.assertEqual(entry["id"], row.pk)
        self.assertEqual(entry["user"], {"id": self.tr.pk, "name": self.tr.short_name})
        self.assertEqual(entry["work_mode"], {"value": "office", "ar": "من المكتب", "en": "Office"})
        self.assertEqual(entry["check_in"], {"ar": "9:20 AM", "en": "9:20 AM"})
        self.assertIsNone(entry["check_out"])
        self.assertTrue(entry["is_open"])
        self.assertEqual((entry["late_minutes"], entry["short_minutes"], entry["overtime_minutes"], entry["needs_review"]), (20, 30, 15, True))
        self.assertEqual(entry["status"]["tone"], "ok")
        self.assertEqual(body["flagged_count"], 1)

    def test_the_four_numbers_are_counted_over_the_rows(self):
        self.day(check_in=self.stamp(9, 20), late_minutes=20, work_minutes=60, overtime_minutes=10)
        other = User.objects.create_user("person_second", password="pw", role="translator")
        self.day(person=other, off_site=True, work_minutes=30, check_in=self.stamp(9), check_out=self.stamp(17))
        totals = _json(self.get_board())["totals"]
        self.assertEqual(totals, {"present": 2, "late": 1, "off_site": 1, "open": 1, "minutes": 90, "overtime": 10})

    def test_the_filters_narrow_the_rows(self):
        other = User.objects.create_user("person_second", password="pw", role="operation")
        first = self.day(status="present", schedule_label="Early")
        second = self.day(person=other, status="unexcused", work_mode="remote", schedule_label="Late", absence_reason="x")
        ids = lambda **query: [one["id"] for one in _json(self.get_board(**query))["rows"]]
        self.assertEqual(sorted(ids()), sorted([first.pk, second.pk]))
        self.assertEqual(ids(user=self.tr.pk), [first.pk])
        self.assertEqual(ids(role="operation"), [second.pk])
        self.assertEqual(ids(status="unexcused"), [second.pk])
        self.assertEqual(ids(day_mode="remote"), [second.pk])
        self.assertEqual(ids(shift="Early"), [first.pk])
        self.assertEqual(ids(flagged="1"), [])
        WorkDay.objects.filter(pk=first.pk).update(needs_review=True)
        self.assertEqual(ids(flagged="1"), [first.pk])

    def test_a_user_that_is_not_an_id_is_refused_not_a_500(self):
        for bad in ("abc", "1;2", "-3", "9" * 40):
            self.assertEqual(self.get_board(user=bad).status_code, 400, bad)
        self.assertEqual(_json(self.get_board(user="abc"))["error"], "bad_user")

    def test_an_unknown_view_is_a_day_and_a_bad_date_is_today(self):
        body = _json(self.get_board(view="year", date="not-a-date"))
        self.assertEqual((body["view"], body["date"]), ("day", self.today.isoformat()))

    def test_a_week_starts_on_saturday_and_a_month_on_the_first(self):
        anchor = date(2026, 9, 16)  # a Wednesday
        week = _json(self.get_board(view="week", date=anchor.isoformat()))
        self.assertEqual((week["first_day"], week["last_day"]), ("2026-09-12", "2026-09-18"))
        month = _json(self.get_board(view="month", date=anchor.isoformat()))
        self.assertEqual((month["first_day"], month["last_day"]), ("2026-09-01", "2026-09-30"))

    def test_the_rostered_with_no_row_are_named_on_a_day_view_only(self):
        template = ShiftTemplate.objects.create(name="Morning", name_ar="الصبح", start_time=time(9), end_time=time(17))
        attendance.assign_shift(self.tr, template, range(7))
        day_view = _json(self.get_board())
        self.assertIn({"user": {"id": self.tr.pk, "name": self.tr.short_name}, "schedule": "الصبح"}, day_view["missing"])
        self.assertEqual(_json(self.get_board(view="week"))["missing"], [])
        self.day()
        self.assertEqual([one["user"]["id"] for one in _json(self.get_board())["missing"]], [])

    def test_somebody_who_does_not_clock_in_is_not_on_the_board(self):
        quiet = User.objects.create_user("person_quiet", password="pw", role="translator", attendance_enabled=False)
        self.day(person=quiet)
        self.day()
        body = _json(self.get_board())
        self.assertEqual([one["user"]["id"] for one in body["rows"]], [self.tr.pk])
        self.assertNotIn(quiet.pk, [one["id"] for one in body["options"]["people"]])

    def test_the_filter_lists_carry_both_languages(self):
        options = _json(self.get_board())["options"]
        self.assertIn({"value": "hr", "ar": "موارد بشرية", "en": "HR"}, options["roles"])
        self.assertIn({"value": "remote", "ar": "عن بُعد", "en": "Remote"}, options["day_modes"])
        self.assertEqual([one["value"] for one in options["statuses"]][:3], ["present", "leave", "excused"])
        template = ShiftTemplate.objects.create(name="Morning", name_ar="الصبح", start_time=time(9), end_time=time(17))
        self.assertIn(template.label, _json(self.get_board())["options"]["shifts"])

    def test_more_than_the_cap_is_said_not_hidden(self):
        for number in range(1, 6):
            self.day(when=date(2026, 9, number))
        with mock.patch("dashboard.api_hr.MAX_BOARD_ROWS", 3):
            body = _json(self.get_board(view="month", date="2026-09-15"))
        self.assertEqual((len(body["rows"]), body["truncated"]), (3, True))
        self.assertFalse(_json(self.get_board(view="month", date="2026-09-15"))["truncated"])

    def test_the_number_of_queries_does_not_grow_with_the_rows(self):
        def queries():
            with CaptureQueriesContext(connection) as seen:
                self.get_board(view="month", date="2026-09-15")
            return len(seen)

        self.day(when=date(2026, 9, 1))
        queries()  # the first call also loads what is cached afterwards
        few = queries()
        for number in range(2, 20):
            self.day(when=date(2026, 9, number))
        self.assertEqual(queries(), few)

    def test_a_get_writes_nothing(self):
        self.day(check_in=self.stamp(9), check_out=self.stamp(17))
        audit = AuditLog.objects.count()
        edits = AttendanceEdit.objects.count()
        self.get_board()
        self.assertEqual((AuditLog.objects.count(), AttendanceEdit.objects.count()), (audit, edits))

    def test_the_board_settles_the_days_nobody_checked_out_of_like_the_classic_one(self):
        old = self.today - timedelta(days=3)
        row = self.day(
            when=old, check_in=self.stamp(9, when=old), scheduled_start=self.stamp(9, when=old), scheduled_end=self.stamp(17, when=old),
        )
        self.get_board()
        row.refresh_from_db()
        self.assertTrue(row.checkout_missed)


class DayTests(_Hr):
    def setUp(self):
        super().setUp()
        self.row = self.day(
            check_in=self.stamp(9, 20, 41), check_out=self.stamp(17), scheduled_start=self.stamp(9), scheduled_end=self.stamp(17),
            scheduled_minutes=480, grace_minutes=10, work_minutes=460,
        )

    def read(self, user=None):
        browser = DjangoClient()
        browser.force_login(user or self.hr)
        return browser.get(reverse(DAY, args=[self.row.pk]))

    def test_the_punches_are_listed_with_their_evidence_and_the_extra_time_one_is_named(self):
        AttendanceEvent.objects.create(
            work_day=self.row, user=self.tr, kind=PunchKind.CHECK_IN, at=self.stamp(9, 20), within_geofence=True, distance_m=40,
            accuracy_m=12, ip="10.1.2.3", latitude="30.044400", longitude="31.235700",
        )
        AttendanceEvent.objects.create(work_day=self.row, user=self.tr, kind=PunchKind.EXTRA_START, at=self.stamp(17, 5))
        body = _json(self.read())
        first, second = body["events"]
        self.assertEqual(first["kind"], {"value": "check_in", "ar": "حضور", "en": "Check in"})
        self.assertEqual((first["within_geofence"], first["distance_m"], first["accuracy_m"], first["ip"]), (True, 40, 12, "10.1.2.3"))
        self.assertEqual(second["kind"]["en"], "Extra time start")
        self.assertIsNone(second["within_geofence"])

    def test_no_coordinates_leave_the_door(self):
        AttendanceEvent.objects.create(
            work_day=self.row, user=self.tr, kind=PunchKind.CHECK_IN, at=self.stamp(9), latitude="30.044400", longitude="31.235700",
        )
        text = self.read().content.decode()
        for needle in ("30.0444", "31.2357", "latitude", "longitude", "user_agent"):
            self.assertNotIn(needle, text, needle)

    def test_the_frozen_schedule_and_the_state_of_the_day_are_there(self):
        day = _json(self.read())["day"]
        self.assertEqual((day["scheduled_minutes"], day["grace_minutes"], day["work_minutes"]), (480, 10, 460))
        self.assertEqual(day["scheduled_start"], {"ar": "9:00 AM", "en": "9:00 AM"})
        self.assertEqual(day["schedule"], "9 AM - 5 PM")

    def test_the_trail_names_who_changed_what_and_why(self):
        attendance.apply_edit(WorkDay.objects.get(pk=self.row.pk), self.hr, {"note": "Traffic"}, "Told us")
        trail = _json(self.read())["edits"]
        self.assertEqual(len(trail), 1)
        self.assertEqual((trail[0]["actor"], trail[0]["field"], trail[0]["new"], trail[0]["reason"]), (self.hr.short_name, "note", "Traffic", "Told us"))

    def test_the_form_speaks_both_languages_and_starts_from_the_day(self):
        fields = {one["name"]: one for one in _json(self.read())["form"]}
        self.assertEqual(list(fields), ["status", "work_mode", "check_in", "check_out", "break_minutes", "absence_reason", "note", "reason"])
        self.assertEqual((fields["status"]["label_ar"], fields["status"]["label_en"]), ("الحالة", "Status"))
        self.assertEqual(fields["check_in"]["kind"], "datetime")
        self.assertEqual(fields["check_in"]["value"], f"{self.today.isoformat()}T09:20")
        self.assertTrue(fields["reason"]["required"])
        self.assertIn("hint_ar", fields["reason"])
        present = [one for one in fields["status"]["choices"] if one["value"] == "present"][0]
        self.assertEqual((present["label_ar"], present["label_en"]), ("حاضر", "Present"))

    def test_a_get_writes_nothing(self):
        audit = AuditLog.objects.count()
        self.read()
        self.assertEqual((AuditLog.objects.count(), AttendanceEdit.objects.count()), (audit, 0))


class SaveTests(_Hr):
    def setUp(self):
        super().setUp()
        # Kept to the second, as a punch is: a box that shows it to the minute must not rewrite it.
        self.row = self.day(check_in=self.stamp(9, 20, 41, 500), check_out=self.stamp(17, 3, 12), work_minutes=462, late_minutes=20)

    def save(self, values, user=None):
        return self.post(user or self.hr, SAVE, {"values": values}, [self.row.pk])

    def test_a_correction_without_a_reason_is_refused_and_nothing_is_written(self):
        answer = self.save({"status": "excused", "absence_reason": "Sick"})
        self.assertEqual((answer.status_code, _json(answer)["error"], "reason" in _json(answer)["errors"]), (400, "invalid", True))
        self.row.refresh_from_db()
        self.assertEqual(self.row.status, "present")
        self.assertFalse(AttendanceEdit.objects.exists())

    def test_a_reason_of_only_spaces_is_no_reason(self):
        answer = self.save({"note": "x", "reason": "   "})
        self.assertEqual((answer.status_code, "reason" in _json(answer)["errors"]), (400, True))

    def test_a_correction_with_a_reason_is_written_with_its_trail_and_its_audit_row(self):
        answer = self.save({"status": "excused", "absence_reason": "Sick", "reason": "Doctor's note"})
        self.assertEqual((answer.status_code, sorted(_json(answer)["written"])), (200, ["absence_reason", "status"]))
        self.row.refresh_from_db()
        self.assertEqual((self.row.status, self.row.absence_reason), ("excused", "Sick"))
        trail = {one.field: one for one in AttendanceEdit.objects.filter(work_day=self.row)}
        self.assertEqual(set(trail), {"status", "absence_reason"})
        self.assertEqual((trail["status"].old_value, trail["status"].new_value, trail["status"].reason, trail["status"].actor), ("present", "excused", "Doctor's note", self.hr))
        self.assertTrue(AuditLog.objects.filter(action="attendance.edit", actor=self.hr).exists())

    def test_the_boxes_nobody_touched_are_not_edits(self):
        before = (self.row.check_in, self.row.check_out)
        answer = self.save({"note": "Left early with permission", "reason": "HR note"})
        self.assertEqual(_json(answer)["written"], ["note"])
        self.row.refresh_from_db()
        self.assertEqual((self.row.check_in, self.row.check_out), before)
        self.assertEqual([one.field for one in AttendanceEdit.objects.all()], ["note"])

    def test_nothing_changed_writes_nothing(self):
        audit = AuditLog.objects.filter(action="attendance.edit").count()
        answer = self.save({"note": "", "reason": "Looked"})
        self.assertEqual((answer.status_code, _json(answer)["written"]), (200, []))
        self.assertEqual((AttendanceEdit.objects.count(), AuditLog.objects.filter(action="attendance.edit").count()), (0, audit))

    def test_times_are_read_as_cairo_time(self):
        self.save({"check_out": f"{self.today.isoformat()}T18:00", "reason": "Stayed"})
        self.row.refresh_from_db()
        self.assertEqual(timezone.localtime(self.row.check_out).strftime("%H:%M"), "18:00")

    def test_the_forms_own_rules_are_the_rules(self):
        late = self.save({"check_out": f"{self.today.isoformat()}T08:00", "reason": "Typo"})
        self.assertEqual((late.status_code, "check_out" in _json(late)["errors"]), (400, True))
        absent = self.save({"status": "unexcused", "reason": "Absent"})
        self.assertEqual((absent.status_code, "absence_reason" in _json(absent)["errors"]), (400, True))
        self.assertFalse(AttendanceEdit.objects.exists())

    def test_a_box_the_form_does_not_have_is_refused(self):
        for values in ({"words": 99, "reason": "x"}, {"user": 3, "reason": "x"}):
            answer = self.save(values)
            self.assertEqual((answer.status_code, _json(answer)["error"]), (400, "bad_body"), values)
        self.row.refresh_from_db()
        self.assertEqual(self.row.words, 0)

    def test_a_body_that_is_not_the_shape_is_refused(self):
        for body in ({"values": [1]}, {"values": "x"}, {"values": {"note": ["a"], "reason": "x"}}, {"values": {"break_minutes": True, "reason": "x"}}):
            self.assertEqual(self.post(self.hr, SAVE, body, [self.row.pk]).status_code, 400, body)
        browser = DjangoClient()
        browser.force_login(self.hr)
        self.assertEqual(browser.post(reverse(SAVE, args=[self.row.pk]), "{bad", content_type="application/json").status_code, 400)
        self.assertEqual(browser.post(reverse(SAVE, args=[self.row.pk]), {"values": "{}"}).status_code, 400)

    def test_a_restored_day_is_counted_again(self):
        WorkDay.objects.filter(pk=self.row.pk).update(status="unexcused", checkout_missed=True, absence_reason="x")
        self.save({"status": "present", "reason": "He had a reason"})
        self.row.refresh_from_db()
        self.assertEqual((self.row.status, self.row.checkout_missed), ("present", False))

    def test_the_flag_holder_may_correct_a_day_and_an_ordinary_role_may_not(self):
        self.assertEqual(self.save({"note": "a", "reason": "r"}, self.flagged).status_code, 200)
        self.assertEqual(self.save({"note": "b", "reason": "r"}, self.ops).status_code, 403)
        self.row.refresh_from_db()
        self.assertEqual(self.row.note, "a")


class ClearTests(_Hr):
    def setUp(self):
        super().setUp()
        self.row = self.day(needs_review=True, review_reason="Odd place")

    def test_a_flagged_day_is_marked_reviewed_with_a_trail(self):
        answer = self.post(self.hr, CLEAR, {"reason": "Checked the map"}, [self.row.pk])
        self.assertEqual(answer.status_code, 200)
        self.row.refresh_from_db()
        self.assertEqual((self.row.needs_review, self.row.review_reason), (False, ""))
        trail = AttendanceEdit.objects.get(work_day=self.row)
        self.assertEqual((trail.field, trail.reason, trail.actor), ("needs_review", "Checked the map", self.hr))
        self.assertTrue(AuditLog.objects.filter(action="attendance.review").exists())

    def test_no_reason_is_fine_and_a_day_that_is_not_flagged_is_left_alone(self):
        self.assertEqual(self.post(self.hr, CLEAR, {}, [self.row.pk]).status_code, 200)
        self.assertEqual(AttendanceEdit.objects.get(work_day=self.row).reason, "reviewed")
        count = AttendanceEdit.objects.count()
        self.post(self.hr, CLEAR, {}, [self.row.pk])
        self.assertEqual(AttendanceEdit.objects.count(), count)

    def test_a_reason_that_is_not_text_is_refused(self):
        for reason in (5, ["a"], "x" * 251, "a\x00b"):
            self.assertEqual(self.post(self.hr, CLEAR, {"reason": reason}, [self.row.pk]).status_code, 400, reason)
        self.row.refresh_from_db()
        self.assertTrue(self.row.needs_review)


class ReportTests(_Hr):
    def get_report(self, **query):
        browser = DjangoClient()
        browser.force_login(self.hr)
        return browser.get(reverse(REPORT), query)

    def test_the_month_is_the_same_figures_the_classic_report_prints(self):
        self.day(check_in=self.stamp(9, 20), check_out=self.stamp(17), late_minutes=20, work_minutes=460, overtime_minutes=15)
        body = _json(self.get_report(user=self.tr.pk))
        first, last = payroll.month_bounds(self.today.year, self.today.month)
        figures = attendance.month_summary(self.tr, first, last)
        for key in ("scheduled_days", "present_days", "late_days", "late_minutes", "work_minutes", "overtime_minutes", "needs_review"):
            self.assertEqual(body["summary"][key], figures[key], key)
        self.assertEqual((body["year"], body["month"]), (self.today.year, self.today.month))
        entry = body["summary"]["days"][0]
        self.assertEqual((entry["date"], entry["late_minutes"], entry["overtime_minutes"]), (self.today.isoformat(), 20, 15))
        self.assertEqual(entry["check_in"], {"ar": "9:20 AM", "en": "9:20 AM"})

    def test_a_month_is_asked_for_as_text_and_a_typo_is_an_error(self):
        self.assertEqual(_json(self.get_report(period="2026-9"))["month"], 9)
        for bad in ("2026", "2026-13", "x-y", "2026-1-2", "99999-1"):
            self.assertEqual(self.get_report(period=bad).status_code, 400, bad)
        self.assertEqual(_json(self.get_report(period="2026-13"))["error"], "bad_period")

    def test_the_first_person_is_shown_when_nobody_is_named_and_a_bad_id_is_refused(self):
        body = _json(self.get_report())
        self.assertEqual(body["person"], body["people"][0])
        self.assertEqual(self.get_report(user="abc").status_code, 400)
        missing = _json(self.get_report(user=99999999))
        self.assertEqual((missing["person"], missing["summary"]), (None, None))

    def test_the_months_on_offer_are_this_one_and_the_twelve_before(self):
        periods = _json(self.get_report())["periods"]
        self.assertEqual((len(periods), periods[0]), (13, {"year": self.today.year, "month": self.today.month}))


class SwitchAndHandOnTests(_Hr):
    def setUp(self):
        super().setUp()
        self.row = self.day()

    def classic(self, who, name, args=None, **query):
        browser = DjangoClient()
        browser.force_login(who)
        return browser.get(reverse(f"dashboard:{name}", args=args), query)

    def test_the_board_is_handed_on_with_its_filters(self):
        self.switch(roles=["hr"])
        page = self.classic(self.hr, "hr_attendance", view="week", date="2026-09-16", user=str(self.tr.pk), flagged="1", ignored="x")
        self.assertEqual(page.status_code, 302)
        target = page["Location"]
        self.assertTrue(target.startswith("/app/hr/attendance?"), target)
        for part in ("view=week", "date=2026-09-16", f"user={self.tr.pk}", "flagged=1"):
            self.assertIn(part, target)
        self.assertNotIn("ignored", target)

    def test_a_day_and_the_report_are_handed_on_and_the_month_is_carried(self):
        self.switch(roles=["hr"])
        self.assertEqual(self.classic(self.hr, "hr_attendance_day", [self.row.pk])["Location"], f"/app/hr/attendance/{self.row.pk}")
        report = self.classic(self.hr, "hr_report", year="2026", month="9", user=str(self.tr.pk))["Location"]
        self.assertTrue(report.startswith("/app/hr/report?"), report)
        self.assertIn("period=2026-9", report)
        self.assertIn(f"user={self.tr.pk}", report)

    def test_the_admin_is_handed_on_when_ticked(self):
        self.switch(roles=["admin"])
        self.assertEqual(self.classic(self.admin, "hr_attendance").status_code, 302)
