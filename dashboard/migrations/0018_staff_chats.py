"""One-to-one chats between two employees.

``ChatRoom`` gains a third kind and a ``pair_key``. The key is what stops the
same two people ending up with two conversations: whoever opens it second
lands in the one that already exists, because the unique index refuses the
duplicate rather than trusting a read-then-write to win the race.

``pair_key`` is NULL on every room that is not a staff chat, and a unique
index lets NULL repeat as often as it likes - which is why it is nullable
rather than blank.

The ``kind`` field is altered only because its choices grew. Choices are not
schema, so the database is untouched; the row is here so
``makemigrations --check`` keeps returning clean and a real schema change is
never lost in the noise.
"""

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("dashboard", "0017_mail_replies"),
    ]

    operations = [
        migrations.AddField(
            model_name="chatroom",
            name="pair_key",
            field=models.CharField(
                blank=True,
                help_text="Staff chats only: the two user ids, smallest first.",
                max_length=32,
                null=True,
                unique=True,
            ),
        ),
        migrations.AlterField(
            model_name="chatroom",
            name="kind",
            field=models.CharField(
                choices=[
                    ("ops_lead", "Operation + Team leader"),
                    ("group", "Operation + Team leader + Translator"),
                    ("staff", "Two employees, one to one"),
                    ("client", "Team + Client (relayed to WhatsApp)"),
                ],
                max_length=12,
            ),
        ),
    ]
