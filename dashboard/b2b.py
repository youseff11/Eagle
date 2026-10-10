"""B2B: the company sheets, and contacting a company from its row (10/10/2026).

The Sales manager (a Sales person the owner marked, ``User.is_sales_manager``) makes a sheet and gives it to one Sales
person. That person fills it with the companies they research and contacts each one from its row:

* WhatsApp: the company has never written to us, so Meta carries nothing to it but an approved template. The button sends
  the opening template (``INTRO_TEMPLATE``) from the Sales person's own number and opens the conversation in the chats; once
  the company answers it is an ordinary chat. A company whose 24-hour window on that number is still open gets no template:
  the conversation just opens.
* E-mail: a letter written on the row leaves from the Sales person's own address, dressed like their other letters.
* A phone call is written by hand (outcome, notes, the next follow-up).

Whatever reaches the company on the Sales person's line marks the row by itself - the button's message and any message they
send it later from the chats or the mail page (``note_outbound``, called by ``services.send_client_message``). Nobody types
"contacted".

Who:

* the sheet's Sales person reads and writes it, and is the only one who contacts from it (it is their line);
* the Sales manager and the owner read and write every sheet, and are the ones who make, hand over and delete sheets;
* nobody else has a door here. A company on a sheet is a client's identity: the operation never sees it.
"""

from datetime import timedelta

from django.core.exceptions import ValidationError
from django.core.validators import validate_email
from django.db import transaction
from django.db.models import Q
from django.utils import timezone

from .models import Channel, Client, Lead, LeadActivity, LeadSheet, OutboundMessage, Role, User

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
    """Who a sheet may be given to: the Sales people still working."""
    return User.objects.filter(role=Role.SALES, is_active=True).order_by("first_name", "username")


# ---------------------------------------------------------------------------
# Marking a row: whatever reached the company on the Sales person's line
# ---------------------------------------------------------------------------

KIND_OF_CHANNEL = {Channel.WHATSAPP: LeadActivity.Kind.WHATSAPP, Channel.EMAIL: LeadActivity.Kind.EMAIL}
FIRST_FIELD = {
    LeadActivity.Kind.WHATSAPP: "whatsapp_at",
    LeadActivity.Kind.EMAIL: "email_at",
    LeadActivity.Kind.CALL: "call_at",
}


def _record(lead, kind, by, *, outbound=None, automatic=False, at=None, **details):
    """Write what happened on the row's timeline and stamp the row. A message is one line a day per channel: a chat of
    forty messages is one conversation on the timeline, not forty lines; the row's last contact moves with every one."""
    at = at or timezone.now()
    fields = []
    first = FIRST_FIELD[kind]
    if getattr(lead, first) is None:
        setattr(lead, first, at)
        fields.append(first)
    if lead.last_contact_at is None or at > lead.last_contact_at:
        lead.last_contact_at = at
        fields.append("last_contact_at")
    if outbound is not None and lead.client_id is None:
        lead.client_id = outbound.client_id
        fields.append("client")
    if fields:
        lead.save(update_fields=fields + ["updated_at"])
    if automatic:
        day = timezone.localtime(at).date()
        if lead.activities.filter(kind=kind, automatic=True, at__date=day).exists():
            return None
    return LeadActivity.objects.create(
        lead=lead, kind=kind, automatic=automatic, at=at, by=by, outbound=outbound, **details
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
    ok, _outbound, error = services.send_client_message(client, user, body, force_channel=Channel.EMAIL, subject=subject)
    if not ok:
        raise Refused("send_failed", error or "الإيميل ماتبعتش.", "The e-mail was not sent.")
    services.log(user, "b2b.email", client.code, f"lead {lead.pk}")
    return client


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
