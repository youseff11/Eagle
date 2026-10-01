"""Where the live pushes are triggered from.

On the model signals rather than at each call site: a chat message is created
in ten places and a notification in dozens, and a push that depends on every
future author remembering to add it is a push that goes missing. Connected in
``DashboardConfig.ready``.
"""

from django.db.models.signals import post_save
from django.dispatch import receiver

from . import realtime
from .models import ChatMessage, Notification


@receiver(post_save, sender=Notification, dispatch_uid="realtime_notification")
def push_notification(sender, instance, created, raw=False, **kwargs):
    if created and not raw:
        realtime.send_to_users([instance.user_id], {"t": realtime.NOTIFY})


@receiver(post_save, sender=ChatMessage, dispatch_uid="realtime_chat_message")
def push_chat_message(sender, instance, created, raw=False, **kwargs):
    if created and not raw:
        realtime.push_room(instance.room_id)
