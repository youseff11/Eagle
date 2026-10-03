"""The call endpoints as the new app reads them.

The calls themselves are the classic endpoints and keep their tests (``tests.CallTests``); the new app draws them from
``lib/calls.ts``, which depends on the exact shape of what they answer. Pinned here so a change to a key is seen from
this side: the heartbeat's ``call``, the call as either end reads it, the two refusals, and the ICE servers.
"""

from django.test import Client as DjangoClient
from django.test import TestCase

from . import services
from .models import CallSession, Role, User


class CallContractTests(TestCase):
    def setUp(self):
        self.a = User.objects.create_user("person_caller", password="pw", role=Role.OPERATION)
        self.b = User.objects.create_user("person_callee", password="pw", role=Role.TEAM_LEAD)
        self.c = User.objects.create_user("person_third", password="pw", role=Role.TRANSLATOR)

    def browser(self, user):
        browser = DjangoClient()
        browser.force_login(user)
        return browser

    def test_the_heartbeat_carries_a_ringing_call_with_exactly_what_the_overlay_draws(self):
        call, _error = services.start_call(self.a, self.b, video=True)
        body = self.browser(self.b).get("/api/heartbeat/").json()["call"]
        self.assertEqual(body, {
            "id": call.pk, "video": True, "from": self.a.short_name, "initials": self.a.initials,
            "chat_url": f"/ops/chats/u/{self.a.pk}/",
        })
        # Nobody else hears it ring, and the caller's own heartbeat says nothing.
        self.assertIsNone(self.browser(self.c).get("/api/heartbeat/").json()["call"])
        self.assertIsNone(self.browser(self.a).get("/api/heartbeat/").json()["call"])

    def test_it_stops_ringing_once_answered_or_ended(self):
        call, _error = services.start_call(self.a, self.b)
        services.answer_call(call, self.b)
        self.assertIsNone(self.browser(self.b).get("/api/heartbeat/").json()["call"])

    def test_starting_a_call_answers_with_the_call_as_the_caller_reads_it_and_the_ice_servers(self):
        body = self.browser(self.a).post("/api/calls/start/", {"user": self.b.pk, "video": "1"}).json()
        self.assertTrue(body["ok"])
        self.assertEqual(set(body["call"]), {"id", "status", "video", "caller", "other", "initials", "answered_at"})
        self.assertEqual(
            (body["call"]["status"], body["call"]["video"], body["call"]["caller"], body["call"]["other"], body["call"]["answered_at"]),
            ("ringing", True, True, self.b.short_name, ""),
        )
        self.assertTrue(body["ice"] and all("urls" in server for server in body["ice"]))

    def test_the_callee_reads_it_as_not_the_caller_and_with_when_it_was_answered(self):
        call, _error = services.start_call(self.a, self.b)
        answered = self.browser(self.b).post(f"/api/calls/{call.pk}/answer/").json()
        self.assertEqual((answered["ok"], answered["call"]["status"], answered["call"]["caller"]), (True, "active", False))
        self.assertTrue(answered["call"]["answered_at"])
        self.assertTrue(answered["ice"])

    def test_a_refusal_is_a_400_with_the_reason_in_words_and_not_an_exception(self):
        busy = self.browser(self.a).post("/api/calls/start/", {"user": self.a.pk})
        self.assertEqual((busy.status_code, busy.json()["ok"]), (400, False))
        self.assertTrue(busy.json()["error"])
        call, _error = services.start_call(self.a, self.b)
        services.end_call(call, self.a, reason="missed")
        late = self.browser(self.b).post(f"/api/calls/{call.pk}/answer/")
        self.assertEqual((late.status_code, late.json()["ok"]), (400, False))
        self.assertTrue(late.json()["error"])

    def test_the_signals_come_with_the_calls_state_so_one_poll_says_both_things(self):
        call, _error = services.start_call(self.a, self.b)
        self.browser(self.a).post(f"/api/calls/{call.pk}/signals/", {"kind": "offer", "payload": "{}"})
        body = self.browser(self.b).get(f"/api/calls/{call.pk}/signals/?after=0").json()
        self.assertEqual(body["call"]["status"], "ringing")
        self.assertEqual([(one["kind"], set(one)) for one in body["signals"]], [("offer", {"id", "kind", "payload"})])
        # The caller does not read back their own offer.
        self.assertEqual(self.browser(self.a).get(f"/api/calls/{call.pk}/signals/?after=0").json()["signals"], [])

    def test_ending_is_idempotent_so_both_ends_hanging_up_at_once_write_one_line(self):
        call, _error = services.start_call(self.a, self.b)
        services.answer_call(call, self.b)
        first = self.browser(self.a).post(f"/api/calls/{call.pk}/end/", {"reason": "ended"})
        second = self.browser(self.b).post(f"/api/calls/{call.pk}/end/", {"reason": "ended"})
        self.assertEqual((first.status_code, second.status_code), (200, 200))
        call.refresh_from_db()
        self.assertEqual(call.status, CallSession.Status.ENDED)
        self.assertEqual(call.room.messages.count(), 1)

    def test_somebody_who_is_not_on_the_call_gets_a_404_on_every_door(self):
        call, _error = services.start_call(self.a, self.b)
        stranger = self.browser(self.c)
        self.assertEqual(stranger.get(f"/api/calls/{call.pk}/signals/").status_code, 404)
        self.assertEqual(stranger.post(f"/api/calls/{call.pk}/answer/").status_code, 404)
        self.assertEqual(stranger.post(f"/api/calls/{call.pk}/end/").status_code, 404)
