"""The list of aliases the staff page offers (``AppSettings.mail_aliases``).

Before this the admin typed an address on each person's page; now they pick
it from this list, kept on the settings page. The production row is seeded
with the aliases that exist on the company mailbox today (29/09/2026) - only
when that mailbox is the one they were made on. hr@ and accounts@ are left
out on purpose: Gmail files them away before the dashboard reads the inbox.

Written by hand and compared with ``models.py`` (blank, help_text).
"""

from django.db import migrations, models

SEED = (
    "operation1@eaglelingua.com",
    "operation2@eaglelingua.com",
    "operation@eaglelingua.com",
    "sales1@eaglelingua.com",
    "sales2@eaglelingua.com",
    "sales@eaglelingua.com",
)


def seed_the_list(apps, schema_editor):
    AppSettings = apps.get_model("dashboard", "AppSettings")
    for conf in AppSettings.objects.filter(singleton=1):
        if (conf.imap_user or "").strip().lower().endswith("@eaglelingua.com") and not conf.mail_aliases:
            conf.mail_aliases = "\n".join(SEED)
            conf.save(update_fields=["mail_aliases"])


class Migration(migrations.Migration):

    dependencies = [
        ("dashboard", "0034_mail_alias_per_person"),
    ]

    operations = [
        migrations.AddField(
            model_name="appsettings",
            name="mail_aliases",
            field=models.TextField(
                blank=True,
                help_text="One address per line: the aliases on the company mailbox.",
            ),
        ),
        migrations.RunPython(seed_the_list, migrations.RunPython.noop),
    ]
