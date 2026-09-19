"""Attendance and workforce management.

Four things arrive together, because none of them is useful alone:

* **The contract, on the person.** Full-time or part-time, office or remote or
  hybrid, fixed or custom - and whether they clock in at all.
* **The roster, as data.** ``ShiftTemplate`` holds the company's shifts so the
  three in the contract are seeded once and edited from the panel rather than
  compiled in. ``Shift`` becomes a roster row that points at a template (or
  carries its own times, for a custom schedule) and knows where that day is
  worked. ``ScheduleOverride`` moves a single date without touching any of it.
* **The punches.** ``AttendanceEvent`` is append-only and carries whatever the
  browser reported at the moment the button was pressed. ``WorkDay`` gains the
  day's derived figures *and* a frozen copy of the shift that governed it, so
  changing somebody's roster next month cannot rewrite last week's lateness.
* **The accountability.** ``AttendanceEdit`` records every correction with a
  reason, ``AuthorizedDevice`` makes a new browser a decision rather than a
  silent fact, and ``OvertimeClaim`` makes extra hours a claim somebody signs.

Every threshold lands on ``PayrollSettings``, which is the existing promise
that a rule change never needs a deploy.

``Shift.start_time`` and ``end_time`` become nullable here. Existing rows keep
their times and simply have no template, which is exactly what a custom
schedule looks like - so nobody's roster changes shape on migrate.
"""

from decimal import Decimal

import django.db.models.deletion
from django.conf import settings
from django.db import migrations, models


DAY_MODE_CHOICES = [("office", "From the office"), ("remote", "Remote")]
APPROVAL_CHOICES = [
    ("pending", "Waiting for approval"),
    ("approved", "Approved"),
    ("rejected", "Rejected"),
]
POLICY_CHOICES = [
    ("review", "Record it and flag it for review"),
    ("reject", "Refuse the punch"),
]


def seed_shifts(apps, schema_editor):
    """Write the contract's three shifts once. Editable from the panel after."""
    from datetime import time

    ShiftTemplate = apps.get_model("dashboard", "ShiftTemplate")
    if ShiftTemplate.objects.exists():
        return
    rows = (
        ("Shift 1", "الشيفت 1", time(9, 0), time(17, 0)),
        ("Shift 2", "الشيفت 2", time(12, 0), time(20, 0)),
        ("Shift 3", "الشيفت 3", time(17, 0), time(1, 0)),
    )
    ShiftTemplate.objects.bulk_create([
        ShiftTemplate(
            name=name, name_ar=name_ar, start_time=start, end_time=end,
            sort_order=order, break_minutes=0, is_active=True,
        )
        for order, (name, name_ar, start, end) in enumerate(rows, start=1)
    ])


def drop_shifts(apps, schema_editor):
    """Reversing drops only the seeded rows; a roster row would block it."""
    ShiftTemplate = apps.get_model("dashboard", "ShiftTemplate")
    ShiftTemplate.objects.filter(shifts__isnull=True).delete()


class Migration(migrations.Migration):

    dependencies = [
        ("dashboard", "0009_word_count"),
    ]

    operations = [
        # -- the contract, on the person --------------------------------
        migrations.AddField(
            model_name="user",
            name="employment_type",
            field=models.CharField(
                choices=[
                    ("full_time", "Full time"),
                    ("part_time", "Part time"),
                    ("freelance", "Freelancer / contractor"),
                ],
                default="full_time", max_length=12,
            ),
        ),
        migrations.AddField(
            model_name="user",
            name="work_mode",
            field=models.CharField(
                choices=[
                    ("office", "From the office"),
                    ("remote", "Remote"),
                    ("hybrid", "Hybrid"),
                ],
                default="office", max_length=8,
                help_text="Hybrid means the roster decides each day.",
            ),
        ),
        migrations.AddField(
            model_name="user",
            name="schedule_kind",
            field=models.CharField(
                choices=[
                    ("fixed", "Fixed shift"),
                    ("flexible", "Flexible shift"),
                    ("custom", "Custom schedule"),
                ],
                default="fixed", max_length=10,
            ),
        ),
        migrations.AddField(
            model_name="user",
            name="attendance_enabled",
            field=models.BooleanField(
                default=True,
                help_text="Turn off for somebody who does not clock in at all.",
            ),
        ),
        migrations.AddField(
            model_name="user",
            name="attendance_manager",
            field=models.BooleanField(
                default=False,
                help_text=(
                    "May run the attendance board and correct other people's "
                    "days (HR)."
                ),
            ),
        ),

        # -- the company's shifts, as data ------------------------------
        migrations.CreateModel(
            name="ShiftTemplate",
            fields=[
                ("id", models.BigAutoField(
                    auto_created=True, primary_key=True, serialize=False, verbose_name="ID"
                )),
                ("name", models.CharField(max_length=60)),
                ("name_ar", models.CharField(blank=True, max_length=60)),
                ("start_time", models.TimeField()),
                ("end_time", models.TimeField()),
                ("break_minutes", models.PositiveSmallIntegerField(
                    default=0,
                    help_text="Unpaid break this shift grants. 0 uses the company default.",
                )),
                ("is_active", models.BooleanField(default=True)),
                ("sort_order", models.PositiveSmallIntegerField(default=0)),
            ],
            options={"ordering": ("sort_order", "start_time")},
        ),

        # -- the roster row -----------------------------------------------
        migrations.AlterField(
            model_name="shift",
            name="start_time",
            field=models.TimeField(blank=True, null=True),
        ),
        migrations.AlterField(
            model_name="shift",
            name="end_time",
            field=models.TimeField(blank=True, null=True),
        ),
        migrations.AddField(
            model_name="shift",
            name="template",
            field=models.ForeignKey(
                blank=True, null=True,
                on_delete=django.db.models.deletion.PROTECT,
                related_name="shifts", to="dashboard.shifttemplate",
            ),
        ),
        migrations.AddField(
            model_name="shift",
            name="work_mode",
            field=models.CharField(
                blank=True, choices=DAY_MODE_CHOICES, max_length=8,
                help_text="Blank follows the person's own work mode.",
            ),
        ),
        migrations.AddField(
            model_name="shift",
            name="required_minutes",
            field=models.PositiveSmallIntegerField(
                default=0, help_text="0 means the shift's own length."
            ),
        ),

        # -- where a punch may come from ----------------------------------
        migrations.CreateModel(
            name="OfficeLocation",
            fields=[
                ("id", models.BigAutoField(
                    auto_created=True, primary_key=True, serialize=False, verbose_name="ID"
                )),
                ("name", models.CharField(max_length=80)),
                ("name_ar", models.CharField(blank=True, max_length=80)),
                ("latitude", models.DecimalField(decimal_places=6, max_digits=9)),
                ("longitude", models.DecimalField(decimal_places=6, max_digits=9)),
                ("radius_meters", models.PositiveIntegerField(
                    default=200,
                    help_text="Phone GPS is routinely 50-100 m out - leave room.",
                )),
                ("is_active", models.BooleanField(default=True)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
            ],
            options={"ordering": ("name",)},
        ),

        # -- which browser it came from -----------------------------------
        migrations.CreateModel(
            name="AuthorizedDevice",
            fields=[
                ("id", models.BigAutoField(
                    auto_created=True, primary_key=True, serialize=False, verbose_name="ID"
                )),
                ("fingerprint", models.CharField(db_index=True, max_length=64)),
                ("label", models.CharField(blank=True, max_length=80)),
                ("user_agent", models.CharField(blank=True, max_length=250)),
                ("status", models.CharField(
                    choices=APPROVAL_CHOICES, db_index=True, default="pending", max_length=10
                )),
                ("first_seen", models.DateTimeField(auto_now_add=True)),
                ("last_seen", models.DateTimeField(auto_now=True)),
                ("approved_at", models.DateTimeField(blank=True, null=True)),
                ("approved_by", models.ForeignKey(
                    blank=True, null=True,
                    on_delete=django.db.models.deletion.SET_NULL,
                    related_name="+", to=settings.AUTH_USER_MODEL,
                )),
                ("user", models.ForeignKey(
                    on_delete=django.db.models.deletion.CASCADE,
                    related_name="devices", to=settings.AUTH_USER_MODEL,
                )),
            ],
            options={
                "ordering": ("-last_seen",),
                "unique_together": {("user", "fingerprint")},
            },
        ),

        # -- one date moved, roster untouched -----------------------------
        migrations.CreateModel(
            name="ScheduleOverride",
            fields=[
                ("id", models.BigAutoField(
                    auto_created=True, primary_key=True, serialize=False, verbose_name="ID"
                )),
                ("date", models.DateField(db_index=True)),
                ("is_day_off", models.BooleanField(default=False)),
                ("start_time", models.TimeField(blank=True, null=True)),
                ("end_time", models.TimeField(blank=True, null=True)),
                ("work_mode", models.CharField(blank=True, choices=DAY_MODE_CHOICES, max_length=8)),
                ("required_minutes", models.PositiveSmallIntegerField(default=0)),
                ("reason", models.CharField(blank=True, max_length=200)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("created_by", models.ForeignKey(
                    null=True, on_delete=django.db.models.deletion.SET_NULL,
                    related_name="+", to=settings.AUTH_USER_MODEL,
                )),
                ("template", models.ForeignKey(
                    blank=True, null=True,
                    on_delete=django.db.models.deletion.PROTECT,
                    related_name="+", to="dashboard.shifttemplate",
                )),
                ("user", models.ForeignKey(
                    on_delete=django.db.models.deletion.CASCADE,
                    related_name="schedule_overrides", to=settings.AUTH_USER_MODEL,
                )),
            ],
            options={
                "ordering": ("-date",),
                "unique_together": {("user", "date")},
            },
        ),

        # -- the day itself -----------------------------------------------
        migrations.AddField(
            model_name="workday",
            name="work_mode",
            field=models.CharField(blank=True, choices=DAY_MODE_CHOICES, max_length=8),
        ),
        migrations.AddField(
            model_name="workday",
            name="scheduled_start",
            field=models.DateTimeField(blank=True, null=True),
        ),
        migrations.AddField(
            model_name="workday",
            name="scheduled_end",
            field=models.DateTimeField(blank=True, null=True),
        ),
        migrations.AddField(
            model_name="workday",
            name="scheduled_minutes",
            field=models.PositiveSmallIntegerField(default=0),
        ),
        migrations.AddField(
            model_name="workday",
            name="grace_minutes",
            field=models.PositiveSmallIntegerField(default=0),
        ),
        migrations.AddField(
            model_name="workday",
            name="schedule_label",
            field=models.CharField(blank=True, max_length=60),
        ),
        migrations.AddField(
            model_name="workday",
            name="break_minutes",
            field=models.PositiveSmallIntegerField(default=0),
        ),
        migrations.AddField(
            model_name="workday",
            name="work_minutes",
            field=models.PositiveSmallIntegerField(default=0),
        ),
        migrations.AddField(
            model_name="workday",
            name="short_minutes",
            field=models.PositiveSmallIntegerField(default=0),
        ),
        migrations.AddField(
            model_name="workday",
            name="overtime_minutes",
            field=models.PositiveSmallIntegerField(default=0),
        ),
        migrations.AddField(
            model_name="workday",
            name="off_site",
            field=models.BooleanField(
                default=False,
                help_text="An office day punched from outside the allowed radius.",
            ),
        ),
        migrations.AddField(
            model_name="workday",
            name="needs_review",
            field=models.BooleanField(db_index=True, default=False),
        ),
        migrations.AddField(
            model_name="workday",
            name="review_reason",
            field=models.CharField(blank=True, max_length=160),
        ),
        migrations.AddField(
            model_name="workday",
            name="self_recorded",
            field=models.BooleanField(default=False),
        ),

        # -- the punches, append-only -------------------------------------
        migrations.CreateModel(
            name="AttendanceEvent",
            fields=[
                ("id", models.BigAutoField(
                    auto_created=True, primary_key=True, serialize=False, verbose_name="ID"
                )),
                ("kind", models.CharField(
                    choices=[
                        ("check_in", "Check in"),
                        ("check_out", "Check out"),
                        ("break_start", "Break start"),
                        ("break_end", "Break end"),
                    ],
                    max_length=12,
                )),
                ("at", models.DateTimeField(db_index=True)),
                ("latitude", models.DecimalField(
                    blank=True, decimal_places=6, max_digits=9, null=True
                )),
                ("longitude", models.DecimalField(
                    blank=True, decimal_places=6, max_digits=9, null=True
                )),
                ("accuracy_m", models.PositiveIntegerField(blank=True, null=True)),
                ("distance_m", models.PositiveIntegerField(blank=True, null=True)),
                ("within_geofence", models.BooleanField(blank=True, null=True)),
                ("ip", models.GenericIPAddressField(blank=True, null=True)),
                ("user_agent", models.CharField(blank=True, max_length=250)),
                ("source", models.CharField(default="web", max_length=10)),
                ("note", models.CharField(blank=True, max_length=160)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("device", models.ForeignKey(
                    blank=True, null=True,
                    on_delete=django.db.models.deletion.SET_NULL,
                    related_name="+", to="dashboard.authorizeddevice",
                )),
                ("office", models.ForeignKey(
                    blank=True, null=True,
                    on_delete=django.db.models.deletion.SET_NULL,
                    related_name="+", to="dashboard.officelocation",
                )),
                ("user", models.ForeignKey(
                    on_delete=django.db.models.deletion.CASCADE,
                    related_name="attendance_events", to=settings.AUTH_USER_MODEL,
                )),
                ("work_day", models.ForeignKey(
                    blank=True, null=True,
                    on_delete=django.db.models.deletion.CASCADE,
                    related_name="events", to="dashboard.workday",
                )),
            ],
            options={"ordering": ("at", "id")},
        ),
        migrations.AddIndex(
            model_name="attendanceevent",
            index=models.Index(fields=["user", "at"], name="dash_att_user_at_idx"),
        ),

        # -- every correction, with a reason ------------------------------
        migrations.CreateModel(
            name="AttendanceEdit",
            fields=[
                ("id", models.BigAutoField(
                    auto_created=True, primary_key=True, serialize=False, verbose_name="ID"
                )),
                ("field", models.CharField(max_length=40)),
                ("old_value", models.CharField(blank=True, max_length=160)),
                ("new_value", models.CharField(blank=True, max_length=160)),
                ("reason", models.CharField(max_length=250)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("actor", models.ForeignKey(
                    null=True, on_delete=django.db.models.deletion.SET_NULL,
                    related_name="+", to=settings.AUTH_USER_MODEL,
                )),
                ("work_day", models.ForeignKey(
                    on_delete=django.db.models.deletion.CASCADE,
                    related_name="edits", to="dashboard.workday",
                )),
            ],
            options={"ordering": ("-created_at", "-id")},
        ),

        # -- extra hours, waiting on a decision ---------------------------
        migrations.CreateModel(
            name="OvertimeClaim",
            fields=[
                ("id", models.BigAutoField(
                    auto_created=True, primary_key=True, serialize=False, verbose_name="ID"
                )),
                ("date", models.DateField(db_index=True)),
                ("minutes", models.PositiveIntegerField(default=0)),
                ("hourly_rate", models.DecimalField(
                    decimal_places=2, default=Decimal("0.00"), max_digits=9
                )),
                ("amount", models.DecimalField(
                    decimal_places=2, default=Decimal("0.00"), max_digits=9
                )),
                ("status", models.CharField(
                    choices=APPROVAL_CHOICES, db_index=True, default="pending", max_length=10
                )),
                ("reason", models.CharField(blank=True, max_length=250)),
                ("approved_at", models.DateTimeField(blank=True, null=True)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("approved_by", models.ForeignKey(
                    blank=True, null=True,
                    on_delete=django.db.models.deletion.SET_NULL,
                    related_name="+", to=settings.AUTH_USER_MODEL,
                )),
                ("user", models.ForeignKey(
                    on_delete=django.db.models.deletion.CASCADE,
                    related_name="overtime_claims", to=settings.AUTH_USER_MODEL,
                )),
            ],
            options={
                "ordering": ("-date", "-id"),
                "unique_together": {("user", "date")},
            },
        ),

        # -- the payslip carries the month's attendance -------------------
        migrations.AddField(
            model_name="payrollline",
            name="scheduled_days",
            field=models.PositiveSmallIntegerField(default=0),
        ),
        migrations.AddField(
            model_name="payrollline",
            name="office_days",
            field=models.PositiveSmallIntegerField(default=0),
        ),
        migrations.AddField(
            model_name="payrollline",
            name="remote_days",
            field=models.PositiveSmallIntegerField(default=0),
        ),
        migrations.AddField(
            model_name="payrollline",
            name="late_days",
            field=models.PositiveSmallIntegerField(default=0),
        ),
        migrations.AddField(
            model_name="payrollline",
            name="late_minutes",
            field=models.PositiveIntegerField(default=0),
        ),
        migrations.AddField(
            model_name="payrollline",
            name="early_leave_minutes",
            field=models.PositiveIntegerField(default=0),
        ),
        migrations.AddField(
            model_name="payrollline",
            name="short_minutes",
            field=models.PositiveIntegerField(default=0),
        ),
        migrations.AddField(
            model_name="payrollline",
            name="work_minutes",
            field=models.PositiveIntegerField(default=0),
        ),
        migrations.AddField(
            model_name="payrollline",
            name="overtime_minutes",
            field=models.PositiveIntegerField(default=0),
        ),
        migrations.AddField(
            model_name="payrollline",
            name="overtime_bonus",
            field=models.DecimalField(
                decimal_places=2, default=Decimal("0.00"), max_digits=10
            ),
        ),

        # -- the rules, as editable numbers --------------------------------
        migrations.AddField(
            model_name="payrollsettings",
            name="grace_minutes",
            field=models.PositiveSmallIntegerField(default=10),
        ),
        migrations.AddField(
            model_name="payrollsettings",
            name="early_leave_grace_minutes",
            field=models.PositiveSmallIntegerField(default=10),
        ),
        migrations.AddField(
            model_name="payrollsettings",
            name="break_minutes_allowed",
            field=models.PositiveSmallIntegerField(default=60),
        ),
        migrations.AddField(
            model_name="payrollsettings",
            name="break_counts_as_work",
            field=models.BooleanField(
                default=False,
                help_text="Off: hours = out - in - break, which is the contract.",
            ),
        ),
        migrations.AddField(
            model_name="payrollsettings",
            name="geofence_radius_m",
            field=models.PositiveIntegerField(default=200),
        ),
        migrations.AddField(
            model_name="payrollsettings",
            name="off_site_policy",
            field=models.CharField(choices=POLICY_CHOICES, default="review", max_length=8),
        ),
        migrations.AddField(
            model_name="payrollsettings",
            name="checkout_needs_location",
            field=models.BooleanField(
                default=False,
                help_text=(
                    "Section 14: location is read at the punch, never between them."
                ),
            ),
        ),
        migrations.AddField(
            model_name="payrollsettings",
            name="unknown_device_policy",
            field=models.CharField(choices=POLICY_CHOICES, default="review", max_length=8),
        ),
        migrations.AddField(
            model_name="payrollsettings",
            name="device_check_enabled",
            field=models.BooleanField(default=True),
        ),
        migrations.AddField(
            model_name="payrollsettings",
            name="overtime_enabled",
            field=models.BooleanField(default=True),
        ),
        migrations.AddField(
            model_name="payrollsettings",
            name="overtime_min_minutes",
            field=models.PositiveSmallIntegerField(
                default=30,
                help_text="Below this, staying a little late is not overtime.",
            ),
        ),
        migrations.AddField(
            model_name="payrollsettings",
            name="overtime_hourly_rate",
            field=models.DecimalField(
                decimal_places=2, default=Decimal("0.00"), max_digits=9,
                help_text="0 derives the rate from the salary: day value / daily hours.",
            ),
        ),
        migrations.AddField(
            model_name="payrollsettings",
            name="overtime_multiplier",
            field=models.DecimalField(
                decimal_places=2, default=Decimal("1.00"), max_digits=4
            ),
        ),
        migrations.AddField(
            model_name="payrollsettings",
            name="overtime_needs_approval",
            field=models.BooleanField(default=True),
        ),
        migrations.AddField(
            model_name="payrollsettings",
            name="missing_checkin_after_minutes",
            field=models.PositiveSmallIntegerField(default=30),
        ),
        migrations.AddField(
            model_name="payrollsettings",
            name="missing_checkout_after_minutes",
            field=models.PositiveSmallIntegerField(default=60),
        ),
        migrations.AddField(
            model_name="payrollsettings",
            name="short_hours_alert_minutes",
            field=models.PositiveSmallIntegerField(
                default=60,
                help_text="Missing this much of the scheduled day raises an alert.",
            ),
        ),

        migrations.RunPython(seed_shifts, drop_shifts),
    ]
