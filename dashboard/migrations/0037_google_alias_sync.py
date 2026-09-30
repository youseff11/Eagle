"""The alias list read from Google Workspace (``galiases.py``, 30/09/2026).

The OAuth client and its refresh token, when the list was last read and how
it went, and the aliases never to offer. The production row gets hr@ and
accounts@ hidden - the two 0035 left out of the list by hand - so the first
sync does not bring them back.

Written by hand and compared with ``models.py`` (max_length, null, blank,
help_text).
"""

from django.db import migrations, models

HIDDEN = ("hr@eaglelingua.com", "accounts@eaglelingua.com")


def hide_hr_and_accounts(apps, schema_editor):
    AppSettings = apps.get_model("dashboard", "AppSettings")
    for conf in AppSettings.objects.filter(singleton=1):
        if (conf.imap_user or "").strip().lower().endswith("@eaglelingua.com") and not conf.mail_aliases_hidden:
            conf.mail_aliases_hidden = "\n".join(HIDDEN)
            conf.save(update_fields=["mail_aliases_hidden"])


class Migration(migrations.Migration):

    dependencies = [
        ("dashboard", "0036_sales_mail_brand"),
    ]

    operations = [
        migrations.AddField(
            model_name="appsettings",
            name="mail_aliases_hidden",
            field=models.TextField(
                blank=True,
                help_text="Aliases on the mailbox never offered on the staff page. One per line.",
            ),
        ),
        migrations.AddField(
            model_name="appsettings",
            name="google_client_id",
            field=models.CharField(blank=True, max_length=200),
        ),
        migrations.AddField(
            model_name="appsettings",
            name="google_client_secret",
            field=models.CharField(blank=True, max_length=200),
        ),
        migrations.AddField(
            model_name="appsettings",
            name="google_refresh_token",
            field=models.CharField(blank=True, max_length=500),
        ),
        migrations.AddField(
            model_name="appsettings",
            name="google_sync_at",
            field=models.DateTimeField(blank=True, null=True),
        ),
        migrations.AddField(
            model_name="appsettings",
            name="google_sync_error",
            field=models.CharField(blank=True, max_length=300),
        ),
        migrations.RunPython(hide_hr_and_accounts, migrations.RunPython.noop),
    ]
