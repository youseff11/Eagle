"""Reactions on chat messages - like, love, laugh, wow, sad, done.

One per person per message; the three nullable targets match the three kinds
of row a conversation is drawn from. Internal only - see ``ChatReaction``.
"""

from django.conf import settings
from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):

    dependencies = [
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
        ("dashboard", "0026_forwarding"),
    ]

    operations = [
        migrations.CreateModel(
            name="ChatReaction",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True,
                                           serialize=False, verbose_name="ID")),
                ("kind", models.CharField(choices=[
                    ("like", "Like"), ("love", "Love"), ("laugh", "Laugh"),
                    ("wow", "Wow"), ("sad", "Sad"), ("done", "Done"),
                ], max_length=10)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("inbound", models.ForeignKey(
                    blank=True, null=True, on_delete=django.db.models.deletion.CASCADE,
                    related_name="reactions", to="dashboard.inboundmessage",
                )),
                ("message", models.ForeignKey(
                    blank=True, null=True, on_delete=django.db.models.deletion.CASCADE,
                    related_name="reactions", to="dashboard.chatmessage",
                )),
                ("outbound", models.ForeignKey(
                    blank=True, null=True, on_delete=django.db.models.deletion.CASCADE,
                    related_name="reactions", to="dashboard.outboundmessage",
                )),
                ("user", models.ForeignKey(
                    on_delete=django.db.models.deletion.CASCADE,
                    related_name="chat_reactions", to=settings.AUTH_USER_MODEL,
                )),
            ],
        ),
        migrations.AddConstraint(
            model_name="chatreaction",
            constraint=models.UniqueConstraint(
                condition=models.Q(message__isnull=False),
                fields=("user", "message"), name="uniq_reaction_message",
            ),
        ),
        migrations.AddConstraint(
            model_name="chatreaction",
            constraint=models.UniqueConstraint(
                condition=models.Q(inbound__isnull=False),
                fields=("user", "inbound"), name="uniq_reaction_inbound",
            ),
        ),
        migrations.AddConstraint(
            model_name="chatreaction",
            constraint=models.UniqueConstraint(
                condition=models.Q(outbound__isnull=False),
                fields=("user", "outbound"), name="uniq_reaction_outbound",
            ),
        ),
    ]
