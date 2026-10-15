"""B2C part 2: the B2C numbers (``b2c_board.py``, ``/api/v1/b2c/board/``).

Held here: who reads whose numbers; the six figures of the requirements, each with what it is made of and «not measured»
when there is nothing to divide; the filters; the lists of companies that need someone; the CSV export and its safety.
"""

import json
from datetime import date, timedelta
from decimal import Decimal

from django.test import Client as DjangoClient
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from . import b2b, b2c, b2c_board
from .models import (
    AppSettings, AuditLog, FieldVisit, Lead, LeadActivity, LeadSheet, LeadStatus, LeaveKind, LeaveRequest, LeaveStatus,
    Market, Quotation, Role, SalesTrack, User,
)

TOWER = (Decimal("30.045900"), Decimal("31.224300"))
NEAR = (30.0459, 31.2248)


def _json(response):
    return json.loads(response.content.decode("utf-8"))


class _Board(TestCase):
    def setUp(self):
        make = lambda name, role, **kw: User.objects.create_user(name, password="pw", role=role, first_name=name.title(), **kw)
        self.admin = make("owner", Role.ADMIN)
        self.manager = make("b2cboss", Role.SALES, is_sales_manager=True, sales_track=SalesTrack.B2C_ONLINE)
        self.field = make("walker", Role.SALES, sales_track=SalesTrack.B2C_FIELD)
        self.online = make("caller", Role.SALES, sales_track=SalesTrack.B2C_ONLINE)
        self.b2b_sales = make("abroad", Role.SALES)
        self.ops = make("ops", Role.OPERATION)
        self.sheet = LeadSheet.objects.create(title="Cairo", assigned_to=self.field, market=Market.B2C)
        self.lead = Lead.objects.create(
            sheet=self.sheet, company_name="Nile Trading", governorate="Cairo", source="Facebook",
            latitude=TOWER[0], longitude=TOWER[1],
        )
        self.other = Lead.objects.create(sheet=self.sheet, company_name="Delta Co", governorate="Giza", source="Referral")
        self.online_sheet = LeadSheet.objects.create(title="Phones", assigned_to=self.online, market=Market.B2C)
        self.b2b_sheet = LeadSheet.objects.create(title="Germany", assigned_to=self.b2b_sales)
        Lead.objects.create(sheet=self.b2b_sheet, company_name="Lingua GmbH", source="Facebook")
        self.today = timezone.localdate()
        conf = AppSettings.load()
        conf.b2c_visit_target = 10
        conf.save()

    def browser(self, user):
        browser = DjangoClient()
        browser.force_login(user)
        return browser

    def board(self, user, **query):
        query.setdefault("from", self.today.replace(day=1).isoformat())
        query.setdefault("to", self.today.isoformat())
        return self.browser(user).get(reverse("dashboard:v1_b2c_board"), query)

    def row(self, answer, person):
        return next(row for row in answer["rows"] if row["person"]["id"] == person.pk)

    def visit(self, lead=None, verified=True):
        visit = b2c.plan(lead or self.lead, self.field, self.field)
        b2c.check_in(visit, self.field, lat=NEAR[0], lng=NEAR[1], accuracy=5)
        b2c.check_out(visit, self.field, {"outcome": "interested", "summary": "ok"}, lat=NEAR[0], lng=NEAR[1], accuracy=5)
        b2c.decide(visit, self.manager, verified, "checked")
        return visit

    def stage(self, lead, status, by=None):
        before = lead.status
        lead.status = status
        lead.save()
        b2b.note_status(lead, before, status, by or self.field)


class DoorTests(_Board):
    def test_the_doors_are_under_api_v1(self):
        self.assertEqual(reverse("dashboard:v1_b2c_board"), "/api/v1/b2c/board/")
        self.assertEqual(reverse("dashboard:v1_b2c_board_export"), "/api/v1/b2c/board/export/")

    def test_the_b2c_people_and_the_owner_read_it(self):
        for user in (self.field, self.online, self.manager, self.admin):
            self.assertEqual(self.board(user).status_code, 200, user)
        for user in (self.b2b_sales, self.ops):
            self.assertEqual(self.board(user).status_code, 403, user)

    def test_a_sales_person_reads_their_own_row_the_manager_the_team(self):
        own = _json(self.board(self.online))
        self.assertEqual([row["person"]["id"] for row in own["rows"]], [self.online.pk])
        self.assertFalse(own["team"])
        self.assertEqual(own["filters"]["people"], [])
        team = _json(self.board(self.manager))
        self.assertEqual({row["person"]["id"] for row in team["rows"]}, {self.field.pk, self.online.pk})
        self.assertTrue(team["team"])

    def test_a_person_outside_the_team_is_refused(self):
        self.assertEqual(self.board(self.manager, person=self.b2b_sales.pk).status_code, 400)
        # A Sales person cannot read a colleague by naming them.
        self.assertEqual(self.board(self.online, person=self.field.pk).status_code, 400)
        answer = _json(self.board(self.manager, person=self.field.pk))
        self.assertEqual([row["person"]["id"] for row in answer["rows"]], [self.field.pk])

    def test_a_bad_period_is_refused(self):
        self.assertEqual(self.board(self.manager, **{"from": "2026-13-01"}).status_code, 400)


class FigureTests(_Board):
    def test_visit_achievement_and_verification_against_the_target(self):
        self.visit()
        self.visit(self.other)
        self.visit(verified=False)
        row = self.row(_json(self.board(self.field, **{"from": self.today.replace(day=1).isoformat(), "to": b2c.month_days(self.today.replace(day=1))[-1].isoformat()})), self.field)
        self.assertEqual(row["due"], 10)
        self.assertEqual(row["visit_achievement"], {"value": 20, "part": 2, "whole": 10})
        self.assertEqual(row["verification_rate"], {"value": 67, "part": 2, "whole": 3})

    def test_an_online_person_owes_no_visits_not_measured(self):
        row = self.row(_json(self.board(self.online)), self.online)
        self.assertEqual(row["due"], 0)
        self.assertEqual(row["visit_achievement"]["value"], None)
        self.assertEqual(row["win_rate"]["value"], None)

    def test_lead_conversion_counts_a_company_qualified_after_its_verified_visit(self):
        self.stage(self.other, LeadStatus.REQUIREMENT)
        self.visit(self.other)
        self.visit()
        self.stage(self.lead, LeadStatus.NEGOTIATION)
        row = self.row(_json(self.board(self.field)), self.field)
        # Delta Co was qualified before its visit: only Nile Trading counts.
        self.assertEqual(row["lead_conversion"], {"value": 50, "part": 1, "whole": 2})
        self.assertEqual(row["qualified"], 2)

    def test_quotation_conversion_and_win_rate(self):
        self.stage(self.lead, LeadStatus.REQUIREMENT)
        self.stage(self.other, LeadStatus.REQUIREMENT)
        Quotation.objects.create(
            lead=self.lead, owner=self.field, source_lang="en", target_lang="ar", quantity=100, rate=Decimal("1"),
            total=Decimal("100"), currency="EGP", status=Quotation.Status.SENT, sent_at=timezone.now(),
        )
        self.stage(self.lead, LeadStatus.WON)
        self.stage(self.other, LeadStatus.LOST)
        answer = _json(self.board(self.field))
        row = self.row(answer, self.field)
        self.assertEqual(row["quotation_conversion"], {"value": 50, "part": 1, "whole": 2})
        self.assertEqual(row["win_rate"], {"value": 50, "part": 1, "whole": 2})
        self.assertEqual(answer["total"]["quote_average"], {"EGP": "100.00"})

    def test_follow_up_compliance(self):
        yesterday = self.today - timedelta(days=1)
        LeadActivity.objects.create(lead=self.lead, kind=LeadActivity.Kind.CALL, owner=self.field, follow_up_for=self.today, at=timezone.now())
        late_at = timezone.now()
        LeadActivity.objects.create(lead=self.other, kind=LeadActivity.Kind.CALL, owner=self.field, follow_up_for=yesterday, at=late_at)
        row = self.row(_json(self.board(self.field, **{"from": yesterday.isoformat(), "to": self.today.isoformat()})), self.field)
        self.assertEqual(row["follow_up_compliance"], {"value": 50, "part": 1, "whole": 2})

    def test_the_period_target_is_the_days_worked_of_the_month(self):
        first = date(2026, 11, 1)
        self.assertEqual(b2c.due_for_period(self.field, first, date(2026, 11, 30)), 10)
        LeaveRequest.objects.create(
            user=self.field, kind=LeaveKind.ANNUAL, start_date=date(2026, 11, 1), end_date=date(2026, 11, 30), status=LeaveStatus.APPROVED,
        )
        self.assertEqual(b2c.due_for_period(self.field, first, date(2026, 11, 30)), 0)

    def test_half_a_month_owes_about_half(self):
        due = b2c.due_for_period(self.field, date(2026, 11, 1), date(2026, 11, 15))
        self.assertIn(due, (4, 5, 6))


class FilterTests(_Board):
    def test_source_and_governorate_narrow_everything(self):
        answer = _json(self.board(self.manager, source="facebook"))
        self.assertEqual(self.row(answer, self.field)["new_leads"], 1)
        self.assertEqual([one["value"] for one in answer["sources"]], ["Facebook"])
        answer = _json(self.board(self.manager, governorate="Giza"))
        self.assertEqual(self.row(answer, self.field)["holding"], 1)
        self.assertEqual(answer["filters"]["governorates"], ["Cairo", "Giza"])
        # The B2B company with the same source is never counted.
        self.assertEqual(_json(self.board(self.manager, source="Facebook"))["total"]["new_leads"], 1)

    def test_the_stages_now_and_the_person_by_stage(self):
        self.stage(self.lead, LeadStatus.NEGOTIATION)
        answer = _json(self.board(self.manager))
        stages = {one["value"]: one["count"] for one in answer["stages"]}
        self.assertEqual((stages["new"], stages["negotiation"]), (1, 1))
        walker = next(one for one in answer["matrix"] if one["person"]["id"] == self.field.pk)
        self.assertEqual(walker["stages"]["negotiation"], 1)


class ListTests(_Board):
    def test_untouched_and_overdue_companies_and_the_log(self):
        self.visit()
        Lead.objects.filter(pk=self.other.pk).update(next_follow_up=self.today - timedelta(days=2))
        answer = _json(self.board(self.manager))
        self.assertEqual([one["company_name"] for one in answer["untouched"]], ["Delta Co"])
        self.assertEqual([one["company_name"] for one in answer["overdue"]], ["Delta Co"])
        self.assertTrue(AuditLog.objects.filter(target="b2c board").exists())

    def test_turned_down_visits_with_their_reason(self):
        self.visit(verified=False)
        answer = _json(self.board(self.manager))
        self.assertEqual([(one["company_name"], one["note"]) for one in answer["rejected"]], [("Nile Trading", "checked")])


class ExportTests(_Board):
    def export(self, user, **query):
        query.setdefault("from", self.today.replace(day=1).isoformat())
        query.setdefault("to", self.today.isoformat())
        return self.browser(user).get(reverse("dashboard:v1_b2c_board_export"), query)

    def test_the_csv_opens_in_excel_and_is_logged(self):
        answer = self.export(self.manager)
        self.assertEqual(answer.status_code, 200)
        self.assertTrue(answer["Content-Type"].startswith("text/csv"))
        text = answer.content.decode("utf-8")
        self.assertTrue(text.startswith("\ufeff"))
        self.assertIn("الـSales", text.splitlines()[0])
        self.assertIn("Walker", text)
        self.assertNotIn("Nile Trading", text)
        self.assertTrue(AuditLog.objects.filter(action="b2c.export").exists())

    def test_a_name_that_looks_like_a_formula_is_not_one(self):
        User.objects.filter(pk=self.online.pk).update(first_name="=HYPERLINK(1)")
        text = self.export(self.manager).content.decode("utf-8")
        self.assertIn("'=HYPERLINK(1)", text)

    def test_the_export_has_the_same_door(self):
        self.assertEqual(self.export(self.b2b_sales).status_code, 403)
        self.assertEqual(self.export(self.online, person=self.field.pk).status_code, 400)


class EdgeTests(_Board):
    def test_a_b2b_sheet_of_a_b2c_person_is_not_counted(self):
        # Somebody moved from one team to the other keeps the other team's companies apart.
        old = LeadSheet.objects.create(title="Old B2B", assigned_to=self.field, market=Market.B2B)
        Lead.objects.create(sheet=old, company_name="Abroad Co")
        self.assertEqual(self.row(_json(self.board(self.manager)), self.field)["holding"], 2)

    def test_a_planned_visit_is_not_contact_a_started_one_is(self):
        planned = b2c.plan(self.other, self.field, self.field)
        names = lambda: [one["company_name"] for one in _json(self.board(self.manager))["untouched"]]
        self.assertIn("Delta Co", names())
        b2c.check_in(planned, self.field, lat=NEAR[0], lng=NEAR[1], accuracy=5)
        self.assertNotIn("Delta Co", names())

    def test_leave_inside_the_period_is_not_owed(self):
        LeaveRequest.objects.create(
            user=self.field, kind=LeaveKind.ANNUAL, start_date=date(2026, 11, 1), end_date=date(2026, 11, 15), status=LeaveStatus.APPROVED,
        )
        self.assertEqual(b2c.due_for_period(self.field, date(2026, 11, 1), date(2026, 11, 15)), 0)
        self.assertGreater(b2c.due_for_period(self.field, date(2026, 11, 16), date(2026, 11, 30)), 0)


class GuideTests(_Board):
    def test_the_board_guide_is_told_to_the_b2c_team(self):
        from . import guides

        told = lambda user: {guide.id for guide in guides.for_user(user)}
        self.assertIn("b2c-performance", told(self.field))
        self.assertIn("b2c-performance", told(self.online))
        self.assertIn("b2c-performance", told(self.admin))
        self.assertNotIn("b2c-performance", told(self.b2b_sales))
