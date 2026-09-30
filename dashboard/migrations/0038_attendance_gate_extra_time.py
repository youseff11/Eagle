"""Attendance, 30/09/2026: the check-in screen, extra time, a forgotten check-out.

* ``AttendanceEvent.kind`` gains ``extra_start`` - the "extra time" button.
* ``WorkDay.extra_started_at`` / ``checkout_missed``.
* ``PayrollSettings.checkin_prompt_before_minutes`` - when the screen opens.
* ``PayrollSettings.overtime_multiplier`` defaults to 1.5 (an hour and a half
  per overtime hour), and the live row still on the old 1.00 is moved to it.
* ``missing_checkout_after_minutes`` keeps its default and gains the
  help_text that says what it now decides.

Written by hand and compared with ``models.py`` (choices, default,
max_length, null, blank, help_text).
"""

from decimal import Decimal

from django.db import migrations, models


def hour_and_a_half(apps, schema_editor):
    PayrollSettings = apps.get_model("dashboard", "PayrollSettings")
    PayrollSettings.objects.filter(overtime_multiplier=Decimal("1.00")).update(
        overtime_multiplier=Decimal("1.50")
    )


def back_to_one(apps, schema_editor):
    """Nothing to undo on the way down: the column goes back to its old default."""


class Migration(migrations.Migration):

    dependencies = [
        ("dashboard", "0037_google_alias_sync"),
    ]

    operations = [
        migrations.AlterField(
            model_name="attendanceevent",
            name="kind",
            field=models.CharField(
                choices=[
                    ("check_in", "Check in"),
                    ("check_out", "Check out"),
                    ("break_start", "Break start"),
                    ("break_end", "Break end"),
                    ("extra_start", "Extra time start"),
                ],
                max_length=12,
            ),
        ),
        migrations.AddField(
            model_name="workday",
            name="extra_started_at",
            field=models.DateTimeField(blank=True, null=True),
        ),
        migrations.AddField(
            model_name="workday",
            name="checkout_missed",
            field=models.BooleanField(default=False),
        ),
        migrations.AddField(
            model_name="payrollsettings",
            name="checkin_prompt_before_minutes",
            field=models.PositiveSmallIntegerField(
                default=15,
                help_text="The check-in screen opens by itself this many minutes before the shift.",
            ),
        ),
        migrations.AlterField(
            model_name="payrollsettings",
            name="missing_checkout_after_minutes",
            field=models.PositiveSmallIntegerField(
                default=60,
                help_text="Minutes after the shift ends to check out. Past it with no check-out the day is not counted.",
            ),
        ),
        migrations.AlterField(
            model_name="payrollsettings",
            name="overtime_multiplier",
            field=models.DecimalField(decimal_places=2, default=Decimal("1.50"), max_digits=4),
        ),
        migrations.RunPython(hour_and_a_half, back_to_one),
    ]
