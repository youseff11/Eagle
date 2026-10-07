"""A translator's ladder: trainee, then Junior, Translator, Senior, Expert, moved by the owner from the person's file.

The first rung is the only one anything reads: a trainee works and clocks in, but the accounts do not run on them (no payroll line,
no deduction draft, no overtime claim, no deduction proposed or approved) until the owner promotes them. The other four are names
beside the person's name and move no pay: the owner types each salary by hand. Held here: those guards, that promoting starts the
accounts, who may set a level, that only a translator carries one, and that the register and the file say it.
"""

from datetime import date
from decimal import Decimal

from . import attendance, payroll
from .forms import StaffCreateForm, StaffEditForm, ViolationForm
from .models import (
    ApprovalStatus, AuditLog, OvertimeClaim, PayrollLine, PayrollSettings, Role, SalaryRecord, TranslatorLevel, User, Violation, WorkDay,
)
from .tests_accounts_screen import DECIDE, SALARY_SAVE, VIOLATION_NEW, _Accounts
from .tests_api_v1 import _json

SAVE = "dashboard:v1_admin_user_save"
REGISTER = "dashboard:v1_hr_register"
EMPLOYEE = "dashboard:v1_hr_employee"
GRADES = ("junior", "translator", "senior", "expert")


class _Training(_Accounts):
    def setUp(self):
        super().setUp()
        self.first = self.today.replace(day=1)
        self.rookie = User.objects.create_user("rookie_tr", password="pw", role=Role.TRANSLATOR, translator_level=TranslatorLevel.TRAINEE)
        SalaryRecord.objects.create(user=self.rookie, amount=Decimal("3000.00"), effective_from=date(2020, 1, 1), created_by=self.admin)
        self.absence(self.tr)
        self.absence(self.rookie)

    def absence(self, person):
        return WorkDay.objects.create(user=person, date=self.first, status="unexcused")


class TheLadderTests(_Training):
    def test_it_is_these_five_in_this_order(self):
        self.assertEqual(tuple(TranslatorLevel.values), ("trainee",) + GRADES)
        self.assertEqual(
            [label for _value, label in TranslatorLevel.choices],
            ["Trainee", "Junior Translator", "Translator", "Senior Translator", "Expert Translator"],
        )

    def test_only_the_first_rung_is_a_trainee_and_only_for_a_translator(self):
        self.assertTrue(self.rookie.is_trainee)
        for level in ("",) + GRADES:
            User.objects.filter(pk=self.tr.pk).update(translator_level=level)
            self.assertFalse(User.objects.get(pk=self.tr.pk).is_trainee, level)
        # An operation person cannot be one: the rung is a translator's.
        stray = User(username="stray", role=Role.OPERATION, translator_level=TranslatorLevel.TRAINEE)
        self.assertFalse(stray.is_trainee)
        stray.save()
        self.assertEqual(User.objects.get(pk=stray.pk).translator_level, "")


class TheAccountsDoNotRunTests(_Training):
    def test_no_payroll_line_for_a_trainee_and_one_for_everybody_else(self):
        self.run_month()
        self.assertFalse(PayrollLine.objects.filter(user=self.rookie).exists())
        self.assertTrue(PayrollLine.objects.filter(user=self.tr).exists())

    def test_the_door_that_names_people_does_not_get_around_it(self):
        payroll.compute_period(self.today.year, self.today.month, users=[self.rookie, self.tr])
        self.assertFalse(PayrollLine.objects.filter(user=self.rookie).exists())
        self.assertTrue(PayrollLine.objects.filter(user=self.tr).exists())

    def test_the_engine_raises_no_deduction_for_them(self):
        self.run_month()
        self.assertTrue(Violation.objects.filter(user=self.tr, kind="unexcused").exists())
        self.assertFalse(Violation.objects.filter(user=self.rookie).exists())
        drafts = payroll.raise_drafts(self.rookie, self.today.year, self.today.month, list(self.rookie.work_days.all()), payroll.rules_for(self.rookie))
        self.assertEqual(drafts, [])

    def test_no_overtime_claim_for_them(self):
        conf = PayrollSettings.load()
        conf.overtime_enabled = True
        conf.overtime_min_minutes = 15
        conf.save()
        for person in (self.tr, self.rookie):
            WorkDay.objects.filter(user=person).delete()
            WorkDay.objects.create(user=person, date=self.today, status="present", overtime_minutes=120, scheduled_minutes=480)
            attendance.raise_overtime(person, self.first, self.today, conf=conf)
        self.assertTrue(OvertimeClaim.objects.filter(user=self.tr).exists())
        self.assertFalse(OvertimeClaim.objects.filter(user=self.rookie).exists())

    def test_the_extra_time_claimed_at_check_out_is_not_made_for_them_either(self):
        conf = PayrollSettings.load()
        conf.overtime_enabled = True
        conf.save()
        rows = {}
        for person in (self.tr, self.rookie):
            WorkDay.objects.filter(user=person).delete()
            rows[person.pk] = WorkDay.objects.create(user=person, date=self.today, status="present", overtime_minutes=90, scheduled_minutes=480)
        self.assertIsNotNone(attendance._claim_extra(rows[self.tr.pk], conf))
        self.assertIsNone(attendance._claim_extra(rows[self.rookie.pk], conf))
        self.assertFalse(OvertimeClaim.objects.filter(user=self.rookie).exists())

    def test_promoted_off_the_first_rung_they_are_worked_out_like_anybody(self):
        self.run_month()
        self.assertEqual(self.post(self.admin, SAVE, {"values": {"translator_level": "junior"}}, [self.rookie.pk]).status_code, 200)
        self.run_month()
        self.assertTrue(PayrollLine.objects.filter(user=self.rookie).exists())
        self.assertTrue(Violation.objects.filter(user=self.rookie, kind="unexcused").exists())


class NoDeductionByHandTests(_Training):
    def test_the_form_does_not_offer_them(self):
        ids = set(ViolationForm().fields["user"].queryset.values_list("pk", flat=True))
        self.assertIn(self.tr.pk, ids)
        self.assertNotIn(self.rookie.pk, ids)

    def test_proposing_one_for_them_is_refused_and_writes_nothing(self):
        values = {"user": str(self.rookie.pk), "date": self.today.isoformat(), "kind": "quality", "penalty_days": "1", "reason": "x"}
        answer = self.post(self.accounting, VIOLATION_NEW, {"values": values})
        self.assertEqual(answer.status_code, 400)
        self.assertFalse(Violation.objects.filter(user=self.rookie).exists())
        answer = self.post(self.accounting, VIOLATION_NEW, {"values": {**values, "user": str(self.tr.pk)}})
        self.assertEqual(answer.status_code, 200)

    def test_one_written_before_the_training_cannot_be_approved_but_can_be_rejected(self):
        row = self.violation(user=self.rookie)
        answer = self.post(self.accounting, DECIDE, {}, [row.pk, "approve"])
        self.assertEqual((answer.status_code, _json(answer)["error"]), (409, "trainee"))
        row.refresh_from_db()
        self.assertEqual(row.status, ApprovalStatus.PENDING)
        self.assertEqual(self.post(self.accounting, DECIDE, {}, [row.pk, "reject"]).status_code, 200)
        row.refresh_from_db()
        self.assertEqual(row.status, ApprovalStatus.REJECTED)

    def test_the_same_deduction_on_a_graded_translator_is_approved_as_before(self):
        User.objects.filter(pk=self.tr.pk).update(translator_level="junior")
        row = self.violation(user=self.tr)
        self.assertEqual(self.post(self.accounting, DECIDE, {}, [row.pk, "approve"]).status_code, 200)
        row.refresh_from_db()
        self.assertEqual(row.status, ApprovalStatus.APPROVED)


class TheOwnerSetsItTests(_Training):
    def test_each_rung_is_set_from_the_staff_form_and_written_down(self):
        for level in ("trainee",) + GRADES:
            self.assertEqual(self.post(self.admin, SAVE, {"values": {"translator_level": level}}, [self.tr.pk]).status_code, 200, level)
            self.assertEqual(User.objects.get(pk=self.tr.pk).translator_level, level)
        self.assertTrue(AuditLog.objects.filter(action="user.update", target=self.tr.username, detail__contains="translator_level").exists())

    def test_a_rung_that_is_not_one_is_refused(self):
        self.assertEqual(self.post(self.admin, SAVE, {"values": {"translator_level": "boss"}}, [self.tr.pk]).status_code, 400)
        self.assertEqual(User.objects.get(pk=self.tr.pk).translator_level, "")

    def test_only_a_translator_carries_one(self):
        answer = self.post(self.admin, SAVE, {"values": {"translator_level": "senior"}}, [self.ops.pk])
        self.assertEqual(answer.status_code, 400)
        self.assertEqual(User.objects.get(pk=self.ops.pk).translator_level, "")
        User.objects.filter(pk=self.tr.pk).update(translator_level="senior")
        person = User.objects.get(pk=self.tr.pk)
        person.role = Role.OPERATION
        person.save()
        self.assertEqual(User.objects.get(pk=self.tr.pk).translator_level, "")

    def test_nobody_but_the_admin_sets_it(self):
        for who in (self.hr, self.accounting, self.ops):
            self.assertEqual(self.post(who, SAVE, {"values": {"translator_level": "expert"}}, [self.tr.pk]).status_code, 403, who.username)
        self.assertEqual(User.objects.get(pk=self.tr.pk).translator_level, "")

    def test_a_new_person_can_start_as_a_trainee(self):
        self.assertIn("translator_level", StaffCreateForm().fields)
        self.assertIn("translator_level", StaffEditForm(instance=self.tr).fields)

    def test_no_pay_is_worked_out_from_a_grade(self):
        nets = set()
        for level in ("", "junior", "translator", "senior", "expert"):
            User.objects.filter(pk=self.tr.pk).update(translator_level=level)
            nets.add(self.line_of().net)
        self.assertEqual(len(nets), 1)

    def test_the_salary_is_typed_from_the_file_through_the_owners_door(self):
        answer = self.post(self.admin, SALARY_SAVE, {"values": {"amount": "4200", "effective_from": "2026-10-01", "note": "promoted"}}, [self.rookie.pk])
        self.assertEqual(answer.status_code, 200)
        self.assertEqual(SalaryRecord.amount_on(self.rookie, date(2026, 10, 7)), Decimal("4200"))
        self.assertEqual(self.post(self.accounting, SALARY_SAVE, {"values": {"amount": "1", "effective_from": "2026-10-01"}}, [self.rookie.pk]).status_code, 403)


class SaidBesideTheNameTests(_Training):
    def test_the_register_says_it_and_says_nothing_for_somebody_not_graded(self):
        User.objects.filter(pk=self.tr.pk).update(translator_level="expert")
        rows = {row["id"]: row for row in _json(self.get(self.admin, REGISTER))["rows"]}
        self.assertEqual(rows[self.tr.pk]["level"], {"value": "expert", "ar": "مترجم خبير", "en": "Expert Translator"})
        self.assertEqual(rows[self.rookie.pk]["level"]["value"], "trainee")
        self.assertIsNone(rows[self.ops.pk]["level"])

    def test_the_file_says_it(self):
        User.objects.filter(pk=self.tr.pk).update(translator_level="senior")
        self.assertEqual(_json(self.get(self.admin, EMPLOYEE, [self.tr.pk]))["person"]["level"]["value"], "senior")
        self.assertEqual(_json(self.get(self.admin, EMPLOYEE, [self.rookie.pk]))["person"]["level"]["ar"], "متدرب")
        self.assertIsNone(_json(self.get(self.admin, EMPLOYEE, [self.ops.pk]))["person"]["level"])
