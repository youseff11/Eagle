"""The keys the admin's usage panel reads the month's bill with: Bunny, Neon (and its organization), Render."""

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('dashboard', '0086_commission_on_deal'),
    ]

    operations = [
        migrations.AddField(
            model_name='appsettings',
            name='bunny_api_key',
            field=models.CharField(blank=True, max_length=250),
        ),
        migrations.AddField(
            model_name='appsettings',
            name='neon_api_key',
            field=models.CharField(blank=True, max_length=250),
        ),
        migrations.AddField(
            model_name='appsettings',
            name='neon_org_id',
            field=models.CharField(blank=True, max_length=80),
        ),
        migrations.AddField(
            model_name='appsettings',
            name='render_api_key',
            field=models.CharField(blank=True, max_length=250),
        ),
    ]
