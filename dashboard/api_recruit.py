"""``/api/v1/hr/`` - recruitment, the pipeline side: the board, vacancies and the questions the bot asks, the question bank, the rules.

The pages are ``views.hr_recruitment``, ``hr_vacancies``, ``hr_vacancy``, ``hr_questions`` (and ``hr_department_add``) and
``hr_recruitment_settings``. HR and the admin open them (``can_recruit``), exactly as on the classic pages.

Rules that matter on these pages:

* The privacy rule of section 3: nothing a candidate reads carries the company's name until HR has deliberately revealed it. The
  enforcement is ``recruitment.outbound_text``, not these doors; what they do is say so when it is not armed - silence would
  read as safety.
* The questions are HR's to choose, vacancy by vacancy, in the order HR gives them. Nothing forces a department's questions on a
  vacancy; the department only helps find one.
* A GET changes nothing; a form's rules are the classic form's.
"""

from django.db.models import Count
from django.http import JsonResponse
from django.shortcuts import get_object_or_404
from django.utils import timezone

from . import api_forms, identity, recruitment, services
from .api_forms import named
from .api_hr import _digits
from .api_people import can_recruit
from .api_v1 import BadBody, _error, _object, _stamp, _two, endpoint
from .forms import DepartmentForm, RecruitmentQuestionForm, RecruitmentSettingsForm, VacancyForm
from .models import (
    AnswerTarget, AppSettings, Candidate, CandidateSource, Department, Interview, InterviewKind, QuestionKind,
    RecruitmentQuestion, RecruitmentSettings, Vacancy, VacancyQuestion, VacancyStatus,
)
from .templatetags.eagle_tags import CANDIDATE_STATUS_MAP, EMPLOYMENT_MAP, WORK_MODE_MAP

#: The board lists this many: the classic page's own numbers.
MAX_RECENT = 15
MAX_WAITING = 10
MAX_APPLICANTS = 30
#: The most days a vacancy may stay open from now (ten years is not a deadline, it is a typo).
MAX_DEADLINE_DAYS = 3650

SOURCE_MAP = {
    CandidateSource.WHATSAPP: ("واتساب", "WhatsApp"),
    CandidateSource.EMAIL: ("إيميل", "Email"),
    CandidateSource.WEBSITE: ("الموقع", "Website"),
    CandidateSource.LINKEDIN: ("لينكد إن", "LinkedIn"),
    CandidateSource.ADVERT: ("إعلان وظيفة", "Job advertisement"),
    CandidateSource.REFERRAL: ("ترشيح", "Referral"),
    CandidateSource.OTHER: ("حاجة تانية", "Other"),
}
INTERVIEW_KIND_MAP = {
    InterviewKind.ONLINE: ("أونلاين", "Online"),
    InterviewKind.OFFICE: ("في المكتب", "At the office"),
}
VACANCY_STATUS_MAP = {
    VacancyStatus.DRAFT: ("wait", "مسودة", "Draft"),
    VacancyStatus.OPEN: ("ok", "مفتوحة", "Open"),
    VacancyStatus.CLOSED: ("dead", "مقفولة", "Closed"),
}
QUESTION_KIND_MAP = {
    QuestionKind.TEXT: ("نص", "Text"),
    QuestionKind.CHOICE: ("اختيار واحد", "Multiple choice (one)"),
    QuestionKind.MULTI: ("اختيار متعدد", "Multiple select"),
    QuestionKind.YES_NO: ("نعم / لا", "Yes / No"),
    QuestionKind.NUMBER: ("رقم", "Number"),
    QuestionKind.DATE: ("تاريخ", "Date"),
    QuestionKind.FILE: ("ملف", "File upload"),
    QuestionKind.DROPDOWN: ("قايمة منسدلة", "Dropdown"),
}
TARGET_MAP = {
    AnswerTarget.NONE: ("إجابة بس", "Just an answer"),
    AnswerTarget.FULL_NAME: ("اسم المرشح", "Candidate name"),
    AnswerTarget.EMAIL: ("الإيميل", "E-mail"),
    AnswerTarget.EXPERIENCE: ("سنين الخبرة", "Years of experience"),
    AnswerTarget.LANGUAGES: ("اللغات", "Languages"),
    AnswerTarget.SKILLS: ("المهارات", "Skills"),
    AnswerTarget.EXPECTED_SALARY: ("الراتب المتوقع", "Expected salary"),
    AnswerTarget.CV: ("الـCV", "CV"),
}

VACANCY_TEXT = {
    "title": ("المسمى الوظيفي", "Job title"),
    "department": ("القسم", "Department"),
    "openings": ("عدد الشواغر", "Openings"),
    "required_experience": ("الخبرة المطلوبة", "Required experience"),
    "required_languages": ("اللغات المطلوبة", "Required languages"),
    "required_skills": ("المهارات المطلوبة", "Required skills"),
    "salary_min": ("أقل راتب", "Salary from"),
    "salary_max": ("أعلى راتب", "Salary to"),
    "employment_type": ("نوع التوظيف", "Employment type"),
    "work_mode": ("نظام العمل", "Work mode"),
    "shifts": ("الشيفتات المتاحة", "Available shifts"),
    "job_description": ("وصف الوظيفة", "Job description"),
    "requirements": ("المطلوب", "Requirements"),
    "deadline_days": ("الإعلان يقفل بعد (يوم)", "Closes in (days)"),
    "status": ("الحالة", "Status"),
}
VACANCY_HINT = {
    "shifts": (
        "البوت بيعرض دول بس. شيفت واحد = سؤال نعم/لا، وأكتر = اختيار بالأرقام.",
        "The bot offers exactly these. One shift becomes a yes/no; several become a numbered choice.",
    ),
    "deadline_days": (
        "بالأيام. سيبها فاضية يعني سيب الميعاد زي ما هو، وصفر يعني من غير ميعاد.",
        "In days. Leave it empty to keep the date as it is; zero means no deadline.",
    ),
}
VACANCY_CHOICES = {
    "employment_type": {key: pair for key, pair in EMPLOYMENT_MAP.items()},
    "work_mode": {key: pair for key, pair in WORK_MODE_MAP.items()},
    "status": {key: (ar, en) for key, (_tone, ar, en) in VACANCY_STATUS_MAP.items()},
}


def _badge(table, value):
    tone, ar, en = table.get(value, ("", value, value))
    return {"value": value, "tone": tone, "ar": ar, "en": en}


def candidate_row(candidate):
    """A candidate as the lists draw one. The phone is HR's to see, as on the classic page; nothing else of the person."""
    return {
        "code": candidate.code,
        "name": candidate.display_name,
        "vacancy": candidate.vacancy.title if candidate.vacancy_id else None,
        "vacancy_code": candidate.vacancy.code if candidate.vacancy_id else None,
        "phone": candidate.phone,
        "source": _two(SOURCE_MAP, candidate.source),
        "status": _badge(CANDIDATE_STATUS_MAP, candidate.status),
        "applied_on": candidate.applied_at.date().isoformat(),
        "anonymous": not candidate.identity_revealed,
        "shift": candidate.shift_choice,
    }


def read_deadline_days(values):
    """``(values without the deadline box, the days or None)`` from a request's values; ``None`` days means "left alone".

    The classic deadline box is three inputs of its own (``DeadlineInput``); here it is one number, in days, and the form still
    reads it through its own widget.
    """
    values = dict(values)
    if "deadline_days" not in values:
        return values, None
    raw = values.pop("deadline_days")
    if raw is None or raw == "":
        return values, None
    if isinstance(raw, bool) or not isinstance(raw, (int, str)):
        raise api_forms.BadValues("bad_value", "deadline_days")
    text = str(raw).strip()
    if not (text.isascii() and text.isdecimal()) or int(text) > MAX_DEADLINE_DAYS:
        raise api_forms.BadValues("bad_value", "deadline_days")
    return values, int(text)


def with_deadline(data, days, was=""):
    """The form's input with the deadline boxes laid in: ``days`` from now, or blank, which keeps ``was`` (what the page drew).

    The classic page carried the current deadline in a hidden box, and a blank box meant "leave it": without it a save that
    never mentioned the deadline would have wiped it.
    """
    data["deadline_days"] = "" if days is None else str(days)
    data["deadline_hours"] = ""
    data["deadline_minutes"] = ""
    data["deadline_was"] = was
    return data


def _vacancy_form(instance=None):
    fields = [one for one in api_forms.describe(VacancyForm(instance=instance)) if one["name"] != "deadline"]
    status_at = [one["name"] for one in fields].index("status")
    fields.insert(status_at, {
        "name": "deadline_days", "label": "Closes in (days)", "kind": "number", "required": False, "help": "", "disabled": False,
        "ltr": True, "min": 0, "value": "",
    })
    return named(fields, VACANCY_TEXT, VACANCY_HINT, choices=VACANCY_CHOICES)


# ---------------------------------------------------------------------------
# The board
# ---------------------------------------------------------------------------

@endpoint("GET")
@can_recruit
def board(request):
    """The pipeline at a glance: the counts, the latest applicants, today's interviews and who waits for the owner."""
    conf = RecruitmentSettings.load()
    app = AppSettings.load()
    today = timezone.localdate()
    return JsonResponse({
        "ok": True,
        "counts": recruitment.dashboard_counts(),
        "recent": [candidate_row(one) for one in Candidate.objects.select_related("vacancy")[:MAX_RECENT]],
        "today_interviews": [
            {
                "candidate": {"code": one.candidate.code, "name": one.candidate.display_name},
                "kind": _two(INTERVIEW_KIND_MAP, one.kind),
                "at": _stamp(one.scheduled_at, ""),
            }
            for one in Interview.objects.filter(scheduled_at__date=today).select_related("candidate", "interviewer")
        ],
        "waiting_owner": [candidate_row(one) for one in Candidate.objects.filter(status="owner_approval").select_related("vacancy")[:MAX_WAITING]],
        # If nothing is configured to redact, section 3 is not being enforced and the screen says so rather than implying it is.
        "privacy_armed": bool(conf.term_list),
        "bot_enabled": conf.bot_enabled,
        "recruit_number": app.recruit_number_display,
        "can": {"approve": request.user.can_approve_hiring},
    })


# ---------------------------------------------------------------------------
# Vacancies
# ---------------------------------------------------------------------------

def _vacancy_row(row):
    return {
        "code": row.code,
        "title": row.title,
        "department": row.department.label if row.department_id else None,
        "work_mode": _two(WORK_MODE_MAP, row.work_mode),
        "applicants": row.applicants,
        "status": _badge(VACANCY_STATUS_MAP, row.status),
    }


@endpoint("GET")
@can_recruit
def vacancies(request):
    """Every vacancy with how many applied: ``?status=draft|open|closed``; and the blank form that adds one."""
    rows = Vacancy.objects.select_related("department").annotate(applicants=Count("candidates"))
    if request.GET.get("status"):
        rows = rows.filter(status=request.GET["status"])
    return JsonResponse({
        "ok": True,
        "rows": [_vacancy_row(one) for one in rows],
        "statuses": [_badge(VACANCY_STATUS_MAP, value) for value, _label in VacancyStatus.choices],
        "form": _vacancy_form(),
    })


def _vacancy_input(request, instance=None):
    """``(form, None)`` for a vacancy form filled in from ``{"values": {...}}`` and valid, else ``(None, the answer to give)``."""
    try:
        values = _object(request).get("values", {})
        if not isinstance(values, dict):
            raise BadBody
        values, days = read_deadline_days(values)
        data = api_forms.form_data(VacancyForm, values, instance=instance)
    except (BadBody, api_forms.BadValues):
        return None, _error(400, "bad_body")
    was = instance.deadline.isoformat() if instance is not None and instance.deadline else ""
    with_deadline(data, days, was)
    form = VacancyForm(data, instance=instance)
    if not form.is_valid():
        return None, api_forms.invalid(form)
    return form, None


@endpoint("POST")
@can_recruit
def vacancy_create(request):
    """Add a vacancy (``{"values": {...}}``); its code comes back so the page can go on to choose the bot's questions."""
    form, refused = _vacancy_input(request)
    if refused:
        return refused
    row = form.save(commit=False)
    row.created_by = request.user
    row.save()
    form.save_m2m()
    services.log(request.user, "recruitment.vacancy.create", row.code, row.title)
    return JsonResponse({"ok": True, "code": row.code})


@endpoint("GET")
@can_recruit
def vacancy(request, code):
    """One vacancy: its details, the questions the bot will ask in order, the questions it could be given, and who applied."""
    row = get_object_or_404(Vacancy.objects.select_related("department"), code=code)
    chosen = row.question_links.values_list("question_id", flat=True)
    pool = RecruitmentQuestion.objects.filter(is_active=True).exclude(pk__in=chosen)
    if row.department_id:
        # The department narrows the list; it never dictates it (section 11).
        from django.db.models import Q

        pool = pool.filter(Q(department_id=row.department_id) | Q(department__isnull=True))
    return JsonResponse({
        "ok": True,
        "vacancy": {
            "code": row.code,
            "title": row.title,
            "status": _badge(VACANCY_STATUS_MAP, row.status),
            "applicants": row.applicant_count,
            "deadline": row.deadline.isoformat() if row.deadline else None,
        },
        "form": _vacancy_form(row),
        "links": [
            {
                "id": link.pk,
                "order": link.order,
                "required": link.is_required,
                "question": {
                    "id": link.question_id,
                    "text": link.question.text,
                    "kind": _two(QUESTION_KIND_MAP, link.question.kind),
                    "maps_to": _two(TARGET_MAP, link.question.maps_to) if link.question.maps_to else None,
                },
            }
            for link in row.questions_in_order()
        ],
        "pool": [
            {"id": one.pk, "department": one.department.label if one.department_id else None, "text": one.text[:60]}
            for one in pool.select_related("department")
        ],
        "candidates": [candidate_row(one) for one in row.candidates.select_related("vacancy")[:MAX_APPLICANTS]],
    })


@endpoint("POST")
@can_recruit
def vacancy_save(request, code):
    """Change a vacancy (``{"values": {...}}``, only the boxes that changed; a deadline left out is left alone)."""
    row = get_object_or_404(Vacancy, code=code)
    form, refused = _vacancy_input(request, instance=row)
    if refused:
        return refused
    form.save()
    services.log(request.user, "recruitment.vacancy.update", row.code)
    return JsonResponse({"ok": True})


@endpoint("POST")
@can_recruit
def vacancy_question_add(request, code):
    """Give the vacancy a question from the bank (``{"question": id}``). A question it already has, or an inactive one, is not added."""
    row = get_object_or_404(Vacancy, code=code)
    try:
        which = _object(request).get("question")
    except BadBody:
        return _error(400, "bad_body")
    if isinstance(which, bool) or not isinstance(which, int) or not 0 < which < 2 ** 63:
        return _error(400, "bad_body")
    question = get_object_or_404(RecruitmentQuestion, pk=which, is_active=True)
    link, made = VacancyQuestion.objects.get_or_create(
        vacancy=row, question=question, defaults={"order": row.question_links.count() + 1, "is_required": True},
    )
    if made:
        services.log(request.user, "recruitment.vacancy.question", row.code)
    return JsonResponse({"ok": True, "id": link.pk, "added": made})


@endpoint("POST")
@can_recruit
def vacancy_questions_order(request, code):
    """Order and "required" for the vacancy's questions in one save (``{"rows": [{"id": 3, "order": 1, "required": true}]}``)."""
    row = get_object_or_404(Vacancy, code=code)
    try:
        rows = _object(request).get("rows")
        if not isinstance(rows, list) or len(rows) > 200:
            raise BadBody
        for one in rows:
            if (
                not isinstance(one, dict) or isinstance(one.get("id"), bool) or not isinstance(one.get("id"), int)
                or isinstance(one.get("order"), bool) or not isinstance(one.get("order"), int) or not 0 <= one["order"] <= 32000
                or not isinstance(one.get("required"), bool)
            ):
                raise BadBody
    except BadBody:
        return _error(400, "bad_body")
    wanted = {one["id"]: one for one in rows}
    links = list(row.question_links.all())
    for link in links:
        if link.pk in wanted:
            link.order = wanted[link.pk]["order"]
            link.is_required = wanted[link.pk]["required"]
            link.save(update_fields=["order", "is_required"])
    return JsonResponse({"ok": True, "saved": sum(1 for link in links if link.pk in wanted)})


@endpoint("POST")
@can_recruit
def vacancy_question_delete(request, pk):
    link = get_object_or_404(VacancyQuestion.objects.select_related("vacancy"), pk=pk)
    code = link.vacancy.code
    link.delete()
    services.log(request.user, "recruitment.vacancy.question.remove", code)
    return JsonResponse({"ok": True, "code": code})


# ---------------------------------------------------------------------------
# The question bank
# ---------------------------------------------------------------------------

QUESTION_TEXT = {
    "text": ("السؤال بالعربي", "Question (Arabic)"),
    "text_en": ("بالإنجليزي", "English"),
    "kind": ("النوع", "Type"),
    "department": ("القسم", "Department"),
    "options_text": ("الاختيارات (واحد في كل سطر)", "Options (one per line)"),
    "maps_to": ("بيملا حقل في ملف المرشح", "Fills a profile field"),
    "help_text": ("تلميح للمرشح", "Hint for the candidate"),
    "sort_order": ("الترتيب", "Sort"),
    "is_active": ("شغال", "Active"),
}
QUESTION_HINT = {
    "maps_to": (
        "اختار الحقل هنا والنظام هياخد الإجابة لوحده. من غير كده الإجابة بتتسجل كإجابة بس.",
        "Tag the field and the answer lands there by itself. Untagged, it is stored as an answer only.",
    ),
}
DEPARTMENT_TEXT = {"name": ("الاسم", "Name"), "name_ar": ("بالعربي", "Arabic")}


def _question_json(row):
    return {
        "id": row.pk,
        "text": row.text,
        "options": row.option_list,
        "department": row.department.label if row.department_id else None,
        "kind": _two(QUESTION_KIND_MAP, row.kind),
        "maps_to": _two(TARGET_MAP, row.maps_to) if row.maps_to else None,
        "is_active": row.is_active,
    }


@endpoint("GET")
@can_recruit
def questions(request):
    """The bank (``?department=<id>``), the form (blank, or the question ``?edit=<id>`` names) and the departments with their counts."""
    rows = RecruitmentQuestion.objects.select_related("department")
    if request.GET.get("department"):
        which = _digits(request.GET["department"])
        if which is None:
            return _error(400, "bad_department")
        rows = rows.filter(department_id=which)
    raw = request.GET.get("edit") or ""
    editing = RecruitmentQuestion.objects.filter(pk=raw).first() if raw.isascii() and raw.isdecimal() and len(raw) < 18 else None
    form = named(
        api_forms.describe(RecruitmentQuestionForm(instance=editing)), QUESTION_TEXT, QUESTION_HINT,
        choices={"kind": {key: pair for key, pair in QUESTION_KIND_MAP.items()}, "maps_to": {key: pair for key, pair in TARGET_MAP.items()}},
    )
    return JsonResponse({
        "ok": True,
        "rows": [_question_json(one) for one in rows],
        "editing": editing.pk if editing else None,
        "form": form,
        "departments": [
            {"id": one.pk, "label": one.label, "questions": one.question_count}
            for one in Department.objects.filter(is_active=True).annotate(question_count=Count("questions"))
        ],
        "department_form": named(api_forms.describe(DepartmentForm()), DEPARTMENT_TEXT),
    })


@endpoint("POST")
@can_recruit
def question_save(request):
    """Add a question to the bank, or change one (``{"id": 3, "values": {...}}``). Whoever adds one is written on it."""
    try:
        body = _object(request)
        which = body.get("id")
        values = body.get("values", {})
        if which is not None and (isinstance(which, bool) or not isinstance(which, int) or not 0 < which < 2 ** 63):
            raise BadBody
        if not isinstance(values, dict):
            raise BadBody
    except BadBody:
        return _error(400, "bad_body")
    editing = get_object_or_404(RecruitmentQuestion, pk=which) if which is not None else None
    try:
        data = api_forms.form_data(RecruitmentQuestionForm, values, instance=editing)
    except api_forms.BadValues:
        return _error(400, "bad_body")
    form = RecruitmentQuestionForm(data, instance=editing)
    if not form.is_valid():
        return api_forms.invalid(form)
    row = form.save(commit=False)
    if not row.pk:
        row.created_by = request.user
    row.save()
    services.log(request.user, "recruitment.question.save", str(row.pk), row.text[:80])
    return JsonResponse({"ok": True, "id": row.pk})


@endpoint("POST")
@can_recruit
def department_add(request):
    """Add a department (``{"values": {name, name_ar}}``). It is open from the start: a department that is not is invisible."""
    try:
        values = _object(request).get("values", {})
        if not isinstance(values, dict) or set(values) - {"name", "name_ar"}:
            raise BadBody
        data = api_forms.form_data(DepartmentForm, values)
    except (BadBody, api_forms.BadValues):
        return _error(400, "bad_body")
    data["is_active"] = True
    form = DepartmentForm(data)
    if not form.is_valid():
        return api_forms.invalid(form)
    row = form.save()
    services.log(request.user, "recruitment.department.add", row.name)
    return JsonResponse({"ok": True, "id": row.pk})


# ---------------------------------------------------------------------------
# The rules: the privacy filter, the bot, the probation length
# ---------------------------------------------------------------------------

SETTINGS_TEXT = {
    "redact_terms": ("الكلمات (واحدة في كل سطر)", "Terms (one per line)"),
    "redact_placeholder": ("البديل اللي بيتحط مكانها", "Replacement"),
    "bot_name_ar": ("الاسم اللي المرشح بيشوفه", "Name the candidate sees"),
    "bot_name": ("بالإنجليزي", "English"),
    "session_timeout_hours": ("مهلة المحادثة (ساعة)", "Session timeout (hours)"),
    "probation_days": ("مدة فترة الاختبار (يوم)", "Probation (days)"),
    "greeting_ar": ("رسالة الترحيب", "Greeting"),
    "closing_ar": ("رسالة الختام", "Closing"),
    "bot_enabled": ("البوت شغال", "The bot is on"),
}
SETTINGS_HINT = {
    "greeting_ar": ("سيبها فاضية والنظام هيستخدم الصيغة الافتراضية.", "Leave it empty for the built-in wording."),
}


def _settings_body(conf, user):
    app = AppSettings.load()
    terms = conf.term_list
    return {
        "ok": True,
        "form": named(api_forms.describe(RecruitmentSettingsForm(instance=conf, actor=user)), SETTINGS_TEXT, SETTINGS_HINT),
        # The words that hide the company from a candidate are the owner's to change; HR sees them and cannot.
        "can": {"redact": user.can_approve_hiring},
        "privacy_armed": bool(terms),
        # What the filter makes of a message that names the company: the proof it works, shown beside the list.
        "sample": recruitment.outbound_text(None, "مرحبًا من " + (terms[0] if terms else "—"), conf=conf),
        "line": {"number": app.recruit_number_display, "phone_number_id": bool(app.recruit_phone_number_id)},
    }


@endpoint("GET")
@can_recruit
def recruitment_settings(request):
    """The recruitment rules, whether the identity rule is armed, and the recruitment line (its number; whether its ID is set)."""
    return JsonResponse(_settings_body(RecruitmentSettings.load(), request.user))


def _words(items):
    return ", ".join(items)[:240]


@endpoint("POST")
@can_recruit
def recruitment_settings_save(request):
    """Save the rules (``{"values": {...}}``, only the boxes that changed).

    The words and the stand-in that hide the company from a candidate are the owner's: anybody else who sends either is refused
    (and the refusal is written down, as every refusal is), even with the same value. When the owner changes them, the log
    carries the words that went and the words that came.
    """
    conf = RecruitmentSettings.load()
    try:
        values = _object(request).get("values", {})
        if not isinstance(values, dict):
            raise BadBody
    except BadBody:
        return _error(400, "bad_body")
    owner = request.user.can_approve_hiring
    if not owner and any(name in values for name in RecruitmentSettingsForm.OWNER_ONLY):
        identity.record_denied(request, "recruitment redact rules are the owner's")
        return _error(403, "owner_only")
    try:
        data = api_forms.form_data(RecruitmentSettingsForm, values, instance=conf, form_kwargs={"actor": request.user})
    except api_forms.BadValues:
        return _error(400, "bad_body")
    before_terms, before_stand_in = conf.term_list, conf.redact_placeholder
    form = RecruitmentSettingsForm(data, instance=conf, actor=request.user)
    if not form.is_valid():
        return api_forms.invalid(form)
    form.save()
    services.log(request.user, "recruitment.settings.update")
    conf = RecruitmentSettings.load()
    gone = [word for word in before_terms if word not in conf.term_list]
    came = [word for word in conf.term_list if word not in before_terms]
    if gone or came or conf.redact_placeholder != before_stand_in:
        services.log(
            request.user, "recruitment.redact.update", "",
            f"removed: {_words(gone) or '-'} | added: {_words(came) or '-'} | stand-in: {before_stand_in} -> {conf.redact_placeholder} | armed: {bool(conf.term_list)}",
        )
    return JsonResponse(_settings_body(conf, request.user))
