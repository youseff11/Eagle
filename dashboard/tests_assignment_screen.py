"""The accept screen in the new app: a hand-off read before it is taken (``/api/v1/assignments/<id>/``).

The 60-second popup and the page behind "see the files first" were the last thing only the classic interface
could show a translator. What is pinned here is what the new page may *read*, and that reading changes nothing:

* only the person it was handed to (and the admin) - anybody else is a 404 and a row in the audit log;
* the client is a code, and the free words (the brief, the sender's note) have the name taken out;
* looking is never answering: a GET does not even record that the files were opened (the page does, with a POST),
  and the window keeps running;
* what the heartbeat tells the popup is the shape the popup draws;
* the classic accept and decline are untouched, and a waiting assignment no longer keeps a translator off the new app.
"""

import json
from datetime import datetime, timedelta

from django.core.files.base import ContentFile
from django.test import Client as DjangoClient
from django.urls import reverse
from django.utils import timezone

from . import services
from .models import (
    Assignment, AssignmentStatus, AppSettings, AuditLog, ChatMessage, InboundMessage, MessageAttachment, Role, Task,
    TaskStatus, User,
)
from .tests_api_v1 import CLIENT_EMAIL, CLIENT_NAME, CLIENT_PHONE, IDENTITY_MARKERS, _json
from .tests_translator_home import _Desk, _make_task

DOOR = "dashboard:v1_assignment"


class _Handoff(_Desk):
    def setUp(self):
        super().setUp()
        Assignment.objects.filter(assignee=self.tr).delete()
        self.job = _make_task(self, status=TaskStatus.LEAD_ACCEPTED, title="Needs an answer",
                              description=f"For {CLIENT_NAME}. Call {CLIENT_PHONE} or {CLIENT_EMAIL}.")
        self.handoff = services.assign_to_translator(self.job, self.tr, self.lead, note=f"From {CLIENT_NAME}, urgent")

    def read(self, user, pk=None, **kw):
        browser = DjangoClient()
        if user is not None:
            browser.force_login(user)
        return browser.get(reverse(DOOR, args=[pk or self.handoff.pk]), kw)

    def handoff_to_lead(self):
        task = _make_task(self, status=TaskStatus.NEW, title="For the leader")
        return services.assign_to_lead(task, self.lead, self.ops, note="Please take it")


class AssignmentDoorTests(_Handoff):
    def test_only_the_person_it_was_handed_to_and_the_admin_are_answered(self):
        for user in (self.tr, self.admin):
            self.assertEqual(self.read(user).status_code, 200, user.username)
        other = User.objects.create_user("person_other_translator", password="pw", role=Role.TRANSLATOR, team_lead=self.lead)
        for user in (other, self.lead, self.ops, self.hr, self.reviewer, self.accounting, self.sales):
            before = AuditLog.objects.filter(actor=user, action="security.denied").count()
            answer = self.read(user)
            self.assertEqual((answer.status_code, _json(answer)), (404, {"ok": False, "error": "not_found"}), user.username)
            self.assertNotIn(self.job.code.encode(), answer.content)
            self.assertEqual(AuditLog.objects.filter(actor=user, action="security.denied").count(), before + 1, user.username)

    def test_signed_out_is_401_and_only_a_get_is_answered_and_nothing_is_stored(self):
        self.assertEqual(self.read(None).status_code, 401)
        browser = DjangoClient()
        browser.force_login(self.tr)
        self.assertEqual(browser.post(reverse(DOOR, args=[self.handoff.pk])).status_code, 405)
        self.assertEqual(self.read(self.tr)["Cache-Control"], "private, no-store")
        self.assertEqual(self.read(self.tr, 999999).status_code, 404)

    def test_what_the_page_draws_from_the_hand_off(self):
        mine = timezone.now() + timedelta(hours=5)
        Task.objects.filter(pk=self.job.pk).update(translator_deadline=mine, deadline=timezone.now() + timedelta(days=9),
                                                   source_lang="Arabic", target_lang="English")
        body = _json(self.read(self.tr))
        window = AppSettings.load().response_window_seconds
        a = body["assignment"]
        self.assertEqual((a["id"], a["status"], a["pending"], a["role"], a["from"], a["mine"]),
                         (self.handoff.pk, "pending", True, "translator", self.lead.short_name, True))
        self.assertEqual(a["window"], window)
        self.assertTrue(0 < a["seconds_left"] <= window)
        task = body["task"]
        self.assertEqual((task["code"], task["title"], task["client"]), (self.job.code, "Needs an answer", self.client_obj.code))
        self.assertEqual((task["source_lang"], task["target_lang"]), ("Arabic", "English"))
        # The translator's own date, in both languages, and the moment for the live "time left" line.
        self.assertTrue(task["due"]["ar"] and task["due"]["en"])
        self.assertIn(timezone.localtime(mine).strftime("%Y-%m-%d"), task["due"]["en"])
        self.assertNotIn(timezone.localtime(timezone.now() + timedelta(days=9)).strftime("%Y-%m-%d"), self.read(self.tr).content.decode())
        self.assertTrue(task["origin"] is None or task["origin"]["value"])

    def test_the_translators_own_date_and_the_leaders_are_not_the_same_date(self):
        mine = timezone.now() + timedelta(hours=5)
        theirs = timezone.now() + timedelta(days=9)
        Task.objects.filter(pk=self.job.pk).update(translator_deadline=mine, deadline=theirs)
        # The moment itself, not the start of its text: the answer is in UTC and the day Cairo reads can differ from it.
        task = _json(self.read(self.tr))["task"]
        self.assertLess(abs(datetime.fromisoformat(task["due_iso"]) - mine), timedelta(seconds=1))
        # A team leader is asked to take the task before any translator date exists: they are told the client's.
        handoff = self.handoff_to_lead()
        Task.objects.filter(pk=handoff.task_id).update(deadline=theirs)
        task = _json(self.read(self.lead, handoff.pk))["task"]
        self.assertLess(abs(datetime.fromisoformat(task["due_iso"]) - theirs), timedelta(seconds=1))

    def test_no_deadline_at_all_is_an_empty_moment_and_not_an_error(self):
        Task.objects.filter(pk=self.job.pk).update(translator_deadline=None, deadline=None)
        task = _json(self.read(self.tr))["task"]
        self.assertEqual((task["due"], task["due_iso"]), (None, ""))

    def test_a_get_changes_nothing_not_even_the_record_that_the_files_were_opened(self):
        self.assertIsNone(Assignment.objects.get(pk=self.handoff.pk).opened_at)
        self.read(self.tr)
        self.read(self.tr)
        fresh = Assignment.objects.get(pk=self.handoff.pk)
        self.assertEqual((fresh.opened_at, fresh.status), (None, AssignmentStatus.PENDING))

    def test_the_brief_and_the_note_have_the_client_taken_out_and_the_admin_reads_them_as_written(self):
        raw = self.read(self.tr).content.decode("utf-8")
        for marker in IDENTITY_MARKERS + (CLIENT_NAME, CLIENT_PHONE, CLIENT_EMAIL):
            self.assertNotIn(marker, raw, marker)
        body = json.loads(raw)
        self.assertIn(f"For {self.client_obj.code}.", body["task"]["description"])
        self.assertEqual(body["assignment"]["note"], f"From {self.client_obj.code}, urgent")
        admin = _json(self.read(self.admin))
        self.assertIn(CLIENT_NAME, admin["task"]["description"])
        self.assertIn(CLIENT_PHONE, admin["task"]["description"])
        self.assertEqual(admin["assignment"]["note"], f"From {CLIENT_NAME}, urgent")
        self.assertFalse(admin["assignment"]["mine"])

    def test_the_files_are_the_jobs_own_and_a_voice_note_is_not_one_of_them(self):
        inbound = InboundMessage.objects.create(client=self.client_obj, channel="whatsapp", body="x", task=self.job,
                                                sender_identity=CLIENT_PHONE)
        MessageAttachment.objects.create(message=inbound, file=ContentFile(b"o", name="contract.pdf"),
                                         original_name="contract.pdf", size=2048)
        MessageAttachment.objects.create(message=inbound, file=ContentFile(b"v", name="talk.ogg"),
                                         original_name="talk.ogg", size=5)
        # Another task's file, not this one's.
        elsewhere = InboundMessage.objects.create(client=self.client_obj, channel="whatsapp", body="y",
                                                  sender_identity=CLIENT_PHONE)
        MessageAttachment.objects.create(message=elsewhere, file=ContentFile(b"z", name="other.pdf"),
                                         original_name="other.pdf", size=1)
        files = _json(self.read(self.tr))["task"]["files"]
        self.assertEqual([(f["name"], f["size"], f["image"]) for f in files], [("contract.pdf", "2.0 KB", False)])
        self.assertTrue(files[0]["url"].startswith("/"))

    def test_a_task_with_no_files_has_an_empty_list(self):
        self.assertEqual(_json(self.read(self.tr))["task"]["files"], [])

    def test_only_a_hand_off_still_inside_its_window_is_pending(self):
        for status in (AssignmentStatus.ACCEPTED, AssignmentStatus.DECLINED, AssignmentStatus.EXPIRED, AssignmentStatus.CANCELLED):
            Assignment.objects.filter(pk=self.handoff.pk).update(status=status)
            a = _json(self.read(self.tr))["assignment"]
            self.assertEqual((a["status"], a["pending"]), (status, False), status)
        # Still marked pending, but the clock ran out and the sweep has not been by yet.
        Assignment.objects.filter(pk=self.handoff.pk).update(status=AssignmentStatus.PENDING,
                                                             expires_at=timezone.now() - timedelta(seconds=5))
        a = _json(self.read(self.tr))["assignment"]
        self.assertEqual((a["pending"], a["seconds_left"]), (False, 0))

    def test_a_team_leader_asked_to_take_a_task_reads_their_own_hand_off(self):
        handoff = self.handoff_to_lead()
        body = _json(self.read(self.lead, handoff.pk))
        self.assertEqual((body["assignment"]["role"], body["assignment"]["from"], body["assignment"]["mine"]),
                         ("team_lead", self.ops.short_name, True))
        self.assertEqual(self.read(self.tr, handoff.pk).status_code, 404)


class PendingAsTheHeartbeatSendsIt(_Handoff):
    """The popup draws from ``/api/heartbeat/``: the keys it reads are the keys that are there."""

    KEYS = {"id", "task_code", "task_title", "task_url", "client", "role", "seconds_left", "window", "assigned_by",
            "files_url", "open_url", "priority", "deadline", "deadline_iso", "note", "part"}

    def beat(self, user):
        browser = DjangoClient()
        browser.force_login(user)
        return browser.get(reverse("dashboard:api_heartbeat"))

    def test_the_shape_the_popup_reads(self):
        pending = _json(self.beat(self.tr))["pending"]
        self.assertEqual(set(pending), self.KEYS)
        self.assertEqual((pending["id"], pending["task_code"], pending["role"]), (self.handoff.pk, self.job.code, "translator"))
        self.assertEqual(pending["client"], self.client_obj.code)
        self.assertEqual(pending["files_url"], f"/assignments/{self.handoff.pk}/")
        self.assertEqual(pending["open_url"], f"/api/assignments/{self.handoff.pk}/files/")
        self.assertEqual(pending["task_url"], f"/tasks/{self.job.code}/")
        self.assertEqual(pending["window"], AppSettings.load().response_window_seconds)

    def test_nothing_of_the_client_in_what_the_popup_is_given_the_senders_note_included(self):
        raw = self.beat(self.tr).content.decode("utf-8")
        for marker in IDENTITY_MARKERS + (CLIENT_NAME, CLIENT_PHONE, CLIENT_EMAIL):
            self.assertNotIn(marker, raw, marker)
        # The note still reads: the name is the code. The admin, who may know it, is told it as it was written.
        self.assertEqual(_json(self.beat(self.tr))["pending"]["note"], f"From {self.client_obj.code}, urgent")
        Assignment.objects.filter(pk=self.handoff.pk).update(assignee=self.admin)
        self.assertEqual(_json(self.beat(self.admin))["pending"]["note"], f"From {CLIENT_NAME}, urgent")

    def test_nobody_but_the_assignee_is_told(self):
        for user in (self.lead, self.ops, self.admin):
            self.assertIsNone(_json(self.beat(user))["pending"], user.username)

    def test_an_answered_hand_off_stops_being_pending(self):
        browser = DjangoClient()
        browser.force_login(self.tr)
        answer = browser.post(reverse("dashboard:api_accept", args=[self.handoff.pk]))
        self.assertEqual((answer.status_code, _json(answer)["ok"]), (200, True))
        self.assertIsNone(_json(self.beat(self.tr))["pending"])


class AcceptAndDeclineAreTheClassicEndpoints(_Handoff):
    """The new page calls the endpoints the classic popup always did, so their answers are the contract."""

    def post(self, name, user, **data):
        browser = DjangoClient()
        browser.force_login(user)
        return browser.post(reverse(name, args=[self.handoff.pk]), data)

    def test_accepting_in_time_moves_the_task_and_says_so(self):
        answer = self.post("dashboard:api_accept", self.tr)
        self.assertEqual(_json(answer), {"ok": True, "reason": "accepted", "task": self.job.code})
        self.job.refresh_from_db()
        self.assertEqual(self.job.status, TaskStatus.IN_PROGRESS)

    def test_accepting_too_late_is_ok_false_with_a_200_and_the_reason(self):
        Assignment.objects.filter(pk=self.handoff.pk).update(expires_at=timezone.now() - timedelta(seconds=1))
        answer = self.post("dashboard:api_accept", self.tr)
        self.assertEqual((answer.status_code, _json(answer)["ok"], _json(answer)["reason"]), (200, False, "expired"))

    def test_a_second_accept_says_it_is_already_accepted(self):
        self.post("dashboard:api_accept", self.tr)
        answer = self.post("dashboard:api_accept", self.tr)
        self.assertEqual((_json(answer)["ok"], _json(answer)["reason"]), (False, "accepted"))

    def test_somebody_else_cannot_accept_it(self):
        # Not found, written down, and nothing of the task in the answer (it used to say "forbidden" with the task's code).
        before = AuditLog.objects.filter(actor=self.lead, action="security.denied").count()
        answer = self.post("dashboard:api_accept", self.lead)
        self.assertEqual(answer.status_code, 404)
        self.assertNotIn(self.job.code.encode(), answer.content)
        self.assertEqual(AuditLog.objects.filter(actor=self.lead, action="security.denied").count(), before + 1)
        self.job.refresh_from_db()
        self.assertEqual(self.job.status, TaskStatus.AWAITING_TRANSLATOR)

    def test_declining_needs_a_reason_and_a_400_says_so(self):
        answer = self.post("dashboard:api_decline", self.tr, reason="   ")
        self.assertEqual((answer.status_code, _json(answer)["ok"]), (400, False))
        self.assertTrue(_json(answer)["error"])
        answer = self.post("dashboard:api_decline", self.tr, reason="Busy with another file")
        self.assertEqual((answer.status_code, _json(answer)["ok"]), (200, True))
        self.assertEqual(Assignment.objects.get(pk=self.handoff.pk).reason, "Busy with another file")

    def test_opening_the_files_is_a_post_of_its_own_and_is_not_an_answer(self):
        browser = DjangoClient()
        browser.force_login(self.tr)
        answer = browser.post(reverse("dashboard:api_assignment_files", args=[self.handoff.pk]))
        self.assertEqual(_json(answer), {"ok": True, "url": f"/assignments/{self.handoff.pk}/"})
        fresh = Assignment.objects.get(pk=self.handoff.pk)
        self.assertEqual(fresh.status, AssignmentStatus.PENDING)
        self.assertIsNotNone(fresh.opened_at)
        # Not for somebody else's hand-off.
        from .models import AuditLog

        before = AuditLog.objects.filter(action="security.denied", actor=self.lead).count()
        browser.force_login(self.lead)
        self.assertEqual(browser.post(reverse("dashboard:api_assignment_files", args=[self.handoff.pk])).status_code, 404)
        self.assertEqual(AuditLog.objects.filter(action="security.denied", actor=self.lead).count(), before + 1)
        self.assertIsNotNone(Assignment.objects.get(pk=self.handoff.pk).opened_at)


class AssignmentHandOnTests(_Handoff):
    def classic(self, user, pk=None, **query):
        browser = DjangoClient()
        browser.force_login(user)
        return browser.get(reverse("dashboard:assignment_preview", args=[pk or self.handoff.pk]), query)

    def test_a_translator_with_the_switch_reads_the_job_in_the_new_app(self):
        self.turn_on(roles=["translator"])
        answer = self.classic(self.tr)
        self.assertEqual((answer.status_code, answer["Location"]), (302, f"/app/assignments/{self.handoff.pk}"))

    def test_somebody_elses_hand_off_is_sent_on_and_refused_there(self):
        self.turn_on(roles=["translator"])
        other = User.objects.create_user("person_other_translator", password="pw", role=Role.TRANSLATOR, team_lead=self.lead)
        task = _make_task(self, translator=other, status=TaskStatus.LEAD_ACCEPTED, title="Theirs")
        theirs = services.assign_to_translator(task, other, self.lead)
        self.assertEqual(self.classic(self.tr, theirs.pk)["Location"], f"/app/assignments/{theirs.pk}")
        self.assertEqual(self.read(self.tr, theirs.pk).status_code, 404)
