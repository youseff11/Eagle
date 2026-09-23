"""Where a task's request came in - WhatsApp or e-mail - shown beside its title.

Existing tasks are filled from the messages they were made from, or failing
that from the client files they were given. A task with neither stays blank,
which is what a task typed by hand is.
"""

from django.db import migrations, models


KNOWN = ("whatsapp", "email")


def fill_origin(apps, schema_editor):
    Task = apps.get_model("dashboard", "Task")
    InboundMessage = apps.get_model("dashboard", "InboundMessage")
    MessageAttachment = apps.get_model("dashboard", "MessageAttachment")

    for task in Task.objects.filter(origin="").only("id").iterator():
        channel = (
            InboundMessage.objects.filter(task_id=task.id, channel__in=KNOWN)
            .order_by("received_at", "id").values_list("channel", flat=True).first()
        )
        if not channel:
            channel = (
                MessageAttachment.objects.filter(tasks=task.id, message__channel__in=KNOWN)
                .order_by("id").values_list("message__channel", flat=True).first()
            )
        if channel:
            Task.objects.filter(pk=task.id).update(origin=channel)


class Migration(migrations.Migration):

    dependencies = [
        ("dashboard", "0028_calls"),
    ]

    operations = [
        migrations.AddField(
            model_name="task",
            name="origin",
            field=models.CharField(
                blank=True, default="", max_length=12,
                choices=[("whatsapp", "WhatsApp"), ("email", "Email"), ("manual", "Manual")],
                help_text="The channel the client's request arrived on. Blank = typed by hand.",
            ),
        ),
        migrations.RunPython(fill_origin, migrations.RunPython.noop),
    ]
