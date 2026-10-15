"""A WhatsApp message Meta took and then reported as not delivered (15/10/2026): the B2B row it marked is not «contacted» by
it, and «أداء المبيعات» counts it under «رسايل فشلت»."""

import importlib
from unittest import mock

from django.apps import apps
from django.utils import timezone

from . import b2b, services
from .models import Lead, LeadActivity, LeadStatus, OutboundMessage
from .tests_b2b import _B2b

FAILED = "(#131049) This message was not delivered to maintain healthy ecosystem engagement."


class FailedAfterSendTests(_B2b):
    def send(self):
        b2b.start_whatsapp(self.lead, self.sales)
        self.lead.refresh_from_db()
        self.assertEqual(self.lead.status, LeadStatus.CONTACTED)
        return OutboundMessage.objects.get(provider_id="wamid.intro.1")

    def kpis(self):
        today = timezone.localdate()
        return b2b.kpis(self.sales, today, today)[0][0]

    def test_the_row_goes_back_to_new_and_the_numbers_agree(self):
        self.send()
        services.record_whatsapp_status("wamid.intro.1", "failed", FAILED)
        self.lead.refresh_from_db()
        self.assertEqual(self.lead.status, LeadStatus.NEW)
        self.assertEqual((self.lead.whatsapp_at, self.lead.last_outreach_at, self.lead.last_contact_at), (None, None, None))
        self.assertFalse(self.lead.activities.exists())
        row = self.kpis()
        self.assertEqual((row["contacted"], row["whatsapp"], row["failed"], row["untouched"]), (0, 0, 1, 1))
        # The conversation keeps its client: the next press starts from it.
        self.assertIsNotNone(self.lead.client_id)

    def test_a_second_failure_event_changes_nothing(self):
        self.send()
        services.record_whatsapp_status("wamid.intro.1", "failed", FAILED)
        stamp = Lead.objects.get(pk=self.lead.pk).updated_at
        services.record_whatsapp_status("wamid.intro.1", "failed", FAILED)
        self.assertEqual(Lead.objects.get(pk=self.lead.pk).updated_at, stamp)

    def test_another_message_that_day_that_went_keeps_the_row_contacted(self):
        first = self.send()
        second = OutboundMessage.objects.create(
            client=first.client, kind=OutboundMessage.Kind.CHAT, created_by=self.sales, owner=self.sales,
            channel=first.channel, to_identity=first.to_identity, body="hello", status=OutboundMessage.Status.SENT,
            provider_id="wamid.text.2",
        )
        b2b.note_outbound(second)
        services.record_whatsapp_status("wamid.intro.1", "failed", FAILED)
        self.lead.refresh_from_db()
        self.assertEqual(self.lead.status, LeadStatus.CONTACTED)
        self.assertIsNotNone(self.lead.whatsapp_at)
        self.assertEqual(self.lead.activities.get(kind=LeadActivity.Kind.WHATSAPP).outbound_id, second.pk)
        row = self.kpis()
        self.assertEqual((row["contacted"], row["whatsapp"], row["failed"]), (1, 1, 1))

    def test_a_call_keeps_the_row_contacted(self):
        self.send()
        b2b.log_call(self.lead, self.sales, outcome="no_answer")
        services.record_whatsapp_status("wamid.intro.1", "failed", FAILED)
        self.lead.refresh_from_db()
        self.assertEqual(self.lead.status, LeadStatus.CONTACTED)
        self.assertIsNone(self.lead.whatsapp_at)
        self.assertIsNotNone(self.lead.call_at)

    def test_a_stage_chosen_by_hand_stays(self):
        self.send()
        b2b.note_status(self.lead, LeadStatus.CONTACTED, LeadStatus.FOLLOW_UP, self.sales)
        Lead.objects.filter(pk=self.lead.pk).update(status=LeadStatus.FOLLOW_UP)
        services.record_whatsapp_status("wamid.intro.1", "failed", FAILED)
        self.lead.refresh_from_db()
        self.assertEqual(self.lead.status, LeadStatus.FOLLOW_UP)
        self.assertIsNone(self.lead.whatsapp_at)

    def test_contacted_chosen_by_hand_stays(self):
        b2b.note_status(self.lead, LeadStatus.NEW, LeadStatus.CONTACTED, self.sales)
        Lead.objects.filter(pk=self.lead.pk).update(status=LeadStatus.CONTACTED)
        self.lead.refresh_from_db()
        self.send()
        services.record_whatsapp_status("wamid.intro.1", "failed", FAILED)
        self.lead.refresh_from_db()
        self.assertEqual(self.lead.status, LeadStatus.CONTACTED)
        self.assertIsNone(self.lead.whatsapp_at)

    def test_their_own_message_is_not_ours(self):
        self.send()
        at = timezone.now()
        LeadActivity.objects.create(lead=self.lead, kind=LeadActivity.Kind.WHATSAPP, incoming=True, automatic=True, at=at, owner=self.sales)
        services.record_whatsapp_status("wamid.intro.1", "failed", FAILED)
        self.lead.refresh_from_db()
        self.assertEqual((self.lead.whatsapp_at, self.lead.last_outreach_at, self.lead.last_contact_at), (None, None, at))

    def test_a_message_already_read_is_not_failed_and_not_unmarked(self):
        self.send()
        services.record_whatsapp_status("wamid.intro.1", "read")
        services.record_whatsapp_status("wamid.intro.1", "failed", FAILED)
        self.lead.refresh_from_db()
        self.assertEqual(self.lead.status, LeadStatus.CONTACTED)
        self.assertEqual(self.kpis()["failed"], 0)

    def test_the_sheet_breaking_does_not_lose_the_status(self):
        out = self.send()
        with mock.patch("dashboard.b2b.unmark_failed", side_effect=RuntimeError("boom")):
            services.record_whatsapp_status("wamid.intro.1", "failed", FAILED)
        out.refresh_from_db()
        self.assertEqual(out.status, OutboundMessage.Status.FAILED)

    def test_the_migration_puts_right_the_rows_marked_before(self):
        out = self.send()
        # Failed before this existed: the message is failed, the row still says «contacted».
        OutboundMessage.objects.filter(pk=out.pk).update(status=OutboundMessage.Status.FAILED)
        importlib.import_module("dashboard.migrations.0075_unmark_failed_whatsapp").unmark(apps, None)
        self.lead.refresh_from_db()
        self.assertEqual((self.lead.status, self.lead.whatsapp_at), (LeadStatus.NEW, None))
