"""What the help assistant can DO for the owner - and only after the owner says yes.

The owner switches this on in the settings (``AppSettings.helpbot_actions_enabled``, off by default) and it works for no one else.
Then they can say "make a shift from 9 to 5" or "deduct a day from so-and-so for this reason" and the assistant does it. It is
built so that the assistant is never the one who decides:

* **A fixed list of orders** (``ACTIONS``). The model is told the list and can only name one of them; anything else is refused.
  Adding an order is adding one entry here, with the door it goes through.
* **The model proposes, the server checks.** Every value it gives is read again here (``resolve``): a person is found in the
  database by the name the owner used - never by an id the model wrote - and a date, a time, an amount, a choice or a code that
  does not hold is refused in words. What is left is stored as a ``HelpAction`` and shown on a card whose words the *server*
  wrote from those checked values, so the model cannot make an order look like something else.
* **The owner confirms** (``run``). One press, by the person it was prepared for, within ``LIFETIME``, once: the row is claimed
  before anything runs, so a second press or a replayed request does nothing.
* **It goes through the same door a click would.** The order is made with the owner's own session, to the very view a button on
  the page posts to (``call``), so that door's rules, refusals and audit rows are the order's. A deduction is therefore only
  recorded, waiting for approval, as every deduction is; nothing here approves money.

What the owner types goes to Claude cleaned (``helpbot.scrub``), but the *values* of an order are the owner's words and are saved as
the order says; they are never sent anywhere but to the door.
"""

import json
import logging
import re
from collections import namedtuple
from dataclasses import dataclass
from datetime import date, time, timedelta
from decimal import Decimal, InvalidOperation

from django.test.client import RequestFactory
from django.urls import resolve, reverse
from django.utils import timezone

from . import clock, helpbot, services
from .models import (
    ApprovalStatus, Client, ClientRequirement, HelpAction, LeaveRequest, LeaveStatus, Role, Task, TaskStatus, User, Violation,
    ViolationKind,
)

log = logging.getLogger("dashboard")

#: How long a prepared order waits for its yes, and how many the owner may run a minute.
LIFETIME = timedelta(minutes=10)
RUNS_PER_MINUTE = 10
#: A date an order may carry is within this many days of today: a typo in the year is not an order.
DATE_SPAN = 366


class Problem(Exception):
    """Something the owner is told in words: a value that does not hold, a person not found. Nothing was done."""

    def __init__(self, ar, en):
        super().__init__(en)
        self.ar, self.en = ar, en

    def text(self, lang):
        return self.ar if lang == "ar" else self.en


def available(conf, user):
    """Is the assistant allowed to prepare orders for this person: the owner, with the switch on and the AI there to read them."""
    return bool(
        getattr(user, "is_authenticated", False) and user.is_admin_role
        and conf.helpbot_actions_enabled and helpbot.ai_available(conf)
    )


# ----------------------------------------------------------------------------------------------------------------------
# Values
# ----------------------------------------------------------------------------------------------------------------------

@dataclass(frozen=True)
class Param:
    name: str
    #: person, text, date, time, int, number, choice, bool, task, client.
    kind: str
    #: What it is called to the owner, in both languages: ``(arabic, english)``.
    label: tuple
    required: bool = True
    default: object = None
    #: Bounds of an int or a number, the longest a text may be, the words a choice may be, the roles a person may have.
    lo: object = None
    hi: object = None
    limit: int = 250
    choices: tuple = ()
    roles: tuple = ()
    #: A person who is switched off may be meant too (switching an account back on).
    anyone: bool = False
    #: One English line for the model: what the value looks like.
    hint: str = ""


#: The kinds of a deduction and of a client requirement, as the card says them.
_KINDS = {
    "discipline": ("قواعد داخلية", "internal rules"),
    "quality": ("خطأ في الترجمة", "translation error"),
    "low_output": ("إنتاجية منخفضة", "low productivity"),
    "unexcused": ("غياب من غير إذن", "absence without permission"),
    "extra_leave": ("إجازة زيادة عن الرصيد", "leave beyond the balance"),
    "target_miss": ("التارجت الشهري ماتحققش", "monthly target missed"),
    "manual": ("تسوية يدوية", "manual adjustment"),
    "like": ("بيحبه", "likes"),
    "dislike": ("مابيحبوش", "dislikes"),
    "rule": ("قاعدة", "rule"),
}


def _kind(value, lang):
    return _KINDS.get(value, (value, value))[0 if lang == "ar" else 1]


_GENERIC_WORDS = frozenset(
    "الموظف موظف المترجم مترجم المترجمه التيم ليدر الليدر استاذ الاستاذ دكتور الدكتور ا م د employee translator leader mr ms".split()
)


def _find_person(text, roles, anyone=False):
    """The one person the owner meant (an active one, unless ``anyone``): by username or by name, never the owner, never a guess
    between two people."""
    query = [word for word in helpbot.words_of(text) if word not in _GENERIC_WORDS]
    if not query:
        raise Problem("مفهمتش اسم الموظف.", "I did not catch the employee's name.")
    pool = User.objects.all() if anyone else User.objects.filter(is_active=True)
    if roles:
        pool = pool.filter(role__in=roles)
    people = [one for one in pool if not one.is_admin_role]
    named = [(one, helpbot.words_of(one.get_full_name()), helpbot.normalize(one.username)) for one in people]
    joined = " ".join(query)

    # The whole name decides; then whoever the username or the words of the name fit; then whoever the beginnings of the words fit.
    # What fits more than one person is asked about, never decided: "ahmed" is a username and also the start of "Ahmed Samir".
    exact = [one for one, words, _u in named if " ".join(words) == joined]
    if len(exact) == 1:
        return exact[0]
    tiers = [
        [one for one, words, username in named if username == joined or all(word in words for word in query)],
        [one for one, words, _u in named if all(any(w.startswith(word) for w in words) for word in query)],
    ]
    for found in tiers:
        if len(found) == 1:
            return found[0]
        if len(found) > 1:
            names = "، ".join(one.short_name for one in found[:5])
            names_en = ", ".join(one.short_name for one in found[:5])
            raise Problem(
                f"فيه أكتر من واحد بالاسم ده: {names}. قول لي الاسم كامل.",
                f"More than one person fits: {names_en}. Give me the full name.",
            )
    raise Problem(f"مفيش موظف بالاسم «{text.strip()[:40]}».", f"No employee is called \"{text.strip()[:40]}\".")


def _code(text, prefix, width):
    found = re.fullmatch(rf"(?:{prefix.lower()})?[\s\-_]*0*([0-9]{{1,6}})", helpbot.normalize(text).strip())
    return f"{prefix}-{int(found.group(1)):0{width}d}" if found else ""


def _value(param, raw, today):
    """One value, checked: JSON-safe, and shaped as the door will be given it. Raises :class:`Problem`."""
    label_ar, label_en = param.label
    bad = Problem(f"القيمة اللي اتقالت لـ «{label_ar}» مش مظبوطة.", f"The value given for \"{label_en}\" is not right.")
    kind = param.kind
    if kind == "person":
        if not isinstance(raw, str):
            raise bad
        person = _find_person(raw, param.roles, param.anyone)
        return {"id": person.pk, "name": person.short_name}
    if kind == "text":
        if not isinstance(raw, str) or "\x00" in raw:
            raise bad
        text = " ".join(raw.split())
        if len(text) > param.limit:
            raise Problem(f"«{label_ar}» أطول من {param.limit} حرف.", f"\"{label_en}\" is longer than {param.limit} characters.")
        return text
    if kind == "date":
        try:
            day = date.fromisoformat(str(raw).strip())
        except ValueError:
            raise bad from None
        if abs((day - today).days) > DATE_SPAN:
            raise Problem("التاريخ ده بعيد عن النهارده أكتر من سنة.", "That date is more than a year from today.")
        return day.isoformat()
    if kind == "time":
        found = re.fullmatch(r"([01]?[0-9]|2[0-3]):([0-5][0-9])", str(raw).strip())
        if not found:
            raise bad
        return f"{int(found.group(1)):02d}:{found.group(2)}"
    if kind == "int":
        if isinstance(raw, bool) or not isinstance(raw, (int, str)) or not re.fullmatch(r"-?[0-9]{1,6}", str(raw).strip()):
            raise bad
        number = int(raw)
        if not param.lo <= number <= param.hi:
            raise Problem(f"«{label_ar}» لازم يبقى من {param.lo} إلى {param.hi}.", f"\"{label_en}\" must be from {param.lo} to {param.hi}.")
        return number
    if kind == "number":
        if isinstance(raw, bool) or not isinstance(raw, (int, float, str)):
            raise bad
        try:
            number = Decimal(str(raw).strip()).quantize(Decimal("0.01"))
        except InvalidOperation:
            raise bad from None
        if not number.is_finite():
            raise bad
        if not Decimal(str(param.lo)) <= number <= Decimal(str(param.hi)):
            raise Problem(f"«{label_ar}» لازم يبقى من {param.lo} إلى {param.hi}.", f"\"{label_en}\" must be from {param.lo} to {param.hi}.")
        return str(number)
    if kind == "choice":
        if not isinstance(raw, str) or raw.strip() not in param.choices:
            raise bad
        return raw.strip()
    if kind == "bool":
        if not isinstance(raw, bool):
            raise bad
        return raw
    if kind == "task":
        code = _code(str(raw), "TSK", 5)
        task = Task.objects.filter(code=code).first() if code else None
        if task is None:
            raise Problem("مفيش تاسك بالكود ده.", "There is no task with that code.")
        return {"code": task.code, "status": task.status}
    if kind == "client":
        code = _code(str(raw), "CL", 4)
        if not code or not Client.objects.filter(code=code).exists():
            raise Problem("مفيش عميل بالكود ده.", "There is no client with that code.")
        return {"code": code}
    raise AssertionError(f"unknown kind {kind}")


def check_values(action, raw, today=None):
    """The values of an order, checked. ``raw`` is whatever the model wrote; only the order's own parameters are read."""
    today = today or timezone.localdate()
    raw = raw if isinstance(raw, dict) else {}
    values = {}
    for param in action.params:
        given = raw.get(param.name)
        if given is None or (isinstance(given, str) and not given.strip()):
            if param.required:
                raise Problem(f"ناقصني: {param.label[0]}.", f"I still need: {param.label[1]}.")
            if param.default is not None:
                values[param.name] = param.default
            continue
        values[param.name] = _value(param, given, today)
    return values


# ----------------------------------------------------------------------------------------------------------------------
# The orders
# ----------------------------------------------------------------------------------------------------------------------

#: The door an order goes through: its URL name, the arguments of the address, and the body (JSON or form fields).
Call = namedtuple("Call", "url args json form", defaults=(None, None))


@dataclass(frozen=True)
class Action:
    name: str
    title: tuple
    #: One English sentence for the model: what the order does.
    about: str
    params: tuple
    #: Cross-checks and lookups that need the values together (raises :class:`Problem`); may add to the values.
    check: object
    call: object
    summary: object
    done: object
    #: A card in red: it removes or stops something.
    danger: bool = False


def _t(lang, ar, en):
    return ar if lang == "ar" else en


def _clock(text, lang):
    return clock.fmt12(time.fromisoformat(text), lang)


def _nothing(values, today):
    return None


# -- a company shift ---------------------------------------------------------------------------------------------------

def _shift_summary(v, lang):
    hours = f"{_clock(v['start'], lang)} - {_clock(v['end'], lang)}"
    name = v.get("title") or hours
    pause = _t(lang, f"، بريك {v['break_minutes']} دقيقة", f", {v['break_minutes']} minute break") if v.get("break_minutes") else ""
    return _t(lang, f"عمل شيفت جديد «{name}» من {_clock(v['start'], lang)} لـ {_clock(v['end'], lang)}{pause}.",
              f"Make a new company shift \"{name}\" from {_clock(v['start'], lang)} to {_clock(v['end'], lang)}{pause}.")


# -- a deduction -------------------------------------------------------------------------------------------------------

def _violation_check(v, today):
    if not (Decimal(v.get("days", "0")) or Decimal(v.get("amount", "0"))):
        raise Problem("حدد الخصم بالأيام أو بمبلغ.", "Give the deduction in days or as an amount.")


def _violation_summary(v, lang):
    parts = []
    if Decimal(v.get("days", "0")):
        parts.append(_t(lang, f"{v['days']} يوم", f"{v['days']} day(s) of pay"))
    if Decimal(v.get("amount", "0")):
        parts.append(_t(lang, f"مبلغ {v['amount']}", f"an amount of {v['amount']}"))
    what = _t(lang, " و".join(parts), " and ".join(parts))
    return _t(
        lang,
        f"تسجيل خصم على {v['employee']['name']} ({_kind(v['kind'], lang)}) عن يوم {v['date']}: {what}، بسبب: {v['reason']}. بيتسجل «مستنية الاعتماد» وماينفذش لحد ما يتعتمد من «المخالفات والخصومات».",
        f"Record a deduction for {v['employee']['name']} ({_kind(v['kind'], lang)}) for {v['date']}: {what}, because: {v['reason']}. It is saved as waiting for approval and applies only once approved under \"Violations\".",
    )


# -- a day off, or other hours, for one day ----------------------------------------------------------------------------

def _override_check(v, today):
    person = User.objects.filter(pk=v["employee"]["id"]).first()
    if person is not None and not person.follows_company_rules:
        raise Problem(f"{v['employee']['name']} مالوش جدول شغل.", f"{v['employee']['name']} has no work schedule.")
    if not v.get("day_off") and not (v.get("start") and v.get("end")):
        raise Problem("قول لي إنه أجازة، أو ابتدا وانتهى إمتى.", "Tell me it is a day off, or when it starts and ends.")


def _override_summary(v, lang):
    who = v["employee"]["name"]
    why = _t(lang, f" السبب (بيظهر في جدوله): {v['reason']}", f" Reason (shown on their schedule): {v['reason']}") if v.get("reason") else ""
    if v.get("day_off"):
        return _t(lang, f"يوم {v['date']} أجازة لـ {who}.{why}", f"Make {v['date']} a day off for {who}.{why}")
    return _t(
        lang, f"يوم {v['date']} شغل {who} من {_clock(v['start'], lang)} لـ {_clock(v['end'], lang)} (من غير ما الجدول الأسبوعي يتغيّر).{why}",
        f"On {v['date']} {who} works {_clock(v['start'], lang)} to {_clock(v['end'], lang)} (the weekly roster is not changed).{why}",
    )


# -- a leave request ---------------------------------------------------------------------------------------------------

def _leave_check(v, today):
    open_ones = LeaveRequest.objects.filter(
        user_id=v["employee"]["id"], status__in=(LeaveStatus.PENDING, LeaveStatus.MANAGER_OK)
    ).order_by("start_date")
    rows = list(open_ones[:6])
    if not rows:
        raise Problem(f"مفيش طلب إجازة مستني عند {v['employee']['name']}.", f"{v['employee']['name']} has no leave request waiting.")
    if len(rows) > 1:
        dates = "، ".join(str(one.start_date) for one in rows)
        raise Problem(f"عند {v['employee']['name']} أكتر من طلب مستني ({dates}). قرّر من «طلبات الإجازة».",
                      f"{v['employee']['name']} has more than one request waiting ({dates}). Decide from \"Leave requests\".")
    v["request"] = {"id": rows[0].pk, "from": str(rows[0].start_date), "to": str(rows[0].end_date)}


def _leave_summary(v, lang):
    span = f"{v['request']['from']} - {v['request']['to']}"
    verb = _t(lang, "الموافقة على" if v["decision"] == "approve" else "رفض", "Approve" if v["decision"] == "approve" else "Reject")
    note = _t(lang, f" (ملاحظة: {v['note']})", f" (note: {v['note']})") if v.get("note") else ""
    return _t(lang, f"{verb} طلب إجازة {v['employee']['name']} ({span}){note}.",
              f"{verb} {v['employee']['name']}'s leave request ({span}){note}.")


# -- a task ------------------------------------------------------------------------------------------------------------

def _cancel_check(v, today):
    if v["task"]["status"] in (TaskStatus.DELIVERED, TaskStatus.CANCELLED):
        raise Problem("التاسك دي اتسلّمت أو اتلغت قبل كده.", "That task was already delivered or cancelled.")


def _assign_check(v, today):
    if v["task"]["status"] not in (TaskStatus.NEW, TaskStatus.AWAITING_LEAD):
        raise Problem("التاسك دي اتبعتت لتيم ليدر قبل كده أو خلصت.", "That task has already been handed on or is finished.")


# -- the staff ---------------------------------------------------------------------------------------------------------

def _active_summary(v, lang):
    if v["active"]:
        return _t(lang, f"إعادة تفعيل حساب {v['employee']['name']}.", f"Switch {v['employee']['name']}'s account back on.")
    return _t(lang, f"إيقاف حساب {v['employee']['name']}: مش هيقدر يدخل السيستم لحد ما تفعّله تاني.",
              f"Switch {v['employee']['name']}'s account off: they cannot sign in until you switch it on again.")


def _alias_check(v, today):
    address = v["address"].lower()
    if address.count("@") != 1 or " " in address or "." not in address.rpartition("@")[2]:
        raise Problem("العنوان ده مش إيميل صحيح.", "That is not a valid address.")
    v["address"] = address


# -- a deadline --------------------------------------------------------------------------------------------------------

def _deadline_check(v, today):
    if not (v.get("days") or v.get("hours") or v.get("minutes")):
        raise Problem("قول الديدلاين بعد كام يوم أو ساعة.", "Tell me the deadline as days or hours from now.")
    if v["task"]["status"] in (TaskStatus.DELIVERED, TaskStatus.CANCELLED):
        raise Problem("التاسك دي اتسلّمت أو اتلغت.", "That task was delivered or cancelled.")


def _deadline_summary(v, lang):
    parts = [(v.get("days"), "يوم", "day(s)"), (v.get("hours"), "ساعة", "hour(s)"), (v.get("minutes"), "دقيقة", "minute(s)")]
    ar = " و".join(f"{n} {a}" for n, a, _e in parts if n)
    en = " and ".join(f"{n} {e}" for n, _a, e in parts if n)
    return _t(lang, f"ديدلاين التاسك {v['task']['code']} بعد {ar} من دلوقتي.", f"Deadline of task {v['task']['code']}: {en} from now.")


# -- a deduction waiting for a decision --------------------------------------------------------------------------------

def _decide_violation_check(v, today):
    rows = list(Violation.objects.filter(user_id=v["employee"]["id"], status=ApprovalStatus.PENDING).order_by("date")[:6])
    if not rows:
        raise Problem(f"مفيش خصم مستني عند {v['employee']['name']}.", f"{v['employee']['name']} has no deduction waiting.")
    if len(rows) > 1:
        dates = "، ".join(str(one.date) for one in rows)
        raise Problem(f"عند {v['employee']['name']} أكتر من خصم مستني ({dates}). قرّر من «المخالفات والخصومات».",
                      f"{v['employee']['name']} has more than one deduction waiting ({dates}). Decide from \"Violations\".")
    v["violation"] = {"id": rows[0].pk, "date": str(rows[0].date)}


def _decide_violation_summary(v, lang):
    yes = v["decision"] == "approve"
    return _t(lang, f"{'اعتماد' if yes else 'رفض'} خصم {v['employee']['name']} عن يوم {v['violation']['date']}.",
              f"{'Approve' if yes else 'Reject'} {v['employee']['name']}'s deduction for {v['violation']['date']}.")


def _client_check(v):
    if not any(key in v for key in _CLIENT_FIELDS):
        raise Problem("قول لي إيه اللي يتغيّر في العميل.", "Tell me what to change on the client.")


def _task_create_check(v, today):
    client = Client.objects.filter(code=v["client"]["code"], is_active=True).first()
    if client is None:
        raise Problem("العميل ده مش شغال أو مش موجود.", "That client is inactive or does not exist.")
    v["client"]["id"] = client.pk


_CLIENT_FIELDS = ("name", "company", "phone", "email", "admin_notes")


def _client_changes(v):
    return [f"{key} = {v[key]}" for key in _CLIENT_FIELDS if key in v]


ACTIONS = {
    action.name: action
    for action in (
        Action(
            "shift.create", ("عمل شيفت", "Make a shift"),
            "Create a company shift (a named set of hours people can be rostered on).",
            (
                Param("title", "text", ("اسم الشيفت", "the shift's name"), required=False, limit=60, hint="optional; leave out to name it by its hours"),
                Param("start", "time", ("بداية الشيفت", "when it starts"), hint="HH:MM, 24-hour"),
                Param("end", "time", ("نهاية الشيفت", "when it ends"), hint="HH:MM, 24-hour; earlier than the start means it crosses midnight"),
                Param("break_minutes", "int", ("مدة البريك بالدقايق", "the break in minutes"), required=False, default=0, lo=0, hi=300, hint="optional, 0 to 300"),
            ),
            _nothing,
            lambda v: Call("v1_hr_shift_save", (), json={"values": {
                "name_ar": v.get("title", ""), "start_time": v["start"], "end_time": v["end"],
                "break_minutes": v.get("break_minutes", 0), "is_active": True,
            }}),
            _shift_summary,
            lambda v, lang: _t(lang, "الشيفت اتعمل. هتلاقيه في «الشيفتات».", "The shift was made. You will find it under \"Shifts\"."),
        ),
        Action(
            "violation.create", ("تسجيل خصم", "Record a deduction"),
            "Record a deduction against a translator, in days of pay or as an amount. It is saved as WAITING FOR APPROVAL; it never applies by itself.",
            (
                Param("employee", "person", ("المترجم", "the translator"), roles=(Role.TRANSLATOR,), hint="the name the owner used"),
                Param("kind", "choice", ("نوع الخصم", "the kind"), required=False, default="manual", choices=tuple(ViolationKind.values),
                      hint="one of: discipline (internal rules), quality (translation error), low_output, unexcused (absence without permission), extra_leave, target_miss, manual (default)"),
                Param("days", "number", ("عدد الأيام", "days of pay"), required=False, default="0.00", lo=0, hi=30, hint="optional; days of pay, e.g. 1 or 0.5"),
                Param("amount", "number", ("المبلغ", "an amount"), required=False, default="0.00", lo=0, hi=1000000, hint="optional; a flat amount"),
                Param("date", "date", ("التاريخ", "the date"), required=False, hint="YYYY-MM-DD; today when the owner did not say"),
                Param("reason", "text", ("السبب", "the reason"), limit=250, hint="the owner's own words"),
            ),
            _violation_check,
            lambda v: Call("v1_accounts_violation_create", (), json={"values": {
                "user": v["employee"]["id"], "date": v["date"], "kind": v["kind"],
                "penalty_days": v.get("days", "0.00"), "penalty_amount": v.get("amount", "0.00"), "reason": v["reason"],
            }}),
            _violation_summary,
            lambda v, lang: _t(lang, "الخصم اتسجل ومستني الاعتماد من «المخالفات والخصومات».", "The deduction was recorded and waits for approval under \"Violations\"."),
        ),
        Action(
            "day.override", ("تغيير يوم", "Change one day"),
            "Make one date a day off for an employee, or give them other hours on that date. The weekly roster is not touched.",
            (
                Param("employee", "person", ("الموظف", "the employee")),
                Param("date", "date", ("اليوم", "the date"), hint="YYYY-MM-DD"),
                Param("day_off", "bool", ("أجازة؟", "is it a day off"), required=False, default=False, hint="true for a day off"),
                Param("start", "time", ("بداية الشغل", "start"), required=False, hint="HH:MM, only when it is not a day off"),
                Param("end", "time", ("نهاية الشغل", "end"), required=False, hint="HH:MM, only when it is not a day off"),
                Param("reason", "text", ("السبب", "the reason"), required=False, limit=200),
            ),
            _override_check,
            lambda v: Call("v1_hr_override_add", (), json={"user": v["employee"]["id"], "values": {
                "date": v["date"], "is_day_off": bool(v.get("day_off")), "start_time": v.get("start", ""),
                "end_time": v.get("end", ""), "reason": v.get("reason", ""),
            }}),
            _override_summary,
            lambda v, lang: _t(lang, "اليوم اتغيّر. هتلاقيه في «جداول العمل».", "The day was changed. You will find it under \"Schedules\"."),
        ),
        Action(
            "leave.decide", ("قرار إجازة", "Decide a leave request"),
            "Approve or reject the one leave request that is waiting for an employee.",
            (
                Param("employee", "person", ("الموظف", "the employee")),
                Param("decision", "choice", ("القرار", "the decision"), choices=("approve", "reject"), hint="approve or reject"),
                Param("note", "text", ("ملاحظة", "a note"), required=False, limit=250),
            ),
            _leave_check,
            lambda v: Call("v1_leave_decide", (v["request"]["id"], v["decision"]), json={"note": v.get("note", "")}),
            _leave_summary,
            lambda v, lang: _t(lang, "القرار اتسجّل.", "The decision was recorded."),
        ),
        Action(
            "task.create", ("تاسك جديدة", "Create a task"),
            "Create a new task for a client (found by its code): title, languages and optional deadline, priority and word count.",
            (
                Param("client", "client", ("كود العميل", "the client's code"), hint="like CL-0007"),
                Param("title", "text", ("عنوان التاسك", "the title"), limit=200),
                Param("source_lang", "text", ("لغة الأصل", "the source language"), limit=30, hint="like English or EN"),
                Param("target_lang", "text", ("لغة الترجمة", "the target language"), limit=30, hint="like Arabic or AR"),
                Param("description", "text", ("وصف", "a description"), required=False, limit=2000),
                Param("priority", "choice", ("الأولوية", "the priority"), required=False, default="normal", choices=("low", "normal", "high", "urgent"), hint="low, normal (default), high or urgent"),
                Param("word_count", "int", ("عدد الكلمات", "the word count"), required=False, lo=0, hi=1000000, hint="optional"),
                Param("days", "int", ("ديدلاين أيام", "deadline days"), required=False, default=0, lo=0, hi=365, hint="optional; days from now"),
                Param("hours", "int", ("ديدلاين ساعات", "deadline hours"), required=False, default=0, lo=0, hi=2000, hint="optional; hours from now"),
            ),
            _task_create_check,
            lambda v: Call("v1_task_create", (), json={
                "client": v["client"]["id"], "title": v["title"], "description": v.get("description", ""),
                "source_lang": v["source_lang"], "target_lang": v["target_lang"], "priority": v.get("priority", "normal"),
                "word_count": v.get("word_count"),
                "deadline": {"days": str(v.get("days") or ""), "hours": str(v.get("hours") or ""), "minutes": ""},
            }),
            lambda v, lang: _t(
                lang, f"عمل تاسك جديدة «{v['title']}» للعميل {v['client']['code']} ({v['source_lang']} إلى {v['target_lang']}).",
                f"Create a task \"{v['title']}\" for client {v['client']['code']} ({v['source_lang']} to {v['target_lang']}).",
            ),
            lambda v, lang: _t(lang, "التاسك اتعملت. هتلاقيها في «التاسكات».", "The task was created. You will find it under \"Tasks\"."),
        ),
        Action(
            "task.cancel", ("إلغاء تاسك", "Cancel a task"),
            "Cancel a task that has not been delivered.",
            (
                Param("task", "task", ("كود التاسك", "the task's code"), hint="like TSK-00012"),
                Param("reason", "text", ("السبب", "the reason"), required=False, limit=200),
            ),
            _cancel_check,
            lambda v: Call("api_task_action", (v["task"]["code"], "cancel"), form={"reason": v.get("reason", "")}),
            lambda v, lang: _t(
                lang,
                f"إلغاء التاسك {v['task']['code']} وتنبيه كل اللي عليها (المترجم كمان)" + (f". السبب اللي هيوصلهم: {v['reason']}" if v.get("reason") else "."),
                f"Cancel task {v['task']['code']} and tell everybody on it (the translator too)" + (f". The reason they will read: {v['reason']}" if v.get("reason") else "."),
            ),
            lambda v, lang: _t(lang, f"التاسك {v['task']['code']} اتلغت.", f"Task {v['task']['code']} was cancelled."),
            danger=True,
        ),
        Action(
            "task.assign_lead", ("إسناد تاسك لتيم ليدر", "Give a task to a team leader"),
            "Send a new task to one team leader, who then has a short time to accept it.",
            (
                Param("task", "task", ("كود التاسك", "the task's code"), hint="like TSK-00012"),
                Param("leader", "person", ("التيم ليدر", "the team leader"), roles=(Role.TEAM_LEAD,)),
            ),
            _assign_check,
            lambda v: Call("api_assign_lead", (v["task"]["code"],), form={"user": str(v["leader"]["id"])}),
            lambda v, lang: _t(lang, f"إرسال التاسك {v['task']['code']} للتيم ليدر {v['leader']['name']}.", f"Send task {v['task']['code']} to team leader {v['leader']['name']}."),
            lambda v, lang: _t(lang, "اتبعتت للتيم ليدر.", "It was sent to the team leader."),
        ),
        Action(
            "client.requirement", ("متطلب لعميل", "Add a client requirement"),
            "Add a requirement or note to a client, found by its code. It is shown on every task of that client.",
            (
                Param("client", "client", ("كود العميل", "the client's code"), hint="like CL-0007"),
                Param("kind", "choice", ("النوع", "the kind"), required=False, default="rule", choices=tuple(ClientRequirement.Kind.values), hint="like, dislike or rule (default)"),
                Param("text", "text", ("المتطلب", "the requirement"), limit=2000),
            ),
            _nothing,
            lambda v: Call("v1_client_requirement", (v["client"]["code"],), json={"kind": v["kind"], "text": v["text"]}),
            lambda v, lang: _t(
                lang,
                f"إضافة متطلب ({_kind(v['kind'], lang)}) للعميل {v['client']['code']}: {v['text']}. هيظهر لكل مترجم على تاسكات العميل ده.",
                f"Add a requirement ({_kind(v['kind'], lang)}) to client {v['client']['code']}: {v['text']}. Every translator on that client's tasks will read it.",
            ),
            lambda v, lang: _t(lang, "المتطلب اتضاف.", "The requirement was added."),
        ),
        Action(
            "task.deadline", ("ديدلاين تاسك", "Set a task's deadline"),
            "Set the client deadline of a task, counted from now in days, hours and minutes.",
            (
                Param("task", "task", ("كود التاسك", "the task's code"), hint="like TSK-00012"),
                Param("days", "int", ("أيام", "days"), required=False, default=0, lo=0, hi=365, hint="optional"),
                Param("hours", "int", ("ساعات", "hours"), required=False, default=0, lo=0, hi=2000, hint="optional"),
                Param("minutes", "int", ("دقايق", "minutes"), required=False, default=0, lo=0, hi=10000, hint="optional"),
            ),
            _deadline_check,
            lambda v: Call("api_set_deadline", (v["task"]["code"],), form={
                "deadline_days": str(v.get("days", 0) or ""), "deadline_hours": str(v.get("hours", 0) or ""),
                "deadline_minutes": str(v.get("minutes", 0) or ""),
            }),
            _deadline_summary,
            lambda v, lang: _t(lang, "الديدلاين اتحدد.", "The deadline was set."),
        ),
        Action(
            "violation.decide", ("قرار خصم", "Decide a deduction"),
            "Approve or reject the one deduction that is waiting for an employee. Approving makes it count in their pay.",
            (
                Param("employee", "person", ("الموظف", "the employee")),
                Param("decision", "choice", ("القرار", "the decision"), choices=("approve", "reject"), hint="approve or reject"),
            ),
            _decide_violation_check,
            lambda v: Call("v1_accounts_violation_decide", (v["violation"]["id"], v["decision"]), json={}),
            _decide_violation_summary,
            lambda v, lang: _t(lang, "القرار اتسجّل.", "The decision was recorded."),
            danger=True,
        ),
        Action(
            "client.update", ("تعديل عميل", "Edit a client"),
            "Change a client's name, company, main phone, main e-mail or admin note, found by its code. Only the values given change.",
            (
                Param("client", "client", ("كود العميل", "the client's code"), hint="like CL-0007"),
                Param("name", "text", ("الاسم", "the name"), required=False, limit=120),
                Param("company", "text", ("الشركة", "the company"), required=False, limit=120),
                Param("phone", "text", ("رقم الواتساب", "the WhatsApp number"), required=False, limit=30, hint="digits with the country code"),
                Param("email", "text", ("الإيميل", "the e-mail"), required=False, limit=120),
                Param("admin_notes", "text", ("ملاحظة الأدمن", "the admin note"), required=False, limit=1000),
            ),
            lambda v, today: _client_check(v),
            lambda v: Call("v1_admin_client_save", (v["client"]["code"],), json={"values": {
                key: v[key] for key in ("name", "company", "phone", "email", "admin_notes") if key in v
            }}),
            lambda v, lang: _t(lang, f"تعديل العميل {v['client']['code']}: " + "، ".join(_client_changes(v)) + ".",
                               f"Edit client {v['client']['code']}: " + ", ".join(_client_changes(v)) + "."),
            lambda v, lang: _t(lang, "العميل اتعدّل.", "The client was changed."),
        ),
        Action(
            "staff.message", ("رسالة لموظف", "Message a colleague"),
            "Send a chat message from the owner to one employee, in the colleagues chat (never to a client).",
            (
                Param("employee", "person", ("الموظف", "the employee")),
                Param("text", "text", ("نص الرسالة", "the message"), limit=1000, hint="exactly the words the owner wants sent"),
            ),
            _nothing,
            lambda v: Call("v1_staff_send", (v["employee"]["id"],), form={"body": v["text"]}),
            lambda v, lang: _t(lang, f"إرسال رسالة لـ {v['employee']['name']}: «{v['text']}».", f"Send {v['employee']['name']} the message: \"{v['text']}\"."),
            lambda v, lang: _t(lang, "الرسالة اتبعتت.", "The message was sent."),
        ),
        Action(
            "employee.set_active", ("إيقاف أو تفعيل حساب", "Switch an account off or on"),
            "Switch an employee's account off (they cannot sign in) or back on.",
            (
                Param("employee", "person", ("الموظف", "the employee"), anyone=True),
                Param("active", "bool", ("مفعّل؟", "active"), hint="false to switch the account off, true to switch it on"),
            ),
            _nothing,
            lambda v: Call("v1_admin_user_save", (v["employee"]["id"],), json={"values": {"is_active": v["active"]}}),
            _active_summary,
            lambda v, lang: _t(lang, "حساب الموظف اتغيّر.", "The account was changed."),
            danger=True,
        ),
        Action(
            "employee.mail_alias", ("عنوان ميل لموظف", "Give an employee a mail address"),
            "Set the company mail address an operation or Sales person receives mail on.",
            (
                Param("employee", "person", ("الموظف", "the employee"), roles=(Role.OPERATION, Role.SALES)),
                Param("address", "text", ("العنوان", "the address"), limit=120, hint="an address already on the company mailbox"),
            ),
            _alias_check,
            lambda v: Call("v1_admin_user_save", (v["employee"]["id"],), json={"values": {"mail_alias": v["address"]}}),
            lambda v, lang: _t(lang, f"{v['employee']['name']} يستقبل ميلات العنوان {v['address']} (والأدمن)، وردّه يطلع منه.",
                               f"{v['employee']['name']} receives mail for {v['address']} (with the owner) and replies from it."),
            lambda v, lang: _t(lang, "العنوان اتحدد.", "The address was set."),
        ),
    )
}


# ----------------------------------------------------------------------------------------------------------------------
# What the model is told
# ----------------------------------------------------------------------------------------------------------------------

ORDERS_INSTRUCTIONS = (
    "The person you are talking to is the owner, and they have allowed you to prepare ORDERS for them. These are the only orders "
    "that exist; you cannot do anything else in the system.\n"
    "When the owner asks you to DO one of them (not to explain how), reply with \"action\": {\"name\": \"<order>\", \"params\": {...}} "
    "and a one-sentence \"answer\". You never carry the order out and you never say it is done: the system carries it out "
    "itself and shows the owner what it did.\n"
    "- Use only the parameters listed for the order, with the formats given. Dates are YYYY-MM-DD and times are HH:MM (24-hour); "
    "work them out from today's date, which is given to you.\n"
    "- Refer to people by the name the owner used, exactly as they wrote it. Never invent a person, a number, an amount, a date or a "
    "reason: if a required value is missing or unclear, ask for it in \"answer\" and set \"action\" to null.\n"
    "- One order per reply. If the owner only asks how to do something, answer from the guides and set \"action\" to null.\n"
    "- Add \"action\": null (or leave it out) in every reply that is not an order."
)


OPEN_INSTRUCTIONS = (
    "The person you are talking to is the owner, and you can OPEN an employee's file for them. When they ask you to open, show or "
    "go to a named employee's file or profile, reply with \"open_employee\": \"<the name exactly as they wrote it>\" and a one-sentence "
    "\"answer\"; the system finds the person and puts the button on the screen. Never invent a name; leave \"open_employee\" out in "
    "every other reply."
)


def open_employee(name, lang):
    """The page of the employee file the owner named: ``(title, path)``. Raises :class:`Problem` when no one person fits.

    Only a link: nothing is changed, and the file's own page decides what the owner sees there.
    """
    person = _find_person(name, (), anyone=True)
    return (
        _t(lang, f"ملف {person.short_name}", f"{person.short_name}'s file"),
        f"/hr/employees/{person.pk}",
    )


def prompt_text():
    """The orders and their parameters, as the model is told them (the same for every owner, so it can be cached)."""
    lines = [ORDERS_INSTRUCTIONS, "ORDERS:"]
    for action in ACTIONS.values():
        params = []
        for param in action.params:
            hint = f" - {param.hint}" if param.hint else ""
            params.append(f"{param.name} ({param.kind}{'' if param.required else ', optional'}{hint})")
        lines.append(f"- {action.name}: {action.about} Parameters: " + "; ".join(params) + ".")
    return "\n".join(lines)


# ----------------------------------------------------------------------------------------------------------------------
# Preparing, confirming, running
# ----------------------------------------------------------------------------------------------------------------------

def prepare(user, name, raw_params, lang, today=None):
    """Check an order the model proposed and keep it, waiting for the owner. Raises :class:`Problem` with nothing kept.

    One order waits at a time: preparing a new one withdraws the one before it, so the card on the screen is the only live one.
    """
    action = ACTIONS.get(name)
    if action is None:
        raise Problem("الأمر ده مش من الأوامر اللي أقدر أجهزها.", "That is not an order I can prepare.")
    today = today or timezone.localdate()
    try:
        values = check_values(action, raw_params, today)
        if "date" in {param.name for param in action.params} and "date" not in values:
            values["date"] = today.isoformat()
        action.check(values, today)
        summary = {"ar": action.summary(values, "ar"), "en": action.summary(values, "en")}
    except Problem:
        raise
    except Exception as failure:  # noqa: BLE001 - a value nobody thought of is a value that does not hold
        log.warning("help assistant: an order's values were refused (%s)", type(failure).__name__)
        raise Problem("القيم اللي اتقالت مش مظبوطة.", "The values given are not right.") from None
    HelpAction.objects.filter(user=user, status=HelpAction.Status.PENDING).update(
        status=HelpAction.Status.CANCELLED, finished_at=timezone.now()
    )
    return HelpAction.objects.create(user=user, name=name, params=values, summary=summary)


def card(row, lang):
    """A prepared order as the page draws it: what it is, what it will do, and how long it waits."""
    action = ACTIONS[row.name]
    left = max(0, int((row.created_at + LIFETIME - timezone.now()).total_seconds()))
    return {
        "id": row.pk,
        "title": action.title[0 if lang == "ar" else 1],
        "summary": row.summary.get("ar" if lang == "ar" else "en", ""),
        "danger": action.danger,
        "expires_in": left,
    }


def _call(request, user, call):
    """Make the order's request, as the owner, to the view a click would reach. ``(status, payload)``."""
    path = reverse(f"dashboard:{call.url}", args=call.args)
    extra = {key: request.META[key] for key in ("REMOTE_ADDR", "HTTP_X_FORWARDED_FOR", "HTTP_USER_AGENT") if key in request.META}
    factory = RequestFactory()
    if call.json is not None:
        fake = factory.post(path, json.dumps(call.json), content_type="application/json", **extra)
    else:
        fake = factory.post(path, call.form or {}, **extra)
    fake.user = user
    fake.session = getattr(request, "session", {})
    match = resolve(path)
    try:
        response = match.func(fake, *match.args, **match.kwargs)
        payload = json.loads(response.content.decode("utf-8"))
        return response.status_code, payload if isinstance(payload, dict) else {}
    except Exception as failure:  # noqa: BLE001 - a door that blew up is a refused order, not a broken page
        log.warning("help assistant: the door for an order failed (%s)", type(failure).__name__)
        return 500, {}


_CODES = {
    "bad_status": ("حالة التاسك دلوقتي مابتسمحش بالأمر ده.", "The task's state does not allow that."),
    "forbidden": ("مش مسموح.", "Not allowed."),
    "not_found": ("مش موجود.", "Not found."),
    "already_decided": ("اتقرر فيه قبل كده.", "It was already decided."),
    "invalid": ("السيستم رفض القيم.", "The system refused the values."),
}


def _refusal(status, payload, lang):
    """Why a door said no, in words: its own sentence when it gave one, else what is known about the code."""
    if status >= 500:
        return _t(
            lang,
            "حصلت مشكلة أثناء التنفيذ ومش متأكد إن الأمر اتنفّذ. راجع الصفحة قبل ما تكرره.",
            "Something went wrong while it ran and I cannot be sure it was not carried out. Check the page before you repeat it.",
        )
    errors = payload.get("errors")
    if isinstance(errors, dict):
        sentences = [str(m) for messages in errors.values() for m in (messages if isinstance(messages, list) else [messages])]
        if sentences:
            return "; ".join(sentences[:3])[:300]
    for key in (("message_en", "message") if lang == "en" else ("message", "message_en")):
        if isinstance(payload.get(key), str) and payload[key]:
            return payload[key][:300]
    code = payload.get("error")
    if isinstance(code, str) and code in _CODES:
        return _CODES[code][0 if lang == "ar" else 1]
    if isinstance(code, str) and " " in code:
        return code[:300]
    return _t(lang, "السيستم رفض الأمر ومحصلش حاجة.", "The system refused the order and nothing was done.")


class NotAllowed(Exception):
    """The owner's yes cannot be used: ``code`` says why (``gone``, ``expired``, ``done``, ``busy``)."""

    def __init__(self, code):
        super().__init__(code)
        self.code = code


def run(request, user, pk, lang):
    """The owner's yes: carry out the prepared order ``pk`` once. ``(row, ok, message)``.

    Only the person it was prepared for, only while it waits and before it expires; a second press finds it already claimed.
    """
    row = HelpAction.objects.filter(pk=pk, user=user).first()
    if row is None or row.name not in ACTIONS:
        raise NotAllowed("gone")
    if row.status != HelpAction.Status.PENDING:
        raise NotAllowed("done")
    if timezone.now() - row.created_at > LIFETIME:
        HelpAction.objects.filter(pk=pk, status=HelpAction.Status.PENDING).update(
            status=HelpAction.Status.CANCELLED, finished_at=timezone.now()
        )
        raise NotAllowed("expired")
    since = timezone.now() - timedelta(minutes=1)
    if HelpAction.objects.filter(user=user, finished_at__gte=since).exclude(status=HelpAction.Status.CANCELLED).count() >= RUNS_PER_MINUTE:
        raise NotAllowed("busy")
    # The claim: only one request can move it out of "waiting".
    if not HelpAction.objects.filter(pk=pk, status=HelpAction.Status.PENDING).update(status=HelpAction.Status.RUNNING):
        raise NotAllowed("done")

    action = ACTIONS[row.name]
    status, payload = _call(request, user, action.call(row.params))
    ok = status == 200 and payload.get("ok") is True
    message = {
        "ar": action.done(row.params, "ar") if ok else _refusal(status, payload, "ar"),
        "en": action.done(row.params, "en") if ok else _refusal(status, payload, "en"),
    }
    row.status = HelpAction.Status.DONE if ok else HelpAction.Status.FAILED
    row.result = {"ok": ok, **message}
    row.finished_at = timezone.now()
    row.save(update_fields=["status", "result", "finished_at"])
    # Which boxes, not what is in them (the door's own rule for a client's identity).
    said = ", ".join(sorted(key for key in _CLIENT_FIELDS if key in row.params)) if row.name == "client.update" else row.summary.get("en", "")
    services.log(user, "help.action", row.name, f"{'done' if ok else 'refused'}: {said}"[:250])
    return row, ok, message["ar" if lang == "ar" else "en"]


def cancel(user, pk):
    """The owner's no. ``True`` when a waiting order of theirs was withdrawn."""
    return bool(
        HelpAction.objects.filter(pk=pk, user=user, status=HelpAction.Status.PENDING)
        .update(status=HelpAction.Status.CANCELLED, finished_at=timezone.now())
    )
