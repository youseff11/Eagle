"""The team leader chooses what deadline the translator gets: the operation's own, or a shorter one he types (07/10/2026).

He is handed a job with a deadline - "due on such a day, so much time left" - and he decides whether the translator works to that same
date or to an earlier one (the gap being the time he keeps to review). It is his choice, asked every time: nothing is chosen for him,
a request that does not say is refused, and a shorter one has to be written and has to be shorter. What these tests hold: both choices
reach the translator as the date they are, "the same" clears an earlier one, and the countdown the translator and the leader read is
the date that was chosen.
"""

from datetime import timedelta

from django.test import Client as DjangoClient
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from . import services
from .models import Client, Role, TaskStatus, User


#: What the leader has to say about the share he gives, with or without a deadline: the pair and the words.
PART = {"source_lang": "EN", "target_lang": "AR", "words": "500"}


class DeadlineChoiceTests(TestCase):
    def setUp(self):
        make = lambda name, role, **kw: User.objects.create_user(name, password="x", role=role, **kw)
        self.ops = make("ops_dc", Role.OPERATION)
        self.lead = make("lead_dc", Role.TEAM_LEAD)
        self.other_lead = make("lead_dc_two", Role.TEAM_LEAD)
        self.admin = make("admin_dc", Role.ADMIN)
        self.tr = make("tr_dc", Role.TRANSLATOR, team_lead=self.lead)
        self.acme = Client.objects.create(name="ACME", phone="+201000000071")
        self.due = timezone.now() + timedelta(days=3)
        self.task = services.create_task(client=self.acme, title="Doc", created_by=self.ops, deadline=self.due)
        services.accept_assignment(services.assign_to_lead(self.task, self.lead, self.ops), self.lead)
        self.task.refresh_from_db()

    def assign(self, user=None, **data):
        browser = DjangoClient()
        browser.force_login(user or self.lead)
        return browser.post(reverse("dashboard:api_assign_translator", args=[self.task.code]), {"user": self.tr.pk, **PART, **data})

    def fresh(self):
        self.task.refresh_from_db()
        return self.task

    def assigned(self):
        return self.fresh().translator_id == self.tr.pk

    # -- he has to choose ---------------------------------------------------------------------------
    def test_a_request_that_does_not_say_what_he_chose_is_refused_and_nothing_goes_out(self):
        for data in ({}, {"tdeadline_mode": ""}, {"tdeadline_days": "1"}, {"tdeadline_mode": "later"}, {"tdeadline_mode": "SAME"}):
            answer = self.assign(**data)
            self.assertEqual((answer.status_code, answer.json()["error"]), (400, services.PICK_TRANSLATOR_DEADLINE_AR), data)
            self.assertEqual(answer.json()["code"], "pick_deadline")
        self.assertFalse(self.assigned())
        self.assertEqual(self.fresh().status, TaskStatus.LEAD_ACCEPTED)

    # -- the same ------------------------------------------------------------------------------------
    def test_the_same_deadline_is_the_operations_and_the_translator_has_none_of_his_own(self):
        self.assertEqual(self.assign(tdeadline_mode="same").status_code, 200)
        task = self.fresh()
        self.assertTrue(self.assigned())
        self.assertIsNone(task.translator_deadline)
        self.assertEqual(task.deadline_for(self.tr), self.due)
        self.assertEqual(task.deadline_for(self.lead), self.due)

    def test_the_same_ignores_whatever_was_typed_in_the_boxes(self):
        self.assign(tdeadline_mode="same", tdeadline_days="1", tdeadline_hours="2")
        self.assertIsNone(self.fresh().translator_deadline)

    def test_the_same_takes_back_an_earlier_date_a_first_hand_over_gave(self):
        self.assign(tdeadline_mode="shorter", tdeadline_days="1")
        self.assertIsNotNone(self.fresh().translator_deadline)
        # The translator did not answer in time (or said no), and the leader sends it again, this time on the same date.
        self.assign(tdeadline_mode="same")
        self.assertIsNone(self.fresh().translator_deadline)

    # -- shorter -------------------------------------------------------------------------------------
    def test_a_shorter_deadline_is_the_one_he_typed_counted_from_now(self):
        self.assertEqual(self.assign(tdeadline_mode="shorter", tdeadline_days="1", tdeadline_hours="6").status_code, 200)
        task = self.fresh()
        expected = timezone.now() + timedelta(days=1, hours=6)
        self.assertLess(abs((task.translator_deadline - expected).total_seconds()), 120)
        self.assertLess(task.translator_deadline, task.deadline)
        self.assertEqual(task.deadline_for(self.tr), task.translator_deadline)
        self.assertEqual(task.deadline_for(self.lead), self.due)
        self.assertEqual(task.deadline_for(self.ops), self.due)

    def test_choosing_shorter_means_writing_one(self):
        for data in ({}, {"tdeadline_days": "", "tdeadline_hours": "", "tdeadline_minutes": ""}, {"tdeadline_days": "0", "tdeadline_hours": "0"}):
            answer = self.assign(tdeadline_mode="shorter", **data)
            self.assertEqual((answer.status_code, answer.json()["error"]), (400, services.TYPE_SHORTER_DEADLINE_AR), data)
        self.assertFalse(self.assigned())

    def test_it_has_to_be_shorter_than_the_operations_not_equal_and_not_longer(self):
        for data in ({"tdeadline_days": "3"}, {"tdeadline_days": "3", "tdeadline_hours": "1"}, {"tdeadline_days": "9"}):
            answer = self.assign(tdeadline_mode="shorter", **data)
            self.assertEqual((answer.status_code, answer.json()["error"]), (400, services.SHORTER_THAN_OPERATIONS_AR), data)
        self.assertFalse(self.assigned())
        self.assertIsNone(self.fresh().translator_deadline)

    def test_what_is_not_a_number_or_is_below_nought_is_refused_in_the_forms_own_words(self):
        for bad in ("abc", "-1", "1.5"):
            answer = self.assign(tdeadline_mode="shorter", tdeadline_days=bad)
            self.assertEqual(answer.status_code, 400, bad)
        self.assertFalse(self.assigned())

    def test_a_task_the_operation_gave_no_date_can_still_be_given_a_shorter_one(self):
        task = services.create_task(client=self.acme, title="Open ended", created_by=self.ops, deadline=None)
        services.accept_assignment(services.assign_to_lead(task, self.lead, self.ops), self.lead)
        browser = DjangoClient()
        browser.force_login(self.lead)
        answer = browser.post(
            reverse("dashboard:api_assign_translator", args=[task.code]),
            {"user": self.tr.pk, **PART, "tdeadline_mode": "shorter", "tdeadline_days": "2"},
        )
        self.assertEqual(answer.status_code, 200)
        task.refresh_from_db()
        self.assertIsNotNone(task.translator_deadline)

    # -- who and when ----------------------------------------------------------------------------------
    def test_only_the_tasks_own_leader_and_the_admin_choose(self):
        self.assertEqual(self.assign(self.other_lead, tdeadline_mode="same").status_code, 404)
        self.assertEqual(self.assign(self.ops, tdeadline_mode="same").status_code, 403)
        self.assertFalse(self.assigned())
        self.assertEqual(self.assign(self.admin, tdeadline_mode="shorter", tdeadline_days="1").status_code, 200)

    def test_a_task_that_is_not_waiting_for_a_translator_takes_no_choice(self):
        self.assertEqual(self.assign(tdeadline_mode="same").status_code, 200)
        self.task.status = TaskStatus.DELIVERED
        self.task.save(update_fields=["status"])
        self.assertEqual(self.assign(tdeadline_mode="same").status_code, 400)

    # -- what both read ----------------------------------------------------------------------------------
    def test_the_translators_task_carries_the_date_the_leader_chose_for_the_countdown(self):
        self.assign(tdeadline_mode="shorter", tdeadline_days="1")
        services.accept_assignment(self.task.assignments.order_by("-id").first(), self.tr)
        browser = DjangoClient()
        browser.force_login(self.tr)
        task = browser.get(reverse("dashboard:v1_translator_task", args=[self.task.code])).json()["task"]
        self.assertEqual(task["due_iso"], self.fresh().translator_deadline.isoformat())
        self.assertNotEqual(task["due_iso"], self.due.isoformat())

    def test_the_translator_with_the_same_date_counts_down_to_the_operations(self):
        self.assign(tdeadline_mode="same")
        services.accept_assignment(self.task.assignments.order_by("-id").first(), self.tr)
        browser = DjangoClient()
        browser.force_login(self.tr)
        task = browser.get(reverse("dashboard:v1_translator_task", args=[self.task.code])).json()["task"]
        self.assertEqual(task["due_iso"], self.due.isoformat())

    def test_the_leaders_page_carries_both_dates_for_the_two_countdowns(self):
        self.assign(tdeadline_mode="shorter", tdeadline_days="1")
        browser = DjangoClient()
        browser.force_login(self.lead)
        task = browser.get(reverse("dashboard:v1_task", args=[self.task.code])).json()["task"]
        self.assertEqual(task["due_iso"], self.due.isoformat())
        self.assertEqual(task["translator_due_iso"], self.fresh().translator_deadline.isoformat())

    def test_with_the_same_date_the_leaders_page_has_no_second_countdown(self):
        self.assign(tdeadline_mode="same")
        browser = DjangoClient()
        browser.force_login(self.lead)
        task = browser.get(reverse("dashboard:v1_task", args=[self.task.code])).json()["task"]
        self.assertEqual((task["due_iso"], task["translator_due_iso"]), (self.due.isoformat(), ""))

    def test_a_task_that_is_done_has_nothing_to_count_down_to(self):
        self.assign(tdeadline_mode="shorter", tdeadline_days="1")
        self.task.status = TaskStatus.DELIVERED
        self.task.save(update_fields=["status"])
        browser = DjangoClient()
        browser.force_login(self.ops)
        task = browser.get(reverse("dashboard:v1_task", args=[self.task.code])).json()["task"]
        self.assertEqual((task["due_iso"], task["translator_due_iso"]), ("", ""))
