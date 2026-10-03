"""The rest of the translator's screen in the new app: the payslip and the task page.

Two read doors (``/api/v1/translator/payroll/`` and ``/api/v1/translator/tasks/<code>/``) and the hand-on from
the classic pages. The writes on a task page (finished, the translation file, more time, the AI check) are the
classic endpoints and keep their own tests; what is pinned here is what the new page may *read*:

* only the person's own pay and only their own task - a task that is not theirs is a 404 and a row in the audit
  log, never a 403 that says the code exists;
* the client is a code. Not the name, not the number, not the address - in the brief and the requirements as
  well, which people type: the name becomes the code, the contacts are taken out;
* the date is the translator's own, the translator's page has none of the operation's or the leader's cards;
* one switch for the desk, the payslip and the task page, and only a translator is ever sent on.
"""

import json
from datetime import date, timedelta
from decimal import Decimal

from django.core.files.base import ContentFile
from django.test import Client as DjangoClient
from django.urls import reverse
from django.utils import timezone

from . import clock, services
from .models import (
    AICheckResult, AppSettings, AuditLog, ChatAttachment, ChatMessage, ClientRequirement, ExtensionRequest,
    InboundMessage, MessageAttachment, PayrollLine, PayrollPeriod, Role, Task, TaskStatus, User, Violation, WorkDay,
)
from .tests_api_v1 import CLIENT_EMAIL, CLIENT_NAME, CLIENT_PHONE, IDENTITY_MARKERS, _json
from .tests_translator_home import _Desk, _make_task

PAYROLL = "dashboard:v1_translator_payroll"
TASK = "dashboard:v1_translator_task"


class _Screen(_Desk):
    def door(self, user, name, args=None, /, **query):
        browser = DjangoClient()
        if user is not None:
            browser.force_login(user)
        return browser.get(reverse(name, args=args), query)

    def payroll(self, user, /, **query):
        return self.door(user, PAYROLL, **query)

    def task_page(self, user, code=None):
        return self.door(user, TASK, [code or self.task.code])

    def slip(self, user, year, month, **fields):
        period, _ = PayrollPeriod.objects.get_or_create(year=year, month=month)
        values = dict(base_salary=Decimal("5000.00"), production_bonus=Decimal("750.50"), deductions=Decimal("120.00"),
                      net=Decimal("5630.50"))
        values.update(fields)
        return PayrollLine.objects.create(period=period, user=user, **values)

    def other_translator(self, name="person_other_translator"):
        return User.objects.create_user(name, password="pw", role=Role.TRANSLATOR, team_lead=self.lead)


# ---------------------------------------------------------------------------------------------------------------------
# The payslip
# ---------------------------------------------------------------------------------------------------------------------

class PayrollApiTests(_Screen):
    def setUp(self):
        super().setUp()
        today = timezone.localdate()
        self.year, self.month = today.year, today.month

    def test_the_translator_and_the_admin_are_answered_everybody_else_is_refused(self):
        for user in (self.tr, self.admin):
            self.assertEqual(self.payroll(user).status_code, 200, user.username)
        for user in (self.ops, self.lead, self.hr, self.reviewer, self.accounting, self.sales):
            answer = self.payroll(user)
            self.assertEqual((answer.status_code, _json(answer)), (403, {"ok": False, "error": "forbidden"}), user.username)
        self.assertEqual(self.payroll(None).status_code, 401)
        browser = DjangoClient()
        browser.force_login(self.tr)
        self.assertEqual(browser.post(reverse(PAYROLL)).status_code, 405)
        self.assertEqual(self.payroll(self.tr)["Cache-Control"], "private, no-store")

    def test_the_month_is_what_the_classic_page_shows(self):
        line = self.slip(self.tr, self.year, self.month)
        WorkDay.objects.create(user=self.tr, date=date(self.year, self.month, 1), status="present", words=3100)
        WorkDay.objects.create(user=self.tr, date=date(self.year, self.month, 2), status="leave")
        WorkDay.objects.create(user=self.tr, date=date(self.year, self.month, 3), status="unexcused")
        Violation.objects.create(user=self.tr, date=date(self.year, self.month, 3), kind="unexcused", status="approved",
                                 reason="No word from you")
        Violation.objects.create(user=self.tr, date=date(self.year, self.month, 2), kind="quality", status="pending")
        body = _json(self.payroll(self.tr))
        self.assertEqual((body["year"], body["month"]), (self.year, self.month))
        # Money is text, to the cent: a float would round it.
        self.assertEqual(
            body["line"],
            {"id": line.pk, "base_salary": "5000.00", "production_bonus": "750.50", "deductions": "120.00", "net": "5630.50",
             "pending_bonus": str(line.pending_bonus), "url": f"/accounts/line/{line.pk}/"},
        )
        self.assertEqual([(d["date"], d["status"]["value"], d["words"]) for d in body["days"]],
                         [(f"{self.year}-{self.month:02d}-01", "present", 3100),
                          (f"{self.year}-{self.month:02d}-02", "leave", 0),
                          (f"{self.year}-{self.month:02d}-03", "unexcused", 0)])
        self.assertEqual(body["days"][0]["status"]["ar"], "حاضر")
        self.assertEqual(body["days"][2]["status"]["en"], "Unexcused")
        self.assertEqual([(v["kind"]["value"], v["status"], v["reason"]) for v in body["violations"]],
                         [("unexcused", "approved", "No word from you"), ("quality", "pending", "")])
        self.assertTrue(body["violations"][0]["kind"]["ar"] and body["violations"][0]["kind"]["en"])
        self.assertEqual(body["daily_target_words"], 3000)

    def test_a_month_that_has_not_been_run_has_no_line_and_is_not_an_error(self):
        body = _json(self.payroll(self.tr))
        self.assertIsNone(body["line"])
        self.assertEqual((body["days"], body["violations"]), ([], []))

    def test_only_their_own_pay_and_days_and_violations(self):
        other = self.other_translator()
        self.slip(other, self.year, self.month, base_salary=Decimal("9999.99"), net=Decimal("8888.88"))
        WorkDay.objects.create(user=other, date=date(self.year, self.month, 1), status="present", words=7777)
        Violation.objects.create(user=other, date=date(self.year, self.month, 1), kind="quality", status="approved",
                                 reason="SOMEONE ELSE'S MISTAKE")
        mine = self.slip(self.tr, self.year, self.month)
        raw = self.payroll(self.tr).content.decode("utf-8")
        for marker in ("9999.99", "8888.88", "7777", "SOMEONE ELSE"):
            self.assertNotIn(marker, raw, marker)
        self.assertEqual(_json(self.payroll(self.tr))["line"]["id"], mine.pk)
        # Nothing in the request can name another person.
        for query in ({"user": other.pk}, {"user_id": other.pk}, {"id": other.pk}):
            self.assertNotIn("9999.99", self.payroll(self.tr, **query).content.decode("utf-8"))

    def test_the_admin_is_answered_with_their_own_pay_not_a_translators(self):
        self.slip(self.tr, self.year, self.month, base_salary=Decimal("4321.00"))
        raw = self.payroll(self.admin).content.decode("utf-8")
        self.assertNotIn("4321.00", raw)
        self.assertIsNone(_json(self.payroll(self.admin))["line"])

    def test_the_month_picker_names_the_requested_month_and_lists_thirteen(self):
        body = _json(self.payroll(self.tr))
        self.assertEqual(len(body["periods"]), 13)
        self.assertEqual((body["periods"][0]["year"], body["periods"][0]["month"]), (self.year, self.month))
        self.assertEqual(len({(p["year"], p["month"]) for p in body["periods"]}), 13)
        for earlier, later in zip(body["periods"][1:], body["periods"]):
            self.assertLess((earlier["year"], earlier["month"]), (later["year"], later["month"]))

    def test_a_month_asked_for_by_name_and_only_its_own_days(self):
        self.slip(self.tr, 2026, 9, net=Decimal("1111.11"))
        WorkDay.objects.create(user=self.tr, date=date(2026, 9, 30), status="present", words=10)
        WorkDay.objects.create(user=self.tr, date=date(2026, 10, 1), status="present", words=20)
        for period in ("2026-09", "2026-9"):
            body = _json(self.payroll(self.tr, period=period))
            self.assertEqual((body["year"], body["month"]), (2026, 9), period)
            self.assertEqual(body["line"]["net"], "1111.11")
            self.assertEqual([d["date"] for d in body["days"]], ["2026-09-30"])

    def test_a_period_that_is_not_one_is_refused_and_not_taken_for_this_month(self):
        for bad in ("evil", "2026", "2026-13", "2026-00", "1999-05", "2026-1-1", "20266-1", "２０２６-０９", "2026-009", "-", "2026-"):
            answer = self.payroll(self.tr, period=bad)
            self.assertEqual((answer.status_code, _json(answer)), (400, {"ok": False, "error": "bad_period"}), bad)

    def test_the_figures_are_the_ones_on_the_classic_page(self):
        self.slip(self.tr, self.year, self.month)
        page = self.client_classic()
        body = _json(self.payroll(self.tr))["line"]
        for figure in (body["base_salary"], body["production_bonus"], body["deductions"], body["net"]):
            self.assertIn(figure, page)

    def client_classic(self):
        browser = DjangoClient()
        browser.force_login(self.tr)
        return browser.get(reverse("dashboard:translator_payroll"), {"classic": 1}).content.decode("utf-8")

    def test_a_pending_bonus_is_carried_as_the_classic_property_says(self):
        line = self.slip(self.tr, self.year, self.month, discipline_bonus_earned=True, bonuses_approved=False)
        self.assertEqual(_json(self.payroll(self.tr))["line"]["pending_bonus"], str(line.pending_bonus))
        PayrollLine.objects.filter(pk=line.pk).update(bonuses_approved=True)
        self.assertEqual(_json(self.payroll(self.tr))["line"]["pending_bonus"], "0.00")


class PayrollHandOnTests(_Screen):
    def classic(self, user, **query):
        browser = DjangoClient()
        browser.force_login(user)
        return browser.get(reverse("dashboard:translator_payroll"), query)

    def test_a_translator_with_the_switch_is_sent_to_the_new_payslip_and_keeps_the_month(self):
        self.turn_on(roles=["translator"])
        answer = self.classic(self.tr)
        self.assertEqual((answer.status_code, answer["Location"]), (302, "/app/payroll"))
        self.assertEqual(self.classic(self.tr, period="2026-09")["Location"], "/app/payroll?period=2026-09")

    def test_what_is_not_a_month_is_not_carried_into_the_address(self):
        self.turn_on(roles=["translator"])
        for bad in ("evil", "//evil.example", "2026-09&x=1", "2026-13"):
            self.assertEqual(self.classic(self.tr, period=bad)["Location"], "/app/payroll", bad)

    def test_without_the_switch_or_with_classic_the_classic_page_opens(self):
        self.assertEqual(self.classic(self.tr).status_code, 200)
        self.turn_on(roles=["translator"])
        self.assertEqual(self.classic(self.tr, classic=1).status_code, 200)

    def test_the_admin_is_never_sent_on_from_it(self):
        self.turn_on(roles=["translator", "admin"])
        self.assertEqual(self.classic(self.admin).status_code, 200)


# ---------------------------------------------------------------------------------------------------------------------
# The task page
# ---------------------------------------------------------------------------------------------------------------------

class TaskApiTests(_Screen):
    def test_the_translator_and_the_admin_are_answered_everybody_else_is_refused(self):
        for user in (self.tr, self.admin):
            self.assertEqual(self.task_page(user).status_code, 200, user.username)
        for user in (self.ops, self.lead, self.hr, self.reviewer, self.accounting, self.sales):
            answer = self.task_page(user)
            self.assertEqual((answer.status_code, _json(answer)), (403, {"ok": False, "error": "forbidden"}), user.username)
        self.assertEqual(self.task_page(None).status_code, 401)
        browser = DjangoClient()
        browser.force_login(self.tr)
        self.assertEqual(browser.post(reverse(TASK, args=[self.task.code])).status_code, 405)
        self.assertEqual(self.task_page(self.tr)["Cache-Control"], "private, no-store")

    def test_a_task_that_is_not_theirs_is_a_404_and_a_row_in_the_audit_log(self):
        other = self.other_translator()
        theirs = _make_task(self, translator=other, title="Not yours", description="THEIR PRIVATE BRIEF")
        before = AuditLog.objects.filter(actor=self.tr, action="security.denied").count()
        answer = self.task_page(self.tr, theirs.code)
        self.assertEqual((answer.status_code, _json(answer)), (404, {"ok": False, "error": "not_found"}))
        self.assertNotIn(b"THEIR PRIVATE", answer.content)
        self.assertNotIn(theirs.code.encode(), answer.content)
        self.assertEqual(AuditLog.objects.filter(actor=self.tr, action="security.denied").count(), before + 1)
        # A code that is not a task at all answers the same, so the answer says nothing about which exist.
        self.assertEqual(_json(self.task_page(self.tr, "TSK-99999")), {"ok": False, "error": "not_found"})

    def test_a_task_of_theirs_that_was_taken_back_is_no_longer_theirs_to_open(self):
        other = self.other_translator()
        Task.objects.filter(pk=self.task.pk).update(translator=other)
        self.assertEqual(self.task_page(self.tr).status_code, 404)

    def test_the_task_as_the_classic_page_shows_it(self):
        mine = timezone.now() + timedelta(hours=2)
        clients = timezone.now() + timedelta(days=9)
        Task.objects.filter(pk=self.task.pk).update(translator_deadline=mine, deadline=clients, source_lang="Arabic",
                                                    target_lang="English")
        task = _json(self.task_page(self.tr))["task"]
        self.assertEqual((task["code"], task["title"]), (self.task.code, "Doc"))
        self.assertEqual(task["status"]["value"], TaskStatus.IN_PROGRESS)
        self.assertTrue(task["status"]["ar"] and task["status"]["en"] and task["status"]["tone"])
        self.assertEqual(task["client"], self.client_obj.code)
        self.assertEqual((task["source_lang"], task["target_lang"]), ("Arabic", "English"))
        self.assertEqual(task["people"], {"operation": self.ops.short_name, "team_lead": self.lead.short_name,
                                          "translator": self.tr.short_name})
        # The translator's own date: never the client's.
        self.assertEqual(task["due"]["en"], clock.fmt12(mine, "en", "%Y-%m-%d"))
        self.assertEqual(task["due"]["ar"], clock.fmt12(mine, "ar", "%Y-%m-%d"))
        self.assertNotIn(timezone.localtime(clients).strftime("%Y-%m-%d"), self.task_page(self.tr).content.decode("utf-8"))
        self.assertTrue(task["mine"])
        self.assertIn(task["due_state"], ("ok", "soon"))

    def test_no_deadline_at_all_is_null_and_not_an_error(self):
        Task.objects.filter(pk=self.task.pk).update(translator_deadline=None, deadline=None)
        task = _json(self.task_page(self.tr))["task"]
        self.assertEqual((task["due"], task["due_state"]), (None, "none"))

    def test_nothing_of_the_clients_identity_reaches_the_translator_anywhere_on_the_page(self):
        Task.objects.filter(pk=self.task.pk).update(
            description=f"For {CLIENT_NAME}. Call {CLIENT_PHONE} or write to {CLIENT_EMAIL}.",
        )
        ClientRequirement.objects.create(client=self.client_obj, kind="rule", author=self.ops,
                                         text=f"{CLIENT_NAME.upper()} wants British spelling ({CLIENT_EMAIL})")
        ExtensionRequest.objects.create(task=self.task, requested_by=self.tr, minutes=60,
                                        reason=f"The file from {CLIENT_EMAIL} is huge")
        AICheckResult.objects.create(task=self.task, requested_by=self.tr, status="issues",
                                     summary=f"Looked at {CLIENT_PHONE}")
        raw = self.task_page(self.tr).content.decode("utf-8")
        for marker in IDENTITY_MARKERS + (CLIENT_NAME, CLIENT_PHONE, CLIENT_EMAIL, CLIENT_NAME.upper()):
            self.assertNotIn(marker, raw, marker)
        task = json.loads(raw)["task"]
        # The name is the code, not a hole: the brief still reads.
        self.assertIn(f"For {self.client_obj.code}.", task["description"])
        self.assertIn(self.client_obj.code, task["requirements"][0]["text"])

    def test_the_admin_who_may_know_the_client_gets_the_words_as_they_were_written(self):
        Task.objects.filter(pk=self.task.pk).update(description=f"For {CLIENT_NAME}. Call {CLIENT_PHONE}.")
        task = _json(self.task_page(self.admin))["task"]
        self.assertEqual(task["description"], f"For {CLIENT_NAME}. Call {CLIENT_PHONE}.")
        self.assertIn(CLIENT_NAME, task["client"])

    def test_the_placeholder_lines_are_taken_out_of_the_brief(self):
        Task.objects.filter(pk=self.task.pk).update(description="[document]\nTranslate pages 2-4\n[image]")
        self.assertEqual(_json(self.task_page(self.tr))["task"]["description"], "Translate pages 2-4")

    def test_the_files_the_job_is_and_the_ones_handed_in(self):
        inbound = InboundMessage.objects.filter(task=self.task).first()
        MessageAttachment.objects.create(message=inbound, file=ContentFile(b"o", name="contract.pdf"),
                                         original_name="contract.pdf", size=2048)
        MessageAttachment.objects.create(message=inbound, file=ContentFile(b"p", name="photo.png"),
                                         original_name="photo.png", size=10)
        MessageAttachment.objects.create(message=inbound, file=ContentFile(b"v", name="talk.ogg"),
                                         original_name="talk.ogg", size=5)
        sent = ChatMessage.objects.create(room=self.work_group, sender=self.tr, task=self.task, body="done")
        ChatAttachment.objects.create(message=sent, file=ContentFile(b"t", name="translated.docx"),
                                      original_name="translated.docx", size=1536)
        # Somebody else's file in the same group, for another task: not this job's.
        stray = ChatMessage.objects.create(room=self.work_group, sender=self.lead, body="unrelated")
        ChatAttachment.objects.create(message=stray, file=ContentFile(b"x", name="unrelated.pdf"),
                                      original_name="unrelated.pdf", size=1)
        task = _json(self.task_page(self.tr))["task"]
        original = {f["name"]: f for f in task["files"]["original"]}
        # A voice note is talk, not a document to translate.
        self.assertEqual(sorted(original), ["contract.pdf", "photo.png"])
        self.assertEqual((original["contract.pdf"]["size"], original["contract.pdf"]["image"]), ("2.0 KB", False))
        self.assertTrue(original["photo.png"]["image"])
        self.assertTrue(original["contract.pdf"]["url"].startswith("/"))
        (handed,) = task["files"]["translation"]
        self.assertEqual((handed["name"], handed["size"]), ("translated.docx", "1.5 KB"))
        self.assertTrue(handed["at"]["ar"] and handed["at"]["en"])
        self.assertNotIn("unrelated.pdf", json.dumps(task))
        self.assertFalse(task["translation_missing"])

    def test_the_upload_box_and_the_finished_button_are_the_translators_own_while_the_job_is_in_progress(self):
        task = _json(self.task_page(self.tr))["task"]
        self.assertEqual((task["can_upload"], task["translation_missing"], task["under_review"]), (True, True, False))
        Task.objects.filter(pk=self.task.pk).update(status=TaskStatus.UNDER_REVIEW)
        task = _json(self.task_page(self.tr))["task"]
        self.assertEqual((task["can_upload"], task["under_review"]), (False, True))
        # The admin may look; none of the translator's buttons is theirs.
        Task.objects.filter(pk=self.task.pk).update(status=TaskStatus.IN_PROGRESS)
        task = _json(self.task_page(self.admin))["task"]
        self.assertEqual((task["mine"], task["can_upload"], task["under_review"], task["extension"]["can_ask"],
                          task["ai"]["visible"]), (False, False, False, False, False))

    def test_more_time_can_be_asked_while_in_progress_and_nothing_is_pending(self):
        self.assertTrue(_json(self.task_page(self.tr))["task"]["extension"]["can_ask"])
        ExtensionRequest.objects.create(task=self.task, requested_by=self.tr, minutes=90, reason="Heavy tables")
        extension = _json(self.task_page(self.tr))["task"]["extension"]
        self.assertEqual((extension["can_ask"], extension["pending"], extension["last"]),
                         (False, {"minutes": 90, "reason": "Heavy tables"}, None))

    def test_the_leaders_answer_to_an_earlier_request_is_shown_with_its_note(self):
        ExtensionRequest.objects.create(task=self.task, requested_by=self.tr, minutes=1500, reason="x", status="declined",
                                        decided_by=self.lead, decided_at=timezone.now(), decision_note="Client needs it today")
        extension = _json(self.task_page(self.tr))["task"]["extension"]
        self.assertTrue(extension["can_ask"])
        self.assertIsNone(extension["pending"])
        self.assertEqual((extension["last"]["status"], extension["last"]["minutes"], extension["last"]["note"]),
                         ("declined", 1500, "Client needs it today"))
        self.assertTrue(extension["last"]["at"]["ar"])

    def test_the_chat_is_a_link_to_the_group_with_the_leader_never_to_the_client(self):
        chat = _json(self.task_page(self.tr))["task"]["chat"]
        self.assertEqual(chat["url"], f"/ops/chats/g/{self.work_group.pk}/")
        self.assertTrue(chat["label_ar"] and chat["label_en"])
        self.assertNotIn(str(self.task_client_room.pk), chat["url"])

    def test_the_clients_requirements_and_the_assignment_history(self):
        ClientRequirement.objects.create(client=self.client_obj, kind="like", author=self.ops, text="Formal tone")
        ClientRequirement.objects.create(client=self.client_obj, kind="dislike", author=None, text="Contractions")
        task = _json(self.task_page(self.tr))["task"]
        self.assertEqual([(r["kind"]["value"], r["author"], r["text"]) for r in task["requirements"]],
                         [("dislike", None, "Contractions"), ("like", self.ops.short_name, "Formal tone")])
        self.assertTrue(task["requirements"][0]["kind"]["ar"] and task["requirements"][0]["kind"]["en"])
        names = [(h["name"], h["role"], h["status"]) for h in task["history"]]
        self.assertIn((self.lead.short_name, "team_lead", "accepted"), names)
        self.assertIn((self.tr.short_name, "translator", "accepted"), names)

    def test_another_clients_requirements_are_not_on_this_page(self):
        from .models import Client

        other = Client.objects.create(name="Other Co", phone="+201005550000")
        ClientRequirement.objects.create(client=other, kind="rule", author=self.ops, text="NOT THIS CLIENT'S RULE")
        self.assertNotIn("NOT THIS CLIENT", self.task_page(self.tr).content.decode("utf-8"))

    def test_the_operations_and_the_leaders_cards_are_not_on_the_translators_page(self):
        # The word count, the delivery log, the client's own messages, the leader's AI notes.
        raw = self.task_page(self.tr).content.decode("utf-8")
        for absent in ("word_count", "deliveries", "source_messages", "ai_notes", "deliverables", "claimed_by"):
            self.assertNotIn(absent, raw, absent)
        self.assertNotIn("hello there", raw)

    def test_the_ai_check_card_is_theirs_with_the_last_five_checks_and_the_switch(self):
        self.assertEqual(_json(self.task_page(self.tr))["task"]["ai"], {"visible": True, "enabled": False, "checks": []})
        conf = AppSettings.load()
        conf.ai_check_enabled = True
        conf.save()
        base = timezone.now() - timedelta(hours=1)
        for index in range(7):
            # The newest is the one that ran by itself (nobody asked). Distinct moments: a clock may not tick between rows.
            row = AICheckResult.objects.create(task=self.task, requested_by=None if index == 6 else self.tr,
                                               status="clean", summary=f"Check {index}")
            AICheckResult.objects.filter(pk=row.pk).update(created_at=base + timedelta(minutes=index))
        ai = _json(self.task_page(self.tr))["task"]["ai"]
        self.assertTrue(ai["enabled"])
        self.assertEqual([c["summary"] for c in ai["checks"]], [f"Check {n}" for n in (6, 5, 4, 3, 2)])
        self.assertEqual([c["automatic"] for c in ai["checks"]], [True, False, False, False, False])

    def test_somebody_elses_ai_checks_are_not_shown_to_a_translator_who_is_not_on_the_task(self):
        other = self.other_translator()
        theirs = _make_task(self, translator=other, title="Not yours")
        AICheckResult.objects.create(task=theirs, requested_by=other, status="issues", summary="OTHER'S CHECK")
        self.assertNotIn("OTHER'S CHECK", self.task_page(self.tr, theirs.code).content.decode("utf-8"))

    def test_a_cancelled_or_delivered_task_of_theirs_still_opens_to_read(self):
        for status in (TaskStatus.DELIVERED, TaskStatus.CANCELLED):
            Task.objects.filter(pk=self.task.pk).update(status=status)
            task = _json(self.task_page(self.tr))["task"]
            self.assertEqual((task["status"]["value"], task["can_upload"], task["extension"]["can_ask"]), (status, False, False))
            self.assertEqual(task["due_state"], "done")


class ExtensionStateTests(_Screen):
    """``services.extension_state`` is what the classic page and the new door share."""

    def test_the_translator_the_leader_and_the_admin_are_told_different_things_and_nobody_else_anything(self):
        ExtensionRequest.objects.create(task=self.task, requested_by=self.tr, minutes=60, reason="Heavy")
        for user, can_ask, can_decide in ((self.tr, False, False), (self.lead, False, True), (self.admin, False, True)):
            state = services.extension_state(self.task, user)
            self.assertEqual((state["extension_can_ask"], state["extension_can_decide"]), (can_ask, can_decide), user.username)
            self.assertIsNotNone(state["extension_pending"])
        # Only a leader is shown where the deadline would land - the translator never learns the client's date.
        self.assertIsNone(services.extension_state(self.task, self.tr)["extension_new_due"])
        for user in (self.ops, self.hr, self.sales, self.accounting, self.reviewer):
            self.assertEqual(services.extension_state(self.task, user), {}, user.username)


class TaskHandOnTests(_Screen):
    def classic(self, user, code=None, **query):
        browser = DjangoClient()
        browser.force_login(user)
        return browser.get(reverse("dashboard:task_detail", args=[code or self.task.code]), query)

    def test_a_translator_with_the_switch_is_sent_to_the_same_task_in_the_new_app(self):
        self.turn_on(roles=["translator"])
        answer = self.classic(self.tr)
        self.assertEqual((answer.status_code, answer["Location"]), (302, f"/app/tasks/{self.task.code}"))

    def test_without_the_switch_with_classic_or_for_anybody_else_the_classic_page_opens(self):
        self.assertEqual(self.classic(self.tr).status_code, 200)
        self.turn_on(roles=["translator", "admin", "operation", "team_lead"])
        self.assertEqual(self.classic(self.tr, classic=1).status_code, 200)
        # The classic page shows the admin, the operation and the leader what the translator's page leaves out.
        for user in (self.admin, self.ops, self.lead):
            self.assertEqual(self.classic(user).status_code, 200, user.username)

    def test_what_is_not_a_code_is_not_carried_into_the_address(self):
        self.turn_on(roles=["translator"])
        for odd in ("we.ird", "x" * 41, "a:b"):
            answer = self.classic(self.tr, odd)
            self.assertNotEqual(answer.status_code, 302, odd)
            self.assertEqual(answer.status_code, 404, odd)

    def test_a_task_that_is_not_theirs_is_sent_on_and_refused_there(self):
        self.turn_on(roles=["translator"])
        other = self.other_translator()
        theirs = _make_task(self, translator=other, title="Not yours")
        self.assertEqual(self.classic(self.tr, theirs.code)["Location"], f"/app/tasks/{theirs.code}")
        self.assertEqual(self.task_page(self.tr, theirs.code).status_code, 404)

    def test_an_assignment_waiting_for_an_answer_no_longer_holds_them_back_the_new_app_shows_it_itself(self):
        from .models import Assignment, AssignmentStatus

        self.turn_on(roles=["translator"])
        Assignment.objects.filter(assignee=self.tr).delete()
        task = _make_task(self, status=TaskStatus.LEAD_ACCEPTED, title="Needs an answer")
        services.assign_to_translator(task, self.tr, self.lead)
        self.assertTrue(Assignment.objects.filter(assignee=self.tr, status=AssignmentStatus.PENDING).exists())
        self.assertEqual(self.classic(self.tr, self.task.code).status_code, 302)

    def test_the_translators_desk_links_stay_the_classic_addresses_the_new_page_turns_into_routes(self):
        row = _json(self.door(self.tr, "dashboard:v1_translator_home"))["open"][0]
        self.assertEqual(row["url"], f"/tasks/{row['code']}/")


class QueryCostTests(_Screen):
    def test_the_task_page_costs_the_same_queries_however_much_is_on_it(self):
        from django.db import connection
        from django.test.utils import CaptureQueriesContext

        from .models import Client

        def cost():
            browser = DjangoClient()
            browser.force_login(self.tr)
            browser.get(reverse(TASK, args=[self.task.code]))  # warm the session and the settings row
            with CaptureQueriesContext(connection) as queries:
                self.assertEqual(browser.get(reverse(TASK, args=[self.task.code])).status_code, 200)
            return len(queries)

        few = cost()
        inbound = InboundMessage.objects.filter(task=self.task).first()
        sent = ChatMessage.objects.create(room=self.work_group, sender=self.tr, task=self.task, body="done")
        for index in range(12):
            ClientRequirement.objects.create(client=self.client_obj, kind="rule", author=self.ops, text=f"Rule {index}")
            MessageAttachment.objects.create(message=inbound, file=ContentFile(b"o", name=f"in{index}.pdf"),
                                             original_name=f"in{index}.pdf", size=1)
            ChatAttachment.objects.create(message=sent, file=ContentFile(b"t", name=f"out{index}.docx"),
                                          original_name=f"out{index}.docx", size=1)
            AICheckResult.objects.create(task=self.task, requested_by=self.tr, status="clean", summary=f"c{index}")
            ExtensionRequest.objects.create(task=self.task, requested_by=self.tr, minutes=10 + index, status="declined")
        self.assertEqual(cost(), few)


class MaskClientTests(_Screen):
    """``identity.mask_client``: the words people type about a client, for somebody who may not know who it is."""

    def mask(self, text, viewer=None, client=None):
        from . import identity

        return identity.mask_client(text, client or self.client_obj, viewer or self.tr)

    def test_the_name_becomes_the_code_however_it_is_cased_and_the_contacts_go(self):
        out = self.mask(f"{CLIENT_NAME} / {CLIENT_NAME.upper()} / {CLIENT_NAME.lower()}: {CLIENT_PHONE} {CLIENT_EMAIL}")
        self.assertEqual(out.count(self.client_obj.code), 3)
        for marker in IDENTITY_MARKERS + (CLIENT_NAME, CLIENT_PHONE, CLIENT_EMAIL):
            self.assertNotIn(marker.lower(), out.lower(), marker)

    def test_the_company_is_masked_as_well_as_the_name(self):
        from .models import Client

        client = Client.objects.create(name="Mr Hassan", company="Hassan Trading House", phone="+201009990000")
        out = self.mask("From Hassan Trading House, attention Mr Hassan", client=client)
        self.assertEqual(out, f"From {client.code}, attention {client.code}")

    def test_whoever_may_know_the_client_gets_the_words_as_written(self):
        text = f"{CLIENT_NAME} {CLIENT_PHONE}"
        self.assertEqual(self.mask(text, viewer=self.admin), text)
        self.assertEqual(self.mask(None, viewer=self.admin), "")

    def test_a_name_too_short_to_mean_anything_is_left_alone_and_nothing_breaks_without_a_client(self):
        from . import identity
        from .models import Client

        tiny = Client.objects.create(name="Al", phone="+201008880000")
        self.assertEqual(self.mask("Al-Ahram and Alexandria", client=tiny), "Al-Ahram and Alexandria")
        self.assertEqual(identity.mask_client("call +201001234567", None, self.tr), "call [...]")
        self.assertEqual(identity.mask_client(None, self.client_obj, self.tr), "")

    def test_a_name_with_regex_characters_is_taken_literally(self):
        from .models import Client

        client = Client.objects.create(name="A+B (Holdings) [x]", phone="+201007770000")
        self.assertEqual(self.mask("Deal with A+B (Holdings) [x] today", client=client), f"Deal with {client.code} today")
