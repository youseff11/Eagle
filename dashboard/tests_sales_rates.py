"""Sales read the rate talk (``User.sees_rate_talk``).

The rate words (``AppSettings.rate_keywords``) keep prices from the operation. Sales quote prices, so a client message
that names a rate on a Sales person's own number or address is theirs like any other: in the chat list, in the
conversation, in the mailbox, in its counters and its bell. The line rule still holds - the company line is not theirs,
rate talk or not - and the operation is still kept from every rate message.
"""

import json
from datetime import timedelta
from unittest import mock

from django.test import Client as DjangoClient
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from . import realtime, services
from .models import AppSettings, Channel, Client, InboundMessage, Role, User


def _json(response):
    return json.loads(response.content.decode("utf-8"))


class SalesReadRatesTests(TestCase):
    def setUp(self):
        make = lambda name, role: User.objects.create_user(name, password="pw", role=role)
        self.admin = make("person_admin", Role.ADMIN)
        self.ops = make("person_operation", Role.OPERATION)
        self.sales = make("person_salesman", Role.SALES)
        self.client_obj = Client.objects.create(name="Rate Client", phone="+201000000999", email="rates@example.test")
        now = timezone.now()
        self.chat = InboundMessage.objects.create(
            client=self.client_obj, channel=Channel.WHATSAPP, body="WHAT IS YOUR RATE PER PAGE", owner=self.sales,
            external_id="wamid.rate1", received_at=now - timedelta(minutes=5), is_rate_blocked=True, blocked_keyword="rate",
        )
        self.letter = InboundMessage.objects.create(
            client=self.client_obj, channel=Channel.EMAIL, subject="PRICE QUESTION", body="SEND THE PRICE LIST",
            owner=self.sales, sender_identity="rates@example.test", thread_key="kr", external_id="<r1@mail.test>",
            received_at=now - timedelta(minutes=4), is_rate_blocked=True, blocked_keyword="price",
        )
        # The same talk on the company line: the operation's line, and the rate rule keeps it from them.
        self.company = InboundMessage.objects.create(
            client=self.client_obj, channel=Channel.EMAIL, subject="COMPANY PRICE", body="COMPANY RATE WORDS",
            sender_identity="rates@example.test", thread_key="kc", external_id="<c1@mail.test>",
            received_at=now - timedelta(minutes=3), is_rate_blocked=True, blocked_keyword="price",
        )

    def get(self, user, name, args=None, **query):
        browser = DjangoClient()
        browser.force_login(user)
        answer = browser.get(reverse(name, args=args), query)
        return answer

    def test_the_rule_is_the_admin_and_sales_and_nobody_else(self):
        self.assertTrue(self.admin.sees_rate_talk)
        self.assertTrue(self.sales.sees_rate_talk)
        self.assertFalse(self.ops.sees_rate_talk)
        for role in (Role.TEAM_LEAD, Role.TRANSLATOR, Role.HR, Role.REVIEWER, Role.ACCOUNTING, Role.SUPPORT):
            self.assertFalse(User(role=role).sees_rate_talk, role)

    def test_sales_see_the_rate_chat_on_their_own_number(self):
        rows = _json(self.get(self.sales, "dashboard:v1_chats", type="clients"))["items"]
        self.assertIn(self.client_obj.code, [row["code"] for row in rows])
        answer = self.get(self.sales, "dashboard:v1_client_messages", [self.client_obj.code])
        self.assertEqual(answer.status_code, 200)
        self.assertIn("WHAT IS YOUR RATE PER PAGE", answer.content.decode("utf-8"))
        self.assertTrue(self.chat.visible_to(self.sales))
        self.assertEqual(services.unread_by_client(self.sales, [self.client_obj.pk]), {self.client_obj.pk: 1})

    def test_sales_read_the_rate_letter_on_their_own_address_and_it_counts(self):
        body = _json(self.get(self.sales, "dashboard:v1_mail_threads"))
        self.assertEqual([row["subject"] for row in body["threads"]], ["PRICE QUESTION"])
        self.assertEqual((body["unseen"], body["unclaimed"]), (1, 1))
        answer = self.get(self.sales, "dashboard:v1_mail_thread", [self.letter.pk])
        self.assertEqual(answer.status_code, 200)
        self.assertIn("SEND THE PRICE LIST", answer.content.decode("utf-8"))

    def test_the_company_line_is_still_not_theirs(self):
        self.assertFalse(self.company.visible_to(self.sales))
        self.assertEqual(self.get(self.sales, "dashboard:v1_mail_thread", [self.company.pk]).status_code, 404)
        self.assertNotIn("COMPANY PRICE", self.get(self.sales, "dashboard:v1_mail_threads").content.decode("utf-8"))

    def test_the_operation_is_still_kept_from_every_rate_message(self):
        self.assertFalse(self.company.visible_to(self.ops))
        mail = self.get(self.ops, "dashboard:v1_mail_threads")
        self.assertNotIn("COMPANY PRICE", mail.content.decode("utf-8"))
        self.assertEqual((_json(mail)["unseen"], _json(mail)["unclaimed"]), (0, 0))
        self.assertEqual(self.get(self.ops, "dashboard:v1_mail_thread", [self.company.pk]).status_code, 404)
        self.assertEqual(self.get(self.ops, "dashboard:v1_mail_thread", [self.letter.pk]).status_code, 404)

    def test_a_rate_letter_to_a_sales_persons_address_rings_them(self):
        conf = AppSettings.load()
        conf.rate_keywords = "price"
        conf.save()
        with mock.patch.object(realtime, "_deliver") as deliver, self.captureOnCommitCallbacks(execute=True):
            message = services.ingest_message(
                channel=Channel.EMAIL, sender_identity="someone@example.test", subject="Hello",
                body="What is your price per page", owner=self.sales,
            )
        self.assertTrue(message.is_rate_blocked)
        told = set()
        for call in deliver.call_args_list:
            ids, event = call.args
            if event.get("t") == realtime.NOTIFY:
                told.update(ids)
        self.assertEqual(told, {self.sales.pk, self.admin.pk})
