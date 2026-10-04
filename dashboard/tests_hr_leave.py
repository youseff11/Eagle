"""Leave in the new app: a person's own balance and requests, the HR queue, and the decision.

What these tests hold: a request is only ever the person's own (nothing names anybody else, and one that is not theirs is not
there), a decision is the manager's or HR's or the admin's and a stranger is told the request does not exist (and it is written
down), the engine decides the steps and the days an approval writes, a GET changes nothing, and the new pages are reached only
by who their switch is on for.
"""

import json
from datetime import time, timedelta

from django.db import connection
from django.test import Client as DjangoClient
from django.test.utils import CaptureQueriesContext
from django.urls import reverse
from django.utils import timezone

from . import attendance, employees, identity, newui
from .models import (
    AppSettings, AuditLog, LeaveRequest, LeaveStatus, Notification, PayrollSettings, ShiftTemplate, User, WorkDay,
)
from .tests_api_v1 import _json
from .tests_hr_attendance import _Hr

MINE = "dashboard:v1_leave"
ASK = "dashboard:v1_leave_request"
CANCEL = "dashboard:v1_leave_cancel"
DECIDE = "dashboard:v1_leave_decide"
QUEUE = "dashboard:v1_hr_leave"


class _Leave(_Hr):
    def setUp(self):
        super().setUp()
        self.morning = ShiftTemplate.objects.create(name="Morning", name_ar="الصبح", start_time=time(9), end_time=time(17))
        attendance.assign_shift(self.tr, self.morning, range(7))
        self.start = self.today + timedelta(days=10)

    def needs_manager(self, on):
        conf = PayrollSettings.load()
        conf.leave_needs_manager = on
        conf.save()

    def ask_for(self, person=None, days=2, **over):
        start = over.pop("start_date", self.start)
        values = dict(kind="annual", start_date=start, end_date=start + timedelta(days=days - 1), actor=person or self.tr)
        values.update(over)
        return employees.request_leave(person or self.tr, **values)

    def read(self, name, who, args=None, **query):
        browser = DjangoClient()
        browser.force_login(who)
        return browser.get(reverse(name, args=args), query)


class MineTests(_Leave):
    def test_everybody_signed_in_has_their_own_page_and_nobody_else_does(self):
        for who in (self.admin, self.ops, self.lead, self.tr, self.hr, self.reviewer, self.accounting, self.sales):
            answer = self.read(MINE, who)
            self.assertEqual(answer.status_code, 200, who.username)
            self.assertIn("no-store", answer["Cache-Control"])
        self.assertEqual(DjangoClient().get(reverse(MINE)).status_code, 401)

    def test_the_balance_is_the_engines_and_the_rows_are_only_the_persons_own(self):
        mine = self.ask_for()
        self.ask_for(person=self.ops)
        body = _json(self.read(MINE, self.tr))
        figures = employees.leave_balance(self.tr, self.today.year, self.today.month)
        self.assertEqual(body["balance"], figures)
        self.assertEqual([one["id"] for one in body["rows"]], [mine.pk])
        self.assertEqual(body["needs_manager"], False)

    def test_a_request_is_drawn_with_its_kind_status_and_length(self):
        row = self.ask_for(days=3)
        entry = _json(self.read(MINE, self.tr))["rows"][0]
        self.assertEqual(entry["kind"], {"value": "annual", "ar": "إجازة اعتيادية", "en": "Annual leave"})
        self.assertEqual((entry["days"], entry["start_date"], entry["end_date"], entry["is_open"]), (3, self.start.isoformat(), (self.start + timedelta(days=2)).isoformat(), True))
        self.assertEqual(entry["status"]["value"], "manager_ok")
        self.assertEqual(entry["status"]["tone"], "info")
        self.assertEqual(row.status, LeaveStatus.MANAGER_OK)

    def test_a_permission_has_a_window_and_no_end_date_or_days(self):
        self.ask_for(kind="permission", end_date=None, start_time=time(10), end_time=time(12), days=1)
        entry = _json(self.read(MINE, self.tr))["rows"][0]
        self.assertEqual((entry["is_permission"], entry["end_date"], entry["days"], entry["minutes"]), (True, None, 0, 120))
        self.assertEqual((entry["start_time"]["ar"], entry["end_time"]["en"]), ("10:00 ص", "12:00 PM"))

    def test_the_form_speaks_both_languages_and_the_kinds_have_their_words(self):
        fields = {one["name"]: one for one in _json(self.read(MINE, self.tr))["form"]}
        self.assertEqual(list(fields), ["kind", "start_date", "end_date", "start_time", "end_time", "reason"])
        self.assertEqual((fields["start_time"]["label_ar"], fields["start_time"]["label_en"]), ("من الساعة (للإذن)", "From (permission)"))
        labels = {one["value"]: one["label_en"] for one in fields["kind"]["choices"]}
        self.assertEqual(labels["permission"], "Permission (hours)")
        self.assertEqual((fields["start_date"]["kind"], fields["start_time"]["kind"]), ("date", "time"))

    def test_only_the_latest_forty_are_listed(self):
        for number in range(45):
            LeaveRequest.objects.create(user=self.tr, kind="other", start_date=self.start + timedelta(days=number), end_date=self.start + timedelta(days=number))
        self.assertEqual(len(_json(self.read(MINE, self.tr))["rows"]), 40)

    def test_a_get_writes_nothing_and_the_queries_do_not_grow(self):
        self.ask_for()
        audit = AuditLog.objects.count()

        def queries():
            with CaptureQueriesContext(connection) as seen:
                self.read(MINE, self.tr)
            return len(seen)

        queries()
        few = queries()
        for number in range(1, 8):
            LeaveRequest.objects.create(user=self.tr, kind="other", start_date=self.start + timedelta(days=20 + number), end_date=self.start + timedelta(days=20 + number))
        self.assertEqual(queries(), few)
        self.assertEqual(AuditLog.objects.count(), audit)


class AskTests(_Leave):
    def ask(self, values, who=None):
        return self.post(who or self.tr, ASK, {"values": values})

    def test_a_request_goes_straight_to_hr_when_the_manager_is_not_in_the_chain(self):
        answer = self.ask({"start_date": self.start.isoformat(), "end_date": (self.start + timedelta(days=1)).isoformat(), "reason": "Trip"})
        self.assertEqual((answer.status_code, _json(answer)["ok"]), (200, True))
        row = LeaveRequest.objects.get(user=self.tr)
        self.assertEqual((row.status, row.kind, row.reason, row.manager), (LeaveStatus.MANAGER_OK, "annual", "Trip", self.lead))
        self.assertTrue(Notification.objects.filter(user=self.hr, url="/hr/leave/").exists())
        self.assertTrue(AuditLog.objects.filter(action="leave.request", actor=self.tr).exists())

    def test_a_request_waits_for_the_manager_first_when_the_chain_says_so(self):
        self.needs_manager(True)
        self.ask({"start_date": self.start.isoformat()})
        row = LeaveRequest.objects.get(user=self.tr)
        self.assertEqual(row.status, LeaveStatus.PENDING)
        self.assertTrue(Notification.objects.filter(user=self.lead, url="/hr/leave/").exists())
        self.assertEqual(_json(self.read(MINE, self.tr))["needs_manager"], True)

    def test_a_missing_end_date_is_the_start_date(self):
        self.ask({"start_date": self.start.isoformat()})
        row = LeaveRequest.objects.get(user=self.tr)
        self.assertEqual(row.end_date, row.start_date)

    def test_a_permission_is_one_day_with_a_window_and_the_form_asks_for_both_times(self):
        refused = self.ask({"kind": "permission", "start_date": self.start.isoformat(), "start_time": "10:00"})
        self.assertEqual((refused.status_code, "__all__" in _json(refused)["errors"]), (400, True))
        self.ask({"kind": "permission", "start_date": self.start.isoformat(), "end_date": (self.start + timedelta(days=5)).isoformat(), "start_time": "10:00", "end_time": "12:00"})
        row = LeaveRequest.objects.get(user=self.tr)
        self.assertEqual((row.end_date, row.minutes), (self.start, 120))

    def test_the_forms_rules_and_the_engines_rules_are_the_rules(self):
        before = self.ask({"start_date": self.start.isoformat(), "end_date": (self.start - timedelta(days=1)).isoformat()})
        self.assertEqual((before.status_code, "end_date" in _json(before)["errors"]), (400, True))
        self.assertEqual(self.ask({"start_date": "soon"}).status_code, 400)
        self.assertEqual(self.ask({}).status_code, 400)
        self.ask({"start_date": self.start.isoformat(), "end_date": (self.start + timedelta(days=2)).isoformat()})
        clash = self.ask({"start_date": (self.start + timedelta(days=1)).isoformat()})
        body = _json(clash)
        self.assertEqual((clash.status_code, body["error"]), (409, "refused"))
        self.assertEqual((body["message"], body["message_en"]), ("فيه طلب تاني على نفس الأيام.", "Another request already covers those days."))
        self.assertEqual(LeaveRequest.objects.filter(user=self.tr).count(), 1)

    def test_a_permission_longer_than_allowed_is_refused_in_the_engines_words(self):
        answer = self.ask({"kind": "permission", "start_date": self.start.isoformat(), "start_time": "08:00", "end_time": "20:00"})
        self.assertEqual((answer.status_code, _json(answer)["error"]), (409, "refused"))
        self.assertFalse(LeaveRequest.objects.exists())

    def test_nobody_can_ask_for_somebody_else(self):
        for values in ({"user": self.ops.pk, "start_date": self.start.isoformat()}, {"status": "approved", "start_date": self.start.isoformat()},
                       {"manager": self.admin.pk, "start_date": self.start.isoformat()}):
            self.assertEqual(self.ask(values).status_code, 400, values)
        self.assertFalse(LeaveRequest.objects.exists())

    def test_a_body_that_is_not_the_shape_is_refused(self):
        browser = DjangoClient()
        browser.force_login(self.tr)
        for body in ("{bad", json.dumps({"values": []}), json.dumps({"values": {"reason": ["a"]}})):
            self.assertEqual(browser.post(reverse(ASK), body, content_type="application/json").status_code, 400, body)
        self.assertEqual(browser.post(reverse(ASK), {"values": "{}"}).status_code, 400)
        self.assertFalse(LeaveRequest.objects.exists())

    def test_anonymous_and_the_wrong_method_are_refused(self):
        self.assertEqual(DjangoClient().post(reverse(ASK), "{}", content_type="application/json").status_code, 401)
        browser = DjangoClient()
        browser.force_login(self.tr)
        self.assertEqual(browser.get(reverse(ASK)).status_code, 405)


class CancelTests(_Leave):
    def test_a_person_withdraws_their_own_open_request(self):
        row = self.ask_for()
        answer = self.post(self.tr, CANCEL, {}, [row.pk])
        self.assertEqual((answer.status_code, _json(answer)["ok"]), (200, True))
        row.refresh_from_db()
        self.assertEqual(row.status, LeaveStatus.CANCELLED)
        self.assertTrue(AuditLog.objects.filter(action="leave.cancel", actor=self.tr).exists())

    def test_a_request_that_is_decided_stays_decided(self):
        row = self.ask_for()
        employees.decide_leave(row, self.hr, approve=True)
        answer = self.post(self.tr, CANCEL, {}, [row.pk])
        self.assertEqual((answer.status_code, _json(answer)["error"]), (409, "already_decided"))
        row.refresh_from_db()
        self.assertEqual(row.status, LeaveStatus.APPROVED)

    def test_somebody_elses_request_is_not_there(self):
        row = self.ask_for()
        for who in (self.ops, self.hr, self.admin, self.lead):
            self.assertEqual(self.post(who, CANCEL, {}, [row.pk]).status_code, 404, who.username)
        row.refresh_from_db()
        self.assertEqual(row.status, LeaveStatus.MANAGER_OK)
        self.assertEqual(self.post(self.tr, CANCEL, {}, [999999]).status_code, 404)


class DecideTests(_Leave):
    def decide(self, row, who, action="approve", note=None):
        body = {} if note is None else {"note": note}
        return self.post(who, DECIDE, body, [row.pk, action])

    def test_hr_approves_and_the_days_land_on_the_attendance_sheet(self):
        row = self.ask_for(days=2)
        answer = self.decide(row, self.hr)
        self.assertEqual((answer.status_code, _json(answer)["ok"]), (200, True))
        row.refresh_from_db()
        self.assertEqual((row.status, row.hr_decision_by), (LeaveStatus.APPROVED, self.hr))
        self.assertEqual(WorkDay.objects.filter(user=self.tr, status="leave").count(), 2)
        self.assertTrue(Notification.objects.filter(user=self.tr, url="/leave/").exists())
        self.assertTrue(AuditLog.objects.filter(action="leave.approve", actor=self.hr).exists())

    def test_hr_rejects_with_a_note_and_no_day_is_written(self):
        row = self.ask_for()
        self.decide(row, self.hr, "reject", "Busy week")
        row.refresh_from_db()
        self.assertEqual((row.status, row.decision_note), (LeaveStatus.REJECTED, "Busy week"))
        self.assertFalse(WorkDay.objects.filter(user=self.tr).exists())

    def test_the_manager_signs_first_and_hr_after_when_the_chain_says_so(self):
        self.needs_manager(True)
        row = self.ask_for()
        self.assertEqual(self.decide(row, self.lead).status_code, 200)
        row.refresh_from_db()
        self.assertEqual(row.status, LeaveStatus.MANAGER_OK)
        self.assertFalse(WorkDay.objects.filter(user=self.tr).exists())
        again = self.decide(row, self.lead)
        self.assertEqual((again.status_code, _json(again)["error"]), (409, "refused"))
        self.assertEqual(self.decide(row, self.hr).status_code, 200)
        row.refresh_from_db()
        self.assertEqual(row.status, LeaveStatus.APPROVED)

    def test_the_admin_may_decide(self):
        row = self.ask_for()
        self.assertEqual(self.decide(row, self.admin).status_code, 200)

    def test_somebody_with_nothing_to_do_with_it_is_told_it_is_not_there_and_it_is_written_down(self):
        row = self.ask_for()
        before = AuditLog.objects.filter(action=identity.ACCESS_DENIED).count()
        for who in (self.ops, self.tr, self.reviewer, self.accounting, self.sales):
            self.assertEqual(self.decide(row, who).status_code, 404, who.username)
        self.assertEqual(AuditLog.objects.filter(action=identity.ACCESS_DENIED).count(), before + 5)
        row.refresh_from_db()
        self.assertEqual(row.status, LeaveStatus.MANAGER_OK)
        self.assertFalse(WorkDay.objects.filter(user=self.tr).exists())

    def test_a_team_leader_who_is_not_the_requesters_manager_has_nothing_to_do_with_it(self):
        other = User.objects.create_user("person_other_lead", password="pw", role="team_lead")
        row = self.ask_for()
        self.assertEqual(self.decide(row, other).status_code, 404)

    def test_a_request_that_was_decided_is_not_decided_again(self):
        row = self.ask_for()
        self.decide(row, self.hr)
        again = self.decide(row, self.hr, "reject")
        body = _json(again)
        self.assertEqual((again.status_code, body["error"]), (409, "refused"))
        self.assertEqual(body["message_en"], "This request has already been decided.")
        row.refresh_from_db()
        self.assertEqual(row.status, LeaveStatus.APPROVED)

    def test_an_action_that_is_not_one_and_a_request_that_is_not_there_are_not_there(self):
        row = self.ask_for()
        self.assertEqual(self.decide(row, self.hr, "pay").status_code, 404)
        self.assertEqual(self.post(self.hr, DECIDE, {}, [999999, "approve"]).status_code, 404)

    def test_a_note_must_be_short_text(self):
        row = self.ask_for()
        for note in (5, ["a"], "x" * 251, "a\x00b"):
            self.assertEqual(self.decide(row, self.hr, "reject", note).status_code, 400, note)
        row.refresh_from_db()
        self.assertEqual(row.status, LeaveStatus.MANAGER_OK)

    def test_a_day_the_person_actually_punched_is_not_overwritten(self):
        row = self.ask_for(days=1)
        WorkDay.objects.create(user=self.tr, date=self.start, status="present", check_in=timezone.now())
        self.decide(row, self.hr)
        self.assertEqual(WorkDay.objects.get(user=self.tr, date=self.start).status, "present")


class QueueTests(_Leave):
    def test_hr_the_admin_and_the_flag_holder_are_answered_and_nobody_else(self):
        for who in (self.hr, self.admin, self.flagged):
            self.assertEqual(self.read(QUEUE, who).status_code, 200, who.username)
        for who in (self.ops, self.lead, self.tr, self.reviewer, self.accounting, self.sales):
            self.assertEqual(self.read(QUEUE, who).status_code, 403, who.username)
        self.assertEqual(DjangoClient().get(reverse(QUEUE)).status_code, 401)

    def test_what_waits_says_who_it_waits_for_and_whether_this_person_may_decide(self):
        self.needs_manager(True)
        waiting_manager = self.ask_for()
        signed = self.ask_for(person=self.ops, days=1, start_date=self.start + timedelta(days=30))
        employees.decide_leave(signed, self.admin, approve=True)  # admin approves at HR's step
        later = self.ask_for(person=self.ops, days=1, start_date=self.start + timedelta(days=60))
        queue = _json(self.read(QUEUE, self.hr))["waiting"]
        by_id = {one["id"]: one for one in queue}
        self.assertEqual(set(by_id), {waiting_manager.pk, later.pk})
        self.assertEqual(by_id[waiting_manager.pk]["manager"], self.lead.short_name)
        self.assertEqual(by_id[waiting_manager.pk]["status"]["value"], "pending")
        self.assertTrue(all(one["can_decide"] for one in queue))
        self.assertEqual(by_id[waiting_manager.pk]["user"], {"id": self.tr.pk, "name": self.tr.short_name})

    def test_the_record_is_filtered_by_person_and_status(self):
        first = self.ask_for()
        second = self.ask_for(person=self.ops)
        employees.decide_leave(second, self.hr, approve=False, note="No")
        ids = lambda **query: [one["id"] for one in _json(self.read(QUEUE, self.hr, **query))["rows"]]
        self.assertEqual(sorted(ids()), sorted([first.pk, second.pk]))
        self.assertEqual(ids(user=self.ops.pk), [second.pk])
        self.assertEqual(ids(status="rejected"), [second.pk])
        row = [one for one in _json(self.read(QUEUE, self.hr))["rows"] if one["id"] == second.pk][0]
        self.assertEqual((row["decided_by"], row["decision_note"], row["applied"]), (self.hr.short_name, "No", False))
        self.assertEqual(self.read(QUEUE, self.hr, user="abc").status_code, 400)

    def test_an_approved_request_says_its_days_were_written(self):
        row = self.ask_for()
        employees.decide_leave(row, self.hr, approve=True)
        entry = [one for one in _json(self.read(QUEUE, self.hr))["rows"] if one["id"] == row.pk][0]
        self.assertTrue(entry["applied"])

    def test_the_options_are_the_active_people_and_the_statuses_with_their_words(self):
        gone = User.objects.create_user("person_gone", password="pw", role="translator", is_active=False)
        options = _json(self.read(QUEUE, self.hr))["options"]
        self.assertNotIn(gone.pk, [one["id"] for one in options["people"]])
        self.assertIn({"value": "manager_ok", "tone": "info", "ar": "المدير وافق", "en": "Manager approved"}, options["statuses"])

    def test_a_get_writes_nothing_and_the_queries_do_not_grow(self):
        self.ask_for()
        audit = AuditLog.objects.count()

        def queries():
            with CaptureQueriesContext(connection) as seen:
                self.read(QUEUE, self.hr)
            return len(seen)

        queries()
        few = queries()
        for number in range(1, 8):
            LeaveRequest.objects.create(user=self.ops, kind="other", start_date=self.start + timedelta(days=20 + number), end_date=self.start + timedelta(days=20 + number))
        self.assertEqual(queries(), few)
        self.assertEqual(AuditLog.objects.count(), audit)

