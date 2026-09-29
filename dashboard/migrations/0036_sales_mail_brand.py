"""The branded letter Sales people's e-mails go out in (``mailbrand.py``).

Two settings for the parts that are the company's, not the person's: the
website under the signature and the dark band under the letter. Both blank
by default - blank simply leaves that part out. The person's own name,
title and number come from their staff page.

Written by hand and compared with ``models.py`` (max_length, blank,
help_text).
"""

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("dashboard", "0035_mail_alias_list"),
    ]

    operations = [
        migrations.AddField(
            model_name="appsettings",
            name="sales_mail_website",
            field=models.CharField(
                blank=True, max_length=190,
                help_text="Shown under a Sales person's signature. Blank = not shown.",
            ),
        ),
        migrations.AddField(
            model_name="appsettings",
            name="sales_mail_footer",
            field=models.TextField(
                blank=True,
                help_text="The dark band under a Sales letter: hours, address. One line each.",
            ),
        ),
    ]
