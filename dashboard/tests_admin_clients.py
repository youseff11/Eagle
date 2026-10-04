"""The admin panel's client records in the new app: the list, the identity form, deleting junk clients.

Only the admin is answered. This is where a client's whole identity is on a page, so opening it is written down (a list
is one row, a client's form is one row), a delete needs its explicit yes, and the blockers are worked out again at the yes.
"""

import json

from django.core.files.base import ContentFile
from django.db import connection
from django.test import Client as DjangoClient
from django.test.utils import CaptureQueriesContext
from django.urls import reverse

from . import identity, services
from .models import AuditLog, Channel, Client, InboundMessage, MessageAttachment, OutboundMessage, Task, TaskStatus
from .tests_admin_screen import _Admin
from .tests_api_v1 import CLIENT_EMAIL, CLIENT_NAME, CLIENT_PHONE, _json

LIST = "dashboard:v1_admin_clients"
NEW = "dashboard:v1_admin_client_new"
CREATE = "dashboard:v1_admin_client_create"
PLAN = "dashboard:v1_admin_clients_plan"
DELETE = "dashboard:v1_admin_clients_delete"
ONE = "dashboard:v1_admin_client"
SAVE = "dashboard:v1_admin_client_save"


class _Records(_Admin):
    def post(self, user, name, body, args=None):
        browser = DjangoClient()
        if user is not None:
            browser.force_login(user)
        return browser.post(reverse(name, args=args), json.dumps(body), content_type="application/json")

    def junk(self, address="no-reply@service.example"):
        """A client that is only a robot's address, with one letter."""
        row = Client.objects.create(email=address)
        InboundMessage.objects.create(client=row, channel=Channel.EMAIL, sender_identity=address, body="Automated notice")
        return row

    def plain(self, name="Plain Buyer", phone="+201112223334"):
        return Client.objects.create(name=name, phone=phone)


class DoorMatrixTests(_Records):
    def doors(self):
        code = self.client_obj.code
        return [
            ("GET", LIST, None), ("GET", NEW, None), ("GET", ONE, [code]), ("POST", CREATE, None),
            ("POST", SAVE, [code]), ("POST", PLAN, None), ("POST", DELETE, None),
        ]

    def call(self, user, method, name, args):
        browser = DjangoClient()
        if user is not None:
            browser.force_login(user)
        url = reverse(name, args=args)
        return browser.get(url) if method == "GET" else browser.post(url, "{}", content_type="application/json")

    def test_only_the_admin_is_answered(self):
        for method, name, args in self.doors():
            for user in (self.ops, self.lead, self.tr, self.hr, self.reviewer, self.accounting, self.sales):
                denied = self.call(user, method, name, args)
                self.assertEqual((denied.status_code, _json(denied)), (403, {"ok": False, "error": "forbidden"}), (name, user.username))
            self.assertEqual(self.call(None, method, name, args).status_code, 401, name)
            self.assertNotEqual(self.call(self.admin, method, name, args).status_code, 403, name)

    def test_a_refusal_never_shows_a_name_or_number(self):
        for method, name, args in self.doors():
            for user in (self.ops, self.sales, self.accounting):
                text = self.call(user, method, name, args).content.decode("utf-8")
                for marker in (CLIENT_NAME, CLIENT_PHONE, CLIENT_EMAIL):
                    self.assertNotIn(marker, text, (name, user.username))

    def test_the_wrong_method_is_a_405_that_says_what_is_allowed(self):
        for method, name, args in self.doors():
            other = "POST" if method == "GET" else "GET"
            answer = self.call(self.admin, other, name, args)
            self.assertEqual((answer.status_code, answer["Allow"]), (405, method), name)

    def test_every_answer_is_private(self):
        for method, name, args in self.doors():
            self.assertEqual(self.call(self.admin, method, name, args)["Cache-Control"], "private, no-store", name)


class ListTests(_Records):
    def test_a_client_is_a_row_with_the_real_details(self):
        row = next(one for one in _json(self.get(self.admin, LIST))["clients"] if one["id"] == self.client_obj.pk)
        self.assertEqual(
            row,
            {"id": self.client_obj.pk, "code": self.client_obj.code, "name": CLIENT_NAME, "company": "", "phone": CLIENT_PHONE,
             "more_phones": 0, "email": CLIENT_EMAIL, "more_emails": 0, "active": True},
        )

    def test_the_other_numbers_and_addresses_are_counted_not_listed(self):
        self.client_obj.extra_phones = "+201555000111\n+201555000222"
        self.client_obj.extra_emails = "second@acme-secret.example"
        self.client_obj.save()
        row = next(one for one in _json(self.get(self.admin, LIST))["clients"] if one["id"] == self.client_obj.pk)
        self.assertEqual((row["phone"], row["more_phones"], row["email"], row["more_emails"]), (CLIENT_PHONE, 2, CLIENT_EMAIL, 1))

    def test_a_search_matches_the_code_and_every_identity_field(self):
        other = self.plain()
        for query, expected in (
            (self.client_obj.code, {self.client_obj.pk}), ("ACME", {self.client_obj.pk}), ("1234567", {self.client_obj.pk}),
            ("acme-secret", {self.client_obj.pk}), ("Plain", {other.pk}), ("zzz-nothing", set()),
        ):
            rows = _json(self.get(self.admin, LIST, q=query))["clients"]
            self.assertEqual({row["id"] for row in rows}, expected, query)

    def test_the_robot_filter_lists_only_no_reply_clients(self):
        robot = self.junk()
        body = _json(self.get(self.admin, LIST, show="robots"))
        self.assertEqual([row["id"] for row in body["clients"]], [robot.pk])
        self.assertEqual((body["show"], body["robots_count"], body["all_count"]), ("robots", 1, 2))

    def test_the_numbers_agree_with_the_classic_page(self):
        self.junk()
        self.plain()
        classic = self.get(self.admin, "dashboard:admin_clients", classic=1, q="")
        body = _json(self.get(self.admin, LIST))
        self.assertEqual(
            (body["shown"], body["all_count"], body["robots_count"], [row["id"] for row in body["clients"]]),
            (classic.context["shown"], classic.context["all_count"], classic.context["robots_count"], [c.pk for c in classic.context["clients"]]),
        )

    def test_a_filter_that_is_not_one_is_a_400(self):
        for params in ({"show": "everything"}, {"q": "x" * 300}, {"q": "a\x00b"}):
            answer = self.get(self.admin, LIST, **params)
            self.assertEqual((answer.status_code, _json(answer)["error"]), (400, "bad_filter"), params)

    def test_at_most_three_hundred_are_listed_and_the_count_says_how_many_there_are(self):
        Client.objects.bulk_create([Client(code=f"X-{index:04d}", name=f"n{index}") for index in range(310)])
        body = _json(self.get(self.admin, LIST))
        self.assertEqual((len(body["clients"]), body["shown"]), (300, 311))

    def test_opening_the_list_is_written_down_once_with_the_codes_and_the_search(self):
        self.plain()
        before = AuditLog.objects.filter(action=identity.IDENTITY_LIST).count()
        self.get(self.admin, LIST, q="Plain")
        rows = AuditLog.objects.filter(action=identity.IDENTITY_LIST)
        self.assertEqual(rows.count(), before + 1)
        newest = rows.latest("pk")
        self.assertEqual((newest.actor_id, newest.detail), (self.admin.pk, "1 clients · q=Plain"))

    def test_an_empty_list_writes_nothing(self):
        before = AuditLog.objects.filter(action=identity.IDENTITY_LIST).count()
        self.get(self.admin, LIST, q="zzz-nothing")
        self.assertEqual(AuditLog.objects.filter(action=identity.IDENTITY_LIST).count(), before)

    def test_the_number_of_questions_does_not_grow_with_the_clients(self):
        def questions():
            with CaptureQueriesContext(connection) as seen:
                self.assertEqual(self.get(self.admin, LIST).status_code, 200)
            return len(seen)

        few = questions()
        for index in range(20):
            Client.objects.create(name=f"n{index}", phone=f"+2010099{index:05d}", extra_emails=f"a{index}@x.example")
        self.assertEqual(questions(), few)


class PlanTests(_Records):
    def test_a_client_with_a_task_is_blocked_and_one_without_is_deletable(self):
        free = self.plain()
        InboundMessage.objects.create(client=free, channel=Channel.EMAIL, sender_identity="a@x.example", body="Hello")
        body = _json(self.post(self.admin, PLAN, {"ids": [self.client_obj.pk, free.pk]}))
        self.assertEqual([row["code"] for row in body["deletable"]], [free.code])
        self.assertEqual([row["code"] for row in body["blocked"]], [self.client_obj.code])
        self.assertEqual(body["blocked"][0]["blocked"], "عليه تاسكات.")
        self.assertEqual((body["deletable"][0]["letters"], body["deletable"][0]["name"]), (1, "Plain Buyer"))

    def test_it_changes_nothing(self):
        free = self.plain()
        counts = (Client.objects.count(), InboundMessage.objects.count(), AuditLog.objects.filter(action="client.delete").count())
        self.post(self.admin, PLAN, {"ids": [free.pk]})
        self.assertEqual((Client.objects.count(), InboundMessage.objects.count(), AuditLog.objects.filter(action="client.delete").count()), counts)

    def test_it_counts_what_would_go_with_each_client(self):
        free = self.plain()
        letter = InboundMessage.objects.create(client=free, channel=Channel.EMAIL, sender_identity="a@x.example", body="Hello")
        MessageAttachment.objects.create(message=letter, file=ContentFile(b"x", name="a.pdf"), original_name="a.pdf", size=1)
        OutboundMessage.objects.create(client=free, channel=Channel.EMAIL, body="Reply", created_by=self.ops)
        row = _json(self.post(self.admin, PLAN, {"ids": [free.pk]}))["deletable"][0]
        self.assertEqual((row["letters"], row["files"], row["replies"]), (1, 1, 1))

    def test_a_body_that_is_not_the_shape_is_refused(self):
        for body in ({}, {"ids": []}, {"ids": "1"}, {"ids": [True]}, {"ids": ["1"]}, {"ids": [-1]}, {"ids": [2 ** 70]}, {"ids": list(range(1, 400))}, {"ids": [1.5]}):
            answer = self.post(self.admin, PLAN, body)
            self.assertEqual((answer.status_code, _json(answer)["error"]), (400, "bad_body"), body)

    def test_clients_that_do_not_exist_are_a_404_not_an_empty_plan(self):
        answer = self.post(self.admin, PLAN, {"ids": [999999]})
        self.assertEqual((answer.status_code, _json(answer)["error"]), (404, "no_clients"))

    def test_asking_for_it_is_written_down(self):
        free = self.plain()
        self.post(self.admin, PLAN, {"ids": [free.pk]})
        self.assertTrue(AuditLog.objects.filter(action=identity.IDENTITY_LIST, actor=self.admin, detail__contains="delete plan").exists())


class DeleteTests(_Records):
    """Deleting clients asks what the two clear-outs ask: the owner's own password, the explicit yes, and a backup comes back."""

    def delete(self, ids, **over):
        body = {"ids": ids, "confirm": True, "password": "pw"}
        body.update(over)
        return self.post(self.admin, DELETE, body)

    def test_without_the_explicit_yes_nothing_is_deleted(self):
        free = self.plain()
        for body in ({"ids": [free.pk]}, {"ids": [free.pk], "confirm": False}, {"ids": [free.pk], "confirm": "1"}, {"ids": [free.pk], "confirm": 1}, {"ids": [free.pk], "confirm": "true"}):
            answer = self.post(self.admin, DELETE, {**body, "password": "pw"})
            self.assertEqual((answer.status_code, _json(answer)["error"]), (400, "confirm_required"), body)
        self.assertTrue(Client.objects.filter(pk=free.pk).exists())

    def test_a_wrong_or_missing_password_deletes_nothing_and_is_written_down(self):
        free = self.plain()
        for password in ("not-the-password", ""):
            answer = self.delete([free.pk], password=password)
            self.assertEqual((answer.status_code, _json(answer)["error"]), (400, "refused"), password)
        self.assertEqual(self.post(self.admin, DELETE, {"ids": [free.pk], "confirm": True}).status_code, 400)
        self.assertTrue(Client.objects.filter(pk=free.pk).exists())
        self.assertEqual(AuditLog.objects.filter(action="client.reset_refused", actor=self.admin).count(), 3)

    def test_too_many_wrong_passwords_shut_it_even_to_the_right_one(self):
        free = self.plain()
        for _ in range(services.RESET_WRONG_LIMIT):
            self.delete([free.pk], password="wrong")
        answer = self.delete([free.pk])
        self.assertEqual((answer.status_code, _json(answer)["error"]), (429, "too_many_attempts"))
        self.assertTrue(Client.objects.filter(pk=free.pk).exists())

    def test_with_the_password_and_the_yes_the_client_goes_with_its_letters_files_and_replies_and_the_backup_comes_back(self):
        free = self.plain()
        letter = InboundMessage.objects.create(client=free, channel=Channel.EMAIL, sender_identity="a@x.example", body="Hello")
        MessageAttachment.objects.create(message=letter, file=ContentFile(b"x", name="gone.pdf"), original_name="gone.pdf", size=1)
        OutboundMessage.objects.create(client=free, channel=Channel.EMAIL, body="Reply", created_by=self.ops)
        answer = self.delete([free.pk])
        self.assertEqual(answer.status_code, 200)
        self.assertEqual((answer["X-Eagle-Deleted"], answer["X-Eagle-Blocked"], answer["X-Eagle-Files"]), ("1", "0", "1"))
        self.assertIn("eagle-clients-backup", answer["Content-Disposition"])
        self.assertIn("no-store", answer["Cache-Control"])
        rows = json.loads(answer.content)
        models = {row["model"] for row in rows}
        self.assertTrue({"dashboard.client", "dashboard.inboundmessage", "dashboard.messageattachment", "dashboard.outboundmessage"} <= models, models)
        self.assertEqual([row["pk"] for row in rows if row["model"] == "dashboard.client"], [free.pk])
        self.assertFalse(Client.objects.filter(pk=free.pk).exists())
        self.assertFalse(InboundMessage.objects.filter(pk=letter.pk).exists())
        self.assertFalse(OutboundMessage.objects.filter(client_id=free.pk).exists())
        self.assertTrue(AuditLog.objects.filter(action=identity.DATA_EXPORT, actor=self.admin).exists())

    def test_the_backup_holds_only_what_went(self):
        free = self.plain()
        answer = self.delete([self.client_obj.pk, free.pk])
        rows = json.loads(answer.content)
        self.assertEqual([row["pk"] for row in rows if row["model"] == "dashboard.client"], [free.pk])
        self.assertEqual((answer["X-Eagle-Deleted"], answer["X-Eagle-Blocked"]), ("1", "1"))
        self.assertTrue(Client.objects.filter(pk=self.client_obj.pk).exists())
        self.assertTrue(Task.objects.filter(pk=self.task.pk).exists())

    def test_when_nothing_can_go_it_is_a_409_with_the_reason_in_words(self):
        answer = self.delete([self.client_obj.pk])
        body = _json(answer)
        self.assertEqual((answer.status_code, body["error"], body["blocked"]), (409, "refused", [self.client_obj.code]))
        self.assertTrue(body["message"])
        self.assertTrue(Client.objects.filter(pk=self.client_obj.pk).exists())

    def test_a_task_made_since_the_plan_was_drawn_still_blocks(self):
        late = self.plain()
        self.post(self.admin, PLAN, {"ids": [late.pk]})
        Task.objects.create(client=late, title="Made after the plan", created_by=self.ops, status=TaskStatus.NEW)
        answer = self.delete([late.pk])
        self.assertEqual(answer.status_code, 409)
        self.assertTrue(Client.objects.filter(pk=late.pk).exists())

    def test_the_log_carries_codes_and_never_a_name_or_the_password(self):
        free = self.plain(name="Secret Buyer Name")
        self.delete([free.pk])
        row = AuditLog.objects.filter(action="client.delete").latest("pk")
        self.assertIn(free.code, row.detail)
        everything = json.dumps(list(AuditLog.objects.values()), default=str)
        self.assertNotIn("Secret Buyer Name", everything)
        self.assertNotIn('"pw"', everything)

    def test_ids_that_are_not_the_shape_delete_nothing(self):
        free = self.plain()
        for body in ({"confirm": True}, {"ids": [], "confirm": True}, {"ids": ["x"], "confirm": True}, {"ids": [free.pk, "x"], "confirm": True}):
            answer = self.post(self.admin, DELETE, {**body, "password": "pw"})
            self.assertEqual((answer.status_code, _json(answer)["error"]), (400, "bad_body"), body)
        self.assertTrue(Client.objects.filter(pk=free.pk).exists())

    def test_the_same_request_twice_is_a_refusal_the_second_time_and_not_a_crash(self):
        free = self.plain()
        self.assertEqual(self.delete([free.pk]).status_code, 200)
        self.assertEqual(self.delete([free.pk]).status_code, 409)

    def test_robots_can_be_cleared_the_way_the_page_says(self):
        robots = [self.junk(f"no-reply{index}@service.example") for index in range(3)]
        answer = self.delete([row.pk for row in robots])
        self.assertEqual(answer["X-Eagle-Deleted"], "3")
        self.assertEqual(_json(self.get(self.admin, LIST, show="robots"))["clients"], [])


class FormTests(_Records):
    def values(self, **over):
        body = {"name": "New Buyer", "company": "Buyer Co", "phone": "+201700000001", "email": "new@buyer.example", "is_active": True}
        body.update(over)
        return {"values": body}

    def test_the_form_is_the_classic_forms_fields_with_the_clients_values(self):
        body = _json(self.get(self.admin, ONE, [self.client_obj.code]))
        by_name = {field["name"]: field for field in body["form"]}
        self.assertEqual(body["code"], self.client_obj.code)
        self.assertEqual((by_name["name"]["value"], by_name["phone"]["value"], by_name["email"]["kind"]), (CLIENT_NAME, CLIENT_PHONE, "email"))
        self.assertEqual(by_name["admin_notes"]["kind"], "textarea")
        self.assertIs(by_name["is_active"]["value"], True)
        self.assertIn("رقم في كل سطر", by_name["extra_phones"]["help"])

    def test_opening_a_clients_form_is_written_down(self):
        before = AuditLog.objects.filter(action=identity.IDENTITY_VIEW).count()
        self.get(self.admin, ONE, [self.client_obj.code])
        row = AuditLog.objects.filter(action=identity.IDENTITY_VIEW).latest("pk")
        self.assertEqual((AuditLog.objects.filter(action=identity.IDENTITY_VIEW).count(), row.target, row.detail), (before + 1, self.client_obj.code, "admin_client_edit"))

    def test_a_client_that_does_not_exist_is_a_404_and_writes_no_identity_row(self):
        before = AuditLog.objects.filter(action=identity.IDENTITY_VIEW).count()
        self.assertEqual(self.get(self.admin, ONE, ["CL-9999"]).status_code, 404)
        self.assertEqual(AuditLog.objects.filter(action=identity.IDENTITY_VIEW).count(), before)

    def test_a_client_is_made_and_given_the_next_code(self):
        answer = self.post(self.admin, CREATE, self.values())
        self.assertEqual((answer.status_code, _json(answer)["ok"]), (200, True))
        row = Client.objects.get(name="New Buyer")
        self.assertEqual(_json(answer)["code"], row.code)
        self.assertEqual((row.company, row.phone, row.email), ("Buyer Co", "+201700000001", "new@buyer.example"))
        self.assertNotEqual(row.code, self.client_obj.code)

    def test_a_number_that_belongs_to_another_client_is_refused(self):
        answer = self.post(self.admin, CREATE, self.values(phone=CLIENT_PHONE))
        body = _json(answer)
        self.assertEqual((answer.status_code, body["error"]), (400, "invalid"))
        self.assertIn(self.client_obj.code, body["errors"]["phone"][0])
        self.assertFalse(Client.objects.filter(name="New Buyer").exists())

    def test_an_address_that_belongs_to_another_client_is_refused_but_a_clients_own_is_not(self):
        refused = self.post(self.admin, CREATE, self.values(email=CLIENT_EMAIL))
        self.assertEqual((refused.status_code, "email" in _json(refused)["errors"]), (400, True))
        kept = self.post(self.admin, SAVE, {"values": {"company": "Renamed Co"}}, [self.client_obj.code])
        self.assertEqual(kept.status_code, 200)
        self.client_obj.refresh_from_db()
        self.assertEqual((self.client_obj.company, self.client_obj.email, self.client_obj.phone), ("Renamed Co", CLIENT_EMAIL, CLIENT_PHONE))

    def test_extra_numbers_and_addresses_are_cleaned_and_the_main_one_is_dropped_from_them(self):
        answer = self.post(self.admin, CREATE, self.values(extra_phones="+201700000001\n+201700000002", extra_emails="new@buyer.example\nother@buyer.example"))
        self.assertEqual(answer.status_code, 200)
        row = Client.objects.get(name="New Buyer")
        self.assertEqual(row.extra_phones, "+201700000002")
        self.assertEqual(row.extra_emails, "other@buyer.example")

    def test_a_bad_extra_number_or_address_is_refused(self):
        bad_phone = self.post(self.admin, CREATE, self.values(extra_phones="12"))
        self.assertIn("extra_phones", _json(bad_phone)["errors"])
        bad_email = self.post(self.admin, CREATE, self.values(extra_emails="not-an-address"))
        self.assertIn("extra_emails", _json(bad_email)["errors"])

    def test_a_save_changes_only_what_was_sent(self):
        self.client_obj.admin_notes = "Pays late"
        self.client_obj.save()
        self.post(self.admin, SAVE, {"values": {"company": "Only This"}}, [self.client_obj.code])
        self.client_obj.refresh_from_db()
        self.assertEqual((self.client_obj.company, self.client_obj.admin_notes, self.client_obj.name, self.client_obj.is_active), ("Only This", "Pays late", CLIENT_NAME, True))

    def test_a_save_never_changes_the_code(self):
        code = self.client_obj.code
        self.post(self.admin, SAVE, {"values": {"name": "Another Name"}}, [code])
        self.client_obj.refresh_from_db()
        self.assertEqual(self.client_obj.code, code)

    def test_a_field_the_form_does_not_have_is_refused(self):
        for extra in ({"code": "CL-0099"}, {"id": 5}, {"created_at": "2020-01-01"}):
            answer = self.post(self.admin, SAVE, {"values": extra}, [self.client_obj.code])
            self.assertEqual((answer.status_code, _json(answer)["error"]), (400, "bad_body"), extra)

    def test_a_client_can_be_switched_off_and_on(self):
        self.post(self.admin, SAVE, {"values": {"is_active": False}}, [self.client_obj.code])
        self.client_obj.refresh_from_db()
        self.assertFalse(self.client_obj.is_active)

    def test_the_form_for_a_new_client_is_empty(self):
        body = _json(self.get(self.admin, NEW))
        self.assertEqual(body["code"], "")
        values = {field["name"]: field.get("value") for field in body["form"]}
        self.assertEqual((values["name"], values["phone"]), ("", ""))

    def test_a_created_client_is_written_down_by_code_only(self):
        self.post(self.admin, CREATE, self.values())
        row = AuditLog.objects.filter(action="client.create").latest("pk")
        self.assertEqual((row.actor_id, row.target, row.detail), (self.admin.pk, Client.objects.get(name="New Buyer").code, ""))
        self.assertNotIn("New Buyer", json.dumps(list(AuditLog.objects.values()), default=str))

    def test_a_saved_client_is_written_down_by_the_names_of_the_boxes_changed_and_never_the_values(self):
        self.post(self.admin, SAVE, {"values": {"company": "Renamed Co", "extra_phones": "+201555000333"}}, [self.client_obj.code])
        row = AuditLog.objects.filter(action="client.update").latest("pk")
        self.assertEqual((row.target, sorted(row.detail.split(", "))), (self.client_obj.code, ["company", "extra_phones"]))
        everything = json.dumps(list(AuditLog.objects.values()), default=str)
        for value in ("Renamed Co", "+201555000333"):
            self.assertNotIn(value, everything)

    def test_a_refused_save_writes_nothing(self):
        other = self.plain()
        before = AuditLog.objects.filter(action__in=("client.create", "client.update")).count()
        answer = self.post(self.admin, SAVE, {"values": {"phone": CLIENT_PHONE}}, [other.code])
        self.assertEqual(answer.status_code, 400)
        self.assertEqual(AuditLog.objects.filter(action__in=("client.create", "client.update")).count(), before)

    def test_a_refused_save_changes_nothing(self):
        other = self.plain()
        answer = self.post(self.admin, SAVE, {"values": {"name": "Changed", "phone": CLIENT_PHONE}}, [other.code])
        self.assertEqual(answer.status_code, 400)
        other.refresh_from_db()
        self.assertEqual(other.name, "Plain Buyer")


class HandOnTests(_Records):
    def test_the_pages_go_on_with_the_switch(self):
        self.turn_on()
        code = self.client_obj.code
        for answer, target in (
            (self.get(self.admin, "dashboard:admin_clients"), "/app/admin/clients"),
            (self.get(self.admin, "dashboard:admin_clients", show="robots", q="x y"), "/app/admin/clients?show=robots&q=x+y"),
            (self.get(self.admin, "dashboard:admin_client_new"), "/app/admin/clients/new"),
            (self.get(self.admin, "dashboard:admin_client_edit", [code]), f"/app/admin/clients/{code}/edit"),
        ):
            self.assertEqual((answer.status_code, answer["Location"]), (302, target))

    def test_a_filter_that_is_not_one_is_never_carried_into_the_address(self):
        self.turn_on()
        answer = self.get(self.admin, "dashboard:admin_clients", show="everything", q="a" * 500)
        self.assertEqual(answer["Location"], "/app/admin/clients")

    def test_without_the_switch_and_by_name_the_classic_pages_open(self):
        code = self.client_obj.code
        pages = (("dashboard:admin_clients", None), ("dashboard:admin_client_new", None), ("dashboard:admin_client_edit", [code]))
        for name, args in pages:
            self.assertEqual(self.get(self.admin, name, args).status_code, 200, name)
        self.turn_on()
        for name, args in pages:
            self.assertEqual(self.get(self.admin, name, args, classic=1).status_code, 200, name)

    def test_the_classic_delete_and_forms_already_open_are_answered_where_they_are(self):
        self.turn_on()
        free = self.plain()
        browser = DjangoClient()
        browser.force_login(self.admin)
        answer = browser.post(reverse("dashboard:admin_clients_delete"), {"clients": [free.pk]})
        self.assertEqual(answer.status_code, 200)
        self.assertTrue(Client.objects.filter(pk=free.pk).exists())
        saved = browser.post(reverse("dashboard:admin_client_edit", args=[free.code]), {"name": "By Classic", "phone": free.phone, "is_active": "on"})
        self.assertEqual(saved.status_code, 302)
        self.assertNotIn("/app/", saved["Location"])
