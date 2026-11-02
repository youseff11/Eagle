"""«سجل الدفع»: what each host's bill came to, month by month, kept after the month is over (``UsageMonth``).

The usage panel (``usage.py``) is this month's bill so far, asked of the hosts at most every ten minutes. Each time it asks,
what it read is kept here as the running month's rows (``keep``). Once a month is over it is closed (``close``) with the
panel's own sums for the whole month:

* **Neon, Render and Meta** are asked again for the month's dates. Render's is the panel's estimate from the plans the
  services are on today; Neon's is nothing before 15/10/2026, when the account left the free plan.
* **Claude** is our own count (``ClaudeUsage``): a month before the counting started is «مش متقاس», and the month it
  started in says from when.
* **Bunny** answers this month's bill only: a month is closed with the last figure read during it, and says when; a month
  nobody read is «مش متقاس».

A host that cannot answer at the closing keeps the running figure it had (marked as the last one read), or its error, and is
asked again at the next closings for ``RETRY_DAYS``. Nothing measured is ever a zero: it is ``None``.

Closing is from the worker's sweep, ``manage.py sweep`` and the heartbeat (in a thread of its own, since it asks the hosts),
at most once an hour in each process, ``CATCH_UP`` months at a time, back to the month the first person joined and no more
than ``HISTORY_MONTHS``. Months are the hosts' own UTC months; every time shown is Cairo's (``clock``).
"""

import logging
import threading
from datetime import date, datetime, timedelta
from datetime import timezone as dt_timezone
from decimal import Decimal

from django.core.cache import cache
from django.db import IntegrityError, connection, transaction
from django.utils import timezone

from . import clock, usage
from .models import AppSettings, ClaudeUsage, UsageMonth, User

log = logging.getLogger("dashboard")

#: How far back the history goes, in months before this one.
HISTORY_MONTHS = 12
#: The most months one closing asks the hosts about.
CATCH_UP = 3
#: A host that failed at a month's closing is asked again for this many days after the month ended.
RETRY_DAYS = 3

MONTHS = (
    ("يناير", "January"), ("فبراير", "February"), ("مارس", "March"), ("أبريل", "April"), ("مايو", "May"), ("يونيو", "June"),
    ("يوليو", "July"), ("أغسطس", "August"), ("سبتمبر", "September"), ("أكتوبر", "October"), ("نوفمبر", "November"),
    ("ديسمبر", "December"),
)

State = UsageMonth.State


def this_month(now):
    return usage._month(now)[0].date()


def _bounds(month):
    """The first moment of ``month`` and of the one after it, in UTC."""
    start = datetime(month.year, month.month, 1, tzinfo=dt_timezone.utc)
    return start, (start + timedelta(days=32)).replace(day=1)


def _shift(month, back):
    index = month.year * 12 + month.month - 1 - back
    return date(index // 12, index % 12 + 1, 1)


def _decimal(value):
    return None if value is None else Decimal(str(value)).quantize(Decimal("0.01"))


def _save(month, host, values, open_only=False):
    """Write one cell. Two processes closing the same month at once write it once (the pair is unique)."""
    rows = UsageMonth.objects.filter(month=month, host=host)
    if open_only:
        rows = rows.filter(closed_at__isnull=True)
    if rows.update(**values):
        return
    if open_only and UsageMonth.objects.filter(month=month, host=host).exists():
        return
    try:
        with transaction.atomic():
            UsageMonth.objects.create(month=month, host=host, **values)
    except IntegrityError:
        rows.update(**values)


def _from_card(card):
    return {
        "state": State.OK, "amount_usd": _decimal(card.get("month_usd")), "amount_text": str(card.get("amount") or "")[:60],
        "estimate": bool(card.get("estimate")), "error": "",
    }


def keep(cards, now):
    """The panel's cards that were read become the running month's rows. Never raises: the panel matters more."""
    try:
        month = this_month(now)
        for card in cards:
            if card.get("state") == "ok":
                _save(month, card["key"], {**_from_card(card), "note_ar": "", "note_en": ""}, open_only=True)
    except Exception:  # noqa: BLE001 - the panel's answer must not wait on its history
        log.exception("usage history: could not keep the running month")


def _last_read(row):
    """What a host had when it could not be asked about its month again: the running row, said to be the last one read."""
    when = row.updated_at
    return {
        "state": State.OK, "amount_usd": row.amount_usd, "amount_text": row.amount_text, "estimate": True, "error": "",
        "note_ar": f"آخر قراءة {clock.fmt12(when, 'ar', '%d/%m')}", "note_en": f"Last read {clock.fmt12(when, 'en', '%d/%m')}",
    }


def _unknown(note_ar="", note_en=""):
    return {"state": State.UNKNOWN, "amount_usd": None, "amount_text": "", "estimate": False, "error": "",
            "note_ar": note_ar, "note_en": note_en}


def _closing(host, conf, month, running):
    """One host's figure for a month that is over."""
    from .api_admin_settings import scrub  # the settings door owns the list of secrets

    start, end = _bounds(month)
    read = running if running is not None and running.state == State.OK else None
    if not usage.linked(host, conf):
        return _last_read(read) if read else {**_unknown(), "state": State.OFF}
    if host.get("now_only"):
        return _last_read(read) if read else _unknown()
    note = ("", "")
    if host["key"] == "claude":
        first = ClaudeUsage.objects.order_by("created_at").values_list("created_at", flat=True).first()
        if first is None or first >= end:
            return _unknown("ماكانش بيتعد لسه", "Not counted yet")
        if first > start:
            since = clock.local(first).strftime("%d/%m")
            note = (f"بيتعد من {since}", f"Counted since {since}")
    card = usage._one(host, conf, end - timedelta(microseconds=1))
    if card["state"] == "error":
        if read:
            return _last_read(read)
        return {**_unknown(), "state": State.ERROR, "error": scrub(card["error"], conf)[:200]}
    return {**_from_card(card), "note_ar": note[0], "note_en": note[1]}


def close(month, conf=None, now=None, hosts=None):
    """Close ``month`` (its first day): every host's figure for the whole of it. ``hosts`` closes only those keys."""
    conf = conf or AppSettings.load()
    now = now or timezone.now()
    running = {row.host: row for row in UsageMonth.objects.filter(month=month)}
    for host in usage.HOSTS:
        if hosts is not None and host["key"] not in hosts:
            continue
        _save(month, host["key"], {**_closing(host, conf, month, running.get(host["key"])), "closed_at": now})


def first_month(now):
    """The oldest month the history goes back to: the month the first person joined, and ``HISTORY_MONTHS`` at most."""
    current = this_month(now)
    joined = User.objects.order_by("date_joined").values_list("date_joined", flat=True).first()
    oldest = _shift(current, HISTORY_MONTHS)
    return max(oldest, this_month(joined)) if joined else current


def _due(now, conf):
    """The months to close (newest first) and the failed cells to ask again, as ``[(month, keys or None)]``."""
    if not any(usage.linked(host, conf) for host in usage.HOSTS):
        return []
    current = this_month(now)
    closed = set(UsageMonth.objects.filter(closed_at__isnull=False).values_list("month", flat=True).distinct())
    months, month = [], _shift(current, 1)
    oldest = first_month(now)
    while month >= oldest:
        if month not in closed:
            months.append(month)
        month = _shift(month, 1)
    work = [(month, None) for month in months[:CATCH_UP]]
    retry = {}
    for month, host in UsageMonth.objects.filter(state=State.ERROR, closed_at__isnull=False).values_list("month", "host"):
        if _bounds(month)[1] + timedelta(days=RETRY_DAYS) > now:
            retry.setdefault(month, set()).add(host)
    return work + sorted(retry.items(), reverse=True)


def roll(now=None):
    """Close what is due. Returns how many months were asked about."""
    now = now or timezone.now()
    conf = AppSettings.load()
    work = _due(now, conf)
    for month, hosts in work:
        close(month, conf, now, hosts)
    return len(work)


def _gate(now):
    return cache.add(f"usage-history-roll-{now.astimezone(dt_timezone.utc):%Y%m%d%H}", 1, 3600)


def roll_due(now=None):
    """``roll`` at most once an hour (the worker's sweep and ``manage.py sweep``). Never raises."""
    now = now or timezone.now()
    if not _gate(now):
        return 0
    try:
        return roll(now)
    except Exception:  # noqa: BLE001 - the sweep must go on
        log.exception("usage history: closing failed")
        return 0


def _roll_in_thread(now):
    try:
        roll(now)
    except Exception:  # noqa: BLE001 - nobody is waiting on this thread
        log.exception("usage history: closing failed")
    finally:
        connection.close()


def roll_soon(now=None):
    """From the heartbeat: at most once an hour, and only when something is due, close it in a thread of its own so the beat
    does not wait on the hosts (the worker may be off). Returns the thread, or ``None``."""
    now = now or timezone.now()
    if not _gate(now):
        return None
    try:
        if not _due(now, AppSettings.load()):
            return None
    except Exception:  # noqa: BLE001 - a beat must not fail on its housekeeping
        log.exception("usage history: could not tell what is due")
        return None
    worker = threading.Thread(target=_roll_in_thread, args=(now,), name="usage-history", daemon=True)
    worker.start()
    return worker


# ---------------------------------------------------------------------------
# The page
# ---------------------------------------------------------------------------

def _cell(row, host, conf):
    if row is None:
        state = State.UNKNOWN if usage.linked(host, conf) else State.OFF
        return {"state": state, "usd": None, "amount": "", "estimate": False, "note": None, "error": ""}
    note = {"ar": row.note_ar, "en": row.note_en} if row.note_ar or row.note_en else None
    return {
        "state": row.state, "usd": None if row.amount_usd is None else float(row.amount_usd), "amount": row.amount_text,
        "estimate": row.estimate, "note": note, "error": row.error,
    }


def table(now=None):
    """Every month on record, newest first, this month's running figures on top, each with its hosts and its total.

    The total is of the dollar figures; ``complete`` is false when a linked host is not measured, failed or is in another
    currency, so the total is what is known and says so."""
    now = now or timezone.now()
    conf = AppSettings.load()
    current = this_month(now)
    cells = {}
    for row in UsageMonth.objects.all():
        cells.setdefault(row.month, {})[row.host] = row
    months = []
    for month in sorted(set(cells) | {current}, reverse=True):
        rows = cells.get(month, {})
        drawn = {host["key"]: _cell(rows.get(host["key"]), host, conf) for host in usage.HOSTS}
        known = [cell["usd"] for cell in drawn.values() if cell["usd"] is not None]
        updated = max((row.updated_at for row in rows.values()), default=None)
        ar, en = MONTHS[month.month - 1]
        months.append({
            "month": month.strftime("%Y-%m"),
            "label": {"ar": f"{ar} {month.year}", "en": f"{en} {month.year}"},
            "running": month == current,
            "closed": bool(rows) and all(row.closed_at is not None for row in rows.values()),
            "cells": drawn,
            "total_usd": round(sum(known), 2) if known else None,
            "complete": all(cell["usd"] is not None for cell in drawn.values() if cell["state"] != State.OFF),
            "estimate": any(cell["estimate"] for cell in drawn.values()),
            "at": {"ar": clock.fmt12(updated, "ar", "%d/%m"), "en": clock.fmt12(updated, "en", "%d/%m")} if updated else None,
        })
    return {
        "ok": True,
        "hosts": [{"key": host["key"], "name": host["name"], "link": host["link"]} for host in usage.HOSTS],
        "months": months,
    }
