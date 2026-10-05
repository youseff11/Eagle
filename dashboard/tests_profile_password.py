"""A person changes their own password (``api_profile.password_change``).

Held here: anybody signed in can, whatever the role, and only their own; the current password is asked for and a wrong one
changes nothing; wrong guesses are counted and shut the door for a while (a right one is no way in during it); the new one
must pass the project's validators and be typed twice; the session that changed it stays signed in and the others do not;
and the password is in no answer and no audit row.
"""

import json
from datetime import timedelta
from unittest import mock

from django.test import Client as DjangoClient
from django.urls import reverse
from django.utils import timezone

from . import identity, services
from .models import AuditLog, Role, User
from .tests_api_v1 import _Site, _json

URL = "dashboard:v1_me_password"
#: Not the stored "pw": long, uncommon, not close to a name.
FRESH = "Quiet-harbour-77-lantern"


def _body(old="pw", new=FRESH, again=None):
    return {"old_password": old, "new_password1": new, "new_password2": new if again is None else again}


class _Change(_Site):
    def post(self, who, body, raw=None, content_type="application/json"):
        browser = DjangoClient()
        if who is not None:
            browser.force_login(who)
        data = raw if raw is not None else json.dumps(body)
        return browser.post(reverse(URL), data, content_type=content_type), browser

    def stored(self, person):
        return User.objects.get(pk=person.pk).password


class ChangeTests(_Change):
    def test_every_role_changes_its_own_and_can_then_sign_in_with_the_new_one_only(self):
        for person in self.everyone:
            answer, _browser = self.post(person, _body())
            self.assertEqual((answer.status_code, _json(answer)), (200, {"ok": True}), person.role)
            self.assertFalse(DjangoClient().login(username=person.username, password="pw"), person.role)
            self.assertTrue(DjangoClient().login(username=person.username, password=FRESH), person.role)

    def test_only_the_signed_in_persons_own_password_changes(self):
        others = {person.pk: self.stored(person) for person in self.everyone if person.pk != self.tr.pk}
        self.post(self.tr, _body())
        for person in self.everyone:
            if person.pk != self.tr.pk:
                self.assertEqual(self.stored(person), others[person.pk], person.username)

    def test_the_address_names_nobody_and_a_body_cannot_name_somebody_else(self):
        before = self.stored(self.ops)
        answer, _browser = self.post(self.tr, {**_body(), "user": self.ops.pk, "id": self.ops.pk, "username": self.ops.username})
        self.assertEqual(answer.status_code, 200)
        self.assertEqual(self.stored(self.ops), before)

    def test_the_session_that_changed_it_stays_in_and_the_others_are_signed_out(self):
        answer, here = self.post(self.tr, _body())
        self.assertEqual(answer.status_code, 200)
        self.assertEqual(here.get(reverse("dashboard:v1_me")).status_code, 200)
        elsewhere = DjangoClient()
        elsewhere.force_login(self.tr)
        # A second session started with the old password is not good any more once the password has changed.
        self.post(self.tr, _body(old=FRESH, new="Another-calm-pier-88-mist"))
        self.assertEqual(elsewhere.get(reverse("dashboard:v1_me")).status_code, 401)

    def test_a_change_is_written_down_without_the_password(self):
        self.post(self.tr, _body())
        rows = AuditLog.objects.filter(actor=self.tr, action="profile.password")
        self.assertEqual(rows.count(), 1)
        every_row = " ".join(f"{row.action} {row.target} {row.detail}" for row in AuditLog.objects.all())
        for secret in (FRESH, "pw"):
            self.assertNotIn(secret + " ", every_row + " ")

    def test_the_answer_carries_no_password_and_is_private(self):
        answer, _browser = self.post(self.tr, _body())
        self.assertEqual(answer["Cache-Control"], "private, no-store")
        text = answer.content.decode("utf-8")
        for secret in (FRESH, "pw", "pbkdf2", "md5"):
            self.assertNotIn(secret, text.replace('"ok"', ""))


class RefusalTests(_Change):
    def test_a_wrong_current_password_changes_nothing_and_is_counted(self):
        before = self.stored(self.tr)
        answer, _browser = self.post(self.tr, _body(old="not-it"))
        self.assertEqual((answer.status_code, _json(answer)["error"]), (400, "wrong_password"))
        self.assertEqual(self.stored(self.tr), before)
        self.assertEqual(AuditLog.objects.filter(actor=self.tr, action="profile.password_refused").count(), 1)
        self.assertNotIn("not-it", " ".join(row.detail for row in AuditLog.objects.all()))

    def test_an_empty_current_password_is_wrong_too(self):
        answer, _browser = self.post(self.tr, _body(old=""))
        self.assertEqual((answer.status_code, _json(answer)["error"]), (400, "wrong_password"))

    def test_five_wrong_ones_shut_the_door_even_to_the_right_one(self):
        for _ in range(services.RESET_WRONG_LIMIT):
            self.assertEqual(self.post(self.tr, _body(old="not-it"))[0].status_code, 400)
        before = self.stored(self.tr)
        answer, _browser = self.post(self.tr, _body())
        self.assertEqual((answer.status_code, _json(answer)["error"]), (429, "too_many_attempts"))
        self.assertEqual(self.stored(self.tr), before)
        # A refusal while shut is its own row and is not counted: waiting does not push the end of the window away.
        self.assertEqual(AuditLog.objects.filter(actor=self.tr, action="profile.password_locked").count(), 1)
        self.assertEqual(AuditLog.objects.filter(actor=self.tr, action="profile.password_refused").count(), services.RESET_WRONG_LIMIT)

    def test_the_door_opens_again_once_the_window_has_passed(self):
        for _ in range(services.RESET_WRONG_LIMIT):
            self.post(self.tr, _body(old="not-it"))
        AuditLog.objects.filter(actor=self.tr, action="profile.password_refused").update(
            created_at=timezone.now() - timedelta(minutes=services.RESET_LOCK_MINUTES + 1),
        )
        self.assertEqual(self.post(self.tr, _body())[0].status_code, 200)

    def test_one_persons_wrong_guesses_do_not_shut_another_persons_door(self):
        for _ in range(services.RESET_WRONG_LIMIT):
            self.post(self.tr, _body(old="not-it"))
        self.assertEqual(self.post(self.ops, _body())[0].status_code, 200)

    def test_two_new_passwords_that_differ_are_refused_beside_their_box_and_nothing_changes(self):
        before = self.stored(self.tr)
        answer, _browser = self.post(self.tr, _body(again=FRESH + "x"))
        body = _json(answer)
        self.assertEqual((answer.status_code, body["error"]), (400, "invalid"))
        self.assertIn("new_password2", body["errors"])
        self.assertEqual(self.stored(self.tr), before)

    def test_a_password_the_project_refuses_is_refused(self):
        before = self.stored(self.tr)
        for weak in ("short1", "password123", "12345678901234", "person_translator"):
            answer, _browser = self.post(self.tr, _body(new=weak))
            self.assertEqual((answer.status_code, _json(answer)["error"]), (400, "invalid"), weak)
        self.assertEqual(self.stored(self.tr), before)

    def test_a_failed_change_leaves_the_old_password_working(self):
        self.post(self.tr, _body(new="short1"))
        self.assertTrue(DjangoClient().login(username=self.tr.username, password="pw"))

    def test_a_body_that_is_not_the_shape_is_refused_and_nothing_changes(self):
        before = self.stored(self.tr)
        for body in ([], "text", {"old_password": 5, "new_password1": FRESH, "new_password2": FRESH},
                     {"old_password": "pw", "new_password1": [FRESH], "new_password2": FRESH},
                     {"old_password": "pw", "new_password1": FRESH + "\x00", "new_password2": FRESH + "\x00"},
                     {"old_password": "pw", "new_password1": "a" * 500, "new_password2": "a" * 500}):
            answer, _browser = self.post(self.tr, body)
            self.assertEqual((answer.status_code, _json(answer)["error"]), (400, "bad_body"), body)
        answer, _browser = self.post(self.tr, None, raw="old_password=pw", content_type="application/x-www-form-urlencoded")
        self.assertEqual(answer.status_code, 400)
        self.assertEqual(self.stored(self.tr), before)


class ShutDoorTests(_Change):
    """What happens at and past the limit: the guessing session is signed out, one row says so, one count is kept for all doors."""

    def shut(self, person):
        for _ in range(services.RESET_WRONG_LIMIT):
            self.post(person, _body(old="not-it"))

    def test_the_session_that_guesses_past_the_limit_is_signed_out(self):
        self.shut(self.tr)
        answer, browser = self.post(self.tr, _body(old="not-it"))
        self.assertEqual((answer.status_code, _json(answer)["error"]), (429, "too_many_attempts"))
        # A stolen cookie that keeps guessing does not keep its session.
        self.assertEqual(browser.get(reverse("dashboard:v1_me")).status_code, 401)

    def test_a_signed_in_person_who_has_not_guessed_wrong_is_not_signed_out_by_a_good_change(self):
        answer, browser = self.post(self.tr, _body())
        self.assertEqual(answer.status_code, 200)
        self.assertEqual(browser.get(reverse("dashboard:v1_me")).status_code, 200)

    def test_every_try_while_shut_is_one_row_and_not_a_row_each(self):
        self.shut(self.tr)
        for _ in range(4):
            self.assertEqual(self.post(self.tr, _body())[0].status_code, 429)
        self.assertEqual(AuditLog.objects.filter(actor=self.tr, action=identity.PASSWORD_LOCKED).count(), 1)

    def test_the_rows_carry_the_address_and_are_security_rows(self):
        self.post(self.tr, _body(old="not-it"))
        self.post(self.tr, _body())
        for action in (identity.PASSWORD_REFUSED, identity.PASSWORD_CHANGE):
            row = AuditLog.objects.get(actor=self.tr, action=action)
            self.assertEqual((row.ip, row.path), ("127.0.0.1", reverse(URL)), action)
            self.assertIn(action, identity.SECURITY_ACTIONS)
        self.assertIn(identity.PASSWORD_LOCKED, identity.SECURITY_ACTIONS)

    def test_the_clear_outs_and_the_profile_share_one_count_of_wrong_passwords(self):
        self.assertIn(identity.PASSWORD_REFUSED, services.WRONG_PASSWORD_ACTIONS)
        for action in ("task.reset_refused", "mail.reset_refused", "client.reset_refused"):
            self.assertIn(action, services.WRONG_PASSWORD_ACTIONS)
        # Wrong passwords typed at the clear-outs count here, and the other way round.
        for _ in range(services.RESET_WRONG_LIMIT):
            services.log(self.admin, "task.reset_refused", "", "wrong password")
        self.assertEqual(self.post(self.admin, _body())[0].status_code, 429)
        self.shut(self.ops)
        self.assertEqual(services.reset_password_problem(self.ops, "pw", "task"), services.RESET_LOCKED_MESSAGE)


class StaleRowTests(_Change):
    def test_only_the_password_is_written_so_an_admins_change_in_between_is_not_undone(self):
        real = User.check_password

        def meanwhile(user, raw):
            # The admin switches the person off and changes their role while this request is still working.
            User.objects.filter(pk=user.pk).update(is_active=False, role=Role.SALES, client_identity_access=False)
            return real(user, raw)

        with mock.patch.object(User, "check_password", autospec=True, side_effect=meanwhile):
            answer, _browser = self.post(self.tr, _body())
        self.assertEqual(answer.status_code, 200)
        fresh = User.objects.get(pk=self.tr.pk)
        self.assertEqual((fresh.is_active, fresh.role), (False, Role.SALES))
        self.assertTrue(fresh.check_password(FRESH))


class DoorTests(_Change):
    def test_nobody_signed_out_is_answered(self):
        answer, _browser = self.post(None, _body())
        self.assertEqual(answer.status_code, 401)

    def test_a_post_without_the_csrf_token_is_refused_and_changes_nothing(self):
        browser = DjangoClient(enforce_csrf_checks=True)
        browser.force_login(self.tr)
        before = self.stored(self.tr)
        answer = browser.post(reverse(URL), json.dumps(_body()), content_type="application/json")
        self.assertEqual(answer.status_code, 403)
        self.assertEqual(self.stored(self.tr), before)

    def test_a_lone_surrogate_is_a_refused_body_and_not_a_crash(self):
        before = self.stored(self.tr)
        answer, _browser = self.post(self.tr, None, raw='{"old_password": "\\ud800", "new_password1": "x", "new_password2": "x"}')
        self.assertEqual((answer.status_code, _json(answer)["error"]), (400, "bad_body"))
        self.assertEqual(self.stored(self.tr), before)

    def test_it_is_a_post(self):
        browser = DjangoClient()
        browser.force_login(self.tr)
        answer = browser.get(reverse(URL))
        self.assertEqual((answer.status_code, answer["Allow"]), (405, "POST"))
