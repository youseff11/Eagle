"""Internal work groups - a name, the people you picked, and no client.

No new column: a team group is a ``ChatRoom`` with a title, members and a
kind, all of which already exist. The only thing that changed is the list of
kinds, and choices are not schema - the database is untouched.

The row is here anyway so ``makemigrations --check`` keeps returning clean.
A tree that never returns clean is a tree where a real schema change goes
unnoticed, which is exactly how the mismatch in 0013 got in.
"""

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("dashboard", "0018_staff_chats"),
    ]

    operations = [
        migrations.AlterField(
            model_name="chatroom",
            name="kind",
            field=models.CharField(
                choices=[
                    ("ops_lead", "Operation + Team leader"),
                    ("group", "Operation + Team leader + Translator"),
                    ("staff", "Two employees, one to one"),
                    ("team", "Internal work group"),
                    ("client", "Team + Client (relayed to WhatsApp)"),
                ],
                max_length=12,
            ),
        ),
    ]
