"""B2B: the company sheets, and contacting a company from its row (10/10/2026).

The Sales manager (a Sales person the owner marked, ``User.is_sales_manager``) makes a sheet and gives it to one Sales
person. That person fills it with the companies they research and contacts each one from its row:

* WhatsApp: the company has never written to us, so Meta carries nothing to it but an approved template. The button sends
  the opening template (``INTRO_TEMPLATE``) from the Sales person's own number and opens the conversation in the chats; once
  the company answers it is an ordinary chat. A company whose 24-hour window on that number is still open gets no template:
  the conversation just opens.
* E-mail: a letter written on the row leaves from the Sales person's own address, dressed like their other letters.
* A phone call is written by hand (outcome, notes, the next follow-up).

Part 2 (10/10/2026): the company's answer on the Sales person's line marks the row too (``note_inbound``, called by
``services.ingest_message``); a row's next follow-up is due, late or done (``follow_up_state``); the Sales person gets one
reminder a day for theirs (``daily_digest``, from ``manage.py sweep`` and the heartbeat) and the manager sees the team's late
ones; the manager moves a company to another Sales person's sheet (``move_lead``).

Whatever reaches the company on the Sales person's line marks the row by itself - the button's message and any message they
send it later from the chats or the mail page (``note_outbound``, called by ``services.send_client_message``). Nobody types
"contacted".

Who:

* the sheet's Sales person reads and writes it, and is the only one who contacts from it (it is their line);
* the Sales manager and the owner read and write every sheet, and are the ones who make, hand over and delete sheets;
* nobody else has a door here. A company on a sheet is a client's identity: the operation never sees it.
"""

from datetime import timedelta
from decimal import ROUND_HALF_UP, Decimal

from django.core.exceptions import ValidationError
from django.core.validators import validate_email
from django.db import transaction
from django.db.models import Q
from django.utils import timezone

from .models import Channel, Client, Lead, LeadActivity, LeadSheet, LeadStatus, OutboundMessage, Quotation, Role, User

# ---------------------------------------------------------------------------
# The opening template
# ---------------------------------------------------------------------------

#: The template the WhatsApp button sends. Submitted to Meta by ``manage.py wa_templates <WABA_ID> --submit b2b_intro_en``
#: (the command reads it from here). A rejected template is renamed here, never deleted at Meta: see the
#: whatsapp-templates skill. It is MARKETING because it greets a company that has done nothing yet; Meta allows no other
#: category for a first contact.
INTRO_TEMPLATE = "b2b_intro_en"
INTRO_LANGUAGE = "en"
INTRO_SPEC = {
    "category": "MARKETING",
    "language": INTRO_LANGUAGE,
    "body": "Hello {{1}}, this is {{2}} from EagleLingua, a translation company based in Egypt. "
            "We work with translation agencies worldwide on {{3}} projects and would be glad to support your team. "
            "Would you be open to a short chat this week?",
    "footer": "EagleLingua",
    "example": ["Anna", "Yousef", "English to Arabic"],
    "purpose": "The first message to a company on a B2B sheet, sent from the Sales person's own number.",
}
#: What fills ``{{1}}`` and ``{{3}}`` when the row has nothing there.
NO_CONTACT_NAME = "there"
NO_LANGUAGES = "Arabic"


def intro_params(lead, user):
    first = (lead.contact_person or "").strip().split(" ")[0] or NO_CONTACT_NAME
    sender = (user.get_full_name() or user.username).strip()
    return [first, sender, (lead.languages or "").strip() or NO_LANGUAGES]


def intro_text(params):
    """The template's words as the company reads them, for the conversation on our side."""
    text = INTRO_SPEC["body"]
    for index, value in enumerate(params, start=1):
        text = text.replace("{{%d}}" % index, value)
    return text


# ---------------------------------------------------------------------------
# The columns of a row
# ---------------------------------------------------------------------------

#: ``(field, longest, Arabic, English)`` in the order the sheet shows them, which is also the order of the columns a pasted
#: block of cells is read in. The B2B requirements' section 4; the Sales person is the sheet's, Last contact is the system's.
COLUMNS = (
    ("company_name", 160, "اسم الشركة", "Company name"),
    ("country", 80, "الدولة", "Country"),
    ("website", 250, "الموقع", "Website"),
    ("industry", 120, "نوع الشركة", "Industry / type"),
    ("contact_person", 160, "الشخص المسؤول", "Contact person"),
    ("position", 120, "المنصب", "Position"),
    ("email", 254, "الإيميل", "Email"),
    ("phone", 40, "التليفون", "Phone"),
    ("whatsapp", 40, "واتساب", "WhatsApp"),
    ("linkedin", 250, "لينكدإن", "LinkedIn"),
    ("languages", 250, "اللغات", "Language pairs"),
    ("services", 250, "الخدمات المطلوبة", "Services required"),
    ("source", 120, "المصدر", "Source"),
)
COLUMN_LIMITS = {name: limit for name, limit, _ar, _en in COLUMNS}
#: The longest notes a row (or a call) keeps.
MAX_NOTES = 4000
#: The most rows one paste may add, and the most a sheet may hold.
MAX_PASTE_ROWS = 500
MAX_SHEET_ROWS = 2000


class Refused(Exception):
    """Nothing was done, and why: a short code for the page and the reason in both languages."""

    def __init__(self, code, ar, en):
        super().__init__(code)
        self.code, self.ar, self.en = code, ar, en


# ---------------------------------------------------------------------------
# Who
# ---------------------------------------------------------------------------

def has_door(user):
    """Whether the B2B pages are this person's at all: the Sales people and the owner."""
    return bool(getattr(user, "is_authenticated", False) and (user.is_admin_role or user.is_sales))


def sheets_for(user):
    """The sheets this person reads: all of them for the manager and the owner, their own for a Sales person."""
    rows = LeadSheet.objects.select_related("assigned_to", "created_by")
    if user.manages_sales:
        return rows
    if user.is_sales:
        return rows.filter(assigned_to=user)
    return rows.none()


def may_read(user, sheet):
    return user.manages_sales or (user.is_sales and sheet.assigned_to_id == user.pk)


def may_contact(user, sheet):
    """Only the sheet's own Sales person writes to its companies: the messages leave from their number and address."""
    return user.is_sales and sheet.assigned_to_id == user.pk


def sales_people():
    """Who a sheet may be given to: the Sales people still working - never a Sales manager (the owner's rule, 10/10/2026):
    the manager hands the sheets out and watches them, and does not hold one. The list the page draws and the check of what
    is posted are both this, so a manager typed into the request by hand is refused like anybody else not on it."""
    return User.objects.filter(role=Role.SALES, is_active=True, is_sales_manager=False).order_by("first_name", "username")


# ---------------------------------------------------------------------------
# Marking a row: whatever reached the company on the Sales person's line
# ---------------------------------------------------------------------------

KIND_OF_CHANNEL = {Channel.WHATSAPP: LeadActivity.Kind.WHATSAPP, Channel.EMAIL: LeadActivity.Kind.EMAIL}
FIRST_FIELD = {
    LeadActivity.Kind.WHATSAPP: "whatsapp_at",
    LeadActivity.Kind.EMAIL: "email_at",
    LeadActivity.Kind.CALL: "call_at",
}


def _later(lead, field, at):
    """Move ``field`` on to ``at`` when it is later; ``[field]`` when it moved."""
    if getattr(lead, field) is None or at > getattr(lead, field):
        setattr(lead, field, at)
        return [field]
    return []


def _record(lead, kind, by, *, outbound=None, client_id=None, automatic=False, incoming=False, at=None, **details):
    """Write what happened on the row's timeline and stamp the row. A message is one line a day per channel and direction:
    a chat of forty messages is one conversation on the timeline, not forty lines; the row's times move with every one.

    Ours (a message sent, a call) stamps the channel's first time and the last outreach; the company's answer stamps the
    first reply. Both move the last contact."""
    at = at or timezone.now()
    fields = []
    # A follow-up that was due and not done yet is done by this, our own message or call on its day or after it.
    follow_up_for = None
    if not incoming and lead.next_follow_up is not None and lead.status not in CLOSED_STATUSES:
        done_before = lead.last_outreach_at is not None and timezone.localtime(lead.last_outreach_at).date() >= lead.next_follow_up
        if not done_before and timezone.localtime(at).date() >= lead.next_follow_up:
            follow_up_for = lead.next_follow_up
    if incoming:
        if lead.replied_at is None:
            lead.replied_at = at
            fields.append("replied_at")
    else:
        first = FIRST_FIELD[kind]
        if getattr(lead, first) is None:
            setattr(lead, first, at)
            fields.append(first)
        fields += _later(lead, "last_outreach_at", at)
    fields += _later(lead, "last_contact_at", at)
    client_id = client_id or (outbound.client_id if outbound is not None else None)
    if client_id and lead.client_id is None:
        lead.client_id = client_id
        fields.append("client")
    # The pipeline's first step moves by itself: the first letter to a new company is «Email sent».
    if kind == LeadActivity.Kind.EMAIL and not incoming and lead.status == LeadStatus.NEW:
        lead.status = LeadStatus.EMAIL_SENT
        fields.append("status")
    if fields:
        lead.save(update_fields=fields + ["updated_at"])
    if "status" in fields:
        note_status(lead, LeadStatus.NEW, LeadStatus.EMAIL_SENT, by, automatic=True, at=at)
    owner_id = lead.sheet.assigned_to_id
    if automatic and follow_up_for is None:
        day = timezone.localtime(at).date()
        if lead.activities.filter(kind=kind, automatic=True, incoming=incoming, at__date=day).exists():
            return None
    return LeadActivity.objects.create(
        lead=lead, kind=kind, automatic=automatic, incoming=incoming, at=at, by=by, outbound=outbound,
        owner_id=owner_id, follow_up_for=follow_up_for, **details
    )


def note_status(lead, before, after, by, *, automatic=False, at=None):
    """The company moved on the pipeline: a line on its timeline (the stage it moved to, counted for whoever holds the
    company) and a row in the audit log. Nothing when the stage did not change."""
    from . import services

    if before == after:
        return None
    services.log(by, "b2b.lead_status", f"lead {lead.pk}", f"{before} -> {after}" + (" (automatic)" if automatic else ""))
    return LeadActivity.objects.create(
        lead=lead, kind=LeadActivity.Kind.STATUS, status=after, automatic=automatic, at=at or timezone.now(), by=by,
        owner_id=lead.sheet.assigned_to_id, notes=f"{before} -> {after}",
    )


def note_outbound(outbound):
    """A message reached a client: mark every row of the sender's own sheets that is that company.

    Only the Sales person's own line counts (``owner``), and only on their own sheets: a message from the company line, or
    from another Sales person, is not this person contacting the company. A row is the company when it was contacted from
    the row before (its ``client``), or - a row nobody has pressed yet - when the number or the address it was sent to is
    the row's.
    """
    if outbound.status != OutboundMessage.Status.SENT or outbound.owner_id is None:
        return
    kind = KIND_OF_CHANNEL.get(outbound.channel)
    if kind is None:
        return
    same = Q(client_id=outbound.client_id)
    target = (outbound.to_identity or "").strip()
    if kind == LeadActivity.Kind.WHATSAPP:
        key = Client.phone_key(target)
        if key:
            same |= Q(client__isnull=True, phone_key=key)
    elif target:
        same |= Q(client__isnull=True, email_key=target.lower())
    for lead in Lead.objects.filter(same, sheet__assigned_to_id=outbound.owner_id):
        _record(lead, kind, outbound.created_by, outbound=outbound, automatic=True)


def note_inbound(message):
    """The company answered: a message came in on the Sales person's own line (``owner``) from a company on their sheets.

    The same rule as ``note_outbound``, the other way: only the owner's line and the owner's sheets, and a row is the company
    when it is linked to the client already or - a row nobody pressed yet - when the number or the address is the row's. A
    message to the company line (``owner`` empty) is nobody's sheet. The words are never copied onto the row.
    """
    if message.owner_id is None or message.client_id is None:
        return
    kind = KIND_OF_CHANNEL.get(message.channel)
    if kind is None:
        return
    same = Q(client_id=message.client_id)
    sender = (message.sender_identity or "").strip()
    if kind == LeadActivity.Kind.WHATSAPP:
        key = Client.phone_key(sender)
        if key:
            same |= Q(client__isnull=True, phone_key=key)
    elif sender:
        same |= Q(client__isnull=True, email_key=sender.lower())
    for lead in Lead.objects.filter(same, sheet__assigned_to_id=message.owner_id):
        _record(lead, kind, None, client_id=message.client_id, automatic=True, incoming=True, at=message.received_at)


# ---------------------------------------------------------------------------
# Follow-ups (part 2)
# ---------------------------------------------------------------------------

#: Where a row's next follow-up stands. A follow-up is done once the Sales person reached out on or after its day (a message
#: or a call: the company writing to us is not us following up). Won and lost companies are followed up no more.
FOLLOW_UP_DONE, FOLLOW_UP_UPCOMING, FOLLOW_UP_TODAY, FOLLOW_UP_OVERDUE = "done", "upcoming", "today", "overdue"
CLOSED_STATUSES = (LeadStatus.WON, LeadStatus.LOST)


def follow_up_state(lead, today=None):
    """``""`` (no follow-up), or one of the four above."""
    if lead.next_follow_up is None or lead.status in CLOSED_STATUSES:
        return ""
    today = today or timezone.localdate()
    if lead.last_outreach_at is not None and timezone.localtime(lead.last_outreach_at).date() >= lead.next_follow_up:
        return FOLLOW_UP_DONE
    if lead.next_follow_up > today:
        return FOLLOW_UP_UPCOMING
    return FOLLOW_UP_TODAY if lead.next_follow_up == today else FOLLOW_UP_OVERDUE


def _open_follow_ups(rows, today):
    """The rows whose follow-up is due today or late: narrowed in the query, then ``follow_up_state`` (the "done" test
    needs the Cairo date of the last outreach, which is clearer here than in SQL)."""
    rows = rows.filter(next_follow_up__isnull=False, next_follow_up__lte=today).exclude(status__in=CLOSED_STATUSES)
    return [lead for lead in rows if follow_up_state(lead, today) in (FOLLOW_UP_TODAY, FOLLOW_UP_OVERDUE)]


#: The most follow-ups one list answers with.
MAX_FOLLOW_UPS = 300


def follow_ups_for(user, today=None):
    """The follow-ups due today or late on the sheets this person reads: their own, or the team's for the manager."""
    today = today or timezone.localdate()
    rows = Lead.objects.filter(sheet__in=sheets_for(user)).select_related("sheet", "sheet__assigned_to")
    return _open_follow_ups(rows.order_by("next_follow_up", "id"), today)[:MAX_FOLLOW_UPS]


#: The hour (Cairo) from which the day's reminder goes: not at midnight, when the sweep may happen to run first.
DIGEST_HOUR = 9
DIGEST_PATH = "/app/leads"


def digest_marker(day):
    """The reminder's link, which is also how the day's one is found again: one a day per person."""
    return f"{DIGEST_PATH}#follow-ups-{day.isoformat()}"


def daily_digest(user, now=None):
    """One reminder a day to a Sales person: how many of their follow-ups are due today and how many are late. Nothing
    when there is none, before ``DIGEST_HOUR``, or when today's went already. Returns the notification or ``None``."""
    from . import services
    from .models import Notification

    if not (user.is_active and user.is_sales):
        return None
    now = timezone.localtime(now or timezone.now())
    if now.hour < DIGEST_HOUR:
        return None
    today = now.date()
    marker = digest_marker(today)
    if Notification.objects.filter(user=user, url=marker).exists():
        return None
    due = _open_follow_ups(Lead.objects.filter(sheet__assigned_to=user), today)
    if not due:
        return None
    late = sum(1 for lead in due if lead.next_follow_up < today)
    on_time = len(due) - late
    parts_ar = [f"{on_time} النهارده"] if on_time else []
    parts_en = [f"{on_time} today"] if on_time else []
    if late:
        parts_ar.append(f"{late} متأخرة")
        parts_en.append(f"{late} overdue")
    return services.notify(
        user,
        title_ar="متابعات الشركات",
        title_en="Company follow-ups",
        body_ar=f"عندك متابعات: {' و'.join(parts_ar)}. افتح «شيتات الشركات».",
        body_en=f"You have follow-ups: {' and '.join(parts_en)}. Open «Company sheets».",
        level="warning" if late else "info",
        url=marker,
    )


def sweep(now=None):
    """The day's reminder to every Sales person who has follow-ups (``manage.py sweep``). Returns how many went."""
    sent = 0
    for person in User.objects.filter(role=Role.SALES, is_active=True, lead_sheets__isnull=False).distinct():
        if daily_digest(person, now=now) is not None:
            sent += 1
    return sent


# ---------------------------------------------------------------------------
# The Sales numbers (part 3): the B2B requirements' sections 11 and 12
# ---------------------------------------------------------------------------

#: The longest period the numbers are counted over.
MAX_KPI_DAYS = 366
#: The counts a person's row carries (zero is a real zero: nothing was done), and the two rates (``None`` when there is
#: nothing to divide by: "not measured", never 0%).
KPI_COUNTS = (
    "new_leads", "contacted", "whatsapp", "emails", "calls", "replies", "meetings", "proposals", "won", "lost",
    "follow_ups_on_time", "follow_ups_late", "follow_ups_missed", "overdue_now", "holding", "untouched",
    "quotations", "quotes_accepted",
)


def _revenue(rows):
    """The accepted quotations' totals, one figure per currency: dollars and pounds are never added together."""
    out = {}
    for currency, total in rows:
        out[currency] = out.get(currency, Decimal(0)) + total
    return {currency: f"{amount:.2f}" for currency, amount in sorted(out.items())}


def _rate(part, whole):
    return None if not whole else round(100 * part / whole)


def _rates(row):
    row["conversion_rate"] = _rate(row["won"], row["won"] + row["lost"])
    due = row["follow_ups_on_time"] + row["follow_ups_late"] + row["follow_ups_missed"]
    row["follow_up_rate"] = _rate(row["follow_ups_on_time"], due)
    return row


def kpi_people(user, start_at, end_at):
    """Whose numbers this person reads: their own, or - for the manager and the owner - every Sales person who holds
    companies now or worked one in the period (somebody who left mid-month still has their month)."""
    if not user.manages_sales:
        return [user] if user.is_sales else []
    worked = LeadActivity.objects.filter(at__gte=start_at, at__lt=end_at).values("owner_id")
    rows = User.objects.filter(role=Role.SALES).filter(
        Q(is_active=True, is_sales_manager=False) | Q(pk__in=worked) | Q(lead_sheets__isnull=False)
    ).distinct()
    return list(rows.order_by("first_name", "username"))


def kpis(user, start, end, today=None):
    """``(rows, total)`` for the days ``start``..``end`` (Cairo, both included).

    * new_leads - companies added to the person's sheets in the period;
    * contacted - companies they reached out to (a message or a call); whatsapp / emails - the messages themselves that left
      their line to a company on their sheets; calls - the calls they logged;
    * replies - companies that answered them for the first time in the period;
    * meetings / proposals / won / lost - companies moved to that stage in the period (each company once);
    * follow-ups that fell due in the period: done on the day, done later, or still not done;
    * overdue_now, holding, untouched - today, whatever the period: late follow-ups, companies on their sheets, and of those
      the ones nobody contacted yet;
    * quotations - the quotations they sent in the period; quotes_accepted and revenue - the ones accepted in the period,
      and their totals per currency (part 4).

    Counted for the person who held the company when it happened (``LeadActivity.owner``).
    """
    from datetime import datetime, time as dtime

    today = today or timezone.localdate()
    start_at = timezone.make_aware(datetime.combine(start, dtime.min))
    end_at = timezone.make_aware(datetime.combine(end + timedelta(days=1), dtime.min))
    rows = []
    for person in kpi_people(user, start_at, end_at):
        acts = LeadActivity.objects.filter(owner=person, at__gte=start_at, at__lt=end_at)
        ours = acts.filter(incoming=False, kind__in=(LeadActivity.Kind.WHATSAPP, LeadActivity.Kind.EMAIL, LeadActivity.Kind.CALL))
        stage = acts.filter(kind=LeadActivity.Kind.STATUS)
        sent = OutboundMessage.objects.filter(
            owner=person, status=OutboundMessage.Status.SENT, created_at__gte=start_at, created_at__lt=end_at,
            client__leads__sheet__assigned_to=person,
        )
        mine = Lead.objects.filter(sheet__assigned_to=person)
        done = [
            (timezone.localtime(at).date(), due)
            for at, due in acts.filter(follow_up_for__isnull=False).values_list("at", "follow_up_for")
        ]
        missed = [
            lead for lead in _open_follow_ups(mine, today)
            if lead.next_follow_up < today and start <= lead.next_follow_up <= end
        ]
        row = {
            "person": {"id": person.pk, "name": person.get_full_name() or person.username, "active": person.is_active},
            "new_leads": mine.filter(created_at__gte=start_at, created_at__lt=end_at).count(),
            "contacted": ours.values("lead").distinct().count(),
            "whatsapp": sent.filter(channel=Channel.WHATSAPP).distinct().count(),
            "emails": sent.filter(channel=Channel.EMAIL).distinct().count(),
            "calls": ours.filter(kind=LeadActivity.Kind.CALL).count(),
            "replies": Lead.objects.filter(
                activities__owner=person, activities__incoming=True, replied_at__gte=start_at, replied_at__lt=end_at,
            ).distinct().count(),
            "meetings": stage.filter(status=LeadStatus.MEETING).values("lead").distinct().count(),
            "proposals": stage.filter(status=LeadStatus.PROPOSAL).values("lead").distinct().count(),
            "won": stage.filter(status=LeadStatus.WON).values("lead").distinct().count(),
            "lost": stage.filter(status=LeadStatus.LOST).values("lead").distinct().count(),
            "follow_ups_on_time": sum(1 for day, due in done if day == due),
            "follow_ups_late": sum(1 for day, due in done if day > due),
            "follow_ups_missed": len(missed),
            "overdue_now": sum(1 for lead in _open_follow_ups(mine, today) if lead.next_follow_up < today),
            "holding": mine.count(),
            "untouched": mine.filter(whatsapp_at__isnull=True, email_at__isnull=True, call_at__isnull=True).count(),
        }
        quotes = Quotation.objects.filter(owner=person)
        accepted = quotes.filter(status=Quotation.Status.ACCEPTED, decided_at__gte=start_at, decided_at__lt=end_at)
        row["quotations"] = quotes.filter(sent_at__gte=start_at, sent_at__lt=end_at).count()
        row["quotes_accepted"] = accepted.count()
        row["revenue"] = _revenue(accepted.values_list("currency", "total"))
        rows.append(_rates(row))
    total = _rates({name: sum(row[name] for row in rows) for name in KPI_COUNTS})
    total["revenue"] = _revenue(
        (currency, Decimal(amount)) for row in rows for currency, amount in row["revenue"].items()
    )
    return rows, total


# ---------------------------------------------------------------------------
# Handing a company to another Sales person (part 2)
# ---------------------------------------------------------------------------

def move_lead(lead, sheet, actor):
    """The manager moves a row to another sheet - and so to that sheet's Sales person. The conversation with the company
    stays on the line it was had on: the new Sales person starts their own from the row. ``Refused`` when it may not."""
    from . import services

    if not actor.manages_sales:
        raise Refused("not_manager", "نقل الشركات للمانجر بس.", "Only the Sales manager moves companies.")
    if sheet.pk == lead.sheet_id:
        raise Refused("same_sheet", "الشركة في الشيت ده أصلًا.", "The company is on that sheet already.")
    if not sales_people().filter(pk=sheet.assigned_to_id).exists():
        raise Refused("no_sales", "الشيت ده مع حد مايستلمش شركات (مانجر أو حساب مقفول).", "That sheet is with someone who takes no companies (a manager, or a closed account).")
    if sheet.leads.count() >= MAX_SHEET_ROWS:
        raise Refused("sheet_full", f"الشيت مايشيلش أكتر من {MAX_SHEET_ROWS} شركة.", f"A sheet holds at most {MAX_SHEET_ROWS} companies.")
    before = lead.sheet
    lead.sheet = sheet
    lead.save(update_fields=["sheet", "updated_at"])
    services.log(actor, "b2b.lead_move", f"lead {lead.pk}", f"sheet {before.pk} -> {sheet.pk} ({sheet.assigned_to.username})")
    if sheet.assigned_to_id not in (actor.pk, before.assigned_to_id):
        services.notify(
            sheet.assigned_to,
            title_ar="شركة اتنقلتلك",
            title_en="A company was moved to you",
            body_ar=f"«{lead.company_name}» بقت في شيت «{sheet.title}».",
            body_en=f"“{lead.company_name}” is now on the sheet “{sheet.title}”.",
            level="info", url=f"/app/leads/{sheet.pk}",
        )
    return lead


# ---------------------------------------------------------------------------
# Contacting from the row
# ---------------------------------------------------------------------------

def _client_for(lead, channel, value):
    """The client this company is: the row's own once it has one and it still owns the number / address, otherwise one we
    already know by it (a company that wrote to us first), otherwise a new client made from the row."""
    owns = (lambda c: c.owns_phone(value)) if channel == Channel.WHATSAPP else (lambda c: c.owns_email(value))
    if lead.client_id and owns(lead.client):
        return lead.client
    found = Client.find_by_phone(value) if channel == Channel.WHATSAPP else Client.find_by_email(value)
    if found is not None:
        return found
    phone = value if channel == Channel.WHATSAPP else (lead.whatsapp or lead.phone)
    email = value if channel == Channel.EMAIL else lead.email
    try:
        validate_email(email or "")
    except ValidationError:
        email = ""
    return Client.objects.create(
        name=lead.contact_person[:160], company=lead.company_name[:160], phone=(phone or "")[:40],
        email=email or "", country=lead.country[:80],
    )


#: Two presses on the WhatsApp button send one template: another one goes only after this long without an answer.
INTRO_REPEAT = timedelta(hours=24)


def start_whatsapp(lead, user):
    """The WhatsApp button: ``(client, sent)``, or ``Refused``.

    ``sent`` is False when nothing had to go: the company's window on this person's number is open (they wrote within 24
    hours) and the conversation just opens, or the template already went within ``INTRO_REPEAT`` and they have not answered.
    """
    from . import services, whatsapp as wa
    from .identity import scrub_contacts

    if not may_contact(user, lead.sheet):
        raise Refused("not_yours", "الشيت ده مش بتاعك: صاحبه بس هو اللي بيتواصل منه.", "Only the sheet's own Sales person contacts from it.")
    number = wa.normalize_number(lead.whatsapp or lead.phone)
    if len(number) < 8:
        raise Refused("no_number", "مفيش رقم واتساب مظبوط للشركة دي. اكتبه بكود الدولة (+44...).", "This company has no usable WhatsApp number. Write it with the country code (+44...).")
    from_id = (user.wa_phone_number_id or "").strip()
    if not from_id:
        raise Refused("no_line", "مفيش رقم واتساب متسجّل ليك. ضيفه من «رقمي وإيميلي» الأول.", "You have no WhatsApp number yet. Add it on «My number & mail» first.")

    with transaction.atomic():
        # The row alone, no join: Postgres refuses FOR UPDATE on the nullable side of an outer join.
        Lead.objects.select_for_update().filter(pk=lead.pk).first()
        lead.refresh_from_db()
        client = _client_for(lead, Channel.WHATSAPP, number)
        if lead.client_id != client.pk:
            lead.client = client
            lead.save(update_fields=["client", "updated_at"])
        window_open, _left = Client.window_from(client.last_inbound_on(user))
        if window_open:
            return client, False
        since = timezone.now() - INTRO_REPEAT
        recent = client.deliveries.filter(
            owner=user, channel=Channel.WHATSAPP, created_at__gte=since,
            status__in=(OutboundMessage.Status.SENDING, OutboundMessage.Status.SENT),
        )
        if recent.exists():
            return client, False
        params = intro_params(lead, user)
        outbound = OutboundMessage.objects.create(
            client=client, kind=OutboundMessage.Kind.CHAT, created_by=user, owner=user,
            channel=Channel.WHATSAPP, to_identity=number, body=intro_text(params),
            status=OutboundMessage.Status.SENDING,
        )

    try:
        outbound.provider_id = wa.send_template(number, INTRO_TEMPLATE, INTRO_LANGUAGE, params, from_id=from_id)[:190]
    except wa.WhatsAppError as exc:
        outbound.status = OutboundMessage.Status.FAILED
        outbound.error_message = scrub_contacts(exc.message_ar)
        outbound.save(update_fields=["status", "error_message"])
        services.log(user, "b2b.whatsapp_failed", client.code, (exc.message_en or "")[:200])
        raise Refused("send_failed", outbound.error_message or "واتساب رفض الرسالة.", exc.message_en or "WhatsApp refused the message.") from None
    except Exception:  # noqa: BLE001 - a dropped connection while Meta answered: nobody knows whether it arrived
        outbound.status = OutboundMessage.Status.FAILED
        outbound.error_message = services.SEND_UNSURE_AR
        outbound.save(update_fields=["status", "error_message"])
        services.log(user, "b2b.whatsapp_failed", client.code, "unexpected error")
        raise Refused("send_failed", services.SEND_UNSURE_AR, "Not sure the message went. Check the chat before sending again.") from None
    outbound.status = OutboundMessage.Status.SENT
    outbound.save(update_fields=["status", "provider_id"])
    services.log(user, "b2b.whatsapp", client.code, f"lead {lead.pk} template {INTRO_TEMPLATE}")
    note_outbound(outbound)
    return client, True


#: The longest subject and letter the e-mail button sends.
MAX_SUBJECT = 250
MAX_LETTER = 20000


def send_email(lead, user, subject, body):
    """The e-mail button: a letter from this person's own address. ``client``, or ``Refused``."""
    from . import services

    if not may_contact(user, lead.sheet):
        raise Refused("not_yours", "الشيت ده مش بتاعك: صاحبه بس هو اللي بيتواصل منه.", "Only the sheet's own Sales person contacts from it.")
    address = (lead.email or "").strip()
    try:
        validate_email(address)
    except ValidationError:
        raise Refused("no_email", "الإيميل اللي في الصف مش مظبوط.", "The row's e-mail address is not valid.") from None
    if not (user.mail_alias or "").strip():
        raise Refused("no_line", "مفيش إيميل متحدد ليك. الأدمن يحدده من صفحة الموظف.", "You have no mail address yet. The admin sets it on your employee page.")
    if not subject or not body:
        raise Refused("empty", "اكتب العنوان والرسالة.", "Write a subject and a message.")
    with transaction.atomic():
        Lead.objects.select_for_update().filter(pk=lead.pk).first()
        lead.refresh_from_db()
        client = _client_for(lead, Channel.EMAIL, address)
        if lead.client_id != client.pk:
            lead.client = client
            lead.save(update_fields=["client", "updated_at"])
    # The row is marked by ``note_outbound``, which the send calls when the letter has left.
    ok, outbound, error = services.send_client_message(client, user, body, force_channel=Channel.EMAIL, subject=subject)
    if not ok:
        raise Refused("send_failed", error or "الإيميل ماتبعتش.", "The e-mail was not sent.")
    services.log(user, "b2b.email", client.code, f"lead {lead.pk}")
    return client, outbound


def log_call(lead, user, *, outcome, notes="", duration=None, at=None, next_follow_up=None):
    """A phone call, written by hand: it marks the row like a message does, and may set the next follow-up."""
    from . import services

    if not may_contact(user, lead.sheet):
        raise Refused("not_yours", "الشيت ده مش بتاعك: صاحبه بس هو اللي بيسجّل مكالماته.", "Only the sheet's own Sales person logs its calls.")
    if outcome not in LeadActivity.Outcome.values:
        raise Refused("bad_outcome", "اختار نتيجة المكالمة.", "Choose the outcome of the call.")
    at = at or timezone.now()
    if at > timezone.now() + timedelta(minutes=5):
        raise Refused("future", "وقت المكالمة لسه ماجاش.", "That call time is in the future.")
    with transaction.atomic():
        Lead.objects.select_for_update().filter(pk=lead.pk).first()
        lead.refresh_from_db()
        activity = _record(
            lead, LeadActivity.Kind.CALL, user, at=at, outcome=outcome, notes=notes, duration_minutes=duration,
        )
        if next_follow_up is not None:
            lead.next_follow_up = next_follow_up
            lead.save(update_fields=["next_follow_up", "updated_at"])
    services.log(user, "b2b.call", f"lead {lead.pk}", outcome)
    return activity


# ---------------------------------------------------------------------------
# Quotations (part 4, the requirements' section 13)
# ---------------------------------------------------------------------------

#: The stages a company is still before the proposal at: a quotation sent moves it on to «Proposal / rate sheet sent».
BEFORE_PROPOSAL = (
    LeadStatus.NEW, LeadStatus.EMAIL_SENT, LeadStatus.FOLLOW_UP_1, LeadStatus.FOLLOW_UP_2, LeadStatus.MEETING,
)
#: The largest figures a quotation takes: a quantity, a unit price, and the discount in percent.
MAX_QUANTITY = 10_000_000
MAX_RATE = Decimal("1000000")
CENT = Decimal("0.01")


def quotation_total(quantity, rate, discount_percent):
    """quantity x rate, less the discount, to the cent (half up, as an invoice rounds)."""
    gross = Decimal(quantity) * Decimal(rate)
    return (gross * (Decimal(100) - Decimal(discount_percent)) / Decimal(100)).quantize(CENT, rounding=ROUND_HALF_UP)


def _quote_line(quote, kind_word, by, at=None):
    """A line on the company's timeline: the quotation was made, sent, accepted or turned down."""
    return LeadActivity.objects.create(
        lead=quote.lead, kind=LeadActivity.Kind.QUOTATION, quotation=quote, notes=kind_word,
        automatic=kind_word != "accepted" and kind_word != "rejected", at=at or timezone.now(), by=by,
        owner_id=quote.lead.sheet.assigned_to_id,
    )


def may_decide(user, lead):
    """Who writes down the company's answer to a quotation: the Sales person who sent it, the manager, the owner."""
    return may_contact(user, lead.sheet) or user.manages_sales


def save_quotation(lead, user, values, quote=None):
    """Make a quotation, or change a draft one. ``values`` are already of the right types (the door checks them); the
    languages are written as the task form writes them (EN, AR...). ``Refused`` when it may not."""
    from . import services
    from .forms import _language_code

    if not may_contact(user, lead.sheet):
        raise Refused("not_yours", "عروض الأسعار لصاحب الشيت بس.", "Only the sheet's own Sales person makes its quotations.")
    if quote is not None and quote.status != Quotation.Status.DRAFT:
        raise Refused("not_draft", "العرض ده اتبعت، فمابيتغيّرش. اعمل نسخة جديدة منه.", "This quotation was sent, so it is not changed. Make a new copy of it.")
    source, target = _language_code(values["source_lang"]), _language_code(values["target_lang"])
    if not source or not target:
        raise Refused("no_languages", "اكتب اللغتين.", "Write both languages.")
    if source == target:
        raise Refused("same_language", "اللغتين لازم يبقوا مختلفين.", "The two languages must differ.")
    if not 0 < values["quantity"] <= MAX_QUANTITY:
        raise Refused("bad_quantity", "الكمية لازم تبقى رقم أكبر من صفر.", "The quantity must be more than zero.")
    if not Decimal(0) < values["rate"] <= MAX_RATE:
        raise Refused("bad_rate", "السعر لازم يبقى أكبر من صفر.", "The rate must be more than zero.")
    if not Decimal(0) <= values["discount_percent"] < Decimal(100):
        raise Refused("bad_discount", "الخصم من 0 لأقل من 100%.", "The discount is from 0 to under 100%.")
    if values["deadline"] is not None and values["deadline"] < timezone.localdate():
        raise Refused("past_deadline", "الديدلاين عدّى.", "That deadline has passed.")
    made = quote is None
    quote = quote or Quotation(lead=lead, owner=lead.sheet.assigned_to, created_by=user)
    for name, value in values.items():
        setattr(quote, name, value)
    quote.source_lang, quote.target_lang = source, target
    quote.total = quotation_total(quote.quantity, quote.rate, quote.discount_percent)
    quote.save()
    if made:
        _quote_line(quote, "created", user)
        services.log(user, "b2b.quote_create", quote.code, f"lead {lead.pk} {quote.total} {quote.currency}")
    else:
        services.log(user, "b2b.quote_update", quote.code, f"{quote.total} {quote.currency}")
    return quote


def copy_quotation(quote, user):
    """A new draft with the same figures: how a sent price is changed, so the company's earlier quotation stays as it was."""
    values = {name: getattr(quote, name) for name in QUOTE_FIELDS}
    if values["deadline"] is not None and values["deadline"] < timezone.localdate():
        values["deadline"] = None
    return save_quotation(quote.lead, user, values)


#: The figures of a quotation: what a form writes, and what a copy takes.
QUOTE_FIELDS = (
    "source_lang", "target_lang", "service", "unit", "quantity", "rate", "discount_percent", "currency", "deadline",
    "payment_terms", "notes",
)


def _amount(value):
    return f"{value:,.2f}"


def quotation_letter(quote, user):
    """``(subject, body)`` of the letter a quotation goes in: English, like the company's side of the conversation."""
    name = (quote.lead.contact_person or "").strip().split(" ")[0] or "there"
    sender = (user.get_full_name() or user.username).strip()
    unit = quote.get_unit_display().lower()
    lines = [
        f"Dear {name},",
        "",
        f"Thank you for your interest in EagleLingua. Please find our quotation {quote.code} below.",
        "",
        f"Service: {quote.get_service_display()}",
        f"Language pair: {quote.source_lang} > {quote.target_lang}",
        f"Volume: {quote.quantity:,} {unit}",
        f"Rate: {quote.rate.normalize():f} {quote.currency} per {unit.rstrip('s')}" if quote.unit != Quotation.Unit.PROJECT
        else f"Rate: {_amount(quote.rate)} {quote.currency}",
    ]
    if quote.discount_percent:
        lines.append(f"Discount: {quote.discount_percent.normalize():f}%")
    lines.append(f"Total: {_amount(quote.total)} {quote.currency}")
    if quote.deadline:
        lines.append(f"Delivery by: {quote.deadline:%d %B %Y}")
    if quote.payment_terms:
        lines.append(f"Payment terms: {quote.payment_terms}")
    if quote.notes.strip():
        lines += ["", quote.notes.strip()]
    lines += ["", "To go ahead, simply reply to this e-mail.", "", "Best regards,", sender]
    return f"Quotation {quote.code} - EagleLingua", "\n".join(lines)


def send_quotation(quote, user):
    """Send a draft quotation by e-mail from the person's own address. The company moves on to «Proposal / rate sheet sent»
    when it was not that far yet. ``Refused`` when it may not or the letter did not leave (the quotation stays a draft)."""
    lead = quote.lead
    if not may_contact(user, lead.sheet):
        raise Refused("not_yours", "عروض الأسعار لصاحب الشيت بس.", "Only the sheet's own Sales person sends its quotations.")
    with transaction.atomic():
        locked = Quotation.objects.select_for_update().filter(pk=quote.pk).first()
        if locked is None or locked.status != Quotation.Status.DRAFT:
            raise Refused("not_draft", "العرض ده اتبعت قبل كده.", "This quotation was sent already.")
        # Written before the letter leaves, so a second press finds it on its way and sends nothing.
        locked.status = Quotation.Status.SENT
        locked.sent_at = timezone.now()
        locked.save(update_fields=["status", "sent_at", "updated_at"])
    subject, body = quotation_letter(quote, user)
    try:
        _client, outbound = send_email(lead, user, subject, body)
    except Refused:
        Quotation.objects.filter(pk=quote.pk).update(status=Quotation.Status.DRAFT, sent_at=None)
        raise
    quote.refresh_from_db()
    quote.outbound = outbound
    quote.save(update_fields=["outbound", "updated_at"])
    _quote_line(quote, "sent", user, at=quote.sent_at)
    lead.refresh_from_db()
    if lead.status in BEFORE_PROPOSAL:
        before = lead.status
        lead.status = LeadStatus.PROPOSAL
        lead.save(update_fields=["status", "updated_at"])
        note_status(lead, before, LeadStatus.PROPOSAL, user, automatic=True)
    return quote


def decide_quotation(quote, user, accepted):
    """The company's answer to a sent quotation. Accepted: the company is Won, and the operation is told to make the task
    from it (the link fills the task form; the operation makes the task). Turned down: written down, the company stays
    where it is (another price may follow). ``Refused`` when it may not."""
    from . import services

    lead = quote.lead
    if not may_decide(user, lead):
        raise Refused("not_yours", "مش من حقك تسجّل رد الشركة على العرض ده.", "You may not record this company's answer.")
    with transaction.atomic():
        locked = Quotation.objects.select_for_update().filter(pk=quote.pk).first()
        if locked is None or locked.status != Quotation.Status.SENT:
            raise Refused("not_sent", "ده مش عرض متبعت ومستني رد.", "This is not a sent quotation waiting for an answer.")
        locked.status = Quotation.Status.ACCEPTED if accepted else Quotation.Status.REJECTED
        locked.decided_at = timezone.now()
        locked.decided_by = user
        locked.save(update_fields=["status", "decided_at", "decided_by", "updated_at"])
    quote.refresh_from_db()
    _quote_line(quote, "accepted" if accepted else "rejected", user, at=quote.decided_at)
    services.log(user, "b2b.quote_accepted" if accepted else "b2b.quote_rejected", quote.code, f"lead {lead.pk}")
    if not accepted:
        return quote
    lead.refresh_from_db()
    if lead.status != LeadStatus.WON:
        before = lead.status
        lead.status = LeadStatus.WON
        lead.save(update_fields=["status", "updated_at"])
        note_status(lead, before, LeadStatus.WON, user, automatic=True)
    _tell_the_operation(quote)
    return quote


def _tell_the_operation(quote):
    """The operation (and the owner) hear that a quotation was accepted, with a link that fills the task form from it. The
    words carry the client's code, the pair, the size and the deadline - never the company's name nor the price."""
    from . import services

    client = quote.lead.client
    code = client.code if client is not None else "—"
    size = f"{quote.quantity:,} {quote.get_unit_display().lower()}"
    due_ar = f"، الديدلاين {quote.deadline:%d/%m/%Y}" if quote.deadline else ""
    due_en = f", due {quote.deadline:%d/%m/%Y}" if quote.deadline else ""
    for person in User.objects.filter(role__in=(Role.OPERATION, Role.ADMIN), is_active=True):
        services.notify(
            person,
            title_ar="عرض سعر اتقبل: اعمل التاسك",
            title_en="A quotation was accepted: make the task",
            body_ar=f"{quote.code} للعميل {code}: {quote.source_lang} > {quote.target_lang}، {size}{due_ar}. الفورم متعبّية من العرض.",
            body_en=f"{quote.code} for client {code}: {quote.source_lang} > {quote.target_lang}, {size}{due_en}. The form is filled from it.",
            level="info", url=f"/app/tasks/new?quote={quote.code}", sound=True,
        )


def delete_quotation(quote, user):
    """Take a draft away. A sent quotation is what the company saw: it is kept."""
    from . import services

    if not may_contact(user, quote.lead.sheet):
        raise Refused("not_yours", "عروض الأسعار لصاحب الشيت بس.", "Only the sheet's own Sales person deletes its quotations.")
    if quote.status != Quotation.Status.DRAFT:
        raise Refused("not_draft", "العرض ده اتبعت للشركة، فمابيتمسحش.", "This quotation went to the company, so it is kept.")
    services.log(user, "b2b.quote_delete", quote.code, f"lead {quote.lead_id}")
    quote.delete()


def quotation_for_task(code, user):
    """The accepted quotation a new task is being made from (``?quote=``), or ``None``: one not accepted, one a task was made
    from already, or a person who does not make tasks finds nothing."""
    if not (user.is_operation or user.is_admin_role) or not code:
        return None
    return (
        Quotation.objects.select_related("lead__client")
        .filter(code=code, status=Quotation.Status.ACCEPTED, task__isnull=True, lead__client__isnull=False)
        .first()
    )


def link_task(quote, task):
    """The task the operation made from the quotation. Once: a second task from the same quotation is a task of its own."""
    return Quotation.objects.filter(pk=quote.pk, task__isnull=True).update(task=task) == 1
