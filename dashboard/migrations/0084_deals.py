"""Commissions per deal (21/10/2026, the owner's change): a deal a Sales person closed, and each person's percent of it.

The lines of 15/10 hung on an invoice, each with a ``share`` of it. Each invoice that has lines becomes a deal (its value
and currency the invoice's), and a line's share is folded into its rate: 50% of a 10% rate is 5% of the deal. The companies
moved to «تم التعاقد» on a sheet with no deal yet get theirs, with the Sales person who moved them, so the page shows the
deals closed before today too. The old columns go in 0085, in their own transaction (Postgres refuses to alter a table with
rows changed in the same one).
"""

import django.db.models.deletion
from decimal import ROUND_HALF_UP, Decimal
from django.conf import settings
from django.db import migrations, models
from django.utils import timezone

CENT = Decimal("0.01")


def deals_for_old_lines(apps, schema_editor):
    AppSettings = apps.get_model("dashboard", "AppSettings")
    Commission = apps.get_model("dashboard", "Commission")
    Deal = apps.get_model("dashboard", "Deal")
    Invoice = apps.get_model("dashboard", "Invoice")
    LeadActivity = apps.get_model("dashboard", "LeadActivity")
    Quotation = apps.get_model("dashboard", "Quotation")
    User = apps.get_model("dashboard", "User")

    conf = AppSettings.objects.first()
    company_rate = conf.commission_rate if conf is not None else None
    number = 0

    def make(**fields):
        nonlocal number
        number += 1
        return Deal.objects.create(code=f"DEAL-{number:04d}", **fields)

    invoice_ids = Commission.objects.order_by().values_list("invoice_id", flat=True).distinct()
    for invoice in Invoice.objects.filter(pk__in=list(invoice_ids)).order_by("id"):
        lines = list(Commission.objects.filter(invoice_id=invoice.pk).order_by("id"))
        quote = Quotation.objects.filter(pk=invoice.quotation_id).first() if invoice.quotation_id else None
        lead = quote.lead if quote is not None else None
        cancelled = invoice.status == "cancelled" or all(line.status == "cancelled" for line in lines)
        if lead is not None and not cancelled and Deal.objects.filter(lead=lead, status="open").exists():
            lead = None
        deal = make(
            lead=lead, market=lead.sheet.market if lead is not None else "b2b",
            company=lead.company_name if lead is not None else "", client_id=invoice.client_id,
            owner_id=invoice.owner_id or lines[0].person_id, quotation=quote,
            invoice=None if cancelled else invoice, value=invoice.amount, currency=invoice.currency,
            status="cancelled" if cancelled else "open", won_at=invoice.created_at,
        )
        for line in lines:
            share = line.share
            if share != Decimal("100"):
                rate = line.rate
                if rate is None and line.status == "pending":
                    person_rate = User.objects.filter(pk=line.person_id).values_list("commission_rate", flat=True).first()
                    rate = person_rate if person_rate is not None else company_rate
                line.rate = None if rate is None else (rate * share / Decimal("100")).quantize(CENT, rounding=ROUND_HALF_UP)
            line.deal = deal
            line.save(update_fields=["deal", "rate"])

    seen = set(Deal.objects.exclude(lead__isnull=True).values_list("lead_id", flat=True))
    moves = LeadActivity.objects.filter(kind="status", status="won", lead__status="won").select_related("lead__sheet", "owner")
    for move in moves.order_by("at", "id"):
        lead = move.lead
        if lead.pk in seen:
            continue
        seen.add(lead.pk)
        quote = Quotation.objects.filter(lead=lead, status="accepted").order_by("-decided_at", "-id").first()
        if quote is not None:
            value, currency = quote.total, quote.currency
        elif lead.deal_value is not None:
            value, currency = lead.deal_value, "EGP"
        else:
            value, currency = None, ""
        invoice = None
        if quote is not None:
            taken = Deal.objects.filter(status="open", invoice__isnull=False).values("invoice_id")
            invoice = Invoice.objects.filter(quotation=quote).exclude(status="cancelled").exclude(pk__in=taken).order_by("-id").first()
        owner = move.owner
        deal = make(
            lead=lead, market=lead.sheet.market, company=lead.company_name, client_id=lead.client_id, owner=owner,
            quotation=quote, invoice=invoice, value=value, currency=currency, won_at=move.at or timezone.now(),
            won_by_id=move.by_id,
        )
        if owner is not None and owner.role == "sales":
            line_number = Commission.objects.count() + 1
            while Commission.objects.filter(code=f"COM-{line_number:04d}").exists():
                line_number += 1
            Commission.objects.create(code=f"COM-{line_number:04d}", deal=deal, person=owner, invoice_id=None)


def back_to_invoices(apps, schema_editor):
    """Going back: a line with no invoice (a deal closed on a sheet) has no place on an invoice, and goes. The rates stay
    as they were folded."""
    apps.get_model("dashboard", "Commission").objects.filter(invoice__isnull=True).delete()


class Migration(migrations.Migration):

    dependencies = [
        ('dashboard', '0083_ai_translation'),
    ]

    operations = [
        migrations.CreateModel(
            name='Deal',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('code', models.CharField(blank=True, max_length=20, unique=True)),
                ('market', models.CharField(choices=[('b2b', 'B2B'), ('b2c', 'B2C')], default='b2b', max_length=3)),
                ('company', models.CharField(blank=True, max_length=160)),
                ('value', models.DecimalField(blank=True, decimal_places=2, max_digits=14, null=True)),
                ('currency', models.CharField(blank=True, max_length=3)),
                ('value_by_hand', models.BooleanField(default=False)),
                ('status', models.CharField(choices=[('open', 'Open'), ('cancelled', 'Cancelled')], db_index=True, default='open', max_length=10)),
                ('won_at', models.DateTimeField(default=timezone.now)),
                ('note', models.CharField(blank=True, max_length=250)),
                ('created_at', models.DateTimeField(auto_now_add=True)),
                ('client', models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name='deals', to='dashboard.client')),
                ('invoice', models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name='deals', to='dashboard.invoice')),
                ('lead', models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name='deals', to='dashboard.lead')),
                ('owner', models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name='closed_deals', to=settings.AUTH_USER_MODEL)),
                ('quotation', models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name='deals', to='dashboard.quotation')),
                ('won_by', models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name='+', to=settings.AUTH_USER_MODEL)),
            ],
            options={
                'ordering': ('-won_at', '-id'),
                'constraints': [
                    models.UniqueConstraint(condition=models.Q(('status', 'open')), fields=('lead',), name='one_open_deal_a_lead'),
                    models.UniqueConstraint(condition=models.Q(('status', 'open')), fields=('invoice',), name='one_open_deal_an_invoice'),
                ],
            },
        ),
        migrations.AddField(
            model_name='commission',
            name='deal',
            field=models.ForeignKey(null=True, on_delete=django.db.models.deletion.CASCADE, related_name='lines', to='dashboard.deal'),
        ),
        # A line made by the backfill below has no invoice: the column takes none until 0085 drops it.
        migrations.AlterField(
            model_name='commission',
            name='invoice',
            field=models.ForeignKey(null=True, on_delete=django.db.models.deletion.CASCADE, related_name='commissions', to='dashboard.invoice'),
        ),
        migrations.RunPython(deals_for_old_lines, back_to_invoices),
    ]
