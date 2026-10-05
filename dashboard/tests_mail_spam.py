"""Reading the mailbox's Spam folder, and the second IDLE watcher that goes with it.

Gmail files a real client's first letter under Spam now and then and nobody looks there. With "read the Spam folder" on
(``AppSettings.imap_read_spam``) the fetch reads that folder after the inbox and a second IDLE watcher rings the moment
something lands in it. What these tests hold: it is off unless the admin turns it on; the inbox is never lost because of
the Spam folder (missing, refused, failing); the Spam folder is found by the server's own ``\\Junk`` flag and not by its
name; the same filters apply there as to the inbox; and the watchers are started, put to sleep and let go as the switch
moves.
"""

import imaplib
import json
import threading
from email.message import EmailMessage
from unittest import mock

from django.test import TestCase

from . import mailbox
from .management.commands import run_worker
from .models import AppSettings, InboundMessage
from .tests_admin_settings import GET, _Settings
from .tests_api_v1 import _json

GMAIL_LIST = [
    b'(\\HasNoChildren) "/" "INBOX"',
    b'(\\HasNoChildren \\Junk) "/" "[Gmail]/Spam"',
    b'(\\HasNoChildren \\Trash) "/" "[Gmail]/Trash"',
]


def raw(sender, subject):
    message = EmailMessage()
    message["From"], message["To"] = sender, "inbox@eagle.test"
    message["Subject"], message["Message-ID"] = subject, f"<{subject}@spam-test>"
    message.set_content("hello")
    return message.as_bytes()


class FakeBox:
    """An IMAP connection with named folders, each holding raw letters.

    UIDs count from 1 in each folder. Every letter is unread unless ``read`` names it as a
    ``(folder, uid)`` pair - a letter somebody opened in Gmail. ``validity`` is the folder's UIDVALIDITY
    (a number, or a ``{folder: number}`` map); ``None`` plays a server that does not announce one.
    """

    def __init__(self, folders, listing=GMAIL_LIST, list_status="OK", list_error=None, read=(), validity=7):
        self.folders = folders
        self.listing, self.list_status, self.list_error = listing, list_status, list_error
        self.read, self.validity = set(read), validity
        self.selected = None
        self.selects, self.raw_selects, self.lists, self.fetched = [], [], 0, []

    def login(self, *_args):
        pass

    def select(self, name):
        self.raw_selects.append(name)
        bare = name.strip('"')
        self.selects.append(bare)
        if bare not in self.folders:
            return "NO", [b"no such folder"]
        self.selected = bare
        return "OK", [b"1"]

    def response(self, code):
        letters = self.folders[self.selected]
        if code == "UIDNEXT":
            return code, [str(len(letters) + 1).encode()]
        if code == "UIDVALIDITY":
            value = self.validity.get(self.selected, 7) if isinstance(self.validity, dict) else self.validity
            return code, [None if value is None else str(value).encode()]
        return code, [None]

    def list(self):
        self.lists += 1
        if self.list_error:
            raise self.list_error
        return self.list_status, self.listing

    def uid(self, command, *args):
        letters = self.folders[self.selected]
        everyone = list(range(1, len(letters) + 1))
        if command == "SEARCH":
            if args == ("UNSEEN",):
                found = [u for u in everyone if (self.selected, u) not in self.read]
            elif args == ("ALL",):
                found = everyone
            else:
                assert args[0] == "UID", args
                low = int(args[1].split(":")[0])
                # Like a real server: ``n:*`` always answers with the newest letter, even one below n.
                found = [u for u in everyone if u >= low] or everyone[-1:]
            return "OK", [" ".join(map(str, found)).encode()]
        assert command == "FETCH", command
        number = int(args[0])
        self.fetched.append((self.selected, number))
        # Like Gmail: the receipt time comes after the letter, in the next part of the answer.
        head = f"{number} (UID {number} RFC822 {{1}}".encode()
        return "OK", [(head, letters[number - 1]), b' INTERNALDATE "05-Oct-2026 00:03:48 +0300")']

    def close(self):
        pass

    def logout(self):
        pass


class JunkNameTests(TestCase):
    def test_the_folder_flagged_junk_is_the_spam_folder(self):
        self.assertEqual(mailbox.junk_folder_in(GMAIL_LIST), "[Gmail]/Spam")

    def test_the_answer_as_it_comes_off_the_wire_reads_the_same(self):
        wire = [b'* LIST (\\HasNoChildren) "/" "INBOX"', b'* LIST (\\HasNoChildren \\Junk) "/" "[Gmail]/Spam"']
        self.assertEqual(mailbox.junk_folder_in(wire), "[Gmail]/Spam")

    def test_the_flag_decides_not_the_name(self):
        self.assertEqual(mailbox.junk_folder_in([b'(\\HasNoChildren \\Junk) "/" "[Gmail]/Pourriel"']), "[Gmail]/Pourriel")
        self.assertEqual(mailbox.junk_folder_in([b'(\\HasNoChildren) "/" "Junk"', b'(\\HasNoChildren) "/" "Spam"']), "")

    def test_the_flag_is_read_whatever_its_case(self):
        self.assertEqual(mailbox.junk_folder_in([b'(\\JUNK) "." Junk']), "Junk")

    def test_a_quoted_name_is_unquoted_and_unescaped(self):
        self.assertEqual(mailbox.junk_folder_in([b'(\\Junk) "/" "a\\"b\\\\c"']), 'a"b\\c')

    def test_no_junk_folder_is_an_empty_answer_not_an_error(self):
        for lines in (None, [], [b'(\\HasNoChildren) "/" "INBOX"'], [b"garbage"], [(b"literal", b"x")]):
            self.assertEqual(mailbox.junk_folder_in(lines), "")

    def test_a_refused_list_is_an_empty_answer(self):
        self.assertEqual(mailbox.junk_folder(FakeBox({}, list_status="NO")), "")


class SpamFolderFetchTests(TestCase):
    def setUp(self):
        conf = AppSettings.load()
        conf.imap_host, conf.imap_user, conf.imap_password = "imap.test", "inbox@eagle.test", "pw"
        conf.save()
        self.inbox = [raw("Ann <ann@client.test>", "from-the-inbox")]
        self.spam = [raw("Bob <bob@client.test>", "from-the-spam-folder")]

    def turn_on(self, on=True):
        conf = AppSettings.load()
        conf.imap_read_spam = on
        conf.save()

    def fetch(self, box):
        with mock.patch.object(mailbox.imaplib, "IMAP4_SSL", return_value=box):
            return mailbox.fetch(conf=AppSettings.load())

    def stored(self, subject):
        return InboundMessage.objects.filter(subject=subject).exists()

    def test_it_is_off_unless_the_admin_turns_it_on(self):
        self.assertFalse(AppSettings.load().imap_read_spam)
        box = FakeBox({"INBOX": self.inbox, "[Gmail]/Spam": self.spam})
        self.assertEqual(self.fetch(box), 1)
        self.assertEqual(box.selects, ["INBOX"])
        self.assertEqual(box.lists, 0)
        self.assertTrue(self.stored("from-the-inbox"))
        self.assertFalse(self.stored("from-the-spam-folder"))

    def test_on_it_reads_the_spam_folder_after_the_inbox(self):
        self.turn_on()
        box = FakeBox({"INBOX": self.inbox, "[Gmail]/Spam": self.spam})
        self.assertEqual(self.fetch(box), 2)
        self.assertEqual(box.selects, ["INBOX", "[Gmail]/Spam"])
        self.assertTrue(self.stored("from-the-inbox"))
        self.assertTrue(self.stored("from-the-spam-folder"))

    def test_the_folder_name_is_quoted_on_the_wire(self):
        self.turn_on()
        box = FakeBox({"INBOX": [], "[Gmail]/Spam": self.spam})
        self.fetch(box)
        self.assertEqual(box.raw_selects[-1], '"[Gmail]/Spam"')

    def test_the_server_decides_what_its_spam_folder_is_called(self):
        self.turn_on()
        listing = [b'(\\HasNoChildren) "/" "INBOX"', b'(\\HasNoChildren \\Junk) "/" "[Gmail]/Pourriel"']
        box = FakeBox({"INBOX": [], "[Gmail]/Pourriel": self.spam}, listing=listing)
        self.assertEqual(self.fetch(box), 1)
        self.assertEqual(box.selects, ["INBOX", "[Gmail]/Pourriel"])

    def test_a_mailbox_with_no_spam_folder_still_gives_its_inbox(self):
        self.turn_on()
        box = FakeBox({"INBOX": self.inbox}, listing=[b'(\\HasNoChildren) "/" "INBOX"'])
        self.assertEqual(self.fetch(box), 1)
        self.assertEqual(box.selects, ["INBOX"])

    def test_a_spam_folder_the_server_refuses_does_not_cost_the_inbox(self):
        self.turn_on()
        box = FakeBox({"INBOX": self.inbox})            # listed as Spam, but selecting it says NO
        self.assertEqual(self.fetch(box), 1)
        self.assertTrue(self.stored("from-the-inbox"))

    def test_a_list_that_fails_does_not_cost_the_inbox(self):
        self.turn_on()
        for box in (
            FakeBox({"INBOX": self.inbox}, list_status="NO"),
            FakeBox({"INBOX": self.inbox}, list_error=imaplib.IMAP4.error("boom")),
        ):
            InboundMessage.objects.all().delete()
            AppSettings.objects.update(mail_uid_state="")       # each box is a fresh first look
            AppSettings._cached = None
            self.assertEqual(self.fetch(box), 1)
            self.assertTrue(self.stored("from-the-inbox"))

    def test_the_same_filters_apply_to_the_spam_folder(self):
        self.turn_on()
        spam = [
            raw("no-reply@security.test", "robot"),
            raw("inbox@eagle.test", "ourselves"),
            raw("Bob <bob@client.test>", "a-person"),
        ]
        box = FakeBox({"INBOX": [], "[Gmail]/Spam": spam})
        self.assertEqual(self.fetch(box), 1)
        self.assertTrue(self.stored("a-person"))
        self.assertFalse(self.stored("robot"))
        self.assertFalse(self.stored("ourselves"))

    def test_a_letter_seen_in_both_folders_is_stored_once(self):
        self.turn_on()
        same = raw("Ann <ann@client.test>", "twice")
        box = FakeBox({"INBOX": [same], "[Gmail]/Spam": [same]})
        self.fetch(box)
        self.assertEqual(InboundMessage.objects.filter(subject="twice").count(), 1)


class UidTrackingTests(TestCase):
    """New mail is decided by UID, not by the unread flag.

    A letter somebody opens in Gmail before the worker gets to it is already read. Going by "unread" lost it for
    good (three test letters were lost this way on 05/10/2026), so each folder remembers the highest UID handled.
    """

    def setUp(self):
        conf = AppSettings.load()
        conf.imap_host, conf.imap_user, conf.imap_password = "imap.test", "inbox@eagle.test", "pw"
        conf.save()

    def fetch(self, box, **kwargs):
        with mock.patch.object(mailbox.imaplib, "IMAP4_SSL", return_value=box):
            return mailbox.fetch(conf=AppSettings.load(), **kwargs)

    def stored(self, subject):
        return InboundMessage.objects.filter(subject=subject).exists()

    def state(self):
        return json.loads(AppSettings.load().mail_uid_state)

    def letter(self, subject, sender="Ann <ann@client.test>"):
        return raw(sender, subject)

    def test_the_first_look_takes_the_unread_ones_and_remembers_how_far_it_got(self):
        box = FakeBox(
            {"INBOX": [self.letter("old-and-read"), self.letter("unread-one"), self.letter("unread-two")]},
            read={("INBOX", 1)},
        )
        self.assertEqual(self.fetch(box), 2)
        self.assertFalse(self.stored("old-and-read"))
        self.assertTrue(self.stored("unread-one") and self.stored("unread-two"))
        self.assertEqual(self.state(), {"INBOX": {"validity": 7, "last": 3}})

    def test_a_letter_read_in_gmail_first_is_still_recorded(self):
        box = FakeBox({"INBOX": [self.letter("first")]})
        self.assertEqual(self.fetch(box), 1)
        box.folders["INBOX"].append(self.letter("opened-in-gmail-before-we-came"))
        box.read.add(("INBOX", 2))                      # somebody read it in Gmail already
        self.assertEqual(self.fetch(box), 1)
        self.assertTrue(self.stored("opened-in-gmail-before-we-came"))
        self.assertEqual(self.state()["INBOX"]["last"], 2)

    def test_what_was_recorded_is_not_fetched_again(self):
        box = FakeBox({"INBOX": [self.letter("one"), self.letter("two")]})
        self.fetch(box)
        asked = len(box.fetched)
        self.assertEqual(self.fetch(box), 0)
        self.assertEqual(len(box.fetched), asked)

    def test_a_folder_the_server_rebuilt_is_looked_at_afresh(self):
        box = FakeBox({"INBOX": [self.letter("before")]}, validity=7)
        self.fetch(box)
        rebuilt = FakeBox(
            {"INBOX": [self.letter("read-in-the-new-folder"), self.letter("unread-in-the-new-folder")]},
            read={("INBOX", 1)}, validity=8,
        )
        self.assertEqual(self.fetch(rebuilt), 1)
        self.assertTrue(self.stored("unread-in-the-new-folder"))
        self.assertFalse(self.stored("read-in-the-new-folder"))
        self.assertEqual(self.state()["INBOX"], {"validity": 8, "last": 2})

    def test_only_as_many_as_the_limit_at_a_time_and_the_rest_next_time(self):
        box = FakeBox({"INBOX": []})
        self.fetch(box)                                   # the first look, on an empty folder
        box.folders["INBOX"].extend(self.letter(f"letter-{n}") for n in range(5))
        self.assertEqual([self.fetch(box, limit=2) for _ in range(4)], [2, 2, 1, 0])

    def test_letters_we_skip_still_move_the_mark_on(self):
        box = FakeBox({"INBOX": []})
        self.fetch(box)
        box.folders["INBOX"].extend([
            self.letter("robot", "no-reply@security.test"),
            self.letter("ourselves", "inbox@eagle.test"),
            self.letter("a-person"),
        ])
        self.assertEqual(self.fetch(box), 1)
        asked = len(box.fetched)
        self.assertEqual(self.fetch(box), 0)
        self.assertEqual(len(box.fetched), asked)         # the two skipped ones are not asked for again

    def test_a_letter_that_cannot_be_recorded_does_not_hold_up_the_ones_behind_it(self):
        from . import services

        box = FakeBox({"INBOX": []})
        self.fetch(box)
        box.folders["INBOX"].extend([self.letter("poison"), self.letter("fine")])
        real = services.ingest_message

        def ingest(**parsed):
            if parsed["subject"] == "poison":
                raise RuntimeError("cannot be recorded")
            return real(**parsed)

        with mock.patch.object(services, "ingest_message", side_effect=ingest):
            self.assertEqual(self.fetch(box), 1)
        self.assertTrue(self.stored("fine"))
        asked = len(box.fetched)
        self.assertEqual(self.fetch(box), 0)
        self.assertEqual(len(box.fetched), asked)         # the bad one is not tried again forever

    def test_each_folder_has_its_own_mark(self):
        conf = AppSettings.load()
        conf.imap_read_spam = True
        conf.save()
        box = FakeBox({"INBOX": [self.letter("in-inbox")], "[Gmail]/Spam": [self.letter("in-spam")]})
        self.assertEqual(self.fetch(box), 2)
        self.assertEqual(
            self.state(),
            {"INBOX": {"validity": 7, "last": 1}, "[Gmail]/Spam": {"validity": 7, "last": 1}},
        )
        box.folders["[Gmail]/Spam"].append(self.letter("later-in-spam"))
        self.assertEqual(self.fetch(box), 1)
        self.assertTrue(self.stored("later-in-spam"))

    def test_a_stale_save_cannot_move_a_folder_backwards(self):
        conf = AppSettings.load()
        mailbox._save_uid_state(conf, {"INBOX": {"validity": 7, "last": 10}})
        mailbox._save_uid_state(conf, {"INBOX": {"validity": 7, "last": 4}})
        self.assertEqual(self.state()["INBOX"]["last"], 10)
        mailbox._save_uid_state(conf, {"INBOX": {"validity": 8, "last": 1}})   # a rebuilt folder starts over
        self.assertEqual(self.state()["INBOX"], {"validity": 8, "last": 1})

    def test_a_damaged_memory_is_ignored_not_trusted(self):
        for text in ("{not json", "[1, 2]", '"text"', '{"INBOX": "x"}'):
            AppSettings.objects.update(mail_uid_state=text)
            AppSettings._cached = None
            InboundMessage.objects.all().delete()
            self.assertEqual(self.fetch(FakeBox({"INBOX": [self.letter("unread")]})), 1, text)

    def test_a_server_that_gives_no_uidvalidity_is_read_by_the_flag_as_before(self):
        box = FakeBox({"INBOX": [self.letter("one")]}, validity=None)
        self.assertEqual(self.fetch(box), 1)
        self.assertEqual(AppSettings.load().mail_uid_state, "")      # nothing it could trust was remembered

    def test_the_age_of_a_letter_when_it_was_read_is_reported(self):
        self.fetch(FakeBox({"INBOX": []}))
        self.assertIsNone(mailbox.last_letter_age)
        box = FakeBox({"INBOX": [self.letter("one")]})
        AppSettings.objects.update(mail_uid_state="")
        AppSettings._cached = None
        self.fetch(box)
        self.assertIsInstance(mailbox.last_letter_age, float)
        self.assertGreaterEqual(mailbox.last_letter_age, 0.0)

    def test_the_worker_prints_the_age_and_how_long_the_fetch_took(self):
        command = run_worker.Command()
        command._mail_lock = threading.Lock()
        said = []
        command._say = lambda text, error=False: said.append(text)

        def fetch():
            mailbox.last_letter_age = 4.2
            return 1, ""

        with mock.patch.object(mailbox, "fetch_and_record", fetch), mock.patch("django.db.close_old_connections"):
            command._fetch_mail()
        self.assertEqual(len(said), 1)
        self.assertTrue(said[0].startswith("mail: 1 new, 4s after the server received it (fetch took "), said[0])


class FakeSock:
    """Scripted server lines; ``None`` is a read that times out."""

    def __init__(self, replies):
        self.replies = [r if r is None else r.encode() + b"\r\n" for r in replies]
        self.sent = []

    def settimeout(self, _seconds):
        pass

    def sendall(self, data):
        self.sent.append(data.decode().strip())

    def recv(self, _size):
        import socket

        item = self.replies.pop(0) if self.replies else None
        if item is None:
            raise socket.timeout("timed out")
        return item

    def close(self):
        pass


class Conf:
    imap_host = "imap.example.com"
    imap_port = 993
    imap_user = "eagle@example.com"
    imap_password = "app password"
    imap_folder = "INBOX"


class IdleOnSpamTests(TestCase):
    HELLO = ["* OK ready", "E0001 OK logged in", "* CAPABILITY IMAP4rev1 IDLE", "E0002 OK"]

    def test_the_spam_watcher_looks_the_folder_up_and_selects_it(self):
        sock = FakeSock(self.HELLO + [
            '* LIST (\\HasNoChildren) "/" "INBOX"',
            '* LIST (\\HasNoChildren \\Junk) "/" "[Gmail]/Spam"',
            "E0003 OK Success",
            "* 0 EXISTS", "E0004 OK [READ-WRITE] selected",
        ])
        mailbox.IdleWatcher(Conf, sock=sock, folder=mailbox.JUNK)
        self.assertIn('E0003 LIST "" "*"', sock.sent)
        self.assertIn('E0004 SELECT "[Gmail]/Spam"', sock.sent)

    def test_a_mailbox_with_no_spam_folder_is_told_apart(self):
        sock = FakeSock(self.HELLO + ['* LIST (\\HasNoChildren) "/" "INBOX"', "E0003 OK Success"])
        with self.assertRaises(mailbox.NoJunkFolder):
            mailbox.IdleWatcher(Conf, sock=sock, folder=mailbox.JUNK)

    def test_the_inbox_watcher_never_asks_for_the_list(self):
        sock = FakeSock(self.HELLO + ["* 3 EXISTS", "E0003 OK [READ-WRITE] INBOX selected"])
        mailbox.IdleWatcher(Conf, sock=sock)
        self.assertEqual([line for line in sock.sent if "LIST" in line], [])
        self.assertIn('E0003 SELECT "INBOX"', sock.sent)

    def test_a_letter_announced_while_the_idle_is_closing_is_not_lost(self):
        sock = FakeSock(self.HELLO + [
            "* 3 EXISTS", "E0003 OK [READ-WRITE] INBOX selected",
            "+ idling",
            None,                                   # the renew time comes, nothing announced yet
            "* 4 EXISTS",                           # ... and a letter lands as DONE is on its way
            "E0004 OK IDLE terminated",
        ])
        watcher = mailbox.IdleWatcher(Conf, sock=sock)
        self.assertTrue(watcher.wait(60))


class PollBetweenIdlesTests(TestCase):
    """A server that is slow to announce a letter is asked outright, between short IDLEs."""

    HELLO = [
        "* OK ready", "E0001 OK logged in", "* CAPABILITY IMAP4rev1 IDLE", "E0002 OK",
        "* 3 EXISTS", "E0003 OK [READ-WRITE] INBOX selected",
    ]

    def watcher(self, replies, poll_every=3):
        sock = FakeSock(self.HELLO + replies)
        watcher = mailbox.IdleWatcher(Conf, sock=sock)
        watcher.poll_every = poll_every
        return watcher, sock

    def test_a_letter_the_server_did_not_announce_is_found_by_asking(self):
        watcher, sock = self.watcher([
            "+ idling", None, "E0004 OK IDLE terminated", "E0005 OK NOOP completed",                  # nothing yet
            "+ idling", None, "E0006 OK IDLE terminated", "* 4 EXISTS", "E0007 OK NOOP completed",    # now there is
        ])
        self.assertTrue(watcher.wait(60))
        self.assertEqual(watcher.how, "poll")
        self.assertEqual([line for line in sock.sent if "NOOP" in line], ["E0005 NOOP", "E0007 NOOP"])

    def test_a_count_the_server_repeats_is_not_a_letter(self):
        watcher, sock = self.watcher([
            "+ idling", None, "E0004 OK IDLE terminated", "* 3 EXISTS", "E0005 OK NOOP completed",    # the same count again
            "+ idling", None, "E0006 OK IDLE terminated", "* 4 EXISTS", "E0007 OK NOOP completed",
        ])
        self.assertTrue(watcher.wait(60))
        self.assertEqual(sock.replies, [])                  # it went on to the second look, not stopped at the first

    def test_a_letter_announced_while_idling_is_found_by_the_idle(self):
        watcher, sock = self.watcher(["+ idling", "* 4 EXISTS", "E0004 OK IDLE terminated"])
        self.assertTrue(watcher.wait(60))
        self.assertEqual(watcher.how, "idle")
        self.assertEqual([line for line in sock.sent if "NOOP" in line], [])

    def test_a_count_that_went_down_is_not_a_letter(self):
        watcher, sock = self.watcher([
            "+ idling", None, "E0004 OK IDLE terminated", "* 2 EXISTS", "E0005 OK NOOP completed",    # one was deleted
            "+ idling", None, "E0006 OK IDLE terminated", "* 3 EXISTS", "E0007 OK NOOP completed",    # one came: 2 -> 3
        ])
        self.assertTrue(watcher.wait(60))
        self.assertEqual(sock.replies, [])

    def test_without_poll_every_it_is_one_long_idle_and_never_asks(self):
        watcher, sock = self.watcher(["+ idling", None, "E0004 OK IDLE terminated"], poll_every=None)
        self.assertFalse(watcher.wait(60))
        self.assertEqual([line for line in sock.sent if "NOOP" in line], [])

    def test_the_count_a_folder_had_when_selected_is_the_one_to_beat(self):
        sock = FakeSock(self.HELLO)
        self.assertEqual(mailbox.IdleWatcher(Conf, sock=sock)._exists, 3)

    def test_only_a_real_exists_line_counts(self):
        self.assertEqual(mailbox._exists_count(b"* 12 EXISTS"), 12)
        self.assertEqual(mailbox._exists_count(b"* 12 exists"), 12)
        self.assertEqual(mailbox._exists_count(b"* 0 EXISTS"), 0)
        for line in (b"* 3 FETCH (FLAGS (\\Seen))", b"* OK still here", b"E0004 OK EXISTS", b"* x EXISTS", b"+ idling", b""):
            self.assertIsNone(mailbox._exists_count(line), line)


class _Stop:
    """A stop flag whose waits are instant, and which sets itself after ``rounds`` of them.

    It also gives up after 50 looks, so that a watcher that wrongly never sleeps or never ends fails its test
    instead of looping for ever.
    """

    def __init__(self, rounds=1):
        self.rounds, self.waits, self._set, self.looks = rounds, [], False, 0

    def is_set(self):
        self.looks += 1
        if self.looks > 50:
            self._set = True
        return self._set

    def wait(self, seconds):
        self.waits.append(seconds)
        if len(self.waits) >= self.rounds:
            self._set = True
        return self._set


class SpamWatchTests(TestCase):
    def setUp(self):
        conf = AppSettings.load()
        conf.imap_host, conf.imap_user, conf.imap_password = "imap.x", "u@x.com", "p"
        conf.save()
        self.built = []

    def turn_on(self, on=True):
        conf = AppSettings.load()
        conf.imap_read_spam = on
        conf.save()

    def watch(self, watcher_class, stop, folder, fetched=None):
        # close_old_connections would end the test's own transaction.
        with mock.patch.object(mailbox, "IdleWatcher", watcher_class), mock.patch("django.db.close_old_connections"):
            mailbox.watch(
                on_mail=lambda: (fetched if fetched is not None else []).append(1),
                stop=stop, log=lambda _m: None, folder=folder,
            )

    def watcher_class(test, pushes=(True,), then=None):
        class Watcher:
            def __init__(self, _conf, folder=None):
                test.built.append(folder)
                self.rounds, self.closed = 0, False

            def wait(self, _seconds):
                self.rounds += 1
                if then:
                    then(self.rounds)
                return pushes[self.rounds - 1] if self.rounds <= len(pushes) else False

            def close(self):
                self.closed = True

        return Watcher

    def test_the_spam_watcher_sleeps_while_the_option_is_off(self):
        stop, fetched = _Stop(), []
        self.watch(self.watcher_class(), stop, mailbox.JUNK, fetched)
        self.assertEqual(self.built, [])
        self.assertEqual(fetched, [])
        self.assertEqual(stop.waits, [60])

    def test_the_spam_watcher_connects_to_the_spam_folder_when_asked(self):
        self.turn_on()
        stop, fetched = _Stop(rounds=99), []

        def then(rounds):
            if rounds >= 2:
                stop._set = True

        self.watch(self.watcher_class(pushes=(True, False), then=then), stop, mailbox.JUNK, fetched)
        self.assertEqual(self.built, [mailbox.JUNK])
        self.assertEqual(len(fetched), 2)               # once on connecting, once for the push

    def test_the_spam_watcher_lets_go_when_the_option_is_turned_off(self):
        self.turn_on()
        stop, fetched = _Stop(rounds=1), []
        watchers = []

        def then(rounds):
            self.turn_on(False)                          # the admin unticks it while the watcher waits

        base = self.watcher_class(pushes=(True,), then=then)

        class Watcher(base):
            def __init__(self, *args, **kwargs):
                super().__init__(*args, **kwargs)
                watchers.append(self)

        self.watch(Watcher, stop, mailbox.JUNK, fetched)
        self.assertEqual(len(fetched), 2)
        self.assertTrue(watchers[0].closed)
        self.assertEqual(watchers[0].rounds, 1)          # it did not wait again
        self.assertEqual(stop.waits, [60])               # and went back to sleeping

    def test_watch_polls_between_idles_and_says_how_the_mail_was_found(self):
        stop, logged, made = _Stop(rounds=99), [], []

        class Watcher:
            how = "poll"

            def __init__(self, _conf):
                made.append(self)

            def wait(self, _seconds):
                stop._set = True
                return True

            def close(self):
                pass

        with mock.patch.object(mailbox, "IdleWatcher", Watcher), mock.patch("django.db.close_old_connections"):
            mailbox.watch(on_mail=lambda: None, stop=stop, log=logged.append)
        self.assertEqual(made[0].poll_every, mailbox.POLL_SECONDS)
        self.assertIn("mail push: new mail announced (poll)", logged)

    def test_the_inbox_watcher_is_built_exactly_as_it_always_was(self):
        stop = _Stop(rounds=99)
        built = []

        class Watcher:
            def __init__(self, _conf):                   # no folder argument: the old signature
                built.append(1)

            def wait(self, _seconds):
                stop._set = True
                return False

            def close(self):
                pass

        self.watch(Watcher, stop, None)
        self.assertEqual(built, [1])

    def test_the_inbox_watcher_does_not_care_about_the_option(self):
        self.turn_on(False)
        stop = _Stop(rounds=99)
        self.watch(self.watcher_class(pushes=(False,), then=lambda rounds: setattr(stop, "_set", True)), stop, None)
        self.assertEqual(self.built, [None])

    def test_a_mailbox_with_no_spam_folder_is_left_alone_for_a_while(self):
        self.turn_on()
        stop = _Stop()

        class Watcher:
            def __init__(self, _conf, folder=None):
                raise mailbox.NoJunkFolder("لا", "no")

        self.watch(Watcher, stop, mailbox.JUNK)
        self.assertEqual(stop.waits, [900])

    def test_a_server_without_idle_leaves_the_polling_to_the_inbox_watcher(self):
        self.turn_on()
        stop, fetched = _Stop(), []

        class Watcher:
            def __init__(self, _conf, folder=None):
                raise mailbox.IdleUnsupported("لا", "no")

        self.watch(Watcher, stop, mailbox.JUNK, fetched)
        self.assertEqual(stop.waits, [3600])
        self.assertEqual(fetched, [])


class WorkerStartsBothWatchersTests(TestCase):
    def test_one_watcher_for_the_inbox_and_one_for_the_spam_folder(self):
        command = run_worker.Command()
        command._mail_lock = threading.Lock()
        with mock.patch.object(run_worker.threading, "Thread") as thread:
            command._start_push()
        calls = thread.call_args_list
        self.assertEqual([call.kwargs["name"] for call in calls], ["eagle-mail-push", "eagle-mail-push-spam"])
        self.assertEqual([call.kwargs["kwargs"]["folder"] for call in calls], [None, mailbox.JUNK])
        self.assertTrue(all(call.kwargs["target"] is mailbox.watch for call in calls))
        self.assertTrue(all(call.kwargs["daemon"] for call in calls))
        self.assertEqual(thread.return_value.start.call_count, 2)
        # Both rings go to the same fetch, which is never run twice at once.
        self.assertTrue(all(call.kwargs["kwargs"]["on_mail"] == command._fetch_mail for call in calls))


class SettingsDoorTests(_Settings):
    def fields(self):
        return {field["name"]: field for field in _json(self.get(self.admin, GET))["fields"]}

    def test_the_option_is_a_tick_box_in_the_receiving_group_and_off(self):
        body = _json(self.get(self.admin, GET))
        email = next(section for section in body["sections"] if section["key"] == "email")
        imap = next(group for group in email["groups"] if "imap_read_spam" in group["fields"])
        self.assertIn("imap_host", imap["fields"])
        field = self.fields()["imap_read_spam"]
        self.assertEqual((field["kind"], field["value"]), ("checkbox", False))
        self.assertIn("hint_ar", field)

    def test_the_admin_turns_it_on_and_off(self):
        self.assertEqual(self.save(imap_read_spam=True).status_code, 200)
        self.assertTrue(self.fresh().imap_read_spam)
        self.assertEqual(self.save(imap_read_spam=False).status_code, 200)
        self.assertFalse(self.fresh().imap_read_spam)
