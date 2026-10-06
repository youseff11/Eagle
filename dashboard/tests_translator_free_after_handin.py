"""A translator who has handed their files in is free beside their name; a send-back makes them busy again.

The task stays "under review" and "reviewed" with the leader and the operation, so those statuses count for the leader and for the
operation's open number, never for the translator who is already done with it. Every screen that draws the dot beside a translator
asks the same question, so each is checked here.
"""

from django.test import Client as DjangoClient
from django.urls import reverse

from . import services
from .models import TaskStatus, TRANSLATOR_HOLDING_STATUSES
from .tests_api_v1 import _json
from .tests_lead_screen import BOARD, HOME, _Lead


class TranslatorFreeAfterHandInTests(_Lead):
    def setUp(self):
        super().setUp()
        self.here(self.tr)

    def _get(self, user, name):
        browser = DjangoClient()
        browser.force_login(user)
        return _json(browser.get(reverse(name)))

    def _states(self):
        """The state beside the translator on each screen that draws one."""
        board = {row["name"]: row["state"] for row in self._get(self.lead, BOARD)["team"]}
        home = {row["name"]: row["state"] for row in self._get(self.lead, HOME)["team"]}
        team = {
            member["name"]: member["state"]
            for lead in self._get(self.ops, "dashboard:v1_team")["leads"] for member in lead["members"]
        }
        register = {row["name"]: row["state"] for row in self._get(self.hr, "dashboard:v1_hr_register")["rows"]}
        name = self.tr.short_name
        return board[name], home[name], team[name], register[name]

    def _hand_in(self):
        self.task.status = TaskStatus.UNDER_REVIEW
        self.task.save(update_fields=["status"])

    def test_working_on_a_task_is_busy_everywhere(self):
        self.assertEqual(self._states(), ("busy",) * 4)
        self.assertTrue(self.tr.is_busy)

    def test_handing_the_files_in_makes_them_free_everywhere(self):
        self._hand_in()
        self.assertEqual(self._states(), ("free",) * 4)
        self.assertFalse(self.tr.is_busy)
        self.assertEqual(self.tr.active_task_count, 0)

    def test_it_stays_free_while_the_task_is_reviewed_and_after_it_is_delivered(self):
        for status in (TaskStatus.REVIEWED, TaskStatus.DELIVERED):
            self.task.status = status
            self.task.save(update_fields=["status"])
            self.assertEqual(self._states(), ("free",) * 4, status)

    def test_a_send_back_makes_them_busy_again(self):
        self._hand_in()
        self.assertTrue(services.send_back_for_revision(self.task, self.lead, "again"))
        self.assertEqual(self._states(), ("busy",) * 4)

    def test_another_open_task_keeps_them_busy_after_the_first_is_handed_in(self):
        from .models import Task

        Task.objects.create(
            client=self.client_obj, title="Second", created_by=self.ops, team_lead=self.lead,
            translator=self.tr, status=TaskStatus.IN_PROGRESS,
        )
        self._hand_in()
        self.assertEqual(self._states(), ("busy",) * 4)

    def test_the_leader_is_still_busy_with_a_task_under_review(self):
        self._hand_in()
        self.assertEqual(self.lead.active_task_count, 1)

    def test_the_handed_in_statuses_are_not_holding_ones(self):
        for status in (TaskStatus.UNDER_REVIEW, TaskStatus.REVIEWED, TaskStatus.DELIVERED, TaskStatus.CANCELLED):
            self.assertNotIn(status, TRANSLATOR_HOLDING_STATUSES)
        self.assertIn(TaskStatus.IN_PROGRESS, TRANSLATOR_HOLDING_STATUSES)
