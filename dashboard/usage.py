"""The admin's usage panel: what Bunny, Neon, Render, Claude and Meta have charged this month so far.

Each host is asked with the key the admin pasted in the settings (``AppSettings.bunny_api_key`` and the rest), and only read:
nothing here changes anything at a host. What comes back is a card for each and a total:

* **Bunny** answers its own bill (``GET /billing``): the month's charges and the prepaid balance, exact.
* **Neon** answers the month's compute-unit seconds (``consumption_history/v2/projects``, the source its docs name for billing),
  priced here at the Launch plan's rate. Storage is left out: at our size it is under a cent.
* **Render** has no bill in its API. The panel adds up each service's plan, pro-rated by the seconds of the month it has run, and
  the bandwidth over the plan's 5 GB at $0.15/GB. It is an estimate and says so; the bill is on Render's page.
* **Claude** is counted here, not asked: the account is an individual one with no Admin API key, so every call the product
  makes is written down with the tokens its answer says it used and priced at the model's list rate (``claude_usage.py``).
  It is an estimate of the product's own spending; the prepaid balance has no API at all.
* **Meta** answers what the WhatsApp messages delivered this month cost, by kind (``pricing_analytics`` on the business
  account), with the WhatsApp token already saved. It is in the account's currency: only dollars join the total.

A host not set up is ``off``, a host that failed is ``error`` with a short reason, and the total is of the hosts that answered.
The report is kept ten minutes (one minute when a host failed), so opening the app does not ask the hosts every time. No key
is ever in an answer: an error text is cleaned of every stored secret before it leaves (``api_admin_settings.scrub``).
"""

import json
import logging
import math
import urllib.error
import urllib.parse
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta
from datetime import timezone as dt_timezone

from django.core.cache import cache
from django.utils import timezone

from . import clock, net
from .models import AppSettings

log = logging.getLogger("dashboard")

CACHE_KEY = "usage:report"
CACHE_SECONDS = 600
#: A report with a failed host is kept a minute only: a fixed key shows at the next look.
CACHE_SECONDS_FAILED = 60
TIMEOUT = 15
#: The most pages of a list the panel reads from one host.
MAX_PAGES = 5

BUNNY_URL = "https://api.bunny.net/billing"
NEON_URL = "https://console.neon.tech/api/v2/consumption_history/v2/projects"
RENDER_SERVICES_URL = "https://api.render.com/v1/services"
RENDER_BANDWIDTH_URL = "https://api.render.com/v1/metrics/bandwidth"

#: Neon's Launch plan: dollars per compute-unit hour (the bill of 15/10-22/10/2026: 50.27 hours = $5.33).
NEON_CU_HOUR_USD = 0.106
#: Render's monthly price of one instance of each plan, in dollars. A plan not here is counted as unknown, not as free.
RENDER_PLAN_USD = {
    "free": 0, "starter": 7, "standard": 25, "pro": 85, "pro_plus": 175, "pro_max": 225, "pro_ultra": 450,
}
#: Render's Hobby workspace: bandwidth included each month, and the price of each gigabyte over it.
RENDER_INCLUDED_GB = 5
RENDER_GB_USD = 0.15
#: What one of each unit a bandwidth series is in comes to in gigabytes. Render counts in 1024s: on 22/10/2026 its series said
#: 17,783.22 MB and its bill 17.35 GB.
RENDER_UNIT_GB = {"b": 1 / 1024 ** 3, "bytes": 1 / 1024 ** 3, "kb": 1 / 1024 ** 2, "mb": 1 / 1024, "gb": 1.0, "tb": 1024.0}

#: Meta's kinds of message, as the panel names them.
META_KINDS = {
    "MARKETING": ("تسويق", "Marketing"),
    "UTILITY": ("تنبيهات", "Utility"),
    "AUTHENTICATION": ("أكواد تحقق", "Authentication"),
    "SERVICE": ("رد على العميل", "Service"),
}

BUNNY_TRAFFIC = (
    "MonthlyChargesEUTraffic", "MonthlyChargesUSTraffic", "MonthlyChargesASIATraffic", "MonthlyChargesAFTraffic",
    "MonthlyChargesSATraffic",
)


class HostError(Exception):
    """A host refused or could not be reached. The text is short and goes to the admin (cleaned of secrets first)."""


def _get(url, headers):
    """GET ``url`` and read JSON. Every call to a host goes through here (the tests stand in for it)."""
    request = urllib.request.Request(url, headers={"Accept": "application/json", **headers}, method="GET")
    try:
        with net.urlopen(request, timeout=TIMEOUT) as response:
            return json.loads(response.read().decode("utf-8") or "null")
    except urllib.error.HTTPError as exc:
        if exc.code in (401, 403):
            raise HostError("key_refused") from exc
        detail = ""
        try:
            detail = exc.read().decode("utf-8", "replace")[:160]
        except Exception:  # noqa: BLE001 - the status alone is enough
            pass
        raise HostError(f"HTTP {exc.code} {detail}".strip()) from exc
    except (urllib.error.URLError, TimeoutError, OSError) as exc:
        raise HostError("unreachable") from exc
    except ValueError as exc:
        raise HostError("bad_answer") from exc


def _num(value):
    """A number the host sent, or ``None`` (a host sends ``null``, or an object where a number was expected)."""
    if isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        return float(value)
    return None


def _usd(value):
    return None if value is None else round(value, 2)


def _line(ar, en, value):
    return {"ar": ar, "en": en, "value": value}


def _money(value):
    return "-" if value is None else f"${value:,.2f}"


def _month(now):
    """The first moment of this month and of the next one, in UTC (the hosts bill by UTC months)."""
    now = now.astimezone(dt_timezone.utc)
    start = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
    end = (start + timedelta(days=32)).replace(day=1)
    return start, end


def _iso(moment):
    return moment.astimezone(dt_timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _parse(text):
    try:
        moment = datetime.fromisoformat(str(text).replace("Z", "+00:00"))
    except ValueError:
        return None
    return moment if moment.tzinfo else moment.replace(tzinfo=dt_timezone.utc)


# ---------------------------------------------------------------------------
# The three hosts
# ---------------------------------------------------------------------------

def bunny(conf, now):
    data = _get(BUNNY_URL, {"AccessKey": conf.bunny_api_key.strip()})
    if not isinstance(data, dict):
        raise HostError("bad_answer")
    month = _num(data.get("ThisMonthCharges"))
    balance = _num(data.get("Balance"))
    storage = _num(data.get("MonthlyChargesStorage"))
    traffic = [_num(data.get(name)) for name in BUNNY_TRAFFIC]
    traffic = sum(value for value in traffic if value is not None) if any(value is not None for value in traffic) else None
    lines = [
        _line("الرصيد", "Balance", _money(_usd(balance))),
        _line("التخزين", "Storage", _money(_usd(storage))),
        _line("الترافيك", "Traffic", _money(_usd(traffic))),
    ]
    return {"month_usd": _usd(month), "balance_usd": _usd(balance), "lines": lines}


def _neon_pages(conf, start, to):
    params = {
        "from": _iso(start), "to": _iso(to), "granularity": "daily", "org_id": conf.neon_org_id.strip(),
        "metrics": "compute_unit_seconds,public_network_transfer_bytes", "limit": "100",
    }
    headers = {"Authorization": f"Bearer {conf.neon_api_key.strip()}"}
    cursor = ""
    for _ in range(MAX_PAGES):
        query = dict(params, cursor=cursor) if cursor else params
        data = _get(f"{NEON_URL}?{urllib.parse.urlencode(query)}", headers)
        if not isinstance(data, dict):
            raise HostError("bad_answer")
        yield from data.get("projects") or []
        cursor = (data.get("pagination") or {}).get("cursor") or ""
        if not cursor or not data.get("projects"):
            return


def neon(conf, now):
    if not conf.neon_org_id.strip():
        raise HostError("neon_org_missing")
    start, _ = _month(now)
    # Days are whole at this granularity: up to the start of tomorrow takes today's hours in.
    tomorrow = (now.astimezone(dt_timezone.utc) + timedelta(days=1)).replace(hour=0, minute=0, second=0, microsecond=0)
    try:
        projects = list(_neon_pages(conf, start, tomorrow))
    except HostError as exc:
        # Should Neon refuse an end in the future, up to now still counts every day but today.
        if not str(exc).startswith("HTTP 400"):
            raise
        projects = list(_neon_pages(conf, start, now))
    totals = {"compute_unit_seconds": 0.0, "public_network_transfer_bytes": 0.0}
    for project in projects:
        for period in project.get("periods") or []:
            for frame in period.get("consumption") or []:
                for metric in frame.get("metrics") or []:
                    name = metric.get("metric_name")
                    value = _num(metric.get("value"))
                    if name in totals and value is not None:
                        totals[name] += value
    hours = totals["compute_unit_seconds"] / 3600
    transfer_gb = totals["public_network_transfer_bytes"] / 1e9
    return {
        "month_usd": _usd(hours * NEON_CU_HOUR_USD),
        "lines": [
            _line("ساعات الكمبيوت", "Compute hours", f"{hours:,.2f}"),
            _line("نقل الداتا", "Network transfer", f"{transfer_gb:,.2f} GB"),
        ],
    }


def _render_services(conf):
    headers = {"Authorization": f"Bearer {conf.render_api_key.strip()}"}
    cursor = ""
    for _ in range(MAX_PAGES):
        query = {"limit": "100", **({"cursor": cursor} if cursor else {})}
        data = _get(f"{RENDER_SERVICES_URL}?{urllib.parse.urlencode(query)}", headers)
        if not isinstance(data, list):
            raise HostError("bad_answer")
        for row in data:
            if isinstance(row, dict) and isinstance(row.get("service"), dict):
                yield row["service"]
        if len(data) < 100:
            return
        cursor = (data[-1] or {}).get("cursor") or ""
        if not cursor:
            return


def _render_overage(gigabytes):
    """What the bandwidth over the included part costs: Render bills each gigabyte begun (12.35 over = 13 x $0.15 = $1.95)."""
    return math.ceil(max(0.0, gigabytes - RENDER_INCLUDED_GB) - 1e-9) * RENDER_GB_USD


def render(conf, now):
    start, end = _month(now)
    month_seconds = (end - start).total_seconds()
    spent = projected = 0.0
    unknown, running = [], []
    for service in _render_services(conf):
        if service.get("suspended") == "suspended":
            continue
        details = service.get("serviceDetails") or {}
        plan = details.get("plan")
        if service.get("type") == "static_site" or not plan:
            continue
        price = RENDER_PLAN_USD.get(plan)
        if price is None:
            unknown.append(service.get("name") or service.get("id") or "?")
            continue
        running.append(service.get("id"))
        instances = _num(details.get("numInstances")) or 1
        since = max(start, _parse(service.get("createdAt")) or start)
        spent += price * instances * max(0.0, (now - since).total_seconds()) / month_seconds
        projected += price * instances * max(0.0, (end - since).total_seconds()) / month_seconds

    gigabytes = 0.0
    if running:
        query = [("resource", sid) for sid in running if sid] + [("startTime", _iso(start)), ("endTime", _iso(now))]
        series = _get(f"{RENDER_BANDWIDTH_URL}?{urllib.parse.urlencode(query)}", {"Authorization": f"Bearer {conf.render_api_key.strip()}"})
        for row in series if isinstance(series, list) else []:
            row = row or {}
            per_gb = RENDER_UNIT_GB.get(str(row.get("unit") or "").strip().lower())
            if per_gb is None:
                # A unit not known here would be a number off by a thousand: say so instead of guessing.
                raise HostError(f"unit {row.get('unit')!r}"[:60])
            for point in row.get("values") or []:
                value = _num((point or {}).get("value"))
                if value is not None:
                    gigabytes += value * per_gb
    elapsed = max(1.0, (now - start).total_seconds())
    over = _render_overage(gigabytes)
    over_projected = _render_overage(gigabytes * month_seconds / elapsed)
    lines = [
        _line("الخدمات", "Services", _money(_usd(spent))),
        _line("الباندويدث", "Bandwidth", f"{gigabytes:,.2f} / {RENDER_INCLUDED_GB} GB"),
        _line("المتوقع للشهر", "Expected for the month", _money(_usd(projected + over_projected))),
    ]
    if unknown:
        lines.append(_line("خطة مش معروفة", "Unknown plan", ", ".join(unknown)[:120]))
    return {"month_usd": _usd(spent + over), "estimate": True, "lines": lines}


def _tomorrow(now):
    return (now.astimezone(dt_timezone.utc) + timedelta(days=1)).replace(hour=0, minute=0, second=0, microsecond=0)


def claude(conf, now):
    """The month's calls from ``ClaudeUsage``: their cost, how many, and what for. Read here, in the request's own thread."""
    from django.db.models import Count, Q, Sum

    from .claude_usage import FEATURES
    from .models import ClaudeUsage

    start, _ = _month(now)
    rows = ClaudeUsage.objects.filter(created_at__gte=start)
    totals = rows.aggregate(cost=Sum("cost_usd"), calls=Count("id"), unpriced=Count("id", filter=Q(cost_usd__isnull=True)))
    lines = [_line("النداءات", "Calls", f"{totals['calls']:,}")]
    for row in rows.values("feature").annotate(cost=Sum("cost_usd"), calls=Count("id")).order_by("-cost", "feature"):
        ar, en = FEATURES.get(row["feature"], (row["feature"], row["feature"]))
        lines.append(_line(ar, en, f"{row['calls']:,} · {_money(_usd(float(row['cost'] or 0)))}"))
    if totals["unpriced"]:
        names = rows.filter(cost_usd__isnull=True).values_list("model", flat=True).distinct()[:3]
        lines.append(_line("موديل مالوش سعر", "Model with no price", ", ".join(names)[:120]))
    first = ClaudeUsage.objects.order_by("created_at").values_list("created_at", flat=True).first()
    if first is None or first > start:
        # The counting started after the month did: what came before it was never written down.
        since = clock.local(first).strftime("%d/%m") if first else "-"
        lines.append(_line("بيتعد من", "Counted since", since))
    lines.append(_line("الرصيد: من صفحة Billing", "Balance: on the Billing page", "-"))
    return {"month_usd": _usd(float(totals["cost"] or 0)), "estimate": True, "lines": lines}


def meta(conf, now):
    from . import whatsapp

    start, _ = _month(now)
    waba = conf.whatsapp_waba_id.strip()
    headers = {"Authorization": f"Bearer {conf.whatsapp_access_token.strip()}"}

    def ask(end):
        field = (
            f"currency,pricing_analytics.start({int(start.timestamp())}).end({int(end.timestamp())})"
            '.granularity(DAILY).dimensions(["PRICING_CATEGORY"])'
        )
        url = f"{whatsapp.GRAPH_HOST}/{whatsapp._version(conf)}/{urllib.parse.quote(waba)}?{urllib.parse.urlencode({'fields': field})}"
        return _get(url, headers)

    try:
        data = ask(now)
    except HostError as exc:
        if not str(exc).startswith("HTTP 400"):
            raise
        data = ask(_tomorrow(now))
    if not isinstance(data, dict):
        raise HostError("bad_answer")
    currency = str(data.get("currency") or "").strip().upper() or "USD"
    kinds, cost, count = {}, 0.0, 0
    for block in (data.get("pricing_analytics") or {}).get("data") or []:
        for point in (block or {}).get("data_points") or []:
            point = point or {}
            kind = str(point.get("pricing_category") or "OTHER")
            spent, sent = _num(point.get("cost")) or 0.0, int(_num(point.get("volume")) or 0)
            had = kinds.setdefault(kind, [0.0, 0])
            had[0] += spent
            had[1] += sent
            cost += spent
            count += sent

    def amount(value):
        return _money(_usd(value)) if currency == "USD" else f"{value:,.2f} {currency}"

    lines = [_line("الرسايل اللي اتسلّمت", "Messages delivered", f"{count:,}")]
    for kind, (spent, sent) in sorted(kinds.items(), key=lambda item: -item[1][0]):
        ar, en = META_KINDS.get(kind, (kind.title(), kind.title()))
        lines.append(_line(ar, en, f"{sent:,} · {amount(spent)}"))
    found = {"lines": lines, "estimate": True}
    if currency == "USD":
        found["month_usd"] = _usd(cost)
    else:
        found["amount"] = amount(cost)
    return found


HOSTS = (
    {"key": "bunny", "name": "Bunny.net", "fetch": bunny, "needs": ("bunny_api_key",), "link": "https://dash.bunny.net/billing"},
    {"key": "neon", "name": "Neon", "fetch": neon, "needs": ("neon_api_key",), "link": "https://console.neon.tech/app/billing"},
    {"key": "render", "name": "Render", "fetch": render, "needs": ("render_api_key",), "link": "https://dashboard.render.com/billing"},
    {"key": "claude", "name": "Claude", "fetch": claude, "needs": ("claude_api_key",), "local": True,
     "link": "https://platform.claude.com/settings/billing"},
    {"key": "meta", "name": "WhatsApp (Meta)", "fetch": meta, "needs": ("whatsapp_access_token", "whatsapp_waba_id"),
     "link": "https://business.facebook.com/billing_hub/"},
)


def _one(host, conf, now):
    """One host's card. A failure is the card's state, never the report's: the others still show. ``amount`` is the month's
    figure when it is not in dollars (Meta bills in the account's currency), and then it is not in the total."""
    card = {"key": host["key"], "name": host["name"], "link": host["link"], "state": "off", "month_usd": None,
            "amount": "", "estimate": False, "lines": [], "error": ""}
    if not all(str(getattr(conf, name, "") or "").strip() for name in host["needs"]):
        return card
    try:
        found = host["fetch"](conf, now)
    except HostError as exc:
        card.update(state="error", error=str(exc))
        return card
    except Exception:  # noqa: BLE001 - one host's surprise must not take the panel down
        log.exception("usage: %s failed", host["key"])
        card.update(state="error", error="failed")
        return card
    card.update(state="ok", **found)
    return card


def report(force=False, now=None):
    """The cards and their total. Kept ten minutes unless ``force``."""
    if not force:
        kept = cache.get(CACHE_KEY)
        if kept is not None:
            return kept
    from .api_admin_settings import scrub  # the settings door owns the list of secrets

    conf = AppSettings.load()
    now = now or timezone.now()
    # The hosts are asked side by side; a card read from our own tables (``local``) is read here, on the request's connection.
    away = [host for host in HOSTS if not host.get("local")]
    with ThreadPoolExecutor(max_workers=len(away)) as pool:
        found = dict(zip((host["key"] for host in away), pool.map(lambda host: _one(host, conf, now), away)))
    cards = [found[host["key"]] if host["key"] in found else _one(host, conf, now) for host in HOSTS]
    for card in cards:
        card["error"] = scrub(card["error"], conf)
    answered = [card["month_usd"] for card in cards if card["state"] == "ok" and card["month_usd"] is not None]
    out = {
        "ok": True,
        "cards": cards,
        "total_usd": _usd(sum(answered)) if answered else None,
        "estimate": any(card["estimate"] for card in cards if card["state"] == "ok"),
        "at": {"ar": clock.fmt12(now, "ar", "%d/%m"), "en": clock.fmt12(now, "en", "%d/%m")},
    }
    failed = any(card["state"] == "error" for card in cards)
    cache.set(CACHE_KEY, out, CACHE_SECONDS_FAILED if failed else CACHE_SECONDS)
    return out
