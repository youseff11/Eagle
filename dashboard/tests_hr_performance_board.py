"""The performance board: who delivered the most this month, the best three apart, and one person's months.

HR and the admin open it (``can_recruit``, like the page of one person). What these tests hold: the figures are the ones the
person's own page shows (one function makes both), a person who delivered nothing is listed and not ranked, a person with no
target is "not measured" and never a zero, a few queries answer however many people there are, and a GET writes nothing.
"""

import tempfile
from datetime import date, timedelta

from django.conf import settings
from django.db import connection
from django.test import Client as DjangoClient
from django.test import override_settings
from django.test.utils import CaptureQueriesContext
from django.urls import reverse
from django.utils import timezone

from . import avatars, payroll, performance
from .models import AuditLog, PayrollSettings, Role, SalaryPlan, Task, User, WorkDay
from .tests_api_v1 import _json, _Site
from .tests_avatar import jpeg

BOARD = "dashboard:v1_hr_performance_board"
PERSON = "dashboard:v1_hr_performance"


class _Board(_Site):
    def setUp(self):
        super().setUp()
        self.today = timezone.localdate()
        self.first, self.last = payroll.month_bounds(self.today.year, self.today.month)
        conf = PayrollSettings.load()
        conf.monthly_target_words = 1000
        conf.save()
        # The fixture's own translator delivered nothing: the tests below add the people they need.
        self.count = 0

    def translator(self, name, words=0, when=None, active=True, **over):
        self.count += 1
        person = User.objects.create_user(f"board_{name}_{self.count}", password="pw", role=Role.TRANSLATOR, first_name=name, last_name="Board", is_active=active, **over)
        if words:
            self.delivered(person, words, when)
        return person

    def delivered(self, person, words, when=None):
        when = when or self.today
        WorkDay.objects.create(user=person, date=when, status="present", work_mode="office", schedule_label="9-5", words=words)

    def deliver_task(self, person, when=None):
        moment = timezone.make_aware(timezone.datetime.combine(when or self.today, timezone.datetime.min.time())) + timedelta(hours=10)
        return Task.objects.create(client=self.client_obj, title="Delivered", translator=person, translated_at=moment)

    def read(self, name, who=None, **query):
        browser = DjangoClient()
        browser.force_login(who or self.hr)
        return browser.get(reverse(name), query)

    def board(self, who=None, **query):
        return self.read(BOARD, who, **query)

    def rows(self, **query):
        body = _json(self.board(**query))
        return body, body["podium"], body["rest"]

    def names(self, rows):
        return [row["name"] for row in rows]


class RankingTests(_Board):
    def setUp(self):
        super().setUp()
        # Fixture translator: the test of that one has delivered nothing. Put it out of the way of the counts below.
        User.objects.filter(pk=self.tr.pk).update(is_active=False)

    def test_the_best_three_stand_on_the_podium_in_order_and_the_rest_follow_ranked(self):
        for name, words in (("Eve", 300), ("Adam", 900), ("Cara", 600), ("Dan", 1200), ("Bob", 750)):
            self.translator(name, words)
        _body, podium, rest = self.rows()
        self.assertEqual([(row["rank"], row["name"]) for row in podium], [(1, "Dan Board"), (2, "Adam Board"), (3, "Bob Board")])
        self.assertEqual([(row["rank"], row["name"]) for row in rest], [(4, "Cara Board"), (5, "Eve Board")])
        self.assertEqual([row["words"] for row in podium + rest], [1200, 900, 750, 600, 300])

    def test_the_score_is_words_against_the_target_and_is_capped_where_the_person_page_caps_it(self):
        self.translator("Over", 5000)
        self.translator("Half", 500)
        _body, podium, _rest = self.rows()
        self.assertEqual([(row["name"], row["score"], row["target"]) for row in podium], [("Over Board", 120, 1000), ("Half Board", 50, 1000)])

    def test_fewer_than_three_with_words_means_a_shorter_podium_not_an_empty_step(self):
        self.translator("Only", 400)
        self.translator("Nothing", 0)
        _body, podium, rest = self.rows()
        self.assertEqual(self.names(podium), ["Only Board"])
        self.assertEqual(self.names(rest), ["Nothing Board"])

    def test_a_person_who_delivered_nothing_is_listed_with_a_zero_and_no_rank_after_the_ranked(self):
        self.translator("Zed", 0)
        self.translator("Abe", 0)
        self.translator("Mid", 200)
        for count in range(3):
            self.translator(f"Top{count}", 900 - count)
        _body, podium, rest = self.rows()
        self.assertEqual(len(podium), 3)
        self.assertEqual([(row["name"], row["rank"], row["score"]) for row in rest], [("Mid Board", 4, 20), ("Abe Board", None, 0), ("Zed Board", None, 0)])

    def test_a_month_with_nothing_delivered_has_no_podium_and_everybody_listed(self):
        self.translator("One", 0)
        self.translator("Two", 0)
        _body, podium, rest = self.rows()
        self.assertEqual(podium, [])
        self.assertEqual(len(rest), 2)
        self.assertTrue(all(row["rank"] is None for row in rest))

    def test_a_person_with_no_target_is_not_measured_and_never_a_zero_or_on_the_podium(self):
        # No company target and no plan: nothing to measure the words against.
        conf = PayrollSettings.load()
        conf.monthly_target_words = 0
        conf.save()
        plan = SalaryPlan.objects.create(name="Plan with a target", monthly_target_words=2000)
        measured = self.translator("Measured", 1000, salary_plan=plan)
        self.translator("Unmeasured", 5000)
        _body, podium, rest = self.rows()
        self.assertEqual([(row["name"], row["score"], row["rank"]) for row in podium], [("Measured Board", 50, 1)])
        self.assertEqual([(row["name"], row["score"], row["rank"], row["target"], row["words"]) for row in rest], [("Unmeasured Board", None, None, 0, 5000)])
        self.assertEqual(rest[0]["band"]["value"], "unknown")
        self.assertEqual(podium[0]["id"], measured.pk)

    def test_the_score_decides_before_the_words_so_a_smaller_target_met_counts_for_more(self):
        # 400 words of a 500-word plan (80%) stands above 700 words of the company's 1000 (70%): measured against what each was asked.
        small = SalaryPlan.objects.create(name="Part-time", monthly_target_words=500)
        self.translator("Part", 400, salary_plan=small)
        self.translator("Full", 700)
        _body, podium, _rest = self.rows()
        self.assertEqual([(row["name"], row["score"], row["words"]) for row in podium], [("Part Board", 80, 400), ("Full Board", 70, 700)])

    def test_the_same_score_goes_to_whoever_delivered_more_and_then_to_the_name(self):
        small = SalaryPlan.objects.create(name="Small", monthly_target_words=1000)
        big = SalaryPlan.objects.create(name="Big", monthly_target_words=2000)
        self.translator("Zoe", 500, salary_plan=small)
        self.translator("Yara", 1000, salary_plan=big)
        self.translator("Anna", 500, salary_plan=small)
        _body, podium, _rest = self.rows()
        self.assertEqual(self.names(podium), ["Yara Board", "Anna Board", "Zoe Board"])

    def test_only_the_active_translators_are_on_it(self):
        self.translator("Gone", 900, active=False)
        self.translator("Here", 100)
        for who in (self.ops, self.lead, self.hr, self.admin):
            self.delivered(who, 5000)
        _body, podium, rest = self.rows()
        self.assertEqual(self.names(podium + rest), ["Here Board"])

    def test_words_of_another_month_do_not_count_and_a_period_picks_the_month(self):
        earlier = date(self.today.year - 1, 3, 10)
        person = self.translator("Past", 0)
        self.delivered(person, 800, earlier)
        self.delivered(person, 100)
        _body, podium, _rest = self.rows()
        self.assertEqual((podium[0]["words"], podium[0]["score"]), (100, 10))
        body, podium, _rest = self.rows(period=f"{earlier.year}-{earlier.month}")
        self.assertEqual((body["year"], body["month"], podium[0]["words"], podium[0]["score"]), (earlier.year, earlier.month, 800, 80))

    def test_projects_delivered_in_the_month_are_counted_per_person(self):
        busy = self.translator("Busy", 500)
        calm = self.translator("Calm", 400)
        self.deliver_task(busy)
        self.deliver_task(busy)
        self.deliver_task(busy, date(self.today.year - 1, 1, 5))
        self.deliver_task(calm)
        _body, podium, _rest = self.rows()
        self.assertEqual({row["name"]: row["projects"] for row in podium}, {"Busy Board": 2, "Calm Board": 1})

    def test_the_figures_are_the_ones_the_persons_own_page_shows(self):
        people = [self.translator(name, words) for name, words in (("A", 350), ("B", 1400), ("C", 0))]
        _body, podium, rest = self.rows()
        by_id = {row["id"]: row for row in podium + rest}
        for person in people:
            own = _json(self.read(PERSON, user=person.pk))["report"]["parts"]["productivity"]
            row = by_id[person.pk]
            self.assertEqual((row["score"], row["words"], row["target"]), (own["score"], own["words"], own["target"]), person.first_name)
            expected = performance.productivity(person, self.first, self.last)
            self.assertEqual((row["score"], row["words"]), (expected["score"], expected["words"]))

    def test_a_bad_period_is_refused_and_a_get_writes_nothing(self):
        audit = AuditLog.objects.count()
        self.assertEqual(self.board(period="2026-13").status_code, 400)
        self.assertEqual(self.board(period="soon").status_code, 400)
        self.assertEqual(self.board().status_code, 200)
        self.assertEqual(AuditLog.objects.count(), audit)

    def test_the_answer_carries_the_months_to_pick_from(self):
        body, _podium, _rest = self.rows()
        self.assertEqual(len(body["periods"]), 13)
        self.assertEqual(body["periods"][0], {"year": self.today.year, "month": self.today.month})


class QueryCountTests(_Board):
    def count_queries(self):
        browser = DjangoClient()
        browser.force_login(self.hr)  # signing in is the test's own cost, not the board's
        with CaptureQueriesContext(connection) as captured:
            self.assertEqual(browser.get(reverse(BOARD)).status_code, 200)
        return len(captured)

    def test_a_few_queries_answer_however_many_people_there_are(self):
        User.objects.filter(pk=self.tr.pk).update(is_active=False)
        for index in range(3):
            self.translator(f"Few{index}", 100 * (index + 1))
            self.deliver_task(User.objects.get(first_name=f"Few{index}"))
        few = self.count_queries()
        for index in range(12):
            plan = SalaryPlan.objects.create(name=f"Plan {index}", monthly_target_words=900 + index)
            person = self.translator(f"Many{index}", 50 * (index + 1), salary_plan=plan)
            self.deliver_task(person)
        many = self.count_queries()
        self.assertEqual(few, many)
        # The session, the person, the payroll rules, the translators with their plans, the words and the projects.
        self.assertLessEqual(many, 8)


class PicturesTests(_Board):
    def setUp(self):
        super().setUp()
        folder = tempfile.TemporaryDirectory()
        self.addCleanup(folder.cleanup)
        override = override_settings(
            MEDIA_ROOT=folder.name,
            STORAGES={**settings.STORAGES, "default": {"BACKEND": "dashboard.storages.ProtectedFileSystemStorage"}},
        )
        override.enable()
        self.addCleanup(override.disable)
        User.objects.filter(pk=self.tr.pk).update(is_active=False)

    def test_a_translators_picture_rides_with_their_row_and_none_when_they_have_none(self):
        with_face = self.translator("Face", 500)
        self.translator("Plain", 400)
        avatars.replace(with_face, jpeg(40, 40))
        with_face.refresh_from_db()
        _body, podium, _rest = self.rows()
        faces = {row["name"]: row["avatar"] for row in podium}
        self.assertEqual(faces, {"Face Board": with_face.avatar.url, "Plain Board": None})
        self.assertEqual(podium[0]["initials"], "FB")


class AccessTests(_Board):
    """The board is every employee's; a person's own page of figures is HR's and the admin's."""

    def setUp(self):
        super().setUp()
        self.plan = SalaryPlan.objects.create(name="Plan", monthly_target_words=2500)
        self.translator("Seen", 700, salary_plan=self.plan)

    def test_every_role_reads_the_board_and_only_a_signed_out_request_does_not(self):
        for who in self.everyone:
            answer = self.board(who)
            self.assertEqual(answer.status_code, 200, who.role)
            self.assertEqual(self.names(_json(answer)["podium"]), ["Seen Board"], who.role)
        self.assertEqual(self.client.get(reverse(BOARD)).status_code, 401)

    def test_the_pay_plans_target_is_read_by_hr_and_the_admin_only(self):
        for who, sees in ((self.hr, True), (self.admin, True), (self.ops, False), (self.lead, False), (self.tr, False), (self.reviewer, False), (self.accounting, False), (self.sales, False)):
            row = _json(self.board(who))["podium"][0]
            self.assertEqual(row["target"], 2500 if sees else None, who.role)
            # The words and the percentage are what the board is for: everybody has them.
            self.assertEqual((row["words"], row["score"]), (700, 28), who.role)

    def test_a_persons_own_figures_stay_with_hr_and_the_admin(self):
        person = User.objects.get(first_name="Seen")
        for who, status in ((self.hr, 200), (self.admin, 200), (self.ops, 403), (self.lead, 403), (self.tr, 403), (self.reviewer, 403), (self.accounting, 403), (self.sales, 403)):
            self.assertEqual(self.read(PERSON, who, user=person.pk).status_code, status, who.role)

    def test_nothing_of_a_clients_rides_on_the_board(self):
        body = _json(self.board(self.tr))
        text = str(body)
        for secret in (self.client_obj.name, self.client_obj.phone, "password", "mail_alias", "wa_phone"):
            self.assertNotIn(secret, text)


class HistoryTests(_Board):
    def setUp(self):
        super().setUp()
        self.person = self.translator("Record", 0)

    def history(self, **query):
        return _json(self.read(PERSON, user=self.person.pk, **query))["history"]

    def test_six_months_ending_at_the_one_picked_newest_first(self):
        rows = self.history(period="2026-3")
        self.assertEqual([(row["year"], row["month"]) for row in rows], [(2026, 3), (2026, 2), (2026, 1), (2025, 12), (2025, 11), (2025, 10)])

    def test_each_month_has_its_words_its_score_against_the_target_and_its_projects(self):
        this = (self.today.year, self.today.month)
        before = (self.today.year - 1, 12) if self.today.month == 1 else (self.today.year, self.today.month - 1)
        self.delivered(self.person, 300)
        self.delivered(self.person, 200, date(*before, 15))
        self.deliver_task(self.person)
        self.deliver_task(self.person, date(*before, 15))
        self.deliver_task(self.person, date(*before, 16))
        rows = {(row["year"], row["month"]): row for row in self.history()}
        self.assertEqual((rows[this]["words"], rows[this]["score"], rows[this]["target"], rows[this]["projects"]), (300, 30, 1000, 1))
        self.assertEqual((rows[before]["words"], rows[before]["score"], rows[before]["projects"]), (200, 20, 2))

    def test_a_month_with_nothing_is_a_zero_row_not_a_missing_one(self):
        rows = self.history()
        self.assertEqual(len(rows), 6)
        self.assertTrue(all((row["words"], row["score"], row["projects"]) == (0, 0, 0) for row in rows))

    def test_a_person_with_no_target_has_a_history_of_not_measured(self):
        conf = PayrollSettings.load()
        conf.monthly_target_words = 0
        conf.save()
        self.delivered(self.person, 900)
        rows = self.history()
        self.assertTrue(all(row["score"] is None and row["band"]["value"] == "unknown" for row in rows))
        self.assertEqual(rows[0]["words"], 900)

    def test_a_month_reads_the_same_as_that_months_own_page(self):
        self.delivered(self.person, 640)
        first, last = payroll.month_bounds(self.today.year, self.today.month)
        expected = performance.productivity(self.person, first, last)
        row = self.history()[0]
        self.assertEqual((row["words"], row["score"]), (expected["words"], expected["score"]))
        own = _json(self.read(PERSON, user=self.person.pk))["report"]["parts"]["productivity"]
        self.assertEqual(row["score"], own["score"])

    def test_no_person_no_history(self):
        body = _json(self.read(PERSON, user=99999999))
        self.assertEqual((body["report"], body["history"]), (None, []))
