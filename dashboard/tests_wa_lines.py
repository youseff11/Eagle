"""WhatsApp numbers for the operation too, linking a number from the settings page, and the admin's line switch (11/10/2026).

* A number of the company's account given to an operation person on the staff page is theirs and the admin's - the rest of
  the operation room keeps the company number, exactly like a letter to their own address (``lines``).
* The settings page lists the account's numbers and links a new one: the code it was texted is verified and the number
  registered in one step, with a PIN the system keeps and never shows (``walines``).
* The admin's chats list can be narrowed to one line; it is a view on the list, not a permission.
"""

import json
import urllib.parse
from unittest import mock

from django.test import TestCase

from . import lines, services, walines, whatsapp
from .models import AppSettings, AuditLog, Client, InboundMessage, Notification, Role, User

COMPANY, RECRUIT, MONA_NUMBER, FREE = "111", "999", "222", "333"
NUMBERS = [
    {"id": COMPANY, "display_phone_number": "+20 15 15871599", "verified_name": "Eagle", "status": "CONNECTED",
     "code_verification_status": "VERIFIED"},
    {"id": MONA_NUMBER, "display_phone_number": "+20 15 15321563", "verified_name": "Eagle", "status": "CONNECTED",
     "code_verification_status": "VERIFIED"},
    {"id": FREE, "display_phone_number": "+20 10 00000333", "verified_name": "Eagle", "status": "PENDING",
     "code_verification_status": "NOT_VERIFIED"},
]


def _settings(**over):
    conf = AppSettings.load()
    conf.whatsapp_phone_number_id = COMPANY
    conf.recruit_phone_number_id = RECRUIT
    conf.whatsapp_access_token = "token-abcdef"
    conf.whatsapp_waba_id = "4444"
    for key, value in over.items():
        setattr(conf, key, value)
    conf.save()
    return conf


class FakeMeta:
    """``whatsapp._call`` answered from a table, every call written down (the URL and the form it carried)."""

    def __init__(self, verified=False, refuse=None):
        self.calls = []
        self.verified = verified
        self.refuse = refuse or {}

    def __call__(self, url, *, token, data=None, headers=None, method="GET", raw_response=False):
        path = urllib.parse.urlparse(url).path
        form = urllib.parse.parse_qs(data.decode("utf-8")) if data else {}
        self.calls.append((method, path, form))
        for tail, error in self.refuse.items():
            if path.endswith(tail):
                raise error
        if path.endswith("/phone_numbers"):
            return {"data": NUMBERS}
        if path.endswith(("/request_code", "/verify_code", "/register")):
            return {"success": True}
        return {"id": FREE, "code_verification_status": "VERIFIED" if self.verified else "NOT_VERIFIED"}

    def posted(self, tail):
        return [form for method, path, form in self.calls if method == "POST" and path.endswith(tail)]


class LinkingTests(TestCase):
    def setUp(self):
        self.admin = User.objects.create_user("own_wl", password="x", role=Role.ADMIN)
        self.ops = User.objects.create_user("ops_wl", password="x", role=Role.OPERATION)
        _settings()
        self.client.force_login(self.admin)

    def _post(self, path, body):
        return self.client.post(f"/api/v1/admin/settings/whatsapp/{path}/", json.dumps(body), content_type="application/json")

    def test_the_list_comes_from_meta_and_says_what_each_number_is_for(self):
        meta = FakeMeta()
        with mock.patch.object(whatsapp, "_call", meta):
            response = self._post("numbers", {})
        self.assertEqual(response.status_code, 200)
        uses = {row["id"]: row["use"]["kind"] for row in response.json()["numbers"]}
        self.assertEqual(uses, {COMPANY: "company", MONA_NUMBER: "free", FREE: "free"})
        self.assertIn(("GET", "/v23.0/4444/phone_numbers", {}), meta.calls)
        # Kept: the settings page and the staff page read it without asking Meta again.
        page = self.client.get("/api/v1/admin/settings/").json()
        self.assertEqual([row["id"] for row in page["wa_numbers"]], [COMPANY, MONA_NUMBER, FREE])
        self.assertTrue(page["status"]["waba_saved"])

    def test_the_code_is_texted_to_the_number(self):
        meta = FakeMeta()
        with mock.patch.object(whatsapp, "_call", meta):
            response = self._post("send-code", {"id": FREE, "method": "SMS"})
        self.assertEqual(response.status_code, 200)
        self.assertEqual(meta.posted(f"/{FREE}/request_code"), [{"code_method": ["SMS"], "language": ["ar"]}])

    def test_typing_the_code_verifies_and_registers_with_a_pin_the_system_keeps(self):
        meta = FakeMeta()
        with mock.patch.object(whatsapp, "_call", meta):
            response = self._post("link", {"id": FREE, "code": "123-456"})
        self.assertEqual(response.status_code, 200, response.content)
        self.assertEqual(meta.posted(f"/{FREE}/verify_code"), [{"code": ["123456"]}])
        registered = meta.posted(f"/{FREE}/register")
        self.assertEqual(len(registered), 1)
        pin = registered[0]["pin"][0]
        self.assertTrue(pin.isdigit() and len(pin) == 6)
        self.assertEqual(registered[0]["messaging_product"], ["whatsapp"])
        self.assertEqual(AppSettings.load().whatsapp_pin, pin)
        # The PIN is never in an answer or the log.
        self.assertNotIn(pin, response.content.decode())
        self.assertNotIn(pin, self.client.get("/api/v1/admin/settings/").content.decode())
        self.assertFalse(AuditLog.objects.filter(detail__contains=pin).exists())
        self.assertTrue(AuditLog.objects.filter(action="whatsapp.link", target=FREE).exists())

    def test_the_kept_pin_is_used_again_for_the_next_number(self):
        _settings(whatsapp_pin="246810")
        meta = FakeMeta(verified=True)
        with mock.patch.object(whatsapp, "_call", meta):
            self.assertEqual(self._post("link", {"id": FREE}).status_code, 200)
        self.assertEqual(meta.posted(f"/{FREE}/register")[0]["pin"], ["246810"])
        # Verified already: nothing to verify.
        self.assertEqual(meta.posted(f"/{FREE}/verify_code"), [])

    def test_a_number_that_is_not_verified_needs_the_code(self):
        meta = FakeMeta()
        with mock.patch.object(whatsapp, "_call", meta):
            response = self._post("link", {"id": FREE})
        self.assertEqual(response.status_code, 400)
        self.assertIn("اطلب الكود", response.json()["error_ar"])
        self.assertEqual(meta.posted("/register"), [])

    def test_a_wrong_pin_never_replaces_the_one_that_works(self):
        _settings(whatsapp_pin="246810")
        refusal = whatsapp.WhatsAppError("x", "PIN mismatch", code=133005, raw="Two step verification PIN Mismatch")
        meta = FakeMeta(verified=True, refuse={"/register": refusal})
        with mock.patch.object(whatsapp, "_call", meta):
            response = self._post("link", {"id": FREE, "pin": "135790"})
        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.json()["code"], 133005)
        self.assertEqual(AppSettings.load().whatsapp_pin, "246810")
        self.assertNotIn("246810", response.content.decode())

    def test_bad_input_never_reaches_meta(self):
        meta = FakeMeta()
        with mock.patch.object(whatsapp, "_call", meta):
            for body in ({"id": "12a"}, {"id": FREE, "code": "12345"}, {"id": FREE, "pin": "12"}):
                self.assertEqual(self._post("link", body).status_code, 400, body)
            self.assertEqual(self._post("send-code", {"id": FREE, "method": "FAX"}).status_code, 400)
        self.assertEqual(meta.calls, [])

    def test_only_the_admin(self):
        self.client.force_login(self.ops)
        meta = FakeMeta()
        with mock.patch.object(whatsapp, "_call", meta):
            for path in ("numbers", "send-code", "link"):
                self.assertEqual(self._post(path, {"id": FREE, "code": "123456"}).status_code, 403, path)
        self.assertEqual(meta.calls, [])


class OperationLineTests(TestCase):
    """An operation person's own number works like their own mail address."""

    def setUp(self):
        self.admin = User.objects.create_user("own_ol", password="x", role=Role.ADMIN)
        self.mona = User.objects.create_user("mona_ol", password="x", role=Role.OPERATION, first_name="Mona")
        self.omar = User.objects.create_user("omar_ol", password="x", role=Role.OPERATION)
        conf = _settings()
        conf.wa_numbers = json.dumps([walines._row(item) for item in NUMBERS])
        conf.save()

    def _edit(self, person, **changes):
        self.client.force_login(self.admin)
        return self.client.post(
            f"/api/v1/admin/users/{person.pk}/save/", json.dumps({"values": changes}), content_type="application/json",
        )

    def _give_mona_her_number(self):
        self.assertEqual(self._edit(self.mona, wa_phone_number_id=MONA_NUMBER).status_code, 200)
        self.mona.refresh_from_db()

    def _wa(self, to_number, sender, text="hello"):
        payload = {"entry": [{"changes": [{"value": {
            "metadata": {"phone_number_id": to_number},
            "contacts": [{"wa_id": sender, "profile": {"name": "Client"}}],
            "messages": [{"from": sender, "id": f"wamid.{to_number}.{sender}", "type": "text", "text": {"body": text}}],
        }}]}]}
        self.client.logout()
        response = self.client.post("/webhooks/whatsapp/", data=json.dumps(payload), content_type="application/json")
        self.assertEqual(response.status_code, 200)
        return InboundMessage.objects.get(external_id=f"wamid.{to_number}.{sender}")

    # -- the staff page --------------------------------------------------------------
    def test_the_admin_gives_a_number_from_the_staff_page(self):
        self._give_mona_her_number()
        self.assertEqual(self.mona.wa_phone_number_id, MONA_NUMBER)
        # The number as people dial it comes from Meta's list: nobody types it.
        self.assertEqual(self.mona.wa_display_number, "+20 15 15321563")
        self.assertTrue(AuditLog.objects.filter(action="user.wa_line", target=self.mona.username).exists())
        form = self.client.get(f"/api/v1/admin/users/{self.omar.pk}/").json()["form"]
        offered = next(field for field in form if field["name"] == "wa_phone_number_id")
        labels = " ".join(str(choice) for choice in offered.get("choices", []))
        self.assertIn("مع mona_ol", labels)
        self.assertNotIn(COMPANY, [str(choice[0] if isinstance(choice, (list, tuple)) else choice.get("value")) for choice in offered.get("choices", [])])

    def test_one_number_one_person_and_never_the_company_number(self):
        self._give_mona_her_number()
        for number in (MONA_NUMBER, COMPANY, RECRUIT):
            self.assertEqual(self._edit(self.omar, wa_phone_number_id=number).status_code, 400, number)
        self.omar.refresh_from_db()
        self.assertEqual(self.omar.wa_phone_number_id, "")

    def test_only_operation_and_sales_hold_one(self):
        lead = User.objects.create_user("lead_ol", password="x", role=Role.TEAM_LEAD)
        self.assertEqual(self._edit(lead, wa_phone_number_id=FREE).status_code, 400)
        lead.wa_phone_number_id = FREE
        lead.save()
        lead.refresh_from_db()
        self.assertEqual(lead.wa_phone_number_id, "")
        # And whoever moves out of the operation loses theirs.
        self._give_mona_her_number()
        self.mona.role = Role.TRANSLATOR
        self.mona.save()
        self.mona.refresh_from_db()
        self.assertEqual((self.mona.wa_phone_number_id, self.mona.wa_display_number), ("", ""))

    # -- where it lands --------------------------------------------------------------
    def test_a_client_who_writes_to_her_number_is_hers_and_the_admins(self):
        self._give_mona_her_number()
        row = self._wa(MONA_NUMBER, "201000000601")
        self.assertEqual(row.owner, self.mona)
        self.assertIn(row.client, services.client_conversations(self.mona))
        self.assertIn(row.client, services.client_conversations(self.admin))
        self.assertNotIn(row.client, services.client_conversations(self.omar))
        self.assertTrue(row.visible_to(self.mona))
        self.assertFalse(row.visible_to(self.omar))
        rung = set(Notification.objects.filter(title_ar="رسالة جديدة من عميل").values_list("user_id", flat=True))
        self.assertEqual(rung, {self.mona.pk, self.admin.pk})

    def test_she_keeps_the_company_number_too(self):
        self._give_mona_her_number()
        row = self._wa(COMPANY, "201000000602")
        self.assertIsNone(row.owner)
        self.assertIn(row.client, services.client_conversations(self.mona))
        self.assertIn(row.client, services.client_conversations(self.omar))

    def test_the_answer_leaves_from_the_number_the_client_wrote_to(self):
        self._give_mona_her_number()
        own = self._wa(MONA_NUMBER, "201000000603")
        self.assertEqual(lines.reply_line(own.client, self.mona, "whatsapp"), self.mona)
        company = self._wa(COMPANY, "201000000604")
        self.assertIsNone(lines.reply_line(company.client, self.mona, "whatsapp"))
        with mock.patch.object(whatsapp, "send_text", return_value={"messages": [{"id": "wamid.out"}]}) as sent:
            ok, outbound, error = services.send_client_message(own.client, self.mona, body="hi")
        self.assertTrue(ok, error)
        self.assertEqual(sent.call_args.kwargs.get("from_id"), MONA_NUMBER)
        self.assertEqual(outbound.owner, self.mona)

    def test_a_person_without_a_number_answers_from_the_company(self):
        row = self._wa(COMPANY, "201000000605")
        self.assertIsNone(lines.reply_line(row.client, self.omar, "whatsapp"))


class AdminLineViewTests(TestCase):
    def setUp(self):
        self.admin = User.objects.create_user("own_av", password="x", role=Role.ADMIN)
        self.mona = User.objects.create_user("mona_av", password="x", role=Role.OPERATION, first_name="Mona")
        self.mona.wa_phone_number_id = MONA_NUMBER
        self.mona.save()
        _settings()
        self.hers = Client.objects.create(name="Hers", phone="+201000000701")
        InboundMessage.objects.create(client=self.hers, channel="whatsapp", body="x", sender_identity="+201000000701", owner=self.mona)
        self.company = Client.objects.create(name="Company", phone="+201000000702")
        InboundMessage.objects.create(client=self.company, channel="whatsapp", body="y", sender_identity="+201000000702")

    def _pick(self, line):
        return self.client.post("/api/v1/chats/lines/pick/", json.dumps({"line": line}), content_type="application/json")

    def _listed(self):
        rows = self.client.get("/api/v1/chats/?type=clients").json()["items"]
        return {row["code"] for row in rows}

    def test_the_admin_narrows_the_list_to_one_line_and_back(self):
        self.client.force_login(self.admin)
        lines_page = self.client.get("/api/v1/chats/lines/").json()
        self.assertEqual([line["key"] for line in lines_page["lines"]], ["", "company", str(self.mona.pk)])
        self.assertEqual(self._listed(), {self.hers.code, self.company.code})
        self.assertEqual(self._pick(str(self.mona.pk)).status_code, 200)
        self.assertEqual(self._listed(), {self.hers.code})
        self.assertEqual(self._pick("company").status_code, 200)
        self.assertEqual(self._listed(), {self.company.code})
        self.assertEqual(self._pick("").status_code, 200)
        self.assertEqual(self._listed(), {self.hers.code, self.company.code})

    def test_a_view_not_a_permission(self):
        self.client.force_login(self.admin)
        self._pick("company")
        # Her client's chat still opens by its address.
        response = self.client.get(f"/api/v1/clients/{self.hers.code}/messages/")
        self.assertEqual(response.status_code, 200)

    def test_only_a_line_there_is(self):
        self.client.force_login(self.admin)
        for bad in ("12345", "x", "../1"):
            self.assertEqual(self._pick(bad).status_code, 400, bad)

    def test_only_the_admin(self):
        self.client.force_login(self.mona)
        self.assertEqual(self.client.get("/api/v1/chats/lines/").status_code, 403)
        self.assertEqual(self._pick("company").status_code, 403)
        # And a choice left on an account that is no admin any more means nothing.
        self.mona.line_view = "company"
        self.mona.save()
        self.mona.refresh_from_db()
        self.assertEqual(self.mona.line_view, "")
