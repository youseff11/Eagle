"""Sales commissions (part 3, 15/10/2026; the B2C requirements' section 10, for both Sales teams).

The owner's decisions, as he gave them:

1. the rate is his to set, as he likes: the company's (``AppSettings.commission_rate``), a person's own
   (``User.commission_rate``), or one line's (``Commission.rate``) - the most particular one counts;
2. it is counted on the invoice's whole amount (``Invoice.amount``);
3. it is due once the client has paid the invoice in full (``Invoice.Status.PAID``): a part payment does not make it due;
4. when several people worked the deal he splits it, each person's ``share`` in percent, adding up to 100;
5. he alone approves it and marks it paid - not the Sales manager, not Accounting;
6. both teams, B2B and B2C.

An invoice made from a Sales person's accepted quotation gets its line by itself, the whole of it theirs
(``ensure_default``). Until a line is approved its figures follow the invoice and the rates; approving writes them down. A
cancelled invoice cancels its lines that were not approved (an invoice with money on it cannot be cancelled). Every change
is in the audit log. Who reads: the owner every line; a Sales person their own; a Sales manager their own team's too.
"""

from decimal import ROUND_HALF_UP, Decimal

from django.db import transaction
from django.db.models import Q, Sum
from django.utils import timezone

from .b2b import track_q
from .models import AppSettings, Commission, Invoice, Role, User

CENT = Decimal("0.01")
HUNDRED = Decimal("100")
MAX_PEOPLE = 10


class Refused(Exception):
    """Nothing was done, and why: a short code for the page and the reason in both languages."""

    def __init__(self, code, ar, en):
        super().__init__(code)
        self.code, self.ar, self.en = code, ar, en


def has_door(user):
    """The owner (every line) and the Sales people (their own; a manager their team's)."""
    return bool(getattr(user, "is_authenticated", False) and (user.is_admin_role or user.is_sales))


def lines_for(user):
    rows = Commission.objects.select_related("invoice", "invoice__client", "person", "approved_by", "paid_by")
    if user.is_admin_role:
        return rows
    if user.is_sales and user.is_sales_manager:
        return rows.filter(Q(person=user) | Q(person__in=User.objects.filter(track_q(user.sales_market), role=Role.SALES)))
    if user.is_sales:
        return rows.filter(person=user)
    return rows.none()


def money(value):
    return Decimal(value).quantize(CENT, rounding=ROUND_HALF_UP)


def _owner(user):
    if not user.is_admin_role:
        raise Refused("forbidden", "العمولات بيعتمدها ويظبطها المالك بس.", "Commissions are set and approved by the owner alone.")


def effective_rate(line, conf=None):
    """The rate the line is counted at: its own, else the person's, else the company's; ``None`` when none is set."""
    if line.status in (Commission.Status.APPROVED, Commission.Status.PAID):
        return line.rate
    if line.rate is not None:
        return line.rate
    if line.person.commission_rate is not None:
        return line.person.commission_rate
    return (conf or AppSettings.load()).commission_rate


def figures(line, conf=None):
    """``{"base", "currency", "rate", "amount", "egp_rate", "amount_egp"}``: written down once approved, worked out from the
    invoice and the rates until then. A figure that cannot be known yet (no rate, no exchange rate) is ``None``."""
    if line.status in (Commission.Status.APPROVED, Commission.Status.PAID):
        return {
            "base": line.base, "currency": line.currency, "rate": line.rate, "amount": line.amount,
            "egp_rate": line.egp_rate, "amount_egp": line.amount_egp,
        }
    invoice = line.invoice
    rate = effective_rate(line, conf)
    amount = None if rate is None else money(invoice.amount * line.share / HUNDRED * rate / HUNDRED)
    egp = invoice.egp_rate
    return {
        "base": invoice.amount, "currency": invoice.currency, "rate": rate, "amount": amount, "egp_rate": egp,
        "amount_egp": None if amount is None or not egp else money(amount * egp),
    }


def is_due(line):
    """The client paid the invoice in full: the line may be approved and paid."""
    return line.invoice.status == Invoice.Status.PAID


def ensure_default(invoice, by=None):
    """The invoice of a Sales person's deal gets their line, the whole of it theirs. Nothing when it has lines already or
    no Sales person."""
    from . import services

    if invoice.owner_id is None or invoice.status == Invoice.Status.CANCELLED or invoice.commissions.exists():
        return None
    line, made = Commission.objects.get_or_create(invoice=invoice, person_id=invoice.owner_id)
    if made:
        services.log(by, "commission.make", line.code, f"{invoice.code} {invoice.owner.username} 100%")
    return line


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


def set_line_rate(actor, line, value):
    from . import services

    _owner(actor)
    rate = _rate(value)
    with transaction.atomic():
        row = Commission.objects.select_for_update().get(pk=line.pk)
        if row.status != Commission.Status.PENDING:
            raise Refused("not_pending", "العمولة دي اتعتمدت. رجّعها الأول لو عايز تغيّرها.", "This commission is approved. Take it back first to change it.")
        before = row.rate
        row.rate = rate
        row.save(update_fields=["rate"])
    services.log(actor, "commission.line_rate", row.code, f"{before} -> {rate}")
    return row


def set_split(actor, invoice, shares):
    """``shares`` = ``[(person, share), ...]``: who worked the deal and each one's part, adding up to 100. Replaces the
    invoice's lines, while none of them is approved yet."""
    from . import services

    _owner(actor)
    if not shares or len(shares) > MAX_PEOPLE:
        raise Refused("no_people", "اختار مين اشتغل على الصفقة.", "Choose who worked the deal.")
    people = [person.pk for person, _share in shares]
    if len(set(people)) != len(people):
        raise Refused("twice", "نفس الشخص اتكتب مرتين.", "The same person is written twice.")
    for person, share in shares:
        if not person.is_sales:
            raise Refused("not_sales", "العمولة للـSales بس.", "Commissions are for Sales people only.")
        if share is None or not Decimal(0) < share <= HUNDRED or share != share.quantize(CENT):
            raise Refused("bad_share", "نصيب كل واحد رقم أكبر من صفر ولحد 100.", "Each share is a number above zero, up to 100.")
    if sum(share for _person, share in shares) != HUNDRED:
        raise Refused("not_whole", "مجموع النصيب لازم يبقى 100%.", "The shares must add up to 100%.")
    with transaction.atomic():
        locked = Invoice.objects.select_for_update().get(pk=invoice.pk)
        if locked.status == Invoice.Status.CANCELLED:
            raise Refused("cancelled", "الفاتورة دي اتلغت.", "This invoice was cancelled.")
        lines = list(Commission.objects.select_for_update().filter(invoice=locked))
        if any(line.status in (Commission.Status.APPROVED, Commission.Status.PAID) for line in lines):
            raise Refused("decided", "فيه عمولة على الفاتورة دي اتعتمدت. رجّعها الأول.", "A commission on this invoice is approved. Take it back first.")
        kept = {line.person_id: line for line in lines}
        for line in lines:
            if line.person_id not in people:
                line.delete()
        for person, share in shares:
            line = kept.get(person.pk) or Commission(invoice=locked, person=person)
            line.share = share
            line.status = Commission.Status.PENDING
            line.save()
    services.log(actor, "commission.split", invoice.code, ", ".join(f"{p.username} {s}%" for p, s in shares))
    return list(invoice.commissions.select_related("person"))


def approve(actor, line, note=""):
    """The owner approves a line of a paid invoice: its figures are written down as they stand now."""
    from . import services

    _owner(actor)
    conf = AppSettings.load()
    with transaction.atomic():
        row = Commission.objects.select_for_update().get(pk=line.pk)
        invoice = Invoice.objects.get(pk=row.invoice_id)
        row.invoice = invoice
        if row.status != Commission.Status.PENDING:
            raise Refused("not_pending", "العمولة دي مش مستنية اعتماد.", "This commission is not waiting for approval.")
        if invoice.status != Invoice.Status.PAID:
            raise Refused("not_paid", "العمولة بتستحق لما العميل يدفع الفاتورة كلها.", "A commission is due once the client has paid the whole invoice.")
        if invoice.commissions.exclude(status=Commission.Status.CANCELLED).aggregate(total=Sum("share"))["total"] != HUNDRED:
            raise Refused("not_whole", "مجموع النصيب على الفاتورة دي مش 100%. ظبّط التقسيم الأول.", "The shares on this invoice do not add up to 100%. Fix the split first.")
        figure = figures(row, conf)
        if figure["rate"] is None:
            raise Refused("no_rate", "لسه مفيش نسبة عمولة. حط النسبة الأول.", "No commission rate is set yet. Set the rate first.")
        row.base, row.currency, row.rate = figure["base"], figure["currency"], figure["rate"]
        row.amount, row.egp_rate, row.amount_egp = figure["amount"], figure["egp_rate"], figure["amount_egp"]
        row.status = Commission.Status.APPROVED
        row.approved_by, row.approved_at = actor, timezone.now()
        row.note = (note or "")[:250]
        row.save()
    services.log(actor, "commission.approve", row.code, f"{row.amount} {row.currency} ({row.rate}% of {row.share}%)")
    return row


def mark_paid(actor, line):
    from . import services

    _owner(actor)
    with transaction.atomic():
        row = Commission.objects.select_for_update().get(pk=line.pk)
        if row.status != Commission.Status.APPROVED:
            raise Refused("not_approved", "العمولة بتتصرف بعد ما تتعتمد.", "A commission is paid after it is approved.")
        if Invoice.objects.get(pk=row.invoice_id).status != Invoice.Status.PAID:
            raise Refused("not_paid", "الفاتورة مابقتش مدفوعة كلها (دفعة اتمسحت؟). راجعها الأول.", "The invoice is no longer fully paid (a payment removed?). Check it first.")
        row.status = Commission.Status.PAID
        row.paid_by, row.paid_at = actor, timezone.now()
        row.save(update_fields=["status", "paid_by", "paid_at"])
    services.log(actor, "commission.paid", row.code, f"{row.amount} {row.currency}")
    services.notify(
        row.person,
        title_ar="عمولة اتصرفت",
        title_en="A commission was paid",
        body_ar=f"عمولتك {row.code} على الفاتورة {row.invoice.code} اتصرفت.",
        body_en=f"Your commission {row.code} on invoice {row.invoice.code} was paid.",
        level="success", url="/app/commissions",
    )
    return row


def take_back(actor, line):
    """An approval made by mistake goes back to pending (its figures follow the rates again). A paid one stays paid."""
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
    """The invoice was cancelled: its lines not approved are cancelled with it (kept, not deleted)."""
    from . import services

    count = invoice.commissions.filter(status=Commission.Status.PENDING).update(status=Commission.Status.CANCELLED)
    if count:
        services.log(by, "commission.cancel", invoice.code, f"{count} line(s)")
    return count


def uncovered_invoices(limit=100):
    """Invoices with no commission line yet (made by hand, with no Sales person): the owner splits them if anybody sold
    them. Cancelled ones are left out."""
    return (
        Invoice.objects.exclude(status=Invoice.Status.CANCELLED).filter(commissions__isnull=True)
        .select_related("client").order_by("-created_at")[:limit]
    )
