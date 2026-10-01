"""Find translators seated in client rooms - and, if asked, clean up after them.

A client room is the client's own conversation. A translator works from a task
code and must never read it, but until ``ChatRoom.can_access`` refused them the
add-members endpoint could seat one, and the notification that quotes the
client's words went to every member of the room. Rows from that time may still
be in the database: a membership, and notifications with the client's words in
them addressed to a translator.

    python manage.py client_room_translators                      # report only
    python manage.py client_room_translators --remove             # drop the seats
    python manage.py client_room_translators --purge-notifications

Nothing is changed unless a flag says so. The notifications that count are the
ones addressed to a seated translator and pointing at that room (the link in a
chat or mirrored-message notification carries the room's id), so a translator's
ordinary notifications about their own tasks are left alone.
"""

from django.core.management.base import BaseCommand
from django.db.models import Q

from dashboard.models import ChatRoom, Notification, Role, RoomKind


def _room_links(room):
    return Q(url=f"/ops/chats/g/{room.pk}/") | Q(url__endswith=f"?room={room.pk}")


class Command(BaseCommand):
    help = "Report (and optionally remove) translators seated in client rooms."

    def add_arguments(self, parser):
        parser.add_argument(
            "--remove", action="store_true",
            help="Take every translator out of every client room.",
        )
        parser.add_argument(
            "--purge-notifications", action="store_true",
            help="Delete the notifications those translators got about those rooms.",
        )

    def handle(self, *args, **options):
        seats = []
        for room in ChatRoom.objects.filter(kind=RoomKind.CLIENT).order_by("id"):
            for person in room.members.filter(role=Role.TRANSLATOR):
                seats.append((room, person))

        if not seats:
            self.stdout.write("No translator is seated in a client room.")
            return

        total = 0
        for room, person in seats:
            notes = Notification.objects.filter(user=person).filter(_room_links(room))
            count = notes.count()
            total += count
            self.stdout.write(
                f"room {room.pk} ({room.display_title}): translator {person.username}, "
                f"{count} notification(s) about it"
            )
            if options["purge_notifications"]:
                notes.delete()
            if options["remove"]:
                room.members.remove(person)

        verbs = []
        if options["remove"]:
            verbs.append(f"removed {len(seats)} seat(s)")
        if options["purge_notifications"]:
            verbs.append(f"deleted {total} notification(s)")
        if verbs:
            self.stdout.write("Done: " + ", ".join(verbs) + ".")
        else:
            self.stdout.write(
                f"{len(seats)} seat(s), {total} notification(s). Nothing changed: "
                "run with --remove and/or --purge-notifications."
            )
