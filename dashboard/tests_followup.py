"""«رسالة متابعة»: the approved template that goes on with a client chat after WhatsApp's 24-hour window closed."""

import json
from datetime import timedelta
from unittest import mock

from django.test import Client as DjangoClient
from django.test import TestCase
from django.urls import resolve, reverse
from django.utils import timezone

from . import api_v1, followup, whatsapp
from .models import AuditLog, Channel, Client, InboundMessage, OutboundMessage, Role, User

COMPANY = "ACME Secret Ltd"
PHONE = "+201001234567"


def _json(response):
    return json.loads(response.content.decode("utf-8"))


class _Site(TestCase):
    def setUp(self):
        make = lambda name, role, **kw: User.objects.create_user(name, password="pw", role=role, **kw)
        self.admin = make("person_admin", Role.ADMIN)
        self.ops = make("person_operation", Role.OPERATION)
        self.sales = make("person_salesman", Role.SALES, wa_phone_number_id="555000")
        self.tr = make("person_translator", Role.TRANSLATOR)
        self.client_obj = Client.objects.create(name="Mr Secret", company=COMPANY, phone=PHONE)
        # The client wrote to the company number a day and a half ago: that window is closed.
        self.inbound = InboundMessage.objects.create(
            client=self.client_obj, channel=Channel.WHATSAPP, body="hello", sender_identity=PHONE,
            received_at=timezone.now() - timedelta(hours=36),
        )
        self.template = mock.patch("dashboard.whatsapp.send_template", return_value="wamid.follow.1").start()
        self.addCleanup(mock.patch.stopall)

    def press(self, user, code=None, language="ar"):
        browser = DjangoClient()
        browser.force_login(user)
        return browser.post(
            reverse("dashboard:v1_client_followup", args=[code or self.client_obj.code]),
            data=json.dumps({"language": language}), content_type="application/json",
        )

    def open_row(self, user):
        browser = DjangoClient()
        browser.force_login(user)
        return _json(browser.get(reverse("dashboard:v1_client_messages", args=[self.client_obj.code])))["client"]


class SendTests(_Site):
    def test_the_door_is_the_api_one(self):
        self.assertIs(resolve(f"/api/v1/clients/{self.client_obj.code}/followup/").func, api_v1.client_followup)

    def test_the_operation_sends_the_arabic_template_from_the_company_number_with_the_company_greeted(self):
        answer = self.press(self.ops)
        self.assertEqual(answer.status_code, 200)
        self.assertTrue(_json(answer)["delivered"])
        self.template.assert_called_once_with(PHONE, "chat_followup_ar", "ar", [COMPANY], from_id="")
        row = OutboundMessage.objects.get()
        self.assertEqual(row.status, OutboundMessage.Status.SENT)
        self.assertIsNone(row.owner)
        self.assertEqual(row.provider_id, "wamid.follow.1")
        self.assertTrue(AuditLog.objects.filter(action="client.followup", target=self.client_obj.code).exists())

    def test_what_the_company_line_keeps_holds_the_code_not_the_company(self):
        answer = _json(self.press(self.ops))
        row = OutboundMessage.objects.get()
        self.assertIn(self.client_obj.code, row.body)
        self.assertNotIn("ACME", row.body)
        self.assertNotIn("ACME", json.dumps(answer, ensure_ascii=False))

    def test_english_when_asked(self):
        self.assertEqual(self.press(self.ops, language="en").status_code, 200)
        self.template.assert_called_once_with(PHONE, "chat_followup_en", "en", [COMPANY], from_id="")

    def test_a_language_it_does_not_have_is_refused(self):
        self.assertEqual(_json(self.press(self.ops, language="fr"))["error"], "bad_language")
        self.template.assert_not_called()

    def test_no_company_greets_the_client_politely(self):
        Client.objects.filter(pk=self.client_obj.pk).update(company="")
        self.press(self.ops)
        self.assertEqual(self.template.call_args.args[3], ["حضرتك"])
        self.assertIn("أهلًا حضرتك،", OutboundMessage.objects.get().body)

    def test_nothing_goes_while_the_window_is_open(self):
        InboundMessage.objects.filter(pk=self.inbound.pk).update(received_at=timezone.now() - timedelta(hours=2))
        answer = self.press(self.ops)
        self.assertEqual(answer.status_code, 409)
        self.assertEqual(_json(answer)["error"], "window_open")
        self.template.assert_not_called()
        self.assertFalse(OutboundMessage.objects.exists())

    def test_one_follow_up_a_day_while_the_client_has_not_answered(self):
        self.assertEqual(self.press(self.ops).status_code, 200)
        again = self.press(self.ops, language="en")
        self.assertEqual(again.status_code, 409)
        self.assertEqual(_json(again)["error"], "sent_recently")
        self.assertEqual(self.template.call_count, 1)
        self.assertTrue(self.open_row(self.ops)["followup"]["sent_recently"])

    def test_a_failed_follow_up_does_not_count_as_sent(self):
        self.template.side_effect = whatsapp.WhatsAppError("واتساب رفض", "Meta said no")
        answer = self.press(self.ops)
        self.assertEqual(answer.status_code, 200)
        self.assertFalse(_json(answer)["delivered"])
        self.assertEqual(OutboundMessage.objects.get().status, OutboundMessage.Status.FAILED)
        self.template.side_effect = None
        self.assertTrue(_json(self.press(self.ops))["delivered"])

    def test_a_blocked_client_gets_nothing(self):
        Client.objects.filter(pk=self.client_obj.pk).update(blocked_at=timezone.now())
        answer = self.press(self.ops)
        self.assertEqual(answer.status_code, 409)
        self.assertEqual(_json(answer)["error"], "blocked")
        self.template.assert_not_called()

    def test_a_translator_may_not(self):
        self.assertEqual(self.press(self.tr).status_code, 403)
        self.template.assert_not_called()

    def test_a_client_off_this_persons_line_answers_like_an_unknown_one(self):
        # Only ever written to a Sales person's own number: the operation has no line in it.
        InboundMessage.objects.filter(pk=self.inbound.pk).update(owner=self.sales)
        answer = self.press(self.ops)
        self.assertEqual(answer.status_code, 404)
        self.assertEqual(self.press(self.ops, code="CL-9999").status_code, 404)
        self.template.assert_not_called()

    def test_sales_sends_from_their_own_number_and_even_their_line_keeps_the_code(self):
        # A row is carried further than its line (an admin forwards it to the operation as it is): no name in it.
        InboundMessage.objects.filter(pk=self.inbound.pk).update(owner=self.sales)
        self.assertEqual(self.press(self.sales).status_code, 200)
        self.template.assert_called_once_with(PHONE, "chat_followup_ar", "ar", [COMPANY], from_id="555000")
        row = OutboundMessage.objects.get()
        self.assertEqual(row.owner, self.sales)
        self.assertNotIn("ACME", row.body)
        self.assertIn(self.client_obj.code, row.body)

    def test_the_admin_writes_to_a_sales_client_who_never_answered_from_the_sales_number(self):
        # Only the Sales person's opening message: no message from the client on any line. The company number would be
        # a stranger to them, and would hand the client to the operation's line.
        InboundMessage.objects.all().delete()
        OutboundMessage.objects.create(
            client=self.client_obj, kind=OutboundMessage.Kind.CHAT, created_by=self.sales, owner=self.sales,
            channel=Channel.WHATSAPP, to_identity=PHONE, body="opening", status=OutboundMessage.Status.SENT,
            created_at=timezone.now() - timedelta(days=3),
        )
        OutboundMessage.objects.filter(body="opening").update(created_at=timezone.now() - timedelta(days=3))
        self.assertEqual(self.press(self.admin).status_code, 200)
        self.template.assert_called_once_with(PHONE, "chat_followup_ar", "ar", [COMPANY], from_id="555000")
        self.assertEqual(OutboundMessage.objects.exclude(body="opening").get().owner, self.sales)
        self.assertEqual(self.press(self.ops).status_code, 404)

    def test_the_answer_opens_the_window_again(self):
        self.press(self.ops)
        InboundMessage.objects.create(
            client=self.client_obj, channel=Channel.WHATSAPP, body="yes", sender_identity=PHONE, received_at=timezone.now(),
        )
        row = self.open_row(self.ops)
        self.assertTrue(row["window_open"])
        self.assertIsNone(row["followup"])


class OfferTests(_Site):
    def test_offered_while_closed_with_the_language_of_the_number(self):
        offer = self.open_row(self.ops)["followup"]
        self.assertEqual(offer["language"], "ar")
        self.assertFalse(offer["sent_recently"])
        self.assertIn(self.client_obj.code, offer["texts"]["ar"])
        self.assertIn(self.client_obj.code, offer["texts"]["en"])

    def test_the_operation_never_reads_the_company(self):
        self.assertNotIn("ACME", json.dumps(self.open_row(self.ops), ensure_ascii=False))

    def test_the_admin_reads_it_as_the_client_will(self):
        offer = self.open_row(self.admin)["followup"]
        self.assertTrue(offer["texts"]["ar"].startswith(f"أهلًا {COMPANY}،"))
        self.assertTrue(offer["texts"]["en"].startswith(f"Hello {COMPANY},"))

    def test_a_foreign_number_suggests_english(self):
        Client.objects.filter(pk=self.client_obj.pk).update(phone="+491701234567")
        InboundMessage.objects.filter(pk=self.inbound.pk).update(sender_identity="+491701234567")
        self.assertEqual(self.open_row(self.ops)["followup"]["language"], "en")

    def test_not_offered_for_a_client_off_this_persons_line(self):
        InboundMessage.objects.filter(pk=self.inbound.pk).update(owner=self.sales)
        self.assertIsNone(followup.offer(self.client_obj, self.ops))
        self.assertIsNotNone(followup.offer(self.client_obj, self.sales))

    def test_not_offered_to_a_blocked_client(self):
        Client.objects.filter(pk=self.client_obj.pk).update(blocked_at=timezone.now())
        self.assertIsNone(self.open_row(self.ops)["followup"])


class TemplateRulesTests(TestCase):
    def test_both_follow_the_three_rules_and_are_submitted_by_the_command(self):
        from .management.commands.wa_templates import TEMPLATES

        self.assertEqual(set(followup.FOLLOWUP_TEMPLATES), {"ar", "en"})
        for language, (name, spec) in followup.FOLLOWUP_TEMPLATES.items():
            self.assertEqual(spec["language"], language)
            count = spec["body"].count("{{")
            self.assertEqual(count, 1, name)
            self.assertEqual(len(spec["example"]), count, name)
            self.assertFalse(spec["body"].lstrip().startswith("{{"), name)
            self.assertFalse(spec["body"].rstrip().rstrip(".?!؟").endswith("}}"), name)
            self.assertIs(TEMPLATES[name], spec)
