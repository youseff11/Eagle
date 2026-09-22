"""A chat message can say which task it is work on.

A task used to own a room, so "which task is this file for" and "which room
is it in" were the same question. The work happens in the chat between two
people now, and that chat outlives any one task - so the link moves onto the
message itself.

Nothing is backfilled. Older messages keep answering through their room's
task, and every reader accepts either link, so the two generations of data
live side by side instead of one of them going quiet.
"""

from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):

    dependencies = [
        ("dashboard", "0021_archive_rooms"),
    ]

    operations = [
        migrations.AddField(
            model_name="chatmessage",
            name="task",
            field=models.ForeignKey(
                blank=True,
                db_index=True,
                null=True,
                on_delete=django.db.models.deletion.SET_NULL,
                related_name="chat_messages",
                to="dashboard.task",
            ),
        ),
    ]
