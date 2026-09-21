"""E-mail conversations: ``InboundMessage.thread_key``.

/ops/inbox/ now lists conversations the way Gmail does, not single letters. The
column is added blank and the mail that is already there is grouped by the same
rules the live mailbox uses (``dashboard/threads.py``), oldest letter first, so
a reply always finds the letter it answers already keyed.

Only ``In-Reply-To`` was ever stored — ``References`` was not — so old mail is
grouped by that and by the subject. New mail gets both headers.
"""

from django.db import migrations, models


def group_existing_mail(apps, schema_editor):
    from dashboard import threads

    Message = apps.get_model("dashboard", "InboundMessage")
    # A list, not an iterator: every row below writes to this same table.
    rows = list(
        Message.objects.filter(channel="email", thread_key="")
        .order_by("received_at", "id")
        .values_list("id", "client_id", "sender_identity", "subject",
                     "reply_to_external", "received_at")
    )
    for pk, client_id, sender, subject, in_reply_to, received_at in rows:
        key = threads.find_thread_key(
            Message,
            channel="email",
            client_id=client_id,
            sender=sender,
            subject=subject,
            refs=threads.message_ids(in_reply_to),
            when=received_at,
            exclude_pk=pk,
        ) or threads.new_key()
        Message.objects.filter(pk=pk).update(thread_key=key)


class Migration(migrations.Migration):

    dependencies = [
        ("dashboard", "0015_mail_inbox_and_source_files"),
    ]

    operations = [
        migrations.AddField(
            model_name="inboundmessage",
            name="thread_key",
            field=models.CharField(blank=True, db_index=True, max_length=32),
        ),
        migrations.RunPython(group_existing_mail, migrations.RunPython.noop),
    ]
