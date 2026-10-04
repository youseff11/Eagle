"""The admin panel's settings page in the new app.

This page holds the WhatsApp token, the Claude key, the mail passwords and Google's secrets, and the switches that send people
to the new interface. What these tests hold: no secret is ever in an answer (not on a GET, not on a refusal, not in a test
report, not in the log), a secret left alone is kept and only an explicit null clears it, the classic form decides what is
valid, a request that carries one box saves one box, and the page that holds the switches stays reachable.
"""

import json
from unittest import mock

from django import forms
from django.db import connection
from django.test import Client as DjangoClient
from django.test.utils import CaptureQueriesContext
from django.urls import reverse
from django.utils import timezone

from . import api_admin_settings, api_forms, newui
from .forms import SettingsForm
from .models import AppSettings, AuditLog, Role, User
from .tests_admin_screen import SECRETS as SENTINELS, _Admin
from .tests_api_v1 import _json

GET = "dashboard:v1_admin_settings"
SAVE = "dashboard:v1_admin_settings_save"
SYNC = "dashboard:v1_admin_google_sync"
DISCONNECT = "dashboard:v1_admin_google_disconnect"
TEST_WA = "dashboard:v1_admin_test_whatsapp"
TEST_MAIL = "dashboard:v1_admin_test_email"

#: Every stored secret, with a value no other text would contain. ``SENTINELS`` covers the six with a password box; the
#: two plain-box secrets and Google's refresh token are added.
ALL_SECRETS = {
    **SENTINELS,
    "whatsapp_verify_token": "SECRET-verify-token-value",
    "google_refresh_token": "SECRET-google-refresh-value",
}


class _Settings(_Admin):
    def post(self, user, name, body):
        browser = DjangoClient()
        if user is not None:
            browser.force_login(user)
        return browser.post(reverse(name), json.dumps(body), content_type="application/json")

    def save(self, **values):
        return self.post(self.admin, SAVE, {"values": values})

    def store_secrets(self):
        conf = AppSettings.load()
        for name, value in ALL_SECRETS.items():
            setattr(conf, name, value)
        conf.save()
        return conf

    def fresh(self):
        AppSettings._cached = None
        return AppSettings.load()


class DoorMatrixTests(_Settings):
    def doors(self):
        return [("GET", GET), ("POST", SAVE), ("POST", SYNC), ("POST", DISCONNECT), ("POST", TEST_WA), ("POST", TEST_MAIL)]

    def call(self, user, method, name):
        browser = DjangoClient()
        if user is not None:
            browser.force_login(user)
        url = reverse(name)
        return browser.get(url) if method == "GET" else browser.post(url, "{}", content_type="application/json")

    def test_only_the_admin_is_answered(self):
        self.store_secrets()
        for method, name in self.doors():
            for user in (self.ops, self.lead, self.tr, self.hr, self.reviewer, self.accounting, self.sales):
                denied = self.call(user, method, name)
                self.assertEqual((denied.status_code, _json(denied)), (403, {"ok": False, "error": "forbidden"}), (name, user.username))
                for value in ALL_SECRETS.values():
                    self.assertNotIn(value, denied.content.decode("utf-8"))
            self.assertEqual(self.call(None, method, name).status_code, 401, name)

    def test_the_wrong_method_is_a_405_that_says_what_is_allowed(self):
        for method, name in self.doors():
            answer = self.call(self.admin, "POST" if method == "GET" else "GET", name)
            self.assertEqual((answer.status_code, answer["Allow"]), (405, method), name)

    def test_every_answer_is_private(self):
        for method, name in self.doors():
            with mock.patch("dashboard.galiases.sync", return_value=(False, "", None)), \
                    mock.patch("dashboard.whatsapp.check_connection", return_value={"ok": False}), \
                    mock.patch("dashboard.mailer.check_connection", return_value={"ok": False}):
                self.assertEqual(self.call(self.admin, method, name)["Cache-Control"], "private, no-store", name)


class NoSecretLeavesTests(_Settings):
    """The first promise: whatever is stored, no answer of this layer carries it."""

    def everything_said(self):
        """Every answer the layer gives the admin about settings, as one text."""
        said = [self.get(self.admin, GET).content.decode("utf-8")]
        said.append(self.save(response_window_seconds="45").content.decode("utf-8"))
        said.append(self.save(mail_aliases="not an address").content.decode("utf-8"))
        said.append(self.save(imap_port="not a number").content.decode("utf-8"))
        said.append(self.save(claude_model="x" * 500).content.decode("utf-8"))
        said.append(self.save(nothing_like_this="1").content.decode("utf-8"))
        with mock.patch("dashboard.galiases.sync", return_value=(True, "", ([], [], []))):
            said.append(self.post(self.admin, SYNC, {}).content.decode("utf-8"))
        said.append(self.get(self.admin, "dashboard:v1_admin_users").content.decode("utf-8"))
        return "\n".join(said)

    def test_no_stored_secret_is_in_any_answer(self):
        self.store_secrets()
        text = self.everything_said()
        for name, value in ALL_SECRETS.items():
            self.assertNotIn(value, text, name)

    def test_a_secret_is_described_as_saved_or_not_and_never_with_a_value(self):
        self.store_secrets()
        fields = {field["name"]: field for field in _json(self.get(self.admin, GET))["fields"]}
        for name in api_admin_settings.SECRET_FIELDS:
            self.assertEqual(fields[name]["kind"], "password", name)
            self.assertIs(fields[name]["saved"], True, name)
            self.assertNotIn("value", fields[name], name)
        AppSettings.objects.update(claude_api_key="")
        AppSettings._cached = None
        again = {field["name"]: field for field in _json(self.get(self.admin, GET))["fields"]}
        self.assertIs(again["claude_api_key"]["saved"], False)

    def test_every_field_with_a_password_box_is_treated_as_a_secret(self):
        form = SettingsForm(instance=AppSettings.load())
        for name, field in form.fields.items():
            if isinstance(field.widget, forms.PasswordInput):
                self.assertIn(name, api_admin_settings.SECRET_FIELDS, f"{name} has a password box but is not listed as a secret")

    def test_every_listed_secret_is_a_field_of_the_form(self):
        form = SettingsForm(instance=AppSettings.load())
        for name in api_admin_settings.SECRET_FIELDS:
            self.assertIn(name, form.fields)

    def test_no_value_of_a_secret_is_in_the_log(self):
        self.store_secrets()
        self.save(response_window_seconds="45")
        self.save(newui_operation_roles=["admin", "operation"])
        everything = json.dumps(list(AuditLog.objects.values()), default=str)
        for name, value in ALL_SECRETS.items():
            self.assertNotIn(value, everything, name)

    def test_the_error_of_a_connection_test_is_cleaned_of_any_stored_secret(self):
        self.store_secrets()
        leaky = {
            "ok": False, "error_ar": f"فشل {ALL_SECRETS['whatsapp_access_token']}", "error_en": f"Failed: {ALL_SECRETS['imap_password']}",
            "nested": {"detail": [ALL_SECRETS["claude_api_key"]]}, "number": "", "sent": False,
        }
        with mock.patch("dashboard.whatsapp.check_connection", return_value=leaky), mock.patch("dashboard.mailer.check_connection", return_value=leaky):
            texts = [self.post(self.admin, TEST_WA, {"to": "2010"}).content.decode("utf-8"), self.post(self.admin, TEST_MAIL, {"to": "a@b.example"}).content.decode("utf-8")]
        for text in texts:
            for value in ALL_SECRETS.values():
                self.assertNotIn(value, text)
            self.assertIn("***", text)

    def test_the_error_of_a_google_sync_is_cleaned_too(self):
        self.store_secrets()
        failing = (False, f"Google said no to {ALL_SECRETS['google_client_secret']}", None)
        with mock.patch("dashboard.galiases.sync", return_value=failing):
            text = self.post(self.admin, SYNC, {}).content.decode("utf-8")
        self.assertNotIn(ALL_SECRETS["google_client_secret"], text)
        self.assertIn("***", text)

    def test_the_last_google_error_on_the_page_is_cleaned(self):
        conf = self.store_secrets()
        conf.google_sync_error = f"bad {ALL_SECRETS['google_refresh_token']}"
        conf.save()
        text = self.get(self.admin, GET).content.decode("utf-8")
        self.assertNotIn(ALL_SECRETS["google_refresh_token"], text)

    def test_a_short_value_is_not_scrubbed_out_of_ordinary_words(self):
        conf = AppSettings.load()
        conf.imap_password = "ab"
        conf.save()
        self.assertEqual(api_admin_settings.scrub("an ab word", conf), "an ab word")


class SecretEditingTests(_Settings):
    """The second promise: left alone is kept, typed is replaced, null clears."""

    def test_a_secret_left_out_is_kept(self):
        self.store_secrets()
        self.assertEqual(self.save(claude_model="claude-x").status_code, 200)
        conf = self.fresh()
        for name, value in ALL_SECRETS.items():
            self.assertEqual(getattr(conf, name), value, name)
        self.assertEqual(conf.claude_model, "claude-x")

    def test_a_secret_sent_empty_is_kept(self):
        self.store_secrets()
        names = [name for name in api_admin_settings.SECRET_FIELDS]
        self.assertEqual(self.save(**{name: "" for name in names}).status_code, 200)
        conf = self.fresh()
        for name in names:
            self.assertEqual(getattr(conf, name), ALL_SECRETS[name], name)

    def test_a_secret_typed_replaces_the_stored_one_and_only_that_one(self):
        self.store_secrets()
        self.save(whatsapp_access_token="EAAG-brand-new-token")
        conf = self.fresh()
        self.assertEqual(conf.whatsapp_access_token, "EAAG-brand-new-token")
        self.assertEqual(conf.claude_api_key, ALL_SECRETS["claude_api_key"])
        self.assertEqual(conf.imap_password, ALL_SECRETS["imap_password"])

    def test_only_an_explicit_null_clears_a_secret(self):
        self.store_secrets()
        self.save(claude_api_key=None)
        conf = self.fresh()
        self.assertEqual(conf.claude_api_key, "")
        self.assertEqual(conf.imap_password, ALL_SECRETS["imap_password"])
        fields = {field["name"]: field for field in _json(self.get(self.admin, GET))["fields"]}
        self.assertIs(fields["claude_api_key"]["saved"], False)

    def test_a_secret_of_the_wrong_shape_is_refused_and_nothing_changes(self):
        self.store_secrets()
        for bad in (["x"], 5, True, {"a": 1}):
            answer = self.save(claude_api_key=bad)
            self.assertEqual((answer.status_code, _json(answer)["error"]), (400, "bad_body"), repr(bad))
        self.assertEqual(self.fresh().claude_api_key, ALL_SECRETS["claude_api_key"])

    def test_a_stored_google_refresh_token_cannot_be_touched_from_here(self):
        self.store_secrets()
        answer = self.save(google_refresh_token="stolen")
        self.assertEqual((answer.status_code, _json(answer)["error"]), (400, "bad_body"))
        self.assertEqual(self.fresh().google_refresh_token, ALL_SECRETS["google_refresh_token"])


class FormTests(_Settings):
    def test_every_field_of_the_form_is_in_exactly_one_group_of_one_section(self):
        form = SettingsForm(instance=AppSettings.load())
        shown = [name for section in api_admin_settings.SECTIONS for group in section["groups"] for name in group["fields"]]
        rollout = {name for name in form.fields if name.startswith("newui_")}
        self.assertEqual(sorted(shown), sorted(set(form.fields) - rollout))
        self.assertEqual(len(shown), len(set(shown)))

    def test_every_text_override_names_a_field_that_exists(self):
        form = SettingsForm(instance=AppSettings.load())
        self.assertEqual(set(api_admin_settings.TEXTS) - set(form.fields), set())

    def test_the_door_sends_the_sections_the_fields_and_the_bilingual_texts(self):
        body = _json(self.get(self.admin, GET))
        self.assertEqual([section["key"] for section in body["sections"]], ["ai", "workflow", "whatsapp", "email"])
        fields = {field["name"]: field for field in body["fields"]}
        self.assertEqual((fields["claude_model"]["label_ar"], fields["claude_model"]["label_en"]), ("الموديل", "Model"))
        self.assertIn("hint_ar", fields["rate_keywords"])
        self.assertEqual(fields["group_creator_roles"]["kind"], "multi")
        self.assertEqual(fields["smtp_use_tls"]["kind"], "checkbox")
        self.assertEqual(fields["mail_aliases"]["kind"], "textarea")
        self.assertEqual(fields["imap_port"]["kind"], "number")

    def test_the_values_are_the_stored_ones(self):
        conf = AppSettings.load()
        conf.claude_model = "claude-test-model"
        conf.imap_host = "imap.example.com"
        conf.rate_keywords = "price, rate"
        conf.group_creator_roles = "admin,operation"
        conf.save()
        fields = {field["name"]: field for field in _json(self.get(self.admin, GET))["fields"]}
        self.assertEqual(fields["claude_model"]["value"], "claude-test-model")
        self.assertEqual(fields["imap_host"]["value"], "imap.example.com")
        self.assertEqual(fields["rate_keywords"]["value"], "price, rate")
        self.assertEqual(fields["group_creator_roles"]["value"], ["operation"])

    def test_a_change_is_saved_and_written_down(self):
        answer = self.save(claude_model="claude-new", response_window_seconds="75", smtp_use_tls=False)
        self.assertEqual((answer.status_code, _json(answer)), (200, {"ok": True}))
        conf = self.fresh()
        self.assertEqual((conf.claude_model, conf.response_window_seconds, conf.smtp_use_tls), ("claude-new", 75, False))
        self.assertTrue(AuditLog.objects.filter(action="settings.update", actor=self.admin).exists())

    def test_one_box_saves_one_box(self):
        before = self.fresh()
        self.save(claude_model="claude-new")
        after = self.fresh()
        changed = [
            field.name for field in AppSettings._meta.fields
            if field.name not in ("claude_model", "updated_at") and getattr(before, field.name) != getattr(after, field.name)
        ]
        self.assertEqual(changed, [])

    def test_what_the_classic_form_refuses_is_refused_with_its_messages_and_nothing_is_saved(self):
        before = self.fresh().claude_model
        for values, field in (
            ({"mail_aliases": "not an address"}, "mail_aliases"),
            ({"mail_aliases_hidden": "also not"}, "mail_aliases_hidden"),
            ({"imap_port": "abc"}, "imap_port"),
            ({"response_window_seconds": "-5"}, "response_window_seconds"),
            ({"group_creator_roles": ["translator", "pilot"]}, "group_creator_roles"),
        ):
            answer = self.save(claude_model="should-not-stick", **values)
            body = _json(answer)
            self.assertEqual((answer.status_code, body["error"]), (400, "invalid"), values)
            self.assertIn(field, body["errors"], values)
        self.assertEqual(self.fresh().claude_model, before)

    def test_the_alias_list_is_cleaned_like_the_classic_page_does(self):
        self.save(mail_aliases="Ops1@Example.com\nops1@example.com\n\nSales@Example.com, hr@example.com")
        self.assertEqual(self.fresh().mail_aliases, "ops1@example.com\nsales@example.com\nhr@example.com")

    def test_the_group_creators_always_include_the_admin(self):
        self.save(group_creator_roles=["translator"])
        self.assertEqual(self.fresh().group_roles, ["admin", "translator"])
        self.save(group_creator_roles=[])
        self.assertEqual(self.fresh().group_roles, ["admin"])

    def test_the_alias_list_is_google_s_while_google_is_linked(self):
        conf = AppSettings.load()
        conf.google_client_id, conf.google_client_secret, conf.google_refresh_token = "cid", "csecret-value", "refresh-value"
        conf.mail_aliases = "from-google@example.com"
        conf.save()
        field = next(one for one in _json(self.get(self.admin, GET))["fields"] if one["name"] == "mail_aliases")
        self.assertIs(field["disabled"], True)
        self.save(mail_aliases="typed@example.com", claude_model="x")
        self.assertEqual(self.fresh().mail_aliases, "from-google@example.com")

    def test_hiding_an_address_takes_it_off_the_list_at_once(self):
        with mock.patch("dashboard.galiases.sync") as sync:
            self.save(mail_aliases_hidden="hr@example.com")
        sync.assert_called_once_with(force=True)
        with mock.patch("dashboard.galiases.sync") as sync:
            self.save(claude_model="y")
        sync.assert_not_called()

    def test_fields_the_form_does_not_have_are_refused(self):
        for extra in ({"google_refresh_token": "x"}, {"new_ui": {}}, {"id": 1}, {"google_sync_at": "2020-01-01"}, {"password": "x"}):
            answer = self.save(**extra)
            self.assertEqual((answer.status_code, _json(answer)["error"]), (400, "bad_body"), extra)

    def test_a_body_that_is_not_the_shape_is_refused(self):
        browser = DjangoClient()
        browser.force_login(self.admin)
        for payload, kind in (("[]", "application/json"), ("{", "application/json"), ('{"values": []}', "application/json"), ("values=1", "application/x-www-form-urlencoded")):
            answer = browser.post(reverse(SAVE), payload, content_type=kind)
            self.assertEqual((answer.status_code, _json(answer)["error"]), (400, "bad_body"), payload)
        for values in ({"claude_model": ["a"]}, {"claude_model": {"a": 1}}, {"smtp_use_tls": "yes"}, {"claude_model": "a\x00b"}, {"group_creator_roles": "admin"}):
            self.assertEqual(self.save(**values).status_code, 400, values)

    def test_a_get_changes_nothing(self):
        self.store_secrets()
        before = (AuditLog.objects.count(), self.fresh().updated_at if hasattr(AppSettings, "updated_at") else None)
        self.get(self.admin, GET)
        self.assertEqual((AuditLog.objects.count(), self.fresh().updated_at if hasattr(AppSettings, "updated_at") else None), before)

    def test_the_status_and_the_addresses(self):
        conf = AppSettings.load()
        conf.whatsapp_access_token, conf.whatsapp_phone_number_id = "EAAG-token-value", "12345"
        conf.imap_host, conf.imap_user = "imap.example.com", "mail@example.com"
        conf.google_sync_at = timezone.now()
        conf.save()
        body = _json(self.get(self.admin, GET))
        self.assertEqual(body["status"]["whatsapp_saved"], True)
        self.assertEqual(body["status"]["email_saved"], True)
        self.assertEqual(body["status"]["google_connected"], False)
        self.assertTrue(body["urls"]["webhook"].endswith("/webhooks/whatsapp/"))
        self.assertTrue(body["urls"]["google_redirect"].endswith("/callback/"))
        self.assertEqual((body["urls"]["is_local"], body["urls"]["is_https"]), (False, False))
        self.assertTrue(body["status"]["google_sync_at"]["en"])
        # The rollout switches are gone from the page: the whole site is the app.
        self.assertNotIn("newui", body)
        self.assertFalse([name for name in (field["name"] for field in body["fields"]) if name.startswith("newui_")])

    def test_the_number_of_questions_does_not_grow_with_the_people(self):
        def questions():
            with CaptureQueriesContext(connection) as seen:
                self.assertEqual(self.get(self.admin, GET).status_code, 200)
            return len(seen)

        few = questions()
        for index in range(15):
            User.objects.create_user(f"extra_{index}", password="pw", role=Role.OPERATION)
        self.assertEqual(questions(), few)


class RolloutSwitchTests(_Settings):
    """The switches that send people to the new interface live on this page."""

    def switch(self, key):
        return newui.config(self.fresh(), key)

    def test_the_same_switches_again_write_nothing_new(self):
        self.save(newui_operation_roles=["admin", "operation"])
        count = AuditLog.objects.filter(action="settings.new_ui").count()
        self.save(newui_operation_roles=["admin", "operation"])
        self.assertEqual(AuditLog.objects.filter(action="settings.new_ui").count(), count)

class GoogleAndTestTests(_Settings):
    def test_a_sync_says_what_changed(self):
        self.ops.mail_alias = "gone@example.com"
        self.ops.save()
        with mock.patch("dashboard.galiases.sync", return_value=(True, "", (["new@example.com"], ["gone@example.com"], [self.ops]))) as sync:
            body = _json(self.post(self.admin, SYNC, {}))
        sync.assert_called_once_with(force=True)
        self.assertEqual(
            (body["ran"], body["error"], body["added"], body["removed"], body["released"]),
            (True, "", ["new@example.com"], ["gone@example.com"], [str(self.ops)]),
        )

    def test_a_sync_that_could_not_run_says_why_and_is_not_an_error_of_the_door(self):
        with mock.patch("dashboard.galiases.sync", return_value=(False, "Google refused", None)):
            answer = self.post(self.admin, SYNC, {})
        self.assertEqual((answer.status_code, _json(answer)["ok"], _json(answer)["error"], _json(answer)["added"]), (200, True, "Google refused", []))

    def test_disconnecting_forgets_the_token_keeps_the_client_settings_and_is_written_down(self):
        conf = self.store_secrets()
        conf.google_client_id = "client-id-value"
        conf.save()
        answer = self.post(self.admin, DISCONNECT, {})
        self.assertEqual(_json(answer), {"ok": True})
        conf = self.fresh()
        self.assertEqual((conf.google_refresh_token, conf.google_client_id), ("", "client-id-value"))
        self.assertEqual(conf.google_client_secret, ALL_SECRETS["google_client_secret"])
        self.assertTrue(AuditLog.objects.filter(action="settings.google_disconnect", actor=self.admin).exists())

    def test_the_connection_tests_pass_the_address_on_and_return_the_report(self):
        report = {"ok": True, "number": "+20100", "name": "Eagle", "sent": True}
        with mock.patch("dashboard.whatsapp.check_connection", return_value=report) as wa:
            self.assertEqual(_json(self.post(self.admin, TEST_WA, {"to": " 2010123 "})), report)
        wa.assert_called_once_with("2010123")
        with mock.patch("dashboard.mailer.check_connection", return_value={"ok": True, "sent": False}) as mail:
            self.post(self.admin, TEST_MAIL, {})
        self.assertEqual(mail.call_args.args[1], "")

    def test_an_address_that_is_not_the_shape_is_refused_before_anything_is_sent(self):
        with mock.patch("dashboard.whatsapp.check_connection") as wa, mock.patch("dashboard.mailer.check_connection") as mail:
            for body in ({"to": ["x"]}, {"to": 5}, {"to": "x" * 300}, {"to": "a\x00b"}):
                self.assertEqual(self.post(self.admin, TEST_WA, body).status_code, 400, body)
                self.assertEqual(self.post(self.admin, TEST_MAIL, body).status_code, 400, body)
        wa.assert_not_called()
        mail.assert_not_called()


class HandOnTests(_Settings):
    def test_the_classic_page_goes_on_with_the_switch(self):
        self.turn_on()
        answer = self.get(self.admin, "dashboard:admin_settings")
        self.assertEqual((answer.status_code, answer["Location"]), (302, "/app/admin/settings"))

    def test_the_google_steps_land_on_the_settings_page_of_the_app(self):
        answer = self.get(self.admin, "dashboard:google_callback")
        self.assertEqual((answer.status_code, answer["Location"]), (302, "/app/admin/settings"))

class WhatWasChangedTests(_Settings):
    """A save says which boxes it changed - by name, never by value - and a secret as set or cleared."""

    def last_detail(self):
        return AuditLog.objects.filter(action="settings.update").latest("pk").detail

    def test_the_names_of_the_changed_boxes_are_written_down(self):
        self.save(claude_model="claude-new", response_window_seconds="75")
        self.assertEqual(sorted(self.last_detail().split(", ")), ["claude_model", "response_window_seconds"])

    def test_a_secret_is_written_as_set_or_cleared_and_never_with_its_value(self):
        self.store_secrets()
        self.save(whatsapp_app_secret="a-brand-new-app-secret", webhook_shared_secret=None)
        detail = self.last_detail()
        self.assertIn("whatsapp_app_secret:set", detail)
        self.assertIn("webhook_shared_secret:cleared", detail)
        everything = json.dumps(list(AuditLog.objects.values()), default=str)
        for value in (*ALL_SECRETS.values(), "a-brand-new-app-secret"):
            self.assertNotIn(value, everything)

    def test_the_group_creators_are_named_only_when_they_were_sent(self):
        self.save(claude_model="claude-x")
        self.assertEqual(self.last_detail(), "claude_model")
        self.save(group_creator_roles=["translator"])
        self.assertEqual(self.last_detail(), "group_creator_roles")

    def test_nothing_changed_writes_an_empty_detail(self):
        self.save(claude_model=self.fresh().claude_model)
        self.assertEqual(self.last_detail(), "")

    def test_a_secret_left_alone_is_not_named(self):
        self.store_secrets()
        self.save(claude_model="claude-other")
        self.assertEqual(self.last_detail(), "claude_model")

    def test_the_page_is_told_whether_the_webhook_can_check_a_signature(self):
        status = _json(self.get(self.admin, GET))["status"]
        self.assertEqual((status["webhook_signed"], status["webhook_secret_set"]), (False, False))
        conf = AppSettings.load()
        conf.whatsapp_app_secret, conf.webhook_shared_secret = "app-secret-value", "shared-secret-value"
        conf.save()
        status = _json(self.get(self.admin, GET))["status"]
        self.assertEqual((status["webhook_signed"], status["webhook_secret_set"]), (True, True))
        self.assertNotIn("app-secret-value", json.dumps(status))
        self.save(whatsapp_app_secret=None)
        self.assertIs(_json(self.get(self.admin, GET))["status"]["webhook_signed"], False)
