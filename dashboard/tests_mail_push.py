"""A letter that lands rings the people it is for, the moment it is recorded.

The chain is: the worker's IMAP IDLE connection (``mailbox.watch``) says "new mail", ``mailbox.fetch_and_record`` stores
the letter with ``services.ingest_message``, which notifies the people it is for, and a new ``Notification`` rings its
owner's socket (``signals.push_notification``). The page then asks the API again (``RealtimeProvider.handleEvent``).
This file holds the middle of it - who is rung for which letter - so that nobody who adds a way for mail to arrive can
leave the bell out, and so that a letter is never rung to a person who must not see it.
"""

from unittest import mock

from django.test import TestCase

from . import realtime, services
from .models import AppSettings, Channel, Role, User


class LetterRingsTests(TestCase):
    def setUp(self):
        make = lambda name, role: User.objects.create_user(name, password="pw", role=role)
        self.admin = make("person_admin", Role.ADMIN)
        self.ops = make("person_operation", Role.OPERATION)
        self.other_ops = make("person_operation_two", Role.OPERATION)
        self.sales = make("person_salesman", Role.SALES)
        self.other_sales = make("person_salesman_two", Role.SALES)
        self.translator = make("person_translator", Role.TRANSLATOR)

    def rung(self, **kwargs):
        """The people a new letter rings: the ids that were told ``notify``, and nothing else was told."""
        with mock.patch.object(realtime, "_deliver") as deliver, self.captureOnCommitCallbacks(execute=True):
            services.ingest_message(
                channel=kwargs.pop("channel", Channel.EMAIL), sender_identity=kwargs.pop("sender", "client@example.com"),
                subject="Hello", body=kwargs.pop("body", "A document to translate"), **kwargs,
            )
        told = set()
        for call in deliver.call_args_list:
            ids, event = call.args
            if event.get("t") == realtime.NOTIFY:
                told.update(ids)
        return told

    def test_a_letter_to_the_company_rings_the_operation_and_the_admin(self):
        self.assertEqual(self.rung(), {self.ops.pk, self.other_ops.pk, self.admin.pk})

    def test_a_letter_to_a_sales_persons_own_address_rings_them_and_the_admin_but_not_the_operation(self):
        self.assertEqual(self.rung(owner=self.sales), {self.sales.pk, self.admin.pk})

    def test_a_letter_to_no_ones_address_rings_the_admin_alone_when_the_admin_keeps_those(self):
        conf = AppSettings.load()
        conf.mail_unassigned_admin_only = True
        conf.save()
        self.assertEqual(self.rung(), {self.admin.pk})

    def test_a_letter_about_rates_rings_the_admin_alone(self):
        conf = AppSettings.load()
        conf.rate_keywords = "price"
        conf.save()
        self.assertEqual(self.rung(body="What is your price per page"), {self.admin.pk})

    def test_the_same_letter_arriving_twice_rings_once(self):
        with mock.patch.object(realtime, "_deliver") as deliver, self.captureOnCommitCallbacks(execute=True):
            for _ in range(2):
                services.ingest_message(
                    channel=Channel.EMAIL, sender_identity="client@example.com", subject="Hello", body="Hi",
                    external_id="<one-letter@example.com>",
                )
        first = deliver.call_count
        self.assertGreater(first, 0)
        with mock.patch.object(realtime, "_deliver") as again, self.captureOnCommitCallbacks(execute=True):
            services.ingest_message(
                channel=Channel.EMAIL, sender_identity="client@example.com", subject="Hello", body="Hi",
                external_id="<one-letter@example.com>",
            )
        self.assertEqual(again.call_count, 0)

    def test_the_ring_carries_a_kind_and_nothing_about_the_letter(self):
        with mock.patch.object(realtime, "_deliver") as deliver, self.captureOnCommitCallbacks(execute=True):
            services.ingest_message(
                channel=Channel.EMAIL, sender_identity="secret-client@example.com", subject="Private subject",
                body="Private words",
            )
        # A loop over no calls would pass for a bell that never rang.
        self.assertGreater(deliver.call_count, 0)
        for call in deliver.call_args_list:
            self.assertEqual(realtime.clean_event(call.args[1]), {"t": realtime.NOTIFY})
            self.assertNotIn("secret-client", repr(call))
            self.assertNotIn("Private", repr(call))
