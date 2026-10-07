"""The step-by-step guides the help assistant answers from (``helpbot.py``).

Each guide says how to do one thing *in this system*: which menu line to open, which button to press, in what order. The
assistant never answers from general knowledge about translation offices - only from these, so what it says is what the screen
has.

Rules for writing one:

* **Name every button and menu line exactly as the screen draws it, between guillemets** (``«احفظ»``). A test reads every
  name between guillemets and looks it up in the front end's source (and in the forms and settings texts): rename a button and
  the guide that names it fails the gate until it is updated. A name that is not a label (a role, a word) goes without them.
* **A guide is for the roles that can do it.** ``roles`` is who is shown the guide (the owner is ``admin``); ``cap`` adds the
  people who hold a capability of another role (an attendance manager who is not HR). A role that is not listed is never told
  how, and never sees the guide in the list the assistant is given.
* **Nothing here names a client.** A guide talks about codes, never about a person's name, number or address, and says so when
  a role may not know who the client is.
* Both languages, step for step (a test holds the two lists to the same length). Egyptian Arabic, short imperative steps.
"""

from dataclasses import dataclass

from .models import Role

#: Every role but the owner, and every role.
STAFF = (
    Role.OPERATION, Role.TEAM_LEAD, Role.TRANSLATOR, Role.HR, Role.REVIEWER, Role.ACCOUNTING, Role.SALES,
)
EVERYONE = (Role.ADMIN, *STAFF, Role.SUPPORT)
#: Who has the chats: everybody on the company's rules and technical support.
CHAT = (*STAFF, Role.SUPPORT)
#: The people who work the client mailbox and chat.
CLIENT_DESK = (Role.OPERATION, Role.SALES, Role.ADMIN)


@dataclass(frozen=True)
class Guide:
    id: str
    #: ``(arabic, english)``.
    title: tuple
    roles: tuple
    #: The page the guide starts on, under ``/app`` ("" when it is not one page): the assistant offers a button to it.
    path: str
    #: ``(arabic words, english words)``: how people ask for this, separated by commas.
    keywords: tuple
    #: ``(arabic steps, english steps)``: two lists of the same length.
    steps: tuple
    #: ``(arabic, english)``, or ``("", "")``.
    note: tuple = ("", "")
    #: The ``User`` property that also opens the guide to a person of another role.
    cap: str = ""
    #: Offered as a first question: to every role that can read it (``True``), or only to the roles named.
    starter: object = False

    def shown_to(self, user):
        """Is this guide for this person: their role, or a capability they were given."""
        role = Role.ADMIN if user.is_admin_role else user.role
        if role in self.roles:
            return True
        return bool(self.cap) and bool(getattr(user, self.cap, False))

    def starter_for(self, role):
        """Is this one of the first questions offered to a person of this role."""
        return self.starter is True or (isinstance(self.starter, tuple) and role in self.starter)

    def text(self, lang):
        """The guide as one block of words, in one language."""
        index = 0 if lang == "ar" else 1
        lines = [self.title[index]]
        lines += [f"{number}. {step}" for number, step in enumerate(self.steps[index], start=1)]
        if self.note[index]:
            lines.append(self.note[index])
        return "\n".join(lines)


def _guide(id, roles, path, title, keywords, ar, en, note=("", ""), cap="", starter=False):
    return Guide(
        id=id, roles=tuple(roles), path=path, title=title, keywords=keywords,
        steps=(tuple(ar), tuple(en)), note=note, cap=cap, starter=starter,
    )


GUIDES = (
    # ------------------------------------------------------------------------------------------------------------------
    # Everybody: finding things, attendance, leave, the account, chats, notifications.
    # ------------------------------------------------------------------------------------------------------------------
    _guide(
        "menu-where", EVERYONE, "",
        ("إزاي ألاقي صفحة في السيستم", "How do I find a page"),
        (
            "فين الصفحة، ألاقي صفحة، مش لاقي، مش لاقي الصفحة، القايمة، المنيو، القايمة الجانبية، دور على صفحة، بحث في القايمة",
            "where is the page, find a page, cannot find, menu, sidebar, search the menu, look for a page",
        ),
        [
            "القايمة الجانبية فيها صفحاتك مقسّمة أقسام (زي «الشغل» و«حسابي»). اضغط على اسم القسم يفتح أو يتقفل.",
            "على الموبايل القايمة بتتفتح من زرار القايمة اللي في الشريط اللي فوق.",
            "فوق القايمة خانة بحث: اكتب اسم الصفحة واختارها من النتايج، أو اضغط Ctrl+K من أي مكان في السيستم.",
            "لو صفحة مش ظاهرة في القايمة يبقى مش من صلاحيات دورك.",
        ],
        [
            "The side menu holds your pages in sections (such as «Work» and «My account»). Press a section's name to open or fold it.",
            "On a phone the menu opens from the menu button in the bar at the top.",
            "Above the menu there is a search box: type the page's name and pick it, or press Ctrl+K anywhere in the system.",
            "A page that is not in your menu is not part of your role.",
        ],
        starter=(Role.SUPPORT,),
    ),
    _guide(
        "attendance-checkin", STAFF, "/attendance",
        ("إزاي أسجل حضور", "How do I check in"),
        (
            "حضور، سجل حضور، تسجيل الحضور، اسجل حضوري، بصمة، ابدأ الشغل، دخول الشغل، شاشة الحضور، متأخر، تأخير، سماح",
            "check in, clock in, attendance, punch in, start my shift, late, grace",
        ),
        [
            "أول ما تفتح السيستم في ميعاد شيفتك بتظهر لوحدها شاشة «سجّل حضورك» ومابتتقفلش غير بالتسجيل.",
            "اضغط «تسجيل حضور». لو الشركة مفعّلة فحص الموقع، اسمح للمتصفح يعرف موقعك.",
            "فيه سماح قصير (10 دقايق)؛ بعده التأخير كله بيتحسب وبيتحوّل للـHR وانت بتتبلّغ.",
            "تقدر برضه تسجل من صفحة «حضوري» اللي في قسم «حسابي».",
        ],
        [
            "When you open the system at your shift's time, the screen «سجّل حضورك» appears by itself and stays until you check in.",
            "Press «Check in». If the company checks location, let the browser share where you are.",
            "There is a short grace (10 minutes); after it the whole delay counts, goes to HR, and you are told.",
            "You can also check in from «My attendance» in the «My account» section.",
        ],
        starter=True,
    ),
    _guide(
        "attendance-checkout", STAFF, "/attendance",
        ("إزاي أسجل انصراف", "How do I check out"),
        (
            "انصراف، سجل انصراف، تسجيل الانصراف، خلصت شغل، امشي، نهاية الشيفت، نسيت الانصراف، نسيت أسجل انصراف",
            "check out, clock out, leave work, end of shift, forgot to check out",
        ),
        [
            "افتح «حضوري» من قسم «حسابي».",
            "لما شيفتك يخلص اضغط «تسجيل انصراف».",
            "لو نسيت تسجل انصراف في المهلة اللي بعد نهاية الشيفت، اليوم كله مش بيتحسب.",
        ],
        [
            "Open «My attendance» in the «My account» section.",
            "When your shift ends press «Check out».",
            "If you forget to check out within the window after the shift, the whole day does not count.",
        ],
        starter=True,
    ),
    _guide(
        "attendance-break", STAFF, "/attendance",
        ("إزاي أسجل بريك", "How do I record a break"),
        ("بريك، استراحة، فسحة، غدا، ابدأ بريك، انهي البريك", "break, rest, lunch, start break, end break"),
        [
            "افتح «حضوري» من قسم «حسابي».",
            "لما تبدأ بريك اضغط «ابدأ بريك».",
            "لما ترجع للشغل اضغط «إنهاء البريك».",
        ],
        [
            "Open «My attendance» in the «My account» section.",
            "When your break starts press «Start break».",
            "When you are back press «End break».",
        ],
    ),
    _guide(
        "attendance-extra", STAFF, "/attendance",
        ("إزاي أحسّب أوفرتايم (اكسترا تايم)", "How do I count overtime (extra time)"),
        (
            "اكسترا تايم، أوفرتايم، شغل زيادة، ساعات إضافية، كمل شغل بعد الشيفت، حساب الأوفرتايم",
            "extra time, overtime, extra hours, work after my shift",
        ),
        [
            "لما شيفتك يخلص وعايز تكمّل شغل اضغط «اكسترا تايم» (بتظهر في شاشة نهاية الشيفت وفي «حضوري»).",
            "لما تخلص سجّل «تسجيل انصراف».",
            "الأوفرتايم بيتحسب من وقت ما تضغط الزرار بس، والـHR هي اللي بتعتمده.",
        ],
        [
            "When your shift ends and you want to carry on, press «Extra time» (it is on the end-of-shift screen and in «My attendance»).",
            "When you finish press «Check out».",
            "Overtime counts only from the moment you press the button, and HR approves it.",
        ],
    ),
    _guide(
        "leave-ask", STAFF, "/leave",
        ("إزاي أطلب إجازة", "How do I ask for leave"),
        (
            "إجازة، اطلب إجازة، عايز إجازة، أجازة، إذن، رصيد الإجازات، اسحب طلب إجازة، طلب إجازة",
            "leave, ask for leave, time off, vacation, holiday, leave balance, withdraw a leave request",
        ),
        [
            "من قسم «حسابي» افتح «إجازاتي».",
            "اضغط «اطلب إجازة» واختار النوع والتواريخ واكتب السبب.",
            "اضغط «ابعت الطلب». الطلب بيروح للموارد البشرية (أو لمديرك الأول وبعدها HR لو الشركة مظبطاه كده).",
            "تتابعه تحت «طلباتي»، وتقدر «اسحب» الطلب طول ما هو مستني.",
        ],
        [
            "In the «My account» section open «My leave».",
            "Press «Ask for leave», pick the kind and the dates and write the reason.",
            "Press «Send». The request goes to HR (or to your manager first and then HR, if the company set it so).",
            "You follow it under «My requests», and you can «Withdraw» it while it is waiting.",
        ],
        starter=True,
    ),
    _guide(
        "password-change", EVERYONE, "",
        ("إزاي أغيّر كلمة السر", "How do I change my password"),
        (
            "كلمة السر، باسورد، غيّر الباسورد، غير كلمة السر، نسيت الباسورد، تغيير الباسورد",
            "password, change my password, change password, forgot password",
        ),
        [
            "اضغط على اسمك أو صورتك في الشريط اللي فوق.",
            "اضغط «غيّر كلمة السر».",
            "اكتب «كلمة السر الحالية» و«كلمة السر الجديدة» وبعدها «الجديدة تاني».",
            "اضغط «احفظ كلمة السر».",
        ],
        [
            "Press your name or picture in the bar at the top.",
            "Press «Change password».",
            "Type «Current password», then «New password», then «New password again».",
            "Press «Save password».",
        ],
        note=(
            "ماتكتبش كلمة السر هنا في الشات ده. ولو غلطت في الحالية مرات كتير الباب بيتقفل 15 دقيقة. لو نسيتها خالص كلّم الأدمن.",
            "Never type your password into this chat. Too many wrong tries shut the door for 15 minutes. If you have forgotten it, ask the admin.",
        ),
    ),
    _guide(
        "profile-picture", EVERYONE, "",
        ("إزاي أحط صورة لحسابي", "How do I set my profile picture"),
        (
            "صورة، صورة البروفايل، صورتي، حط صورة، غيّر الصورة، امسح الصورة، بروفايل",
            "picture, profile picture, my photo, change my picture, remove my picture, profile",
        ),
        [
            "اضغط على اسمك أو صورتك في الشريط اللي فوق.",
            "اضغط «ارفع صورة» (أو «غيّر الصورة» لو عندك صورة) واختار الصورة. بتتقص مربعة لوحدها.",
            "لو عايز تشيلها اضغط «احذف الصورة».",
        ],
        [
            "Press your name or picture in the bar at the top.",
            "Press «Upload a picture» (or «Change picture» if you have one) and choose it. It is cropped to a square for you.",
            "To take it off press «Remove picture».",
        ],
    ),
    _guide(
        "language-theme", EVERYONE, "",
        ("إزاي أغيّر اللغة أو الوضع الليلي", "How do I change the language or dark mode"),
        (
            "لغة، اللغة، انجليزي، عربي، وضع ليلي، دارك مود، الوضع الداكن، غيّر اللغة، ثيم",
            "language, english, arabic, dark mode, night mode, theme, switch language",
        ),
        [
            "في الشريط اللي فوق اضغط «عربي» أو «EN» عشان تغيّر لغة السيستم.",
            "زرار القمر/الشمس جنبهم بيبدّل بين الوضع الفاتح والليلي.",
        ],
        [
            "In the bar at the top press «عربي» or «EN» to change the system's language.",
            "The moon/sun button beside them switches between light and dark mode.",
        ],
    ),
    _guide(
        "notifications", EVERYONE, "/notifications",
        ("فين التنبيهات وإزاي أقراها", "Where are my notifications"),
        (
            "تنبيهات، التنبيهات، الجرس، إشعارات، علّم مقروء، علم الكل مقروء، تنبيه جديد",
            "notifications, the bell, alerts, mark as read, mark all read",
        ),
        [
            "الجرس في الشريط اللي فوق عليه رقم التنبيهات اللي لسه ماتقراتش. اضغط عليه (أو افتح «التنبيهات» من قسم «حسابي»).",
            "اضغط «افتح» على أي تنبيه يوديك للصفحة المعنية.",
            "زرار «مقروء» جمب أي تنبيه لسه ماتقراش بيعلّمه هو بس. «علّم الكل مقروء» بيصفّر العداد. «المزيد» بيجيب الأقدم.",
        ],
        [
            "The bell in the bar at the top shows how many notifications are unread. Press it (or open «Notifications» in the «My account» section).",
            "Press «Open» on a notification to go to the page it is about.",
            "The «Read» button beside an unread notification marks just that one. «Mark all read» clears the counter. «Load more» brings the older ones.",
        ],
        starter=(Role.SUPPORT,),
    ),
    _guide(
        "chat-send", CHAT, "/chats",
        ("إزاي أبعت رسالة في الشات", "How do I send a chat message"),
        (
            "شات، الشات، ابعت رسالة، كلّم زميل، رسالة لزميل، محادثة، كلم التيم ليدر، ابعت لزميل",
            "chat, send a message, message a colleague, conversation, talk to the team leader",
        ),
        [
            "من قسم «الشغل» افتح «الشات».",
            "اختار التبويب: «الجروبات» أو «الزمايل»، والأوبريشن والـSales عندهم كمان «العملاء».",
            "دوّر على الاسم أو الكود في خانة البحث واضغط على المحادثة.",
            "اكتب في «اكتب رسالة...» واضغط «إرسال».",
        ],
        [
            "In the «Work» section open «Chats».",
            "Pick the tab: «Groups» or «Colleagues»; operation and Sales also have «Clients».",
            "Search the name or code in the search box and press the conversation.",
            "Write in «Write a message...» and press «Send».",
        ],
        starter=(Role.SUPPORT,),
    ),
    _guide(
        "chat-attach", CHAT, "/chats",
        ("إزاي أبعت ملف في الشات", "How do I send a file in a chat"),
        (
            "ملف، ابعت ملف، ارفع ملف في الشات، مرفق، مرفقات، صورة في الشات، ملفات",
            "file, send a file, attach, attachment, upload in a chat, files",
        ),
        [
            "افتح المحادثة من «الشات».",
            "اضغط «إرفاق ملفات» واختار الملف (أو أكتر من ملف).",
            "اضغط «إرسال». في محادثة العميل الملف بيوصل للعميل نفسه، فراجعه قبل ما تبعت.",
        ],
        [
            "Open the conversation from «Chats».",
            "Press «Attach files» and choose the file (or several).",
            "Press «Send». In a client's conversation the file reaches the client, so check it before sending.",
        ],
    ),
    _guide(
        "chat-voice", CHAT, "/chats",
        ("إزاي أبعت رسالة صوتية", "How do I send a voice note"),
        (
            "رسالة صوتية، فويس، صوت، سجل صوت، ريكورد، ميكروفون",
            "voice note, voice message, record audio, microphone",
        ),
        [
            "افتح المحادثة من «الشات».",
            "اضغط «سجّل رسالة صوتية» واسمح للمتصفح يستخدم الميكروفون لو سأل.",
            "اتكلم، وبعدين اضغط «وقّف».",
            "اسمعها («اسمعها قبل ما تبعتها») وبعدين اضغط «ابعت»، أو «إلغاء التسجيل» لو مش عايزها.",
        ],
        [
            "Open the conversation from «Chats».",
            "Press «Record a voice note» and let the browser use the microphone if it asks.",
            "Speak, then press «Stop».",
            "Listen to it («Listen before sending») and press «Send», or «Cancel the recording» if you do not want it.",
        ],
    ),
    _guide(
        "chat-emoji", CHAT, "/chats",
        ("إزاي أحط إيموجي في رسالة", "How do I put an emoji in a message"),
        (
            "ايموجي، إيموجي، سمايل، وش ضاحك، قلب، رموز، استيكر، حط ايموجي، ازاي ابعت ايموجي",
            "emoji, smiley, smile, heart, symbols, put an emoji, send an emoji",
        ),
        [
            "افتح المحادثة من «الشات».",
            "اضغط زرار «إيموجي» اللي جنب خانة الكتابة.",
            "اختار المجموعة من فوق (اللي استخدمتهم، أو وشوش، أو إيدين، أو قلوب، أو شغل) واضغط على الإيموجي. بيتحط عند المؤشر وتقدر تحط أكتر من واحد.",
            "اضغط «إرسال».",
        ],
        [
            "Open the conversation from «Chats».",
            "Press the «Emoji» button beside the box you write in.",
            "Pick a group at the top (recent, faces, hands, hearts or work) and press an emoji. It goes in at the cursor and you can add several.",
            "Press «Send».",
        ],
    ),
    _guide(
        "chat-call", CHAT, "/chats",
        ("إزاي أكلم زميل صوت أو فيديو", "How do I call a colleague"),
        (
            "مكالمة، اتصل بزميل، كلم زميل، مكالمة فيديو، مكالمة صوتية، كول، فيديو كول",
            "call, call a colleague, voice call, video call, ring",
        ),
        [
            "من «الشات» افتح تبويب «الزمايل» واضغط على الزميل.",
            "في أعلى المحادثة اضغط «مكالمة صوتية» أو «مكالمة فيديو».",
            "اسمح للمتصفح بالميكروفون (والكاميرا للفيديو). الزميل بيرن عليه في أي صفحة هو فيها.",
        ],
        [
            "In «Chats» open the «Colleagues» tab and press the colleague.",
            "At the top of the conversation press «Voice call» or «Video call».",
            "Let the browser use the microphone (and the camera for video). Your colleague is rung on whatever page they are on.",
        ],
    ),
    _guide(
        "chat-forward", CHAT, "/chats",
        ("إزاي أحوّل رسايل لشات تاني", "How do I forward messages to another chat"),
        (
            "حوّل رسالة، تحويل رسايل، فورورد، ابعت الرسالة لحد تاني، انقل الرسالة",
            "forward, forward messages, send this message on, move the message",
        ),
        [
            "افتح المحادثة من «الشات» واضغط «تحويل رسايل».",
            "علّم الرسايل اللي عايز تحوّلها واضغط «تحويل لشات».",
            "دوّر على الزميل أو الجروب واختاره (الأوبريشن بيقدر كمان يختار كود عميل: الرسالة وقتها بتوصل العميل على واتساب).",
            "لو عايز اكتب «كلمة مع التحويل (اختياري)» وبعدها اضغط «ابعت».",
            "من شات عميل: الملفات بتروح لأي زميل أو جروب، وكلام العميل بيروح للأوبريشن والأدمن بس. الأدمن بس بيقدر يبعت كلام العميل لأي حد، ومن غير اسم العميل ولا رقمه لمن مالوش حق يعرفهم.",
        ],
        [
            "Open the conversation from «Chats» and press «Forward».",
            "Tick the messages you want to forward and press «Forward».",
            "Search a colleague or a group and pick it (operation can also pick a client code: the message then reaches the client on WhatsApp).",
            "If you like add «Add a note (optional)», then press «Send».",
            "From a client's chat the files go to any colleague or group, and the client's words go to operation and admin only. Only the admin can send a client's words to anybody, without the client's name or number for those who may not know them.",
        ],
    ),
    _guide(
        "chat-group", (Role.OPERATION, Role.TEAM_LEAD, Role.ADMIN), "/chats",
        ("إزاي أعمل جروب شغل", "How do I open a work group"),
        (
            "جروب، اعمل جروب، جروب شغل، جروب جديد، ضيف مترجم في جروب، جروب مع المترجم",
            "group, make a group, work group, new group, add a translator to a group",
        ),
        [
            "من «الشات» افتح تبويب «الجروبات».",
            "اضغط «جروب شغل».",
            "اكتب «اسم الجروب» (لو سبته فاضي بيتسمى بالمترجم والليدر) واختار «الأعضاء».",
            "اضغط «اعمل الجروب».",
        ],
        [
            "In «Chats» open the «Groups» tab.",
            "Press «Work group».",
            "Type the «Group name» (left empty it is named for the translator and the leader) and pick the «Members».",
            "Press «Create».",
        ],
        note=(
            "ده جروب داخلي: مفيش حاجة فيه بتوصل العميل.",
            "This is an internal group: nothing in it reaches a client.",
        ),
    ),
    _guide(
        "chat-mention", (Role.ADMIN, *STAFF), "/chats",
        ("إزاي أنبّه زميل باسمه (منشن)", "How do I mention a colleague by name"),
        (
            "منشن، منشن لحد، نادي على حد باسمه، نبّه حد باسمه، @، تاج، اشارة",
            "mention, tag, @, mention someone, ping someone in the group, notify a colleague in a group",
        ),
        [
            "افتح الجروب من «الشات» (تبويب «الجروبات»).",
            "في صندوق الكتابة اكتب @ أو اضغط زرار «منشن لحد في الجروب»، وهتظهر قايمة بالناس اللي في الجروب.",
            "اكتب أول حروف الاسم عشان تضيّق القايمة، واختار الاسم بالأسهم وبعدها Enter أو بالضغط عليه.",
            "كمّل رسالتك وابعتها: الشخص ده بيوصله إشعار بصوت باسمك، والرسالة بتتلوّن عنده.",
        ],
        [
            "Open the group from «Chats» (the «Groups» tab).",
            "In the message box type @ or press the «Mention someone in the group» button, and a list of the people in the group appears.",
            "Type the first letters of the name to narrow the list, and pick the name with the arrows and Enter, or by tapping it.",
            "Finish your message and send it: that person gets a notification with a sound in your name, and the message stands out for them.",
        ],
        note=(
            "المنشن في الجروبات الداخلية بس. جروب فيه عميل مفيهوش منشن، لأن كلامه بيتبعت للعميل زي ما هو.",
            "Mentions work in internal groups only. A group that reaches a client has none, because what is typed there goes to the client as it is.",
        ),
    ),
    _guide(
        "contact-support", (Role.ADMIN, *STAFF), "/chats",
        ("إزاي أتواصل مع الدعم الفني", "How do I contact technical support"),
        (
            "الدعم الفني، كلم الدعم، تواصل مع الدعم، عندي مشكلة، مشكلة في السيستم، السيستم مش شغال، مش شغال، بايظ، مساعدة، عطل",
            "technical support, contact support, talk to support, I have a problem, the system is not working, broken, help",
        ),
        [
            "اضغط «المساعد» في الشريط اللي فوق وبعدها «تواصل مع الدعم الفني». بتتفتح محادثة معاه.",
            "اكتب مشكلتك (وقول كنت بتعمل إيه ولقيت إيه) واضغط «إرسال».",
            "أو من «الشات» افتح تبويب «الزمايل» وادوّر على الدعم الفني؛ عليه شارة «دعم فني».",
        ],
        [
            "Press «Assistant» in the bar at the top and then «Contact technical support». A chat with them opens.",
            "Write your problem (what you were doing and what you found) and press «Send».",
            "Or open «Chats», the «Colleagues» tab, and look for technical support; they carry a «Technical support» tag.",
        ],
    ),
    _guide(
        "support-tasks", (Role.SUPPORT,), "/tasks",
        ("إزاي أتابع التاسكات وأتأكد إن كله ماشي", "How do I follow the tasks and check everything is running"),
        (
            "التاسكات، متابعة التاسكات، اتأكد إن كله ماشي، تاسك متأخرة، تاسكات واقفة، حالة التاسك، شوف التاسكات، الدعم الفني",
            "tasks, follow the tasks, check everything is running, late tasks, stuck tasks, task state, look at the tasks, technical support",
        ),
        [
            "من قسم «الشغل» افتح «التاسكات».",
            "الأرقام اللي فوق والتبويبات بيقولوا فين التاسكات؛ والمتأخرة بتبان في حالة الديدلاين.",
            "اضغط «افتح» على تاسك تشوف مين عليها (الأوبريشن والتيم ليدر والمترجم) وحالتها وديدلاينها وسجل التوزيع.",
            "«حالة الفرق» بتوريك مين فاضي ومين مشغول.",
        ],
        [
            "In the «Work» section open «Tasks».",
            "The numbers at the top and the tabs tell you where the tasks are; late ones show in the deadline's state.",
            "Press «Open» on a task to see who has it (operation, team leader, translator), its state, its deadlines and the hand-off history.",
            "«Team status» shows who is free and who is busy.",
        ],
        note=(
            "انت بتتفرج بس: ماتقدرش تعدّل ولا تسلّم ولا تلغي، ومش بتشوف ملفات العميل ولا رسايله ولا اسمه (بتشتغل بالكود).",
            "You only look: you cannot change, deliver or cancel, and you do not see the client's files, messages or name (you work by code).",
        ),
        starter=True,
    ),
    _guide(
        "performance-board", STAFF, "/hr/performance",
        ("فين لوحة الأداء وترتيب المترجمين", "Where is the performance board"),
        (
            "لوحة الأداء، الأداء، ترتيب المترجمين، مين الأول، لوحة الشرف، الأكتر إنتاجية، إنتاجية",
            "performance board, performance, ranking, top translators, leaderboard, productivity",
        ),
        [
            "من قسم «حسابي» افتح «الأداء».",
            "هتلاقي ترتيب المترجمين بالإنتاجية للشهر. اختار الشهر من فوق.",
        ],
        [
            "In the «My account» section open «Performance».",
            "You will find the translators ranked by productivity for the month. Pick the month at the top.",
        ],
    ),
    # ------------------------------------------------------------------------------------------------------------------
    # The translator.
    # ------------------------------------------------------------------------------------------------------------------
    _guide(
        "tr-accept", (Role.TRANSLATOR,), "/translator",
        ("إزاي أستلم تاسك اتبعتتلي", "How do I accept a task I was sent"),
        (
            "استلام تاسك، استلمت، تاسك جديدة ليا، العداد، عرض تاسك، ارفض تاسك، رفض تاسك، تاسك اتبعتتلي، وافق على التاسك",
            "accept a task, accepted, new task for me, the timer, decline a task, task offered to me",
        ),
        [
            "لما تتبعتلك تاسك بتظهر شاشة «تاسك جديدة ليك» وفيها عداد (حوالي دقيقة).",
            "لو عايز تشوف الملفات الأول اضغط «شوف الملفات والتفاصيل الأول». فتح الصفحة مش استلام والعداد لسه شغال.",
            "اضغط «استلمت» قبل ما العداد يخلص.",
            "لو مش هتقدر اضغط «رفض» واكتب السبب (لازم).",
        ],
        [
            "When a task is sent to you the screen «A task is waiting for you» appears with a timer (about a minute).",
            "To see the files first press «See the files and details first». Opening the page is not accepting and the timer keeps running.",
            "Press «Accept» before the timer runs out.",
            "If you cannot take it press «Decline» and write the reason (required).",
        ],
        note=(
            "لو العداد خلص من غير ما ترد بيتخصم من تقييمك.",
            "If the timer runs out with no answer a rating penalty is applied.",
        ),
        starter=True,
    ),
    _guide(
        "tr-work", (Role.TRANSLATOR,), "/translator",
        ("فين شغلي وإزاي أفتح التاسك", "Where is my work and how do I open a task"),
        (
            "شغلي، تاسكاتي، التاسكات الحالية، افتح التاسك، ابدأ تاسك، ابدأ شغل، ابدأ الترجمة، فين التاسك، ملفات العميل، متطلبات العميل، الديدلاين",
            "my work, my tasks, current tasks, open a task, start a task, start translating, client files, requirements, deadline",
        ),
        [
            "من قسم «الشغل» افتح «شغلي».",
            "تحت «التاسكات الحالية» اضغط «افتح التاسك» على التاسك اللي هتشتغل عليه.",
            "في صفحة التاسك نزّل «الملف الأصلي (من العميل)» واقرا «متطلبات العميل» قبل ما تبدأ، وخلّي بالك من الديدلاين اللي فوق.",
            "اشتغل على الملف، ولما تخلص ارفع الترجمة (شوف دليل: إزاي أسلّم الترجمة).",
        ],
        [
            "In the «Work» section open «My work».",
            "Under «Current tasks» press «Open the task» on the one you will work on.",
            "On the task page download the «Original (from the client)» and read the «Client requirements» before you start, and watch the deadline at the top.",
            "Do the work and upload the translation when you finish (see the guide: How do I hand in the translation).",
        ],
        starter=True,
    ),
    _guide(
        "tr-deliver", (Role.TRANSLATOR,), "/translator",
        ("إزاي أسلّم الترجمة (أخلّص التاسك)", "How do I hand in the translation"),
        (
            "سلّم الترجمة، تسليم، خلصت الترجمة، خلصت التاسك، ارفع الترجمة، ارفع ملف الترجمة، خلّص التاسك، ابعت الترجمة",
            "hand in the translation, deliver, finished, finish the task, upload the translation, send the translation",
        ),
        [
            "افتح التاسك من «شغلي».",
            "اضغط «ارفع ملف الترجمة» واختار ملف الترجمة النهائي. بيترفع وبيتبعت في الجروب مع التيم ليدر لوحده.",
            "بعد ما الملف يترفع بتتفتح «خلصت الترجمة»؛ اضغطها.",
            "أكّد بـ«أيوه، خلصت». التيم ليدر بيبدأ مراجعتها.",
        ],
        [
            "Open the task from «My work».",
            "Press «Upload the translation» and choose the final translated file. It is uploaded and posted in the group with your team leader on its own.",
            "Once the file is up «Finished» opens; press it.",
            "Confirm with «Yes, finished». Your team leader starts reviewing it.",
        ],
        note=(
            "«خلصت الترجمة» مابتتفتحش قبل رفع الملف. تقدر كمان تخلّص من الشات: افتح جروب الشغل مع التيم ليدر، اضغط «تحديد ملفات» واختار ملفات الترجمة وبعدها «خلصت التاسك».",
            "«Finished» does not open before the file is uploaded. You can also finish from the chat: open the work group with your team leader, press «Select files», pick the translated files and then «Task done».",
        ),
        starter=True,
    ),
    _guide(
        "tr-extension", (Role.TRANSLATOR,), "/translator",
        ("إزاي أطلب وقت أطول على تاسك", "How do I ask for more time on a task"),
        (
            "وقت أطول، وقت إضافي، تمديد، مد الديدلاين، عايز وقت زيادة، الديدلاين مش هلحق، تأخير التاسك",
            "more time, extra time, extension, extend the deadline, I will not make the deadline",
        ),
        [
            "افتح التاسك من «شغلي».",
            "اضغط «اطلب وقت أطول».",
            "اكتب المدة (يوم / ساعة / دقيقة) واكتب «السبب (اختياري)».",
            "اضغط «ابعت الطلب للتيم ليدر» وانتظر رده؛ الرد بيظهر في صفحة التاسك.",
        ],
        [
            "Open the task from «My work».",
            "Press «Ask for more time».",
            "Write the length (days / hours / minutes) and the «Why (optional)».",
            "Press «Ask the team leader» and wait for the answer; it shows on the task page.",
        ],
        note=(
            "التيم ليدر بيوافق أو بيرفض، والموافقة مابتعدّيش ديدلاين العميل.",
            "The team leader approves or declines, and an approval never goes past the client's deadline.",
        ),
    ),
    _guide(
        "tr-ai-check", (Role.TRANSLATOR,), "/translator",
        ("إزاي أراجع ترجمتي بالـAI قبل التسليم", "How do I check my translation with the AI before handing in"),
        (
            "مراجعة بالذكاء الاصطناعي، تشيك، اتشيك، راجع ترجمتي، فحص الترجمة، ai، الذكاء الاصطناعي، اغلاط الترجمة",
            "ai check, check my translation, review my translation, artificial intelligence, mistakes in my translation",
        ),
        [
            "افتح التاسك من «شغلي».",
            "في كارت «مراجعة الترجمة بالـ AI» اضغط «تشيك». لو مكتوب فيه «متوقفة من الأدمن» يبقى الأدمن مقفلها.",
            "استنى؛ التنبيه بيوصلك أول ما الفحص يخلص وهيقولك الأخطاء ومكانها من غير ما يعدّل الترجمة.",
            "صلّح بنفسك وارفع الملف تاني.",
        ],
        [
            "Open the task from «My work».",
            "In the card «AI translation check» press «Check». If it says «Disabled by admin» the admin has switched it off.",
            "Wait; you are notified when the check finishes. It tells you the mistakes and where they are, without editing the translation.",
            "Fix them yourself and upload the file again.",
        ],
    ),
    _guide(
        "tr-payroll", (Role.TRANSLATOR,), "/payroll",
        ("إزاي أشوف مستحقاتي", "How do I see my payroll"),
        (
            "مستحقات، مستحقاتي، مرتبي، راتبي، الراتب، كشف الحساب، بونص، خصومات، الصافي، كام هاخد",
            "payroll, my pay, my salary, payslip, bonus, deductions, net, how much will I get",
        ),
        [
            "من قسم «حسابي» افتح «مستحقاتي».",
            "اختار الشهر.",
            "هتلاقي «الراتب الأساسي» و«بونص الإنتاج» و«خصومات» و«الصافي»، وكلماتك وأيامك.",
            "«التفاصيل كاملة» بتفتح الحساب بالتفصيل.",
        ],
        [
            "In the «My account» section open «My payroll».",
            "Pick the month.",
            "You will find the «Base salary», «Production bonus», «Deductions» and «Net», with your words and days.",
            "«Full breakdown» opens the full working-out.",
        ],
        note=(
            "الشهر اللي لسه ماتحسبش مابيظهرش لحد ما الحسابات تشغّله.",
            "A month that has not been run yet does not show until accounts computes it.",
        ),
    ),
    _guide(
        "tr-rating", (Role.TRANSLATOR,), "/translator",
        ("إزاي أعرف تقييمي اتخصم منه ليه", "How do I see why my rating dropped"),
        (
            "تقييمي، التقييم، اتخصم من تقييمي، سجل التقييم، نجمة، خصم تقييم",
            "my rating, rating, rating penalty, rating history, stars",
        ),
        [
            "من قسم «الشغل» افتح «شغلي».",
            "اضغط على «سجل التقييم» تلاقي كل خصم وسببه.",
        ],
        [
            "In the «Work» section open «My work».",
            "Press «Rating history» to see every penalty and its reason.",
        ],
    ),
    # ------------------------------------------------------------------------------------------------------------------
    # The client desk: operation and Sales (the owner can do all of it).
    # ------------------------------------------------------------------------------------------------------------------
    _guide(
        "ops-mail-read", CLIENT_DESK, "/inbox",
        ("إزاي أقرا ميلات العملاء", "How do I read the client mail"),
        (
            "ميل، ميلات، الميلات الواردة، إيميل، اقرا الميل، صندوق البريد، الوارد، ميلات واردة، ميلاتي، فين الميلات",
            "mail, e-mail, inbox, incoming mail, read the mail, where is the mail",
        ),
        [
            "من قسم «الشغل» افتح «ميلات واردة» (الـSales بيفتح «ميلاتي»).",
            "الرقم الأحمر جنب الاسم هو عدد المحادثات اللي لسه ماتفتحتش.",
            "اختار من «الفلتر»: «كل الميلات» أو «اللي أنا استلمتها» أو «محادثات محدش استلمها».",
            "دوّر بالعنوان أو نص الميل أو كود العميل، واضغط على المحادثة وبعدها على الميل عشان يتفتح.",
        ],
        [
            "In the «Work» section open «Incoming mail» (Sales open «My mail»).",
            "The red number beside the name is how many conversations have not been opened.",
            "Pick from the «Filter»: «All mail», «Claimed by me» or «Conversations nobody has claimed».",
            "Search the subject, the text or a client code, press the conversation and then the letter to open it.",
        ],
        starter=True,
    ),
    _guide(
        "ops-mail-fetch", CLIENT_DESK, "/inbox",
        ("إزاي أجيب الميلات الجديدة دلوقتي", "How do I fetch new mail right now"),
        (
            "جيب الميلات، حدّث الميلات، الميل مش بيوصل، ميل جديد مجاش، تحديث الصندوق",
            "fetch mail, refresh the mail, mail not arriving, new mail has not come",
        ),
        [
            "افتح «ميلات واردة» (أو «ميلاتي»).",
            "اضغط «جيب الميلات دلوقتي».",
            "الميلات بتوصل لوحدها كمان؛ لو مكتوب «صندوق البريد مش متظبّط» كلّم الأدمن.",
        ],
        [
            "Open «Incoming mail» (or «My mail»).",
            "Press «Fetch mail now».",
            "Mail also arrives by itself; if it says «The mailbox is not configured» tell the admin.",
        ],
    ),
    _guide(
        "ops-mail-reply", CLIENT_DESK, "/inbox",
        ("إزاي أرد على ميل عميل", "How do I reply to a client's e-mail"),
        (
            "رد على ميل، ارد على العميل، رد، ابعت ميل للعميل، اكتب رد، ريبلاي",
            "reply to an e-mail, answer the client, reply, send the client a mail, write a reply",
        ),
        [
            "افتح المحادثة من «ميلات واردة» (أو «ميلاتي»).",
            "تحت الميلات اكتب ردك في «اكتب ردك هنا…». تقدر «ارفق ملفات» لحد 25 ميجا.",
            "اضغط «ابعت» (أو Ctrl+Enter).",
            "الرد بيظهر تحت «ردّنا»؛ لو فشل بيفضل في الصفحة ومكتوب سبب الفشل.",
        ],
        [
            "Open the conversation from «Incoming mail» (or «My mail»).",
            "Under the letters write your reply in «Write your reply…». You can «Attach files» up to 25 MB.",
            "Press «Send» (or Ctrl+Enter).",
            "The reply shows under «Our reply»; if it fails it stays on the page with the reason.",
        ],
    ),
    _guide(
        "ops-mail-receipt", CLIENT_DESK, "/inbox",
        ("إزاي أأكد للعميل إن ميله وصل (استلمت)", "How do I tell a client their mail arrived"),
        (
            "استلمت الميل، أكد استلام، تأكيد الاستلام، confirmed، استلمت ميل العميل، رد تلقائي بالاستلام",
            "confirm receipt, received the mail, acknowledge the client's mail, confirmed",
        ),
        [
            "افتح المحادثة من «ميلات واردة» (أو «ميلاتي») واضغط على الميل عشان يتفتح.",
            "اضغط «استلمت».",
            "أكّد بـ«ابعت». العميل بيجيله رد فيه كلمة confirmed، واسمك بيظهر على الميل («استلمها»).",
        ],
        [
            "Open the conversation from «Incoming mail» (or «My mail») and press the letter to open it.",
            "Press «Received».",
            "Confirm with «Send». The client gets a reply saying confirmed, and your name shows on the letter («Claimed by»).",
        ],
    ),
    _guide(
        "ops-task-from-mail", (Role.OPERATION, Role.ADMIN), "/inbox",
        ("إزاي أبدأ تاسك جديدة من ميل", "How do I start a task from an e-mail"),
        (
            "ابدأ تاسك، اعمل تاسك، تاسك جديدة، تاسك من ميل، حوّل الميل لتاسك، افتح تاسك، ابدا تاسك، تحويل لتاسك، تاسك جديد",
            "start a task, make a task, new task, task from an e-mail, convert the mail to a task, open a task",
        ),
        [
            "افتح المحادثة من «ميلات واردة» واضغط على الميل اللي فيه الشغل.",
            "علّم الملفات اللي هتروح للمترجم (لو ماعلّمتش حاجة بتروح كلها).",
            "اضغط «تحويل لتاسك».",
            "في الفورم اكتب «كود العميل» و«عنوان التاسك» و«من لغة» و«للغة» و«عدد الكلمات» و«الديدلاين (بتاخده من العميل)» و«الأولوية»، وراجع «متطلبات العميل».",
            "اضغط «اعمل التاسك». بعدها وزّعها على تيم ليدر (شوف دليل: إزاي أبعت التاسك لتيم ليدر).",
        ],
        [
            "Open the conversation from «Incoming mail» and press the letter with the work in it.",
            "Tick the files that go to the translator (nothing ticked means all of them).",
            "Press «Convert to task».",
            "In the form write the «Client code», «Task title», «Source language», «Target language», «Word count», «Deadline (agreed with the client)» and «Priority», and check the «Client requirements».",
            "Press «Create task». Then send it to a team leader (see the guide: How do I send a task to a team leader).",
        ],
        starter=True,
    ),
    _guide(
        "ops-task-from-chat", (Role.OPERATION, Role.ADMIN), "/chats",
        ("إزاي أحوّل رسايل عميل في الشات لتاسك", "How do I turn a client's chat messages into a task"),
        (
            "تاسك من الشات، حوّل رسايل الواتساب لتاسك، تحويل لتاسك، ملفات من الواتساب، تاسك من واتساب",
            "task from a chat, turn WhatsApp messages into a task, convert to task, files from WhatsApp",
        ),
        [
            "من «الشات» افتح تبويب «العملاء» وافتح محادثة العميل بالكود.",
            "اضغط «تحديد ملفات» وعلّم الملفات اللي هتروح للمترجم (تقدر تعلّم من أكتر من رسالة).",
            "اضغط «تحويل لتاسك» وبعدها «كمّل».",
            "كمّل الفورم واضغط «اعمل التاسك».",
        ],
        [
            "In «Chats» open the «Clients» tab and open the client's conversation by its code.",
            "Press «Select files» and tick the files that go to the translator (you can tick from several messages).",
            "Press «Convert to task» and then «Continue».",
            "Complete the form and press «Create task».",
        ],
    ),
    _guide(
        "ops-task-new", (Role.OPERATION, Role.ADMIN), "/tasks/new",
        ("إزاي أعمل تاسك جديدة من غير ميل", "How do I make a task without a message"),
        (
            "تاسك جديدة، اعمل تاسك جديدة، تاسك جديد، فورم التاسك، اضافة تاسك، ضيف تاسك",
            "new task, make a new task, task form, add a task",
        ),
        [
            "افتح «التاسكات» من قسم «الشغل».",
            "اضغط «تاسك جديدة».",
            "املا «كود العميل» و«عنوان التاسك» و«من لغة» و«للغة» و«عدد الكلمات» و«الديدلاين (بتاخده من العميل)» و«الأولوية».",
            "اضغط «اعمل التاسك».",
        ],
        [
            "In the «Work» section open «Tasks».",
            "Press «New task».",
            "Fill the «Client code», «Task title», «Source language», «Target language», «Word count», «Deadline (agreed with the client)» and «Priority».",
            "Press «Create task».",
        ],
    ),
    _guide(
        "ops-assign-lead", (Role.OPERATION, Role.ADMIN), "/tasks",
        ("إزاي أبعت التاسك لتيم ليدر", "How do I send a task to a team leader"),
        (
            "وزّع التاسك، assign، اعمل assign لتيم ليدر، ابعت التاسك لليدر، توزيع التاسك، اختار تيم ليدر، تاسك جديدة محتاجة توزيع",
            "assign a task, send the task to the leader, distribute, pick a team leader, new task needs assigning",
        ),
        [
            "افتح «التاسكات» من قسم «الشغل»؛ التاسكات الجديدة بتظهر في «جديدة — محتاجة توزيع».",
            "افتح التاسك.",
            "من «اعمل assign لتيم ليدر» اختار تيم ليدر (قدّام كل اسم online أو offline وعدد تاسكاته).",
            "اضغط «ابعتها للتيم ليدر». بيظهر له عداد قصير عشان يستلم.",
        ],
        [
            "In the «Work» section open «Tasks»; new tasks show under «New — need assigning».",
            "Open the task.",
            "From «Assign a team leader» pick one (each name shows online or offline and their task count).",
            "Press «Send to team leader». A short timer starts for them to accept.",
        ],
        starter=True,
    ),
    _guide(
        "ops-deliver", (Role.OPERATION, Role.ADMIN), "/tasks",
        ("إزاي أسلّم الترجمة للعميل", "How do I deliver the translation to the client"),
        (
            "سلّم للعميل، تسليم للعميل، ابعت للعميل، ابعت الشغل للعميل، ابعت الملفات للعميل، سلّم الشغل للعميل، استلمت التاسك، قفل التاسك، التسليم النهائي، ابعت الترجمة للعميل",
            "deliver to the client, send to the client, take over the task, close the task, final delivery",
        ),
        [
            "لما التيم ليدر يخلص المراجعة التاسك بتبقى «التاسك مستنية استلامك». افتحها من «التاسكات» (فلتر «جاهزة للتسليم»).",
            "اضغط «استلمت التاسك» وأكّد «أيوه، استلمتها». مفيش ملف بيروح للعميل قبل كده.",
            "في «الملفات اللي هتتبعت للعميل» علّم الملفات (ملف المترجم معلّم من الأول) واكتب «رسالة للعميل (اختياري)».",
            "اتأكد إن القناة ظاهرة (واتساب أو إيميل)؛ لو مكتوب «مفيش رقم ولا إيميل للعميل» ماينفعش تبعت.",
            "اضغط «ابعت للعميل وسلّم». ولو عايز تقفل من غير ما تبعت حاجة اضغط «قفل التاسك من غير إرسال».",
        ],
        [
            "When the team leader finishes the review the task is «Waiting for you to take it over». Open it from «Tasks» (filter «Ready to deliver»).",
            "Press «I have the task» and confirm «Yes, I have it». No file reaches the client before that.",
            "Under «Files to send to the client» tick the files (the translator's is ticked to begin with) and write a «Message to the client (optional)».",
            "Check the channel shows (WhatsApp or e-mail); if it says «No phone or e-mail on file» you cannot send.",
            "Press «Send to client & close». To close without sending anything press «Close without sending».",
        ],
        starter=True,
    ),
    _guide(
        "ops-deadline", (Role.OPERATION, Role.ADMIN), "/tasks",
        ("إزاي أعدّل ديدلاين العميل على تاسك", "How do I change a task's client deadline"),
        (
            "ديدلاين، عدّل الديدلاين، الموعد، غيّر ميعاد التسليم، ديدلاين العميل",
            "deadline, change the deadline, due date, the client's date",
        ),
        [
            "افتح التاسك من «التاسكات».",
            "في «الديدلاين (من العميل)» اكتب المدة من دلوقتي بالأيام والساعات والدقايق.",
            "اضغط «حفظ الديدلاين». سيبها فاضية لو مش عايز تغيّر، وأصفار معناها من غير ديدلاين.",
        ],
        [
            "Open the task from «Tasks».",
            "In «Deadline (from the client)» write the time from now in days, hours and minutes.",
            "Press «Save the deadline». Leave it empty to keep it; zeros mean no deadline.",
        ],
    ),
    _guide(
        "ops-cancel-task", (Role.OPERATION, Role.ADMIN), "/tasks",
        ("إزاي ألغي تاسك", "How do I cancel a task"),
        (
            "الغي التاسك، إلغاء تاسك، امسح التاسك، وقف التاسك، كانسل",
            "cancel a task, stop the task, cancel",
        ),
        [
            "افتح التاسك من «التاسكات».",
            "اضغط «إلغاء التاسك».",
            "أكّد بـ«ألغي التاسك».",
        ],
        [
            "Open the task from «Tasks».",
            "Press «Cancel task».",
            "Confirm with «Cancel the task».",
        ],
        note=(
            "الزرار مابيظهرش لو التاسك اتسلّمت أو مش من صلاحيتك تلغيها.",
            "The button does not show if the task was delivered or you may not cancel it.",
        ),
    ),
    _guide(
        "ops-client-codes", (Role.OPERATION, Role.TEAM_LEAD, Role.SALES, Role.ADMIN), "/clients",
        ("إزاي ألاقي عميل بالكود", "How do I find a client by code"),
        (
            "عميل، كود العميل، أكواد العملاء، دوّر على عميل، ملف العميل، تاسكات العميل، بيانات العميل",
            "client, client code, client codes, find a client, client profile, client tasks",
        ),
        [
            "من قسم «الشغل» افتح «أكواد العملاء».",
            "اكتب الكود في «ابحث بالكود…» واضغط «بحث».",
            "اضغط «افتح» على العميل.",
            "هتلاقي «تاسكات العميل» و«المتطلبات والملاحظات».",
        ],
        [
            "In the «Work» section open «Client codes».",
            "Type the code in «Search by code…» and press «Search».",
            "Press «Open» on the client.",
            "You will find the «Client tasks» and the «Requirements & notes».",
        ],
        note=(
            "الأوبريشن والتيم ليدر بيشتغلوا بالكود؛ اسم العميل وأرقامه ظاهرة للأدمن والـSales بس.",
            "Operation and team leaders work by code; the client's name and numbers are shown to the admin and Sales only.",
        ),
    ),
    _guide(
        "ops-requirement", (Role.OPERATION, Role.ADMIN), "/clients",
        ("إزاي أضيف متطلب أو ملاحظة لعميل", "How do I add a requirement or note to a client"),
        (
            "متطلبات العميل، ضيف متطلب، ملاحظة على العميل، شروط العميل، طلبات العميل",
            "client requirements, add a requirement, note on the client, the client's conditions",
        ),
        [
            "افتح «أكواد العملاء» وادخل على العميل.",
            "في «المتطلبات والملاحظات» اختار «النوع» واكتب «المتطلب».",
            "اضغط «ضيف متطلب». هتظهر للمترجم في صفحة أي تاسك للعميل ده، فاكتب المتطلب نفسه من غير اسم العميل ولا بياناته.",
        ],
        [
            "Open «Client codes» and go into the client.",
            "In «Requirements & notes» pick the «Kind» and write the «Requirement».",
            "Press «Add requirement». The translator sees it on any task of that client, so write the requirement itself, without the client's name or details.",
        ],
    ),
    _guide(
        "ops-team-status", (Role.OPERATION, Role.ADMIN), "/team",
        ("إزاي أعرف مين من الفرق فاضي ومين مشغول", "How do I see which teams are free or busy"),
        (
            "حالة الفرق، مين فاضي، مين مشغول، التيم ليدرز، حالة المترجمين، مين أونلاين، الفرق",
            "team status, who is free, who is busy, team leaders, translator status, who is online",
        ),
        [
            "من قسم «الشغل» افتح «حالة الفرق».",
            "هتلاقي كل تيم ليدر ومترجميه، وحالتهم («نشط دلوقتي» / «فاضيين» / «مشغولين» / «أوفلاين») والتاسك الحالية.",
        ],
        [
            "In the «Work» section open «Team status».",
            "You will see every team leader and their translators, their state («Online now» / «Free» / «Busy» / «Offline») and the current task.",
        ],
    ),
    _guide(
        "ops-client-reply", CLIENT_DESK, "/chats",
        ("إزاي أرد على عميل في الواتساب", "How do I answer a client on WhatsApp"),
        (
            "رد على عميل، واتساب، رد واتساب، ابعت للعميل، رسالة للعميل، شات العميل، كلم العميل",
            "answer a client, WhatsApp, reply on WhatsApp, message the client, client chat, talk to the client",
        ),
        [
            "من «الشات» افتح تبويب «العملاء».",
            "دوّر بكود العميل واضغط على المحادثة.",
            "اكتب في «اكتب رسالتك للعميل...» واضغط «إرسال».",
        ],
        [
            "In «Chats» open the «Clients» tab.",
            "Search the client's code and press the conversation.",
            "Write in «Write your reply to the client...» and press «Send».",
        ],
        note=(
            "واتساب بيسمح بالرد خلال 24 ساعة من آخر رسالة من العميل. لو ظهر «نافذة الـ24 ساعة قفلت» مش هينفع تبعت لحد ما العميل يكتب تاني.",
            "WhatsApp allows a reply within 24 hours of the client's last message. If you see «The 24-hour window is closed» you cannot send until the client writes again.",
        ),
    ),
    _guide(
        "sales-line", (Role.SALES, Role.ADMIN), "/line",
        ("إزاي أظبّط رقمي وإيميلي (خط الـSales)", "How do I set my number and mail (the Sales line)"),
        (
            "رقمي وإيميلي، رقم الواتساب بتاعي، خط المبيعات، عنواني على ميل الشركة، رقم Sales، ظبط رقمي",
            "my number and mail, my WhatsApp number, sales line, my address on the company mailbox",
        ),
        [
            "من قسم «الشغل» افتح «رقمي وإيميلي».",
            "اكتب «رقم الواتساب» زي ما العميل بيكتبه واضغط «حفظ».",
            "«عنوانك على ميل الشركة» بيحدده الأدمن من صفحة الموظف، مش من هنا.",
            "بعد الحفظ أي عميل يكلمك على الرقم أو العنوان ده بيظهر عندك انت بس.",
        ],
        [
            "In the «Work» section open «My number & mail».",
            "Type your «WhatsApp number» as clients dial it and press «Save».",
            "«Your address on the company mailbox» is set by the admin on the staff page, not here.",
            "After saving, any client who writes to that number or address shows up for you only.",
        ],
        starter=True,
    ),
    # ------------------------------------------------------------------------------------------------------------------
    # The team leader.
    # ------------------------------------------------------------------------------------------------------------------
    _guide(
        "lead-my-tasks", (Role.TEAM_LEAD,), "/lead",
        ("فين تاسكاتي اللي عندي", "Where are the tasks I hold"),
        (
            "تاسكاتي، التاسكات اللي عندي، لوحة التيم ليدر، تاسكات مفتوحة، فريقي، مترجمين فاضيين",
            "my tasks, the tasks I hold, team leader board, open tasks, my team, free translators",
        ),
        [
            "من قسم «الشغل» افتح «تاسكاتي».",
            "تحت «التاسكات اللي عندي» كل تاسك وحالته وديدلاينه. التاسك الجديدة عليها «وزّع على مترجم» والمخلّصة عليها «راجع الترجمة».",
            "«فريقي» بيقولك مين من مترجميك فاضي ومين مشغول.",
        ],
        [
            "In the «Work» section open «My tasks».",
            "Under «My tasks» (the list) each task shows its state and deadline. A new one has «Assign a translator» and a finished one has «Review».",
            "«My team» tells you which of your translators is free and which is busy.",
        ],
        starter=True,
    ),
    _guide(
        "lead-assign-translator", (Role.TEAM_LEAD, Role.ADMIN), "/lead",
        ("إزاي أوزّع تاسك على مترجم", "How do I assign a task to a translator"),
        (
            "وزّع على مترجم، اعمل assign لمترجم، ابعت التاسك لمترجم، اختار مترجم، ديدلاين المترجم، ابعتها للمترجم",
            "assign to a translator, send the task to a translator, pick a translator, the translator's deadline",
        ),
        [
            "افتح «تاسكاتي» واضغط «وزّع على مترجم» على التاسك (أو افتح التاسك).",
            "من «اعمل assign لمترجم من فريقك» اختار المترجم؛ قدّام كل اسم فاضي أو مشغول أو أوفلاين وتقييمه.",
            "في «الديدلاين اللي هتديه للمترجم» شايف ديدلاين الأوبريشن وعدّاده التنازلي. لازم تختار: «نفس ديدلاين الأوبريشن» أو «ديدلاين أقل».",
            "لو اخترت «ديدلاين أقل» اكتب بعد كام يوم أو ساعة أو دقيقة من دلوقتي، ولازم يكون أقل من الوقت الباقي عشان يفضلك وقت تراجع. المترجم بيشوف العد التنازلي بالديدلاين اللي حطيته.",
            "اضغط «ابعتها للمترجم» (مابتتفتحش قبل ما تختار). بيظهر له عداد يستلم.",
            "لو عايز تغيّر ديدلاينه بعدين اكتب المدة واضغط «حفظ ديدلاين المترجم».",
        ],
        [
            "Open «My tasks» and press «Assign a translator» on the task (or open the task).",
            "From «Assign a translator from your team» pick the translator; each name shows free, busy or offline and their rating.",
            "In «The deadline you are giving the translator» you see the operation's deadline and its countdown. You have to choose: «The same as the operation's deadline» or «A shorter deadline».",
            "If you choose «A shorter deadline» write how many days, hours or minutes from now; it has to be less than the time left, so you keep time to review. The translator counts down to the deadline you gave.",
            "Press «Send to translator» (it stays off until you choose). A timer for accepting starts for them.",
            "To change their deadline later write the time and press «Save the translator's deadline».",
        ],
        starter=True,
    ),
    _guide(
        "lead-extension", (Role.TEAM_LEAD, Role.ADMIN), "/lead",
        ("إزاي أرد على طلب وقت إضافي من مترجم", "How do I answer a translator's request for more time"),
        (
            "وقت إضافي، المترجم طالب وقت، وافق على التمديد، ارفض التمديد، طلب تمديد، مد ديدلاين",
            "extra time request, the translator asks for time, approve the extension, decline the extension",
        ),
        [
            "افتح التاسك من «تاسكاتي»؛ فوق هتلاقي «المترجم طالب وقت إضافي» والمدة والسبب والديدلاين الجديد.",
            "اضغط «موافق»، أو «رفض» وأكّد «أيوه، ارفض».",
        ],
        [
            "Open the task from «My tasks»; at the top you will find «The translator asks for more time» with the length, reason and new deadline.",
            "Press «Approve», or «Decline» and confirm «Yes, decline».",
        ],
        note=(
            "الموافقة مابتعدّيش ديدلاين العميل.",
            "An approval never goes past the client's deadline.",
        ),
        starter=True,
    ),
    _guide(
        "lead-review", (Role.TEAM_LEAD, Role.ADMIN), "/lead",
        ("إزاي أراجع ترجمة وأخلّص المراجعة", "How do I review a translation and finish the review"),
        (
            "راجع الترجمة، مراجعة الترجمة، تمت المراجعة، خلصت المراجعة، ملاحظات الـ AI، اراجع شغل المترجم",
            "review the translation, finish the review, review completed, AI notes, check the translator's work",
        ),
        [
            "افتح «تاسكاتي» واضغط «راجع الترجمة» على التاسك.",
            "قارن «ملف الترجمة (من المترجم)» بـ«الملف الأصلي (من العميل)».",
            "لو الـAI مفعّل هتلاقي «ملاحظات الـ AI على الترجمة» (وفيها «أعد الفحص»)؛ دي اقتراحات بس والقرار ليك.",
            "علّم «اقبلها» على الملاحظات اللي صح واضغط زرار قبول المحدد، أو «اقبل الكل» لو كلها صح. كل ملاحظة بتتقبل بتخصم نجوم من تقييم المترجم بس، وبيطلع لك سؤال بعدد النجوم قبل ما يتنفذ.",
            "لو فيه ملاحظات كلّم المترجم في جروب الشغل من «الشات» واستنى الملف المعدّل.",
            "لو انت اللي عدّلت الملف: من «الملف اللي ظبطته» اختار ملفك واضغط «احفظ الملف المعدّل». ده اللي هيروح للأوبريشن مع المراجعة بدل ملف المترجم. لو مارفعتش ملف هيروح ملف المترجم زي ما هو.",
            "لما تبقى تمام اضغط «تمت المراجعة» وأكّد «أيوه، خلصت». التاسك بتروح للأوبريشن تستلمها وتسلّمها للعميل.",
        ],
        [
            "Open «My tasks» and press «Review» on the task.",
            "Compare the «Translation (from the translator)» with the «Original (from the client)».",
            "If the AI is on you will find «AI notes on the translation» (with «Check again»); they are suggestions only and the decision is yours.",
            "Tick «Accept» on the notes that are right and press the accept-selected button, or «Accept all» if all are. Each accepted note takes stars off the translator's rating only, and you are asked how many before it is done.",
            "If there are notes, talk to the translator in the work group from «Chats» and wait for the corrected file.",
            "If you corrected the file yourself: under «The file you corrected» choose your file and press «Save the corrected file». That is what the operation gets with the review, in place of the translator's file. With none put there, the translator's file goes as it is.",
            "When it is right press «Review completed» and confirm «Yes, it is done». The task goes to operation to take over and deliver to the client.",
        ],
        starter=True,
    ),
    _guide(
        "lead-send-corrected-file", (Role.TEAM_LEAD, Role.ADMIN), "/lead",
        ("إزاي أبعت للأوبريشن الملف اللي أنا ظبطته", "How do I send the operation the file I corrected"),
        (
            "ملفي المعدّل، الملف اللي عدلته، ابعت ملفي مش ملف المترجم، نسختي بعد المراجعة، ملف معدل، غيرت الملف",
            "my corrected file, the file I edited, send my file not the translator's, my version after review, corrected file",
        ),
        [
            "افتح التاسك من «تاسكاتي». وانت في مرحلة المراجعة هتلاقي في «الإجراءات» خانة «الملف اللي ظبطته».",
            "اختار ملفك (أو أكتر من ملف) واضغط «احفظ الملف المعدّل». ملفك هو اللي هيتبعت للأوبريشن، مش ملف المترجم.",
            "اضغط «تمت المراجعة» وأكّد «أيوه، خلصت». الأوبريشن بيستلم ملفك في الشات بتاعك معاه، وهو اللي بيتعلّم تلقائيًا لما يسلّم للعميل.",
            "لو افتكرت تعديل بعد ما ضغطت «تمت المراجعة»: ارفع الملف الجديد من نفس الخانة واضغط «ابعت الملف المعدّل للأوبريشن». بيوصله على طول ومكتوب إنه بدل اللي قبله.",
        ],
        [
            "Open the task from «My tasks». While it is under review you will find «The file you corrected» in «Actions».",
            "Choose your file (or several) and press «Save the corrected file». Your file is what goes to the operation, not the translator's.",
            "Press «Review completed» and confirm «Yes, it is done». The operation receives your file in their chat with you, and it is the one ticked for the client.",
            "If you notice a fix after pressing «Review completed»: put the new file in the same box and press «Send the corrected file to the operation». It reaches them at once and says it replaces the first.",
        ],
    ),
    _guide(
        "hr-incentive", (Role.ADMIN,), "/hr/employees",
        ("إزاي أضيف حوافز (زيادة مرتب) لموظف", "How do I add an incentive (a pay raise) to an employee"),
        (
            "حوافز، زيادة مرتب، علاوة، حافز شهري، ضيف على المرتب، مبلغ يدوي على المرتب",
            "incentive, pay raise, monthly bonus, add to the salary, manual amount on the salary",
        ),
        [
            "افتح «ملفات الموظفين» واختار الموظف.",
            "تحت «خطة الراتب» هتلاقي «الحوافز (زيادة مرتب)». اكتب المبلغ الشهري واضغط «سجّل».",
            "المبلغ بيتضاف على مرتب الموظف كل شهر لحد ما تغيّره، بالإيد من غير أي قاعدة بتحسبه. اكتب صفر عشان تشيله.",
            "الشهر اللي اتحسب قبل كده بيفضل زي ما اتدفع، والحوافز بتظهر في كشف المرتب.",
        ],
        [
            "Open «Employee files» and choose the person.",
            "Under «Salary plan» you will find «Incentive (pay raise)». Type the monthly amount and press «Record».",
            "The amount is added to the person's pay every month until you change it, by hand, with no rule working it out. Type zero to take it off.",
            "A month that was already run stays as it was paid, and the incentive shows on the payslip.",
        ],
    ),
    _guide(
        "hr-penalty-change", (Role.ADMIN,), "/hr/employees",
        ("إزاي أغيّر قرار خصم نجوم اتاخد قبل كده", "How do I change a decision on a star penalty"),
        (
            "خصم التقييم، خصومات التقييم، سامح الخصم، اطبق الخصم تاني، غيّر قرار الخصم، رجّع النجوم",
            "rating penalty, forgive a penalty, apply the penalty again, change the decision, give the stars back",
        ),
        [
            "افتح «ملفات الموظفين» واختار الموظف وانزل لـ«خصومات التقييم».",
            "الخصم اللي اتطبق عليه زرار «سامحه وارجّع النجوم». اضغطه والنجوم بترجع للموظف وبيتبلّغ.",
            "الخصم اللي اتسامح عليه زرار «طبّق الخصم تاني». اضغطه والنجوم بتتخصم تاني وبيتبلّغ.",
            "القرار اللي بيتاخد من الـHR بيفضل مرة واحدة؛ انت بس اللي بتقدر تغيّره بعد كده.",
        ],
        [
            "Open «Employee files», choose the person and scroll to «Rating penalties».",
            "A penalty that was applied has the button «Forgive and give the stars back». Press it and the stars go back to the person, who is told.",
            "A penalty that was forgiven has the button «Apply it again». Press it and the stars come off again, and the person is told.",
            "A decision HR takes stands once; only you can change it afterwards.",
        ],
    ),
    _guide(
        "lead-translators-board", (Role.TEAM_LEAD, Role.ADMIN), "/lead/translators",
        ("إزاي أعرف مين من المترجمين اللي عندي فاضي", "How do I see which of my translators is free"),
        (
            "حالة المترجمين، مين فاضي، مين مشغول، المترجمين اللي عندي، فريقي، الحِمل، مين أوفلاين",
            "translator status, who is free, who is busy, my translators, my team, workload, who is offline",
        ),
        [
            "من قسم «الشغل» افتح «حالة المترجمين».",
            "هتلاقي «فاضيين دلوقتي» و«مشغولين» وقدّام كل مترجم تقييمه وحمله وأقرب ديدلاين.",
        ],
        [
            "In the «Work» section open «Translator status».",
            "You will find «Free now» and «Busy», with each translator's rating, load and next deadline.",
        ],
    ),
    # ------------------------------------------------------------------------------------------------------------------
    # The reviewer (and whoever marks candidate tests).
    # ------------------------------------------------------------------------------------------------------------------
    _guide(
        "reviewer-mark-test", (Role.REVIEWER, Role.TEAM_LEAD, Role.ADMIN), "/reviewer/tests",
        ("إزاي أصحّح اختبار مرشح", "How do I mark a candidate's test"),
        (
            "صحّح اختبار، تصحيح الاختبار، اختبارات المرشحين، قيّم الاختبار، درجة المرشح، مراجع",
            "mark a test, marking, candidate tests, score the test, candidate's grade, reviewer",
        ),
        [
            "افتح «اختبارات المرشحين» (قسم «التوظيف»).",
            "في «مستنية تصحيح» اضغط «صحّح» على الاختبار.",
            "نزّل «ملف تسليم المرشح» وقارنه بالمطلوب.",
            "اكتب درجة كل بند من 10 واضغط «احفظ التقييم». الإجمالي بيتحسب لوحده.",
        ],
        [
            "Open «Candidate tests» (the «Recruitment» section).",
            "Under «Waiting to be marked» press «Mark» on the test.",
            "Download «The candidate's submission» and compare it with what was asked.",
            "Write each item's score out of 10 and press «Save». The total is computed for you.",
        ],
        note=(
            "ماتعرفش مين المرشح: بتشوف كود وشغله بس.",
            "You do not see who the candidate is: only a code and the work.",
        ),
        starter=True,
    ),
    # ------------------------------------------------------------------------------------------------------------------
    # HR (and the owner, who can do it all). The attendance guides also open to an attendance manager of another role.
    # ------------------------------------------------------------------------------------------------------------------
    _guide(
        "hr-board", (Role.HR, Role.ADMIN), "/hr/attendance",
        ("إزاي أتابع حضور الموظفين النهارده", "How do I follow today's attendance"),
        (
            "لوحة الحضور، حضور الموظفين، مين حضر، مين اتأخر، مين مجاش، متابعة الحضور، مسجلوش حضور",
            "attendance board, staff attendance, who is in, who is late, who did not come, follow attendance, no check-in",
        ),
        [
            "من قسم «الموظفين» افتح «لوحة الحضور».",
            "ضيّق بالفلاتر (الموظف والدور والشيفت والحالة والمدى).",
            "«مسجلوش حضور النهارده» بيقولك مين لسه ما سجلش، و«محتاج مراجعة» بيعرض الأيام المعلّمة.",
            "اضغط «عدّل» على أي يوم لتصحيحه.",
        ],
        [
            "In the «People» section open «Attendance board».",
            "Narrow it with the filters (employee, role, shift, status and range).",
            "«No check-in today» tells you who has not checked in, and «Needs review» lists the flagged days.",
            "Press «Edit» on any day to correct it.",
        ],
        cap="can_manage_attendance",
        starter=True,
    ),
    _guide(
        "hr-fix-day", (Role.HR, Role.ADMIN), "/hr/attendance",
        ("إزاي أصحّح يوم حضور لموظف", "How do I correct an employee's attendance day"),
        (
            "عدّل اليوم، صحح الحضور، عدل الحضور، يوم غلط، نسي يسجل، تعديل يوم، حضور اتسجل غلط",
            "correct the day, fix attendance, edit attendance, wrong day, forgot to check in, edit a day",
        ),
        [
            "من «لوحة الحضور» اضغط «عدّل» على اليوم (أو «مراجعة» لو معلّم).",
            "في «عدّل اليوم» غيّر الخانات المطلوبة.",
            "اكتب «السبب» (لازم) واضغط «احفظ».",
            "كل تعديل بيتسجل في «سجل التعديلات» ومابيتمسحش.",
        ],
        [
            "From the «Attendance board» press «Edit» on the day (or «Review» if flagged).",
            "In «Correct the day» change the boxes you need.",
            "Write the «Reason» (required) and press «Save».",
            "Every change is recorded in the «Audit trail» and is never erased.",
        ],
        cap="can_manage_attendance",
    ),
    _guide(
        "hr-schedules", (Role.HR, Role.ADMIN), "/hr/schedules",
        ("إزاي أظبط جدول شغل موظف", "How do I set an employee's work schedule"),
        (
            "جدول الموظف، جداول العمل، الجدول الأسبوعي، شيفت الموظف، ضيف يوم للجدول، أجازة أسبوعية، عدّل يوم واحد",
            "work schedule, schedules, weekly roster, employee's shift, add a roster day, weekly day off, override one day",
        ),
        [
            "من قسم «الموظفين» افتح «جداول العمل» واختار الموظف.",
            "في «الجدول الأسبوعي» اضغط «ضيف يوم للجدول» واختار اليوم والشيفت. اليوم اللي مالوش سطر = أجازة.",
            "لتغيير يوم واحد بس استخدم «عدّل يوم واحد» واكتب السبب.",
            "اضغط «احفظ».",
        ],
        [
            "In the «People» section open «Schedules» and pick the employee.",
            "In the «Weekly roster» press «Add a roster day» and pick the day and the shift. A day with no row is a day off.",
            "To change one day only use «Override one day» and write the reason.",
            "Press «Save».",
        ],
        cap="can_manage_attendance",
    ),
    _guide(
        "hr-shifts", (Role.HR, Role.ADMIN), "/hr/shifts",
        ("إزاي أضيف أو أعدّل شيفت", "How do I add or edit a shift"),
        (
            "شيفت جديد، الشيفتات، عدّل شيفت، مواعيد الشيفت، شيفتات الشركة، ضيف شيفت",
            "new shift, shifts, edit a shift, shift hours, company shifts, add a shift",
        ),
        [
            "من قسم «الموظفين» افتح «الشيفتات».",
            "اضغط «شيفت جديد» واكتب الاسم والمواعيد (لو بيعدّي نص الليل علّمه) واضغط «احفظ».",
            "للتعديل اضغط «عدّل» على الشيفت. «احذف» مابتشتغلش لو الشيفت عليه موظفين.",
        ],
        [
            "In the «People» section open «Shifts».",
            "Press «New shift», write the name and hours (tick it if it crosses midnight) and press «Save».",
            "To change one press «Edit» on it. «Delete» refuses while staff are on the shift.",
        ],
        cap="can_manage_attendance",
    ),
    _guide(
        "hr-leave", (Role.HR, Role.ADMIN), "/hr/leave",
        ("إزاي أوافق على إجازة أو أرفضها", "How do I approve or reject a leave request"),
        (
            "طلبات الإجازة، وافق على إجازة، ارفض إجازة، قرار الإجازة، إجازات الموظفين",
            "leave requests, approve leave, reject leave, decide on leave, staff leave",
        ),
        [
            "من قسم «الموظفين» افتح «طلبات الإجازة».",
            "الطلبات المستنية فوق («مستني قرار»). راجع الأيام والسبب.",
            "اضغط «وافق» أو «ارفض».",
        ],
        [
            "In the «People» section open «Leave requests».",
            "The waiting ones are at the top («Waiting»). Check the dates and the reason.",
            "Press «Approve» or «Reject».",
        ],
        cap="can_manage_attendance",
    ),
    _guide(
        "hr-overtime", (Role.HR, Role.ADMIN), "/hr/overtime",
        ("إزاي أعتمد الأوفرتايم", "How do I approve overtime"),
        (
            "اعتمد الأوفرتايم، أوفرتايم، الأوفرتايم، ساعات إضافية، ارفض الأوفرتايم، اكسترا",
            "approve overtime, overtime, extra hours, reject overtime, extra",
        ),
        [
            "من قسم «الموظفين» افتح «الأوفرتايم».",
            "راجع الوقت والمبلغ لكل مطالبة «مستنية اعتماد».",
            "اضغط «اعتمد» أو «ارفض».",
        ],
        [
            "In the «People» section open «Overtime».",
            "Check the time and the amount of each claim «Waiting for approval».",
            "Press «Approve» or «Reject».",
        ],
        cap="can_manage_attendance",
    ),
    _guide(
        "hr-report", (Role.HR, Role.ADMIN), "/hr/report",
        ("إزاي أطلّع تقرير حضور شهري لموظف", "How do I get an employee's monthly attendance report"),
        (
            "التقرير الشهري، تقرير الحضور، تقرير موظف، حضور الشهر، يوم بيوم",
            "monthly report, attendance report, employee report, the month's attendance, day by day",
        ),
        [
            "من قسم «الموظفين» افتح «التقرير الشهري».",
            "اختار الموظف والشهر.",
            "هتلاقي «الملخص» و«يوم بيوم». لو فيه أيام لسه محتاجة مراجعة بيتنبّهك فوق.",
        ],
        [
            "In the «People» section open «Monthly report».",
            "Pick the employee and the month.",
            "You will find the «Summary» and «Day by day». A warning at the top says if some days still need review.",
        ],
        cap="can_manage_attendance",
    ),
    _guide(
        "hr-offices", (Role.HR, Role.ADMIN), "/hr/offices",
        ("إزاي أضيف موقع مكتب لفحص الحضور", "How do I add an office location for the attendance check"),
        (
            "مواقع المكاتب، موقع المكتب، نطاق الحضور، الجيو، اضافة مكتب، فحص الموقع",
            "office locations, office, attendance radius, geofence, add an office, location check",
        ),
        [
            "من قسم «الإعدادات» افتح «مواقع المكاتب».",
            "اضغط «ضيف مكتب»، اكتب الاسم و«النطاق» بالمتر.",
            "وانت في المكتب اضغط «استخدم موقعي الحالي» (أو اكتب الإحداثيات بإيدك) واضغط «احفظ».",
        ],
        [
            "In the «Settings» section open «Office locations».",
            "Press «Add an office» and write the name and the «Radius» in metres.",
            "While at the office press «Use my current location» (or type the coordinates) and press «Save».",
        ],
        cap="can_manage_attendance",
    ),
    _guide(
        "hr-devices", (Role.HR, Role.ADMIN), "/hr/devices",
        ("إزاي أوافق على جهاز موظف للحضور", "How do I approve an employee's device for attendance"),
        (
            "أجهزة الحضور، جهاز الموظف، وافق على جهاز، اعتمد الجهاز، موبايل الموظف",
            "attendance devices, employee's device, approve a device, phone",
        ),
        [
            "من قسم «الإعدادات» افتح «أجهزة الحضور».",
            "الأجهزة «مستنية موافقة» هتلاقيها فوق.",
            "اضغط «اعتمد» أو «ارفض».",
        ],
        [
            "In the «Settings» section open «Attendance devices».",
            "The devices «Waiting for approval» are at the top.",
            "Press «Approve» or «Reject».",
        ],
        cap="can_manage_attendance",
    ),
    _guide(
        "hr-vacancy", (Role.HR, Role.ADMIN), "/hr/vacancies",
        ("إزاي أفتح وظيفة جديدة", "How do I open a new vacancy"),
        (
            "وظيفة جديدة، الوظائف، اعلان وظيفة، افتح وظيفة، وظيفة، أسئلة البوت للوظيفة",
            "new vacancy, vacancies, job ad, open a vacancy, job, the bot's questions for the vacancy",
        ),
        [
            "من قسم «التوظيف» افتح «الوظائف».",
            "اضغط «وظيفة جديدة»، اكتب «المسمى» واختار «القسم» و«النظام» واضغط «احفظ».",
            "بعد الحفظ افتح الوظيفة واختار «أسئلة البوت للوظيفة دي» بـ«ضيف سؤال» ورتّبها واضغط «احفظ الترتيب».",
        ],
        [
            "In the «Recruitment» section open «Vacancies».",
            "Press «New vacancy», write the «Title», pick the «Department» and «Mode» and press «Save».",
            "After saving open the vacancy and choose «The bot's questions» with «Add a question», order them and press «Save the order».",
        ],
        cap="can_recruit",
        starter=True,
    ),
    _guide(
        "hr-candidates", (Role.HR, Role.ADMIN), "/hr/candidates",
        ("إزاي أتابع مرشح (حالة ورسالة واختبار ومقابلة)", "How do I handle a candidate (status, message, test, interview)"),
        (
            "مرشح، المرشحين، متقدم، اتابع مرشح، غيّر حالة المرشح، ابعت رسالة لمرشح، اختبار مرشح، مقابلة، حدد مقابلة، لوحة التوظيف",
            "candidate, candidates, applicant, handle a candidate, change the candidate's status, message a candidate, test, interview, schedule an interview",
        ),
        [
            "من قسم «التوظيف» افتح «المرشحين» (أو «لوحة التوظيف» لآخر المتقدمين) وادخل على المرشح.",
            "لتغيير حالته اختار «الحالة الجديدة» واضغط «انقل».",
            "لرسالة اضغط «ابعتله رسالة» واكتبها واضغط «ابعت». الرسالة بتخرج من رقم التوظيف وبتعدي على فلتر إخفاء هوية الشركة.",
            "لاختبار اضغط «اضبط اختبار»، ولمقابلة اضغط «حدّد مقابلة»، وبعد المقابلة اضغط «قيّم» وسجّل الدرجات.",
        ],
        [
            "In the «Recruitment» section open «Candidates» (or the «Recruitment board» for the latest applicants) and go into the candidate.",
            "To change the status pick the «New status» and press «Move».",
            "For a message press «Message the candidate», write it and press «Send». It leaves from the recruitment number and passes the company-identity filter.",
            "For a test press «Set a test», for an interview press «Schedule an interview», and after it press «Score» and record the marks.",
        ],
        cap="can_recruit",
        starter=True,
    ),
    _guide(
        "hr-hire", (Role.HR, Role.ADMIN), "/hr/candidates",
        ("إزاي أعيّن مرشح موظف", "How do I hire a candidate"),
        (
            "عيّن مرشح، تعيين، حوّله لموظف، وظّف، موافقة المالك، عيّنه، تعيين موظف جديد",
            "hire a candidate, hiring, make an employee, take on, owner approval",
        ),
        [
            "التعيين مابيحصلش تلقائي: لازم المالك يوافق الأول من «موافقات التعيين».",
            "بعد الموافقة افتح المرشح من «المرشحين» واضغط «حوّله لموظف».",
            "راجع «بيانات التعاقد» (الشيفت والقسم والراتب المتفق عليه) واضغط «عيّنه».",
            "هتلاقيه بعد كده في «ملفات الموظفين» وبتفتحله «ملف الموظف».",
        ],
        [
            "Hiring is never automatic: the owner must approve first under «Hiring approvals».",
            "After approval open the candidate from «Candidates» and press «Make an employee».",
            "Check the «Contract details» (shift, department and agreed salary) and press «Hire».",
            "You will then find them in «Employee files» and open their «Employee file».",
        ],
        cap="can_recruit",
    ),
    _guide(
        "hr-employee-file", (Role.HR, Role.ADMIN), "/hr/employees",
        ("إزاي أفتح ملف موظف", "How do I open an employee's file"),
        (
            "ملف الموظف، ملفات الموظفين، بيانات الموظف، حضور الموظف، سجل الراتب، الموظفين، فتح ملف موظف",
            "employee file, employee files, employee details, employee's attendance, salary history, staff, open an employee's file",
        ),
        [
            "من قسم «الموظفين» افتح «ملفات الموظفين».",
            "فلتر بالقسم أو الحالة، واضغط على الموظف.",
            "هتلاقي «البيانات» و«حضور الشهر ده» و«إجازات» و«فترة الاختبار» و«سجل الراتب»، وفوقهم «التقرير الكامل».",
        ],
        [
            "In the «People» section open «Employee files».",
            "Filter by department or status and press the employee.",
            "You will find the «Details», «Attendance this month», «Leave», «Probation» and «Salary history», with the «Full report» above them.",
        ],
        cap="can_recruit",
    ),
    _guide(
        "hr-star-penalties", (Role.HR, Role.ADMIN), "/hr/employees",
        ("إزاي أقرر في خصم نجوم من موظف", "How do I decide on stars taken off an employee"),
        (
            "خصم نجوم، خصم التقييم، سامح الموظف، طبّق الخصم، خصومات مستنية، تقييم الموظف، النجوم",
            "stars taken off, rating penalty, forgive an employee, apply a penalty, waiting penalties, employee rating, stars",
        ),
        [
            "افتح «الموظفين». فوق السجل هتلاقي «خصومات نجوم مستنية قرار» فيها اسم الموظف وعدد النجوم والسبب والتاسك.",
            "النجوم اتخصمت فعلًا. اضغط «طبّق الخصم» عشان يفضل زي ما هو، أو «سامحه وارجّع النجوم» عشان النجوم ترجع للموظف ويتبلّغ.",
            "تقدر تكتب ملاحظة قبل ما تقرر. الخصم بيتقرر فيه مرة واحدة، وبيفضل ظاهر في ملف الموظف تحت «خصومات التقييم» بإسم اللي قرر.",
        ],
        [
            "Open «Employees». Above the register you will find «Star penalties waiting for a decision» with the employee, the stars, the reason and the task.",
            "The stars are already off. Press «Apply it» to keep the penalty, or «Forgive and give the stars back» to return the stars to the employee, who is told.",
            "You may write a note first. A penalty is decided once, and stays on the employee's file under «Rating penalties» with who decided it.",
        ],
        cap="can_recruit",
    ),
    _guide(
        "hr-probation", (Role.HR, Role.ADMIN), "/hr/probation",
        ("إزاي أتابع فترة اختبار موظف", "How do I follow an employee's probation"),
        (
            "فترة الاختبار، فترة تجربة، مراجعة الموظف الجديد، قرّر في الموظف، تحت الاختبار",
            "probation, trial period, review a new employee, decide on an employee, on probation",
        ),
        [
            "من قسم «الموظفين» افتح «فترة الاختبار».",
            "«تحت الاختبار» فيها كل اللي لسه في الفترة؛ افتح المراجعات المستحقة بـ«افتح المراجعات».",
            "اضغط «قرّر» وسجّل التقييم والنتيجة واضغط «احفظ».",
        ],
        [
            "In the «People» section open «Probation».",
            "«On probation» lists everybody still in the period; open the due ones with «Open the reviews».",
            "Press «Decide», record the score and the outcome and press «Save».",
        ],
        cap="can_recruit",
    ),
    _guide(
        "hr-complaint", (Role.HR, Role.ADMIN), "/hr/complaints",
        ("إزاي أسجّل شكوى عميل على مترجم", "How do I log a client complaint about a translator"),
        (
            "شكوى، شكاوى العملاء، سجل شكوى، شكوى على مترجم، اقفل الشكوى",
            "complaint, client complaints, log a complaint, complaint about a translator, resolve the complaint",
        ),
        [
            "من قسم «الموظفين» افتح «شكاوى العملاء».",
            "اضغط «سجّل شكوى»، اختار المترجم والتاسك (بالكود) واكتب الشكوى والدرجة.",
            "اضغط «سجّل». لما تتحل اضغط «اقفلها».",
        ],
        [
            "In the «People» section open «Complaints».",
            "Press «Log a complaint», pick the translator and the task (by code) and write the complaint and its severity.",
            "Press «Log». When it is settled press «Resolve».",
        ],
        cap="can_recruit",
    ),
    _guide(
        "hr-salary-request", (Role.HR, Role.ADMIN), "/hr/salary-requests",
        ("إزاي أطلب تغيير راتب موظف", "How do I ask for a change to an employee's salary"),
        (
            "تغيير الراتب، زيادة الراتب، طلب راتب، طلبات تغيير الراتب، اطلب زيادة، علاوة",
            "salary change, raise, salary request, ask for a raise, pay rise",
        ),
        [
            "من قسم «الموظفين» افتح «طلبات تغيير الراتب».",
            "اضغط «اطلب تغيير»، اختار الموظف واكتب الراتب الجديد و«ساري من» والسبب.",
            "اضغط «ابعت للمالك». المالك هو اللي بيوافق؛ مفيش حد غيره بيحدد الراتب.",
        ],
        [
            "In the «People» section open «Salary requests».",
            "Press «Request a change», pick the employee and write the new salary, «Effective» date and the reason.",
            "Press «Send to the owner». Only the owner decides; nobody else sets a salary.",
        ],
        cap="can_recruit",
    ),
    _guide(
        "hr-questions", (Role.HR, Role.ADMIN), "/hr/questions",
        ("إزاي أضيف سؤال لبنك أسئلة التوظيف", "How do I add a question to the recruitment question bank"),
        (
            "بنك الأسئلة، سؤال جديد، أسئلة التوظيف، أسئلة البوت، ضيف قسم",
            "question bank, new question, recruitment questions, the bot's questions, add a department",
        ),
        [
            "من قسم «الإعدادات» افتح «بنك الأسئلة».",
            "اضغط «سؤال جديد» واكتب السؤال واختار القسم والنوع واضغط «احفظ».",
            "لقسم جديد استخدم «ضيف قسم». السؤال بيتختار بعد كده لأي وظيفة.",
        ],
        [
            "In the «Settings» section open «Question bank».",
            "Press «New question», write the question, pick the department and type and press «Save».",
            "For a new department use «Add». The question can then be chosen for any vacancy.",
        ],
        cap="can_recruit",
    ),
    # ------------------------------------------------------------------------------------------------------------------
    # Accounting.
    # ------------------------------------------------------------------------------------------------------------------
    _guide(
        "acc-month", (Role.ACCOUNTING, Role.ADMIN), "/accounts",
        ("إزاي أحسب مستحقات الشهر وأقفله", "How do I run the month's payroll and lock it"),
        (
            "كشف الشهر، احسب الشهر، حسابات المترجمين، اعتماد الشهر، اقفل الشهر، المرتبات، مرتبات الشهر، قفل الشهر",
            "the month, run the month, translator payroll, approve the month, lock the month, salaries, close the month",
        ),
        [
            "من قسم «الحسابات» افتح «كشف الشهر» واختار الشهر.",
            "اضغط «احسب الشهر». لو فيه مترجمين من غير راتب مسجل هيتنبّهك (سطرهم هيطلع بصفر).",
            "راجع الأسطر و«خصومات مستنية الاعتماد» الأول.",
            "اضغط «اعتماد». وبعد ما تتأكد خالص اضغط «اقفل الشهر» وأكّد.",
        ],
        [
            "In the «Accounts» section open «Monthly payroll» and pick the month.",
            "Press «Run the month». If some translators have no salary on record you are warned (their line computes to zero).",
            "Check the lines and the «Deductions awaiting approval» first.",
            "Press «Approve». When you are completely sure press «Lock it» and confirm.",
        ],
        note=(
            "الشهر المقفول مابيتحسبش تاني ومفيش رجوع.",
            "A locked month is never computed again and there is no way back.",
        ),
        starter=True,
    ),
    _guide(
        "acc-violation", (Role.ACCOUNTING, Role.ADMIN), "/accounts/violations",
        ("إزاي أسجّل مخالفة أو خصم وأعتمده", "How do I record a violation or deduction and approve it"),
        (
            "مخالفة، خصم، المخالفات والخصومات، سجل مخالفة، اعتمد الخصم، ارفض الخصم، خصم من المترجم",
            "violation, deduction, violations and deductions, record a violation, approve the deduction, reject the deduction",
        ),
        [
            "من قسم «الحسابات» افتح «المخالفات والخصومات».",
            "اضغط «سجل مخالفة» واختار المترجم والنوع والتاريخ والتاسك (بالكود) والسبب، واضغط «سجل». بتتسجل «مستنية الاعتماد».",
            "في «مستنية الاعتماد» اضغط «اعتماد» أو «رفض».",
        ],
        [
            "In the «Accounts» section open «Violations».",
            "Press «Record a violation» and pick the translator, kind, date, task (by code) and reason, then press «Record». It is saved «Awaiting approval».",
            "Under «Awaiting approval» press «Approve» or «Reject».",
        ],
        note=(
            "مفيش خصم بيتطبق قبل اعتماده.",
            "No deduction applies before it is approved.",
        ),
        starter=True,
    ),
    _guide(
        "acc-salary", (Role.ACCOUNTING, Role.ADMIN), "/accounts",
        ("إزاي أشوف راتب مترجم وتاريخه", "How do I see a translator's salary and its history"),
        (
            "راتب المترجم، سجل الراتب، الرواتب، الراتب القديم، تاريخ الراتب، راتب جديد",
            "translator's salary, salary history, salaries, old salary, new salary",
        ),
        [
            "افتح «كشف الشهر» من قسم «الحسابات».",
            "اضغط على المترجم وبعدين «سجل الراتب».",
            "هتلاقي «الشهور المحسوبة» وكل راتب وساري من إمتى. الراتب القديم مابيتمسحش.",
        ],
        [
            "Open «Monthly payroll» in the «Accounts» section.",
            "Press the translator and then «Salary history».",
            "You will find the «Computed months» and every salary with its effective date. An old salary is never overwritten.",
        ],
        note=(
            "الراتب بيحدده المالك بس. الحسابات بتقراه وبتصرفه، وأي تغيير بيطلبه الـHR والمالك بيوافق.",
            "Only the owner sets a salary. Accounts reads and pays it, and a change is asked for by HR and approved by the owner.",
        ),
    ),
    _guide(
        "acc-rules", (Role.ADMIN,), "/accounts/rules",
        ("إزاي أغيّر قواعد حساب المستحقات", "How do I change the payroll rules"),
        (
            "قواعد الحساب، قواعد المستحقات، شرائح البونص، التارجت، الحد اليومي، بونص الإنتاج",
            "payroll rules, bonus bands, target, daily floor, production bonus",
        ),
        [
            "من قسم «الإعدادات» افتح «قواعد الحساب».",
            "عدّل الأرقام (التارجت الشهري والحد اليومي والشرائح) أو اضغط «ضيف شريحة».",
            "اضغط «حفظ». الأرقام بتتغيّر من غير ما حد يفتح الكود.",
        ],
        [
            "In the «Settings» section open «Payroll rules».",
            "Change the numbers (the monthly target, the daily floor and the bands) or press «Add a band».",
            "Press «Save». The numbers change without anyone touching the code.",
        ],
    ),
    # ------------------------------------------------------------------------------------------------------------------
    # The owner.
    # ------------------------------------------------------------------------------------------------------------------
    _guide(
        "admin-overview", (Role.ADMIN,), "/admin",
        ("فين نظرة عامة على الشغل", "Where is the overview of the work"),
        (
            "نظرة عامة، لوحة الأدمن، الأوفرفيو، تاسكات متأخرة، تاسكات جديدة، تأكيدات مستنية",
            "overview, admin panel, late tasks, new tasks, pending confirmations",
        ),
        [
            "من قسم «الشغل» افتح «نظرة عامة».",
            "هتلاقي عدد «تاسكات جديدة» و«تاسكات عدّت الديدلاين» و«تأكيدات مستنية»، و«آخر التاسكات»، والرسايل المحجوبة عن الأوبريشن.",
        ],
        [
            "In the «Work» section open «Overview».",
            "You will find the counts of «New tasks», «Late tasks» and «Pending confirmations», the «Latest tasks», and the messages hidden from Operation.",
        ],
    ),
    _guide(
        "admin-employee-new", (Role.ADMIN,), "/hr/employees/new",
        ("إزاي أضيف موظف جديد", "How do I add a new staff member"),
        (
            "موظف جديد، اضافة موظف، اعمل حساب لموظف، ضيف موظف، يوزر جديد، حساب جديد",
            "new staff member, add an employee, make an account, add staff, new user",
        ),
        [
            "من قسم «الموظفين» افتح «ملفات الموظفين».",
            "اضغط «موظف جديد».",
            "اكتب اسم المستخدم والاسم والإيميل والموبايل واختار الدور، والتيم ليدر للمترجم، واكتب كلمة السر مرتين.",
            "اضغط «حفظ». سلّم الموظف كلمة السر بنفسك؛ هو يقدر يغيّرها من البروفايل.",
        ],
        [
            "In the «People» section open «Employee files».",
            "Press «New staff member».",
            "Write the username, name, e-mail and phone, pick the role (and the team leader for a translator) and type the password twice.",
            "Press «Save». Give the employee the password yourself; they can change it from their profile.",
        ],
        starter=True,
    ),
    _guide(
        "admin-support-account", (Role.ADMIN,), "/hr/employees",
        ("إزاي أعمل حساب الدعم الفني", "How do I make the technical-support account"),
        (
            "الدعم الفني، حساب الدعم، حساب دعم فني، موظف دعم، سبورت، ادّي حد دعم فني، account الدعم",
            "technical support, support account, make a support account, support staff, give someone support",
        ),
        [
            "من قسم «الموظفين» افتح «ملفات الموظفين» واضغط «موظف جديد».",
            "اكتب اسم المستخدم والاسم وكلمة السر، واختار الدور «دعم فني».",
            "اضغط «حفظ». الموظفين كلهم هيلاقوا الحساب ده في «الشات» تحت «الزمايل» وعليه شارة «دعم فني»، وفي المساعد زرار «تواصل مع الدعم الفني».",
        ],
        [
            "In the «People» section open «Employee files» and press «New staff member».",
            "Write the username, name and password, and pick the role «Technical support».",
            "Press «Save». Everybody will find the account in «Chats» under «Colleagues» with a «Technical support» tag, and the assistant has a «Contact technical support» button.",
        ],
        note=(
            "الحساب ده بيشوف التاسكات (مين عليها وحالتها وديدلاينها) من غير ملفات العميل ولا رسايله ولا اسمه، ومابيعدّلش حاجة. ومالوش حضور ولا جدول ولا إجازات ولا حسابات، وريستارت الموظفين مابيمسحوش.",
            "This account reads the tasks (who has them, their state and deadlines) without the client's files, messages or name, and changes nothing. It has no attendance, schedule, leave or pay, and the staff reset leaves it alone.",
        ),
    ),
    _guide(
        "admin-mail-alias", (Role.ADMIN,), "/hr/employees",
        ("إزاي أحدد إيميل لموظف أوبريشن أو Sales", "How do I give an operation or Sales person their own mail address"),
        (
            "إيميل الموظف، عنوان الميل، alias، بيستقبل ميلات العنوان ده، ميل خاص بالموظف، ربط إيميل بموظف",
            "employee's e-mail, mail address, alias, receives mail for this address, a person's own mailbox, assign an address",
        ),
        [
            "افتح «ملفات الموظفين» وادخل على الموظف (أوبريشن أو Sales).",
            "في كارت «الحساب والصلاحيات» اختار العنوان من «بيستقبل ميلات العنوان ده».",
            "اضغط «حفظ». الميل على العنوان ده بيروحله هو والأدمن، وردّه بيطلع منه.",
        ],
        [
            "Open «Employee files» and go into the person (operation or Sales).",
            "In the «Account and access» card pick the address under «Receives mail for».",
            "Press «Save». Mail to that address goes to them and to the admin, and their reply leaves from it.",
        ],
        note=(
            "عنوان واحد لكل موظف. القايمة من العناوين الموجودة على ميل الشركة في الإعدادات، وأي عنوان جديد لازم يتضاف alias في Google الأول.",
            "One address per person. The list comes from the aliases on the company mailbox in the settings, and a new address must first be added as an alias in Google.",
        ),
        starter=True,
    ),
    _guide(
        "admin-identity-access", (Role.ADMIN,), "/hr/employees",
        ("إزاي أدّي حد صلاحية يشوف هوية العميل", "How do I let someone see a client's identity"),
        (
            "هوية العميل، اسم العميل، صلاحية الهوية، يشوف اسم العميل، صلاحية الحسابات، إخفاء الاسم",
            "client identity, client name, identity access, see the client's name, accounting access, hidden name",
        ),
        [
            "افتح «ملفات الموظفين» وادخل على الشخص.",
            "في «الحساب والصلاحيات» علّم خانة يشوف هوية العميل الحقيقية.",
            "اضغط «حفظ». كل تغيير وكل فتح بعده بيتسجل في «سجل النشاط».",
        ],
        [
            "Open «Employee files» and go into the person.",
            "In «Account and access» tick the box that lets them see the client's real identity.",
            "Press «Save». Every change and every opening afterwards is written to the «Audit log».",
        ],
        note=(
            "الصلاحية دي لـAccounting بس. الأوبريشن والتيم ليدر والمترجم مستحيل يشوفوا الهوية حتى لو الخانة معلّمة، والـSales بيشوفها دايمًا.",
            "It is for Accounting only. Operation, team leaders and translators can never see it even if the box is ticked, and Sales always do.",
        ),
    ),
    _guide(
        "admin-hire-approve", (Role.ADMIN,), "/hr/approvals",
        ("إزاي أوافق على تعيين مرشح", "How do I approve hiring a candidate"),
        (
            "موافقات التعيين، وافق على التعيين، ارفض مرشح، قرار التعيين، المالك يوافق",
            "hiring approvals, approve the hire, reject a candidate, hiring decision, owner approval",
        ),
        [
            "من قسم «التوظيف» افتح «موافقات التعيين».",
            "في «مستني قرارك» راجع «توصية HR:» ودرجة الاختبار والمقابلة والـCV والراتب المتوقع.",
            "اضغط «وافق على التعيين»، أو «ارفض» واكتب «سبب الرفض».",
        ],
        [
            "In the «Recruitment» section open «Hiring approvals».",
            "Under «Waiting for you» check the «HR recommendation:», the test and interview scores, the CV and the expected salary.",
            "Press «Approve», or «Reject» and write the «Reason for rejecting».",
        ],
    ),
    _guide(
        "admin-settings", (Role.ADMIN,), "/admin/settings",
        ("فين الإعدادات (واتساب والإيميل والـAI)", "Where are the settings (WhatsApp, e-mail, AI)"),
        (
            "الإعدادات، إعدادات النظام، واتساب، إعداد الإيميل، مفتاح Claude، الـ AI، التوكن، IMAP، SMTP، فعّل المراجعة",
            "settings, system settings, WhatsApp, e-mail setup, Claude key, AI, token, IMAP, SMTP, switch on the check",
        ),
        [
            "من قسم «الإعدادات» افتح «الإعدادات و AI».",
            "الصفحة أقسام: «مراجعة الترجمة بالـ AI» و«قواعد الشغل» و«واتساب» و«الإيميل».",
            "عدّل واضغط حفظ. الأسرار (التوكنات والباسوردات ومفتاح Claude) بتلصقها انت بنفسك؛ مابتظهرش تاني بعد الحفظ، وسيبها فاضية لو مش عايز تغيّرها.",
        ],
        [
            "In the «Settings» section open «Settings & AI».",
            "The page has sections: «AI translation check», «Workflow rules», «WhatsApp» and «Email».",
            "Change and save. You paste the secrets (tokens, passwords and the Claude key) yourself; they are never shown again after saving, and leaving one empty keeps it.",
        ],
        starter=True,
    ),
    _guide(
        "admin-ai-assistant", (Role.ADMIN,), "/admin/settings",
        ("إزاي أشغّل المساعد بالـAI", "How do I switch the assistant's AI on"),
        (
            "المساعد، شات بوت، المساعد الذكي، فعّل المساعد، المساعد بالـ AI، بوت المساعدة",
            "the assistant, chatbot, help bot, switch on the assistant, assistant AI",
        ),
        [
            "افتح «الإعدادات و AI» من قسم «الإعدادات».",
            "في «مراجعة الترجمة بالـ AI» تأكد إن مفتاح Claude محفوظ (لصقه بإيدك).",
            "في «مساعد النظام» علّم «خلّي المساعد يرد بالـ AI» واحفظ.",
        ],
        [
            "Open «Settings & AI» in the «Settings» section.",
            "In «AI translation check» make sure the Claude key is saved (you paste it yourself).",
            "In «The help assistant» tick «Let the assistant answer with the AI» and save.",
        ],
        note=(
            "المساعد بيرد من دليل الخطوات حتى من غير ده. لو فعّلته بيبعت سؤال الموظف ودليل دوره بس لـ Claude، بعد ما بيشيل منه الإيميلات والأرقام والمفاتيح وأسماء العملاء المعروفة (بتتحوّل لكود العميل). ومفيش حاجة من الشغل بتتبعت. نبّه الموظفين ما يكتبوش بيانات عملاء. الأسئلة اللي ملهاش رد بتشوفها في لوحة Django (Help questions).",
            "The assistant answers from the step guides even without this. When on it sends only the person's question and their role's guides to Claude, after taking out e-mails, numbers, keys and known clients' names (a name becomes the client's code). Nothing from the work is sent. Tell staff not to type client details. Questions with no answer are in Django's admin (Help questions).",
        ),
    ),
    _guide(
        "admin-assistant-orders", (Role.ADMIN,), "/admin/settings",
        ("إزاي أخلّي المساعد ينفّذ أوامر (شيفت، خصم، إجازة...)", "How do I let the assistant carry out orders (a shift, a deduction, leave...)"),
        (
            "أوامر المساعد، نفّذ أمر، خلي البوت ينفذ، اعمل شيفت بالمساعد، اخصم بالمساعد، الشات بوت ينفذ أوامر، تنفيذ الأوامر، أمر للمساعد",
            "assistant orders, carry out an order, let the bot do it, make a shift with the assistant, deduct with the assistant, give the assistant an order",
        ),
        [
            "افتح «الإعدادات و AI». في «مساعد النظام» علّم «خلّي المساعد يرد بالـ AI» وبعدها «خلّي المساعد ينفّذ أوامري (للأدمن بس)» واحفظ. مفتاح Claude لازم يكون محفوظ (بتلصقه انت).",
            "اضغط «المساعد» في الشريط اللي فوق واكتب الأمر بكلامك، مثلًا: اعمل شيفت من 9 لـ 5، أو اخصم يوم من (اسم المترجم) بسبب كذا.",
            "بيظهر كارت فيه اللي هيتنفّذ بالظبط. راجعه واضغط «نفّذ»، أو «إلغاء» لو مش عايزه.",
            "الأوامر المتاحة: عمل شيفت، تسجيل خصم، أجازة أو ساعات مختلفة ليوم واحد، قرار في طلب إجازة، إلغاء تاسك، إسناد تاسك لتيم ليدر، متطلب لعميل، إيقاف أو تفعيل حساب، وعنوان ميل لموظف.",
        ],
        [
            "Open «Settings & AI». Under «The help assistant» tick «Let the assistant answer with the AI» and then «Let the assistant carry out my orders (admin only)», and save. The Claude key must be saved (you paste it yourself).",
            "Press «Assistant» in the bar at the top and write the order in your own words, for example: make a shift from 9 to 5, or deduct a day from (the translator's name) for this reason.",
            "A card shows exactly what will be done. Check it and press «Run», or «Cancel» if you do not want it.",
            "The orders it can take: make a shift, record a deduction, a day off or other hours for one day, decide a leave request, cancel a task, give a task to a team leader, add a client requirement, switch an account off or on, and give an employee a mail address.",
        ],
        note=(
            "ماينفّذش حاجة من غير ضغطتك. الخصم بيتسجل «مستنية الاعتماد» زي أي خصم ومابيتعتمدش لوحده. كل أمر بيتنفّذ بيتسجل في «سجل النشاط»، والخيار ده ليك انت بس.",
            "Nothing runs without your press. A deduction is recorded as waiting for approval like any other and is never approved by itself. Every order that ran is written to the «Audit log», and this works for you alone.",
        ),
    ),
    _guide(
        "admin-google", (Role.ADMIN,), "/admin/settings",
        ("إزاي أربط Google لقايمة عناوين الميل", "How do I link Google for the mail address list"),
        (
            "اربط Google، جوجل، قايمة العناوين، aliases، مزامنة العناوين، ربط جوجل",
            "connect Google, Google, address list, aliases, sync addresses, link Google",
        ),
        [
            "افتح «الإعدادات و AI» ثم قسم «الإيميل».",
            "في «مزامنة العناوين مع Google» املا «Client ID» و«Client Secret» (بتلصقهم انت) واحفظ.",
            "انسخ عنوان إعادة التوجيه اللي بتحطه في Authorized redirect URIs في Google Cloud.",
            "اضغط «اربط Google» ووافق على قراءة العناوين بس.",
        ],
        [
            "Open «Settings & AI» and then the «Email» section.",
            "Under «Sync aliases with Google» fill the «Client ID» and «Client Secret» (you paste them) and save.",
            "Copy the redirect address and add it to Authorized redirect URIs in Google Cloud.",
            "Press «Connect Google» and allow read access to the addresses only.",
        ],
    ),
    _guide(
        "admin-clients", (Role.ADMIN,), "/admin/clients",
        ("إزاي أشوف أو أعدّل بيانات العملاء الحقيقية", "How do I see or edit the clients' real details"),
        (
            "بيانات العملاء، اسم العميل الحقيقي، عميل جديد، عدّل عميل، رقم العميل، إيميل العميل",
            "client records, the client's real name, new client, edit a client, the client's number, the client's e-mail",
        ),
        [
            "افتح «بيانات العملاء» من قسم «الشغل».",
            "دوّر بالكود أو الاسم أو التليفون أو الإيميل.",
            "اضغط «تعديل» لتعديل عميل، أو «عميل جديد» لإضافة واحد، واحفظ.",
        ],
        [
            "Open «Client records» in the «Work» section.",
            "Search by code, name, phone or e-mail.",
            "Press «Edit» to change a client, or «New client» to add one, and save.",
        ],
        note=(
            "الصفحة دي للأدمن بس وفيها الأسماء والأرقام الحقيقية. كل فتح للهوية بيتسجل في «سجل النشاط».",
            "This page is the admin's only and holds the real names and numbers. Every opening of an identity is written to the «Audit log».",
        ),
    ),
    _guide(
        "admin-delete-clients", (Role.ADMIN,), "/admin/clients",
        ("إزاي أمسح عملاء", "How do I delete clients"),
        (
            "امسح عميل، مسح العملاء، احذف عميل، امسح المحدّد، مسح نهائي للعملاء",
            "delete a client, delete clients, remove a client, delete selected",
        ),
        [
            "افتح «بيانات العملاء» وعلّم العملاء (أو «حدّد الكل»).",
            "اضغط «امسح المحدّد» وراجع اللي هيتمسح.",
            "علّم خانة الفهم (إن ده مسح نهائي)، واكتب «باسورد الأدمن بتاعك»، واضغط «امسح العملاء دول». هتنزل نسخة احتياطية.",
        ],
        [
            "Open «Client records» and tick the clients (or «Select all»).",
            "Press «Delete selected» and check what goes.",
            "Tick the box saying you understand it is permanent, type «Your admin password» and press «Delete these clients». A backup downloads.",
        ],
        note=(
            "مفيش رجوع. العميل اللي عليه تاسكات شغالة مش بيتمسح.",
            "There is no undo. A client with running tasks is not deleted.",
        ),
    ),
    _guide(
        "admin-simulate", (Role.ADMIN,), "/admin/simulate",
        ("إزاي أجرّب رسالة عميل من غير واتساب", "How do I try a client message without WhatsApp"),
        (
            "محاكاة رسالة، جرّب رسالة، رسالة تجريبية، محاكاة عميل، اختبار الفلو",
            "simulate a message, try a message, test message, simulate a client, test the flow",
        ),
        [
            "من قسم «الإعدادات» افتح «محاكاة رسالة».",
            "اختار «القناة» واكتب «رقم / إيميل العميل» و«نص الرسالة» (و«الموضوع» للإيميل).",
            "اضغط «ابعت». الرسالة بتنزل زي رسالة عميل حقيقي.",
        ],
        [
            "In the «Settings» section open «Simulate message».",
            "Pick the «Channel» and write the «Client phone / email» and the «Message body» (and the «Subject» for e-mail).",
            "Press «Send». The message arrives like a real client's.",
        ],
        note=(
            "لو النص فيه كلمة rate الرسالة بتتحجب عن الأوبريشن وتظهر للأدمن بس.",
            "If the text contains the word rate the message is hidden from Operation and shown to the admin only.",
        ),
    ),
    _guide(
        "admin-audit", (Role.ADMIN,), "/admin/audit",
        ("فين سجل النشاط", "Where is the audit log"),
        (
            "سجل النشاط، اللوج، مين فتح، مين عمل إيه، سجل الأمان، مراقبة، رفض صلاحية",
            "audit log, the log, who opened, who did what, security log, monitoring, denied access",
        ),
        [
            "من قسم «الإعدادات» افتح «سجل النشاط».",
            "كل صف فيه «الشخص» و«الحدث» و«الهدف» و«من فين» والوقت.",
            "«حدّث» بيجيب الجديد و«الأقدم» بيجيب الأقدم.",
        ],
        [
            "In the «Settings» section open «Audit log».",
            "Each row has the «Actor», «Action», «Target», «From» and the time.",
            "«Refresh» brings the new ones and «Older» brings the older.",
        ],
    ),
    _guide(
        "admin-reset", (Role.ADMIN,), "/admin",
        ("إزاي أمسح كل التاسكات أو الميلات أو الموظفين (ريستارت)", "How do I wipe all tasks, mail or staff (reset)"),
        (
            "ريستارت، امسح كل التاسكات، امسح كل الميلات، امسح كل الموظفين، ابدأ من الأول، تصفير النظام، منطقة خطر",
            "reset, delete every task, delete all mail, delete all staff, start over, wipe, danger zone",
        ),
        [
            "في قسم «منطقة خطر» اختار «ريستارت التاسكات» أو «مسح الميلات» أو «ريستارت الموظفين».",
            "راجع «اللي هيتمسح» و«اللي بيفضل».",
            "علّم خانة الفهم، واكتب «باسورد الأدمن بتاعك»، واضغط زرار المسح. بينزل لك ملف JSON فيه كل اللي اتمسح.",
        ],
        [
            "In the «Danger zone» section pick «Reset all tasks», «Delete all mail» or «Reset all staff».",
            "Check «What goes» and «What stays».",
            "Tick the understanding box, type «Your admin password» and press the delete button. A JSON file of everything deleted downloads to you.",
        ],
        note=(
            "مفيش رجوع، والملف مابيتحفظش على السيرفر: احتفظ بيه. 5 محاولات باسورد غلط في 15 دقيقة بتقفل الباب.",
            "There is no undo and the file is not kept on the server: keep it. Five wrong passwords in 15 minutes shut the door.",
        ),
    ),
)

BY_ID = {guide.id: guide for guide in GUIDES}


def for_user(user):
    """The guides this person may be told, in the catalog's order."""
    return [guide for guide in GUIDES if guide.shown_to(user)]
