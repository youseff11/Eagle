"""HR's schedules, company shifts, offices, devices and overtime in the new app.

Same rule for who may open them as the attendance board (``can_manage_attendance``). What these tests hold: a roster day added
here is switched on (the classic box saved it off and silently), a company shift added from the four boxes is saved and open (the
classic box refused every one), a shift people lean on is closed and never deleted, a browser's token never leaves whole, an
overtime claim that has been decided is not decided again, and the new pages are reached only by who the HR switch is on for.
"""

import json
from datetime import date, time, timedelta
from decimal import Decimal

from django.test import Client as DjangoClient
from django.urls import reverse
from django.utils import timezone

from . import attendance, identity
from .models import (
    ApprovalStatus, AppSettings, AuditLog, AuthorizedDevice, OfficeLocation, OvertimeClaim, PayrollSettings, ScheduleOverride,
    Shift, ShiftTemplate, User, Vacancy, WorkDay,
)
from .tests_api_v1 import _json
from .tests_hr_attendance import _Hr

SCHEDULES = "dashboard:v1_hr_schedules"
SHIFT_ADD = "dashboard:v1_hr_shift_add"
SHIFT_DELETE = "dashboard:v1_hr_shift_delete"
OVERRIDE_ADD = "dashboard:v1_hr_override_add"
OVERRIDE_DELETE = "dashboard:v1_hr_override_delete"
TEMPLATE_ADD = "dashboard:v1_hr_template_add"
SHIFTS = "dashboard:v1_hr_shifts"
SHIFT_SAVE = "dashboard:v1_hr_shift_save"
TEMPLATE_DELETE = "dashboard:v1_hr_shift_template_delete"
OFFICES = "dashboard:v1_hr_offices"
OFFICE_SAVE = "dashboard:v1_hr_office_save"
OFFICE_DELETE = "dashboard:v1_hr_office_delete"
DEVICES = "dashboard:v1_hr_devices"
DEVICE_DECIDE = "dashboard:v1_hr_device_decide"
OVERTIME = "dashboard:v1_hr_overtime"
OVERTIME_DECIDE = "dashboard:v1_hr_overtime_decide"


class _Sched(_Hr):
    def setUp(self):
        super().setUp()
        self.morning = ShiftTemplate.objects.create(name="Morning", name_ar="الصبح", start_time=time(9), end_time=time(17), sort_order=1)

    def read(self, name, args=None, who=None, **query):
        browser = DjangoClient()
        browser.force_login(who or self.hr)
        return browser.get(reverse(name, args=args), query)

    def next_weekday(self, number):
        day = self.today
        while day.weekday() != number:
            day += timedelta(days=1)
        return day


class DoorMatrixTests(_Sched):
    def setUp(self):
        super().setUp()
        self.shift = Shift.objects.create(user=self.tr, weekday=0, template=self.morning)
        self.override = ScheduleOverride.objects.create(user=self.tr, date=self.today, is_day_off=True)
        self.office = OfficeLocation.objects.create(name="HQ", latitude="30.044400", longitude="31.235700", radius_meters=200)
        self.device = AuthorizedDevice.objects.create(user=self.tr, fingerprint="a" * 40)
        self.claim = OvertimeClaim.objects.create(user=self.tr, date=self.today, minutes=60, hourly_rate=Decimal("10.00"), amount=Decimal("10.00"))
        self.spare = ShiftTemplate.objects.create(name="Spare", start_time=time(1), end_time=time(2))

    def doors(self):
        return [
            ("GET", SCHEDULES, None), ("POST", SHIFT_ADD, None), ("POST", SHIFT_DELETE, [self.shift.pk]),
            ("POST", OVERRIDE_ADD, None), ("POST", OVERRIDE_DELETE, [self.override.pk]), ("POST", TEMPLATE_ADD, None),
            ("GET", SHIFTS, None), ("POST", SHIFT_SAVE, None), ("POST", TEMPLATE_DELETE, [self.spare.pk]),
            ("GET", OFFICES, None), ("POST", OFFICE_SAVE, None), ("POST", OFFICE_DELETE, [self.office.pk]),
            ("GET", DEVICES, None), ("POST", DEVICE_DECIDE, [self.device.pk, "approve"]),
            ("GET", OVERTIME, None), ("POST", OVERTIME_DECIDE, [self.claim.pk, "approve"]),
        ]

    def call(self, who, method, name, args):
        browser = DjangoClient()
        if who is not None:
            browser.force_login(who)
        url = reverse(name, args=args)
        return browser.get(url) if method == "GET" else browser.post(url, "{}", content_type="application/json")

    def test_hr_the_admin_and_the_flag_holder_are_answered_and_nobody_else(self):
        for method, name, args in self.doors():
            for who in (self.ops, self.lead, self.tr, self.reviewer, self.accounting, self.sales):
                self.assertEqual(self.call(who, method, name, args).status_code, 403, f"{name} {who.username}")
            self.assertEqual(self.call(None, method, name, args).status_code, 401, name)
        for method, name, args in self.doors():
            for who in (self.hr, self.admin, self.flagged):
                self.assertNotIn(self.call(who, method, name, args).status_code, (401, 403), f"{name} {who.username}")
                # a door that deletes or decides is answered once, so the next person finds it again
                self.restore()

    def restore(self):
        """Put back what an earlier call in the loop may have removed or decided."""
        if not Shift.objects.filter(pk=self.shift.pk).exists():
            self.shift = Shift.objects.create(user=self.tr, weekday=0, template=self.morning)
        if not ScheduleOverride.objects.filter(pk=self.override.pk).exists():
            self.override = ScheduleOverride.objects.create(user=self.tr, date=self.today, is_day_off=True)
        if not OfficeLocation.objects.filter(pk=self.office.pk).exists():
            self.office = OfficeLocation.objects.create(name="HQ", latitude="30.044400", longitude="31.235700", radius_meters=200)
        if not ShiftTemplate.objects.filter(pk=self.spare.pk).exists():
            self.spare = ShiftTemplate.objects.create(name="Spare", start_time=time(1), end_time=time(2))
        AuthorizedDevice.objects.filter(pk=self.device.pk).update(status=ApprovalStatus.PENDING)
        OvertimeClaim.objects.filter(pk=self.claim.pk).update(status=ApprovalStatus.PENDING)

    def test_a_refusal_is_written_down_and_changes_nothing(self):
        before = AuditLog.objects.filter(action=identity.ACCESS_DENIED).count()
        answer = self.call(self.tr, "POST", OVERTIME_DECIDE, [self.claim.pk, "approve"])
        self.assertEqual((answer.status_code, _json(answer)["error"]), (403, "forbidden"))
        self.assertEqual(AuditLog.objects.filter(action=identity.ACCESS_DENIED).count(), before + 1)
        self.claim.refresh_from_db()
        self.assertEqual(self.claim.status, ApprovalStatus.PENDING)

    def test_the_wrong_method_is_refused(self):
        for name, args, wrong in (
            (SCHEDULES, None, "post"), (SHIFTS, None, "post"), (OFFICES, None, "post"), (DEVICES, None, "post"), (OVERTIME, None, "post"),
            (SHIFT_ADD, None, "get"), (OVERRIDE_ADD, None, "get"), (TEMPLATE_ADD, None, "get"), (SHIFT_SAVE, None, "get"),
            (OFFICE_SAVE, None, "get"), (DEVICE_DECIDE, [1, "approve"], "get"), (OVERTIME_DECIDE, [1, "approve"], "get"),
            (SHIFT_DELETE, [1], "get"), (OFFICE_DELETE, [1], "get"), (TEMPLATE_DELETE, [1], "get"),
        ):
            browser = DjangoClient()
            browser.force_login(self.hr)
            self.assertEqual(getattr(browser, wrong)(reverse(name, args=args)).status_code, 405, name)


class ScheduleTests(_Sched):
    def test_the_roster_lists_each_day_with_what_the_classic_page_prints(self):
        Shift.objects.create(user=self.tr, weekday=0, template=self.morning)
        night = Shift.objects.create(user=self.tr, weekday=2, start_time=time(22), end_time=time(6), work_mode="remote", required_minutes=300)
        body = _json(self.read(SCHEDULES, user=self.tr.pk))
        first, second = body["shifts"]
        self.assertEqual(first["weekday"], {"value": 0, "ar": "الاتنين", "en": "Monday"})
        self.assertEqual((first["template"], first["start"]["ar"], first["end"]["en"], first["minutes"]), ("الصبح", "9:00 ص", "5:00 PM", 480))
        self.assertEqual((second["id"], second["crosses_midnight"], second["minutes"], second["work_mode"]["en"]), (night.pk, True, 300, "Remote"))
        self.assertIsNone(second["template"])
        self.assertEqual(body["person"]["id"], self.tr.pk)
        self.assertEqual(body["person"]["employment"]["value"], self.tr.employment_type)

    def test_a_row_that_is_switched_off_is_shown_as_off(self):
        Shift.objects.create(user=self.tr, weekday=0, template=self.morning, is_active=False)
        self.assertFalse(_json(self.read(SCHEDULES, user=self.tr.pk))["shifts"][0]["is_active"])

    def test_the_overrides_are_the_last_month_on_and_the_next_fortnight_is_resolved(self):
        old = ScheduleOverride.objects.create(user=self.tr, date=self.today - timedelta(days=60), is_day_off=True)
        keep = ScheduleOverride.objects.create(user=self.tr, date=self.today + timedelta(days=2), template=self.morning, reason="Swap")
        attendance.assign_shift(self.tr, self.morning, range(7))
        body = _json(self.read(SCHEDULES, user=self.tr.pk))
        self.assertEqual([one["id"] for one in body["overrides"]], [keep.pk])
        self.assertNotIn(old.pk, [one["id"] for one in body["overrides"]])
        self.assertEqual(len(body["preview"]), 14)
        self.assertEqual(body["preview"][0]["date"], self.today.isoformat())
        swapped = body["preview"][2]
        self.assertEqual((swapped["source"], swapped["label"], swapped["working"]), ("override", "الصبح", True))
        self.assertEqual(body["preview"][1]["source"], "roster")

    def test_a_day_off_in_the_preview_has_no_hours(self):
        body = _json(self.read(SCHEDULES, user=self.tr.pk))
        off = body["preview"][0]
        self.assertEqual((off["working"], off["start"], off["end"], off["mode"], off["label"]), (False, None, None, None, ""))

    def test_everybody_active_can_be_picked_and_the_first_is_the_default(self):
        gone = User.objects.create_user("person_gone", password="pw", role="translator", is_active=False)
        body = _json(self.read(SCHEDULES))
        names = [one["id"] for one in body["people"]]
        self.assertIn(self.ops.pk, names)
        self.assertNotIn(gone.pk, names)
        self.assertEqual(body["person"]["id"], body["people"][0]["id"])
        self.assertEqual(_json(self.read(SCHEDULES, user=99999999))["person"], None)
        self.assertEqual(self.read(SCHEDULES, user="abc").status_code, 400)

    def test_the_company_shifts_are_listed_and_the_forms_speak_both_languages(self):
        closed = ShiftTemplate.objects.create(name="Closed", start_time=time(1), end_time=time(2), is_active=False)
        body = _json(self.read(SCHEDULES, user=self.tr.pk))
        # The real migration seeds three company shifts of its own; the ones made here are among them.
        labels = {one["label"]: one["is_active"] for one in body["templates"]}
        self.assertEqual((labels["الصبح"], labels["Closed"]), (True, False))
        shift_form = {one["name"]: one for one in body["shift_form"]}
        self.assertNotIn("is_active", shift_form)
        self.assertEqual((shift_form["weekday"]["label_ar"], shift_form["weekday"]["label_en"]), ("اليوم", "Weekday"))
        self.assertEqual([c["label_en"] for c in shift_form["weekday"]["choices"]][:3], ["— Choose —", "Monday", "Tuesday"])
        offered = [c["value"] for c in shift_form["template"]["choices"] if c["value"]]
        self.assertIn(str(self.morning.pk), offered)
        self.assertNotIn(str(closed.pk), offered)
        self.assertIn("hint_ar", shift_form["required_minutes"])
        self.assertEqual([one["name"] for one in body["template_form"]], ["name", "name_ar", "start_time", "end_time"])
        self.assertEqual(shift_form["start_time"]["kind"], "time")
        override_form = {one["name"]: one for one in body["override_form"]}
        self.assertEqual(override_form["date"]["kind"], "date")
        self.assertEqual(override_form["is_day_off"]["kind"], "checkbox")

    def test_a_get_writes_nothing(self):
        audit = AuditLog.objects.count()
        self.read(SCHEDULES)
        self.assertEqual(AuditLog.objects.count(), audit)

    def test_the_number_of_queries_does_not_grow_with_the_roster(self):
        from django.db import connection
        from django.test.utils import CaptureQueriesContext

        def queries():
            with CaptureQueriesContext(connection) as seen:
                self.read(SCHEDULES, user=self.tr.pk)
            return len(seen)

        Shift.objects.create(user=self.tr, weekday=0, template=self.morning)
        queries()
        few = queries()
        for number in range(1, 6):
            Shift.objects.create(user=self.tr, weekday=number, template=self.morning)
        self.assertEqual(queries(), few)


class ShiftAddTests(_Sched):
    def add(self, values, who=None, user=None):
        return self.post(who or self.hr, SHIFT_ADD, {"user": (user or self.tr).pk, "values": values})

    def test_a_day_added_here_is_switched_on_and_counts(self):
        answer = self.add({"weekday": "0", "template": str(self.morning.pk)})
        self.assertEqual((answer.status_code, _json(answer)["ok"]), (200, True))
        row = Shift.objects.get(user=self.tr)
        self.assertTrue(row.is_active)
        plan = attendance.plan_for(self.tr, self.next_weekday(0))
        self.assertTrue(plan.working)
        self.assertEqual(plan.label, "الصبح")
        self.assertTrue(AuditLog.objects.filter(action="schedule.shift.add", actor=self.hr).exists())

    def test_it_is_switched_on_even_when_the_body_says_off(self):
        self.add({"weekday": "1", "template": str(self.morning.pk), "is_active": False})
        self.assertTrue(Shift.objects.get(user=self.tr).is_active)

    def test_typed_times_make_a_custom_day(self):
        self.add({"weekday": "3", "start_time": "10:00", "end_time": "14:30", "work_mode": "remote", "required_minutes": "200"})
        row = Shift.objects.get(user=self.tr)
        self.assertEqual((row.start_time, row.end_time, row.work_mode, row.required_minutes), (time(10), time(14, 30), "remote", 200))

    def test_a_shift_or_times_are_needed(self):
        answer = self.add({"weekday": "0"})
        self.assertEqual((answer.status_code, "__all__" in _json(answer)["errors"]), (400, True))
        self.assertFalse(Shift.objects.exists())

    def test_a_person_that_is_not_there_or_is_not_active_is_not_there(self):
        gone = User.objects.create_user("person_gone", password="pw", role="translator", is_active=False)
        self.assertEqual(self.post(self.hr, SHIFT_ADD, {"user": 99999999, "values": {}}).status_code, 404)
        self.assertEqual(self.add({"weekday": "0", "template": str(self.morning.pk)}, user=gone).status_code, 404)

    def test_a_body_that_is_not_the_shape_is_refused(self):
        for body in ({"values": {}}, {"user": "3", "values": {}}, {"user": True, "values": {}}, {"user": self.tr.pk, "values": []},
                     {"user": self.tr.pk, "values": {"nope": 1}}, {"user": self.tr.pk, "values": {"weekday": ["1"]}}):
            self.assertEqual(self.post(self.hr, SHIFT_ADD, body).status_code, 400, body)
        self.assertFalse(Shift.objects.exists())

    def test_a_closed_company_shift_cannot_be_picked(self):
        closed = ShiftTemplate.objects.create(name="Closed", start_time=time(1), end_time=time(2), is_active=False)
        answer = self.add({"weekday": "0", "template": str(closed.pk)})
        self.assertEqual((answer.status_code, "template" in _json(answer)["errors"]), (400, True))

    def test_the_delete_removes_the_day_and_says_whose_it_was(self):
        row = Shift.objects.create(user=self.tr, weekday=0, template=self.morning)
        answer = self.post(self.hr, SHIFT_DELETE, {}, [row.pk])
        self.assertEqual((answer.status_code, _json(answer)["user"]), (200, self.tr.pk))
        self.assertFalse(Shift.objects.exists())
        self.assertTrue(AuditLog.objects.filter(action="schedule.shift.delete").exists())
        self.assertEqual(self.post(self.hr, SHIFT_DELETE, {}, [row.pk]).status_code, 404)


class OverrideTests(_Sched):
    def add(self, values, user=None):
        return self.post(self.hr, OVERRIDE_ADD, {"user": (user or self.tr).pk, "values": values})

    def test_a_day_off_is_enough(self):
        day = (self.today + timedelta(days=3)).isoformat()
        answer = self.add({"date": day, "is_day_off": True, "reason": "Wedding"})
        self.assertEqual(answer.status_code, 200)
        row = ScheduleOverride.objects.get(user=self.tr)
        self.assertEqual((row.is_day_off, row.reason, row.created_by), (True, "Wedding", self.hr))
        self.assertFalse(attendance.plan_for(self.tr, self.today + timedelta(days=3)).working)
        self.assertTrue(AuditLog.objects.filter(action="schedule.override", actor=self.hr).exists())

    def test_a_second_save_for_the_same_date_replaces_the_first(self):
        day = (self.today + timedelta(days=3)).isoformat()
        self.add({"date": day, "is_day_off": True})
        self.add({"date": day, "template": str(self.morning.pk), "reason": "Back"})
        rows = list(ScheduleOverride.objects.filter(user=self.tr))
        self.assertEqual((len(rows), rows[0].is_day_off, rows[0].template), (1, False, self.morning))

    def test_a_working_day_needs_a_shift_or_times(self):
        answer = self.add({"date": self.today.isoformat()})
        self.assertEqual((answer.status_code, "__all__" in _json(answer)["errors"]), (400, True))
        self.assertFalse(ScheduleOverride.objects.exists())

    def test_the_date_is_needed_and_must_be_a_date(self):
        for values in ({"is_day_off": True}, {"date": "tomorrow", "is_day_off": True}):
            answer = self.add(values)
            self.assertEqual((answer.status_code, "date" in _json(answer)["errors"]), (400, True), values)

    def test_the_delete_removes_it(self):
        row = ScheduleOverride.objects.create(user=self.tr, date=self.today, is_day_off=True)
        self.assertEqual(self.post(self.hr, OVERRIDE_DELETE, {}, [row.pk]).status_code, 200)
        self.assertFalse(ScheduleOverride.objects.exists())
        self.assertEqual(self.post(self.hr, OVERRIDE_DELETE, {}, [row.pk]).status_code, 404)


class TemplateAddTests(_Sched):
    def add(self, values):
        return self.post(self.hr, TEMPLATE_ADD, {"values": values})

    def test_a_shift_from_the_four_boxes_is_saved_and_open(self):
        top = ShiftTemplate.objects.order_by("-sort_order").first().sort_order
        answer = self.add({"name_ar": "ليلي", "start_time": "22:00", "end_time": "06:00"})
        self.assertEqual(answer.status_code, 200)
        row = ShiftTemplate.objects.get(name_ar="ليلي")
        self.assertTrue(row.is_active)
        self.assertEqual((row.start_time, row.end_time, row.break_minutes), (time(22), time(6), 0))
        self.assertEqual(row.sort_order, top + 1)
        self.assertEqual(row.name, "ليلي")
        self.assertTrue(AuditLog.objects.filter(action="schedule.template.add").exists())

    def test_a_shift_with_no_name_is_named_by_its_hours(self):
        self.add({"start_time": "05:00", "end_time": "13:00"})
        self.assertEqual(ShiftTemplate.objects.get(name="5:00 ص - 1:00 م").start_time, time(5))

    def test_hours_that_are_the_same_are_not_a_shift(self):
        before = ShiftTemplate.objects.count()
        answer = self.add({"name_ar": "x", "start_time": "09:00", "end_time": "09:00"})
        self.assertEqual((answer.status_code, "__all__" in _json(answer)["errors"]), (400, True))
        self.assertEqual(ShiftTemplate.objects.count(), before)

    def test_a_box_that_is_not_one_of_the_four_is_refused(self):
        before = ShiftTemplate.objects.count()
        for values in ({"is_active": False, "start_time": "05:00", "end_time": "13:00"}, {"sort_order": "9", "start_time": "05:00", "end_time": "13:00"},
                       {"name": 5, "start_time": "05:00", "end_time": "13:00"}, {"name": "x" * 61}):
            self.assertEqual(self.add(values).status_code, 400, values)
        self.assertEqual(ShiftTemplate.objects.count(), before)

    def test_the_new_shift_can_be_put_on_a_roster_straight_away(self):
        self.add({"name_ar": "ليلي", "start_time": "22:00", "end_time": "06:00"})
        fresh = ShiftTemplate.objects.get(name_ar="ليلي")
        answer = self.post(self.hr, SHIFT_ADD, {"user": self.tr.pk, "values": {"weekday": "0", "template": str(fresh.pk)}})
        self.assertEqual(answer.status_code, 200)


class ClassicBoxesTests(_Sched):
    """The two classic boxes that did nothing useful: a roster day saved switched off, a company shift always refused."""

    def classic_post(self, name, data):
        browser = DjangoClient()
        browser.force_login(self.hr)
        return browser.post(reverse(name), data)

    def test_the_classic_roster_day_box_saves_a_day_that_counts(self):
        answer = self.classic_post("dashboard:hr_schedules", {
            "action": "shift", "user": self.tr.pk, "weekday": "0", "template": "", "start_time": "09:00", "end_time": "17:00",
            "work_mode": "", "required_minutes": "0",
        })
        self.assertEqual(answer.status_code, 302)
        row = Shift.objects.get(user=self.tr)
        self.assertTrue(row.is_active)
        self.assertTrue(attendance.plan_for(self.tr, self.next_weekday(0)).working)

    def test_the_classic_company_shift_box_saves_a_shift(self):
        answer = self.classic_post("dashboard:hr_template_add", {"name": "Night", "name_ar": "ليلي", "start_time": "22:00", "end_time": "06:00"})
        self.assertEqual(answer.status_code, 302)
        row = ShiftTemplate.objects.get(name="Night")
        self.assertTrue(row.is_active)

    def test_the_classic_company_shift_box_still_refuses_a_bad_one(self):
        self.classic_post("dashboard:hr_template_add", {"name": "Bad", "start_time": "09:00", "end_time": "09:00"})
        self.assertFalse(ShiftTemplate.objects.filter(name="Bad").exists())


class CompanyShiftTests(_Sched):
    def test_each_shift_says_who_leans_on_it(self):
        Shift.objects.create(user=self.tr, weekday=0, template=self.morning)
        Shift.objects.create(user=self.tr, weekday=1, template=self.morning)
        Shift.objects.create(user=self.ops, weekday=1, template=self.morning)
        ScheduleOverride.objects.create(user=self.tr, date=self.today, template=self.morning)
        vacancy = Vacancy.objects.create(title="Translator")
        vacancy.shifts.add(self.morning)
        free = ShiftTemplate.objects.create(name="Free", start_time=time(1), end_time=time(9), sort_order=2)
        rows = {one["id"]: one for one in _json(self.read(SHIFTS))["rows"]}
        used = rows[self.morning.pk]
        self.assertEqual((used["people"], used["overrides"], used["vacancies"], used["in_use"]), (2, 1, 1, True))
        self.assertEqual((used["hours"], used["label"], used["start"]["ar"]), ("8", "الصبح", "9:00 ص"))
        self.assertEqual((rows[free.pk]["in_use"], rows[free.pk]["hours"]), (False, "8"))

    def test_a_shift_that_crosses_midnight_says_so(self):
        night = ShiftTemplate.objects.create(name="Night", start_time=time(22), end_time=time(6))
        rows = {one["id"]: one for one in _json(self.read(SHIFTS))["rows"]}
        self.assertTrue(rows[night.pk]["crosses_midnight"])
        self.assertFalse(rows[self.morning.pk]["crosses_midnight"])

    def test_the_form_starts_blank_or_from_the_shift_being_changed(self):
        blank = _json(self.read(SHIFTS))
        self.assertEqual((blank["editing"], {one["name"]: one["value"] for one in blank["form"]}["is_active"]), (None, True))
        edited = _json(self.read(SHIFTS, edit=self.morning.pk))
        fields = {one["name"]: one for one in edited["form"]}
        self.assertEqual((edited["editing"], fields["name_ar"]["value"], fields["start_time"]["value"]), (self.morning.pk, "الصبح", "09:00"))
        self.assertEqual((fields["name_ar"]["label_ar"], fields["name_ar"]["label_en"]), ("الاسم", "Name"))
        for bad in ("abc", "999999", "²"):
            self.assertEqual(_json(self.read(SHIFTS, edit=bad))["editing"], None, bad)

    def save(self, values, which=None):
        body = {"values": values}
        if which is not None:
            body["id"] = which
        return self.post(self.hr, SHIFT_SAVE, body)

    def test_a_shift_is_added(self):
        answer = self.save({"name_ar": "المساء", "start_time": "16:00", "end_time": "00:00", "sort_order": "3"})
        self.assertEqual(answer.status_code, 200)
        row = ShiftTemplate.objects.get(name_ar="المساء")
        self.assertEqual((row.start_time, row.end_time, row.sort_order, row.is_active), (time(16), time(0), 3, True))
        self.assertTrue(AuditLog.objects.filter(action="schedule.template.save", actor=self.hr).exists())

    def test_a_shift_is_changed_by_the_boxes_that_were_sent_and_closed_from_its_form(self):
        self.save({"end_time": "18:00"}, self.morning.pk)
        self.morning.refresh_from_db()
        self.assertEqual((self.morning.end_time, self.morning.start_time, self.morning.name_ar), (time(18), time(9), "الصبح"))
        self.save({"is_active": False}, self.morning.pk)
        self.morning.refresh_from_db()
        self.assertFalse(self.morning.is_active)

    def test_the_forms_own_rules_are_the_rules(self):
        answer = self.save({"start_time": "09:00", "end_time": "09:00"}, self.morning.pk)
        self.assertEqual((answer.status_code, "__all__" in _json(answer)["errors"]), (400, True))
        self.morning.refresh_from_db()
        self.assertEqual(self.morning.end_time, time(17))
        self.assertEqual(self.save({"start_time": "late", "end_time": "09:00"}).status_code, 400)

    def test_a_shift_that_is_not_there_is_not_there_and_an_id_must_be_a_number(self):
        self.assertEqual(self.save({"name_ar": "x"}, 999999).status_code, 404)
        for body in ({"id": "3", "values": {}}, {"id": True, "values": {}}, {"id": 0, "values": {}}, {"values": []}):
            self.assertEqual(self.post(self.hr, SHIFT_SAVE, body).status_code, 400, body)

    def test_a_shift_nobody_is_on_is_deleted(self):
        free = ShiftTemplate.objects.create(name="Free", start_time=time(1), end_time=time(9))
        answer = self.post(self.hr, TEMPLATE_DELETE, {}, [free.pk])
        self.assertEqual(answer.status_code, 200)
        self.assertFalse(ShiftTemplate.objects.filter(pk=free.pk).exists())
        self.assertTrue(AuditLog.objects.filter(action="schedule.template.delete").exists())

    def test_a_shift_somebody_leans_on_is_refused_with_the_reason_and_kept(self):
        Shift.objects.create(user=self.tr, weekday=0, template=self.morning)
        answer = self.post(self.hr, TEMPLATE_DELETE, {}, [self.morning.pk])
        body = _json(answer)
        self.assertEqual((answer.status_code, body["error"]), (409, "in_use"))
        self.assertIn("اقفله", body["message"])
        self.assertTrue(ShiftTemplate.objects.filter(pk=self.morning.pk).exists())

    def test_a_shift_a_vacancy_or_an_override_leans_on_is_kept_too(self):
        vacancy = Vacancy.objects.create(title="Translator")
        vacancy.shifts.add(self.morning)
        self.assertEqual(self.post(self.hr, TEMPLATE_DELETE, {}, [self.morning.pk]).status_code, 409)
        vacancy.shifts.clear()
        ScheduleOverride.objects.create(user=self.tr, date=self.today, template=self.morning)
        self.assertEqual(self.post(self.hr, TEMPLATE_DELETE, {}, [self.morning.pk]).status_code, 409)

    def test_a_shift_that_is_not_there_is_not_there(self):
        self.assertEqual(self.post(self.hr, TEMPLATE_DELETE, {}, [999999]).status_code, 404)


class OfficeTests(_Sched):
    def save(self, values, which=None):
        body = {"values": values}
        if which is not None:
            body["id"] = which
        return self.post(self.hr, OFFICE_SAVE, body)

    def test_an_office_is_added_with_its_coordinates_as_text_and_the_policy_is_read_off_the_rules(self):
        answer = self.save({"name": "HQ", "name_ar": "المقر", "latitude": "30.044400", "longitude": "31.235700", "radius_meters": "150", "is_active": True})
        self.assertEqual(answer.status_code, 200)
        body = _json(self.read(OFFICES))
        office = body["offices"][0]
        self.assertEqual((office["label"], office["latitude"], office["longitude"], office["radius_meters"]), ("المقر", "30.044400", "31.235700", 150))
        self.assertEqual(body["policy"], "flag")
        conf = PayrollSettings.load()
        conf.off_site_policy = "reject"
        conf.save()
        self.assertEqual(_json(self.read(OFFICES))["policy"], "reject")
        self.assertTrue(AuditLog.objects.filter(action="attendance.office.add", actor=self.hr).exists())

    def test_an_office_is_changed_by_the_boxes_that_were_sent(self):
        office = OfficeLocation.objects.create(name="HQ", latitude="30.044400", longitude="31.235700", radius_meters=200)
        self.save({"radius_meters": "80"}, office.pk)
        office.refresh_from_db()
        self.assertEqual((office.radius_meters, office.name, str(office.latitude)), (80, "HQ", "30.044400"))
        self.assertTrue(AuditLog.objects.filter(action="attendance.office.edit").exists())

    def test_a_radius_under_twenty_metres_is_refused(self):
        answer = self.save({"name": "HQ", "latitude": "30.04", "longitude": "31.23", "radius_meters": "10"})
        self.assertEqual((answer.status_code, "radius_meters" in _json(answer)["errors"]), (400, True))
        self.assertFalse(OfficeLocation.objects.exists())

    def test_the_form_starts_from_the_office_being_changed(self):
        office = OfficeLocation.objects.create(name="HQ", latitude="30.044400", longitude="31.235700", radius_meters=200)
        body = _json(self.read(OFFICES, edit=office.pk))
        fields = {one["name"]: one for one in body["form"]}
        self.assertEqual((body["editing"], fields["radius_meters"]["value"], fields["latitude"]["value"]), (office.pk, 200, "30.044400"))
        self.assertEqual((fields["radius_meters"]["label_ar"], fields["radius_meters"]["label_en"]), ("النطاق بالمتر", "Radius (metres)"))
        self.assertEqual(_json(self.read(OFFICES, edit="abc"))["editing"], None)

    def test_an_office_that_is_not_there_is_not_there_and_an_id_must_be_a_number(self):
        self.assertEqual(self.save({"name": "x"}, 999999).status_code, 404)
        self.assertEqual(self.post(self.hr, OFFICE_SAVE, {"id": "2", "values": {}}).status_code, 400)

    def test_deleting_an_office_is_idempotent_and_keeps_the_punches_that_named_it(self):
        from .models import AttendanceEvent, PunchKind

        office = OfficeLocation.objects.create(name="HQ", latitude="30.044400", longitude="31.235700", radius_meters=200)
        day = self.day()
        event = AttendanceEvent.objects.create(work_day=day, user=self.tr, kind=PunchKind.CHECK_IN, at=timezone.now(), office=office)
        self.assertEqual(_json(self.post(self.hr, OFFICE_DELETE, {}, [office.pk]))["deleted"], 1)
        self.assertEqual(_json(self.post(self.hr, OFFICE_DELETE, {}, [office.pk]))["deleted"], 0)
        event.refresh_from_db()
        self.assertIsNone(event.office)
        self.assertEqual(AuditLog.objects.filter(action="attendance.office.delete").count(), 1)


class DeviceTests(_Sched):
    def setUp(self):
        super().setUp()
        self.token = "f3a9c1d27b8e4f60aabbccddeeff00112233445566778899"[:40]
        self.device = AuthorizedDevice.objects.create(user=self.tr, fingerprint=self.token, user_agent="Mozilla/5.0 " + "x" * 200)

    def test_a_browser_is_listed_by_the_start_of_its_token_and_never_whole(self):
        raw = self.read(DEVICES).content.decode()
        self.assertNotIn(self.token, raw)
        self.assertIn(self.token[:12], raw)
        pending = _json(self.read(DEVICES))["pending"][0]
        self.assertEqual((pending["fingerprint"], len(pending["browser"]), pending["user"]), (self.token[:12], 60, self.tr.short_name))
        self.assertEqual(pending["first_seen"]["en"][:4], str(self.today.year))

    def test_a_browser_with_a_name_is_listed_by_it(self):
        AuthorizedDevice.objects.filter(pk=self.device.pk).update(label="Sam's phone", status=ApprovalStatus.APPROVED)
        decided = _json(self.read(DEVICES))["decided"][0]
        self.assertEqual((decided["name"], decided["status"]), ("Sam's phone", "approved"))

    def test_approving_and_rejecting_say_who_and_leave_a_trail(self):
        self.assertEqual(self.post(self.hr, DEVICE_DECIDE, {}, [self.device.pk, "approve"]).status_code, 200)
        self.device.refresh_from_db()
        self.assertEqual((self.device.status, self.device.approved_by), (ApprovalStatus.APPROVED, self.hr))
        self.assertTrue(AuditLog.objects.filter(action="attendance.device.approve", actor=self.hr).exists())
        self.assertEqual(_json(self.read(DEVICES))["decided"][0]["decided_by"], self.hr.short_name)

    def test_an_approved_browser_can_be_turned_away(self):
        self.post(self.hr, DEVICE_DECIDE, {}, [self.device.pk, "approve"])
        self.post(self.hr, DEVICE_DECIDE, {}, [self.device.pk, "reject"])
        self.device.refresh_from_db()
        self.assertEqual(self.device.status, ApprovalStatus.REJECTED)

    def test_an_action_that_is_not_one_and_a_browser_that_is_not_there_are_not_there(self):
        self.assertEqual(self.post(self.hr, DEVICE_DECIDE, {}, [self.device.pk, "delete"]).status_code, 404)
        self.assertEqual(self.post(self.hr, DEVICE_DECIDE, {}, [999999, "approve"]).status_code, 404)
        self.device.refresh_from_db()
        self.assertEqual(self.device.status, ApprovalStatus.PENDING)

    def test_a_get_writes_nothing(self):
        audit = AuditLog.objects.count()
        self.read(DEVICES)
        self.assertEqual(AuditLog.objects.count(), audit)


class OvertimeTests(_Sched):
    def setUp(self):
        super().setUp()
        self.claim = OvertimeClaim.objects.create(user=self.tr, date=self.today, minutes=90, hourly_rate=Decimal("12.50"), amount=Decimal("18.75"))
        # The claim is for time the day really holds: approving one for a day that no longer has it is refused.
        self.day(self.tr, self.today, overtime_minutes=90)
        self.day(self.tr, self.today - timedelta(days=1), overtime_minutes=30)

    def test_a_claim_is_listed_with_money_as_text(self):
        pending = _json(self.read(OVERTIME))["pending"][0]
        self.assertEqual((pending["hours"], pending["hourly_rate"], pending["amount"], pending["status"]), ("1:30", "12.50", "18.75", "pending"))

    def test_approving_pays_and_rejecting_does_not_and_each_leaves_a_trail(self):
        other = OvertimeClaim.objects.create(user=self.tr, date=self.today - timedelta(days=1), minutes=30, amount=Decimal("5.00"))
        self.assertEqual(self.post(self.hr, OVERTIME_DECIDE, {}, [self.claim.pk, "approve"]).status_code, 200)
        self.assertEqual(self.post(self.hr, OVERTIME_DECIDE, {}, [other.pk, "reject"]).status_code, 200)
        self.claim.refresh_from_db()
        other.refresh_from_db()
        self.assertEqual((self.claim.status, self.claim.approved_by, other.status), (ApprovalStatus.APPROVED, self.hr, ApprovalStatus.REJECTED))
        self.assertEqual(AuditLog.objects.filter(action__startswith="attendance.overtime.").count(), 2)
        decided = {one["id"]: one for one in _json(self.read(OVERTIME))["decided"]}
        self.assertEqual(decided[self.claim.pk]["decided_by"], self.hr.short_name)

    def test_a_claim_for_a_day_that_was_corrected_is_not_approved(self):
        WorkDay.objects.filter(user=self.tr, date=self.today).update(overtime_minutes=0)
        answer = self.post(self.hr, OVERTIME_DECIDE, {}, [self.claim.pk, "approve"])
        self.assertEqual((answer.status_code, _json(answer)["error"]), (409, "stale_claim"))
        self.claim.refresh_from_db()
        self.assertEqual(self.claim.status, ApprovalStatus.PENDING)
        # It can still be turned down.
        self.assertEqual(self.post(self.hr, OVERTIME_DECIDE, {}, [self.claim.pk, "reject"]).status_code, 200)

    def test_a_claim_that_was_decided_is_not_decided_again(self):
        self.post(self.hr, OVERTIME_DECIDE, {}, [self.claim.pk, "approve"])
        answer = self.post(self.hr, OVERTIME_DECIDE, {}, [self.claim.pk, "reject"])
        self.assertEqual((answer.status_code, _json(answer)["error"]), (409, "already_decided"))
        self.claim.refresh_from_db()
        self.assertEqual(self.claim.status, ApprovalStatus.APPROVED)
        self.assertEqual(AuditLog.objects.filter(action="attendance.overtime.reject").count(), 0)

    def test_an_action_that_is_not_one_and_a_claim_that_is_not_there_are_not_there(self):
        self.assertEqual(self.post(self.hr, OVERTIME_DECIDE, {}, [self.claim.pk, "pay"]).status_code, 404)
        self.assertEqual(self.post(self.hr, OVERTIME_DECIDE, {}, [999999, "approve"]).status_code, 404)
        self.claim.refresh_from_db()
        self.assertEqual(self.claim.status, ApprovalStatus.PENDING)

    def test_the_number_of_queries_does_not_grow_with_the_claims(self):
        from django.db import connection
        from django.test.utils import CaptureQueriesContext

        def queries():
            with CaptureQueriesContext(connection) as seen:
                self.read(OVERTIME)
            return len(seen)

        queries()
        few = queries()
        for offset in range(2, 12):
            OvertimeClaim.objects.create(user=self.ops, date=self.today - timedelta(days=offset), minutes=30)
        self.assertEqual(queries(), few)


class HandOnTests(_Sched):
    def setUp(self):
        super().setUp()
        self.switch(roles=["hr"])

    def classic(self, name, who=None, **query):
        browser = DjangoClient()
        browser.force_login(who or self.hr)
        return browser.get(reverse(f"dashboard:{name}"), query)

    def test_each_page_is_handed_on_with_what_it_carries(self):
        for name, path, query, kept in (
            ("hr_schedules", "/app/hr/schedules", {"user": str(self.tr.pk)}, f"user={self.tr.pk}"),
            ("hr_shifts", "/app/hr/shifts", {"edit": str(self.morning.pk)}, f"edit={self.morning.pk}"),
            ("hr_offices", "/app/hr/offices", {"edit": "4"}, "edit=4"),
            ("hr_devices", "/app/hr/devices", {}, ""),
            ("hr_overtime", "/app/hr/overtime", {}, ""),
        ):
            answer = self.classic(name, **query)
            self.assertEqual(answer.status_code, 302, name)
            self.assertTrue(answer["Location"].startswith(path), answer["Location"])
            self.assertIn(kept, answer["Location"])

    def test_the_old_way_back_is_gone_and_the_flag_holder_is_handed_on_to_the_attendance_pages(self):
        for name in ("hr_schedules", "hr_shifts", "hr_offices", "hr_devices", "hr_overtime"):
            self.assertEqual(self.classic(name, classic=1).status_code, 302, name)
            answer = self.classic(name, who=self.flagged)
            self.assertEqual(answer.status_code, 302, name)
            self.assertTrue(answer["Location"].startswith("/app/hr/"), answer["Location"])

    def test_a_post_to_a_classic_page_is_never_handed_on(self):
        browser = DjangoClient()
        browser.force_login(self.hr)
        answer = browser.post(reverse("dashboard:hr_offices"), {"name": "HQ", "latitude": "30.04", "longitude": "31.23", "radius_meters": "150", "is_active": "on"})
        self.assertEqual(answer.status_code, 302)
        self.assertEqual(answer["Location"], reverse("dashboard:hr_offices"))
        self.assertTrue(OfficeLocation.objects.filter(name="HQ").exists())
