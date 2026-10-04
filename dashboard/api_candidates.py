"""``/api/v1/hr/`` - recruitment, the candidates' side: the list, a candidate's file, and everything HR does to one.

The pages are ``views.hr_candidates``, ``hr_candidate`` and ``hr_interview_score``. HR and the admin open them
(``can_recruit``), exactly as on the classic pages. The pipeline's rules are ``recruitment.*`` - which move is legal, who is told,
what a message may say - so what the classic page refused is refused here, in the same words.

Rules that matter on these pages:

* A message to a candidate goes through ``recruitment.send_to_candidate`` and nothing else: it is the one place the company's
  name is scrubbed out of what an anonymous candidate reads. Nothing here sends by any other road, and the body is never logged.
* The status moves are ``recruitment.move_status`` - a candidate can only go where the pipeline lets them, and to the owner's
  queue only by being sent there. A hire is not a status: it is ``recruitment.hire`` making the employee.
* Revealing the company to a candidate is logged with who, when and why, and cannot be taken back.
* A file a candidate sent (a CV) or HR attached (a test) is stored under a name that says nothing, whatever it was called: the
  name people give their files is mostly their own. The name it had is kept beside it for the people who may read it.
* A GET changes nothing.
"""

import json
import os
import uuid

from django.db.models import Q
from django.http import JsonResponse
from django.shortcuts import get_object_or_404
from django.utils import timezone

from . import api_forms, recruitment, services
from .api_forms import named
from .api_leave import refusal
from .api_people import can_recruit
from .api_recruit import (
    SOURCE_MAP, INTERVIEW_KIND_MAP, _badge, candidate_row,
)
from .api_v1 import BadBody, _error, _object, _stamp, _text, _two, endpoint
from .forms import CandidateForm, CandidateTestForm, InterviewForm, InterviewScoreForm
from .models import (
    AppSettings, Candidate, CandidateStatus, CandidateTest, Interview, RecruitmentSettings, Vacancy,
)
from .templatetags.eagle_tags import CANDIDATE_STATUS_MAP

#: The list shows this many (the classic page's own number) and says how many there were.
MAX_CANDIDATES = 300
#: The longest search text, and the longest vacancy code, read from the address.
MAX_QUERY = 80
MAX_CODE = 20
#: A document (a CV, a test file): far above any real one, below what would be a way to fill the disk.
MAX_DOC_BYTES = 20 * 1024 * 1024
#: The longest message to a candidate (a WhatsApp text is at most 4096).
MAX_MESSAGE = 4000
#: The longest "values" text a multipart request may carry.
MAX_VALUES_JSON = 40_000
#: The most that a deadline box may hold (days); an hour or a minute box is held to the same.
MAX_DEADLINE_PART = 3650

CANDIDATE_TEXT = {
    "full_name": ("الاسم", "Name"),
    "phone": ("الموبايل", "Phone"),
    "email": ("الإيميل", "E-mail"),
    "vacancy": ("الوظيفة", "Vacancy"),
    "department": ("القسم", "Department"),
    "experience_years": ("الخبرة", "Experience"),
    "languages": ("اللغات", "Languages"),
    "skills": ("المهارات", "Skills"),
    "expected_salary": ("الراتب المتوقع", "Expected salary"),
    "shift_choice": ("الشيفت", "Shift"),
    "source": ("المصدر", "Source"),
    "hr_notes": ("ملاحظات HR", "HR notes"),
    "hr_recommendation": ("توصية HR", "HR recommendation"),
}
INTERVIEW_TEXT = {
    "scheduled_at": ("الموعد", "When"),
    "interviewer": ("المُقابِل", "Interviewer"),
    "kind": ("النوع", "Type"),
    "meeting_link": ("لينك الاجتماع", "Meeting link"),
    "location": ("المكان", "Location"),
    "notes": ("ملاحظات", "Notes"),
}
SCORE_TEXT = {
    "communication": ("التواصل", "Communication"),
    "experience": ("الخبرة", "Experience"),
    "technical": ("التقني", "Technical"),
    "computer_skills": ("الكمبيوتر", "Computer skills"),
    "attitude": ("السلوك", "Attitude"),
    "comments": ("ملاحظات", "Comments"),
}
TEST_TEXT = {
    "title": ("العنوان", "Title"),
    "department": ("القسم", "Department"),
    "brief": ("التعليمات", "Brief"),
    "language_pair": ("زوج اللغات", "Language pair"),
    "word_count": ("عدد الكلمات", "Word count"),
    "reviewer": ("المراجع", "Reviewer"),
    "deadline_days": ("يوم", "Days"),
    "deadline_hours": ("ساعة", "Hours"),
    "deadline_minutes": ("دقيقة", "Minutes"),
}
TEST_HINT = {
    "deadline_days": (
        "المهلة اللي هتديها للمرشح من دلوقتي. سيبها فاضية يعني من غير ميعاد.",
        "How long the candidate gets, starting now. Leave it empty for no deadline.",
    ),
}


class CandidateDataForm(CandidateForm):
    """The candidate form without the CV: a file is not a value in a JSON body, it has a door of its own."""

    class Meta(CandidateForm.Meta):
        fields = tuple(name for name in CandidateForm.Meta.fields if name != "cv")
        widgets = {name: widget for name, widget in CandidateForm.Meta.widgets.items() if name != "cv"}


class TestDataForm(CandidateTestForm):
    """The test form without its file, and with the deadline as three number boxes (see ``read_deadline_parts``)."""

    class Meta(CandidateTestForm.Meta):
        fields = tuple(name for name in CandidateTestForm.Meta.fields if name != "assignment")
        widgets = {name: widget for name, widget in CandidateTestForm.Meta.widgets.items() if name != "assignment"}


# ---------------------------------------------------------------------------
# Reading a request
# ---------------------------------------------------------------------------

def read_deadline_parts(values, parts=("days", "hours", "minutes")):
    """``(values without the deadline boxes, {part: digits or ""})``: a deadline written as how long from now.

    Every box is whole digits (or empty). A box of the form's own deadline widget reads them back, so blank means "none" on a
    new test - there is nothing to keep.
    """
    values = dict(values)
    out = {}
    for part in parts:
        key = f"deadline_{part}"
        raw = values.pop(key, "")
        if raw is None or raw == "":
            out[part] = ""
            continue
        if isinstance(raw, bool) or not isinstance(raw, (int, str)):
            raise api_forms.BadValues("bad_value", key)
        text = str(raw).strip()
        if not (text.isascii() and text.isdecimal()) or int(text) > MAX_DEADLINE_PART:
            raise api_forms.BadValues("bad_value", key)
        out[part] = text
    return values, out


def values_and_file(request, file_field):
    """``(values, upload or None)`` from a JSON body, or from a multipart form: ``values`` as JSON text and the file beside it."""
    if (request.content_type or "").startswith("multipart/"):
        raw = request.POST.get("values", "{}")
        if len(raw) > MAX_VALUES_JSON:
            raise BadBody
        try:
            values = json.loads(raw)
        except (ValueError, RecursionError):
            raise BadBody from None
        if not isinstance(values, dict):
            raise BadBody
        return values, request.FILES.get(file_field)
    values = _object(request).get("values", {})
    if not isinstance(values, dict):
        raise BadBody
    return values, None


def anonymous_upload(upload):
    """The upload under a name that says nothing (the name it came with is the caller's to keep), or ``None`` for one that is empty or too big.

    The extension stays (a browser and the viewer need it), only when it is a short run of letters and digits.
    """
    if upload is None or upload.size == 0 or upload.size > MAX_DOC_BYTES:
        return None
    ext = os.path.splitext(upload.name or "")[1].lower()
    if not (ext and len(ext) <= 8 and ext[1:].isalnum() and ext.isascii()):
        ext = ""
    upload.name = f"{uuid.uuid4().hex}{ext}"
    return upload


def _file_json(field, name):
    """A stored file as the page links it (``/files/...``, never the host behind it), or ``None``."""
    if not field:
        return None
    return {"url": field.url, "name": name or "file"}


# ---------------------------------------------------------------------------
# The list
# ---------------------------------------------------------------------------

@endpoint("GET")
@can_recruit
def candidates(request):
    """Everyone who applied, newest first. ``?status=``, ``?source=``, ``?vacancy=<code>`` and ``?q=`` (name, phone, code, e-mail)."""
    rows = Candidate.objects.select_related("vacancy", "department")
    for name in ("status", "source"):
        value = request.GET.get(name)
        if value:
            rows = rows.filter(**{name: value[:MAX_CODE]})
    if request.GET.get("vacancy"):
        rows = rows.filter(vacancy__code=request.GET["vacancy"][:MAX_CODE])
    query = (request.GET.get("q") or "").strip()[:MAX_QUERY]
    if query:
        rows = rows.filter(
            Q(full_name__icontains=query) | Q(phone__icontains=query) | Q(code__icontains=query) | Q(email__icontains=query)
        )
    total = rows.count()
    return JsonResponse({
        "ok": True,
        "rows": [candidate_row(one) for one in rows[:MAX_CANDIDATES]],
        "total": total,
        "limit": MAX_CANDIDATES,
        "counts": recruitment.dashboard_counts(),
        "statuses": [_badge(CANDIDATE_STATUS_MAP, value) for value, _label in CandidateStatus.choices],
        "sources": [_two(SOURCE_MAP, value) for value in SOURCE_MAP],
        "vacancies": [{"code": one.code, "title": one.title} for one in Vacancy.objects.all()],
    })


# ---------------------------------------------------------------------------
# One candidate
# ---------------------------------------------------------------------------

def _marks(row, fields):
    return {name: getattr(row, name) for name in fields}


def interview_json(row):
    return {
        "id": row.pk,
        "at": _stamp(row.scheduled_at, "%Y-%m-%d"),
        "kind": _two(INTERVIEW_KIND_MAP, row.kind),
        "interviewer": row.interviewer.short_name if row.interviewer_id else None,
        "meeting_link": row.meeting_link,
        "location": row.location,
        "notes": row.notes,
        "evaluated": row.is_evaluated,
        "marks": _marks(row, Interview.SCORE_FIELDS),
        "total": row.total_score,
        "max": row.max_score,
        "comments": row.comments,
    }


def exam_json(row):
    """A candidate's test as HR reads it: the candidate is the page's own, so the names stay."""
    return {
        "id": row.pk,
        "title": row.title,
        "department": row.department.label if row.department_id else None,
        "brief": row.brief,
        "language_pair": row.language_pair,
        "word_count": row.word_count,
        "assignment": _file_json(row.assignment, row.assignment_name),
        "submission": _file_json(row.submission, row.submission_name),
        "submitted_at": _stamp(row.submitted_at, "%m-%d"),
        "deadline": _stamp(row.deadline, "%Y-%m-%d"),
        "overdue": row.is_overdue,
        "reviewer": row.reviewer.short_name if row.reviewer_id else None,
        "marked": row.is_marked,
        "marks": _marks(row, CandidateTest.SCORE_FIELDS),
        "total": row.total_score,
        "max": row.max_score,
        "comments": row.comments,
    }


def _candidate_form(instance):
    return named(
        api_forms.describe(CandidateDataForm(instance=instance)), CANDIDATE_TEXT,
        choices={"source": {value: pair for value, pair in SOURCE_MAP.items()}},
    )


def _interview_form():
    return named(
        api_forms.describe(InterviewForm()), INTERVIEW_TEXT,
        choices={"kind": {value: pair for value, pair in INTERVIEW_KIND_MAP.items()}},
    )


def _deadline_fields():
    """The deadline as the boxes a person fills (days, hours, minutes), in place of the form's own deadline widget."""
    return [
        {
            "name": f"deadline_{part}", "label": part, "kind": "number", "required": False, "help": "", "disabled": False,
            "ltr": True, "min": 0, "value": "",
        }
        for part in ("days", "hours", "minutes")
    ]


def _test_form():
    fields = [one for one in api_forms.describe(TestDataForm()) if one["name"] != "deadline"]
    return named(fields + _deadline_fields(), TEST_TEXT, TEST_HINT)


def candidate_body(candidate, user):
    """Everything on a candidate's page. ``user`` is HR or the admin: the name and the phone are theirs to read."""
    conf = RecruitmentSettings.load()
    return {
        "ok": True,
        "candidate": {
            **candidate_row(candidate),
            "email": candidate.email,
            "department": candidate.department.label if candidate.department_id else None,
            "experience_years": candidate.experience_years,
            "languages": candidate.languages,
            "skills": candidate.skills,
            "expected_salary": candidate.expected_salary,
            "hr_notes": candidate.hr_notes,
            "hr_recommendation": candidate.hr_recommendation,
            "rejection_reason": candidate.rejection_reason,
            "cv": _file_json(candidate.cv, candidate.cv_name or "CV"),
            "identity": {
                "revealed": candidate.identity_revealed,
                "at": _stamp(candidate.identity_revealed_at, "%Y-%m-%d"),
                "by": candidate.identity_revealed_by.short_name if candidate.identity_revealed_by_id else None,
            },
            "owner_decision": {
                "at": _stamp(candidate.owner_decision_at, "%Y-%m-%d"),
                "by": candidate.owner_decision_by.short_name if candidate.owner_decision_by_id else None,
            } if candidate.owner_decision_at else None,
            "hired_user": candidate.hired_user_id,
        },
        "form": _candidate_form(candidate),
        "answers": [
            {
                "order": one.order,
                "question": one.question.text,
                "value": one.value,
                "file": _file_json(one.file, one.file_name),
                "at": _stamp(one.answered_at, "%m-%d"),
            }
            for one in candidate.answers.select_related("question")
        ],
        "interviews": [interview_json(one) for one in candidate.interviews.select_related("interviewer")],
        "tests": [exam_json(one) for one in candidate.tests.select_related("reviewer", "department")],
        # Where this candidate may go from here: the pipeline's own table, minus nothing the engine would refuse.
        "next_statuses": [_badge(CANDIDATE_STATUS_MAP, value) for value in recruitment.ALLOWED_MOVES.get(candidate.status, ())],
        "privacy_armed": bool(conf.term_list),
        # Whether a message can go out: with no recruitment line set it would leave on the client's number.
        "line_ready": bool(AppSettings.load().recruit_phone_number_id),
        "interview_form": _interview_form(),
        "test_form": _test_form(),
        "can": {"hire": candidate.status == CandidateStatus.APPROVED, "mark": user.can_review_tests},
    }


def _candidate(code):
    return get_object_or_404(
        Candidate.objects.select_related("vacancy", "department", "hired_user", "identity_revealed_by", "owner_decision_by"),
        code=code,
    )


@endpoint("GET")
@can_recruit
def candidate(request, code):
    return JsonResponse(candidate_body(_candidate(code), request.user))


@endpoint("POST")
@can_recruit
def candidate_save(request, code):
    """Change the profile (``{"values": {...}}``, only the boxes that changed). The CV has its own door."""
    row = get_object_or_404(Candidate, code=code)
    form, refused = api_forms.filled(request, CandidateDataForm, instance=row)
    if refused:
        return refused
    form.save()
    services.log(request.user, "recruitment.candidate.update", row.code)
    return JsonResponse({"ok": True})


@endpoint("POST")
@can_recruit
def candidate_cv(request, code):
    """Attach a CV (multipart: ``file``). It replaces the one there; the name it came with is kept for the page."""
    row = get_object_or_404(Candidate, code=code)
    upload = request.FILES.get("file")
    original = (upload.name if upload is not None else "")[:200]
    stored = anonymous_upload(upload)
    if stored is None:
        return _error(400, "bad_file")
    row.cv = stored
    row.cv_name = original
    row.save(update_fields=["cv", "cv_name", "updated_at"])
    services.log(request.user, "recruitment.candidate.cv", row.code)
    return JsonResponse({"ok": True})


@endpoint("POST")
@can_recruit
def candidate_status(request, code):
    """Move the candidate along (``{"status": "...", "reason": "..."}``): only where ``recruitment.ALLOWED_MOVES`` lets them."""
    row = get_object_or_404(Candidate, code=code)
    try:
        body = _object(request)
        target = _text(body, "status", 20)
        reason = _text(body, "reason", 250)
    except BadBody:
        return _error(400, "bad_body")
    if target not in CandidateStatus.values:
        return _error(400, "bad_status")
    try:
        recruitment.move_status(row, target, request.user, reason)
    except recruitment.PipelineError as refused:
        return refusal(refused)
    return JsonResponse({"ok": True})


@endpoint("POST")
@can_recruit
def candidate_reveal(request, code):
    """Tell this candidate who the company is (``{"reason": "..."}``). Logged, and not undone."""
    row = get_object_or_404(Candidate, code=code)
    try:
        reason = _text(_object(request), "reason", 250)
    except BadBody:
        return _error(400, "bad_body")
    recruitment.reveal_identity(row, request.user, reason)
    return JsonResponse({"ok": True})


@endpoint("POST")
@can_recruit
def candidate_message(request, code):
    """Write to the candidate (``{"body": "..."}``) from the recruitment number, through the identity filter. Nothing else sends."""
    row = get_object_or_404(Candidate, code=code)
    try:
        text = _text(_object(request), "body", MAX_MESSAGE)
    except BadBody:
        return _error(400, "bad_body")
    if not text:
        return JsonResponse({"ok": False, "error": "invalid", "errors": {"body": ["This field is required."]}}, status=400)
    ok, error = recruitment.send_to_candidate(row, text)
    if not ok:
        if error == "no phone":
            return _error(409, "no_phone")
        if error == "no recruitment line":
            return _error(409, "no_recruit_line")
        return JsonResponse({"ok": False, "error": "send_failed", "message": error}, status=502)
    services.log(request.user, "recruitment.message", row.code)
    return JsonResponse({"ok": True})


# ---------------------------------------------------------------------------
# Interviews
# ---------------------------------------------------------------------------

@endpoint("POST")
@can_recruit
def interview_create(request, code):
    """Book an interview (``{"values": {...}}``)."""
    row = get_object_or_404(Candidate, code=code)
    form, refused = api_forms.filled(request, InterviewForm)
    if refused:
        return refused
    interview = form.save(commit=False)
    interview.candidate = row
    interview.created_by = request.user
    interview.save()
    services.log(request.user, "recruitment.interview.schedule", row.code)
    return JsonResponse({"ok": True, "id": interview.pk})


def _score_form(interview):
    return named(api_forms.describe(InterviewScoreForm(instance=interview)), SCORE_TEXT)


@endpoint("GET")
@can_recruit
def interview(request, pk):
    """One interview with the five marks it has so far, and the form that sets them (each out of ten)."""
    row = get_object_or_404(Interview.objects.select_related("candidate", "interviewer"), pk=pk)
    return JsonResponse({
        "ok": True,
        "interview": interview_json(row),
        "candidate": {"code": row.candidate.code, "name": row.candidate.display_name},
        "form": _score_form(row),
    })


@endpoint("POST")
@can_recruit
def interview_score(request, pk):
    """Mark the interview (``{"values": {...}}``). The total is the system's: it adds the marks up, nobody types it."""
    row = get_object_or_404(Interview.objects.select_related("candidate"), pk=pk)
    form, refused = api_forms.filled(request, InterviewScoreForm, instance=row)
    if refused:
        return refused
    marked = form.save(commit=False)
    marked.evaluated_at = timezone.now()
    marked.evaluated_by = request.user
    marked.save()
    services.log(request.user, "recruitment.interview.score", row.candidate.code, f"{marked.total_score}/{marked.max_score}")
    return JsonResponse({"ok": True, "total": marked.total_score, "max": marked.max_score})


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

@endpoint("POST")
@can_recruit
def candidate_test_create(request, code):
    """Set the candidate a test. JSON ``{"values": {...}}``, or multipart with ``values`` (JSON text) and the ``assignment`` file.

    The deadline is how long the candidate gets, from now, as ``deadline_days``, ``deadline_hours`` and ``deadline_minutes``.
    """
    person = get_object_or_404(Candidate, code=code)
    try:
        values, upload = values_and_file(request, "assignment")
        values, parts = read_deadline_parts(values)
        data = api_forms.form_data(TestDataForm, values)
    except (BadBody, api_forms.BadValues):
        return _error(400, "bad_body")
    original = (upload.name if upload is not None else "")[:200]
    stored = anonymous_upload(upload) if upload is not None else None
    if upload is not None and stored is None:
        return _error(400, "bad_file")
    for part, text in parts.items():
        data[f"deadline_{part}"] = text
    data["deadline_was"] = ""
    form = TestDataForm(data)
    if not form.is_valid():
        return api_forms.invalid(form)
    test = form.save(commit=False)
    test.candidate = person
    test.department = test.department or person.department
    test.created_by = request.user
    if stored is not None:
        test.assignment = stored
        test.assignment_name = original
    test.save()
    services.log(request.user, "recruitment.test.assign", person.code)
    return JsonResponse({"ok": True, "id": test.pk})
