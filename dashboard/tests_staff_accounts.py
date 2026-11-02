"""«حسابات الموظفين»: technical support works inside an employee's account and sets passwords (impersonation.py)."""

import json

from django.test import Client as DjangoClient
from django.test import TestCase
from django.urls import reverse

from . import identity, impersonation
from .models import AuditLog, Notification, Role, User

LIST = reverse("dashboard:v1_accounts")
LEAVE = reverse("dashboard:v1_account_leave")
ME = reverse("dashboard:v1_me")


def enter_url(person):
    return reverse("dashboard:v1_account_enter", args=[person.pk])


def password_url(person):
    return reverse("dashboard:v1_account_password", args=[person.pk])


class _Accounts(TestCase):
    def setUp(self):
        make = lambda name, role, **kw: User.objects.create_user(name, password="Old-pass-4821", role=role, **kw)
        self.support = make("person_support", Role.SUPPORT)
        self.admin = make("person_admin", Role.ADMIN)
        self.ops = make("person_operation", Role.OPERATION)
        self.tr = make("person_translator", Role.TRANSLATOR)
        self.hr = make("person_hr_staff", Role.HR)
        self.other_support = make("person_support_two", Role.SUPPORT)
        self.off = make("person_off", Role.SALES, is_active=False)

    def browser(self, user):
        browser = DjangoClient()
        browser.force_login(user)
        return browser

    def inside(self, person):
        browser = self.browser(self.support)
        answer = browser.post(enter_url(person))
        self.assertEqual(answer.status_code, 200, answer.content)
        return browser


class ListTests(_Accounts):
    def test_support_sees_the_working_staff_without_the_owner_and_support(self):
        answer = self.browser(self.support).get(LIST)
        self.assertEqual(answer.status_code, 200)
        names = {row["username"] for row in answer.json()["accounts"]}
        self.assertEqual(names, {"person_operation", "person_translator", "person_hr_staff"})

    def test_a_deleted_employee_is_not_on_the_list(self):
        from django.utils import timezone

        User.objects.filter(pk=self.tr.pk).update(deleted_at=timezone.now())
        names = {row["username"] for row in self.browser(self.support).get(LIST).json()["accounts"]}
        self.assertNotIn("person_translator", names)

    def test_nobody_else_reaches_the_doors(self):
        for person in (self.ops, self.tr, self.hr):
            browser = self.browser(person)
            with self.subTest(role=person.role):
                self.assertEqual(browser.get(LIST).status_code, 403)
                self.assertEqual(browser.post(enter_url(self.tr)).status_code, 403)
                self.assertEqual(browser.post(password_url(self.tr), "{}", content_type="application/json").status_code, 403)
        self.assertEqual(DjangoClient().get(LIST).status_code, 401)


class EnterTests(_Accounts):
    def test_support_sees_the_app_as_the_person(self):
        browser = self.inside(self.tr)
        me = browser.get(ME).json()
        self.assertEqual(me["user"]["username"], "person_translator")
        self.assertEqual(me["screens"], self.browser(self.tr).get(ME).json()["screens"])
        self.assertEqual(me["impersonating"], {"by": self.support.short_name})
        row = AuditLog.objects.get(action=impersonation.ENTER)
        self.assertEqual((row.actor_id, row.target), (self.support.pk, "person_translator"))

    def test_the_person_is_not_shown_as_signed_in_or_online(self):
        browser = self.inside(self.tr)
        browser.get(reverse("dashboard:api_heartbeat"))
        self.tr.refresh_from_db()
        self.assertIsNone(self.tr.last_login)
        self.assertIsNone(self.tr.last_seen)

    def test_support_acts_inside_as_the_person(self):
        Notification.objects.create(user=self.tr, title_ar="x", title_en="x")
        browser = self.inside(self.tr)
        answer = browser.post(reverse("dashboard:v1_notifications_read"), json.dumps({"all": True}), content_type="application/json")
        self.assertEqual(answer.status_code, 200, answer.content)
        self.assertTrue(Notification.objects.get(user=self.tr).is_read)

    def test_attendance_is_never_punched_inside(self):
        from .models import WorkDay

        before = WorkDay.objects.count()
        browser = self.inside(self.tr)
        answer = browser.post(reverse("dashboard:api_attendance_punch"), {"action": "check_in"})
        self.assertEqual((answer.status_code, answer.json()["ok"], answer.json()["error"]), (200, False, "support_inside"))
        self.assertTrue(answer.json()["ar"])
        self.assertEqual(WorkDay.objects.count(), before)

    def test_back_to_my_account(self):
        browser = self.inside(self.tr)
        self.assertEqual(browser.post(LEAVE).status_code, 200)
        me = browser.get(ME).json()
        self.assertEqual((me["user"]["username"], me["impersonating"]), ("person_support", None))
        self.assertTrue(AuditLog.objects.filter(action=impersonation.LEAVE, actor=self.support, target="person_translator").exists())
        # And writing works again: support's own doors are support's.
        self.assertEqual(browser.get(LIST).status_code, 200)

    def test_the_owner_support_itself_and_a_switched_off_account_are_not_opened(self):
        browser = self.browser(self.support)
        for person in (self.admin, self.other_support, self.support, self.off):
            with self.subTest(person=person.username):
                self.assertEqual(browser.post(enter_url(person)).status_code, 404)
        self.assertEqual(browser.get(ME).json()["user"]["username"], "person_support")

    def test_support_switched_off_while_inside_is_signed_out(self):
        browser = self.inside(self.tr)
        User.objects.filter(pk=self.support.pk).update(is_active=False)
        self.assertEqual(browser.get(ME).status_code, 401)

    def test_a_person_made_owner_while_looked_at_ends_the_look(self):
        browser = self.inside(self.tr)
        User.objects.filter(pk=self.tr.pk).update(role=Role.ADMIN)
        self.assertEqual(browser.get(ME).status_code, 401)

    def test_an_audit_row_written_inside_names_support(self):
        browser = self.inside(self.tr)
        browser.get(reverse("dashboard:v1_announce"))
        row = AuditLog.objects.filter(action=identity.ACCESS_DENIED).latest("id")
        self.assertEqual(row.actor_id, self.tr.pk)
        self.assertIn("[support person_support]", row.detail)


class PasswordTests(_Accounts):
    def set(self, person, one, two=None):
        return self.browser(self.support).post(
            password_url(person), json.dumps({"new_password1": one, "new_password2": two if two is not None else one}),
            content_type="application/json",
        )

    def test_support_gives_a_new_password(self):
        answer = self.set(self.tr, "Brand-new-7731")
        self.assertEqual(answer.status_code, 200, answer.content)
        self.tr.refresh_from_db()
        self.assertTrue(self.tr.check_password("Brand-new-7731"))
        row = AuditLog.objects.get(action=impersonation.PASSWORD_SET)
        self.assertEqual((row.actor_id, row.target), (self.support.pk, "person_translator"))
        self.assertNotIn("Brand-new-7731", row.detail)

    def test_the_person_is_signed_out_by_the_change(self):
        browser = self.browser(self.tr)
        self.assertEqual(browser.get(ME).status_code, 200)
        self.set(self.tr, "Brand-new-7731")
        self.assertEqual(browser.get(ME).status_code, 401)

    def test_the_project_rules_hold(self):
        for one, two in (("abc", "abc"), ("Brand-new-7731", "Brand-new-7732"), ("", "")):
            with self.subTest(one=one, two=two):
                self.assertEqual(self.set(self.tr, one, two).status_code, 400)
        self.tr.refresh_from_db()
        self.assertTrue(self.tr.check_password("Old-pass-4821"))

    def test_the_owner_and_support_keep_theirs(self):
        for person in (self.admin, self.other_support):
            with self.subTest(person=person.username):
                self.assertEqual(self.set(person, "Brand-new-7731").status_code, 404)
                person.refresh_from_db()
                self.assertTrue(person.check_password("Old-pass-4821"))
