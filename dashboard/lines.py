"""Client lines: the company's, and each Sales person's own.

Decided 27/09/2026. A Sales person may put their own WhatsApp Business number
(a second number on the company's business account, known to Meta by its
Phone number ID) and their own sub-address on the company mailbox. A client
who writes to one of those is that Sales person's conversation:

* it lands in *their* chats and mail, and in the admin's - nobody else's;
* the operation room keeps the company line and never sees theirs;
* the answer leaves from the same number / address it came in on.

A message carries its line on ``owner`` (``InboundMessage.owner`` and
``OutboundMessage.owner``). Null is the company line. Everything that lists
client messages filters through :func:`line_q`, so the rule is written once.

29/09/2026: every address on the company mailbox (operation1@, sales@...) is
given to one person by the admin, on the staff page (``User.mail_alias``,
Sales and Operation). A letter to it is that person's - theirs and the
admin's. A letter to no one's address is the company line; the setting
``AppSettings.mail_unassigned_admin_only`` decides whether the operation room
still sees those, or only the admin does.
"""

import email.utils
import re

from django.db.models import Q


def _unassigned_mail_is_admins():
    from .models import AppSettings

    return bool(AppSettings.load().mail_unassigned_admin_only)


def line_q(user, field="owner"):
    """The rows of the line(s) this person works, as a ``Q`` on ``field``.

    The admin sees every line. A Sales person sees their own. Anybody else
    (the operation room) sees the company's WhatsApp line, the letters sent
    to their own address, and - unless the admin keeps them - the letters
    sent to no one's.

    The channel sits next to ``owner`` on every row this is used on
    (``owner`` -> ``channel``, ``messages__owner`` -> ``messages__channel``).
    No negation on purpose: across a to-many join ``~Q`` would drop a client
    for having *any* letter, not just the one being filtered.
    """
    if user.is_admin_role:
        return Q()
    if user.is_sales:
        return Q(**{field: user})
    from .models import Channel

    channel = field[: -len("owner")] + "channel"
    not_mail = [c for c in Channel.values if c != Channel.EMAIL]
    if _unassigned_mail_is_admins():
        company = Q(**{f"{field}__isnull": True, f"{channel}__in": not_mail})
    else:
        company = Q(**{f"{field}__isnull": True})
    return company | Q(**{field: user, channel: Channel.EMAIL})


def sees(user, owner_id, channel):
    """``line_q`` for one row already in hand: may this person read it?"""
    from .models import Channel

    if user.is_admin_role:
        return True
    if user.is_sales:
        return owner_id == user.pk
    if owner_id is None:
        return channel != Channel.EMAIL or not _unassigned_mail_is_admins()
    return channel == Channel.EMAIL and owner_id == user.pk


def owner_for_number(phone_number_id):
    """The active Sales person whose WhatsApp number this is, or ``None``."""
    from .models import Role, User

    phone_number_id = str(phone_number_id or "").strip()
    if not phone_number_id:
        return None
    return User.objects.filter(
        role=Role.SALES, is_active=True, wa_phone_number_id=phone_number_id
    ).first()


_ADDRESS = re.compile(r"[A-Za-z0-9._%+'-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}")


def addresses_in(*headers):
    """Every e-mail address named in these header values, lower-cased.

    One header at a time, and the empty ones skipped: since Python 3.13
    ``getaddresses`` is strict, and a list with a blank header in it (a letter
    with no Cc) comes back as a single empty pair - every address lost. A
    header the parser still refuses is read with a plain pattern instead.
    """
    found = []
    for header in headers:
        header = str(header or "").strip()
        if not header:
            continue
        pairs = [a for _n, a in email.utils.getaddresses([header]) if a and "@" in a]
        for address in pairs or _ADDRESS.findall(header):
            address = address.strip().lower()
            if address not in found:
                found.append(address)
    return found


def owner_for_addresses(addresses):
    """The active person one of these addresses belongs to, or ``None``."""
    from .models import MAIL_ALIAS_ROLES, User

    wanted = [a.strip().lower() for a in addresses or () if a and "@" in a]
    if not wanted:
        return None
    for person in User.objects.filter(
        role__in=MAIL_ALIAS_ROLES, is_active=True
    ).exclude(mail_alias=""):
        if person.mail_alias.strip().lower() in wanted:
            return person
    return None


def reply_line(client, user, channel):
    """Whose line an answer to this client leaves from. ``None`` = the company's.

    A Sales person always answers from their own. The operation from the
    company's - except a letter that came to their own address, answered from
    that address. The admin answers on whatever line the client last wrote
    to on that channel - replying to a Sales person's client from the company
    number would be a stranger answering.
    """
    from .models import Channel

    if user.is_sales:
        return user
    if client is None:
        return None
    if not user.is_admin_role:
        if channel != Channel.EMAIL or not (user.mail_alias or "").strip():
            return None
        last = (
            client.messages.filter(channel=channel).filter(line_q(user))
            .order_by("-received_at").first()
        )
        return user if last is not None and last.owner_id == user.pk else None
    last = (
        client.messages.filter(channel=channel)
        .order_by("-received_at").select_related("owner").first()
    )
    return last.owner if last is not None else None


def number_problem(user, phone_number_id):
    """Why this can't be this person's WhatsApp line. Empty when it can."""
    from .models import AppSettings, User

    value = (phone_number_id or "").strip()
    if not value:
        return ""
    if not value.isdigit():
        return "الـPhone number ID أرقام بس — هتلاقيه في WhatsApp Manager جنب الرقم."
    conf = AppSettings.load()
    if value in {
        (conf.whatsapp_phone_number_id or "").strip(),
        (conf.recruit_phone_number_id or "").strip(),
    }:
        return "ده رقم الشركة نفسه — لازم رقم تاني خاص بيك."
    if User.objects.filter(wa_phone_number_id=value).exclude(pk=user.pk).exists():
        return "الرقم ده متسجّل لحد تاني."
    return ""


def save_own_line(user, phone_number_id, display_number):
    """Put a Sales person's own WhatsApp number on their record. Returns the reason it cannot be, or ``""``.

    One function for the classic page and the new app's door, so what may be saved is written once. Nothing is
    changed when there is a reason.
    """
    from . import services

    phone_number_id = (phone_number_id or "").strip()[:40]
    display_number = (display_number or "").strip()[:30]
    problem = number_problem(user, phone_number_id)
    if problem:
        return problem
    user.wa_phone_number_id = phone_number_id
    user.wa_display_number = display_number
    user.save(update_fields=["wa_phone_number_id", "wa_display_number"])
    services.log(user, "sales.line", user.username, f"wa={phone_number_id or '-'}")
    return ""


def alias_problem(user, alias):
    """Why this can't be this person's mail address. Empty when it can."""
    from .models import AppSettings, User

    value = (alias or "").strip().lower()
    if not value:
        return ""
    if value.count("@") != 1 or " " in value or "." not in value.rpartition("@")[2]:
        return "اكتب عنوان إيميل صحيح."
    conf = AppSettings.load()
    company = {
        email.utils.parseaddr(x or "")[1].strip().lower()
        for x in (conf.imap_user, conf.smtp_user, conf.smtp_from)
    }
    if value in company:
        return "ده إيميل الشركة نفسه — اكتب العنوان الفرعي (alias)."
    # A typo in the domain would be an address that never arrives here.
    domain = (conf.imap_user or "").strip().lower().rpartition("@")[2]
    if domain and value.rpartition("@")[2] != domain:
        return f"العنوان لازم يكون على دومين إيميل الشركة (@{domain})."
    if User.objects.filter(mail_alias__iexact=value).exclude(pk=user.pk).exists():
        return "العنوان ده متسجّل لحد تاني."
    return ""
