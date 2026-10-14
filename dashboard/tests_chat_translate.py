"""«ترجم» beside a client's message: the words in Arabic, for the person answering (``/api/v1/clients/<code>/messages/<id>/translate/``).

What is pinned here:

* only a message this person already sees in the conversation is translated - a message off their line, one rate-blocked
  from them, one of another client named under this client's code, or any of it for a role that does not answer clients,
  answers like an unknown one and nothing reaches the model;
* the translation is kept on the message: a second press, by anybody, does not call the model again;
* nothing is sent to the client, and the message itself is left as it came;
* off in the settings (the default), no key, a broken call, too many in a minute and a message with no words each say so, and keep nothing;
* the open conversation says whether the button is offered (on in the settings and a key saved), on the fetch and on
  the answer to a send; only the admin turns it on or off, from the settings page.
"""

import json
from unittest import mock

from django.core.cache import cache
from django.urls import reverse

from . import translate
from .models import AppSettings, AuditLog, Channel, InboundMessage
from .tests_chat_lists import _json
from .tests_chat_send import _Send

ARABIC = "من فضلك سعّرلي ده"


def _answer(text=ARABIC):
    return {"content": [{"type": "text", "text": text}]}


class _Translate(_Send):
    def setUp(self):
        super().setUp()
        cache.clear()
        AppSettings.load()
        AppSettings.objects.update(claude_api_key="a-test-key-not-a-real-one", chat_translate_enabled=True)
        self.model = mock.patch("dashboard.ai._post", return_value=_answer()).start()

    def translate(self, user, message, code=None, method="post"):
        url = reverse("dashboard:v1_client_translate", args=[code or message.client.code, message.pk])
        call = getattr(self.browser(user), method)
        return call(url, "{}", content_type="application/json") if method == "post" else call(url)

    def refused_unseen(self, answer):
        self.assertEqual(answer.status_code, 404)
        self.model.assert_not_called()
        self.nothing_left_the_building()


class TranslateDoorTests(_Translate):
    def test_the_operation_reads_a_client_message_in_arabic(self):
        answer = self.translate(self.ops, self.heard)
        self.assertEqual(answer.status_code, 200)
        self.assertEqual(_json(answer), {"ok": True, "uid": f"in-{self.heard.pk}", "text": ARABIC})
        # The words went to the model as text to translate, and nothing went to the client.
        prompt = self.model.call_args.args[2]
        self.assertIn("<message>\nPlease quote this\n</message>", prompt)
        self.nothing_left_the_building()
        self.heard.refresh_from_db()
        self.assertEqual((self.heard.body, self.heard.translation_ar), ("Please quote this", ARABIC))

    def test_a_second_press_by_anybody_does_not_call_the_model_again(self):
        self.translate(self.ops, self.heard)
        for person in (self.ops, self.admin):
            self.assertEqual(_json(self.translate(person, self.heard))["text"], ARABIC)
        self.assertEqual(self.model.call_count, 1)

    def test_the_admin_and_sales_on_their_own_line(self):
        self.assertEqual(self.translate(self.admin, self.heard).status_code, 200)
        self.assertEqual(self.translate(self.sales, self.sales_heard).status_code, 200)

    def test_a_message_off_this_persons_line_answers_like_an_unknown_one(self):
        before = AuditLog.objects.count()
        # The operation and a Sales number's client; another Sales person and the company line.
        self.refused_unseen(self.translate(self.ops, self.sales_heard))
        self.refused_unseen(self.translate(self.sales2, self.sales_heard))
        self.refused_unseen(self.translate(self.sales, self.heard))
        self.assertEqual(AuditLog.objects.count(), before + 3)
        self.sales_heard.refresh_from_db()
        self.assertEqual(self.sales_heard.translation_ar, "")

    def test_a_message_of_another_client_under_this_clients_code(self):
        # The operation may open this client, and the id is a real message - of a client on a Sales line.
        self.refused_unseen(self.translate(self.ops, self.sales_heard, code=self.client_obj.code))
        # And an id that is nobody's.
        url = reverse("dashboard:v1_client_translate", args=[self.client_obj.code, 999999])
        self.assertEqual(self.browser(self.ops).post(url, "{}", content_type="application/json").status_code, 404)
        self.model.assert_not_called()

    def test_a_rate_blocked_message_is_not_translated_for_the_operation(self):
        InboundMessage.objects.filter(pk=self.heard.pk).update(is_rate_blocked=True)
        self.refused_unseen(self.translate(self.ops, self.heard))
        # The admin sees it in the thread, so may read it in Arabic.
        self.assertEqual(self.translate(self.admin, self.heard).status_code, 200)

    def test_an_email_is_not_a_message_of_the_chat(self):
        letter = InboundMessage.objects.create(client=self.client_obj, channel=Channel.EMAIL, body="A letter")
        self.refused_unseen(self.translate(self.ops, letter))

    def test_roles_that_do_not_answer_clients_reach_nothing(self):
        for person in (self.lead, self.tr, self.hr, self.reviewer, self.accounting):
            with self.subTest(role=person.role):
                self.assertIn(self.translate(person, self.heard).status_code, (403, 404))
        self.model.assert_not_called()
        self.assertEqual(self.translate(None, self.heard).status_code, 401)

    def test_only_a_post(self):
        self.assertEqual(self.translate(self.ops, self.heard, method="get").status_code, 405)
        self.model.assert_not_called()


class TranslateRefusalTests(_Translate):
    def assertRefused(self, answer, status, code):
        self.assertEqual(answer.status_code, status)
        self.assertEqual(_json(answer), {"ok": False, "error": code})
        self.heard.refresh_from_db()
        self.assertEqual(self.heard.translation_ar, "")

    def test_off_in_the_settings(self):
        AppSettings.objects.update(chat_translate_enabled=False)
        self.assertRefused(self.translate(self.ops, self.heard), 503, "unavailable")
        self.model.assert_not_called()

    def test_off_by_default(self):
        AppSettings.objects.all().delete()
        AppSettings.objects.create(claude_api_key="a-test-key-not-a-real-one")
        self.assertIs(translate.available(), False)

    def test_no_key_saved(self):
        AppSettings.objects.update(claude_api_key="")
        self.assertRefused(self.translate(self.ops, self.heard), 503, "unavailable")
        self.model.assert_not_called()

    def test_the_call_broke(self):
        self.model.side_effect = OSError("the provider said something with the key in it")
        self.assertRefused(self.translate(self.ops, self.heard), 503, "unavailable")

    def test_an_empty_answer_is_not_kept(self):
        self.model.return_value = _answer("   ")
        self.assertRefused(self.translate(self.ops, self.heard), 503, "unavailable")

    def test_a_message_with_no_words(self):
        InboundMessage.objects.filter(pk=self.heard.pk).update(body="[image]")
        self.assertRefused(self.translate(self.ops, self.heard), 400, "empty")
        self.model.assert_not_called()

    def test_too_many_in_a_minute(self):
        others = [
            InboundMessage.objects.create(client=self.client_obj, channel=Channel.WHATSAPP, body=f"Hello {n}")
            for n in range(2)
        ]
        with mock.patch.object(translate, "NEW_PER_MINUTE", 2):
            for message in others:
                self.assertEqual(self.translate(self.ops, message).status_code, 200)
            self.assertRefused(self.translate(self.ops, self.heard), 429, "too_fast")
            # One already kept is free.
            self.assertEqual(self.translate(self.ops, others[0]).status_code, 200)
        self.assertEqual(self.model.call_count, 2)


class TranslateOfferTests(_Translate):
    def fetch(self, user):
        url = reverse("dashboard:v1_client_messages", args=[self.client_obj.code])
        return _json(self.browser(user).get(url))

    def test_the_open_conversation_says_whether_it_is_offered(self):
        self.assertIs(self.fetch(self.ops)["client"]["translate"], True)
        AppSettings.objects.update(claude_api_key="")
        self.assertIs(self.fetch(self.ops)["client"]["translate"], False)
        AppSettings.objects.update(claude_api_key="a-test-key-not-a-real-one", chat_translate_enabled=False)
        self.assertIs(self.fetch(self.ops)["client"]["translate"], False)

    def test_the_admin_turns_it_on_and_off_from_the_settings(self):
        save = reverse("dashboard:v1_admin_settings_save")
        for on in (False, True):
            answer = self.browser(self.admin).post(save, json.dumps({"values": {"chat_translate_enabled": on}}), content_type="application/json")
            self.assertEqual(answer.status_code, 200, answer.content)
            self.assertIs(AppSettings.load().chat_translate_enabled, on)
            self.assertIs(self.fetch(self.ops)["client"]["translate"], on)
        # It is on the settings page, in the AI section.
        page = self.browser(self.admin).get(reverse("dashboard:v1_admin_settings")).content.decode("utf-8")
        self.assertIn("chat_translate_enabled", page)

    def test_nobody_else_can_turn_it_on(self):
        AppSettings.objects.update(chat_translate_enabled=False)
        save = reverse("dashboard:v1_admin_settings_save")
        for person in (self.ops, self.sales, self.lead):
            answer = self.browser(person).post(save, json.dumps({"values": {"chat_translate_enabled": True}}), content_type="application/json")
            self.assertEqual(answer.status_code, 403)
        self.assertIs(AppSettings.load().chat_translate_enabled, False)

    def test_the_answer_to_a_send_keeps_it(self):
        body = _json(self.to_client(self.ops, body="Hello"))
        self.assertIs(body["client"]["translate"], True)

    def test_the_lists_do_not_carry_it(self):
        answer = self.browser(self.ops).get(reverse("dashboard:v1_chats"), {"type": "clients"})
        self.assertEqual(answer.status_code, 200)
        self.assertIn(self.client_obj.code, answer.content.decode("utf-8"))
        self.assertNotIn(json.dumps("translate"), answer.content.decode("utf-8"))
