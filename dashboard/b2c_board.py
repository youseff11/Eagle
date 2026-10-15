"""B2C part 2: the B2C numbers (15/10/2026, the B2C requirements' section 9).

One answer for every reader, narrowed to whom they may read: a Sales person their own row, the B2C manager and the owner
every B2C Sales person's, with the team's total, the breakdowns and the lists of companies that need someone.

The six figures of the requirements, each with what it is made of (a rate is ``{"value", "part", "whole"}``, the value
``None`` when there is nothing to divide by - "not measured", never 0%):

* visit achievement - verified visits / the visits owed for the period (``b2c.due_for_period``: the month's target, less
  approved leave, spread over the days worked);
* lead conversion - companies that became qualified after a verified visit / the verified visits;
* quotation conversion - quotations sent / companies that became qualified;
* win rate - won / (won + lost);
* follow-up compliance - follow-ups done on their day / the follow-ups that fell due;
* visit verification rate - verified / visits sent to the manager (verified, turned down or waiting).

«Qualified» is a company moved to «Requirement collected» or any stage after it (``QUALIFIED``). Every count is of the
period (Cairo days, both ends included) except what says "now": the stages, the untouched companies, the overdue
follow-ups, the open deals. A visit belongs to the day «I arrived» was pressed. A filter by source or governorate narrows
everything to the companies that have it.
"""

from datetime import datetime, time as dtime, timedelta
from decimal import Decimal

from django.db.models import Count, Min, Q, Sum
from django.utils import timezone

from . import b2c
from .b2b import CLOSED_STATUSES, _open_follow_ups
from .models import (
    B2C_STATUSES, B2C_TRACKS, AppSettings, Channel, FieldVisit, Lead, LeadActivity, LeadStatus, Market, OutboundMessage,
    Quotation, Role, SalesTrack, User,
)

#: The stages that say the company is a real opportunity: its need is known.
QUALIFIED = (LeadStatus.REQUIREMENT, LeadStatus.QUOTED, LeadStatus.WAITING, LeadStatus.NEGOTIATION, LeadStatus.WON)
MAX_DAYS = 366
#: The most companies a list of the board names.
MAX_LIST = 50
#: The most values a filter offers.
MAX_CHOICES = 150
OUTREACH = (LeadActivity.Kind.WHATSAPP, LeadActivity.Kind.EMAIL, LeadActivity.Kind.CALL, LeadActivity.Kind.VISIT)
SUBMITTED = (FieldVisit.Status.PENDING, FieldVisit.Status.VERIFIED, FieldVisit.Status.REJECTED)

#: The counts a row carries; zero is a real zero.
COUNTS = (
    "new_leads", "contacted", "calls", "messages", "planned", "submitted", "verified", "rejected", "pending", "due",
    "qualified", "qualified_from_visits", "quotations", "quotes_waiting", "won", "lost", "follow_ups_on_time",
    "follow_ups_late", "follow_ups_missed", "overdue_now", "untouched", "holding",
)


def has_door(user):
    """The B2C numbers are the B2C Sales people's (their own) and the owner's."""
    return bool(getattr(user, "is_authenticated", False) and (user.is_admin_role or user.is_b2c_sales))


def rate(part, whole):
    return {"value": None if not whole else round(100 * part / whole), "part": part, "whole": whole}


class Filters:
    """What the board is narrowed to: a person (the manager's choice), a source and a governorate (as written on the rows,
    compared without case)."""

    def __init__(self, person=None, source="", governorate=""):
        self.person, self.source, self.governorate = person, source.strip(), governorate.strip()

    def q(self, prefix=""):
        """The companies that pass, as a filter on ``Lead`` reached through ``prefix`` (``"lead__"``, ``""``...)."""
        out = Q(**{f"{prefix}sheet__market": Market.B2C})
        if self.source:
            out &= Q(**{f"{prefix}source__iexact": self.source})
        if self.governorate:
            out &= Q(**{f"{prefix}governorate__iexact": self.governorate})
        return out


def team(user):
    """Everybody the reader may read: their own self for a Sales person; for the manager and the owner every B2C Sales
    person still working (not the managers, unless they hold companies themselves) and anybody who holds a B2C sheet."""
    if not b2c.manages(user):
        return [user] if user.is_b2c_sales else []
    rows = User.objects.filter(role=Role.SALES).filter(
        Q(sales_track__in=B2C_TRACKS, is_active=True, is_sales_manager=False)
        | Q(lead_sheets__market=Market.B2C)
        | Q(field_visits__isnull=False)
    ).distinct()
    return list(rows.order_by("first_name", "username"))


def _bounds(start, end):
    return (
        timezone.make_aware(datetime.combine(start, dtime.min)),
        timezone.make_aware(datetime.combine(end + timedelta(days=1), dtime.min)),
    )


def _row(person, start, end, filters, today, conf):
    start_at, end_at = _bounds(start, end)
    lead_q = filters.q()
    mine = Lead.objects.filter(lead_q, sheet__assigned_to=person)
    acts = LeadActivity.objects.filter(filters.q("lead__"), owner=person, at__gte=start_at, at__lt=end_at)
    stage = acts.filter(kind=LeadActivity.Kind.STATUS)
    visits = FieldVisit.objects.filter(filters.q("lead__"), person=person)
    month = visits.filter(check_in_at__gte=start_at, check_in_at__lt=end_at)
    verified = month.filter(status=FieldVisit.Status.VERIFIED)
    planned = visits.filter(status=FieldVisit.Status.PLANNED).filter(
        Q(planned_at__gte=start_at, planned_at__lt=end_at) | Q(planned_at__isnull=True, created_at__gte=start_at, created_at__lt=end_at)
    )
    # Qualified after a verified visit: the company moved to a qualified stage on or after the first verified «I arrived».
    first_visit = dict(verified.values("lead_id").annotate(first=Min("check_in_at")).values_list("lead_id", "first"))
    after = 0
    if first_visit:
        moves = LeadActivity.objects.filter(
            kind=LeadActivity.Kind.STATUS, status__in=QUALIFIED, lead_id__in=list(first_visit),
        ).values_list("lead_id", "at")
        after = len({lead for lead, at in moves if at >= first_visit[lead]})
    done = [
        (timezone.localtime(at).date(), due)
        for at, due in acts.filter(follow_up_for__isnull=False).values_list("at", "follow_up_for")
    ]
    open_follow_ups = _open_follow_ups(mine, today)
    quotes = Quotation.objects.filter(filters.q("lead__"), owner=person)
    sent = quotes.filter(sent_at__gte=start_at, sent_at__lt=end_at)
    is_open = mine.exclude(status__in=CLOSED_STATUSES)
    field = person.sales_track == SalesTrack.B2C_FIELD or visits.exists()
    row = {
        "person": {"id": person.pk, "name": person.get_full_name() or person.username, "active": person.is_active,
                   "track": person.sales_track},
        "field": field,
        "new_leads": mine.filter(created_at__gte=start_at, created_at__lt=end_at).count(),
        "contacted": acts.filter(incoming=False, kind__in=OUTREACH).values("lead").distinct().count(),
        "calls": acts.filter(kind=LeadActivity.Kind.CALL).count(),
        "messages": OutboundMessage.objects.filter(
            filters.q("client__leads__"), owner=person, created_at__gte=start_at, created_at__lt=end_at,
            client__leads__sheet__assigned_to=person, status=OutboundMessage.Status.SENT,
            channel__in=(Channel.WHATSAPP, Channel.EMAIL),
        ).distinct().count(),
        "planned": planned.count(),
        "submitted": month.filter(status__in=SUBMITTED).count(),
        "verified": verified.count(),
        "rejected": month.filter(status=FieldVisit.Status.REJECTED).count(),
        "pending": month.filter(status=FieldVisit.Status.PENDING).count(),
        # Owed only by a field person: the online people have no visit target.
        "due": b2c.due_for_period(person, start, end, conf) if person.sales_track == SalesTrack.B2C_FIELD else 0,
        "qualified": stage.filter(status__in=QUALIFIED).values("lead").distinct().count(),
        "qualified_from_visits": after,
        "quotations": sent.count(),
        "quotes_waiting": quotes.filter(status=Quotation.Status.SENT).count(),
        "won": stage.filter(status=LeadStatus.WON).values("lead").distinct().count(),
        "lost": stage.filter(status=LeadStatus.LOST).values("lead").distinct().count(),
        "follow_ups_on_time": sum(1 for day, due in done if day == due),
        "follow_ups_late": sum(1 for day, due in done if day > due),
        "follow_ups_missed": sum(1 for lead in open_follow_ups if lead.next_follow_up < today and start <= lead.next_follow_up <= end),
        "overdue_now": sum(1 for lead in open_follow_ups if lead.next_follow_up < today),
        "untouched": _untouched(is_open).count(),
        "holding": mine.count(),
        # What the open companies are worth, as the Sales people guess it (no currency, as on the sheet).
        "open_value": f"{is_open.aggregate(total=Sum('deal_value'))['total'] or Decimal(0):.2f}",
        "quote_values": _per_currency(sent),
    }
    return _rates(row)


def _untouched(rows):
    """Open companies nobody reached in any way: no message, no call, nobody at the door (a visit only planned is not one)."""
    return rows.filter(
        whatsapp_at__isnull=True, email_at__isnull=True, call_at__isnull=True, last_outreach_at__isnull=True,
    ).exclude(visits__check_in_at__isnull=False)


def _per_currency(quotes):
    """``{currency: {"total", "count"}}`` of quotations: dollars and pounds are never added together."""
    out = {}
    for currency, total, count in quotes.values("currency").annotate(total=Sum("total"), count=Count("id")).values_list("currency", "total", "count"):
        out[currency] = {"total": f"{total:.2f}", "count": count}
    return out


def _rates(row):
    row["visit_achievement"] = rate(row["verified"], row["due"])
    row["verification_rate"] = rate(row["verified"], row["submitted"])
    row["lead_conversion"] = rate(row["qualified_from_visits"], row["verified"])
    row["quotation_conversion"] = rate(row["quotations"], row["qualified"])
    row["win_rate"] = rate(row["won"], row["won"] + row["lost"])
    row["follow_up_compliance"] = rate(
        row["follow_ups_on_time"], row["follow_ups_on_time"] + row["follow_ups_late"] + row["follow_ups_missed"],
    )
    return row


def _total(rows):
    total = {name: sum(row[name] for row in rows) for name in COUNTS}
    total["open_value"] = f"{sum(Decimal(row['open_value']) for row in rows):.2f}"
    values = {}
    for row in rows:
        for currency, figure in row["quote_values"].items():
            sum_, count = values.get(currency, (Decimal(0), 0))
            values[currency] = (sum_ + Decimal(figure["total"]), count + figure["count"])
    total["quote_values"] = {currency: {"total": f"{s:.2f}", "count": c} for currency, (s, c) in sorted(values.items())}
    # The average quotation, per currency (the requirements' «متوسط قيمة عرض السعر»).
    total["quote_average"] = {currency: f"{s / c:.2f}" for currency, (s, c) in sorted(values.items()) if c}
    return _rates(total)


def _company(lead):
    return {
        "id": lead.pk, "company_name": lead.company_name, "sheet": lead.sheet_id,
        "person": lead.sheet.assigned_to.get_full_name() or lead.sheet.assigned_to.username,
        "governorate": lead.governorate, "next_follow_up": lead.next_follow_up.isoformat() if lead.next_follow_up else "",
    }


def board(user, start, end, filters, today=None):
    """Everything the page draws. ``filters.person`` is a person the reader may read, or ``None``."""
    today = today or timezone.localdate()
    conf = AppSettings.load()
    people = team(user)
    if filters.person is not None:
        people = [person for person in people if person.pk == filters.person.pk]
    rows = [_row(person, start, end, filters, today, conf) for person in people]
    start_at, end_at = _bounds(start, end)
    scope = Lead.objects.filter(filters.q(), sheet__assigned_to__in=people).select_related("sheet", "sheet__assigned_to")
    stages = dict(scope.values("status").annotate(n=Count("id")).values_list("status", "n"))
    new = scope.filter(created_at__gte=start_at, created_at__lt=end_at)
    sources = {}
    for source, status in new.values_list("source", "status"):
        key = (source or "").strip()
        count, won = sources.get(key, (0, 0))
        sources[key] = (count + 1, won + (status == LeadStatus.WON))
    verified_where = dict(
        FieldVisit.objects.filter(
            filters.q("lead__"), person__in=people, status=FieldVisit.Status.VERIFIED,
            check_in_at__gte=start_at, check_in_at__lt=end_at,
        ).values("lead__governorate").annotate(n=Count("id")).values_list("lead__governorate", "n")
    )
    places = dict(scope.values("governorate").annotate(n=Count("id")).values_list("governorate", "n"))
    matrix = {}
    for person_id, status, n in scope.values("sheet__assigned_to", "status").annotate(n=Count("id")).values_list("sheet__assigned_to", "status", "n"):
        matrix.setdefault(person_id, {})[status] = n
    open_rows = scope.exclude(status__in=CLOSED_STATUSES)
    overdue = [lead for lead in _open_follow_ups(open_rows.order_by("next_follow_up", "id"), today) if lead.next_follow_up < today]
    rejected = FieldVisit.objects.filter(
        filters.q("lead__"), person__in=people, status=FieldVisit.Status.REJECTED,
        check_in_at__gte=start_at, check_in_at__lt=end_at,
    ).select_related("lead", "person").order_by("-check_in_at")
    return {
        "rows": rows,
        "total": _total(rows),
        "stages": [{"value": value, "count": stages.get(value, 0)} for value in B2C_STATUSES],
        "sources": [
            {"value": key, "count": count, "won": won}
            for key, (count, won) in sorted(sources.items(), key=lambda item: -item[1][0])
        ],
        "governorates": [
            {"value": key or "", "count": count, "verified": verified_where.get(key, 0)}
            for key, count in sorted(places.items(), key=lambda item: -item[1])
        ],
        "matrix": [
            {"person": row["person"], "stages": {value: matrix.get(row["person"]["id"], {}).get(value, 0) for value in B2C_STATUSES}}
            for row in rows
        ],
        "untouched": [_company(lead) for lead in _untouched(open_rows).order_by("created_at", "id")[:MAX_LIST]],
        "overdue": [_company(lead) for lead in overdue[:MAX_LIST]],
        "rejected": [
            {
                "code": visit.code, "company_name": visit.lead.company_name, "sheet": visit.lead.sheet_id,
                "person": visit.person.get_full_name() or visit.person.username, "note": visit.decision_note,
                "flags": list(visit.flags or []),
            }
            for visit in rejected[:MAX_LIST]
        ],
    }


def choices(user, filters):
    """What the filters offer: the people the reader may read, and the sources and governorates written on their rows."""
    people = team(user)
    scope = Lead.objects.filter(sheet__market=Market.B2C, sheet__assigned_to__in=people)
    words = lambda field: sorted(
        {value.strip() for value in scope.exclude(**{field: ""}).values_list(field, flat=True).distinct()[:MAX_CHOICES * 4] if value.strip()},
        key=str.casefold,
    )[:MAX_CHOICES]
    return {
        "people": [{"id": person.pk, "name": person.get_full_name() or person.username} for person in people] if b2c.manages(user) else [],
        "sources": words("source"),
        "governorates": words("governorate"),
    }


#: The columns of the export, in order: ``(key, Arabic, English)``; a rate is written as its percentage and what it is made of.
EXPORT = (
    ("person", "الـSales", "Sales person"),
    ("new_leads", "شركات جديدة", "New leads"),
    ("contacted", "اتواصلنا معاهم", "Contacted"),
    ("calls", "مكالمات", "Calls"),
    ("messages", "رسايل", "Messages"),
    ("due", "تارجت الزيارات", "Visits owed"),
    ("verified", "زيارات معتمدة", "Verified visits"),
    ("rejected", "زيارات مرفوضة", "Turned-down visits"),
    ("pending", "زيارات مستنية", "Visits waiting"),
    ("visit_achievement", "تحقيق تارجت الزيارات", "Visit achievement"),
    ("verification_rate", "نسبة اعتماد الزيارات", "Visit verification rate"),
    ("qualified", "فرص مؤهلة", "Qualified"),
    ("lead_conversion", "تحويل الزيارات لفرص", "Lead conversion"),
    ("quotations", "عروض أسعار اتبعتت", "Quotations sent"),
    ("quotation_conversion", "تحويل الفرص لعروض", "Quotation conversion"),
    ("won", "تم التعاقد", "Won"),
    ("lost", "خسرناه", "Lost"),
    ("win_rate", "نسبة الكسب", "Win rate"),
    ("follow_up_compliance", "الالتزام بالمتابعات", "Follow-up compliance"),
    ("overdue_now", "متابعات متأخرة دلوقتي", "Overdue follow-ups now"),
    ("untouched", "لسه محدش كلمهم", "Untouched"),
    ("open_value", "قيمة الفرص المفتوحة", "Open deal value"),
)


def _cell(value):
    """A cell as text, made safe for a spreadsheet: a value starting with = + - @ is not read as a formula."""
    if isinstance(value, dict) and "value" in value:
        value = "" if value["value"] is None else f"{value['value']}% ({value['part']}/{value['whole']})"
    elif isinstance(value, dict):
        value = value.get("name", "")
    text = str(value)
    return "'" + text if text[:1] in ("=", "+", "-", "@", "\t", "\r") else text


def export_rows(answer, lang):
    head = [ar if lang == "ar" else en for _key, ar, en in EXPORT]
    lines = [head]
    for row in answer["rows"]:
        lines.append([_cell(row[key]) for key, *_words in EXPORT])
    total = answer["total"]
    lines.append([("الفريق كله" if lang == "ar" else "Whole team")] + [_cell(total[key]) for key, *_words in EXPORT[1:]])
    return lines
