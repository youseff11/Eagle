"""Take the old client and task rooms out of the chats lists.

They stay in the database and stay readable by their URL - this only sets a
flag. Nothing is deleted, because these rows hold real conversations with
real clients and a row removed to tidy a list cannot be got back.

    python manage.py archive_client_rooms --dry-run   # count them first
    python manage.py archive_client_rooms
    python manage.py archive_client_rooms --undo
"""

from django.core.management.base import BaseCommand

from dashboard.models import ChatRoom, RoomKind


#: The kinds the chats page used to be built around. The internal ones - the
#: staff chats and the work groups - are what the page is for now, and they
#: are never touched by this command.
OLD_KINDS = (RoomKind.CLIENT, RoomKind.GROUP, RoomKind.OPS_LEAD)


class Command(BaseCommand):
    help = "Archive the old client and task rooms (reversible, nothing deleted)."

    def add_arguments(self, parser):
        parser.add_argument(
            "--dry-run", action="store_true",
            help="Say how many would change and write nothing.",
        )
        parser.add_argument(
            "--undo", action="store_true",
            help="Bring them back into the lists.",
        )
        parser.add_argument(
            "--delete", action="store_true",
            help="Delete them for good. Needs --yes-i-am-sure as well.",
        )
        parser.add_argument(
            "--yes-i-am-sure", action="store_true",
            help="Confirms --delete. There is no undo.",
        )

    def handle(self, *args, **options):
        if options["delete"]:
            return self._delete(options)
        archiving = not options["undo"]
        rooms = ChatRoom.objects.filter(
            kind__in=OLD_KINDS, is_archived=not archiving
        )
        count = rooms.count()

        if options["dry_run"]:
            word = "archive" if archiving else "restore"
            self.stdout.write(f"would {word} {count} room(s). Nothing written.")
            return

        rooms.update(is_archived=archiving)
        word = "archived" if archiving else "restored"
        self.stdout.write(self.style.SUCCESS(f"{word} {count} room(s)."))
        if archiving:
            self.stdout.write(
                "They are out of the lists, not gone: each one still opens at "
                "/ops/chats/g/<id>/ and the task page still links to its own."
            )

    def _delete(self, options):
        """Remove them for good. Two flags, because there is no undo.

        What goes: the rooms and the team-side copies of those conversations.
        What stays: every message the client sent (InboundMessage) and every
        message that went out to them (OutboundMessage). The client's actual
        conversation is rendered from those two, under "Clients", and this
        does not touch either.
        """
        rooms = ChatRoom.objects.filter(kind__in=OLD_KINDS)
        count = rooms.count()

        if not options["yes_i_am_sure"]:
            self.stdout.write(self.style.WARNING(
                f"{count} room(s) would be deleted for good, with their "
                f"messages. Nothing written.\n"
                f"The client's own messages and everything sent to them are "
                f"kept - they live outside these rooms.\n"
                f"Run it again with --yes-i-am-sure if that is what you want."
            ))
            return

        deleted, _detail = rooms.delete()
        self.stdout.write(self.style.SUCCESS(
            f"deleted {count} room(s) ({deleted} rows in total). No undo."
        ))
