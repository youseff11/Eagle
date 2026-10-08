"""The language pair is the operation's, and the words are the team leader's at the review (08/10/2026).

What these tests hold:

- the operation (and the admin) says the pair on the new-task form - it cannot be left empty - and corrects it on the task page; the leader and
  the translators never type it, and a task without one does not go to a translator;
- the leader writes how many words each translator translated while the translation is with him; the review cannot be finished without
  them, and a number is never written by anybody else or at any other time;
- the words feed the task's own count and the month's production the way they always did.
"""

import json
from datetime import timedelta

from django.test import Client as DjangoClient
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from . import payroll, services
from .models import Assignment, AssignmentStatus, AuditLog, Client, Role, Task, TaskStatus, User
from .tests import hand_in_translation

WORDS = "dashboard:v1_task_part_words"
LANGUAGES = "dashboard:v1_task_languages"
TASK = "dashboard:v1_task"


def _json(response):
    return json.loads(response.content.decode("utf-8"))


class _Review(TestCase):
    """A task with two translators (pages 1-10 and 11-20) who have both handed in: it is with the leader for review."""

    def setUp(self):
        make = lambda name, role, **kw: User.objects.create_user(name, password="x", role=role, **kw)
        self.ops = make("ops_rw", Role.OPERATION)
        self.lead = make("lead_rw", Role.TEAM_LEAD)
        self.other_lead = make("lead_rw_two", Role.TEAM_LEAD)
        self.admin = make("admin_rw", Role.ADMIN)
        self.support = make("support_rw", Role.SUPPORT)
        self.a = make("tr_rw_a", Role.TRANSLATOR, team_lead=self.lead)
        self.b = make("tr_rw_b", Role.TRANSLATOR, team_lead=self.lead)
        self.acme = Client.objects.create(name="ACME Secret Ltd", phone="+201000000092")
        self.task = self.accepted("Big contract")
        self.give(self.task, (self.a, 1, 10), (self.b, 11, 20))
        hand_in_translation(self.task, self.a)
        hand_in_translation(self.task, self.b)
        self.task.refresh_from_db()
        self.assertEqual(self.task.status, TaskStatus.UNDER_REVIEW)

    def accepted(self, title):
        task = services.create_task(
            client=self.acme, title=title, created_by=self.ops, deadline=timezone.now() + timedelta(days=3),
            source_lang="EN", target_lang="AR",
        )
        services.accept_assignment(services.assign_to_lead(task, self.lead, self.ops), self.lead)
        task.refresh_from_db()
        return task

    def give(self, task, *shares):
        parts = [services.Part(who, task.source_lang, task.target_lang, 0, first, last) for who, first, last in shares]
        for share in services.assign_to_translators(task, parts, self.lead):
            services.accept_assignment(share, share.assignee)
        task.refresh_from_db()

    def shares(self, task=None):
        return {
            a.assignee_id: a for a in Assignment.objects.filter(task=task or self.task, target_role=Role.TRANSLATOR).exclude(
                status=AssignmentStatus.CANCELLED
            )
        }

    def post(self, user, name, body, code=None):
        browser = DjangoClient()
        if user is not None:
            browser.force_login(user)
        return browser.post(reverse(name, args=[code or self.task.code]), json.dumps(body), content_type="application/json")

    def review(self, user, code=None):
        browser = DjangoClient()
        browser.force_login(user)
        return browser.post(f"/api/tasks/{code or self.task.code}/reviewed/")

    def put(self, user, a=None, b=None, code=None, task=None):
        shares = self.shares(task)
        parts = []
        if a is not None:
            parts.append({"id": shares[self.a.pk].pk, "words": a})
        if b is not None:
            parts.append({"id": shares[self.b.pk].pk, "words": b})
        return self.post(user, WORDS, {"parts": parts}, code)

    def fresh(self):
        self.task.refresh_from_db()
        return self.task


class TheLeaderWritesTheWordsAtTheReviewTests(_Review):
    def test_he_writes_each_translators_words_and_they_are_kept_on_the_shares(self):
        answer = self.put(self.lead, a=800, b=450)
        self.assertEqual(answer.status_code, 200, answer.content)
        shares = self.shares()
        self.assertEqual((shares[self.a.pk].words, shares[self.b.pk].words), (800, 450))
        self.assertEqual({row["words"] for row in _json(answer)["parts"]}, {800, 450})
        self.assertTrue(AuditLog.objects.filter(action="task.part_words", target=self.task.code, actor=self.lead).exists())

    def test_one_can_be_corrected_later_while_it_is_still_under_review(self):
        self.put(self.lead, a=800, b=450)
        self.assertEqual(self.put(self.lead, a=900).status_code, 200)
        self.assertEqual((self.shares()[self.a.pk].words, self.shares()[self.b.pk].words), (900, 450))

    def test_the_admin_may_too(self):
        self.assertEqual(self.put(self.admin, a=1, b=2).status_code, 200)

    def test_nobody_else_may_and_nothing_is_written(self):
        # Another leader does not find the task at all; the operation, a translator and support are refused.
        self.assertEqual(self.put(self.other_lead, a=5, b=5).status_code, 404)
        for who in (self.ops, self.a, self.support):
            self.assertEqual(self.put(who, a=5, b=5).status_code, 403, who.username)
        self.assertEqual(self.put(None, a=5, b=5).status_code, 401)
        self.assertEqual({s.words for s in self.shares().values()}, {0})

    def test_only_while_the_task_is_under_review(self):
        for status in (TaskStatus.IN_PROGRESS, TaskStatus.REVIEWED, TaskStatus.DELIVERED, TaskStatus.CANCELLED):
            Task.objects.filter(pk=self.task.pk).update(status=status)
            answer = self.put(self.lead, a=5, b=5)
            self.assertEqual((answer.status_code, _json(answer)["error"]), (400, "bad_status"), status)
        self.assertEqual({s.words for s in self.shares().values()}, {0})

    def test_a_number_that_is_not_a_whole_count_is_refused_in_words_and_nothing_is_written(self):
        for bad in (0, -5, "12x", 1.5, True, "", 10**9, [3]):
            answer = self.put(self.lead, a=800, b=bad)
            self.assertEqual((answer.status_code, _json(answer)["code"]), (400, "bad_words"), bad)
            self.assertIn(self.b.short_name, _json(answer)["error"])
        # A share with no number at all is the same refusal, and the good one beside the bad one was not kept either.
        missing = self.post(self.lead, WORDS, {"parts": [{"id": self.shares()[self.b.pk].pk}]})
        self.assertEqual((missing.status_code, _json(missing)["code"]), (400, "bad_words"))
        self.assertEqual({s.words for s in self.shares().values()}, {0})

    def test_a_share_that_is_not_on_this_task_is_refused(self):
        other = self.accepted("Another job")
        self.give(other, (self.a, 1, 5))
        foreign = self.shares(other)[self.a.pk]
        for parts in ([{"id": foreign.pk, "words": 5}], [{"id": 99999, "words": 5}], [{"id": "x", "words": 5}], [], "no", [5]):
            answer = self.post(self.lead, WORDS, {"parts": parts})
            self.assertEqual((answer.status_code, _json(answer)["error"]), (400, "bad_parts"), parts)
        mine = self.shares()[self.a.pk].pk
        twice = self.post(self.lead, WORDS, {"parts": [{"id": mine, "words": 5}, {"id": mine, "words": 6}]})
        self.assertEqual((twice.status_code, _json(twice)["error"]), (400, "bad_parts"))
        self.assertEqual(Assignment.objects.get(pk=foreign.pk).words, 0)
        self.assertEqual({s.words for s in self.shares().values()}, {0})

    def test_an_offer_nobody_took_has_no_words_to_write(self):
        pending = Assignment.objects.create(
            task=self.task, assignee=User.objects.get(username="tr_rw_a"), assigned_by=self.lead, target_role=Role.TRANSLATOR,
            status=AssignmentStatus.CANCELLED,
        )
        answer = self.post(self.lead, WORDS, {"parts": [{"id": pending.pk, "words": 5}]})
        self.assertEqual((answer.status_code, _json(answer)["error"]), (400, "bad_parts"))


class TheServicesRefuseOnTheirOwnTests(_Review):
    """The doors check who is asking, and so do the services: a second caller (an order, a script) is held to the same rules."""

    def test_the_words_are_the_task_own_leaders_and_the_admins_alone(self):
        entries = [{"id": self.shares()[self.a.pk].pk, "words": 5}]
        for who in (self.ops, self.other_lead, self.a, self.support):
            self.assertEqual(services.set_part_words(self.task, entries, who), (None, "forbidden"), who.username)
        self.assertEqual({s.words for s in self.shares().values()}, {0})
        shares, why = services.set_part_words(self.task, entries, self.lead)
        self.assertEqual((len(shares), why), (2, ""))

    def test_the_pair_is_the_operations_and_the_admins_alone(self):
        for who in (self.lead, self.other_lead, self.a, self.support):
            self.assertEqual(services.set_task_languages(self.task, "FR", "DE", who), (False, "forbidden"), who.username)
        self.assertEqual((self.fresh().source_lang, self.fresh().target_lang), ("EN", "AR"))
        self.assertEqual(services.set_task_languages(self.task, "FR", "DE", self.ops), (True, ""))


class TheTasksOwnCountFollowsTheSharesTests(_Review):
    def test_with_no_count_settled_it_becomes_the_sum_and_keeps_following_it(self):
        self.assertEqual(self.fresh().word_count_state, "confirmed" if self.task.word_count else "manual_needed")
        self.put(self.lead, a=800, b=450)
        task = self.fresh()
        self.assertEqual((task.word_count, task.word_count_state), (1250, "confirmed"))
        self.put(self.lead, b=500)
        self.assertEqual(self.fresh().word_count, 1300)

    def test_a_count_a_person_settled_is_never_overwritten(self):
        Task.objects.filter(pk=self.task.pk).update(word_count=4000, word_count_state="confirmed")
        self.put(self.lead, a=800, b=450)
        self.assertEqual(self.fresh().word_count, 4000)


class TheReviewCannotBeFinishedWithoutThemTests(_Review):
    def test_a_review_with_a_translator_whose_words_are_not_written_is_refused_in_words(self):
        answer = self.review(self.lead)
        self.assertEqual((answer.status_code, _json(answer)["code"]), (400, "words_missing"))
        self.assertEqual(_json(answer)["error"], services.WORDS_MISSING_AR)
        self.assertEqual(self.fresh().status, TaskStatus.UNDER_REVIEW)
        # One of two is not enough.
        self.put(self.lead, a=800)
        self.assertEqual(self.review(self.lead).status_code, 400)
        self.assertEqual(self.fresh().status, TaskStatus.UNDER_REVIEW)

    def test_the_service_refuses_on_its_own_as_well(self):
        self.assertFalse(services.mark_reviewed(self.task, self.lead))
        self.assertFalse(services.mark_reviewed(self.task, self.admin))
        self.assertEqual(self.fresh().status, TaskStatus.UNDER_REVIEW)

    def test_with_every_translators_words_written_the_review_goes_through(self):
        self.put(self.lead, a=800, b=450)
        answer = self.review(self.lead)
        self.assertEqual((answer.status_code, _json(answer)["ok"]), (200, True))
        self.assertEqual(self.fresh().status, TaskStatus.REVIEWED)
        # A second press on a reviewed task is the idempotent case it always was.
        self.assertEqual(self.review(self.lead).status_code, 200)

    def test_a_task_with_no_shares_behind_it_is_reviewed_as_before(self):
        old = Task.objects.create(
            client=self.acme, title="Old", created_by=self.ops, team_lead=self.lead, translator=self.a, status=TaskStatus.UNDER_REVIEW,
        )
        self.assertEqual(self.review(self.lead, old.code).status_code, 200)
        old.refresh_from_db()
        self.assertEqual(old.status, TaskStatus.REVIEWED)

    def test_a_share_that_fell_through_does_not_hold_the_review_back(self):
        # B was given pages and said no: only the translators who took a share are asked for words.
        task = self.accepted("Falls through")
        shares = services.assign_to_translators(
            task, [services.Part(self.a, "EN", "AR", 0, 1, 5), services.Part(self.b, "EN", "AR", 0, 6, 9)], self.lead,
        )
        services.accept_assignment(shares[0], self.a)
        services.decline_assignment(shares[1], self.b, "no")
        task.refresh_from_db()
        hand_in_translation(task, self.a)
        task.refresh_from_db()
        self.assertEqual(task.status, TaskStatus.UNDER_REVIEW)
        self.assertEqual([s.assignee_id for s in services.parts_without_words(task)], [self.a.pk])
        self.assertEqual(self.review(self.lead, task.code).status_code, 400)
        self.assertEqual(self.put(self.lead, a=300, code=task.code, task=task).status_code, 200)
        self.assertEqual(self.review(self.lead, task.code).status_code, 200)


class WhatThePageTellsTheLeaderTests(_Review):
    def lead_tools(self, user=None):
        browser = DjangoClient()
        browser.force_login(user or self.lead)
        return _json(browser.get(reverse(TASK, args=[self.task.code])))["task"]["lead"]

    def test_the_box_is_offered_only_while_the_task_is_under_review_and_has_a_share(self):
        self.assertTrue(self.lead_tools()["can_set_part_words"])
        self.assertTrue(self.lead_tools(self.admin)["can_set_part_words"])
        for status in (TaskStatus.IN_PROGRESS, TaskStatus.REVIEWED):
            Task.objects.filter(pk=self.task.pk).update(status=status)
            self.assertFalse(self.lead_tools()["can_set_part_words"], status)

    def test_each_share_carries_its_id_and_the_words_written(self):
        self.put(self.lead, a=800)
        browser = DjangoClient()
        browser.force_login(self.lead)
        parts = _json(browser.get(reverse(TASK, args=[self.task.code])))["task"]["parts"]
        self.assertEqual({p["name"]: (p["id"], p["words"], p["done"]) for p in parts}, {
            self.a.short_name: (self.shares()[self.a.pk].pk, 800, True), self.b.short_name: (self.shares()[self.b.pk].pk, 0, True),
        })

    def test_the_translator_reads_their_words_once_the_leader_has_written_them(self):
        self.put(self.lead, a=800)
        browser = DjangoClient()
        browser.force_login(self.a)
        mine = _json(browser.get(reverse("dashboard:v1_translator_task", args=[self.task.code])))["task"]["part"]
        self.assertEqual((mine["words"], mine["source_lang"], mine["target_lang"]), (800, "EN", "AR"))


class TheMonthsProductionIsCountedFromThemTests(_Review):
    def test_each_translator_is_counted_for_the_words_the_leader_wrote_on_the_day_they_handed_in(self):
        today = timezone.localtime().date()
        self.assertEqual({done.words for done in payroll.production(self.a, today, today)}, {0})
        self.put(self.lead, a=800, b=450)
        self.assertEqual([done.words for done in payroll.production(self.a, today, today)], [800])
        self.assertEqual([done.words for done in payroll.production(self.b, today, today)], [450])


class TheOperationSaysThePairTests(_Review):
    def test_the_operation_and_the_admin_set_it_and_the_hand_offs_already_made_follow(self):
        for user in (self.ops, self.admin):
            answer = self.post(user, LANGUAGES, {"source_lang": "english", "target_lang": "الفرنسية"})
            self.assertEqual((answer.status_code, _json(answer)["source_lang"], _json(answer)["target_lang"]), (200, "EN", "FR"), user.username)
        task = self.fresh()
        self.assertEqual((task.source_lang, task.target_lang), ("EN", "FR"))
        self.assertEqual({(s.source_lang, s.target_lang) for s in self.shares().values()}, {("EN", "FR")})
        self.assertTrue(AuditLog.objects.filter(action="task.languages", target=self.task.code, actor=self.ops).exists())

    def test_the_leader_the_translator_and_support_may_not_say_it(self):
        for who in (self.lead, self.a, self.support):
            self.assertEqual(self.post(who, LANGUAGES, {"source_lang": "FR", "target_lang": "DE"}).status_code, 403, who.username)
        self.assertEqual(self.post(None, LANGUAGES, {"source_lang": "FR", "target_lang": "DE"}).status_code, 401)
        self.assertEqual((self.fresh().source_lang, self.fresh().target_lang), ("EN", "AR"))

    def test_an_empty_or_unreadable_pair_is_refused_in_words_and_nothing_changes(self):
        for body in (
            {"source_lang": "", "target_lang": "AR"}, {"source_lang": "EN", "target_lang": "  "}, {}, {"source_lang": "EN"},
        ):
            answer = self.post(self.ops, LANGUAGES, body)
            self.assertEqual((answer.status_code, _json(answer)["code"]), (400, "bad_languages"), body)
            self.assertEqual(_json(answer)["error"], services.LANGUAGE_PAIR_AR)
        too_long = self.post(self.ops, LANGUAGES, {"source_lang": "EN", "target_lang": "x" * 41})
        self.assertEqual(_json(too_long)["error"], services.LANGUAGE_TOO_LONG_AR)
        for body in ({"source_lang": ["EN"], "target_lang": "AR"}, {"source_lang": 5, "target_lang": "AR"}, {"source_lang": "x" * 81, "target_lang": "AR"}):
            self.assertEqual(self.post(self.ops, LANGUAGES, body).status_code, 400, body)
        self.assertEqual((self.fresh().source_lang, self.fresh().target_lang), ("EN", "AR"))

    def test_a_finished_task_keeps_its_pair(self):
        for status in (TaskStatus.DELIVERED, TaskStatus.CANCELLED):
            Task.objects.filter(pk=self.task.pk).update(status=status)
            answer = self.post(self.ops, LANGUAGES, {"source_lang": "FR", "target_lang": "DE"})
            self.assertEqual((answer.status_code, _json(answer)["error"]), (400, "bad_status"), status)
        self.assertEqual((self.fresh().source_lang, self.fresh().target_lang), ("EN", "AR"))

    def test_a_task_that_had_no_pair_can_then_go_to_a_translator(self):
        task = self.accepted("No pair yet")
        Task.objects.filter(pk=task.pk).update(source_lang="", target_lang="")
        task.refresh_from_db()
        with self.assertRaises(services.PartError) as refused:
            services.parse_parts(task, [{"translator": self.a.pk}], self.lead)
        self.assertEqual(refused.exception.code, "task_needs_languages")
        self.assertEqual(self.post(self.ops, LANGUAGES, {"source_lang": "EN", "target_lang": "AR"}, task.code).status_code, 200)
        task.refresh_from_db()
        parts = services.parse_parts(task, [{"translator": self.a.pk}], self.lead)
        self.assertEqual([(p.source_lang, p.target_lang, p.words) for p in parts], [("EN", "AR", 0)])

    def test_the_task_page_offers_the_box_to_the_operation_and_the_admin_only_and_not_once_it_is_done(self):
        def can(user):
            browser = DjangoClient()
            browser.force_login(user)
            return _json(browser.get(reverse(TASK, args=[self.task.code])))["task"]["can"]["set_languages"]

        self.assertEqual({u.username: can(u) for u in (self.ops, self.admin, self.lead, self.support)}, {
            "ops_rw": True, "admin_rw": True, "lead_rw": False, "support_rw": False,
        })
        Task.objects.filter(pk=self.task.pk).update(status=TaskStatus.DELIVERED)
        self.assertFalse(can(self.ops))


class TheNewTaskFormInsistsOnThePairTests(_Review):
    def create(self, **over):
        body = {"client": self.acme.pk, "title": "A job", "description": "", "source_lang": "en", "target_lang": "ar", "priority": "normal", **over}
        browser = DjangoClient()
        browser.force_login(self.ops)
        return browser.post(reverse("dashboard:v1_task_create"), json.dumps(body), content_type="application/json")

    def test_a_task_cannot_be_made_without_both_languages(self):
        before = Task.objects.count()
        for over, box in (({"source_lang": ""}, "source_lang"), ({"target_lang": ""}, "target_lang"), ({"source_lang": " ", "target_lang": " "}, "source_lang")):
            answer = self.create(**over)
            self.assertEqual(answer.status_code, 400, over)
            self.assertIn(box, _json(answer)["fields"], over)
        self.assertEqual(Task.objects.count(), before)

    def test_with_both_it_is_made_and_the_pair_is_read_as_codes(self):
        answer = self.create(source_lang="english", target_lang="arabic")
        self.assertEqual(answer.status_code, 200)
        task = Task.objects.get(code=_json(answer)["code"])
        self.assertEqual((task.source_lang, task.target_lang), ("EN", "AR"))
