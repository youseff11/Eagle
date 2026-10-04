"""The Sales screen in the new app: the person's own line, and the mail and client pages they read there.

A Sales person works their own line (``lines.py``): their number and their address, their conversations, the client
codes. The new app gives them the same pages the operation has (the mail, the client codes), by their own switch, and
one of their own (``/app/line``). What is pinned here: the doors answer each person what is theirs (the line rule is
``tests_mail_screen``), a Sales person may know who a client is and writes nothing about one, the admin is not switched on
for a screen that is not theirs, and nobody is handed on to a page that is another role's.
"""

import json
from unittest import mock

from django.test import Client as DjangoClient
from django.urls import reverse

from . import identity, newui
from .models import AppSettings, AuditLog, Client, ClientRequirement, Role, Task, TaskStatus, User
from .tests_api_v1 import CLIENT_EMAIL, CLIENT_NAME, CLIENT_PHONE, _json, _Site

LINE = "dashboard:v1_sales_line"
SAVE = "dashboard:v1_sales_line_save"


class _Sales(_Site):
    def setUp(self):
        super().setUp()
        built = mock.patch("dashboard.spa.built_assets", return_value={"js": "x.js", "css": []})
        built.start()
        self.addCleanup(built.stop)
        self.other_sales = User.objects.create_user(
            "person_salesman_two", password="pw", role=Role.SALES, wa_phone_number_id="555000111", wa_display_number="+20 100 555 0001",
        )

    def get(self, user, name, args=None, /, **query):
        browser = DjangoClient()
        if user is not None:
            browser.force_login(user)
        return browser.get(reverse(name, args=args), query)

    def post(self, user, name, body, args=None, raw=None, content_type="application/json"):
        browser = DjangoClient()
        if user is not None:
            browser.force_login(user)
        return browser.post(reverse(name, args=args), raw if raw is not None else json.dumps(body), content_type=content_type)

    def turn_on(self, key="sales", roles=(), users=()):
        conf = AppSettings.load()
        conf.save()


class ScreenSwitchTests(_Sales):
    def test_the_menu_of_the_new_app_lists_it_only_for_who_is_switched_on(self):
        self.turn_on(roles=["sales"])
        self.assertIn("sales", _json(self.get(self.sales, "dashboard:v1_me"))["screens"])
        self.assertNotIn("sales", _json(self.get(self.ops, "dashboard:v1_me"))["screens"])
        self.assertNotIn("sales", _json(self.get(self.admin, "dashboard:v1_me"))["screens"])

class LineDoorTests(_Sales):
    def test_the_sales_person_reads_their_own_line_and_nothing_of_anybody_elses(self):
        self.sales.wa_phone_number_id = "123456"
        self.sales.wa_display_number = "+20 100 000 0000"
        self.sales.mail_alias = "sales1@company.example"
        self.sales.save()
        answer = self.get(self.sales, LINE)
        body = _json(answer)
        self.assertEqual(answer["Cache-Control"], "private, no-store")
        self.assertTrue(body["ok"] and body["is_owner"])
        self.assertEqual(body["values"], {"wa_phone_number_id": "123456", "wa_display_number": "+20 100 000 0000", "mail_alias": "sales1@company.example"})
        text = answer.content.decode("utf-8")
        for other in ("555000111", "555 0001", "person_salesman_two"):
            self.assertNotIn(other, text)

    def test_the_company_mailbox_is_told_where_the_address_has_to_deliver(self):
        conf = AppSettings.load()
        conf.imap_user = "inbox@company.example"
        conf.save()
        self.assertEqual(_json(self.get(self.sales, LINE))["company_mail"], "inbox@company.example")

    def test_the_admin_may_read_what_it_asks_for_and_is_not_its_owner(self):
        body = _json(self.get(self.admin, LINE))
        self.assertFalse(body["is_owner"])
        self.assertEqual(body["values"]["wa_phone_number_id"], "")

    def test_nobody_else_has_it(self):
        for user in (self.ops, self.lead, self.tr, self.hr, self.reviewer, self.accounting):
            answer = self.get(user, LINE)
            self.assertEqual((answer.status_code, _json(answer)), (403, {"ok": False, "error": "forbidden"}), user.username)
        self.assertEqual(self.get(None, LINE).status_code, 401)
        browser = DjangoClient()
        browser.force_login(self.sales)
        self.assertEqual(browser.post(reverse(LINE)).status_code, 405)


class LineSaveTests(_Sales):
    def test_a_number_is_saved_trimmed_and_comes_back(self):
        answer = self.post(self.sales, SAVE, {"wa_phone_number_id": "  987654321 ", "wa_display_number": " +20 100 123 4567 "})
        body = _json(answer)
        self.assertEqual(answer.status_code, 200)
        self.assertEqual((body["values"]["wa_phone_number_id"], body["values"]["wa_display_number"]), ("987654321", "+20 100 123 4567"))
        self.sales.refresh_from_db()
        self.assertEqual((self.sales.wa_phone_number_id, self.sales.wa_display_number), ("987654321", "+20 100 123 4567"))

    def test_it_is_written_to_the_audit_log(self):
        self.post(self.sales, SAVE, {"wa_phone_number_id": "987654321", "wa_display_number": ""})
        row = AuditLog.objects.get(action="sales.line")
        self.assertEqual((row.actor, row.target), (self.sales, self.sales.username))
        self.assertIn("987654321", row.detail)

    def test_empty_means_no_line_of_my_own(self):
        self.sales.wa_phone_number_id = "123456"
        self.sales.save()
        self.assertEqual(self.post(self.sales, SAVE, {"wa_phone_number_id": "", "wa_display_number": ""}).status_code, 200)
        self.sales.refresh_from_db()
        self.assertEqual(self.sales.wa_phone_number_id, "")

    def test_a_number_that_is_not_digits_is_refused_in_the_boxs_name_and_nothing_changes(self):
        self.sales.wa_phone_number_id = "123456"
        self.sales.save()
        answer = self.post(self.sales, SAVE, {"wa_phone_number_id": "12ab", "wa_display_number": "+20 1"})
        self.assertEqual(answer.status_code, 400)
        body = _json(answer)
        self.assertEqual((body["ok"], body["error"], list(body["fields"])), (False, "invalid", ["wa_phone_number_id"]))
        self.assertIn("أرقام بس", body["fields"]["wa_phone_number_id"])
        self.sales.refresh_from_db()
        self.assertEqual((self.sales.wa_phone_number_id, self.sales.wa_display_number), ("123456", ""))
        self.assertFalse(AuditLog.objects.filter(action="sales.line").exists())

    def test_the_companys_own_number_is_refused(self):
        conf = AppSettings.load()
        conf.whatsapp_phone_number_id = "111222333"
        conf.recruit_phone_number_id = "444555666"
        conf.save()
        for number in ("111222333", "444555666"):
            answer = self.post(self.sales, SAVE, {"wa_phone_number_id": number, "wa_display_number": ""})
            self.assertEqual(answer.status_code, 400, number)
            self.assertIn("رقم الشركة", _json(answer)["fields"]["wa_phone_number_id"])
        self.sales.refresh_from_db()
        self.assertEqual(self.sales.wa_phone_number_id, "")

    def test_a_number_that_is_somebody_elses_is_refused_without_saying_whose(self):
        answer = self.post(self.sales, SAVE, {"wa_phone_number_id": "555000111", "wa_display_number": ""})
        self.assertEqual(answer.status_code, 400)
        self.assertIn("متسجّل لحد تاني", _json(answer)["fields"]["wa_phone_number_id"])
        text = answer.content.decode("utf-8")
        self.assertNotIn("person_salesman_two", text)
        self.assertNotIn(self.other_sales.short_name, text)

    def test_the_same_number_again_is_not_a_clash_with_oneself(self):
        self.post(self.sales, SAVE, {"wa_phone_number_id": "777888999", "wa_display_number": ""})
        self.assertEqual(self.post(self.sales, SAVE, {"wa_phone_number_id": "777888999", "wa_display_number": "+20 1"}).status_code, 200)

    def test_it_is_a_sales_persons_to_save_and_nobody_elses(self):
        for user in (self.admin, self.ops, self.lead, self.tr, self.hr, self.reviewer, self.accounting):
            answer = self.post(user, SAVE, {"wa_phone_number_id": "424242", "wa_display_number": ""})
            self.assertEqual((answer.status_code, _json(answer)["error"]), (403, "forbidden"), user.username)
        self.assertEqual(self.post(None, SAVE, {"wa_phone_number_id": "424242"}).status_code, 401)
        self.assertFalse(User.objects.filter(wa_phone_number_id="424242").exists())

    def test_the_door_takes_only_a_json_object_of_the_right_size(self):
        for kwargs in (
            {"raw": "wa_phone_number_id=1", "content_type": "application/x-www-form-urlencoded"},
            {"raw": "[1]"},
            {"raw": "{"},
            {"body": {"wa_phone_number_id": 5}},
            {"body": {"wa_phone_number_id": "1" * 41}},
            {"body": {"wa_phone_number_id": "1", "wa_display_number": "x" * 31}},
            {"body": {"wa_phone_number_id": ["1"]}},
            {"body": {"wa_phone_number_id": "1\x00"}},
        ):
            answer = self.post(self.sales, SAVE, kwargs.get("body"), raw=kwargs.get("raw"), content_type=kwargs.get("content_type", "application/json"))
            self.assertEqual((answer.status_code, _json(answer)["error"]), (400, "bad_request"), kwargs)
        self.sales.refresh_from_db()
        self.assertEqual(self.sales.wa_phone_number_id, "")

class HandOnTests(_Sales):
    def test_the_classic_pages_go_on_for_a_sales_person_with_the_switch_and_keep_their_filters(self):
        self.turn_on(roles=["sales"])
        code = self.client_obj.code
        expected = (
            (("dashboard:sales_line", None, {}), "/app/line"),
            (("dashboard:ops_inbox", None, {}), "/app/inbox"),
            (("dashboard:ops_inbox", None, {"state": "mine", "q": "lease"}), "/app/inbox?state=mine&q=lease"),
            (("dashboard:client_list", None, {}), "/app/clients"),
            (("dashboard:client_list", None, {"q": "CL"}), "/app/clients?q=CL"),
            (("dashboard:client_detail", [code], {}), f"/app/clients/{code}"),
        )
        for (name, args, query), target in expected:
            answer = self.get(self.sales, name, args, **query)
            self.assertEqual((answer.status_code, answer["Location"]), (302, target), name)

    def test_a_conversation_goes_on_by_its_id(self):
        from .models import Channel, InboundMessage

        self.turn_on(roles=["sales"])
        mine = InboundMessage.objects.create(
            client=self.client_obj, channel=Channel.EMAIL, subject="s", body="b", sender_identity=CLIENT_EMAIL,
            thread_key="k-sales", external_id="<sales1@mail.test>", owner=self.sales,
        )
        answer = self.get(self.sales, "dashboard:ops_mail_thread", [mine.pk], state="mine")
        self.assertEqual(answer["Location"], f"/app/inbox/thread/{mine.pk}?state=mine")

class ClientDoorsForSalesTests(_Sales):
    def test_a_sales_person_may_know_who_the_clients_are_and_it_is_logged_as_it_is_for_the_admin(self):
        body = _json(self.get(self.sales, "dashboard:v1_clients"))
        self.assertTrue(body["sees_identity"])
        row = body["clients"][0]
        self.assertEqual((row["name"], row["phone"]), (CLIENT_NAME, CLIENT_PHONE))
        self.assertTrue(AuditLog.objects.filter(action=identity.IDENTITY_LIST, actor=self.sales).exists())

    def test_the_search_finds_them_by_name_too(self):
        found = _json(self.get(self.sales, "dashboard:v1_clients", q="ACME"))
        self.assertEqual([row["code"] for row in found["clients"]], [self.client_obj.code])

    def test_one_client_is_read_with_who_they_are_the_follow_up_numbers_and_the_tasks(self):
        Task.objects.create(client=self.client_obj, title="Delivered one", created_by=self.ops, status=TaskStatus.DELIVERED)
        ClientRequirement.objects.create(client=self.client_obj, kind="rule", text=f"Send to {CLIENT_NAME}", author=self.ops)
        body = _json(self.get(self.sales, "dashboard:v1_client", [self.client_obj.code]))
        self.assertEqual((body["client"]["name"], body["client"]["emails"][0]), (CLIENT_NAME, CLIENT_EMAIL))
        self.assertEqual((body["activity"]["total"], body["activity"]["delivered"]), (2, 1))
        # They may know the name, so the words are as they were written.
        self.assertIn(CLIENT_NAME, body["requirements"][0]["text"])
        self.assertTrue(body["tasks"])
        self.assertTrue(AuditLog.objects.filter(action=identity.IDENTITY_VIEW, actor=self.sales, target=self.client_obj.code).exists())

    def test_they_read_and_write_nothing_about_a_client(self):
        code = self.client_obj.code
        body = _json(self.get(self.sales, "dashboard:v1_client", [code]))
        self.assertFalse(body["may_edit"])
        self.assertNotIn("edit_url", body)
        self.assertEqual(body["client"]["admin_notes"], "")
        answer = self.post(self.sales, "dashboard:v1_client_requirement", {"kind": "rule", "text": "x"}, args=[code])
        self.assertEqual(answer.status_code, 403)
        self.assertEqual(ClientRequirement.objects.count(), 0)

    def test_the_others_who_open_the_classic_pages_still_have_no_door(self):
        code = self.client_obj.code
        for user in (self.tr, self.hr, self.reviewer, self.accounting):
            self.assertEqual(self.get(user, "dashboard:v1_clients").status_code, 403, user.username)
            self.assertEqual(self.get(user, "dashboard:v1_client", [code]).status_code, 403, user.username)

    def test_the_operation_still_reads_codes_only_and_no_follow_up(self):
        body = _json(self.get(self.ops, "dashboard:v1_client", [self.client_obj.code]))
        self.assertFalse(body["sees_identity"])
        self.assertIsNone(body["activity"])
        self.assertEqual(set(body["client"]), {"code"})
