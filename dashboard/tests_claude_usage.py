"""What the product spends at Claude, counted from each answer's ``usage`` (``claude_usage.py``).

What these tests hold: a model is priced by its name, date suffix or not, and the longest name wins; a call's price is its four
kinds of token at the model's rates; every place the product calls Claude (the AI check, a client's message translated, the AI
translation, the help assistant) writes one row under its own name; the streamed translation is counted from its events,
cut short or not; nothing but counts is kept; and writing the row never costs the caller its answer.
"""

import json
from decimal import Decimal
from unittest import mock

from django.test import TestCase

from . import ai, ai_translate, claude_usage, helpbot, translate
from .models import AppSettings, ClaudeUsage

USAGE = {"input_tokens": 1000, "output_tokens": 500, "cache_creation_input_tokens": 0, "cache_read_input_tokens": 0}


class _Answer:
    def __init__(self, body):
        self.body = body

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False

    def read(self):
        return json.dumps(self.body).encode()


def _stream(*events):
    response = mock.MagicMock()
    response.__enter__.return_value = iter([f"data: {json.dumps(event)}\n".encode() for event in events])
    return response


class PriceTests(TestCase):
    def test_a_model_is_priced_by_its_name_with_or_without_a_date(self):
        self.assertEqual(claude_usage.price_of("claude-sonnet-4-5"), (3, 15, 0.30))
        self.assertEqual(claude_usage.price_of("claude-sonnet-4-5-20250929"), (3, 15, 0.30))
        self.assertEqual(claude_usage.price_of("CLAUDE-OPUS-5-5"), (4, 20, 0.20))

    def test_the_longest_name_wins(self):
        self.assertEqual(claude_usage.price_of("claude-opus-5-5"), (4, 20, 0.20))
        self.assertEqual(claude_usage.price_of("claude-opus-5"), (5, 25, 0.50))
        self.assertEqual(claude_usage.price_of("claude-sonnet-5-5"), (2, 10, 0.20))

    def test_a_model_not_in_the_table_has_no_price(self):
        self.assertIsNone(claude_usage.price_of("claude-unknown-9"))
        self.assertIsNone(claude_usage.price_of(""))
        self.assertIsNone(claude_usage.cost_of("claude-unknown-9", 1000, 1000, 0, 0))

    def test_a_call_is_its_four_kinds_of_token_at_the_model_rates(self):
        # Sonnet 4.5: 1M in = $3, 1M out = $15, a cache write 1.25 x $3, a cache read $0.30.
        self.assertEqual(claude_usage.cost_of("claude-sonnet-4-5", 1_000_000, 0, 0, 0), Decimal("3"))
        self.assertEqual(claude_usage.cost_of("claude-sonnet-4-5", 0, 1_000_000, 0, 0), Decimal("15"))
        self.assertEqual(claude_usage.cost_of("claude-sonnet-4-5", 0, 0, 1_000_000, 0), Decimal("3.75"))
        self.assertEqual(claude_usage.cost_of("claude-sonnet-4-5", 0, 0, 0, 1_000_000), Decimal("0.3"))
        self.assertEqual(claude_usage.cost_of("claude-sonnet-4-5", 1000, 500, 0, 0), Decimal("0.0105"))


class RecordTests(TestCase):
    def test_a_row_is_counts_only(self):
        row = claude_usage.record("check", "claude-sonnet-4-5", {**USAGE, "cache_read_input_tokens": 200})
        self.assertEqual(
            (row.feature, row.model, row.input_tokens, row.output_tokens, row.cache_write_tokens, row.cache_read_tokens),
            ("check", "claude-sonnet-4-5", 1000, 500, 0, 200),
        )
        self.assertEqual(row.cost_usd, Decimal("0.010560"))
        fields = {field.name for field in ClaudeUsage._meta.get_fields()}
        self.assertEqual(fields, {
            "id", "created_at", "feature", "model", "input_tokens", "output_tokens", "cache_write_tokens", "cache_read_tokens",
            "cost_usd",
        })

    def test_an_answer_with_no_usage_writes_nothing(self):
        self.assertIsNone(claude_usage.record("check", "claude-sonnet-4-5", None))
        self.assertIsNone(claude_usage.record("check", "claude-sonnet-4-5", {"input_tokens": "x"}))
        self.assertFalse(ClaudeUsage.objects.exists())

    def test_an_unpriced_model_is_kept_with_no_price(self):
        row = claude_usage.record("check", "claude-unknown-9", USAGE)
        self.assertIsNone(row.cost_usd)

    def test_a_failure_to_write_never_reaches_the_caller(self):
        with mock.patch.object(claude_usage, "cost_of", side_effect=RuntimeError("database down")):
            with mock.patch.object(claude_usage, "log") as logged:
                self.assertIsNone(claude_usage.record("check", "claude-sonnet-4-5", USAGE))
        self.assertTrue(logged.exception.called)


class CallSiteTests(TestCase):
    def setUp(self):
        AppSettings._cached = None
        conf = AppSettings.load()
        conf.claude_api_key = "sk-test-key-1234567890"
        conf.claude_model = "claude-sonnet-4-5"
        conf.save()
        self.conf = AppSettings.load()

    def answer(self, text="{}"):
        return _Answer({"model": "claude-sonnet-4-5-20250929", "content": [{"type": "text", "text": text}], "usage": USAGE})

    def test_the_ai_check_writes_a_row(self):
        with mock.patch.object(ai.net, "urlopen", return_value=self.answer()):
            ai._call_claude(self.conf, "prompt")
        row = ClaudeUsage.objects.get()
        self.assertEqual((row.feature, row.model, row.input_tokens, row.output_tokens), ("check", "claude-sonnet-4-5-20250929", 1000, 500))

    def test_a_translated_client_message_is_written_as_translate(self):
        with mock.patch.object(ai.net, "urlopen", return_value=self.answer("hello")):
            ai._post(self.conf, translate.SYSTEM_PROMPT, "<message>x</message>", None, translate.MAX_TOKENS, feature="translate")
        self.assertEqual(ClaudeUsage.objects.get().feature, "translate")

    def test_translating_a_message_on_the_chat_is_written_as_translate(self):
        message = mock.MagicMock(translation_ar="", pk=1)
        with mock.patch.object(translate, "words_of", return_value="Bonjour"), \
                mock.patch.object(translate, "available", return_value=True), \
                mock.patch.object(translate, "_too_fast", return_value=False), \
                mock.patch.object(ai.net, "urlopen", return_value=self.answer("مرحبا")):
            self.assertEqual(translate.to_arabic(message, None), "مرحبا")
        self.assertEqual(ClaudeUsage.objects.get().feature, "translate")

    def test_the_help_assistant_writes_a_row(self):
        with mock.patch.object(helpbot.net, "urlopen", return_value=self.answer()):
            helpbot._call_claude(self.conf, "SYSTEM", "CONTEXT", [{"role": "user", "content": "q"}])
        self.assertEqual(ClaudeUsage.objects.get().feature, "helpbot")

    def test_the_streamed_translation_is_counted_from_its_events(self):
        response = _stream(
            {"type": "message_start", "message": {"model": "claude-sonnet-4-5-20250929", "usage": {
                "input_tokens": 2000, "cache_creation_input_tokens": 0, "cache_read_input_tokens": 0, "output_tokens": 1}}},
            {"type": "content_block_delta", "delta": {"type": "text_delta", "text": "hi"}},
            {"type": "message_delta", "delta": {"stop_reason": "end_turn"}, "usage": {"output_tokens": 800}},
        )
        with mock.patch.object(ai_translate.net, "urlopen", return_value=response):
            ai_translate.stream_text(self.conf, "s", "p", [])
        row = ClaudeUsage.objects.get()
        self.assertEqual((row.feature, row.input_tokens, row.output_tokens), ("ai_translate", 2000, 800))
        self.assertEqual(row.cost_usd, claude_usage.cost_of("claude-sonnet-4-5", 2000, 800, 0, 0))

    def test_a_stream_cut_short_is_still_counted(self):
        response = _stream(
            {"type": "message_start", "message": {"usage": {"input_tokens": 2000, "output_tokens": 1}}},
            {"type": "error", "error": {"type": "overloaded_error"}},
        )
        with mock.patch.object(ai_translate.net, "urlopen", return_value=response):
            with self.assertRaises(RuntimeError):
                ai_translate.stream_text(self.conf, "s", "p", [])
        row = ClaudeUsage.objects.get()
        self.assertEqual((row.feature, row.model, row.input_tokens), ("ai_translate", "claude-sonnet-4-5", 2000))

    def test_a_failing_row_leaves_the_answer(self):
        with mock.patch.object(claude_usage, "cost_of", side_effect=RuntimeError("database down")):
            with mock.patch.object(ai.net, "urlopen", return_value=self.answer('{"ok": 1}')), mock.patch.object(claude_usage, "log"):
                self.assertEqual(ai._call_claude(self.conf, "prompt"), '{"ok": 1}')
        self.assertFalse(ClaudeUsage.objects.exists())
