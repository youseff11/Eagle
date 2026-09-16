"""Forms used by the Eagle dashboard."""

from django import forms
from django.contrib.auth.forms import UserCreationForm

from .models import (
    AppSettings,
    Client,
    ClientRequirement,
    PayrollSettings,
    ProductionTier,
    Role,
    SalaryRecord,
    Shift,
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
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["team_lead"].queryset = User.objects.filter(role=Role.TEAM_LEAD)
        self.fields["team_lead"].required = False


class ShiftForm(forms.ModelForm):
    class Meta:
        model = Shift
        fields = ("weekday", "start_time", "end_time", "is_active")
        widgets = {
            "weekday": forms.Select(attrs={"class": "input"}),
            "start_time": forms.TimeInput(attrs={"class": "input", "type": "time"}),
            "end_time": forms.TimeInput(attrs={"class": "input", "type": "time"}),
        }


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
        )

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
