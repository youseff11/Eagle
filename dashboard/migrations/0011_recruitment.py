"""HR and recruitment: from a first WhatsApp message to an employee file.

What arrives here
-----------------
* **Three roles.** ``hr``, ``reviewer`` and ``accounting`` join the existing
  four. "Manager" in the spec is the team leader Eagle already had, so it is
  not duplicated. Nobody's role changes on migrate.
* **The question bank.** ``Department`` and ``RecruitmentQuestion`` hold what
  HR asks; ``Vacancy`` and ``VacancyQuestion`` hold which of those questions
  each opening uses and in what order. Adding a department, a role or a whole
  new line of work is data from here on, never a deploy.
* **The application.** ``Candidate`` with its ``CandidateAnswer`` rows, plus
  ``CandidateSession`` - the bot's cursor through one conversation.
* **The decisions.** ``Interview`` and ``CandidateTest`` carry their marks;
  the owner's verdict lands on the candidate itself.
* **The employee file.** Fields on ``User`` rather than a second table, so a
  hire does not end up with two identities in one system.
* **The privacy rule as state.** ``Candidate.identity_revealed`` plus the
  terms on ``RecruitmentSettings``. Until HR flips the flag, every outbound
  message is scrubbed of the company's names by ``recruitment.outbound_text``.

``AppSettings.recruit_phone_number_id`` is the whole of the second WhatsApp
line: same token, same webhook, and this ID is what tells a candidate's
message apart from a client's. Blank - which is how it starts - means nothing
changes and every message still goes to the client inbox.
"""

import django.db.models.deletion
from django.conf import settings
from django.db import migrations, models

import dashboard.models


ROLE_CHOICES = [
    ("admin", "Admin"),
    ("operation", "Operation"),
    ("team_lead", "Team Leader"),
    ("translator", "Translator"),
    ("hr", "HR"),
    ("reviewer", "Reviewer"),
    ("accounting", "Accounting"),
]

EMPLOYMENT_STATUS_CHOICES = [
    ("probation", "On probation"),
    ("active", "Confirmed"),
    ("notice", "Serving notice"),
    ("left", "Left the company"),
]

CANDIDATE_STATUS_CHOICES = [
    ("new", "New"),
    ("screening", "HR screening"),
    ("interview", "Interview"),
    ("test", "Test"),
    ("final_review", "Final review"),
    ("owner_approval", "Waiting for the owner"),
    ("approved", "Approved"),
    ("hired", "Hired"),
    ("rejected", "Rejected"),
]

SOURCE_CHOICES = [
    ("whatsapp", "WhatsApp"),
    ("email", "Email"),
    ("website", "Website"),
    ("linkedin", "LinkedIn"),
    ("advert", "Job advertisement"),
    ("referral", "Referral"),
    ("other", "Other"),
]

QUESTION_KIND_CHOICES = [
    ("text", "Text"),
    ("choice", "Multiple choice (one)"),
    ("multi", "Multiple select"),
    ("yes_no", "Yes / No"),
    ("number", "Number"),
    ("date", "Date"),
    ("file", "File upload"),
    ("dropdown", "Dropdown"),
]

ANSWER_TARGET_CHOICES = [
    ("", "Just an answer"),
    ("full_name", "Candidate name"),
    ("email", "E-mail"),
    ("experience_years", "Years of experience"),
    ("languages", "Languages"),
    ("skills", "Skills"),
    ("expected_salary", "Expected salary"),
    ("cv", "CV"),
]

VACANCY_STATUS_CHOICES = [("draft", "Draft"), ("open", "Open"), ("closed", "Closed")]
INTERVIEW_KIND_CHOICES = [("online", "Online"), ("office", "At the office")]
SESSION_STATE_CHOICES = [
    ("picking", "Choosing a vacancy"),
    ("asking", "Answering the questions"),
    ("done", "Handed to HR"),
    ("abandoned", "Went quiet"),
]
EMPLOYMENT_TYPE_CHOICES = [
    ("full_time", "Full time"),
    ("part_time", "Part time"),
    ("freelance", "Freelancer / contractor"),
]
WORK_MODE_CHOICES = [
    ("office", "From the office"),
    ("remote", "Remote"),
    ("hybrid", "Hybrid"),
]


def seed_departments(apps, schema_editor):
    """Section 29's list, plus an armed privacy rule.

    The redaction terms are written here rather than left blank on purpose.
    Section 3 calls for a system rule, and a rule that does nothing until an
    admin remembers to configure it is not one - so the company's own names
    are in place the moment this migration runs, for HR to edit afterwards.
    """
    Settings = apps.get_model("dashboard", "RecruitmentSettings")
    if not Settings.objects.exists():
        Settings.objects.create(
            singleton=1,
            redact_terms="\n".join((
                "EagleLingua",
                "Eagle Translation",
                "النسر للتوريدات العامه",
                "eagel-operation.com",
            )),
        )

    Department = apps.get_model("dashboard", "Department")
    if Department.objects.exists():
        return
    rows = (
        ("Translation", "الترجمة"),
        ("Sales", "المبيعات"),
        ("Marketing", "التسويق"),
        ("Operations", "الأوبريشن"),
        ("HR", "الموارد البشرية"),
        ("Customer Service", "خدمة العملاء"),
        ("Finance", "الحسابات"),
        ("IT", "تكنولوجيا المعلومات"),
    )
    Department.objects.bulk_create([
        Department(name=name, name_ar=name_ar, is_active=True) for name, name_ar in rows
    ])


def drop_departments(apps, schema_editor):
    Department = apps.get_model("dashboard", "Department")
    Department.objects.filter(
        vacancies__isnull=True, candidates__isnull=True, questions__isnull=True
    ).delete()


class Migration(migrations.Migration):

    dependencies = [
        ("dashboard", "0010_attendance"),
    ]

    operations = [
        # -- departments come first: everything else points at them --------
        migrations.CreateModel(
            name="Department",
            fields=[
                ("id", models.BigAutoField(
                    auto_created=True, primary_key=True, serialize=False, verbose_name="ID"
                )),
                ("name", models.CharField(max_length=80, unique=True)),
                ("name_ar", models.CharField(blank=True, max_length=80)),
                ("is_active", models.BooleanField(default=True)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
            ],
            options={"ordering": ("name",)},
        ),

        # -- the three new roles -------------------------------------------
        migrations.AlterField(
            model_name="user",
            name="role",
            field=models.CharField(
                choices=ROLE_CHOICES, default="translator", max_length=20
            ),
        ),

        # -- the employee file ----------------------------------------------
        migrations.AddField(
            model_name="user",
            name="employee_code",
            field=models.CharField(blank=True, db_index=True, max_length=20),
        ),
        migrations.AddField(
            model_name="user",
            name="job_title",
            field=models.CharField(blank=True, max_length=120),
        ),
        migrations.AddField(
            model_name="user",
            name="department",
            field=models.ForeignKey(
                blank=True, null=True,
                on_delete=django.db.models.deletion.SET_NULL,
                related_name="members", to="dashboard.department",
            ),
        ),
        migrations.AddField(
            model_name="user",
            name="joining_date",
            field=models.DateField(blank=True, null=True),
        ),
        migrations.AddField(
            model_name="user",
            name="employment_status",
            field=models.CharField(
                choices=EMPLOYMENT_STATUS_CHOICES, db_index=True,
                default="active", max_length=12,
            ),
        ),
        migrations.AddField(
            model_name="user",
            name="probation_start",
            field=models.DateField(blank=True, null=True),
        ),
        migrations.AddField(
            model_name="user",
            name="probation_end",
            field=models.DateField(blank=True, null=True),
        ),
        migrations.AddField(
            model_name="user",
            name="contract",
            field=models.FileField(
                blank=True, null=True, upload_to=dashboard.models.upload_hr_doc
            ),
        ),

        # -- the recruitment line -------------------------------------------
        migrations.AddField(
            model_name="appsettings",
            name="recruit_phone_number_id",
            field=models.CharField(
                blank=True, max_length=60,
                help_text="Phone number ID of the dedicated recruitment line.",
            ),
        ),
        migrations.AddField(
            model_name="appsettings",
            name="recruit_number_display",
            field=models.CharField(
                blank=True, max_length=32, help_text="Shown on the HR screens only."
            ),
        ),

        # -- the question bank ----------------------------------------------
        migrations.CreateModel(
            name="RecruitmentQuestion",
            fields=[
                ("id", models.BigAutoField(
                    auto_created=True, primary_key=True, serialize=False, verbose_name="ID"
                )),
                ("text", models.CharField(max_length=300)),
                ("text_en", models.CharField(blank=True, max_length=300)),
                ("kind", models.CharField(
                    choices=QUESTION_KIND_CHOICES, default="text", max_length=10
                )),
                ("options", models.JSONField(
                    blank=True, default=list,
                    help_text="Choices, for the pick-one / pick-many / dropdown kinds.",
                )),
                ("maps_to", models.CharField(
                    blank=True, choices=ANSWER_TARGET_CHOICES, max_length=20,
                    help_text="Fills this field on the candidate's profile.",
                )),
                ("help_text", models.CharField(blank=True, max_length=250)),
                ("is_active", models.BooleanField(default=True)),
                ("sort_order", models.PositiveSmallIntegerField(default=0)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("created_by", models.ForeignKey(
                    null=True, on_delete=django.db.models.deletion.SET_NULL,
                    related_name="+", to=settings.AUTH_USER_MODEL,
                )),
                ("department", models.ForeignKey(
                    blank=True, null=True,
                    on_delete=django.db.models.deletion.SET_NULL,
                    related_name="questions", to="dashboard.department",
                    help_text="Blank means a general question.",
                )),
            ],
            options={"ordering": ("department__name", "sort_order", "id")},
        ),

        # -- vacancies -------------------------------------------------------
        migrations.CreateModel(
            name="Vacancy",
            fields=[
                ("id", models.BigAutoField(
                    auto_created=True, primary_key=True, serialize=False, verbose_name="ID"
                )),
                ("code", models.CharField(blank=True, max_length=20, unique=True)),
                ("title", models.CharField(max_length=140)),
                ("openings", models.PositiveSmallIntegerField(default=1)),
                ("required_experience", models.CharField(blank=True, max_length=140)),
                ("required_languages", models.CharField(blank=True, max_length=160)),
                ("required_skills", models.CharField(blank=True, max_length=250)),
                ("salary_min", models.DecimalField(
                    blank=True, decimal_places=2, max_digits=10, null=True
                )),
                ("salary_max", models.DecimalField(
                    blank=True, decimal_places=2, max_digits=10, null=True
                )),
                ("employment_type", models.CharField(
                    choices=EMPLOYMENT_TYPE_CHOICES, default="full_time", max_length=12
                )),
                ("work_mode", models.CharField(
                    choices=WORK_MODE_CHOICES, default="office", max_length=8
                )),
                ("job_description", models.TextField(blank=True)),
                ("requirements", models.TextField(blank=True)),
                ("deadline", models.DateField(blank=True, null=True)),
                ("status", models.CharField(
                    choices=VACANCY_STATUS_CHOICES, db_index=True,
                    default="draft", max_length=8,
                )),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                ("created_by", models.ForeignKey(
                    null=True, on_delete=django.db.models.deletion.SET_NULL,
                    related_name="+", to=settings.AUTH_USER_MODEL,
                )),
                ("department", models.ForeignKey(
                    blank=True, null=True,
                    on_delete=django.db.models.deletion.SET_NULL,
                    related_name="vacancies", to="dashboard.department",
                )),
                ("shifts", models.ManyToManyField(
                    blank=True, related_name="vacancies", to="dashboard.shifttemplate"
                )),
            ],
            options={"ordering": ("-created_at",), "verbose_name_plural": "Vacancies"},
        ),
        migrations.CreateModel(
            name="VacancyQuestion",
            fields=[
                ("id", models.BigAutoField(
                    auto_created=True, primary_key=True, serialize=False, verbose_name="ID"
                )),
                ("order", models.PositiveSmallIntegerField(default=0)),
                ("is_required", models.BooleanField(default=True)),
                ("question", models.ForeignKey(
                    on_delete=django.db.models.deletion.PROTECT,
                    related_name="vacancy_links", to="dashboard.recruitmentquestion",
                )),
                ("vacancy", models.ForeignKey(
                    on_delete=django.db.models.deletion.CASCADE,
                    related_name="question_links", to="dashboard.vacancy",
                )),
            ],
            options={
                "ordering": ("order", "id"),
                "unique_together": {("vacancy", "question")},
            },
        ),

        # -- the application --------------------------------------------------
        migrations.CreateModel(
            name="Candidate",
            fields=[
                ("id", models.BigAutoField(
                    auto_created=True, primary_key=True, serialize=False, verbose_name="ID"
                )),
                ("code", models.CharField(blank=True, max_length=20, unique=True)),
                ("full_name", models.CharField(blank=True, max_length=140)),
                ("phone", models.CharField(blank=True, db_index=True, max_length=32)),
                ("email", models.EmailField(blank=True, max_length=254)),
                ("cv", models.FileField(
                    blank=True, null=True, upload_to=dashboard.models.upload_cv
                )),
                ("cv_name", models.CharField(blank=True, max_length=200)),
                ("experience_years", models.CharField(blank=True, max_length=60)),
                ("languages", models.CharField(blank=True, max_length=160)),
                ("skills", models.CharField(blank=True, max_length=250)),
                ("expected_salary", models.CharField(blank=True, max_length=60)),
                ("shift_choice", models.CharField(blank=True, max_length=120)),
                ("source", models.CharField(
                    choices=SOURCE_CHOICES, default="whatsapp", max_length=10
                )),
                ("status", models.CharField(
                    choices=CANDIDATE_STATUS_CHOICES, db_index=True,
                    default="new", max_length=14,
                )),
                ("hr_notes", models.TextField(blank=True)),
                ("hr_recommendation", models.CharField(blank=True, max_length=250)),
                ("rejection_reason", models.CharField(blank=True, max_length=250)),
                ("identity_revealed", models.BooleanField(default=False)),
                ("identity_revealed_at", models.DateTimeField(blank=True, null=True)),
                ("owner_decision_at", models.DateTimeField(blank=True, null=True)),
                ("applied_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                ("department", models.ForeignKey(
                    blank=True, null=True,
                    on_delete=django.db.models.deletion.SET_NULL,
                    related_name="candidates", to="dashboard.department",
                )),
                ("hired_user", models.OneToOneField(
                    blank=True, null=True,
                    on_delete=django.db.models.deletion.SET_NULL,
                    related_name="candidate_record", to=settings.AUTH_USER_MODEL,
                )),
                ("identity_revealed_by", models.ForeignKey(
                    blank=True, null=True,
                    on_delete=django.db.models.deletion.SET_NULL,
                    related_name="+", to=settings.AUTH_USER_MODEL,
                )),
                ("owner_decision_by", models.ForeignKey(
                    blank=True, null=True,
                    on_delete=django.db.models.deletion.SET_NULL,
                    related_name="+", to=settings.AUTH_USER_MODEL,
                )),
                ("vacancy", models.ForeignKey(
                    blank=True, null=True,
                    on_delete=django.db.models.deletion.SET_NULL,
                    related_name="candidates", to="dashboard.vacancy",
                )),
            ],
            options={"ordering": ("-applied_at",)},
        ),
        migrations.AddIndex(
            model_name="candidate",
            index=models.Index(
                fields=["status", "-applied_at"], name="dash_cand_status_idx"
            ),
        ),
        migrations.CreateModel(
            name="CandidateAnswer",
            fields=[
                ("id", models.BigAutoField(
                    auto_created=True, primary_key=True, serialize=False, verbose_name="ID"
                )),
                ("order", models.PositiveSmallIntegerField(default=0)),
                ("value", models.TextField(blank=True)),
                ("file", models.FileField(
                    blank=True, null=True, upload_to=dashboard.models.upload_cv
                )),
                ("file_name", models.CharField(blank=True, max_length=200)),
                ("answered_at", models.DateTimeField(auto_now_add=True)),
                ("candidate", models.ForeignKey(
                    on_delete=django.db.models.deletion.CASCADE,
                    related_name="answers", to="dashboard.candidate",
                )),
                ("question", models.ForeignKey(
                    on_delete=django.db.models.deletion.PROTECT,
                    related_name="answers", to="dashboard.recruitmentquestion",
                )),
            ],
            options={
                "ordering": ("order", "id"),
                "unique_together": {("candidate", "question")},
            },
        ),
        migrations.CreateModel(
            name="CandidateSession",
            fields=[
                ("id", models.BigAutoField(
                    auto_created=True, primary_key=True, serialize=False, verbose_name="ID"
                )),
                ("channel", models.CharField(default="whatsapp", max_length=10)),
                ("contact", models.CharField(db_index=True, max_length=40)),
                ("display_name", models.CharField(blank=True, max_length=120)),
                ("state", models.CharField(
                    choices=SESSION_STATE_CHOICES, default="picking", max_length=10
                )),
                ("step", models.PositiveSmallIntegerField(default=0)),
                ("pending_options", models.JSONField(blank=True, default=list)),
                ("started_at", models.DateTimeField(auto_now_add=True)),
                ("last_message_at", models.DateTimeField(auto_now=True)),
                ("candidate", models.ForeignKey(
                    blank=True, null=True,
                    on_delete=django.db.models.deletion.SET_NULL,
                    related_name="sessions", to="dashboard.candidate",
                )),
                ("vacancy", models.ForeignKey(
                    blank=True, null=True,
                    on_delete=django.db.models.deletion.SET_NULL,
                    related_name="+", to="dashboard.vacancy",
                )),
            ],
            options={"ordering": ("-last_message_at",)},
        ),
        migrations.AddIndex(
            model_name="candidatesession",
            index=models.Index(fields=["contact", "state"], name="dash_sess_contact_idx"),
        ),

        # -- interviews and tests ----------------------------------------------
        migrations.CreateModel(
            name="Interview",
            fields=[
                ("id", models.BigAutoField(
                    auto_created=True, primary_key=True, serialize=False, verbose_name="ID"
                )),
                ("scheduled_at", models.DateTimeField()),
                ("kind", models.CharField(
                    choices=INTERVIEW_KIND_CHOICES, default="online", max_length=8
                )),
                ("meeting_link", models.CharField(blank=True, max_length=300)),
                ("location", models.CharField(blank=True, max_length=200)),
                ("notes", models.TextField(blank=True)),
                ("communication", models.PositiveSmallIntegerField(blank=True, null=True)),
                ("experience", models.PositiveSmallIntegerField(blank=True, null=True)),
                ("technical", models.PositiveSmallIntegerField(blank=True, null=True)),
                ("computer_skills", models.PositiveSmallIntegerField(blank=True, null=True)),
                ("attitude", models.PositiveSmallIntegerField(blank=True, null=True)),
                ("comments", models.TextField(blank=True)),
                ("evaluated_at", models.DateTimeField(blank=True, null=True)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("candidate", models.ForeignKey(
                    on_delete=django.db.models.deletion.CASCADE,
                    related_name="interviews", to="dashboard.candidate",
                )),
                ("created_by", models.ForeignKey(
                    null=True, on_delete=django.db.models.deletion.SET_NULL,
                    related_name="+", to=settings.AUTH_USER_MODEL,
                )),
                ("evaluated_by", models.ForeignKey(
                    blank=True, null=True,
                    on_delete=django.db.models.deletion.SET_NULL,
                    related_name="+", to=settings.AUTH_USER_MODEL,
                )),
                ("interviewer", models.ForeignKey(
                    blank=True, null=True,
                    on_delete=django.db.models.deletion.SET_NULL,
                    related_name="interviews_given", to=settings.AUTH_USER_MODEL,
                )),
            ],
            options={"ordering": ("-scheduled_at", "-id")},
        ),
        migrations.CreateModel(
            name="CandidateTest",
            fields=[
                ("id", models.BigAutoField(
                    auto_created=True, primary_key=True, serialize=False, verbose_name="ID"
                )),
                ("title", models.CharField(blank=True, max_length=160)),
                ("brief", models.TextField(blank=True)),
                ("language_pair", models.CharField(blank=True, max_length=80)),
                ("word_count", models.PositiveIntegerField(default=0)),
                ("assignment", models.FileField(
                    blank=True, null=True, upload_to=dashboard.models.upload_test
                )),
                ("assignment_name", models.CharField(blank=True, max_length=200)),
                ("submission", models.FileField(
                    blank=True, null=True, upload_to=dashboard.models.upload_test
                )),
                ("submission_name", models.CharField(blank=True, max_length=200)),
                ("submitted_at", models.DateTimeField(blank=True, null=True)),
                ("deadline", models.DateTimeField(blank=True, null=True)),
                ("accuracy", models.PositiveSmallIntegerField(blank=True, null=True)),
                ("grammar", models.PositiveSmallIntegerField(blank=True, null=True)),
                ("terminology", models.PositiveSmallIntegerField(blank=True, null=True)),
                ("formatting", models.PositiveSmallIntegerField(blank=True, null=True)),
                ("instructions", models.PositiveSmallIntegerField(blank=True, null=True)),
                ("comments", models.TextField(blank=True)),
                ("marked_at", models.DateTimeField(blank=True, null=True)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("candidate", models.ForeignKey(
                    on_delete=django.db.models.deletion.CASCADE,
                    related_name="tests", to="dashboard.candidate",
                )),
                ("created_by", models.ForeignKey(
                    null=True, on_delete=django.db.models.deletion.SET_NULL,
                    related_name="+", to=settings.AUTH_USER_MODEL,
                )),
                ("department", models.ForeignKey(
                    blank=True, null=True,
                    on_delete=django.db.models.deletion.SET_NULL,
                    related_name="+", to="dashboard.department",
                )),
                ("reviewer", models.ForeignKey(
                    blank=True, null=True,
                    on_delete=django.db.models.deletion.SET_NULL,
                    related_name="tests_reviewed", to=settings.AUTH_USER_MODEL,
                )),
            ],
            options={"ordering": ("-created_at", "-id")},
        ),

        # -- the module's own rules ---------------------------------------------
        migrations.CreateModel(
            name="RecruitmentSettings",
            fields=[
                ("singleton", models.PositiveSmallIntegerField(
                    default=1, editable=False, primary_key=True, serialize=False
                )),
                ("bot_enabled", models.BooleanField(default=True)),
                ("bot_name", models.CharField(
                    default="Recruitment Team", max_length=80,
                    help_text="What the candidate sees instead of the company name.",
                )),
                ("bot_name_ar", models.CharField(default="فريق التوظيف", max_length=80)),
                ("redact_terms", models.TextField(
                    blank=True,
                    help_text=(
                        "One per line: company names, domain, address. Removed from "
                        "anything sent to an anonymous candidate."
                    ),
                )),
                ("redact_placeholder", models.CharField(default="[—]", max_length=60)),
                ("greeting_ar", models.TextField(
                    blank=True, help_text="Blank uses the built-in wording."
                )),
                ("greeting_en", models.TextField(blank=True)),
                ("closing_ar", models.TextField(blank=True)),
                ("closing_en", models.TextField(blank=True)),
                ("session_timeout_hours", models.PositiveSmallIntegerField(default=48)),
                ("probation_days", models.PositiveSmallIntegerField(default=90)),
                ("updated_at", models.DateTimeField(auto_now=True)),
            ],
            options={
                "verbose_name": "Recruitment settings",
                "verbose_name_plural": "Recruitment settings",
            },
        ),

        migrations.RunPython(seed_departments, drop_departments),
    ]
