"""A client can have more than one WhatsApp number and more than one e-mail.

Messages from any of them land on the same client, under the same code.
"""

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("dashboard", "0029_task_origin"),
    ]

    operations = [
        migrations.AddField(
            model_name="client",
            name="extra_phones",
            field=models.TextField(
                blank=True, help_text="More WhatsApp numbers for the same client, one per line.",
            ),
        ),
        migrations.AddField(
            model_name="client",
            name="extra_emails",
            field=models.TextField(
                blank=True, help_text="More e-mail addresses for the same client, one per line.",
            ),
        ),
    ]
