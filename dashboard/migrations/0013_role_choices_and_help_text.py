"""Two alterations the state was missing. Neither one touches the database.

``Assignment.target_role`` carries ``Role.choices`` exactly like ``User.role``
does, and ``0011`` altered only the second one when the three new roles landed.
Choices are validation, not schema, so the column was always fine - but the
migration state disagreed with the models, and a state that disagrees is a
``makemigrations`` that never comes back clean, which is how a real schema
change ends up hiding inside the noise.

``PayrollSettings.leave_needs_manager`` differs only by its ``help_text``.

Both are recorded here rather than by editing the applied migrations, so the
history stays a record of what actually ran.
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
]


class Migration(migrations.Migration):

    dependencies = [
        ("dashboard", "0012_lifecycle"),
    ]

    operations = [
        migrations.AlterField(
            model_name="assignment",
            name="target_role",
            field=models.CharField(choices=ROLE_CHOICES, max_length=20),
        ),
        migrations.AlterField(
            model_name="payrollsettings",
            name="leave_needs_manager",
            field=models.BooleanField(
                default=False,
                help_text="Require the team leader's approval before HR sees a leave request.",
            ),
        ),
    ]
