"""Forms used by the Eagle dashboard."""

from datetime import datetime, timedelta

from django import forms
from django.contrib.auth.forms import UserCreationForm
from django.utils import timezone

from .models import (
    AppSettings,
    Candidate,
    CandidateTest,
    Client,
    ClientRequirement,
    ClientComplaint,
    Department,
    Interview,
    LeaveKind,
    LeaveRequest,
    OfficeLocation,
    PayrollSettings,
    ProductionTier,
    Role,
    ProbationOutcome,
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
    VacancyStatus,
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


# ---------------------------------------------------------------------------
# Deadlines
# ---------------------------------------------------------------------------

#: The units a deadline is entered in, in the order they are shown, with the
#: label each box wears in both languages.
DEADLINE_PARTS = (
    ("days", "يوم", "days"),
    ("hours", "ساعة", "hours"),
    ("minutes", "دقيقة", "minutes"),
)

DEADLINE_SECONDS = {"days": 86400, "hours": 3600, "minutes": 60}


class DeadlineInput(forms.Widget):
    """Days, hours and minutes — not a calendar.

    Nobody is told a date. The client says "in three days", or "by tomorrow
    afternoon", and the calendar then makes you work out which Thursday that
    is while they are still on the phone. So the boxes ask the question the
    client actually answered, and the page works out the date. What gets
    stored is the moment it lands on, exactly as before.

    Three rules, the same everywhere:
      blank    leave the deadline as it is (no deadline, on a new form)
      zeros    no deadline
      numbers  that long from now

    Blank means "leave it alone" so that opening an old record and pressing
    save cannot quietly wipe a deadline that has already passed — a past
    deadline has nothing left to count down, so its boxes come up empty.

    Drawn in Python rather than through a widget template: this project's
    form renderer only sees Django's own templates, and switching
    FORM_RENDERER across the whole site to place three <input>s is not a
    trade worth making.
    """

    def __init__(self, attrs=None, parts=("days", "hours", "minutes"), scope=""):
        super().__init__(attrs)
        self.parts = tuple(parts)
        #: Prefix for the element ids. Two forms on one page can ask for the
        #: same deadline - the team leader's, once while handing the job
        #: over and once to change it afterwards - and they post the same
        #: field names on purpose. Only the ids have to differ.
        self.scope = scope

    def value_from_datadict(self, data, files, name):
        typed = {p: (data.get(f"{name}_{p}") or "").strip() for p in self.parts}
        # What the deadline was when the page was drawn, so that "blank"
        # can mean "leave it alone" without the field having to see initial.
        typed["was"] = (data.get(f"{name}_was") or "").strip()
        return typed

    def value_omitted_from_data(self, data, files, name):
        return all(f"{name}_{part}" not in data for part in self.parts)

    def boxes(self, value):
        """``({part: text}, was)`` — what to draw in each box."""
        empty = {part: "" for part in self.parts}
        if isinstance(value, dict):
            # The form came back (invalid, most likely). Keep what was typed.
            return {p: value.get(p, "") for p in self.parts}, value.get("was", "")
        if not value:
            return empty, ""

        was = value.isoformat()
        if isinstance(value, datetime):
            left = int((value - timezone.now()).total_seconds())
        else:
            left = (value - timezone.localdate()).days * DEADLINE_SECONDS["days"]
        if left <= 0:
            # Already passed. Blank, which reads as "leave it alone".
            return empty, was

        boxes, rest = {}, left
        for part in ("days", "hours", "minutes"):
            size = DEADLINE_SECONDS[part]
            if part not in self.parts:
                continue
            # The last box shown carries whatever the bigger ones left over,
            # so a days-only field says "3" for anything inside the third day.
            if part == self.parts[-1]:
                boxes[part] = str(rest // size)
            else:
                boxes[part], rest = str(rest // size), rest % size
        return boxes, was

    def render(self, name, value, attrs=None, renderer=None):
        from django.utils.html import escape
        from django.utils.safestring import mark_safe

        boxes, was = self.boxes(value)
        cells = "".join(
            '<label class="dur__part">'
            f'<input class="input dur__num" type="number" min="0" step="1"'
            f' inputmode="numeric" name="{escape(name)}_{part}"'
            f' id="id_{escape(self.scope)}{escape(name)}_{part}"'
            f' value="{escape(boxes.get(part, ""))}">'
            f'<span class="dur__unit" data-ar="{escape(ar)}" data-en="{escape(en)}">'
            f'{escape(ar)}</span>'
            "</label>"
            for part, ar, en in DEADLINE_PARTS if part in self.parts
        )
        return mark_safe(
            '<div class="dur" data-deadline>'
            f"{cells}"
            f'<input type="hidden" name="{escape(name)}_was" value="{escape(was)}">'
            '<div class="dur__out mono" data-deadline-out></div>'
            "</div>"
        )


class DeadlineField(forms.Field):
    """A deadline as "in how long", stored as the moment it lands on.

    ``as_date`` for the model fields that keep a date and not a time; those
    get the days box on its own, because hours typed into a field that
    cannot hold them are hours quietly thrown away.
    """

    def __init__(self, *args, as_date=False, parts=("days", "hours", "minutes"), **kwargs):
        self.as_date = as_date
        self.parts = tuple(parts)
        kwargs.setdefault("widget", DeadlineInput(parts=self.parts))
        super().__init__(*args, **kwargs)

    def clean(self, value):
        if not isinstance(value, dict):
            # Not from our widget (a test posting a datetime, say). Take it.
            if value in self.empty_values:
                if self.required:
                    raise forms.ValidationError(
                        self.error_messages["required"], code="required"
                    )
                return None
            return value

        total, typed = 0, False
        for part in self.parts:
            raw = (value.get(part) or "").strip()
            if not raw:
                continue
            typed = True
            try:
                number = int(raw)
            except ValueError:
                raise forms.ValidationError("اكتب رقم صحيح.", code="invalid")
            if number < 0:
                raise forms.ValidationError("مفيش ديدلاين بالسالب.", code="invalid")
            total += number * DEADLINE_SECONDS[part]

        if not typed:
            # Blank: leave whatever is there. On a new form there is nothing.
            kept = self.was(value.get("was", ""))
            if kept is None and self.required:
                raise forms.ValidationError(
                    self.error_messages["required"], code="required"
                )
            return kept
        if total <= 0:
            # Zeros, deliberately typed: no deadline.
            if self.required:
                raise forms.ValidationError(
                    self.error_messages["required"], code="required"
                )
            return None

        moment = timezone.now() + timedelta(seconds=total)
        return timezone.localtime(moment).date() if self.as_date else moment

    def was(self, raw):
        """The deadline the page was drawn with, back from the hidden field."""
        from django.utils.dateparse import parse_date, parse_datetime

        raw = (raw or "").strip()
        if not raw:
            return None
        if self.as_date:
            return parse_date(raw)
        moment = parse_datetime(raw)
        if moment is not None and timezone.is_naive(moment):
            moment = timezone.make_aware(moment, timezone.get_current_timezone())
        return moment

    def has_changed(self, initial, data):
        # The boxes are redrawn from the deadline every time the page loads,
        # so "same as it was" is the normal case and not a change.
        try:
            return self.clean(data) != initial
        except forms.ValidationError:
            return True


#: Languages offered on the task form - (code, Arabic, English). The code is
#: what is stored, so every task reads "EN → AR" the same way, and a list
#: filtered by language finds all of them. Free text is still allowed: a pair
#: that is not here can be typed, and it is then offered next time too
#: (``language_choices``).
LANGUAGES = (
    ("AR", "العربية", "Arabic"),
    ("EN", "الإنجليزية", "English"),
    ("FR", "الفرنسية", "French"),
    ("DE", "الألمانية", "German"),
    ("IT", "الإيطالية", "Italian"),
    ("ES", "الإسبانية", "Spanish"),
    ("PT", "البرتغالية", "Portuguese"),
    ("RU", "الروسية", "Russian"),
    ("TR", "التركية", "Turkish"),
    ("ZH", "الصينية", "Chinese"),
    ("JA", "اليابانية", "Japanese"),
    ("KO", "الكورية", "Korean"),
    ("FA", "الفارسية", "Persian"),
    ("UR", "الأردو", "Urdu"),
    ("HI", "الهندية", "Hindi"),
    ("HE", "العبرية", "Hebrew"),
    ("NL", "الهولندية", "Dutch"),
    ("SV", "السويدية", "Swedish"),
    ("EL", "اليونانية", "Greek"),
    ("PL", "البولندية", "Polish"),
    ("ID", "الإندونيسية", "Indonesian"),
    ("MS", "الماليزية", "Malay"),
)

#: The ones drawn as one-tap buttons under the two fields.
QUICK_LANGUAGES = ("AR", "EN", "FR", "DE", "IT", "ES")


def _language_code(value):
    """"en", "English", "انجليزي", "الإنجليزية" -> "EN". Anything else as typed.

    Arabic is compared with its alefs, ya and ta marbuta folded and a leading
    "ال" dropped, so "الانجليزيه" and "إنجليزي" land on the same code.
    """
    import re

    raw = (value or "").strip()
    if not raw:
        return ""

    def forms_of(text):
        """The word with and without a leading "ال", its endings trimmed."""
        text = re.sub(r"[\u064B-\u0652\u0640]", "", text.lower().strip())
        text = re.sub("[\u0623\u0625\u0622]", "\u0627", text)
        text = text.replace("\u0629", "\u0647").replace("\u0649", "\u064a")
        out = set()
        for word in (text, text[2:] if text.startswith("\u0627\u0644") else text):
            out.add(re.sub(r"(\u064a\u0647|\u064a)$", "", word))
        return out

    wanted = forms_of(raw)
    for code, ar, en in LANGUAGES:
        if wanted & ({code.lower()} | forms_of(en) | forms_of(ar)):
            return code
    return raw.upper() if len(raw) <= 3 else raw


def language_choices():
    """The list offered in the fields: the known languages, then any other
    value already used on a task, so a pair typed once is offered again."""
    known = {code for code, _ar, _en in LANGUAGES}
    rows = [{"code": code, "ar": ar, "en": en} for code, ar, en in LANGUAGES]
    used = set()
    for pair in Task.objects.values_list("source_lang", "target_lang").distinct()[:500]:
        used.update(v.strip() for v in pair if v and v.strip())
    rows += [{"code": v, "ar": v, "en": v} for v in sorted(used - known)]
    return rows


class TaskForm(forms.ModelForm):
    deadline = DeadlineField(required=False)

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
            # ``list`` ties both to the <datalist> on the page: a dropdown of
            # suggestions that still lets anything be typed.
            "source_lang": forms.TextInput(attrs={
                "class": "input", "placeholder": "EN", "list": "langOptions",
                "autocomplete": "off", "dir": "ltr",
            }),
            "target_lang": forms.TextInput(attrs={
                "class": "input", "placeholder": "AR", "list": "langOptions",
                "autocomplete": "off", "dir": "ltr",
            }),
            "priority": forms.Select(attrs={"class": "input"}),
            "word_count": forms.NumberInput(
                attrs={"class": "input", "dir": "ltr", "min": 0, "placeholder": "3000"}
            ),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["client"].queryset = Client.objects.filter(is_active=True)

    # Whatever was typed - "en", "English", "انجليزي" - is kept as the code.
    def clean_source_lang(self):
        return _language_code(self.cleaned_data.get("source_lang"))

    def clean_target_lang(self):
        return _language_code(self.cleaned_data.get("target_lang"))


class ClientForm(forms.ModelForm):
    """The client's identity. Every number and address here is one client.

    A number that already belongs to another client is refused rather than
    shared: two clients answering to one number would split the messages
    between two codes, which is the very thing the extra fields are for.
    """

    class Meta:
        model = Client
        fields = (
            "name", "company", "phone", "extra_phones", "email", "extra_emails",
            "country", "admin_notes", "is_active",
        )
        labels = {
            "phone": "رقم الواتساب الأساسي",
            "extra_phones": "أرقام تانية لنفس العميل",
            "email": "الإيميل الأساسي",
            "extra_emails": "إيميلات تانية لنفس العميل",
        }
        help_texts = {
            "extra_phones": "رقم في كل سطر. أي رسالة من أي رقم فيهم بتروح لنفس كود العميل.",
            "extra_emails": "إيميل في كل سطر. أي ميل من أي عنوان فيهم بيروح لنفس كود العميل.",
        }
        widgets = {
            "name": forms.TextInput(attrs={"class": "input"}),
            "company": forms.TextInput(attrs={"class": "input"}),
            "phone": forms.TextInput(attrs={"class": "input", "dir": "ltr"}),
            "extra_phones": forms.Textarea(attrs={
                "class": "input", "rows": 3, "dir": "ltr", "placeholder": "+201234567890",
            }),
            "email": forms.EmailInput(attrs={"class": "input", "dir": "ltr"}),
            "extra_emails": forms.Textarea(attrs={
                "class": "input", "rows": 3, "dir": "ltr", "placeholder": "name@example.com",
            }),
            "country": forms.TextInput(attrs={"class": "input"}),
            "admin_notes": forms.Textarea(attrs={"class": "input", "rows": 3}),
        }

    def _taken(self, found, value):
        return forms.ValidationError(
            f"{value} متسجل بالفعل للعميل {found.code}.", code="taken",
        )

    def clean_extra_phones(self):
        raw = self.cleaned_data.get("extra_phones", "")
        numbers = Client.split_phones(raw)
        bad = [
            line for line in Client._lines(raw)
            if len("".join(ch for ch in line if ch.isdigit())) < Client.PHONE_KEY_DIGITS
        ]
        if bad:
            raise forms.ValidationError(f"رقم مش صحيح: {bad[0]}")
        pk = self.instance.pk
        for number in numbers:
            found = Client.find_by_phone(number, exclude_pk=pk)
            if found:
                raise self._taken(found, number)
        return "\n".join(numbers)

    def clean_extra_emails(self):
        from django.core.validators import validate_email
        from django.core.exceptions import ValidationError as CoreError

        addresses = Client.split_emails(self.cleaned_data.get("extra_emails", ""))
        pk = self.instance.pk
        for address in addresses:
            try:
                validate_email(address)
            except CoreError:
                raise forms.ValidationError(f"إيميل مش صحيح: {address}")
            found = Client.find_by_email(address, exclude_pk=pk)
            if found:
                raise self._taken(found, address)
        return "\n".join(addresses)

    def clean_phone(self):
        phone = (self.cleaned_data.get("phone") or "").strip()
        if phone:
            found = Client.find_by_phone(phone, exclude_pk=self.instance.pk)
            if found:
                raise self._taken(found, phone)
        return phone

    def clean_email(self):
        email = (self.cleaned_data.get("email") or "").strip()
        if email:
            found = Client.find_by_email(email, exclude_pk=self.instance.pk)
            if found:
                raise self._taken(found, email)
        return email

    def clean(self):
        data = super().clean()
        # The main number typed again in the "others" box is the same number,
        # not a second one - drop it quietly.
        phone_key = Client.phone_key(data.get("phone", ""))
        if phone_key and data.get("extra_phones"):
            data["extra_phones"] = "\n".join(
                n for n in data["extra_phones"].split("\n") if Client.phone_key(n) != phone_key
            )
        email = (data.get("email") or "").lower()
        if email and data.get("extra_emails"):
            data["extra_emails"] = "\n".join(
                a for a in data["extra_emails"].split("\n") if a != email
            )
        return data


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
            "recruit_phone_number_id", "recruit_number_display",
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
            # -- leave and performance (sections 20 and 22) -----------------
            "leave_needs_manager", "permission_max_minutes",
            "weight_productivity", "weight_quality",
            "weight_deadline", "weight_attendance",
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

        # A permission longer than the day is a day off wearing another name,
        # and it would skip the leave balance entirely.
        limit = data.get("permission_max_minutes")
        hours = data.get("daily_hours")
        if limit and hours and limit >= int(hours * 60):
            self.add_error(
                "permission_max_minutes",
                "الإذن أطول من يوم الشغل نفسه — ده بقى إجازة، مش إذن.",
            )

        # Every weight at zero leaves nothing to average, so the page would
        # show "not measured" for everybody, for ever.
        weights = [
            data.get("weight_productivity"), data.get("weight_quality"),
            data.get("weight_deadline"), data.get("weight_attendance"),
        ]
        if all(w == 0 for w in weights if w is not None) and any(w is not None for w in weights):
            self.add_error(
                "weight_attendance",
                "كل الأوزان صفر — يبقى مفيش تقييم أصلًا. لازم واحد على الأقل أكبر من صفر.",
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


# ---------------------------------------------------------------------------
# HR / recruitment
# ---------------------------------------------------------------------------

class DepartmentForm(forms.ModelForm):
    class Meta:
        model = Department
        fields = ("name", "name_ar", "is_active")
        widgets = {
            "name": forms.TextInput(attrs={"class": "input", "dir": "ltr"}),
            "name_ar": forms.TextInput(attrs={"class": "input"}),
        }


class RecruitmentQuestionForm(forms.ModelForm):
    """One question for the bank.

    ``options`` is a JSON list in the database but a textarea here - one
    choice per line, which is how a person thinks about a list.
    """

    options_text = forms.CharField(
        required=False,
        widget=forms.Textarea(attrs={"class": "input", "rows": 4}),
        label="الاختيارات (واحد في كل سطر)",
    )

    class Meta:
        model = RecruitmentQuestion
        fields = (
            "text", "text_en", "kind", "department", "maps_to",
            "help_text", "sort_order", "is_active",
        )
        widgets = {
            "text": forms.TextInput(attrs={"class": "input"}),
            "text_en": forms.TextInput(attrs={"class": "input", "dir": "ltr"}),
            "kind": forms.Select(attrs={"class": "input"}),
            "department": forms.Select(attrs={"class": "input"}),
            "maps_to": forms.Select(attrs={"class": "input"}),
            "help_text": forms.TextInput(attrs={"class": "input"}),
            "sort_order": forms.NumberInput(attrs={"class": "input", "dir": "ltr", "min": 0}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["department"].queryset = Department.objects.filter(is_active=True)
        self.fields["department"].required = False
        self.fields["department"].empty_label = "— سؤال عام —"
        if self.instance and self.instance.pk:
            self.fields["options_text"].initial = "\n".join(self.instance.option_list)

    def clean(self):
        data = super().clean()
        kind = data.get("kind")
        lines = [
            line.strip() for line in (data.get("options_text") or "").splitlines()
            if line.strip()
        ]
        if kind in ("choice", "multi", "dropdown") and len(lines) < 2:
            self.add_error("options_text", "النوع ده محتاج اختيارين على الأقل.")
        data["options_list"] = lines
        return data

    def save(self, commit=True):
        row = super().save(commit=False)
        row.options = self.cleaned_data.get("options_list") or []
        if commit:
            row.save()
        return row


class VacancyForm(forms.ModelForm):
    # A vacancy closes on a day, not at a minute, so it gets the days box on
    # its own — see DeadlineField.
    deadline = DeadlineField(required=False, as_date=True, parts=("days",))

    class Meta:
        model = Vacancy
        fields = (
            "title", "department", "openings", "required_experience",
            "required_languages", "required_skills", "salary_min", "salary_max",
            "employment_type", "work_mode", "shifts", "job_description",
            "requirements", "deadline", "status",
        )
        widgets = {
            "title": forms.TextInput(attrs={"class": "input"}),
            "department": forms.Select(attrs={"class": "input"}),
            "openings": forms.NumberInput(attrs={"class": "input", "dir": "ltr", "min": 1}),
            "required_experience": forms.TextInput(attrs={"class": "input"}),
            "required_languages": forms.TextInput(attrs={"class": "input"}),
            "required_skills": forms.TextInput(attrs={"class": "input"}),
            "salary_min": forms.NumberInput(attrs={"class": "input", "dir": "ltr", "step": "0.01"}),
            "salary_max": forms.NumberInput(attrs={"class": "input", "dir": "ltr", "step": "0.01"}),
            "employment_type": forms.Select(attrs={"class": "input"}),
            "work_mode": forms.Select(attrs={"class": "input"}),
            "shifts": forms.CheckboxSelectMultiple(),
            "job_description": forms.Textarea(attrs={"class": "input", "rows": 4}),
            "requirements": forms.Textarea(attrs={"class": "input", "rows": 3}),
            "status": forms.Select(attrs={"class": "input"}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["department"].queryset = Department.objects.filter(is_active=True)
        self.fields["shifts"].queryset = ShiftTemplate.objects.filter(is_active=True)
        self.fields["shifts"].required = False

    def clean(self):
        data = super().clean()
        low, high = data.get("salary_min"), data.get("salary_max")
        if low and high and high < low:
            self.add_error("salary_max", "لازم يكون أكبر من أقل راتب.")
        return data


class CandidateForm(forms.ModelForm):
    """HR entering or correcting a candidate by hand (a referral, a walk-in)."""

    class Meta:
        model = Candidate
        fields = (
            "full_name", "phone", "email", "vacancy", "department", "cv",
            "experience_years", "languages", "skills", "expected_salary",
            "shift_choice", "source", "hr_notes", "hr_recommendation",
        )
        widgets = {
            "full_name": forms.TextInput(attrs={"class": "input"}),
            "phone": forms.TextInput(attrs={"class": "input", "dir": "ltr"}),
            "email": forms.EmailInput(attrs={"class": "input", "dir": "ltr"}),
            "vacancy": forms.Select(attrs={"class": "input"}),
            "department": forms.Select(attrs={"class": "input"}),
            "cv": forms.ClearableFileInput(attrs={"class": "input"}),
            "experience_years": forms.TextInput(attrs={"class": "input"}),
            "languages": forms.TextInput(attrs={"class": "input"}),
            "skills": forms.TextInput(attrs={"class": "input"}),
            "expected_salary": forms.TextInput(attrs={"class": "input", "dir": "ltr"}),
            "shift_choice": forms.TextInput(attrs={"class": "input"}),
            "source": forms.Select(attrs={"class": "input"}),
            "hr_notes": forms.Textarea(attrs={"class": "input", "rows": 4}),
            "hr_recommendation": forms.TextInput(attrs={"class": "input"}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["department"].required = False
        self.fields["vacancy"].required = False
        self.fields["vacancy"].queryset = Vacancy.objects.exclude(
            status=VacancyStatus.CLOSED
        )


class InterviewForm(forms.ModelForm):
    scheduled_at = DateTimeLocalField()

    class Meta:
        model = Interview
        fields = (
            "scheduled_at", "interviewer", "kind", "meeting_link", "location", "notes",
        )
        widgets = {
            "interviewer": forms.Select(attrs={"class": "input"}),
            "kind": forms.Select(attrs={"class": "input"}),
            "meeting_link": forms.TextInput(attrs={"class": "input", "dir": "ltr"}),
            "location": forms.TextInput(attrs={"class": "input"}),
            "notes": forms.Textarea(attrs={"class": "input", "rows": 3}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["interviewer"].queryset = User.objects.filter(is_active=True)
        self.fields["interviewer"].required = False


class InterviewScoreForm(forms.ModelForm):
    """Section 14's five marks. The total is the system's, not a typed number."""

    class Meta:
        model = Interview
        fields = (
            "communication", "experience", "technical", "computer_skills",
            "attitude", "comments",
        )
        widgets = {
            name: forms.NumberInput(
                attrs={"class": "input", "dir": "ltr", "min": 0, "max": 10}
            )
            for name in Interview.SCORE_FIELDS
        } | {"comments": forms.Textarea(attrs={"class": "input", "rows": 3})}

    def clean(self):
        data = super().clean()
        for name in Interview.SCORE_FIELDS:
            value = data.get(name)
            if value is not None and not 0 <= value <= 10:
                self.add_error(name, "من 0 لـ 10.")
        return data


class CandidateTestForm(forms.ModelForm):
    deadline = DeadlineField(required=False)

    class Meta:
        model = CandidateTest
        fields = (
            "title", "department", "brief", "language_pair", "word_count",
            "assignment", "deadline", "reviewer",
        )
        widgets = {
            "title": forms.TextInput(attrs={"class": "input"}),
            "department": forms.Select(attrs={"class": "input"}),
            "brief": forms.Textarea(attrs={"class": "input", "rows": 3}),
            "language_pair": forms.TextInput(attrs={"class": "input", "dir": "ltr"}),
            "word_count": forms.NumberInput(attrs={"class": "input", "dir": "ltr", "min": 0}),
            "assignment": forms.ClearableFileInput(attrs={"class": "input"}),
            "reviewer": forms.Select(attrs={"class": "input"}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["department"].required = False
        self.fields["reviewer"].required = False
        self.fields["reviewer"].queryset = User.objects.filter(
            is_active=True, role__in=(Role.REVIEWER, Role.TEAM_LEAD, Role.ADMIN)
        )


class TestScoreForm(forms.ModelForm):
    class Meta:
        model = CandidateTest
        fields = (
            "accuracy", "grammar", "terminology", "formatting", "instructions",
            "comments", "submission",
        )
        widgets = {
            name: forms.NumberInput(
                attrs={"class": "input", "dir": "ltr", "min": 0, "max": 10}
            )
            for name in CandidateTest.SCORE_FIELDS
        } | {
            "comments": forms.Textarea(attrs={"class": "input", "rows": 3}),
            "submission": forms.ClearableFileInput(attrs={"class": "input"}),
        }

    def clean(self):
        data = super().clean()
        for name in CandidateTest.SCORE_FIELDS:
            value = data.get(name)
            if value is not None and not 0 <= value <= 10:
                self.add_error(name, "من 0 لـ 10.")
        return data


class HireForm(forms.Form):
    """Section 17: what the system still needs that the application did not."""

    role = forms.ChoiceField(
        choices=Role.choices, initial=Role.TRANSLATOR,
        widget=forms.Select(attrs={"class": "input"}), label="الدور",
    )
    job_title = forms.CharField(
        required=False, widget=forms.TextInput(attrs={"class": "input"}),
        label="المسمى الوظيفي",
    )
    joining_date = forms.DateField(
        widget=forms.DateInput(attrs={"class": "input", "type": "date"}),
        label="تاريخ الانضمام",
    )
    salary = forms.DecimalField(
        required=False, max_digits=10, decimal_places=2,
        widget=forms.NumberInput(attrs={"class": "input", "dir": "ltr", "step": "0.01"}),
        label="الراتب الأساسي",
    )
    team_lead = forms.ModelChoiceField(
        queryset=User.objects.none(), required=False,
        widget=forms.Select(attrs={"class": "input"}), label="المدير المباشر",
    )
    username = forms.CharField(
        required=False,
        widget=forms.TextInput(attrs={"class": "input", "dir": "ltr"}),
        label="اسم المستخدم", help_text="سيبه فاضي والنظام هيولّده.",
    )
    password = forms.CharField(
        required=False,
        widget=forms.PasswordInput(attrs={"class": "input", "dir": "ltr"}),
        label="الباسورد", help_text="سيبه فاضي والحساب يتقفل لحد ما تحطه.",
    )

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["team_lead"].queryset = User.objects.filter(
            is_active=True, role=Role.TEAM_LEAD
        )

    def clean_username(self):
        name = (self.cleaned_data.get("username") or "").strip()
        if name and User.objects.filter(username=name).exists():
            raise forms.ValidationError("الاسم ده مستخدم بالفعل.")
        return name


class RecruitmentSettingsForm(forms.ModelForm):
    class Meta:
        model = RecruitmentSettings
        fields = (
            "bot_enabled", "bot_name", "bot_name_ar", "redact_terms",
            "redact_placeholder", "greeting_ar", "closing_ar",
            "session_timeout_hours", "probation_days",
        )
        widgets = {
            "bot_name": forms.TextInput(attrs={"class": "input", "dir": "ltr"}),
            "bot_name_ar": forms.TextInput(attrs={"class": "input"}),
            "redact_terms": forms.Textarea(attrs={"class": "input", "rows": 6}),
            "redact_placeholder": forms.TextInput(attrs={"class": "input"}),
            "greeting_ar": forms.Textarea(attrs={"class": "input", "rows": 4}),
            "closing_ar": forms.Textarea(attrs={"class": "input", "rows": 3}),
            "session_timeout_hours": forms.NumberInput(
                attrs={"class": "input", "dir": "ltr", "min": 1}
            ),
            "probation_days": forms.NumberInput(
                attrs={"class": "input", "dir": "ltr", "min": 0}
            ),
        }


class CandidateMessageForm(forms.Form):
    """HR writing to a candidate. The privacy rule applies to this too."""

    body = forms.CharField(
        widget=forms.Textarea(attrs={"class": "input", "rows": 3}), label="الرسالة"
    )


# ---------------------------------------------------------------------------
# Employee lifecycle - probation, leave, pay
# ---------------------------------------------------------------------------

class LeaveRequestForm(forms.ModelForm):
    """What somebody fills in to ask for time off.

    Permission is the odd one: it is hours inside a single day, so the two
    time fields appear and the end date is forced to match the start.
    """

    class Meta:
        model = LeaveRequest
        fields = ("kind", "start_date", "end_date", "start_time", "end_time", "reason")
        widgets = {
            "kind": forms.Select(attrs={"class": "input"}),
            "start_date": forms.DateInput(attrs={"class": "input", "type": "date"}),
            "end_date": forms.DateInput(attrs={"class": "input", "type": "date"}),
            "start_time": forms.TimeInput(attrs={"class": "input", "type": "time"}),
            "end_time": forms.TimeInput(attrs={"class": "input", "type": "time"}),
            "reason": forms.TextInput(attrs={"class": "input"}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        for name in ("end_date", "start_time", "end_time", "reason"):
            self.fields[name].required = False

    def clean(self):
        data = super().clean()
        kind = data.get("kind")
        start = data.get("start_date")
        end = data.get("end_date") or start
        if kind == LeaveKind.PERMISSION:
            if not (data.get("start_time") and data.get("end_time")):
                raise forms.ValidationError("الإذن محتاج وقت بداية ونهاية.")
            data["end_date"] = start
        elif start and end and end < start:
            self.add_error("end_date", "لازم يكون بعد تاريخ البداية.")
        else:
            data["end_date"] = end
        return data


class LeaveDecisionForm(forms.Form):
    note = forms.CharField(
        required=False, max_length=250,
        widget=forms.TextInput(attrs={"class": "input", "placeholder": "ملاحظة"}),
    )


class ProbationDecisionForm(forms.Form):
    outcome = forms.ChoiceField(
        choices=[
            (value, label) for value, label in ProbationOutcome.choices
            if value != ProbationOutcome.PENDING
        ],
        widget=forms.Select(attrs={"class": "input"}), label="النتيجة",
    )
    score = forms.IntegerField(
        required=False, min_value=0, max_value=10,
        widget=forms.NumberInput(attrs={"class": "input", "dir": "ltr", "min": 0, "max": 10}),
        label="التقييم من 10",
    )
    extend_days = forms.IntegerField(
        required=False, min_value=1, max_value=365, initial=30,
        widget=forms.NumberInput(attrs={"class": "input", "dir": "ltr"}),
        label="تمديد كام يوم",
    )
    notes = forms.CharField(
        required=False,
        widget=forms.Textarea(attrs={"class": "input", "rows": 3}), label="الملاحظات",
    )

    def clean(self):
        data = super().clean()
        if data.get("outcome") == ProbationOutcome.EXTENDED and not data.get("extend_days"):
            self.add_error("extend_days", "اكتب مدة التمديد.")
        return data


class ClientComplaintForm(forms.ModelForm):
    class Meta:
        model = ClientComplaint
        fields = ("client", "task", "translator", "severity", "summary", "detail", "happened_on")
        widgets = {
            "client": forms.Select(attrs={"class": "input"}),
            "task": forms.Select(attrs={"class": "input"}),
            "translator": forms.Select(attrs={"class": "input"}),
            "severity": forms.Select(attrs={"class": "input"}),
            "summary": forms.TextInput(attrs={"class": "input"}),
            "detail": forms.Textarea(attrs={"class": "input", "rows": 3}),
            "happened_on": forms.DateInput(attrs={"class": "input", "type": "date"}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        for name in ("client", "task", "translator", "happened_on", "detail"):
            self.fields[name].required = False
        self.fields["translator"].queryset = User.objects.filter(
            is_active=True, role=Role.TRANSLATOR
        )
        # A complaint is about recent work, so the picker is not the whole
        # history of the company.
        self.fields["task"].queryset = Task.objects.order_by("-created_at")[:200]


class SalaryPlanForm(forms.ModelForm):
    """Every number optional. A blank one keeps the company's."""

    class Meta:
        model = SalaryPlan
        fields = (
            "name", "note", "daily_target_words", "secondary_daily_target_words",
            "monthly_target_words", "extra_word_rate", "fixed_allowance",
            "discipline_bonus", "target_bonus", "target_miss_penalty",
            "working_days_per_month", "monthly_leave_allowance",
            "overtime_hourly_rate", "is_active",
        )
        widgets = {
            "name": forms.TextInput(attrs={"class": "input"}),
            "note": forms.TextInput(attrs={"class": "input"}),
            "extra_word_rate": forms.NumberInput(
                attrs={"class": "input", "dir": "ltr", "step": "0.0001"}
            ),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        for name, field in self.fields.items():
            if isinstance(field.widget, forms.NumberInput):
                field.widget.attrs.setdefault("class", "input")
                field.widget.attrs.setdefault("dir", "ltr")
            if name not in ("name", "is_active", "fixed_allowance"):
                field.required = False

    def clean(self):
        data = super().clean()
        days = data.get("working_days_per_month")
        daily = data.get("daily_target_words")
        monthly = data.get("monthly_target_words")
        # The same arithmetic trap the company rules guard against: a monthly
        # target above what the days can hold is unreachable by construction.
        if days and daily and monthly and monthly > days * daily:
            self.add_error("monthly_target_words", (
                f"أكبر من {days} يوم × {daily} كلمة = {days * daily}."
            ))
        return data


class SalaryChangeRequestForm(forms.Form):
    new_amount = forms.DecimalField(
        max_digits=10, decimal_places=2, min_value=0,
        widget=forms.NumberInput(attrs={"class": "input", "dir": "ltr", "step": "0.01"}),
        label="الراتب الجديد",
    )
    effective_from = forms.DateField(
        widget=forms.DateInput(attrs={"class": "input", "type": "date"}),
        label="ساري من",
    )
    reason = forms.CharField(
        required=False, max_length=250,
        widget=forms.TextInput(attrs={"class": "input"}), label="السبب",
    )


class ReviewScoreForm(forms.Form):
    """The team leader's mark on a finished translation."""

    score = forms.IntegerField(
        min_value=0, max_value=10,
        widget=forms.NumberInput(attrs={"class": "input", "dir": "ltr", "min": 0, "max": 10}),
        label="تقييم المراجعة من 10",
    )
    note = forms.CharField(
        required=False, max_length=250,
        widget=forms.TextInput(attrs={"class": "input"}), label="ملاحظة",
    )
