"""The price list and the discount limits (part 4, 15/10/2026; the B2C requirements' section 8, both Sales teams).

* The owner keeps the price list. Saving it makes a new version; a version is never changed, and the newest is the one in
  force. A price is a service, by a unit, in a currency - for one language pair ("EN>AR") or for any pair.
* A quotation, each time it is saved, is priced against the version in force: it keeps the version and the list's price
  of a unit (``price``). How far under the list it is - its rate under the list price, and its discount on top - is its
  effective discount.
* Each person may go so far under the list: a Sales person ``AppSettings.discount_limit_sales``, a Sales manager
  ``discount_limit_manager``, the owner without limit. A quotation beyond its maker's limit waits for an approval before
  it may be sent: the Sales manager of its team approves up to their own limit, beyond it only the owner. Nobody approves
  their own quotation (the owner's need none). A turned-down discount is changed and saved again.
"""

import re
from decimal import ROUND_HALF_UP, Decimal

from django.db import transaction
from django.db.models import Max
from django.utils import timezone

from .b2b import Refused, manages, sheets_for
from .models import AppSettings, PriceItem, PriceList, Quotation, Role, User

CENT = Decimal("0.01")
HUNDRED = Decimal("100")
MAX_ITEMS = 500
MAX_RATE = Decimal("1000000")
PENDING, APPROVED, REJECTED = "pending", "approved", "rejected"
PAIR = re.compile(r"^[A-Z]{2,5}>[A-Z]{2,5}$")


def current():
    return PriceList.objects.order_by("-version").first()


def pair_of(source, target):
    return f"{(source or '').strip().upper()}>{(target or '').strip().upper()}"


def item_for(price_list, service, unit, currency, source, target):
    """The price for this pair if the list has one, else the price for any pair; ``None`` when the list has neither."""
    if price_list is None:
        return None
    rows = {item.pair: item for item in price_list.items.filter(service=service, unit=unit, currency=currency)}
    return rows.get(pair_of(source, target)) or rows.get("")


def _owner(user):
    if not user.is_admin_role:
        raise Refused("forbidden", "قايمة الأسعار والحدود بيظبطها المالك بس.", "The price list and the limits are the owner's alone.")


def _rate(value):
    try:
        rate = Decimal(str(value).strip())
    except Exception:  # noqa: BLE001 - anything that is not a number
        return None
    if not rate.is_finite() or not Decimal(0) < rate <= MAX_RATE or rate.as_tuple().exponent < -4:
        return None
    return rate


def save_version(actor, items, note=""):
    """A new version of the list from ``items`` (``[{"service", "unit", "currency", "pair", "rate"}, ...]``). The versions
    before it stay as they were."""
    from . import services

    _owner(actor)
    if not isinstance(items, list) or not items or len(items) > MAX_ITEMS:
        raise Refused("no_items", "ضيف سعر واحد على الأقل.", "Add at least one price.")
    rows, seen = [], set()
    for item in items:
        if not isinstance(item, dict):
            raise Refused("bad_item", "سطر في القايمة مش مفهوم.", "A line of the list is not understood.")
        service, unit, currency = item.get("service"), item.get("unit"), item.get("currency")
        pair = re.sub(r"\s+", "", str(item.get("pair") or "")).upper().replace("<", ">")
        rate = _rate(item.get("rate"))
        if service not in Quotation.Service.values or unit not in Quotation.Unit.values or currency not in Quotation.Currency.values:
            raise Refused("bad_item", "اختار الخدمة والوحدة والعملة في كل سطر.", "Choose the service, the unit and the currency on every line.")
        if pair and not PAIR.match(pair):
            raise Refused("bad_pair", f"زوج اللغات «{pair}» يتكتب زي EN>AR، أو سيبه فاضي لأي زوج.", f"Write the pair «{pair}» like EN>AR, or leave it empty for any pair.")
        if rate is None:
            raise Refused("bad_rate", "السعر لازم يبقى رقم أكبر من صفر.", "A price must be a number above zero.")
        key = (service, unit, currency, pair)
        if key in seen:
            raise Refused("twice", "نفس الخدمة والوحدة والعملة والزوج اتكتبوا مرتين.", "The same service, unit, currency and pair are written twice.")
        seen.add(key)
        rows.append(PriceItem(service=service, unit=unit, currency=currency, pair=pair, rate=rate))
    with transaction.atomic():
        # The versions are counted under a lock, so two saves at once cannot make the same number.
        list(PriceList.objects.select_for_update().all()[:1])
        number = (PriceList.objects.aggregate(top=Max("version"))["top"] or 0) + 1
        version = PriceList.objects.create(version=number, note=(note or "")[:250], created_by=actor)
        for row in rows:
            row.price_list = version
        PriceItem.objects.bulk_create(rows)
    services.log(actor, "pricing.version", f"v{number}", f"{len(rows)} price(s)")
    return version


def _limit_value(value):
    try:
        limit = Decimal(str(value).strip())
    except Exception:  # noqa: BLE001
        limit = None
    if limit is None or not limit.is_finite() or not Decimal(0) <= limit <= HUNDRED or limit != limit.quantize(CENT):
        raise Refused("bad_limit", "الحد نسبة من 0 لـ 100.", "A limit is a percentage from 0 to 100.")
    return limit


def save_limits(actor, sales, manager):
    from . import services

    _owner(actor)
    sales, manager = _limit_value(sales), _limit_value(manager)
    if manager < sales:
        raise Refused("manager_below", "حد المانجر مايبقاش أقل من حد الـSales.", "The manager's limit cannot be below the Sales person's.")
    conf = AppSettings.load()
    conf.discount_limit_sales, conf.discount_limit_manager = sales, manager
    conf.save(update_fields=["discount_limit_sales", "discount_limit_manager"])
    services.log(actor, "pricing.limits", "settings", f"sales {sales} manager {manager}")
    return sales, manager


def limit_of(user, conf=None):
    """How far under the list this person may go without an approval."""
    conf = conf or AppSettings.load()
    if user.is_admin_role:
        return HUNDRED
    if user.is_sales and user.is_sales_manager:
        return conf.discount_limit_manager
    if user.is_sales:
        return conf.discount_limit_sales
    return Decimal(0)


def effective_discount(quote):
    """How far under the list the quotation is, in percent: ``1 - total / (quantity x list price)``. With no list price,
    its own discount."""
    if quote.list_rate:
        listed = Decimal(quote.quantity) * quote.list_rate
        if listed > 0:
            off = (Decimal(1) - Decimal(quote.total) / listed) * HUNDRED
            return max(Decimal(0), off.quantize(CENT, rounding=ROUND_HALF_UP))
    return Decimal(quote.discount_percent).quantize(CENT)


def price(quote, user):
    """Price a quotation being saved against the list in force, and say whether its discount needs an approval. Called
    by ``b2b.save_quotation`` before the save."""
    version = current()
    item = item_for(version, quote.service, quote.unit, quote.currency, quote.source_lang, quote.target_lang)
    quote.price_list = version if item is not None else None
    quote.list_rate = item.rate if item is not None else None
    quote.effective_discount = effective_discount(quote)
    over = quote.effective_discount > limit_of(user)
    quote.discount_state = PENDING if over else ""
    quote.discount_by, quote.discount_at, quote.discount_note = None, None, ""
    return over


def may_approve(user, quote):
    """The owner; or a Sales manager of the quotation's team, up to their limit - never on their own quotation."""
    if user.is_admin_role:
        return True
    if quote.owner_id == user.pk or not manages(user, quote.lead.sheet):
        return False
    return quote.effective_discount <= limit_of(user)


def approvers(quote):
    """Who is told a discount waits: the team's managers who may approve it, and the owner."""
    people = User.objects.filter(is_active=True).filter(role__in=(Role.ADMIN, Role.SALES))
    return [person for person in people if (person.is_admin_role or person.is_sales_manager) and may_approve(person, quote)]


def tell_approvers(quote):
    from . import services

    for person in approvers(quote):
        if person.pk == quote.owner_id:
            continue
        services.notify(
            person,
            title_ar="خصم محتاج اعتمادك",
            title_en="A discount needs your approval",
            body_ar=f"العرض {quote.code} تحت قايمة الأسعار بـ{quote.effective_discount}%، أكتر من حد صاحبه.",
            body_en=f"Quotation {quote.code} is {quote.effective_discount}% under the price list, beyond its maker's limit.",
            level="warning", url="/app/price-list",
        )


def decide(quote, user, approved, note=""):
    """Approve or turn down a discount that waits. Turning down needs the reason; the maker is told either way."""
    from . import services

    note = (note or "").strip()[:250]
    with transaction.atomic():
        row = Quotation.objects.select_for_update().get(pk=quote.pk)
        row.lead = quote.lead
        if row.discount_state != PENDING or row.status != Quotation.Status.DRAFT:
            raise Refused("not_pending", "العرض ده مش مستني اعتماد خصم.", "This quotation is not waiting for a discount approval.")
        if not may_approve(user, row):
            raise Refused("not_yours", "الخصم ده أكبر من حدك أو العرض بتاعك.", "This discount is beyond your limit, or the quotation is yours.")
        if not approved and not note:
            raise Refused("needs_reason", "اكتب سبب الرفض.", "Write why it is turned down.")
        row.discount_state = APPROVED if approved else REJECTED
        row.discount_by, row.discount_at, row.discount_note = user, timezone.now(), note
        row.save(update_fields=["discount_state", "discount_by", "discount_at", "discount_note", "updated_at"])
    services.log(user, "pricing.discount_approve" if approved else "pricing.discount_reject", row.code, f"{row.effective_discount}% {note}"[:200])
    if row.owner_id and row.owner_id != user.pk:
        services.notify(
            row.owner,
            title_ar="الخصم اتعتمد" if approved else "الخصم اترفض",
            title_en="The discount was approved" if approved else "The discount was turned down",
            body_ar=f"العرض {row.code}: {'تقدر تبعته دلوقتي' if approved else note}",
            body_en=f"Quotation {row.code}: {'you may send it now' if approved else note}",
            level="success" if approved else "warning", url=f"/app/leads/{row.lead.sheet_id}",
        )
    return row


def waiting_for(user):
    """The quotations whose discount this person may approve, oldest first."""
    rows = Quotation.objects.filter(discount_state=PENDING, status=Quotation.Status.DRAFT).select_related(
        "lead", "lead__sheet", "owner",
    ).order_by("updated_at")
    if not user.is_admin_role:
        rows = rows.filter(lead__sheet__in=sheets_for(user))
    return [quote for quote in rows[:300] if may_approve(user, quote)]
