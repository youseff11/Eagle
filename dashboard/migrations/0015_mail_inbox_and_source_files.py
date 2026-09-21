"""The e-mail inbox, and the client files somebody actually picked for a task.

``Task.source_files`` is the operation's tick list. Until now every attachment
on every message linked to a task travelled to the translator, whether it was
the contract or the client's signature image. Empty stays the old meaning —
"all of them" — so nothing has to be backfilled and no existing task changes.

The three ``mail_*`` columns are the mailbox's last result. "IMAP is filled in"
and "mail is arriving" are different statements, and only the second one is
worth putting on a screen.
"""

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("dashboard", "0014_handover_ack"),
    ]

    operations = [
        migrations.AddField(
            model_name="task",
            name="source_files",
            field=models.ManyToManyField(
                blank=True,
                help_text="Client attachments chosen for this task. Empty = all of them.",
                related_name="tasks",
                to="dashboard.messageattachment",
            ),
        ),
        migrations.AddField(
            model_name="appsettings",
            name="mail_last_fetch_at",
            field=models.DateTimeField(blank=True, null=True),
        ),
        migrations.AddField(
            model_name="appsettings",
            name="mail_last_count",
            field=models.PositiveIntegerField(default=0),
        ),
        migrations.AddField(
            model_name="appsettings",
            name="mail_last_error",
            field=models.CharField(blank=True, max_length=300),
        ),
    ]
