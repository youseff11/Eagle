"""A task has two deadlines: the client's, and the translator's.

They were the same field until now, which meant the team leader had to
choose between handing the translator the client's own date - leaving
themselves no time at all to review before the job went out - and lying
about it somewhere outside the system.

So the leader now sets a second one when they hand the job over. It is
never later than the client's; the difference is the review.

Nothing is backfilled. A task already in flight has no translator deadline,
and ``translator_due`` falls back to the client's - which is exactly what
those tasks have been running on all along.
"""

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("dashboard", "0023_mail_seen"),
    ]

    operations = [
        migrations.AddField(
            model_name="task",
            name="translator_deadline",
            field=models.DateTimeField(blank=True, null=True),
        ),
        migrations.AddField(
            model_name="task",
            name="translator_warned_at",
            field=models.DateTimeField(blank=True, null=True),
        ),
        migrations.AddField(
            model_name="task",
            name="translator_missed_notified",
            field=models.BooleanField(default=False),
        ),
    ]
