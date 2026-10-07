"""Star penalties in front of HR and the admin: seen with the amount and the reason, then applied or forgiven.

The stars come off the moment a penalty is written (the assignment order reads them). What HR and the admin decide is whether it
stands: apply it (it is only marked, the stars are already gone) or forgive it (the stars go back, up to the company's maximum, and
the person is told). What these tests hold: a penalty is decided once, only HR and the admin decide, HR cannot decide a penalty of
their own, a forgiven one stops counting as a rating drop, the door answers a task by its code and never by its title, and the
register and the file say what is waiting.
"""

import json
from datetime import timedelta
from decimal import Decimal

from django.test import Client as DjangoClient
from django.urls import reverse
from django.utils import timezone

from . import penalties, services
from .models import AppSettings, AuditLog, Notification, RatingEvent, Role, TaskStatus, User
from .tests_api_v1 import CLIENT_NAME, CLIENT_PHONE, _json, _Site

LIST = "dashboard:v1_hr_penalties"
DECIDE = "dashboard:v1_hr_penalty_decide"
EMPLOYEE = "dashboard:v1_hr_employee"
REGISTER = "dashboard:v1_hr_register"


class _Penalties(_Site):
    def setUp(self):
        super().setUp()
        self.hr_two = User.objects.create_user("person_hr_second", password="pw", role=Role.HR)
        self.tr.apply_penalty(self.task, "No response within 60s on TSK", "لم يرد خلال 60 ثانية على TSK")
        self.tr.refresh_from_db()
        self.event = RatingEvent.objects.get(user=self.tr)

    def browser(self, user):
        browser = DjangoClient()
        if user is not None:
            browser.force_login(user)
        return browser

    def listing(self, who, **query):
        return self.browser(who).get(reverse(LIST), query)

    def decide(self, user, action, pk=None, body=None, raw=None):
        pk = pk if pk is not None else self.event.pk
        data = raw if raw is not None else json.dumps(body if body is not None else {})
        return self.browser(user).post(reverse(DECIDE, args=[pk, action]), data=data, content_type="application/json")

    def fresh(self):
        self.event.refresh_from_db()
        self.tr.refresh_from_db()


class WrittenTests(_Penalties):
    def test_a_penalty_takes_the_stars_at_once_and_waits_for_a_decision(self):
        self.assertEqual(self.tr.rating, Decimal("4.875"))
        self.assertEqual(self.event.delta, Decimal("-0.125"))
        self.assertEqual(self.event.decision, RatingEvent.Decision.PENDING)
        self.assertIsNone(self.event.decided_by)

    def test_hr_and_the_admin_are_told_with_the_amount_the_reason_and_where_to_decide(self):
        for person in (self.hr, self.hr_two, self.admin):
            note = Notification.objects.get(user=person, title_en="Stars taken off an employee")
            self.assertIn("0.125", note.body_en)
            self.assertIn("No response within 60s on TSK", note.body_en)
            self.assertIn("لم يرد خلال 60 ثانية", note.body_ar)
            self.assertEqual(note.url, f"/hr/employees/{self.tr.pk}/")
        # Nobody else hears of it: not the operation, the leader, nor the person (who has their own notice on expiry).
        for person in (self.ops, self.lead, self.tr, self.accounting, self.sales, self.reviewer):
            self.assertFalse(Notification.objects.filter(user=person, title_en="Stars taken off an employee").exists(), person.username)

    def test_an_hr_person_who_lost_stars_is_not_asked_to_decide_it_by_a_notice(self):
        Notification.objects.all().delete()
        self.hr.apply_penalty(self.task, "late", "اتأخر")
        self.assertFalse(Notification.objects.filter(user=self.hr, title_en="Stars taken off an employee").exists())
        self.assertTrue(Notification.objects.filter(user=self.hr_two, title_en="Stars taken off an employee").exists())

    def test_a_missed_assignment_goes_the_whole_way(self):
        inbound = services.ingest_message(channel="whatsapp", body="again", sender_identity=CLIENT_PHONE)
        task = services.create_task(
            client=self.client_obj, title="Second", created_by=self.ops,
            deadline=timezone.now() + timedelta(hours=3), messages=[inbound],
        )
        services.accept_assignment(services.assign_to_lead(task, self.lead, self.ops), self.lead)
        offer = services.assign_to_translator(task, self.tr, self.lead)
        before = RatingEvent.objects.filter(user=self.tr).count()
        services.expire_assignment(offer)
        events = RatingEvent.objects.filter(user=self.tr)
        self.assertEqual(events.count(), before + 1)
        newest = events.order_by("-id").first()
        self.assertEqual(newest.decision, RatingEvent.Decision.PENDING)
        self.assertEqual(newest.task, task)
        self.assertTrue(Notification.objects.filter(user=self.admin, task=task, title_en="Stars taken off an employee").exists())


class ListTests(_Penalties):
    def test_hr_and_the_admin_read_the_waiting_ones_with_amount_reason_and_task_code(self):
        for user in (self.hr, self.admin):
            answer = self.listing(user)
            self.assertEqual(answer.status_code, 200, user.username)
            self.assertEqual(answer["Cache-Control"], "private, no-store")
            body = _json(answer)
            self.assertEqual(body["waiting"], 1)
            row = body["rows"][0]
            self.assertEqual(row["id"], self.event.pk)
            self.assertEqual(row["amount"], "0.125")
            self.assertEqual(row["user"], {"id": self.tr.pk, "name": self.tr.short_name})
            self.assertEqual(row["task"], self.task.code)
            self.assertEqual(row["reason"], {"ar": self.event.reason_ar, "en": self.event.reason_en})
            self.assertEqual(row["decision"]["value"], "pending")

    def test_nobody_else_reads_it(self):
        for user in (self.ops, self.lead, self.tr, self.reviewer, self.accounting, self.sales):
            self.assertEqual(self.listing(user).status_code, 403, user.username)
        self.assertEqual(self.listing(None).status_code, 401)

    def test_the_decided_are_left_out_unless_asked_for_and_the_count_is_of_the_waiting(self):
        penalties.decide(self.event.pk, self.hr, "confirm")
        self.tr.apply_penalty(self.task, "again", "تاني")
        waiting = _json(self.listing(self.hr))
        self.assertEqual((len(waiting["rows"]), waiting["waiting"]), (1, 1))
        everything = _json(self.listing(self.hr, status="all"))
        self.assertEqual(len(everything["rows"]), 2)
        self.assertEqual(everything["waiting"], 1)

    def test_one_persons_penalties_by_id_and_a_bad_id_is_refused(self):
        self.lead.apply_penalty(self.task, "lead late", "الليدر اتأخر")
        mine = _json(self.listing(self.hr, user=self.tr.pk, status="all"))["rows"]
        self.assertEqual({row["user"]["id"] for row in mine}, {self.tr.pk})
        self.assertEqual(self.listing(self.hr, user="abc").status_code, 400)
        self.assertEqual(self.listing(self.hr, user="9" * 30).status_code, 400)

    def test_it_reaches_the_new_door_and_not_a_removed_address(self):
        # A test that hits a removed address passes blind: the path has to be the one the app calls.
        self.assertEqual(reverse(LIST), "/api/v1/hr/penalties/")
        self.assertEqual(reverse(DECIDE, args=[3, "forgive"]), "/api/v1/hr/penalties/3/forgive/")
        self.assertEqual(self.listing(self.hr).status_code, 200)

    def test_a_task_is_named_by_its_code_and_nothing_of_the_client_reaches_hr(self):
        self.task.title = f"Contract for {CLIENT_NAME}"
        self.task.save(update_fields=["title"])
        text = self.listing(self.hr, status="all").content.decode("utf-8")
        self.assertNotIn(CLIENT_NAME, text)
        self.assertNotIn(CLIENT_PHONE, text)
        file_text = self.browser(self.hr).get(reverse(EMPLOYEE, args=[self.tr.pk])).content.decode("utf-8")
        self.assertNotIn(CLIENT_NAME, file_text)

    def test_a_listing_writes_nothing(self):
        before = (RatingEvent.objects.count(), AuditLog.objects.count(), Notification.objects.count())
        self.listing(self.hr)
        self.assertEqual((RatingEvent.objects.count(), AuditLog.objects.count(), Notification.objects.count()), before)


class DecideTests(_Penalties):
    def test_forgiving_gives_the_stars_back_marks_who_and_tells_the_person(self):
        answer = self.decide(self.hr, "forgive", body={"note": "عذر مقبول"})
        self.assertEqual(answer.status_code, 200)
        self.fresh()
        self.assertEqual(self.tr.rating, Decimal("5.000"))
        self.assertEqual(self.event.decision, RatingEvent.Decision.FORGIVEN)
        self.assertEqual(self.event.decided_by, self.hr)
        self.assertIsNotNone(self.event.decided_at)
        self.assertEqual(self.event.decision_note, "عذر مقبول")
        row = _json(answer)["penalty"]
        self.assertEqual((row["decision"]["value"], row["decided_by"], row["note"]), ("forgiven", self.hr.short_name, "عذر مقبول"))
        told = Notification.objects.get(user=self.tr, title_en="A penalty was forgiven")
        self.assertIn("0.125", told.body_en)
        self.assertEqual(told.level, "success")
        self.assertTrue(AuditLog.objects.filter(actor=self.hr, action="rating.forgive", target=self.tr.username).exists())

    def test_applying_keeps_the_stars_off_and_tells_the_person(self):
        answer = self.decide(self.admin, "confirm")
        self.assertEqual(answer.status_code, 200)
        self.fresh()
        self.assertEqual(self.tr.rating, Decimal("4.875"))
        self.assertEqual(self.event.decision, RatingEvent.Decision.CONFIRMED)
        self.assertEqual(self.event.decided_by, self.admin)
        self.assertTrue(Notification.objects.filter(user=self.tr, title_en="A penalty was applied", level="danger").exists())
        self.assertTrue(AuditLog.objects.filter(actor=self.admin, action="rating.confirm").exists())

    def test_forgiving_never_lifts_a_person_over_the_company_maximum(self):
        User.objects.filter(pk=self.tr.pk).update(rating=Decimal("5.000"))
        self.assertEqual(self.decide(self.hr, "forgive").status_code, 200)
        self.fresh()
        self.assertEqual(self.tr.rating, Decimal("5.000"))
        conf = AppSettings.load()
        conf.max_rating = Decimal("4.900")
        conf.save()
        self.tr.apply_penalty(self.task, "again", "تاني")
        self.tr.refresh_from_db()
        second = RatingEvent.objects.filter(user=self.tr).order_by("-id").first()
        penalties.decide(second.pk, self.hr, "forgive")
        self.tr.refresh_from_db()
        self.assertEqual(self.tr.rating, Decimal("4.900"))

    def test_a_penalty_is_decided_once_and_the_stars_are_not_given_back_twice(self):
        self.assertEqual(self.decide(self.hr, "forgive").status_code, 200)
        self.fresh()
        stars = self.tr.rating
        for action in ("forgive", "confirm"):
            answer = self.decide(self.hr_two, action)
            self.assertEqual(answer.status_code, 409, action)
            self.assertEqual(_json(answer)["error"], "decided")
        self.fresh()
        self.assertEqual(self.tr.rating, stars)
        self.assertEqual(self.event.decision, RatingEvent.Decision.FORGIVEN)
        self.assertEqual(self.event.decided_by, self.hr)

    def test_a_decided_penalty_is_not_decided_the_other_way_round(self):
        self.decide(self.hr, "confirm")
        self.assertEqual(self.decide(self.hr, "forgive").status_code, 409)
        self.fresh()
        self.assertEqual(self.tr.rating, Decimal("4.875"))

    def test_only_hr_and_the_admin_decide_and_nothing_is_written_for_the_rest(self):
        for user in (self.ops, self.lead, self.tr, self.reviewer, self.accounting, self.sales):
            for action in ("forgive", "confirm"):
                self.assertEqual(self.decide(user, action).status_code, 403, user.username)
        self.assertEqual(self.decide(None, "forgive").status_code, 401)
        self.fresh()
        self.assertEqual(self.event.decision, RatingEvent.Decision.PENDING)
        self.assertEqual(self.tr.rating, Decimal("4.875"))

    def test_the_person_cannot_forgive_their_own_penalty_by_any_road(self):
        self.assertEqual(self.decide(self.tr, "forgive").status_code, 403)
        self.assertEqual(penalties.decide(self.event.pk, self.tr, "forgive"), (None, "forbidden"))
        self.fresh()
        self.assertEqual(self.tr.rating, Decimal("4.875"))

    def test_hr_cannot_decide_a_penalty_of_their_own_but_the_admin_can(self):
        self.hr.apply_penalty(self.task, "late", "اتأخر")
        own = RatingEvent.objects.get(user=self.hr)
        refused = self.decide(self.hr, "forgive", pk=own.pk)
        self.assertEqual((refused.status_code, _json(refused)["error"]), (409, "own_record"))
        self.hr.refresh_from_db()
        self.assertEqual(self.hr.rating, Decimal("4.875"))
        self.assertEqual(self.decide(self.hr_two, "forgive", pk=own.pk).status_code, 200)
        self.hr.refresh_from_db()
        self.assertEqual(self.hr.rating, Decimal("5.000"))
        self.admin.apply_penalty(self.task, "x", "س")
        mine = RatingEvent.objects.get(user=self.admin)
        self.assertEqual(self.decide(self.admin, "forgive", pk=mine.pk).status_code, 200)

    def test_the_odd_requests_are_refused_and_change_nothing(self):
        cases = (
            (self.decide(self.hr, "approve"), 400),
            (self.decide(self.hr, "forgive", pk=999999), 404),
            (self.decide(self.hr, "forgive", body={"note": "x" * 201}), 400),
            (self.decide(self.hr, "forgive", body={"note": 5}), 400),
            (self.decide(self.hr, "forgive", raw="not json"), 400),
            (self.decide(self.hr, "forgive", raw="[1]"), 400),
        )
        for answer, status in cases:
            self.assertEqual(answer.status_code, status, answer.content)
        self.fresh()
        self.assertEqual(self.event.decision, RatingEvent.Decision.PENDING)
        self.assertEqual(self.tr.rating, Decimal("4.875"))

    def test_a_get_is_not_a_decision(self):
        answer = self.browser(self.hr).get(reverse(DECIDE, args=[self.event.pk, "forgive"]))
        self.assertEqual(answer.status_code, 405)
        self.fresh()
        self.assertEqual(self.event.decision, RatingEvent.Decision.PENDING)

    def test_an_inactive_hr_account_decides_nothing(self):
        User.objects.filter(pk=self.hr_two.pk).update(is_active=False)
        self.hr_two.refresh_from_db()
        self.assertEqual(penalties.decide(self.event.pk, self.hr_two, "forgive"), (None, "forbidden"))

    def test_the_note_is_kept_to_its_length_and_may_be_empty(self):
        self.assertEqual(self.decide(self.hr, "confirm").status_code, 200)
        self.fresh()
        self.assertEqual(self.event.decision_note, "")

    def test_a_forgiven_penalty_no_longer_counts_as_a_rating_drop(self):
        from . import performance

        today = timezone.localdate()
        first, last = today.replace(day=1), today
        self.assertEqual(performance.quality(self.tr, first, last)["rating_drops"], 1)
        self.decide(self.hr, "forgive")
        self.assertEqual(performance.quality(self.tr, first, last)["rating_drops"], 0)
        # Applied, it still counts.
        self.tr.apply_penalty(self.task, "again", "تاني")
        newest = RatingEvent.objects.filter(user=self.tr).order_by("-id").first()
        self.decide(self.hr, "confirm", pk=newest.pk)
        self.assertEqual(performance.quality(self.tr, first, last)["rating_drops"], 1)


class WhatWasTakenTests(_Penalties):
    def test_a_person_near_nought_loses_less_and_forgiving_gives_back_only_that(self):
        User.objects.filter(pk=self.tr.pk).update(rating=Decimal("0.050"))
        self.tr.refresh_from_db()
        self.tr.apply_penalty(self.task, "again", "تاني")
        self.tr.refresh_from_db()
        self.assertEqual(self.tr.rating, Decimal("0.000"))
        newest = RatingEvent.objects.filter(user=self.tr).order_by("-id").first()
        self.assertEqual(newest.delta, Decimal("-0.050"))
        row = _json(self.listing(self.hr))["rows"][0]
        self.assertEqual(row["amount"], "0.05")
        self.decide(self.hr, "forgive", pk=newest.pk)
        self.tr.refresh_from_db()
        self.assertEqual(self.tr.rating, Decimal("0.050"))

    def test_a_person_already_at_nought_loses_nothing_and_gets_nothing_back(self):
        User.objects.filter(pk=self.tr.pk).update(rating=Decimal("0.000"))
        self.tr.refresh_from_db()
        self.tr.apply_penalty(self.task, "again", "تاني")
        newest = RatingEvent.objects.filter(user=self.tr).order_by("-id").first()
        self.assertEqual(newest.delta, Decimal("0.000"))
        self.decide(self.hr, "forgive", pk=newest.pk)
        self.tr.refresh_from_db()
        self.assertEqual(self.tr.rating, Decimal("0.000"))

    def test_a_superuser_with_another_role_may_decide_as_the_admin_does_elsewhere(self):
        boss = User.objects.create_user("person_boss", password="pw", role=Role.OPERATION, is_superuser=True)
        self.assertTrue(penalties.may_decide(boss) == boss.is_admin_role)


class FileAndRegisterTests(_Penalties):
    def file(self, user, person=None):
        return _json(self.browser(user).get(reverse(EMPLOYEE, args=[(person or self.tr).pk])))

    def test_the_file_lists_the_penalties_to_hr_and_the_admin_with_what_they_may_do(self):
        for user in (self.hr, self.admin):
            body = self.file(user)
            self.assertTrue(body["can"]["decide_penalties"], user.username)
            self.assertEqual([row["id"] for row in body["penalties"]], [self.event.pk])
            self.assertEqual(body["penalties"][0]["amount"], "0.125")

    def test_a_decided_penalty_stays_on_the_file_with_who_decided(self):
        self.decide(self.hr, "forgive", body={"note": "ok"})
        row = self.file(self.admin)["penalties"][0]
        self.assertEqual((row["decision"]["value"], row["decided_by"], row["note"]), ("forgiven", self.hr.short_name, "ok"))

    def test_the_owner_has_no_rating_so_no_penalty_list(self):
        self.assertEqual(self.file(self.hr, self.admin)["penalties"], [])

    def test_the_register_counts_what_waits_beside_each_person(self):
        self.tr.apply_penalty(self.task, "again", "تاني")
        rows = {row["id"]: row for row in _json(self.browser(self.hr).get(reverse(REGISTER)))["rows"]}
        self.assertEqual(rows[self.tr.pk]["penalties_waiting"], 2)
        self.assertEqual(rows[self.lead.pk]["penalties_waiting"], 0)
        penalties.decide(self.event.pk, self.hr, "forgive")
        rows = {row["id"]: row for row in _json(self.browser(self.admin).get(reverse(REGISTER)))["rows"]}
        self.assertEqual(rows[self.tr.pk]["penalties_waiting"], 1)
        # The owner has no rating: a count would be a nought that means nothing.
        self.assertEqual(rows[self.admin.pk]["penalties_waiting"], 0)

    def test_the_register_does_not_ask_the_database_once_a_person(self):
        from django.db import connection
        from django.test.utils import CaptureQueriesContext

        def queries():
            with CaptureQueriesContext(connection) as captured:
                self.browser(self.hr).get(reverse(REGISTER))
            return len(captured)

        before = queries()
        for index in range(6):
            person = User.objects.create_user(f"person_extra_{index}", password="pw", role=Role.TRANSLATOR, team_lead=self.lead)
            person.apply_penalty(self.task, "x", "س")
        self.assertLessEqual(queries(), before + 1)

    def test_the_employees_own_desk_says_a_forgiven_penalty_was_forgiven(self):
        self.decide(self.hr, "forgive")
        events = _json(self.browser(self.tr).get(reverse("dashboard:v1_translator_home")))["rating_events"]
        self.assertEqual(events[0]["decision"], "forgiven")
        self.assertEqual(events[0]["delta"], "-0.125")


class OldRowsTests(_Penalties):
    def test_penalties_written_before_this_stand_and_are_not_put_to_hr(self):
        import importlib

        from django.apps import apps

        RatingEvent.objects.update(decision=RatingEvent.Decision.PENDING)
        migration = importlib.import_module("dashboard.migrations.0051_penalty_decision_and_ai_revision")
        migration.old_penalties_stand(apps, None)
        self.assertEqual(RatingEvent.objects.get(pk=self.event.pk).decision, RatingEvent.Decision.CONFIRMED)

    def test_a_task_is_not_needed_for_a_penalty(self):
        self.assertEqual(self.task.status, TaskStatus.IN_PROGRESS)
        self.tr.apply_penalty(None, "x", "س")
        newest = RatingEvent.objects.filter(user=self.tr).order_by("-id").first()
        self.assertIsNone(newest.task)
        row = _json(self.listing(self.hr))["rows"][0]
        self.assertIn(row["task"], (None, self.task.code))


class AdminChangesADecisionTests(_Penalties):
    """What HR decides once, the owner may take back: forgive what stands, apply again what was forgiven (07/10/2026)."""

    def test_the_admin_forgives_what_was_applied_and_the_stars_come_back(self):
        self.decide(self.hr, "confirm")
        self.fresh()
        self.assertEqual(self.tr.rating, Decimal("4.875"))
        answer = self.decide(self.admin, "forgive", body={"note": "changed my mind"})
        self.assertEqual(answer.status_code, 200)
        self.fresh()
        self.assertEqual(self.tr.rating, Decimal("5.000"))
        self.assertEqual((self.event.decision, self.event.decided_by), (RatingEvent.Decision.FORGIVEN, self.admin))
        self.assertEqual(self.event.decision_note, "changed my mind")
        self.assertTrue(Notification.objects.filter(user=self.tr, title_en="A penalty was forgiven").exists())
        log = AuditLog.objects.filter(action="rating.forgive", actor=self.admin).get()
        self.assertIn("(was confirmed)", log.detail)

    def test_the_admin_applies_again_what_was_forgiven_and_the_stars_go_off_again(self):
        self.decide(self.hr, "forgive")
        self.fresh()
        self.assertEqual(self.tr.rating, Decimal("5.000"))
        self.assertEqual(self.decide(self.admin, "confirm").status_code, 200)
        self.fresh()
        self.assertEqual(self.tr.rating, Decimal("4.875"))
        self.assertEqual(self.event.decision, RatingEvent.Decision.CONFIRMED)
        self.assertTrue(Notification.objects.filter(user=self.tr, title_en="A penalty was applied").exists())

    def test_turning_it_round_twice_leaves_the_stars_where_they_were(self):
        self.decide(self.hr, "confirm")
        for action in ("forgive", "confirm", "forgive", "confirm"):
            self.assertEqual(self.decide(self.admin, action).status_code, 200, action)
        self.fresh()
        self.assertEqual(self.tr.rating, Decimal("4.875"))
        self.assertEqual(self.event.decision, RatingEvent.Decision.CONFIRMED)

    def test_what_stands_already_is_not_decided_again_so_the_stars_are_not_given_back_twice(self):
        self.decide(self.admin, "forgive")
        self.fresh()
        stars = self.tr.rating
        for who in (self.admin, self.hr):
            answer = self.decide(who, "forgive")
            self.assertEqual((answer.status_code, _json(answer)["error"]), (409, "decided"), who.username)
        self.fresh()
        self.assertEqual(self.tr.rating, stars)

    def test_hr_still_decides_once_and_cannot_turn_a_decision_round(self):
        self.decide(self.hr, "confirm")
        for who in (self.hr, self.hr_two):
            answer = self.decide(who, "forgive")
            self.assertEqual((answer.status_code, _json(answer)["error"]), (409, "decided"), who.username)
        self.fresh()
        self.assertEqual((self.event.decision, self.tr.rating), (RatingEvent.Decision.CONFIRMED, Decimal("4.875")))

    def test_nobody_else_turns_a_decision_round(self):
        self.decide(self.hr, "confirm")
        for user in (self.ops, self.lead, self.tr, self.accounting):
            self.assertEqual(self.decide(user, "forgive").status_code, 403, user.username)
        self.fresh()
        self.assertEqual(self.event.decision, RatingEvent.Decision.CONFIRMED)

    def test_applying_again_never_takes_the_stars_below_nought(self):
        self.decide(self.hr, "forgive")
        User.objects.filter(pk=self.tr.pk).update(rating=Decimal("0.050"))
        self.decide(self.admin, "confirm")
        self.fresh()
        self.assertEqual(self.tr.rating, Decimal("0.000"))

    def test_forgiving_never_lifts_the_stars_above_the_companys_maximum(self):
        self.decide(self.hr, "confirm")
        User.objects.filter(pk=self.tr.pk).update(rating=AppSettings.load().max_rating)
        self.decide(self.admin, "forgive")
        self.fresh()
        self.assertEqual(self.tr.rating, AppSettings.load().max_rating)

    def test_the_file_says_who_may_turn_a_decision_round(self):
        for who, expected in ((self.admin, True), (self.hr, False)):
            browser = self.browser(who)
            body = _json(browser.get(reverse(EMPLOYEE, args=[self.tr.pk])))
            self.assertEqual(body["can"]["change_penalties"], expected, who.username)
            self.assertTrue(body["can"]["decide_penalties"], who.username)
