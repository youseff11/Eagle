"""``/app/``: the page that carries the React app.

It must be behind the login, carry no data about anyone, say plainly when the app
has not been built, and never let someone use the new app to skip the check-in
screen.
"""

import json
import re
import tempfile
from pathlib import Path
from unittest import mock

from django.test import Client as DjangoClient
from django.test import TestCase
from django.urls import resolve, reverse

from . import spa
from .models import Role, User

MANIFEST = {
    "src/main.tsx": {
        "file": "assets/main-AbC123.js",
        "name": "main",
        "src": "src/main.tsx",
        "isEntry": True,
        "css": ["assets/main-XyZ789.css"],
    }
}


class _Built(TestCase):
    """A user, and a manifest on disk as ``npm run build`` would leave it."""

    def setUp(self):
        self.user = User.objects.create_user(
            "person_spa_user", password="pw", role=Role.OPERATION, first_name="Nour", last_name="Operation",
        )
        folder = tempfile.TemporaryDirectory()
        self.addCleanup(folder.cleanup)
        self.manifest_file = Path(folder.name) / "manifest.json"
        self.write_manifest(MANIFEST)
        patcher = mock.patch.object(spa, "MANIFEST_PATH", self.manifest_file)
        patcher.start()
        self.addCleanup(patcher.stop)

    def write_manifest(self, data):
        self.manifest_file.write_text(json.dumps(data), encoding="utf-8")

    def open(self, path="/app/", user="default", **cookies):
        browser = DjangoClient()
        for name, value in cookies.items():
            browser.cookies[name] = value
        if user == "default":
            browser.force_login(self.user)
        elif user is not None:
            browser.force_login(user)
        return browser.get(path)

    def config_of(self, response):
        match = re.search(r'<script id="app-config" type="application/json">(.*?)</script>', response.content.decode())
        self.assertIsNotNone(match, "no app-config script in the page")
        return json.loads(match.group(1))


class ShellPageTests(_Built):
    def test_the_anonymous_are_sent_to_sign_in_and_come_back(self):
        answer = self.open("/app/notifications", user=None)
        self.assertEqual(answer.status_code, 302)
        self.assertEqual(answer["Location"], "/login/?next=/app/notifications")

    def test_a_signed_in_person_gets_the_page_with_the_built_files(self):
        answer = self.open()
        self.assertEqual(answer.status_code, 200)
        page = answer.content.decode()
        self.assertIn('<div id="root"></div>', page)
        self.assertRegex(page, r'<script type="module" src="[^"]*assets/main-AbC123\.js"></script>')
        self.assertRegex(page, r'<link rel="stylesheet" href="[^"]*assets/main-XyZ789\.css">')

    def test_the_design_system_comes_before_the_apps_own_css(self):
        page = self.open().content.decode()
        self.assertLess(page.index("css/app.css"), page.index("assets/main-XyZ789.css"))

    def test_the_icon_sprite_is_in_the_page(self):
        page = self.open().content.decode()
        self.assertIn('id="i-bell"', page)
        self.assertIn('id="i-message"', page)

    def test_any_path_under_app_is_the_same_page(self):
        first = self.open("/app/").content
        for path in ("/app/notifications", "/app/a/b/c", "/app/chats/g12"):
            self.assertEqual(self.open(path).content, first, path)

    def test_the_classic_pages_scripts_are_not_loaded(self):
        page = self.open().content.decode()
        for old in ("js/app.js", "js/chat.js", "js/calls.js", "js/attendance.js", "EAGLE_CFG"):
            self.assertNotIn(old, page, old)

    def test_the_page_carries_no_data_about_the_person(self):
        page = self.open().content.decode()
        for private in ("person_spa_user", "Nour", "Operation", "pw"):
            self.assertNotIn(f">{private}<", page)
        self.assertNotIn("person_spa_user", page)

    def test_it_is_never_cached(self):
        answer = self.open()
        self.assertIn("no-cache", answer["Cache-Control"])
        self.assertIn("no-store", answer["Cache-Control"])

    def test_it_hands_over_the_csrf_cookie(self):
        self.assertIn("csrftoken", self.open().cookies)

    def test_only_a_read_is_allowed(self):
        browser = DjangoClient()
        browser.force_login(self.user)
        self.assertEqual(browser.post("/app/").status_code, 405)
        self.assertEqual(browser.head("/app/").status_code, 200)

    def test_both_urls_resolve_to_the_one_view(self):
        self.assertEqual(resolve("/app/").url_name, "app")
        self.assertEqual(resolve("/app/anything/here").url_name, "app_path")
        self.assertEqual(reverse("dashboard:app"), "/app/")


class ShellNotBuiltTests(_Built):
    def test_it_says_so_instead_of_failing(self):
        self.manifest_file.unlink()
        answer = self.open()
        self.assertEqual(answer.status_code, 503)
        text = answer.content.decode()
        self.assertIn("npm run build", text)
        self.assertIn("لسه متبنتش", text)
        self.assertIn("text/plain", answer["Content-Type"])

    def test_a_broken_manifest_is_the_same_as_none(self):
        for broken in ("{not json", "[]", "null", '{"src/main.tsx": {"name": "main"}}', "{}"):
            self.manifest_file.write_text(broken, encoding="utf-8")
            self.assertEqual(self.open().status_code, 503, broken)


class ConfigTests(_Built):
    def test_the_default_is_arabic_dark_and_the_classic_poll_interval(self):
        answer = self.open()
        config = self.config_of(answer)
        self.assertEqual(config["lang"], "ar")
        self.assertEqual(config["theme"], "dark")
        self.assertIsInstance(config["pollMs"], int)
        page = answer.content.decode()
        self.assertIn('lang="ar" dir="rtl" data-theme="dark"', page)

    def test_the_cookie_the_classic_pages_set_is_honoured(self):
        answer = self.open(eagle_lang="en", eagle_theme="light")
        self.assertIn('lang="en" dir="ltr" data-theme="light"', answer.content.decode())
        self.assertEqual(self.config_of(answer)["lang"], "en")

    def test_a_cookie_that_is_not_a_known_value_does_not_override_the_saved_preference(self):
        self.user.ui_lang, self.user.ui_theme = "en", "light"
        self.user.save()
        config = self.config_of(self.open(eagle_lang="fr", eagle_theme="blue"))
        self.assertEqual((config["lang"], config["theme"]), ("en", "light"))

    def test_the_saved_preference_is_used_without_a_cookie(self):
        self.user.ui_lang, self.user.ui_theme = "en", "light"
        self.user.save()
        config = self.config_of(self.open())
        self.assertEqual((config["lang"], config["theme"]), ("en", "light"))

    def test_a_hostile_cookie_cannot_get_into_the_page(self):
        evil = '"></script><script>alert(1)</script>'
        answer = self.open(eagle_lang=evil, eagle_theme=evil)
        page = answer.content.decode()
        self.assertNotIn("<script>alert(1)", page)
        self.assertEqual(self.config_of(answer)["lang"], "ar")
        self.assertEqual(self.config_of(answer)["theme"], "dark")
        self.assertIn('lang="ar" dir="rtl" data-theme="dark"', page)


class CheckInTests(_Built):
    def test_when_the_check_in_screen_is_due_the_person_goes_to_the_classic_interface(self):
        with mock.patch("dashboard.spa.attendance.gate_for", return_value={"kind": "check_in"}):
            for path in ("/app/", "/app/notifications"):
                answer = self.open(path)
                self.assertEqual(answer.status_code, 302, path)
                self.assertEqual(answer["Location"], "/")

    def test_the_reminders_that_can_be_put_off_do_not_send_anyone_away(self):
        for kind in ("check_out", "extra"):
            with mock.patch("dashboard.spa.attendance.gate_for", return_value={"kind": kind}):
                self.assertEqual(self.open().status_code, 200, kind)

    def test_when_nothing_is_due_the_app_opens(self):
        with mock.patch("dashboard.spa.attendance.gate_for", return_value=None):
            self.assertEqual(self.open().status_code, 200)


class BuiltAssetsTests(_Built):
    def test_urls_come_from_the_manifest_through_static(self):
        assets = spa.built_assets()
        self.assertTrue(assets["js"].endswith("app/assets/main-AbC123.js"))
        self.assertEqual(len(assets["css"]), 1)
        self.assertTrue(assets["css"][0].endswith("app/assets/main-XyZ789.css"))

    def test_an_entry_under_another_key_is_still_found(self):
        self.write_manifest({"whatever": {"file": "assets/x.js", "isEntry": True}})
        self.assertTrue(spa.built_assets()["js"].endswith("app/assets/x.js"))
        self.assertEqual(spa.built_assets()["css"], [])

    def test_a_chunk_that_is_not_an_entry_is_not_taken(self):
        self.write_manifest({"chunk": {"file": "assets/c.js"}})
        self.assertIsNone(spa.built_assets())

    def test_no_file_means_not_built(self):
        self.manifest_file.unlink()
        self.assertIsNone(spa.built_assets())


class ContentSecurityPolicyTests(_Built):
    def policy(self, **kwargs):
        browser = DjangoClient()
        browser.force_login(self.user)
        header = browser.get("/app/", **kwargs)["Content-Security-Policy"]
        return {part.split(" ", 1)[0]: part.split(" ", 1)[1] if " " in part else "" for part in header.split("; ")}

    def test_scripts_and_styles_only_from_this_site(self):
        policy = self.policy()
        self.assertEqual(policy["script-src"], "'self'")
        self.assertEqual(policy["default-src"], "'self'")
        self.assertEqual(policy["style-src"], "'self' https://fonts.googleapis.com")
        self.assertEqual(policy["object-src"], "'none'")
        self.assertEqual(policy["base-uri"], "'none'")

    def test_nothing_is_allowed_to_run_from_a_string(self):
        header = "; ".join(f"{k} {v}" for k, v in self.policy().items())
        self.assertNotIn("'unsafe-eval'", header)
        for directive in ("script-src", "style-src", "default-src"):
            self.assertNotIn("unsafe-inline", self.policy()[directive], directive)
        # The one inline thing is the icon sprite's style attribute, and only as an attribute.
        self.assertEqual(self.policy()["style-src-attr"], "'unsafe-inline'")

    def test_the_page_cannot_be_framed_and_forms_post_home(self):
        policy = self.policy()
        self.assertEqual(policy["frame-ancestors"], "'none'")
        self.assertEqual(policy["form-action"], "'self'")

    def test_the_socket_is_allowed_on_this_host_and_with_the_right_scheme(self):
        self.assertEqual(self.policy()["connect-src"], "'self' ws://testserver")
        self.assertEqual(self.policy(secure=True)["connect-src"], "'self' wss://testserver")

    def test_the_apps_page_has_nothing_the_policy_forbids(self):
        page = self.open().content.decode()
        # Inline scripts that run, inline event handlers, and style attributes in the page itself.
        scripts = re.findall(r"<script([^>]*)>", page)
        for attrs in scripts:
            self.assertTrue('type="application/json"' in attrs or " src=" in attrs, attrs)
        self.assertNotRegex(page, r"\son[a-z]+=")
        self.assertNotIn("javascript:", page)
        self.assertNotIn("<base", page)

    def test_only_the_apps_page_gets_it(self):
        self.assertNotIn("Content-Security-Policy", DjangoClient().get("/login/"))
        self.manifest_file.unlink()
        broken = self.open()
        self.assertEqual(broken.status_code, 503)
        self.assertNotIn("Content-Security-Policy", broken)
