"""Accounts: attendance, production tiers, violations and the monthly payroll.

The two tables from the contract are seeded here rather than hard-coded, so
the admin can move a band or a value from the panel without a deploy.
"""

import django.db.models.deletion
from decimal import Decimal
from django.conf import settings
from django.db import migrations, models


PRIMARY_TIERS = (
    (3000, 3800, "25"),
    (3800, 4600, "35"),
    (4600, 5900, "45"),
    (5900, None, "60"),
)

SECONDARY_TIERS = (
    (1500, 2000, "25"),
    (2000, 2500, "35"),
    (2500, 3000, "45"),
    (3000, 3500, "55"),
    (3500, 4000, "65"),
    (4000, 4500, "75"),
    (4500, 5000, "85"),
    (5000, None, "95"),
)


def seed_tiers(apps, schema_editor):
    ProductionTier = apps.get_model("dashboard", "ProductionTier")
    if ProductionTier.objects.exists():
        return
    rows = []
    for scale, bands in (("primary", PRIMARY_TIERS), ("secondary", SECONDARY_TIERS)):
        for low, high, bonus in bands:
            rows.append(ProductionTier(
                scale=scale, min_words=low, max_words=high, bonus=Decimal(bonus)
            ))
    ProductionTier.objects.bulk_create(rows)


def drop_tiers(apps, schema_editor):
    apps.get_model("dashboard", "ProductionTier").objects.all().delete()


class Migration(migrations.Migration):

    dependencies = [
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
        ("dashboard", "0007_replies"),
    ]

    operations = [
        # -- the job now carries its size ----------------------------------
        migrations.AddField(
            model_name="task",
            name="word_count",
            field=models.PositiveIntegerField(default=0),
        ),
        migrations.AddField(
            model_name="task",
            name="is_difficult",
            field=models.BooleanField(
                default=False,
                help_text=(
                    "Set by the project manager - exempts the day from the "
                    "production floor."
                ),
            ),
        ),
        migrations.AddField(
            model_name="task",
            name="is_secondary_language",
            field=models.BooleanField(
                default=False,
                help_text="The translator worked outside their main language.",
            ),
        ),

        # -- the rule book --------------------------------------------------
        migrations.CreateModel(
            name="PayrollSettings",
            fields=[
                ("singleton", models.PositiveSmallIntegerField(
                    default=1, editable=False, primary_key=True, serialize=False)),
                ("daily_hours", models.PositiveSmallIntegerField(default=8)),
                ("working_days_per_month", models.PositiveSmallIntegerField(default=26)),
                ("monthly_leave_allowance", models.PositiveSmallIntegerField(default=4)),
                ("daily_target_words", models.PositiveIntegerField(default=3000)),
                ("secondary_daily_target_words", models.PositiveIntegerField(default=1500)),
                ("monthly_target_words", models.PositiveIntegerField(default=78000)),
                ("monthly_alert_words", models.PositiveIntegerField(
                    default=75000,
                    help_text="Below this the admin is warned for the month.")),
                ("extra_leave_penalty_days", models.DecimalField(
                    decimal_places=2, default=Decimal("1.25"), max_digits=5,
                    help_text="Per leave day beyond the monthly allowance.")),
                ("unexcused_penalty_days", models.DecimalField(
                    decimal_places=2, default=Decimal("2.00"), max_digits=5)),
                ("quality_penalty_days", models.DecimalField(
                    decimal_places=2, default=Decimal("2.00"), max_digits=5)),
                ("low_output_penalty_days", models.DecimalField(
                    decimal_places=2, default=Decimal("0.25"), max_digits=5)),
                ("unexcused_escalation_count", models.PositiveSmallIntegerField(
                    default=3,
                    help_text=(
                        "The n-th absence without permission escalates to the owner."
                    ))),
                ("target_miss_penalty", models.DecimalField(
                    decimal_places=2, default=Decimal("250.00"), max_digits=9)),
                ("discipline_bonus", models.DecimalField(
                    decimal_places=2, default=Decimal("250.00"), max_digits=9)),
                ("target_bonus", models.DecimalField(
                    decimal_places=2, default=Decimal("250.00"), max_digits=9)),
                ("bonuses_need_approval", models.BooleanField(default=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
            ],
            options={
                "verbose_name": "Payroll settings",
                "verbose_name_plural": "Payroll settings",
            },
        ),
        migrations.CreateModel(
            name="ProductionTier",
            fields=[
                ("id", models.BigAutoField(
                    auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("scale", models.CharField(
                    choices=[("primary", "Primary language"),
                             ("secondary", "Secondary language")],
                    default="primary", max_length=12)),
                ("min_words", models.PositiveIntegerField(help_text="Exclusive lower edge.")),
                ("max_words", models.PositiveIntegerField(
                    blank=True, null=True,
                    help_text="Inclusive upper edge. Blank = open ended.")),
                ("bonus", models.DecimalField(decimal_places=2, max_digits=9)),
            ],
            options={
                "ordering": ("scale", "min_words"),
                "unique_together": {("scale", "min_words")},
            },
        ),

        # -- salary history --------------------------------------------------
        migrations.CreateModel(
            name="SalaryRecord",
            fields=[
                ("id", models.BigAutoField(
                    auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("amount", models.DecimalField(decimal_places=2, max_digits=10)),
                ("effective_from", models.DateField()),
                ("note", models.CharField(blank=True, max_length=200)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("created_by", models.ForeignKey(
                    null=True, on_delete=django.db.models.deletion.SET_NULL,
                    related_name="+", to=settings.AUTH_USER_MODEL)),
                ("user", models.ForeignKey(
                    on_delete=django.db.models.deletion.CASCADE,
                    related_name="salary_records", to=settings.AUTH_USER_MODEL)),
            ],
            options={"ordering": ("-effective_from", "-id")},
        ),

        # -- attendance and daily production ---------------------------------
        migrations.CreateModel(
            name="WorkDay",
            fields=[
                ("id", models.BigAutoField(
                    auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("date", models.DateField(db_index=True)),
                ("status", models.CharField(
                    choices=[("present", "Present"), ("leave", "Paid leave"),
                             ("excused", "Excused absence"),
                             ("unexcused", "Unexcused absence"),
                             ("weekly_off", "Weekly off"), ("holiday", "Public holiday")],
                    db_index=True, default="present", max_length=12)),
                ("check_in", models.DateTimeField(blank=True, null=True)),
                ("check_out", models.DateTimeField(blank=True, null=True)),
                ("late_minutes", models.PositiveIntegerField(default=0)),
                ("early_leave_minutes", models.PositiveIntegerField(default=0)),
                ("words", models.PositiveIntegerField(default=0)),
                ("words_from_jobs", models.BooleanField(default=False)),
                ("is_secondary_language", models.BooleanField(
                    default=False,
                    help_text="Worked in a language other than their main one.")),
                ("difficult_file", models.BooleanField(
                    default=False,
                    help_text=(
                        "Manager marked the file difficult - exempt from the "
                        "daily floor."
                    ))),
                ("absence_reason", models.CharField(blank=True, max_length=200)),
                ("note", models.CharField(blank=True, max_length=250)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                ("user", models.ForeignKey(
                    on_delete=django.db.models.deletion.CASCADE,
                    related_name="work_days", to=settings.AUTH_USER_MODEL)),
            ],
            options={
                "ordering": ("-date",),
                "unique_together": {("user", "date")},
            },
        ),
        migrations.AddIndex(
            model_name="workday",
            index=models.Index(fields=["user", "date"], name="dash_workday_user_date_idx"),
        ),

        # -- violations, every one of them waiting on a decision --------------
        migrations.CreateModel(
            name="Violation",
            fields=[
                ("id", models.BigAutoField(
                    auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("date", models.DateField(db_index=True)),
                ("kind", models.CharField(
                    choices=[("discipline", "Internal rules"),
                             ("quality", "Translation error"),
                             ("low_output", "Low productivity"),
                             ("unexcused", "Absence without permission"),
                             ("extra_leave", "Leave beyond the balance"),
                             ("target_miss", "Monthly target missed"),
                             ("manual", "Manual adjustment")],
                    max_length=16)),
                ("status", models.CharField(
                    choices=[("pending", "Waiting for approval"),
                             ("approved", "Approved"), ("rejected", "Rejected")],
                    db_index=True, default="pending", max_length=10)),
                ("penalty_days", models.DecimalField(
                    decimal_places=2, default=Decimal("0.00"), max_digits=5)),
                ("penalty_amount", models.DecimalField(
                    decimal_places=2, default=Decimal("0.00"), max_digits=9)),
                ("reason", models.CharField(blank=True, max_length=250)),
                ("escalated", models.BooleanField(
                    default=False,
                    help_text=(
                        "Third absence without permission - sent to the owner."
                    ))),
                ("auto_key", models.CharField(blank=True, db_index=True, max_length=80)),
                ("approved_at", models.DateTimeField(blank=True, null=True)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("approved_by", models.ForeignKey(
                    blank=True, null=True,
                    on_delete=django.db.models.deletion.SET_NULL,
                    related_name="+", to=settings.AUTH_USER_MODEL)),
                ("created_by", models.ForeignKey(
                    null=True, on_delete=django.db.models.deletion.SET_NULL,
                    related_name="+", to=settings.AUTH_USER_MODEL)),
                ("task", models.ForeignKey(
                    blank=True, null=True,
                    on_delete=django.db.models.deletion.SET_NULL,
                    related_name="+", to="dashboard.task")),
                ("user", models.ForeignKey(
                    on_delete=django.db.models.deletion.CASCADE,
                    related_name="violations", to=settings.AUTH_USER_MODEL)),
            ],
            options={"ordering": ("-date", "-id")},
        ),
        migrations.AddIndex(
            model_name="violation",
            index=models.Index(
                fields=["user", "date", "status"], name="dash_viol_user_date_idx"
            ),
        ),

        # -- the payroll run --------------------------------------------------
        migrations.CreateModel(
            name="PayrollPeriod",
            fields=[
                ("id", models.BigAutoField(
                    auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("year", models.PositiveSmallIntegerField()),
                ("month", models.PositiveSmallIntegerField()),
                ("status", models.CharField(
                    choices=[("draft", "Draft"), ("approved", "Approved"),
                             ("locked", "Locked")],
                    default="draft", max_length=10)),
                ("note", models.CharField(blank=True, max_length=250)),
                ("approved_at", models.DateTimeField(blank=True, null=True)),
                ("computed_at", models.DateTimeField(blank=True, null=True)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("approved_by", models.ForeignKey(
                    blank=True, null=True,
                    on_delete=django.db.models.deletion.SET_NULL,
                    related_name="+", to=settings.AUTH_USER_MODEL)),
            ],
            options={
                "ordering": ("-year", "-month"),
                "unique_together": {("year", "month")},
            },
        ),
        migrations.CreateModel(
            name="PayrollLine",
            fields=[
                ("id", models.BigAutoField(
                    auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("base_salary", models.DecimalField(
                    decimal_places=2, default=Decimal("0.00"), max_digits=10)),
                ("working_days", models.PositiveSmallIntegerField(default=0)),
                ("day_value", models.DecimalField(
                    decimal_places=2, default=Decimal("0.00"), max_digits=10)),
                ("worked_days", models.PositiveSmallIntegerField(default=0)),
                ("leave_days", models.PositiveSmallIntegerField(default=0)),
                ("unexcused_days", models.PositiveSmallIntegerField(default=0)),
                ("extra_leave_days", models.PositiveSmallIntegerField(default=0)),
                ("total_words", models.PositiveIntegerField(default=0)),
                ("target_words", models.PositiveIntegerField(default=0)),
                ("under_target_days", models.PositiveSmallIntegerField(default=0)),
                ("production_bonus", models.DecimalField(
                    decimal_places=2, default=Decimal("0.00"), max_digits=10)),
                ("discipline_bonus", models.DecimalField(
                    decimal_places=2, default=Decimal("0.00"), max_digits=10)),
                ("target_bonus", models.DecimalField(
                    decimal_places=2, default=Decimal("0.00"), max_digits=10)),
                ("deductions", models.DecimalField(
                    decimal_places=2, default=Decimal("0.00"), max_digits=10)),
                ("gross", models.DecimalField(
                    decimal_places=2, default=Decimal("0.00"), max_digits=10)),
                ("net", models.DecimalField(
                    decimal_places=2, default=Decimal("0.00"), max_digits=10)),
                ("discipline_bonus_earned", models.BooleanField(default=False)),
                ("target_bonus_earned", models.BooleanField(default=False)),
                ("bonuses_approved", models.BooleanField(default=False)),
                ("below_alert_threshold", models.BooleanField(default=False)),
                ("breakdown", models.JSONField(blank=True, default=dict)),
                ("computed_at", models.DateTimeField(auto_now=True)),
                ("period", models.ForeignKey(
                    on_delete=django.db.models.deletion.CASCADE,
                    related_name="lines", to="dashboard.payrollperiod")),
                ("user", models.ForeignKey(
                    on_delete=django.db.models.deletion.CASCADE,
                    related_name="payroll_lines", to=settings.AUTH_USER_MODEL)),
            ],
            options={
                "ordering": ("user__username",),
                "unique_together": {("period", "user")},
            },
        ),

        migrations.RunPython(seed_tiers, drop_tiers),
    ]
