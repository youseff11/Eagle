"""Rooms can be archived: out of the lists, still readable.

The chats page used to be the client rooms. It is the internal ones now, and
the old rooms would otherwise sit in the groups tab for ever.

Archiving, not deleting. These rows hold real conversations with real
clients, and a row removed to tidy a list cannot be got back. The command
``archive_client_rooms`` is what actually sets the flag, so the decision to
sweep them stays a person's rather than a migration's.
"""

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("dashboard", "0020_handoff_in_chat"),
    ]

    operations = [
        migrations.AddField(
            model_name="chatroom",
            name="is_archived",
            field=models.BooleanField(default=False),
        ),
    ]
