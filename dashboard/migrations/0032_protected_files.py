"""Client file names: the one the client used, kept for the admin.

``MessageAttachment.original_name`` becomes the masked name the dashboard
shows (the client's name, company, domain and number replaced by the code);
``raw_name`` keeps the name exactly as it arrived. Existing rows are left
alone here - ``python manage.py mask_file_names --apply`` fills them.

The ``upload_to`` functions changed body, not name, so the stored paths of
the FileFields need no AlterField.
"""

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("dashboard", "0031_client_identity_masking"),
    ]

    operations = [
        migrations.AddField(
            model_name="messageattachment",
            name="raw_name",
            field=models.CharField(blank=True, max_length=250),
        ),
    ]
