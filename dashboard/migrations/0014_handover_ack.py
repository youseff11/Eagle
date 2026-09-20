"""The operation's hand-raise between review and delivery, and a running AI check.

``Task.handover_ack_at`` is the step the workflow was missing. A reviewed task
used to sit in a status nobody had to acknowledge, so the last human decision
before files leave the building was implied rather than made. Sending to a
client cannot be undone, so it now waits for a person to say the job is theirs.
``handover_ack_by`` records which person that was.

``AICheckResult.RUNNING`` is a state, not a result: the check is written before
the model is called so a page opened mid-call says so, and a process that dies
during the call leaves a row that ``run_ai_checks`` can finish. Choices are
validation rather than schema, so this alteration touches no column.
"""

import django.db.models.deletion
from django.conf import settings
from django.db import migrations, models


AI_STATUS_CHOICES = [
    ("running", "Running"),
    ("clean", "No issues"),
    ("issues", "Issues found"),
    ("error", "Error"),
]


class Migration(migrations.Migration):

    dependencies = [
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
        ("dashboard", "0013_role_choices_and_help_text"),
    ]

    operations = [
        migrations.AddField(
            model_name="task",
            name="handover_ack_at",
            field=models.DateTimeField(blank=True, null=True),
        ),
        migrations.AddField(
            model_name="task",
            name="handover_ack_by",
            field=models.ForeignKey(
                blank=True, null=True,
                on_delete=django.db.models.deletion.SET_NULL,
                related_name="+", to=settings.AUTH_USER_MODEL,
            ),
        ),
        migrations.AlterField(
            model_name="aicheckresult",
            name="status",
            field=models.CharField(
                choices=AI_STATUS_CHOICES, default="clean", max_length=10
            ),
        ),
    ]
