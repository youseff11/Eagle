"""Who has opened which letter.

The mail badge counted letters nobody had *claimed*, so opening a letter left
it exactly where it was - you read it, the number did not move. Claiming is a
decision and reading is not, and the badge was asking the wrong one.

One row per (person, letter). Nothing is backfilled: on the first day after
this lands every letter reads as unopened, which is honest - nobody has
opened one *here* yet - and the number settles as the room reads its mail.
"""

from django.conf import settings
from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):

    dependencies = [
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
        ("dashboard", "0022_message_task"),
    ]

    operations = [
        migrations.CreateModel(
            name="MailRead",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True,
                                           serialize=False, verbose_name="ID")),
                ("seen_at", models.DateTimeField(auto_now_add=True)),
                ("message", models.ForeignKey(
                    on_delete=django.db.models.deletion.CASCADE,
                    related_name="reads",
                    to="dashboard.inboundmessage",
                )),
                ("user", models.ForeignKey(
                    on_delete=django.db.models.deletion.CASCADE,
                    related_name="mail_reads",
                    to=settings.AUTH_USER_MODEL,
                )),
            ],
        ),
        migrations.AddConstraint(
            model_name="mailread",
            constraint=models.UniqueConstraint(
                fields=("message", "user"), name="uniq_mail_read"
            ),
        ),
    ]
