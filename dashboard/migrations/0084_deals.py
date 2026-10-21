"""Commissions per deal (21/10/2026, the owner's change): a deal a Sales person closed, and each person's percent of it.

The tables only. The lines are moved onto their deals in 0085 and the old columns go in 0086, each in its own transaction:
Postgres builds the indexes of a migration at its end, and refuses to while rows changed in the same transaction (the
first deploy failed on "cannot CREATE INDEX ... pending trigger events"; SQLite never says so).
"""

import django.db.models.deletion
from django.conf import settings
from django.db import migrations, models
from django.utils import timezone


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
        # A line made by the backfill (0085) has no invoice: the column takes none until 0086 drops it.
        migrations.AlterField(
            model_name='commission',
            name='invoice',
            field=models.ForeignKey(null=True, on_delete=django.db.models.deletion.CASCADE, related_name='commissions', to='dashboard.invoice'),
        ),
    ]
