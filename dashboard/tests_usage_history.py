"""«سجل الدفع»: each host's bill month by month (``usage_history.py``, ``/api/v1/admin/usage/months/``).

What these tests hold: only the admin is answered, and the page never asks a host; what the usage panel reads is the running
month's row; a month that is over is closed with each host's figure for the whole of it (Neon, Render and Meta asked for the
month's own dates, Claude counted from our rows of that month only, Bunny's last figure read during the month); what cannot be
known is ``None`` and never a zero; a host that failed at the closing is asked again for a few days and then left; the closing
runs at most once an hour and the heartbeat hands it to a thread only when something is due.
"""

import urllib.parse
from datetime import date, datetime
from datetime import timezone as dt_timezone
from decimal import Decimal
from unittest import mock

from django.test import Client as DjangoClient
from django.urls import reverse

from . import usage, usage_history
from .models import AppSettings, UsageMonth, User
from .tests_usage import KEYS, META_PRICING, META_URL, _Hosts, _Usage

URL = "dashboard:v1_admin_usage_months"
#: 02/11/2026: October is over.
NOVEMBER = datetime(2026, 11, 2, 9, 0, tzinfo=dt_timezone.utc)
OCTOBER = date(2026, 10, 1)
SEPTEMBER = date(2026, 9, 1)


class _History(_Usage):
    def setUp(self):
        super().setUp()
        # The first person joined in September: the history goes back to it.
        User.objects.filter(pk=self.admin.pk).update(date_joined=datetime(2026, 9, 10, tzinfo=dt_timezone.utc))
        usage_history.cache.clear()

    def months(self, user=None, hosts=None):
        browser = DjangoClient()
        browser.force_login(user or self.admin)
        with mock.patch.object(usage, "_get", hosts or _Hosts()), mock.patch.object(usage.timezone, "now", return_value=NOVEMBER):
            return browser.get(reverse(URL))

    def roll(self, hosts=None, now=NOVEMBER):
        hosts = hosts or _Hosts()
        with mock.patch.object(usage, "_get", hosts):
            done = usage_history.roll(now)
        return hosts, done

    def cell(self, month, host):
        return UsageMonth.objects.get(month=month, host=host)

    def month(self, answer, key):
        return next(month for month in answer.json()["months"] if month["month"] == key)


class DoorTests(_History):
    def test_the_door_is_the_api_one(self):
        self.assertEqual(reverse(URL), "/api/v1/admin/usage/months/")

    def test_only_the_admin_is_answered_and_no_host_is_asked(self):
        self.keys()
        for user in self.others:
            hosts = _Hosts()
            self.assertEqual(self.months(user, hosts).status_code, 403, user.role)
            self.assertEqual(hosts.asked, [], user.role)
        hosts = _Hosts()
        answer = self.months(hosts=hosts)
        self.assertEqual(answer.status_code, 200)
        self.assertEqual(hosts.asked, [])
        self.assertEqual([host["key"] for host in answer.json()["hosts"]], ["bunny", "neon", "render", "claude", "meta"])

    def test_nobody_signed_in_is_refused(self):
        self.assertEqual(DjangoClient().get(reverse(URL)).status_code, 401)

    def test_this_month_is_on_top_and_unread_is_not_a_zero(self):
        self.keys(bunny_api_key="")
        answer = self.months().json()
        top = answer["months"][0]
        self.assertEqual((top["month"], top["running"], top["closed"]), ("2026-11", True, False))
        self.assertEqual(top["label"], {"ar": "نوفمبر 2026", "en": "November 2026"})
        self.assertEqual(top["cells"]["bunny"]["state"], "off")
        self.assertEqual(top["cells"]["neon"]["state"], "unknown")
        self.assertIsNone(top["cells"]["neon"]["usd"])
        self.assertIsNone(top["total_usd"])
        self.assertFalse(top["complete"])


class RunningMonthTests(_History):
    def test_the_panel_keeps_what_it_read_as_the_running_month(self):
        self.keys()
        self.claude_calls(("check", "claude-sonnet-4-5", "2.50", 5))
        self.ask()
        bunny = self.cell(OCTOBER, "bunny")
        self.assertEqual((bunny.state, bunny.amount_usd, bunny.closed_at), ("ok", Decimal("1.27"), None))
        self.assertEqual(self.cell(OCTOBER, "neon").amount_usd, Decimal("5.33"))
        self.assertEqual(self.cell(OCTOBER, "claude").amount_usd, Decimal("2.50"))

    def test_a_host_that_failed_leaves_its_running_row_as_it_was(self):
        self.keys()
        self.ask()
        usage.cache.delete(usage.CACHE_KEY)
        self.ask(hosts=_Hosts(**{usage.BUNNY_URL: usage.HostError("unreachable")}), fresh="1")
        self.assertEqual(self.cell(OCTOBER, "bunny").amount_usd, Decimal("1.27"))


class ClosingTests(_History):
    def setUp(self):
        super().setUp()
        self.keys()
        # October's calls are $3.00; 30/09 is September's (and the first ever), 01/11 is November's.
        self.claude_calls(
            ("check", "claude-sonnet-4-5", "2.50", 5), ("helpbot", "claude-sonnet-4-5", "0.50", 20),
            ("check", "claude-sonnet-4-5", "9.99", (9, 30)), ("check", "claude-sonnet-4-5", "1.00", (11, 1)),
        )

    def test_each_host_is_asked_for_the_whole_month(self):
        hosts, done = self.roll()
        self.assertEqual(done, 2)
        october = {row.host: row for row in UsageMonth.objects.filter(month=OCTOBER)}
        self.assertTrue(all(row.closed_at is not None for row in october.values()))
        self.assertEqual(october["neon"].amount_usd, Decimal("5.33"))
        # Render: the web service the whole month, the worker from 11/10 (21 of 31 days), 17 GB = 12 over at $0.15.
        self.assertEqual(october["render"].amount_usd, Decimal("13.54"))
        self.assertTrue(october["render"].estimate)
        self.assertEqual(october["meta"].amount_usd, Decimal("2.20"))
        self.assertEqual(october["claude"].amount_usd, Decimal("3.00"))
        self.assertEqual(october["claude"].note_en, "")

        neon = [urllib.parse.parse_qs(urllib.parse.urlsplit(url).query) for url, _ in hosts.asked if url.startswith(usage.NEON_URL)]
        # October's Neon is asked from the day the account left the free plan to the month's end, September's not at all.
        self.assertEqual(len(neon), 1)
        self.assertEqual((neon[0]["from"], neon[0]["to"]), (["2026-10-15T00:00:00Z"], ["2026-11-01T00:00:00Z"]))
        bandwidth = [urllib.parse.parse_qs(urllib.parse.urlsplit(url).query) for url, _ in hosts.asked if url.startswith(usage.RENDER_BANDWIDTH_URL)]
        self.assertIn(["2026-10-31T23:59:59Z"], [query["endTime"] for query in bandwidth])
        start = int(datetime(2026, 10, 1, tzinfo=dt_timezone.utc).timestamp())
        end = int(datetime(2026, 11, 1, tzinfo=dt_timezone.utc).timestamp()) - 1
        self.assertTrue(any(f".start({start}).end({end})" in urllib.parse.unquote(url) for url, _ in hosts.asked))
        # Bunny answers this month only: it is never asked about a month gone by.
        self.assertNotIn(usage.BUNNY_URL, hosts.hosts())

    def test_what_cannot_be_known_is_none_and_says_so(self):
        self.roll()
        bunny = self.cell(OCTOBER, "bunny")
        self.assertEqual((bunny.state, bunny.amount_usd), ("unknown", None))
        # September: Neon was on the free plan, and Claude was counted from 30/09 only.
        self.assertEqual(self.cell(SEPTEMBER, "neon").amount_usd, Decimal("0.00"))
        claude = self.cell(SEPTEMBER, "claude")
        self.assertEqual((claude.amount_usd, claude.note_en), (Decimal("9.99"), "Counted since 30/09"))

    def test_bunny_closes_with_the_last_figure_read_in_its_month(self):
        self.ask()
        self.roll()
        bunny = self.cell(OCTOBER, "bunny")
        self.assertEqual((bunny.state, bunny.amount_usd, bunny.estimate), ("ok", Decimal("1.27"), True))
        self.assertTrue(bunny.note_en.startswith("Last read 22/10"), bunny.note_en)
        self.assertTrue(bunny.note_ar.startswith("آخر قراءة 22/10"), bunny.note_ar)

    def test_a_month_before_claude_was_counted_is_not_measured(self):
        UsageMonth.objects.all().delete()
        from .models import ClaudeUsage

        ClaudeUsage.objects.filter(created_at__lt=datetime(2026, 10, 1, tzinfo=dt_timezone.utc)).delete()
        self.roll()
        claude = self.cell(SEPTEMBER, "claude")
        self.assertEqual((claude.state, claude.amount_usd, claude.note_en), ("unknown", None, "Not counted yet"))

    def test_the_page_totals_the_dollars_and_says_when_something_is_missing(self):
        self.roll()
        october = self.month(self.months(), "2026-10")
        self.assertTrue(october["closed"])
        self.assertFalse(october["running"])
        self.assertEqual(october["cells"]["render"]["usd"], 13.54)
        self.assertIsNone(october["cells"]["bunny"]["usd"])
        self.assertEqual(october["total_usd"], round(5.33 + 13.54 + 3.00 + 2.20, 2))
        self.assertFalse(october["complete"])

    def test_meta_in_another_currency_is_shown_not_added(self):
        euro = {**META_PRICING, "currency": "EUR"}
        self.roll(_Hosts(**{META_URL: euro}))
        meta = self.cell(OCTOBER, "meta")
        self.assertEqual((meta.amount_usd, meta.amount_text), (None, "2.20 EUR"))
        october = self.month(self.months(), "2026-10")
        self.assertEqual(october["total_usd"], round(5.33 + 13.54 + 3.00, 2))
        self.assertFalse(october["complete"])

    def test_a_closed_month_is_not_asked_again(self):
        self.roll()
        hosts, done = self.roll()
        self.assertEqual((done, hosts.asked), (0, []))

    def test_without_any_key_nothing_is_closed(self):
        conf = AppSettings.load()
        for name in (*KEYS, "whatsapp_waba_id"):
            setattr(conf, name, "")
        conf.save()
        AppSettings._cached = None
        hosts, done = self.roll()
        self.assertEqual((done, hosts.asked, UsageMonth.objects.count()), (0, [], 0))


class FailureTests(_History):
    def setUp(self):
        super().setUp()
        self.keys()
        User.objects.filter(pk=self.admin.pk).update(date_joined=datetime(2026, 10, 10, tzinfo=dt_timezone.utc))

    def test_a_failed_host_is_kept_as_an_error_with_no_secret_and_asked_again(self):
        failing = _Hosts(**{usage.NEON_URL: usage.HostError(f"HTTP 500 {KEYS['neon_api_key']}")})
        self.roll(failing)
        neon = self.cell(OCTOBER, "neon")
        self.assertEqual((neon.state, neon.amount_usd), ("error", None))
        self.assertNotIn(KEYS["neon_api_key"], neon.error)
        # The next closing, within the days it is retried, asks Neon only.
        hosts, _ = self.roll(now=datetime(2026, 11, 3, tzinfo=dt_timezone.utc))
        self.assertEqual(set(hosts.hosts()), {usage.NEON_URL})
        neon.refresh_from_db()
        self.assertEqual((neon.state, neon.amount_usd), ("ok", Decimal("5.33")))

    def test_a_failure_is_left_after_the_retry_days(self):
        self.roll(_Hosts(**{usage.NEON_URL: usage.HostError("unreachable")}))
        hosts, done = self.roll(now=datetime(2026, 11, 10, tzinfo=dt_timezone.utc))
        self.assertEqual((done, hosts.asked), (0, []))
        self.assertEqual(self.cell(OCTOBER, "neon").state, "error")

    def test_a_failed_host_with_a_running_figure_keeps_it(self):
        self.ask()
        self.roll(_Hosts(**{usage.NEON_URL: usage.HostError("unreachable")}))
        neon = self.cell(OCTOBER, "neon")
        self.assertEqual((neon.state, neon.amount_usd), ("ok", Decimal("5.33")))
        self.assertTrue(neon.note_en.startswith("Last read"))


class GateTests(_History):
    def setUp(self):
        super().setUp()
        self.keys()

    def test_the_closing_runs_once_an_hour(self):
        with mock.patch.object(usage, "_get", _Hosts()):
            self.assertEqual(usage_history.roll_due(NOVEMBER), 2)
            UsageMonth.objects.all().delete()
            self.assertEqual(usage_history.roll_due(NOVEMBER), 0)
            self.assertEqual(usage_history.roll_due(datetime(2026, 11, 2, 10, 0, tzinfo=dt_timezone.utc)), 2)

    def test_the_heartbeat_hands_it_to_a_thread_only_when_something_is_due(self):
        with mock.patch.object(usage_history.threading, "Thread") as thread:
            self.assertIsNotNone(usage_history.roll_soon(NOVEMBER))
            thread.assert_called_once()
            self.assertIs(thread.call_args.kwargs["target"], usage_history._roll_in_thread)
        usage_history.cache.clear()
        with mock.patch.object(usage, "_get", _Hosts()):
            usage_history.roll(NOVEMBER)
        with mock.patch.object(usage_history.threading, "Thread") as thread:
            self.assertIsNone(usage_history.roll_soon(NOVEMBER))
            thread.assert_not_called()

    def test_the_heartbeat_reaches_it(self):
        from . import services

        usage_history.cache.clear()
        with mock.patch.object(usage_history, "roll_soon") as soon:
            services.heartbeat(self.admin)
        soon.assert_called_once()

