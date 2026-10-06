"""Technical support tells every employee something: a notification to all, only from the support account (and the owner)."""

import json

from django.test import Client as DjangoClient
from django.urls import reverse

from . import services
from .models import AuditLog, Notification, Role, User
from .tests_api_v1 import _Site, _json

DOOR = "dashboard:v1_announce"


class _Announce(_Site):
    def setUp(self):
        super().setUp()
        self.support = User.objects.create_user("person_support", password="pw", role=Role.SUPPORT, first_name="Sami", last_name="Support")
        # The fixture's own task hand-offs notified people: what is counted here is only what an announcement sends.
        Notification.objects.all().delete()

    def send(self, user, body=None, raw=None, content_type="application/json"):
        browser = DjangoClient()
        browser.force_login(user)
        data = raw if raw is not None else json.dumps(body or {})
        return browser.post(reverse(DOOR), data, content_type=content_type)

    def read(self, user):
        browser = DjangoClient()
        browser.force_login(user)
        return browser.get(reverse(DOOR))


class SendingTests(_Announce):
    def test_everybody_active_but_the_sender_is_told(self):
        off = User.objects.create_user("person_gone", password="pw", role=Role.TRANSLATOR, is_active=False)
        answer = self.send(self.support, {"title": "System restart at 6", "body": "Save your work.", "level": "warning", "sound": True})
        self.assertEqual(answer.status_code, 200, answer.content)
        self.assertEqual(_json(answer)["reached"], len(self.everyone))
        for person in self.everyone:
            note = Notification.objects.get(user=person)
            with self.subTest(person=person.role):
                self.assertEqual((note.title_ar, note.title_en), ("System restart at 6",) * 2)
                self.assertEqual((note.body_ar, note.body_en), ("Save your work.",) * 2)
                self.assertEqual((note.level, note.sound, note.url, note.is_read), ("warning", True, "", False))
        self.assertFalse(Notification.objects.filter(user__in=[self.support, off]).exists())

    def test_it_is_written_to_the_audit_log_with_who_and_how_many(self):
        self.send(self.support, {"title": "Hello", "body": "all"})
        row = AuditLog.objects.get(action=services.ANNOUNCE_ACTION)
        self.assertEqual((row.actor_id, row.target), (self.support.pk, "Hello"))
        self.assertTrue(row.detail.endswith(f"\n{len(self.everyone)}"))

    def test_sound_is_off_unless_asked_for_with_a_real_true(self):
        self.send(self.support, {"title": "Quiet", "sound": "yes"})
        self.assertFalse(Notification.objects.filter(sound=True).exists())

    def test_a_title_is_needed_and_the_level_is_one_we_know(self):
        for body in ({"title": "  "}, {"body": "no title"}, {"title": "x", "level": "danger"}, {"title": "x" * 201}, {"title": "x", "body": "y" * 401}):
            with self.subTest(body=body):
                self.assertEqual(self.send(self.support, body).status_code, 400)
        self.assertFalse(Notification.objects.exists())

    def test_an_unreadable_body_is_refused(self):
        self.assertEqual(self.send(self.support, raw="not json").status_code, 400)
        self.assertEqual(self.send(self.support, raw="title=x", content_type="application/x-www-form-urlencoded").status_code, 400)
        self.assertEqual(self.send(self.support, {"title": "a\x00b"}).status_code, 400)
        self.assertFalse(Notification.objects.exists())

    def test_the_same_words_twice_in_a_row_are_sent_once(self):
        first = self.send(self.support, {"title": "Again", "body": "x"})
        second = self.send(self.support, {"title": "Again", "body": "x"})
        self.assertEqual((first.status_code, second.status_code), (200, 409))
        self.assertEqual(Notification.objects.filter(user=self.tr).count(), 1)
        # Other words are another announcement.
        self.assertEqual(self.send(self.support, {"title": "Again", "body": "y"}).status_code, 200)
        self.assertEqual(Notification.objects.filter(user=self.tr).count(), 2)


class WhoMaySendTests(_Announce):
    def test_support_and_the_owner_may_and_nobody_else(self):
        self.assertEqual(self.send(self.admin, {"title": "From the owner"}).status_code, 200)
        Notification.objects.all().delete()
        for person in self.everyone:
            if person.role == Role.ADMIN:
                continue
            with self.subTest(person=person.role):
                self.assertEqual(self.send(person, {"title": "Hello everybody"}).status_code, 403)
                self.assertEqual(self.read(person).status_code, 403)
        self.assertFalse(Notification.objects.exists())

    def test_nobody_signed_out_may(self):
        browser = DjangoClient()
        self.assertEqual(browser.post(reverse(DOOR), "{}", content_type="application/json").status_code, 401)
        self.assertEqual(browser.get(reverse(DOOR)).status_code, 401)


class ReadingTests(_Announce):
    def test_it_says_how_many_it_would_reach_and_lists_the_latest(self):
        before = _json(self.read(self.support))
        self.assertEqual(before["reach"], len(self.everyone))
        self.assertEqual(before["recent"], [])
        self.send(self.support, {"title": "One", "body": "first"})
        after = _json(self.read(self.support))
        row = after["recent"][0]
        self.assertEqual((row["title"], row["body"], row["reached"], row["by"]), ("One", "first", len(self.everyone), "Sami Support"))

    def test_the_list_holds_the_latest_ten(self):
        for index in range(12):
            services.announce(self.support, title=f"n{index}")
        titles = [row["title"] for row in _json(self.read(self.support))["recent"]]
        self.assertEqual(len(titles), 10)
        self.assertIn("n11", titles)
        self.assertNotIn("n0", titles)
