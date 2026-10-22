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

from . import api_forms, galiases, identity, services, usage as usage_report, walines
from .api_v1 import BadBody, _error, _object, _stamp, endpoint
from .forms import SettingsForm
from .models import AppSettings, Role
from .permissions import api_role_required

#: Fields that hold a secret. The six with a password box are found by their widget; the two plain boxes are named here so
#: that they are treated the same way everywhere (a verify token and a shared secret are secrets as much as a password is).
SECRET_FIELDS = (
    "claude_api_key", "whatsapp_access_token", "whatsapp_app_secret", "whatsapp_verify_token", "webhook_shared_secret",
    "imap_password", "smtp_password", "google_client_secret", "bunny_api_key", "neon_api_key", "render_api_key",
)
#: Stored secrets that are not form fields at all, but must not leave inside a message either.
HIDDEN_SECRETS = ("google_refresh_token", "whatsapp_pin")

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
            {"ar": "ترجمة رسايل العملاء", "en": "Translating clients' messages", "fields": ("chat_translate_enabled",)},
            {"ar": "الترجمة بالـAI بدل المترجم", "en": "AI translation instead of a translator", "fields": ("ai_translate_enabled",)},
        ),
    },
    {
        "key": "b2b", "icon": "building", "ar": "المبيعات (B2B)", "en": "Sales (B2B)",
        "groups": ({"fields": ("b2b_auto_leads", "b2b_reminder_email", "b2b_whatsapp_daily_limit")},),
    },
    {
        "key": "b2c", "icon": "map-pin", "ar": "المبيعات (B2C) والزيارات", "en": "Sales (B2C) and visits",
        "note": (
            "الـSales الميداني بيضغط «وصلت» وهو عند الشركة و«خلصت» وهو ماشي، والموبايل بيدّي مكانه مرة واحدة مع كل ضغطة. الزيارة مابتتعتمدش لوحدها: المانجر بيعتمدها.",
            "A field Sales person presses «I arrived» at the company and «I am done» on leaving; the phone gives its place once at each press. A visit is never verified by itself: the manager verifies it.",
        ),
        "groups": ({"fields": ("b2c_visit_target", "b2c_work_days", "b2c_visit_radius_m", "b2c_gps_accuracy_m")},),
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
                "whatsapp_api_version", "webhook_shared_secret", "whatsapp_waba_id",
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
        ),
    },
    {
        "key": "usage", "icon": "chart", "ar": "متابعة الاستهلاك", "en": "Usage and bills",
        "note": (
            "اللوحة اللي تحت في القايمة بتقرا فاتورة الشهر من Bunny وNeon وRender بالمفاتيح دي، للأدمن بس. المفاتيح بتتقري بس عشان الأرقام، ومابتظهرش لحد.",
            "The panel at the foot of the menu reads the month's bill from Bunny, Neon and Render with these keys, for the admin only. They are only used to read the numbers and are never shown.",
        ),
        "groups": (
            {"ar": "Bunny.net", "en": "Bunny.net", "fields": ("bunny_api_key",)},
            {"ar": "Neon", "en": "Neon", "fields": ("neon_api_key", "neon_org_id")},
            {"ar": "Render", "en": "Render", "fields": ("render_api_key",)},
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
            "المساعد (الزرار اللي فوق جنب التنبيهات) بيرد من دليل الخطوات في كل الأحوال. لو فتحت ده ومفتاح Claude موجود، بيبعت سؤال الموظف ودليل دوره بس لـ Claude عشان يفهم السؤال ويرتّب الرد. مابيبعتش أي حاجة من الشغل. وكلام الموظف نفسه بيتبعت بعد ما الإيميلات والأرقام والمفاتيح وأسماء العملاء المعروفة بتتشال منه (اسم العميل بيتحوّل لكوده)، فنبّه الموظفين ما يكتبوش بيانات عملاء في المساعد.",
            "The assistant (the button in the top bar) always answers from the step guides. When this is on and a Claude key is saved, it sends the person's question and the guides of their role to Claude, which understands the question and words the reply. Nothing from the work is sent. What a person types is cleaned first (e-mails, numbers, keys and known clients' names are taken out; a client's name becomes their code), so tell staff not to type client details into the assistant.",
        ),
    },
    "chat_translate_enabled": {
        "label": ("زرار «ترجم» تحت رسايل العملاء في الشات", "The «Translate» button under clients' messages in the chat"),
        "hint": (
            "الأدمن والأوبريشن والـSales بيشوفوا «ترجم» تحت أي رسالة من العميل مكتوبة بلغة غير العربي، ولما يضغطوا الترجمة العربي بتظهر تحتها. كلام الرسالة بيتبعت لـ Claude عشان يترجمه، والترجمة بتتحفظ على الرسالة فمابتتطلبش تاني. مابتتبعتش للعميل. محتاج مفتاح Claude محفوظ.",
            "The admin, the operation and Sales get «Translate» under any client message that is not in Arabic; pressing it shows the Arabic under the words. The message's words are sent to Claude to translate, and the translation is kept on the message so it is not asked for twice. It is never sent to the client. It needs a Claude key saved.",
        ),
    },
    "ai_translate_enabled": {
        "label": ("زرار «ترجمها بالـAI» للتيم ليدر", "The «Translate it with the AI» button for the team leader"),
        "hint": (
            "التيم ليدر بيشوف على التاسك اللي معاه اختيارين: يبعتها لمترجم، أو يضغط «ترجمها بالـAI». ملفات التاسك الأصلية بتتبعت لـ Claude ويرجع ملف Word بالترجمة، والتاسك بتروح للمراجعة عند الليدر نفسه: يراجعها ويرفع النسخة اللي ظبطها لو عدّل، وبعدين «تمت المراجعة» زي أي تاسك. محدش بيتحسب له كلمات عليها. محتاج مفتاح Claude محفوظ.",
            "On a task he holds the team leader gets two choices: send it to a translator, or press «Translate it with the AI». The task's source files are sent to Claude and a Word file with the translation comes back; the task goes to the leader's own review, where he uploads his corrected version if he changed anything and finishes the review as with any task. Nobody is paid words for it. It needs a Claude key saved.",
        ),
    },
    "b2b_auto_leads": {
        "label": ("الشركة اللي تكلّم Sales لأول مرة تتضاف لشيته لوحدها", "A company that writes to a Sales person first is added to their sheet"),
        "hint": (
            "لو شركة مش في أي شيت بعتت على رقم Sales أو إيميله، بتتضاف صف في شيت «شركات كلّمتنا» بتاعه ومكتوب عليها إنها ردّت. الرسايل الآلية (no-reply) مابتتضافش، وخط الشركة مابيتأثرش.",
            "A company on no sheet that writes to a Sales person's own number or address becomes a row on their «Companies that wrote to us» sheet, marked as having answered. Automatic senders (no-reply) are skipped; the company line is not affected.",
        ),
    },
    "b2b_reminder_email": {
        "label": ("ابعت تذكير المتابعات اليومي بالإيميل كمان", "Also e-mail the daily follow-up reminder"),
        "hint": (
            "بيروح على الإيميل المكتوب في حساب الـSales (من صفحة الموظف)، مش على عنوانه على ميل الشركة. اللي مالوش إيميل مابيوصلوش غير التنبيه جوه السيستم.",
            "It goes to the e-mail on the Sales person's account (the employee page), not their company-mailbox address. Somebody with none gets the in-app notice only.",
        ),
    },
    "b2b_whatsapp_daily_limit": {
        "label": ("أقصى رسايل تعارف واتساب في اليوم لكل رقم", "Most WhatsApp opening messages a day from each number"),
        "hint": (
            "زرار واتساب في الشيت بيبعت رسالة التعارف لحد العدد ده من كل رقم في اليوم (يوم مصر)، وبعده بيقول «خلص عدد النهارده». "
            "ميتا قيّدت الحساب 30 يوم بسبب السبام لما اتبعت حوالي 500 في 3 أيام، ووعدناهم بـ50 في اليوم من كل رقم. "
            "0 = الزرار مايبعتش رسالة تعارف خالص. الشات مع شركة كلّمتنا في آخر 24 ساعة مابيتحسبش.",
            "The WhatsApp button on a sheet sends the opening message up to this many times a day from each number (Cairo's day), "
            "then says today's count is used up. Meta restricted the account for 30 days for spam after about 500 in three days, "
            "and we promised them 50 a day from each number. 0 = the button sends no opening message at all. Opening the chat of a "
            "company that wrote to us within 24 hours does not count.",
        ),
    },
    "b2c_visit_target": {
        "label": ("تارجت الزيارات المعتمدة في الشهر لكل Sales ميداني", "Verified visits a month for each field Sales person"),
        "hint": ("بيقل بنسبة أيام الإجازات المعتمدة في الشهر.", "It is lowered in proportion to the month's approved leave days."),
    },
    "b2c_work_days": {"label": ("أيام الشغل في الشهر", "Working days a month")},
    "b2c_visit_radius_m": {
        "label": ("أقصى بُعد عن الشركة وقت «وصلت» (متر)", "Furthest from the company at «I arrived» (metres)"),
        "hint": (
            "أبعد من كده الزيارة بتتعلّم «بعيد عن الشركة» والمانجر بيقرر. الشركة اللي مالهاش لوكيشن بتاخد مكان أول زيارة معتمدة ليها.",
            "Further than this the visit is marked «Away from the company» and the manager decides. A company with no location takes the place of its first verified visit.",
        ),
    },
    "b2c_gps_accuracy_m": {
        "label": ("أقل دقة مقبولة للوكيشن (متر)", "Least precise location accepted (metres)"),
        "hint": ("لوكيشن دقته أسوأ من كده بيتعلّم «مش دقيق» ويروح للمراجعة.", "A location less precise than this is marked «not precise» and goes to review."),
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
    "whatsapp_waba_id": {
        "label": ("WhatsApp Business Account ID", "WhatsApp Business Account ID"),
        "hint": (
            "بيظهر في WhatsApp Manager فوق جنب اسم الحساب. محتاجينه عشان نجيب قايمة أرقام الحساب تحت.",
            "Shown in WhatsApp Manager next to the account's name. Needed to list the account's numbers below.",
        ),
    },
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
    "bunny_api_key": {
        "label": ("مفتاح حساب Bunny (Account API key)", "Bunny account API key"),
        "hint": (
            "من Bunny: Account settings ← API key. ده مفتاح الحساب، مش باسورد الـStorage zone اللي الملفات شغالة بيه.",
            "In Bunny: Account settings, API key. The account's key, not the storage zone password the files use.",
        ),
    },
    "neon_api_key": {
        "label": ("مفتاح Neon API", "Neon API key"),
        "hint": (
            "من Neon: Organization settings ← API keys ← Create. مفتاح المنظمة اللي فيها الداتابيز.",
            "In Neon: Organization settings, API keys, Create. A key of the organization the database is in.",
        ),
    },
    "neon_org_id": {
        "label": ("Organization ID بتاع Neon", "Neon organization ID"),
        "hint": (
            "اللي في لينك الكونسول بعد /app/، بيبدأ بـ org-.",
            "The part of the console's address after /app/, starting with org-.",
        ),
    },
    "render_api_key": {
        "label": ("مفتاح Render API", "Render API key"),
        "hint": (
            "من Render: Account settings ← API keys ← Create API key. Render مابيدّيش الفاتورة من الـAPI، فاللوحة بتحسبها تقريبًا من الخدمات والباندويدث.",
            "In Render: Account settings, API keys, Create API key. Render gives no bill through its API, so the panel works it out roughly from the services and the bandwidth.",
        ),
    },
    "sales_mail_footer": {
        "label": ("الشريط اللي تحت (المواعيد والعنوان)", "Bottom band (hours, address)"),
        "hint": ("سطر لكل معلومة. فاضي = الشريط مش هيظهر.", "One line each. Blank = no band."),
    },
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
            "waba_saved": bool((conf.whatsapp_waba_id or "").strip()),
        },
        "wa_numbers": walines.describe(conf),
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


@endpoint("GET")
@api_role_required(Role.ADMIN)
def usage(request):
    """The usage panel at the foot of the menu: this month's bill at Bunny, Neon and Render (``usage.py``). ``?fresh=1`` asks
    the hosts again instead of the ten-minute copy. No key is in the answer."""
    return JsonResponse(usage_report.report(force=request.GET.get("fresh") == "1"))


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


# ---------------------------------------------------------------------------
# The account's WhatsApp numbers: list them, send a code, link one (``walines``)
# ---------------------------------------------------------------------------

def _line_failure(exc, conf):
    """A refusal - ours or Meta's - as the page shows it, cleaned of any stored secret (the PIN among them)."""
    return JsonResponse(_clean({
        "ok": False,
        "error_ar": getattr(exc, "message_ar", ""),
        "error_en": getattr(exc, "message_en", ""),
        "code": getattr(exc, "code", None),
    }, conf), status=400)


def _line_body(request):
    try:
        body = _object(request)
    except BadBody:
        return None
    return {key: body.get(key) for key in ("id", "code", "pin", "method") if isinstance(body.get(key), str)}


@endpoint("POST")
@api_role_required(Role.ADMIN)
def wa_numbers_refresh(request):
    """Ask Meta for the account's numbers now. A failure keeps the list there was."""
    from . import whatsapp as wa

    conf = AppSettings.load()
    try:
        walines.refresh(conf)
    except wa.WhatsAppError as exc:
        return _line_failure(exc, conf)
    return JsonResponse({"ok": True, "numbers": walines.describe(conf)})


@endpoint("POST")
@api_role_required(Role.ADMIN)
def wa_send_code(request):
    """``{"id": "<phone number id>", "method": "SMS" | "VOICE"}``: Meta texts (or calls) the number its code."""
    from . import whatsapp as wa

    body = _line_body(request)
    if body is None:
        return _error(400, "bad_body")
    conf = AppSettings.load()
    try:
        walines.send_code(body.get("id"), body.get("method") or "SMS")
    except (walines.LineError, wa.WhatsAppError) as exc:
        return _line_failure(exc, conf)
    services.log(request.user, "whatsapp.send_code", (body.get("id") or "")[:40])
    return JsonResponse({"ok": True})


@endpoint("POST")
@api_role_required(Role.ADMIN)
def wa_link(request):
    """``{"id", "code", "pin"?}``: verify the number with the code it was sent and register it, in one step.

    The PIN is only for a number that already has one; without it the system's own is used (``walines.link``). Neither the
    code nor the PIN is logged or answered.
    """
    from . import whatsapp as wa

    body = _line_body(request)
    if body is None:
        return _error(400, "bad_body")
    conf = AppSettings.load()
    try:
        row = walines.link(body.get("id"), body.get("code") or "", body.get("pin") or "")
    except (walines.LineError, wa.WhatsAppError) as exc:
        services.log(request.user, "whatsapp.link_failed", (body.get("id") or "")[:40], scrub(getattr(exc, "message_en", ""), conf)[:200])
        return _line_failure(exc, conf)
    services.log(request.user, "whatsapp.link", row.get("id", ""), row.get("number", ""))
    return JsonResponse({"ok": True, "number": row, "numbers": walines.describe()})


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
