"""Smoke tests for the Eagle workflow engine."""

from datetime import timedelta
from decimal import Decimal

from django.test import TestCase
from django.utils import timezone

from . import services
from .models import (
    AppSettings,
    AssignmentStatus,
    Client,
    Role,
    Task,
    TaskStatus,
    User,
)


class WorkflowTests(TestCase):
    def setUp(self):
        self.ops = User.objects.create_user("ops", password="x", role=Role.OPERATION)
        self.lead = User.objects.create_user("lead", password="x", role=Role.TEAM_LEAD)
        self.tr = User.objects.create_user(
            "tr", password="x", role=Role.TRANSLATOR, team_lead=self.lead
        )
        self.client_obj = Client.objects.create(name="ACME", phone="+201000000000")

    def make_task(self):
        return services.create_task(
            client=self.client_obj, title="Doc", created_by=self.ops,
            deadline=timezone.now() + timedelta(hours=2),
        )

    def test_codes_are_sequential(self):
        self.assertTrue(self.client_obj.code.startswith("CL-"))
        self.assertTrue(self.make_task().code.startswith("TSK-"))

    def test_rate_keyword_hides_message(self):
        msg = services.ingest_message(
            channel="whatsapp", body="what is your rate for 10 pages?",
            sender_identity="+201000000000",
        )
        self.assertTrue(msg.is_rate_blocked)
        self.assertFalse(msg.visible_to(self.ops))

    def test_client_identity_is_masked(self):
        self.assertEqual(self.client_obj.label_for(self.ops), self.client_obj.code)

    def test_full_happy_path(self):
        task = self.make_task()
        a1 = services.assign_to_lead(task, self.lead, self.ops)
        self.assertEqual(a1.status, AssignmentStatus.PENDING)
        ok, _ = services.accept_assignment(a1, self.lead)
        self.assertTrue(ok)
        task.refresh_from_db()
        self.assertEqual(task.status, TaskStatus.LEAD_ACCEPTED)

        a2 = services.assign_to_translator(task, self.tr, self.lead)
        ok, _ = services.accept_assignment(a2, self.tr)
        self.assertTrue(ok)
        task.refresh_from_db()
        self.assertEqual(task.status, TaskStatus.IN_PROGRESS)
        self.assertEqual(task.rooms.count(), 2)

        services.mark_translated(task, self.tr)
        task.refresh_from_db()
        self.assertEqual(task.status, TaskStatus.UNDER_REVIEW)
        services.mark_reviewed(task, self.lead)
        task.refresh_from_db()
        self.assertEqual(task.status, TaskStatus.REVIEWED)
        services.mark_delivered(task, self.ops)
        task.refresh_from_db()
        self.assertEqual(task.status, TaskStatus.DELIVERED)

    def test_expired_assignment_costs_an_eighth_of_a_star(self):
        task = self.make_task()
        assignment = services.assign_to_lead(task, self.lead, self.ops)
        assignment.expires_at = timezone.now() - timedelta(seconds=1)
        assignment.save(update_fields=["expires_at"])

        services.sweep_expired_assignments()
        assignment.refresh_from_db()
        self.lead.refresh_from_db()
        task.refresh_from_db()

        self.assertEqual(assignment.status, AssignmentStatus.EXPIRED)
        self.assertEqual(self.lead.rating, Decimal("4.875"))
        self.assertEqual(task.status, TaskStatus.NEW)
        self.assertIsNone(task.team_lead_id)

    def test_deadline_warning_fires_once(self):
        conf = AppSettings.load()
        task = self.make_task()
        services.assign_to_lead(task, self.lead, self.ops)
        task.refresh_from_db()
        task.deadline = timezone.now() + timedelta(minutes=conf.deadline_warning_minutes - 1)
        task.translator = self.tr
        task.save()

        self.assertEqual(services.sweep_deadlines(), 1)
        self.assertEqual(services.sweep_deadlines(), 0)
        self.assertTrue(
            self.tr.notifications.filter(title_en="Deadline approaching").exists()
        )
