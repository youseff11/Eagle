"""Django-admin registration (the day-to-day UI is the dashboard itself)."""

from django.contrib import admin
from django.contrib.auth.admin import UserAdmin as BaseUserAdmin

from .models import (
    AICheckResult,
    AppSettings,
    Assignment,
    Candidate,
    CandidateAnswer,
    CandidateSession,
    CandidateTest,
    AttendanceEdit,
    AttendanceEvent,
    AuditLog,
    AuthorizedDevice,
    OfficeLocation,
    OutboundMessage,
    OvertimeClaim,
    ChatAttachment,
    ChatMessage,
    ChatRoom,
    Client,
    ClientComplaint,
    ClientRequirement,
    Department,
    InboundMessage,
    Interview,
    LeaveRequest,
    MessageAttachment,
    Notification,
    OutboundAttachment,
    PayrollLine,
    PayrollPeriod,
    PayrollSettings,
    ProductionTier,
    ProbationReview,
    RatingEvent,
    RecruitmentQuestion,
    RecruitmentSettings,
    SalaryChangeRequest,
    SalaryPlan,
    SalaryRecord,
    ScheduleOverride,
    Shift,
    ShiftTemplate,
    Task,
    User,
    Vacancy,
    VacancyQuestion,
    Violation,
    WorkDay,
)


@admin.register(User)
class UserAdmin(BaseUserAdmin):
    list_display = (
        "username", "get_full_name", "role", "employment_type", "work_mode", "is_active"
    )
    list_filter = ("role", "is_active", "force_offline", "employment_type", "work_mode")
    fieldsets = BaseUserAdmin.fieldsets + (
        ("Eagle", {
            "fields": (
                "role", "team_lead", "phone", "languages", "rating",
                "force_offline", "last_seen", "display_name_ar",
                "ui_lang", "ui_theme",
            )
        }),
        ("Workforce", {
            "fields": (
                "employment_type", "work_mode", "schedule_kind",
                "attendance_enabled", "attendance_manager",
            )
        }),
        ("Client identity", {"fields": ("client_identity_access",)}),
        ("Employee file", {
            "fields": (
                "employee_code", "job_title", "department", "joining_date",
                "employment_status", "probation_start", "probation_end",
                "contract", "salary_plan",
            )
        }),
    )
    add_fieldsets = BaseUserAdmin.add_fieldsets + (
        ("Eagle", {"fields": ("role", "team_lead", "phone")}),
    )

    def save_model(self, request, obj, form, change):
        """Role and identity-grant changes made here are logged like ours."""
        from . import identity

        before = identity.access_snapshot(User.objects.filter(pk=obj.pk).first()) if change else {}
        super().save_model(request, obj, form, change)
        identity.record_access_change(request, request.user, obj, before)


class RequirementInline(admin.TabularInline):
    model = ClientRequirement
    extra = 0


@admin.register(Client)
class ClientAdmin(admin.ModelAdmin):
    list_display = ("code", "name", "company", "phone", "email", "is_active")
    search_fields = ("code", "name", "company", "phone", "email")
    inlines = [RequirementInline]


class MessageAttachmentInline(admin.TabularInline):
    model = MessageAttachment
    extra = 0


@admin.register(InboundMessage)
class InboundMessageAdmin(admin.ModelAdmin):
    list_display = ("id", "channel", "client", "is_rate_blocked", "claimed_by", "received_at")
    list_filter = ("channel", "is_rate_blocked")
    # thread_key is editable here on purpose: two letters grouped wrongly are
    # separated by giving one of them a new key, and joined by copying one.
    search_fields = ("subject", "thread_key", "sender_identity")
    inlines = [MessageAttachmentInline]


class AssignmentInline(admin.TabularInline):
    model = Assignment
    extra = 0
    readonly_fields = ("assigned_at", "expires_at", "responded_at")


@admin.register(Task)
class TaskAdmin(admin.ModelAdmin):
    list_display = ("code", "title", "client", "status", "team_lead", "translator", "deadline")
    list_filter = ("status", "priority")
    search_fields = ("code", "title")
    inlines = [AssignmentInline]


class ChatAttachmentInline(admin.TabularInline):
    model = ChatAttachment
    extra = 0


@admin.register(ChatMessage)
class ChatMessageAdmin(admin.ModelAdmin):
    list_display = ("id", "room", "sender", "is_system", "created_at")
    inlines = [ChatAttachmentInline]


@admin.register(AppSettings)
class AppSettingsAdmin(admin.ModelAdmin):
    list_display = ("__str__", "ai_check_enabled", "response_window_seconds", "updated_at")

    def has_add_permission(self, request):
        return not AppSettings.objects.exists()

    def has_delete_permission(self, request, obj=None):
        return False


class OutboundAttachmentInline(admin.TabularInline):
    model = OutboundAttachment
    extra = 0


@admin.register(OutboundMessage)
class OutboundMessageAdmin(admin.ModelAdmin):
    list_display = ("task", "client", "channel", "kind", "status", "file_count", "created_at")
    list_filter = ("channel", "status", "kind")
    inlines = [OutboundAttachmentInline]


@admin.register(ProductionTier)
class ProductionTierAdmin(admin.ModelAdmin):
    list_display = ("scale", "min_words", "max_words", "bonus")
    list_filter = ("scale",)


@admin.register(WorkDay)
class WorkDayAdmin(admin.ModelAdmin):
    list_display = (
        "user", "date", "status", "work_mode", "check_in", "check_out",
        "late_minutes", "work_minutes", "words", "needs_review",
    )
    list_filter = ("status", "work_mode", "needs_review", "off_site")
    search_fields = ("user__username",)
    date_hierarchy = "date"


@admin.register(AttendanceEvent)
class AttendanceEventAdmin(admin.ModelAdmin):
    """Read-only on purpose: punches are evidence, not editable records."""

    list_display = ("user", "kind", "at", "within_geofence", "distance_m", "ip")
    list_filter = ("kind", "within_geofence", "source")
    search_fields = ("user__username",)
    date_hierarchy = "at"

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False


@admin.register(AttendanceEdit)
class AttendanceEditAdmin(admin.ModelAdmin):
    """The trail that makes a corrected day trustworthy. Nobody edits it."""

    list_display = ("work_day", "actor", "field", "old_value", "new_value", "created_at")
    search_fields = ("work_day__user__username", "reason")

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False


@admin.register(ShiftTemplate)
class ShiftTemplateAdmin(admin.ModelAdmin):
    list_display = ("name", "name_ar", "start_time", "end_time", "break_minutes", "is_active")


@admin.register(OfficeLocation)
class OfficeLocationAdmin(admin.ModelAdmin):
    list_display = ("name", "latitude", "longitude", "radius_meters", "is_active")


@admin.register(AuthorizedDevice)
class AuthorizedDeviceAdmin(admin.ModelAdmin):
    list_display = ("user", "label", "status", "first_seen", "last_seen")
    list_filter = ("status",)
    search_fields = ("user__username", "fingerprint")


@admin.register(OvertimeClaim)
class OvertimeClaimAdmin(admin.ModelAdmin):
    list_display = ("user", "date", "minutes", "hourly_rate", "amount", "status")
    list_filter = ("status",)
    search_fields = ("user__username",)


class VacancyQuestionInline(admin.TabularInline):
    model = VacancyQuestion
    extra = 0


@admin.register(Vacancy)
class VacancyAdmin(admin.ModelAdmin):
    list_display = ("code", "title", "department", "status", "employment_type", "created_at")
    list_filter = ("status", "department", "employment_type", "work_mode")
    search_fields = ("code", "title")
    inlines = [VacancyQuestionInline]


@admin.register(RecruitmentQuestion)
class RecruitmentQuestionAdmin(admin.ModelAdmin):
    list_display = ("text", "department", "kind", "maps_to", "is_active")
    list_filter = ("kind", "department", "is_active")
    search_fields = ("text",)


class CandidateAnswerInline(admin.TabularInline):
    model = CandidateAnswer
    extra = 0
    readonly_fields = ("answered_at",)


@admin.register(Candidate)
class CandidateAdmin(admin.ModelAdmin):
    list_display = (
        "code", "full_name", "vacancy", "status", "source",
        "identity_revealed", "applied_at",
    )
    list_filter = ("status", "source", "identity_revealed", "department")
    search_fields = ("code", "full_name", "phone", "email")
    inlines = [CandidateAnswerInline]


@admin.register(Interview)
class InterviewAdmin(admin.ModelAdmin):
    list_display = ("candidate", "scheduled_at", "interviewer", "kind", "total_score")
    list_filter = ("kind",)


@admin.register(CandidateTest)
class CandidateTestAdmin(admin.ModelAdmin):
    list_display = ("candidate", "title", "department", "reviewer", "total_score", "marked_at")
    list_filter = ("department",)


@admin.register(CandidateSession)
class CandidateSessionAdmin(admin.ModelAdmin):
    """The bot's own cursor. Useful when a conversation went sideways."""

    list_display = ("contact", "candidate", "vacancy", "state", "step", "last_message_at")
    list_filter = ("state", "channel")
    search_fields = ("contact",)


@admin.register(Department)
class DepartmentAdmin(admin.ModelAdmin):
    list_display = ("name", "name_ar", "is_active")


@admin.register(RecruitmentSettings)
class RecruitmentSettingsAdmin(admin.ModelAdmin):
    list_display = ("__str__", "bot_enabled", "updated_at")

    def has_add_permission(self, request):
        return not RecruitmentSettings.objects.exists()

    def has_delete_permission(self, request, obj=None):
        return False


@admin.register(ProbationReview)
class ProbationReviewAdmin(admin.ModelAdmin):
    list_display = ("user", "stage", "due_date", "outcome", "score", "reviewer")
    list_filter = ("stage", "outcome")
    search_fields = ("user__username",)


@admin.register(LeaveRequest)
class LeaveRequestAdmin(admin.ModelAdmin):
    list_display = (
        "user", "kind", "start_date", "end_date", "status", "applied_at",
    )
    list_filter = ("kind", "status")
    search_fields = ("user__username",)
    date_hierarchy = "start_date"


@admin.register(ClientComplaint)
class ClientComplaintAdmin(admin.ModelAdmin):
    list_display = ("summary", "translator", "client", "severity", "happened_on", "resolved")
    list_filter = ("severity", "resolved")
    search_fields = ("summary", "translator__username")


@admin.register(SalaryPlan)
class SalaryPlanAdmin(admin.ModelAdmin):
    list_display = ("name", "extra_word_rate", "fixed_allowance", "is_active")
    list_filter = ("is_active",)


@admin.register(SalaryChangeRequest)
class SalaryChangeRequestAdmin(admin.ModelAdmin):
    """Read-only: a salary moves through the request flow, never from here."""

    list_display = (
        "user", "current_amount", "new_amount", "effective_from", "status", "decided_by",
    )
    list_filter = ("status",)

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False


@admin.register(Violation)
class ViolationAdmin(admin.ModelAdmin):
    list_display = ("user", "date", "kind", "status", "penalty_days", "penalty_amount")
    list_filter = ("kind", "status")
    search_fields = ("user__username", "reason")


class PayrollLineInline(admin.TabularInline):
    model = PayrollLine
    extra = 0
    readonly_fields = ("user", "base_salary", "production_bonus", "deductions", "net")


@admin.register(PayrollPeriod)
class PayrollPeriodAdmin(admin.ModelAdmin):
    list_display = ("label", "status", "computed_at", "approved_by")
    list_filter = ("status",)
    inlines = [PayrollLineInline]


@admin.register(PayrollSettings)
class PayrollSettingsAdmin(admin.ModelAdmin):
    list_display = ("__str__", "working_days_per_month", "daily_target_words", "updated_at")

    def has_add_permission(self, request):
        return not PayrollSettings.objects.exists()

    def has_delete_permission(self, request, obj=None):
        return False


admin.site.register([
    Shift, ClientRequirement, Assignment, ChatRoom, Notification,
    RatingEvent, AICheckResult, AuditLog, SalaryRecord, ScheduleOverride,
])

admin.site.site_header = "Eagle administration"
admin.site.site_title = "Eagle"
