"""Replies: quote a message, and quote it on the client's phone too."""

import django.db.models.deletion
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("dashboard", "0006_client_groups"),
    ]

    operations = [
        migrations.AddField(
            model_name="chatmessage",
            name="relay_wamid",
            field=models.CharField(blank=True, max_length=190),
        ),
        migrations.AddField(
            model_name="chatmessage",
            name="reply_to",
            field=models.ForeignKey(
                blank=True, null=True,
                on_delete=django.db.models.deletion.SET_NULL,
                related_name="replies", to="dashboard.chatmessage",
            ),
        ),
        migrations.AddField(
            model_name="inboundmessage",
            name="reply_to_external",
            field=models.CharField(blank=True, max_length=190),
        ),
        migrations.AddField(
            model_name="outboundmessage",
            name="reply_to_wamid",
            field=models.CharField(blank=True, max_length=190),
        ),
        migrations.AddField(
            model_name="outboundmessage",
            name="reply_preview",
            field=models.CharField(blank=True, max_length=160),
        ),
    ]
