"""The heartbeat's cost (15/10/2026): Neon paused the database for traffic, and the heartbeat was most of it.

Every open tab beat every 3 s, and every beat wrote the presence stamp and ran the expiry and deadline sweeps. These
hold the three cuts - the sweeps run once per few seconds for the whole server, the stamp is written once per half
minute per person, and a call rings over the socket so the page can beat slowly - and that what the beat is for still
happens: a hand-off past its window is taken back, and the presence dot stays on.
"""

from datetime import timedelta
from unittest import mock

from django.core.cache import cache
from django.test import Client as DjangoClient
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from . import realtime, services
from .models import Assignment, AssignmentStatus, CallSession, Role, User
from .tests_assignment_screen import _Handoff

BEAT = "dashboard:api_heartbeat"


def _beat(user):
    browser = DjangoClient()
    browser.force_login(user)
    answer = browser.get(reverse(BEAT))
    assert answer.status_code == 200, answer.status_code
    return answer


class SweepPaceTests(TestCase):
    def setUp(self):
        cache.clear()
        self.addCleanup(cache.clear)
        self.ops = User.objects.create_user("pace_ops", password="x", role=Role.OPERATION)
        self.tr = User.objects.create_user("pace_tr", password="x", role=Role.TRANSLATOR)

    def test_the_door_is_the_heartbeat_and_it_runs_the_sweeps(self):
        with mock.patch.object(services, "sweep_expired_assignments") as expiry, \
                mock.patch.object(services, "sweep_deadlines") as deadlines:
            _beat(self.ops)
        self.assertEqual((expiry.call_count, deadlines.call_count), (1, 1))

    def test_many_beats_from_many_people_run_the_sweeps_once_per_window(self):
        with mock.patch.object(services, "sweep_expired_assignments") as expiry, \
                mock.patch.object(services, "sweep_deadlines") as deadlines:
            for _ in range(3):
                _beat(self.ops)
                _beat(self.tr)
        self.assertEqual((expiry.call_count, deadlines.call_count), (1, 1))

    def test_once_the_window_has_passed_the_next_beat_runs_them_again(self):
        with mock.patch.object(services, "sweep_expired_assignments") as expiry, \
                mock.patch.object(services, "sweep_deadlines"):
            _beat(self.ops)
            cache.delete("heartbeat-housekeeping")  # what the window running out does
            _beat(self.tr)
        self.assertEqual(expiry.call_count, 2)

    def test_the_window_is_short_enough_for_a_sixty_second_hand_off(self):
        self.assertLessEqual(services.HOUSEKEEPING_EVERY_SECONDS, 5)


class PresencePaceTests(TestCase):
    def setUp(self):
        cache.clear()
        self.addCleanup(cache.clear)
        self.tr = User.objects.create_user("presence_tr", password="x", role=Role.TRANSLATOR)

    def stamp(self, seconds_ago):
        at = None if seconds_ago is None else timezone.now() - timedelta(seconds=seconds_ago)
        User.objects.filter(pk=self.tr.pk).update(last_seen=at)
        return at

    def test_a_first_beat_writes_the_stamp(self):
        self.stamp(None)
        _beat(self.tr)
        self.tr.refresh_from_db()
        self.assertIsNotNone(self.tr.last_seen)
        self.assertTrue(self.tr.is_online)

    def test_a_fresh_stamp_is_not_written_again(self):
        at = self.stamp(10)
        _beat(self.tr)
        self.tr.refresh_from_db()
        self.assertEqual(self.tr.last_seen, at)
        self.assertTrue(self.tr.is_online)

    def test_a_stamp_half_a_minute_old_is_written(self):
        at = self.stamp(services.PRESENCE_WRITE_EVERY_SECONDS + 1)
        _beat(self.tr)
        self.tr.refresh_from_db()
        self.assertGreater(self.tr.last_seen, at)

    def test_the_skipped_write_can_never_make_an_open_page_look_offline(self):
        # A page with its socket open beats every 30 s (`LIVE_BEAT_MS`): the stamp is at most one skip plus one beat old.
        self.assertLess(services.PRESENCE_WRITE_EVERY_SECONDS + 30, User.PRESENCE_TIMEOUT)


class ExpiryStillOnTimeTests(_Handoff):
    def setUp(self):
        super().setUp()
        cache.clear()
        self.addCleanup(cache.clear)

    def test_a_beat_takes_back_a_hand_off_past_its_window(self):
        Assignment.objects.filter(pk=self.handoff.pk).update(expires_at=timezone.now() - timedelta(seconds=1))
        answer = _beat(self.tr).json()
        self.handoff.refresh_from_db()
        self.assertEqual(self.handoff.status, AssignmentStatus.EXPIRED)
        self.assertIsNone(answer["pending"])


class CallRingsOverTheSocketTests(TestCase):
    def setUp(self):
        self.ops = User.objects.create_user("call_ops", password="x", role=Role.OPERATION)
        self.lead = User.objects.create_user("call_lead", password="x", role=Role.TEAM_LEAD)

    def test_placing_a_call_rings_the_callee_and_nobody_else(self):
        with mock.patch.object(realtime, "send_to_users") as send:
            call, error = services.start_call(self.ops, self.lead)
        self.assertEqual(error, "")
        calls = [c for c in send.call_args_list if c.args[1] == {"t": realtime.CALL}]
        self.assertEqual([c.args[0] for c in calls], [[self.lead.pk]])

    def test_the_call_answered_or_ended_does_not_ring_again(self):
        call, _ = services.start_call(self.ops, self.lead)
        with mock.patch.object(realtime, "send_to_users") as send:
            call.status = CallSession.Status.ACTIVE
            call.save()
        self.assertFalse([c for c in send.call_args_list if c.args[1] == {"t": realtime.CALL}])

    def test_the_call_event_carries_its_kind_only(self):
        self.assertEqual(realtime.clean_event({"t": "call", "from": "Mona", "id": 3}), {"t": "call", "id": 3})
        self.assertIn(realtime.CALL, realtime.KINDS)
