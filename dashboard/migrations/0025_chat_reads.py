"""Unread counters and "seen" in the chats.

``ChatRead`` is one cursor per (person, conversation): everything up to that
message id has been read. The counters in the chats list and the sidebar
badge are the messages past it, and a staff chat's "seen" is the other
person's cursor passing your message.

``wa_receipt`` / ``relay_receipt`` hold what WhatsApp reports back about our
own messages on the client's phone - delivered, then read.

Unlike ``0023_mail_seen`` this one *does* backfill. A mailbox that starts
out "all unopened" settles in a morning; a chats list where every client
anyone ever spoke to lights up with a three-digit number is a list people
learn to ignore on the first day. So everybody who can see a conversation
today starts with it read up to its newest message, and the counters only
count what arrives from here on.
"""

from django.conf import settings
from django.db import migrations, models
from django.db.models import Max
import django.db.models.deletion


def baseline(apps, schema_editor):
    User = apps.get_model("dashboard", "User")
    ChatRoom = apps.get_model("dashboard", "ChatRoom")
    ChatMessage = apps.get_model("dashboard", "ChatMessage")
    InboundMessage = apps.get_model("dashboard", "InboundMessage")
    ChatRead = apps.get_model("dashboard", "ChatRead")

    rows = []

    # The 1:1 client conversations: the people who have the client tab.
    client_tops = dict(
        InboundMessage.objects.filter(channel="whatsapp", client__isnull=False)
        .values_list("client_id").annotate(top=Max("id")).order_by()
    )
    inbox_people = User.objects.filter(
        models.Q(role__in=["operation", "admin"]) | models.Q(is_superuser=True)
    ).values_list("id", flat=True)
    admins = set(User.objects.filter(
        models.Q(role="admin") | models.Q(is_superuser=True)
    ).values_list("id", flat=True))
    for user_id in inbox_people:
        for client_id, top in client_tops.items():
            rows.append(ChatRead(user_id=user_id, client_id=client_id, last_read_id=top))

    # Staff chats and groups: their members, plus every admin for a client
    # room (the admin's list shows all of those).
    room_tops = dict(
        ChatMessage.objects.values_list("room_id").annotate(top=Max("id")).order_by()
    )
    for room in ChatRoom.objects.filter(kind__in=["staff", "team", "client"]):
        top = room_tops.get(room.id)
        if not top:
            continue
        people = set(room.members.values_list("id", flat=True))
        if room.kind == "client":
            people |= admins
        for user_id in people:
            rows.append(ChatRead(user_id=user_id, room_id=room.id, last_read_id=top))

    ChatRead.objects.bulk_create(rows, batch_size=500, ignore_conflicts=True)


class Migration(migrations.Migration):

    dependencies = [
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
        ("dashboard", "0024_translator_deadline"),
    ]

    operations = [
        migrations.AddField(
            model_name="chatmessage",
            name="relay_receipt",
            field=models.CharField(blank=True, max_length=10),
        ),
        migrations.AddField(
            model_name="outboundmessage",
            name="wa_receipt",
            field=models.CharField(blank=True, max_length=10),
        ),
        migrations.CreateModel(
            name="ChatRead",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True,
                                           serialize=False, verbose_name="ID")),
                ("last_read_id", models.BigIntegerField(default=0)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                ("client", models.ForeignKey(
                    blank=True, null=True,
                    on_delete=django.db.models.deletion.CASCADE,
                    related_name="chat_reads",
                    to="dashboard.client",
                )),
                ("room", models.ForeignKey(
                    blank=True, null=True,
                    on_delete=django.db.models.deletion.CASCADE,
                    related_name="reads",
                    to="dashboard.chatroom",
                )),
                ("user", models.ForeignKey(
                    on_delete=django.db.models.deletion.CASCADE,
                    related_name="chat_reads",
                    to=settings.AUTH_USER_MODEL,
                )),
            ],
        ),
        migrations.AddConstraint(
            model_name="chatread",
            constraint=models.UniqueConstraint(
                condition=models.Q(room__isnull=False),
                fields=("user", "room"), name="uniq_chat_read_room",
            ),
        ),
        migrations.AddConstraint(
            model_name="chatread",
            constraint=models.UniqueConstraint(
                condition=models.Q(client__isnull=False),
                fields=("user", "client"), name="uniq_chat_read_client",
            ),
        ),
        migrations.RunPython(baseline, migrations.RunPython.noop),
    ]
