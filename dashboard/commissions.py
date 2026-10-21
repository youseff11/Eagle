"""Sales commissions, per deal (part 3 of 15/10/2026, changed by the owner on 21/10/2026; both Sales teams).

The owner's decisions, as he gave them:

1. a deal is a company a Sales person moved to «تم التعاقد» on a sheet (by the cell, a call, an accepted quotation or the
   «شركة جديدة» form, all through ``b2b.note_status``): it shows on the commissions page by itself, with what it was about
   (``deal_from_lead``), and the one who closed it gets its first line;
2. he sets each person's commission himself, in percent of the deal's value, and when several people worked it each one
   gets their own percent (``set_deal``); a line with none takes the person's own rate (``User.commission_rate``), or else the
   company's (``AppSettings.commission_rate``);
3. the value starts from the deal's accepted quotation (its total and currency), else the row's «deal value» in EGP, and he
   may correct it; the invoice made from the quotation fills a value he did not write himself;
4. a commission is due once the client has paid the deal's invoice in full (``Invoice.Status.PAID``): a part payment does
   not make it due. The invoice is the one made from the deal's quotation, or the one he links;
5. he alone approves it and marks it paid - not the Sales manager, not Accounting.

Until a line is approved its figures follow the deal and the rates; approving writes them down. A deal made by mistake is
cancelled, with its lines, while none is approved. An invoice with no deal (made by hand) can become one. Every change is
in the audit log. Who reads: the owner every deal; a Sales person the deals they have a line on, their own line only; a
Sales manager their team's lines too.
"""

import logging
from decimal import ROUND_HALF_UP, Decimal

from django.db import IntegrityError, transaction
from django.db.models import Prefetch, Q
from django.utils import timezone

from .b2b import track_q
from .models import HOME_CURRENCY, AppSettings, Commission, Deal, Invoice, Quotation, Role, User

logger = logging.getLogger(__name__)

CENT = Decimal("0.01")
HUNDRED = Decimal("100")
MAX_PEOPLE = 10
MAX_VALUE = Decimal("999999999999.99")
CURRENCIES = tuple(value for value, _label in Quotation.Currency.choices)
DECIDED = (Commission.Status.APPROVED, Commission.Status.PAID)


class Refused(Exception):
    """Nothing was done, and why: a short code for the page and the reason in both languages."""

    def __init__(self, code, ar, en):
        super().__init__(code)
        self.code, self.ar, self.en = code, ar, en


def has_door(user):
    """The owner (every deal) and the Sales people (their own lines; a manager their team's)."""
    return bool(getattr(user, "is_authenticated", False) and (user.is_admin_role or user.is_sales))


def lines_for(user):
    rows = Commission.objects.select_related("deal", "person", "approved_by", "paid_by")
    if user.is_admin_role:
        return rows
    if user.is_sales and user.is_sales_manager:
        return rows.filter(Q(person=user) | Q(person__in=User.objects.filter(track_q(user.sales_market), role=Role.SALES)))
    if user.is_sales:
        return rows.filter(person=user)
    return rows.none()


def deals_for(user):
    """The deals the reader reads, each with ``shown`` = the lines of it they read, the newest first."""
    lines = lines_for(user).order_by("created_at", "id")
    rows = Deal.objects.select_related("lead", "lead__sheet", "owner", "won_by", "quotation", "invoice", "client")
    if not user.is_admin_role:
        rows = rows.filter(pk__in=lines.values("deal_id"))
    return rows.prefetch_related(Prefetch("lines", queryset=lines, to_attr="shown"))


def money(value):
    return Decimal(value).quantize(CENT, rounding=ROUND_HALF_UP)


def _owner(user):
    if not user.is_admin_role:
        raise Refused("forbidden", "العمولات بيعتمدها ويظبطها المالك بس.", "Commissions are set and approved by the owner alone.")


def effective_rate(line, conf=None):
    """The rate the line is counted at: its own, else the person's, else the company's; ``None`` when none is set."""
    if line.status in DECIDED:
        return line.rate
    if line.rate is not None:
        return line.rate
    if line.person.commission_rate is not None:
        return line.person.commission_rate
    return (conf or AppSettings.load()).commission_rate


def egp_rate_of(deal):
    """What one unit of the deal's currency is in EGP: 1 for EGP, the invoice's own rate when it is in the same currency,
    else the newest invoice's in that currency; ``None`` when none is known."""
    from . import finance

    if not deal.currency:
        return None
    if deal.currency == HOME_CURRENCY:
        return Decimal("1")
    invoice = deal.invoice
    if invoice is not None and invoice.currency == deal.currency and invoice.egp_rate:
        return invoice.egp_rate
    return finance.last_rate(deal.currency)


def figures(line, conf=None, egp=None):
    """``{"base", "currency", "rate", "amount", "egp_rate", "amount_egp"}``: written down once approved, worked out from the
    deal and the rates until then. A figure that cannot be known yet (no value, no rate, no exchange rate) is ``None``.
    ``egp``: the deal's exchange rate when the caller has it already."""
    if line.status in DECIDED:
        return {
            "base": line.base, "currency": line.currency, "rate": line.rate, "amount": line.amount,
            "egp_rate": line.egp_rate, "amount_egp": line.amount_egp,
        }
    deal = line.deal
    rate = effective_rate(line, conf)
    amount = None if rate is None or deal.value is None else money(deal.value * rate / HUNDRED)
    if egp is None:
        egp = egp_rate_of(deal)
    return {
        "base": deal.value, "currency": deal.currency, "rate": rate, "amount": amount, "egp_rate": egp,
        "amount_egp": None if amount is None or not egp else money(amount * egp),
    }


def is_paid(deal):
    """The client paid the deal's invoice in full: its lines may be approved and paid."""
    return deal.status == Deal.Status.OPEN and deal.invoice is not None and deal.invoice.status == Invoice.Status.PAID


def is_due(line):
    return is_paid(line.deal)


def _decided(deal):
    return deal.lines.filter(status__in=DECIDED).exists()


def _new_line(deal, person, by=None):
    from . import services

    line = Commission.objects.create(deal=deal, person=person)
    services.log(by, "commission.make", line.code, f"{deal.code} {person.username}")
    return line


def _value_of_lead(lead):
    """``(value, currency, quotation)`` a deal on this company starts from: its accepted quotation, else the row's
    «deal value» (in EGP: the B2C team's companies are in Egypt, and the sheet holds no currency), else nothing."""
    quote = lead.quotations.filter(status=Quotation.Status.ACCEPTED).order_by("-decided_at", "-id").first()
    if quote is not None:
        return quote.total, quote.currency, quote
    if lead.deal_value is not None:
        return lead.deal_value, HOME_CURRENCY, None
    return None, "", None


def deal_from_lead(lead, by=None):
    """The company moved to «تم التعاقد»: its deal shows on the commissions page, the sheet's Sales person on it, and the
    owner hears of it. Nothing when the company has an open deal already. Never stops the move that made it: a failure is
    written to the log and the move stands."""
    try:
        with transaction.atomic():
            return _deal_from_lead(lead, by)
    except IntegrityError:  # the same company moved twice at once: the other one made it
        return None
    except Exception:  # noqa: BLE001
        logger.exception("The deal of lead %s was not made", lead.pk)
        return None


def _deal_from_lead(lead, by):
    from . import services

    if Deal.objects.filter(lead=lead, status=Deal.Status.OPEN).exists():
        return None
    sheet = lead.sheet
    owner = sheet.assigned_to
    value, currency, quote = _value_of_lead(lead)
    invoice = None
    if quote is not None:
        invoice = (
            quote.invoices.exclude(status=Invoice.Status.CANCELLED)
            .exclude(deals__status=Deal.Status.OPEN).order_by("-created_at").first()
        )
    deal = Deal.objects.create(
        lead=lead, market=sheet.market, company=lead.company_name, client=lead.client, owner=owner, quotation=quote,
        invoice=invoice, value=value, currency=currency, won_by=by,
    )
    services.log(by, "commission.deal", deal.code, f"lead {lead.pk} {owner.username} {value} {currency}")
    if owner.is_sales:
        _new_line(deal, owner, by)
    worth = f" ({value:.2f} {currency})" if value is not None else ""
    for person in User.objects.filter(role=Role.ADMIN, is_active=True):
        services.notify(
            person,
            title_ar="صفقة جديدة",
            title_en="A new deal",
            body_ar=f"{owner.get_full_name() or owner.username} قفل صفقة مع {lead.company_name}{worth}. حدد العمولة من «العمولات».",
            body_en=f"{owner.get_full_name() or owner.username} closed a deal with {lead.company_name}{worth}. Set the commission under «Commissions».",
            level="success", url="/app/commissions",
        )
    return deal


def deal_for_invoice(invoice, by=None):
    """An invoice was drafted from an accepted quotation: it becomes its company's deal's invoice (and its amount the value,
    unless the owner wrote one himself). A company with no open deal gets one, the invoice's Sales person on it."""
    from . import services

    if invoice.status == Invoice.Status.CANCELLED or Deal.objects.filter(invoice=invoice, status=Deal.Status.OPEN).exists():
        return None
    quote = invoice.quotation
    lead = quote.lead if quote is not None else None
    deal = None
    if lead is not None:
        deal = Deal.objects.select_for_update().filter(lead=lead, status=Deal.Status.OPEN).first()
    if deal is not None and deal.invoice_id is None:
        deal.invoice = invoice
        deal.quotation = deal.quotation or quote
        fields = ["invoice", "quotation"]
        if not deal.value_by_hand and not _decided(deal):
            deal.value, deal.currency = invoice.amount, invoice.currency
            fields += ["value", "currency"]
        deal.save(update_fields=fields)
        services.log(by, "commission.deal_invoice", deal.code, f"{invoice.code} (automatic)")
        return deal
    if deal is not None or invoice.owner is None:
        return None
    return _deal_of_invoice(invoice, invoice.owner, by)


def _deal_of_invoice(invoice, person, by):
    from . import services

    quote = invoice.quotation
    lead = quote.lead if quote is not None else None
    if lead is not None and Deal.objects.filter(lead=lead, status=Deal.Status.OPEN).exists():
        lead = None
    deal = Deal.objects.create(
        lead=lead, market=lead.sheet.market if lead is not None else (person.sales_market if person else "b2b"),
        company=lead.company_name if lead is not None else "", client=invoice.client, owner=person, quotation=quote,
        invoice=invoice, value=invoice.amount, currency=invoice.currency, won_by=by,
    )
    services.log(by, "commission.deal", deal.code, f"{invoice.code} {person.username if person else ''}")
    if person is not None and person.is_sales:
        _new_line(deal, person, by)
    return deal


def deal_from_invoice(actor, invoice):
    """The owner makes a deal of an invoice that has none (one made by hand): its people are his to choose next."""
    _owner(actor)
    with transaction.atomic():
        locked = Invoice.objects.select_for_update().get(pk=invoice.pk)
        if locked.status == Invoice.Status.CANCELLED:
            raise Refused("cancelled", "الفاتورة دي اتلغت.", "This invoice was cancelled.")
        if Deal.objects.filter(invoice=locked, status=Deal.Status.OPEN).exists():
            raise Refused("has_deal", "الفاتورة دي عليها صفقة بالفعل.", "This invoice has a deal already.")
        owner = locked.owner if locked.owner is not None and locked.owner.is_sales else None
        return _deal_of_invoice(locked, owner, actor)


def _rate(value):
    """A rate in percent, 0 to 100, two places; ``None`` for nothing. ``Refused`` for anything else."""
    if value in (None, ""):
        return None
    try:
        rate = Decimal(str(value).strip().replace("%", ""))
    except Exception:  # noqa: BLE001 - anything that is not a number
        rate = None
    if rate is None or not rate.is_finite() or not Decimal(0) <= rate <= HUNDRED or rate != rate.quantize(CENT):
        raise Refused("bad_rate", "النسبة رقم من 0 لـ 100 (لحد رقمين بعد العلامة).", "A rate is a number from 0 to 100 (up to two decimals).")
    return rate


def _value(value):
    """A deal's value: above zero, two places; ``None`` for nothing."""
    if value in (None, ""):
        return None
    try:
        number = Decimal(str(value).strip().replace(",", ""))
    except Exception:  # noqa: BLE001
        number = None
    if number is None or not number.is_finite() or not Decimal(0) < number <= MAX_VALUE or number != number.quantize(CENT):
        raise Refused("bad_value", "قيمة الصفقة رقم أكبر من صفر (لحد رقمين بعد العلامة).", "The deal's value is a number above zero (up to two decimals).")
    return number


def set_company_rate(actor, value):
    from . import services

    _owner(actor)
    rate = _rate(value)
    conf = AppSettings.load()
    before = conf.commission_rate
    conf.commission_rate = rate
    conf.save(update_fields=["commission_rate"])
    services.log(actor, "commission.company_rate", "settings", f"{before} -> {rate}")
    return rate


def set_person_rate(actor, person, value):
    from . import services

    _owner(actor)
    if not person.is_sales:
        raise Refused("not_sales", "العمولة للـSales بس.", "Commissions are for Sales people only.")
    rate = _rate(value)
    before = person.commission_rate
    User.objects.filter(pk=person.pk).update(commission_rate=rate)
    person.commission_rate = rate
    services.log(actor, "commission.person_rate", person.username, f"{before} -> {rate}")
    return rate


KEEP = object()


def set_deal(actor, deal, *, value=KEEP, currency=KEEP, invoice=KEEP, people=KEEP, note=KEEP):
    """The owner sets up a deal: its value and currency, its invoice (``None`` unlinks it), and ``people`` =
    ``[(person, rate), ...]`` - who earned a commission on it and each one's percent of the value (``None`` = the person's
    own rate, or else the company's). Replaces the deal's lines. Only what is passed changes, while none of its lines is
    approved."""
    from . import services

    _owner(actor)
    if value is not KEEP:
        value = _value(value)
    if currency is not KEEP and currency not in CURRENCIES:
        raise Refused("bad_currency", "اختار العملة.", "Choose the currency.")
    if people is not KEEP:
        if not people or len(people) > MAX_PEOPLE:
            raise Refused("no_people", "اختار مين اشتغل على الصفقة.", "Choose who worked the deal.")
        ids = [person.pk for person, _rate_value in people]
        if len(set(ids)) != len(ids):
            raise Refused("twice", "نفس الشخص اتكتب مرتين.", "The same person is written twice.")
        if any(not person.is_sales for person, _rate_value in people):
            raise Refused("not_sales", "العمولة للـSales بس.", "Commissions are for Sales people only.")
        people = [(person, _rate(rate)) for person, rate in people]
        if sum(rate for _person, rate in people if rate is not None) > HUNDRED:
            raise Refused("over_whole", "مجموع النسب على الصفقة أكتر من 100%.", "The rates on this deal add up to more than 100%.")
    with transaction.atomic():
        locked = Deal.objects.select_for_update().get(pk=deal.pk)
        if locked.status != Deal.Status.OPEN:
            raise Refused("cancelled", "الصفقة دي اتلغت.", "This deal was cancelled.")
        if _decided(locked):
            raise Refused("decided", "فيه عمولة على الصفقة دي اتعتمدت. رجّعها الأول.", "A commission on this deal is approved. Take it back first.")
        changed = []
        if value is not KEEP and value != locked.value:
            locked.value, locked.value_by_hand = value, value is not None
            changed += ["value", "value_by_hand"]
        if currency is not KEEP and currency != locked.currency:
            locked.currency = currency
            changed.append("currency")
        if invoice is not KEEP and (invoice.pk if invoice else None) != locked.invoice_id:
            if invoice is not None:
                if invoice.status == Invoice.Status.CANCELLED:
                    raise Refused("cancelled_invoice", "الفاتورة دي اتلغت.", "This invoice was cancelled.")
                if Deal.objects.filter(invoice=invoice, status=Deal.Status.OPEN).exclude(pk=locked.pk).exists():
                    raise Refused("invoice_taken", "الفاتورة دي على صفقة تانية.", "This invoice is on another deal.")
            locked.invoice = invoice
            changed.append("invoice")
        if note is not KEEP:
            locked.note = (note or "")[:250]
            changed.append("note")
        if changed:
            locked.save(update_fields=changed)
        if people is not KEEP:
            lines = {line.person_id: line for line in Commission.objects.select_for_update().filter(deal=locked)}
            wanted = {person.pk for person, _rate_value in people}
            for person_id, line in lines.items():
                if person_id not in wanted:
                    line.delete()
            for person, rate in people:
                line = lines.get(person.pk) or Commission(deal=locked, person=person)
                line.rate, line.status = rate, Commission.Status.PENDING
                line.save()
    detail = [f"{name}={getattr(locked, name)}" for name in changed if name not in ("value_by_hand",)]
    if people is not KEEP:
        detail.append(", ".join(f"{p.username} {r if r is not None else '-'}%" for p, r in people))
    services.log(actor, "commission.deal_set", locked.code, "; ".join(str(item) for item in detail))
    return locked


def cancel_deal(actor, deal):
    """A deal made by mistake (a company moved to «تم التعاقد» by error): it and its lines are cancelled, kept, while none
    of them is approved."""
    from . import services

    _owner(actor)
    with transaction.atomic():
        locked = Deal.objects.select_for_update().get(pk=deal.pk)
        if locked.status != Deal.Status.OPEN:
            raise Refused("cancelled", "الصفقة دي اتلغت قبل كده.", "This deal was cancelled already.")
        if _decided(locked):
            raise Refused("decided", "فيه عمولة على الصفقة دي اتعتمدت. رجّعها الأول.", "A commission on this deal is approved. Take it back first.")
        locked.status = Deal.Status.CANCELLED
        locked.save(update_fields=["status"])
        locked.lines.update(status=Commission.Status.CANCELLED)
    services.log(actor, "commission.deal_cancel", locked.code, "")
    return locked


def approve(actor, line, note=""):
    """The owner approves a line once its deal's invoice is paid in full: its figures are written down as they stand now."""
    from . import services

    _owner(actor)
    conf = AppSettings.load()
    with transaction.atomic():
        row = Commission.objects.select_for_update().get(pk=line.pk)
        row.deal = Deal.objects.select_related("invoice").get(pk=row.deal_id)
        if row.status != Commission.Status.PENDING:
            raise Refused("not_pending", "العمولة دي مش مستنية اعتماد.", "This commission is not waiting for approval.")
        if row.deal.status != Deal.Status.OPEN:
            raise Refused("cancelled", "الصفقة دي اتلغت.", "This deal was cancelled.")
        if row.deal.invoice is None:
            raise Refused("no_invoice", "الصفقة لسه مالهاش فاتورة. اربطها بالفاتورة الأول.", "The deal has no invoice yet. Link it to its invoice first.")
        if not is_paid(row.deal):
            raise Refused("not_paid", "العمولة بتستحق لما العميل يدفع الفاتورة كلها.", "A commission is due once the client has paid the whole invoice.")
        if row.deal.value is None or not row.deal.currency:
            raise Refused("no_value", "لسه مفيش قيمة للصفقة. اكتبها الأول.", "The deal has no value yet. Write it first.")
        figure = figures(row, conf)
        if figure["rate"] is None:
            raise Refused("no_rate", "لسه مفيش نسبة عمولة. حط النسبة الأول.", "No commission rate is set yet. Set the rate first.")
        row.base, row.currency, row.rate = figure["base"], figure["currency"], figure["rate"]
        row.amount, row.egp_rate, row.amount_egp = figure["amount"], figure["egp_rate"], figure["amount_egp"]
        row.status = Commission.Status.APPROVED
        row.approved_by, row.approved_at = actor, timezone.now()
        row.note = (note or "")[:250]
        row.save()
    services.log(actor, "commission.approve", row.code, f"{row.amount} {row.currency} ({row.rate}% of {row.base})")
    return row


def mark_paid(actor, line):
    from . import services

    _owner(actor)
    with transaction.atomic():
        row = Commission.objects.select_for_update().get(pk=line.pk)
        deal = Deal.objects.select_related("invoice").get(pk=row.deal_id)
        if row.status != Commission.Status.APPROVED:
            raise Refused("not_approved", "العمولة بتتصرف بعد ما تتعتمد.", "A commission is paid after it is approved.")
        if not is_paid(deal):
            raise Refused("not_paid", "الفاتورة مابقتش مدفوعة كلها (دفعة اتمسحت؟). راجعها الأول.", "The invoice is no longer fully paid (a payment removed?). Check it first.")
        row.status = Commission.Status.PAID
        row.paid_by, row.paid_at = actor, timezone.now()
        row.save(update_fields=["status", "paid_by", "paid_at"])
    services.log(actor, "commission.paid", row.code, f"{row.amount} {row.currency}")
    services.notify(
        row.person,
        title_ar="عمولة اتصرفت",
        title_en="A commission was paid",
        body_ar=f"عمولتك {row.code} على الصفقة {deal.code} اتصرفت.",
        body_en=f"Your commission {row.code} on deal {deal.code} was paid.",
        level="success", url="/app/commissions",
    )
    return row


def take_back(actor, line):
    """An approval made by mistake goes back to pending (its figures follow the deal and the rates again). A paid one stays
    paid."""
    from . import services

    _owner(actor)
    with transaction.atomic():
        row = Commission.objects.select_for_update().get(pk=line.pk)
        if row.status != Commission.Status.APPROVED:
            raise Refused("not_approved", "اللي بيرجع هو العمولة المعتمدة اللي لسه ماتصرفتش.", "Only an approved commission not yet paid is taken back.")
        row.status = Commission.Status.PENDING
        row.base = row.amount = row.egp_rate = row.amount_egp = None
        row.currency = ""
        row.approved_by = row.approved_at = None
        row.save()
    services.log(actor, "commission.take_back", row.code, "")
    return row


def cancel_for(invoice, by=None):
    """The invoice was cancelled: the deals it was on lose it (none can have an approved line: an invoice with money on it
    is not cancelled), and wait for the next one."""
    from . import services

    count = Deal.objects.filter(invoice=invoice, status=Deal.Status.OPEN).update(invoice=None)
    if count:
        services.log(by, "commission.deal_invoice", invoice.code, f"cancelled: {count} deal(s) unlinked")
    return count


def uncovered_invoices(limit=100):
    """Invoices on no open deal (made by hand, or with no Sales person): the owner links one to its deal or makes a deal of
    it. Cancelled ones are left out."""
    return (
        Invoice.objects.exclude(status=Invoice.Status.CANCELLED).exclude(deals__status=Deal.Status.OPEN)
        .select_related("client").order_by("-created_at").distinct()[:limit]
    )
