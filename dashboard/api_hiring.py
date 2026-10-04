"""``/api/v1/`` - the end of recruitment: the owner's approvals, hiring, and the reviewer's queue of candidate tests.

The pages are ``views.hr_approvals`` and ``hr_approval_decide`` (the owner alone), ``hr_hire`` (HR and the owner), and
``reviewer_tests`` and ``hr_test_score`` (the reviewer, a team leader, the owner). The rules are ``recruitment.*``.

Rules that matter on these pages:

* Hiring is never automatic. ``recruitment.decide_hiring`` is the only door into "approved" and it is the owner's; the hire
  itself (``recruitment.hire``) makes the employee once, from an approved candidate, and refuses anything else in its own words.
* HR hires into the roles it may hand out and no more. The Sales role reads client identities and the owner's role reads
  everything; an account created here with a password is an account somebody can sign in to, so those two (and the money
  role) are the owner's to create, from the staff page. The password typed here goes to the engine and nowhere else: it is not
  answered, not logged, not echoed back on a refusal.
* A reviewer is blind. The candidate is a code: no name, no phone, no e-mail, no expected salary, no vacancy. The name a
  candidate's submission was uploaded under is the candidate's own, so it is shown as a plain word with the file's extension;
  only the owner reads the real one. A test is the reviewer's own (assigned to them or to nobody) - another reviewer's is not
  there, and the attempt is written down.
* A GET changes nothing.
"""

import os

from django.db.models import Q
from django.http import JsonResponse
from django.shortcuts import get_object_or_404
from django.utils import timezone

from . import api_forms, identity, recruitment, services
from .api_candidates import _file_json, anonymous_upload, values_and_file
from .api_forms import named
from .api_leave import refusal
from .api_people import can_recruit, is_owner
from .api_recruit import _badge, candidate_row
from .api_v1 import BadBody, _error, _object, _stamp, _text, endpoint
from .forms import HireForm, TestScoreForm
from .models import Candidate, CandidateStatus, CandidateTest, RecruitmentSettings
from .permissions import api_gate
from .templatetags.eagle_tags import CANDIDATE_STATUS_MAP, ROLE_MAP

can_mark = api_gate(lambda user: user.can_review_tests)

#: The lists show this many: the classic pages' own numbers.
MAX_DECIDED = 30
MAX_MARKED = 40

HIRE_TEXT = {
    "role": ("الدور", "Role"),
    "job_title": ("المسمى الوظيفي", "Job title"),
    "joining_date": ("تاريخ الانضمام", "Joining date"),
    "salary": ("الراتب الأساسي", "Base salary"),
    "team_lead": ("المدير المباشر", "Direct manager"),
    "username": ("اسم المستخدم", "Username"),
    "password": ("الباسورد", "Password"),
}
HIRE_HINT = {
    "username": ("سيبه فاضي والنظام هيولّده.", "Leave it empty and the system makes one."),
    "password": ("سيبه فاضي والحساب يتقفل لحد ما تحطه.", "Leave it empty and the account stays locked until one is set."),
}
SCORE_TEXT = {
    "accuracy": ("الدقة", "Accuracy"),
    "grammar": ("القواعد", "Grammar"),
    "terminology": ("المصطلحات", "Terminology"),
    "formatting": ("التنسيق", "Formatting"),
    "instructions": ("اتباع التعليمات", "Following instructions"),
    "comments": ("ملاحظات المراجع", "Reviewer comments"),
}


class TestMarkForm(TestScoreForm):
    """The marks form without the submission: a file is not a value in a JSON body, the door takes it beside the values."""

    class Meta(TestScoreForm.Meta):
        fields = tuple(name for name in TestScoreForm.Meta.fields if name != "submission")
        widgets = {name: widget for name, widget in TestScoreForm.Meta.widgets.items() if name != "submission"}


# ---------------------------------------------------------------------------
# The owner's approvals
# ---------------------------------------------------------------------------

def _score(total, top):
    return {"total": total, "max": top} if total is not None else None


def _evidence(candidate):
    """What the owner decides on: how the interview and the test went, what was asked for, what HR thinks."""
    interview = candidate.latest_interview
    test = candidate.latest_test
    return {
        **candidate_row(candidate),
        "interview_score": _score(candidate.interview_score, interview.max_score if interview else 50),
        "test_score": _score(candidate.test_score, test.max_score if test else 50),
        "expected_salary": candidate.expected_salary,
        "hr_recommendation": candidate.hr_recommendation,
        "hr_notes": candidate.hr_notes,
        "cv": _file_json(candidate.cv, candidate.cv_name or "CV"),
        "department": candidate.department.label if candidate.department_id else None,
    }


@endpoint("GET")
@is_owner
def approvals(request):
    """The owner's queue and the last decisions. This page is the only place a hire is decided."""
    waiting = Candidate.objects.filter(status=CandidateStatus.OWNER_APPROVAL).select_related("vacancy", "department")
    decided = Candidate.objects.filter(status__in=(CandidateStatus.APPROVED, CandidateStatus.HIRED)).select_related("vacancy")
    return JsonResponse({
        "ok": True,
        "waiting": [_evidence(one) for one in waiting],
        "decided": [
            {**candidate_row(one), "decided_at": _stamp(one.owner_decision_at, "%Y-%m-%d"), "can_hire": one.status == CandidateStatus.APPROVED}
            for one in decided[:MAX_DECIDED]
        ],
    })


@endpoint("POST")
@is_owner
def approval_decide(request, code, action):
    """Approve or reject (``{"reason": "..."}``; the reason is for a rejection). The engine says who may and when."""
    if action not in ("approve", "reject"):
        return _error(404, "not_found")
    row = get_object_or_404(Candidate, code=code)
    try:
        reason = _text(_object(request), "reason", 250)
    except BadBody:
        return _error(400, "bad_body")
    try:
        recruitment.decide_hiring(row, request.user, approve=(action == "approve"), reason=reason)
    except recruitment.PipelineError as refused:
        return refusal(refused)
    return JsonResponse({"ok": True})


# ---------------------------------------------------------------------------
# Hiring
# ---------------------------------------------------------------------------

def _hire_kwargs(candidate, user):
    """How the hire form is made: for whom, and what it starts from (the vacancy's title, today): the page's own, so a box left alone is sent as drawn."""
    return {
        "actor": user,
        "initial": {
            "job_title": candidate.vacancy.title if candidate.vacancy_id else "",
            "joining_date": timezone.localdate(),
        },
    }


def _hire_form(candidate, user):
    return named(
        api_forms.describe(HireForm(**_hire_kwargs(candidate, user))), HIRE_TEXT, HIRE_HINT,
        choices={"role": {value: pair for value, pair in ROLE_MAP.items()}},
    )


def _hire_body(candidate, user):
    hireable = candidate.status == CandidateStatus.APPROVED and not candidate.hired_user_id
    conf = RecruitmentSettings.load()
    return {
        "ok": True,
        "candidate": {
            "code": candidate.code,
            "name": candidate.full_name,
            "phone": candidate.phone,
            "email": candidate.email,
            "languages": candidate.languages,
            "department": candidate.department.label if candidate.department_id else None,
            "shift": candidate.shift_choice,
            "cv": _file_json(candidate.cv, candidate.cv_name or "CV"),
            "status": _badge(CANDIDATE_STATUS_MAP, candidate.status),
            "hired_user": candidate.hired_user_id,
        },
        "hireable": hireable,
        "probation_days": conf.probation_days or 90,
        "form": _hire_form(candidate, user) if hireable else [],
    }


@endpoint("GET")
@can_recruit
def hire_form(request, code):
    """What carries over from the application, and the form for the contract side. No form unless the candidate is approved."""
    row = get_object_or_404(Candidate.objects.select_related("department", "vacancy"), code=code)
    return JsonResponse(_hire_body(row, request.user))


@endpoint("POST")
@can_recruit
def hire(request, code):
    """Turn an approved candidate into an employee, once (``{"values": {...}}``). Everything else is ``recruitment.hire``."""
    row = get_object_or_404(Candidate.objects.select_related("department", "vacancy"), code=code)
    try:
        values = _object(request).get("values", {})
        if not isinstance(values, dict):
            raise BadBody
        data = api_forms.form_data(HireForm, values, form_kwargs=_hire_kwargs(row, request.user))
    except (BadBody, api_forms.BadValues):
        return _error(400, "bad_body")
    form = HireForm(data, actor=request.user)
    if not form.is_valid():
        return api_forms.invalid(form)
    done = form.cleaned_data
    try:
        person = recruitment.hire(
            row, request.user, role=done["role"], job_title=done["job_title"], joining_date=done["joining_date"],
            salary=done["salary"], team_lead=done["team_lead"], username=done["username"], password=done["password"],
        )
    except recruitment.PipelineError as refused:
        return refusal(refused)
    return JsonResponse({"ok": True, "id": person.pk, "username": person.username})


# ---------------------------------------------------------------------------
# The reviewer's queue
# ---------------------------------------------------------------------------

def _mine(user):
    """The tests this person may open: the owner's are all of them; a reviewer's are theirs and the ones nobody has taken."""
    rows = CandidateTest.objects.select_related("candidate", "department")
    if not user.is_admin_role:
        rows = rows.filter(Q(reviewer=user) | Q(reviewer__isnull=True))
    return rows


def _queue_row(row):
    return {
        "id": row.pk,
        "candidate": row.candidate.code,
        "title": row.title,
        "department": row.department.label if row.department_id else None,
        "overdue": row.is_overdue,
        "submitted": row.is_submitted,
        "submitted_at": _stamp(row.submitted_at, "%m-%d"),
        "marked_at": _stamp(row.marked_at, "%Y-%m-%d"),
        "total": row.total_score if row.is_marked else None,
        "max": row.max_score,
    }


@endpoint("GET")
@can_mark
def reviewer_tests(request):
    """The reviewer's own queue: tests to mark, and the ones marked. Tests and nothing else (section 24)."""
    mine = _mine(request.user)
    return JsonResponse({
        "ok": True,
        "pending": [_queue_row(one) for one in mine.filter(marked_at__isnull=True)],
        "done": [_queue_row(one) for one in mine.filter(marked_at__isnull=False)[:MAX_MARKED]],
    })


def _extension(name):
    ext = os.path.splitext(name or "")[1].lower()
    return ext if ext and len(ext) <= 8 and ext[1:].isalnum() and ext.isascii() else ""


def _test_of(request, pk):
    """The test, or the page that is not there. Somebody else's is not there either, and that is written down."""
    row = get_object_or_404(CandidateTest.objects.select_related("candidate", "department"), pk=pk)
    if not request.user.is_admin_role and row.reviewer_id not in (None, request.user.pk):
        identity.hidden(request, "candidate test")
    return row


def _test_body(row, user):
    blind = not user.is_admin_role
    submission = None
    if row.submission:
        # What the candidate named their own file is theirs: the reviewer reads "submission" and its extension.
        shown = ("submission" + _extension(row.submission.name)) if blind else (row.submission_name or "submission")
        submission = _file_json(row.submission, shown)
    return {
        "ok": True,
        "blind": blind,
        "candidate": {"code": row.candidate.code} if blind else {"code": row.candidate.code, "name": row.candidate.display_name},
        "test": {
            "id": row.pk,
            "title": row.title,
            "brief": row.brief,
            "department": row.department.label if row.department_id else None,
            "language_pair": row.language_pair,
            "word_count": row.word_count,
            "deadline": _stamp(row.deadline, "%Y-%m-%d"),
            # The name HR gave the file is often the candidate's: a blind reviewer reads a plain word and the extension.
            "assignment": _file_json(row.assignment, ("assignment" + _extension(row.assignment.name)) if blind else row.assignment_name)
            if row.assignment else None,
            "submission": submission,
            "submitted_at": _stamp(row.submitted_at, "%m-%d"),
            "marked": row.is_marked,
            "total": row.total_score,
            "max": row.max_score,
        },
        "form": named(api_forms.describe(TestMarkForm(instance=row)), SCORE_TEXT),
    }


@endpoint("GET")
@can_mark
def reviewer_test(request, pk):
    return JsonResponse(_test_body(_test_of(request, pk), request.user))


@endpoint("POST")
@can_mark
def reviewer_test_score(request, pk):
    """Mark the test. JSON ``{"values": {...}}``, or multipart with ``values`` and the candidate's ``submission`` file."""
    row = _test_of(request, pk)
    try:
        values, upload = values_and_file(request, "submission")
        data = api_forms.form_data(TestMarkForm, values, instance=row)
    except (BadBody, api_forms.BadValues):
        return _error(400, "bad_body")
    original = (upload.name if upload is not None else "")[:200]
    stored = anonymous_upload(upload) if upload is not None else None
    if upload is not None and stored is None:
        return _error(400, "bad_file")
    form = TestMarkForm(data, instance=row)
    if not form.is_valid():
        return api_forms.invalid(form)
    marked = form.save(commit=False)
    now = timezone.now()
    if stored is not None:
        marked.submission = stored
        marked.submission_name = original
    if marked.submission and not marked.submitted_at:
        marked.submitted_at = now
    marked.marked_at = now
    marked.reviewer = marked.reviewer or request.user
    marked.save()
    services.log(request.user, "recruitment.test.score", row.candidate.code, f"{marked.total_score}/{marked.max_score}")
    return JsonResponse({"ok": True, "total": marked.total_score, "max": marked.max_score})
