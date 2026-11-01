"""The admin's usage panel: this month's bill at Bunny, Neon, Render, Claude and Meta (``usage.py``, ``/api/v1/admin/usage/``).

What these tests hold: only the admin is answered; a host with no key is ``off`` and never asked; each host's answer is read
into the card the panel draws (Bunny's bill as it is, Neon's compute hours priced, Render worked out from its plans and its
bandwidth, Claude counted from the product's own calls and never asked, Meta's messages by kind and in its own currency); one host failing leaves the others; no key is ever in an answer, not even inside a host's error; and the report
is kept ten minutes unless the panel asks for a fresh one.
"""

import json
import urllib.parse
from datetime import datetime
from decimal import Decimal
from datetime import timezone as dt_timezone
from unittest import mock

from django.core.cache import cache
from django.test import Client as DjangoClient
from django.test import TestCase
from django.urls import reverse

from . import api_admin_settings, usage
from .forms import SettingsForm
from .models import AppSettings, ClaudeUsage, Role, User

URL = "dashboard:v1_admin_usage"
#: 22/10/2026 at noon UTC: 21.5 days of a 31-day month are behind.
NOW = datetime(2026, 10, 22, 12, 0, tzinfo=dt_timezone.utc)
KEYS = {
    "bunny_api_key": "SECRET-bunny-account-key",
    "neon_api_key": "SECRET-neon-api-key",
    "render_api_key": "SECRET-render-api-key",
    "claude_api_key": "sk-ant-SECRET-claude-usage",
    "whatsapp_access_token": "EAAG-SECRET-whatsapp-usage",
}
WABA = "111222333"
META_URL = f"https://graph.facebook.com/v23.0/{WABA}"

BUNNY_BILL = {
    "Balance": 18.4, "ThisMonthCharges": 1.27, "MonthlyChargesStorage": 0.42,
    "MonthlyChargesEUTraffic": 0.5, "MonthlyChargesUSTraffic": 0.35, "MonthlyChargesASIATraffic": None,
    "MonthlyBandwidthUsed": {"not": "a number"},
}
NEON_USAGE = {
    "projects": [{
        "project_id": "p-1",
        "periods": [{
            "period_plan": "launch",
            "consumption": [
                {"metrics": [{"metric_name": "compute_unit_seconds", "value": 100000},
                             {"metric_name": "public_network_transfer_bytes", "value": 2_000_000_000}]},
                {"metrics": [{"metric_name": "compute_unit_seconds", "value": 80972}]},
            ],
        }],
    }],
    "pagination": {"cursor": ""},
}
RENDER_SERVICES = [
    {"cursor": "c1", "service": {"id": "srv-web", "name": "eagle", "type": "web_service", "suspended": "not_suspended",
                                 "createdAt": "2026-08-01T00:00:00Z", "serviceDetails": {"plan": "starter", "numInstances": 1}}},
    {"cursor": "c2", "service": {"id": "srv-worker", "name": "worker", "type": "background_worker", "suspended": "not_suspended",
                                 "createdAt": "2026-10-11T00:00:00Z", "serviceDetails": {"plan": "starter"}}},
    {"cursor": "c3", "service": {"id": "srv-old", "name": "old", "type": "web_service", "suspended": "suspended",
                                 "createdAt": "2026-01-01T00:00:00Z", "serviceDetails": {"plan": "standard"}}},
    {"cursor": "c4", "service": {"id": "srv-site", "name": "site", "type": "static_site", "suspended": "not_suspended",
                                 "createdAt": "2026-01-01T00:00:00Z", "serviceDetails": {}}},
]
META_PRICING = {
    "currency": "USD",
    "pricing_analytics": {"data": [{"data_points": [
        {"start": 1, "end": 2, "volume": 30, "cost": 1.5, "pricing_type": "REGULAR", "pricing_category": "MARKETING"},
        {"start": 2, "end": 3, "volume": 10, "cost": 0.2, "pricing_type": "REGULAR", "pricing_category": "UTILITY"},
        {"start": 3, "end": 4, "volume": 10, "cost": 0.5, "pricing_type": "REGULAR", "pricing_category": "MARKETING"},
        {"start": 3, "end": 4, "volume": 40, "cost": 0, "pricing_type": "FREE_CUSTOMER_SERVICE", "pricing_category": "SERVICE"},
    ]}]},
    "id": WABA,
}
RENDER_BANDWIDTH = [
    {"labels": [{"field": "service", "value": "srv-web"}], "unit": "GB", "values": [{"value": 10.0}, {"value": 7.0}]},
]


class _Hosts:
    """Stands in for ``usage._get``: answers each host's address and writes down what was asked, headers included."""

    def __init__(self, **overrides):
        self.asked = []
        self.answers = {
            usage.BUNNY_URL: BUNNY_BILL, usage.NEON_URL: NEON_USAGE,
            usage.RENDER_SERVICES_URL: RENDER_SERVICES, usage.RENDER_BANDWIDTH_URL: RENDER_BANDWIDTH,
            META_URL: META_PRICING,
        }
        self.answers.update(overrides)

    def __call__(self, url, headers):
        self.asked.append((url, headers))
        answer = self.answers[url.split("?")[0]]
        if isinstance(answer, Exception):
            raise answer
        return answer

    def hosts(self):
        return [url.split("?")[0] for url, _ in self.asked]


class _Usage(TestCase):
    def setUp(self):
        cache.delete(usage.CACHE_KEY)
        self.addCleanup(cache.delete, usage.CACHE_KEY)
        AppSettings._cached = None
        self.admin = User.objects.create_user("person_admin", password="pw", role=Role.ADMIN)
        self.others = [
            User.objects.create_user(f"person_{role}", password="pw", role=role)
            for role in (Role.OPERATION, Role.ACCOUNTING, Role.HR, Role.SALES, Role.TEAM_LEAD, Role.SUPPORT)
        ]

    def keys(self, **extra):
        conf = AppSettings.load()
        for name, value in {**KEYS, "neon_org_id": "org-test-1", "whatsapp_waba_id": WABA, "whatsapp_api_version": "v23.0", **extra}.items():
            setattr(conf, name, value)
        conf.save()
        AppSettings._cached = None

    def ask(self, user=None, hosts=None, **query):
        browser = DjangoClient()
        browser.force_login(user or self.admin)
        with mock.patch.object(usage, "_get", hosts or _Hosts()), mock.patch.object(usage.timezone, "now", return_value=NOW):
            return browser.get(reverse(URL), query)

    def card(self, answer, key):
        return next(card for card in answer.json()["cards"] if card["key"] == key)

    def claude_calls(self, *rows):
        """``(feature, model, dollars, day of the month or (month, day))`` as ``ClaudeUsage`` rows of 2026."""
        for feature, model, dollars, day in rows:
            month, day = day if isinstance(day, tuple) else (10, day)
            row = ClaudeUsage.objects.create(
                feature=feature, model=model, input_tokens=1, cost_usd=None if dollars is None else Decimal(dollars),
            )
            ClaudeUsage.objects.filter(pk=row.pk).update(created_at=datetime(2026, month, day, 9, tzinfo=dt_timezone.utc))


class DoorTests(_Usage):
    def test_the_door_is_the_api_one(self):
        self.assertEqual(reverse(URL), "/api/v1/admin/usage/")

    def test_only_the_admin_is_answered(self):
        self.keys()
        for user in self.others:
            hosts = _Hosts()
            answer = self.ask(user, hosts)
            self.assertEqual(answer.status_code, 403, user.role)
            self.assertEqual(hosts.asked, [], user.role)
        self.assertEqual(self.ask().status_code, 200)

    def test_nobody_signed_in_is_refused(self):
        self.assertEqual(DjangoClient().get(reverse(URL)).status_code, 401)

    def test_without_keys_every_host_is_off_and_none_is_asked(self):
        hosts = _Hosts()
        answer = self.ask(hosts=hosts).json()
        self.assertEqual([card["state"] for card in answer["cards"]], ["off"] * len(usage.HOSTS))
        self.assertEqual([card["key"] for card in answer["cards"]], ["bunny", "neon", "render", "claude", "meta"])
        self.assertIsNone(answer["total_usd"])
        self.assertEqual(hosts.asked, [])

    def test_neon_without_its_organization_says_so(self):
        self.keys(neon_org_id="")
        hosts = _Hosts()
        card = self.card(self.ask(hosts=hosts), "neon")
        self.assertEqual((card["state"], card["error"]), ("error", "neon_org_missing"))
        self.assertNotIn(usage.NEON_URL, hosts.hosts())


class ReadingTests(_Usage):
    def setUp(self):
        super().setUp()
        self.keys()
        # $3.23 this month; the call of 30/09 is last month's.
        self.claude_calls(
            ("check", "claude-sonnet-4-5", "2.50", 5), ("helpbot", "claude-sonnet-4-5", "0.50", 20),
            ("check", "claude-sonnet-4-5", "0.23", 21), ("check", "claude-sonnet-4-5", "9.99", (9, 30)),
        )

    def test_bunny_is_its_own_bill(self):
        hosts = _Hosts()
        card = self.card(self.ask(hosts=hosts), "bunny")
        self.assertEqual(card["state"], "ok")
        self.assertEqual(card["month_usd"], 1.27)
        self.assertEqual(card["balance_usd"], 18.4)
        self.assertFalse(card["estimate"])
        values = {line["en"]: line["value"] for line in card["lines"]}
        self.assertEqual(values, {"Balance": "$18.40", "Storage": "$0.42", "Traffic": "$0.85"})
        url, headers = next(entry for entry in hosts.asked if entry[0] == usage.BUNNY_URL)
        self.assertEqual(headers["AccessKey"], KEYS["bunny_api_key"])

    def test_neon_prices_the_compute_hours(self):
        hosts = _Hosts()
        card = self.card(self.ask(hosts=hosts), "neon")
        # 180972 seconds = 50.27 hours, the 22/10/2026 bill: $5.33.
        self.assertEqual(card["month_usd"], 5.33)
        values = {line["en"]: line["value"] for line in card["lines"]}
        self.assertEqual(values, {"Compute hours": "50.27", "Network transfer": "2.00 GB"})
        url, headers = next(entry for entry in hosts.asked if entry[0].startswith(usage.NEON_URL))
        query = urllib.parse.parse_qs(urllib.parse.urlparse(url).query)
        self.assertEqual(query["org_id"], ["org-test-1"])
        self.assertEqual(query["from"], ["2026-10-01T00:00:00Z"])
        self.assertEqual(query["to"], ["2026-10-23T00:00:00Z"])
        self.assertEqual(query["granularity"], ["daily"])
        self.assertEqual(headers["Authorization"], f"Bearer {KEYS['neon_api_key']}")

    def test_neon_refusing_an_end_in_the_future_is_asked_up_to_now(self):
        calls = []

        def answer(url, headers):
            calls.append(url)
            if "2026-10-23" in url:
                raise usage.HostError("HTTP 400 to is in the future")
            return NEON_USAGE

        with mock.patch.object(usage, "_get", answer):
            card = usage._one(usage.HOSTS[1], AppSettings.load(), NOW)
        self.assertEqual(card["state"], "ok")
        self.assertEqual(len(calls), 2)
        self.assertIn("to=2026-10-22T12%3A00%3A00Z", calls[1])

    def test_render_is_worked_out_from_the_plans_and_the_bandwidth(self):
        hosts = _Hosts()
        card = self.card(self.ask(hosts=hosts), "render")
        self.assertEqual(card["state"], "ok")
        self.assertTrue(card["estimate"])
        # The web service all 21.5 days ($7 x 21.5/31), the worker from 11/10 (11.5 days), the suspended one and the static
        # site nothing; bandwidth 17 GB, 12 over the five included at $0.15.
        services = 7 * 21.5 / 31 + 7 * 11.5 / 31
        self.assertEqual(card["month_usd"], round(services + 12 * 0.15, 2))
        values = {line["en"]: line["value"] for line in card["lines"]}
        self.assertEqual(values["Services"], f"${services:,.2f}")
        self.assertEqual(values["Bandwidth"], "17.00 / 5 GB")
        bandwidth = next(url for url, _ in hosts.asked if url.startswith(usage.RENDER_BANDWIDTH_URL))
        query = urllib.parse.parse_qs(urllib.parse.urlparse(bandwidth).query)
        self.assertEqual(query["resource"], ["srv-web", "srv-worker"])

    def test_a_plan_with_no_known_price_is_named_not_counted_as_free(self):
        odd = [dict(RENDER_SERVICES[0], service=dict(RENDER_SERVICES[0]["service"], serviceDetails={"plan": "mystery_plus"}))]
        card = self.card(self.ask(hosts=_Hosts(**{usage.RENDER_SERVICES_URL: odd})), "render")
        values = {line["en"]: line["value"] for line in card["lines"]}
        self.assertEqual(values["Unknown plan"], "eagle")

    def test_bandwidth_in_megabytes_is_read_as_megabytes(self):
        # 22/10/2026: the series said 17,783.22 MB, Render's bill 17.35 GB and $1.95 (12.35 over, billed as 13 GB).
        series = [{"labels": [], "unit": "MB", "values": [{"value": 17000.0}, {"value": 783.22}]}]
        card = self.card(self.ask(hosts=_Hosts(**{usage.RENDER_BANDWIDTH_URL: series})), "render")
        values = {line["en"]: line["value"] for line in card["lines"]}
        self.assertEqual(values["Bandwidth"], "17.37 / 5 GB")
        services = 7 * 21.5 / 31 + 7 * 11.5 / 31
        self.assertEqual(card["month_usd"], round(services + 1.95, 2))

    def test_a_bandwidth_unit_not_known_is_an_error_not_a_guess(self):
        for unit in ("PB", None):
            cache.delete(usage.CACHE_KEY)
            series = [{"labels": [], "unit": unit, "values": [{"value": 3.0}]}]
            card = self.card(self.ask(hosts=_Hosts(**{usage.RENDER_BANDWIDTH_URL: series})), "render")
            self.assertEqual(card["state"], "error", unit)
            self.assertIn("unit", card["error"])

    def test_each_gigabyte_begun_over_the_included_is_billed(self):
        self.assertEqual(usage._render_overage(4.9), 0)
        self.assertEqual(usage._render_overage(5.0), 0)
        self.assertAlmostEqual(usage._render_overage(5.01), 0.15)
        self.assertAlmostEqual(usage._render_overage(17.35), 1.95)
        self.assertAlmostEqual(usage._render_overage(17.0), 1.80)

    def test_claude_is_counted_from_the_calls_and_never_asked(self):
        hosts = _Hosts()
        card = self.card(self.ask(hosts=hosts), "claude")
        self.assertEqual((card["state"], card["month_usd"], card["estimate"]), ("ok", 3.23, True))
        values = {line["en"]: line["value"] for line in card["lines"]}
        self.assertEqual(values, {
            "Calls": "3", "Translation check": "2 · $2.73", "Assistant": "1 · $0.50", "Balance: on the Billing page": "-",
        })
        self.assertFalse([url for url, _ in hosts.asked if "anthropic" in url])

    def test_claude_says_when_the_counting_began(self):
        ClaudeUsage.objects.filter(created_at__month=9).delete()
        values = {line["en"]: line["value"] for line in self.card(self.ask(), "claude")["lines"]}
        self.assertEqual(values["Counted since"], "05/10")

    def test_claude_names_a_model_with_no_price(self):
        self.claude_calls(("check", "claude-unknown-9", None, 22))
        card = self.card(self.ask(), "claude")
        values = {line["en"]: line["value"] for line in card["lines"]}
        self.assertEqual(values["Model with no price"], "claude-unknown-9")
        self.assertEqual(card["month_usd"], 3.23)

    def test_claude_without_its_key_is_off(self):
        self.keys(claude_api_key="")
        self.assertEqual(self.card(self.ask(), "claude")["state"], "off")

    def test_meta_is_the_messages_by_kind(self):
        hosts = _Hosts()
        card = self.card(self.ask(hosts=hosts), "meta")
        self.assertEqual((card["state"], card["month_usd"], card["amount"]), ("ok", 2.2, ""))
        values = {line["en"]: line["value"] for line in card["lines"]}
        self.assertEqual(values, {
            "Messages delivered": "90", "Marketing": "40 · $2.00", "Utility": "10 · $0.20", "Service": "40 · $0.00",
        })
        url, headers = next(entry for entry in hosts.asked if entry[0].startswith(META_URL))
        self.assertEqual(headers["Authorization"], f"Bearer {KEYS['whatsapp_access_token']}")
        self.assertNotIn(KEYS["whatsapp_access_token"], url)
        fields = urllib.parse.parse_qs(urllib.parse.urlparse(url).query)["fields"][0]
        self.assertIn(f"pricing_analytics.start({int(datetime(2026, 10, 1, tzinfo=dt_timezone.utc).timestamp())})", fields)
        self.assertIn(f".end({int(NOW.timestamp())})", fields)

    def test_meta_in_another_currency_is_shown_but_not_added_to_the_dollars(self):
        pricing = dict(META_PRICING, currency="EGP")
        answer = self.ask(hosts=_Hosts(**{META_URL: pricing})).json()
        card = self.card_of(answer, "meta")
        self.assertIsNone(card["month_usd"])
        self.assertEqual(card["amount"], "2.20 EGP")
        self.assertEqual(answer["total_usd"], round(1.27 + 5.33 + 3.23 + 7 * 21.5 / 31 + 7 * 11.5 / 31 + 1.80, 2))

    def card_of(self, answer, key):
        return next(card for card in answer["cards"] if card["key"] == key)

    def test_meta_without_the_account_id_is_off(self):
        self.keys(whatsapp_waba_id="")
        hosts = _Hosts()
        self.assertEqual(self.card(self.ask(hosts=hosts), "meta")["state"], "off")
        self.assertNotIn(META_URL, hosts.hosts())

    def test_the_total_is_of_the_hosts_that_answered(self):
        hosts = _Hosts(**{usage.RENDER_SERVICES_URL: usage.HostError("unreachable")})
        answer = self.ask(hosts=hosts).json()
        self.assertEqual(self.card_state(answer), {"bunny": "ok", "neon": "ok", "render": "error", "claude": "ok", "meta": "ok"})
        self.assertEqual(answer["total_usd"], round(1.27 + 5.33 + 3.23 + 2.2, 2))

    def card_state(self, answer):
        return {card["key"]: card["state"] for card in answer["cards"]}

    def test_a_surprise_from_one_host_leaves_the_others(self):
        hosts = _Hosts(**{usage.BUNNY_URL: ["not", "a", "bill"]})
        answer = self.ask(hosts=hosts).json()
        self.assertEqual(self.card_state(answer), {"bunny": "error", "neon": "ok", "render": "ok", "claude": "ok", "meta": "ok"})


class SecretTests(_Usage):
    def test_no_key_is_in_the_answer_even_when_a_host_quotes_it(self):
        self.keys()
        hosts = _Hosts(**{
            usage.BUNNY_URL: usage.HostError(f"HTTP 500 bad key {KEYS['bunny_api_key']}"),
            usage.NEON_URL: usage.HostError(f"HTTP 500 {KEYS['neon_api_key']}"),
            usage.RENDER_SERVICES_URL: usage.HostError(f"HTTP 500 {KEYS['render_api_key']}"),
            META_URL: usage.HostError(f"HTTP 500 {KEYS['whatsapp_access_token']}"),
        })
        text = self.ask(hosts=hosts).content.decode()
        for value in KEYS.values():
            self.assertNotIn(value, text)
        self.assertIn("***", text)

    def test_the_keys_are_secrets_of_the_settings_page(self):
        self.keys()
        for name in KEYS:
            self.assertIn(name, api_admin_settings.SECRET_FIELDS)
            self.assertIsInstance(SettingsForm.base_fields[name].widget, type(SettingsForm.base_fields["claude_api_key"].widget))
        browser = DjangoClient()
        browser.force_login(self.admin)
        text = browser.get(reverse("dashboard:v1_admin_settings")).content.decode()
        for value in KEYS.values():
            self.assertNotIn(value, text)
        fields = {field["name"]: field for field in json.loads(text)["fields"]}
        for name in KEYS:
            self.assertTrue(fields[name]["saved"], name)


class CacheTests(_Usage):
    def setUp(self):
        super().setUp()
        self.keys()

    def test_the_report_is_kept_until_a_fresh_one_is_asked_for(self):
        first = _Hosts()
        self.ask(hosts=first)
        self.assertTrue(first.asked)
        again = _Hosts()
        self.ask(hosts=again)
        self.assertEqual(again.asked, [])
        fresh = _Hosts()
        self.ask(hosts=fresh, fresh="1")
        self.assertTrue(fresh.asked)

    def test_a_failed_host_is_kept_a_minute_only(self):
        with mock.patch.object(usage.cache, "set") as kept:
            self.ask(hosts=_Hosts(**{usage.BUNNY_URL: usage.HostError("unreachable")}))
        self.assertEqual(kept.call_args.args[2], usage.CACHE_SECONDS_FAILED)
        cache.delete(usage.CACHE_KEY)
        with mock.patch.object(usage.cache, "set") as kept:
            self.ask(hosts=_Hosts())
        self.assertEqual(kept.call_args.args[2], usage.CACHE_SECONDS)
