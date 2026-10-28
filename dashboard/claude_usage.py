"""What the product spends at Claude: every answer's own ``usage`` written down and priced (the usage panel's Claude card).

The account is an individual one, and an individual account has no Admin API key, so Anthropic's cost report is shut to us.
What is open is the ``usage`` each answer carries: the tokens read, written, and read from or written to the prompt cache. Each
call the product makes (the AI check, translating a client's message, the AI translation, the help assistant) is one
``ClaudeUsage`` row with those counts and their price at the model's list rate. Only counts are kept: never a word of what was
sent or answered.

Two things this cannot see, and the card says so: anything else spent with the same key outside the product, and the prepaid
balance (Anthropic has no API for it; it is on the Console's Billing page).

Writing a row must never cost the caller its answer: a failure here is logged and forgotten.
"""

import logging
from decimal import Decimal

log = logging.getLogger("dashboard")

#: Dollars per million tokens: (input, output, cache read). A cache write costs 1.25 times the input (the five-minute cache).
#: Prices of 06/10/2026 from the Claude API's model table; a model is matched by its name with any date suffix after it.
PRICES = {
    "claude-fable-5-1": (10, 50, 0.25),
    "claude-fable-5": (10, 50, 1.0),
    "claude-opus-5-5": (4, 20, 0.20),
    "claude-opus-5": (5, 25, 0.50),
    "claude-opus-4-8": (5, 25, 0.50),
    "claude-opus-4-7": (5, 25, 0.50),
    "claude-opus-4-6": (5, 25, 0.50),
    "claude-opus-4-5": (5, 25, 0.50),
    "claude-sonnet-5-5": (2, 10, 0.20),
    "claude-sonnet-5": (2, 10, 0.20),
    "claude-sonnet-4-6": (3, 15, 0.30),
    "claude-sonnet-4-5": (3, 15, 0.30),
    "claude-haiku-5-5": (0.10, 0.50, 0.01),
    "claude-haiku-4-5": (1, 5, 0.10),
}
CACHE_WRITE = Decimal("1.25")
MILLION = Decimal(1_000_000)

#: What each call is for, as the card names it.
FEATURES = {
    "check": ("مراجعة الترجمة", "Translation check"),
    "translate": ("ترجمة رسايل العملاء", "Client messages"),
    "ai_translate": ("الترجمة بالـAI", "AI translation"),
    "doc_review": ("مراجعة مستندات التيم ليدر", "Team leader's document review"),
    "helpbot": ("المساعد", "Assistant"),
}


def price_of(model):
    """The model's prices, or ``None`` for a model not in the table. The longest name it starts with wins
    (``claude-opus-5-5`` is not ``claude-opus-5``)."""
    name = str(model or "").strip().lower()
    for key in sorted(PRICES, key=len, reverse=True):
        if name == key or name.startswith(key + "-"):
            return PRICES[key]
    return None


def _count(usage, name):
    try:
        return max(0, int((usage or {}).get(name) or 0))
    except (TypeError, ValueError):
        return 0


def cost_of(model, input_tokens, output_tokens, cache_write_tokens, cache_read_tokens):
    """The call's price in dollars, or ``None`` when the model has none here."""
    prices = price_of(model)
    if prices is None:
        return None
    given, made, cached = (Decimal(str(value)) for value in prices)
    total = (
        input_tokens * given + output_tokens * made + cache_write_tokens * given * CACHE_WRITE + cache_read_tokens * cached
    )
    return (total / MILLION).quantize(Decimal("0.000001"))


def record(feature, model, usage):
    """Write one call down from the answer's ``usage``. Never raises."""
    from .models import ClaudeUsage

    try:
        counts = {
            "input_tokens": _count(usage, "input_tokens"),
            "output_tokens": _count(usage, "output_tokens"),
            "cache_write_tokens": _count(usage, "cache_creation_input_tokens"),
            "cache_read_tokens": _count(usage, "cache_read_input_tokens"),
        }
        if not any(counts.values()):
            return None
        model = str(model or "")[:80]
        return ClaudeUsage.objects.create(
            feature=str(feature)[:20], model=model, cost_usd=cost_of(model, *counts.values()), **counts,
        )
    except Exception:  # noqa: BLE001 - the caller's answer matters more than this row
        log.exception("claude usage: could not write the row")
        return None


def from_body(feature, body, fallback_model=""):
    """``record`` from a whole answer of the messages API."""
    if isinstance(body, dict):
        record(feature, body.get("model") or fallback_model, body.get("usage"))
