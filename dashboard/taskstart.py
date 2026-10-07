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

    @property
    def message(self):
        return self.messages[0] if self.messages else None


def resolve(user, message_ids=(), file_ids=(), from_code="", text_ids=None):
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
        raw_files = [str(a.pk) for a in services.task_source_files(from_task)]
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
    return Start(messages=messages, picked=picked, from_task=from_task, initial=initial)


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
