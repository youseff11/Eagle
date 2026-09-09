"""Data model for the Eagle translation-workflow dashboard (Phase 1)."""

from datetime import timedelta
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


class RoomKind(models.TextChoices):
    OPS_LEAD = "ops_lead", "Operation + Team leader"
    GROUP = "group", "Operation + Team leader + Translator"


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
    def can_see_client_identity(self):
        """Only the admin ever sees the real client name / phone / email."""
        return self.is_admin_role

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

    @property
    def is_online(self):
        if not self.is_active or self.force_offline:
            return False
        if self.active_shifts():
            return self.shift_now() is not None
        # No shift configured -> fall back to the browser heartbeat.
        return bool(self.last_seen and (timezone.now() - self.last_seen).total_seconds() < 120)

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


class Shift(models.Model):
    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name="shifts")
    weekday = models.IntegerField(choices=WEEKDAYS)
    start_time = models.TimeField()
    end_time = models.TimeField()
    is_active = models.BooleanField(default=True)

    class Meta:
        ordering = ("weekday", "start_time")

    def __str__(self):
        return f"{self.user} · {self.get_weekday_display()} {self.start_time:%H:%M}-{self.end_time:%H:%M}"

    @property
    def crosses_midnight(self):
        return self.end_time <= self.start_time

    def covers(self, now_time, today, yesterday):
        if not self.crosses_midnight:
            return self.weekday == today and self.start_time <= now_time < self.end_time
        # Overnight shift: it belongs to `weekday` but spills into the next day.
        if self.weekday == today and now_time >= self.start_time:
            return True
        if self.weekday == yesterday and now_time < self.end_time:
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
        last = self.messages.order_by("-received_at").first()
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

    def visible_to(self, user):
        if user.is_admin_role:
            return True
        if self.is_rate_blocked:
            return False
        return user.is_operation


class MessageAttachment(models.Model):
    message = models.ForeignKey(
        InboundMessage, on_delete=models.CASCADE, related_name="attachments"
    )
    file = models.FileField(upload_to=upload_inbound)
    original_name = models.CharField(max_length=250, blank=True)
    size = models.BigIntegerField(default=0)
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
    priority = models.CharField(max_length=10, choices=Priority.choices, default=Priority.NORMAL)
    status = models.CharField(
        max_length=24, choices=TaskStatus.choices, default=TaskStatus.NEW, db_index=True
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

    lead_accepted_at = models.DateTimeField(null=True, blank=True)
    translator_accepted_at = models.DateTimeField(null=True, blank=True)
    translated_at = models.DateTimeField(null=True, blank=True)
    reviewed_at = models.DateTimeField(null=True, blank=True)
    delivered_at = models.DateTimeField(null=True, blank=True)

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
    task = models.ForeignKey(Task, on_delete=models.CASCADE, related_name="rooms")
    kind = models.CharField(max_length=12, choices=RoomKind.choices)
    members = models.ManyToManyField(User, related_name="chat_rooms", blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ("id",)
        constraints = [
            models.UniqueConstraint(fields=["task", "kind"], name="uniq_room_per_task_kind")
        ]

    def __str__(self):
        return f"{self.task.code} · {self.get_kind_display()}"

    def can_access(self, user):
        if user.is_admin_role:
            return True
        return self.members.filter(pk=user.pk).exists()


class ChatMessage(models.Model):
    room = models.ForeignKey(ChatRoom, on_delete=models.CASCADE, related_name="messages")
    sender = models.ForeignKey(
        User, null=True, blank=True, on_delete=models.SET_NULL, related_name="chat_messages"
    )
    body = models.TextField(blank=True)
    is_system = models.BooleanField(default=False)
    system_key = models.CharField(max_length=60, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ("id",)

    def __str__(self):
        return f"#{self.pk} {self.room_id}"


class ChatAttachment(models.Model):
    message = models.ForeignKey(ChatMessage, on_delete=models.CASCADE, related_name="attachments")
    file = models.FileField(upload_to=upload_chat)
    original_name = models.CharField(max_length=250, blank=True)
    size = models.BigIntegerField(default=0)

    def __str__(self):
        return self.original_name or self.file.name

    @property
    def pretty_size(self):
        value = float(self.size or 0)
        for unit in ("B", "KB", "MB", "GB"):
            if value < 1024 or unit == "GB":
                return f"{value:.0f} {unit}" if unit == "B" else f"{value:.1f} {unit}"
            value /= 1024
        return f"{value:.1f} GB"


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
        CLEAN = "clean", "No issues"
        ISSUES = "issues", "Issues found"
        ERROR = "error", "Error"

    task = models.ForeignKey(Task, on_delete=models.CASCADE, related_name="ai_checks")
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

    imap_host = models.CharField(max_length=120, blank=True)
    imap_port = models.PositiveIntegerField(default=993)
    imap_user = models.CharField(max_length=190, blank=True)
    imap_password = models.CharField(max_length=250, blank=True)
    imap_folder = models.CharField(max_length=60, default="INBOX")

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


class OutboundAttachment(models.Model):
    """A real file the operation sent to the client from the chat."""

    message = models.ForeignKey(
        OutboundMessage, on_delete=models.CASCADE, related_name="uploads"
    )
    file = models.FileField(upload_to=upload_outbound)
    original_name = models.CharField(max_length=250, blank=True)
    size = models.BigIntegerField(default=0)
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return self.original_name or self.file.name

    @property
    def pretty_size(self):
        value = float(self.size or 0)
        for unit in ("B", "KB", "MB", "GB"):
            if value < 1024 or unit == "GB":
                return f"{value:.0f} {unit}" if unit == "B" else f"{value:.1f} {unit}"
            value /= 1024
        return f"{value:.1f} GB"


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
