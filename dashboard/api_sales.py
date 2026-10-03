"""``/api/v1/`` - the Sales person's own line: the WhatsApp number they put on the company's business account, and the
mail address the admin gave them (phase 5, screen 6).

The page ``views.sales_line`` was a form that posted back to itself; here it is a read and a write, so a front end can
say what happened. The rules are the classic page's, written once in ``lines``: a number may not be the company's own
nor another person's, and nothing is changed when it may not be. What a line *does* (clients who write to this number or
address are this person's conversations, and the answers leave from the same number) is ``lines.py``, untouched.

A Sales person holds a line; the admin opens the page to read what it asks for and cannot save one (it is not theirs
to hold), and nobody else has it. The mail address is the admin's to give (the staff page), so it is shown, not edited.
"""

from django.http import JsonResponse

from . import lines
from .api_v1 import BadBody, _error, _object, _text, endpoint
from .models import AppSettings, Role
from .permissions import api_role_required

#: The longest a Phone number ID and a display number may be (the columns of ``User``).
MAX_PHONE_ID = 40
MAX_DISPLAY = 30


def _line_json(user):
    conf = AppSettings.load()
    return {
        "ok": True,
        # Each Sales person fills it in for themselves; anybody else may read what it asks for.
        "is_owner": user.is_sales,
        "values": {
            "wa_phone_number_id": user.wa_phone_number_id,
            "wa_display_number": user.wa_display_number,
            "mail_alias": user.mail_alias,
        },
        # Where the person's address has to deliver to: the company mailbox.
        "company_mail": conf.imap_user or conf.smtp_user or "",
    }


@endpoint("GET")
@api_role_required(Role.SALES)
def line(request):
    """The person's own number and address, and what the page tells them about setting them up."""
    return JsonResponse(_line_json(request.user))


@endpoint("POST")
@api_role_required(Role.SALES)
def line_save(request):
    """Save the person's own WhatsApp number: ``{"wa_phone_number_id": "...", "wa_display_number": "..."}``.

    Empty is allowed and means "no line of my own". A refusal names the box and says why, in the classic page's words,
    and nothing is saved.
    """
    user = request.user
    if not user.is_sales:
        # The admin may read the page, not hold a line.
        return _error(403, "forbidden")
    try:
        body = _object(request)
        phone_id, display = _text(body, "wa_phone_number_id", MAX_PHONE_ID), _text(body, "wa_display_number", MAX_DISPLAY)
    except BadBody:
        return _error(400, "bad_request")
    problem = lines.save_own_line(user, phone_id, display)
    if problem:
        return JsonResponse({"ok": False, "error": "invalid", "fields": {"wa_phone_number_id": problem}}, status=400)
    return JsonResponse(_line_json(user))
