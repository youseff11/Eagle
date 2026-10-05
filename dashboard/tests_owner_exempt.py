"""The owner (the admin) is not bound by the company's rules: no attendance, no leave, no salary, no roster, no probation.

Held here: the model keeps the owner's attendance off whichever way they became an admin (and the migration did it for the ones that
existed); no door that clocks, rosters, grants leave or asks for a salary will take the owner as its person; no HR or accounts list
offers them; the register and the file say "nothing to count" and not a nought or a closed card; and an ordinary employee is
exactly as bound as before.
"""

import importlib
from datetime import time

from django.apps import apps
from django.test import Client as DjangoClient
from django.urls import reverse

from . import attendance, employees, newui, payroll
from .forms import StaffEditForm
from .models import (
    PayrollLine, PayrollPeriod, ProbationReview, Role, SalaryChangeRequest, ScheduleOverride, Shift, User, rule_followers,
)
from .tests_api_v1 import _json
from .tests_hr_people import (
    EMP_MODE, EMP_PLAN, EMP_SHIFT, EMPLOYEE, PROBATION, REGISTER, REQUESTS, _People,
)

SCHEDULES = "dashboard:v1_hr_schedules"
LEAVE_QUEUE = "dashboard:v1_hr_leave"
ASK = "dashboard:v1_leave_request"
BOARD = "dashboard:v1_hr_board"
SHIFT_ADD = "dashboard:v1_admin_shift_add"
SAVE = "dashboard:v1_admin_user_save"


class TheModelTests(_People):
    def test_an_admin_is_never_saved_with_attendance_on(self):
        for how in (
            lambda: User.objects.create_user("owner_a", password="pw", role=Role.ADMIN, attendance_enabled=True),
            lambda: User.objects.create_superuser("owner_b", password="pw", role=Role.TRANSLATOR, attendance_enabled=True),
        ):
            person = how()
            person.refresh_from_db()
            self.assertTrue(person.is_admin_role)
            self.assertFalse(person.attendance_enabled)

    def test_a_person_made_an_admin_later_loses_it_and_an_employee_keeps_it(self):
        self.assertTrue(User.objects.get(pk=self.tr.pk).attendance_enabled)
        self.tr.role = Role.ADMIN
        self.tr.save()
        self.assertFalse(User.objects.get(pk=self.tr.pk).attendance_enabled)

    def test_the_migration_switches_it_off_for_the_admins_that_already_exist(self):
        User.objects.filter(pk=self.admin.pk).update(attendance_enabled=True)
        boss = User.objects.create_superuser("owner_c", password="pw", role=Role.HR)
        User.objects.filter(pk=boss.pk).update(attendance_enabled=True)
        migration = importlib.import_module("dashboard.migrations.0044_owner_has_no_attendance")
        migration.owner_has_no_attendance(apps, None)
        for person in (self.admin, boss):
            self.assertFalse(User.objects.get(pk=person.pk).attendance_enabled)
        for person in (self.tr, self.hr, self.ops):
            self.assertTrue(User.objects.get(pk=person.pk).attendance_enabled)

    def test_the_rule_followers_are_everybody_but_the_owner(self):
        boss = User.objects.create_superuser("owner_d", password="pw", role=Role.HR)
        ids = set(rule_followers(User.objects.all()).values_list("pk", flat=True))
        self.assertNotIn(self.admin.pk, ids)
        self.assertNotIn(boss.pk, ids)
        self.assertIn(self.tr.pk, ids)
        self.assertTrue(self.tr.follows_company_rules)
        self.assertFalse(self.admin.follows_company_rules)

    def test_the_staff_form_does_not_offer_the_owner_a_box_for_it(self):
        form = StaffEditForm(instance=self.admin)
        self.assertTrue(form.fields["attendance_enabled"].disabled)
        self.assertFalse(StaffEditForm(instance=self.tr).fields["attendance_enabled"].disabled)
        answer = self.post(self.admin, SAVE, {"values": {"attendance_enabled": True}}, [self.admin.pk])
        self.assertEqual(answer.status_code, 200)
        self.assertFalse(User.objects.get(pk=self.admin.pk).attendance_enabled)


class TheDoorsTests(_People):
    def test_the_owner_cannot_clock_in_and_is_never_asked_to(self):
        Shift.objects.create(user=self.admin, weekday=self.today.weekday(), start_time=time(0, 0), end_time=time(23, 59))
        with self.assertRaises(attendance.PunchRefused) as refused:
            attendance.punch(self.admin, "check_in")
        self.assertEqual(refused.exception.code, "disabled")
        self.assertIsNone(attendance.gate_for(self.admin))

    def test_the_owner_has_no_attendance_screen_in_their_menu_and_an_employee_does(self):
        self.assertNotIn("attendance", newui.enabled_keys(self.admin))
        self.assertIn("attendance", newui.enabled_keys(self.tr))

    def test_no_leave_for_the_owner(self):
        answer = self.post(self.admin, ASK, {"values": {"kind": "annual", "start_date": self.today.isoformat(), "end_date": self.today.isoformat()}})
        self.assertEqual((answer.status_code, _json(answer)["error"]), (409, "refused"))
        self.assertEqual(self.admin.leave_requests.count(), 0)
        with self.assertRaises(employees.LifecycleError):
            employees.request_leave(self.admin, kind="annual", start_date=self.today)

    def test_no_salary_request_for_the_owner(self):
        with self.assertRaises(employees.LifecycleError):
            employees.request_salary_change(self.admin, new_amount="5000", effective_from=self.today)
        answer = self.post(self.hr, "dashboard:v1_hr_salary_request_create", {"user": self.admin.pk, "values": {"new_amount": "5000", "reason": "x"}})
        self.assertEqual(answer.status_code, 409)
        self.assertEqual(SalaryChangeRequest.objects.filter(user=self.admin).count(), 0)

    def test_the_doors_that_write_a_roster_a_mode_or_a_plan_refuse_the_owner(self):
        body = {"template": "", "weekdays": [], "new_name": "", "new_start": "", "new_end": ""}
        for name, send in ((EMP_SHIFT, body), (EMP_MODE, {"work_mode": "office"}), (EMP_PLAN, {"plan": None})):
            answer = self.post(self.admin, name, send, [self.admin.pk])
            self.assertEqual((answer.status_code, _json(answer)["error"]), (400, "owner"), name)
        answer = self.post(self.admin, SHIFT_ADD, {"weekday": 0, "start_time": "09:00", "end_time": "17:00"}, [self.admin.pk])
        self.assertEqual((answer.status_code, _json(answer)["error"]), (400, "owner"))
        self.assertEqual(self.admin.shifts.count(), 0)

    def test_the_same_doors_still_take_an_employee(self):
        answer = self.post(self.admin, EMP_MODE, {"work_mode": "remote"}, [self.tr.pk])
        self.assertEqual(answer.status_code, 200)


class TheListsTests(_People):
    def test_the_owner_is_not_on_the_attendance_board_or_offered_for_a_roster(self):
        self.day(person=self.tr)
        rows = _json(self.read(BOARD, self.hr))["rows"]
        self.assertTrue(rows)
        self.assertNotIn(self.admin.pk, [row["user"]["id"] for row in rows])
        body = _json(self.read(SCHEDULES, self.hr, user=self.admin.pk))
        self.assertIsNone(body.get("person"))

    def test_the_owner_is_not_offered_for_leave_or_a_salary_change(self):
        options = _json(self.read(LEAVE_QUEUE, self.hr))["options"]["people"]
        self.assertNotIn(self.admin.pk, [one["id"] for one in options])
        self.assertIn(self.tr.pk, [one["id"] for one in options])
        people = _json(self.read(REQUESTS, self.hr))["people"]
        self.assertNotIn(self.admin.pk, [one["id"] for one in people])
        self.assertIsNone(_json(self.read(REQUESTS, self.hr, user=self.admin.pk))["person"])

    def test_the_owner_is_not_on_the_probation_board(self):
        ProbationReview.objects.create(user=self.admin, stage="final", due_date=self.today)
        ProbationReview.objects.create(user=self.tr, stage="final", due_date=self.today)
        body = _json(self.read(PROBATION, self.hr))
        self.assertEqual([row["user"]["id"] for row in body["rows"]], [self.tr.pk])
        User.objects.filter(pk=self.admin.pk).update(employment_status="probation")
        self.assertNotIn(self.admin.pk, [one["id"] for one in _json(self.read(PROBATION, self.hr))["on_probation"]])

    def test_no_payroll_line_is_made_for_the_owner(self):
        period = payroll.compute_period(self.today.year, self.today.month)
        self.assertIsInstance(period, PayrollPeriod)
        self.assertFalse(PayrollLine.objects.filter(user=self.admin).exists())

    def test_the_register_says_nothing_to_count_for_the_owner_and_counts_the_rest(self):
        rows = {row["id"]: row for row in _json(self.read(REGISTER, self.admin))["rows"]}
        self.assertEqual((rows[self.admin.pk]["shifts"], rows[self.admin.pk]["rating"]), (None, None))
        self.assertIsInstance(rows[self.tr.pk]["shifts"], int)
        self.assertIsInstance(rows[self.tr.pk]["rating"], float)


class TheOwnersFileTests(_People):
    def test_the_file_carries_who_they_are_and_none_of_the_rules(self):
        Shift.objects.create(user=self.admin, weekday=0, start_time=time(9), end_time=time(17))
        ScheduleOverride.objects.create(user=self.admin, date=self.today, is_day_off=True)
        body = _json(self.read(EMPLOYEE, self.admin, args=[self.admin.pk]))
        self.assertTrue(body["person"]["exempt"])
        self.assertEqual(body["shifts"], [])
        for key in ("summary", "picker", "work_mode_card"):
            self.assertIsNone(body[key], key)
        for key in ("probation", "leave", "salary"):
            self.assertEqual(body[key], [], key)
        self.assertEqual(body["plan"], {"current": None, "options": []})
        self.assertEqual((body["can"]["shift"], body["can"]["plan"]), (False, False))
        self.assertTrue(body["can"]["edit"])

    def test_an_employees_file_is_as_bound_as_it_was(self):
        body = _json(self.read(EMPLOYEE, self.admin, args=[self.tr.pk]))
        self.assertFalse(body["person"]["exempt"])
        self.assertIsNotNone(body["picker"])
        self.assertIsNotNone(body["summary"])
        self.assertTrue(body["can"]["plan"])
