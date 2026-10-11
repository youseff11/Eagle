"""The WhatsApp numbers on the company's business account, and bringing a new one to life (11/10/2026).

A number added in WhatsApp Manager is verified by a code Meta texts to it, and then stays "Pending" until it is registered on
the Cloud API - something WhatsApp Manager has no button for. The settings page does both from here: the admin asks for the
code (``send_code``), types it, and ``link`` verifies it and registers the number in the same step.

Registering needs a six-digit two-step PIN. Nobody has to make one up or remember it: the first one is made here and kept on
``AppSettings.whatsapp_pin`` (a secret like the token next to it - never in an answer, never in the log), and every number
registered later uses the same one. A PIN typed on the page is for a number that already has a PIN of its own.

The list Meta gives is kept on ``AppSettings.wa_numbers`` (``refresh``), so the staff page can offer the numbers by name and
the chats page can name a line without asking Meta each time.
"""

import json
import secrets

from . import whatsapp
from .models import AppSettings, User, WA_LINE_ROLES

#: Meta's word for a number that is on the Cloud API.
CONNECTED = "CONNECTED"
METHODS = ("SMS", "VOICE")


class LineError(Exception):
    """A request this module refuses before Meta is asked."""

    def __init__(self, message_ar, message_en):
        super().__init__(message_en)
        self.message_ar = message_ar
        self.message_en = message_en


def _digits(value, longest):
    value = str(value or "").strip()
    return value if value.isdigit() and len(value) <= longest else ""


def clean_id(value):
    phone_id = _digits(value, 40)
    if not phone_id:
        raise LineError("الـPhone number ID أرقام بس.", "The phone number ID is digits only.")
    return phone_id


def clean_code(value):
    """The six digits Meta sent, however they were typed ("123-456", "123 456")."""
    code = "".join(ch for ch in str(value or "") if ch.isdigit())
    if code and len(code) != 6:
        raise LineError("الكود 6 أرقام.", "The code is 6 digits.")
    return code


def clean_pin(value):
    pin = str(value or "").strip()
    if pin and not (pin.isdigit() and len(pin) == 6):
        raise LineError("الـPIN 6 أرقام.", "The PIN is 6 digits.")
    return pin


def _row(item):
    return {
        "id": str(item.get("id") or ""),
        "number": str(item.get("display_phone_number") or ""),
        "name": str(item.get("verified_name") or ""),
        "status": str(item.get("status") or "").upper(),
        "verified": str(item.get("code_verification_status") or "").upper() == "VERIFIED",
    }


def known(conf=None):
    """The numbers as Meta last listed them: ``[{"id", "number", "name", "status", "verified"}]``."""
    conf = conf or AppSettings.load()
    try:
        rows = json.loads(conf.wa_numbers or "[]")
    except ValueError:
        return []
    return [row for row in rows if isinstance(row, dict) and row.get("id")]


def refresh(conf=None):
    """Ask Meta for the account's numbers and keep the list. Raises ``whatsapp.WhatsAppError``; a failure keeps the old list."""
    conf = conf or AppSettings.load()
    rows = [_row(item) for item in whatsapp.list_numbers(conf) if item.get("id")]
    conf.wa_numbers = json.dumps(rows, ensure_ascii=False)
    conf.save(update_fields=["wa_numbers"])
    return rows


def number_of(phone_id, conf=None):
    """The number as people dial it, from the kept list, or ``""``."""
    phone_id = str(phone_id or "").strip()
    for row in known(conf):
        if row["id"] == phone_id:
            return row["number"]
    return ""


def describe(conf=None):
    """The kept list, each number with what it is used for: the company's, the hiring line, a person's, or nothing yet."""
    conf = conf or AppSettings.load()
    company = (conf.whatsapp_phone_number_id or "").strip()
    recruit = (conf.recruit_phone_number_id or "").strip()
    holders = {
        person.wa_phone_number_id: person
        for person in User.objects.filter(role__in=WA_LINE_ROLES).exclude(wa_phone_number_id="")
    }
    out = []
    for row in known(conf):
        use = {"kind": "free"}
        if row["id"] == company:
            use = {"kind": "company"}
        elif row["id"] == recruit:
            use = {"kind": "recruit"}
        elif row["id"] in holders:
            person = holders[row["id"]]
            use = {"kind": "person", "id": person.pk, "name": person.short_name, "role": person.role}
        out.append({**row, "connected": row["status"] == CONNECTED, "use": use})
    return out


def send_code(phone_id, method="SMS"):
    """Have Meta text (or call) the number its verification code."""
    phone_id = clean_id(phone_id)
    method = str(method or "SMS").upper()
    if method not in METHODS:
        raise LineError("اختار رسالة أو مكالمة.", "Choose a text or a call.")
    whatsapp.request_code(phone_id, method)


def link(phone_id, code="", pin=""):
    """Verify the number with ``code`` (when it is not verified yet) and register it. Returns the kept list's row for it.

    Raises ``LineError`` for what is refused here and ``whatsapp.WhatsAppError`` for what Meta refuses. Nothing is kept until
    Meta has registered the number: a wrong PIN typed on the page never replaces the one that works.
    """
    phone_id, code, typed = clean_id(phone_id), clean_code(code), clean_pin(pin)
    conf = AppSettings.load()
    info = whatsapp.number_info(phone_id, conf)
    if str(info.get("code_verification_status") or "").upper() != "VERIFIED":
        if not code:
            raise LineError("الرقم لسه ماتأكدش: اطلب الكود واكتبه.", "The number is not verified yet: ask for the code and type it.")
        whatsapp.verify_code(phone_id, code, conf)
    use = typed or conf.whatsapp_pin or f"{secrets.randbelow(1_000_000):06d}"
    whatsapp.register_number(phone_id, use, conf)
    if use != conf.whatsapp_pin:
        conf.whatsapp_pin = use
        conf.save(update_fields=["whatsapp_pin"])
    try:
        refresh(conf)
    except whatsapp.WhatsAppError:
        pass
    return next((row for row in describe(conf) if row["id"] == phone_id), {"id": phone_id})


def staff_choices(person):
    """The numbers the staff page offers this person: theirs, and every other that is not the company's, the hiring line or
    somebody else's (named, so the admin sees who holds it)."""
    conf = AppSettings.load()
    taken = {(conf.whatsapp_phone_number_id or "").strip(), (conf.recruit_phone_number_id or "").strip()}
    holders = dict(
        User.objects.exclude(wa_phone_number_id="").exclude(pk=person.pk).values_list("wa_phone_number_id", "username")
    )
    choices = [("", "— ولا رقم —")]
    current = (person.wa_phone_number_id or "").strip()
    seen = set()
    for row in known(conf):
        if row["id"] in taken:
            continue
        label = f"{row['number'] or row['id']} — {row['name']}" if row["name"] else (row["number"] or row["id"])
        if row["status"] != CONNECTED:
            label += " (مش متربط)"
        if row["id"] in holders:
            label += f" — مع {holders[row['id']]}"
        choices.append((row["id"], label))
        seen.add(row["id"])
    if current and current not in seen:
        # Saving the file must not quietly take away a number the list does not show (yet).
        choices.insert(1, (current, person.wa_display_number or current))
    return choices
