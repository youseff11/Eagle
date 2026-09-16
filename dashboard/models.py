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
    #: The team on one side, the client's WhatsApp on the other. Eagle relays
    #: between them, so the team gets a group chat without the client ever
    #: leaving WhatsApp — and without anyone's phone number being exposed.
    CLIENT = "client", "Team + Client (relayed to WhatsApp)"


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
    #: The WhatsApp id this message replies to, when the client quoted one.
    reply_to_external = models.CharField(max_length=190, blank=True)
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
        """Attachments to show — the client's own when this mirrors an inbound."""
        if self.inbound_id:
            return self.inbound.attachments.all()
        return self.attachments.all()


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
        return obj

    def target_for(self, secondary=False):
        return self.secondary_daily_target_words if secondary else self.daily_target_words


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
        if not (self.check_in and self.check_out):
            return 0
        return max(0, int((self.check_out - self.check_in).total_seconds() // 60))

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

    production_bonus = models.DecimalField(max_digits=10, decimal_places=2, default=Decimal("0.00"))
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
