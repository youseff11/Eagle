"""Commissions per deal, part two: every line has its deal now (0084), so the invoice and the share leave the line."""

import django.db.models.deletion
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('dashboard', '0084_deals'),
    ]

    operations = [
        migrations.RemoveConstraint(
            model_name='commission',
            name='one_commission_a_person_an_invoice',
        ),
        migrations.RemoveField(
            model_name='commission',
            name='invoice',
        ),
        migrations.RemoveField(
            model_name='commission',
            name='share',
        ),
        migrations.AlterField(
            model_name='commission',
            name='deal',
            field=models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='lines', to='dashboard.deal'),
        ),
        migrations.AddConstraint(
            model_name='commission',
            constraint=models.UniqueConstraint(fields=('deal', 'person'), name='one_commission_a_person_a_deal'),
        ),
    ]
