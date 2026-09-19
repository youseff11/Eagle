"""Forms used by the Eagle dashboard."""

from django import forms
from django.contrib.auth.forms import UserCreationForm

from .models import (
    AppSettings,
    Client,
    ClientRequirement,
    OfficeLocation,
    PayrollSettings,
    ProductionTier,
    Role,
    SalaryRecord,
    ScheduleOverride,
    Shift,
    ShiftTemplate,
    Task,
    User,
    Violation,
    WorkDay,
)

DATETIME_INPUT_FORMATS = ["%Y-%m-%dT%H:%M", "%Y-%m-%d %H:%M", "%Y-%m-%d %H:%M:%S"]


class MultipleFileInput(forms.ClearableFileInput):
    """Django refuses ``multiple`` on the stock widget; opt in explicitly."""

    allow_multiple_selected = True


class MultipleFileField(forms.FileField):
    def __init__(self, *args, **kwargs):
        kwargs.setdefault(
            "widget", MultipleFileInput(attrs={"class": "input", "multiple": True})
        )
        super().__init__(*args, **kwargs)

    def clean(self, data, initial=None):
        single = super().clean
        if isinstance(data, (list, tuple)):
            return [single(item, initial) for item in data]
        return single(data, initial)


class DateTimeLocalField(forms.DateTimeField):
    widget = forms.DateTimeInput(attrs={"type": "datetime-local", "class": "input"})

    def __init__(self, *args, **kwargs):
        kwargs.setdefault("input_formats", DATETIME_INPUT_FORMATS)
        super().__init__(*args, **kwargs)


class TaskForm(forms.ModelForm):
    deadline = DateTimeLocalField(required=False)

    class Meta:
        model = Task
        fields = (
            "client", "title", "description", "source_lang",
            "target_lang", "priority", "deadline",
            # The job's size is what the accounts side later reads as the
            # translator's production, so it is captured with the task itself.
            "word_count", "is_difficult", "is_secondary_language",
        )
        widgets = {
            "client": forms.Select(attrs={"class": "input"}),
            "title": forms.TextInput(attrs={"class": "input"}),
            "description": forms.Textarea(attrs={"class": "input", "rows": 3}),
            "source_lang": forms.TextInput(attrs={"class": "input", "placeholder": "EN"}),
            "target_lang": forms.TextInput(attrs={"class": "input", "placeholder": "AR"}),
            "priority": forms.Select(attrs={"class": "input"}),
            "word_count": forms.NumberInput(
                attrs={"class": "input", "dir": "ltr", "min": 0, "placeholder": "3000"}
            ),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["client"].queryset = Client.objects.filter(is_active=True)


class ClientForm(forms.ModelForm):
    class Meta:
        model = Client
        fields = ("name", "company", "phone", "email", "country", "admin_notes", "is_active")
        widgets = {
            "name": forms.TextInput(attrs={"class": "input"}),
            "company": forms.TextInput(attrs={"class": "input"}),
            "phone": forms.TextInput(attrs={"class": "input", "dir": "ltr"}),
            "email": forms.EmailInput(attrs={"class": "input", "dir": "ltr"}),
            "country": forms.TextInput(attrs={"class": "input"}),
            "admin_notes": forms.Textarea(attrs={"class": "input", "rows": 3}),
        }


class RequirementForm(forms.ModelForm):
    class Meta:
        model = ClientRequirement
        fields = ("kind", "text")
        widgets = {
            "kind": forms.Select(attrs={"class": "input"}),
            "text": forms.Textarea(attrs={"class": "input", "rows": 2}),
        }


class StaffCreateForm(UserCreationForm):
    class Meta:
        model = User
        fields = (
            "username", "first_name", "last_name", "email", "phone",
            "role", "team_lead", "languages",
            "employment_type", "work_mode", "schedule_kind",
        )
        widgets = {
            "username": forms.TextInput(attrs={"class": "input", "dir": "ltr"}),
            "first_name": forms.TextInput(attrs={"class": "input"}),
            "last_name": forms.TextInput(attrs={"class": "input"}),
            "email": forms.EmailInput(attrs={"class": "input", "dir": "ltr"}),
            "phone": forms.TextInput(attrs={"class": "input", "dir": "ltr"}),
            "role": forms.Select(attrs={"class": "input"}),
            "team_lead": forms.Select(attrs={"class": "input"}),
            "languages": forms.TextInput(attrs={"class": "input"}),
            "employment_type": forms.Select(attrs={"class": "input"}),
            "work_mode": forms.Select(attrs={"class": "input"}),
            "schedule_kind": forms.Select(attrs={"class": "input"}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["team_lead"].queryset = User.objects.filter(role=Role.TEAM_LEAD)
        self.fields["team_lead"].required = False
        for name in ("password1", "password2"):
            if name in self.fields:
                self.fields[name].widget.attrs.update({"class": "input", "dir": "ltr"})


class StaffEditForm(forms.ModelForm):
    class Meta:
        model = User
        fields = (
            "first_name", "last_name", "email", "phone", "role",
            "team_lead", "languages", "is_active", "force_offline", "rating",
            "employment_type", "work_mode", "schedule_kind",
            "attendance_enabled", "attendance_manager",
        )
        widgets = {
            "first_name": forms.TextInput(attrs={"class": "input"}),
            "last_name": forms.TextInput(attrs={"class": "input"}),
            "email": forms.EmailInput(attrs={"class": "input", "dir": "ltr"}),
            "phone": forms.TextInput(attrs={"class": "input", "dir": "ltr"}),
            "role": forms.Select(attrs={"class": "input"}),
            "team_lead": forms.Select(attrs={"class": "input"}),
            "languages": forms.TextInput(attrs={"class": "input"}),
            "rating": forms.NumberInput(attrs={"class": "input", "step": "0.125", "dir": "ltr"}),
            "employment_type": forms.Select(attrs={"class": "input"}),
            "work_mode": forms.Select(attrs={"class": "input"}),
            "schedule_kind": forms.Select(attrs={"class": "input"}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["team_lead"].queryset = User.objects.filter(role=Role.TEAM_LEAD)
        self.fields["team_lead"].required = False


class ShiftForm(forms.ModelForm):
    """One roster row: which day, which shift, and where it is worked.

    Either a template or a pair of times - the template is the normal path, so
    editing "Shift 1" moves everybody on it; typed times are what a custom
    schedule needs.
    """

    class Meta:
        model = Shift
        fields = (
            "weekday", "template", "start_time", "end_time",
            "work_mode", "required_minutes", "is_active",
        )
        widgets = {
            "weekday": forms.Select(attrs={"class": "input"}),
            "template": forms.Select(attrs={"class": "input"}),
            "start_time": forms.TimeInput(attrs={"class": "input", "type": "time"}),
            "end_time": forms.TimeInput(attrs={"class": "input", "type": "time"}),
            "work_mode": forms.Select(attrs={"class": "input"}),
            "required_minutes": forms.NumberInput(attrs={"class": "input", "dir": "ltr", "min": 0}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["template"].queryset = ShiftTemplate.objects.filter(is_active=True)
        self.fields["template"].required = False
        self.fields["template"].empty_label = "— جدول مخصص —"

    def clean(self):
        data = super().clean()
        if not data.get("template") and not (data.get("start_time") and data.get("end_time")):
            raise forms.ValidationError("اختار شيفت جاهز، أو اكتب وقت البداية والنهاية.")
        return data


class ShiftTemplateForm(forms.ModelForm):
    class Meta:
        model = ShiftTemplate
        fields = (
            "name", "name_ar", "start_time", "end_time",
            "break_minutes", "sort_order", "is_active",
        )
        widgets = {
            "name": forms.TextInput(attrs={"class": "input", "dir": "ltr"}),
            "name_ar": forms.TextInput(attrs={"class": "input"}),
            "start_time": forms.TimeInput(attrs={"class": "input", "type": "time"}),
            "end_time": forms.TimeInput(attrs={"class": "input", "type": "time"}),
            "break_minutes": forms.NumberInput(attrs={"class": "input", "dir": "ltr", "min": 0}),
            "sort_order": forms.NumberInput(attrs={"class": "input", "dir": "ltr", "min": 0}),
        }


class ScheduleOverrideForm(forms.ModelForm):
    """Move one date without touching the standing roster."""

    class Meta:
        model = ScheduleOverride
        fields = (
            "date", "is_day_off", "template", "start_time", "end_time",
            "work_mode", "required_minutes", "reason",
        )
        widgets = {
            "date": forms.DateInput(attrs={"class": "input", "type": "date"}),
            "template": forms.Select(attrs={"class": "input"}),
            "start_time": forms.TimeInput(attrs={"class": "input", "type": "time"}),
            "end_time": forms.TimeInput(attrs={"class": "input", "type": "time"}),
            "work_mode": forms.Select(attrs={"class": "input"}),
            "required_minutes": forms.NumberInput(attrs={"class": "input", "dir": "ltr", "min": 0}),
            "reason": forms.TextInput(attrs={"class": "input"}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["template"].queryset = ShiftTemplate.objects.filter(is_active=True)
        self.fields["template"].required = False
        self.fields["template"].empty_label = "— وقت مخصص —"

    def clean(self):
        data = super().clean()
        if data.get("is_day_off"):
            return data
        if not data.get("template") and not (data.get("start_time") and data.get("end_time")):
            raise forms.ValidationError("اختار شيفت، أو اكتب الوقت، أو علّم إن اليوم أجازة.")
        return data


class OfficeLocationForm(forms.ModelForm):
    class Meta:
        model = OfficeLocation
        fields = ("name", "name_ar", "latitude", "longitude", "radius_meters", "is_active")
        widgets = {
            "name": forms.TextInput(attrs={"class": "input", "dir": "ltr"}),
            "name_ar": forms.TextInput(attrs={"class": "input"}),
            "latitude": forms.NumberInput(attrs={"class": "input", "dir": "ltr", "step": "0.000001"}),
            "longitude": forms.NumberInput(attrs={"class": "input", "dir": "ltr", "step": "0.000001"}),
            "radius_meters": forms.NumberInput(attrs={"class": "input", "dir": "ltr", "min": 20}),
        }

    def clean_radius_meters(self):
        radius = self.cleaned_data["radius_meters"]
        if radius < 20:
            raise forms.ValidationError("أقل من 20 متر هيرفض حضور سليم — دقة الـGPS نفسها أوسع من كده.")
        return radius


class AttendanceEditForm(forms.ModelForm):
    """HR's correction of one day. The reason is not optional (section 9)."""

    reason = forms.CharField(
        max_length=250,
        widget=forms.TextInput(attrs={"class": "input", "placeholder": "سبب التعديل"}),
        label="سبب التعديل",
    )

    class Meta:
        model = WorkDay
        fields = (
            "status", "work_mode", "check_in", "check_out",
            "break_minutes", "absence_reason", "note",
        )
        widgets = {
            "status": forms.Select(attrs={"class": "input"}),
            "work_mode": forms.Select(attrs={"class": "input"}),
            "check_in": forms.DateTimeInput(attrs={"class": "input", "type": "datetime-local"}),
            "check_out": forms.DateTimeInput(attrs={"class": "input", "type": "datetime-local"}),
            "break_minutes": forms.NumberInput(attrs={"class": "input", "dir": "ltr", "min": 0}),
            "absence_reason": forms.TextInput(attrs={"class": "input"}),
            "note": forms.TextInput(attrs={"class": "input"}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["check_in"].input_formats = DATETIME_INPUT_FORMATS
        self.fields["check_out"].input_formats = DATETIME_INPUT_FORMATS
        self.fields["check_in"].required = False
        self.fields["check_out"].required = False

    def clean(self):
        data = super().clean()
        start, end = data.get("check_in"), data.get("check_out")
        if start and end and end <= start:
            self.add_error("check_out", "الانصراف لازم يكون بعد الحضور.")
        if data.get("status") in ("unexcused", "excused") and not data.get("absence_reason"):
            self.add_error("absence_reason", "سبب الغياب مطلوب.")
        return data


class SettingsForm(forms.ModelForm):
    """The admin panel's settings. ``group_creator_roles`` is stored as a
    comma-separated string but edited as checkboxes, so it is swapped for a
    MultipleChoiceField and joined back on save."""

    GROUP_ROLE_CHOICES = (
        ("operation", "الأوبريشن · Operation"),
        ("team_lead", "التيم ليدر · Team leader"),
        ("translator", "المترجم · Translator"),
    )

    group_creator_roles = forms.MultipleChoiceField(
        choices=GROUP_ROLE_CHOICES,
        required=False,
        widget=forms.CheckboxSelectMultiple,
        label="مين يقدر يعمل جروب مع عميل",
        help_text="الأدمن دايمًا يقدر — مش هينفع يتشال من هنا.",
    )

    def clean_group_creator_roles(self):
        roles = self.cleaned_data.get("group_creator_roles") or []
        # The admin is always allowed; storing it keeps the value honest for
        # anyone reading the column directly.
        return ",".join(["admin"] + [r for r in roles if r != "admin"])

    class Meta:
        model = AppSettings
        fields = (
            "ai_check_enabled", "claude_api_key", "claude_model",
            "response_window_seconds", "deadline_warning_minutes",
            "penalty_value", "max_rating", "rate_keywords",
            "whatsapp_verify_token", "whatsapp_access_token",
            "whatsapp_phone_number_id", "whatsapp_app_secret", "whatsapp_api_version",
            "webhook_shared_secret",
            "imap_host", "imap_port", "imap_user", "imap_password", "imap_folder",
            "smtp_host", "smtp_port", "smtp_user", "smtp_password",
            "smtp_from", "smtp_use_tls",
            "simulation_enabled", "poll_ms",
            "group_creator_roles",
        )
        widgets = {
            "claude_api_key": forms.PasswordInput(
                attrs={"class": "input", "dir": "ltr"}, render_value=True
            ),
            "imap_password": forms.PasswordInput(
                attrs={"class": "input", "dir": "ltr"}, render_value=True
            ),
            "smtp_password": forms.PasswordInput(
                attrs={"class": "input", "dir": "ltr"}, render_value=True
            ),
            "whatsapp_access_token": forms.PasswordInput(
                attrs={"class": "input", "dir": "ltr"}, render_value=True
            ),
            "whatsapp_app_secret": forms.PasswordInput(
                attrs={"class": "input", "dir": "ltr"}, render_value=True
            ),
            "rate_keywords": forms.Textarea(attrs={"class": "input", "rows": 2}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        for name, field in self.fields.items():
            if isinstance(field.widget, (forms.TextInput, forms.NumberInput, forms.EmailInput)):
                field.widget.attrs.setdefault("class", "input")

        # The model stores "admin,operation"; the checkboxes want a list.
        instance = getattr(self, "instance", None)
        if instance is not None and not self.is_bound:
            self.initial["group_creator_roles"] = [
                r for r in instance.group_roles if r != "admin"
            ]


class SimulateMessageForm(forms.Form):
    CHANNELS = (("whatsapp", "WhatsApp"), ("email", "Email"))

    channel = forms.ChoiceField(
        choices=CHANNELS, widget=forms.Select(attrs={"class": "input"})
    )
    sender_identity = forms.CharField(
        label="Phone / Email",
        widget=forms.TextInput(attrs={"class": "input", "dir": "ltr", "placeholder": "+201000000000"}),
    )
    subject = forms.CharField(
        required=False, widget=forms.TextInput(attrs={"class": "input"})
    )
    body = forms.CharField(widget=forms.Textarea(attrs={"class": "input", "rows": 4}))
    files = MultipleFileField(required=False)


class AICheckForm(forms.Form):
    source_text = forms.CharField(
        required=False, widget=forms.Textarea(attrs={"class": "input", "rows": 6})
    )
    translated_text = forms.CharField(
        required=False, widget=forms.Textarea(attrs={"class": "input", "rows": 6})
    )


# ---------------------------------------------------------------------------
# Accounts
# ---------------------------------------------------------------------------

class PayrollSettingsForm(forms.ModelForm):
    """The contract, as editable numbers. Nothing here is hard-coded anywhere
    else, so changing a band or a bonus never needs a deploy."""

    class Meta:
        model = PayrollSettings
        fields = (
            "daily_hours", "working_days_per_month", "monthly_leave_allowance",
            "daily_target_words", "secondary_daily_target_words",
            "monthly_target_words", "monthly_alert_words",
            "extra_leave_penalty_days", "unexcused_penalty_days",
            "quality_penalty_days", "low_output_penalty_days",
            "unexcused_escalation_count",
            "target_miss_penalty", "discipline_bonus", "target_bonus",
            "bonuses_need_approval",
            # -- attendance (section 7: none of this may be hard-coded) -----
            "grace_minutes", "early_leave_grace_minutes",
            "break_minutes_allowed", "break_counts_as_work",
            "geofence_radius_m", "off_site_policy", "checkout_needs_location",
            "device_check_enabled", "unknown_device_policy",
            "overtime_enabled", "overtime_min_minutes", "overtime_hourly_rate",
            "overtime_multiplier", "overtime_needs_approval",
            "missing_checkin_after_minutes", "missing_checkout_after_minutes",
            "short_hours_alert_minutes",
        )
        widgets = {
            "off_site_policy": forms.Select(attrs={"class": "input"}),
            "unknown_device_policy": forms.Select(attrs={"class": "input"}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        for field in self.fields.values():
            if isinstance(field.widget, (forms.TextInput, forms.NumberInput)):
                field.widget.attrs.setdefault("class", "input")
                field.widget.attrs.setdefault("dir", "ltr")

    def clean(self):
        data = super().clean()
        days = data.get("working_days_per_month")
        daily = data.get("daily_target_words")
        monthly = data.get("monthly_target_words")
        alert = data.get("monthly_alert_words")
        # A monthly target above what the working days can physically produce
        # would make the target bonus unreachable by arithmetic, not by effort.
        if days and daily and monthly and monthly > days * daily:
            self.add_error("monthly_target_words", (
                f"أكبر من {days} يوم × {daily} كلمة = {days * daily}. "
                "التارجت مش هيتحقق مهما حصل."
            ))
        if monthly and alert and alert > monthly:
            self.add_error("monthly_alert_words", "حد التنبيه لازم يكون أقل من التارجت.")

        # A grace window as long as the shift would mean nobody is ever late.
        grace = data.get("grace_minutes")
        if grace is not None and grace > 120:
            self.add_error("grace_minutes", "فترة سماح أكبر من ساعتين معناها مفيش تأخير أصلًا.")
        radius = data.get("geofence_radius_m")
        if radius is not None and radius < 20:
            self.add_error(
                "geofence_radius_m",
                "أقل من 20 متر هيرفض حضور سليم — دقة الـGPS نفسها أوسع من كده.",
            )
        return data


class ProductionTierForm(forms.ModelForm):
    class Meta:
        model = ProductionTier
        fields = ("scale", "min_words", "max_words", "bonus")
        widgets = {
            "scale": forms.Select(attrs={"class": "input"}),
            "min_words": forms.NumberInput(attrs={"class": "input", "dir": "ltr"}),
            "max_words": forms.NumberInput(attrs={"class": "input", "dir": "ltr"}),
            "bonus": forms.NumberInput(attrs={"class": "input", "dir": "ltr", "step": "0.01"}),
        }

    def clean(self):
        data = super().clean()
        low, high = data.get("min_words"), data.get("max_words")
        if low is not None and high is not None and high <= low:
            self.add_error("max_words", "لازم يكون أكبر من بداية الشريحة.")
        return data


class SalaryRecordForm(forms.ModelForm):
    class Meta:
        model = SalaryRecord
        fields = ("amount", "effective_from", "note")
        widgets = {
            "amount": forms.NumberInput(attrs={"class": "input", "dir": "ltr", "step": "0.01"}),
            "effective_from": forms.DateInput(attrs={"class": "input", "type": "date"}),
            "note": forms.TextInput(attrs={"class": "input"}),
        }


class WorkDayForm(forms.ModelForm):
    """The admin's attendance sheet.

    ``words`` is here because the job log only carries word counts from now
    on, and a month recorded before that still has to be payable. The moment a
    day has jobs, the refresh takes the number over and this box stops being
    the source - which is what the help text says. The translator never sees
    this form, so the contract's rule still holds: they do not type their own
    production anywhere.
    """

    class Meta:
        model = WorkDay
        fields = (
            "date", "status", "check_in", "check_out",
            "late_minutes", "early_leave_minutes", "words",
            "is_secondary_language", "difficult_file", "absence_reason", "note",
        )
        widgets = {
            "words": forms.NumberInput(attrs={"class": "input", "dir": "ltr", "min": 0}),
            "date": forms.DateInput(attrs={"class": "input", "type": "date"}),
            "status": forms.Select(attrs={"class": "input"}),
            "check_in": forms.DateTimeInput(
                attrs={"class": "input", "type": "datetime-local"}
            ),
            "check_out": forms.DateTimeInput(
                attrs={"class": "input", "type": "datetime-local"}
            ),
            "late_minutes": forms.NumberInput(attrs={"class": "input", "dir": "ltr"}),
            "early_leave_minutes": forms.NumberInput(attrs={"class": "input", "dir": "ltr"}),
            "absence_reason": forms.TextInput(attrs={"class": "input"}),
            "note": forms.TextInput(attrs={"class": "input"}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["check_in"].input_formats = DATETIME_INPUT_FORMATS
        self.fields["check_out"].input_formats = DATETIME_INPUT_FORMATS

    def clean(self):
        data = super().clean()
        status = data.get("status")
        if status in ("unexcused", "excused") and not data.get("absence_reason"):
            self.add_error("absence_reason", "سبب الغياب مطلوب.")
        return data


class ViolationForm(forms.ModelForm):
    """A deduction someone is proposing. It is worth nothing until approved."""

    class Meta:
        model = Violation
        fields = ("user", "task", "date", "kind", "penalty_days", "penalty_amount", "reason")
        widgets = {
            "user": forms.Select(attrs={"class": "input"}),
            "task": forms.Select(attrs={"class": "input"}),
            "date": forms.DateInput(attrs={"class": "input", "type": "date"}),
            "kind": forms.Select(attrs={"class": "input"}),
            "penalty_days": forms.NumberInput(
                attrs={"class": "input", "dir": "ltr", "step": "0.25"}
            ),
            "penalty_amount": forms.NumberInput(
                attrs={"class": "input", "dir": "ltr", "step": "0.01"}
            ),
            "reason": forms.TextInput(attrs={"class": "input"}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["user"].queryset = User.objects.filter(
            role=Role.TRANSLATOR, is_active=True
        )
        self.fields["task"].required = False
        self.fields["task"].queryset = Task.objects.order_by("-created_at")[:200]

    def clean(self):
        data = super().clean()
        if not data.get("penalty_days") and not data.get("penalty_amount"):
            self.add_error("penalty_days", "حدد خصم بالأيام أو بالمبلغ.")
        return data


class TaskWordsForm(forms.ModelForm):
    """What the job actually was. This is where production enters the system."""

    class Meta:
        model = Task
        fields = ("word_count", "is_difficult", "is_secondary_language")
        widgets = {
            "word_count": forms.NumberInput(attrs={"class": "input", "dir": "ltr", "min": 0}),
        }
