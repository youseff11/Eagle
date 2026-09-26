"""B2B client identity masking - the pieces the schema needs.

* ``Role.SALES`` joins the role choices, on both fields that carry them
  (``User.role`` and ``Assignment.target_role`` - 0013 is the story of what
  happens when only one of the two is altered).
* ``User.client_identity_access``: the admin's explicit, per-person grant of
  the real client identity to a Sales or Accounting user.
* ``AuditLog.ip`` / ``AuditLog.path``: where an access entry came from.

Choices are validation, not schema: the two AlterField operations do not
touch the database. The three AddField operations add nullable/defaulted
columns, so existing rows need nothing.
"""

from django.db import migrations, models


ROLE_CHOICES = [
    ("admin", "Admin"),
    ("operation", "Operation"),
    ("team_lead", "Team Leader"),
    ("translator", "Translator"),
    ("hr", "HR"),
    ("reviewer", "Reviewer"),
    ("accounting", "Accounting"),
    ("sales", "Sales"),
]


class Migration(migrations.Migration):

    dependencies = [
        ("dashboard", "0030_client_extra_identities"),
    ]

    operations = [
        migrations.AlterField(
            model_name="user",
            name="role",
            field=models.CharField(choices=ROLE_CHOICES, default="translator", max_length=20),
        ),
        migrations.AlterField(
            model_name="assignment",
            name="target_role",
            field=models.CharField(choices=ROLE_CHOICES, max_length=20),
        ),
        migrations.AddField(
            model_name="user",
            name="client_identity_access",
            field=models.BooleanField(
                default=False,
                help_text="Sales / Accounting only: may see the real client name and contacts.",
            ),
        ),
        migrations.AddField(
            model_name="auditlog",
            name="ip",
            field=models.GenericIPAddressField(blank=True, null=True),
        ),
        migrations.AddField(
            model_name="auditlog",
            name="path",
            field=models.CharField(blank=True, max_length=250),
        ),
    ]
