"""The admin panel's staff pages in the new app: the list, a person's file, a new person, the shifts.

Only the admin is answered. The forms are the classic forms, so what they refuse is refused here and what the classic page
wrote down is written down here. A password is accepted on the one request that makes a person and appears nowhere else.
"""

import json
from datetime import time, timedelta
from unittest import mock

from django.db import connection
from django.test import Client as DjangoClient
from django.test.utils import CaptureQueriesContext
from django.urls import reverse
from django.utils import timezone

from . import api_forms, attendance, identity, views
from .forms import StaffEditForm
from .models import AppSettings, AuditLog, Role, Shift, ShiftTemplate, Task, TaskStatus, User
from .tests_admin_screen import _Admin
from .tests_api_v1 import _json

LIST = "dashboard:v1_admin_users"
NEW = "dashboard:v1_admin_user_new"
CREATE = "dashboard:v1_admin_user_create"
ONE = "dashboard:v1_admin_user"
SAVE = "dashboard:v1_admin_user_save"
PICK = "dashboard:v1_admin_user_shift"
SHIFT_ADD = "dashboard:v1_admin_shift_add"
SHIFT_DELETE = "dashboard:v1_admin_shift_delete"
SYNC = "dashboard:v1_admin_aliases_sync"

#: A password the project's validators accept; it is written nowhere but the one request that sets it.
PASSWORD = "Mx7-quiet-harbour-41"


class _Staff(_Admin):
    def post(self, user, name, body, args=None):
        browser = DjangoClient()
        if user is not None:
            browser.force_login(user)
        return browser.post(reverse(name, args=args), json.dumps(body), content_type="application/json")

    def new_person(self, **values):
        body = {
            "username": "person_new", "first_name": "Nora", "last_name": "Hassan", "role": "operation",
            "password1": PASSWORD, "password2": PASSWORD,
        }
        body.update(values)
        return self.post(self.admin, CREATE, {"values": body})


class DoorMatrixTests(_Staff):
    def doors(self):
        return [
            ("GET", LIST, None), ("GET", NEW, None), ("GET", ONE, [self.tr.pk]),
            ("POST", CREATE, None), ("POST", SAVE, [self.tr.pk]), ("POST", PICK, [self.tr.pk]),
            ("POST", SHIFT_ADD, [self.tr.pk]), ("POST", SHIFT_DELETE, [self.tr.pk, 1]), ("POST", SYNC, None),
        ]

    def call(self, user, method, name, args):
        browser = DjangoClient()
        if user is not None:
            browser.force_login(user)
        url = reverse(name, args=args)
        if method == "GET":
            return browser.get(url)
        return browser.post(url, "{}", content_type="application/json")

    def test_only_the_admin_is_answered(self):
        for method, name, args in self.doors():
            for user in (self.ops, self.lead, self.tr, self.hr, self.reviewer, self.accounting, self.sales):
                denied = self.call(user, method, name, args)
                self.assertEqual((denied.status_code, _json(denied)), (403, {"ok": False, "error": "forbidden"}), (name, user.username))
            self.assertEqual(self.call(None, method, name, args).status_code, 401, name)
            self.assertNotEqual(self.call(self.admin, method, name, args).status_code, 403, name)

    def test_the_wrong_method_is_a_405_that_says_what_is_allowed(self):
        for method, name, args in self.doors():
            other = "POST" if method == "GET" else "GET"
            answer = self.call(self.admin, other, name, args)
            self.assertEqual((answer.status_code, answer["Allow"]), (405, method), name)

    def test_every_answer_is_private(self):
        for method, name, args in self.doors():
            self.assertEqual(self.call(self.admin, method, name, args)["Cache-Control"], "private, no-store", name)


class ListTests(_Staff):
    def test_every_person_is_a_row_with_what_the_classic_table_shows(self):
        rows = {row["username"]: row for row in _json(self.get(self.admin, LIST))["users"]}
        self.assertEqual(set(rows), {user.username for user in self.everyone})
        row = rows[self.tr.username]
        self.assertEqual((row["name"], row["team_lead"], row["role"]["value"], row["shifts"]), (self.tr.short_name, self.lead.short_name, "translator", 0))
        self.assertEqual(row["role"]["en"], "Translator")
        self.assertEqual(rows[self.lead.username]["team_lead"], None)
        self.assertEqual(row["rating"], float(self.tr.rating))

    def test_a_mail_address_and_the_shift_count_are_shown(self):
        self.ops.mail_alias = "ops1@example.com"
        self.ops.save()
        Shift.objects.create(user=self.ops, weekday=0, start_time=time(9), end_time=time(17))
        Shift.objects.create(user=self.ops, weekday=1, start_time=time(9), end_time=time(17))
        row = next(one for one in _json(self.get(self.admin, LIST))["users"] if one["id"] == self.ops.pk)
        self.assertEqual((row["mail_alias"], row["shifts"]), ("ops1@example.com", 2))

    def test_the_state_of_each_person_is_what_the_model_says(self):
        now = timezone.now()
        for person in (self.tr, self.lead, self.ops):
            person.last_seen = now
            person.save()
        self.hr.is_active = False
        self.hr.save()
        rows = {row["id"]: row for row in _json(self.get(self.admin, LIST))["users"]}
        self.assertEqual(rows[self.hr.pk]["state"], "disabled")
        # The translator and the leader hold the task in progress; the operation is just here.
        self.assertEqual(rows[self.tr.pk]["state"], "busy")
        self.assertEqual(rows[self.lead.pk]["state"], "busy")
        self.assertEqual(rows[self.ops.pk]["state"], "free")
        self.assertEqual(rows[self.reviewer.pk]["state"], "off")

    def test_busy_agrees_with_user_is_busy_for_every_role(self):
        now = timezone.now()
        for person in self.everyone:
            person.last_seen = now
            person.save()
        rows = {row["id"]: row for row in _json(self.get(self.admin, LIST))["users"]}
        for person in User.objects.all():
            self.assertEqual(rows[person.pk]["state"] == "busy", person.is_busy, person.username)

    def test_a_person_on_shift_who_has_not_opened_eagle_is_shift_not_free(self):
        local = timezone.localtime()
        Shift.objects.create(
            user=self.reviewer, weekday=local.weekday(),
            start_time=(local - timedelta(hours=1)).time(), end_time=(local + timedelta(hours=1)).time(),
        )
        rows = {row["id"]: row for row in _json(self.get(self.admin, LIST))["users"]}
        self.assertEqual(rows[self.reviewer.pk]["state"], "shift" if self.reviewer.on_shift else "off")

    def test_the_number_of_questions_does_not_grow_with_the_people(self):
        def questions():
            with CaptureQueriesContext(connection) as seen:
                self.assertEqual(self.get(self.admin, LIST).status_code, 200)
            return len(seen)

        few = questions()
        for index in range(15):
            person = User.objects.create_user(f"extra_{index}", password="pw", role=Role.TRANSLATOR, team_lead=self.lead)
            Shift.objects.create(user=person, weekday=0, start_time=time(9), end_time=time(17))
            Task.objects.create(client=self.client_obj, title=f"t{index}", created_by=self.ops, team_lead=self.lead, translator=person, status=TaskStatus.IN_PROGRESS)
        self.assertEqual(questions(), few)

    def test_a_get_changes_nothing(self):
        before = (AuditLog.objects.count(), User.objects.count())
        self.get(self.admin, LIST)
        self.assertEqual((AuditLog.objects.count(), User.objects.count()), before)

    def test_no_password_hash_is_in_the_answer(self):
        text = self.get(self.admin, LIST).content.decode("utf-8")
        self.assertNotIn("pbkdf2", text)
        self.assertNotIn(self.admin.password, text)


class FileTests(_Staff):
    def test_the_form_is_the_classic_forms_fields_in_order(self):
        body = _json(self.get(self.admin, ONE, [self.ops.pk]))
        self.assertEqual([field["name"] for field in body["form"]], list(StaffEditForm(instance=self.ops).fields))
        by_name = {field["name"]: field for field in body["form"]}
        self.assertEqual(by_name["role"]["kind"], "select")
        self.assertIn("operation", [choice["value"] for choice in by_name["role"]["choices"]])
        self.assertEqual(by_name["is_active"]["kind"], "checkbox")
        self.assertIs(by_name["is_active"]["value"], True)
        self.assertEqual(by_name["rating"]["kind"], "number")
        self.assertEqual(by_name["mail_alias"]["kind"], "select")

    def test_the_head_names_the_person(self):
        body = _json(self.get(self.admin, ONE, [self.tr.pk]))
        self.assertEqual(body["user"], {
            "id": self.tr.pk, "username": self.tr.username, "name": self.tr.short_name, "initials": self.tr.initials,
            "role": {"value": "translator", "ar": "مترجم", "en": "Translator"},
        })

    def test_the_mail_address_choices_say_who_holds_each(self):
        conf = AppSettings.load()
        conf.mail_aliases = "ops1@example.com\nops2@example.com"
        conf.save()
        self.other_ops = User.objects.create_user("person_operation_two", password="pw", role=Role.OPERATION, mail_alias="ops2@example.com")
        field = next(one for one in _json(self.get(self.admin, ONE, [self.ops.pk]))["form"] if one["name"] == "mail_alias")
        labels = {choice["value"]: choice["label"] for choice in field["choices"]}
        self.assertEqual(labels["ops1@example.com"], "ops1@example.com")
        self.assertIn("person_operation_two", labels["ops2@example.com"])
        self.assertIn("", labels)

    def test_the_shifts_and_the_penalties_are_listed(self):
        Shift.objects.create(user=self.tr, weekday=0, start_time=time(9), end_time=time(17))
        self.tr.apply_penalty(self.task, "Late", "اتأخر")
        body = _json(self.get(self.admin, ONE, [self.tr.pk]))
        self.assertEqual(len(body["shifts"]), 1)
        self.assertEqual(body["shifts"][0]["weekday"]["en"], "Monday")
        self.assertEqual(body["shifts"][0]["start"]["en"], "9:00 AM")
        self.assertEqual(body["shifts"][0]["end"]["ar"], "5:00 م")
        self.assertEqual(len(body["events"]), 1)
        self.assertEqual(body["events"][0]["reason"], "اتأخر")

    def test_the_shift_picker_agrees_with_the_classic_one(self):
        template = ShiftTemplate.objects.create(name="Noon", name_ar="الضهر", start_time=time(12), end_time=time(20))
        attendance.assign_shift(self.tr, template, [0, 1, 2])
        picker = _json(self.get(self.admin, ONE, [self.tr.pk]))["picker"]
        classic = views._shift_picker(self.tr, "/")
        self.assertEqual(picker["current"], classic["current"].pk)
        self.assertEqual(picker["has_custom"], classic["has_custom"])
        self.assertEqual([row["id"] for row in picker["templates"]], [row.pk for row in classic["templates"]])
        self.assertEqual([(row["num"], row["checked"]) for row in picker["days"]], [(row["num"], row["checked"]) for row in classic["days"]])

    def test_a_person_that_does_not_exist_is_a_404(self):
        self.assertEqual(self.get(self.admin, ONE, [999999]).status_code, 404)

    def test_opening_a_file_does_not_ask_google_or_write_anything(self):
        before = AuditLog.objects.count()
        with mock.patch("dashboard.galiases.sync") as sync:
            self.get(self.admin, ONE, [self.tr.pk])
        sync.assert_not_called()
        self.assertEqual(AuditLog.objects.count(), before)

    def test_no_password_is_in_the_file(self):
        text = self.get(self.admin, ONE, [self.ops.pk]).content.decode("utf-8")
        self.assertNotIn("pbkdf2", text)
        self.assertNotIn("password", [field["name"] for field in _json(self.get(self.admin, ONE, [self.ops.pk]))["form"]])

    def test_the_form_for_a_new_person_has_the_password_boxes_and_never_a_value_for_them(self):
        fields = {field["name"]: field for field in _json(self.get(self.admin, NEW))["form"]}
        for name in ("password1", "password2"):
            self.assertEqual(fields[name]["kind"], "password")
            self.assertNotIn("value", fields[name])
            self.assertIs(fields[name]["saved"], False)
        self.assertIn("username", fields)

    def test_the_number_of_questions_does_not_grow_with_the_shifts_and_penalties(self):
        def questions():
            with CaptureQueriesContext(connection) as seen:
                self.assertEqual(self.get(self.admin, ONE, [self.tr.pk]).status_code, 200)
            return len(seen)

        # One of each first: the first shift on a template and the first penalty each cost a question of their own.
        first = ShiftTemplate.objects.create(name="first", start_time=time(1), end_time=time(9))
        Shift.objects.create(user=self.tr, weekday=0, template=first)
        self.tr.apply_penalty(self.task, "Late", "اتأخر")
        few = questions()
        for day in range(1, 7):
            template = ShiftTemplate.objects.create(name=f"s{day}", start_time=time(day + 1), end_time=time(day + 9))
            Shift.objects.create(user=self.tr, weekday=day, template=template)
        for _ in range(10):
            self.tr.apply_penalty(self.task, "Late", "اتأخر")
        self.assertEqual(questions(), few)


class CreateTests(_Staff):
    def test_a_person_is_made_with_a_password_that_works_and_is_hashed(self):
        answer = self.new_person()
        self.assertEqual((answer.status_code, _json(answer)["ok"]), (200, True))
        person = User.objects.get(username="person_new")
        self.assertEqual((person.role, person.first_name), ("operation", "Nora"))
        self.assertTrue(person.check_password(PASSWORD))
        self.assertNotEqual(person.password, PASSWORD)
        self.assertEqual(_json(answer)["id"], person.pk)

    def test_the_password_is_nowhere_in_the_answer_or_the_log(self):
        answer = self.new_person()
        self.assertNotIn(PASSWORD, answer.content.decode("utf-8"))
        everything = json.dumps(list(AuditLog.objects.values()), default=str)
        self.assertNotIn(PASSWORD, everything)
        self.assertNotIn("pbkdf2", everything)

    def test_the_creation_is_written_down(self):
        self.new_person()
        self.assertTrue(AuditLog.objects.filter(action="user.create", target="person_new", actor=self.admin).exists())
        self.assertTrue(AuditLog.objects.filter(action=identity.ROLE_CHANGE, target="person_new").exists())

    def test_two_passwords_that_differ_are_refused_and_nobody_is_made(self):
        answer = self.new_person(password2="Other-quiet-harbour-41")
        self.assertEqual(answer.status_code, 400)
        body = _json(answer)
        self.assertEqual(body["error"], "invalid")
        self.assertIn("password2", body["errors"])
        self.assertFalse(User.objects.filter(username="person_new").exists())
        self.assertNotIn(PASSWORD, answer.content.decode("utf-8"))

    def test_a_password_the_project_refuses_is_refused(self):
        answer = self.new_person(password1="12345678", password2="12345678")
        self.assertEqual(answer.status_code, 400)
        self.assertFalse(User.objects.filter(username="person_new").exists())

    def test_a_name_that_is_taken_is_refused(self):
        answer = self.new_person(username=self.ops.username)
        self.assertEqual((answer.status_code, "username" in _json(answer)["errors"]), (400, True))

    def test_a_team_leader_can_be_picked_only_among_leaders(self):
        ok = self.new_person(role="translator", team_lead=str(self.lead.pk))
        self.assertEqual(ok.status_code, 200)
        self.assertEqual(User.objects.get(username="person_new").team_lead_id, self.lead.pk)
        bad = self.new_person(username="person_new_two", role="translator", team_lead=str(self.ops.pk))
        self.assertEqual((bad.status_code, "team_lead" in _json(bad)["errors"]), (400, True))

    def test_a_field_the_form_does_not_have_is_refused_and_nothing_is_made(self):
        for extra in ({"is_superuser": True}, {"password": PASSWORD}, {"is_staff": True}):
            answer = self.new_person(**extra)
            self.assertEqual((answer.status_code, _json(answer)["error"]), (400, "bad_body"), extra)
        self.assertFalse(User.objects.filter(username="person_new").exists())

    def test_a_body_that_is_not_the_shape_is_refused(self):
        browser = DjangoClient()
        browser.force_login(self.admin)
        for payload, kind in (("[]", "application/json"), ("{", "application/json"), ('{"values": []}', "application/json"), ("values=1", "application/x-www-form-urlencoded")):
            answer = browser.post(reverse(CREATE), payload, content_type=kind)
            self.assertEqual((answer.status_code, _json(answer)["error"]), (400, "bad_body"), payload)

    def test_values_of_the_wrong_kind_are_refused(self):
        for values in ({"username": ["a"]}, {"username": {"a": 1}}, {"username": True}, {"username": "a\x00b"}):
            answer = self.post(self.admin, CREATE, {"values": {"role": "operation", "password1": PASSWORD, "password2": PASSWORD, **values}})
            self.assertEqual(answer.status_code, 400, values)

    def test_a_person_made_here_can_sign_in_with_the_password(self):
        self.new_person()
        browser = DjangoClient()
        self.assertTrue(browser.login(username="person_new", password=PASSWORD))


class SaveTests(_Staff):
    def save(self, person, **values):
        return self.post(self.admin, SAVE, {"values": values}, [person.pk])

    def test_a_changed_field_is_saved_and_the_others_are_kept(self):
        self.tr.phone = "0100"
        self.tr.languages = "EN-AR"
        self.tr.save()
        answer = self.save(self.tr, first_name="Mahmoud")
        self.assertEqual((answer.status_code, _json(answer)["ok"]), (200, True))
        self.tr.refresh_from_db()
        self.assertEqual((self.tr.first_name, self.tr.phone, self.tr.languages, self.tr.is_active, self.tr.role), ("Mahmoud", "0100", "EN-AR", True, "translator"))
        self.assertEqual(self.tr.team_lead_id, self.lead.pk)

    def test_a_flag_is_cleared_only_when_it_is_sent_false(self):
        self.save(self.tr, first_name="X")
        self.tr.refresh_from_db()
        self.assertTrue(self.tr.is_active)
        self.save(self.tr, is_active=False)
        self.tr.refresh_from_db()
        self.assertFalse(self.tr.is_active)

    def test_the_save_is_written_down(self):
        self.save(self.tr, first_name="Mahmoud")
        self.assertTrue(AuditLog.objects.filter(action="user.update", target=self.tr.username, actor=self.admin).exists())

    def test_a_changed_role_is_written_down_with_before_and_after(self):
        self.save(self.tr, role="reviewer", team_lead="")
        row = AuditLog.objects.filter(action=identity.ROLE_CHANGE, target=self.tr.username).latest("pk")
        self.assertEqual(row.detail, "translator -> reviewer")
        self.assertEqual(row.actor_id, self.admin.pk)
        self.assertTrue(row.ip is None or row.ip)

    def test_an_identity_grant_to_accounting_is_written_down_and_to_anyone_else_refused(self):
        granted = self.save(self.accounting, client_identity_access=True)
        self.assertEqual(granted.status_code, 200)
        self.assertTrue(AuditLog.objects.filter(action=identity.ACCESS_GRANT, target=self.accounting.username, detail="granted").exists())
        self.accounting.refresh_from_db()
        self.assertTrue(self.accounting.can_see_client_identity)
        refused = self.save(self.ops, client_identity_access=True)
        self.assertEqual((refused.status_code, "client_identity_access" in _json(refused)["errors"]), (400, True))
        self.ops.refresh_from_db()
        self.assertFalse(self.ops.client_identity_access)
        self.assertFalse(self.ops.can_see_client_identity)

    def test_a_refused_save_changes_nothing(self):
        before = (self.ops.first_name, self.ops.role, self.ops.client_identity_access)
        count = AuditLog.objects.filter(action__in=("user.update", identity.ROLE_CHANGE, identity.ACCESS_GRANT)).count()
        answer = self.save(self.ops, first_name="Changed", role="translator", client_identity_access=True)
        self.assertEqual(answer.status_code, 400)
        self.ops.refresh_from_db()
        self.assertEqual((self.ops.first_name, self.ops.role, self.ops.client_identity_access), before)
        self.assertEqual(AuditLog.objects.filter(action__in=("user.update", identity.ROLE_CHANGE, identity.ACCESS_GRANT)).count(), count)

    def test_a_mail_address_is_given_to_one_person_and_written_down(self):
        conf = AppSettings.load()
        conf.mail_aliases = "ops1@example.com\nops2@example.com"
        conf.save()
        answer = self.save(self.ops, mail_alias="ops1@example.com")
        self.assertEqual(answer.status_code, 200)
        self.ops.refresh_from_db()
        self.assertEqual(self.ops.mail_alias, "ops1@example.com")
        self.assertTrue(AuditLog.objects.filter(action="user.mail_alias", target=self.ops.username, detail="- -> ops1@example.com").exists())

    def test_an_address_already_held_is_refused(self):
        conf = AppSettings.load()
        conf.mail_aliases = "ops1@example.com"
        conf.save()
        User.objects.create_user("person_operation_two", password="pw", role=Role.OPERATION, mail_alias="ops1@example.com")
        answer = self.save(self.ops, mail_alias="ops1@example.com")
        self.assertEqual((answer.status_code, "mail_alias" in _json(answer)["errors"]), (400, True))
        self.ops.refresh_from_db()
        self.assertEqual(self.ops.mail_alias, "")

    def test_an_address_for_a_role_that_has_none_is_refused(self):
        conf = AppSettings.load()
        conf.mail_aliases = "ops1@example.com"
        conf.save()
        answer = self.save(self.tr, mail_alias="ops1@example.com")
        self.assertEqual((answer.status_code, "mail_alias" in _json(answer)["errors"]), (400, True))

    def test_a_field_the_form_does_not_have_is_refused(self):
        for extra in ({"is_superuser": True}, {"password": PASSWORD}, {"username": "renamed"}, {"last_login": "2020-01-01"}):
            answer = self.save(self.tr, **extra)
            self.assertEqual((answer.status_code, _json(answer)["error"]), (400, "bad_body"), extra)
        self.tr.refresh_from_db()
        self.assertFalse(self.tr.is_superuser)

    def test_a_rating_out_of_the_decimal_shape_is_refused(self):
        answer = self.save(self.tr, rating="not a number")
        self.assertEqual((answer.status_code, "rating" in _json(answer)["errors"]), (400, True))

    def test_the_admin_cannot_be_turned_into_a_superuser_from_here(self):
        self.save(self.tr, first_name="A")
        self.tr.refresh_from_db()
        self.assertFalse(self.tr.is_superuser)

    def test_a_person_that_does_not_exist_is_a_404(self):
        self.assertEqual(self.post(self.admin, SAVE, {"values": {}}, [999999]).status_code, 404)

    def test_the_answer_carries_nothing_of_the_person(self):
        body = _json(self.save(self.tr, first_name="Mahmoud"))
        self.assertEqual(body, {"ok": True})


class ShiftTests(_Staff):
    def test_a_typed_shift_is_added_active_and_counted(self):
        answer = self.post(self.admin, SHIFT_ADD, {"weekday": 2, "start_time": "09:00", "end_time": "17:00"}, [self.tr.pk])
        self.assertEqual((answer.status_code, _json(answer)["ok"]), (200, True))
        row = Shift.objects.get(user=self.tr)
        self.assertEqual((row.weekday, row.start_time, row.end_time, row.is_active, row.required_minutes), (2, time(9), time(17), True, 0))
        self.assertEqual(len(self.tr.active_shifts()), 1)

    def test_a_shift_needs_both_times_and_they_must_differ(self):
        for body, error in (
            ({"weekday": 2, "start_time": "09:00"}, "times_required"),
            ({"weekday": 2, "start_time": "", "end_time": "17:00"}, "times_required"),
            ({"weekday": 2, "start_time": 9, "end_time": "17:00"}, "times_required"),
            ({"weekday": 2, "start_time": "09:00", "end_time": "09:00"}, "invalid"),
            ({"weekday": 2, "start_time": "25:99", "end_time": "17:00"}, "invalid"),
            ({"weekday": 9, "start_time": "09:00", "end_time": "17:00"}, "invalid"),
            ({"weekday": "x", "start_time": "09:00", "end_time": "17:00"}, "invalid"),
            ({"weekday": None, "start_time": "09:00", "end_time": "17:00"}, "invalid"),
        ):
            answer = self.post(self.admin, SHIFT_ADD, body, [self.tr.pk])
            self.assertEqual((answer.status_code, _json(answer)["error"]), (400, error), body)
        self.assertFalse(Shift.objects.filter(user=self.tr).exists())

    def test_a_night_shift_across_midnight_is_accepted(self):
        answer = self.post(self.admin, SHIFT_ADD, {"weekday": 0, "start_time": "17:00", "end_time": "01:00"}, [self.tr.pk])
        self.assertEqual(answer.status_code, 200)
        self.assertTrue(Shift.objects.get(user=self.tr).crosses_midnight)

    def test_a_shift_is_deleted_only_from_its_own_person(self):
        mine = Shift.objects.create(user=self.tr, weekday=0, start_time=time(9), end_time=time(17))
        other = Shift.objects.create(user=self.ops, weekday=0, start_time=time(9), end_time=time(17))
        wrong = self.post(self.admin, SHIFT_DELETE, {}, [self.tr.pk, other.pk])
        self.assertEqual(_json(wrong)["deleted"], 0)
        self.assertTrue(Shift.objects.filter(pk=other.pk).exists())
        right = self.post(self.admin, SHIFT_DELETE, {}, [self.tr.pk, mine.pk])
        self.assertEqual(_json(right)["deleted"], 1)
        self.assertFalse(Shift.objects.filter(pk=mine.pk).exists())

    def test_a_person_that_does_not_exist_is_a_404_for_a_new_shift(self):
        self.assertEqual(self.post(self.admin, SHIFT_ADD, {"weekday": 0, "start_time": "09:00", "end_time": "17:00"}, [999999]).status_code, 404)


class PickTests(_Staff):
    def setUp(self):
        super().setUp()
        self.noon = ShiftTemplate.objects.create(name="Noon", name_ar="الضهر", start_time=time(12), end_time=time(20))

    def rows(self, person):
        return sorted(Shift.objects.filter(user=person).values_list("weekday", "template_id"))

    def test_a_company_shift_for_some_days_replaces_the_roster(self):
        Shift.objects.create(user=self.tr, weekday=4, start_time=time(8), end_time=time(9))
        answer = self.post(self.admin, PICK, {"template": self.noon.pk, "weekdays": [0, 1, "2"]}, [self.tr.pk])
        self.assertEqual((answer.status_code, _json(answer)), (200, {"ok": True, "label": "الضهر"}))
        self.assertEqual(self.rows(self.tr), [(0, self.noon.pk), (1, self.noon.pk), (2, self.noon.pk)])
        self.assertTrue(AuditLog.objects.filter(action="schedule.assign", target=self.tr.username).exists())

    def test_no_shift_clears_the_roster(self):
        attendance.assign_shift(self.tr, self.noon, [0, 1])
        answer = self.post(self.admin, PICK, {"template": "", "weekdays": []}, [self.tr.pk])
        self.assertEqual((answer.status_code, _json(answer)["label"]), (200, ""))
        self.assertEqual(self.rows(self.tr), [])

    def test_a_new_shift_is_made_and_used_and_a_second_one_with_the_same_hours_is_reused(self):
        body = {"template": "new", "new_name": "Late", "new_start": "14:00", "new_end": "22:00", "weekdays": [0]}
        self.assertEqual(self.post(self.admin, PICK, body, [self.tr.pk]).status_code, 200)
        made = ShiftTemplate.objects.get(name="Late")
        self.assertEqual((made.start_time, made.end_time), (time(14), time(22)))
        self.assertEqual(self.post(self.admin, PICK, body, [self.ops.pk]).status_code, 200)
        self.assertEqual(ShiftTemplate.objects.filter(start_time=time(14), end_time=time(22)).count(), 1)

    def test_a_refusal_changes_nothing_and_leaves_no_half_made_shift(self):
        attendance.assign_shift(self.tr, self.noon, [0])
        before_templates = ShiftTemplate.objects.count()
        for body, error in (
            ({"template": "new", "new_start": "", "new_end": "15:00", "weekdays": [0]}, "bad_new_shift"),
            ({"template": "new", "new_start": "09:00", "new_end": "09:00", "weekdays": [0]}, "bad_new_shift"),
            ({"template": "new", "new_start": "06:00", "new_end": "14:00", "weekdays": []}, "no_days"),
            ({"template": 999999, "weekdays": [0]}, "no_such_shift"),
            ({"template": self.noon.pk, "weekdays": []}, "no_days"),
        ):
            answer = self.post(self.admin, PICK, body, [self.tr.pk])
            self.assertEqual((answer.status_code, _json(answer)["error"]), (400, error), body)
        self.assertEqual(self.rows(self.tr), [(0, self.noon.pk)])
        self.assertEqual(ShiftTemplate.objects.count(), before_templates)

    def test_a_digit_that_int_cannot_read_is_an_answer_and_not_a_crash(self):
        attendance.assign_shift(self.tr, self.noon, [0])
        for body, error in (
            ({"template": "²", "weekdays": [0]}, "no_such_shift"),
            ({"template": self.noon.pk, "weekdays": ["²"]}, "no_days"),
        ):
            answer = self.post(self.admin, PICK, body, [self.tr.pk])
            self.assertEqual((answer.status_code, _json(answer)["error"]), (400, error), body)
        self.assertEqual(self.rows(self.tr), [(0, self.noon.pk)])

    def test_days_that_are_all_invalid_refuse_the_choice_and_leave_the_roster_as_it_was(self):
        attendance.assign_shift(self.tr, self.noon, [0, 1])
        for days in ([7], ["x"], [-1, 9], [True], ["²", 7]):
            answer = self.post(self.admin, PICK, {"template": self.noon.pk, "weekdays": days}, [self.tr.pk])
            self.assertEqual(answer.status_code, 400, days)
        self.assertEqual(self.rows(self.tr), [(0, self.noon.pk), (1, self.noon.pk)])

    def test_arabic_indic_digits_are_read_as_the_digits_they_are(self):
        self.post(self.admin, PICK, {"template": str(self.noon.pk), "weekdays": ["٠", "١"]}, [self.tr.pk])
        self.assertEqual(self.rows(self.tr), [(0, self.noon.pk), (1, self.noon.pk)])

    def test_a_retired_shift_cannot_be_picked(self):
        self.noon.is_active = False
        self.noon.save()
        answer = self.post(self.admin, PICK, {"template": self.noon.pk, "weekdays": [0]}, [self.tr.pk])
        self.assertEqual(_json(answer)["error"], "no_such_shift")

    def test_days_that_are_not_days_are_dropped_like_the_classic_page_does(self):
        self.post(self.admin, PICK, {"template": self.noon.pk, "weekdays": [0, 7, "x", -1, 3]}, [self.tr.pk])
        self.assertEqual(self.rows(self.tr), [(0, self.noon.pk), (3, self.noon.pk)])

    def test_a_body_that_is_not_the_shape_is_refused(self):
        for body in (
            {"template": ["1"], "weekdays": [0]}, {"template": "1", "weekdays": "0"}, {"template": "1", "weekdays": [[0]]},
            {"template": "1", "weekdays": [True]}, {"template": "1", "weekdays": list(range(30))},
            {"template": "new", "new_name": "x" * 100, "weekdays": [0]}, {"template": "new", "new_start": 9, "weekdays": [0]},
        ):
            answer = self.post(self.admin, PICK, body, [self.tr.pk])
            self.assertEqual((answer.status_code, _json(answer)["error"]), (400, "bad_body"), body)

    def test_it_does_what_the_hr_page_does_for_the_same_choice(self):
        classic = DjangoClient()
        classic.force_login(self.hr)
        classic.post(f"/hr/employees/{self.ops.pk}/shift/", {"template": self.noon.pk, "weekdays": ["0", "1"]})
        self.post(self.admin, PICK, {"template": self.noon.pk, "weekdays": [0, 1]}, [self.tr.pk])
        self.assertEqual(self.rows(self.ops), [(day, template) for day, template in self.rows(self.tr)])


class AliasSyncTests(_Staff):
    def test_it_asks_google_at_most_once_a_minute_and_says_whether_it_did(self):
        with mock.patch("dashboard.galiases.sync", return_value=(True, "", None)) as sync:
            answer = self.post(self.admin, SYNC, {})
        sync.assert_called_once_with(every=60)
        self.assertEqual(_json(answer), {"ok": True, "ran": True})
        with mock.patch("dashboard.galiases.sync", return_value=(False, "", None)):
            self.assertEqual(_json(self.post(self.admin, SYNC, {}))["ran"], False)

    def test_a_failure_of_google_is_not_a_failure_of_the_door(self):
        with mock.patch("dashboard.galiases.sync", return_value=(False, "Google said no", None)):
            answer = self.post(self.admin, SYNC, {})
        self.assertEqual((answer.status_code, _json(answer)["ok"]), (200, True))
        self.assertNotIn("Google said no", answer.content.decode("utf-8"))


class FormToolTests(_Staff):
    """``api_forms`` on its own: the two promises of its docstring."""

    def test_a_secret_is_described_without_its_value(self):
        from .forms import SettingsForm

        conf = AppSettings.load()
        conf.claude_api_key = "sk-ant-SECRET-key"
        conf.save()
        described = api_forms.describe(SettingsForm(instance=conf))
        field = next(one for one in described if one["name"] == "claude_api_key")
        self.assertEqual((field["kind"], field["saved"]), ("password", True))
        self.assertNotIn("value", field)
        self.assertNotIn("sk-ant-SECRET-key", json.dumps(described))

    def test_a_bound_form_is_not_described(self):
        with self.assertRaises(ValueError):
            api_forms.describe(StaffEditForm({}, instance=self.ops))

    def test_an_absent_or_empty_secret_keeps_what_is_stored_and_null_clears_it(self):
        from .forms import SettingsForm

        conf = AppSettings.load()
        conf.claude_api_key = "sk-ant-SECRET-key"
        conf.save()
        for values in ({}, {"claude_api_key": ""}):
            data = api_forms.form_data(SettingsForm, values, instance=conf)
            self.assertEqual(data["claude_api_key"], "sk-ant-SECRET-key")
        self.assertEqual(api_forms.form_data(SettingsForm, {"claude_api_key": "new-value"}, instance=conf)["claude_api_key"], "new-value")
        self.assertEqual(api_forms.form_data(SettingsForm, {"claude_api_key": None}, instance=conf)["claude_api_key"], "")


class HandOnTests(_Staff):
    def test_the_staff_pages_go_on_with_the_switch(self):
        self.turn_on()
        pairs = (
            (self.get(self.admin, "dashboard:admin_users"), "/app/admin/users"),
            (self.get(self.admin, "dashboard:admin_user_new"), "/app/admin/users/new"),
            (self.get(self.admin, "dashboard:admin_user_edit", [self.tr.pk]), f"/app/admin/users/{self.tr.pk}"),
        )
        for answer, target in pairs:
            self.assertEqual((answer.status_code, answer["Location"]), (302, target))

    def test_without_the_switch_and_by_name_the_classic_pages_open(self):
        for name, args in (("dashboard:admin_users", None), ("dashboard:admin_user_new", None), ("dashboard:admin_user_edit", [self.tr.pk])):
            self.assertEqual(self.get(self.admin, name, args).status_code, 200, name)
        self.turn_on()
        for name, args in (("dashboard:admin_users", None), ("dashboard:admin_user_new", None), ("dashboard:admin_user_edit", [self.tr.pk])):
            self.assertEqual(self.get(self.admin, name, args, classic=1).status_code, 200, name)

    def test_a_person_that_does_not_exist_is_a_404_in_both_interfaces(self):
        self.turn_on()
        self.assertEqual(self.get(self.admin, "dashboard:admin_user_edit", [999999]).status_code, 404)

    def test_the_forms_already_open_are_answered_where_they_are(self):
        self.turn_on()
        browser = DjangoClient()
        browser.force_login(self.admin)
        answer = browser.post(reverse("dashboard:admin_user_edit", args=[self.tr.pk]), {"first_name": "Changed", "role": "translator"})
        self.assertNotEqual(answer.get("Location"), f"/app/admin/users/{self.tr.pk}")

    def test_the_classic_box_for_a_typed_shift_saves_the_row_it_was_given(self):
        """It used to save nothing and say nothing (the form wanted fields the box never sent): now it saves an active row."""
        browser = DjangoClient()
        browser.force_login(self.admin)
        answer = browser.post(reverse("dashboard:admin_shift_add", args=[self.tr.pk]), {"weekday": 0, "start_time": "09:00", "end_time": "17:00"})
        self.assertEqual(answer.status_code, 302)
        row = Shift.objects.get(user=self.tr)
        self.assertEqual((row.weekday, row.start_time, row.end_time, row.is_active, row.required_minutes, row.template_id), (0, time(9), time(17), True, 0, None))
        self.assertEqual(len(self.tr.active_shifts()), 1)

    def test_the_classic_box_says_so_when_the_row_is_not_a_row_and_saves_nothing(self):
        browser = DjangoClient()
        browser.force_login(self.admin)
        for body in (
            {"weekday": 0, "start_time": "", "end_time": "17:00"}, {"weekday": 0, "start_time": "09:00"}, {"weekday": 0},
            {"weekday": 0, "start_time": "09:00", "end_time": "09:00"}, {"weekday": 9, "start_time": "09:00", "end_time": "17:00"},
            {"start_time": "09:00", "end_time": "17:00"}, {"weekday": 0, "start_time": "99:99", "end_time": "17:00"},
        ):
            answer = browser.post(reverse("dashboard:admin_shift_add", args=[self.tr.pk]), body, follow=True)
            self.assertContains(answer, "اكتب اليوم ووقت البداية ووقت النهاية", msg_prefix=str(body))
        self.assertFalse(Shift.objects.filter(user=self.tr).exists())

    def test_the_classic_box_and_the_new_door_make_the_same_row(self):
        browser = DjangoClient()
        browser.force_login(self.admin)
        browser.post(reverse("dashboard:admin_shift_add", args=[self.tr.pk]), {"weekday": 2, "start_time": "17:00", "end_time": "01:00"})
        self.post(self.admin, SHIFT_ADD, {"weekday": 2, "start_time": "17:00", "end_time": "01:00"}, [self.ops.pk])
        fields = ("weekday", "start_time", "end_time", "is_active", "required_minutes", "work_mode", "template_id")
        self.assertEqual(
            list(Shift.objects.filter(user=self.tr).values_list(*fields)), list(Shift.objects.filter(user=self.ops).values_list(*fields)),
        )
