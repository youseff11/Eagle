"""HR's people pages in the new app: the register and a person's file, probation, performance, client complaints, pay.

Who may open each is the question its classic page asks: recruitment rights (HR, the admin) for the register, the file,
performance, complaints and salary requests; attendance rights (also a flag) for probation and the file's shift and work-mode
cards; the admin alone for the salary plans, assigning one, and deciding a salary change. What these tests hold: HR cannot move
a salary (it asks, the owner decides, approval writes the record), a complaint never carries a client's identity to HR, a review
or a request that was decided is not decided again, a GET changes nothing.
"""

import json
from datetime import date, time, timedelta
from decimal import Decimal

from django.test import Client as DjangoClient
from django.urls import reverse
from django.utils import timezone

from . import attendance, employees, identity, newui
from .models import (
    ApprovalStatus, AppSettings, AuditLog, Candidate, ClientComplaint, Department, LeaveRequest, ProbationReview, SalaryChangeRequest,
    SalaryPlan, SalaryRecord, ShiftTemplate, User, WorkDay,
)
from .tests_api_v1 import CLIENT_NAME, _json
from .tests_hr_attendance import _Hr

REGISTER = "dashboard:v1_hr_register"
EMPLOYEE = "dashboard:v1_hr_employee"
EMP_SHIFT = "dashboard:v1_hr_employee_shift"
EMP_MODE = "dashboard:v1_hr_employee_workmode"
EMP_PLAN = "dashboard:v1_hr_employee_plan"
EMP_INCENTIVE = "dashboard:v1_hr_employee_incentive"
PROBATION = "dashboard:v1_hr_probation"
PROB_DECIDE = "dashboard:v1_hr_probation_decide"
PROB_OPEN = "dashboard:v1_hr_probation_open"
PERFORMANCE = "dashboard:v1_hr_performance"
PERFORMANCE_BOARD = "dashboard:v1_hr_performance_board"
COMPLAINTS = "dashboard:v1_hr_complaints"
COMPLAINT_NEW = "dashboard:v1_hr_complaint_create"
COMPLAINT_RESOLVE = "dashboard:v1_hr_complaint_resolve"
REQUESTS = "dashboard:v1_hr_salary_requests"
REQUEST_NEW = "dashboard:v1_hr_salary_request_create"
REQUEST_DECIDE = "dashboard:v1_hr_salary_request_decide"
PLANS = "dashboard:v1_hr_salary_plans"
PLAN_SAVE = "dashboard:v1_hr_salary_plan_save"


class _People(_Hr):
    def setUp(self):
        super().setUp()
        self.dept = Department.objects.create(name="Linguistics", name_ar="اللغويات")
        User.objects.filter(pk=self.tr.pk).update(
            department=self.dept, job_title="Translator", joining_date=date(2025, 1, 5), phone="01000000000", languages="AR/EN",
            employee_code="EMP-0042",
        )
        self.tr.refresh_from_db()

    def read(self, name, who=None, args=None, **query):
        browser = DjangoClient()
        browser.force_login(who or self.hr)
        return browser.get(reverse(name, args=args), query)


class DoorMatrixTests(_People):
    def setUp(self):
        super().setUp()
        self.review = ProbationReview.objects.create(user=self.tr, stage="final", due_date=self.today)
        self.complaint = ClientComplaint.objects.create(summary="Late", translator=self.tr)
        self.request_row = SalaryChangeRequest.objects.create(user=self.tr, new_amount=Decimal("100"), effective_from=self.today)
        self.plan = SalaryPlan.objects.create(name="Plan A")

    def call(self, who, method, name, args):
        browser = DjangoClient()
        if who is not None:
            browser.force_login(who)
        url = reverse(name, args=args)
        return browser.get(url) if method == "GET" else browser.post(url, "{}", content_type="application/json")

    def groups(self):
        """(who is let in, the doors)."""
        recruit = [
            ("GET", REGISTER, None), ("GET", EMPLOYEE, [self.tr.pk]), ("GET", PERFORMANCE, None), ("GET", COMPLAINTS, None),
            ("POST", COMPLAINT_NEW, None), ("POST", COMPLAINT_RESOLVE, [self.complaint.pk]), ("GET", REQUESTS, None),
            ("POST", REQUEST_NEW, None),
        ]
        manage = [
            ("POST", EMP_SHIFT, [self.tr.pk]), ("POST", EMP_MODE, [self.tr.pk]), ("GET", PROBATION, None),
            ("POST", PROB_DECIDE, [self.review.pk]), ("POST", PROB_OPEN, [self.tr.pk]),
        ]
        owner = [
            ("POST", EMP_PLAN, [self.tr.pk]), ("POST", REQUEST_DECIDE, [self.request_row.pk, "approve"]),
            ("GET", PLANS, None), ("POST", PLAN_SAVE, None),
        ]
        return (
            ((self.hr, self.admin), (self.ops, self.lead, self.tr, self.reviewer, self.accounting, self.sales, self.flagged), recruit),
            ((self.hr, self.admin, self.flagged), (self.ops, self.lead, self.tr, self.reviewer, self.accounting, self.sales), manage),
            ((self.admin,), (self.hr, self.flagged, self.ops, self.lead, self.tr, self.reviewer, self.accounting, self.sales), owner),
        )

    def test_each_door_lets_in_who_its_classic_page_lets_in_and_nobody_else(self):
        for _in, out, doors in self.groups():
            for method, name, args in doors:
                for who in out:
                    self.assertEqual(self.call(who, method, name, args).status_code, 403, f"{name} {who.username}")
                self.assertEqual(self.call(None, method, name, args).status_code, 401, name)
        for allowed, _out, doors in self.groups():
            for method, name, args in doors:
                for who in allowed:
                    self.assertNotIn(self.call(who, method, name, args).status_code, (401, 403), f"{name} {who.username}")

    def test_a_refusal_is_written_down_and_changes_nothing(self):
        before = AuditLog.objects.filter(action=identity.ACCESS_DENIED).count()
        answer = self.call(self.hr, "POST", REQUEST_DECIDE, [self.request_row.pk, "approve"])
        self.assertEqual((answer.status_code, _json(answer)["error"]), (403, "forbidden"))
        self.assertEqual(AuditLog.objects.filter(action=identity.ACCESS_DENIED).count(), before + 1)
        self.request_row.refresh_from_db()
        self.assertEqual(self.request_row.status, ApprovalStatus.PENDING)
        self.assertFalse(SalaryRecord.objects.filter(user=self.tr).exists())

    def test_the_wrong_method_is_refused(self):
        for name, args, wrong in (
            (REGISTER, None, "post"), (EMPLOYEE, [1], "post"), (PROBATION, None, "post"), (PERFORMANCE, None, "post"), (PERFORMANCE_BOARD, None, "post"),
            (COMPLAINTS, None, "post"), (REQUESTS, None, "post"), (PLANS, None, "post"),
            (EMP_SHIFT, [1], "get"), (EMP_MODE, [1], "get"), (EMP_PLAN, [1], "get"), (PROB_DECIDE, [1], "get"), (PROB_OPEN, [1], "get"),
            (COMPLAINT_NEW, None, "get"), (COMPLAINT_RESOLVE, [1], "get"), (REQUEST_NEW, None, "get"), (REQUEST_DECIDE, [1, "approve"], "get"),
            (PLAN_SAVE, None, "get"),
        ):
            browser = DjangoClient()
            browser.force_login(self.admin)
            self.assertEqual(getattr(browser, wrong)(reverse(name, args=args)).status_code, 405, name)


class RegisterTests(_People):
    def test_the_register_lists_the_active_with_their_words(self):
        gone = User.objects.create_user("person_gone", password="pw", role="translator", is_active=False)
        body = _json(self.read(REGISTER))
        ids = [one["id"] for one in body["rows"]]
        self.assertIn(self.tr.pk, ids)
        self.assertNotIn(gone.pk, ids)
        row = [one for one in body["rows"] if one["id"] == self.tr.pk][0]
        self.assertEqual(
            (row["code"], row["role"]["ar"], row["department"], row["joining_date"], row["status"]["value"]),
            ("EMP-0042", "مترجم", "اللغويات", "2025-01-05", self.tr.employment_status),
        )
        self.assertEqual(row["employment"]["value"], self.tr.employment_type)

    def test_the_filters_narrow_it(self):
        User.objects.filter(pk=self.ops.pk).update(employment_status="probation")
        ids = lambda **query: [one["id"] for one in _json(self.read(REGISTER, **query))["rows"]]
        self.assertEqual(ids(department=self.dept.pk), [self.tr.pk])
        self.assertIn(self.ops.pk, ids(status="probation"))
        self.assertNotIn(self.tr.pk, ids(status="probation"))
        self.assertEqual(self.read(REGISTER, department="abc").status_code, 400)

    def test_the_options_are_the_active_departments_and_the_statuses_with_their_words(self):
        Department.objects.create(name="Old", is_active=False)
        options = _json(self.read(REGISTER))["options"]
        labels = [one["label"] for one in options["departments"]]
        self.assertIn("اللغويات", labels)
        self.assertNotIn("Old", labels)
        self.assertIn({"value": "probation", "tone": "wait", "ar": "تحت الاختبار", "en": "Probation"}, options["statuses"])

    def test_a_get_writes_nothing_and_the_queries_do_not_grow(self):
        from django.db import connection
        from django.test.utils import CaptureQueriesContext

        audit = AuditLog.objects.count()

        def queries():
            with CaptureQueriesContext(connection) as seen:
                self.read(REGISTER)
            return len(seen)

        queries()
        few = queries()
        for number in range(8):
            User.objects.create_user(f"person_more_{number}", password="pw", role="translator", department=self.dept)
        self.assertEqual(queries(), few)
        self.assertEqual(AuditLog.objects.count(), audit)


class FileTests(_People):
    def test_a_file_carries_the_details_the_classic_page_prints(self):
        body = _json(self.read(EMPLOYEE, args=[self.tr.pk]))
        person = body["person"]
        self.assertEqual(
            (person["name"], person["code"], person["job_title"], person["department"], person["manager"], person["languages"], person["phone"]),
            (self.tr.short_name, "EMP-0042", "Translator", "اللغويات", self.lead.short_name, "AR/EN", "01000000000"),
        )
        self.assertEqual((person["joining_date"], person["role"]["en"]), ("2025-01-05", "Translator"))

    def test_this_months_attendance_is_there_unless_attendance_is_off_for_the_account(self):
        WorkDay.objects.create(user=self.tr, date=self.today, status="present", work_mode="office")
        summary = _json(self.read(EMPLOYEE, args=[self.tr.pk]))["summary"]
        self.assertEqual(summary["present_days"], 1)
        User.objects.filter(pk=self.tr.pk).update(attendance_enabled=False)
        self.assertIsNone(_json(self.read(EMPLOYEE, args=[self.tr.pk]))["summary"])

    def test_the_cards_that_are_attendance_rights_are_drawn_for_who_has_them(self):
        template = ShiftTemplate.objects.create(name="Morning", name_ar="الصبح", start_time=time(9), end_time=time(17))
        attendance.assign_shift(self.tr, template, [0, 1])
        body = _json(self.read(EMPLOYEE, args=[self.tr.pk]))
        self.assertEqual(body["picker"]["current"], template.pk)
        self.assertEqual([one["num"] for one in body["picker"]["days"] if one["checked"]], [0, 1])
        self.assertEqual(len(body["shifts"]), 2)
        self.assertFalse(body["work_mode_card"]["is_hybrid"])
        self.assertTrue(body["can"]["shift"])

    def test_the_work_mode_card_names_the_offices_and_what_a_pinned_day_means(self):
        from .models import OfficeLocation

        OfficeLocation.objects.create(name="HQ", name_ar="المقر", latitude="30.0", longitude="31.0", radius_meters=150)
        card = _json(self.read(EMPLOYEE, args=[self.tr.pk]))["work_mode_card"]
        self.assertEqual(card["offices"], [{"label": "المقر", "radius_meters": 150}])
        self.assertEqual(card["pinned_days"], 0)

    def test_who_may_edit_a_person_or_assign_a_plan_is_the_admin_alone(self):
        SalaryPlan.objects.create(name="Plan A")
        as_hr = _json(self.read(EMPLOYEE, args=[self.tr.pk]))
        self.assertEqual(as_hr["can"], {"edit": False, "shift": True, "plan": False, "decide_penalties": True, "change_penalties": False, "incentive": False})
        self.assertEqual(as_hr["plan"]["options"], [])
        as_admin = _json(self.read(EMPLOYEE, self.admin, args=[self.tr.pk]))
        self.assertEqual(as_admin["can"], {"edit": True, "shift": True, "plan": True, "decide_penalties": True, "change_penalties": True, "incentive": True})
        self.assertEqual([one["name"] for one in as_admin["plan"]["options"]], ["Plan A"])

    def test_the_plan_a_person_is_on_is_named_with_what_it_changes(self):
        plan = SalaryPlan.objects.create(name="Plan A", daily_target_words=2000, extra_word_rate=Decimal("0.0500"))
        User.objects.filter(pk=self.tr.pk).update(salary_plan=plan)
        current = _json(self.read(EMPLOYEE, args=[self.tr.pk]))["plan"]["current"]
        self.assertEqual((current["name"], current["overrides"]), ("Plan A", ["daily_target_words", "extra_word_rate"]))

    def test_probation_leave_salary_and_the_application_are_on_the_file_with_money_as_text(self):
        User.objects.filter(pk=self.tr.pk).update(employment_status="probation")
        self.tr.refresh_from_db()
        employees.open_probation(self.tr, actor=self.admin)
        LeaveRequest.objects.create(user=self.tr, kind="annual", start_date=self.today, end_date=self.today)
        SalaryRecord.objects.create(user=self.tr, amount=Decimal("3500.50"), effective_from=date(2025, 1, 1), created_by=self.admin)
        Candidate.objects.create(full_name="Sam Candidate", hired_user=self.tr)
        body = _json(self.read(EMPLOYEE, args=[self.tr.pk]))
        self.assertEqual([one["stage"]["value"] for one in body["probation"]], ["day_30", "day_60", "final"])
        self.assertEqual(body["probation"][0]["outcome"]["value"], "pending")
        self.assertEqual(body["leave"][0]["kind"]["value"], "annual")
        self.assertEqual(body["salary"], [{"effective_from": "2025-01-01", "amount": "3500.50"}])
        self.assertTrue(body["application"]["code"])
        self.assertNotIn("Sam Candidate", json.dumps(body))

    def test_a_person_that_is_not_there_is_not_there(self):
        self.assertEqual(self.read(EMPLOYEE, args=[999999]).status_code, 404)

    def test_a_get_writes_nothing(self):
        audit = AuditLog.objects.count()
        self.read(EMPLOYEE, args=[self.tr.pk])
        self.assertEqual(AuditLog.objects.count(), audit)


class ShiftAndModeTests(_People):
    def setUp(self):
        super().setUp()
        self.morning = ShiftTemplate.objects.create(name="Morning", name_ar="الصبح", start_time=time(9), end_time=time(17))

    def shift(self, body, who=None):
        return self.post(who or self.hr, EMP_SHIFT, body, [self.tr.pk])

    def test_a_person_is_put_on_a_company_shift_for_some_weekdays(self):
        answer = self.shift({"template": str(self.morning.pk), "weekdays": [0, 1, 2]})
        self.assertEqual((answer.status_code, _json(answer)["label"]), (200, "الصبح"))
        self.assertEqual(sorted(self.tr.shifts.values_list("weekday", flat=True)), [0, 1, 2])
        self.assertTrue(all(self.tr.shifts.values_list("is_active", flat=True)))

    def test_no_shift_takes_the_roster_off(self):
        attendance.assign_shift(self.tr, self.morning, [0])
        self.assertEqual(_json(self.shift({"template": "", "weekdays": []}))["label"], "")
        self.assertFalse(self.tr.shifts.exists())

    def test_a_shift_nobody_has_made_yet_is_made_from_its_hours(self):
        answer = self.shift({"template": "new", "weekdays": [0], "new_name": "ليلي", "new_start": "22:00", "new_end": "06:00"})
        self.assertEqual((answer.status_code, _json(answer)["label"]), (200, "ليلي"))
        self.assertTrue(ShiftTemplate.objects.filter(name_ar="ليلي").exists())

    def test_a_bad_choice_is_refused_in_the_shift_pickers_own_codes_and_changes_nothing(self):
        attendance.assign_shift(self.tr, self.morning, [0])
        for body, code in (
            ({"template": "999999", "weekdays": [0]}, "no_such_shift"),
            ({"template": str(self.morning.pk), "weekdays": []}, "no_days"),
            ({"template": "new", "weekdays": [0], "new_start": "22:00"}, "bad_new_shift"),
        ):
            answer = self.shift(body)
            self.assertEqual((answer.status_code, _json(answer)["error"]), (400, code), body)
        self.assertEqual(self.tr.shifts.count(), 1)

    def test_a_body_that_is_not_the_shape_is_refused(self):
        for body in ({"template": ["1"]}, {"template": "1", "weekdays": "0"}, {"template": "1", "weekdays": [True]},
                     {"template": "1", "weekdays": list(range(20))}, {"template": "new", "new_name": "x" * 61}):
            self.assertEqual(self.shift(body).status_code, 400, body)

    def mode(self, value, who=None):
        return self.post(who or self.hr, EMP_MODE, {"work_mode": value}, [self.tr.pk])

    def test_home_or_office_is_saved_and_written_down_once(self):
        User.objects.filter(pk=self.tr.pk).update(work_mode="office")
        self.assertEqual(self.mode("remote").status_code, 200)
        self.tr.refresh_from_db()
        self.assertEqual(self.tr.work_mode, "remote")
        self.assertEqual(AuditLog.objects.filter(action="employee.work_mode").count(), 1)
        self.mode("remote")
        self.assertEqual(AuditLog.objects.filter(action="employee.work_mode").count(), 1)

    def test_hybrid_is_kept_for_somebody_on_it_and_never_offered_fresh(self):
        User.objects.filter(pk=self.tr.pk).update(work_mode="office")
        answer = self.mode("hybrid")
        self.assertEqual((answer.status_code, _json(answer)["error"]), (400, "bad_mode"))
        User.objects.filter(pk=self.tr.pk).update(work_mode="hybrid")
        self.assertEqual(self.mode("hybrid").status_code, 200)
        self.assertTrue(_json(self.read(EMPLOYEE, args=[self.tr.pk]))["work_mode_card"]["is_hybrid"])

    def test_anything_else_is_refused(self):
        for value in ("", "moon", 5, None, ["office"]):
            self.assertEqual(self.mode(value).status_code, 400, value)

    def test_the_flag_holder_may_do_both_and_an_ordinary_role_may_not(self):
        self.assertEqual(self.mode("remote", self.flagged).status_code, 200)
        self.assertEqual(self.mode("office", self.ops).status_code, 403)
        self.assertEqual(self.shift({"template": "", "weekdays": []}, self.flagged).status_code, 200)


class PlanAssignTests(_People):
    def test_the_admin_gives_a_plan_and_takes_it_off(self):
        plan = SalaryPlan.objects.create(name="Plan A")
        self.assertEqual(self.post(self.admin, EMP_PLAN, {"plan": plan.pk}, [self.tr.pk]).status_code, 200)
        self.tr.refresh_from_db()
        self.assertEqual(self.tr.salary_plan, plan)
        self.assertTrue(AuditLog.objects.filter(action="salary.plan.assign", actor=self.admin).exists())
        self.assertEqual(self.post(self.admin, EMP_PLAN, {"plan": None}, [self.tr.pk]).status_code, 200)
        self.tr.refresh_from_db()
        self.assertIsNone(self.tr.salary_plan)

    def test_hr_cannot_and_a_plan_that_is_not_there_is_not_there(self):
        plan = SalaryPlan.objects.create(name="Plan A")
        self.assertEqual(self.post(self.hr, EMP_PLAN, {"plan": plan.pk}, [self.tr.pk]).status_code, 403)
        self.tr.refresh_from_db()
        self.assertIsNone(self.tr.salary_plan)
        self.assertEqual(self.post(self.admin, EMP_PLAN, {"plan": 999999}, [self.tr.pk]).status_code, 404)
        for body in ({"plan": "1"}, {"plan": True}, {"plan": 0}, {}):
            self.assertIn(self.post(self.admin, EMP_PLAN, body, [self.tr.pk]).status_code, (200, 400), body)
        self.assertEqual(self.post(self.admin, EMP_PLAN, {"plan": "1"}, [self.tr.pk]).status_code, 400)


class ProbationTests(_People):
    def setUp(self):
        super().setUp()
        User.objects.filter(pk=self.tr.pk).update(employment_status="probation", probation_start=self.today - timedelta(days=40), probation_end=self.today + timedelta(days=50))
        self.tr.refresh_from_db()
        employees.open_probation(self.tr, actor=self.admin)
        self.reviews = {one.stage: one for one in ProbationReview.objects.filter(user=self.tr)}

    def decide(self, review, values, who=None):
        return self.post(who or self.hr, PROB_DECIDE, {"values": values}, [review.pk])

    def test_the_open_reviews_are_listed_and_the_decision_form_has_no_pending_choice(self):
        body = _json(self.read(PROBATION))
        self.assertEqual((body["state"], len(body["rows"])), ("open", 3))
        first = body["rows"][0]
        self.assertEqual((first["stage"]["ar"], first["outcome"]["value"], first["decided"], first["user"]["id"]), ("مراجعة 30 يوم", "pending", False, self.tr.pk))
        fields = {one["name"]: one for one in body["form"]}
        self.assertEqual([c["value"] for c in fields["outcome"]["choices"] if c["value"]], ["confirmed", "extended", "terminated"])
        self.assertEqual({c["value"]: c["label_en"] for c in fields["outcome"]["choices"] if c["value"]}["terminated"], "End")
        self.assertEqual((fields["extend_days"]["label_ar"], fields["score"]["label_en"]), ("تمديد (يوم)", "Score out of 10"))

    def test_due_and_all_narrow_and_widen_the_list(self):
        ProbationReview.objects.filter(pk=self.reviews["day_30"].pk).update(due_date=self.today - timedelta(days=2))
        due = _json(self.read(PROBATION, state="due"))
        self.assertEqual((due["state"], [one["stage"]["value"] for one in due["rows"]], due["rows"][0]["overdue"], due["due_count"]), ("due", ["day_30"], True, 1))
        employees.decide_probation(self.reviews["day_60"], self.hr, outcome="confirmed")
        self.assertEqual(len(_json(self.read(PROBATION))["rows"]), 2)
        self.assertEqual(len(_json(self.read(PROBATION, state="all"))["rows"]), 3)

    def test_who_is_on_probation_and_whether_their_reviews_were_opened(self):
        other = User.objects.create_user("person_new_hire", password="pw", role="translator", employment_status="probation")
        body = _json(self.read(PROBATION))
        by_id = {one["id"]: one for one in body["on_probation"]}
        self.assertTrue(by_id[self.tr.pk]["has_reviews"])
        self.assertFalse(by_id[other.pk]["has_reviews"])

    def test_a_thirty_day_review_decides_nothing_about_the_person(self):
        answer = self.decide(self.reviews["day_30"], {"outcome": "confirmed", "score": "8", "notes": "Good start"})
        self.assertEqual(answer.status_code, 200)
        self.reviews["day_30"].refresh_from_db()
        self.assertEqual((self.reviews["day_30"].outcome, self.reviews["day_30"].score, self.reviews["day_30"].reviewer), ("confirmed", 8, self.hr))
        self.tr.refresh_from_db()
        self.assertEqual(self.tr.employment_status, "probation")

    def test_the_final_review_confirms_or_ends_somebody(self):
        self.decide(self.reviews["final"], {"outcome": "confirmed"})
        self.tr.refresh_from_db()
        self.assertEqual((self.tr.employment_status, self.tr.is_active), ("active", True))

    def test_ending_somebody_closes_the_account_and_deletes_nothing(self):
        self.decide(self.reviews["final"], {"outcome": "terminated", "notes": "Not a fit"})
        self.tr.refresh_from_db()
        self.assertEqual((self.tr.employment_status, self.tr.is_active), ("left", False))
        self.assertTrue(User.objects.filter(pk=self.tr.pk).exists())

    def test_an_extension_moves_the_end_and_the_final_review_with_it(self):
        end = self.tr.probation_end
        self.decide(self.reviews["day_60"], {"outcome": "extended", "extend_days": "15"})
        self.tr.refresh_from_db()
        self.reviews["final"].refresh_from_db()
        self.assertEqual((self.tr.probation_end, self.reviews["final"].due_date), (end + timedelta(days=15), end + timedelta(days=15)))

    def test_the_forms_rules_are_the_rules(self):
        for values, field in (({"outcome": "extended", "extend_days": ""}, "extend_days"), ({"outcome": "confirmed", "score": "11"}, "score"), ({"outcome": "pending"}, "outcome"), ({}, "outcome")):
            answer = self.decide(self.reviews["final"], values)
            self.assertEqual((answer.status_code, field in _json(answer)["errors"]), (400, True), values)
        self.assertEqual(self.decide(self.reviews["final"], {"outcome": "confirmed", "bogus": 1}).status_code, 400)
        self.reviews["final"].refresh_from_db()
        self.assertEqual(self.reviews["final"].outcome, "pending")

    def test_a_review_that_was_decided_is_not_decided_again(self):
        self.decide(self.reviews["day_30"], {"outcome": "confirmed"})
        again = self.decide(self.reviews["day_30"], {"outcome": "terminated"})
        body = _json(again)
        self.assertEqual((again.status_code, body["error"], body["message_en"]), (409, "refused", "This review has already been decided."))
        self.reviews["day_30"].refresh_from_db()
        self.assertEqual(self.reviews["day_30"].outcome, "confirmed")

    def test_opening_the_reviews_twice_makes_no_more(self):
        other = User.objects.create_user("person_new_hire", password="pw", role="translator", employment_status="probation", probation_start=self.today)
        first = self.post(self.hr, PROB_OPEN, {}, [other.pk])
        self.assertEqual((first.status_code, _json(first)["created"]), (200, 3))
        self.assertEqual(_json(self.post(self.hr, PROB_OPEN, {}, [other.pk]))["created"], 0)
        self.assertEqual(ProbationReview.objects.filter(user=other).count(), 3)
        self.assertEqual(self.post(self.hr, PROB_OPEN, {}, [999999]).status_code, 404)

    def test_a_review_that_is_not_there_is_not_there(self):
        self.assertEqual(self.post(self.hr, PROB_DECIDE, {"values": {"outcome": "confirmed"}}, [999999]).status_code, 404)


class PerformanceTests(_People):
    def test_a_translators_month_has_four_indicators_with_a_band_each(self):
        body = _json(self.read(PERFORMANCE, user=self.tr.pk))
        report = body["report"]
        self.assertEqual(sorted(report["parts"]), ["attendance", "deadline", "productivity", "quality"])
        self.assertEqual(set(report["weights"]), {"productivity", "quality", "deadline", "attendance"})
        self.assertEqual((body["person"]["id"], body["year"], body["month"]), (self.tr.pk, self.today.year, self.today.month))
        for part in report["parts"].values():
            self.assertIn(part["band"]["value"], ("good", "fair", "poor", "unknown"))

    def test_an_indicator_with_no_data_says_not_measured_and_why_in_both_languages(self):
        report = _json(self.read(PERFORMANCE, user=self.tr.pk))["report"]
        quality = report["parts"]["quality"]
        self.assertEqual((quality["score"], quality["band"]["value"], quality["band"]["ar"]), (None, "unknown", "مابتتقاسش"))
        self.assertEqual(quality["reason"], {"ar": "لسه ماتقيّمش حاجة", "en": "Nothing has been marked yet"})
        self.assertEqual(report["parts"]["deadline"]["reason"]["en"], "No jobs with a deadline")
        self.assertIsNone(report["overall"] if report["overall"] is None else None)

    def test_a_complaint_moves_the_quality_indicator_and_is_counted(self):
        ClientComplaint.objects.create(summary="Wrong term", translator=self.tr, severity="high", happened_on=self.today)
        quality = _json(self.read(PERFORMANCE, user=self.tr.pk))["report"]["parts"]["quality"]
        self.assertEqual((quality["complaints"], quality["score"]), (1, 75))

    def test_the_first_translator_is_the_default_and_a_bad_request_is_refused(self):
        body = _json(self.read(PERFORMANCE))
        self.assertEqual(body["person"], body["people"][0])
        self.assertEqual(self.read(PERFORMANCE, period="2026-13").status_code, 400)
        self.assertEqual(self.read(PERFORMANCE, user="abc").status_code, 400)
        self.assertEqual(_json(self.read(PERFORMANCE, user=99999999))["report"], None)

    def test_only_translators_are_picked_from_and_a_get_writes_nothing(self):
        audit = AuditLog.objects.count()
        body = _json(self.read(PERFORMANCE))
        self.assertEqual({one["id"] for one in body["people"]}, set(User.objects.filter(is_active=True, role="translator").values_list("pk", flat=True)))
        self.assertEqual(AuditLog.objects.count(), audit)


class ComplaintTests(_People):
    def make(self, **over):
        values = dict(summary="Late delivery", translator=self.tr, severity="medium", happened_on=self.today)
        values.update(over)
        return ClientComplaint.objects.create(**values)

    def test_a_complaint_is_listed_with_its_task_translator_and_severity(self):
        row = self.make(task=self.task, severity="high", detail="He was told twice")
        entry = _json(self.read(COMPLAINTS))["rows"][0]
        self.assertEqual(entry["id"], row.pk)
        self.assertEqual((entry["task"], entry["translator"], entry["detail"]), (self.task.code, self.tr.short_name, "He was told twice"))
        self.assertEqual((entry["severity"]["value"], entry["severity"]["tone"], entry["severity"]["ar"]), ("high", "dead", "خطيرة"))
        self.assertFalse(entry["resolved"])

    def test_hr_never_reads_a_clients_name_in_a_complaint(self):
        self.make(summary=f"{CLIENT_NAME} was angry", detail=f"Call {CLIENT_NAME} back", client=self.client_obj)
        raw = self.read(COMPLAINTS).content.decode()
        self.assertNotIn(CLIENT_NAME, raw)
        self.assertIn(self.client_obj.code, raw)
        as_admin = self.read(COMPLAINTS, self.admin).content.decode()
        self.assertIn(CLIENT_NAME, as_admin)

    def test_the_form_names_a_client_and_a_task_by_code_and_never_by_title(self):
        Task_title = f"{CLIENT_NAME} contract"
        type(self.task).objects.filter(pk=self.task.pk).update(title=Task_title)
        body = self.read(COMPLAINTS).content.decode()
        self.assertNotIn(CLIENT_NAME, body)
        fields = {one["name"]: one for one in json.loads(body)["form"]}
        self.assertIn(self.task.code, [c["label"] for c in fields["task"]["choices"]])
        self.assertIn(self.client_obj.code, [c["label"] for c in fields["client"]["choices"]])
        self.assertEqual((fields["severity"]["label_ar"], fields["task"]["hint_en"][:12]), ("الدرجة", "Pick the tas"))
        self.assertEqual({c["value"]: c["label_ar"] for c in fields["severity"]["choices"]}["low"], "بسيطة")

    def test_a_task_older_than_the_newest_two_hundred_can_be_picked(self):
        from datetime import datetime

        old = type(self.task).objects.get(pk=self.task.pk)
        type(self.task).objects.filter(pk=old.pk).update(created_at=timezone.make_aware(datetime(2020, 1, 1)))
        for number in range(205):
            copy = type(self.task).objects.get(pk=old.pk)
            copy.pk = None
            copy.code = ""
            copy.save()
        answer = self.post(self.hr, COMPLAINT_NEW, {"values": {"summary": "Old job", "task": str(old.pk)}})
        self.assertEqual((answer.status_code, _json(answer)["ok"]), (200, True))
        self.assertEqual(ClientComplaint.objects.get(summary="Old job").task_id, old.pk)

    def test_a_complaint_is_logged_by_whoever_logs_it_and_the_translator_fills_itself_in(self):
        answer = self.post(self.hr, COMPLAINT_NEW, {"values": {"summary": "Wrong term", "task": str(self.task.pk), "severity": "low"}})
        self.assertEqual(answer.status_code, 200)
        row = ClientComplaint.objects.get(summary="Wrong term")
        self.assertEqual((row.logged_by, row.translator, row.severity, row.happened_on), (self.hr, self.tr, "low", self.today))
        self.assertTrue(AuditLog.objects.filter(action="complaint.log", actor=self.hr).exists())

    def test_the_forms_rules_are_the_rules(self):
        self.assertEqual("summary" in _json(self.post(self.hr, COMPLAINT_NEW, {"values": {}}))["errors"], True)
        self.assertEqual(self.post(self.hr, COMPLAINT_NEW, {"values": {"summary": "x", "logged_by": 3}}).status_code, 400)
        self.assertEqual(self.post(self.hr, COMPLAINT_NEW, {"values": {"summary": "x", "translator": str(self.ops.pk)}}).status_code, 400)
        self.assertFalse(ClientComplaint.objects.exists())

    def test_closing_and_reopening(self):
        row = self.make()
        self.assertTrue(_json(self.post(self.hr, COMPLAINT_RESOLVE, {}, [row.pk]))["resolved"])
        row.refresh_from_db()
        self.assertTrue(row.resolved)
        self.assertFalse(_json(self.post(self.hr, COMPLAINT_RESOLVE, {}, [row.pk]))["resolved"])
        self.assertEqual(self.post(self.hr, COMPLAINT_RESOLVE, {}, [999999]).status_code, 404)

    def test_the_list_is_filtered_by_translator_and_a_bad_id_is_refused(self):
        other = User.objects.create_user("person_other_tr", password="pw", role="translator")
        mine, theirs = self.make(), self.make(translator=other, summary="Other")
        ids = [one["id"] for one in _json(self.read(COMPLAINTS, translator=other.pk))["rows"]]
        self.assertEqual(ids, [theirs.pk])
        self.assertEqual(self.read(COMPLAINTS, translator="abc").status_code, 400)
        self.assertIn(mine.pk, [one["id"] for one in _json(self.read(COMPLAINTS))["rows"]])


class SalaryRequestTests(_People):
    def setUp(self):
        super().setUp()
        SalaryRecord.objects.create(user=self.tr, amount=Decimal("3000.00"), effective_from=date(2020, 1, 1), created_by=self.admin)

    def ask(self, values, who=None, user=None):
        return self.post(who or self.hr, REQUEST_NEW, {"user": (user or self.tr).pk, "values": values})

    def test_the_page_shows_the_current_salary_as_text_for_the_person_picked(self):
        body = _json(self.read(REQUESTS, user=self.tr.pk))
        self.assertEqual((body["person"]["id"], body["current"]), (self.tr.pk, "3000.00"))
        self.assertEqual(_json(self.read(REQUESTS))["current"], None)
        fields = {one["name"]: one for one in body["form"]}
        self.assertEqual((fields["new_amount"]["label_ar"], fields["effective_from"]["value"]), ("الراتب الجديد", self.today.isoformat()))
        self.assertEqual(self.read(REQUESTS, user="abc").status_code, 400)

    def test_hr_asks_and_nothing_moves_until_the_owner_decides(self):
        answer = self.ask({"new_amount": "3500", "effective_from": self.today.isoformat(), "reason": "Raise"})
        self.assertEqual(answer.status_code, 200)
        row = SalaryChangeRequest.objects.get()
        self.assertEqual((row.current_amount, row.new_amount, row.status, row.requested_by), (Decimal("3000.00"), Decimal("3500"), ApprovalStatus.PENDING, self.hr))
        self.assertEqual(SalaryRecord.amount_on(self.tr, self.today), Decimal("3000.00"))
        self.assertTrue(AuditLog.objects.filter(action="salary.request", actor=self.hr).exists())
        waiting = _json(self.read(REQUESTS))["pending"][0]
        self.assertEqual((waiting["current_amount"], waiting["new_amount"], waiting["delta"], waiting["requested_by"]), ("3000.00", "3500.00", "500.00", self.hr.short_name))

    def test_a_request_without_a_date_is_from_today_as_the_page_drew_it(self):
        answer = self.ask({"new_amount": "3500"})
        self.assertEqual(answer.status_code, 200, answer.content)
        self.assertEqual(SalaryChangeRequest.objects.get().effective_from, self.today)

    def test_the_engines_rules_answer_in_its_words(self):
        same = self.ask({"new_amount": "3000", "effective_from": self.today.isoformat()})
        self.assertEqual((same.status_code, _json(same)["message_en"]), (409, "That is already the current salary."))
        self.ask({"new_amount": "3500", "effective_from": self.today.isoformat()})
        twice = self.ask({"new_amount": "3600", "effective_from": self.today.isoformat()})
        self.assertEqual((twice.status_code, _json(twice)["error"]), (409, "refused"))
        self.assertEqual(SalaryChangeRequest.objects.count(), 1)

    def test_the_forms_rules_are_the_rules(self):
        for values, field in (({"effective_from": self.today.isoformat()}, "new_amount"), ({"new_amount": "-5", "effective_from": self.today.isoformat()}, "new_amount"),
                              ({"new_amount": "abc", "effective_from": "x"}, "new_amount"), ({"new_amount": "100", "effective_from": "x"}, "effective_from")):
            answer = self.ask(values)
            self.assertEqual((answer.status_code, field in _json(answer)["errors"]), (400, True), values)
        self.assertEqual(self.ask({"new_amount": "1", "effective_from": self.today.isoformat(), "status": "approved"}).status_code, 400)
        self.assertFalse(SalaryChangeRequest.objects.exists())

    def test_a_request_is_for_somebody_who_is_there_and_active(self):
        gone = User.objects.create_user("person_gone", password="pw", role="translator", is_active=False)
        self.assertEqual(self.post(self.hr, REQUEST_NEW, {"user": 99999999, "values": {}}).status_code, 404)
        self.assertEqual(self.ask({"new_amount": "1", "effective_from": self.today.isoformat()}, user=gone).status_code, 404)
        for body in ({"values": {}}, {"user": "3", "values": {}}, {"user": True, "values": {}}, {"user": self.tr.pk, "values": []}):
            self.assertEqual(self.post(self.hr, REQUEST_NEW, body).status_code, 400, body)

    def test_the_owner_approves_and_the_salary_record_is_written(self):
        self.ask({"new_amount": "3500", "effective_from": self.today.isoformat(), "reason": "Raise"})
        row = SalaryChangeRequest.objects.get()
        self.assertEqual(self.post(self.admin, REQUEST_DECIDE, {}, [row.pk, "approve"]).status_code, 200)
        row.refresh_from_db()
        self.assertEqual((row.status, row.decided_by), (ApprovalStatus.APPROVED, self.admin))
        self.assertEqual(SalaryRecord.amount_on(self.tr, self.today), Decimal("3500.00"))
        self.assertTrue(AuditLog.objects.filter(action="salary.approve", actor=self.admin).exists())
        decided = _json(self.read(REQUESTS))["decided"][0]
        self.assertEqual((decided["status"], decided["decided_by"]), ("approved", self.admin.short_name))

    def test_the_owner_rejects_with_a_note_and_the_salary_stays(self):
        self.ask({"new_amount": "3500", "effective_from": self.today.isoformat()})
        row = SalaryChangeRequest.objects.get()
        self.post(self.admin, REQUEST_DECIDE, {"note": "Not now"}, [row.pk, "reject"])
        row.refresh_from_db()
        self.assertEqual((row.status, row.decision_note), (ApprovalStatus.REJECTED, "Not now"))
        self.assertEqual(SalaryRecord.amount_on(self.tr, self.today), Decimal("3000.00"))

    def test_a_request_that_was_decided_is_not_decided_again_and_the_inputs_are_checked(self):
        self.ask({"new_amount": "3500", "effective_from": self.today.isoformat()})
        row = SalaryChangeRequest.objects.get()
        self.post(self.admin, REQUEST_DECIDE, {}, [row.pk, "approve"])
        again = self.post(self.admin, REQUEST_DECIDE, {}, [row.pk, "reject"])
        self.assertEqual((again.status_code, _json(again)["error"]), (409, "refused"))
        self.assertEqual(SalaryRecord.objects.filter(user=self.tr).count(), 2)
        self.assertEqual(self.post(self.admin, REQUEST_DECIDE, {}, [row.pk, "pay"]).status_code, 404)
        self.assertEqual(self.post(self.admin, REQUEST_DECIDE, {}, [999999, "approve"]).status_code, 404)
        for note in (5, "x" * 251):
            self.assertEqual(self.post(self.admin, REQUEST_DECIDE, {"note": note}, [row.pk, "reject"]).status_code, 400, note)

    def test_the_page_says_who_may_decide(self):
        self.assertFalse(_json(self.read(REQUESTS))["can"]["decide"])
        self.assertTrue(_json(self.read(REQUESTS, self.admin))["can"]["decide"])


class PlanTests(_People):
    def save(self, values, which=None, who=None):
        body = {"values": values}
        if which is not None:
            body["id"] = which
        return self.post(who or self.admin, PLAN_SAVE, body)

    def test_the_plans_are_listed_with_who_is_on_each_and_the_company_numbers(self):
        plan = SalaryPlan.objects.create(name="Plan A", note="Senior", daily_target_words=2000, fixed_allowance=Decimal("150.00"))
        User.objects.filter(pk=self.tr.pk).update(salary_plan=plan)
        body = _json(self.read(PLANS, self.admin))
        row = body["rows"][0]
        self.assertEqual((row["name"], row["members"], row["overrides"], row["fixed_allowance"], row["extra_word_rate"]), ("Plan A", 1, ["daily_target_words"], "150.00", None))
        fields = {one["name"]: one for one in body["form"]}
        for name in ("daily_target_words", "monthly_target_words", "discipline_bonus", "target_bonus", "working_days_per_month", "monthly_leave_allowance"):
            self.assertTrue(fields[name]["hint_en"].startswith("Company: "), name)
            self.assertTrue(fields[name]["hint_ar"].startswith("الشركة: "), name)
        self.assertNotIn("hint_en", fields["name"])
        self.assertGreaterEqual(body["unassigned"], 0)

    def test_the_form_starts_blank_or_from_the_plan_being_changed(self):
        plan = SalaryPlan.objects.create(name="Plan A", daily_target_words=2000)
        blank = _json(self.read(PLANS, self.admin))
        self.assertEqual(blank["editing"], None)
        edited = _json(self.read(PLANS, self.admin, edit=plan.pk))
        fields = {one["name"]: one for one in edited["form"]}
        self.assertEqual((edited["editing"], fields["name"]["value"], fields["daily_target_words"]["value"]), (plan.pk, "Plan A", 2000))
        self.assertEqual((fields["daily_target_words"]["label_ar"], fields["extra_word_rate"]["hint_en"]), ("التارجت اليومي", "Blank keeps the bonus bands."))
        self.assertEqual(_json(self.read(PLANS, self.admin, edit="abc"))["editing"], None)

    def test_a_plan_is_added_with_the_admin_written_on_it_and_a_trail(self):
        answer = self.save({"name": "Plan B", "monthly_target_words": "50000", "extra_word_rate": "0.0500"})
        self.assertEqual(answer.status_code, 200)
        plan = SalaryPlan.objects.get(name="Plan B")
        self.assertEqual((plan.created_by, plan.monthly_target_words, plan.extra_word_rate, plan.is_active), (self.admin, 50000, Decimal("0.0500"), True))
        self.assertTrue(AuditLog.objects.filter(action="salary.plan.save", actor=self.admin).exists())

    def test_a_plan_is_changed_by_the_boxes_that_were_sent(self):
        plan = SalaryPlan.objects.create(name="Plan A", daily_target_words=2000, note="keep")
        self.save({"daily_target_words": "2500"}, plan.pk)
        plan.refresh_from_db()
        self.assertEqual((plan.daily_target_words, plan.note, plan.name), (2500, "keep", "Plan A"))
        self.save({"daily_target_words": ""}, plan.pk)
        plan.refresh_from_db()
        self.assertIsNone(plan.daily_target_words)

    def test_the_forms_rules_are_the_rules(self):
        SalaryPlan.objects.create(name="Plan A")
        for values, field in (({"name": "Plan A"}, "name"), ({}, "name"), ({"name": "X", "monthly_target_words": "-1"}, "monthly_target_words")):
            answer = self.save(values)
            self.assertEqual((answer.status_code, field in _json(answer)["errors"]), (400, True), values)
        self.assertEqual(self.save({"name": "X", "id": 3}).status_code, 400)
        self.assertEqual(SalaryPlan.objects.count(), 1)

    def test_a_plan_that_is_not_there_is_not_there_and_an_id_must_be_a_number(self):
        self.assertEqual(self.save({"name": "x"}, 999999).status_code, 404)
        for body in ({"id": "2", "values": {}}, {"id": True, "values": {}}, {"id": 0, "values": {}}, {"values": []}):
            self.assertEqual(self.post(self.admin, PLAN_SAVE, body).status_code, 400, body)

    def test_hr_cannot_even_read_them(self):
        self.assertEqual(self.read(PLANS).status_code, 403)
        self.assertEqual(self.save({"name": "Sneaky"}, who=self.hr).status_code, 403)
        self.assertFalse(SalaryPlan.objects.filter(name="Sneaky").exists())

    def test_the_number_of_queries_does_not_grow_with_the_plans(self):
        from django.db import connection
        from django.test.utils import CaptureQueriesContext

        def queries():
            with CaptureQueriesContext(connection) as seen:
                self.read(PLANS, self.admin)
            return len(seen)

        SalaryPlan.objects.create(name="Plan 0")
        queries()
        few = queries()
        for number in range(1, 8):
            SalaryPlan.objects.create(name=f"Plan {number}")
        self.assertEqual(queries(), few)


class HandOnTests(_People):
    def setUp(self):
        super().setUp()
        self.switch(roles=["hr", "admin"])

    def classic(self, name, args=None, who=None, **query):
        browser = DjangoClient()
        browser.force_login(who or self.hr)
        return browser.get(reverse(f"dashboard:{name}", args=args), query)

    def test_each_page_is_handed_on_with_what_it_carries(self):
        for name, args, path, query, kept in (
            ("hr_employees", None, "/app/hr/employees", {"department": str(self.dept.pk), "status": "probation"}, f"department={self.dept.pk}"),
            ("hr_employee", [self.tr.pk], f"/app/hr/employees/{self.tr.pk}", {}, ""),
            ("hr_probation", None, "/app/hr/probation", {"state": "due"}, "state=due"),
            ("hr_performance", None, "/app/hr/performance", {"year": "2026", "month": "9", "user": str(self.tr.pk)}, "period=2026-9"),
            ("hr_complaints", None, "/app/hr/complaints", {"translator": str(self.tr.pk)}, f"translator={self.tr.pk}"),
            ("hr_salary_requests", None, "/app/hr/salary-requests", {"user": str(self.tr.pk)}, f"user={self.tr.pk}"),
        ):
            answer = self.classic(name, args, **query)
            self.assertEqual(answer.status_code, 302, name)
            self.assertTrue(answer["Location"].startswith(path), answer["Location"])
            self.assertIn(kept, answer["Location"])

    def test_the_old_way_back_to_the_classic_page_is_gone_and_the_flag_holder_is_handed_on_with_everybody_else(self):
        for name in ("hr_employees", "hr_probation", "hr_performance", "hr_complaints", "hr_salary_requests"):
            self.assertEqual(self.classic(name, classic=1).status_code, 302, name)
        self.assertEqual(self.classic("hr_probation", who=self.flagged).status_code, 302)


class IncentiveTests(_People):
    """The incentive: a sum the owner types by hand, added to a person's pay every month (07/10/2026)."""

    def set(self, who, body, pk=None):
        return self.post(who, EMP_INCENTIVE, body, [pk or self.tr.pk])

    def file(self, who):
        return _json(self.read(EMPLOYEE, who, [self.tr.pk]))

    def test_the_admin_sets_it_and_it_is_in_the_file_and_the_trail(self):
        answer = self.set(self.admin, {"amount": "750.50"})
        self.assertEqual((answer.status_code, _json(answer)["incentive"]), (200, "750.50"))
        self.tr.refresh_from_db()
        self.assertEqual(self.tr.incentive, Decimal("750.50"))
        body = self.file(self.admin)
        self.assertEqual((body["incentive"], body["can"]["incentive"]), ("750.50", True))
        log = AuditLog.objects.get(action="salary.incentive", actor=self.admin)
        self.assertEqual(log.detail, "0.00 -> 750.50")

    def test_a_whole_number_and_a_number_are_taken_too_and_zero_takes_it_off(self):
        for given, kept in (("500", "500.00"), (300, "300.00"), ("0", "0.00")):
            self.assertEqual(self.set(self.admin, {"amount": given}).status_code, 200, given)
            self.tr.refresh_from_db()
            self.assertEqual(str(self.tr.incentive), kept, given)

    def test_setting_what_is_there_already_writes_nothing_to_the_trail(self):
        self.set(self.admin, {"amount": "100"})
        self.set(self.admin, {"amount": "100.00"})
        self.assertEqual(AuditLog.objects.filter(action="salary.incentive").count(), 1)

    def test_money_is_the_owners_so_nobody_else_sets_it_or_is_told_what_it_is(self):
        self.set(self.admin, {"amount": "900"})
        for who in (self.hr, self.flagged, self.ops, self.tr, self.accounting):
            self.assertEqual(self.set(who, {"amount": "1"}).status_code, 403, who.username)
        self.tr.refresh_from_db()
        self.assertEqual(self.tr.incentive, Decimal("900.00"))
        body = self.file(self.hr)
        self.assertIsNone(body["incentive"])
        self.assertFalse(body["can"]["incentive"])
        self.assertNotIn(b"900", self.read(EMPLOYEE, self.hr, [self.tr.pk]).content)

    def test_what_is_not_an_amount_is_refused_and_nothing_changes(self):
        self.set(self.admin, {"amount": "100"})
        for bad in ("abc", "", "-5", "1.234", "NaN", "Infinity", "1e3", "100000000", True, None, [], {}, "1" * 30):
            answer = self.set(self.admin, {"amount": bad})
            self.assertEqual((answer.status_code, _json(answer)["error"]), (400, "bad_amount"), repr(bad))
        self.assertEqual(self.set(self.admin, {}).status_code, 400)
        self.tr.refresh_from_db()
        self.assertEqual(self.tr.incentive, Decimal("100.00"))

    def test_a_person_the_company_rules_do_not_bind_has_none(self):
        owner = self.admin
        answer = self.set(self.admin, {"amount": "5"}, pk=owner.pk)
        self.assertEqual((answer.status_code, _json(answer)["error"]), (400, "owner"))

    def test_a_person_who_is_not_there_is_not_there(self):
        self.assertEqual(self.set(self.admin, {"amount": "5"}, pk=999999).status_code, 404)
