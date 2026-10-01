"""Where the live pushes are triggered from.

On the model signals rather than at each call site: a chat message is created
in ten places and a notification in dozens, and a push that depends on every
future author remembering to add it is a push that goes missing. Connected in
``DashboardConfig.ready``.

A chat message pings on every save, not only the first. It is created first
and finished afterwards - its files are attached, the task is tagged, the
relay to the client reports ``sent`` or ``failed`` - and a page told only about
the first moment would show a half-finished message, or one that looks sent
and was not. A file arriving pings too. The pings carry nothing, so there is no
harm in several; the page can fold them into one refresh.
"""

from django.db.models.signals import post_save
from django.dispatch import receiver

from . import realtime
from .models import ChatAttachment, ChatMessage, Notification


@receiver(post_save, sender=Notification, dispatch_uid="realtime_notification")
def push_notification(sender, instance, created, raw=False, **kwargs):
    if created and not raw:
        realtime.send_to_users([instance.user_id], {"t": realtime.NOTIFY})


@receiver(post_save, sender=ChatMessage, dispatch_uid="realtime_chat_message")
def push_chat_message(sender, instance, created, raw=False, **kwargs):
    if not raw:
        realtime.push_room(instance.room_id)


@receiver(post_save, sender=ChatAttachment, dispatch_uid="realtime_chat_attachment")
def push_chat_attachment(sender, instance, created, raw=False, **kwargs):
    if created and not raw:
        realtime.push_room(instance.message.room_id)
