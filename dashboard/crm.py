"""The CRM sheets of the real-estate branch (09/11/2026).

The company has a translation branch and a real-estate branch, and the two have nothing to do with each other. The real-estate
sales team is its own role (``Role.CRM``), not a Sales track: nobody on it sees a B2B or B2C sheet, a price list or a
commission, and nobody on the translation side sees a CRM sheet (the owner sees everything).

The CRM manager (a CRM person the owner marked, ``User.crm_manager``) makes a sheet, gives it to one CRM person (themself
included) and reads every sheet. A sheet is four columns and nothing more, as the owner asked: the name, the phone, where the
person stands (``CrmStatus``) and the contact buttons. The person who holds the sheet sets the status; the manager and the
owner also write the rows (add, correct, delete) and hand the sheet on.

Contacting is the row's buttons: a call (the phone's own dialler) and WhatsApp from the number the owner gave this CRM person
on their file (``User.wa_phone_number_id``). A conversation on that number is theirs and the owner's, like a Sales person's
(``lines.line_q``). WhatsApp lets a business start a conversation only with a template Meta approved, and the real-estate
branch has none yet: until it does, the button opens the chat of a person who already wrote to this number and says so for
anybody else, writing nothing.
"""

from django.db import transaction

from .models import Client, CrmContact, CrmSheet, CrmStatus, Role, User

#: The longest title, name and phone.
MAX_TITLE = 160
MAX_NAME = 160
MAX_PHONE = 40
#: The most rows one paste adds.
MAX_PASTE_ROWS = 1000


class Refused(Exception):
    """Nothing was written. ``code`` is what the page is told, in both languages."""

    def __init__(self, code, ar, en=""):
        super().__init__(code)
        self.code = code
        self.ar = ar
        self.en = en or ar


def has_door(user):
    """Has the CRM pages at all: the owner and the CRM team."""
    return bool(getattr(user, "is_authenticated", False)) and (user.is_admin_role or user.is_crm)


def sheets_for(user):
    """The sheets this person reads: every one for the owner and the CRM manager, their own for anybody else on the team."""
    rows = CrmSheet.objects.all()
    if user.runs_crm:
        return rows
    if user.is_crm:
        return rows.filter(assigned_to=user)
    return rows.none()


def may_read(user, sheet):
    return user.runs_crm or (user.is_crm and sheet.assigned_to_id == user.pk)


def may_set_status(user, sheet):
    """The status is the holder's to set, and the manager's and the owner's."""
    return may_read(user, sheet)


def may_contact(user, sheet):
    """Only the person holding the sheet contacts from it: the WhatsApp message leaves from their own number."""
    return user.is_crm and sheet.assigned_to_id == user.pk


def holders():
    """Who a sheet may be given to: the CRM team at work, the manager included."""
    return User.objects.filter(role=Role.CRM, is_active=True).order_by("first_name", "username")


def _holder(person_id):
    person = holders().filter(pk=person_id).first() if person_id else None
    if person is None:
        raise Refused("bad_holder", "اختار حد من فريق الـCRM.", "Pick someone on the CRM team.")
    return person


def _title(value):
    title = str(value or "").strip()
    if not title:
        raise Refused("no_title", "اكتب اسم للشيت.", "Give the sheet a name.")
    if len(title) > MAX_TITLE:
        raise Refused("long_title", "اسم الشيت طويل أوي.", "The sheet's name is too long.")
    return title


def _name(value):
    name = str(value or "").strip()
    if len(name) > MAX_NAME:
        raise Refused("long_name", "الاسم طويل أوي.", "The name is too long.")
    return name


def _phone(value):
    phone = " ".join(str(value or "").split())
    if len(phone) > MAX_PHONE:
        raise Refused("long_phone", "الرقم طويل أوي.", "The phone is too long.")
    return phone


def _status(value):
    status = str(value or "").strip()
    if status not in ("", *CrmStatus.values):
        raise Refused("bad_status", "الحالة دي مش من الاختيارات.", "That status is not one of the choices.")
    return status


def _manager(user):
    if not user.runs_crm:
        raise Refused("not_manager", "ده شغل مدير الـCRM.", "Only the CRM manager does that.")


def create_sheet(user, title, holder_id):
    from . import services

    _manager(user)
    sheet = CrmSheet.objects.create(title=_title(title), assigned_to=_holder(holder_id), created_by=user)
    services.log(user, "crm.sheet_create", f"crm sheet {sheet.pk}", f"to {sheet.assigned_to_id}")
    return sheet


def update_sheet(user, sheet, *, title=None, holder_id=None):
    from . import services

    _manager(user)
    fields = []
    if title is not None:
        sheet.title = _title(title)
        fields.append("title")
    if holder_id is not None:
        sheet.assigned_to = _holder(holder_id)
        fields.append("assigned_to")
    if fields:
        sheet.save(update_fields=fields)
        services.log(user, "crm.sheet_update", f"crm sheet {sheet.pk}", f"to {sheet.assigned_to_id}")
    return sheet


def delete_sheet(user, sheet):
    from . import services

    _manager(user)
    services.log(user, "crm.sheet_delete", f"crm sheet {sheet.pk}", sheet.title[:200])
    sheet.delete()


def add_rows(user, sheet, rows):
    """``rows``: a list of ``{"name", "phone", "status"}``. Rows with neither a name nor a phone are skipped."""
    _manager(user)
    if not isinstance(rows, list) or len(rows) > MAX_PASTE_ROWS:
        raise Refused("too_many", f"أقصى حاجة {MAX_PASTE_ROWS} صف في المرة.", f"At most {MAX_PASTE_ROWS} rows at a time.")
    made = []
    for row in rows:
        if not isinstance(row, dict):
            raise Refused("bad_row", "صف مش مفهوم.", "A row could not be read.")
        name, phone, status = _name(row.get("name")), _phone(row.get("phone")), _status(row.get("status"))
        if name or phone:
            made.append(CrmContact(sheet=sheet, name=name, phone=phone, status=status))
    with transaction.atomic():
        return CrmContact.objects.bulk_create(made)


def update_row(user, row, values):
    """``values`` may carry ``status`` (the holder, the manager, the owner) and ``name`` / ``phone`` (the manager and the owner)."""
    sheet = row.sheet
    fields = []
    if "status" in values:
        if not may_set_status(user, sheet):
            raise Refused("not_yours", "الشيت ده مش بتاعك.", "This sheet is not yours.")
        row.status = _status(values["status"])
        fields.append("status")
    if "name" in values or "phone" in values:
        _manager(user)
        if "name" in values:
            row.name = _name(values["name"])
            fields.append("name")
        if "phone" in values:
            phone = _phone(values["phone"])
            if Client.phone_key(phone) != Client.phone_key(row.phone):
                # Another number is another person: the chat the old one opened is not theirs.
                row.client = None
                fields.append("client")
            row.phone = phone
            fields.append("phone")
    if fields:
        row.save(update_fields=[*fields, "updated_at"])
    return row


def delete_row(user, row):
    _manager(user)
    row.delete()


def may_open_client(user, client):
    """May a CRM person open this client's chat at all: one they talked to on their own number, or one a row of a sheet they
    read opened. A translation client's code typed by hand is not one."""
    from . import api

    if user.is_admin_role:
        return True
    if not user.is_crm:
        return False
    if api.may_answer(client, user):
        return True
    return CrmContact.objects.filter(client=client, sheet__in=sheets_for(user)).exists()


def start_whatsapp(row, user):
    """The WhatsApp button: the client whose chat to open, or ``Refused``. Nothing is sent: a business may start a
    conversation only with a template Meta approved, and the real-estate branch has none yet, so this opens the chat of a
    person who already talks to this CRM person's number and says why for anybody else."""
    from . import api
    from .b2b import international_number

    if not may_contact(user, row.sheet):
        raise Refused("not_yours", "صاحب الشيت بس هو اللي بيتواصل منه، من رقمه.", "Only the sheet's holder contacts from it, from their own number.")
    if not (user.wa_phone_number_id or "").strip():
        raise Refused("no_line", "مفيش رقم واتساب متحدد ليك. الأدمن يحدده من ملفك.", "You have no WhatsApp number yet. The owner sets it on your file.")
    number = international_number(row.phone, "Egypt")
    if len(number) < 8:
        raise Refused("no_number", "الرقم ده مش مظبوط. اكتبه كامل (01... أو بكود الدولة +...).", "That number is not usable. Write it in full (01... or with the country code +...).")
    client = Client.find_by_phone(number)
    if client is None or not api.may_answer(client, user):
        raise Refused(
            "needs_template",
            "لسه مفيش كلام بينك وبين الرقم ده على واتساب. واتساب مابيسمحش نبدأ إحنا الكلام غير بقالب رسالة متوافق عليه من Meta، "
            "وقالب العقارات لسه ماتعملش. كلّمه من زرار «اتصل»، أو أول ما يبعتلك على رقمك الشات هيفتح من هنا.",
            "There is no WhatsApp conversation between you and this number yet. WhatsApp lets a business write first only with a "
            "template Meta approved, and the real-estate one is not made yet. Call them, or once they write to your number the "
            "chat opens from here.",
        )
    if row.client_id != client.pk:
        row.client = client
        row.save(update_fields=["client", "updated_at"])
    return client


def counts(sheet_ids):
    """``{sheet id: {"rows", "<status>"...}}`` for the list of sheets, in one query."""
    from django.db.models import Count

    out = {pk: {"rows": 0, **{status: 0 for status in CrmStatus.values}} for pk in sheet_ids}
    for line in CrmContact.objects.filter(sheet_id__in=sheet_ids).values("sheet_id", "status").annotate(n=Count("id")):
        bucket = out[line["sheet_id"]]
        bucket["rows"] += line["n"]
        if line["status"]:
            bucket[line["status"]] = line["n"]
    return out

