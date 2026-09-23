"""Calls between colleagues: the bookkeeping and the signalling mailbox.

The call itself runs browser to browser (WebRTC). See ``CallSession``.
"""

from django.conf import settings
from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):

    dependencies = [
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
        ("dashboard", "0027_chat_reactions"),
    ]

    operations = [
        migrations.CreateModel(
            name="CallSession",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True,
                                           serialize=False, verbose_name="ID")),
                ("video", models.BooleanField(default=False)),
                ("status", models.CharField(choices=[
                    ("ringing", "Ringing"), ("active", "Active"), ("ended", "Ended"),
                    ("missed", "Missed"), ("declined", "Declined"),
                ], db_index=True, default="ringing", max_length=10)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("answered_at", models.DateTimeField(blank=True, null=True)),
                ("ended_at", models.DateTimeField(blank=True, null=True)),
                ("callee", models.ForeignKey(
                    on_delete=django.db.models.deletion.CASCADE,
                    related_name="calls_received", to=settings.AUTH_USER_MODEL,
                )),
                ("caller", models.ForeignKey(
                    on_delete=django.db.models.deletion.CASCADE,
                    related_name="calls_made", to=settings.AUTH_USER_MODEL,
                )),
                ("room", models.ForeignKey(
                    on_delete=django.db.models.deletion.CASCADE,
                    related_name="calls", to="dashboard.chatroom",
                )),
            ],
            options={"ordering": ("-id",)},
        ),
        migrations.CreateModel(
            name="CallSignal",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True,
                                           serialize=False, verbose_name="ID")),
                ("kind", models.CharField(choices=[
                    ("offer", "Offer"), ("answer", "Answer"), ("ice", "ICE candidate"),
                ], max_length=10)),
                ("payload", models.TextField()),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("call", models.ForeignKey(
                    on_delete=django.db.models.deletion.CASCADE,
                    related_name="signals", to="dashboard.callsession",
                )),
                ("sender", models.ForeignKey(
                    on_delete=django.db.models.deletion.CASCADE,
                    related_name="+", to=settings.AUTH_USER_MODEL,
                )),
            ],
            options={"ordering": ("id",)},
        ),
    ]
