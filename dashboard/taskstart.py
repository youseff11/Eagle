"""Starting a task: what it is made from, what the form is filled with, and making it.

The classic page (``views.ops_task_new``) and the new app's door (``api_ops.task_start`` / ``task_create``) start
a task the same way, so the rules that decide it are here once: which client messages a task may be made from,
which of their files go to the translator, what the title and the brief begin as, and what happens to the messages
when the task exists.

Everything that arrives here comes from a browser (an id in an address, a box in a form), so each id is looked up
again against what this person may read: a message of another client, of another line, hidden by the rate rule, or
a file that belongs to some other message finds nothing - it does not join the task.
"""

from dataclasses import dataclass, field

from . import services, wordcount
from .models import InboundMessage, MessageAttachment, Task


def ids(raw_values):
    """Ints out of repeated fields and/or comma-joined strings, in order, once."""
    out = []
    for value in raw_values or []:
        for chunk in str(value).replace(" ", "").split(","):
            if chunk.isdecimal() and int(chunk) not in out:
                out.append(int(chunk))
    return out


def picked_attachments(messages, raw_values):
    """The attachment rows named in ``raw_values`` - but only these messages' own.

    Takes either the repeated ``files=`` checkboxes the mail page posts or one comma-joined string, because the
    chat builds the link in JavaScript. ``messages`` is one message or several: the chat can tick files across a
    whole run of them and make one task out of the lot.

    The ids come from the browser, so the rows are re-fetched against the messages rather than trusted: an id from
    somebody else's conversation must not be able to walk a file into a task it has nothing to do with.
    """
    if isinstance(messages, InboundMessage):
        messages = [messages]
    messages = [m for m in (messages or []) if m is not None]
    wanted = ids(raw_values)
    if not messages or not wanted:
        return []
    return list(MessageAttachment.objects.filter(message__in=messages, pk__in=wanted).order_by("id"))


def source_messages(user, raw_ids):
    """The client messages a new task is being made from - one, or a run of them.

    Every message has to be one this person may see, and they all have to be the same client's: a task has one
    client, and a stray id from another conversation must not be able to join it.
    """
    wanted = ids(raw_ids)
    if not wanted:
        return []
    qs = InboundMessage.objects.filter(pk__in=wanted).select_related("client")
    if not user.is_admin_role:
        qs = qs.filter(is_rate_blocked=False)
    # The line as well: a Sales person's own number is theirs alone, and an id is only a number. ``visible_to`` is
    # the rule ``lines.line_q`` applies to every list, for a row in hand.
    rows = [row for row in qs.prefetch_related("attachments").order_by("received_at", "id") if row.visible_to(user)]
    if not rows:
        return []
    owner = rows[0].client_id
    return [row for row in rows if row.client_id == owner]


@dataclass
class Start:
    """What a new task starts from: the messages and files behind it, the task it repeats, and the form's first values."""

    messages: list = field(default_factory=list)
    picked: list = field(default_factory=list)
    from_task: Task | None = None
    initial: dict = field(default_factory=dict)
    #: The accepted B2B quotation the task is made from (``?quote=``): the operation makes the task, the quotation fills the
    #: form - the client's code, the pair, the size, the deadline. Never the price, nor the company's name.
    quote: object = None

    @property
    def message(self):
        return self.messages[0] if self.messages else None


def resolve(user, message_ids=(), file_ids=(), from_code="", text_ids=None, quote_code=""):
    """Work out what a new task starts from.

    ``from_code`` is "a new request on the same files": a new task on a finished (or running) one's material - the
    same contract into another language, say. It starts from that task's messages and files; everything else is a
    fresh task. Nothing ticked means every file of the messages, which is what it meant before the picker existed.

    ``text_ids`` are the messages ticked to be the task's details (the brief): only their words are written there, in
    the order they arrived, and only if they are among the messages this person may make a task from. ``None`` - nothing
    was ticked - is every message's words, as before.
    """
    from_code = (from_code or "").strip()
    from_task = Task.objects.filter(code=from_code).select_related("client").first() if from_code else None

    messages = source_messages(user, message_ids)
    if from_task is not None and not messages:
        messages = list(
            services.task_inbounds(from_task).select_related("client")
            .prefetch_related("attachments").order_by("received_at", "id")
        )
        messages = [m for m in messages if m.visible_to(user)]
    message = messages[0] if messages else None

    raw_files = list(file_ids or [])
    if from_task is not None and not raw_files:
        # Only the client's own files: a file the leader uploaded is not on any message, and its id is another table's.
        raw_files = [str(a.pk) for a in services.task_source_files(from_task) if isinstance(a, MessageAttachment)]
    picked = picked_attachments(messages, raw_files)
    # A message already behind a task stays with it (services.create_task), so a new task on it has to name its
    # files - "nothing ticked" would otherwise leave it with none at all.
    if not picked and any(m.task_id for m in messages):
        picked = [a for m in messages for a in m.attachments.all()]

    initial = {}
    if message:
        # "[document]" is what the webhook writes for a file with no caption. It says nothing in a task, so it goes;
        # the files are on the task.
        wanted = None if text_ids is None else set(ids(text_ids))
        worded = messages if wanted is None else [m for m in messages if m.pk in wanted]
        texts = [services.clean_client_text(m.body) for m in worded]
        description = "\n\n".join(text for text in texts if text)
        files = len(picked) or sum(len(m.attachments.all()) for m in messages)
        if len(messages) == 1 and (message.subject or (texts and texts[0])):
            title = message.subject or texts[0][:60]
        elif len(worded) == 1 and texts[0] and not files:
            title = texts[0][:60]
        elif files:
            # A title that says what the job is rather than whichever line happened to come first.
            title = f"{files} ملفات من {message.client_code}"
        else:
            title = "Translation request"
        initial = {"client": message.client_id, "title": title.strip(), "description": description}
    if from_task is not None:
        initial.update({
            "client": from_task.client_id,
            "title": f"طلب جديد — {from_task.title}"[:200],
            "description": services.clean_client_text(from_task.description),
            "source_lang": from_task.source_lang,
        })
    from . import b2b

    quote = None if (messages or from_task is not None) else b2b.quotation_for_task((quote_code or "").strip(), user)
    if quote is not None:
        from django.utils import timezone

        size = f"{quote.quantity:,} {quote.get_unit_display().lower()}"
        initial = {
            "client": quote.lead.client_id,
            "title": f"{quote.code} · {quote.source_lang} > {quote.target_lang}",
            "description": f"{quote.get_service_display()}: {size}.",
            "source_lang": quote.source_lang,
            "target_lang": quote.target_lang,
            "word_count": quote.quantity if quote.unit == quote.Unit.WORDS else None,
            "deadline_days": max(0, (quote.deadline - timezone.localdate()).days) if quote.deadline else None,
        }
    return Start(messages=messages, picked=picked, from_task=from_task, initial=initial, quote=quote)


def create(user, cleaned, start):
    """Make the task from a valid form's ``cleaned`` data, and take the messages behind it as this person's."""
    task = services.create_task(
        client=cleaned["client"],
        title=cleaned["title"],
        created_by=user,
        description=cleaned["description"],
        deadline=cleaned["deadline"],
        priority=cleaned["priority"],
        source_lang=cleaned["source_lang"],
        target_lang=cleaned["target_lang"],
        messages=start.messages or None,
        origin=start.from_task.origin if start.from_task is not None else "",
    )
    if start.picked:
        task.source_files.set(start.picked)
    for row in start.messages:
        if not row.claimed_by_id:
            services.claim_message(row, user)
    # The form asks for these three and the first version of this function forgot them: a word count typed here
    # was never saved. It is settled the way every word count is - by a person, on the audit log - and the two
    # switches are what the production floor and the language rule read.
    flags = [name for name in ("is_difficult", "is_secondary_language") if cleaned.get(name)]
    for name in flags:
        setattr(task, name, True)
    if flags:
        task.save(update_fields=[*flags, "updated_at"])
    if cleaned.get("word_count"):
        wordcount.confirm_task(task, user, words=int(cleaned["word_count"]))
    return task


def owner_admin():
    """The admin who answers for a task a team leader made: the first active one. ``None`` when there is none."""
    from .models import Role, User

    return (
        User.objects.filter(role=Role.ADMIN, is_active=True, deleted_at__isnull=True).order_by("pk").first()
        or User.objects.filter(is_superuser=True, is_active=True, deleted_at__isnull=True).order_by("pk").first()
    )


def create_for_lead(lead, cleaned, uploads):
    """A team leader makes a task himself, with the files from his own machine (11/10/2026): ``(task, error)``.

    The owner's rule: the task is the leader's from the first moment (accepted, ready to hand out to his translators) and no
    operation is on it. ``created_by`` is the admin, which is what every later step reads as "who takes it over": the reviewed
    files land in the leader's chat with the admin, and the admin delivers to the client. Errors: ``no_files``, ``no_admin``.
    """
    from django.db import transaction
    from django.utils import timezone

    from .models import AssignmentStatus, Role, TaskStatus

    uploads = [u for u in (uploads or []) if u]
    if not uploads:
        return None, "no_files"
    admin = owner_admin()
    if admin is None:
        return None, "no_admin"
    client = cleaned["client"]
    with transaction.atomic():
        task = services.create_task(
            client=client, title=cleaned["title"], created_by=admin, description=cleaned["description"],
            deadline=cleaned["deadline"], priority=cleaned["priority"],
            source_lang=cleaned["source_lang"], target_lang=cleaned["target_lang"],
        )
        now = timezone.now()
        task.opened_by_lead = lead
        task.team_lead = lead
        task.status = TaskStatus.LEAD_ACCEPTED
        task.lead_accepted_at = now
        task.is_difficult = bool(cleaned.get("is_difficult"))
        task.is_secondary_language = bool(cleaned.get("is_secondary_language"))
        task.save(update_fields=[
            "opened_by_lead", "team_lead", "status", "lead_accepted_at", "is_difficult", "is_secondary_language", "updated_at",
        ])
        # The leader's own "yes", written the way an accepted hand-off is, so the task reads like any task a leader took.
        task.assignments.create(
            assignee=lead, assigned_by=lead, target_role=Role.TEAM_LEAD, status=AssignmentStatus.ACCEPTED,
            assigned_at=now, expires_at=now, responded_at=now,
        )
        add_uploads(task, lead, uploads)
    services.notify(
        admin,
        title_ar="تيم ليدر عمل تاسك",
        title_en="A team leader made a task",
        body_ar=f"{lead.short_name} عمل التاسك {task.code} ({client.code}) بملفاته. هيوزّعها على فريقه، وبعد المراجعة الملفات هتوصلك تسلّمها للعميل.",
        body_en=f"{lead.short_name} made task {task.code} ({client.code}) with their own files. They will hand it out, and after the review the files reach you to deliver.",
        level="info", url=f"/tasks/{task.code}/", sound=True, task=task,
    )
    services.log(lead, "task.lead_create", task.code, f"{len(uploads)} file(s)")
    return task, ""


def add_uploads(task, user, uploads):
    """Store files on the task as the leader's (``TaskUpload``), each name masked against the client."""
    from . import files as stored
    from .models import TaskUpload

    rows = []
    for item in uploads:
        name = services.short_name(item.name)
        rows.append(TaskUpload.objects.create(
            task=task, file=item, original_name=stored.mask_name(name, task.client)[:250], raw_name=name[:250],
            size=item.size or 0, mime=(getattr(item, "content_type", "") or "")[:120], uploaded_by=user,
        ))
    return rows


#: While the translation is still being made, the leader who made the task may add a file he forgot.
ADD_FILES_STATUSES = ("lead_accepted", "awaiting_translator", "in_progress")


def may_add_files(task, user):
    """The leader who made this task himself (and still leads it), or the admin, while it is being translated."""
    if task.opened_by_lead_id is None or task.status not in ADD_FILES_STATUSES:
        return False
    return user.is_admin_role or (user.is_team_lead and task.team_lead_id == user.pk == task.opened_by_lead_id)


def add_files_later(task, user, uploads):
    """A file the leader forgot, added from the task page: stored on the task and put in every translator's chat with him at once.

    ``(rows, error)``; errors ``forbidden``, ``empty``.
    """
    from django.db import transaction

    if not may_add_files(task, user):
        return [], "forbidden"
    uploads = [u for u in (uploads or []) if u]
    if not uploads:
        return [], "empty"
    with transaction.atomic():
        rows = add_uploads(task, user, uploads)
    lead = task.team_lead
    for person in task.translator_users():
        room = services.task_thread(task, lead, person)
        if room is not None:
            services.share_files_quietly(task, room)
    services.log(user, "task.lead_files_added", task.code, str(len(rows)))
    return rows, ""
