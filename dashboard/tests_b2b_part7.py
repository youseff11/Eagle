"""B2B part 7: a company that writes first becomes a row by itself, the follow-up reminder by e-mail, and the Sales targets
with their alerts (``b2b.auto_lead``, ``b2b._email_reminder``, ``b2b.save_target`` / ``check_targets``)."""

from decimal import Decimal

from django.urls import reverse
from django.utils import timezone

from . import b2b, services
from .models import AppSettings, AuditLog, Channel, Lead, Quotation, SalesTarget, User
from .tests_b2b import PHONE, _B2b, _json

NEW_PHONE = "+33 6 12 34 56 78"


def _setting(**values):
    conf = AppSettings.load()
    for name, value in values.items():
        setattr(conf, name, value)
    conf.save()


class AutoLeadTests(_B2b):
    def ingest(self, sender=NEW_PHONE, owner=None, channel=Channel.WHATSAPP, external_id="wamid.auto.1", **kw):
        return services.ingest_message(
            channel=channel, body="Hello, we need a translator", sender_identity=sender, sender_display="Pierre Martin",
            external_id=external_id, owner=owner, **kw,
        )

    def auto_rows(self, person=None):
        return Lead.objects.filter(sheet__title=b2b.AUTO_SHEET_TITLE, sheet__assigned_to=person or self.sales)

    def test_a_new_company_writing_to_a_sales_line_becomes_a_row(self):
        message = self.ingest(owner=self.sales)
        lead = self.auto_rows().get()
        self.assertEqual((lead.contact_person, lead.whatsapp, lead.source, lead.client_id), ("Pierre Martin", NEW_PHONE, "واتساب وارد", message.client_id))
        self.assertEqual(lead.replied_at, message.received_at)
        self.assertTrue(self.sales.notifications.filter(url=f"/app/leads/{lead.sheet_id}").exists())
        self.assertTrue(AuditLog.objects.filter(action="b2b.auto_lead").exists())
        # The second message is the same company: no second row.
        self.ingest(owner=self.sales, external_id="wamid.auto.2")
        self.assertEqual(self.auto_rows().count(), 1)

    def test_the_company_line_and_a_known_company_make_no_row(self):
        self.ingest(owner=None)
        # Lingua is on this person's sheet already, and another person's line does not copy it either.
        self.ingest(sender=PHONE, owner=self.other, external_id="wamid.auto.3")
        self.assertFalse(Lead.objects.filter(sheet__title=b2b.AUTO_SHEET_TITLE).exists())

    def test_the_setting_turns_it_off(self):
        _setting(b2b_auto_leads=False)
        self.ingest(owner=self.sales)
        self.assertFalse(self.auto_rows().exists())

    def test_an_automatic_sender_makes_no_row_and_a_letter_does(self):
        self.ingest(sender="no-reply@bank.test", owner=self.sales, channel=Channel.EMAIL, external_id="<a@bank>", recipients=["seller@eagle.test"])
        self.assertFalse(self.auto_rows().exists())
        self.ingest(sender="info@newco.test", owner=self.sales, channel=Channel.EMAIL, external_id="<b@newco>", recipients=["seller@eagle.test"])
        lead = self.auto_rows().get()
        self.assertEqual((lead.email, lead.source), ("info@newco.test", "إيميل وارد"))

    def test_an_operation_persons_own_address_is_not_a_sales_line(self):
        User.objects.filter(pk=self.ops.pk).update(mail_alias="ops1@eagle.test")
        self.ingest(sender="info@newco.test", channel=Channel.EMAIL, external_id="<c@newco>", recipients=["ops1@eagle.test"])
        self.assertFalse(Lead.objects.filter(sheet__title=b2b.AUTO_SHEET_TITLE).exists())


class ReminderEmailTests(_B2b):
    def setUp(self):
        super().setUp()
        Lead.objects.filter(pk=self.lead.pk).update(next_follow_up=timezone.localdate())
        User.objects.filter(pk=self.sales.pk).update(email="seller.home@example.test")
        self.sales.refresh_from_db()

    def remind(self):
        return b2b.daily_digest(self.sales, now=timezone.localtime().replace(hour=10))

    def test_off_by_default(self):
        self.assertIsNotNone(self.remind())
        self.mail.assert_not_called()

    def test_on_it_goes_to_the_accounts_own_address(self):
        _setting(b2b_reminder_email=True)
        self.remind()
        args, kwargs = self.mail.call_args
        self.assertEqual(args[1], "seller.home@example.test")
        self.assertIn("1 النهارده", kwargs["body"])
        self.assertNotIn("Lingua", kwargs["body"])

    def test_never_to_a_company_mailbox_address(self):
        _setting(b2b_reminder_email=True)
        User.objects.filter(pk=self.sales.pk).update(email="seller@eagle.test")
        self.sales.refresh_from_db()
        self.remind()
        self.mail.assert_not_called()

    def test_a_mail_that_fails_does_not_take_the_notice_with_it(self):
        _setting(b2b_reminder_email=True)
        self.mail.side_effect = RuntimeError("smtp down")
        self.assertIsNotNone(self.remind())


class TargetTests(_B2b):
    def setUp(self):
        super().setUp()
        self.first = timezone.localdate().replace(day=1)
        self.month = f"{self.first:%Y-%m}"

    def set_target(self, user=None, person=None, **figures):
        body = {"person": (person or self.sales).pk, "month": self.month, "revenue_currency": "USD", **figures}
        return self.post(user or self.manager, "v1_b2b_target_save", body)

    def rows(self, user):
        return _json(self.browser(user).get(reverse("dashboard:v1_b2b_targets"), {"month": self.month}))

    def test_the_manager_sets_a_target_and_nobody_else_does(self):
        self.assertEqual(self.set_target(new_leads=10).status_code, 200)
        self.assertEqual(SalesTarget.objects.get().new_leads, 10)
        self.assertEqual(self.set_target(self.sales, won=99).status_code, 403)
        self.assertEqual(self.post(self.ops, "v1_b2b_target_save", {"person": self.sales.pk}).status_code, 403)
        self.assertEqual(_json(self.set_target(person=self.manager, won=1))["error"], "no_sales")
        for bad in ({"won": -1}, {"won": "5"}, {"revenue": "abc"}, {"month": "2026-13"}):
            self.assertEqual(self.set_target(**bad).status_code, 400, bad)
        self.assertEqual(SalesTarget.objects.get().won, None)

    def test_progress_for_who_may_read_it(self):
        self.set_target(new_leads=4, revenue="100")
        Lead.objects.create(sheet=self.sheet, company_name="Two")
        mine = self.rows(self.sales)
        self.assertFalse(mine["can_edit"])
        self.assertEqual([r["person"]["id"] for r in mine["rows"]], [self.sales.pk])
        progress = mine["rows"][0]["progress"]
        self.assertEqual(progress["new_leads"], {"target": 4, "done": 2, "percent": 50})
        self.assertEqual(progress["won"]["percent"], None)
        self.assertEqual(progress["revenue"], {"target": "100.00", "done": "0.00", "percent": 0})
        team = self.rows(self.manager)
        self.assertTrue(team["can_edit"])
        self.assertEqual({r["person"]["id"] for r in team["rows"]}, {self.sales.pk, self.other.pk})
        self.assertEqual(self.browser(self.ops).get(reverse("dashboard:v1_b2b_targets")).status_code, 403)

    def test_a_reached_target_is_told_once_to_the_person_and_the_managers(self):
        self.set_target(new_leads=1)
        self.assertEqual(b2b.check_targets(), 1)
        self.assertEqual(b2b.check_targets(), 0)
        for person in (self.sales, self.manager, self.admin):
            self.assertEqual(person.notifications.filter(title_en="Target reached").count(), 1, person.username)
        self.assertFalse(self.other.notifications.filter(title_en="Target reached").exists())

    def test_behind_from_the_twentieth_once(self):
        self.set_target(new_leads=10)
        early = self.first.replace(day=19)
        late = self.first.replace(day=21)
        self.assertEqual(b2b.check_targets(early), 0)
        self.assertEqual(b2b.check_targets(late), 1)
        self.assertEqual(b2b.check_targets(late), 0)
        self.assertEqual(self.sales.notifications.filter(title_en="Behind the target").count(), 1)

    def test_new_figures_let_the_alerts_go_again(self):
        self.set_target(new_leads=1)
        b2b.check_targets()
        self.set_target(new_leads=1)
        self.assertEqual(SalesTarget.objects.get().alerts, [])
        self.assertEqual(b2b.check_targets(), 1)

    def test_revenue_counts_only_the_targets_currency(self):
        self.set_target(revenue="50")
        Quotation.objects.create(lead=self.lead, owner=self.sales, source_lang="EN", target_lang="AR", quantity=1, rate=Decimal("80"),
                                 total=Decimal("80"), currency="EUR", status="accepted", decided_at=timezone.now())
        self.assertEqual(self.rows(self.sales)["rows"][0]["progress"]["revenue"]["percent"], 0)
        Quotation.objects.update(currency="USD")
        self.assertEqual(self.rows(self.sales)["rows"][0]["progress"]["revenue"]["percent"], 160)

