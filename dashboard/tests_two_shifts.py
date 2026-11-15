"""A translator on two shifts the same day, with a team leader for each (15/11/2026).

What these tests hold: the shift card on the file writes the second shift's rows with their own leader and the first shift's
leader on ``User.team_lead``; a second shift that lands on the first one's hours is refused and nothing moves; the register's
quick box (no ``second`` / ``team_lead`` in the body) leaves both alone; the second leader sees the translator in their team, may
hand them a share, and gets a task sent straight to them while they are on that shift; attendance stays on the first shift.
"""

import json
from datetime import datetime, time, timedelta
from unittest import mock

from django.test import Client as DjangoClient
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from . import attendance, services, shiftpick
from .models import Client, Role, Shift, ShiftTemplate, User, team_q

EMP_SHIFT = "dashboard:v1_hr_employee_shift"
EMPLOYEE = "dashboard:v1_hr_employee"
ALL_WEEK = [0, 1, 2, 3, 4, 5, 6]


def _at(hour, minute=0):
    """A moment today at Cairo time ``hour:minute``."""
    return timezone.make_aware(datetime.combine(timezone.localdate(), time(hour, minute)))


class _TwoShifts(TestCase):
    def setUp(self):
        make = lambda name, role, **kw: User.objects.create_user(name, password="pw", role=role, **kw)
        self.admin = make("person_admin", Role.ADMIN)
        self.morning_lead = make("person_morning_leader", Role.TEAM_LEAD)
        self.night_lead = make("person_night_leader", Role.TEAM_LEAD)
        self.stranger_lead = make("person_other_leader", Role.TEAM_LEAD)
        self.tr = make("person_translator", Role.TRANSLATOR, team_lead=self.morning_lead)
        self.ops = make("person_operation", Role.OPERATION)
        self.morning = ShiftTemplate.objects.create(name="Morning", start_time=time(9), end_time=time(17), sort_order=1)
        self.noon = ShiftTemplate.objects.create(name="Noon", start_time=time(12), end_time=time(20), sort_order=2)
        self.night = ShiftTemplate.objects.create(name="Night", start_time=time(17), end_time=time(1), sort_order=3)

    def post(self, body, person=None):
        browser = DjangoClient()
        browser.force_login(self.admin)
        return browser.post(
            reverse(EMP_SHIFT, args=[(person or self.tr).pk]), json.dumps(body), content_type="application/json",
        )

    def both_shifts(self):
        return self.post({
            "template": self.morning.pk, "weekdays": ALL_WEEK, "team_lead": self.morning_lead.pk,
            "second": {"template": self.night.pk, "weekdays": ALL_WEEK, "team_lead": self.night_lead.pk},
        })


class ShiftCardTests(_TwoShifts):
    def test_the_card_writes_the_second_shift_with_its_own_leader(self):
        response = self.both_shifts()
        self.assertEqual(response.status_code, 200, response.content)
        first = Shift.objects.filter(user=self.tr, slot=Shift.FIRST)
        second = Shift.objects.filter(user=self.tr, slot=Shift.SECOND)
        self.assertEqual(first.count(), 7)
        self.assertEqual(set(first.values_list("template", flat=True)), {self.morning.pk})
        self.assertEqual(set(first.values_list("team_lead", flat=True)), {None})
        self.assertEqual(second.count(), 7)
        self.assertEqual(set(second.values_list("team_lead", flat=True)), {self.night_lead.pk})
        self.tr.refresh_from_db()
        self.assertEqual(self.tr.team_lead_id, self.morning_lead.pk)

        browser = DjangoClient()
        browser.force_login(self.admin)
        picker = json.loads(browser.get(reverse(EMPLOYEE, args=[self.tr.pk])).content)["picker"]
        self.assertEqual(picker["current"], self.morning.pk)
        self.assertEqual(picker["lead"], self.morning_lead.pk)
        self.assertEqual(picker["second"], {"current": self.night.pk, "days": ALL_WEEK, "lead": self.night_lead.pk})
        self.assertIn(self.night_lead.pk, {one["id"] for one in picker["leads"]})

    def test_the_first_leader_is_changed_from_the_card(self):
        response = self.post({"template": self.morning.pk, "weekdays": ALL_WEEK, "team_lead": self.stranger_lead.pk})
        self.assertEqual(response.status_code, 200, response.content)
        self.tr.refresh_from_db()
        self.assertEqual(self.tr.team_lead_id, self.stranger_lead.pk)

    def test_a_second_shift_on_the_first_ones_hours_is_refused_and_nothing_moves(self):
        self.both_shifts()
        before = sorted(Shift.objects.filter(user=self.tr).values_list("slot", "template", "weekday"))
        response = self.post({
            "template": self.morning.pk, "weekdays": ALL_WEEK, "team_lead": self.stranger_lead.pk,
            "second": {"template": self.noon.pk, "weekdays": [0], "team_lead": self.night_lead.pk},
        })
        self.assertEqual(response.status_code, 400)
        self.assertEqual(json.loads(response.content)["error"], shiftpick.SHIFTS_OVERLAP)
        self.assertEqual(sorted(Shift.objects.filter(user=self.tr).values_list("slot", "template", "weekday")), before)
        self.tr.refresh_from_db()
        self.assertEqual(self.tr.team_lead_id, self.morning_lead.pk)

    def test_moving_the_first_shift_onto_the_second_is_refused_too(self):
        self.both_shifts()
        response = self.post({"template": self.noon.pk, "weekdays": ALL_WEEK})
        self.assertEqual(response.status_code, 400)
        self.assertEqual(json.loads(response.content)["error"], shiftpick.SHIFTS_OVERLAP)
        self.assertEqual(set(Shift.objects.filter(user=self.tr, slot=Shift.FIRST).values_list("template", flat=True)), {self.morning.pk})

    def test_overnight_first_shift_and_a_second_from_midnight_overlap(self):
        self.post({"template": self.night.pk, "weekdays": [0]})
        early = ShiftTemplate.objects.create(name="Early", start_time=time(0), end_time=time(4), sort_order=4)
        response = self.post({"template": self.night.pk, "weekdays": [0], "second": {"template": early.pk, "weekdays": [1], "team_lead": ""}})
        self.assertEqual(json.loads(response.content).get("error"), shiftpick.SHIFTS_OVERLAP)

    def test_the_quick_box_without_second_or_leader_leaves_them_alone(self):
        self.both_shifts()
        response = self.post({"template": self.morning.pk, "weekdays": [5, 6, 0]})
        self.assertEqual(response.status_code, 200, response.content)
        self.assertEqual(Shift.objects.filter(user=self.tr, slot=Shift.SECOND).count(), 7)
        self.assertEqual(Shift.objects.filter(user=self.tr, slot=Shift.FIRST).count(), 3)
        self.tr.refresh_from_db()
        self.assertEqual(self.tr.team_lead_id, self.morning_lead.pk)

    def test_second_null_takes_the_second_shift_off(self):
        self.both_shifts()
        self.post({"template": self.morning.pk, "weekdays": ALL_WEEK, "second": None})
        self.assertFalse(Shift.objects.filter(user=self.tr, slot=Shift.SECOND).exists())

    def test_clearing_the_first_shift_clears_the_second(self):
        self.both_shifts()
        self.post({"template": "", "weekdays": []})
        self.assertFalse(Shift.objects.filter(user=self.tr).exists())

    def test_a_second_shift_with_no_first_is_refused(self):
        response = self.post({"template": "", "weekdays": [], "second": {"template": self.night.pk, "weekdays": [0], "team_lead": ""}})
        self.assertEqual(json.loads(response.content).get("error"), shiftpick.NO_FIRST_SHIFT)
        self.assertFalse(Shift.objects.filter(user=self.tr).exists())

    def test_a_leader_is_for_a_translator_only(self):
        response = self.post({"template": self.morning.pk, "weekdays": ALL_WEEK, "team_lead": self.morning_lead.pk}, person=self.ops)
        self.assertEqual(json.loads(response.content).get("error"), shiftpick.LEAD_NOT_TRANSLATOR)
        self.assertFalse(Shift.objects.filter(user=self.ops).exists())

    def test_a_leader_who_is_not_one_is_refused(self):
        response = self.post({"template": self.morning.pk, "weekdays": ALL_WEEK, "team_lead": self.ops.pk})
        self.assertEqual(json.loads(response.content).get("error"), shiftpick.NO_SUCH_LEAD)

    def test_a_badly_shaped_second_is_refused(self):
        for second in ("x", {"template": self.night.pk, "weekdays": "0", "team_lead": ""}, {"template": [1], "weekdays": [], "team_lead": ""}):
            response = self.post({"template": self.morning.pk, "weekdays": ALL_WEEK, "second": second})
            self.assertEqual(response.status_code, 400, second)
            self.assertEqual(json.loads(response.content)["error"], "bad_body")


class TeamTests(_TwoShifts):
    def setUp(self):
        super().setUp()
        self.both_shifts()
        self.tr = User.objects.get(pk=self.tr.pk)

    def test_both_leaders_have_the_translator_in_their_team(self):
        for lead in (self.morning_lead, self.night_lead):
            self.assertTrue(User.objects.filter(team_q(lead), pk=self.tr.pk).exists(), lead)
            self.assertIn(self.tr, [row["person"] for row in services.translator_board(lead)])
        self.assertNotIn(self.tr, [row["person"] for row in services.translator_board(self.stranger_lead)])
        self.assertEqual(self.tr.lead_ids(), {self.morning_lead.pk, self.night_lead.pk})

    def test_the_overview_counts_them_in_both_teams_once_each(self):
        teams = {row["lead"].pk: row["members"] for row in services.team_overview()}
        self.assertEqual(teams[self.morning_lead.pk], [self.tr])
        self.assertEqual(teams[self.night_lead.pk], [self.tr])
        self.assertEqual(teams.get(self.stranger_lead.pk, []), [])

    def test_the_second_leader_may_hand_them_a_share_and_a_stranger_may_not(self):
        self.assertEqual(services.check_translators([{"translator": self.tr.pk}], self.night_lead), [self.tr])
        with self.assertRaises(services.PartError) as refused:
            services.check_translators([{"translator": self.tr.pk}], self.stranger_lead)
        self.assertEqual(refused.exception.code, services.NOT_IN_YOUR_TEAM)

    def test_the_leader_now_follows_the_shift(self):
        for moment, lead in ((_at(11), self.morning_lead), (_at(20), self.night_lead), (_at(3), self.morning_lead)):
            with mock.patch("django.utils.timezone.now", return_value=moment):
                self.assertEqual(User.objects.get(pk=self.tr.pk).lead_now(), lead, moment)

    def test_a_second_leader_who_left_falls_back_to_the_first(self):
        User.objects.filter(pk=self.night_lead.pk).update(is_active=False)
        with mock.patch("django.utils.timezone.now", return_value=_at(20)):
            self.assertEqual(User.objects.get(pk=self.tr.pk).lead_now(), self.morning_lead)

    def test_a_task_sent_straight_to_them_goes_to_the_leader_of_their_shift(self):
        client = Client.objects.create(name="Some company", phone="+201000000001")
        inbound = services.ingest_message(channel="whatsapp", body="hello", sender_identity="+201000000001")
        task = services.create_task(
            client=client, title="Doc", created_by=self.ops, deadline=timezone.now() + timedelta(hours=3), messages=[inbound],
        )
        with mock.patch("django.utils.timezone.now", return_value=_at(20)):
            self.assertIn(self.tr, services.direct_translators())
            services.assign_direct_to_translator(task, User.objects.get(pk=self.tr.pk), self.ops)
        task.refresh_from_db()
        self.assertEqual(task.team_lead_id, self.night_lead.pk)

    def test_attendance_stays_on_the_first_shift(self):
        # Even when the second shift starts earlier in the day than the first.
        early = ShiftTemplate.objects.create(name="Dawn", start_time=time(5), end_time=time(8), sort_order=5)
        Shift.objects.filter(user=self.tr, slot=Shift.SECOND).update(template=early)
        plan = attendance.plan_for(self.tr, timezone.localdate())
        self.assertEqual(plan.start.astimezone(timezone.get_current_timezone()).time(), time(9))
