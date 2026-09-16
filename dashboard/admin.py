"""Django-admin registration (the day-to-day UI is the dashboard itself)."""

from django.contrib import admin
from django.contrib.auth.admin import UserAdmin as BaseUserAdmin

from .models import (
    AICheckResult,
    AppSettings,
    Assignment,
    AuditLog,
    OutboundMessage,
    ChatAttachment,
    ChatMessage,
    ChatRoom,
    Client,
    ClientRequirement,
    InboundMessage,
    MessageAttachment,
    Notification,
    OutboundAttachment,
    PayrollLine,
    PayrollPeriod,
    PayrollSettings,
    ProductionTier,
    RatingEvent,
    SalaryRecord,
    Shift,
    Task,
    User,
    Violation,
    WorkDay,
)


@admin.register(User)
class UserAdmin(BaseUserAdmin):
    list_display = ("username", "get_full_name", "role", "team_lead", "rating", "is_active")
    list_filter = ("role", "is_active", "force_offline")
    fieldsets = BaseUserAdmin.fieldsets + (
        ("Eagle", {
            "fields": (
                "role", "team_lead", "phone", "languages", "rating",
                "force_offline", "last_seen", "display_name_ar",
                "ui_lang", "ui_theme",
            )
        }),
    )
    add_fieldsets = BaseUserAdmin.add_fieldsets + (
        ("Eagle", {"fields": ("role", "team_lead", "phone")}),
    )


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
    list_display = ("user", "date", "status", "words", "is_secondary_language", "difficult_file")
    list_filter = ("status", "is_secondary_language", "difficult_file")
    search_fields = ("user__username",)
    date_hierarchy = "date"


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
    RatingEvent, AICheckResult, AuditLog, SalaryRecord,
])

admin.site.site_header = "Eagle administration"
admin.site.site_title = "Eagle"
