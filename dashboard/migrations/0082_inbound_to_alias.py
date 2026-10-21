from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("dashboard", "0081_call_outcome_contracted"),
    ]

    operations = [
        migrations.AddField(
            model_name="inboundmessage",
            name="to_alias",
            field=models.CharField(blank=True, db_index=True, default="", max_length=190),
        ),
    ]
