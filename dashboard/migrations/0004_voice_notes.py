"""Voice notes: remember a file's type, whether it is a recording, how long."""

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("dashboard", "0003_outboundmessage_kind_and_more"),
    ]

    operations = [
        migrations.AddField(
            model_name="messageattachment",
            name="mime",
            field=models.CharField(blank=True, max_length=120),
        ),
        migrations.AddField(
            model_name="messageattachment",
            name="is_voice",
            field=models.BooleanField(default=False),
        ),
        migrations.AddField(
            model_name="messageattachment",
            name="duration",
            field=models.PositiveIntegerField(default=0, help_text="Seconds"),
        ),
        migrations.AddField(
            model_name="outboundattachment",
            name="mime",
            field=models.CharField(blank=True, max_length=120),
        ),
        migrations.AddField(
            model_name="outboundattachment",
            name="is_voice",
            field=models.BooleanField(default=False),
        ),
        migrations.AddField(
            model_name="outboundattachment",
            name="duration",
            field=models.PositiveIntegerField(default=0, help_text="Seconds"),
        ),
    ]
