"""Sales people's own client lines, and translators asking for more time.

* ``User.wa_phone_number_id`` / ``wa_display_number`` / ``mail_alias``: a
  Sales person's own WhatsApp Business number (by the Phone number ID Meta
  gave it) and their sub-address on the company mailbox (``lines.py``).
* ``InboundMessage.owner`` / ``OutboundMessage.owner``: which Sales line a
  message came in on or went out from. Null is the company line - every row
  that exists today - so nothing already stored changes hands.
* ``ExtensionRequest``: a translator's request for more time, and the team
  leader's answer.

Written by hand and compared with ``models.py`` field by field (max_length,
blank, null, db_index, help_text, related_name, on_delete), as the handoff
note asks. Every AddField is blank/nullable, so existing rows need nothing.
"""

import django.db.models.deletion
from django.conf import settings
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("dashboard", "0032_protected_files"),
    ]

    operations = [
        migrations.AddField(
            model_name="user",
            name="wa_phone_number_id",
            field=models.CharField(
                blank=True, db_index=True, max_length=40,
                help_text="Sales only: Phone number ID of their own WhatsApp Business number.",
            ),
        ),
        migrations.AddField(
            model_name="user",
            name="wa_display_number",
            field=models.CharField(blank=True, max_length=30),
        ),
        migrations.AddField(
            model_name="user",
            name="mail_alias",
            field=models.CharField(
                blank=True, db_index=True, max_length=254,
                help_text="Sales only: their own address on the company mailbox.",
            ),
        ),
        migrations.AddField(
            model_name="inboundmessage",
            name="owner",
            field=models.ForeignKey(
                blank=True, null=True,
                on_delete=django.db.models.deletion.SET_NULL,
                related_name="line_messages", to=settings.AUTH_USER_MODEL,
            ),
        ),
        migrations.AddField(
            model_name="outboundmessage",
            name="owner",
            field=models.ForeignKey(
                blank=True, null=True,
                on_delete=django.db.models.deletion.SET_NULL,
                related_name="line_replies", to=settings.AUTH_USER_MODEL,
            ),
        ),
        migrations.CreateModel(
            name="ExtensionRequest",
            fields=[
                ("id", models.BigAutoField(
                    auto_created=True, primary_key=True, serialize=False, verbose_name="ID",
                )),
                ("minutes", models.PositiveIntegerField()),
                ("reason", models.CharField(blank=True, max_length=300)),
                ("due_before", models.DateTimeField(blank=True, null=True)),
                ("status", models.CharField(
                    choices=[
                        ("pending", "Pending"),
                        ("approved", "Approved"),
                        ("declined", "Declined"),
                    ],
                    db_index=True, default="pending", max_length=10,
                )),
                ("decided_at", models.DateTimeField(blank=True, null=True)),
                ("decision_note", models.CharField(blank=True, max_length=300)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("decided_by", models.ForeignKey(
                    blank=True, null=True,
                    on_delete=django.db.models.deletion.SET_NULL,
                    related_name="+", to=settings.AUTH_USER_MODEL,
                )),
                ("requested_by", models.ForeignKey(
                    null=True,
                    on_delete=django.db.models.deletion.SET_NULL,
                    related_name="extension_requests", to=settings.AUTH_USER_MODEL,
                )),
                ("task", models.ForeignKey(
                    on_delete=django.db.models.deletion.CASCADE,
                    related_name="extension_requests", to="dashboard.task",
                )),
            ],
            options={
                "ordering": ("-created_at",),
            },
        ),
    ]
