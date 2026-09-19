"""Recruitment: the bot that takes an application, and the pipeline after it.

What the bot is for
-------------------
It greets a candidate, explains the opening without saying whose it is,
asks the questions HR picked for that vacancy, takes the CV, and then hands
the whole thing to HR. It does not screen, score, shortlist or hire. Section
28 of the spec puts it plainly and this module keeps it that way: the only
status the bot can ever set is ``SCREENING``, which means "a person's turn".

The privacy rule is code, not a habit
-------------------------------------
Section 3 says a candidate must not learn the company's name early, and that
this has to be a *system rule* rather than an instruction to HR. So every
outbound message goes through :func:`outbound_text`, which redacts the terms
in ``RecruitmentSettings.redact_terms`` whenever the candidate's
``identity_revealed`` flag is off. Nothing sends to a candidate any other
way - not the bot, not HR's own replies - so the rule cannot be forgotten,
only deliberately lifted, and lifting it is written to the audit log.

The questions belong to HR
--------------------------
Nothing in here knows what a translator should be asked. The bot walks
``vacancy.question_links`` in HR's order and prints whatever is there. A new
department, a new kind of role, a reworded question: none of it is a code
change (sections 8-11).

Which number the candidate wrote to
-----------------------------------
Eagle runs two WhatsApp lines on one business account. The webhook tells them
apart by the phone number ID the event arrived for: the client number goes to
the ops inbox as before, the recruitment number comes here. A candidate and a
client can therefore never land in the same queue by accident.
"""

import logging
import re
from datetime import datetime, time as clock_time, timedelta

from django.core.files.base import ContentFile
from django.db import transaction
from django.db.models import Count, Q
from django.utils import timezone

from . import services, whatsapp
from .models import (
    AnswerTarget,
    AppSettings,
    Candidate,
    CandidateAnswer,
    CandidateSession,
    CandidateSource,
    CandidateStatus,
    CandidateTest,
    CHOICE_KINDS,
    EmploymentStatus,
    Interview,
    QuestionKind,
    RecruitmentSettings,
    Role,
    SessionState,
    User,
    Vacancy,
    VacancyStatus,
    next_code,
)

logger = logging.getLogger(__name__)

YES_WORDS = {"yes", "y", "نعم", "اه", "أه", "ايوه", "أيوه", "ايوة", "تمام", "موافق", "ok"}
NO_WORDS = {"no", "n", "لا", "لأ", "مش", "مينفعش", "غير متاح"}


# ---------------------------------------------------------------------------
# The privacy rule
# ---------------------------------------------------------------------------

def redaction_terms(conf=None):
    conf = conf or RecruitmentSettings.load()
    return conf.term_list


#: Splits a term into the pieces a person might put spaces between: words,
#: camel-case humps, runs of digits, and punctuation. "EagleLingua" becomes
#: ("Eagle", "Lingua") and "eagel-operation.com" becomes five pieces.
_TERM_CHUNK = re.compile(r"[A-Z]+(?![a-z])|[A-Z][a-z]+|[a-z]+|[0-9]+|[^\sA-Za-z0-9]+")


def term_pattern(term):
    """A regex that catches a term however it was spaced or capitalised.

    HR types the company's name once. It then has to be caught whether it
    was written "EagleLingua", "Eagle Lingua", or broken across a line - so
    the pieces are rejoined with an optional-whitespace gap rather than
    matched literally. Anything less and the rule leaks on a typo.
    """
    pieces = _TERM_CHUNK.findall(term) or [term]
    return r"\s*".join(re.escape(piece) for piece in pieces)


def outbound_text(candidate, text, conf=None):
    """Scrub the company's identity out of anything an anonymous candidate reads.

    Returns the text unchanged once HR has revealed the identity, or when
    nothing has been configured to redact - and in that second case the
    screens say the rule is not armed, because silence would read as safety.
    """
    text = text or ""
    if candidate is not None and candidate.identity_revealed:
        return text
    conf = conf or RecruitmentSettings.load()
    terms = conf.term_list
    if not terms:
        return text
    placeholder = conf.redact_placeholder or "[—]"
    for term in terms:
        text = re.sub(term_pattern(term), placeholder, text, flags=re.IGNORECASE)
    return text


@transaction.atomic
def reveal_identity(candidate, actor, reason=""):
    """HR decides this candidate may know who we are. Always logged."""
    if candidate.identity_revealed:
        return candidate
    candidate.identity_revealed = True
    candidate.identity_revealed_at = timezone.now()
    candidate.identity_revealed_by = actor
    candidate.save(update_fields=[
        "identity_revealed", "identity_revealed_at", "identity_revealed_by",
    ])
    services.log(
        actor, "recruitment.identity.reveal", candidate.code,
        reason or "HR revealed the company identity to the candidate",
    )
    return candidate


def send_to_candidate(candidate, text, conf=None):
    """The only way a message reaches a candidate. Redacts, then sends.

    Returns ``(ok, error)`` rather than raising: a WhatsApp hiccup must not
    lose the answer that was just recorded, and the screens show the failure.
    """
    conf = conf or RecruitmentSettings.load()
    body = outbound_text(candidate, text, conf=conf)
    if not (candidate and candidate.phone):
        return False, "no phone"
    app = AppSettings.load()
    try:
        whatsapp.send_text(
            candidate.phone, body, from_id=app.recruit_phone_number_id
        )
    except Exception as exc:  # noqa: BLE001 - reported, never fatal
        logger.warning("Recruitment reply to %s failed: %s", candidate.code, exc)
        return False, str(exc)
    return True, ""


def _reply(contact, text, candidate=None, conf=None):
    """Send to a phone number that may not have a candidate row yet."""
    conf = conf or RecruitmentSettings.load()
    body = outbound_text(candidate, text, conf=conf)
    app = AppSettings.load()
    try:
        whatsapp.send_text(contact, body, from_id=app.recruit_phone_number_id)
        return True
    except Exception as exc:  # noqa: BLE001
        logger.warning("Recruitment bot could not reply to %s: %s", contact, exc)
        return False


# ---------------------------------------------------------------------------
# Wording
# ---------------------------------------------------------------------------

def greeting(conf):
    if conf.greeting_ar:
        return conf.greeting_ar
    return (
        f"أهلًا بيك.\nمعاك {conf.bot_name_ar}.\n"
        "إحنا بنستقبل طلبات التوظيف هنا، وهسألك كام سؤال بسيط وناخد الـCV، "
        "وبعدها فريق الموارد البشرية هيراجع طلبك ويرد عليك."
    )


def closing(conf):
    if conf.closing_ar:
        return conf.closing_ar
    return (
        "تمام، استلمنا طلبك كامل.\n"
        "فريق الموارد البشرية هيراجعه ويتواصل معاك. شكرًا لوقتك."
    )


def question_prompt(link, index, total):
    """One question as the candidate sees it, with its options numbered."""
    question = link.question
    head = f"({index}/{total}) {question.text}"
    lines = [head]
    if question.help_text:
        lines.append(question.help_text)

    if question.kind in CHOICE_KINDS:
        for number, option in enumerate(question.option_list, start=1):
            lines.append(f"{number}. {option}")
        if question.kind == QuestionKind.MULTI:
            lines.append("اكتب أرقام كل اللي ينطبق عليك، مفصولة بفاصلة.")
        else:
            lines.append("اكتب رقم الاختيار.")
    elif question.kind == QuestionKind.YES_NO:
        lines.append("رد بـ (نعم) أو (لا).")
    elif question.kind == QuestionKind.FILE:
        lines.append("ابعت الملف هنا كمرفق.")
    elif question.kind == QuestionKind.NUMBER:
        lines.append("اكتب رقم.")
    elif question.kind == QuestionKind.DATE:
        lines.append("اكتب التاريخ بالشكل ده: 2026-09-20")

    if not link.is_required:
        lines.append("لو مش منطبق عليك اكتب: تخطي")
    return "\n".join(lines)


def shift_prompt(vacancy):
    """Section 7: one shift is a yes/no; several is a numbered choice."""
    shifts = vacancy.shift_list
    if not shifts:
        return "", []
    if len(shifts) == 1:
        shift = shifts[0]
        window = f"{shift.start_time:%I:%M %p} - {shift.end_time:%I:%M %p}"
        return (
            f"الشيفت المتاح للوظيفة دي: {window}\nهل تقدر تشتغل في المواعيد دي؟ "
            "(نعم / لا)"
        ), [window]
    lines = ["الشيفتات المتاحة للوظيفة دي:"]
    options = []
    for number, shift in enumerate(shifts, start=1):
        window = f"{shift.start_time:%I:%M %p} - {shift.end_time:%I:%M %p}"
        options.append(window)
        lines.append(f"{number}. {window}")
    lines.append("اكتب رقم الشيفت اللي يناسبك.")
    return "\n".join(lines), options


# ---------------------------------------------------------------------------
# Answer handling
# ---------------------------------------------------------------------------

def _is_yes(text):
    return (text or "").strip().lower() in YES_WORDS


def _is_skip(text):
    return (text or "").strip().lower() in {"تخطي", "تخطى", "skip", "-"}


def parse_choice(text, options, multi=False):
    """Turn "2" or "1,3" - or the option's own words - into the option text."""
    raw = (text or "").strip()
    if not raw or not options:
        return ""
    picks = [part.strip() for part in re.split(r"[,،]", raw)] if multi else [raw]
    chosen = []
    for part in picks:
        if part.isdigit():
            index = int(part) - 1
            if 0 <= index < len(options):
                chosen.append(options[index])
                continue
        for option in options:
            if part.lower() == option.lower():
                chosen.append(option)
                break
    # Preserve order, drop repeats.
    seen, result = set(), []
    for item in chosen:
        if item not in seen:
            seen.add(item)
            result.append(item)
    return "، ".join(result)


def apply_to_profile(candidate, question, value, attachment=None):
    """Copy an answer onto the profile when HR tagged the question.

    This is what keeps the bot from needing to recognise "what is your name?".
    HR says which field a question fills; any wording then works, in any
    language, and a question with no tag is simply stored as an answer.
    """
    target = question.maps_to
    if not target:
        return []

    if target == AnswerTarget.CV:
        if attachment is not None:
            candidate.cv = attachment["file"]
            candidate.cv_name = attachment["name"][:200]
            return ["cv", "cv_name"]
        return []

    field_limits = {
        AnswerTarget.FULL_NAME: ("full_name", 140),
        AnswerTarget.EMAIL: ("email", 254),
        AnswerTarget.EXPERIENCE: ("experience_years", 60),
        AnswerTarget.LANGUAGES: ("languages", 160),
        AnswerTarget.SKILLS: ("skills", 250),
        AnswerTarget.EXPECTED_SALARY: ("expected_salary", 60),
    }
    if target not in field_limits:
        return []
    name, limit = field_limits[target]
    setattr(candidate, name, (value or "")[:limit])
    return [name]


# ---------------------------------------------------------------------------
# The conversation
# ---------------------------------------------------------------------------

def open_vacancies():
    return list(
        Vacancy.objects.filter(status=VacancyStatus.OPEN)
        .select_related("department").order_by("-created_at")
    )


def _fresh_session(contact, display_name, conf):
    """Start over. An old, half-finished chat is not silently resumed."""
    CandidateSession.objects.filter(
        contact=contact, state__in=(SessionState.PICKING, SessionState.ASKING)
    ).update(state=SessionState.ABANDONED)
    return CandidateSession.objects.create(
        contact=contact, display_name=display_name[:120], state=SessionState.PICKING
    )


def _live_session(contact, conf):
    cutoff = timezone.now() - timedelta(hours=conf.session_timeout_hours or 48)
    return (
        CandidateSession.objects
        .filter(contact=contact, state__in=(SessionState.PICKING, SessionState.ASKING))
        .filter(last_message_at__gte=cutoff)
        .select_related("candidate", "vacancy")
        .order_by("-last_message_at")
        .first()
    )


def _ensure_candidate(session, vacancy, conf):
    if session.candidate_id:
        return session.candidate
    candidate = Candidate.objects.create(
        vacancy=vacancy,
        department=vacancy.department if vacancy else None,
        full_name=session.display_name[:140],
        phone=session.contact,
        source=CandidateSource.WHATSAPP,
        status=CandidateStatus.NEW,
    )
    session.candidate = candidate
    session.save(update_fields=["candidate"])
    return candidate


def _ask_next(session, conf):
    """Send the next question, or finish the application."""
    vacancy = session.vacancy
    links = vacancy.questions_in_order() if vacancy else []
    candidate = session.candidate

    if session.step >= len(links):
        return _finish(session, conf)

    link = links[session.step]
    question = link.question
    options = question.option_list if question.kind in CHOICE_KINDS else []
    session.pending_options = options
    session.state = SessionState.ASKING
    session.save(update_fields=["pending_options", "state", "step"])
    _reply(
        session.contact,
        question_prompt(link, session.step + 1, len(links)),
        candidate=candidate, conf=conf,
    )
    return session


@transaction.atomic
def _finish(session, conf):
    """The paperwork is in. Hand the candidate to HR and stop.

    This is the furthest the bot ever moves anybody: ``SCREENING`` means a
    person has to look. No score, no shortlist, no rejection.
    """
    candidate = session.candidate
    session.state = SessionState.DONE
    session.pending_options = []
    session.save(update_fields=["state", "pending_options"])

    if candidate is not None:
        candidate.status = CandidateStatus.SCREENING
        candidate.save(update_fields=["status"])
        _reply(session.contact, closing(conf), candidate=candidate, conf=conf)
        notify_hr(
            title_ar="طلب توظيف جديد",
            title_en="New application",
            body_ar=(
                f"{candidate.display_name} قدّم على "
                f"{candidate.vacancy.title if candidate.vacancy else 'وظيفة'}."
            ),
            body_en=f"{candidate.display_name} completed an application.",
            url=f"/hr/candidates/{candidate.code}/",
        )
        services.log(None, "recruitment.application", candidate.code, "bot handed to HR")
    return session


def hr_people():
    """Everyone who runs recruitment: the HR role, plus the owner."""
    return User.objects.filter(is_active=True).filter(
        Q(role=Role.HR) | Q(role=Role.ADMIN) | Q(is_superuser=True)
    ).distinct()


def notify_hr(**kwargs):
    for person in hr_people():
        services.notify(person, **kwargs)


@transaction.atomic
def handle_inbound(contact, body="", display_name="", attachments=None):
    """One message from a candidate. Returns the session it belongs to.

    Everything the bot ever does starts here, and the shape is deliberately
    boring: work out where in the conversation we are, record what arrived,
    ask the next thing.
    """
    conf = RecruitmentSettings.load()
    attachments = attachments or []
    text = (body or "").strip()

    if not conf.bot_enabled:
        return None

    session = _live_session(contact, conf)
    if session is None:
        session = _fresh_session(contact, display_name, conf)
        return _offer_vacancies(session, conf)

    if session.display_name != display_name and display_name:
        session.display_name = display_name[:120]
        session.save(update_fields=["display_name"])

    if session.state == SessionState.PICKING:
        return _handle_pick(session, text, conf)
    return _handle_answer(session, text, attachments, conf)


def _offer_vacancies(session, conf):
    """Greet, then print what is open. One opening skips the menu."""
    vacancies = open_vacancies()
    if not vacancies:
        _reply(
            session.contact,
            f"{greeting(conf)}\n\nمفيش وظايف مفتوحة دلوقتي. "
            "ابعتلنا تاني قريب وهنكون سعداء نشوف طلبك.",
            conf=conf,
        )
        session.state = SessionState.ABANDONED
        session.save(update_fields=["state"])
        return session

    if len(vacancies) == 1:
        _reply(session.contact, greeting(conf), conf=conf)
        return _start_vacancy(session, vacancies[0], conf)

    lines = [greeting(conf), "", "الوظايف المتاحة دلوقتي:"]
    options = []
    for number, vacancy in enumerate(vacancies, start=1):
        options.append(vacancy.code)
        lines.append(f"{number}. {vacancy.title}")
    lines.append("")
    lines.append("اكتب رقم الوظيفة اللي تحب تقدم عليها.")

    session.pending_options = options
    session.state = SessionState.PICKING
    session.save(update_fields=["pending_options", "state"])
    _reply(session.contact, "\n".join(lines), conf=conf)
    return session


def _handle_pick(session, text, conf):
    codes = session.pending_options or []
    picked = parse_choice(text, codes)
    vacancy = Vacancy.objects.filter(code=picked, status=VacancyStatus.OPEN).first()
    if vacancy is None:
        _reply(
            session.contact,
            "معلش مافهمتش الاختيار. اكتب رقم الوظيفة من القايمة فوق.",
            conf=conf,
        )
        return session
    return _start_vacancy(session, vacancy, conf)


def _start_vacancy(session, vacancy, conf):
    """Confirm the role, ask about the shift, then begin the questions."""
    session.vacancy = vacancy
    session.step = 0
    session.save(update_fields=["vacancy", "step"])
    candidate = _ensure_candidate(session, vacancy, conf)

    summary = [f"الوظيفة: {vacancy.title}"]
    if vacancy.job_description:
        summary.append(vacancy.job_description)
    if vacancy.requirements:
        summary.append(f"المطلوب: {vacancy.requirements}")
    summary.append(
        "نظام العمل: "
        + {"office": "من المكتب", "remote": "عن بُعد", "hybrid": "هجين"}.get(
            vacancy.work_mode, vacancy.work_mode
        )
    )
    _reply(session.contact, "\n\n".join(summary), candidate=candidate, conf=conf)

    prompt, options = shift_prompt(vacancy)
    if prompt:
        session.pending_options = ["__shift__"] + options
        session.state = SessionState.ASKING
        session.save(update_fields=["pending_options", "state"])
        _reply(session.contact, prompt, candidate=candidate, conf=conf)
        return session

    return _ask_next(session, conf)


def _handle_shift_answer(session, text, conf):
    """The shift reply, which sits before the vacancy's own questions."""
    candidate = session.candidate
    options = [o for o in (session.pending_options or []) if o != "__shift__"]

    if len(options) == 1:
        if _is_yes(text):
            candidate.shift_choice = options[0][:120]
        else:
            candidate.shift_choice = ""
            _reply(
                session.contact,
                "تمام، سجّلنا إن المواعيد دي مش مناسبة ليك. "
                "هنكمل باقي الأسئلة وفريق الموارد البشرية هيشوف المتاح.",
                candidate=candidate, conf=conf,
            )
    else:
        picked = parse_choice(text, options)
        if not picked:
            _reply(session.contact, "اكتب رقم الشيفت من القايمة فوق.",
                   candidate=candidate, conf=conf)
            return session
        candidate.shift_choice = picked[:120]
    candidate.save(update_fields=["shift_choice"])

    session.pending_options = []
    session.save(update_fields=["pending_options"])
    return _ask_next(session, conf)


def _handle_answer(session, text, attachments, conf):
    if session.pending_options and session.pending_options[0] == "__shift__":
        return _handle_shift_answer(session, text, conf)

    vacancy = session.vacancy
    links = vacancy.questions_in_order() if vacancy else []
    if session.step >= len(links):
        return _finish(session, conf)

    link = links[session.step]
    question = link.question
    candidate = session.candidate

    attachment = attachments[0] if attachments else None
    value = text

    # -- validate what arrived ------------------------------------------
    if question.kind == QuestionKind.FILE:
        if attachment is None:
            if _is_skip(text) and not link.is_required:
                value = ""
            else:
                _reply(session.contact, "ابعت الملف كمرفق من فضلك.",
                       candidate=candidate, conf=conf)
                return session
        else:
            value = attachment["name"]
    elif _is_skip(text) and not link.is_required:
        value = ""
    elif question.kind in CHOICE_KINDS:
        value = parse_choice(
            text, question.option_list, multi=(question.kind == QuestionKind.MULTI)
        )
        if not value:
            _reply(session.contact, "اكتب رقم الاختيار من القايمة فوق.",
                   candidate=candidate, conf=conf)
            return session
    elif question.kind == QuestionKind.YES_NO:
        low = (text or "").strip().lower()
        if low in YES_WORDS:
            value = "نعم"
        elif low in NO_WORDS:
            value = "لا"
        else:
            _reply(session.contact, "رد بـ (نعم) أو (لا) من فضلك.",
                   candidate=candidate, conf=conf)
            return session
    elif question.kind == QuestionKind.NUMBER:
        if not re.fullmatch(r"[\d\s.,٠-٩]+", text or ""):
            _reply(session.contact, "اكتب رقم من فضلك.", candidate=candidate, conf=conf)
            return session
    elif link.is_required and not text:
        _reply(session.contact, "محتاجين إجابة على السؤال ده.",
               candidate=candidate, conf=conf)
        return session

    # -- record it --------------------------------------------------------
    answer, _ = CandidateAnswer.objects.update_or_create(
        candidate=candidate, question=question,
        defaults={"order": session.step, "value": value},
    )
    if attachment is not None:
        answer.file = attachment["file"]
        answer.file_name = attachment["name"][:200]
        answer.save(update_fields=["file", "file_name"])

    changed = apply_to_profile(candidate, question, value, attachment)
    if changed:
        candidate.save(update_fields=changed)

    session.step += 1
    session.pending_options = []
    session.save(update_fields=["step", "pending_options"])
    return _ask_next(session, conf)


# ---------------------------------------------------------------------------
# The pipeline after the bot
# ---------------------------------------------------------------------------

#: Which statuses a candidate may legally move to from where they are. A
#: pipeline that can skip its own steps is not a pipeline.
ALLOWED_MOVES = {
    CandidateStatus.NEW: (CandidateStatus.SCREENING, CandidateStatus.REJECTED),
    CandidateStatus.SCREENING: (
        CandidateStatus.INTERVIEW, CandidateStatus.TEST, CandidateStatus.REJECTED,
    ),
    CandidateStatus.INTERVIEW: (
        CandidateStatus.TEST, CandidateStatus.FINAL_REVIEW, CandidateStatus.REJECTED,
    ),
    CandidateStatus.TEST: (
        CandidateStatus.FINAL_REVIEW, CandidateStatus.INTERVIEW, CandidateStatus.REJECTED,
    ),
    CandidateStatus.FINAL_REVIEW: (
        CandidateStatus.OWNER_APPROVAL, CandidateStatus.REJECTED,
    ),
    # Only the owner leaves this one, and only through `decide_hiring`.
    CandidateStatus.OWNER_APPROVAL: (),
    CandidateStatus.APPROVED: (CandidateStatus.HIRED, CandidateStatus.REJECTED),
    CandidateStatus.HIRED: (),
    CandidateStatus.REJECTED: (CandidateStatus.SCREENING,),
}


class PipelineError(Exception):
    """A move the pipeline will not make. Carries a bilingual reason."""

    def __init__(self, ar, en):
        super().__init__(en)
        self.ar = ar
        self.en = en


@transaction.atomic
def move_status(candidate, new_status, actor, reason=""):
    """Advance a candidate, refusing steps the pipeline does not allow."""
    if new_status == candidate.status:
        return candidate
    allowed = ALLOWED_MOVES.get(candidate.status, ())
    if new_status not in allowed:
        raise PipelineError(
            f"مينفعش تنقل من «{candidate.get_status_display()}» للحالة دي.",
            f"Cannot move from {candidate.status} to {new_status}.",
        )
    if new_status == CandidateStatus.OWNER_APPROVAL:
        notify_owner(candidate)
    if new_status == CandidateStatus.REJECTED and reason:
        candidate.rejection_reason = reason[:250]

    old = candidate.status
    candidate.status = new_status
    candidate.save(update_fields=["status", "rejection_reason"])
    services.log(
        actor, "recruitment.status", candidate.code, f"{old} -> {new_status} {reason}".strip()
    )
    return candidate


def notify_owner(candidate):
    """Section 16: the owner is told there is a decision waiting."""
    for person in User.objects.filter(is_active=True, role=Role.ADMIN):
        services.notify(
            person,
            title_ar="مرشح مستني موافقتك",
            title_en="Candidate approval required",
            body_ar=f"{candidate.display_name} — {candidate.vacancy.title if candidate.vacancy else ''}",
            body_en=f"{candidate.display_name} is waiting for a hiring decision.",
            level="warning",
            url="/hr/approvals/",
        )


@transaction.atomic
def decide_hiring(candidate, actor, approve, reason=""):
    """The owner's call, and the only door into ``APPROVED``."""
    if not actor.can_approve_hiring:
        raise PipelineError(
            "الموافقة على التعيين للمالك بس.", "Only the owner approves a hire."
        )
    if candidate.status != CandidateStatus.OWNER_APPROVAL:
        raise PipelineError(
            "المرشح ده مش في مرحلة موافقة المالك.",
            "This candidate is not waiting for approval.",
        )
    candidate.status = CandidateStatus.APPROVED if approve else CandidateStatus.REJECTED
    candidate.owner_decision_at = timezone.now()
    candidate.owner_decision_by = actor
    if not approve:
        candidate.rejection_reason = (reason or "owner rejected")[:250]
    candidate.save(update_fields=[
        "status", "owner_decision_at", "owner_decision_by", "rejection_reason",
    ])
    services.log(
        actor, "recruitment.owner." + ("approve" if approve else "reject"),
        candidate.code, reason,
    )
    return candidate


# ---------------------------------------------------------------------------
# Becoming an employee
# ---------------------------------------------------------------------------

def _unique_username(candidate):
    base = re.sub(r"[^a-z0-9]+", "", (candidate.full_name or "").lower())[:20]
    if not base:
        base = "emp" + re.sub(r"\D", "", candidate.phone or "")[-6:]
    candidate_name = base or "employee"
    suffix = 0
    while User.objects.filter(username=candidate_name).exists():
        suffix += 1
        candidate_name = f"{base}{suffix}"
    return candidate_name


@transaction.atomic
def hire(candidate, actor, *, role=Role.TRANSLATOR, job_title="", joining_date=None,
         salary=None, team_lead=None, username="", password=""):
    """Section 17: turn an approved candidate into an employee, once.

    Nothing is retyped. What the bot collected becomes the profile, the
    contract fields come from the hiring form, and the candidate row keeps
    pointing at the person it became - so the application is still readable
    years later next to the employee it produced.
    """
    if candidate.status != CandidateStatus.APPROVED:
        raise PipelineError(
            "لازم المالك يوافق الأول.", "The owner has to approve first."
        )
    if candidate.hired_user_id:
        raise PipelineError(
            "المرشح ده اتعيّن بالفعل.", "This candidate has already been hired."
        )

    conf = RecruitmentSettings.load()
    joining = joining_date or timezone.localdate()
    person = User(
        username=username or _unique_username(candidate),
        first_name=(candidate.full_name or "").split(" ")[0][:150],
        last_name=" ".join((candidate.full_name or "").split(" ")[1:])[:150],
        email=candidate.email or "",
        phone=candidate.phone or "",
        languages=candidate.languages or "",
        role=role,
        department=candidate.department,
        job_title=job_title or (candidate.vacancy.title if candidate.vacancy else ""),
        joining_date=joining,
        employment_status=EmploymentStatus.PROBATION,
        probation_start=joining,
        probation_end=joining + timedelta(days=conf.probation_days or 90),
        employee_code=next_code(User, "employee_code", "EMP"),
        team_lead=team_lead,
    )
    if candidate.vacancy:
        person.employment_type = candidate.vacancy.employment_type
        person.work_mode = candidate.vacancy.work_mode
    if password:
        person.set_password(password)
    else:
        person.set_unusable_password()
    person.save()

    # Carry the CV across so the employee's file is not empty on day one.
    if candidate.cv:
        try:
            candidate.cv.open("rb")
            person.contract.save(
                candidate.cv_name or "cv.pdf",
                ContentFile(candidate.cv.read()), save=True,
            )
        except Exception as exc:  # noqa: BLE001 - a missing file is not fatal
            logger.warning("Could not copy the CV for %s: %s", candidate.code, exc)
        finally:
            try:
                candidate.cv.close()
            except Exception:  # noqa: BLE001
                pass

    candidate.hired_user = person
    candidate.status = CandidateStatus.HIRED
    candidate.save(update_fields=["hired_user", "status"])

    if salary is not None:
        from .models import SalaryRecord

        SalaryRecord.objects.create(
            user=person, amount=salary, effective_from=joining,
            note=f"Starting salary from {candidate.code}", created_by=actor,
        )

    # The probation reviews exist from day one, so a missed one is something
    # you can see rather than something nobody remembered (section 19).
    from . import employees

    employees.open_probation(person, actor=actor)

    services.log(
        actor, "recruitment.hire", candidate.code,
        f"became {person.username} ({person.employee_code})",
    )
    return person


# ---------------------------------------------------------------------------
# Dashboard - section 26
# ---------------------------------------------------------------------------

def dashboard_counts():
    today = timezone.localdate()
    start = timezone.make_aware(datetime.combine(today, clock_time.min))
    by_status = {
        row["status"]: row["n"]
        for row in Candidate.objects.values("status").annotate(n=Count("id"))
    }
    return {
        "open_vacancies": Vacancy.objects.filter(status=VacancyStatus.OPEN).count(),
        "total_applicants": Candidate.objects.count(),
        "new_applicants": by_status.get(CandidateStatus.NEW, 0),
        "screening": by_status.get(CandidateStatus.SCREENING, 0),
        "interviews_today": Interview.objects.filter(
            scheduled_at__gte=start, scheduled_at__lt=start + timedelta(days=1)
        ).count(),
        "pending_tests": CandidateTest.objects.filter(submission="").count(),
        "tests_completed": CandidateTest.objects.exclude(marked_at=None).count(),
        "final_reviews": by_status.get(CandidateStatus.FINAL_REVIEW, 0),
        "pending_owner": by_status.get(CandidateStatus.OWNER_APPROVAL, 0),
        "approved": by_status.get(CandidateStatus.APPROVED, 0),
        "rejected": by_status.get(CandidateStatus.REJECTED, 0),
        "hired": by_status.get(CandidateStatus.HIRED, 0),
        "on_probation": User.objects.filter(
            is_active=True, employment_status=EmploymentStatus.PROBATION
        ).count(),
    }
