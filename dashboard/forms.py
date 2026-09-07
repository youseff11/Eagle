"""Forms used by the Eagle dashboard."""

from django import forms
from django.contrib.auth.forms import UserCreationForm

from .models import (
    AppSettings,
    Client,
    ClientRequirement,
    Role,
    Shift,
    Task,
    User,
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
        )
        widgets = {
            "client": forms.Select(attrs={"class": "input"}),
            "title": forms.TextInput(attrs={"class": "input"}),
            "description": forms.Textarea(attrs={"class": "input", "rows": 3}),
            "source_lang": forms.TextInput(attrs={"class": "input", "placeholder": "EN"}),
            "target_lang": forms.TextInput(attrs={"class": "input", "placeholder": "AR"}),
            "priority": forms.Select(attrs={"class": "input"}),
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
    class Meta:
        model = AppSettings
        fields = (
            "ai_check_enabled", "claude_api_key", "claude_model",
            "response_window_seconds", "deadline_warning_minutes",
            "penalty_value", "max_rating", "rate_keywords",
            "whatsapp_verify_token", "whatsapp_access_token",
            "whatsapp_phone_number_id", "webhook_shared_secret",
            "imap_host", "imap_port", "imap_user", "imap_password", "imap_folder",
            "simulation_enabled", "poll_ms",
        )
        widgets = {
            "claude_api_key": forms.PasswordInput(
                attrs={"class": "input", "dir": "ltr"}, render_value=True
            ),
            "imap_password": forms.PasswordInput(
                attrs={"class": "input", "dir": "ltr"}, render_value=True
            ),
            "rate_keywords": forms.Textarea(attrs={"class": "input", "rows": 2}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        for name, field in self.fields.items():
            if isinstance(field.widget, (forms.TextInput, forms.NumberInput, forms.EmailInput)):
                field.widget.attrs.setdefault("class", "input")


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
