"""Every address on the company mailbox is given to one person by the admin.

* ``User.mail_alias``: no longer Sales only. The admin sets it on the staff
  page for Sales and Operation (``models.MAIL_ALIAS_ROLES``); only the
  help text changes, the column is the same.
* ``AppSettings.mail_unassigned_admin_only``: a letter to an address nobody
  holds reaches the admin alone. Off by default for a fresh install; the
  owner chose "on" (29/09/2026), so the settings row that already exists is
  switched on here. The admin can turn it off again from the settings page.

Written by hand and compared with ``models.py`` (max_length, blank,
db_index, default, help_text).
"""

from django.db import migrations, models


def keep_unassigned_mail_for_the_admin(apps, schema_editor):
    AppSettings = apps.get_model("dashboard", "AppSettings")
    AppSettings.objects.filter(singleton=1).update(mail_unassigned_admin_only=True)


class Migration(migrations.Migration):

    dependencies = [
        ("dashboard", "0033_sales_lines_and_extensions"),
    ]

    operations = [
        migrations.AlterField(
            model_name="user",
            name="mail_alias",
            field=models.CharField(
                blank=True, db_index=True, max_length=254,
                help_text="Sales / Operation: the company-mailbox address this person receives.",
            ),
        ),
        migrations.AddField(
            model_name="appsettings",
            name="mail_unassigned_admin_only",
            field=models.BooleanField(
                default=False,
                help_text="Mail to an address nobody holds reaches the admin only.",
            ),
        ),
        migrations.RunPython(keep_unassigned_mail_for_the_admin, migrations.RunPython.noop),
    ]
