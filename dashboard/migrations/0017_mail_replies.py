"""Replying to an e-mail conversation from its own page.

``OutboundMessage`` learns which conversation it answers and the subject it
went out with, so a reply sent from /ops/inbox/thread/ is shown inside that
conversation, the way Gmail shows "me" between the client's letters. Rows
from before this stay blank and simply stay out of the conversations.
"""

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("dashboard", "0016_mail_threads"),
    ]

    operations = [
        migrations.AddField(
            model_name="outboundmessage",
            name="subject",
            field=models.CharField(blank=True, max_length=250),
        ),
        migrations.AddField(
            model_name="outboundmessage",
            name="thread_key",
            field=models.CharField(blank=True, db_index=True, max_length=32),
        ),
    ]
