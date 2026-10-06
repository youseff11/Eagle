"""``/api/v1/admin/settings/`` - the admin panel's settings page: the form, the "save & test" buttons, the Google link.

This page holds the product's secrets (the WhatsApp token, the Claude key, the mail passwords, Google's) and the switches that
decide which people are sent to the new interface. Two rules follow from that, and every test here is about one of them:

* **No secret is ever in an answer.** The classic form puts the stored values into the page (``render_value=True``); this
  door does not. A secret is described as ``saved: true/false``, accepted when it is typed, kept when it is left empty and
  cleared only by an explicit ``null`` (``api_forms``). The error text of a connection test or a Google sync is cleaned of any
  stored secret before it leaves. Nothing here logs a value.
* **The form decides.** The values go to the classic ``SettingsForm`` as its input, so every rule it has (an address must be an
  address, a list of aliases is cleaned, the alias list is Google's while Google is linked) is the rule here, and what the
  classic page wrote down (``settings.update``) is written down the same way.

Only the admin is answered. A GET changes nothing.
"""


from django.http import JsonResponse
from django.urls import reverse

from . import api_forms, galiases, identity, services
from .api_v1 import BadBody, _error, _object, _stamp, endpoint
from .forms import SettingsForm
from .models import AppSettings, Role
from .permissions import api_role_required

#: Fields that hold a secret. The six with a password box are found by their widget; the two plain boxes are named here so
#: that they are treated the same way everywhere (a verify token and a shared secret are secrets as much as a password is).
SECRET_FIELDS = (
    "claude_api_key", "whatsapp_access_token", "whatsapp_app_secret", "whatsapp_verify_token", "webhook_shared_secret",
    "imap_password", "smtp_password", "google_client_secret",
)
#: Stored secrets that are not form fields at all, but must not leave inside a message either.
HIDDEN_SECRETS = ("google_refresh_token",)

#: The settings page in order: sections, and the groups of fields inside them (a title in both languages, or none).
#: Every field of the form is in exactly one group - a test holds that, so a field added to the form cannot go missing here.
SECTIONS = (
    {
        "key": "ai", "icon": "sparkles", "ar": "مراجعة الترجمة بالـ AI", "en": "AI translation check",
        "note": (
            "لما تكون مفعّلة، المترجم بيشوف زرار «تشيك» بيراجع الترجمة ويقوله الأخطاء ومكانها من غير ما يعدّل حاجة.",
            "When enabled, translators get a Check button that reports issues and their location without editing anything.",
        ),
        "groups": (
            {"fields": ("ai_check_enabled", "claude_api_key", "claude_model")},
            {"ar": "مساعد النظام", "en": "The help assistant", "fields": ("helpbot_ai_enabled", "helpbot_actions_enabled")},
        ),
    },
    {
        "key": "workflow", "icon": "list-checks", "ar": "قواعد الشغل", "en": "Workflow rules",
        "groups": ({"fields": (
            "response_window_seconds", "deadline_warning_minutes", "penalty_value", "max_rating", "poll_ms",
            "rate_keywords", "group_creator_roles",
        )},),
    },
    {
        "key": "whatsapp", "icon": "phone", "ar": "واتساب", "en": "WhatsApp",
        "groups": (
            {"fields": (
                "whatsapp_verify_token", "whatsapp_phone_number_id", "whatsapp_access_token", "whatsapp_app_secret",
                "whatsapp_api_version", "webhook_shared_secret",
            )},
            {"ar": "خط التوظيف", "en": "The recruitment line", "fields": ("recruit_phone_number_id", "recruit_number_display")},
        ),
    },
    {
        "key": "email", "icon": "mail", "ar": "الإيميل", "en": "Email",
        "groups": (
            {"ar": "استقبال (IMAP)", "en": "Receiving (IMAP)", "fields": ("imap_host", "imap_port", "imap_user", "imap_password", "imap_folder", "imap_read_spam")},
            {
                "ar": "إرسال (SMTP)", "en": "Sending (SMTP)",
                "note": ("سيبها فاضية عشان تستخدم نفس بيانات الـ IMAP.", "Leave blank to reuse the IMAP credentials."),
                "fields": ("smtp_host", "smtp_port", "smtp_user", "smtp_password", "smtp_from", "smtp_use_tls"),
            },
            {"fields": ("mail_unassigned_admin_only", "mail_aliases")},
            {
                "ar": "مزامنة العناوين مع Google", "en": "Sync aliases with Google",
                "fields": ("google_client_id", "google_client_secret", "mail_aliases_hidden"),
            },
            {"ar": "شكل إيميلات الـSales", "en": "Sales letter", "fields": ("sales_mail_website", "sales_mail_footer")},
            {"fields": ("simulation_enabled",)},
        ),
    },
)

#: The labels and hints the classic template writes beside its fields, in both languages. A field with none is drawn with
#: the form's own label.
TEXTS = {
    "ai_check_enabled": {"label": ("فعّل مراجعة الـ AI", "Enable the AI check")},
    "claude_api_key": {"label": ("مفتاح Claude API", "Claude API key")},
    "claude_model": {"label": ("الموديل", "Model")},
    "helpbot_actions_enabled": {
        "label": ("خلّي المساعد ينفّذ أوامري (للأدمن بس)", "Let the assistant carry out my orders (admin only)"),
        "hint": (
            "تقوله «اعمل شيفت من 9 لـ 5» أو «اخصم من فلان يوم بسبب كذا» فيجهّز الأمر ويعرضه عليك في كارت، وماينفّذش غير لما تضغط «نفّذ». التنفيذ بيمرّ على نفس الأبواب اللي زرار في الصفحة بيستخدمها، وكل أمر بيتسجل في سجل النشاط. الخصم بيتسجل «مستني الاعتماد» زي أي خصم. محتاج الخيار اللي فوقه شغّال ومفتاح Claude محفوظ، ومش بيشتغل لحد غيرك.",
            "Tell it \"make a shift from 9 to 5\" or \"deduct a day from so-and-so for this reason\" and it prepares the order and shows it on a card; nothing runs until you press «Run». It goes through the same doors a button on the page uses, and every order is written to the audit log. A deduction is recorded as waiting for approval like any other. It needs the option above to be on and a Claude key saved, and it never works for anybody but you.",
        ),
    },
    "helpbot_ai_enabled": {
        "label": ("خلّي المساعد يرد بالـ AI", "Let the assistant answer with the AI"),
        "hint": (
            "المساعد (الزرار اللي فوق جنب التنبيهات) بيرد من دليل الخطوات في كل الأحوال. لو فتحت ده ومفتاح Claude موجود، بيبعت سؤال الموظف ودليل دوره بس لـ Claude عشان يفهم السؤال ويرتّب الرد. مابيبعتش بيانات عملاء ولا أي حاجة من الشغل.",
            "The assistant (the button in the top bar) always answers from the step guides. When this is on and a Claude key is saved, it sends the person's question and the guides of their role to Claude, which understands the question and words the reply. No client data and nothing from the work is sent.",
        ),
    },
    "response_window_seconds": {"label": ("مهلة تأكيد الاستلام (ثانية)", "Confirmation window (seconds)")},
    "deadline_warning_minutes": {"label": ("تحذير قبل الديدلاين (دقيقة)", "Deadline warning (minutes)")},
    "penalty_value": {"label": ("الخصم عند عدم الرد (نجمة)", "Penalty per miss (stars)")},
    "max_rating": {"label": ("أقصى تقييم", "Max rating")},
    "poll_ms": {"label": ("سرعة التحديث (ملي ثانية)", "Polling interval (ms)")},
    "rate_keywords": {
        "label": ("الكلمات اللي بتخفي الرسالة عن الأوبريشن", "Keywords that hide a message from Operation"),
        "hint": ("افصل بينهم بفاصلة.", "Comma separated."),
    },
    "group_creator_roles": {
        "label": ("مين يقدر يعمل جروب مع عميل", "Who can open a client group"),
        "hint": (
            "الجروب بيفتح خط مباشر مع العميل على واتساب، فاختار مين ينفع يعمله. الأدمن دايمًا يقدر.",
            "A group opens a direct line to the client on WhatsApp, so choose who may open one. The admin always can.",
        ),
    },
    "whatsapp_verify_token": {
        "label": ("Verify token", "Verify token"),
        "hint": ("أي كلمة من اختيارك — بس لازم تكتب نفسها في Meta.", "Any string you pick - must match what you type in Meta."),
    },
    "whatsapp_phone_number_id": {"label": ("Phone number ID", "Phone number ID")},
    "whatsapp_access_token": {"label": ("Access token", "Access token")},
    "whatsapp_app_secret": {
        "label": ("App secret", "App secret"),
        "hint": ("اختياري — بيتأكد إن الرسايل جاية من Meta فعلًا.", "Optional - verifies that requests really come from Meta."),
    },
    "whatsapp_api_version": {"label": ("API version", "API version")},
    "webhook_shared_secret": {"label": ("سر الويب هوك (للمحاكاة)", "Webhook secret (simulation)")},
    "recruit_phone_number_id": {
        "label": ("Phone number ID للتوظيف", "Recruitment phone number ID"),
        "hint": (
            "رقم تاني على نفس حساب واتساب الأعمال. نفس التوكن ونفس الويب هوك — الـID ده هو اللي بيوجّه الرسالة لبوت التوظيف بدل إنبوكس العملاء. سيبه فاضي وكل حاجة تفضل زي ما هي.",
            "A second number on the same WhatsApp business account. Same token, same webhook: this ID is what routes a message to the hiring bot instead of the client inbox. Leave it blank and nothing changes.",
        ),
    },
    "recruit_number_display": {"label": ("الرقم (للعرض)", "Number (display only)")},
    "imap_host": {"label": ("Host", "Host"), "hint": ("imap.gmail.com", "imap.gmail.com")},
    "imap_port": {"label": ("Port", "Port")},
    "imap_user": {"label": ("User", "User")},
    "imap_password": {
        "label": ("Password", "Password"),
        "hint": ("جيميل: App Password مش الباسورد العادي.", "Gmail: use an App Password, not your normal password."),
    },
    "imap_folder": {"label": ("Folder", "Folder")},
    "imap_read_spam": {
        "label": ("اقرا فولدر السبام كمان", "Also read the Spam folder"),
        "hint": (
            "جيميل بيحط ميلات عملاء حقيقيين في السبام أحيانًا، وأولها ميل العميل الجديد. لما تفتح الخيار ده الميلات اللي هناك بتنزل زي أي ميل ولحظيًا. بس سبام الغرباء بينزل معاها: كل مرسل جديد بيبقى عميل بكود والأوبريشن بيتنبّه بصوت. لو عارف المرسل، علّمه «مش سبام» في Gmail أحسن.",
            "Gmail sometimes files a real client's mail as spam, a new client's first letter most of all. When on, what is in that folder arrives like any other mail, instantly. Strangers' spam arrives with it: each new sender becomes a client code and the operation is alerted with a sound. Marking a sender you know as \"not spam\" in Gmail is better.",
        ),
    },
    "smtp_host": {"label": ("Host", "Host"), "hint": ("smtp.gmail.com", "smtp.gmail.com")},
    "smtp_port": {"label": ("Port", "Port")},
    "smtp_user": {"label": ("User", "User")},
    "smtp_password": {"label": ("Password", "Password")},
    "smtp_from": {"label": ("المرسل", "From")},
    "smtp_use_tls": {"label": ("TLS", "TLS")},
    "mail_unassigned_admin_only": {
        "label": ("الميل اللي على عنوان مش متحدد لحد يوصل للأدمن بس", "Mail to an address nobody holds reaches the admin only"),
        "hint": (
            "كل موظف بيستقبل ميلات العنوان اللي متحدد له من صفحة الموظفين. الاختيار ده للباقي (زي info@ نفسه): مقفول = الأوبريشن كلهم يشوفوه، مفتوح = الأدمن بس.",
            "Each person receives the address set for them on the staff page. This is for the rest (info@ itself, say): off = the whole operation room sees it, on = the admin alone.",
        ),
    },
    "mail_aliases": {
        "label": ("العناوين الموجودة على ميل الشركة", "Aliases on the company mailbox"),
        "hint": (
            "عنوان في كل سطر. دي القايمة اللي بتظهر في صفحة الموظف تختار منها. أي عنوان جديد لازم يتضاف الأول alias في Google Workspace.",
            "One per line. This is the list the staff page offers. A new address must first be added as an alias in Google Workspace.",
        ),
    },
    "google_client_id": {"label": ("Client ID", "Client ID")},
    "google_client_secret": {"label": ("Client Secret", "Client Secret")},
    "mail_aliases_hidden": {
        "label": ("عناوين متستخبية", "Hidden aliases"),
        "hint": (
            "موجودة في Google بس مش هتظهر في صفحة الموظف (زي hr@ وaccounts@).",
            "On Google, but never offered on the staff page (hr@, accounts@).",
        ),
    },
    "sales_mail_website": {
        "label": ("الموقع", "Website"),
        "hint": ("فاضي = مش هيظهر.", "Blank = not shown."),
    },
    "sales_mail_footer": {
        "label": ("الشريط اللي تحت (المواعيد والعنوان)", "Bottom band (hours, address)"),
        "hint": ("سطر لكل معلومة. فاضي = الشريط مش هيظهر.", "One line each. Blank = no band."),
    },
    "simulation_enabled": {"label": ("اسمح بمحاكاة الرسايل", "Allow message simulation")},
}

#: The longest test address or number a connection test reads.
MAX_TEST_TARGET = 200


def scrub(text, conf=None):
    """``text`` with every stored secret replaced by ``***``: an error from a mail server or Google may quote what it was sent."""
    conf = conf or AppSettings.load()
    out = str(text or "")
    for name in (*SECRET_FIELDS, *HIDDEN_SECRETS):
        secret = str(getattr(conf, name, "") or "")
        if len(secret) >= 4:
            out = out.replace(secret, "***")
    return out


def _clean(value, conf):
    """``scrub`` applied to every string in a report, however deep."""
    if isinstance(value, str):
        return scrub(value, conf)
    if isinstance(value, dict):
        return {key: _clean(item, conf) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_clean(item, conf) for item in value]
    return value


def _changed(form, values):
    """Which boxes a save changed, as names only: a secret is "set" or "cleared", never its value.

    The audit row used to say only that settings were saved. A webhook secret cleared on purpose, by mistake or from a stolen
    session leaves the webhook open to anybody who knows its address, and nothing said so.

    Only boxes the request carried can have changed (the rest were filled from what is stored), which also keeps out the
    fields the form cannot compare when it is filled in (it sets their starting value only for an empty form).
    """
    out = []
    for name in form.changed_data:
        if name not in values:
            continue
        if name in SECRET_FIELDS:
            out.append(f"{name}:{'set' if form.cleaned_data.get(name) else 'cleared'}")
        else:
            out.append(name)
    return ", ".join(out)[:500]


def _is_local(request):
    host = request.get_host()
    return host.split(":")[0] in ("127.0.0.1", "localhost", "0.0.0.0") or host.startswith("192.168.") or host.startswith("10.")


def _pair(texts):
    return {"ar": texts[0], "en": texts[1]}


def _fields(form):
    """The form's fields with the classic template's bilingual labels and hints laid over them."""
    out = []
    for field in api_forms.describe(form, secrets=SECRET_FIELDS):
        texts = TEXTS.get(field["name"], {})
        if "label" in texts:
            field["label_ar"], field["label_en"] = texts["label"]
        if "hint" in texts:
            field["hint_ar"], field["hint_en"] = texts["hint"]
        out.append(field)
    return out


def _sections():
    out = []
    for section in SECTIONS:
        entry = {"key": section["key"], "icon": section["icon"], "ar": section["ar"], "en": section["en"], "groups": []}
        if "note" in section:
            entry.update({"note_ar": section["note"][0], "note_en": section["note"][1]})
        for group in section["groups"]:
            row = {"fields": list(group["fields"])}
            if "ar" in group:
                row.update({"ar": group["ar"], "en": group["en"]})
            if "note" in group:
                row.update({"note_ar": group["note"][0], "note_en": group["note"][1]})
            entry["groups"].append(row)
        out.append(entry)
    return out


@endpoint("GET")
@api_role_required(Role.ADMIN)
def settings(request):
    """Everything the settings page draws. A secret is ``saved`` or not; its value is not here."""
    conf = AppSettings.load()
    form = SettingsForm(instance=conf)
    return JsonResponse({
        "ok": True,
        "fields": _fields(form),
        "sections": _sections(),
        "status": {
            "whatsapp_saved": bool(conf.whatsapp_access_token and conf.whatsapp_phone_number_id),
            "email_saved": bool(conf.imap_host and conf.imap_user),
            "google_configured": bool(conf.google_client_id and conf.google_client_secret),
            "google_connected": galiases.is_connected(conf),
            "google_sync_at": _stamp(conf.google_sync_at, "%d/%m"),
            "google_sync_error": scrub(conf.google_sync_error, conf),
            # Without an App secret the webhook takes a Meta-shaped message from anybody who knows its address (no signature to
            # check); without the shared secret it takes the simple one. The page says so.
            "webhook_signed": bool(conf.whatsapp_app_secret),
            "webhook_secret_set": bool(conf.webhook_shared_secret),
        },
        "urls": {
            "webhook": request.build_absolute_uri(reverse("dashboard:wh_whatsapp")),
            "google_redirect": request.build_absolute_uri(reverse("dashboard:google_callback")),
            "google_connect": reverse("dashboard:google_connect"),
            "is_local": _is_local(request),
            "is_https": request.is_secure(),
        },
    })


@endpoint("POST")
@api_role_required(Role.ADMIN)
def settings_save(request):
    """Save what was changed. The form decides; the log gets what the classic page wrote."""
    conf = AppSettings.load()
    try:
        body = _object(request)
        values = body.get("values", {})
        data = api_forms.form_data(SettingsForm, values, instance=conf, secrets=SECRET_FIELDS)
    except (BadBody, api_forms.BadValues):
        return _error(400, "bad_body")
    form = SettingsForm(data, instance=conf)
    if not form.is_valid():
        return api_forms.invalid(form)
    form.save()
    services.log(request.user, "settings.update", "", _changed(form, values))
    if "mail_aliases_hidden" in form.changed_data:
        # A hidden address leaves the list now, not at the next sync.
        galiases.sync(force=True)
    return JsonResponse({"ok": True})


# ---------------------------------------------------------------------------
# Google, and the two "save & test" buttons
# ---------------------------------------------------------------------------

@endpoint("POST")
@api_role_required(Role.ADMIN)
def google_sync(request):
    """Ask Google for the alias list now. The answer says what changed; a failure changes nothing (``galiases``)."""
    conf = AppSettings.load()
    ran, problem, result = galiases.sync(force=True)
    added = removed = released = []
    if ran and result is not None:
        added, removed, released = result
    return JsonResponse({
        "ok": True,
        "ran": bool(ran),
        "error": scrub(problem, conf),
        "added": list(added),
        "removed": list(removed),
        "released": [str(person) for person in released],
    })


@endpoint("POST")
@api_role_required(Role.ADMIN)
def google_disconnect(request):
    galiases.disconnect(AppSettings.load())
    services.log(request.user, "settings.google_disconnect")
    return JsonResponse({"ok": True})


def _target(request):
    try:
        body = _object(request)
    except BadBody:
        return None
    target = body.get("to", "")
    if not isinstance(target, str) or len(target) > MAX_TEST_TARGET or "\x00" in target:
        return None
    return target.strip()


@endpoint("POST")
@api_role_required(Role.ADMIN)
def test_whatsapp(request):
    """Check the WhatsApp credentials as saved, and send a test message to ``to`` when one is given."""
    from . import whatsapp as wa

    target = _target(request)
    if target is None:
        return _error(400, "bad_body")
    # That a test message went out, not to whom: the number is a person's.
    services.log(request.user, "settings.test_send", "whatsapp", "with a target" if target else "credentials only")
    return JsonResponse(_clean(wa.check_connection(target), AppSettings.load()))


@endpoint("POST")
@api_role_required(Role.ADMIN)
def test_email(request):
    """Check the mail credentials as saved, and send a test mail to ``to`` when one is given."""
    from . import mailer

    target = _target(request)
    if target is None:
        return _error(400, "bad_body")
    services.log(request.user, "settings.test_send", "email", "with a target" if target else "credentials only")
    conf = AppSettings.load()
    return JsonResponse(_clean(mailer.check_connection(conf, target), conf))
