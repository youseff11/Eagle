"""The relayed client room: a third room kind plus its relay bookkeeping."""

import django.db.models.deletion
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("dashboard", "0004_voice_notes"),
    ]

    operations = [
        migrations.AlterField(
            model_name="chatroom",
            name="kind",
            field=models.CharField(
                choices=[
                    ("ops_lead", "Operation + Team leader"),
                    ("group", "Operation + Team leader + Translator"),
                    ("client", "Team + Client (relayed to WhatsApp)"),
                ],
                max_length=12,
            ),
        ),
        migrations.AddField(
            model_name="chatmessage",
            name="relay_status",
            field=models.CharField(blank=True, max_length=10),
        ),
        migrations.AddField(
            model_name="chatmessage",
            name="relay_error",
            field=models.TextField(blank=True),
        ),
        migrations.AddField(
            model_name="chatmessage",
            name="inbound",
            field=models.ForeignKey(
                blank=True, null=True,
                on_delete=django.db.models.deletion.SET_NULL,
                related_name="mirrors", to="dashboard.inboundmessage",
            ),
        ),
    ]
