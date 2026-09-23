"""Forwarding messages and files between chats.

``forwarded`` draws the "محوّلة" tag. ``origin_client`` on a message and on a
file remembers whose conversation it came from, because a forward reuses the
stored file instead of copying it: without it, a client's contract forwarded
into a staff chat would look like any internal upload, and could be forwarded
on from there to a different client.

Nothing to backfill - nothing has been forwarded yet.
"""

from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):

    dependencies = [
        ("dashboard", "0025_chat_reads"),
    ]

    operations = [
        migrations.AddField(
            model_name="chatmessage",
            name="forwarded",
            field=models.BooleanField(default=False),
        ),
        migrations.AddField(
            model_name="chatmessage",
            name="origin_client",
            field=models.ForeignKey(
                blank=True, null=True,
                on_delete=django.db.models.deletion.SET_NULL,
                related_name="+", to="dashboard.client",
            ),
        ),
        migrations.AddField(
            model_name="chatattachment",
            name="origin_client",
            field=models.ForeignKey(
                blank=True, null=True,
                on_delete=django.db.models.deletion.SET_NULL,
                related_name="+", to="dashboard.client",
            ),
        ),
    ]
