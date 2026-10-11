"""``manage.py wa_register``: the call that moves a verified number from Pending to Connected."""

import io
import urllib.parse
from unittest import mock

from django.core.management import call_command
from django.core.management.base import CommandError
from django.test import TestCase

from dashboard import whatsapp
from dashboard.models import AppSettings


class WaRegisterTests(TestCase):
    def setUp(self):
        conf = AppSettings.load()
        conf.whatsapp_access_token = "test-token"
        conf.whatsapp_api_version = "v21.0"
        conf.save()

    def test_posts_register_with_pin_and_messaging_product(self):
        with mock.patch.object(whatsapp, "_call", return_value={"success": True}) as call:
            out = io.StringIO()
            call_command("wa_register", "1409717205552232", pin="123456", stdout=out)
        url = call.call_args.args[0]
        self.assertEqual(url, "https://graph.facebook.com/v21.0/1409717205552232/register")
        self.assertEqual(call.call_args.kwargs["method"], "POST")
        self.assertEqual(call.call_args.kwargs["token"], "test-token")
        body = urllib.parse.parse_qs(call.call_args.kwargs["data"].decode("utf-8"))
        self.assertEqual(body, {"messaging_product": ["whatsapp"], "pin": ["123456"]})
        self.assertIn("Registered", out.getvalue())
        self.assertNotIn("123456", out.getvalue())

    def test_bad_pin_never_reaches_meta(self):
        with mock.patch.object(whatsapp, "_call") as call:
            for pin in ("12345", "abcdef", "1234567"):
                with self.assertRaises(CommandError):
                    call_command("wa_register", "1409717205552232", pin=pin, stdout=io.StringIO())
        call.assert_not_called()

    def test_meta_refusal_is_a_command_error(self):
        err = whatsapp.WhatsAppError("x", "refused", code=133005, raw="Two step verification PIN Mismatch")
        with mock.patch.object(whatsapp, "_call", side_effect=err):
            with self.assertRaises(CommandError):
                call_command("wa_register", "1409717205552232", pin="123456",
                             stdout=io.StringIO(), stderr=io.StringIO())
