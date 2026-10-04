"""The client pages in the new app: the list of codes, one client, and a requirement added to one.

The doors answer to the operation and the admin, and show what the classic pages show them: the code for everybody,
the name, the company, the numbers and the addresses only for whoever may know the client. What a search may match
is part of that, and so is what is written to the audit log when the identity is opened.
"""

import json
from datetime import timedelta
from unittest import mock

from django.db import connection
from django.test import Client as DjangoClient
from django.test.utils import CaptureQueriesContext
from django.urls import reverse
from django.utils import timezone

from . import identity, services
from .models import AuditLog, Client, ClientRequirement, Role, Task, TaskStatus
from .tests_api_v1 import CLIENT_EMAIL, CLIENT_NAME, CLIENT_PHONE, IDENTITY_MARKERS, _json, _Site

LIST = "dashboard:v1_clients"
ONE = "dashboard:v1_client"
ADD = "dashboard:v1_client_requirement"


class _Clients(_Site):
    def get(self, user, name, args=None, /, **query):
        browser = DjangoClient()
        if user is not None:
            browser.force_login(user)
        return browser.get(reverse(name), query) if args is None else browser.get(reverse(name, args=args), query)

    def post(self, user, name, args, body):
        browser = DjangoClient()
        if user is not None:
            browser.force_login(user)
        return browser.post(reverse(name, args=args), json.dumps(body), content_type="application/json")

    def second_client(self, **fields):
        return Client.objects.create(**{"name": "Other Corp", "phone": "+201119998888", "email": "x@other.example", **fields})

    def refused_for_everybody_else(self, name, args=None):
        # The Sales and the team leaders read these pages too (the sections below pin what they are given); nobody else but the operation and the admin.
        for user in (self.tr, self.hr, self.reviewer, self.accounting):
            answer = self.get(user, name, args)
            self.assertEqual((answer.status_code, _json(answer)), (403, {"ok": False, "error": "forbidden"}), user.username)
        self.assertEqual(self.get(None, name, args).status_code, 401)


class ClientListTests(_Clients):
    def test_the_operation_and_the_admin_are_answered_everybody_else_is_refused(self):
        for user in (self.ops, self.admin):
            answer = self.get(user, LIST)
            self.assertEqual(answer.status_code, 200, user.username)
            self.assertEqual(answer["Cache-Control"], "private, no-store")
        self.refused_for_everybody_else(LIST)
        browser = DjangoClient()
        browser.force_login(self.ops)
        self.assertEqual(browser.post(reverse(LIST)).status_code, 405)

    def test_the_accounting_person_who_may_know_the_clients_is_still_not_answered(self):
        # The flag opens the identity on the classic pages; the new app's doors are the operation's.
        self.accounting.client_identity_access = True
        self.accounting.save()
        self.assertEqual(self.get(self.accounting, LIST).status_code, 403)

    def test_the_operation_gets_codes_and_counts_and_nothing_that_names_a_client(self):
        answer = self.get(self.ops, LIST)
        body = _json(answer)
        self.assertFalse(body["sees_identity"])
        self.assertEqual([row["code"] for row in body["clients"]], [self.client_obj.code])
        self.assertEqual(set(body["clients"][0]), {"code", "tasks", "requirements"})
        for marker in IDENTITY_MARKERS:
            self.assertNotIn(marker, answer.content.decode("utf-8"), marker)

    def test_the_admin_gets_the_name_the_company_and_the_phone(self):
        self.client_obj.company = "ACME Holdings"
        self.client_obj.save()
        body = _json(self.get(self.admin, LIST))
        self.assertTrue(body["sees_identity"])
        row = body["clients"][0]
        self.assertEqual((row["name"], row["company"], row["phone"]), (CLIENT_NAME, "ACME Holdings", CLIENT_PHONE))

    def test_the_counts_are_the_clients_own_tasks_and_requirements_and_not_their_product(self):
        for index in range(3):
            ClientRequirement.objects.create(client=self.client_obj, kind="rule", text=f"Rule {index}", author=self.ops)
        for index in range(2):
            Task.objects.create(client=self.client_obj, title=f"More {index}", created_by=self.ops)
        body = _json(self.get(self.ops, LIST))
        row = next(one for one in body["clients"] if one["code"] == self.client_obj.code)
        # The task of the fixture, and the two just made: three. Three requirements, not nine.
        self.assertEqual((row["tasks"], row["requirements"]), (3, 3))

    def test_the_operation_finds_a_client_by_code_and_not_by_name(self):
        other = self.second_client()
        found = _json(self.get(self.ops, LIST, q=other.code))
        self.assertEqual([row["code"] for row in found["clients"]], [other.code])
        # A name typed in the search would hand the name over by answering with the code: it matches nothing.
        for text in (CLIENT_NAME, "ACME", CLIENT_PHONE, CLIENT_EMAIL, "acme-secret"):
            self.assertEqual(_json(self.get(self.ops, LIST, q=text))["clients"], [], text)

    def test_the_admin_finds_a_client_by_what_they_may_know(self):
        other = self.second_client()
        for text, code in ((CLIENT_NAME, self.client_obj.code), ("Other", other.code), (CLIENT_PHONE, self.client_obj.code),
                           ("x@other", other.code), (other.code, other.code)):
            found = _json(self.get(self.admin, LIST, q=text))
            self.assertEqual([row["code"] for row in found["clients"]], [code], text)

    def test_a_search_that_is_not_a_search_is_refused(self):
        for text in ("x" * 201, "a\x00b"):
            answer = self.get(self.ops, LIST, q=text)
            self.assertEqual((answer.status_code, _json(answer)), (400, {"ok": False, "error": "bad_filter"}), repr(text))

    def test_opening_the_identity_in_a_list_is_written_to_the_audit_log_and_a_list_of_codes_is_not(self):
        self.get(self.ops, LIST)
        self.assertFalse(AuditLog.objects.filter(action=identity.IDENTITY_LIST).exists())
        self.get(self.admin, LIST, q="Acme")
        row = AuditLog.objects.get(action=identity.IDENTITY_LIST)
        self.assertEqual(row.actor, self.admin)
        self.assertIn(self.client_obj.code, row.target)
        self.assertIn("q=Acme", row.detail)

    def test_the_list_is_the_newest_two_hundred_and_costs_the_same_however_many(self):
        Client.objects.bulk_create([Client(code=f"BULK-{index:04d}") for index in range(205)])
        body = _json(self.get(self.ops, LIST))
        self.assertEqual(len(body["clients"]), 200)

        def cost():
            with CaptureQueriesContext(connection) as queries:
                self.get(self.ops, LIST)
            return len(queries)

        few = cost()
        Client.objects.bulk_create([Client(code=f"MORE-{index:04d}") for index in range(50)])
        self.assertEqual(cost(), few)

    def test_the_classic_list_still_answers_the_same_people_the_same_way(self):
        browser = DjangoClient()
        browser.force_login(self.ops)
        answer = browser.get(reverse("dashboard:client_list") + "?classic=1")
        self.assertEqual(answer.status_code, 200)
        self.assertNotIn(CLIENT_NAME, answer.content.decode("utf-8"))


class ClientDoorTests(_Clients):
    def test_the_operation_and_the_admin_are_answered_everybody_else_is_refused(self):
        code = self.client_obj.code
        for user in (self.ops, self.admin):
            self.assertEqual(self.get(user, ONE, [code]).status_code, 200, user.username)
        self.refused_for_everybody_else(ONE, [code])

    def test_a_client_that_is_not_there_is_a_404(self):
        self.assertEqual(self.get(self.ops, ONE, ["CL-99999"]).status_code, 404)

    def test_the_operation_reads_the_code_and_nothing_that_names_the_client(self):
        answer = self.get(self.ops, ONE, [self.client_obj.code])
        body = _json(answer)
        self.assertEqual(body["client"], {"code": self.client_obj.code})
        self.assertFalse(body["sees_identity"])
        self.assertIsNone(body["activity"])
        for marker in IDENTITY_MARKERS:
            self.assertNotIn(marker, answer.content.decode("utf-8"), marker)

    def test_the_admin_reads_who_the_client_is_and_what_the_admin_wrote_about_them(self):
        self.client_obj.company = "ACME Holdings"
        self.client_obj.extra_phones = "+201005550000"
        self.client_obj.extra_emails = "second@acme-secret.example"
        self.client_obj.admin_notes = "Pays late"
        self.client_obj.save()
        body = _json(self.get(self.admin, ONE, [self.client_obj.code]))
        client = body["client"]
        self.assertEqual((client["name"], client["company"]), (CLIENT_NAME, "ACME Holdings"))
        self.assertEqual(client["phones"][0], CLIENT_PHONE)
        self.assertEqual(len(client["phones"]), 2)
        self.assertEqual(client["emails"][0], CLIENT_EMAIL)
        self.assertEqual(len(client["emails"]), 2)
        self.assertEqual(client["admin_notes"], "Pays late")
        self.assertTrue(body["sees_identity"])

    def test_the_admins_view_of_the_identity_is_written_to_the_audit_log_and_the_operations_is_not(self):
        self.get(self.ops, ONE, [self.client_obj.code])
        self.assertFalse(AuditLog.objects.filter(action=identity.IDENTITY_VIEW).exists())
        self.get(self.admin, ONE, [self.client_obj.code])
        row = AuditLog.objects.get(action=identity.IDENTITY_VIEW)
        self.assertEqual((row.actor, row.target), (self.admin, self.client_obj.code))

    def test_the_admin_sees_the_follow_up_numbers(self):
        Task.objects.create(client=self.client_obj, title="Done", created_by=self.ops, status=TaskStatus.DELIVERED)
        activity = _json(self.get(self.admin, ONE, [self.client_obj.code]))["activity"]
        self.assertEqual((activity["total"], activity["delivered"]), (2, 1))
        self.assertGreaterEqual(activity["active"], 1)
        self.assertIn("en", activity["last"])

    def test_the_requirements_come_newest_first_with_who_wrote_them_and_when(self):
        ClientRequirement.objects.create(client=self.client_obj, kind="like", text="Likes tables", author=self.lead)
        ClientRequirement.objects.create(client=self.client_obj, kind="dislike", text="No abbreviations", author=self.ops)
        rows = _json(self.get(self.ops, ONE, [self.client_obj.code]))["requirements"]
        self.assertEqual([(row["kind"]["value"], row["text"], row["author"]) for row in rows],
                         [("dislike", "No abbreviations", self.ops.short_name), ("like", "Likes tables", self.lead.short_name)])
        self.assertTrue(rows[0]["at"]["en"])
        self.assertEqual(set(rows[0]["kind"]), {"value", "ar", "en"})

    def test_the_words_of_a_requirement_name_the_client_only_to_whoever_may_know_the_client(self):
        ClientRequirement.objects.create(
            client=self.client_obj, kind="rule", text=f"Send to {CLIENT_NAME} at {CLIENT_EMAIL} or {CLIENT_PHONE}", author=self.admin,
        )
        mine = self.get(self.ops, ONE, [self.client_obj.code])
        for marker in IDENTITY_MARKERS:
            self.assertNotIn(marker, mine.content.decode("utf-8"), marker)
        self.assertIn(self.client_obj.code, _json(mine)["requirements"][0]["text"])
        theirs = _json(self.get(self.admin, ONE, [self.client_obj.code]))["requirements"][0]["text"]
        self.assertIn(CLIENT_NAME, theirs)

    def test_the_tasks_are_the_newest_thirty_with_where_they_came_from_and_how_they_stand(self):
        for index in range(35):
            Task.objects.create(client=self.client_obj, title=f"Extra {index}", created_by=self.ops)
        body = _json(self.get(self.ops, ONE, [self.client_obj.code]))
        self.assertEqual(len(body["tasks"]), 30)
        row = body["tasks"][0]
        self.assertEqual(set(row), {"code", "title", "origin", "status"})
        self.assertEqual(set(row["status"]), {"value", "tone", "ar", "en"})

    def test_the_page_costs_the_same_however_many_requirements_and_tasks(self):
        def cost():
            with CaptureQueriesContext(connection) as queries:
                self.get(self.ops, ONE, [self.client_obj.code])
            return len(queries)

        ClientRequirement.objects.create(client=self.client_obj, kind="rule", text="First", author=self.lead)
        few = cost()
        for index in range(12):
            ClientRequirement.objects.create(client=self.client_obj, kind="rule", text=f"Rule {index}", author=self.lead)
            Task.objects.create(client=self.client_obj, title=f"Extra {index}", created_by=self.ops)
        self.assertEqual(cost(), few)

    def test_a_get_changes_nothing(self):
        before = (ClientRequirement.objects.count(), Task.objects.count(), Client.objects.count())
        self.get(self.ops, ONE, [self.client_obj.code])
        self.assertEqual(before, (ClientRequirement.objects.count(), Task.objects.count(), Client.objects.count()))
        browser = DjangoClient()
        browser.force_login(self.ops)
        self.assertEqual(browser.delete(reverse(ONE, args=[self.client_obj.code])).status_code, 405)

    def test_the_link_to_the_classic_edit_form_is_the_admins_alone(self):
        code = self.client_obj.code
        self.assertEqual(_json(self.get(self.admin, ONE, [code]))["edit_url"], reverse("dashboard:admin_client_edit", args=[code]))
        self.assertNotIn("edit_url", _json(self.get(self.ops, ONE, [code])))

    def test_the_operation_may_edit_and_the_page_says_so(self):
        self.assertTrue(_json(self.get(self.ops, ONE, [self.client_obj.code]))["may_edit"])


class ClientRequirementDoorTests(_Clients):
    def test_the_operation_and_the_admin_add_one_and_everybody_else_is_refused(self):
        code = self.client_obj.code
        for user in (self.ops, self.admin):
            answer = self.post(user, ADD, [code], {"kind": "rule", "text": f"By {user.username}"})
            self.assertEqual(answer.status_code, 200, user.username)
        for user in (self.tr, self.hr, self.reviewer, self.accounting, self.sales):
            self.assertEqual(self.post(user, ADD, [code], {"kind": "rule", "text": "No"}).status_code, 403, user.username)
        self.assertEqual(self.post(None, ADD, [code], {"kind": "rule", "text": "No"}).status_code, 401)
        self.assertEqual(ClientRequirement.objects.count(), 2)

    def test_it_is_saved_with_its_author_and_comes_back_as_the_row(self):
        answer = self.post(self.ops, ADD, [self.client_obj.code], {"kind": "dislike", "text": "  No contractions "})
        body = _json(answer)
        self.assertEqual((answer.status_code, body["ok"]), (200, True))
        row = ClientRequirement.objects.get()
        self.assertEqual((row.client_id, row.author_id, row.kind, row.text), (self.client_obj.pk, self.ops.pk, "dislike", "No contractions"))
        self.assertEqual((body["requirement"]["id"], body["requirement"]["text"], body["requirement"]["author"]),
                         (row.pk, "No contractions", self.ops.short_name))
        self.assertTrue(body["requirement"]["at"]["en"])

    def test_it_is_written_to_the_audit_log(self):
        self.post(self.ops, ADD, [self.client_obj.code], {"kind": "rule", "text": "Formal tone"})
        self.assertTrue(AuditLog.objects.filter(action="client.requirement", target=self.client_obj.code, actor=self.ops).exists())

    def test_the_answer_does_not_name_the_client_to_the_operation(self):
        answer = self.post(self.ops, ADD, [self.client_obj.code], {"kind": "rule", "text": f"Always cc {CLIENT_NAME}"})
        for marker in IDENTITY_MARKERS:
            self.assertNotIn(marker, answer.content.decode("utf-8"), marker)
        # What is stored is what was typed: the admin reads it as it was written.
        self.assertIn(CLIENT_NAME, ClientRequirement.objects.get().text)

    def test_a_requirement_that_is_not_one_is_refused_and_nothing_is_written(self):
        code = self.client_obj.code
        for body in ({"kind": "rule", "text": ""}, {"kind": "rule", "text": "   "}, {"kind": "love", "text": "x"}, {"kind": "", "text": "x"}):
            answer = self.post(self.ops, ADD, [code], body)
            self.assertEqual(answer.status_code, 400, body)
            self.assertEqual(_json(answer)["error"], "bad_requirement", body)
        for body in ({"kind": "rule"}, {"text": "x"}, {"kind": 1, "text": "x"}, {"kind": "rule", "text": "x" * 2001}, {"kind": "rule", "text": ["x"]}):
            self.assertEqual(self.post(self.ops, ADD, [code], body).status_code, 400, body)
        self.assertEqual(ClientRequirement.objects.count(), 0)

    def test_it_takes_only_a_json_object(self):
        browser = DjangoClient()
        browser.force_login(self.ops)
        url = reverse(ADD, args=[self.client_obj.code])
        for kwargs in (
            {"data": "kind=rule&text=x", "content_type": "application/x-www-form-urlencoded"},
            {"data": "[1]", "content_type": "application/json"},
            {"data": "{", "content_type": "application/json"},
        ):
            self.assertEqual(browser.post(url, **kwargs).status_code, 400, kwargs["data"])
        self.assertEqual(browser.get(url).status_code, 405)
        self.assertEqual(ClientRequirement.objects.count(), 0)

    def test_a_client_that_is_not_there_is_a_404(self):
        self.assertEqual(self.post(self.ops, ADD, ["CL-99999"], {"kind": "rule", "text": "x"}).status_code, 404)

    def test_somebody_who_may_read_but_not_write_is_refused_where_the_classic_page_refuses(self):
        # The doors are the operation's today; the rule is kept in one place for the day they open to more.
        with mock.patch("dashboard.api_clients._may_edit", return_value=False):
            answer = self.post(self.ops, ADD, [self.client_obj.code], {"kind": "rule", "text": "x"})
        self.assertEqual((answer.status_code, _json(answer)), (403, {"ok": False, "error": "forbidden"}))
        self.assertEqual(ClientRequirement.objects.count(), 0)

    def test_the_task_page_door_masks_a_requirement_the_same_way(self):
        ClientRequirement.objects.create(client=self.client_obj, kind="rule", text=f"Ask {CLIENT_NAME}", author=self.admin)
        answer = self.get(self.ops, "dashboard:v1_task", [self.task.code])
        for marker in IDENTITY_MARKERS:
            self.assertNotIn(marker, answer.content.decode("utf-8"), marker)
        self.assertIn(self.client_obj.code, _json(answer)["task"]["requirements"][0]["text"])


class ClientsHandOnTests(_Clients):
    """The classic pages go on to the new app with the operation's switch (the admin is on by default)."""

    def setUp(self):
        super().setUp()
        built = mock.patch("dashboard.newui.spa.built_assets", return_value={"js": "x.js", "css": []})
        built.start()
        self.addCleanup(built.stop)

    def turn_on(self, roles=(), users=()):
        from .models import AppSettings

        conf = AppSettings.load()
        conf.new_ui = {**(conf.new_ui or {}), "operation": {"roles": list(roles), "users": list(users)}}
        conf.save()

    def page(self, user, name, args=None, /, **query):
        browser = DjangoClient()
        browser.force_login(user)
        return browser.get(reverse(name, args=args), query)

    def test_the_list_and_a_client_go_on_with_the_search(self):
        self.turn_on(roles=["operation"])
        answer = self.page(self.ops, "dashboard:client_list")
        self.assertEqual((answer.status_code, answer["Location"]), (302, "/app/clients"))
        self.assertEqual(self.page(self.ops, "dashboard:client_list", q="CL 1")["Location"], "/app/clients?q=CL+1")
        answer = self.page(self.ops, "dashboard:client_detail", [self.client_obj.code])
        self.assertEqual((answer.status_code, answer["Location"]), (302, f"/app/clients/{self.client_obj.code}"))

    def test_a_search_that_is_too_long_stays_behind(self):
        self.turn_on(roles=["operation"])
        self.assertEqual(self.page(self.ops, "dashboard:client_list", q="x" * 201)["Location"], "/app/clients")

    def test_the_admin_is_on_by_default(self):
        self.assertEqual(self.page(self.admin, "dashboard:client_list")["Location"], "/app/clients")

    def test_a_form_that_is_already_open_is_answered_where_it_is(self):
        self.turn_on(roles=["operation"])
        browser = DjangoClient()
        browser.force_login(self.ops)
        answer = browser.post(reverse("dashboard:client_detail", args=[self.client_obj.code]), {"kind": "rule", "text": "Posted classic"})
        self.assertEqual(answer.status_code, 302)
        self.assertFalse(answer["Location"].startswith("/app/"))
        self.assertTrue(ClientRequirement.objects.filter(text="Posted classic").exists())

    def test_a_client_that_is_not_there_is_still_a_404(self):
        self.turn_on(roles=["operation"])
        self.assertEqual(self.page(self.ops, "dashboard:client_detail", ["CL-99999"]).status_code, 404)

    def test_a_code_with_odd_characters_is_never_carried_into_the_address(self):
        self.turn_on(roles=["operation"])
        odd = Client.objects.create(code="we.ird", name="Odd")
        answer = self.page(self.ops, "dashboard:client_detail", [odd.code])
        self.assertEqual(answer.status_code, 200)
