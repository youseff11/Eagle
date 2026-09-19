"""Probation, leave, performance and per-person pay - the HR module's part 2.

Four sections of the spec land together because they share one shape: the
engine works out what is true and a person decides what happens about it.

* **Probation (19).** ``ProbationReview`` - three dated rows created when
  somebody is hired, so a missed review is visible instead of forgotten.
* **Performance (20).** Three indicators the system previously had no source
  for now have one: ``Task.review_score`` is the reviewer's mark,
  ``Task.revision_count`` counts the times a job went back, and
  ``ClientComplaint`` is a complaint somebody actually logged. Nothing is
  estimated - an indicator with no data reads as "not measured".
* **Leave (22).** ``LeaveRequest``, plus ``WorkDay.excused_minutes`` so an
  approved permission stops counting as a shortfall. Approving a leave writes
  the days onto the attendance sheet, which is what stops it later reading as
  an unexcused absence.
* **Pay (23).** ``SalaryPlan`` is a set of *optional* overrides - every field
  nullable, every blank falling back to ``PayrollSettings``. Somebody with no
  plan is priced exactly as they were before this migration, which is the
  point. ``SalaryChangeRequest`` is the only path a salary can move along,
  and it ends at the owner.

``PayrollLine.allowance`` is stored rather than recomputed because releasing
a month's bonuses rebuilds ``gross`` from the line, and a component that is
not on the line is a component that quietly disappears when it does.
"""

from decimal import Decimal

import django.db.models.deletion
from django.conf import settings
from django.db import migrations, models


PROBATION_STAGE_CHOICES = [
    ("day_30", "30-day review"),
    ("day_60", "60-day review"),
    ("final", "Final probation review"),
]

PROBATION_OUTCOME_CHOICES = [
    ("pending", "Not decided yet"),
    ("confirmed", "Confirmed"),
    ("extended", "Probation extended"),
    ("terminated", "Terminated"),
]

LEAVE_KIND_CHOICES = [
    ("annual", "Annual leave"),
    ("emergency", "Emergency leave"),
    ("permission", "Permission (hours)"),
    ("unpaid", "Unpaid leave"),
    ("other", "Other"),
]

LEAVE_STATUS_CHOICES = [
    ("pending", "Waiting"),
    ("manager_ok", "Manager approved, waiting for HR"),
    ("approved", "Approved"),
    ("rejected", "Rejected"),
    ("cancelled", "Withdrawn"),
]

SEVERITY_CHOICES = [
    ("low", "Minor"),
    ("medium", "Needs attention"),
    ("high", "Serious"),
]

APPROVAL_CHOICES = [
    ("pending", "Waiting for approval"),
    ("approved", "Approved"),
    ("rejected", "Rejected"),
]


class Migration(migrations.Migration):

    dependencies = [
        ("dashboard", "0011_recruitment"),
    ]

    operations = [
        # -- the two signals section 20 had no source for -------------------
        migrations.AddField(
            model_name="task",
            name="review_score",
            field=models.PositiveSmallIntegerField(blank=True, null=True),
        ),
        migrations.AddField(
            model_name="task",
            name="review_note",
            field=models.CharField(blank=True, max_length=250),
        ),
        migrations.AddField(
            model_name="task",
            name="revision_count",
            field=models.PositiveSmallIntegerField(default=0),
        ),
        migrations.AddField(
            model_name="task",
            name="returned_at",
            field=models.DateTimeField(blank=True, null=True),
        ),

        # -- an approved permission is not a shortfall ----------------------
        migrations.AddField(
            model_name="workday",
            name="excused_minutes",
            field=models.PositiveSmallIntegerField(default=0),
        ),

        # -- the plan, and the line that has to remember its allowance ------
        migrations.CreateModel(
            name="SalaryPlan",
            fields=[
                ("id", models.BigAutoField(
                    auto_created=True, primary_key=True, serialize=False, verbose_name="ID"
                )),
                ("name", models.CharField(max_length=80, unique=True)),
                ("note", models.CharField(blank=True, max_length=250)),
                ("is_active", models.BooleanField(default=True)),
                ("daily_target_words", models.PositiveIntegerField(blank=True, null=True)),
                ("secondary_daily_target_words", models.PositiveIntegerField(
                    blank=True, null=True
                )),
                ("monthly_target_words", models.PositiveIntegerField(blank=True, null=True)),
                ("extra_word_rate", models.DecimalField(
                    blank=True, decimal_places=4, max_digits=8, null=True,
                    help_text=(
                        "Paid per word above the daily quota. Blank uses the "
                        "company's bonus bands."
                    ),
                )),
                ("fixed_allowance", models.DecimalField(
                    decimal_places=2, default=Decimal("0.00"), max_digits=10
                )),
                ("discipline_bonus", models.DecimalField(
                    blank=True, decimal_places=2, max_digits=9, null=True
                )),
                ("target_bonus", models.DecimalField(
                    blank=True, decimal_places=2, max_digits=9, null=True
                )),
                ("target_miss_penalty", models.DecimalField(
                    blank=True, decimal_places=2, max_digits=9, null=True
                )),
                ("working_days_per_month", models.PositiveSmallIntegerField(
                    blank=True, null=True
                )),
                ("monthly_leave_allowance", models.PositiveSmallIntegerField(
                    blank=True, null=True
                )),
                ("overtime_hourly_rate", models.DecimalField(
                    blank=True, decimal_places=2, max_digits=9, null=True
                )),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                ("created_by", models.ForeignKey(
                    null=True, on_delete=django.db.models.deletion.SET_NULL,
                    related_name="+", to=settings.AUTH_USER_MODEL,
                )),
            ],
            options={"ordering": ("name",)},
        ),
        migrations.AddField(
            model_name="user",
            name="salary_plan",
            field=models.ForeignKey(
                blank=True, null=True,
                on_delete=django.db.models.deletion.SET_NULL,
                related_name="members", to="dashboard.salaryplan",
            ),
        ),
        migrations.AddField(
            model_name="payrollline",
            name="allowance",
            field=models.DecimalField(
                decimal_places=2, default=Decimal("0.00"), max_digits=10
            ),
        ),

        # -- probation -------------------------------------------------------
        migrations.CreateModel(
            name="ProbationReview",
            fields=[
                ("id", models.BigAutoField(
                    auto_created=True, primary_key=True, serialize=False, verbose_name="ID"
                )),
                ("stage", models.CharField(choices=PROBATION_STAGE_CHOICES, max_length=8)),
                ("due_date", models.DateField(db_index=True)),
                ("outcome", models.CharField(
                    choices=PROBATION_OUTCOME_CHOICES, db_index=True,
                    default="pending", max_length=12,
                )),
                ("score", models.PositiveSmallIntegerField(blank=True, null=True)),
                ("notes", models.TextField(blank=True)),
                ("extended_to", models.DateField(blank=True, null=True)),
                ("decided_at", models.DateTimeField(blank=True, null=True)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("reviewer", models.ForeignKey(
                    blank=True, null=True,
                    on_delete=django.db.models.deletion.SET_NULL,
                    related_name="+", to=settings.AUTH_USER_MODEL,
                )),
                ("user", models.ForeignKey(
                    on_delete=django.db.models.deletion.CASCADE,
                    related_name="probation_reviews", to=settings.AUTH_USER_MODEL,
                )),
            ],
            options={
                "ordering": ("due_date", "id"),
                "unique_together": {("user", "stage")},
            },
        ),

        # -- leave -----------------------------------------------------------
        migrations.CreateModel(
            name="LeaveRequest",
            fields=[
                ("id", models.BigAutoField(
                    auto_created=True, primary_key=True, serialize=False, verbose_name="ID"
                )),
                ("kind", models.CharField(
                    choices=LEAVE_KIND_CHOICES, default="annual", max_length=10
                )),
                ("start_date", models.DateField()),
                ("end_date", models.DateField()),
                ("start_time", models.TimeField(blank=True, null=True)),
                ("end_time", models.TimeField(blank=True, null=True)),
                ("minutes", models.PositiveSmallIntegerField(default=0)),
                ("reason", models.CharField(blank=True, max_length=250)),
                ("status", models.CharField(
                    choices=LEAVE_STATUS_CHOICES, db_index=True,
                    default="pending", max_length=11,
                )),
                ("manager_decided_at", models.DateTimeField(blank=True, null=True)),
                ("hr_decided_at", models.DateTimeField(blank=True, null=True)),
                ("decision_note", models.CharField(blank=True, max_length=250)),
                ("applied_at", models.DateTimeField(blank=True, null=True)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("hr_decision_by", models.ForeignKey(
                    blank=True, null=True,
                    on_delete=django.db.models.deletion.SET_NULL,
                    related_name="+", to=settings.AUTH_USER_MODEL,
                )),
                ("manager", models.ForeignKey(
                    blank=True, null=True,
                    on_delete=django.db.models.deletion.SET_NULL,
                    related_name="+", to=settings.AUTH_USER_MODEL,
                )),
                ("user", models.ForeignKey(
                    on_delete=django.db.models.deletion.CASCADE,
                    related_name="leave_requests", to=settings.AUTH_USER_MODEL,
                )),
            ],
            options={"ordering": ("-created_at",)},
        ),
        migrations.AddIndex(
            model_name="leaverequest",
            index=models.Index(fields=["user", "status"], name="dash_leave_user_idx"),
        ),

        # -- complaints --------------------------------------------------------
        migrations.CreateModel(
            name="ClientComplaint",
            fields=[
                ("id", models.BigAutoField(
                    auto_created=True, primary_key=True, serialize=False, verbose_name="ID"
                )),
                ("severity", models.CharField(
                    choices=SEVERITY_CHOICES, default="medium", max_length=6
                )),
                ("summary", models.CharField(max_length=250)),
                ("detail", models.TextField(blank=True)),
                ("happened_on", models.DateField(blank=True, default=None, null=True)),
                ("resolved", models.BooleanField(default=False)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("client", models.ForeignKey(
                    blank=True, null=True,
                    on_delete=django.db.models.deletion.SET_NULL,
                    related_name="complaints", to="dashboard.client",
                )),
                ("logged_by", models.ForeignKey(
                    null=True, on_delete=django.db.models.deletion.SET_NULL,
                    related_name="+", to=settings.AUTH_USER_MODEL,
                )),
                ("task", models.ForeignKey(
                    blank=True, null=True,
                    on_delete=django.db.models.deletion.SET_NULL,
                    related_name="complaints", to="dashboard.task",
                )),
                ("translator", models.ForeignKey(
                    blank=True, null=True,
                    on_delete=django.db.models.deletion.SET_NULL,
                    related_name="complaints", to=settings.AUTH_USER_MODEL,
                )),
            ],
            options={"ordering": ("-created_at",)},
        ),

        # -- salary change requests ---------------------------------------------
        migrations.CreateModel(
            name="SalaryChangeRequest",
            fields=[
                ("id", models.BigAutoField(
                    auto_created=True, primary_key=True, serialize=False, verbose_name="ID"
                )),
                ("current_amount", models.DecimalField(
                    decimal_places=2, default=Decimal("0.00"), max_digits=10
                )),
                ("new_amount", models.DecimalField(decimal_places=2, max_digits=10)),
                ("effective_from", models.DateField()),
                ("reason", models.CharField(blank=True, max_length=250)),
                ("status", models.CharField(
                    choices=APPROVAL_CHOICES, db_index=True,
                    default="pending", max_length=10,
                )),
                ("decided_at", models.DateTimeField(blank=True, null=True)),
                ("decision_note", models.CharField(blank=True, max_length=250)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("decided_by", models.ForeignKey(
                    blank=True, null=True,
                    on_delete=django.db.models.deletion.SET_NULL,
                    related_name="+", to=settings.AUTH_USER_MODEL,
                )),
                ("requested_by", models.ForeignKey(
                    null=True, on_delete=django.db.models.deletion.SET_NULL,
                    related_name="+", to=settings.AUTH_USER_MODEL,
                )),
                ("salary_record", models.ForeignKey(
                    blank=True, null=True,
                    on_delete=django.db.models.deletion.SET_NULL,
                    related_name="+", to="dashboard.salaryrecord",
                )),
                ("user", models.ForeignKey(
                    on_delete=django.db.models.deletion.CASCADE,
                    related_name="salary_requests", to=settings.AUTH_USER_MODEL,
                )),
            ],
            options={"ordering": ("-created_at",)},
        ),

        # -- the settings these four sections read -------------------------------
        migrations.AddField(
            model_name="payrollsettings",
            name="leave_needs_manager",
            field=models.BooleanField(default=False),
        ),
        migrations.AddField(
            model_name="payrollsettings",
            name="permission_max_minutes",
            field=models.PositiveSmallIntegerField(
                default=240, help_text="Longest single permission, in minutes."
            ),
        ),
        migrations.AddField(
            model_name="payrollsettings",
            name="weight_productivity",
            field=models.PositiveSmallIntegerField(default=40),
        ),
        migrations.AddField(
            model_name="payrollsettings",
            name="weight_quality",
            field=models.PositiveSmallIntegerField(default=30),
        ),
        migrations.AddField(
            model_name="payrollsettings",
            name="weight_deadline",
            field=models.PositiveSmallIntegerField(default=20),
        ),
        migrations.AddField(
            model_name="payrollsettings",
            name="weight_attendance",
            field=models.PositiveSmallIntegerField(default=10),
        ),
    ]
