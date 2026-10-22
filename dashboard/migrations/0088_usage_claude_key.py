"""The usage panel reads the month's Claude bill with an Admin API key: the working key cannot read it."""

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('dashboard', '0087_usage_keys'),
    ]

    operations = [
        migrations.AddField(
            model_name='appsettings',
            name='anthropic_admin_key',
            field=models.CharField(blank=True, max_length=250),
        ),
    ]
