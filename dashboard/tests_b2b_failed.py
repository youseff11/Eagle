"""A WhatsApp message Meta took and then reported as not delivered (15/10/2026): the B2B row it marked is not «contacted» by
it, and «أداء المبيعات» counts it under «رسايل فشلت»."""

import importlib
import json
from unittest import mock

from django.apps import apps
from django.test import Client as DjangoClient
from django.utils import timezone

from . import b2b, services, whatsapp
from .models import Channel, Lead, LeadActivity, LeadSheet, LeadStatus, OutboundMessage
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

    def test_the_api_carries_the_reasons(self):
        self.send()
        services.record_whatsapp_status("wamid.intro.1", "failed", FAILED)
        body = json.loads(self.get(self.sales, "v1_b2b_kpis").content.decode("utf-8"))
        self.assertEqual([(r["key"], r["count"]) for r in body["rows"][0]["failed_reasons"]], [("marketing_limit", 1)])
        self.assertEqual(body["total"]["failed_reasons"][0]["key"], "marketing_limit")

    def test_the_migration_puts_right_the_rows_marked_before(self):
        out = self.send()
        # Failed before this existed: the message is failed, the row still says «contacted».
        OutboundMessage.objects.filter(pk=out.pk).update(status=OutboundMessage.Status.FAILED)
        importlib.import_module("dashboard.migrations.0075_unmark_failed_whatsapp").unmark(apps, None)
        self.lead.refresh_from_db()
        self.assertEqual((self.lead.status, self.lead.whatsapp_at), (LeadStatus.NEW, None))


class FailReasonTests(_B2b):
    """«ليه الرسايل فشلت» (17/10/2026): every failed message under a reason a manager can act on, per Sales person."""

    def failed(self, client, owner, error):
        return OutboundMessage.objects.create(
            client=client, kind=OutboundMessage.Kind.CHAT, created_by=owner, owner=owner, channel=Channel.WHATSAPP,
            to_identity="+447700900123", body="hi", status=OutboundMessage.Status.FAILED, error_message=error,
        )

    def test_each_reason_is_named(self):
        cases = {
            FAILED: "marketing_limit",
            "This message was not delivered to maintain healthy ecosystem engagement.": "marketing_limit",
            "(#131026) Message Undeliverable.": "not_on_whatsapp",
            "Message Undeliverable.": "not_on_whatsapp",
            whatsapp.ERROR_HINTS[131026][0]: "not_on_whatsapp",
            "(#131050) Unable to deliver the message. This user has stopped marketing messages.": "opted_out",
            whatsapp.ERROR_HINTS[131047][0]: "window",
            "(#131048) Spam rate limit hit": "too_many",
            whatsapp.ERROR_HINTS[131056][0]: "too_many",
            "(#132001) Template name does not exist in the translation": "template",
            whatsapp.ERROR_HINTS[190][0]: "account",
            "": "unknown",
            "WhatsApp reported the message as not delivered.": "unknown",
            services.SEND_UNSURE_AR: "unsure",
        }
        for text, key in cases.items():
            self.assertEqual(b2b.failure_reason(text)[0], key, text)

    def test_an_unknown_reason_keeps_metas_words(self):
        key, ar, en = b2b.failure_reason("(#131000) Something went wrong")
        self.assertEqual((key, ar, en), ("other:(#131000) Something went wrong",) + ("(#131000) Something went wrong",) * 2)

    def test_counted_per_sales_person_and_for_the_team(self):
        b2b.start_whatsapp(self.lead, self.sales)
        services.record_whatsapp_status("wamid.intro.1", "failed", FAILED)
        client = Lead.objects.get(pk=self.lead.pk).client
        # Two failures with the same words are two, not one.
        self.failed(client, self.sales, "(#131026) Message Undeliverable.")
        self.failed(client, self.sales, "(#131026) Message Undeliverable.")
        self.failed(client, self.sales, "(#131000) Something went wrong")
        spain = LeadSheet.objects.create(title="Spain", assigned_to=self.other, created_by=self.manager)
        theirs = Lead.objects.create(sheet=spain, company_name="Traduce SL", country="Spain", whatsapp="+34 600 000 001")
        self.template.return_value = "wamid.intro.2"
        b2b.start_whatsapp(theirs, self.other)
        services.record_whatsapp_status("wamid.intro.2", "failed", "Message Undeliverable.")

        today = timezone.localdate()
        rows, total = b2b.kpis(self.manager, today, today)
        by = {row["person"]["id"]: {r["key"]: r["count"] for r in row["failed_reasons"]} for row in rows}
        self.assertEqual(by[self.sales.pk], {"not_on_whatsapp": 2, "marketing_limit": 1, "other:(#131000) Something went wrong": 1})
        self.assertEqual(by[self.other.pk], {"not_on_whatsapp": 1})
        for row in rows:
            self.assertEqual(sum(r["count"] for r in row["failed_reasons"]), row["failed"])
        self.assertEqual(
            [(r["key"], r["count"]) for r in total["failed_reasons"]],
            [("not_on_whatsapp", 3), ("marketing_limit", 1), ("other:(#131000) Something went wrong", 1)],
        )

    def test_the_webhook_keeps_metas_code(self):
        b2b.start_whatsapp(self.lead, self.sales)
        payload = {"entry": [{"changes": [{"value": {
            "metadata": {"phone_number_id": "900002"},
            "statuses": [{"id": "wamid.intro.1", "status": "failed", "recipient_id": "447700900123", "errors": [{
                "code": 131049, "title": "This message was not delivered to maintain healthy ecosystem engagement.",
                "error_data": {"details": "In order to maintain a healthy ecosystem engagement, the message failed to be delivered."},
            }]}],
        }}]}]}
        response = DjangoClient().post("/webhooks/whatsapp/", data=json.dumps(payload), content_type="application/json")
        self.assertEqual(response.status_code, 200)
        out = OutboundMessage.objects.get(provider_id="wamid.intro.1")
        self.assertEqual(out.status, OutboundMessage.Status.FAILED)
        self.assertTrue(out.error_message.startswith("(#131049) "), out.error_message)
        self.assertEqual(b2b.failure_reason(out.error_message)[0], "marketing_limit")

    def test_a_refused_send_keeps_metas_code_when_no_hint_names_it(self):
        self.template.side_effect = whatsapp.WhatsAppError("واتساب رجّع خطأ (400): Something went wrong", code=131000)
        with self.assertRaises(b2b.Refused):
            b2b.start_whatsapp(self.lead, self.sales)
        out = OutboundMessage.objects.get(client__leads=self.lead)
        self.assertTrue(out.error_message.startswith("(#131000) "), out.error_message)
        # A hint already says it in words: kept as it is.
        OutboundMessage.objects.all().delete()
        self.template.side_effect = whatsapp.WhatsAppError(whatsapp.ERROR_HINTS[131026][0], code=131026)
        with self.assertRaises(b2b.Refused):
            b2b.start_whatsapp(self.lead, self.sales)
        self.assertEqual(OutboundMessage.objects.get(client__leads=self.lead).error_message, whatsapp.ERROR_HINTS[131026][0])

    def test_with_code_does_not_say_it_twice(self):
        self.assertEqual(whatsapp.with_code("(#131049) x", 131049), "(#131049) x")
        self.assertEqual(whatsapp.with_code("x", None), "x")
        self.assertEqual(whatsapp.with_code("x", 4), "(#4) x")
