"""``/api/v1/help/`` - the help assistant: the questions to offer, and the answer to one asked.

Every signed-in person has it, and what it says is decided by who they are: the guides it answers from are the ones their role
may read (``guides.for_user``), whichever way the answer is found (``helpbot``). It explains and does nothing: no door here
changes anything but the log of what was asked, and none reads a person's work.

A GET changes nothing. Asking is a POST (CSRF-protected like every write) because it writes the log and may call Claude.
"""

from django.http import JsonResponse

from . import guides, helpactions, helpbot
from .api_v1 import BadBody, _error, _object, _text, endpoint
from .models import AppSettings, Role, User
from .permissions import api_role_required

#: The longest the front end's conversation may be, and the most one request may carry of it.
MAX_HISTORY_BODY = helpbot.MAX_HISTORY * 2


def _lang(request, user):
    return helpbot.clean_lang(request.GET.get("lang", ""), user)


def _card(guide, lang):
    """A guide as a button: what it is called, and the page it starts on (``""`` when it is not one page)."""
    return {"id": guide.id, "title": guide.title[0 if lang == "ar" else 1], "path": guide.path}


@endpoint("GET")
def home(request):
    """The questions to offer when the assistant opens, in this person's language: their own role's first."""
    user = request.user
    lang = _lang(request, user)
    conf = AppSettings.load()
    # Whoever is not technical support themselves may write to the support account (the first one, when there are several).
    support = None if user.is_support else User.objects.filter(role=Role.SUPPORT, is_active=True).order_by("pk").first()
    return JsonResponse({
        "ok": True,
        "support": {"id": support.pk, "name": support.short_name} if support else None,
        # Whether the owner has put the AI to work is the owner's to know.
        "ai": helpbot.ai_available(conf) if user.is_admin_role else False,
        # Whether this person may give orders: only the owner, only when they switched it on.
        "orders": helpactions.available(conf, user),
        "starters": [_card(guide, lang) for guide in helpbot.starters(user)],
    })


@endpoint("POST")
def ask(request):
    """One question (``{"question", "lang", "page", "history", "guide"}``) and its answer.

    ``guide`` is a question picked from the offered ones; ``page`` is where the person is (reduced to its shape here);
    ``history`` is the last few turns the page kept, which only the AI path reads.
    """
    user = request.user
    try:
        body = _object(request)
        question = _text(body, "question", helpbot.MAX_QUESTION)
        guide_id = _text(body, "guide", 60)
        page = _text(body, "page", 200)
        lang = _text(body, "lang", 5)
        history = body.get("history", [])
        if not isinstance(history, list) or len(history) > MAX_HISTORY_BODY:
            raise BadBody
    except BadBody:
        return _error(400, "bad_body")
    if not question and not guide_id:
        return _error(400, "empty")
    if helpbot.too_fast(user):
        return _error(429, "slow_down")
    lang = helpbot.clean_lang(lang, user)
    result = helpbot.answer(user, question, lang=lang, page=page, history=history, guide_id=guide_id)
    return JsonResponse({
        "ok": True,
        "answer": result.text,
        "answered": result.answered,
        "source": result.source,
        "open": _card(result.guide, lang) if result.guide and result.guide.path else None,
        "related": [_card(guide, lang) for guide in result.related],
        "order": helpactions.card(result.proposal, lang) if result.proposal else None,
        # False for an answer that names people (an order that did not hold): the page does not send it back as conversation.
        "keep": result.keep,
    })


_REFUSALS = {"gone": (404, "not_found"), "done": (409, "already_done"), "expired": (409, "expired"), "busy": (429, "slow_down")}


def _order_lang(request):
    """The language the owner is reading in, from the body of a press on a card (``None`` when the body is not an object)."""
    try:
        return helpbot.clean_lang(_text(_object(request), "lang", 5), request.user)
    except BadBody:
        return None


@endpoint("POST")
@api_role_required(Role.ADMIN)
def order_run(request, pk):
    """The owner's yes to a prepared order: it is carried out, through the door a click would have used, once."""
    lang = _order_lang(request)
    if lang is None:
        return _error(400, "bad_body")
    # The switch is asked again here: an order prepared a minute ago is not run after the owner turned the option off.
    if not helpactions.available(AppSettings.load(), request.user):
        return _error(403, "orders_off")
    try:
        row, ok, message = helpactions.run(request, request.user, pk, lang)
    except helpactions.NotAllowed as refusal:
        status, code = _REFUSALS.get(refusal.code, (409, refusal.code))
        return _error(status, code)
    return JsonResponse({"ok": True, "done": ok, "status": row.status, "message": message})


@endpoint("POST")
@api_role_required(Role.ADMIN)
def order_cancel(request, pk):
    """The owner's no: a waiting order is withdrawn."""
    if not helpactions.cancel(request.user, pk):
        return _error(404, "not_found")
    return JsonResponse({"ok": True})
