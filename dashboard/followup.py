"""The follow-up message: how a client chat goes on after WhatsApp's 24-hour window has closed.

Meta carries a written message only within 24 hours of the client's last one on that line; after that only an approved
template goes. ``FOLLOWUP_TEMPLATES`` is that template, in Arabic and in English. The chat offers it (``offer``) when the
window of the line this person answers from is closed, and ``send`` sends it from that line. When the client answers, the
window is open again and the conversation goes on as always.

The greeting is the client's company (the owner's choice, 17/10/2026): "Hello Lingua GmbH, ...". Nobody types it, the
server fills it from the client's record, so the person pressing the button needs no sight of it. What is kept in the
thread holds the client's code in its place (``kept_greeting``).

Submitted to Meta by ``manage.py wa_templates <WABA_ID> --submit chat_followup_ar chat_followup_en`` (the command reads
the words from here). A rejected one is renamed here, never deleted at Meta: see the whatsapp-templates skill.
"""

import logging
from datetime import timedelta

from django.db import transaction
from django.utils import timezone

from .models import Channel, Client, OutboundMessage

logger = logging.getLogger(__name__)

FOLLOWUP_TEMPLATE_AR = "chat_followup_ar"
FOLLOWUP_TEMPLATE_EN = "chat_followup_en"
#: UTILITY: an answer to a request the client already made with us, not an offer. Meta may still file it under MARKETING
#: (it did so to ``translation_quote_ready``); it is sent all the same, at that price.
FOLLOWUP_SPEC_AR = {
    "category": "UTILITY",
    "language": "ar",
    "body": "أهلًا {{1}}، معاك فريق EagleLingua بخصوص طلبك معانا. "
            "رد على الرسالة دي عشان نكمّل معاك.",
    "footer": "EagleLingua",
    "example": ["شركة النور للترجمة"],
    "purpose": "Opens a client chat again after the 24-hour window closed, from the chat's «رسالة متابعة» button.",
}
FOLLOWUP_SPEC_EN = {
    "category": "UTILITY",
    "language": "en",
    "body": "Hello {{1}}, this is the EagleLingua team following up on your request with us. "
            "Please reply to this message so we can continue.",
    "footer": "EagleLingua",
    "example": ["Lingua GmbH"],
    "purpose": "The English follow-up, for a client who does not read Arabic.",
}
#: language -> (template name, its words at Meta).
FOLLOWUP_TEMPLATES = {"ar": (FOLLOWUP_TEMPLATE_AR, FOLLOWUP_SPEC_AR), "en": (FOLLOWUP_TEMPLATE_EN, FOLLOWUP_SPEC_EN)}
#: What ``{{1}}`` is when the client's record has no company.
NO_COMPANY = {"ar": "حضرتك", "en": "there"}
#: A follow-up that went within this long and was not answered is not sent again: one is enough to ask.
REPEAT = timedelta(hours=24)


class Refused(Exception):
    """Nothing was sent. ``code`` is what the page is told."""

    def __init__(self, code, message_ar=""):
        super().__init__(code)
        self.code = code
        self.message_ar = message_ar


def language_for(number):
    """``"ar"`` for a number from an Arab country, else English (the B2B letter's rule, ``b2b.intro_language``)."""
    from . import b2b

    return "ar" if b2b.intro_language(number) == "ar" else "en"


def company_greeting(client, language):
    # Meta refuses a parameter with a line break, a tab or more than four spaces in a row.
    company = " ".join(str(client.company or "").split())
    return company or NO_COMPANY[language]


def kept_greeting(client, language):
    """``{{1}}`` as the thread keeps it: the client's code, never the company. What is kept is read by everyone on the
    line, and a row is carried further than its line (an admin forwards it to the operation as it is), so the server
    writes no name into it; the client's phone shows the company, the thread the code that stands for it."""
    return client.code if (client.company or "").strip() else NO_COMPANY[language]


def text(language, greeting):
    body = FOLLOWUP_TEMPLATES[language][1]["body"]
    return body.replace("{{1}}", greeting)


def _line(client, user):
    """The line the follow-up leaves from, as for a reply (``lines.reply_line``). The admin answers on the line the client
    last wrote to; a client who never wrote back at all (a Sales person's opening message is all there is) belongs to the
    line that last wrote to them, or a Sales person's company would hear from the company number, a stranger."""
    from . import lines

    owner = lines.reply_line(client, user, Channel.WHATSAPP)
    if owner is None and user.is_admin_role and not client.messages.filter(channel=Channel.WHATSAPP).exists():
        last = client.deliveries.filter(channel=Channel.WHATSAPP).select_related("owner").order_by("-created_at").first()
        if last is not None:
            owner = last.owner
    return owner


def _window_open(client, owner):
    return Client.window_from(client.last_inbound_on(owner))[0]


def _recent(client, owner):
    since = timezone.now() - REPEAT
    return client.deliveries.filter(
        owner=owner, channel=Channel.WHATSAPP, created_at__gte=since,
        body__in=[text(language, kept_greeting(client, language)) for language in FOLLOWUP_TEMPLATES],
        status__in=(OutboundMessage.Status.SENDING, OutboundMessage.Status.SENT),
    ).exists()


def offer(client, user):
    """What the chat shows when the window is closed: ``{"language", "texts", "sent_recently"}``, or ``None`` when no
    follow-up is to be offered (a client off this person's lines, the window open, the client blocked or without a
    WhatsApp number)."""
    from . import api

    if client.is_blocked or not client.reply_target(Channel.WHATSAPP) or not api.may_answer(client, user):
        return None
    owner = _line(client, user)
    if _window_open(client, owner):
        return None
    return {
        "language": language_for(client.reply_target(Channel.WHATSAPP)),
        # As this person may read them: the company for whoever may know the client, the code for everybody else.
        "texts": {
            language: text(language, company_greeting(client, language) if user.can_see_client_identity
                           else kept_greeting(client, language))
            for language in FOLLOWUP_TEMPLATES
        },
        "sent_recently": _recent(client, owner),
    }


def send(client, user, language):
    """Send the follow-up from the line this person answers from. Returns the ``OutboundMessage``; ``Refused`` when
    nothing went (``Refused.code``: blocked, window_open, sent_recently, no_number, no_line, send_failed)."""
    from . import services, whatsapp as wa
    from .identity import scrub_contacts

    if language not in FOLLOWUP_TEMPLATES:
        raise Refused("bad_language")
    if client.is_blocked:
        raise Refused("blocked", services.BLOCKED_AR)
    target = client.reply_target(Channel.WHATSAPP)
    if not target:
        raise Refused("no_number", "العميل ده مفيش عنده رقم واتساب مسجل.")
    owner = _line(client, user)
    from_id = (owner.wa_phone_number_id or "").strip() if owner else ""
    if owner is not None and not from_id:
        raise Refused("no_line", "مفيش رقم واتساب متحدد لصاحب المحادثة دي — الأدمن يحدده من صفحة الموظف.")

    with transaction.atomic():
        # The client's row alone, so that two presses at once send one message.
        Client.objects.select_for_update().filter(pk=client.pk).first()
        if _window_open(client, owner):
            raise Refused("window_open", "النافذة مفتوحة: اكتب للعميل عادي.")
        if _recent(client, owner):
            raise Refused("sent_recently", "رسالة المتابعة اتبعتت في آخر 24 ساعة ولسه العميل مارّدش.")
        template = FOLLOWUP_TEMPLATES[language][0]
        outbound = OutboundMessage.objects.create(
            client=client, kind=OutboundMessage.Kind.CHAT, created_by=user, owner=owner,
            channel=Channel.WHATSAPP, to_identity=target, body=text(language, kept_greeting(client, language)),
            status=OutboundMessage.Status.SENDING,
        )

    try:
        outbound.provider_id = wa.send_template(
            target, template, language, [company_greeting(client, language)], from_id=from_id,
        )[:190]
    except wa.WhatsAppError as exc:
        outbound.status = OutboundMessage.Status.FAILED
        outbound.error_message = scrub_contacts(exc.message_ar)
        outbound.save(update_fields=["status", "error_message"])
        services.log(user, "client.followup_failed", client.code, (exc.message_en or "")[:200])
        raise Refused("send_failed", outbound.error_message or "واتساب رفض الرسالة.") from None
    except Exception:  # noqa: BLE001 - a dropped connection while Meta answered: nobody knows whether it arrived
        outbound.status = OutboundMessage.Status.FAILED
        outbound.error_message = services.SEND_UNSURE_AR
        outbound.save(update_fields=["status", "error_message"])
        services.log(user, "client.followup_failed", client.code, "unexpected error")
        raise Refused("send_failed", services.SEND_UNSURE_AR) from None
    outbound.status = OutboundMessage.Status.SENT
    outbound.save(update_fields=["status", "provider_id"])
    services.log(user, "client.followup", client.code, f"template {template}")
    try:
        from . import b2b

        b2b.note_outbound(outbound)
    except Exception:  # noqa: BLE001 - the message has left; a sheet mark that fails must not say otherwise
        logger.exception("Marking the B2B sheet for client %s failed", client.code)
    return outbound
