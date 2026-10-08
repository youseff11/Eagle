"""The team leader gives each translator a share of the task: the pair, the words and - when several translate - the pages (07/10/2026).

What these tests hold, in the order the work goes:

- the leader has to say the language pair and the words for every translator, even one; the translator types none of it;
- a task can go to several translators at once, each with pages that do not overlap; each answers for their own share only
  (a refusal or a time-out sends back that share, not the task), and a share can be added while the others are being translated;
- each hands their own part in; the task goes to review when the last has;
- the translators read their own share and their own files, never a colleague's;
- the month's production is each translator's own words on the day they handed in, and the early finisher is not late
  because the last one was;
- the AI check runs once for each translator, on their own files and their own share, and its notes cost that translator the stars.
"""

import json
from datetime import timedelta
from unittest import mock

from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import Client as DjangoClient
from django.db import connection
from django.test import TestCase, TransactionTestCase
from django.test.utils import CaptureQueriesContext
from django.urls import reverse
from django.utils import timezone

from . import ai, api, payroll, performance, services
from .models import (
    Assignment, AssignmentStatus, ChatMessage, Client, Notification, RatingEvent, Role, TaskStatus, User, translator_holdings,
)
from .tests import hand_in_translation

URL = "dashboard:api_assign_translator"


def _json(response):
    return json.loads(response.content.decode("utf-8"))


def _file(name="out.txt"):
    return SimpleUploadedFile(name, b"translated", content_type="text/plain")


class _Fixture:
    """A task the leader has accepted, a team of three translators, and one more translator who is somebody else's."""

    def setUp(self):
        make = lambda name, role, **kw: User.objects.create_user(name, password="x", role=role, **kw)
        self.ops = make("ops_sp", Role.OPERATION)
        self.lead = make("lead_sp", Role.TEAM_LEAD)
        self.other_lead = make("lead_sp_two", Role.TEAM_LEAD)
        self.admin = make("admin_sp", Role.ADMIN)
        self.a = make("tr_sp_a", Role.TRANSLATOR, team_lead=self.lead)
        self.b = make("tr_sp_b", Role.TRANSLATOR, team_lead=self.lead)
        self.c = make("tr_sp_c", Role.TRANSLATOR, team_lead=self.lead)
        self.stranger = make("tr_sp_x", Role.TRANSLATOR, team_lead=self.other_lead)
        self.acme = Client.objects.create(name="ACME Secret Ltd", phone="+201000000091")
        self.due = timezone.now() + timedelta(days=3)
        self.task = services.create_task(
            client=self.acme, title="Big contract", created_by=self.ops, deadline=self.due, source_lang="EN", target_lang="AR",
        )
        services.accept_assignment(services.assign_to_lead(self.task, self.lead, self.ops), self.lead)
        self.task.refresh_from_db()

    # -- doors -----------------------------------------------------------------------------------------------
    def part(self, who, **over):
        return {"translator": who.pk, "source_lang": "EN", "target_lang": "AR", "words": "500", "page_from": "", "page_to": "", **over}

    def post(self, parts, user=None, task=None, **extra):
        data = {"parts": json.dumps(parts), "tdeadline_mode": "same", **extra}
        browser = DjangoClient()
        browser.force_login(user or self.lead)
        return browser.post(reverse(URL, args=[(task or self.task).code]), data)

    def get(self, user, name, *args):
        browser = DjangoClient()
        browser.force_login(user)
        return browser.get(reverse(name, args=list(args)))

    def fresh(self):
        self.task.refresh_from_db()
        return self.task

    def shares(self, status=None):
        rows = Assignment.objects.filter(task=self.task, target_role=Role.TRANSLATOR).order_by("id")
        return list(rows.filter(status=status) if status else rows)

    def of(self, who, status=None):
        return next((a for a in self.shares(status) if a.assignee_id == who.pk), None)

    def split(self, *who, take=True):
        """Give pages 1-10, 11-20, ... to each, and let them accept."""
        parts = [self.part(person, words=str(100 * (n + 1)), page_from=str(10 * n + 1), page_to=str(10 * n + 10)) for n, person in enumerate(who)]
        self.assertEqual(self.post(parts).status_code, 200)
        if take:
            for person in who:
                services.accept_assignment(self.of(person), person)
        return self.fresh()


class _Split(_Fixture, TestCase):
    pass


class _SplitTx(_Fixture, TransactionTestCase):
    """The same, outside the transaction a TestCase wraps around everything: for the tests that look at transactions."""


class SingleTranslatorSaysWhatTests(_Split):
    """Even for one translator the leader says the pair and the words."""

    def test_the_pair_and_the_words_are_asked_every_time_and_nothing_goes_out_without_them(self):
        for bad in (
            {"source_lang": ""}, {"target_lang": ""}, {"source_lang": "  ", "target_lang": ""},
            {"words": ""}, {"words": "0"}, {"words": "-5"}, {"words": "12x"}, {"words": "1.5"},
        ):
            answer = self.post([self.part(self.a, **bad)])
            self.assertEqual(answer.status_code, 400, bad)
            self.assertFalse(_json(answer)["ok"])
        self.assertEqual(self.shares(), [])
        self.assertEqual(self.fresh().status, TaskStatus.LEAD_ACCEPTED)
        self.assertIsNone(self.fresh().translator_id)

    def test_each_refusal_says_what_is_missing(self):
        self.assertEqual(_json(self.post([self.part(self.a, source_lang="")]))["code"], "need_languages")
        self.assertEqual(_json(self.post([self.part(self.a, words="")]))["code"], "need_words")

    def test_what_he_said_is_kept_on_the_hand_off_and_the_language_is_read_as_a_code(self):
        answer = self.post([self.part(self.a, source_lang="english", target_lang="الفرنسية", words="1,5")], )
        self.assertEqual(answer.status_code, 400)
        answer = self.post([self.part(self.a, source_lang="english", target_lang="الفرنسية", words="1500")])
        self.assertEqual(answer.status_code, 200)
        share = self.of(self.a)
        self.assertEqual((share.source_lang, share.target_lang, share.words), ("EN", "FR", 1500))
        self.assertIsNone(share.page_from)
        self.assertEqual(self.fresh().translator_id, self.a.pk)

    def test_the_flat_boxes_of_one_translator_do_the_same_as_the_list(self):
        browser = DjangoClient()
        browser.force_login(self.lead)
        answer = browser.post(reverse(URL, args=[self.task.code]), {
            "user": self.a.pk, "source_lang": "EN", "target_lang": "AR", "words": "700", "tdeadline_mode": "same",
        })
        self.assertEqual(answer.status_code, 200)
        self.assertEqual(self.of(self.a).words, 700)
        # And the flat form is held to the same rules.
        answer = browser.post(reverse(URL, args=[self.task.code]), {"user": self.a.pk, "tdeadline_mode": "same"})
        self.assertEqual(answer.status_code, 400)

    def test_pages_are_optional_for_one_translator_but_whole_when_given(self):
        self.assertEqual(self.post([self.part(self.a, page_from="3", page_to="")]).status_code, 400)
        self.assertEqual(self.post([self.part(self.a, page_from="9", page_to="3")]).status_code, 400)
        self.assertEqual(self.post([self.part(self.a, page_from="0", page_to="3")]).status_code, 400)
        self.assertEqual(self.shares(), [])
        self.assertEqual(self.post([self.part(self.a, page_from="3", page_to="9")]).status_code, 200)
        share = self.of(self.a)
        self.assertEqual((share.page_from, share.page_to, share.pages_text), (3, 9, "3-9"))

    def test_the_translator_is_told_what_is_asked_of_them_in_the_card_the_chat_and_the_notice(self):
        self.post([self.part(self.a, words="1200", page_from="2", page_to="6")])
        share = self.of(self.a)
        pending = api._pending_json(share, self.a)
        self.assertEqual(
            pending["part"],
            {
                "source_lang": "EN", "target_lang": "AR", "words": 1200, "page_from": 2, "page_to": 6,
                "text_ar": "EN → AR · 1,200 كلمة · صفحات 2-6", "text_en": "EN → AR · 1,200 words · pages 2-6",
            },
        )
        door = _json(self.get(self.a, "dashboard:v1_assignment", share.pk))["assignment"]
        self.assertEqual(door["part"]["words"], 1200)
        chat = ChatMessage.objects.filter(is_system=True, system_key="handoff").latest("id").body
        self.assertIn("EN → AR · 1,200 كلمة · صفحات 2-6", chat)
        notice = Notification.objects.filter(user=self.a, title_en="New translation task").latest("id")
        self.assertIn("EN → AR · 1,200 كلمة · صفحات 2-6", notice.body_ar)

    def test_a_team_leaders_own_hand_off_carries_no_share(self):
        lead_offer = Assignment.objects.get(task=self.task, target_role=Role.TEAM_LEAD)
        self.assertIsNone(api._pending_json(lead_offer, self.lead)["part"])

    def test_the_first_share_settles_the_tasks_count_when_nobody_had_but_never_overwrites_one_that_was_settled(self):
        self.post([self.part(self.a, words="800")])
        task = self.fresh()
        self.assertEqual((task.word_count, task.word_count_state), (800, "confirmed"))
        # A count the operation settled stands, whatever the leader gives a translator.
        other = services.create_task(client=self.acme, title="Counted", created_by=self.ops, deadline=self.due)
        services.accept_assignment(services.assign_to_lead(other, self.lead, self.ops), self.lead)
        other.word_count, other.word_count_state = 3000, "confirmed"
        other.save(update_fields=["word_count", "word_count_state"])
        self.assertEqual(self.post([self.part(self.b, words="900")], task=other).status_code, 200)
        other.refresh_from_db()
        self.assertEqual(other.word_count, 3000)

    def test_the_operation_sending_it_straight_leaves_the_words_unsaid_and_the_tasks_own_count_stands(self):
        services.accept_assignment(services.assign_direct_to_translator(self.task, self.a, self.ops), self.a)
        share = self.of(self.a)
        self.assertEqual((share.source_lang, share.target_lang, share.words), ("EN", "AR", 0))
        self.assertFalse(share.has_part and share.words)

    def test_who_is_asked_before_what_so_a_wrong_name_is_a_wrong_name(self):
        browser = DjangoClient()
        browser.force_login(self.lead)
        gone = User.objects.create_user("tr_sp_gone", password="x", role=Role.TRANSLATOR, team_lead=self.lead, is_active=False)
        self.assertEqual(browser.post(reverse(URL, args=[self.task.code]), {"user": gone.pk}).status_code, 404)
        answer = self.post([self.part(self.stranger)])
        self.assertEqual((answer.status_code, _json(answer)["error"]), (403, "not_in_your_team"))
        self.assertEqual(self.shares(), [])

    def test_only_the_tasks_own_leader_and_the_admin_may(self):
        self.assertEqual(self.post([self.part(self.a)], user=self.other_lead).status_code, 404)
        self.assertEqual(self.post([self.part(self.a)], user=self.ops).status_code, 403)
        self.assertEqual(self.shares(), [])
        self.assertEqual(self.post([self.part(self.a)], user=self.admin).status_code, 200)


class SplitBetweenSeveralTests(_Split):
    def test_each_translator_gets_an_offer_of_their_own_and_the_task_waits_for_the_first_yes(self):
        task = self.split(self.a, self.b, take=False)
        shares = self.shares(AssignmentStatus.PENDING)
        self.assertEqual([(s.assignee_id, s.words, s.pages_text) for s in shares], [(self.a.pk, 100, "1-10"), (self.b.pk, 200, "11-20")])
        self.assertEqual((task.status, task.translator_id), (TaskStatus.AWAITING_TRANSLATOR, self.a.pk))
        for person in (self.a, self.b):
            self.assertTrue(Notification.objects.filter(user=person, title_en="New translation task").exists())

    def test_with_more_than_one_translator_the_pages_are_asked_of_each_and_must_not_touch(self):
        pair = [self.part(self.a, page_from="1", page_to="10"), self.part(self.b, page_from="", page_to="")]
        self.assertEqual(_json(self.post(pair))["code"], "need_pages")
        for second in (("10", "15"), ("5", "8"), ("1", "10"), ("9", "12")):
            answer = self.post([self.part(self.a, page_from="1", page_to="10"), self.part(self.b, page_from=second[0], page_to=second[1])])
            self.assertEqual(_json(answer)["code"], "overlap", second)
        self.assertEqual(self.shares(), [])
        ok = self.post([self.part(self.a, page_from="1", page_to="10"), self.part(self.b, page_from="11", page_to="11")])
        self.assertEqual(ok.status_code, 200)

    def test_one_translator_cannot_be_given_two_shares_and_the_team_is_the_limit(self):
        twice = [self.part(self.a, page_from="1", page_to="5"), self.part(self.a, page_from="6", page_to="9")]
        self.assertEqual(_json(self.post(twice))["code"], "duplicate")
        many = [self.part(self.a, page_from=str(n), page_to=str(n)) for n in range(1, services.MAX_PARTS + 2)]
        self.assertEqual(_json(self.post(many))["code"], "too_many")
        self.assertEqual(self.shares(), [])

    def test_one_stranger_in_the_list_sends_none_of_it(self):
        answer = self.post([self.part(self.a, page_from="1", page_to="5"), self.part(self.stranger, page_from="6", page_to="9")])
        self.assertEqual((answer.status_code, _json(answer)["error"]), (403, "not_in_your_team"))
        self.assertEqual(self.shares(), [])

    def test_the_list_must_be_a_list_of_shares(self):
        for body in ("not json", "[]", "{}", "[1, 2]", '{"translator": 1}'):
            browser = DjangoClient()
            browser.force_login(self.lead)
            answer = browser.post(reverse(URL, args=[self.task.code]), {"parts": body, "tdeadline_mode": "same"})
            self.assertEqual(answer.status_code, 400, body)
        self.assertEqual(self.shares(), [])

    def test_the_date_is_one_choice_for_all_of_them(self):
        parts = [self.part(self.a, page_from="1", page_to="5"), self.part(self.b, page_from="6", page_to="9")]
        self.assertEqual(self.post(parts, tdeadline_mode="shorter", tdeadline_days="1").status_code, 200)
        task = self.fresh()
        self.assertIsNotNone(task.translator_deadline)
        self.assertEqual(task.deadline_for(self.a), task.deadline_for(self.b))
        self.assertEqual(task.deadline_for(self.lead), self.due)

    # -- each answers for their own share -------------------------------------------------------------------------
    def test_the_first_yes_starts_the_work_and_the_others_join_as_they_answer(self):
        self.split(self.a, self.b, take=False)
        services.accept_assignment(self.of(self.a), self.a)
        task = self.fresh()
        self.assertEqual(task.status, TaskStatus.IN_PROGRESS)
        first = task.translator_accepted_at
        self.assertIsNotNone(first)
        self.assertEqual(self.of(self.b).status, AssignmentStatus.PENDING)
        services.accept_assignment(self.of(self.b), self.b)
        task = self.fresh()
        self.assertEqual(task.status, TaskStatus.IN_PROGRESS)
        self.assertEqual(task.translator_accepted_at, first)
        self.assertEqual({s.assignee_id for s in self.shares(AssignmentStatus.ACCEPTED)}, {self.a.pk, self.b.pk})

    def test_one_who_declines_sends_back_their_share_only(self):
        self.split(self.a, self.b, take=False)
        services.accept_assignment(self.of(self.a), self.a)
        ok, _ = services.decline_assignment(self.of(self.b), self.b, "busy")
        self.assertTrue(ok)
        task = self.fresh()
        self.assertEqual((task.status, task.translator_id), (TaskStatus.IN_PROGRESS, self.a.pk))
        self.assertEqual(self.of(self.a).status, AssignmentStatus.ACCEPTED)
        self.assertTrue(Notification.objects.filter(user=self.lead, title_en="Assignment declined").exists())

    def test_the_task_goes_back_to_the_leader_only_when_nobody_has_a_share_left(self):
        self.split(self.a, self.b, take=False)
        services.decline_assignment(self.of(self.a), self.a, "no")
        task = self.fresh()
        # B is still deciding, and is now the translator on it.
        self.assertEqual((task.status, task.translator_id), (TaskStatus.AWAITING_TRANSLATOR, self.b.pk))
        services.decline_assignment(self.of(self.b), self.b, "no")
        task = self.fresh()
        self.assertEqual((task.status, task.translator_id), (TaskStatus.LEAD_ACCEPTED, None))

    def test_the_primary_translator_stepping_out_hands_the_name_to_whoever_is_left(self):
        self.split(self.a, self.b, take=False)
        services.accept_assignment(self.of(self.b), self.b)
        services.decline_assignment(self.of(self.a), self.a, "no")
        self.assertEqual(self.fresh().translator_id, self.b.pk)
        # And the one who stepped out can no longer open it.
        self.assertEqual(self.get(self.a, "dashboard:v1_translator_task", self.task.code).status_code, 404)

    def test_a_time_out_costs_that_translator_and_not_the_others(self):
        self.split(self.a, self.b, take=False)
        services.accept_assignment(self.of(self.a), self.a)
        Assignment.objects.filter(pk=self.of(self.b).pk).update(expires_at=timezone.now() - timedelta(seconds=1))
        services.expire_assignment(Assignment.objects.get(pk=self.of(self.b).pk))
        self.assertEqual(RatingEvent.objects.filter(user=self.b).count(), 1)
        self.assertEqual(RatingEvent.objects.filter(user=self.a).count(), 0)
        task = self.fresh()
        self.assertEqual((task.status, task.translator_id), (TaskStatus.IN_PROGRESS, self.a.pk))
        self.assertTrue(Notification.objects.filter(user=self.lead, title_en="Translator did not respond").exists())

    def test_a_share_that_fell_through_is_given_to_somebody_else_while_the_rest_is_being_translated(self):
        self.split(self.a, self.b, take=False)
        services.accept_assignment(self.of(self.a), self.a)
        services.decline_assignment(self.of(self.b), self.b, "no")
        again = self.post([self.part(self.c, words="200", page_from="11", page_to="20")])
        self.assertEqual(again.status_code, 200)
        task = self.fresh()
        self.assertEqual(task.status, TaskStatus.IN_PROGRESS)
        self.assertEqual(self.of(self.a).status, AssignmentStatus.ACCEPTED)
        self.assertEqual(self.of(self.c).status, AssignmentStatus.PENDING)
        services.accept_assignment(self.of(self.c), self.c)
        self.assertEqual({s.assignee_id for s in self.shares(AssignmentStatus.ACCEPTED)}, {self.a.pk, self.c.pk})

    def test_a_new_send_replaces_the_offers_nobody_answered_and_leaves_the_shares_taken(self):
        self.split(self.a, self.b, take=False)
        services.accept_assignment(self.of(self.a), self.a)
        pending_b = self.of(self.b)
        self.assertEqual(self.post([self.part(self.c, words="50", page_from="21", page_to="30")]).status_code, 200)
        self.assertEqual(Assignment.objects.get(pk=pending_b.pk).status, AssignmentStatus.CANCELLED)
        self.assertEqual(self.of(self.a).status, AssignmentStatus.ACCEPTED)
        self.assertEqual(self.of(self.c).status, AssignmentStatus.PENDING)
        # The cancelled offer is not a job any more.
        ok, why = services.accept_assignment(Assignment.objects.get(pk=pending_b.pk), self.b)
        self.assertEqual((ok, why), (False, "cancelled"))

    def test_a_translator_who_already_holds_a_share_is_not_given_another_and_cannot_clash_with_it(self):
        self.split(self.a, take=True)
        again = self.post([self.part(self.a, page_from="30", page_to="40")])
        self.assertEqual(_json(again)["code"], "already_has_part")
        clash = self.post([self.part(self.b, page_from="5", page_to="12")])
        self.assertEqual(_json(clash)["code"], "overlap")
        fine = self.post([self.part(self.b, page_from="11", page_to="12")])
        self.assertEqual(fine.status_code, 200)

    def test_adding_to_a_task_with_one_translator_asks_pages_of_the_new_one_at_once(self):
        self.assertEqual(self.post([self.part(self.a)]).status_code, 200)
        services.accept_assignment(self.of(self.a), self.a)
        self.assertEqual(_json(self.post([self.part(self.b)]))["code"], "need_pages")
        self.assertEqual(self.post([self.part(self.b, page_from="1", page_to="4")]).status_code, 200)

    def test_a_task_under_review_takes_no_more_translators(self):
        self.split(self.a, take=True)
        hand_in_translation(self.task, self.a)
        self.assertEqual(self.fresh().status, TaskStatus.UNDER_REVIEW)
        self.assertEqual(self.post([self.part(self.b, page_from="30", page_to="31")]).status_code, 400)


class HandInTests(_Split):
    def setUp(self):
        super().setUp()
        self.split(self.a, self.b)

    def test_the_first_to_finish_does_not_send_the_task_to_review(self):
        self.assertTrue(hand_in_translation(self.task, self.a))
        task = self.fresh()
        self.assertEqual(task.status, TaskStatus.IN_PROGRESS)
        self.assertIsNone(task.translated_at)
        self.assertIsNotNone(self.of(self.a).done_at)
        self.assertIsNone(self.of(self.b).done_at)
        note = Notification.objects.filter(user=self.lead, title_en="A translator handed in their part").latest("id")
        self.assertIn("اتسلّم 1 من 2", note.body_ar)

    def test_the_last_one_sends_it_to_review(self):
        hand_in_translation(self.task, self.a)
        hand_in_translation(self.task, self.b)
        task = self.fresh()
        self.assertEqual(task.status, TaskStatus.UNDER_REVIEW)
        self.assertIsNotNone(task.translated_at)
        self.assertEqual(len(services.translator_files(task)), 2)

    def test_it_waits_for_an_offer_not_yet_answered_as_well(self):
        self.assertEqual(self.post([self.part(self.c, page_from="21", page_to="30")]).status_code, 200)
        hand_in_translation(self.task, self.a)
        hand_in_translation(self.task, self.b)
        self.assertEqual(self.fresh().status, TaskStatus.IN_PROGRESS)
        services.accept_assignment(self.of(self.c), self.c)
        hand_in_translation(self.task, self.c)
        self.assertEqual(self.fresh().status, TaskStatus.UNDER_REVIEW)

    def test_each_is_held_to_their_own_file_not_a_colleagues(self):
        services.upload_translation(self.task, self.a, [_file("a.txt")])
        self.assertFalse(services.translation_missing(self.task))
        self.assertFalse(services.translation_missing(self.task, self.a))
        self.assertTrue(services.translation_missing(self.task, self.b))
        self.assertFalse(services.mark_translated(self.task, self.b))
        self.assertIsNone(self.of(self.b).done_at)
        self.assertEqual(self.fresh().status, TaskStatus.IN_PROGRESS)

    def test_one_cannot_hand_in_twice_and_a_finished_translator_cannot_ask_for_more_time(self):
        hand_in_translation(self.task, self.a)
        self.assertFalse(services.mark_translated(self.task, self.a))
        self.assertFalse(services.extension_state(self.task, self.a)["extension_can_ask"])
        self.assertTrue(services.extension_state(self.task, self.b)["extension_can_ask"])

    def test_somebody_still_deciding_cannot_hand_anything_in(self):
        self.post([self.part(self.c, page_from="21", page_to="30")])
        message, error = services.upload_translation(self.task, self.c, [_file("c.txt")])
        self.assertEqual((message, error), (None, "forbidden"))
        self.assertFalse(services.mark_translated(self.task, self.c))
        self.assertEqual(services.handin_tasks_for(self.c, services.pair_room(self.lead, self.c)), [])

    def test_the_admin_closes_the_whole_translation(self):
        services.upload_translation(self.task, self.a, [_file("a.txt")])
        self.assertTrue(services.mark_translated(self.task, self.admin))
        self.assertEqual(self.fresh().status, TaskStatus.UNDER_REVIEW)
        self.assertTrue(all(share.done_at for share in self.shares(AssignmentStatus.ACCEPTED)))

    def test_a_send_back_opens_every_share_again_and_tells_every_translator(self):
        hand_in_translation(self.task, self.a)
        hand_in_translation(self.task, self.b)
        Notification.objects.all().delete()
        self.assertTrue(services.send_back_for_revision(self.task, self.lead, "check the numbers"))
        self.assertEqual(self.fresh().status, TaskStatus.IN_PROGRESS)
        self.assertTrue(all(share.done_at is None for share in self.shares(AssignmentStatus.ACCEPTED)))
        for person in (self.a, self.b):
            self.assertTrue(Notification.objects.filter(user=person, title_en="Your translation came back").exists())

    def test_a_translator_who_has_handed_in_is_free_while_the_other_is_still_busy(self):
        hand_in_translation(self.task, self.a)
        held = translator_holdings([self.a.pk, self.b.pk])
        self.assertNotIn(self.a.pk, held)
        self.assertEqual([t.pk for t in held[self.b.pk]], [self.task.pk])
        self.assertFalse(self.a.is_busy)
        self.assertTrue(self.b.is_busy)

    def test_the_board_counts_each_translators_share_as_theirs(self):
        rows = {row["person"].pk: row for row in services.translator_board(self.lead)}
        self.assertEqual((rows[self.a.pk]["load"], rows[self.b.pk]["load"], rows[self.c.pk]["load"]), (1, 1, 0))


class WhoSeesWhatTests(_Split):
    def setUp(self):
        super().setUp()
        self.split(self.a, self.b)
        services.upload_translation(self.task, self.a, [_file("from-a.txt")])
        services.upload_translation(self.task, self.b, [_file("from-b.txt")])

    def page(self, who):
        return _json(self.get(who, "dashboard:v1_translator_task", self.task.code))["task"]

    def test_both_translators_open_the_task_and_a_stranger_does_not(self):
        self.assertEqual(self.get(self.a, "dashboard:v1_translator_task", self.task.code).status_code, 200)
        self.assertEqual(self.get(self.b, "dashboard:v1_translator_task", self.task.code).status_code, 200)
        self.assertEqual(self.get(self.stranger, "dashboard:v1_translator_task", self.task.code).status_code, 404)
        self.assertEqual(self.get(self.c, "dashboard:v1_translator_task", self.task.code).status_code, 404)
        self.assertTrue(self.task.can_view(self.a) and self.task.can_view(self.b))
        self.assertFalse(self.task.can_view(self.c) or self.task.can_view(self.stranger))

    def test_each_reads_their_own_share_their_own_name_and_only_their_own_file(self):
        mine, theirs = self.page(self.a), self.page(self.b)
        self.assertEqual((mine["part"]["words"], mine["part"]["page_from"], mine["part"]["page_to"]), (100, 1, 10))
        self.assertEqual((theirs["part"]["words"], theirs["part"]["page_from"], theirs["part"]["page_to"]), (200, 11, 20))
        self.assertEqual(mine["people"]["translator"], self.a.short_name)
        self.assertEqual(theirs["people"]["translator"], self.b.short_name)
        self.assertEqual([f["name"] for f in mine["files"]["translation"]], ["from-a.txt"])
        self.assertEqual([f["name"] for f in theirs["files"]["translation"]], ["from-b.txt"])
        self.assertEqual((mine["source_lang"], mine["target_lang"]), ("EN", "AR"))

    def test_nothing_of_the_client_reaches_a_translator_on_a_shared_task(self):
        raw = self.get(self.a, "dashboard:v1_translator_task", self.task.code).content.decode("utf-8")
        for marker in ("ACME Secret", "201000000091"):
            self.assertNotIn(marker, raw)
        self.assertEqual(self.page(self.a)["client"], self.acme.code)

    def test_the_task_page_says_when_a_translator_has_handed_in(self):
        self.assertFalse(self.page(self.a)["handed_in"])
        services.mark_translated(self.task, self.a)
        page = self.page(self.a)
        self.assertTrue(page["handed_in"])
        self.assertFalse(page["can_upload"])
        self.assertTrue(page["under_review"])
        self.assertFalse(self.page(self.b)["handed_in"])
        self.assertTrue(self.page(self.b)["can_upload"])

    def test_a_translator_only_being_offered_it_reads_it_but_does_not_work_it(self):
        self.post([self.part(self.c, page_from="21", page_to="30")])
        page = self.page(self.c)
        self.assertTrue(page["mine"])
        self.assertFalse(page["can_upload"])
        self.assertEqual(page["part"]["page_from"], 21)

    def test_the_desk_shows_each_translators_own_pair_and_share(self):
        rows = _json(self.get(self.b, "dashboard:v1_translator_home"))["open"]
        self.assertEqual([r["code"] for r in rows], [self.task.code])
        self.assertEqual((rows[0]["part"]["words"], rows[0]["source_lang"], rows[0]["target_lang"]), (200, "EN", "AR"))

    def test_the_leader_and_the_operation_see_every_share_and_whose_file_is_whose(self):
        for who in (self.lead, self.ops):
            task = _json(self.get(who, "dashboard:v1_task", self.task.code))["task"]
            self.assertEqual([(p["name"], p["words"], p["page_from"], p["page_to"], p["status"]) for p in task["parts"]], [
                (self.a.short_name, 100, 1, 10, "accepted"), (self.b.short_name, 200, 11, 20, "accepted"),
            ])
            self.assertEqual({f["by"] for f in task["files"]["translation"]}, {self.a.short_name, self.b.short_name})

    def test_the_leader_reviews_the_files_of_everyone_and_the_operation_gets_them_all(self):
        services.mark_translated(self.task, self.a)
        services.mark_translated(self.task, self.b)
        self.assertEqual(sorted(f.original_name for f in services.final_files(self.fresh())), ["from-a.txt", "from-b.txt"])

    def test_the_translators_chat_with_the_leader_is_their_own_group(self):
        link_a = services.task_chat_link(self.fresh(), self.a)["url"]
        link_b = services.task_chat_link(self.fresh(), self.b)["url"]
        self.assertNotEqual(link_a, link_b)

    def test_a_file_dropped_in_the_leaders_group_is_tagged_to_the_task_for_either_translator(self):
        room = services.pair_room(self.lead, self.b)
        message = ChatMessage.objects.create(room=room, sender=self.b, body="")
        from .models import ChatAttachment

        ChatAttachment.objects.create(message=message, file=_file("late.txt"), original_name="late.txt", size=3)
        self.assertEqual(services.tag_task_message(message), self.task)


class DeadlinesAndExtensionsTests(_Split):
    def setUp(self):
        super().setUp()
        self.split(self.a, self.b)

    def test_changing_the_translators_date_tells_everyone_translating(self):
        Notification.objects.all().delete()
        ok, _ = services.set_translator_deadline(self.task, timezone.now() + timedelta(days=1), self.lead)
        self.assertTrue(ok)
        for person in (self.a, self.b):
            self.assertTrue(Notification.objects.filter(user=person, title_en="Deadline updated").exists())

    def test_the_sweep_warns_only_those_who_have_not_handed_in(self):
        services.set_translator_deadline(self.task, timezone.now() + timedelta(minutes=10), self.lead, tell_translator=False)
        hand_in_translation(self.task, self.a)
        Notification.objects.all().delete()
        services.sweep_deadlines()
        self.assertTrue(Notification.objects.filter(user=self.b, title_en="Deadline approaching").exists())
        self.assertFalse(Notification.objects.filter(user=self.a, title_en="Deadline approaching").exists())

    def test_either_can_ask_for_more_time_and_the_answer_goes_to_the_one_who_asked(self):
        services.set_translator_deadline(self.task, timezone.now() + timedelta(hours=5), self.lead, tell_translator=False)
        row, error = services.request_extension(self.task, self.b, 60, "long table")
        self.assertEqual(error, "")
        Notification.objects.all().delete()
        ok, _ = services.decide_extension(row, self.lead, True)
        self.assertTrue(ok)
        self.assertTrue(Notification.objects.filter(user=self.b, title_en="More time approved").exists())
        # The other translator is only told that their date moved.
        self.assertTrue(Notification.objects.filter(user=self.a, title_en="Deadline updated").exists())
        self.assertFalse(Notification.objects.filter(user=self.a, title_en="More time approved").exists())

    def test_a_stranger_cannot_ask_for_time_on_it(self):
        row, error = services.request_extension(self.task, self.c, 60, "")
        self.assertIsNone(row)
        self.assertTrue(error)


class ProductionTests(_Split):
    """Pay and performance follow the share, not the task."""

    def finish(self, person, at):
        hand_in_translation(self.task, person)
        Assignment.objects.filter(task=self.task, assignee=person).update(done_at=at)

    def month(self, moment):
        first = timezone.localtime(moment).date().replace(day=1)
        last = (first.replace(day=28) + timedelta(days=10)).replace(day=1) - timedelta(days=1)
        return first, last

    def test_each_translator_is_counted_for_their_own_words_on_the_day_they_handed_in(self):
        self.split(self.a, self.b)
        now = timezone.now()
        early, late = now - timedelta(days=40), now
        self.finish(self.a, early)
        self.finish(self.b, late)
        self.task.refresh_from_db()
        mine = payroll.production(self.a, *self.month(early))
        self.assertEqual([(done.task.pk, done.words, done.day) for done in mine], [(self.task.pk, 100, timezone.localtime(early).date())])
        theirs = payroll.production(self.b, *self.month(late))
        self.assertEqual([(done.task.pk, done.words) for done in theirs], [(self.task.pk, 200)])
        # Neither is counted in the other's month.
        self.assertEqual(payroll.production(self.a, *self.month(late)), [])
        self.assertEqual(payroll.production(self.b, *self.month(early)), [])

    def test_the_work_day_cache_gets_their_share_and_the_whole_job_is_not_counted_twice(self):
        self.split(self.a, self.b)
        hand_in_translation(self.task, self.a)
        hand_in_translation(self.task, self.b)
        Task_ = type(self.task)
        Task_.objects.filter(pk=self.task.pk).update(word_count=9999)
        today = timezone.localtime().date()
        payroll.refresh_words(self.a, today, today)
        payroll.refresh_words(self.b, today, today)
        from .models import WorkDay

        self.assertEqual(WorkDay.objects.get(user=self.a, date=today).words, 100)
        self.assertEqual(WorkDay.objects.get(user=self.b, date=today).words, 200)

    def test_a_job_given_whole_with_no_words_said_still_pays_on_the_tasks_own_count(self):
        task = services.create_task(client=self.acme, title="Whole", created_by=self.ops, deadline=self.due)
        services.accept_assignment(services.assign_to_lead(task, self.lead, self.ops), self.lead)
        services.accept_assignment(services.assign_direct_to_translator(task, self.c, self.ops), self.c)
        type(task).objects.filter(pk=task.pk).update(word_count=640, word_count_state="confirmed")
        hand_in_translation(task, self.c)
        today = timezone.localtime().date()
        rows = payroll.production(self.c, today, today)
        self.assertEqual([(done.task.pk, done.words) for done in rows], [(task.pk, 640)])

    def test_a_job_made_before_shares_existed_is_counted_as_it_always_was(self):
        from .models import Task

        legacy = Task.objects.create(
            client=self.acme, title="Old", created_by=self.ops, team_lead=self.lead, translator=self.c,
            status=TaskStatus.DELIVERED, translated_at=timezone.now(), word_count=777,
        )
        today = timezone.localtime().date()
        rows = payroll.production(self.c, today, today)
        self.assertEqual([(done.task.pk, done.words) for done in rows], [(legacy.pk, 777)])

    def test_a_cancelled_job_produced_nothing(self):
        self.split(self.a)
        hand_in_translation(self.task, self.a)
        type(self.task).objects.filter(pk=self.task.pk).update(status=TaskStatus.CANCELLED)
        today = timezone.localtime().date()
        self.assertEqual(payroll.production(self.a, today, today), [])

    def test_the_one_who_finished_early_is_not_late_because_the_last_one_was(self):
        self.split(self.a, self.b)
        due = timezone.now() + timedelta(hours=10)
        type(self.task).objects.filter(pk=self.task.pk).update(translator_deadline=due)
        self.finish(self.a, due - timedelta(hours=2))
        self.finish(self.b, due + timedelta(hours=2))
        self.task.refresh_from_db()
        today = timezone.localtime().date()
        first, last = today.replace(day=1), today.replace(day=28)
        a_late = performance.deadlines(self.a, first, last)
        b_late = performance.deadlines(self.b, first, last)
        self.assertEqual((a_late["total"], a_late["late"], a_late["score"]), (1, 0, 100))
        self.assertEqual((b_late["total"], b_late["late"], b_late["score"]), (1, 1, 0))

    def test_projects_count_once_for_each_translator_who_handed_a_share_in(self):
        self.split(self.a, self.b)
        hand_in_translation(self.task, self.a)
        hand_in_translation(self.task, self.b)
        today = timezone.localtime().date()
        first, last = today.replace(day=1), today.replace(day=28)
        self.assertEqual(performance.for_month(self.a, today.year, today.month)["projects"], 1)
        self.assertEqual(performance.for_month(self.b, today.year, today.month)["projects"], 1)
        counted = performance._projects_by_person([self.a.pk, self.b.pk, self.c.pk], first, last)
        self.assertEqual(counted, {self.a.pk: 1, self.b.pk: 1})


class SharedTaskTests(_Split):
    """What counts as a task shared between translators (``Task.is_split``)."""

    def test_one_translator_alone_with_no_pages_is_not_a_shared_task(self):
        self.assertEqual(self.post([self.part(self.a)]).status_code, 200)
        self.assertFalse(self.fresh().is_split)

    def test_a_share_that_fell_through_still_makes_it_a_shared_task(self):
        self.split(self.a, self.b, take=False)
        services.accept_assignment(self.of(self.a), self.a)
        services.decline_assignment(self.of(self.b), self.b, "no")
        # Only A is on it now, but B's pages are not in anybody's file.
        self.assertEqual(len(self.fresh().translator_ids()), 1)
        self.assertTrue(self.fresh().is_split)

    def test_one_translator_given_pages_is_a_partial_job_too(self):
        self.assertEqual(self.post([self.part(self.a, page_from="1", page_to="5")]).status_code, 200)
        self.assertTrue(self.fresh().is_split)

    def test_a_replaced_offer_with_pages_does_not_count(self):
        self.post([self.part(self.a, page_from="1", page_to="5")])
        self.assertEqual(self.post([self.part(self.b)]).status_code, 200)
        self.assertFalse(self.fresh().is_split)


class WhatOneTranslatorCannotReadOfAnotherTests(_Split):
    def setUp(self):
        super().setUp()
        self.split(self.a, self.b)

    def page(self, who):
        return _json(self.get(who, "dashboard:v1_translator_task", self.task.code))["task"]

    def test_a_request_for_more_time_and_its_answer_are_the_asking_translators_alone(self):
        services.set_translator_deadline(self.task, timezone.now() + timedelta(hours=5), self.lead, tell_translator=False)
        row, error = services.request_extension(self.task, self.a, 120, "my private reason AAA")
        self.assertEqual(error, "")
        theirs = self.page(self.b)["extension"]
        self.assertEqual((theirs["pending"], theirs["last"], theirs["can_ask"]), (None, None, True))
        self.assertEqual(self.page(self.a)["extension"]["pending"]["reason"], "my private reason AAA")
        services.decide_extension(row, self.lead, False, "note-to-A-only BBB")
        self.assertIsNone(self.page(self.b)["extension"]["last"])
        self.assertEqual(self.page(self.a)["extension"]["last"]["note"], "note-to-A-only BBB")
        for text in ("AAA", "BBB"):
            self.assertNotIn(text, self.get(self.b, "dashboard:v1_translator_task", self.task.code).content.decode("utf-8"))

    def test_each_translator_can_have_a_request_of_their_own_open(self):
        services.set_translator_deadline(self.task, timezone.now() + timedelta(hours=5), self.lead, tell_translator=False)
        self.assertIsNotNone(services.request_extension(self.task, self.a, 60, "")[0])
        self.assertIsNotNone(services.request_extension(self.task, self.b, 30, "")[0])
        row, error = services.request_extension(self.task, self.a, 60, "")
        self.assertIsNone(row)
        self.assertTrue(error)

    def test_the_leader_is_told_which_translator_asked(self):
        services.set_translator_deadline(self.task, timezone.now() + timedelta(hours=5), self.lead, tell_translator=False)
        services.request_extension(self.task, self.b, 30, "")
        extension = _json(self.get(self.lead, "dashboard:v1_task", self.task.code))["task"]["lead"]["extension"]
        self.assertEqual(extension["by"], self.b.short_name)

    def test_the_assignment_history_is_their_own_and_the_leaders_never_a_colleagues(self):
        rows = self.page(self.b)["history"]
        self.assertEqual(
            sorted((r["name"], r["role"]) for r in rows),
            sorted([(self.b.short_name, "translator"), (self.lead.short_name, "team_lead")]),
        )
        admin_rows = _json(self.get(self.admin, "dashboard:v1_translator_task", self.task.code))["task"]["history"]
        self.assertEqual(len(admin_rows), 3)

    def test_support_reads_who_is_on_it_and_where_each_stands_but_not_their_words_or_pages(self):
        support = User.objects.create_user("support_sp", password="x", role=Role.SUPPORT)
        parts = _json(self.get(support, "dashboard:v1_task", self.task.code))["task"]["parts"]
        self.assertEqual([p["name"] for p in parts], [self.a.short_name, self.b.short_name])
        for part in parts:
            self.assertEqual((part["words"], part["page_from"], part["page_to"], part["source_lang"], part["target_lang"]), (0, None, None, "", ""))
            self.assertEqual(part["status"], "accepted")

    def test_two_translators_sending_each_other_a_file_is_not_work_on_the_task(self):
        from .models import ChatAttachment

        room = services.pair_room(self.a, self.b)
        message = ChatMessage.objects.create(room=room, sender=self.a, body="")
        ChatAttachment.objects.create(message=message, file=_file("between.txt"), original_name="between.txt", size=3)
        self.assertIsNone(services.tag_task_message(message))
        message.refresh_from_db()
        self.assertIsNone(message.task_id)

    def test_the_leaders_corrected_file_of_a_shared_task_goes_to_the_operation_not_into_one_translators_group(self):
        hand_in_translation(self.task, self.a)
        hand_in_translation(self.task, self.b)
        message, error = services.upload_reviewed(self.task, self.lead, [_file("merged.docx")])
        self.assertEqual(error, "")
        self.assertEqual(message.room_id, services.pair_room(self.lead, self.ops).pk)


class FallingThroughTests(_Split):
    def test_a_late_yes_to_a_task_that_is_under_review_is_refused_and_the_task_stays_where_it_is(self):
        self.split(self.a, take=False)
        services.accept_assignment(self.of(self.a), self.a)
        self.assertEqual(self.post([self.part(self.b, page_from="11", page_to="20")]).status_code, 200)
        offer = self.of(self.b)
        message, error = services.upload_translation(self.fresh(), self.a, [_file("a.txt")])
        self.assertEqual(error, "")
        # The admin closes the whole translation while B is still deciding.
        self.assertTrue(services.mark_translated(self.fresh(), self.admin))
        self.assertEqual(self.fresh().status, TaskStatus.UNDER_REVIEW)
        self.assertEqual(Assignment.objects.get(pk=offer.pk).status, AssignmentStatus.CANCELLED)
        self.assertEqual(services.accept_assignment(Assignment.objects.get(pk=offer.pk), self.b), (False, "cancelled"))
        self.assertEqual(self.fresh().status, TaskStatus.UNDER_REVIEW)

    def test_an_offer_left_open_on_a_cancelled_or_delivered_task_cannot_be_taken(self):
        self.split(self.a, self.b, take=False)
        offer = self.of(self.a)
        type(self.task).objects.filter(pk=self.task.pk).update(status=TaskStatus.DELIVERED)
        self.assertEqual(services.accept_assignment(Assignment.objects.get(pk=offer.pk), self.a), (False, "cancelled"))
        self.assertEqual(self.fresh().status, TaskStatus.DELIVERED)

    def test_when_the_last_open_share_falls_through_after_the_rest_handed_in_the_leader_can_close_the_translation(self):
        self.split(self.a, self.b, take=False)
        services.accept_assignment(self.of(self.a), self.a)
        hand_in_translation(self.task, self.a)
        # B is still deciding: there is something to wait for.
        self.assertFalse(services.lead_may_close(self.fresh(), self.lead))
        services.decline_assignment(self.of(self.b), self.b, "no")
        task = self.fresh()
        # Nothing is left to wait for, and nobody who is done can hand in again.
        self.assertEqual(task.status, TaskStatus.IN_PROGRESS)
        self.assertFalse(services.mark_translated(task, self.a))
        self.assertTrue(services.lead_may_close(task, self.lead))
        self.assertFalse(services.lead_may_close(task, self.other_lead))
        self.assertFalse(services.lead_may_close(task, self.ops))
        self.assertFalse(services.lead_may_close(task, self.a))
        self.assertTrue(_json(self.get(self.lead, "dashboard:v1_task", self.task.code))["task"]["lead"]["can_close_translation"])
        browser = DjangoClient()
        browser.force_login(self.lead)
        answer = browser.post(f"/api/tasks/{self.task.code}/translated/")
        self.assertEqual(answer.status_code, 200)
        self.assertEqual(_json(answer)["status"], "under_review")

    def test_the_leader_cannot_close_it_while_a_share_is_still_out_or_being_decided(self):
        self.split(self.a, self.b)
        hand_in_translation(self.task, self.a)
        self.assertFalse(services.lead_may_close(self.fresh(), self.lead))
        self.assertFalse(services.mark_translated(self.fresh(), self.lead))
        browser = DjangoClient()
        browser.force_login(self.lead)
        self.assertEqual(browser.post(f"/api/tasks/{self.task.code}/translated/").status_code, 403)
        self.assertEqual(self.fresh().status, TaskStatus.IN_PROGRESS)
        # Nor with an offer waiting (B has taken their share, so give B's pages to C once B is out of the way).
        self.assertEqual(self.post([self.part(self.c, page_from="21", page_to="30")]).status_code, 200)
        self.assertFalse(services.lead_may_close(self.fresh(), self.lead))

    def test_cancelling_a_task_whose_first_offer_was_still_open_still_reaches_the_translator_who_had_said_yes(self):
        self.split(self.a, self.b, take=False)
        services.accept_assignment(self.of(self.b), self.b)
        Notification.objects.all().delete()
        self.assertTrue(services.cancel_task(self.task, self.ops, "client withdrew"))
        task = self.fresh()
        self.assertTrue(task.can_view(self.b))
        self.assertTrue(Notification.objects.filter(user=self.b, title_en="Task cancelled").exists())

    def test_adding_a_share_with_another_date_tells_the_translators_already_working(self):
        self.split(self.a, take=True)
        Notification.objects.all().delete()
        answer = self.post([self.part(self.b, page_from="11", page_to="20")], tdeadline_mode="shorter", tdeadline_days="1")
        self.assertEqual(answer.status_code, 200)
        self.assertTrue(Notification.objects.filter(user=self.a, title_en="Deadline updated").exists())
        # The new one reads it in their offer, not twice.
        self.assertFalse(Notification.objects.filter(user=self.b, title_en="Deadline updated").exists())

    def test_adding_a_share_on_the_same_date_says_nothing_new_to_the_others(self):
        self.split(self.a, take=True)
        Notification.objects.all().delete()
        self.post([self.part(self.b, page_from="11", page_to="20")])
        self.assertFalse(Notification.objects.filter(user=self.a, title_en="Deadline updated").exists())


class MalformedSharesTests(_Split):
    def test_a_language_that_is_not_text_or_is_too_long_is_refused_in_words_and_not_by_the_server_or_the_database(self):
        for bad in (["EN"], 5, {"x": 1}, True):
            answer = self.post([self.part(self.a, source_lang=bad)])
            self.assertEqual((answer.status_code, _json(answer)["code"]), (400, "need_languages"), bad)
        answer = self.post([self.part(self.a, target_lang="x" * 41)])
        self.assertEqual((answer.status_code, _json(answer)["code"]), (400, "bad_language"))
        self.assertEqual(self.shares(), [])

    def test_json_that_is_nested_beyond_reason_is_a_bad_request_not_a_crash(self):
        browser = DjangoClient()
        browser.force_login(self.lead)
        answer = browser.post(reverse(URL, args=[self.task.code]), {"parts": "[" * 200000, "tdeadline_mode": "same"})
        self.assertEqual(answer.status_code, 400)


class AnswersAtTheSameMomentTests(_SplitTx):
    """Translators answer one task at about the same moment: the locks are taken inside a transaction, the task's first (07/10/2026).

    SQLite ignores row locks, so what can be held here is the shape: every answer is one transaction, and the task row is locked
    before the assignment's. On Postgres a lock outside a transaction is an error, which is how a refusal once failed on the server.
    """

    def watch(self):
        """Record, for every lock taken, whether a transaction was open and which lock came first."""
        seen = []

        def spy(name, real):
            def wrapper(*args, **kwargs):
                seen.append((name, connection.in_atomic_block))
                return real(*args, **kwargs)

            return wrapper

        return seen, mock.patch.object(services, "_lock_task", spy("task", services._lock_task)), mock.patch.object(
            services, "_lock_assignment", spy("assignment", services._lock_assignment)
        )

    def test_accepting_declining_and_expiring_take_their_locks_in_a_transaction_task_first(self):
        self.split(self.a, self.b, self.c, take=False)
        seen, task_lock, assignment_lock = self.watch()
        with task_lock, assignment_lock:
            services.accept_assignment(self.of(self.a), self.a)
            services.decline_assignment(self.of(self.b), self.b, "no")
            Assignment.objects.filter(pk=self.of(self.c).pk).update(expires_at=timezone.now() - timedelta(seconds=1))
            services.expire_assignment(Assignment.objects.get(pk=self.of(self.c).pk))
        self.assertEqual([name for name, _ in seen], ["task", "assignment"] * 3)
        self.assertTrue(all(inside for _, inside in seen), seen)

    def test_handing_a_share_in_and_sending_a_batch_lock_the_task_inside_a_transaction(self):
        self.split(self.a, self.b)
        seen, task_lock, _ = self.watch()
        with task_lock:
            hand_in_translation(self.fresh(), self.a)
        # The hand-in alone took the task's lock, and inside a transaction.
        self.assertEqual(seen, [("task", True)])
        seen.clear()
        with task_lock:
            self.assertEqual(self.post([self.part(self.c, page_from="21", page_to="30")]).status_code, 200)
        self.assertEqual(seen, [("task", True)])

    def test_a_batch_that_would_give_a_translator_a_second_share_is_refused_under_the_lock_and_writes_nothing(self):
        self.split(self.a, take=True)
        before = Assignment.objects.count()
        parts = [services.Part(self.a, "EN", "AR", 50, 30, 40)]
        with self.assertRaises(services.PartError) as raised:
            services.assign_to_translators(self.fresh(), parts, self.lead)
        self.assertEqual(raised.exception.code, "already_has_part")
        self.assertEqual(Assignment.objects.count(), before)

    def test_the_review_check_starts_after_the_hand_in_is_committed_and_not_inside_it(self):
        self.split(self.a)
        started = []

        def start(task, translator=None, force=False):
            started.append(connection.in_atomic_block)

        with mock.patch.object(ai, "start_background_check", start):
            hand_in_translation(self.task, self.a)
        self.assertEqual(started, [False])
        self.assertEqual(self.fresh().status, TaskStatus.UNDER_REVIEW)


class AnswersNotLostTests(_Split):
    def test_a_batch_that_takes_back_an_offer_tells_whose_it_was(self):
        self.split(self.a, self.b, take=False)
        services.accept_assignment(self.of(self.a), self.a)
        Notification.objects.all().delete()
        self.assertEqual(self.post([self.part(self.c, page_from="21", page_to="30")]).status_code, 200)
        withdrawn = Notification.objects.filter(user=self.b, title_en="The offer was withdrawn")
        self.assertEqual(withdrawn.count(), 1)
        self.assertIn(self.task.code, withdrawn.get().body_ar)
        self.assertFalse(Notification.objects.filter(user=self.a, title_en="The offer was withdrawn").exists())

    def test_the_same_translator_offered_again_is_not_told_their_offer_was_withdrawn(self):
        self.split(self.a, self.b, take=False)
        Notification.objects.all().delete()
        self.assertEqual(self.post([self.part(self.a, page_from="1", page_to="10"), self.part(self.c, page_from="11", page_to="20")]).status_code, 200)
        self.assertTrue(Notification.objects.filter(user=self.b, title_en="The offer was withdrawn").exists())
        self.assertFalse(Notification.objects.filter(user=self.a, title_en="The offer was withdrawn").exists())

    def test_the_tasks_own_count_grows_with_the_shares_while_it_is_the_sum_of_them_and_never_over_a_number_a_person_settled(self):
        self.assertEqual(self.post([self.part(self.a, words="1000")]).status_code, 200)
        services.accept_assignment(self.of(self.a), self.a)
        self.assertEqual(self.fresh().word_count, 1000)
        self.assertEqual(self.post([self.part(self.b, words="500", page_from="11", page_to="20")]).status_code, 200)
        self.assertEqual(self.fresh().word_count, 1500)
        # A person settled it: the next share leaves it alone.
        type(self.task).objects.filter(pk=self.task.pk).update(word_count=4000)
        self.assertEqual(self.post([self.part(self.c, words="300", page_from="21", page_to="30")]).status_code, 200)
        self.assertEqual(self.fresh().word_count, 4000)

    def test_finished_with_no_file_of_their_own_is_said_in_words_even_when_a_colleague_has_uploaded(self):
        self.split(self.a, self.b)
        services.upload_translation(self.fresh(), self.a, [_file("a.txt")])
        browser = DjangoClient()
        browser.force_login(self.b)
        answer = browser.post(f"/api/tasks/{self.task.code}/translated/")
        self.assertEqual((answer.status_code, _json(answer)["code"]), (400, "no_translation_file"))
        self.assertIsNone(self.of(self.b).done_at)


class QueryCostTests(_Split):
    """A list or a page costs what it did however many translators and tasks are on it."""

    def queries(self, run):
        with CaptureQueriesContext(connection) as seen:
            run()
        return len(seen)

    def online(self, person):
        User.objects.filter(pk=person.pk).update(last_seen=timezone.now())

    def test_the_leaders_task_page_does_not_ask_about_each_online_translator_one_by_one(self):
        self.split(self.a)
        page = lambda: self.get(self.lead, "dashboard:v1_task", self.task.code)
        self.online(self.a)
        few = self.queries(page)
        for number in range(8):
            person = User.objects.create_user(f"tr_sp_more_{number}", password="x", role=Role.TRANSLATOR, team_lead=self.lead)
            self.online(person)
        self.assertEqual(self.queries(page), few)

    def test_the_team_overview_and_the_direct_list_cost_the_same_for_a_bigger_team(self):
        team = lambda: services.team_overview()
        few = self.queries(team)
        for number in range(8):
            person = User.objects.create_user(f"tr_sp_team_{number}", password="x", role=Role.TRANSLATOR, team_lead=self.lead)
            self.online(person)
        self.assertEqual(self.queries(team), few)

    def test_filing_a_chat_file_does_not_walk_every_task_of_the_leader(self):
        from .models import ChatAttachment

        def file_message():
            room = services.pair_room(self.lead, self.a)
            message = ChatMessage.objects.create(room=room, sender=self.a, body="")
            ChatAttachment.objects.create(message=message, file=_file("x.txt"), original_name="x.txt", size=3)
            return message

        self.split(self.a)
        first = file_message()
        few = self.queries(lambda: services.tag_task_message(first))
        for number in range(12):
            other = services.create_task(client=self.acme, title=f"Other {number}", created_by=self.ops, deadline=self.due)
            services.accept_assignment(services.assign_to_lead(other, self.lead, self.ops), self.lead)
        second = file_message()
        self.assertEqual(self.queries(lambda: services.tag_task_message(second)), few)


class AiCheckPerTranslatorTests(_Split):
    """A task shared between translators is checked once for each of them, on their own files and their own share of the source (08/10/2026).

    The check compares one translator's file with the source; judged against all of it, every page that is a colleague's would be
    reported as left out. So each check is told the pages and the words the leader gave that translator, reads only that translator's
    files, and the stars of an accepted note come off that translator - never off the one who happens to be the task's first.
    """

    def setUp(self):
        super().setUp()
        from .models import AppSettings

        conf = AppSettings.load()
        conf.ai_check_enabled, conf.claude_api_key = True, "test-key"
        conf.save()
        # A check starts on a thread when a share is handed in: here it only leaves its row, and the tests run the check themselves.
        threads = mock.patch("dashboard.ai.threading.Thread")
        threads.start()
        self.addCleanup(threads.stop)
        self.split(self.a, self.b)

    # -- doors into the model ---------------------------------------------------------------------------------------
    def text(self, name, body):
        return SimpleUploadedFile(name, body.encode("utf-8"), content_type="text/plain")

    def hand(self, who, body):
        services.upload_translation(self.fresh(), who, [self.text(f"{who.username}.txt", body)])

    def run_check(self, who, reply=None, task=None):
        """Run the check for ``who`` with the network replaced: ``(row, the prompt that was sent)``."""
        import io

        from .models import AICheckResult

        sent = {}

        class Reply(io.BytesIO):
            def __enter__(self):
                return self

            def __exit__(self, *exc):
                return False

        def fake(request, timeout=None):
            sent["payload"] = json.loads(request.data.decode("utf-8"))
            text = reply or json.dumps({"verdict": "accurate", "summary_en": "ok", "summary_ar": "تمام", "issues": []})
            return Reply(json.dumps({"content": [{"type": "text", "text": text}]}).encode("utf-8"))

        row = AICheckResult.objects.create(task=task or self.task, translator=who, status="running")
        with mock.patch("dashboard.ai.net.urlopen", side_effect=fake):
            done = ai.finish_check(row.pk, notify_lead=False)
        content = sent["payload"]["messages"][0]["content"]
        return done, content if isinstance(content, str) else content[-1]["text"]

    # -- what each check is told and reads --------------------------------------------------------------------------
    def test_each_check_reads_only_its_translators_files_and_is_told_only_their_share(self):
        self.hand(self.a, "ALPHA translated words")
        self.hand(self.b, "BETA translated words")
        _, prompt_a = self.run_check(self.a)
        _, prompt_b = self.run_check(self.b)
        self.assertIn("ALPHA translated words", prompt_a)
        self.assertNotIn("BETA", prompt_a)
        self.assertIn("BETA translated words", prompt_b)
        self.assertNotIn("ALPHA", prompt_b)
        self.assertIn("SCOPE: this translator was given only pages 1-10 of the SOURCE (about 100 words)", prompt_a)
        self.assertIn("SCOPE: this translator was given only pages 11-20 of the SOURCE (about 200 words)", prompt_b)
        for prompt in (prompt_a, prompt_b):
            self.assertIn("the rest of the source went to other translators", prompt)
            self.assertIn("do not report it as omitted", prompt)

    def test_the_pair_the_leader_gave_a_translator_is_the_pair_the_check_is_told(self):
        Assignment.objects.filter(pk=self.of(self.b).pk).update(target_lang="FR")
        self.hand(self.b, "BETA translated words")
        _, prompt = self.run_check(self.b)
        self.assertIn("Target language: FR", prompt)
        self.assertNotIn("Target language: AR", prompt)

    def test_a_task_given_whole_is_judged_on_all_of_it_with_no_scope(self):
        whole = services.create_task(client=self.acme, title="Whole", created_by=self.ops, deadline=self.due)
        services.accept_assignment(services.assign_to_lead(whole, self.lead, self.ops), self.lead)
        self.assertEqual(self.post([self.part(self.c, words="900")], task=whole).status_code, 200)
        services.accept_assignment(Assignment.objects.get(task=whole, assignee=self.c), self.c)
        whole.refresh_from_db()
        services.upload_translation(whole, self.c, [self.text("c.txt", "GAMMA translated words")])
        _, prompt = self.run_check(self.c, task=whole)
        self.assertIn("GAMMA translated words", prompt)
        self.assertNotIn("SCOPE", prompt)

    def test_one_translator_given_pages_is_told_them_even_when_nobody_else_is_on_it(self):
        task = services.create_task(client=self.acme, title="Partial", created_by=self.ops, deadline=self.due)
        services.accept_assignment(services.assign_to_lead(task, self.lead, self.ops), self.lead)
        self.post([self.part(self.c, words="300", page_from="4", page_to="9")], task=task)
        services.accept_assignment(Assignment.objects.get(task=task, assignee=self.c), self.c)
        task.refresh_from_db()
        services.upload_translation(task, self.c, [self.text("c.txt", "GAMMA")])
        _, prompt = self.run_check(self.c, task=task)
        self.assertIn("pages 4-9 of the SOURCE (about 300 words)", prompt)
        self.assertNotIn("went to other translators", prompt)

    def test_the_check_is_stored_against_the_translator_it_judged(self):
        self.hand(self.a, "ALPHA")
        row, _ = self.run_check(self.a)
        self.assertEqual(row.translator_id, self.a.pk)

    # -- when it runs ------------------------------------------------------------------------------------------------
    def test_handing_a_share_in_starts_the_check_for_that_translator_alone(self):
        with mock.patch.object(ai, "start_background_check") as start:
            hand_in_translation(self.task, self.a)
        start.assert_called_once()
        self.assertEqual(start.call_args.kwargs, {"translator": self.a})
        self.assertEqual(self.fresh().status, TaskStatus.IN_PROGRESS)

    def test_the_second_translators_check_does_not_wait_for_the_first_to_finish(self):
        first = ai.start_background_check(self.task, translator=self.a)
        second = ai.start_background_check(self.task, translator=self.b)
        again = ai.start_background_check(self.task, translator=self.a)
        self.assertEqual((first.translator_id, second.translator_id, again), (self.a.pk, self.b.pk, None))
        self.assertEqual(self.task.ai_checks.count(), 2)

    def test_the_leader_or_the_admin_closing_checks_whoever_was_not_checked_since_they_handed_in(self):
        hand_in_translation(self.task, self.a)
        # A was checked the moment they handed in; closing the translation checks B, and not A a second time.
        self.assertEqual(list(self.task.ai_checks.values_list("translator_id", flat=True)), [self.a.pk])
        # A's check has finished by now (a second one for A would not be blocked by it still running).
        self.task.ai_checks.update(status="clean")
        services.upload_translation(self.fresh(), self.b, [self.text("b.txt", "BETA")])
        self.assertTrue(services.mark_translated(self.fresh(), self.admin))
        who = sorted(self.task.ai_checks.values_list("translator_id", flat=True))
        self.assertEqual(who, sorted([self.a.pk, self.b.pk]))

    def test_asking_again_by_hand_checks_every_translator_who_handed_in(self):
        hand_in_translation(self.task, self.a)
        hand_in_translation(self.task, self.b)
        self.task.ai_checks.all().delete()
        row = ai.start_background_check(self.fresh(), force=True)
        self.assertIsNotNone(row)
        self.assertEqual(sorted(self.task.ai_checks.values_list("translator_id", flat=True)), sorted([self.a.pk, self.b.pk]))
        browser = DjangoClient()
        browser.force_login(self.lead)
        self.task.ai_checks.all().delete()
        answer = browser.post(reverse("dashboard:api_ai_recheck", args=[self.task.code]))
        self.assertEqual(answer.status_code, 200)
        self.assertEqual(self.task.ai_checks.count(), 2)

    def test_asking_again_runs_the_check_for_every_translator_and_gives_back_each_finished_row(self):
        hand_in_translation(self.task, self.a)
        hand_in_translation(self.task, self.b)
        self.task.ai_checks.all().delete()
        with mock.patch.object(ai, "_review", lambda *args, **kwargs: {"status": "clean", "summary": "", "issues": [], "model_used": "", "error_message": ""}):
            rows = ai.recheck_all(self.fresh())
            first = ai.recheck_now(self.fresh())
        self.assertEqual(sorted(row.translator_id for row in rows), sorted([self.a.pk, self.b.pk]))
        self.assertIsNotNone(first)
        self.assertEqual(self.task.ai_checks.filter(translator=self.a).count(), 2)

    def test_a_translators_pdf_is_the_one_the_model_is_given(self):
        services.upload_translation(
            self.fresh(), self.a, [SimpleUploadedFile("a.pdf", b"%PDF-1.4 alpha", content_type="application/pdf")],
        )
        services.upload_translation(
            self.fresh(), self.b, [SimpleUploadedFile("b.pdf", b"%PDF-1.4 beta", content_type="application/pdf")],
        )
        _, mine = ai.collect_documents(self.fresh(), self.a)
        _, theirs = ai.collect_documents(self.fresh(), self.b)
        self.assertEqual([d["name"] for d in mine], ["a.pdf"])
        self.assertEqual([d["name"] for d in theirs], ["b.pdf"])

    def test_the_leader_is_told_whose_work_the_notes_are_about(self):
        from .models import AICheckResult

        self.hand(self.a, "ALPHA")
        row = AICheckResult.objects.create(
            task=self.task, translator=self.a, status="issues", issues=[{"severity": "high", "issue_en": "wrong"}],
        )
        Notification.objects.all().delete()
        ai._tell_the_team_leader(row)
        note = Notification.objects.get(user=self.lead)
        self.assertIn(self.a.short_name, note.body_ar)

    # -- the stars ----------------------------------------------------------------------------------------------------
    def check_for(self, who, issues=None):
        from .models import AICheckResult

        return AICheckResult.objects.create(
            task=self.task, translator=who, status=AICheckResult.Status.ISSUES,
            issues=issues or [{"severity": "high", "issue_en": "x"}, {"severity": "low", "issue_en": "y"}],
        )

    def test_the_stars_come_off_the_translator_the_check_judged_and_not_the_first_one(self):
        before = {person.pk: person.rating for person in (self.a, self.b)}
        taken, error = ai.accept_notes(self.check_for(self.b), self.lead, [0, 1])
        self.assertEqual(error, "")
        self.a.refresh_from_db()
        self.b.refresh_from_db()
        self.assertEqual(self.a.rating, before[self.a.pk])
        self.assertLess(self.b.rating, before[self.b.pk])
        self.assertEqual(RatingEvent.objects.filter(user=self.b).count(), 1)
        self.assertEqual(RatingEvent.objects.filter(user=self.a).count(), 0)
        self.assertEqual(self.fresh().translator_id, self.a.pk)

    def test_a_check_that_names_nobody_costs_nobody_and_never_the_first_translator(self):
        from .models import AICheckResult

        row = AICheckResult.objects.create(
            task=self.task, translator=None, status=AICheckResult.Status.ISSUES, issues=[{"severity": "high", "issue_en": "x"}],
        )
        self.assertEqual(ai.accept_notes(row, self.lead, [0]), (None, "no_translator"))
        self.assertEqual(RatingEvent.objects.count(), 0)
        body = self.notes()
        self.assertFalse(body["can_accept"])
        self.assertIsNone(body["accept_cost"]["translator"])

    def test_the_checks_made_before_there_were_several_translators_are_given_the_tasks_translator_by_the_migration(self):
        import importlib

        from django.apps import apps

        from .models import AICheckResult

        old = AICheckResult.objects.create(task=self.task, translator=None, status="issues", issues=[{"severity": "high"}])
        nobody = services.create_task(client=self.acme, title="Nobody", created_by=self.ops)
        orphan = AICheckResult.objects.create(task=nobody, translator=None, status="issues", issues=[{"severity": "high"}])
        named = AICheckResult.objects.create(task=self.task, translator=self.b, status="issues", issues=[{"severity": "high"}])
        migration = importlib.import_module("dashboard.migrations.0059_aicheck_translator")
        migration.name_the_translator(apps, None)
        for row in (old, orphan, named):
            row.refresh_from_db()
        self.assertEqual(old.translator_id, self.fresh().translator_id)
        self.assertIsNotNone(old.translator_id)
        self.assertIsNone(orphan.translator_id)
        self.assertEqual(named.translator_id, self.b.pk)

    def test_a_note_costs_once_and_a_share_that_fell_through_leaves_nobody_to_charge(self):
        row = self.check_for(self.a)
        self.assertEqual(ai.accept_notes(row, self.lead, [0])[1], "")
        self.assertEqual(ai.accept_notes(row, self.lead, [0]), (None, "already"))
        none = self.check_for(self.a)
        type(none).objects.filter(pk=none.pk).update(translator=None)
        type(self.task).objects.filter(pk=self.task.pk).update(translator=None)
        self.task.refresh_from_db()
        self.assertEqual(ai.accept_notes(none, self.lead, [0]), (None, "no_translator"))

    # -- what the leader's box and the doors say ------------------------------------------------------------------------
    def notes(self, user=None):
        return _json(self.get(user or self.lead, "dashboard:v1_ai_task_notes", self.task.code))

    def test_the_box_has_one_section_for_each_translator_checked_and_says_whose_stars_are_at_stake(self):
        self.check_for(self.a)
        self.check_for(self.b)
        body = self.notes()
        self.assertEqual([c["translator"]["name"] for c in body["checks"]], [self.b.short_name, self.a.short_name])
        self.assertEqual([c["accept_cost"]["translator"] for c in body["checks"]], [self.b.short_name, self.a.short_name])
        self.assertTrue(all(c["can_accept"] for c in body["checks"]))
        # The top of the answer is still the newest check, as it was.
        self.assertEqual(body["check"]["id"], body["checks"][0]["check"]["id"])
        self.assertEqual(body["accept_cost"]["translator"], self.b.short_name)

    def test_a_task_checked_for_one_translator_is_one_box_as_before(self):
        self.check_for(self.a)
        body = self.notes()
        self.assertNotIn("checks", body)
        self.assertEqual(body["accept_cost"]["translator"], self.a.short_name)

    def test_accepting_through_the_door_charges_the_translator_of_the_check_that_was_shown(self):
        mine, theirs = self.check_for(self.a), self.check_for(self.b)
        browser = DjangoClient()
        browser.force_login(self.lead)
        # B's check is the newest, A's is older - but each is the newest of its own translator, so neither is stale.
        for check, person in ((mine, self.a), (theirs, self.b)):
            answer = browser.post(
                reverse("dashboard:v1_ai_accept", args=[self.task.code]),
                data=json.dumps({"issues": [0], "check": check.pk}), content_type="application/json",
            )
            self.assertEqual(answer.status_code, 200, person.username)
            self.assertEqual(RatingEvent.objects.filter(user=person).count(), 1)

    def test_a_newer_check_of_the_same_translator_makes_the_older_one_stale_and_charges_nobody(self):
        old = self.check_for(self.a)
        self.check_for(self.a)
        browser = DjangoClient()
        browser.force_login(self.lead)
        answer = browser.post(
            reverse("dashboard:v1_ai_accept", args=[self.task.code]),
            data=json.dumps({"issues": [0], "check": old.pk}), content_type="application/json",
        )
        self.assertEqual((answer.status_code, _json(answer)["error"]), (409, "stale_check"))
        self.assertEqual(RatingEvent.objects.count(), 0)

    def test_a_check_id_of_another_task_is_stale_and_charges_nobody(self):
        other = services.create_task(client=self.acme, title="Other", created_by=self.ops, deadline=self.due)
        from .models import AICheckResult

        self.check_for(self.a)
        foreign = AICheckResult.objects.create(task=other, translator=self.a, status="issues", issues=[{"severity": "high"}])
        browser = DjangoClient()
        browser.force_login(self.lead)
        answer = browser.post(
            reverse("dashboard:v1_ai_accept", args=[self.task.code]),
            data=json.dumps({"issues": [0], "check": foreign.pk}), content_type="application/json",
        )
        self.assertEqual(answer.status_code, 409)
        self.assertEqual(RatingEvent.objects.count(), 0)

    # -- who reads what ------------------------------------------------------------------------------------------------
    def test_a_translator_reads_the_checks_of_their_own_work_and_never_a_colleagues(self):
        mine, theirs = self.check_for(self.a, [{"severity": "high", "issue_en": "mine"}]), self.check_for(self.b)
        task = _json(self.get(self.a, "dashboard:v1_translator_task", self.task.code))["task"]
        self.assertEqual([c["id"] for c in task["ai"]["checks"]], [mine.pk])
        other = _json(self.get(self.b, "dashboard:v1_translator_task", self.task.code))["task"]
        self.assertEqual([c["id"] for c in other["ai"]["checks"]], [theirs.pk])

    # -- the manual door ----------------------------------------------------------------------------------------------
    def test_a_translator_only_offered_a_share_cannot_check_a_colleagues_file_through_the_manual_door(self):
        self.hand(self.a, "ALPHA SECRET TRANSLATION")
        self.assertEqual(self.post([self.part(self.c, page_from="21", page_to="30")]).status_code, 200)
        before = self.task.ai_checks.count()
        browser = DjangoClient()
        browser.force_login(self.c)
        with mock.patch.object(ai, "_review") as review:
            answer = browser.post(reverse("dashboard:api_ai_check", args=[self.task.code]))
        self.assertEqual(answer.status_code, 403)
        self.assertNotIn("ALPHA", answer.content.decode("utf-8"))
        review.assert_not_called()
        self.assertEqual(self.task.ai_checks.count(), before)

    def test_the_check_card_is_not_drawn_for_a_translator_still_being_offered_the_share(self):
        self.assertEqual(self.post([self.part(self.c, page_from="21", page_to="30")]).status_code, 200)
        page = _json(self.get(self.c, "dashboard:v1_translator_task", self.task.code))["task"]
        self.assertTrue(page["mine"])
        self.assertFalse(page["ai"]["visible"])
        self.assertEqual(page["ai"]["checks"], [])
        self.assertTrue(_json(self.get(self.a, "dashboard:v1_translator_task", self.task.code))["task"]["ai"]["visible"])

    def test_a_translators_own_check_is_theirs_and_neither_hides_the_automatic_one_nor_costs_anyone_stars(self):
        from .models import AICheckResult

        automatic = self.check_for(self.a)
        own = AICheckResult.objects.create(
            task=self.task, translator=self.a, requested_by=self.a, status="issues", issues=[{"severity": "low", "issue_en": "own"}],
        )
        body = self.notes()
        self.assertEqual(body["check"]["id"], automatic.pk)
        self.assertTrue(body["can_accept"])
        browser = DjangoClient()
        browser.force_login(self.lead)
        refused = browser.post(
            reverse("dashboard:v1_ai_accept", args=[self.task.code]),
            data=json.dumps({"issues": [0], "check": own.pk}), content_type="application/json",
        )
        self.assertEqual((refused.status_code, _json(refused)["error"]), (409, "stale_check"))
        # The automatic check stays the one to act on, although a newer row exists for the same translator.
        fine = browser.post(
            reverse("dashboard:v1_ai_accept", args=[self.task.code]),
            data=json.dumps({"issues": [0], "check": automatic.pk}), content_type="application/json",
        )
        self.assertEqual(fine.status_code, 200)
        # Nor does it ever take stars: even asked for directly.
        taken, error = ai.accept_notes(own, self.lead, [0])
        self.assertEqual((taken, error), (None, "no_translator"))

    def test_a_translators_own_check_is_not_the_panel_beside_their_chat(self):
        from .models import AICheckResult

        hand_in_translation(self.task, self.a)
        automatic = self.check_for(self.a, [{"severity": "high", "issue_en": "the real one"}])
        AICheckResult.objects.create(task=self.task, translator=self.a, requested_by=self.a, status="clean", issues=[])
        panel = _json(self.get(self.lead, "dashboard:v1_ai_staff_notes", self.a.pk))["notes"]
        self.assertEqual(panel["issues"][0]["text"]["en"], "the real one")
        self.assertIsNotNone(automatic)

    def test_somebody_who_reads_the_task_says_whose_work_it_is_when_several_translators_are_on_it(self):
        self.hand(self.a, "ALPHA translated words")
        self.hand(self.b, "BETA translated words")
        seen = {}

        def fake_review(conf, task, source, translated, requirements, source_docs=(), translated_docs=(), translator=None):
            seen["translated"], seen["translator"] = translated, translator
            return {"status": "clean", "summary": "", "issues": [], "model_used": "", "error_message": ""}

        browser = DjangoClient()
        browser.force_login(self.lead)
        url = reverse("dashboard:api_ai_check", args=[self.task.code])
        with mock.patch.object(ai, "_review", fake_review):
            guessed = browser.post(url)
            stranger = browser.post(url, {"translator": self.stranger.pk})
            chosen = browser.post(url, {"translator": self.b.pk})
        self.assertEqual((guessed.status_code, _json(guessed)["error"]), (400, "choose_translator"))
        self.assertEqual((stranger.status_code, _json(stranger)["error"]), (400, "bad_translator"))
        self.assertEqual(chosen.status_code, 200)
        self.assertIn("BETA", seen["translated"])
        self.assertNotIn("ALPHA", seen["translated"])
        row = self.task.ai_checks.get()
        self.assertEqual((row.translator_id, row.requested_by_id), (self.b.pk, self.lead.pk))

    def test_a_translator_cannot_open_the_leaders_box(self):
        self.check_for(self.a)
        self.assertEqual(self.get(self.a, "dashboard:v1_ai_task_notes", self.task.code).status_code, 403)

    def test_the_panel_beside_the_chat_with_a_translator_has_their_notes_while_the_others_still_translate(self):
        hand_in_translation(self.task, self.a)
        self.check_for(self.a, [{"severity": "high", "issue_en": "only A"}])
        self.check_for(self.b, [{"severity": "high", "issue_en": "only B"}])
        self.assertEqual(self.fresh().status, TaskStatus.IN_PROGRESS)
        panel = _json(self.get(self.lead, "dashboard:v1_ai_staff_notes", self.a.pk))["notes"]
        self.assertEqual(panel["count"], 1)
        self.assertEqual(panel["issues"][0]["text"]["en"], "only A")
        # B has not handed in: nothing is shown beside B's chat yet.
        self.assertIsNone(_json(self.get(self.lead, "dashboard:v1_ai_staff_notes", self.b.pk))["notes"])

    def test_a_check_asked_by_a_translator_is_about_their_own_files(self):
        self.hand(self.a, "ALPHA translated words")
        self.hand(self.b, "BETA translated words")
        sent = {}

        def fake_review(conf, task, source, translated, requirements, source_docs=(), translated_docs=(), translator=None):
            sent["translated"], sent["translator"] = translated, translator
            return {"status": "clean", "summary": "", "issues": [], "model_used": "", "error_message": ""}

        browser = DjangoClient()
        browser.force_login(self.b)
        with mock.patch.object(ai, "_review", fake_review):
            answer = browser.post(reverse("dashboard:api_ai_check", args=[self.task.code]))
        self.assertEqual(answer.status_code, 200)
        self.assertIn("BETA", sent["translated"])
        self.assertNotIn("ALPHA", sent["translated"])
        self.assertEqual(sent["translator"], self.b)
        self.assertEqual(self.task.ai_checks.get().translator_id, self.b.pk)
