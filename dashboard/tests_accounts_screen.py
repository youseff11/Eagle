"""The money screens in the new app: the month's sheet, a payslip, attendance and output, violations, salaries, the rules.

Accounting and the admin run the month, a translator reads their own payslip, and the rules are the admin's alone. What these
tests hold: nothing moves money on its own (a deduction needs a person, the bonuses need the admin, a locked month is never
computed again), a GET changes nothing, money is text, a payslip is never somebody else's, a deduction's reason does not carry
a client's name to people who may not know it, and the classic form decides what is valid.
"""

import json
from datetime import date, datetime, time, timedelta
from decimal import Decimal
from unittest import mock

from django.db import connection
from django.test import Client as DjangoClient
from django.test.utils import CaptureQueriesContext
from django.urls import reverse
from django.utils import timezone

from . import identity, newui, payroll
from .forms import PayrollSettingsForm, ViolationForm
from .models import (
    ApprovalStatus, AppSettings, AuditLog, PayrollLine, PayrollPeriod, PayrollSettings, ProductionTier, RatingEvent, Role,
    SalaryRecord, Task, TaskStatus, User, Violation, WordCountState, WorkDay,
)
from .payroll_texts import SECTIONS as RULE_SECTIONS
from .payroll_texts import TEXTS as RULE_TEXTS
from .tests_admin_screen import _Admin
from .tests_api_v1 import CLIENT_NAME, _json

OVERVIEW = "dashboard:v1_accounts_overview"
RECALC = "dashboard:v1_accounts_recalculate"
APPROVE = "dashboard:v1_accounts_period_approve"
LINE = "dashboard:v1_accounts_line"
BONUS = "dashboard:v1_accounts_line_bonus"
SHEET = "dashboard:v1_accounts_attendance"
REFRESH = "dashboard:v1_accounts_attendance_refresh"
DAY_SAVE = "dashboard:v1_accounts_attendance_save"
VIOLATIONS = "dashboard:v1_accounts_violations"
VIOLATION_NEW = "dashboard:v1_accounts_violation_create"
DECIDE = "dashboard:v1_accounts_violation_decide"
SALARY = "dashboard:v1_accounts_salary"
SALARY_SAVE = "dashboard:v1_accounts_salary_save"
RULES = "dashboard:v1_accounts_rules"
RULES_SAVE = "dashboard:v1_accounts_rules_save"
TIER_ADD = "dashboard:v1_accounts_tier_add"
TIER_DELETE = "dashboard:v1_accounts_tier_delete"


class _Accounts(_Admin):
    def setUp(self):
        super().setUp()
        self.today = timezone.localdate()
        self.period_text = f"{self.today.year}-{self.today.month}"
        SalaryRecord.objects.create(user=self.tr, amount=Decimal("3000.00"), effective_from=date(2020, 1, 1), created_by=self.admin)

    def post(self, user, name, body, args=None):
        browser = DjangoClient()
        if user is not None:
            browser.force_login(user)
        return browser.post(reverse(name, args=args), json.dumps(body), content_type="application/json")

    def switch(self, key="accounts", roles=(), users=()):
        conf = AppSettings.load()
        conf.save()

    def run_month(self):
        return payroll.compute_period(self.today.year, self.today.month, actor=self.admin)

    def line_of(self, person=None):
        self.run_month()
        return PayrollLine.objects.get(user=person or self.tr, period__year=self.today.year, period__month=self.today.month)

    def violation(self, **over):
        values = {"user": self.tr, "date": self.today, "kind": "quality", "penalty_days": Decimal("1.00"), "reason": "A mistake"}
        values.update(over)
        return Violation.objects.create(**values)


class DoorMatrixTests(_Accounts):
    def setUp(self):
        super().setUp()
        self.line = self.line_of()
        self.violation_row = self.violation()

    def money_doors(self):
        """Open to Accounting and the admin."""
        return [
            ("GET", OVERVIEW, None), ("POST", RECALC, None), ("POST", APPROVE, [self.line.period_id]),
            ("GET", SHEET, None), ("POST", REFRESH, None), ("POST", DAY_SAVE, None),
            ("GET", VIOLATIONS, None), ("POST", VIOLATION_NEW, None), ("POST", DECIDE, [self.violation_row.pk, "approve"]),
            ("GET", SALARY, [self.tr.pk]),
        ]

    def admin_doors(self):
        """The admin's alone."""
        return [
            ("POST", BONUS, [self.line.pk]), ("GET", RULES, None), ("POST", RULES_SAVE, None), ("POST", TIER_ADD, None),
            ("POST", TIER_DELETE, [999999]), ("POST", SALARY_SAVE, [self.tr.pk]),
        ]

    def call(self, user, method, name, args):
        browser = DjangoClient()
        if user is not None:
            browser.force_login(user)
        url = reverse(name, args=args)
        return browser.get(url) if method == "GET" else browser.post(url, "{}", content_type="application/json")

    def test_accounting_and_the_admin_are_answered_and_nobody_else(self):
        for method, name, args in self.money_doors():
            for user in (self.ops, self.lead, self.tr, self.hr, self.reviewer, self.sales):
                denied = self.call(user, method, name, args)
                self.assertEqual((denied.status_code, _json(denied)), (403, {"ok": False, "error": "forbidden"}), (name, user.username))
            self.assertEqual(self.call(None, method, name, args).status_code, 401, name)
            for user in (self.admin, self.accounting):
                self.assertNotIn(self.call(user, method, name, args).status_code, (401, 403), (name, user.username))

    def test_the_rules_and_the_bonuses_are_the_admins_alone(self):
        for method, name, args in self.admin_doors():
            for user in (self.accounting, self.ops, self.lead, self.tr, self.hr, self.reviewer, self.sales):
                denied = self.call(user, method, name, args)
                self.assertEqual((denied.status_code, _json(denied)), (403, {"ok": False, "error": "forbidden"}), (name, user.username))
            self.assertEqual(self.call(None, method, name, args).status_code, 401, name)
            self.assertNotIn(self.call(self.admin, method, name, args).status_code, (401, 403), name)

    def test_the_wrong_method_is_a_405_that_says_what_is_allowed(self):
        for method, name, args in self.money_doors() + self.admin_doors():
            answer = self.call(self.admin, "POST" if method == "GET" else "GET", name, args)
            self.assertEqual((answer.status_code, answer["Allow"]), (405, method), name)

    def test_every_answer_is_private(self):
        for method, name, args in self.money_doors() + self.admin_doors():
            self.assertEqual(self.call(self.admin, method, name, args)["Cache-Control"], "private, no-store", name)

    def test_a_refusal_never_carries_money(self):
        for method, name, args in self.money_doors() + self.admin_doors():
            text = self.call(self.tr, method, name, args).content.decode("utf-8")
            self.assertNotIn("3000", text, name)


class OverviewTests(_Accounts):
    def test_a_month_that_was_never_run_is_empty_and_says_so(self):
        body = _json(self.get(self.admin, OVERVIEW))
        self.assertEqual((body["period"], body["totals"], body["lines"]), (None, None, []))
        self.assertEqual((body["year"], body["month"]), (self.today.year, self.today.month))
        self.assertEqual(len(body["periods"]), 13)

    def test_a_month_is_asked_for_by_name_and_a_typo_is_an_error_not_this_month(self):
        body = _json(self.get(self.accounting, OVERVIEW, period="2026-03"))
        self.assertEqual((body["year"], body["month"]), (2026, 3))
        for bad in ("2026-13", "26-3", "x", "2026", "2026-3-1", "1999-01"):
            answer = self.get(self.accounting, OVERVIEW, period=bad)
            self.assertEqual((answer.status_code, _json(answer)["error"]), (400, "bad_period"), bad)

    def test_a_month_that_was_run_has_its_lines_totals_and_status_with_money_as_text(self):
        line = self.line_of()
        body = _json(self.get(self.accounting, OVERVIEW))
        self.assertEqual(body["period"]["label"], f"{self.today.year}-{self.today.month:02d}")
        self.assertEqual(body["period"]["status"]["value"], "draft")
        row = next(one for one in body["lines"] if one["id"] == line.pk)
        self.assertEqual(row["user"]["id"], self.tr.pk)
        self.assertEqual(row["base_salary"], "3000.00")
        self.assertIsInstance(row["net"], str)
        self.assertEqual(row["net"], str(line.net))
        self.assertEqual(set(body["totals"]), {"net", "words", "deductions", "alerts"})
        self.assertIsInstance(body["totals"]["net"], str)

    def test_a_translator_with_no_salary_is_named(self):
        other = User.objects.create_user("person_translator_two", password="pw", role=Role.TRANSLATOR, team_lead=self.lead)
        ids = {row["id"] for row in _json(self.get(self.admin, OVERVIEW))["missing_salary"]}
        self.assertEqual(ids, {other.pk})

    def test_a_job_whose_words_nobody_settled_is_listed_for_the_month(self):
        Task.objects.filter(pk=self.task.pk).update(
            translated_at=timezone.now(), word_count_state=WordCountState.REVIEW, status=TaskStatus.DELIVERED,
        )
        rows = _json(self.get(self.admin, OVERVIEW))["unsettled_tasks"]
        self.assertEqual(rows, [{"code": self.task.code, "translator": self.tr.short_name}])

    def test_only_the_admin_is_told_they_may_open_a_payslip_or_a_task(self):
        self.assertEqual(_json(self.get(self.admin, OVERVIEW))["can"], {"line": True, "task": True})
        self.assertEqual(_json(self.get(self.accounting, OVERVIEW))["can"], {"line": False, "task": False})

    def test_a_deductions_reason_hides_the_client_from_who_may_not_know_it_and_not_from_the_admin(self):
        self.violation(task=self.task, reason=f"Complaint from {CLIENT_NAME} about page 3")
        for viewer, hides in ((self.accounting, True), (self.admin, False)):
            text = self.get(viewer, OVERVIEW).content.decode("utf-8")
            self.assertEqual(CLIENT_NAME in text, not hides, viewer.username)
        accounting_row = _json(self.get(self.accounting, OVERVIEW))["pending_violations"][0]
        self.assertIn(self.client_obj.code, accounting_row["reason"])

    def test_accounting_with_the_identity_grant_reads_the_reason_as_written(self):
        self.accounting.client_identity_access = True
        self.accounting.save()
        self.violation(task=self.task, reason=f"Complaint from {CLIENT_NAME}")
        self.assertIn(CLIENT_NAME, _json(self.get(self.accounting, OVERVIEW))["pending_violations"][0]["reason"])

    def test_a_get_changes_nothing(self):
        self.line_of()
        before = (PayrollLine.objects.count(), PayrollPeriod.objects.count(), AuditLog.objects.count(), WorkDay.objects.count())
        self.get(self.admin, OVERVIEW)
        self.get(self.accounting, OVERVIEW, period="2025-01")
        self.assertEqual((PayrollLine.objects.count(), PayrollPeriod.objects.count(), AuditLog.objects.count(), WorkDay.objects.count()), before)

    def test_the_number_of_questions_does_not_grow_with_the_lines_and_the_violations(self):
        self.line_of()
        self.violation()

        def questions():
            with CaptureQueriesContext(connection) as seen:
                self.assertEqual(self.get(self.admin, OVERVIEW).status_code, 200)
            return len(seen)

        few = questions()
        for index in range(8):
            person = User.objects.create_user(f"person_extra_{index}", password="pw", role=Role.TRANSLATOR, team_lead=self.lead)
            SalaryRecord.objects.create(user=person, amount=Decimal("1000"), effective_from=date(2020, 1, 1))
            self.violation(user=person, task=self.task, reason=f"r{index}")
        self.run_month()
        self.assertEqual(questions(), few)


class RunTheMonthTests(_Accounts):
    def test_running_a_month_makes_its_lines(self):
        answer = self.post(self.accounting, RECALC, {"period": self.period_text})
        self.assertEqual((answer.status_code, _json(answer)["ok"]), (200, True))
        self.assertTrue(PayrollLine.objects.filter(user=self.tr, period__year=self.today.year).exists())
        self.assertTrue(AuditLog.objects.filter(action="payroll.compute", actor=self.accounting).exists())

    def test_a_locked_month_is_not_run_again_and_says_so(self):
        period = self.run_month()
        period.status = "locked"
        period.save()
        before = PayrollLine.objects.get(user=self.tr, period=period).computed_at
        answer = self.post(self.accounting, RECALC, {"period": self.period_text})
        body = _json(answer)
        self.assertEqual((answer.status_code, body["error"], bool(body["message"])), (409, "period_locked", True))
        self.assertEqual(PayrollLine.objects.get(user=self.tr, period=period).computed_at, before)

    def test_a_period_that_is_not_one_is_refused(self):
        for body in ({"period": "2026-13"}, {"period": "x"}, {}, {"period": 5}):
            self.assertEqual(self.post(self.accounting, RECALC, body).status_code, 400, body)
        self.assertFalse(PayrollPeriod.objects.exists())

    def test_a_deduction_is_not_applied_by_running_the_month(self):
        mine = self.violation()
        line = self.line_of()
        self.assertEqual(line.deductions, Decimal("0.00"))
        mine.refresh_from_db()
        self.assertEqual(mine.status, ApprovalStatus.PENDING)
        # Whatever the engine proposes itself waits for a person too.
        self.assertEqual(Violation.objects.exclude(status=ApprovalStatus.PENDING).count(), 0)


class ApproveAndLockTests(_Accounts):
    def setUp(self):
        super().setUp()
        self.period = self.run_month()

    def test_a_draft_is_approved_then_locked(self):
        answer = self.post(self.accounting, APPROVE, {}, [self.period.pk])
        self.assertEqual((answer.status_code, _json(answer)["period"]["status"]["value"]), (200, "approved"))
        answer = self.post(self.accounting, APPROVE, {"lock": True}, [self.period.pk])
        self.assertEqual(_json(answer)["period"]["status"]["value"], "locked")
        self.period.refresh_from_db()
        self.assertEqual((self.period.status, self.period.approved_by_id), ("locked", self.accounting.pk))
        self.assertTrue(AuditLog.objects.filter(action="payroll.period.locked", target=self.period.label).exists())

    def test_a_locked_month_cannot_be_approved_or_locked_again(self):
        self.post(self.accounting, APPROVE, {"lock": True}, [self.period.pk])
        answer = self.post(self.admin, APPROVE, {}, [self.period.pk])
        self.assertEqual((answer.status_code, _json(answer)["error"]), (409, "period_locked"))
        self.period.refresh_from_db()
        self.assertEqual(self.period.status, "locked")

    def test_lock_has_to_be_a_real_boolean(self):
        for lock in ("1", 1, "true", None):
            self.assertEqual(self.post(self.accounting, APPROVE, {"lock": lock}, [self.period.pk]).status_code, 400, lock)
        self.period.refresh_from_db()
        self.assertEqual(self.period.status, "draft")

    def test_a_month_that_does_not_exist_is_a_404(self):
        self.assertEqual(self.post(self.accounting, APPROVE, {}, [999999]).status_code, 404)


class PayslipTests(_Accounts):
    def setUp(self):
        super().setUp()
        self.line = self.line_of()

    def test_the_admin_reads_any_payslip_in_full(self):
        body = _json(self.get(self.admin, LINE, [self.line.pk]))
        row = body["line"]
        for key in ("base_salary", "day_value", "production_bonus", "gross", "net", "deductions", "overtime_bonus"):
            self.assertIsInstance(row[key], str, key)
        self.assertEqual((row["id"], row["net"], row["label"]), (self.line.pk, str(self.line.net), self.line.period.label))
        self.assertEqual(set(body["conf"]), {"monthly_leave_allowance", "discipline_bonus", "target_bonus"})
        self.assertEqual(body["can"]["salary"], True)

    def test_a_translator_reads_their_own_and_nobody_elses(self):
        self.assertEqual(self.get(self.tr, LINE, [self.line.pk]).status_code, 200)
        other = User.objects.create_user("person_translator_two", password="pw", role=Role.TRANSLATOR, team_lead=self.lead)
        SalaryRecord.objects.create(user=other, amount=Decimal("5000"), effective_from=date(2020, 1, 1))
        theirs = self.line_of(other)
        denied = self.get(self.tr, LINE, [theirs.pk])
        self.assertEqual(denied.status_code, 404)
        self.assertNotIn("5000", denied.content.decode("utf-8"))
        self.assertTrue(AuditLog.objects.filter(action=identity.ACCESS_DENIED, actor=self.tr, detail__contains="payslip").exists())

    def test_everybody_else_gets_a_404_and_a_row_in_the_log_even_accounting_as_the_classic_page_does(self):
        before = AuditLog.objects.filter(action=identity.ACCESS_DENIED).count()
        for user in (self.accounting, self.ops, self.lead, self.hr, self.reviewer, self.sales):
            self.assertEqual(self.get(user, LINE, [self.line.pk]).status_code, 404, user.username)
        self.assertEqual(AuditLog.objects.filter(action=identity.ACCESS_DENIED).count(), before + 6)
        self.assertEqual(self.get(None, LINE, [self.line.pk]).status_code, 401)

    def test_a_translator_is_told_they_may_not_open_the_salary_history_or_release_bonuses(self):
        self.assertEqual(_json(self.get(self.tr, LINE, [self.line.pk]))["can"], {"salary": False, "release": False})

    def test_the_days_and_the_deductions_come_from_what_the_line_froze(self):
        line = self.line
        line.breakdown = {
            "days": [{"date": "2026-10-01", "status": "present", "secondary": True, "difficult": False, "words": 1200, "target": 1000, "bonus": "50.00"}],
            "deductions": [{"date": "2026-10-02", "kind": "quality", "reason": "Error", "days": "1.00", "amount": "100.00"}],
            "pending": [{"date": "2026-10-03", "kind": "unexcused", "reason": "Absent", "days": "1.00", "amount": "100.00"}],
        }
        line.save()
        body = _json(self.get(self.admin, LINE, [line.pk]))
        self.assertEqual(body["days"], [{
            "date": "2026-10-01", "status": {"value": "present", "tone": "ok", "ar": "حاضر", "en": "Present"},
            "secondary": True, "difficult": False, "words": 1200, "target": 1000, "bonus": "50.00",
        }])
        self.assertEqual([(row["status"], row["kind"]["value"], row["amount"]) for row in body["deductions"]], [("applied", "quality", "100.00"), ("pending", "unexcused", "100.00")])
        self.assertEqual(body["deductions"][0]["kind"]["en"], "Translation error")

    def test_a_payslip_that_does_not_exist_is_a_404(self):
        self.assertEqual(self.get(self.admin, LINE, [999999]).status_code, 404)

    def test_a_get_changes_nothing(self):
        before = (PayrollLine.objects.count(), AuditLog.objects.filter(action__startswith="payroll").count())
        self.get(self.admin, LINE, [self.line.pk])
        self.assertEqual((PayrollLine.objects.count(), AuditLog.objects.filter(action__startswith="payroll").count()), before)


class BonusTests(_Accounts):
    def setUp(self):
        super().setUp()
        self.line = self.line_of()
        PayrollLine.objects.filter(pk=self.line.pk).update(discipline_bonus_earned=True, target_bonus_earned=True, bonuses_approved=False)
        conf = PayrollSettings.load()
        conf.discipline_bonus, conf.target_bonus = Decimal("100.00"), Decimal("200.00")
        conf.save()

    def test_the_admin_releases_the_two_bonuses_and_the_net_rises_by_them(self):
        before = PayrollLine.objects.get(pk=self.line.pk).net
        answer = self.post(self.admin, BONUS, {}, [self.line.pk])
        self.assertEqual((answer.status_code, _json(answer)["ok"]), (200, True))
        after = PayrollLine.objects.get(pk=self.line.pk)
        self.assertEqual((after.bonuses_approved, after.net - before), (True, Decimal("300.00")))
        self.assertTrue(AuditLog.objects.filter(action="payroll.bonus.approve", actor=self.admin).exists())

    def test_accounting_cannot_release_them(self):
        self.assertEqual(self.post(self.accounting, BONUS, {}, [self.line.pk]).status_code, 403)
        self.assertFalse(PayrollLine.objects.get(pk=self.line.pk).bonuses_approved)

    def test_they_are_released_once(self):
        self.post(self.admin, BONUS, {}, [self.line.pk])
        net = PayrollLine.objects.get(pk=self.line.pk).net
        answer = self.post(self.admin, BONUS, {}, [self.line.pk])
        self.assertEqual((answer.status_code, _json(answer)["error"]), (409, "already_released"))
        self.assertEqual(PayrollLine.objects.get(pk=self.line.pk).net, net)

    def test_a_locked_month_releases_nothing(self):
        PayrollPeriod.objects.filter(pk=self.line.period_id).update(status="locked")
        answer = self.post(self.admin, BONUS, {}, [self.line.pk])
        self.assertEqual((answer.status_code, _json(answer)["error"]), (409, "period_locked"))
        self.assertFalse(PayrollLine.objects.get(pk=self.line.pk).bonuses_approved)

    def test_the_payslip_says_whether_there_is_anything_to_release(self):
        self.assertTrue(_json(self.get(self.admin, LINE, [self.line.pk]))["can"]["release"])
        self.post(self.admin, BONUS, {}, [self.line.pk])
        self.assertFalse(_json(self.get(self.admin, LINE, [self.line.pk]))["can"]["release"])


class AttendanceSheetTests(_Accounts):
    def test_it_names_the_translators_and_opens_on_the_first_when_none_is_asked_for(self):
        body = _json(self.get(self.accounting, SHEET))
        self.assertEqual([one["id"] for one in body["people"]], [self.tr.pk])
        self.assertEqual(body["person"]["id"], self.tr.pk)

    def test_a_person_who_is_not_a_translator_is_no_one_here(self):
        body = _json(self.get(self.accounting, SHEET, user=self.ops.pk))
        self.assertIsNone(body["person"])
        self.assertEqual(body["days"], [])

    def test_a_user_that_is_not_an_id_is_refused(self):
        for bad in ("x", "1.5", "-1", "1; drop", "²"):
            self.assertEqual(self.get(self.accounting, SHEET, user=bad).status_code, 400, bad)

    def test_the_days_of_the_month_carry_their_status_times_and_notes(self):
        WorkDay.objects.create(user=self.tr, date=self.today, status="unexcused", absence_reason="No call", note="Phone off", words=0)
        WorkDay.objects.create(user=self.tr, date=self.today - timedelta(days=400), status="present", words=999)
        day = _json(self.get(self.accounting, SHEET, period=self.period_text))["days"][0]
        self.assertEqual((day["date"], day["status"]["value"], day["absence_reason"], day["note"]), (self.today.isoformat(), "unexcused", "No call", "Phone off"))
        self.assertEqual(len(_json(self.get(self.accounting, SHEET, period=self.period_text))["days"]), 1)

    def test_the_words_and_the_leave_used_are_the_working_days_and_the_leave_days(self):
        WorkDay.objects.create(user=self.tr, date=self.today.replace(day=1), status="present", words=700)
        WorkDay.objects.create(user=self.tr, date=self.today.replace(day=2), status="leave", words=500)
        body = _json(self.get(self.accounting, SHEET, period=self.period_text))
        self.assertEqual((body["words"], body["leave_used"]), (700, 1))

    def test_a_day_under_the_floor_is_marked(self):
        conf = PayrollSettings.load()
        WorkDay.objects.create(user=self.tr, date=self.today.replace(day=1), status="present", words=max(conf.daily_target_words - 1, 0))
        self.assertTrue(_json(self.get(self.accounting, SHEET, period=self.period_text))["days"][0]["under_floor"])

    def test_the_form_to_record_a_day_is_the_classic_form(self):
        names = [field["name"] for field in _json(self.get(self.accounting, SHEET))["form"]]
        self.assertEqual(names, ["date", "status", "check_in", "check_out", "late_minutes", "early_leave_minutes", "words", "is_secondary_language", "difficult_file", "absence_reason", "note"])

    def test_a_get_does_not_refresh_the_words_from_the_job_log(self):
        day = WorkDay.objects.create(user=self.tr, date=self.today, status="present", words=0)
        Task.objects.filter(pk=self.task.pk).update(
            translator=self.tr, status=TaskStatus.DELIVERED, translated_at=timezone.now(), word_count=777,
        )
        self.get(self.accounting, SHEET, period=self.period_text)
        day.refresh_from_db()
        self.assertEqual(day.words, 0)

    def test_the_refresh_is_its_own_post_and_does_what_the_classic_sheet_did_on_opening(self):
        Task.objects.filter(pk=self.task.pk).update(
            translator=self.tr, status=TaskStatus.DELIVERED, translated_at=timezone.now(), word_count=777,
        )
        answer = self.post(self.accounting, REFRESH, {"user": self.tr.pk, "period": self.period_text})
        self.assertEqual((answer.status_code, _json(answer)["ok"]), (200, True))
        self.assertEqual(WorkDay.objects.get(user=self.tr, date=timezone.localdate()).words, 777)

    def test_the_refresh_names_a_translator_and_a_month(self):
        for body in ({}, {"user": "1", "period": self.period_text}, {"user": True, "period": self.period_text}, {"user": self.tr.pk}, {"user": self.tr.pk, "period": "x"}):
            self.assertEqual(self.post(self.accounting, REFRESH, body).status_code, 400, body)
        self.assertEqual(self.post(self.accounting, REFRESH, {"user": self.ops.pk, "period": self.period_text}).status_code, 404)


class RecordADayTests(_Accounts):
    def save(self, **values):
        base = {"date": self.today.isoformat(), "status": "present"}
        base.update(values)
        return self.post(self.accounting, DAY_SAVE, {"user": self.tr.pk, "values": base})

    def test_a_day_is_recorded_and_written_down(self):
        answer = self.save(words="1500", late_minutes="5", note="Fine")
        self.assertEqual((answer.status_code, _json(answer)["ok"]), (200, True))
        day = WorkDay.objects.get(user=self.tr, date=self.today)
        self.assertEqual((day.status, day.late_minutes, day.note), ("present", 5, "Fine"))
        row = AuditLog.objects.filter(action="workday.save").latest("pk")
        self.assertEqual((row.actor_id, row.target), (self.accounting.pk, f"{self.tr.username} {self.today}"))

    def test_a_second_save_for_the_same_date_edits_the_first(self):
        self.save(words="100")
        self.save(words="900", note="Corrected")
        self.assertEqual(WorkDay.objects.filter(user=self.tr, date=self.today).count(), 1)
        day = WorkDay.objects.get(user=self.tr, date=self.today)
        self.assertEqual((day.words, day.note), (900, "Corrected"))

    def test_a_box_left_out_keeps_what_the_day_already_holds(self):
        self.save(note="First")
        self.save(words="50")
        day = WorkDay.objects.get(user=self.tr, date=self.today)
        self.assertEqual((day.note, day.words), ("First", 50))

    def test_a_note_saved_on_a_day_with_real_punches_does_not_empty_them(self):
        stamp = timezone.make_aware(datetime.combine(self.today, time(9, 0)))
        WorkDay.objects.create(user=self.tr, date=self.today, status="present", check_in=stamp, check_out=stamp + timedelta(hours=8))
        self.save(note="Only a note")
        day = WorkDay.objects.get(user=self.tr, date=self.today)
        self.assertEqual(day.note, "Only a note")
        self.assertIsNotNone(day.check_in)
        self.assertIsNotNone(day.check_out)

    def test_the_times_are_cairo_time_and_do_not_move_when_the_day_is_saved_again(self):
        self.save(check_in=f"{self.today.isoformat()}T09:00", check_out=f"{self.today.isoformat()}T17:00")
        day = WorkDay.objects.get(user=self.tr, date=self.today)
        self.assertEqual(timezone.localtime(day.check_in).strftime("%H:%M"), "09:00")
        self.save(check_in=f"{self.today.isoformat()}T09:00", check_out=f"{self.today.isoformat()}T17:00")
        self.assertEqual(timezone.localtime(WorkDay.objects.get(user=self.tr, date=self.today).check_in).strftime("%H:%M"), "09:00")
        sheet = _json(self.get(self.accounting, SHEET, period=self.period_text))["days"][0]
        self.assertEqual(sheet["check_in"]["en"], "9:00 AM")
        self.assertEqual(sheet["check_out"]["ar"], "5:00 PM")

    def test_an_absence_needs_its_reason_and_nothing_is_saved_without_it(self):
        answer = self.save(status="unexcused")
        body = _json(answer)
        self.assertEqual((answer.status_code, body["error"], "absence_reason" in body["errors"]), (400, "invalid", True))
        self.assertFalse(WorkDay.objects.filter(user=self.tr).exists())

    def test_what_the_form_refuses_is_refused(self):
        for values in ({"date": ""}, {"date": "not a date"}, {"words": "-5"}, {"late_minutes": "abc"}, {"status": "teleported"}):
            self.assertEqual(self.save(**values).status_code, 400, values)

    def test_a_field_the_form_does_not_have_is_refused(self):
        for extra in ({"user": 1}, {"id": 5}, {"work_minutes": 9999}):
            answer = self.save(**extra)
            self.assertEqual((answer.status_code, _json(answer)["error"]), (400, "bad_body"), extra)

    def test_somebody_who_is_not_a_translator_has_no_days_here(self):
        answer = self.post(self.accounting, DAY_SAVE, {"user": self.ops.pk, "values": {"date": self.today.isoformat(), "status": "present"}})
        self.assertEqual(answer.status_code, 404)
        self.assertFalse(WorkDay.objects.exists())

    def test_the_person_has_to_be_named_with_a_real_id(self):
        for who in ("1", None, True, 0, -1, 1.5, [1]):
            self.assertEqual(self.post(self.accounting, DAY_SAVE, {"user": who, "values": {}}).status_code, 400, who)


class ViolationTests(_Accounts):
    def propose(self, **values):
        base = {"user": str(self.tr.pk), "date": self.today.isoformat(), "kind": "quality", "penalty_days": "1", "reason": "A mistake"}
        base.update(values)
        return self.post(self.accounting, VIOLATION_NEW, {"values": base})

    def test_the_lists_hold_what_waits_and_what_was_decided(self):
        waiting = self.violation()
        done = self.violation(status=ApprovalStatus.APPROVED, approved_by=self.admin)
        body = _json(self.get(self.accounting, VIOLATIONS))
        self.assertEqual([row["id"] for row in body["pending"]], [waiting.pk])
        self.assertEqual([(row["id"], row["decided_by"]) for row in body["decided"]], [(done.pk, self.admin.short_name)])
        self.assertEqual(body["pending"][0]["penalty_days"], "1.00")
        self.assertEqual(body["pending"][0]["kind"]["en"], "Translation error")

    def test_the_defaults_are_the_rules_numbers(self):
        conf = PayrollSettings.load()
        self.assertEqual(_json(self.get(self.accounting, VIOLATIONS))["conf"]["quality_penalty_days"], str(conf.quality_penalty_days))

    def test_the_decided_list_holds_every_decision_up_to_a_ceiling(self):
        for _ in range(65):
            self.violation(status=ApprovalStatus.APPROVED, approved_by=self.admin)
        self.assertEqual(len(_json(self.get(self.accounting, VIOLATIONS))["decided"]), 65)
        with mock.patch("dashboard.api_accounts.MAX_DECIDED", 10):
            self.assertEqual(len(_json(self.get(self.accounting, VIOLATIONS))["decided"]), 10)

    def star(self, **over):
        values = {"user": self.tr, "task": self.task, "delta": Decimal("-0.125"), "reason_en": "No response within 30s", "reason_ar": "لم يرد"}
        values.update(over)
        return RatingEvent.objects.create(**values)

    def test_star_penalties_are_listed_in_every_state_applied_ones_included(self):
        waiting = self.star()
        applied = self.star(decision=RatingEvent.Decision.CONFIRMED, decided_by=self.hr)
        forgiven = self.star(decision=RatingEvent.Decision.FORGIVEN, decided_by=self.admin)
        stars = _json(self.get(self.accounting, VIOLATIONS))["stars"]
        self.assertEqual({row["id"] for row in stars["rows"]}, {waiting.pk, applied.pk, forgiven.pk})
        self.assertEqual(stars["waiting"], 1)
        by_id = {row["id"]: row for row in stars["rows"]}
        self.assertEqual(by_id[applied.pk]["decision"]["value"], "confirmed")
        self.assertEqual(by_id[applied.pk]["decided_by"], self.hr.short_name)
        self.assertEqual(by_id[forgiven.pk]["decision"]["value"], "forgiven")
        self.assertEqual(by_id[waiting.pk]["task"], self.task.code)

    def test_a_decision_note_naming_the_client_is_masked_for_accounting_and_open_for_the_admin(self):
        self.star(decision=RatingEvent.Decision.FORGIVEN, decided_by=self.hr, decision_note=f"{CLIENT_NAME} complained, my mistake")
        accounting = json.dumps(_json(self.get(self.accounting, VIOLATIONS))["stars"])
        self.assertNotIn(CLIENT_NAME, accounting)
        self.assertIn(self.client_obj.code, accounting)
        self.assertIn(CLIENT_NAME, json.dumps(_json(self.get(self.admin, VIOLATIONS))["stars"]))

    def test_who_may_decide_a_star_penalty_is_told_to_the_page(self):
        self.star()
        accounting = _json(self.get(self.accounting, VIOLATIONS))["stars"]["can"]
        admin = _json(self.get(self.admin, VIOLATIONS))["stars"]["can"]
        self.assertEqual(accounting, {"decide": False, "change": False})
        self.assertEqual(admin, {"decide": True, "change": True})

    def test_a_star_penalty_applied_here_can_be_forgiven_by_the_admin_through_the_hr_door(self):
        event = self.star(decision=RatingEvent.Decision.CONFIRMED, decided_by=self.hr)
        self.tr.rating = Decimal("3.000")
        self.tr.save()
        answer = self.post(self.admin, "dashboard:v1_hr_penalty_decide", {}, [event.pk, "forgive"])
        self.assertEqual(answer.status_code, 200, answer.content)
        row = next(one for one in _json(self.get(self.admin, VIOLATIONS))["stars"]["rows"] if one["id"] == event.pk)
        self.assertEqual(row["decision"]["value"], "forgiven")
        self.tr.refresh_from_db()
        self.assertEqual(self.tr.rating, Decimal("3.125"))

    def test_a_deduction_is_proposed_and_waits_for_a_person(self):
        answer = self.propose()
        self.assertEqual((answer.status_code, _json(answer)["ok"]), (200, True))
        row = Violation.objects.get()
        self.assertEqual((row.status, row.created_by_id, row.user_id), (ApprovalStatus.PENDING, self.accounting.pk, self.tr.pk))
        self.assertTrue(AuditLog.objects.filter(action="violation.create", actor=self.accounting).exists())

    def test_a_deduction_can_be_tied_to_a_task_which_the_classic_form_never_allowed(self):
        answer = self.propose(task=str(self.task.pk))
        self.assertEqual(answer.status_code, 200, answer.content)
        self.assertEqual(Violation.objects.get().task_id, self.task.pk)

    def test_the_classic_form_takes_a_task_now_too(self):
        form = ViolationForm({"user": self.tr.pk, "task": self.task.pk, "date": self.today, "kind": "quality", "penalty_days": "1", "penalty_amount": "0", "reason": "x"})
        self.assertTrue(form.is_valid(), form.errors)

    def test_the_list_of_tasks_is_the_newest_two_hundred_by_code_and_never_a_title(self):
        for index in range(210):
            Task.objects.create(client=self.client_obj, title=f"Title {CLIENT_NAME} {index}", created_by=self.ops)
        field = next(one for one in _json(self.get(self.accounting, VIOLATIONS))["form"] if one["name"] == "task")
        self.assertEqual(len(field["choices"]), 201)
        self.assertEqual(field["choices"][0], {"value": "", "label": "---------"})
        text = json.dumps(field["choices"])
        self.assertNotIn(CLIENT_NAME, text)
        self.assertNotIn("Title", text)
        codes = {choice["label"] for choice in field["choices"][1:]}
        self.assertTrue(all(code.startswith("TSK-") for code in codes))

    def test_a_task_older_than_the_list_can_still_be_chosen(self):
        old = Task.objects.create(client=self.client_obj, title="Old", created_by=self.ops)
        for index in range(205):
            Task.objects.create(client=self.client_obj, title=f"n{index}", created_by=self.ops)
        self.assertEqual(self.propose(task=str(old.pk)).status_code, 200)

    def test_only_an_active_translator_can_be_charged(self):
        for who in (self.ops, self.lead):
            answer = self.propose(user=str(who.pk))
            self.assertEqual((answer.status_code, "user" in _json(answer)["errors"]), (400, True), who.username)
        self.tr.is_active = False
        self.tr.save()
        self.assertEqual(self.propose().status_code, 400)
        self.assertFalse(Violation.objects.exists())

    def test_a_deduction_needs_days_or_an_amount(self):
        answer = self.propose(penalty_days="", penalty_amount="")
        self.assertEqual((answer.status_code, "penalty_days" in _json(answer)["errors"]), (400, True))

    def test_approving_applies_it_to_nobody_until_the_month_is_run_and_is_written_down(self):
        row = self.violation()
        answer = self.post(self.accounting, DECIDE, {}, [row.pk, "approve"])
        self.assertEqual((answer.status_code, _json(answer)["ok"]), (200, True))
        row.refresh_from_db()
        self.assertEqual((row.status, row.approved_by_id), (ApprovalStatus.APPROVED, self.accounting.pk))
        self.assertTrue(AuditLog.objects.filter(action="violation.approve", target=f"{self.tr.username} {row.date}").exists())
        self.assertEqual(self.line_of().deductions, Decimal("0.00") + (Decimal("1.00") * self.line_of().day_value))

    def test_rejecting_costs_nobody_anything(self):
        row = self.violation()
        self.post(self.accounting, DECIDE, {}, [row.pk, "reject"])
        row.refresh_from_db()
        self.assertEqual(row.status, ApprovalStatus.REJECTED)
        self.assertEqual(self.line_of().deductions, Decimal("0.00"))

    def test_a_decided_deduction_is_not_decided_again_from_here(self):
        row = self.violation()
        self.post(self.accounting, DECIDE, {}, [row.pk, "approve"])
        answer = self.post(self.accounting, DECIDE, {}, [row.pk, "reject"])
        self.assertEqual((answer.status_code, _json(answer)["error"]), (409, "already_decided"))
        row.refresh_from_db()
        self.assertEqual(row.status, ApprovalStatus.APPROVED)

    def test_an_action_that_is_not_one_and_a_row_that_does_not_exist_are_404s(self):
        row = self.violation()
        self.assertEqual(self.post(self.accounting, DECIDE, {}, [row.pk, "delete"]).status_code, 404)
        self.assertEqual(self.post(self.accounting, DECIDE, {}, [999999, "approve"]).status_code, 404)
        row.refresh_from_db()
        self.assertEqual(row.status, ApprovalStatus.PENDING)

    def test_a_get_changes_nothing(self):
        self.violation()
        before = (Violation.objects.count(), AuditLog.objects.count())
        self.get(self.accounting, VIOLATIONS)
        self.assertEqual((Violation.objects.count(), AuditLog.objects.count()), before)


class SalaryTests(_Accounts):
    def test_the_history_and_the_computed_months(self):
        self.line_of()
        body = _json(self.get(self.accounting, SALARY, [self.tr.pk]))
        self.assertEqual(body["person"]["id"], self.tr.pk)
        self.assertEqual([(row["amount"], row["effective_from"]) for row in body["records"]], [("3000.00", "2020-01-01")])
        self.assertEqual(body["records"][0]["by"], self.admin.short_name)
        self.assertEqual(len(body["lines"]), 1)
        self.assertEqual(body["can"], {"line": False, "set": False})
        self.assertEqual(_json(self.get(self.admin, SALARY, [self.tr.pk]))["can"], {"line": True, "set": True})

    def test_a_salary_is_added_and_the_old_one_stays(self):
        answer = self.post(self.admin, SALARY_SAVE, {"values": {"amount": "3500", "effective_from": "2026-01-01", "note": "Raise"}}, [self.tr.pk])
        self.assertEqual((answer.status_code, _json(answer)["ok"]), (200, True))
        self.assertEqual(SalaryRecord.objects.filter(user=self.tr).count(), 2)
        self.assertEqual(SalaryRecord.amount_on(self.tr, date(2025, 6, 1)), Decimal("3000.00"))
        self.assertEqual(SalaryRecord.amount_on(self.tr, date(2026, 6, 1)), Decimal("3500.00"))
        row = AuditLog.objects.filter(action="salary.set").latest("pk")
        self.assertEqual((row.actor_id, row.target, row.detail), (self.admin.pk, self.tr.username, "3500"))

    def test_accounting_reads_a_salary_and_the_owner_alone_sets_it(self):
        answer = self.post(self.accounting, SALARY_SAVE, {"values": {"amount": "9999", "effective_from": "2026-01-01"}}, [self.tr.pk])
        self.assertEqual((answer.status_code, _json(answer)["error"]), (403, "forbidden"))
        self.assertEqual(SalaryRecord.objects.filter(user=self.tr).count(), 1)
        self.assertEqual(self.get(self.accounting, SALARY, [self.tr.pk]).status_code, 200)

    def test_a_salary_that_is_not_one_is_refused(self):
        for values in ({"amount": "abc", "effective_from": "2026-01-01"}, {"amount": "100", "effective_from": ""}, {"amount": "99999999999", "effective_from": "2026-01-01"}):
            self.assertEqual(self.post(self.admin, SALARY_SAVE, {"values": values}, [self.tr.pk]).status_code, 400, values)
        self.assertEqual(SalaryRecord.objects.filter(user=self.tr).count(), 1)

    def test_a_field_the_form_does_not_have_is_refused(self):
        answer = self.post(self.admin, SALARY_SAVE, {"values": {"amount": "1", "effective_from": "2026-01-01", "user": self.ops.pk}}, [self.tr.pk])
        self.assertEqual((answer.status_code, _json(answer)["error"]), (400, "bad_body"))

    def test_a_person_that_does_not_exist_is_a_404(self):
        self.assertEqual(self.get(self.accounting, SALARY, [999999]).status_code, 404)
        self.assertEqual(self.post(self.admin, SALARY_SAVE, {"values": {}}, [999999]).status_code, 404)


class RulesTests(_Accounts):
    def save(self, **values):
        return self.post(self.admin, RULES_SAVE, {"values": values})

    def test_every_box_of_the_form_is_in_exactly_one_section_and_has_its_words(self):
        form = PayrollSettingsForm(instance=PayrollSettings.load())
        shown = [name for section in RULE_SECTIONS for name in section["fields"]]
        self.assertEqual(sorted(shown), sorted(form.fields))
        self.assertEqual(len(shown), len(set(shown)))
        self.assertEqual(set(RULE_TEXTS) - set(form.fields), set())
        self.assertEqual(set(form.fields) - set(RULE_TEXTS), set())

    def test_the_door_sends_the_sections_the_fields_and_the_bilingual_words(self):
        body = _json(self.get(self.admin, RULES))
        self.assertEqual([section["key"] for section in body["sections"]], ["month", "deductions", "bonuses", "attendance", "overtime", "alerts", "leave", "performance"])
        fields = {field["name"]: field for field in body["fields"]}
        self.assertEqual((fields["daily_hours"]["label_ar"], fields["daily_hours"]["label_en"]), ("ساعات اليوم", "Hours a day"))
        self.assertIn("hint_ar", fields["working_days_per_month"])
        self.assertEqual(fields["bonuses_need_approval"]["kind"], "checkbox")
        self.assertEqual(fields["off_site_policy"]["kind"], "select")
        self.assertEqual(body["check"]["working_days"], PayrollSettings.load().working_days_per_month)
        self.assertTrue(any("note_ar" in section for section in body["sections"]))

    def test_the_bands_are_listed_by_scale(self):
        ProductionTier.objects.all().delete()
        ProductionTier.objects.create(scale="primary", min_words=1000, max_words=1500, bonus=Decimal("10.00"))
        ProductionTier.objects.create(scale="secondary", min_words=500, max_words=None, bonus=Decimal("20.00"))
        tiers = _json(self.get(self.admin, RULES))["tiers"]
        self.assertEqual([(row["min_words"], row["max_words"], row["bonus"]) for row in tiers["primary"]], [(1000, 1500, "10.00")])
        self.assertEqual([(row["min_words"], row["max_words"]) for row in tiers["secondary"]], [(500, None)])

    def test_a_change_is_saved_and_only_that_one(self):
        before = PayrollSettings.load().working_days_per_month
        answer = self.save(daily_hours="7")
        self.assertEqual((answer.status_code, _json(answer)), (200, {"ok": True}))
        conf = PayrollSettings.objects.get()
        self.assertEqual(Decimal(str(conf.daily_hours)), Decimal("7"))
        self.assertEqual(conf.working_days_per_month, before)

    def test_the_log_gets_the_names_of_the_boxes_and_not_the_numbers(self):
        self.save(daily_hours="7", unexcused_penalty_days="9")
        row = AuditLog.objects.filter(action="payroll.rules.update").latest("pk")
        self.assertEqual(sorted(row.detail.split(", ")), ["daily_hours", "unexcused_penalty_days"])
        self.assertNotIn("9", row.detail.replace("unexcused_penalty_days", ""))
        self.assertEqual(row.actor_id, self.admin.pk)

    def test_what_the_form_refuses_is_refused_and_nothing_is_saved(self):
        before = PayrollSettings.load().daily_target_words
        answer = self.save(daily_target_words="100", monthly_target_words="99999", working_days_per_month="20")
        body = _json(answer)
        self.assertEqual((answer.status_code, body["error"], "monthly_target_words" in body["errors"]), (400, "invalid", True))
        self.assertEqual(PayrollSettings.load().daily_target_words, before)

    def test_all_the_weights_at_zero_are_refused(self):
        answer = self.save(weight_productivity="0", weight_quality="0", weight_deadline="0", weight_attendance="0")
        self.assertEqual((answer.status_code, "weight_attendance" in _json(answer)["errors"]), (400, True))

    def test_a_field_the_form_does_not_have_is_refused(self):
        answer = self.save(id=3)
        self.assertEqual((answer.status_code, _json(answer)["error"]), (400, "bad_body"))

    def test_a_band_is_added_and_removed(self):
        # 7000 is above every band the migration seeds: a band that starts where a seeded one starts is refused as a duplicate.
        answer = self.post(self.admin, TIER_ADD, {"values": {"scale": "primary", "min_words": "7000", "max_words": "7500", "bonus": "75"}})
        self.assertEqual((answer.status_code, _json(answer)["ok"]), (200, True))
        tier = ProductionTier.objects.get(min_words=7000)
        self.assertTrue(AuditLog.objects.filter(action="payroll.tier.add", actor=self.admin).exists())
        gone = self.post(self.admin, TIER_DELETE, {}, [tier.pk])
        self.assertEqual(_json(gone)["deleted"], 1)
        self.assertFalse(ProductionTier.objects.filter(pk=tier.pk).exists())
        self.assertTrue(AuditLog.objects.filter(action="payroll.tier.delete", target=str(tier.pk)).exists())

    def test_a_band_must_end_above_where_it_starts(self):
        answer = self.post(self.admin, TIER_ADD, {"values": {"scale": "primary", "min_words": "3000", "max_words": "2000", "bonus": "75"}})
        self.assertEqual((answer.status_code, "max_words" in _json(answer)["errors"]), (400, True))

    def test_a_band_that_starts_where_another_one_starts_is_refused_and_nothing_is_added(self):
        ProductionTier.objects.create(scale="primary", min_words=8000, max_words=8500, bonus=Decimal("40.00"))
        answer = self.post(self.admin, TIER_ADD, {"values": {"scale": "primary", "min_words": "8000", "max_words": "9000", "bonus": "75"}})
        self.assertEqual((answer.status_code, _json(answer)["error"], "__all__" in _json(answer)["errors"]), (400, "invalid", True))
        self.assertEqual(ProductionTier.objects.filter(scale="primary", min_words=8000).count(), 1)
        self.assertFalse(AuditLog.objects.filter(action="payroll.tier.add").exists())

    def test_removing_a_band_that_is_not_there_is_not_an_error(self):
        self.assertEqual(_json(self.post(self.admin, TIER_DELETE, {}, [999999]))["deleted"], 0)

    def test_a_get_changes_nothing(self):
        before = AuditLog.objects.count()
        self.get(self.admin, RULES)
        self.assertEqual(AuditLog.objects.count(), before)


class SwitchAndHandOnTests(_Accounts):
    def setUp(self):
        super().setUp()
        self.line = self.line_of()

    def test_the_menu_lists_it_for_who_is_switched_on(self):
        self.switch(roles=["accounting"])
        self.assertIn("accounts", _json(self.get(self.accounting, "dashboard:v1_me"))["screens"])
        self.assertNotIn("accounts", _json(self.get(self.ops, "dashboard:v1_me"))["screens"])

    def test_the_classic_pages_go_on_with_the_switch(self):
        self.switch(roles=["accounting"])
        for name, args, target in (
            ("dashboard:accounts_overview", None, "/app/accounts"),
            ("dashboard:accounts_attendance", None, "/app/accounts/attendance"),
            ("dashboard:accounts_violations", None, "/app/accounts/violations"),
            ("dashboard:accounts_salary", [self.tr.pk], f"/app/accounts/salary/{self.tr.pk}"),
        ):
            answer = self.get(self.accounting, name, args)
            self.assertEqual((answer.status_code, answer["Location"]), (302, target), name)

    def test_the_month_and_the_person_go_along_when_they_are_the_shape_the_new_page_reads(self):
        self.switch(roles=["accounting"])
        self.assertEqual(self.get(self.accounting, "dashboard:accounts_overview", year=2026, month=3)["Location"], "/app/accounts?period=2026-3")
        self.assertEqual(self.get(self.accounting, "dashboard:accounts_overview", period="2026-09")["Location"], "/app/accounts?period=2026-9")
        answer = self.get(self.accounting, "dashboard:accounts_attendance", period="2026-09", user=self.tr.pk)
        self.assertEqual(answer["Location"], f"/app/accounts/attendance?period=2026-9&user={self.tr.pk}")
        self.assertEqual(self.get(self.accounting, "dashboard:accounts_attendance", user="x y")["Location"], "/app/accounts/attendance")
        self.assertEqual(self.get(self.accounting, "dashboard:accounts_overview")["Location"], "/app/accounts")

    def test_the_new_addresses_serve_the_app(self):
        self.switch(roles=["accounting"])
        for address in ("/app/accounts", "/app/accounts/lines/5", "/app/accounts/attendance", "/app/accounts/violations", "/app/accounts/rules", "/app/accounts/salary/5"):
            browser = DjangoClient()
            browser.force_login(self.accounting)
            self.assertEqual(browser.get(address).status_code, 200, address)
