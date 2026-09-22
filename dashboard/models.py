"""Data model for the Eagle translation-workflow dashboard (Phase 1)."""

from datetime import time, timedelta
from decimal import Decimal

from django.conf import settings as dj_settings
from django.contrib.auth.models import AbstractUser
from django.db import models
from django.utils import timezone


# ---------------------------------------------------------------------------
# Choices
# ---------------------------------------------------------------------------

class Role(models.TextChoices):
    ADMIN = "admin", "Admin"
    OPERATION = "operation", "Operation"
    TEAM_LEAD = "team_lead", "Team Leader"
    TRANSLATOR = "translator", "Translator"
    #: Added with the HR module. "Manager" in the spec is the team leader we
    #: already had, so it is not repeated here.
    HR = "hr", "HR"
    REVIEWER = "reviewer", "Reviewer"
    ACCOUNTING = "accounting", "Accounting"


class Channel(models.TextChoices):
    WHATSAPP = "whatsapp", "WhatsApp"
    EMAIL = "email", "Email"
    MANUAL = "manual", "Manual"


class TaskStatus(models.TextChoices):
    NEW = "new", "New"
    AWAITING_LEAD = "awaiting_lead", "Awaiting team leader"
    LEAD_ACCEPTED = "lead_accepted", "Team leader accepted"
    AWAITING_TRANSLATOR = "awaiting_translator", "Awaiting translator"
    IN_PROGRESS = "in_progress", "In progress"
    UNDER_REVIEW = "under_review", "Under review"
    REVIEWED = "reviewed", "Reviewed"
    DELIVERED = "delivered", "Delivered"
    CANCELLED = "cancelled", "Cancelled"


#: Statuses that mean the task is still occupying the people working on it.
ACTIVE_TASK_STATUSES = (
    TaskStatus.AWAITING_LEAD,
    TaskStatus.LEAD_ACCEPTED,
    TaskStatus.AWAITING_TRANSLATOR,
    TaskStatus.IN_PROGRESS,
    TaskStatus.UNDER_REVIEW,
    TaskStatus.REVIEWED,
)


class AssignmentStatus(models.TextChoices):
    PENDING = "pending", "Pending"
    ACCEPTED = "accepted", "Accepted"
    DECLINED = "declined", "Declined"
    EXPIRED = "expired", "Expired"
    CANCELLED = "cancelled", "Cancelled"


class Priority(models.TextChoices):
    LOW = "low", "Low"
    NORMAL = "normal", "Normal"
    HIGH = "high", "High"
    URGENT = "urgent", "Urgent"


class WordCountState(models.TextChoices):
    """Where a task's word count came from, and whether it can be trusted."""

    EMPTY = "empty", "Not counted yet"
    #: Read from the files and cross-checked - it may go straight to payroll.
    AUTO = "auto", "Counted from the files"
    #: Counted, but the two sides disagree or only one could be read.
    REVIEW = "review", "Needs a human to confirm"
    #: Nothing readable - a PDF or a scan. Somebody has to type it.
    MANUAL_NEEDED = "manual_needed", "Must be entered by hand"
    CONFIRMED = "confirmed", "Confirmed by a person"


class RoomKind(models.TextChoices):
    OPS_LEAD = "ops_lead", "Operation + Team leader"
    GROUP = "group", "Operation + Team leader + Translator"
    #: Two employees, one to one. No client anywhere near it, so nothing here
    #: is ever relayed; ``pair_key`` is what keeps a pair to a single room.
    STAFF = "staff", "Two employees, one to one"
    #: A work group somebody opened by hand, with a name and the people they
    #: picked. Not bound to a task and never relayed - the internal room a
    #: team leader opens for a translator lives here.
    TEAM = "team", "Internal work group"
    #: The team on one side, the client's WhatsApp on the other. Eagle relays
    #: between them, so the team gets a group chat without the client ever
    #: leaving WhatsApp — and without anyone's phone number being exposed.
    CLIENT = "client", "Team + Client (relayed to WhatsApp)"


class EmploymentType(models.TextChoices):
    FULL_TIME = "full_time", "Full time"
    PART_TIME = "part_time", "Part time"
    FREELANCE = "freelance", "Freelancer / contractor"


class WorkMode(models.TextChoices):
    OFFICE = "office", "From the office"
    REMOTE = "remote", "Remote"
    HYBRID = "hybrid", "Hybrid"


#: A *day* is worked either at a desk or away from one. "Hybrid" describes the
#: contract, never a single day - which is why the roster carries the day's
#: mode and the profile only carries the default.
DAY_WORK_MODES = (
    (WorkMode.OFFICE, "From the office"),
    (WorkMode.REMOTE, "Remote"),
)


class ScheduleKind(models.TextChoices):
    FIXED = "fixed", "Fixed shift"
    FLEXIBLE = "flexible", "Flexible shift"
    CUSTOM = "custom", "Custom schedule"


class PunchKind(models.TextChoices):
    CHECK_IN = "check_in", "Check in"
    CHECK_OUT = "check_out", "Check out"
    BREAK_START = "break_start", "Break start"
    BREAK_END = "break_end", "Break end"


class OffSitePolicy(models.TextChoices):
    """What happens when a punch fails a check it was supposed to pass."""

    REVIEW = "review", "Record it and flag it for review"
    REJECT = "reject", "Refuse the punch"


# ---------------------------------------------------------------------------
# HR / recruitment choices
# ---------------------------------------------------------------------------

class EmploymentStatus(models.TextChoices):
    PROBATION = "probation", "On probation"
    ACTIVE = "active", "Confirmed"
    NOTICE = "notice", "Serving notice"
    LEFT = "left", "Left the company"


class VacancyStatus(models.TextChoices):
    DRAFT = "draft", "Draft"
    OPEN = "open", "Open"
    CLOSED = "closed", "Closed"


class CandidateStatus(models.TextChoices):
    """Section 13, in order. ``REJECTED`` can happen from any of them."""

    NEW = "new", "New"
    SCREENING = "screening", "HR screening"
    INTERVIEW = "interview", "Interview"
    TEST = "test", "Test"
    FINAL_REVIEW = "final_review", "Final review"
    OWNER_APPROVAL = "owner_approval", "Waiting for the owner"
    APPROVED = "approved", "Approved"
    HIRED = "hired", "Hired"
    REJECTED = "rejected", "Rejected"


#: Stages before a person has agreed to work here. Everything the system says
#: to a candidate in one of these is anonymous unless HR has said otherwise.
EARLY_CANDIDATE_STAGES = (
    CandidateStatus.NEW,
    CandidateStatus.SCREENING,
    CandidateStatus.INTERVIEW,
    CandidateStatus.TEST,
)


class CandidateSource(models.TextChoices):
    WHATSAPP = "whatsapp", "WhatsApp"
    EMAIL = "email", "Email"
    WEBSITE = "website", "Website"
    LINKEDIN = "linkedin", "LinkedIn"
    ADVERT = "advert", "Job advertisement"
    REFERRAL = "referral", "Referral"
    OTHER = "other", "Other"


class QuestionKind(models.TextChoices):
    TEXT = "text", "Text"
    CHOICE = "choice", "Multiple choice (one)"
    MULTI = "multi", "Multiple select"
    YES_NO = "yes_no", "Yes / No"
    NUMBER = "number", "Number"
    DATE = "date", "Date"
    FILE = "file", "File upload"
    DROPDOWN = "dropdown", "Dropdown"


#: Kinds the candidate answers by picking from a list the bot prints.
CHOICE_KINDS = (QuestionKind.CHOICE, QuestionKind.MULTI, QuestionKind.DROPDOWN)


class AnswerTarget(models.TextChoices):
    """Which profile field an answer fills in, if any.

    Without this the bot would need to know that "What is your name?" is the
    name question, which is exactly the hard-coding section 11 rules out. HR
    tags the question instead, and any wording works.
    """

    NONE = "", "Just an answer"
    FULL_NAME = "full_name", "Candidate name"
    EMAIL = "email", "E-mail"
    EXPERIENCE = "experience_years", "Years of experience"
    LANGUAGES = "languages", "Languages"
    SKILLS = "skills", "Skills"
    EXPECTED_SALARY = "expected_salary", "Expected salary"
    CV = "cv", "CV"


class InterviewKind(models.TextChoices):
    ONLINE = "online", "Online"
    OFFICE = "office", "At the office"


class ProbationStage(models.TextChoices):
    DAY_30 = "day_30", "30-day review"
    DAY_60 = "day_60", "60-day review"
    FINAL = "final", "Final probation review"


class ProbationOutcome(models.TextChoices):
    PENDING = "pending", "Not decided yet"
    CONFIRMED = "confirmed", "Confirmed"
    EXTENDED = "extended", "Probation extended"
    TERMINATED = "terminated", "Terminated"


class LeaveKind(models.TextChoices):
    ANNUAL = "annual", "Annual leave"
    EMERGENCY = "emergency", "Emergency leave"
    PERMISSION = "permission", "Permission (hours)"
    UNPAID = "unpaid", "Unpaid leave"
    OTHER = "other", "Other"


#: Which attendance status each kind writes onto the days it covers. A leave
#: nobody records as a day is a leave the payroll cannot see, so approving one
#: writes real `WorkDay` rows - that is the whole point of the integration.
LEAVE_DAY_STATUS = {
    LeaveKind.ANNUAL: "leave",
    LeaveKind.EMERGENCY: "leave",
    LeaveKind.UNPAID: "excused",
    LeaveKind.OTHER: "excused",
}


class LeaveStatus(models.TextChoices):
    PENDING = "pending", "Waiting"
    MANAGER_OK = "manager_ok", "Manager approved, waiting for HR"
    APPROVED = "approved", "Approved"
    REJECTED = "rejected", "Rejected"
    CANCELLED = "cancelled", "Withdrawn"


class ComplaintSeverity(models.TextChoices):
    LOW = "low", "Minor"
    MEDIUM = "medium", "Needs attention"
    HIGH = "high", "Serious"


class SessionState(models.TextChoices):
    PICKING = "picking", "Choosing a vacancy"
    ASKING = "asking", "Answering the questions"
    DONE = "done", "Handed to HR"
    ABANDONED = "abandoned", "Went quiet"


WEEKDAYS = (
    (0, "Monday"),
    (1, "Tuesday"),
    (2, "Wednesday"),
    (3, "Thursday"),
    (4, "Friday"),
    (5, "Saturday"),
    (6, "Sunday"),
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def span_minutes(start, end):
    """Minutes from ``start`` to ``end``, counting midnight as a crossing.

    A shift that ends at or before it starts - 17:00 to 01:00 - is one shift
    running into the next day, so it is 480 minutes and not a negative number.
    This single line is why the overnight shift works everywhere downstream.
    """
    minutes = (end.hour * 60 + end.minute) - (start.hour * 60 + start.minute)
    return minutes if minutes > 0 else minutes + 24 * 60


def next_code(model, field, prefix, width=4):
    """Return the next sequential human code, e.g. ``CL-0007``."""
    last = model.objects.order_by("-id").values_list(field, flat=True).first()
    number = 0
    if last:
        tail = str(last).rsplit("-", 1)[-1]
        if tail.isdigit():
            number = int(tail)
    candidate = number + 1
    while model.objects.filter(**{field: f"{prefix}-{candidate:0{width}d}"}).exists():
        candidate += 1
    return f"{prefix}-{candidate:0{width}d}"


def upload_inbound(instance, filename):
    return f"inbound/{timezone.now():%Y/%m}/{filename}"


def upload_chat(instance, filename):
    return f"chat/{timezone.now():%Y/%m}/{filename}"


def upload_outbound(instance, filename):
    return f"outbound/{timezone.now():%Y/%m}/{filename}"


def upload_cv(instance, filename):
    return f"recruitment/cv/{timezone.now():%Y/%m}/{filename}"


def upload_test(instance, filename):
    return f"recruitment/tests/{timezone.now():%Y/%m}/{filename}"


def upload_hr_doc(instance, filename):
    # Contracts and IDs. `media/` is git-ignored, which is where these belong.
    return f"hr/{timezone.now():%Y/%m}/{filename}"


# ---------------------------------------------------------------------------
# Users
# ---------------------------------------------------------------------------

class User(AbstractUser):
    """Single user model for the four Eagle roles."""

    role = models.CharField(max_length=20, choices=Role.choices, default=Role.TRANSLATOR)
    team_lead = models.ForeignKey(
        "self",
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="team_members",
        limit_choices_to={"role": Role.TEAM_LEAD},
        help_text="Only used for translators: which team leader they report to.",
    )
    display_name_ar = models.CharField(max_length=120, blank=True)
    phone = models.CharField(max_length=32, blank=True)
    languages = models.CharField(max_length=160, blank=True, help_text="e.g. EN, AR, FR")
    rating = models.DecimalField(max_digits=5, decimal_places=3, default=Decimal("5.000"))
    force_offline = models.BooleanField(default=False)
    last_seen = models.DateTimeField(null=True, blank=True)
    ui_lang = models.CharField(max_length=5, default="ar")
    ui_theme = models.CharField(max_length=10, default="dark")

    # -- workforce ---------------------------------------------------------
    # These three describe the contract, not any one day. The day's own shape
    # comes from the roster (`Shift`) and, when somebody moved a single day,
    # from `ScheduleOverride`.
    employment_type = models.CharField(
        max_length=12, choices=EmploymentType.choices, default=EmploymentType.FULL_TIME
    )
    work_mode = models.CharField(
        max_length=8, choices=WorkMode.choices, default=WorkMode.OFFICE,
        help_text="Hybrid means the roster decides each day.",
    )
    schedule_kind = models.CharField(
        max_length=10, choices=ScheduleKind.choices, default=ScheduleKind.FIXED
    )
    attendance_enabled = models.BooleanField(
        default=True, help_text="Turn off for somebody who does not clock in at all."
    )
    attendance_manager = models.BooleanField(
        default=False,
        help_text="May run the attendance board and correct other people's days (HR).",
    )

    # -- employee profile --------------------------------------------------
    # Section 18 asks for an "Employee Profile". It is these fields on the
    # person, not a second table: splitting somebody into a User *and* an
    # Employee is how the two drift apart and how a hire ends up with two
    # identities in the same system.
    employee_code = models.CharField(max_length=20, blank=True, db_index=True)
    job_title = models.CharField(max_length=120, blank=True)
    department = models.ForeignKey(
        "Department", null=True, blank=True, on_delete=models.SET_NULL,
        related_name="members",
    )
    joining_date = models.DateField(null=True, blank=True)
    employment_status = models.CharField(
        max_length=12, choices=EmploymentStatus.choices,
        default=EmploymentStatus.ACTIVE, db_index=True,
    )
    probation_start = models.DateField(null=True, blank=True)
    probation_end = models.DateField(null=True, blank=True)
    contract = models.FileField(upload_to=upload_hr_doc, blank=True, null=True)
    #: Optional. Nobody needs one: a person without a plan is priced by the
    #: company rules exactly as before this field existed.
    salary_plan = models.ForeignKey(
        "SalaryPlan", null=True, blank=True, on_delete=models.SET_NULL,
        related_name="members",
    )

    class Meta:
        ordering = ("role", "username")

    def save(self, *args, **kwargs):
        # `createsuperuser` cannot ask for a role, so it would land on the
        # default (translator) and show up in translator assignment lists.
        if self._state.adding and self.is_superuser and self.role == Role.TRANSLATOR:
            self.role = Role.ADMIN
        super().save(*args, **kwargs)

    def __str__(self):
        return self.get_full_name() or self.username

    # -- role helpers ------------------------------------------------------
    @property
    def is_admin_role(self):
        return self.role == Role.ADMIN or self.is_superuser

    @property
    def is_operation(self):
        return self.role == Role.OPERATION

    @property
    def is_team_lead(self):
        return self.role == Role.TEAM_LEAD

    @property
    def is_translator(self):
        return self.role == Role.TRANSLATOR

    @property
    def is_hr(self):
        return self.role == Role.HR

    @property
    def is_reviewer(self):
        return self.role == Role.REVIEWER

    @property
    def is_accounting(self):
        return self.role == Role.ACCOUNTING

    @property
    def can_recruit(self):
        """Run the hiring pipeline. The owner can always do everything."""
        return self.is_admin_role or self.is_hr

    @property
    def can_review_tests(self):
        """Mark a candidate's test. A team leader marks their own craft's."""
        return self.is_admin_role or self.is_reviewer or self.is_team_lead

    @property
    def can_approve_hiring(self):
        """Section 16: hiring is never automatic - this is the owner alone."""
        return self.is_admin_role

    @property
    def can_see_client_identity(self):
        """Only the admin ever sees the real client name / phone / email."""
        return self.is_admin_role

    @property
    def can_create_team_group(self):
        """Who may open an internal work group.

        A team leader opening one for a translator is the case this exists
        for. It reaches no client, so it is not gated by the client-group
        setting - but it is not everyone either: a translator is put into
        groups rather than making them. One place, easy to widen.
        """
        return self.is_team_lead or self.is_operation or self.is_admin_role

    @property
    def can_manage_attendance(self):
        """The HR role carries it; the flag lets anyone else be given it too."""
        return self.is_admin_role or self.is_hr or self.attendance_manager

    @property
    def is_hybrid(self):
        return self.work_mode == WorkMode.HYBRID

    @property
    def short_name(self):
        return self.get_full_name() or self.username

    @property
    def initials(self):
        source = (self.get_full_name() or self.username).split()
        return "".join(part[0] for part in source[:2]).upper() or "?"

    # -- availability ------------------------------------------------------
    def active_shifts(self):
        """Filtered in Python so ``prefetch_related('shifts')`` is honoured."""
        return [shift for shift in self.shifts.all() if shift.is_active]

    def shift_now(self):
        """Return the shift covering the current moment, if any."""
        now = timezone.localtime()
        today = now.weekday()
        yesterday = (today - 1) % 7
        for shift in self.active_shifts():
            if shift.covers(now.time(), today, yesterday):
                return shift
        return None

    #: How long after the last heartbeat someone still counts as present. The
    #: browser beats on every poll, but a background tab is throttled to about
    #: one timer a minute, so anything under two minutes would blink offline.
    PRESENCE_TIMEOUT = 130

    @property
    def seconds_since_seen(self):
        if not self.last_seen:
            return None
        return (timezone.now() - self.last_seen).total_seconds()

    @property
    def is_online(self):
        """Online means the site is open right now — nothing else.

        A shift used to be enough on its own, so someone rostered from 9 to 5
        showed as present all day whether or not they had ever opened Eagle.
        That made the whole column untrustworthy: the point of the dot is to
        say who can be given a task this minute.
        """
        if not self.is_active or self.force_offline:
            return False
        seen = self.seconds_since_seen
        return seen is not None and seen < self.PRESENCE_TIMEOUT

    @property
    def on_shift(self):
        """Rostered now — which is a different question from being present."""
        return bool(self.active_shifts()) and self.shift_now() is not None

    @property
    def presence(self):
        return "online" if self.is_online else "offline"

    # -- workload ----------------------------------------------------------
    def active_tasks(self):
        qs = Task.objects.filter(status__in=ACTIVE_TASK_STATUSES)
        if self.is_translator:
            return qs.filter(translator=self)
        if self.is_team_lead:
            return qs.filter(team_lead=self)
        return qs.none()

    @property
    def active_task_count(self):
        return self.active_tasks().count()

    @property
    def is_busy(self):
        return self.active_task_count > 0

    @property
    def stars(self):
        """Rating rounded to the nearest eighth, as a float for templates."""
        return float(self.rating)

    def apply_penalty(self, task, reason_en, reason_ar):
        settings_row = AppSettings.load()
        penalty = settings_row.penalty_value
        new_value = max(Decimal("0.000"), Decimal(self.rating) - penalty)
        self.rating = new_value
        self.save(update_fields=["rating"])
        RatingEvent.objects.create(
            user=self, task=task, delta=-penalty,
            reason_en=reason_en, reason_ar=reason_ar,
        )
        return new_value


class ShiftTemplate(models.Model):
    """A named shift the company runs - editable, and never hard-coded.

    The contract's three shifts are seeded once as data. HR can change their
    hours, retire them, or add a fourth, and nothing in the code has to move.
    A template that people are rostered on cannot be deleted (``PROTECT``);
    clearing ``is_active`` takes it out of the pickers instead.
    """

    name = models.CharField(max_length=60)
    name_ar = models.CharField(max_length=60, blank=True)
    start_time = models.TimeField()
    end_time = models.TimeField()
    break_minutes = models.PositiveSmallIntegerField(
        default=0, help_text="Unpaid break this shift grants. 0 uses the company default."
    )
    is_active = models.BooleanField(default=True)
    sort_order = models.PositiveSmallIntegerField(default=0)

    class Meta:
        ordering = ("sort_order", "start_time")

    def __str__(self):
        return f"{self.label} {self.start_time:%H:%M}-{self.end_time:%H:%M}"

    @property
    def label(self):
        return self.name_ar or self.name

    @property
    def crosses_midnight(self):
        """17:00 -> 01:00 is one shift, not two. Everything downstream cares."""
        return self.end_time <= self.start_time

    @property
    def minutes(self):
        return span_minutes(self.start_time, self.end_time)

    #: The contract's table, as data. Seeded once; edited from the panel after.
    DEFAULTS = (
        ("Shift 1", "الشيفت 1", time(9, 0), time(17, 0)),
        ("Shift 2", "الشيفت 2", time(12, 0), time(20, 0)),
        ("Shift 3", "الشيفت 3", time(17, 0), time(1, 0)),
    )

    @classmethod
    def seed_defaults(cls):
        if cls.objects.exists():
            return
        cls.objects.bulk_create([
            cls(name=name, name_ar=name_ar, start_time=start, end_time=end, sort_order=order)
            for order, (name, name_ar, start, end) in enumerate(cls.DEFAULTS, start=1)
        ])


class Shift(models.Model):
    """One person's roster for one weekday.

    A row means "this person works that day". No row means the day is off, so
    a part-timer simply has fewer rows - nothing anywhere assumes eight hours.
    The hours come either from a shift template (so editing the template moves
    everybody on it) or from times typed on the row itself, which is what a
    custom schedule uses.
    """

    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name="shifts")
    weekday = models.IntegerField(choices=WEEKDAYS)
    template = models.ForeignKey(
        ShiftTemplate, null=True, blank=True, on_delete=models.PROTECT, related_name="shifts"
    )
    start_time = models.TimeField(null=True, blank=True)
    end_time = models.TimeField(null=True, blank=True)
    work_mode = models.CharField(
        max_length=8, choices=DAY_WORK_MODES, blank=True,
        help_text="Blank follows the person's own work mode.",
    )
    required_minutes = models.PositiveSmallIntegerField(
        default=0, help_text="0 means the shift's own length.",
    )
    is_active = models.BooleanField(default=True)

    class Meta:
        ordering = ("weekday", "start_time")

    def __str__(self):
        start, end = self.start, self.end
        window = f"{start:%H:%M}-{end:%H:%M}" if start and end else "—"
        return f"{self.user} · {self.get_weekday_display()} {window}"

    # -- resolved hours ----------------------------------------------------
    @property
    def start(self):
        return self.template.start_time if self.template_id else self.start_time

    @property
    def end(self):
        return self.template.end_time if self.template_id else self.end_time

    @property
    def label(self):
        if self.template_id:
            return self.template.label
        start, end = self.start, self.end
        return f"{start:%H:%M}-{end:%H:%M}" if start and end else "—"

    @property
    def minutes(self):
        """What the day is *worth*, which a part-timer sets independently."""
        if self.required_minutes:
            return self.required_minutes
        start, end = self.start, self.end
        return span_minutes(start, end) if start and end else 0

    @property
    def crosses_midnight(self):
        start, end = self.start, self.end
        return bool(start and end) and end <= start

    def mode_for(self, user=None):
        """The day's work mode: the row's own, else the person's default."""
        if self.work_mode:
            return self.work_mode
        owner = user or self.user
        return WorkMode.OFFICE if owner.is_hybrid else owner.work_mode

    def covers(self, now_time, today, yesterday):
        start, end = self.start, self.end
        if not (start and end):
            return False
        if not self.crosses_midnight:
            return self.weekday == today and start <= now_time < end
        # Overnight shift: it belongs to `weekday` but spills into the next day.
        if self.weekday == today and now_time >= start:
            return True
        if self.weekday == yesterday and now_time < end:
            return True
        return False


# ---------------------------------------------------------------------------
# Clients
# ---------------------------------------------------------------------------

class Client(models.Model):
    code = models.CharField(max_length=20, unique=True, blank=True)
    name = models.CharField(max_length=160, blank=True)
    company = models.CharField(max_length=160, blank=True)
    phone = models.CharField(max_length=40, blank=True, db_index=True)
    email = models.EmailField(blank=True, db_index=True)
    country = models.CharField(max_length=80, blank=True)
    admin_notes = models.TextField(blank=True, help_text="Visible to the admin only.")
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ("code",)

    def save(self, *args, **kwargs):
        if not self.code:
            self.code = next_code(Client, "code", "CL")
        super().save(*args, **kwargs)

    def __str__(self):
        return self.code

    def label_for(self, user):
        """What a given role is allowed to see as the client's identity."""
        if user is not None and getattr(user, "can_see_client_identity", False):
            return f"{self.code} · {self.name or self.company or '—'}"
        return self.code

    # -- the WhatsApp 24-hour customer-service window ------------------------
    # WhatsApp only lets a business send a free-form message within 24h of the
    # client's own last message. After that only an approved template works,
    # so the chat UI has to say plainly whether the window is still open.

    @property
    def last_inbound_at(self):
        """The client's last *WhatsApp* message — the only one that opens it.

        Counting e-mail here would have the chat say the window is open when
        Meta will refuse the send: a client who writes an e-mail has not
        touched the WhatsApp clock at all.
        """
        last = (
            self.messages.filter(channel=Channel.WHATSAPP)
            .order_by("-received_at").first()
        )
        return last.received_at if last else None

    @property
    def reply_window_ends(self):
        started = self.last_inbound_at
        return started + timedelta(hours=24) if started else None

    @property
    def reply_window_open(self):
        ends = self.reply_window_ends
        return bool(ends and ends > timezone.now())

    @property
    def reply_window_minutes_left(self):
        ends = self.reply_window_ends
        if not ends:
            return 0
        return max(0, int((ends - timezone.now()).total_seconds() // 60))


class ClientRequirement(models.Model):
    class Kind(models.TextChoices):
        LIKE = "like", "Likes"
        DISLIKE = "dislike", "Dislikes"
        RULE = "rule", "Rule"

    client = models.ForeignKey(Client, on_delete=models.CASCADE, related_name="requirements")
    kind = models.CharField(max_length=10, choices=Kind.choices, default=Kind.RULE)
    text = models.TextField()
    author = models.ForeignKey(User, null=True, on_delete=models.SET_NULL, related_name="+")
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ("-created_at",)

    def __str__(self):
        return f"{self.client.code} · {self.get_kind_display()}"


# ---------------------------------------------------------------------------
# Inbound messages (WhatsApp / Email)
# ---------------------------------------------------------------------------

class InboundMessage(models.Model):
    client = models.ForeignKey(
        Client, null=True, blank=True, on_delete=models.SET_NULL, related_name="messages"
    )
    channel = models.CharField(max_length=12, choices=Channel.choices, default=Channel.WHATSAPP)
    external_id = models.CharField(max_length=190, blank=True, db_index=True)
    #: Raw phone number / email address. Never rendered for non-admin roles.
    sender_identity = models.CharField(max_length=190, blank=True)
    sender_display = models.CharField(max_length=190, blank=True)
    subject = models.CharField(max_length=250, blank=True)
    body = models.TextField(blank=True)
    received_at = models.DateTimeField(default=timezone.now)
    #: The WhatsApp id this message replies to, when the client quoted one.
    reply_to_external = models.CharField(max_length=190, blank=True)
    #: The e-mail conversation this letter belongs to — every reply in it
    #: shares the key, and /ops/inbox/ shows one row per key (``threads.py``).
    #: Blank for WhatsApp, which is a conversation already.
    thread_key = models.CharField(max_length=32, blank=True, db_index=True)
    #: Messages that talk about rates are hidden from the operation role.
    is_rate_blocked = models.BooleanField(default=False)
    blocked_keyword = models.CharField(max_length=60, blank=True)
    claimed_by = models.ForeignKey(
        User, null=True, blank=True, on_delete=models.SET_NULL, related_name="claimed_messages"
    )
    claimed_at = models.DateTimeField(null=True, blank=True)
    task = models.ForeignKey(
        "Task", null=True, blank=True, on_delete=models.SET_NULL, related_name="source_messages"
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ("-received_at",)
        indexes = [models.Index(fields=["is_rate_blocked", "-received_at"])]

    def __str__(self):
        return f"{self.get_channel_display()} · {self.client_code}"

    @property
    def client_code(self):
        return self.client.code if self.client_id else "UNKNOWN"

    @property
    def is_claimed(self):
        return self.claimed_by_id is not None

    @property
    def document_attachments(self):
        """The attachments that are files to work on, not voice notes.

        The two buttons under a letter — "received" and "convert to task" —
        both stand for work on a document the client sent, so they are drawn
        from this list rather than from every attachment. Iterating the
        prefetched ``attachments`` keeps it to the query the page already ran.
        """
        return [a for a in self.attachments.all() if not a.is_audio]

    def visible_to(self, user):
        if user.is_admin_role:
            return True
        if self.is_rate_blocked:
            return False
        return user.is_operation


class PlayableFile:
    """Shared behaviour for the two attachment models.

    Not a model: it only adds properties, so mixing it in costs no migration.
    Both sides of a conversation can carry a voice note, and both need to know
    whether the browser can play the file inline instead of offering a download.
    """

    @property
    def is_audio(self):
        from . import audio

        # getattr: ChatAttachment shares the behaviour without the columns.
        return audio.is_audio(
            getattr(self, "mime", ""), self.original_name or self.file.name
        )

    @property
    def pretty_duration(self):
        from . import audio

        seconds = getattr(self, "duration", 0)
        return audio.pretty_duration(seconds) if seconds else ""

    @property
    def pretty_size(self):
        value = float(self.size or 0)
        for unit in ("B", "KB", "MB", "GB"):
            if value < 1024 or unit == "GB":
                return f"{value:.0f} {unit}" if unit == "B" else f"{value:.1f} {unit}"
            value /= 1024
        return f"{value:.1f} GB"


class MessageAttachment(PlayableFile, models.Model):
    message = models.ForeignKey(
        InboundMessage, on_delete=models.CASCADE, related_name="attachments"
    )
    file = models.FileField(upload_to=upload_inbound)
    original_name = models.CharField(max_length=250, blank=True)
    size = models.BigIntegerField(default=0)
    #: Kept so the dashboard can decide between a player and a download link.
    mime = models.CharField(max_length=120, blank=True)
    #: True for a WhatsApp voice note (push-to-talk), false for an audio file.
    is_voice = models.BooleanField(default=False)
    duration = models.PositiveIntegerField(default=0, help_text="Seconds")
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return self.original_name or self.file.name


# ---------------------------------------------------------------------------
# Tasks
# ---------------------------------------------------------------------------

class Task(models.Model):
    code = models.CharField(max_length=20, unique=True, blank=True)
    title = models.CharField(max_length=200)
    client = models.ForeignKey(Client, on_delete=models.PROTECT, related_name="tasks")
    description = models.TextField(blank=True)
    source_lang = models.CharField(max_length=40, blank=True)
    target_lang = models.CharField(max_length=40, blank=True)
    #: The job's size. Payroll reads production from here and never from
    #: anything the translator types about themselves.
    word_count = models.PositiveIntegerField(default=0)
    #: Counted out of the files by ``wordcount.recount_task``. The source is
    #: what payroll uses - the client sent it, so the person whose bonus rides
    #: on it cannot inflate it. The translated side is kept beside it because
    #: the gap between the two is the signal worth looking at.
    source_words = models.PositiveIntegerField(default=0)
    translated_words = models.PositiveIntegerField(default=0)
    source_word_method = models.CharField(max_length=16, blank=True)
    translated_word_method = models.CharField(max_length=16, blank=True)
    word_count_state = models.CharField(
        max_length=16, choices=WordCountState.choices,
        default=WordCountState.EMPTY, db_index=True,
    )
    word_count_note = models.CharField(max_length=250, blank=True)
    is_difficult = models.BooleanField(
        default=False,
        help_text="Set by the project manager - exempts the day from the production floor.",
    )
    is_secondary_language = models.BooleanField(
        default=False, help_text="The translator worked outside their main language."
    )
    priority = models.CharField(max_length=10, choices=Priority.choices, default=Priority.NORMAL)
    status = models.CharField(
        max_length=24, choices=TaskStatus.choices, default=TaskStatus.NEW, db_index=True
    )

    #: The client files the operation ticked when they turned the message into
    #: this task. Empty means "everything the client sent" - which is what
    #: every task made before the picker existed means too, so no backfill.
    source_files = models.ManyToManyField(
        "MessageAttachment", blank=True, related_name="tasks",
        help_text="Client attachments chosen for this task. Empty = all of them.",
    )

    created_by = models.ForeignKey(
        User, null=True, on_delete=models.SET_NULL, related_name="created_tasks"
    )
    team_lead = models.ForeignKey(
        User, null=True, blank=True, on_delete=models.SET_NULL, related_name="lead_tasks"
    )
    translator = models.ForeignKey(
        User, null=True, blank=True, on_delete=models.SET_NULL, related_name="translator_tasks"
    )

    deadline = models.DateTimeField(null=True, blank=True)
    deadline_warned_at = models.DateTimeField(null=True, blank=True)
    deadline_missed_notified = models.BooleanField(default=False)

    #: The team leader's mark out of ten, set when they finish reviewing.
    #: Null means "not marked", which is not a zero - an unscored task must
    #: not drag an average down.
    review_score = models.PositiveSmallIntegerField(null=True, blank=True)
    review_note = models.CharField(max_length=250, blank=True)
    #: How many times this went back to the translator after review. The
    #: revision rate in section 20 is this, over the tasks they delivered.
    revision_count = models.PositiveSmallIntegerField(default=0)
    returned_at = models.DateTimeField(null=True, blank=True)

    lead_accepted_at = models.DateTimeField(null=True, blank=True)
    translator_accepted_at = models.DateTimeField(null=True, blank=True)
    translated_at = models.DateTimeField(null=True, blank=True)
    reviewed_at = models.DateTimeField(null=True, blank=True)
    delivered_at = models.DateTimeField(null=True, blank=True)

    #: The operation saying, by hand, that they have the reviewed job. Sending
    #: files to a client is the one step nobody can take back, so it waits for
    #: a person to claim it rather than following a status change on its own.
    #: Cleared when a task goes back for revision - the handover is over.
    handover_ack_at = models.DateTimeField(null=True, blank=True)
    handover_ack_by = models.ForeignKey(
        User, null=True, blank=True, on_delete=models.SET_NULL, related_name="+"
    )

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ("-created_at",)

    def save(self, *args, **kwargs):
        if not self.code:
            self.code = next_code(Task, "code", "TSK", width=5)
        super().save(*args, **kwargs)

    def __str__(self):
        return f"{self.code} · {self.title}"

    # -- state helpers -----------------------------------------------------
    @property
    def is_open(self):
        return self.status in ACTIVE_TASK_STATUSES

    @property
    def is_done(self):
        return self.status in (TaskStatus.DELIVERED, TaskStatus.CANCELLED)

    @property
    def pending_assignment(self):
        return self.assignments.filter(status=AssignmentStatus.PENDING).order_by("-id").first()

    @property
    def word_count_is_settled(self):
        """True when the number may walk into payroll without being asked."""
        return self.word_count_state in (WordCountState.AUTO, WordCountState.CONFIRMED)

    @property
    def word_count_gap(self):
        """How far the translation is from its source, as a percentage."""
        if not self.source_words or not self.translated_words:
            return None
        return abs(self.translated_words - self.source_words) / self.source_words * 100

    @property
    def production_date(self):
        """The day this job counts towards, in local time.

        The translator's work is done when the translation lands, so that is
        the stamp payroll uses. Review and delivery can slide into the next
        day - or the next month - without moving the words with them.
        """
        stamp = self.translated_at or self.delivered_at
        return timezone.localtime(stamp).date() if stamp else None

    def deadline_state(self):
        if not self.deadline:
            return "none"
        now = timezone.now()
        if self.status in (TaskStatus.DELIVERED, TaskStatus.CANCELLED):
            return "done"
        remaining = (self.deadline - now).total_seconds()
        if remaining < 0:
            return "late"
        if remaining <= AppSettings.load().deadline_warning_minutes * 60:
            return "soon"
        return "ok"

    @property
    def seconds_to_deadline(self):
        if not self.deadline:
            return None
        return int((self.deadline - timezone.now()).total_seconds())

    def participants(self):
        people = [self.created_by, self.team_lead, self.translator]
        return [p for p in people if p is not None]

    def client_label_for(self, user):
        return self.client.label_for(user)

    def can_view(self, user):
        if user.is_admin_role or user.is_operation:
            return True
        if user.is_team_lead:
            return self.team_lead_id == user.id
        if user.is_translator:
            return self.translator_id == user.id
        return False


class Assignment(models.Model):
    """A hand-off that must be confirmed inside the response window."""

    task = models.ForeignKey(Task, on_delete=models.CASCADE, related_name="assignments")
    assignee = models.ForeignKey(User, on_delete=models.CASCADE, related_name="assignments")
    assigned_by = models.ForeignKey(
        User, null=True, on_delete=models.SET_NULL, related_name="given_assignments"
    )
    target_role = models.CharField(max_length=20, choices=Role.choices)
    status = models.CharField(
        max_length=12, choices=AssignmentStatus.choices, default=AssignmentStatus.PENDING
    )
    assigned_at = models.DateTimeField(default=timezone.now)
    expires_at = models.DateTimeField()
    responded_at = models.DateTimeField(null=True, blank=True)
    penalty_applied = models.BooleanField(default=False)
    note = models.CharField(max_length=250, blank=True)
    #: Why it was refused. Required when a person declines, and written by the
    #: sweep when the window runs out - a sender who only learns "refused"
    #: cannot decide what to do next, which is the whole point of asking.
    reason = models.CharField(max_length=250, blank=True)
    #: When the assignee opened the files. Looking is not accepting: the two
    #: are recorded separately on purpose, so "they saw it and said nothing"
    #: is a fact rather than a guess.
    opened_at = models.DateTimeField(null=True, blank=True)
    #: The one-to-one chat this hand-off was posted into, so the files and the
    #: decision live in the same conversation the two of them already use.
    room = models.ForeignKey(
        "ChatRoom", null=True, blank=True, on_delete=models.SET_NULL,
        related_name="assignments",
    )

    class Meta:
        ordering = ("-assigned_at",)
        indexes = [models.Index(fields=["status", "expires_at"])]

    def save(self, *args, **kwargs):
        if not self.expires_at:
            window = AppSettings.load().response_window_seconds
            self.expires_at = (self.assigned_at or timezone.now()) + timedelta(seconds=window)
        super().save(*args, **kwargs)

    def __str__(self):
        return f"{self.task.code} → {self.assignee} ({self.status})"

    @property
    def seconds_left(self):
        return max(0, int((self.expires_at - timezone.now()).total_seconds()))

    @property
    def is_expired(self):
        return self.status == AssignmentStatus.PENDING and timezone.now() >= self.expires_at


class RatingEvent(models.Model):
    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name="rating_events")
    task = models.ForeignKey(Task, null=True, blank=True, on_delete=models.SET_NULL, related_name="+")
    delta = models.DecimalField(max_digits=5, decimal_places=3)
    reason_en = models.CharField(max_length=200, blank=True)
    reason_ar = models.CharField(max_length=200, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ("-created_at",)

    def __str__(self):
        return f"{self.user} {self.delta}"


# ---------------------------------------------------------------------------
# In-system chat
# ---------------------------------------------------------------------------

class ChatRoom(models.Model):
    #: Internal rooms always hang off a task. A client group can stand on its
    #: own — opened from the chats page for a client with no task in flight —
    #: so both sides are optional and at least one is always set.
    task = models.ForeignKey(
        Task, null=True, blank=True, on_delete=models.CASCADE, related_name="rooms"
    )
    #: Who the room relays to. Mirrored from the task for task-bound rooms so
    #: every client room can be found by client in one query.
    client = models.ForeignKey(
        Client, null=True, blank=True, on_delete=models.CASCADE, related_name="rooms"
    )
    kind = models.CharField(max_length=12, choices=RoomKind.choices)
    #: What the group is called in the chats list. Task rooms leave it empty.
    title = models.CharField(max_length=120, blank=True)
    created_by = models.ForeignKey(
        User, null=True, blank=True, on_delete=models.SET_NULL, related_name="+"
    )
    members = models.ManyToManyField(User, related_name="chat_rooms", blank=True)
    #: Staff chats only: "<smaller id>-<larger id>". Unique, so the same two
    #: people can never end up with two conversations - whoever opens it
    #: second lands in the one that already exists. NULL everywhere else,
    #: which a unique index allows as many times as it likes.
    pair_key = models.CharField(
        max_length=32, blank=True, null=True, unique=True,
        help_text="Staff chats only: the two user ids, smallest first.",
    )
    #: Out of the lists, still readable. Archiving rather than deleting is the
    #: rule here: these rooms hold real conversations with real clients, and a
    #: row removed to tidy a list cannot be got back.
    is_archived = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ("id",)
        constraints = [
            # One room of each kind per task. Standalone groups have no task,
            # so the rule only applies where there is one.
            models.UniqueConstraint(
                fields=["task", "kind"], name="uniq_room_per_task_kind",
                condition=models.Q(task__isnull=False),
            )
        ]

    def __str__(self):
        return f"{self.display_title} · {self.get_kind_display()}"

    @property
    def relay_client(self):
        """The client this room talks to, whichever way it was created."""
        if self.client_id:
            return self.client
        return self.task.client if self.task_id else None

    @property
    def is_group(self):
        """A standalone client group, as opposed to a task's client room."""
        return self.kind == RoomKind.CLIENT and self.task_id is None

    @property
    def display_title(self):
        if self.title:
            return self.title
        if self.task_id:
            return self.task.code
        client = self.relay_client
        return client.code if client else "—"

    @property
    def is_staff_chat(self):
        return self.kind == RoomKind.STAFF

    @property
    def is_team_group(self):
        """An internal work group: a name, some people, and no client."""
        return self.kind == RoomKind.TEAM

    @property
    def reaches_client(self):
        """True when what is typed here ends up on a client's phone.

        The banner at the top of the room is drawn from this, and so is the
        decision to relay. Anything that is not a client room stays inside.
        """
        return self.kind == RoomKind.CLIENT

    def other_member(self, viewer):
        """The person on the far side of a one-to-one staff chat."""
        if self.kind != RoomKind.STAFF or viewer is None:
            return None
        return self.members.exclude(pk=viewer.pk).first()

    def title_for(self, viewer):
        """What this room is called on one particular screen.

        A staff chat has no title of its own: it is called after whoever is
        on the other end, so the same room reads differently to each of the
        two people in it.
        """
        if self.kind == RoomKind.STAFF:
            person = self.other_member(viewer)
            return person.short_name if person else "—"
        return self.display_title

    def can_access(self, user):
        # A staff chat is the two people in it and nobody else - not even the
        # admin, who can open every other room. A private line a third person
        # reads silently is not a private line, and nothing in the product
        # asks for one. Change this only on purpose.
        if self.kind == RoomKind.STAFF:
            return self.members.filter(pk=user.pk).exists()
        if user.is_admin_role:
            return True
        return self.members.filter(pk=user.pk).exists()


class ChatMessage(models.Model):
    room = models.ForeignKey(ChatRoom, on_delete=models.CASCADE, related_name="messages")
    #: Which task this message is work on, when it is work on one.
    #:
    #: A task used to own a room, so "which task is this file for" was the
    #: same question as "which room is it in". The work happens in the chat
    #: between two people now, and that chat outlives any one task - so the
    #: link has to be on the message itself. Null means ordinary talk.
    task = models.ForeignKey(
        "Task", null=True, blank=True, on_delete=models.SET_NULL,
        related_name="chat_messages", db_index=True,
    )
    sender = models.ForeignKey(
        User, null=True, blank=True, on_delete=models.SET_NULL, related_name="chat_messages"
    )
    body = models.TextField(blank=True)
    is_system = models.BooleanField(default=False)
    system_key = models.CharField(max_length=60, blank=True)

    # -- relay bookkeeping (only used by a RoomKind.CLIENT room) -------------
    #: "" for an ordinary in-system message, else "sent" / "failed".
    relay_status = models.CharField(max_length=10, blank=True)
    relay_error = models.TextField(blank=True)
    #: Set when this row mirrors something the client sent us on WhatsApp.
    #: The files stay on the InboundMessage — nothing is copied twice.
    inbound = models.ForeignKey(
        InboundMessage, null=True, blank=True, on_delete=models.SET_NULL,
        related_name="mirrors",
    )
    #: WhatsApp's own id for the relayed copy of this message. Kept so a reply
    #: to it can quote it on the client's phone, not only in our own UI.
    relay_wamid = models.CharField(max_length=190, blank=True)
    reply_to = models.ForeignKey(
        "self", null=True, blank=True, on_delete=models.SET_NULL,
        related_name="replies",
    )

    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ("id",)

    def __str__(self):
        return f"#{self.pk} {self.room_id}"

    @property
    def from_client(self):
        return self.inbound_id is not None

    @property
    def relay_files(self):
        """Attachments to show — the client's own when this mirrors an inbound.

        Where this is internal work on a task, the operation may have ticked
        only some of the client's files when they made it; whoever is working
        should then see exactly those. The client room is deliberately left
        alone: it is the record of what the client actually sent, and hiding
        half of it there would make the conversation lie.

        The test is the room's kind, not a particular kind of room. It used to
        read ``== GROUP`` because a task owned a group; the work moved into
        the one-to-one chats, and a rule written around the old room would
        have gone quietly false - with the client's other files travelling to
        a translator who was never meant to see them.
        """
        if not self.inbound_id:
            return self.attachments.all()

        files = self.inbound.attachments.all()
        task = self.task or (self.room.task if self.room_id else None)
        internal = self.room_id and self.room.kind != RoomKind.CLIENT
        if task and internal and task.source_files.exists():
            files = files.filter(tasks=task)
        return files


class ChatAttachment(PlayableFile, models.Model):
    message = models.ForeignKey(ChatMessage, on_delete=models.CASCADE, related_name="attachments")
    file = models.FileField(upload_to=upload_chat)
    original_name = models.CharField(max_length=250, blank=True)
    size = models.BigIntegerField(default=0)

    def __str__(self):
        return self.original_name or self.file.name


# ---------------------------------------------------------------------------
# Notifications
# ---------------------------------------------------------------------------

class Notification(models.Model):
    class Level(models.TextChoices):
        INFO = "info", "Info"
        SUCCESS = "success", "Success"
        WARNING = "warning", "Warning"
        DANGER = "danger", "Danger"

    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name="notifications")
    level = models.CharField(max_length=10, choices=Level.choices, default=Level.INFO)
    title_ar = models.CharField(max_length=200)
    title_en = models.CharField(max_length=200)
    body_ar = models.CharField(max_length=400, blank=True)
    body_en = models.CharField(max_length=400, blank=True)
    url = models.CharField(max_length=250, blank=True)
    sound = models.BooleanField(default=False)
    is_read = models.BooleanField(default=False)
    task = models.ForeignKey(Task, null=True, blank=True, on_delete=models.CASCADE, related_name="+")
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ("-created_at",)
        indexes = [models.Index(fields=["user", "is_read", "-created_at"])]

    def __str__(self):
        return self.title_en


# ---------------------------------------------------------------------------
# AI review
# ---------------------------------------------------------------------------

class AICheckResult(models.Model):
    class Status(models.TextChoices):
        #: Written before the model is called, so a page opened while the
        #: check is in flight says so, and a worker that dies mid-call leaves
        #: a row behind instead of silence.
        RUNNING = "running", "Running"
        CLEAN = "clean", "No issues"
        ISSUES = "issues", "Issues found"
        ERROR = "error", "Error"

    task = models.ForeignKey(Task, on_delete=models.CASCADE, related_name="ai_checks")
    #: Null means the check ran by itself when the translator handed the job
    #: over - nobody asked for it.
    requested_by = models.ForeignKey(User, null=True, on_delete=models.SET_NULL, related_name="+")
    status = models.CharField(max_length=10, choices=Status.choices, default=Status.CLEAN)
    summary = models.TextField(blank=True)
    #: [{"location": "...", "issue": "...", "severity": "..."}]
    issues = models.JSONField(default=list, blank=True)
    error_message = models.TextField(blank=True)
    model_used = models.CharField(max_length=80, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ("-created_at",)

    def __str__(self):
        return f"{self.task.code} · {self.status}"

    @property
    def issue_count(self):
        return len(self.issues or [])


# ---------------------------------------------------------------------------
# Runtime settings (single row, editable from the admin panel)
# ---------------------------------------------------------------------------

class AppSettings(models.Model):
    singleton = models.PositiveSmallIntegerField(primary_key=True, default=1, editable=False)

    ai_check_enabled = models.BooleanField(default=False)
    claude_api_key = models.CharField(max_length=250, blank=True)
    claude_model = models.CharField(max_length=80, default="claude-sonnet-4-5")

    response_window_seconds = models.PositiveIntegerField(default=60)
    deadline_warning_minutes = models.PositiveIntegerField(default=15)
    penalty_value = models.DecimalField(max_digits=5, decimal_places=3, default=Decimal("0.125"))
    max_rating = models.DecimalField(max_digits=5, decimal_places=3, default=Decimal("5.000"))

    rate_keywords = models.TextField(
        default="rate,rates,rating,ratings,ريت,الريت,سعر,الاسعار",
        help_text="Comma separated. A message containing any of these is hidden from Operation.",
    )

    whatsapp_verify_token = models.CharField(max_length=120, blank=True)
    whatsapp_access_token = models.CharField(max_length=400, blank=True)
    whatsapp_phone_number_id = models.CharField(max_length=60, blank=True)
    whatsapp_app_secret = models.CharField(
        max_length=200, blank=True,
        help_text="Meta App Secret — used to verify the X-Hub-Signature-256 header.",
    )
    whatsapp_api_version = models.CharField(max_length=10, default="v23.0")
    webhook_shared_secret = models.CharField(max_length=120, blank=True)

    #: The recruitment line. A second number on the same WhatsApp business
    #: account, so the same token and the same webhook serve both - what tells
    #: them apart is which phone number ID the event arrived for. Leave it
    #: blank and nothing changes: every message still goes to the client inbox.
    recruit_phone_number_id = models.CharField(
        max_length=60, blank=True,
        help_text="Phone number ID of the dedicated recruitment line.",
    )
    recruit_number_display = models.CharField(
        max_length=32, blank=True, help_text="Shown on the HR screens only."
    )

    imap_host = models.CharField(max_length=120, blank=True)
    imap_port = models.PositiveIntegerField(default=993)
    imap_user = models.CharField(max_length=190, blank=True)
    imap_password = models.CharField(max_length=250, blank=True)
    imap_folder = models.CharField(max_length=60, default="INBOX")

    #: Last time the mailbox was actually polled, and how it went. Without
    #: these the mail page can only say "IMAP is filled in", which is not the
    #: same thing as "mail is arriving" — the difference is the whole point.
    mail_last_fetch_at = models.DateTimeField(null=True, blank=True)
    mail_last_count = models.PositiveIntegerField(default=0)
    mail_last_error = models.CharField(max_length=300, blank=True)

    smtp_host = models.CharField(
        max_length=120, blank=True,
        help_text="Leave blank to derive it from the IMAP host (imap. -> smtp.).",
    )
    smtp_port = models.PositiveIntegerField(default=587)
    smtp_user = models.CharField(max_length=190, blank=True,
                                 help_text="Blank = reuse the IMAP user.")
    smtp_password = models.CharField(max_length=250, blank=True,
                                     help_text="Blank = reuse the IMAP password.")
    smtp_from = models.CharField(max_length=190, blank=True)
    smtp_use_tls = models.BooleanField(default=True)

    #: Which roles may open a client group. Comma-separated role values; the
    #: admin is always allowed, so nobody can lock themselves out of it.
    group_creator_roles = models.CharField(
        max_length=120, default="admin,operation",
        help_text="Roles allowed to create a client group, comma-separated.",
    )

    simulation_enabled = models.BooleanField(default=True)
    poll_ms = models.PositiveIntegerField(default=3000)

    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = "App settings"
        verbose_name_plural = "App settings"

    def __str__(self):
        return "Eagle settings"

    def save(self, *args, **kwargs):
        self.singleton = 1
        super().save(*args, **kwargs)
        AppSettings._cached = None

    _cached = None

    @classmethod
    def load(cls):
        defaults = getattr(dj_settings, "EAGLE", {})
        obj, _ = cls.objects.get_or_create(
            singleton=1,
            defaults={
                "response_window_seconds": defaults.get("RESPONSE_WINDOW_SECONDS", 60),
                "deadline_warning_minutes": defaults.get("DEADLINE_WARNING_MINUTES", 15),
                "penalty_value": Decimal(str(defaults.get("PENALTY", "0.125"))),
                "max_rating": Decimal(str(defaults.get("MAX_RATING", "5.000"))),
                "rate_keywords": defaults.get("RATE_KEYWORDS", "rate,rating,ريت"),
                "poll_ms": defaults.get("POLL_MS", 3000),
            },
        )
        return obj

    @property
    def keyword_list(self):
        return [k.strip().lower() for k in (self.rate_keywords or "").split(",") if k.strip()]

    @property
    def group_roles(self):
        return [r.strip() for r in (self.group_creator_roles or "").split(",") if r.strip()]

    def can_create_group(self, user):
        """A group opens a line to a real client, so this is gated by role."""
        if user is None or not getattr(user, "is_authenticated", False):
            return False
        # The admin is always allowed: the setting lives in the admin panel and
        # locking the admin out of it would be a one-way door.
        if user.is_admin_role:
            return True
        return user.role in self.group_roles


class OutboundMessage(models.Model):
    """Anything we send back to the client — a task delivery or a chat reply."""

    class Status(models.TextChoices):
        SENT = "sent", "Sent"
        FAILED = "failed", "Failed"
        SKIPPED = "skipped", "Closed without sending"

    class Kind(models.TextChoices):
        DELIVERY = "delivery", "Task delivery"
        CHAT = "chat", "Chat reply"

    #: A chat reply belongs to a client, not to a task, so this is optional.
    task = models.ForeignKey(
        Task, null=True, blank=True, on_delete=models.CASCADE, related_name="deliveries"
    )
    kind = models.CharField(max_length=10, choices=Kind.choices, default=Kind.DELIVERY)
    client = models.ForeignKey(Client, on_delete=models.CASCADE, related_name="deliveries")
    channel = models.CharField(max_length=12, choices=Channel.choices, blank=True)
    #: The client's phone/e-mail. Only the admin ever sees it.
    to_identity = models.CharField(max_length=190, blank=True)
    body = models.TextField(blank=True)
    #: [{"name": "...", "status": "sent", "error": ""}]
    files = models.JSONField(default=list, blank=True)
    status = models.CharField(max_length=10, choices=Status.choices, default=Status.SENT)
    error_message = models.TextField(blank=True)
    provider_id = models.CharField(max_length=190, blank=True)
    #: Quoting a message, WhatsApp-style: the id we replied to plus a snippet
    #: of it, so the thread can show the quote without a second lookup.
    reply_to_wamid = models.CharField(max_length=190, blank=True)
    reply_preview = models.CharField(max_length=160, blank=True)
    #: E-mail only: the subject it went out with, and the mail conversation it
    #: answers (``InboundMessage.thread_key``) — which is how a reply written on
    #: /ops/inbox/thread/ shows up inside that conversation. For e-mail,
    #: ``provider_id`` holds our Message-ID, so the client's answer to it finds
    #: its way back to the same conversation.
    subject = models.CharField(max_length=250, blank=True)
    thread_key = models.CharField(max_length=32, blank=True, db_index=True)
    created_by = models.ForeignKey(User, null=True, on_delete=models.SET_NULL, related_name="+")
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ("-created_at",)

    def __str__(self):
        source = self.task.code if self.task_id else self.get_kind_display()
        return f"{source} → {self.client.code} ({self.status})"

    @property
    def file_count(self):
        return len(self.files or [])


class OutboundAttachment(PlayableFile, models.Model):
    """A real file the operation sent to the client from the chat."""

    message = models.ForeignKey(
        OutboundMessage, on_delete=models.CASCADE, related_name="uploads"
    )
    file = models.FileField(upload_to=upload_outbound)
    original_name = models.CharField(max_length=250, blank=True)
    size = models.BigIntegerField(default=0)
    #: Stored after conversion, so this is the format the client received.
    mime = models.CharField(max_length=120, blank=True)
    is_voice = models.BooleanField(default=False)
    duration = models.PositiveIntegerField(default=0, help_text="Seconds")
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return self.original_name or self.file.name


class AuditLog(models.Model):
    actor = models.ForeignKey(User, null=True, on_delete=models.SET_NULL, related_name="+")
    action = models.CharField(max_length=80)
    target = models.CharField(max_length=160, blank=True)
    detail = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ("-created_at",)

    def __str__(self):
        return f"{self.action} · {self.target}"


# ---------------------------------------------------------------------------
# Accounts - translator payroll
#
# The contract is turned into data, not code: every threshold, tier and money
# value below lives in `PayrollSettings` or `ProductionTier` so the admin can
# change the rules from the panel without a deploy. Nothing that costs someone
# money is applied automatically - a deduction becomes a `Violation` that a
# manager has to approve first.
# ---------------------------------------------------------------------------

class TierScale(models.TextChoices):
    PRIMARY = "primary", "Primary language"
    SECONDARY = "secondary", "Secondary language"


class DayStatus(models.TextChoices):
    PRESENT = "present", "Present"
    LEAVE = "leave", "Paid leave"
    EXCUSED = "excused", "Excused absence"
    UNEXCUSED = "unexcused", "Unexcused absence"
    WEEKLY_OFF = "weekly_off", "Weekly off"
    HOLIDAY = "holiday", "Public holiday"


#: Days the translator was expected at a desk. Everything else is either a day
#: off by design or an absence the payroll has to price.
WORKING_DAY_STATUSES = (DayStatus.PRESENT,)

#: Days that eat from the monthly leave balance.
LEAVE_STATUSES = (DayStatus.LEAVE, DayStatus.EXCUSED)


class ViolationKind(models.TextChoices):
    DISCIPLINE = "discipline", "Internal rules"
    QUALITY = "quality", "Translation error"
    LOW_OUTPUT = "low_output", "Low productivity"
    UNEXCUSED = "unexcused", "Absence without permission"
    EXTRA_LEAVE = "extra_leave", "Leave beyond the balance"
    TARGET_MISS = "target_miss", "Monthly target missed"
    MANUAL = "manual", "Manual adjustment"


class ApprovalStatus(models.TextChoices):
    PENDING = "pending", "Waiting for approval"
    APPROVED = "approved", "Approved"
    REJECTED = "rejected", "Rejected"


class PeriodStatus(models.TextChoices):
    DRAFT = "draft", "Draft"
    APPROVED = "approved", "Approved"
    LOCKED = "locked", "Locked"


class PayrollSettings(models.Model):
    """Every number the payroll engine reads. One row, edited from the panel."""

    singleton = models.PositiveSmallIntegerField(primary_key=True, default=1, editable=False)

    daily_hours = models.PositiveSmallIntegerField(default=8)

    #: A calendar month minus the four weekly days off. 26 x 3,000 = 78,000,
    #: which is exactly the monthly target below - the two numbers have to
    #: keep agreeing or the target becomes unreachable by construction.
    working_days_per_month = models.PositiveSmallIntegerField(default=26)
    monthly_leave_allowance = models.PositiveSmallIntegerField(default=4)

    daily_target_words = models.PositiveIntegerField(default=3000)
    secondary_daily_target_words = models.PositiveIntegerField(default=1500)
    monthly_target_words = models.PositiveIntegerField(default=78000)
    monthly_alert_words = models.PositiveIntegerField(
        default=75000, help_text="Below this the admin is warned for the month."
    )

    #: Deductions, in days of pay. None of them is applied without approval.
    extra_leave_penalty_days = models.DecimalField(
        max_digits=5, decimal_places=2, default=Decimal("1.25"),
        help_text="Per leave day beyond the monthly allowance.",
    )
    unexcused_penalty_days = models.DecimalField(
        max_digits=5, decimal_places=2, default=Decimal("2.00")
    )
    quality_penalty_days = models.DecimalField(
        max_digits=5, decimal_places=2, default=Decimal("2.00")
    )
    low_output_penalty_days = models.DecimalField(
        max_digits=5, decimal_places=2, default=Decimal("0.25")
    )
    unexcused_escalation_count = models.PositiveSmallIntegerField(
        default=3, help_text="The n-th absence without permission escalates to the owner."
    )

    #: Money values.
    target_miss_penalty = models.DecimalField(
        max_digits=9, decimal_places=2, default=Decimal("250.00")
    )
    discipline_bonus = models.DecimalField(
        max_digits=9, decimal_places=2, default=Decimal("250.00")
    )
    target_bonus = models.DecimalField(
        max_digits=9, decimal_places=2, default=Decimal("250.00")
    )

    #: How far a translation may sit from its source before the count stops
    #: being applied on its own. Arabic runs shorter than English for the same
    #: content, so a band this wide is normal; well outside it is not.
    word_count_gap_percent = models.PositiveSmallIntegerField(
        default=40,
        help_text="Above this gap between source and translation, a person confirms the count.",
    )

    #: The two bonuses are computed by the system but paid only once approved.
    bonuses_need_approval = models.BooleanField(default=True)

    # -- attendance --------------------------------------------------------
    # Section 7 of the spec is explicit that none of this may be hard-coded,
    # so every threshold below is a column HR edits from /accounts/rules/.

    #: Arrive inside the grace window and the day is simply Present. Step past
    #: it and the *whole* delay counts, not the part beyond the window - the
    #: contract's own example: 09:06 is Present, 09:14 is 14 minutes late.
    grace_minutes = models.PositiveSmallIntegerField(default=10)
    early_leave_grace_minutes = models.PositiveSmallIntegerField(default=10)

    #: Break policy. A shift template may grant its own allowance instead.
    break_minutes_allowed = models.PositiveSmallIntegerField(default=60)
    break_counts_as_work = models.BooleanField(
        default=False, help_text="Off: hours = out - in - break, which is the contract.",
    )

    #: How far from an office a punch still counts as "at the office". Phone
    #: GPS is routinely 50-100 m out, so a tight radius punishes accuracy, not
    #: absence.
    geofence_radius_m = models.PositiveIntegerField(default=200)
    off_site_policy = models.CharField(
        max_length=8, choices=OffSitePolicy.choices, default=OffSitePolicy.REVIEW
    )
    checkout_needs_location = models.BooleanField(
        default=False, help_text="Section 14: location is read at the punch, never between them.",
    )
    unknown_device_policy = models.CharField(
        max_length=8, choices=OffSitePolicy.choices, default=OffSitePolicy.REVIEW
    )
    device_check_enabled = models.BooleanField(default=True)

    #: Overtime. Priced per hour; blank rate falls back to the day's own value
    #: divided by the contractual daily hours.
    overtime_enabled = models.BooleanField(default=True)
    overtime_min_minutes = models.PositiveSmallIntegerField(
        default=30, help_text="Below this, staying a little late is not overtime.",
    )
    overtime_hourly_rate = models.DecimalField(
        max_digits=9, decimal_places=2, default=Decimal("0.00"),
        help_text="0 derives the rate from the salary: day value / daily hours.",
    )
    overtime_multiplier = models.DecimalField(max_digits=4, decimal_places=2, default=Decimal("1.00"))
    overtime_needs_approval = models.BooleanField(default=True)

    #: Alerts (section 10). Minutes after the scheduled edge before the nudge.
    missing_checkin_after_minutes = models.PositiveSmallIntegerField(default=30)
    missing_checkout_after_minutes = models.PositiveSmallIntegerField(default=60)
    short_hours_alert_minutes = models.PositiveSmallIntegerField(
        default=60, help_text="Missing this much of the scheduled day raises an alert.",
    )

    #: Leave (section 22). The approval chain is a setting because the owner
    #: asked for it to be: off, HR alone decides; on, the team leader has to
    #: agree first. Nobody is hard-coded into the chain.
    leave_needs_manager = models.BooleanField(
        default=False, help_text="Require the team leader's approval before HR sees a leave request.",
    )
    permission_max_minutes = models.PositiveSmallIntegerField(
        default=240, help_text="Longest single permission, in minutes.",
    )

    #: Performance (section 20). The weighted mean is taken over the indicators
    #: that actually have data, so these are ratios, not a total that must
    #: reach a hundred. Setting one to zero drops that indicator entirely.
    weight_productivity = models.PositiveSmallIntegerField(default=40)
    weight_quality = models.PositiveSmallIntegerField(default=30)
    weight_deadline = models.PositiveSmallIntegerField(default=20)
    weight_attendance = models.PositiveSmallIntegerField(default=10)

    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = "Payroll settings"
        verbose_name_plural = "Payroll settings"

    def __str__(self):
        return "Payroll rules"

    def save(self, *args, **kwargs):
        self.singleton = 1
        super().save(*args, **kwargs)
        PayrollSettings._cached = None

    _cached = None

    @classmethod
    def load(cls):
        obj, created = cls.objects.get_or_create(singleton=1)
        if created:
            ProductionTier.seed_defaults()
            ShiftTemplate.seed_defaults()
        return obj

    def target_for(self, secondary=False):
        return self.secondary_daily_target_words if secondary else self.daily_target_words

    def break_allowance(self, shift=None):
        """A shift's own allowance wins; otherwise the company default."""
        template = getattr(shift, "template", None)
        if template is not None and template.break_minutes:
            return template.break_minutes
        return self.break_minutes_allowed

    def overtime_rate(self, day_value):
        """Price of one overtime hour for somebody on ``day_value`` a day."""
        if self.overtime_hourly_rate:
            base = Decimal(self.overtime_hourly_rate)
        else:
            hours = Decimal(self.daily_hours or 8)
            base = Decimal(day_value) / hours
        return base * Decimal(self.overtime_multiplier)


class ProductionTier(models.Model):
    """One band of the daily production bonus.

    The band is open on the left and closed on the right: a day pays this tier
    when ``min_words < words <= max_words``. That is what makes the first tier
    start *above* the daily target - hitting 3,000 exactly is the job, not a
    bonus; 3,001 upwards is the extra the contract pays for.
    """

    scale = models.CharField(max_length=12, choices=TierScale.choices, default=TierScale.PRIMARY)
    min_words = models.PositiveIntegerField(help_text="Exclusive lower edge.")
    max_words = models.PositiveIntegerField(
        null=True, blank=True, help_text="Inclusive upper edge. Blank = open ended."
    )
    bonus = models.DecimalField(max_digits=9, decimal_places=2)

    class Meta:
        ordering = ("scale", "min_words")
        unique_together = (("scale", "min_words"),)

    def __str__(self):
        ceiling = self.max_words or "+"
        return f"{self.get_scale_display()} {self.min_words}-{ceiling} = {self.bonus}"

    def covers(self, words):
        if words <= self.min_words:
            return False
        return self.max_words is None or words <= self.max_words

    DEFAULTS = {
        TierScale.PRIMARY: (
            (3000, 3800, "25"),
            (3800, 4600, "35"),
            (4600, 5900, "45"),
            (5900, None, "60"),
        ),
        TierScale.SECONDARY: (
            (1500, 2000, "25"),
            (2000, 2500, "35"),
            (2500, 3000, "45"),
            (3000, 3500, "55"),
            (3500, 4000, "65"),
            (4000, 4500, "75"),
            (4500, 5000, "85"),
            (5000, None, "95"),
        ),
    }

    @classmethod
    def seed_defaults(cls):
        """Write the contract's two tables once, if the table is empty."""
        if cls.objects.exists():
            return
        rows = []
        for scale, bands in cls.DEFAULTS.items():
            for low, high, bonus in bands:
                rows.append(cls(scale=scale, min_words=low, max_words=high, bonus=Decimal(bonus)))
        cls.objects.bulk_create(rows)

    @classmethod
    def bonus_for(cls, words, secondary=False, tiers=None):
        scale = TierScale.SECONDARY if secondary else TierScale.PRIMARY
        pool = tiers if tiers is not None else cls.objects.filter(scale=scale)
        for tier in sorted(pool, key=lambda t: t.min_words):
            if tier.scale == scale and tier.covers(words):
                return Decimal(tier.bonus)
        return Decimal("0.00")


class SalaryRecord(models.Model):
    """Salary history. Raising a salary never rewrites a month already paid."""

    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name="salary_records")
    amount = models.DecimalField(max_digits=10, decimal_places=2)
    effective_from = models.DateField()
    note = models.CharField(max_length=200, blank=True)
    created_by = models.ForeignKey(User, null=True, on_delete=models.SET_NULL, related_name="+")
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ("-effective_from", "-id")

    def __str__(self):
        return f"{self.user} {self.amount} from {self.effective_from}"

    @classmethod
    def amount_on(cls, user, on_date):
        """The salary in force on a date - the basis for recomputing old months."""
        row = cls.objects.filter(user=user, effective_from__lte=on_date).first()
        return Decimal(row.amount) if row else Decimal("0.00")


class WorkDay(models.Model):
    """One translator, one date: attendance plus what that day produced.

    ``words`` is never typed in by the translator. It is refreshed from the
    tasks actually delivered that day (see ``payroll.words_on``), so the
    payroll and the job log can never tell two different stories.
    """

    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name="work_days")
    date = models.DateField(db_index=True)
    status = models.CharField(
        max_length=12, choices=DayStatus.choices, default=DayStatus.PRESENT, db_index=True
    )

    check_in = models.DateTimeField(null=True, blank=True)
    check_out = models.DateTimeField(null=True, blank=True)
    late_minutes = models.PositiveIntegerField(default=0)
    early_leave_minutes = models.PositiveIntegerField(default=0)

    # -- attendance --------------------------------------------------------
    #: Where the day was worked. Set from the roster, so a hybrid week reads
    #: office on some rows and remote on others.
    work_mode = models.CharField(max_length=8, choices=DAY_WORK_MODES, blank=True)

    #: The roster as it stood *when the day happened*, frozen onto the row.
    #: Moving somebody to a later shift next month must not turn last week
    #: into lateness, so nothing downstream ever re-reads today's roster for
    #: a past day - it reads these four fields.
    scheduled_start = models.DateTimeField(null=True, blank=True)
    scheduled_end = models.DateTimeField(null=True, blank=True)
    scheduled_minutes = models.PositiveSmallIntegerField(default=0)
    grace_minutes = models.PositiveSmallIntegerField(default=0)
    schedule_label = models.CharField(max_length=60, blank=True)

    break_minutes = models.PositiveSmallIntegerField(default=0)
    #: Check-out minus check-in minus break. Stored, because it is what the
    #: month is reported on and the punches can be corrected afterwards.
    work_minutes = models.PositiveSmallIntegerField(default=0)
    short_minutes = models.PositiveSmallIntegerField(default=0)
    overtime_minutes = models.PositiveSmallIntegerField(default=0)
    #: Hours an approved permission covers. Subtracted before the day is
    #: called short - otherwise a permission HR granted would still read as a
    #: shortfall and could price a deduction, which is how people stop
    #: trusting the whole module.
    excused_minutes = models.PositiveSmallIntegerField(default=0)

    off_site = models.BooleanField(
        default=False, help_text="An office day punched from outside the allowed radius."
    )
    needs_review = models.BooleanField(default=False, db_index=True)
    review_reason = models.CharField(max_length=160, blank=True)
    #: True when the person punched it themselves; False when HR typed it in.
    self_recorded = models.BooleanField(default=False)

    words = models.PositiveIntegerField(default=0)
    #: True once the refresh has written this day's count from the job log. A
    #: day the admin filled in by hand stays False and the refresh leaves it
    #: alone - otherwise switching a month to job-driven counting would wipe
    #: everything recorded before the jobs carried word counts.
    words_from_jobs = models.BooleanField(default=False)
    is_secondary_language = models.BooleanField(
        default=False, help_text="Worked in a language other than their main one."
    )
    difficult_file = models.BooleanField(
        default=False, help_text="Manager marked the file difficult - exempt from the daily floor."
    )

    absence_reason = models.CharField(max_length=200, blank=True)
    note = models.CharField(max_length=250, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ("-date",)
        unique_together = (("user", "date"),)
        indexes = [models.Index(fields=["user", "date"], name="dash_workday_user_date_idx")]

    def __str__(self):
        return f"{self.user} {self.date} {self.status}"

    @property
    def is_working_day(self):
        return self.status in WORKING_DAY_STATUSES

    @property
    def worked_minutes(self):
        """Net minutes: the stored figure, or the raw span before one exists."""
        if self.work_minutes:
            return self.work_minutes
        if not (self.check_in and self.check_out):
            return 0
        span = int((self.check_out - self.check_in).total_seconds() // 60)
        return max(0, span - self.break_minutes)

    @property
    def is_open(self):
        """Checked in and not out yet - the shift is still running."""
        return bool(self.check_in) and not self.check_out

    @property
    def on_break(self):
        last = self.events.filter(
            kind__in=(PunchKind.BREAK_START, PunchKind.BREAK_END)
        ).order_by("-at", "-id").first()
        return bool(last) and last.kind == PunchKind.BREAK_START

    @property
    def hours_display(self):
        return f"{self.worked_minutes // 60}:{self.worked_minutes % 60:02d}"

    @property
    def is_office_day(self):
        return self.work_mode == WorkMode.OFFICE

    @property
    def is_remote_day(self):
        return self.work_mode == WorkMode.REMOTE

    def target(self, conf=None):
        conf = conf or PayrollSettings.load()
        return conf.target_for(self.is_secondary_language)

    def is_under_target(self, conf=None):
        """A difficult file is exempt - that exemption is the manager's call."""
        if not self.is_working_day or self.difficult_file:
            return False
        return self.words < self.target(conf)

    def bonus(self, tiers=None):
        if not self.is_working_day:
            return Decimal("0.00")
        return ProductionTier.bonus_for(
            self.words, secondary=self.is_secondary_language, tiers=tiers
        )


class Violation(models.Model):
    """Anything that can cost money. Nothing here is applied until approved."""

    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name="violations")
    task = models.ForeignKey(
        Task, null=True, blank=True, on_delete=models.SET_NULL, related_name="+"
    )
    date = models.DateField(db_index=True)
    kind = models.CharField(max_length=16, choices=ViolationKind.choices)
    status = models.CharField(
        max_length=10, choices=ApprovalStatus.choices,
        default=ApprovalStatus.PENDING, db_index=True,
    )

    #: A deduction is priced either in days of pay or as a flat amount.
    penalty_days = models.DecimalField(max_digits=5, decimal_places=2, default=Decimal("0.00"))
    penalty_amount = models.DecimalField(max_digits=9, decimal_places=2, default=Decimal("0.00"))

    reason = models.CharField(max_length=250, blank=True)
    escalated = models.BooleanField(
        default=False, help_text="Third absence without permission - sent to the owner."
    )
    #: Set for rows the engine raised itself, so a recalculation replaces its
    #: own pending drafts instead of piling duplicates on the same day.
    auto_key = models.CharField(max_length=80, blank=True, db_index=True)

    created_by = models.ForeignKey(User, null=True, on_delete=models.SET_NULL, related_name="+")
    approved_by = models.ForeignKey(User, null=True, blank=True, on_delete=models.SET_NULL, related_name="+")
    approved_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ("-date", "-id")
        indexes = [
            models.Index(fields=["user", "date", "status"], name="dash_viol_user_date_idx")
        ]

    def __str__(self):
        return f"{self.user} {self.get_kind_display()} {self.date} ({self.status})"

    @property
    def is_approved(self):
        return self.status == ApprovalStatus.APPROVED

    def approve(self, by):
        self.status = ApprovalStatus.APPROVED
        self.approved_by = by
        self.approved_at = timezone.now()
        self.save(update_fields=["status", "approved_by", "approved_at"])

    def reject(self, by):
        self.status = ApprovalStatus.REJECTED
        self.approved_by = by
        self.approved_at = timezone.now()
        self.save(update_fields=["status", "approved_by", "approved_at"])


class PayrollPeriod(models.Model):
    """One accounting month. A locked period is never recomputed."""

    year = models.PositiveSmallIntegerField()
    month = models.PositiveSmallIntegerField()
    status = models.CharField(
        max_length=10, choices=PeriodStatus.choices, default=PeriodStatus.DRAFT
    )
    note = models.CharField(max_length=250, blank=True)
    approved_by = models.ForeignKey(User, null=True, blank=True, on_delete=models.SET_NULL, related_name="+")
    approved_at = models.DateTimeField(null=True, blank=True)
    computed_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ("-year", "-month")
        unique_together = (("year", "month"),)

    def __str__(self):
        return f"{self.year}-{self.month:02d}"

    @property
    def label(self):
        return f"{self.year}-{self.month:02d}"

    @property
    def is_locked(self):
        return self.status == PeriodStatus.LOCKED

    @property
    def total_net(self):
        return sum((line.net for line in self.lines.all()), Decimal("0.00"))


class PayrollLine(models.Model):
    """One translator's month, frozen. Every figure that produced ``net`` is
    stored next to it, so a payslip can be reread years later without asking
    today's settings what the rules used to be."""

    period = models.ForeignKey(PayrollPeriod, on_delete=models.CASCADE, related_name="lines")
    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name="payroll_lines")

    base_salary = models.DecimalField(max_digits=10, decimal_places=2, default=Decimal("0.00"))
    working_days = models.PositiveSmallIntegerField(default=0)
    day_value = models.DecimalField(max_digits=10, decimal_places=2, default=Decimal("0.00"))

    worked_days = models.PositiveSmallIntegerField(default=0)
    leave_days = models.PositiveSmallIntegerField(default=0)
    unexcused_days = models.PositiveSmallIntegerField(default=0)
    extra_leave_days = models.PositiveSmallIntegerField(default=0)

    total_words = models.PositiveIntegerField(default=0)
    target_words = models.PositiveIntegerField(default=0)
    under_target_days = models.PositiveSmallIntegerField(default=0)

    #: The month's attendance, frozen beside the money it produced. Section 12
    #: asks for exactly these, and a payslip that stores them can be reread
    #: years later without the roster still existing.
    scheduled_days = models.PositiveSmallIntegerField(default=0)
    office_days = models.PositiveSmallIntegerField(default=0)
    remote_days = models.PositiveSmallIntegerField(default=0)
    late_days = models.PositiveSmallIntegerField(default=0)
    late_minutes = models.PositiveIntegerField(default=0)
    early_leave_minutes = models.PositiveIntegerField(default=0)
    short_minutes = models.PositiveIntegerField(default=0)
    work_minutes = models.PositiveIntegerField(default=0)
    overtime_minutes = models.PositiveIntegerField(default=0)

    #: A flat monthly addition from the person's salary plan, if they have
    #: one. Stored on the line so releasing the bonuses can rebuild `gross`
    #: without going back to today's plan for a month already run.
    allowance = models.DecimalField(max_digits=10, decimal_places=2, default=Decimal("0.00"))
    production_bonus = models.DecimalField(max_digits=10, decimal_places=2, default=Decimal("0.00"))
    overtime_bonus = models.DecimalField(max_digits=10, decimal_places=2, default=Decimal("0.00"))
    discipline_bonus = models.DecimalField(max_digits=10, decimal_places=2, default=Decimal("0.00"))
    target_bonus = models.DecimalField(max_digits=10, decimal_places=2, default=Decimal("0.00"))
    deductions = models.DecimalField(max_digits=10, decimal_places=2, default=Decimal("0.00"))

    gross = models.DecimalField(max_digits=10, decimal_places=2, default=Decimal("0.00"))
    net = models.DecimalField(max_digits=10, decimal_places=2, default=Decimal("0.00"))

    #: True when the bonus was earned but is still waiting on the manager, so
    #: the screen can show "earned, not yet paid" instead of silently zero.
    discipline_bonus_earned = models.BooleanField(default=False)
    target_bonus_earned = models.BooleanField(default=False)
    bonuses_approved = models.BooleanField(default=False)
    below_alert_threshold = models.BooleanField(default=False)

    #: Day-by-day and line-by-line detail behind the totals above.
    breakdown = models.JSONField(default=dict, blank=True)

    computed_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ("user__username",)
        unique_together = (("period", "user"),)

    def __str__(self):
        return f"{self.user} {self.period.label} = {self.net}"

    @property
    def bonus_total(self):
        """The two monthly bonuses actually being paid on this line."""
        return self.discipline_bonus + self.target_bonus

    @property
    def work_hours_display(self):
        return f"{self.work_minutes // 60}:{self.work_minutes % 60:02d}"

    @property
    def overtime_hours_display(self):
        return f"{self.overtime_minutes // 60}:{self.overtime_minutes % 60:02d}"

    @property
    def pending_bonus(self):
        """Money the translator has earned that approval is still holding."""
        if self.bonuses_approved:
            return Decimal("0.00")
        conf = PayrollSettings.load()
        total = Decimal("0.00")
        if self.discipline_bonus_earned:
            total += conf.discipline_bonus
        if self.target_bonus_earned:
            total += conf.target_bonus
        return total


# ---------------------------------------------------------------------------
# Attendance
#
# The point of this module is to prove that somebody started and finished a
# day - not to watch them through it. Location is read at a punch and nowhere
# else; there is no continuous GPS, no camera, no screenshots. Whatever a
# person actually produced belongs to the operations side, and the two are
# deliberately kept apart (section 14 of the spec).
#
# Two rules run through everything below:
#
# * **The roster is read once, then frozen.** A day carries the shift it was
#   worked under. Changing somebody's schedule tomorrow cannot rewrite what
#   yesterday counted as late.
# * **Nothing is silently overwritten.** Punches are append-only rows; HR's
#   corrections land on the day *and* in `AttendanceEdit`, with a reason.
# ---------------------------------------------------------------------------

class OfficeLocation(models.Model):
    """A place a punch may be made from, and how close is close enough."""

    name = models.CharField(max_length=80)
    name_ar = models.CharField(max_length=80, blank=True)
    latitude = models.DecimalField(max_digits=9, decimal_places=6)
    longitude = models.DecimalField(max_digits=9, decimal_places=6)
    radius_meters = models.PositiveIntegerField(
        default=200, help_text="Phone GPS is routinely 50-100 m out - leave room."
    )
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ("name",)

    def __str__(self):
        return self.label

    @property
    def label(self):
        return self.name_ar or self.name


class AuthorizedDevice(models.Model):
    """A browser somebody punches from.

    The fingerprint is a random token the browser keeps and sends back - it
    identifies the browser, and nothing about the person or the hardware. A
    token nobody has seen before arrives as ``pending``: HR either recognises
    the new phone or does not, which is what stops one colleague punching in
    for another from their own machine.
    """

    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name="devices")
    fingerprint = models.CharField(max_length=64, db_index=True)
    label = models.CharField(max_length=80, blank=True)
    user_agent = models.CharField(max_length=250, blank=True)
    status = models.CharField(
        max_length=10, choices=ApprovalStatus.choices,
        default=ApprovalStatus.PENDING, db_index=True,
    )
    first_seen = models.DateTimeField(auto_now_add=True)
    last_seen = models.DateTimeField(auto_now=True)
    approved_by = models.ForeignKey(User, null=True, blank=True, on_delete=models.SET_NULL, related_name="+")
    approved_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ("-last_seen",)
        unique_together = (("user", "fingerprint"),)

    def __str__(self):
        return f"{self.user} · {self.label or self.fingerprint[:8]} ({self.status})"

    @property
    def is_approved(self):
        return self.status == ApprovalStatus.APPROVED

    def approve(self, by):
        self.status = ApprovalStatus.APPROVED
        self.approved_by = by
        self.approved_at = timezone.now()
        self.save(update_fields=["status", "approved_by", "approved_at"])

    def reject(self, by):
        self.status = ApprovalStatus.REJECTED
        self.approved_by = by
        self.approved_at = timezone.now()
        self.save(update_fields=["status", "approved_by", "approved_at"])


class ScheduleOverride(models.Model):
    """One day moved, without touching the person's standing roster.

    "Ahmed works 16:00-20:00 on the 20th" is this row. Next Tuesday goes back
    to whatever the roster says, because the roster was never edited.
    """

    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name="schedule_overrides")
    date = models.DateField(db_index=True)
    is_day_off = models.BooleanField(default=False)
    template = models.ForeignKey(
        ShiftTemplate, null=True, blank=True, on_delete=models.PROTECT, related_name="+"
    )
    start_time = models.TimeField(null=True, blank=True)
    end_time = models.TimeField(null=True, blank=True)
    work_mode = models.CharField(max_length=8, choices=DAY_WORK_MODES, blank=True)
    required_minutes = models.PositiveSmallIntegerField(default=0)
    reason = models.CharField(max_length=200, blank=True)
    created_by = models.ForeignKey(User, null=True, on_delete=models.SET_NULL, related_name="+")
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ("-date",)
        unique_together = (("user", "date"),)

    def __str__(self):
        return f"{self.user} {self.date} {'off' if self.is_day_off else self.label}"

    @property
    def start(self):
        return self.template.start_time if self.template_id else self.start_time

    @property
    def end(self):
        return self.template.end_time if self.template_id else self.end_time

    @property
    def label(self):
        if self.template_id:
            return self.template.label
        start, end = self.start, self.end
        return f"{start:%H:%M}-{end:%H:%M}" if start and end else "—"

    @property
    def minutes(self):
        if self.required_minutes:
            return self.required_minutes
        start, end = self.start, self.end
        return span_minutes(start, end) if start and end else 0

    def mode_for(self, user=None):
        if self.work_mode:
            return self.work_mode
        owner = user or self.user
        return WorkMode.OFFICE if owner.is_hybrid else owner.work_mode


class AttendanceEvent(models.Model):
    """One punch. Append-only: rows are written, never edited.

    Everything a punch knows about where and how it happened lives here, so a
    corrected day still carries the evidence of what was originally recorded.
    """

    work_day = models.ForeignKey(
        WorkDay, null=True, blank=True, on_delete=models.CASCADE, related_name="events"
    )
    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name="attendance_events")
    kind = models.CharField(max_length=12, choices=PunchKind.choices)
    at = models.DateTimeField(db_index=True)

    latitude = models.DecimalField(max_digits=9, decimal_places=6, null=True, blank=True)
    longitude = models.DecimalField(max_digits=9, decimal_places=6, null=True, blank=True)
    accuracy_m = models.PositiveIntegerField(null=True, blank=True)
    distance_m = models.PositiveIntegerField(null=True, blank=True)
    office = models.ForeignKey(
        OfficeLocation, null=True, blank=True, on_delete=models.SET_NULL, related_name="+"
    )
    #: None means the punch was never location-checked (a remote day, or a
    #: policy that does not ask for it) - which is not the same as "failed".
    within_geofence = models.BooleanField(null=True, blank=True)

    ip = models.GenericIPAddressField(null=True, blank=True)
    user_agent = models.CharField(max_length=250, blank=True)
    device = models.ForeignKey(
        AuthorizedDevice, null=True, blank=True, on_delete=models.SET_NULL, related_name="+"
    )
    source = models.CharField(max_length=10, default="web")
    note = models.CharField(max_length=160, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ("at", "id")
        indexes = [models.Index(fields=["user", "at"], name="dash_att_user_at_idx")]

    def __str__(self):
        return f"{self.user} {self.kind} {self.at:%Y-%m-%d %H:%M}"


class AttendanceEdit(models.Model):
    """Section 9: no attendance is changed without a trace of who and why.

    One row per field changed. There is no update or delete path anywhere in
    the app - the admin registration is read-only too.
    """

    work_day = models.ForeignKey(WorkDay, on_delete=models.CASCADE, related_name="edits")
    actor = models.ForeignKey(User, null=True, on_delete=models.SET_NULL, related_name="+")
    field = models.CharField(max_length=40)
    old_value = models.CharField(max_length=160, blank=True)
    new_value = models.CharField(max_length=160, blank=True)
    reason = models.CharField(max_length=250)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ("-created_at", "-id")

    def __str__(self):
        return f"{self.work_day} · {self.field}: {self.old_value} -> {self.new_value}"


class OvertimeClaim(models.Model):
    """Extra minutes, priced, waiting for a decision.

    The mirror image of a `Violation`: the engine works out that the time was
    worked, and approval is what releases the money. Nothing reaches a payslip
    on the engine's word alone, in either direction.
    """

    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name="overtime_claims")
    date = models.DateField(db_index=True)
    minutes = models.PositiveIntegerField(default=0)
    hourly_rate = models.DecimalField(max_digits=9, decimal_places=2, default=Decimal("0.00"))
    amount = models.DecimalField(max_digits=9, decimal_places=2, default=Decimal("0.00"))
    status = models.CharField(
        max_length=10, choices=ApprovalStatus.choices,
        default=ApprovalStatus.PENDING, db_index=True,
    )
    reason = models.CharField(max_length=250, blank=True)
    approved_by = models.ForeignKey(User, null=True, blank=True, on_delete=models.SET_NULL, related_name="+")
    approved_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ("-date", "-id")
        unique_together = (("user", "date"),)

    def __str__(self):
        return f"{self.user} {self.date} +{self.minutes}m ({self.status})"

    @property
    def is_approved(self):
        return self.status == ApprovalStatus.APPROVED

    @property
    def hours_display(self):
        return f"{self.minutes // 60}:{self.minutes % 60:02d}"

    def approve(self, by):
        self.status = ApprovalStatus.APPROVED
        self.approved_by = by
        self.approved_at = timezone.now()
        self.save(update_fields=["status", "approved_by", "approved_at"])

    def reject(self, by):
        self.status = ApprovalStatus.REJECTED
        self.approved_by = by
        self.approved_at = timezone.now()
        self.save(update_fields=["status", "approved_by", "approved_at"])


# ---------------------------------------------------------------------------
# HR / recruitment
#
# Three rules shape this section, and each of them is a column or a method
# here rather than a line in a manual:
#
# * **The candidate does not learn who we are until HR says so** (section 3).
#   `Candidate.identity_revealed` gates it, and every outbound message runs
#   through `recruitment.outbound_text`, which redacts the company's names
#   while the flag is off. It is a system rule because a rule people have to
#   remember is not a rule.
# * **The questions are HR's, not the code's** (sections 8-11). There is one
#   bank of questions and each vacancy picks from it, in its own order. Adding
#   a department or a whole new kind of role needs no deploy.
# * **The bot collects; people decide** (section 28). Nothing in here moves a
#   candidate past HR screening on its own, and only the owner hires.
# ---------------------------------------------------------------------------

class Department(models.Model):
    """Translation, Sales, Marketing... Added from the panel, never in code."""

    name = models.CharField(max_length=80, unique=True)
    name_ar = models.CharField(max_length=80, blank=True)
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ("name",)

    def __str__(self):
        return self.label

    @property
    def label(self):
        return self.name_ar or self.name

    #: Seeded once so the bank is not empty on day one. Section 29's list.
    DEFAULTS = (
        ("Translation", "الترجمة"),
        ("Sales", "المبيعات"),
        ("Marketing", "التسويق"),
        ("Operations", "الأوبريشن"),
        ("HR", "الموارد البشرية"),
        ("Customer Service", "خدمة العملاء"),
        ("Finance", "الحسابات"),
        ("IT", "تكنولوجيا المعلومات"),
    )

    @classmethod
    def seed_defaults(cls):
        if cls.objects.exists():
            return
        cls.objects.bulk_create([
            cls(name=name, name_ar=name_ar) for name, name_ar in cls.DEFAULTS
        ])


class RecruitmentQuestion(models.Model):
    """One question in the central bank (section 8).

    A question with no department is a general one - it shows up for every
    vacancy HR builds. Nothing forces a department's questions onto a vacancy;
    the department only helps HR find them.
    """

    text = models.CharField(max_length=300)
    text_en = models.CharField(max_length=300, blank=True)
    kind = models.CharField(max_length=10, choices=QuestionKind.choices, default=QuestionKind.TEXT)
    department = models.ForeignKey(
        Department, null=True, blank=True, on_delete=models.SET_NULL,
        related_name="questions", help_text="Blank means a general question.",
    )
    options = models.JSONField(
        default=list, blank=True,
        help_text="Choices, for the pick-one / pick-many / dropdown kinds.",
    )
    maps_to = models.CharField(
        max_length=20, choices=AnswerTarget.choices, blank=True,
        help_text="Fills this field on the candidate's profile.",
    )
    help_text = models.CharField(max_length=250, blank=True)
    is_active = models.BooleanField(default=True)
    sort_order = models.PositiveSmallIntegerField(default=0)
    created_by = models.ForeignKey(User, null=True, on_delete=models.SET_NULL, related_name="+")
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ("department__name", "sort_order", "id")

    def __str__(self):
        return self.text

    @property
    def option_list(self):
        return [str(item) for item in (self.options or []) if str(item).strip()]

    @property
    def wants_options(self):
        return self.kind in CHOICE_KINDS


class Vacancy(models.Model):
    """A role being hired for, and the questions its applicants are asked."""

    code = models.CharField(max_length=20, unique=True, blank=True)
    title = models.CharField(max_length=140)
    department = models.ForeignKey(
        Department, null=True, blank=True, on_delete=models.SET_NULL, related_name="vacancies"
    )
    openings = models.PositiveSmallIntegerField(default=1)

    required_experience = models.CharField(max_length=140, blank=True)
    required_languages = models.CharField(max_length=160, blank=True)
    required_skills = models.CharField(max_length=250, blank=True)
    salary_min = models.DecimalField(max_digits=10, decimal_places=2, null=True, blank=True)
    salary_max = models.DecimalField(max_digits=10, decimal_places=2, null=True, blank=True)

    employment_type = models.CharField(
        max_length=12, choices=EmploymentType.choices, default=EmploymentType.FULL_TIME
    )
    work_mode = models.CharField(
        max_length=8, choices=WorkMode.choices, default=WorkMode.OFFICE
    )
    #: Section 7: the bot offers exactly these and nothing else. One shift and
    #: it simply asks "can you work these hours?"; several and it lists them.
    shifts = models.ManyToManyField(ShiftTemplate, blank=True, related_name="vacancies")

    job_description = models.TextField(blank=True)
    requirements = models.TextField(blank=True)
    deadline = models.DateField(null=True, blank=True)
    status = models.CharField(
        max_length=8, choices=VacancyStatus.choices, default=VacancyStatus.DRAFT, db_index=True
    )

    created_by = models.ForeignKey(User, null=True, on_delete=models.SET_NULL, related_name="+")
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ("-created_at",)
        verbose_name_plural = "Vacancies"

    def __str__(self):
        return f"{self.code} · {self.title}"

    def save(self, *args, **kwargs):
        if not self.code:
            self.code = next_code(Vacancy, "code", "VAC")
        super().save(*args, **kwargs)

    @property
    def is_open(self):
        return self.status == VacancyStatus.OPEN

    @property
    def salary_range(self):
        if self.salary_min and self.salary_max:
            return f"{self.salary_min:.0f} - {self.salary_max:.0f}"
        return f"{self.salary_min or self.salary_max or '—'}"

    @property
    def shift_list(self):
        return list(self.shifts.all())

    def questions_in_order(self):
        return list(
            self.question_links.select_related("question").order_by("order", "id")
        )

    @property
    def applicant_count(self):
        return self.candidates.count()


class VacancyQuestion(models.Model):
    """One question attached to one vacancy, in HR's chosen order."""

    vacancy = models.ForeignKey(Vacancy, on_delete=models.CASCADE, related_name="question_links")
    question = models.ForeignKey(
        RecruitmentQuestion, on_delete=models.PROTECT, related_name="vacancy_links"
    )
    order = models.PositiveSmallIntegerField(default=0)
    is_required = models.BooleanField(default=True)

    class Meta:
        ordering = ("order", "id")
        unique_together = (("vacancy", "question"),)

    def __str__(self):
        return f"{self.vacancy.code} #{self.order} {self.question.text[:40]}"


class Candidate(models.Model):
    """Somebody applying. Anonymous to themselves until HR lifts the veil."""

    code = models.CharField(max_length=20, unique=True, blank=True)
    vacancy = models.ForeignKey(
        Vacancy, null=True, blank=True, on_delete=models.SET_NULL, related_name="candidates"
    )
    department = models.ForeignKey(
        Department, null=True, blank=True, on_delete=models.SET_NULL, related_name="candidates"
    )

    full_name = models.CharField(max_length=140, blank=True)
    phone = models.CharField(max_length=32, blank=True, db_index=True)
    email = models.EmailField(blank=True)
    cv = models.FileField(upload_to=upload_cv, blank=True, null=True)
    cv_name = models.CharField(max_length=200, blank=True)

    experience_years = models.CharField(max_length=60, blank=True)
    languages = models.CharField(max_length=160, blank=True)
    skills = models.CharField(max_length=250, blank=True)
    expected_salary = models.CharField(max_length=60, blank=True)
    shift_choice = models.CharField(max_length=120, blank=True)

    source = models.CharField(
        max_length=10, choices=CandidateSource.choices, default=CandidateSource.WHATSAPP
    )
    status = models.CharField(
        max_length=14, choices=CandidateStatus.choices,
        default=CandidateStatus.NEW, db_index=True,
    )
    hr_notes = models.TextField(blank=True)
    hr_recommendation = models.CharField(max_length=250, blank=True)
    rejection_reason = models.CharField(max_length=250, blank=True)

    #: Section 3, as state rather than as a promise. While this is False every
    #: outbound message is scrubbed of the company's names by
    #: `recruitment.outbound_text`, whatever a screen or a person typed.
    identity_revealed = models.BooleanField(default=False)
    identity_revealed_at = models.DateTimeField(null=True, blank=True)
    identity_revealed_by = models.ForeignKey(
        User, null=True, blank=True, on_delete=models.SET_NULL, related_name="+"
    )

    owner_decision_at = models.DateTimeField(null=True, blank=True)
    owner_decision_by = models.ForeignKey(
        User, null=True, blank=True, on_delete=models.SET_NULL, related_name="+"
    )
    hired_user = models.OneToOneField(
        User, null=True, blank=True, on_delete=models.SET_NULL, related_name="candidate_record"
    )

    applied_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ("-applied_at",)
        indexes = [models.Index(fields=["status", "-applied_at"], name="dash_cand_status_idx")]

    def __str__(self):
        return f"{self.code} · {self.full_name or self.phone}"

    def save(self, *args, **kwargs):
        if not self.code:
            self.code = next_code(Candidate, "code", "CAN")
        if self.vacancy_id and not self.department_id:
            self.department_id = self.vacancy.department_id
        super().save(*args, **kwargs)

    @property
    def display_name(self):
        return self.full_name or self.phone or self.code

    @property
    def is_early_stage(self):
        return self.status in EARLY_CANDIDATE_STAGES

    @property
    def is_rejected(self):
        return self.status == CandidateStatus.REJECTED

    @property
    def is_hired(self):
        return self.status == CandidateStatus.HIRED

    @property
    def latest_interview(self):
        return self.interviews.order_by("-scheduled_at", "-id").first()

    @property
    def latest_test(self):
        return self.tests.order_by("-created_at", "-id").first()

    @property
    def interview_score(self):
        row = self.latest_interview
        return row.total_score if row and row.is_evaluated else None

    @property
    def test_score(self):
        row = self.latest_test
        return row.total_score if row and row.is_marked else None


class CandidateAnswer(models.Model):
    """What the applicant said to one question, kept verbatim.

    The answer is stored as the candidate gave it even when it also filled a
    profile field, so a later correction to the profile never quietly rewrites
    what somebody actually replied.
    """

    candidate = models.ForeignKey(Candidate, on_delete=models.CASCADE, related_name="answers")
    question = models.ForeignKey(
        RecruitmentQuestion, on_delete=models.PROTECT, related_name="answers"
    )
    order = models.PositiveSmallIntegerField(default=0)
    value = models.TextField(blank=True)
    file = models.FileField(upload_to=upload_cv, blank=True, null=True)
    file_name = models.CharField(max_length=200, blank=True)
    answered_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ("order", "id")
        unique_together = (("candidate", "question"),)

    def __str__(self):
        return f"{self.candidate.code}: {self.value[:40]}"


class CandidateSession(models.Model):
    """The bot's cursor through one conversation.

    Keyed on the phone number, because that is all a first message carries.
    The candidate row is created as soon as there is a name or a vacancy to
    hang it on, and the session then points at it.
    """

    channel = models.CharField(max_length=10, default="whatsapp")
    contact = models.CharField(max_length=40, db_index=True)
    display_name = models.CharField(max_length=120, blank=True)
    candidate = models.ForeignKey(
        Candidate, null=True, blank=True, on_delete=models.SET_NULL, related_name="sessions"
    )
    vacancy = models.ForeignKey(
        Vacancy, null=True, blank=True, on_delete=models.SET_NULL, related_name="+"
    )
    state = models.CharField(
        max_length=10, choices=SessionState.choices, default=SessionState.PICKING
    )
    #: Index into the vacancy's question list. Also how a restart is detected.
    step = models.PositiveSmallIntegerField(default=0)
    #: The numbered list the bot last printed, so "2" can be resolved back.
    pending_options = models.JSONField(default=list, blank=True)
    started_at = models.DateTimeField(auto_now_add=True)
    last_message_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ("-last_message_at",)
        indexes = [models.Index(fields=["contact", "state"], name="dash_sess_contact_idx")]

    def __str__(self):
        return f"{self.contact} ({self.state})"

    @property
    def is_live(self):
        return self.state in (SessionState.PICKING, SessionState.ASKING)


class Interview(models.Model):
    """A meeting, and afterwards the five scores section 14 asks for."""

    candidate = models.ForeignKey(Candidate, on_delete=models.CASCADE, related_name="interviews")
    scheduled_at = models.DateTimeField()
    interviewer = models.ForeignKey(
        User, null=True, blank=True, on_delete=models.SET_NULL, related_name="interviews_given"
    )
    kind = models.CharField(
        max_length=8, choices=InterviewKind.choices, default=InterviewKind.ONLINE
    )
    meeting_link = models.CharField(max_length=300, blank=True)
    location = models.CharField(max_length=200, blank=True)
    notes = models.TextField(blank=True)

    #: Each out of ten. Null means "not marked", which is not the same as zero.
    communication = models.PositiveSmallIntegerField(null=True, blank=True)
    experience = models.PositiveSmallIntegerField(null=True, blank=True)
    technical = models.PositiveSmallIntegerField(null=True, blank=True)
    computer_skills = models.PositiveSmallIntegerField(null=True, blank=True)
    attitude = models.PositiveSmallIntegerField(null=True, blank=True)
    comments = models.TextField(blank=True)
    evaluated_at = models.DateTimeField(null=True, blank=True)
    evaluated_by = models.ForeignKey(
        User, null=True, blank=True, on_delete=models.SET_NULL, related_name="+"
    )

    created_by = models.ForeignKey(User, null=True, on_delete=models.SET_NULL, related_name="+")
    created_at = models.DateTimeField(auto_now_add=True)

    SCORE_FIELDS = ("communication", "experience", "technical", "computer_skills", "attitude")

    class Meta:
        ordering = ("-scheduled_at", "-id")

    def __str__(self):
        return f"{self.candidate.code} {self.scheduled_at:%Y-%m-%d %H:%M}"

    @property
    def is_evaluated(self):
        return any(getattr(self, name) is not None for name in self.SCORE_FIELDS)

    @property
    def total_score(self):
        """Out of 50. The system adds it up - section 14 says so explicitly."""
        marks = [getattr(self, name) for name in self.SCORE_FIELDS]
        return sum(m for m in marks if m is not None)

    @property
    def max_score(self):
        return len(self.SCORE_FIELDS) * 10


class CandidateTest(models.Model):
    """A piece of work set for a candidate, and the reviewer's marks.

    The evaluation columns are the translation ones from section 15, which is
    what Eagle actually hires for; a test for another department simply leaves
    the ones that do not apply blank and carries its verdict in the comments.
    """

    candidate = models.ForeignKey(Candidate, on_delete=models.CASCADE, related_name="tests")
    department = models.ForeignKey(
        Department, null=True, blank=True, on_delete=models.SET_NULL, related_name="+"
    )
    title = models.CharField(max_length=160, blank=True)
    brief = models.TextField(blank=True)
    language_pair = models.CharField(max_length=80, blank=True)
    word_count = models.PositiveIntegerField(default=0)

    assignment = models.FileField(upload_to=upload_test, blank=True, null=True)
    assignment_name = models.CharField(max_length=200, blank=True)
    submission = models.FileField(upload_to=upload_test, blank=True, null=True)
    submission_name = models.CharField(max_length=200, blank=True)
    submitted_at = models.DateTimeField(null=True, blank=True)
    deadline = models.DateTimeField(null=True, blank=True)

    reviewer = models.ForeignKey(
        User, null=True, blank=True, on_delete=models.SET_NULL, related_name="tests_reviewed"
    )
    accuracy = models.PositiveSmallIntegerField(null=True, blank=True)
    grammar = models.PositiveSmallIntegerField(null=True, blank=True)
    terminology = models.PositiveSmallIntegerField(null=True, blank=True)
    formatting = models.PositiveSmallIntegerField(null=True, blank=True)
    instructions = models.PositiveSmallIntegerField(null=True, blank=True)
    comments = models.TextField(blank=True)
    marked_at = models.DateTimeField(null=True, blank=True)

    created_by = models.ForeignKey(User, null=True, on_delete=models.SET_NULL, related_name="+")
    created_at = models.DateTimeField(auto_now_add=True)

    SCORE_FIELDS = ("accuracy", "grammar", "terminology", "formatting", "instructions")

    class Meta:
        ordering = ("-created_at", "-id")

    def __str__(self):
        return f"{self.candidate.code} test {self.title or self.pk}"

    @property
    def is_marked(self):
        return any(getattr(self, name) is not None for name in self.SCORE_FIELDS)

    @property
    def total_score(self):
        marks = [getattr(self, name) for name in self.SCORE_FIELDS]
        return sum(m for m in marks if m is not None)

    @property
    def max_score(self):
        return len(self.SCORE_FIELDS) * 10

    @property
    def is_submitted(self):
        return bool(self.submission)

    @property
    def is_overdue(self):
        return bool(
            self.deadline and not self.is_submitted and timezone.now() > self.deadline
        )


class RecruitmentSettings(models.Model):
    """The module's own rules. One row, edited from the panel."""

    singleton = models.PositiveSmallIntegerField(primary_key=True, default=1, editable=False)

    bot_enabled = models.BooleanField(default=True)
    bot_name = models.CharField(
        max_length=80, default="Recruitment Team",
        help_text="What the candidate sees instead of the company name.",
    )
    bot_name_ar = models.CharField(max_length=80, default="فريق التوظيف")

    #: The words the privacy rule scrubs while a candidate is anonymous. One
    #: per line. Seeded with the company's own names on first load - if this
    #: is empty, section 3 is not being enforced and the screens say so.
    redact_terms = models.TextField(
        blank=True,
        help_text="One per line: company names, domain, address. Removed from anything sent to an anonymous candidate.",
    )
    redact_placeholder = models.CharField(max_length=60, default="[—]")

    greeting_ar = models.TextField(
        blank=True, help_text="Blank uses the built-in wording."
    )
    greeting_en = models.TextField(blank=True)
    closing_ar = models.TextField(blank=True)
    closing_en = models.TextField(blank=True)

    #: A half-finished chat older than this is not resumed - the next message
    #: starts a fresh application instead of continuing a stale one.
    session_timeout_hours = models.PositiveSmallIntegerField(default=48)
    probation_days = models.PositiveSmallIntegerField(default=90)

    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = "Recruitment settings"
        verbose_name_plural = "Recruitment settings"

    def __str__(self):
        return "Recruitment rules"

    #: Armed on the first load rather than left to somebody's memory. A rule
    #: that only works once an admin remembers to switch it on is not the
    #: system rule section 3 asks for. HR edits the list from the panel.
    DEFAULT_TERMS = (
        "EagleLingua",
        "Eagle Translation",
        "النسر للتوريدات العامه",
        "eagel-operation.com",
    )

    def save(self, *args, **kwargs):
        self.singleton = 1
        super().save(*args, **kwargs)

    @classmethod
    def load(cls):
        obj, created = cls.objects.get_or_create(
            singleton=1,
            defaults={"redact_terms": "\n".join(cls.DEFAULT_TERMS)},
        )
        if created:
            Department.seed_defaults()
        return obj

    @property
    def term_list(self):
        return [
            line.strip() for line in (self.redact_terms or "").splitlines() if line.strip()
        ]

    def display_name(self, lang="ar"):
        return self.bot_name_ar if lang == "ar" else self.bot_name


# ---------------------------------------------------------------------------
# Employee lifecycle: probation, leave, pay
#
# Everything here shares one habit with the rest of Eagle: a decision that
# costs somebody money or a job is never taken by the engine. Probation is
# reviewed by a person, leave is approved by a person, and a salary changes
# only when the owner says so. What the code does is make sure the decision
# is recorded, priced consistently, and visible afterwards.
# ---------------------------------------------------------------------------

class ProbationReview(models.Model):
    """A check-in during someone's first months (section 19).

    Three are created when a person is hired - at thirty days, sixty days,
    and the end. They exist as rows from day one so the dates are visible and
    a missed review is a thing you can see rather than a thing nobody
    remembers.
    """

    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name="probation_reviews")
    stage = models.CharField(max_length=8, choices=ProbationStage.choices)
    due_date = models.DateField(db_index=True)

    outcome = models.CharField(
        max_length=12, choices=ProbationOutcome.choices,
        default=ProbationOutcome.PENDING, db_index=True,
    )
    #: Out of ten, like the interview marks. Null means not scored.
    score = models.PositiveSmallIntegerField(null=True, blank=True)
    notes = models.TextField(blank=True)
    extended_to = models.DateField(null=True, blank=True)

    reviewer = models.ForeignKey(
        User, null=True, blank=True, on_delete=models.SET_NULL, related_name="+"
    )
    decided_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ("due_date", "id")
        unique_together = (("user", "stage"),)

    def __str__(self):
        return f"{self.user} {self.stage} ({self.outcome})"

    @property
    def is_decided(self):
        return self.outcome != ProbationOutcome.PENDING

    @property
    def is_overdue(self):
        return not self.is_decided and self.due_date < timezone.localdate()


class LeaveRequest(models.Model):
    """Time off, asked for and signed off (section 22).

    An approved request writes the days onto the attendance sheet itself, so
    the payroll and the leave log can never tell two different stories about
    the same absence. Permission - a few hours rather than a day - writes
    minutes onto the one day instead, which is why it has its own fields.
    """

    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name="leave_requests")
    kind = models.CharField(max_length=10, choices=LeaveKind.choices, default=LeaveKind.ANNUAL)
    start_date = models.DateField()
    end_date = models.DateField()
    #: Permission only: the window inside the single day.
    start_time = models.TimeField(null=True, blank=True)
    end_time = models.TimeField(null=True, blank=True)
    minutes = models.PositiveSmallIntegerField(default=0)

    reason = models.CharField(max_length=250, blank=True)
    status = models.CharField(
        max_length=11, choices=LeaveStatus.choices,
        default=LeaveStatus.PENDING, db_index=True,
    )

    manager = models.ForeignKey(
        User, null=True, blank=True, on_delete=models.SET_NULL, related_name="+"
    )
    manager_decided_at = models.DateTimeField(null=True, blank=True)
    hr_decision_by = models.ForeignKey(
        User, null=True, blank=True, on_delete=models.SET_NULL, related_name="+"
    )
    hr_decided_at = models.DateTimeField(null=True, blank=True)
    decision_note = models.CharField(max_length=250, blank=True)

    #: Set once the days have been written onto the attendance sheet, so a
    #: second approval cannot double-write them.
    applied_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ("-created_at",)
        indexes = [models.Index(fields=["user", "status"], name="dash_leave_user_idx")]

    def __str__(self):
        return f"{self.user} {self.kind} {self.start_date}..{self.end_date}"

    @property
    def is_permission(self):
        return self.kind == LeaveKind.PERMISSION

    @property
    def day_count(self):
        """Calendar days the request spans. Permission is never a day."""
        if self.is_permission:
            return 0
        return (self.end_date - self.start_date).days + 1

    @property
    def is_open(self):
        return self.status in (LeaveStatus.PENDING, LeaveStatus.MANAGER_OK)

    @property
    def is_approved(self):
        return self.status == LeaveStatus.APPROVED

    @property
    def day_status(self):
        """Which attendance status the approved days carry."""
        return LEAVE_DAY_STATUS.get(self.kind, DayStatus.EXCUSED)

    def dates(self):
        cursor = self.start_date
        while cursor <= self.end_date:
            yield cursor
            cursor += timedelta(days=1)


class ClientComplaint(models.Model):
    """A client said something went wrong (section 20).

    Logged by whoever heard it, against the job and the translator. It feeds
    the quality indicator, so it is deliberately a small, cheap row: a
    complaint nobody can be bothered to record is a complaint that never
    reaches the performance page.
    """

    client = models.ForeignKey(
        Client, null=True, blank=True, on_delete=models.SET_NULL, related_name="complaints"
    )
    task = models.ForeignKey(
        Task, null=True, blank=True, on_delete=models.SET_NULL, related_name="complaints"
    )
    translator = models.ForeignKey(
        User, null=True, blank=True, on_delete=models.SET_NULL, related_name="complaints"
    )
    severity = models.CharField(
        max_length=6, choices=ComplaintSeverity.choices, default=ComplaintSeverity.MEDIUM
    )
    summary = models.CharField(max_length=250)
    detail = models.TextField(blank=True)
    happened_on = models.DateField(default=None, null=True, blank=True)
    resolved = models.BooleanField(default=False)
    logged_by = models.ForeignKey(User, null=True, on_delete=models.SET_NULL, related_name="+")
    created_at = models.DateTimeField(auto_now_add=True)

    #: What each one costs the quality score, out of a hundred.
    WEIGHTS = {
        ComplaintSeverity.LOW: 5,
        ComplaintSeverity.MEDIUM: 12,
        ComplaintSeverity.HIGH: 25,
    }

    class Meta:
        ordering = ("-created_at",)

    def __str__(self):
        return f"{self.summary[:40]} ({self.severity})"

    def save(self, *args, **kwargs):
        if self.happened_on is None:
            self.happened_on = timezone.localdate()
        if self.task_id and not self.translator_id:
            self.translator_id = self.task.translator_id
        super().save(*args, **kwargs)

    @property
    def weight(self):
        return self.WEIGHTS.get(self.severity, 12)


class SalaryPlan(models.Model):
    """One person's pay rules, where they differ from the company's.

    Every number here is optional, and a blank one falls back to
    ``PayrollSettings``. That is the whole design: somebody with no plan - or
    a plan that only sets one field - is priced exactly as they were before
    plans existed. A plan can only ever say "except for this".
    """

    name = models.CharField(max_length=80, unique=True)
    note = models.CharField(max_length=250, blank=True)
    is_active = models.BooleanField(default=True)

    #: Word quota (section 23). Blank keeps the company target.
    daily_target_words = models.PositiveIntegerField(null=True, blank=True)
    secondary_daily_target_words = models.PositiveIntegerField(null=True, blank=True)
    monthly_target_words = models.PositiveIntegerField(null=True, blank=True)

    #: Extra words. With a rate set, everything above the daily quota is paid
    #: per word and the company's tier table is not consulted for this person.
    #: Blank keeps the tiers, which is what every translator uses today.
    extra_word_rate = models.DecimalField(
        max_digits=8, decimal_places=4, null=True, blank=True,
        help_text="Paid per word above the daily quota. Blank uses the company's bonus bands.",
    )
    #: Extra payment: a flat monthly addition (a transport or phone allowance).
    fixed_allowance = models.DecimalField(
        max_digits=10, decimal_places=2, default=Decimal("0.00")
    )

    discipline_bonus = models.DecimalField(
        max_digits=9, decimal_places=2, null=True, blank=True
    )
    target_bonus = models.DecimalField(max_digits=9, decimal_places=2, null=True, blank=True)
    target_miss_penalty = models.DecimalField(
        max_digits=9, decimal_places=2, null=True, blank=True
    )
    working_days_per_month = models.PositiveSmallIntegerField(null=True, blank=True)
    monthly_leave_allowance = models.PositiveSmallIntegerField(null=True, blank=True)
    overtime_hourly_rate = models.DecimalField(
        max_digits=9, decimal_places=2, null=True, blank=True
    )

    created_by = models.ForeignKey(User, null=True, on_delete=models.SET_NULL, related_name="+")
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    #: The fields the resolver will look for on a plan before the settings.
    OVERRIDABLE = (
        "daily_target_words", "secondary_daily_target_words", "monthly_target_words",
        "discipline_bonus", "target_bonus", "target_miss_penalty",
        "working_days_per_month", "monthly_leave_allowance", "overtime_hourly_rate",
    )

    class Meta:
        ordering = ("name",)

    def __str__(self):
        return self.name

    @property
    def uses_tiers(self):
        """Without a per-word rate this plan still pays on the bonus bands."""
        return self.extra_word_rate is None

    def overrides(self):
        """The fields this plan actually sets, for the screens to show."""
        return [
            name for name in self.OVERRIDABLE if getattr(self, name) is not None
        ] + (["extra_word_rate"] if self.extra_word_rate is not None else [])


class SalaryChangeRequest(models.Model):
    """HR asks, the owner decides, accounting sees it (section 23).

    HR has no path to `SalaryRecord` at all - the accounts screens are closed
    to them. This row is the only way a salary moves, and it moves by the
    owner approving it, which then writes the history record.
    """

    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name="salary_requests")
    current_amount = models.DecimalField(max_digits=10, decimal_places=2, default=Decimal("0.00"))
    new_amount = models.DecimalField(max_digits=10, decimal_places=2)
    effective_from = models.DateField()
    reason = models.CharField(max_length=250, blank=True)
    status = models.CharField(
        max_length=10, choices=ApprovalStatus.choices,
        default=ApprovalStatus.PENDING, db_index=True,
    )

    requested_by = models.ForeignKey(User, null=True, on_delete=models.SET_NULL, related_name="+")
    decided_by = models.ForeignKey(
        User, null=True, blank=True, on_delete=models.SET_NULL, related_name="+"
    )
    decided_at = models.DateTimeField(null=True, blank=True)
    decision_note = models.CharField(max_length=250, blank=True)
    #: The history row this produced, once approved.
    salary_record = models.ForeignKey(
        SalaryRecord, null=True, blank=True, on_delete=models.SET_NULL, related_name="+"
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ("-created_at",)

    def __str__(self):
        return f"{self.user} {self.current_amount} -> {self.new_amount} ({self.status})"

    @property
    def is_pending(self):
        return self.status == ApprovalStatus.PENDING

    @property
    def delta(self):
        return Decimal(self.new_amount) - Decimal(self.current_amount)
