"""The owner's manual incentive in the month's pay: a flat sum, added to the gross, kept on the line as it was (07/10/2026).

The same month as the payroll tests (26 working days at the target, the four leave days), so what the incentive adds is read
against a net everybody already knows: 5,500 with the bonuses waiting for release.
"""

from datetime import date
from decimal import Decimal

from django.test import TestCase

from . import payroll
from .models import DayStatus, PayrollSettings, PeriodStatus, ProductionTier, Role, SalaryRecord, User, WorkDay


class IncentiveInThePayTests(TestCase):
    """It is added to the month's gross, kept on the line as it was, and a release of the bonuses does not lose it."""

    def setUp(self):
        PayrollSettings.load()
        ProductionTier.seed_defaults()
        self.person = User.objects.create_user("omar_incentive", password="x", role=Role.TRANSLATOR)
        SalaryRecord.objects.create(user=self.person, amount=Decimal("5500.00"), effective_from=date(2026, 1, 1))
        self.build_month(2026, 9, present_days=26, words=3000)

    def build_month(self, year, month, present_days, words, leave=4):
        """The leave days first, then the working days: the same month the payroll tests lay out."""
        day = 1
        for _ in range(leave):
            WorkDay.objects.create(user=self.person, date=date(year, month, day), status=DayStatus.LEAVE)
            day += 1
        for _ in range(present_days):
            WorkDay.objects.create(user=self.person, date=date(year, month, day), status=DayStatus.PRESENT, words=words)
            day += 1

    def line_for(self, year, month):
        return payroll.compute_line(self.person, year, month)

    def give(self, incentive):
        """Typed by the owner: the row changes, and the next run reads the person afresh."""
        User.objects.filter(pk=self.person.pk).update(incentive=Decimal(incentive))
        self.person.refresh_from_db()

    def month(self, incentive):
        self.give(incentive)
        return self.line_for(2026, 9)

    def test_it_is_added_to_the_gross_and_the_net(self):
        base = self.month("0")
        line = self.month("350.50")
        self.assertEqual(line.incentive, Decimal("350.50"))
        self.assertEqual(line.gross, base.gross + Decimal("350.50"))
        self.assertEqual(line.net, base.net + Decimal("350.50"))
        self.assertEqual(line.breakdown["rules"]["incentive"], "350.50")

    def test_a_person_with_none_is_paid_exactly_as_before(self):
        line = self.month("0")
        self.assertEqual((line.incentive, line.net), (Decimal("0.00"), Decimal("5500.00")))

    def test_releasing_the_bonuses_keeps_it_in_the_gross(self):
        self.give("200.00")
        period = payroll.compute_period(2026, 9, users=[self.person])
        line = period.lines.get(user=self.person)
        self.assertEqual(line.net, Decimal("5700.00"))
        payroll.approve_bonuses(line, None)
        line.refresh_from_db()
        self.assertEqual(line.net, Decimal("6200.00"))
        self.assertEqual(line.incentive, Decimal("200.00"))

    def test_a_month_that_was_run_keeps_what_it_was_when_the_incentive_changes_later(self):
        self.give("100.00")
        period = payroll.compute_period(2026, 9, users=[self.person])
        period.status = PeriodStatus.LOCKED
        period.save(update_fields=["status"])
        self.give("999.00")
        payroll.compute_period(2026, 9, users=[self.person])
        self.assertEqual(period.lines.get(user=self.person).incentive, Decimal("100.00"))
