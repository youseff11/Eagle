"""The hand-off moves into the chat, and a refusal has to say why.

``Assignment`` already carried the response window, the accept, the decline
and the penalty. What it could not do is say WHERE the hand-off was posted,
WHY it was refused, or whether the person had even opened the files before
the window closed. Those are the three columns here.

No new model: a second table for "who has this task and did they accept"
would be a second answer to a question that must only ever have one.
"""

from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):

    dependencies = [
        ("dashboard", "0019_team_groups"),
    ]

    operations = [
        migrations.AddField(
            model_name="assignment",
            name="reason",
            field=models.CharField(blank=True, max_length=250),
        ),
        migrations.AddField(
            model_name="assignment",
            name="opened_at",
            field=models.DateTimeField(blank=True, null=True),
        ),
        migrations.AddField(
            model_name="assignment",
            name="room",
            field=models.ForeignKey(
                blank=True,
                null=True,
                on_delete=django.db.models.deletion.SET_NULL,
                related_name="assignments",
                to="dashboard.chatroom",
            ),
        ),
    ]
