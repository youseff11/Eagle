"""The team leader accepts AI notes, and each accepted note takes stars off the translator - and nobody else.

What these tests hold: only the task's leader and the admin accept, and only notes of the latest check, named by their place in it;
the translator loses ``penalty_value`` stars for each note and no other person loses anything; a note costs once however often it
is pressed; a person near nought loses what they have; the deduction is one that HR and the admin can apply or forgive
(``penalties.py``); and the box says what accepting costs before it is pressed.
"""

import json
from decimal import Decimal

from django.test import Client as DjangoClient
from django.urls import reverse

from . import ai, penalties
from .models import AICheckResult, AppSettings, AuditLog, Notification, RatingEvent, User
from .tests_ai_notes import NOTES, _Notes, issue
from .tests_api_v1 import _json

ACCEPT = "dashboard:v1_ai_accept"


class _Accept(_Notes):
    def setUp(self):
        super().setUp()
        self.three = [issue("first", "high"), issue("second", "low", location="page 9"), issue("third", "medium")]

    def post(self, user, body=None, raw=None, code=None):
        browser = DjangoClient()
        if user is not None:
            browser.force_login(user)
        if raw is None:
            body = dict(body if body is not None else {})
            latest = self.task.ai_checks.order_by("-created_at", "-id").first()
            # The box sends the check it showed; a test that is not about that sends the latest.
            body.setdefault("check", latest.pk if latest else 0)
        data = raw if raw is not None else json.dumps(body)
        return browser.post(reverse(ACCEPT, args=[code or self.task.code]), data=data, content_type="application/json")

    def stars(self, person):
        person.refresh_from_db()
        return person.rating


class AcceptTests(_Accept):
    def test_each_accepted_note_takes_the_penalty_off_the_translator_and_nobody_else(self):
        check = self.check(self.three)
        before = {person.pk: self.stars(person) for person in (self.tr, self.lead, self.admin, self.ops, self.hr)}
        answer = self.post(self.lead, {"issues": [0, 2]})
        self.assertEqual(answer.status_code, 200)
        self.assertEqual(answer["Cache-Control"], "private, no-store")
        self.assertEqual(_json(answer)["taken"], "0.25")
        self.assertEqual(self.stars(self.tr), before[self.tr.pk] - Decimal("0.250"))
        for person in (self.lead, self.admin, self.ops, self.hr):
            self.assertEqual(self.stars(person), before[person.pk], person.username)
        check.refresh_from_db()
        self.assertEqual(check.accepted, [0, 2])

    def test_the_deduction_is_one_event_that_waits_for_hr_and_says_why_without_a_title(self):
        self.check(self.three)
        self.post(self.lead, {"all": True})
        event = RatingEvent.objects.get(user=self.tr)
        self.assertEqual((event.delta, event.decision, event.task), (Decimal("-0.375"), RatingEvent.Decision.PENDING, self.task))
        self.assertIn("3", event.reason_en)
        self.assertIn(self.task.code, event.reason_en)
        self.assertNotIn(self.task.title, event.reason_ar + event.reason_en)
        self.assertTrue(Notification.objects.filter(user=self.hr, title_en="Stars taken off an employee").exists())
        self.assertTrue(Notification.objects.filter(user=self.admin, title_en="Stars taken off an employee").exists())

    def test_the_translator_is_told_with_the_count_and_the_stars(self):
        self.check(self.three)
        self.post(self.lead, {"issues": [1]})
        told = Notification.objects.get(user=self.tr, title_en="Rating penalty")
        self.assertIn("1 note", told.body_en)
        self.assertIn("0.125", told.body_en)
        self.assertEqual(told.level, "danger")
        self.assertTrue(AuditLog.objects.filter(actor=self.lead, action="task.ai_accept", target=self.task.code).exists())

    def test_the_admin_may_accept_too(self):
        self.check(self.three)
        self.assertEqual(self.post(self.admin, {"issues": [0]}).status_code, 200)
        self.assertEqual(self.stars(self.tr), Decimal("4.875"))

    def test_the_company_penalty_is_the_price_of_a_note(self):
        conf = AppSettings.load()
        conf.penalty_value = Decimal("0.500")
        conf.save()
        self.check(self.three)
        self.post(self.lead, {"issues": [0, 1]})
        self.assertEqual(self.stars(self.tr), Decimal("4.000"))

    def test_a_person_near_nought_loses_what_they_have_and_forgiving_gives_back_only_that(self):
        User.objects.filter(pk=self.tr.pk).update(rating=Decimal("0.100"))
        self.check(self.three)
        self.assertEqual(_json(self.post(self.lead, {"all": True}))["taken"], "0.1")
        self.assertEqual(self.stars(self.tr), Decimal("0.000"))
        event = RatingEvent.objects.get(user=self.tr)
        self.assertEqual(event.delta, Decimal("-0.100"))
        penalties.decide(event.pk, self.hr, "forgive")
        self.assertEqual(self.stars(self.tr), Decimal("0.100"))

    def test_hr_can_forgive_what_the_leader_accepted(self):
        self.check(self.three)
        self.post(self.lead, {"issues": [0]})
        event = RatingEvent.objects.get(user=self.tr)
        penalties.decide(event.pk, self.hr, "forgive")
        self.assertEqual(self.stars(self.tr), Decimal("5.000"))


class OnceTests(_Accept):
    def test_a_note_costs_once_however_often_it_is_pressed(self):
        self.check(self.three)
        self.post(self.lead, {"issues": [0]})
        again = self.post(self.lead, {"issues": [0]})
        self.assertEqual((again.status_code, _json(again)["error"]), (409, "already"))
        self.assertEqual(self.stars(self.tr), Decimal("4.875"))
        self.assertEqual(RatingEvent.objects.filter(user=self.tr).count(), 1)

    def test_only_the_notes_not_accepted_before_are_charged(self):
        check = self.check(self.three)
        self.post(self.lead, {"issues": [0]})
        self.post(self.lead, {"all": True})
        self.assertEqual(self.stars(self.tr), Decimal("4.625"))
        check.refresh_from_db()
        self.assertEqual(check.accepted, [0, 1, 2])
        self.assertEqual(RatingEvent.objects.filter(user=self.tr).count(), 2)
        self.assertEqual(self.post(self.lead, {"all": True}).status_code, 409)
        self.assertEqual(self.stars(self.tr), Decimal("4.625"))

    def test_a_new_check_has_notes_that_cost_again(self):
        self.check(self.three)
        self.post(self.lead, {"all": True})
        self.check([issue("fresh")])
        self.assertEqual(self.post(self.lead, {"issues": [0]}).status_code, 200)
        self.assertEqual(self.stars(self.tr), Decimal("4.500"))


class RefusalTests(_Accept):
    def test_nobody_else_accepts_and_nothing_is_taken(self):
        self.check(self.three)
        for user in (self.ops, self.tr, self.hr, self.reviewer, self.accounting, self.sales):
            self.assertEqual(self.post(user, {"all": True}).status_code, 403, user.username)
        self.assertEqual(self.post(None, {"all": True}).status_code, 401)
        self.assertEqual(self.stars(self.tr), Decimal("5.000"))
        self.assertEqual(RatingEvent.objects.count(), 0)

    def test_another_leaders_task_is_a_404_and_a_row_in_the_audit_log(self):
        self.check(self.three)
        self.assertEqual(self.post(self.other_lead, {"all": True}).status_code, 404)
        self.assertTrue(AuditLog.objects.filter(actor=self.other_lead, action__startswith="security.denied").exists())
        self.assertEqual(self.stars(self.tr), Decimal("5.000"))

    def test_the_translator_cannot_charge_themselves_or_anybody_by_this_door(self):
        self.check(self.three)
        self.post(self.tr, {"all": True})
        self.assertEqual(RatingEvent.objects.count(), 0)

    def test_ids_must_be_notes_of_this_check_and_are_unique(self):
        check = self.check(self.three)
        for bad in ([3], [-1], [True], ["0"], [1.5], [None], "0", 0, {"a": 1}, [0] * 101):
            self.assertEqual(self.post(self.lead, {"issues": bad}).status_code, 400, bad)
        self.assertEqual(RatingEvent.objects.count(), 0)
        self.post(self.lead, {"issues": [2, 0, 2, 0]})
        check.refresh_from_db()
        self.assertEqual(check.accepted, [0, 2])
        self.assertEqual(self.stars(self.tr), Decimal("4.750"))

    def test_nothing_accepted_is_refused_and_all_must_be_the_true_flag(self):
        self.check(self.three)
        refused = self.post(self.lead, {"issues": []})
        self.assertEqual((refused.status_code, _json(refused)["error"]), (400, "nothing_accepted"))
        for flag in ("true", 1, "all"):
            self.assertEqual(self.post(self.lead, {"all": flag}).status_code, 400, flag)
        self.assertEqual(RatingEvent.objects.count(), 0)

    def test_a_body_that_is_not_json_or_not_an_object_is_refused(self):
        self.check(self.three)
        for raw in ("not json", "[1]", "5"):
            self.assertEqual(self.post(self.lead, raw=raw).status_code, 400, raw)

    def test_a_request_must_name_the_check_it_read_and_it_must_be_the_latest(self):
        old = self.check(self.three)
        self.check([issue("other one"), issue("other two"), issue("other three")])
        stale = self.post(self.lead, {"issues": [0, 2], "check": old.pk})
        self.assertEqual((stale.status_code, _json(stale)["error"]), (409, "stale_check"))
        for body in ({"all": True}, {"all": True, "check": "1"}, {"all": True, "check": True}, {"all": True, "check": None}):
            self.assertEqual(self.post(self.lead, raw=json.dumps(body)).status_code, 400, body)
        self.assertEqual(RatingEvent.objects.count(), 0)

    def test_a_check_with_no_notes_or_no_check_at_all_has_nothing_to_accept(self):
        none = self.post(self.lead, {"all": True})
        self.assertEqual((none.status_code, _json(none)["error"]), (400, "no_notes"))
        self.check([], status=AICheckResult.Status.CLEAN)
        clean = self.post(self.lead, {"all": True})
        self.assertEqual((clean.status_code, _json(clean)["error"]), (400, "no_notes"))
        self.assertEqual(RatingEvent.objects.count(), 0)

    def test_a_task_nobody_holds_has_no_translator_to_charge(self):
        self.check(self.three)
        self.task.translator = None
        self.task.save(update_fields=["translator"])
        answer = self.post(self.lead, {"all": True})
        self.assertEqual((answer.status_code, _json(answer)["error"]), (409, "no_translator"))
        self.assertEqual(RatingEvent.objects.count(), 0)
        check = AICheckResult.objects.get()
        self.assertEqual(check.accepted, [])

    def test_all_is_capped_at_the_most_one_press_carries(self):
        check = self.check([issue(f"n{number}") for number in range(ai.MAX_ACCEPTED + 10)])
        self.post(self.lead, {"all": True})
        check.refresh_from_db()
        self.assertEqual(len(check.accepted), ai.MAX_ACCEPTED)

    def test_it_is_a_post_on_the_new_address(self):
        self.check(self.three)
        browser = DjangoClient()
        browser.force_login(self.lead)
        self.assertEqual(browser.get(reverse(ACCEPT, args=[self.task.code])).status_code, 405)
        self.assertEqual(reverse(ACCEPT, args=["TSK-1"]), "/api/v1/tasks/TSK-1/ai-notes/accept/")
        self.assertEqual(self.stars(self.tr), Decimal("5.000"))


class BoxTests(_Accept):
    def test_the_box_says_what_accepting_costs_and_who_pays_before_anything_is_pressed(self):
        self.check(self.three)
        body = self.notes()
        self.assertTrue(body["can_accept"])
        self.assertEqual(body["accept_cost"], {"each": "0.125", "translator": self.tr.short_name})
        self.assertEqual([one["accepted"] for one in body["issues"]], [False, False, False])
        self.assertEqual(self.stars(self.tr), Decimal("5.000"))

    def test_an_accepted_note_is_marked_and_the_box_stops_offering_when_none_is_left(self):
        self.check(self.three)
        self.post(self.lead, {"issues": [1]})
        body = self.notes()
        by_id = {one["id"]: one["accepted"] for one in body["issues"]}
        self.assertEqual(by_id, {0: False, 1: True, 2: False})
        self.assertTrue(body["can_accept"])
        self.post(self.lead, {"all": True})
        self.assertFalse(self.notes()["can_accept"])

    def test_the_box_cannot_accept_for_a_clean_check_or_a_task_nobody_holds(self):
        self.check([], status=AICheckResult.Status.CLEAN)
        self.assertFalse(self.notes()["can_accept"])
        self.check(self.three)
        self.task.translator = None
        self.task.save(update_fields=["translator"])
        body = self.notes()
        self.assertFalse(body["can_accept"])
        self.assertIsNone(body["accept_cost"]["translator"])

    def test_the_ids_are_places_in_the_check_not_places_on_the_screen(self):
        self.check(self.three)
        body = self.notes()
        self.assertEqual([one["id"] for one in body["issues"]], [0, 2, 1])
        self.assertEqual([one["severity"] for one in body["issues"]], ["high", "medium", "low"])

    def test_nobody_but_the_leader_and_the_admin_reads_the_box_still(self):
        self.check(self.three)
        self.assertEqual(self.get(self.tr, NOTES, [self.task.code]).status_code, 403)
        self.assertEqual(self.get(self.other_lead, NOTES, [self.task.code]).status_code, 404)


class GoneTests(_Accept):
    def test_the_corrected_copy_of_a_translation_is_not_made_any_more(self):
        from django.apps import apps

        with self.assertRaises(LookupError):
            apps.get_model("dashboard", "AIRevision")
        self.assertFalse(hasattr(ai, "start_revision"))
        self.assertFalse(hasattr(ai, "build_docx"))
        with self.assertRaises(Exception):
            reverse("dashboard:v1_ai_revise", args=["TSK-1"])
        from . import files

        self.assertEqual(files.owner_of("revisions/2026/10/none.docx"), [])
        self.assertFalse(files.may_open(self.lead, "revisions/2026/10/none.docx")[0])


class StatusWordsTests(_Accept):
    def test_a_reviewed_task_reads_as_waiting_for_delivery_to_the_client(self):
        from .templatetags.eagle_tags import STATUS_MAP

        tone, ar, en = STATUS_MAP["reviewed"]
        self.assertEqual((tone, ar, en), ("wait", "بانتظار التسليم للعميل", "Awaiting delivery to the client"))
        # The word is the status's own, so every screen that draws it says the same.
        from .models import TaskStatus

        self.assertEqual(TaskStatus.REVIEWED.label, "Awaiting delivery to the client")
        self.assertEqual(TaskStatus.REVIEWED.value, "reviewed")
