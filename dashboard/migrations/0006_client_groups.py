"""Client groups: a room may belong to a client instead of a task."""

import django.db.models.deletion
from django.conf import settings
from django.db import migrations, models


def backfill_room_client(apps, schema_editor):
    """Every existing client room already has a task — copy its client over."""
    ChatRoom = apps.get_model("dashboard", "ChatRoom")
    for room in ChatRoom.objects.filter(kind="client", task__isnull=False):
        room.client_id = room.task.client_id
        room.save(update_fields=["client"])


class Migration(migrations.Migration):

    dependencies = [
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
        ("dashboard", "0005_client_room"),
    ]

    operations = [
        migrations.RemoveConstraint(
            model_name="chatroom",
            name="uniq_room_per_task_kind",
        ),
        migrations.AlterField(
            model_name="chatroom",
            name="task",
            field=models.ForeignKey(
                blank=True, null=True,
                on_delete=django.db.models.deletion.CASCADE,
                related_name="rooms", to="dashboard.task",
            ),
        ),
        migrations.AddField(
            model_name="chatroom",
            name="client",
            field=models.ForeignKey(
                blank=True, null=True,
                on_delete=django.db.models.deletion.CASCADE,
                related_name="rooms", to="dashboard.client",
            ),
        ),
        migrations.AddField(
            model_name="chatroom",
            name="title",
            field=models.CharField(blank=True, max_length=120),
        ),
        migrations.AddField(
            model_name="chatroom",
            name="created_by",
            field=models.ForeignKey(
                blank=True, null=True,
                on_delete=django.db.models.deletion.SET_NULL,
                related_name="+", to="dashboard.user",
            ),
        ),
        migrations.AddConstraint(
            model_name="chatroom",
            constraint=models.UniqueConstraint(
                condition=models.Q(("task__isnull", False)),
                fields=("task", "kind"),
                name="uniq_room_per_task_kind",
            ),
        ),
        migrations.AddField(
            model_name="appsettings",
            name="group_creator_roles",
            field=models.CharField(
                default="admin,operation",
                help_text="Roles allowed to create a client group, comma-separated.",
                max_length=120,
            ),
        ),
        migrations.RunPython(backfill_room_client, migrations.RunPython.noop),
    ]
