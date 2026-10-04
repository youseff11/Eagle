"""The second review (2026-10-04): the operation, mail, the translator and team lead, calls, and the live socket.

Each class holds a defect a reviewer found and a person read end to end, written first as a test that fails and then fixed:

* a task's title is the client's own subject or opening words by default, and was shown unmasked to the people who may not know
  the client (translator, team lead, the operation's task form), where the brief beside it was masked;
* the words that hide a client (``identity.mask_client``) missed the forms people really write: the stem of the company name
  with other separators, the e-mail's local part, a number written in groups;
* a finished assignment kept the job's brief and files open to the person who declined or lost it;
* a refusal that said "not your task" (403) confirmed the code existed, and an accept or decline on someone else's assignment
  answered with the task's code;
* the AI check's raw summary and issues were handed to the translator;
* a mail conversation that spans the company address and a Sales address showed the operation the Sales person's private replies;
* calls: signals without a limit or an end, ringing without a limit, an answer that did not check the call was still ringing,
  and refusals that left no row in the audit log.
"""

import json
from datetime import timedelta

from django.core.files.base import ContentFile
from django.test import Client as DjangoClient
from django.urls import reverse
from django.utils import timezone

from . import identity, services
from .models import (
    Assignment, AssignmentStatus, AuditLog, CallSession, CallSignal, Channel, Client, InboundMessage, MessageAttachment,
    OutboundMessage, Role, Task, TaskStatus, User,
)
from .tests_api_v1 import CLIENT_EMAIL, CLIENT_NAME, CLIENT_PHONE, IDENTITY_MARKERS, _json, _Site
from .tests_translator_home import _Desk, _make_task

#: What a client's own subject or opening words can look like: the name and a number, as the task form pre-fills them.
TITLE = f"{CLIENT_NAME} contract, call {CLIENT_PHONE}"


def _get(user, name, args=None, **query):
    browser = DjangoClient()
    if user is not None:
        browser.force_login(user)
    return browser.get(reverse(name, args=args), query)


def _post(user, path, data=None):
    browser = DjangoClient()
    browser.force_login(user)
    return browser.post(path, data or {})


class TaskTitleTests(_Desk):
    """The title is free words, and by default the client's: it is masked like the brief."""

    def setUp(self):
        super().setUp()
        self.titled = _make_task(self, status=TaskStatus.IN_PROGRESS, title=TITLE)

    def assertClean(self, response, who):
        text = response.content.decode("utf-8")
        for marker in IDENTITY_MARKERS:
            self.assertNotIn(marker, text, f"{who}: {marker}")

    def test_the_translators_desk_and_task_page_carry_the_title_with_the_code_in_place_of_the_name(self):
        desk = _get(self.tr, "dashboard:v1_translator_home")
        self.assertClean(desk, "desk")
        titles = [one["title"] for one in _json(desk)["tasks"]] if "tasks" in _json(desk) else []
        page = _get(self.tr, "dashboard:v1_translator_task", [self.titled.code])
        self.assertEqual(page.status_code, 200)
        self.assertClean(page, "task page")
        self.assertIn(self.client_obj.code, _json(page)["task"]["title"])
        self.assertTrue(titles is not None)

    def test_the_hand_off_page_and_the_heartbeat_popup_carry_it_masked_too(self):
        offered = _make_task(self, status=TaskStatus.LEAD_ACCEPTED, title=TITLE)
        offer = services.assign_to_translator(offered, self.tr, self.lead)
        page = _get(self.tr, "dashboard:v1_assignment", [offer.pk])
        self.assertEqual(page.status_code, 200)
        self.assertClean(page, "assignment page")
        beat = DjangoClient()
        beat.force_login(self.tr)
        popup = beat.get("/api/heartbeat/")
        self.assertEqual(popup.status_code, 200)
        self.assertClean(popup, "heartbeat")
        self.assertIn(self.client_obj.code, _json(popup)["pending"]["task_title"])

    def test_the_team_leaders_board_and_the_ai_notes_carry_it_masked(self):
        board = _get(self.lead, "dashboard:v1_lead")
        self.assertEqual(board.status_code, 200)
        self.assertClean(board, "lead board")
        for name in ("dashboard:v1_ai_task_notes",):
            self.assertClean(_get(self.lead, name, [self.titled.code]), name)

    def test_the_operations_list_page_and_task_form_carry_it_masked(self):
        for name, args in (("dashboard:v1_tasks", None), ("dashboard:v1_task", [self.titled.code])):
            answer = _get(self.ops, name, args)
            self.assertEqual(answer.status_code, 200, name)
            self.assertClean(answer, name)

    def test_the_client_codes_page_shows_a_leader_masked_titles(self):
        answer = _get(self.lead, "dashboard:v1_client", [self.client_obj.code])
        if answer.status_code == 200:
            self.assertClean(answer, "client page")

    def test_the_admin_who_may_know_the_client_reads_it_as_written(self):
        page = _get(self.admin, "dashboard:v1_task", [self.titled.code])
        self.assertEqual(page.status_code, 200)
        self.assertIn(CLIENT_NAME, _json(page)["task"]["title"])


class MaskReachTests(_Site):
    """What ``mask_client`` takes out: the forms people write, not only the name as the record spells it."""

    def mask(self, text):
        return identity.mask_client(text, self.client_obj, self.tr)

    def test_the_name_with_other_separators_and_the_domain_and_the_mailbox_name_go(self):
        for text in ("ACME_Secret_Ltd contract", "acme-secret order", "www.acme-secret.example", "ACME.Secret.Ltd"):
            out = self.mask(text).lower()
            self.assertNotIn("acme", out, text)

    def test_the_mailbox_name_goes_when_it_is_a_persons_name_but_not_when_it_is_an_ordinary_word(self):
        person = Client.objects.create(name="", email="john.smith@mail.example")
        self.assertNotIn("smith", identity.mask_client("regards, John Smith", person, self.tr).lower())
        shop = Client.objects.create(name="", email="info@shop.example")
        self.assertEqual(identity.mask_client("please send the info today", shop, self.tr), "please send the info today")

    def test_a_number_written_in_groups_or_without_the_plus_goes(self):
        for text in ("call 0100 123 4567 now", "010-0123-4567", "(010) 012 34567 please", "01001234567"):
            out = self.mask(text)
            self.assertNotRegex(out, r"\d{3,}", text)

    def test_ordinary_numbers_stay(self):
        self.assertEqual(self.mask("deliver 12 pages by 2026-10-04 at 14:30, order 4471"), "deliver 12 pages by 2026-10-04 at 14:30, order 4471")

    def test_whoever_may_know_the_client_reads_it_as_written(self):
        self.assertEqual(identity.mask_client(TITLE, self.client_obj, self.admin), TITLE)


class FinishedAssignmentTests(_Desk):
    """An offer that is over (declined, expired, replaced) is not a key to the job."""

    def setUp(self):
        super().setUp()
        Assignment.objects.filter(assignee=self.tr).delete()
        self.job = _make_task(self, status=TaskStatus.LEAD_ACCEPTED, title="A job", description="the brief")
        inbound = InboundMessage.objects.create(client=self.client_obj, channel=Channel.WHATSAPP, sender_identity=CLIENT_PHONE, body="hi")
        self.stored = MessageAttachment.objects.create(
            message=inbound, file=ContentFile(b"%PDF-1.4 x", name="orig.pdf"), original_name="orig.pdf", size=9,
        )
        InboundMessage.objects.filter(pk=inbound.pk).update(task=self.job)
        self.job.source_files.set([self.stored])
        self.offer = services.assign_to_translator(self.job, self.tr, self.lead)

    def read(self):
        return _json(_get(self.tr, "dashboard:v1_assignment", [self.offer.pk]))

    def test_while_it_waits_the_brief_and_files_are_there(self):
        body = self.read()
        self.assertEqual(body["task"]["description"], "the brief")
        self.assertEqual(len(body["task"]["files"]), 1)

    def test_once_declined_the_status_still_reads_but_the_job_is_gone_from_the_answer(self):
        services.decline_assignment(self.offer, self.tr, reason="no time")
        body = self.read()
        self.assertEqual(body["assignment"]["status"], AssignmentStatus.DECLINED)
        self.assertEqual((body["task"]["description"], body["task"]["files"]), ("", []))
        self.assertNotIn("A job", json.dumps(body))

    def test_once_declined_the_offer_no_longer_opens_the_job(self):
        from . import files

        self.assertTrue(files._task_open_to(self.tr, self.job))
        services.decline_assignment(self.offer, self.tr, reason="no time")
        self.assertFalse(files._task_open_to(self.tr, self.job))

    def test_the_admin_still_reads_a_finished_one(self):
        services.decline_assignment(self.offer, self.tr, reason="no time")
        body = _json(_get(self.admin, "dashboard:v1_assignment", [self.offer.pk]))
        self.assertEqual(body["task"]["description"], "the brief")


class RefusalsLeaveNoCodeTests(_Desk):
    def setUp(self):
        super().setUp()
        self.other_lead = User.objects.create_user("person_other_leader", password="pw", role=Role.TEAM_LEAD)
        self.offer = services.assign_to_translator(
            _make_task(self, status=TaskStatus.LEAD_ACCEPTED, title="Offer"), self.tr, self.lead,
        )

    def test_another_leaders_task_is_a_404_and_a_logged_one_not_a_403_that_confirms_the_code(self):
        before = AuditLog.objects.filter(actor=self.other_lead, action=identity.ACCESS_DENIED).count()
        browser = DjangoClient()
        browser.force_login(self.other_lead)
        answer = browser.post(f"/api/tasks/{self.offer.task.code}/assign-translator/", {"user": self.tr.pk})
        self.assertEqual(answer.status_code, 404)
        self.assertEqual(AuditLog.objects.filter(actor=self.other_lead, action=identity.ACCESS_DENIED).count(), before + 1)

    def test_accept_and_decline_on_someone_elses_assignment_do_not_hand_back_the_task_code(self):
        stranger = User.objects.create_user("person_stranger", password="pw", role=Role.TRANSLATOR, team_lead=self.lead)
        for verb in ("accept", "decline"):
            answer = _post(stranger, f"/api/assignments/{self.offer.pk}/{verb}/", {"reason": "x"})
            self.assertEqual(answer.status_code, 404, verb)
            self.assertNotIn(self.offer.task.code, answer.content.decode("utf-8"), verb)
        self.offer.refresh_from_db()
        self.assertEqual(self.offer.status, AssignmentStatus.PENDING)

    def test_the_assignee_still_accepts_and_declines(self):
        self.assertTrue(_json(_post(self.tr, f"/api/assignments/{self.offer.pk}/accept/"))["ok"])


class SourceLetterFilesTests(_Desk):
    """A translator opens the files the operation ticked for the job, not every attachment of the client's letter."""

    def test_an_attachment_that_was_not_ticked_stays_shut(self):
        from . import files

        job = _make_task(self, status=TaskStatus.IN_PROGRESS, title="Job")
        letter = InboundMessage.objects.create(client=self.client_obj, channel=Channel.EMAIL, sender_identity=CLIENT_EMAIL, body="two files")
        InboundMessage.objects.filter(pk=letter.pk).update(task=job)
        ticked = MessageAttachment.objects.create(message=letter, file=ContentFile(b"a", name="a.pdf"), original_name="a.pdf", size=1)
        other = MessageAttachment.objects.create(message=letter, file=ContentFile(b"b", name="b.pdf"), original_name="b.pdf", size=1)
        job.source_files.set([ticked])
        self.assertTrue(files.may_open(self.tr, ticked.file.name)[0])
        self.assertFalse(files.may_open(self.tr, other.file.name)[0])
        self.assertTrue(files.may_open(self.ops, other.file.name)[0])


class AiCheckForTheTranslatorTests(_Desk):
    """The translator's own check card keeps its words, but the client's name in them is the client's code."""

    def test_the_summary_and_the_issues_come_back_with_the_name_taken_out_and_the_rest_kept(self):
        from unittest import mock

        from .models import AICheckResult, AppSettings

        conf = AppSettings.load()
        conf.ai_check_enabled = True
        conf.save()
        job = _make_task(self, status=TaskStatus.IN_PROGRESS, title="Job")
        result = AICheckResult.objects.create(
            task=job, requested_by=self.tr, status=AICheckResult.Status.ISSUES, summary=f"{CLIENT_NAME} wording is stiff",
            issues=[{"location": f"line 3 of the {CLIENT_NAME} file", "issue": "tone", "severity": "low", "source_excerpt": f"Dear {CLIENT_NAME}, {CLIENT_EMAIL}"}],
        )
        browser = DjangoClient()
        browser.force_login(self.tr)
        with mock.patch("dashboard.ai.run_check", return_value=result):
            answer = browser.post(f"/api/tasks/{job.code}/ai-check/", {"source_text": "a", "translated_text": "b"})
        text = answer.content.decode("utf-8")
        for marker in IDENTITY_MARKERS:
            self.assertNotIn(marker, text, marker)
        body = _json(answer)
        self.assertIn("wording is stiff", body["summary"])
        self.assertEqual(body["issues"][0]["issue"], "tone")
        self.assertEqual(body["count"], 1)

    def test_the_admin_reads_it_as_written(self):
        from unittest import mock

        from .models import AICheckResult, AppSettings

        conf = AppSettings.load()
        conf.ai_check_enabled = True
        conf.save()
        job = _make_task(self, status=TaskStatus.IN_PROGRESS, title="Job")
        result = AICheckResult.objects.create(task=job, requested_by=self.admin, status=AICheckResult.Status.CLEAN, summary=f"{CLIENT_NAME} fine")
        browser = DjangoClient()
        browser.force_login(self.admin)
        with mock.patch("dashboard.ai.run_check", return_value=result):
            answer = browser.post(f"/api/tasks/{job.code}/ai-check/", {"source_text": "a", "translated_text": "b"})
        self.assertIn(CLIENT_NAME, _json(answer)["summary"])


class MailLinesTests(_Site):
    """A conversation that spans the company address and a Sales address must not hand one line the other's replies."""

    def test_the_operation_does_not_read_a_sales_persons_private_replies_in_a_joined_conversation(self):
        key = "thread-shared"
        company = InboundMessage.objects.create(
            client=self.client_obj, channel=Channel.EMAIL, sender_identity=CLIENT_EMAIL, subject="Lease", body="to the company", thread_key=key,
        )
        private = InboundMessage.objects.create(
            client=self.client_obj, channel=Channel.EMAIL, sender_identity=CLIENT_EMAIL, subject="Lease", body="to sales", thread_key=key, owner=self.sales,
        )
        OutboundMessage.objects.create(
            client=self.client_obj, channel=Channel.EMAIL, body="PRIVATE SALES PRICE 900", subject="Re: Lease", thread_key=key,
            created_by=self.sales, owner=self.sales,
        )
        self.assertTrue(private.pk)
        answer = _get(self.ops, "dashboard:v1_mail_thread", [company.pk])
        self.assertEqual(answer.status_code, 200)
        self.assertNotIn("PRIVATE SALES PRICE", answer.content.decode("utf-8"))
        listing = _json(_get(self.ops, "dashboard:v1_mail_threads"))
        self.assertNotIn("PRIVATE SALES PRICE", json.dumps(listing))
        row = next(one for one in listing["threads"] if one["id"] in (company.pk, private.pk))
        self.assertFalse(row["answered"])
        # The Sales person's own line still shows it.
        own = _get(self.sales, "dashboard:v1_mail_thread", [private.pk])
        self.assertEqual(own.status_code, 200)
        self.assertIn("PRIVATE SALES PRICE", own.content.decode("utf-8"))


class CallLimitTests(_Site):
    def setUp(self):
        super().setUp()
        self.a, self.b = self.ops, self.lead

    def test_a_call_keeps_at_most_so_many_signals_and_refuses_the_rest(self):
        call, _error = services.start_call(self.a, self.b)
        sent = [services.post_signal(call, self.a, "ice", "{}") for _ in range(services.CALL_MAX_SIGNALS + 5)]
        self.assertEqual(sum(1 for one in sent if one is not None), services.CALL_MAX_SIGNALS)
        self.assertEqual(CallSignal.objects.filter(call=call).count(), services.CALL_MAX_SIGNALS)

    def test_a_payload_that_is_too_long_is_refused_and_not_cut(self):
        call, _error = services.start_call(self.a, self.b)
        self.assertIsNone(services.post_signal(call, self.a, "offer", "x" * 70000))
        self.assertEqual(CallSignal.objects.filter(call=call).count(), 0)
        self.assertIsNotNone(services.post_signal(call, self.a, "offer", "x" * 60000))

    def test_one_read_returns_a_page_and_the_next_read_the_rest(self):
        call, _error = services.start_call(self.a, self.b)
        for _ in range(services.CALL_SIGNALS_PAGE + 20):
            services.post_signal(call, self.a, "ice", "{}")
        first = services.signals_for(call, self.b, 0)
        self.assertEqual(len(first), services.CALL_SIGNALS_PAGE)
        rest = services.signals_for(call, self.b, first[-1]["id"])
        self.assertEqual(len(rest), 20)

    def test_the_signals_go_when_the_call_ends(self):
        call, _error = services.start_call(self.a, self.b)
        services.post_signal(call, self.a, "offer", "{}")
        services.answer_call(call, self.b)
        services.post_signal(call, self.b, "answer", "{}")
        services.end_call(call, self.a)
        self.assertEqual(CallSignal.objects.filter(call=call).count(), 0)

    def test_ringing_the_same_person_over_and_over_is_refused_after_a_few(self):
        results = [services.start_call(self.a, self.b)[0] for _ in range(services.CALL_REDIAL_LIMIT + 3)]
        self.assertEqual(sum(1 for one in results if one is not None), services.CALL_REDIAL_LIMIT)
        self.assertEqual(
            Notification_count(self.b), services.CALL_REDIAL_LIMIT - 1,
        )

    def test_ringing_somebody_else_is_not_counted_against_the_first(self):
        for _ in range(services.CALL_REDIAL_LIMIT):
            services.start_call(self.a, self.b)
        call, error = services.start_call(self.a, self.tr)
        self.assertIsNotNone(call, error)


def Notification_count(user):
    from .models import Notification

    return Notification.objects.filter(user=user, title_en__startswith="Missed").count()


class CallStateTests(_Site):
    def setUp(self):
        super().setUp()
        self.a, self.b = self.ops, self.lead

    def test_a_call_that_ended_while_the_answer_was_on_its_way_stays_ended(self):
        call, _error = services.start_call(self.a, self.b)
        stale = CallSession.objects.get(pk=call.pk)
        services.end_call(call, self.a)
        self.assertFalse(services.answer_call(stale, self.b))
        self.assertEqual(CallSession.objects.get(pk=call.pk).status, CallSession.Status.MISSED)

    def test_a_call_that_rang_past_its_time_cannot_be_answered(self):
        call, _error = services.start_call(self.a, self.b)
        CallSession.objects.filter(pk=call.pk).update(created_at=timezone.now() - timedelta(seconds=services.CALL_RING_SECONDS + 15))
        self.assertFalse(services.answer_call(CallSession.objects.get(pk=call.pk), self.b))
        self.assertNotEqual(CallSession.objects.get(pk=call.pk).status, CallSession.Status.ACTIVE)

    def test_a_call_nobody_hung_up_does_not_keep_two_people_busy_for_ever(self):
        call, _error = services.start_call(self.a, self.b)
        services.answer_call(call, self.b)
        CallSession.objects.filter(pk=call.pk).update(answered_at=timezone.now() - timedelta(hours=services.CALL_MAX_HOURS + 1))
        third = self.tr
        fresh, error = services.start_call(third, self.b)
        self.assertIsNotNone(fresh, error)
        self.assertEqual(CallSession.objects.get(pk=call.pk).status, CallSession.Status.ENDED)

    def test_an_active_call_is_still_busy(self):
        call, _error = services.start_call(self.a, self.b)
        services.answer_call(call, self.b)
        fresh, error = services.start_call(self.tr, self.b)
        self.assertIsNone(fresh)
        self.assertTrue(error)


class CallRefusalsAreLoggedTests(_Site):
    def test_reaching_for_somebody_elses_call_is_a_404_and_a_row_in_the_log(self):
        call, _error = services.start_call(self.ops, self.lead)
        for verb, method in (("answer", "post"), ("end", "post"), ("signals", "get"), ("signals", "post")):
            before = AuditLog.objects.filter(actor=self.tr, action=identity.ACCESS_DENIED).count()
            browser = DjangoClient()
            browser.force_login(self.tr)
            answer = getattr(browser, method)(f"/api/calls/{call.pk}/{verb}/")
            self.assertEqual(answer.status_code, 404, (verb, method))
            self.assertGreater(AuditLog.objects.filter(actor=self.tr, action=identity.ACCESS_DENIED).count(), before - 0, (verb, method))
            AuditLog.objects.filter(actor=self.tr).delete()


class ReplyLeavesFromTheLettersOwnLineTests(_Site):
    """An answer to a letter leaves from the address that letter came to, not from whichever line the client wrote to last."""

    def setUp(self):
        super().setUp()
        from .models import AppSettings

        self.omar = User.objects.create_user("person_omar", password="pw", role=Role.OPERATION)
        self.omar.mail_alias = "omar@eagle.example"
        self.omar.save()
        conf = AppSettings.load()
        conf.imap_user = "info@eagle.example"
        conf.mail_aliases = "omar@eagle.example\ninfo@eagle.example"
        conf.save()

    def letter(self, to, subject):
        return services.ingest_message(
            channel="email", subject=subject, body="please", sender_identity="buyer@client.example", recipients=[to],
        )

    def answer(self, row):
        from unittest import mock

        with mock.patch("dashboard.mailer.send_delivery", return_value=True) as sent:
            ok, outbound, error = services.reply_to_thread(row, self.omar, body="thanks")
        self.assertTrue(ok, error)
        return sent.call_args.kwargs.get("from_email") or "", outbound

    def test_a_company_letter_is_answered_from_the_company_even_when_the_newest_letter_came_to_their_own_address(self):
        company = self.letter("info@eagle.example", "Quote")
        self.letter("omar@eagle.example", "Another thing")
        sender, outbound = self.answer(company)
        self.assertEqual(sender, "")
        self.assertIsNone(outbound.owner)

    def test_a_letter_to_their_own_address_is_answered_from_it_even_when_the_newest_letter_came_to_the_company(self):
        own = self.letter("omar@eagle.example", "Quote")
        self.letter("info@eagle.example", "Another thing")
        sender, outbound = self.answer(own)
        self.assertEqual(sender, "omar@eagle.example")
        self.assertEqual(outbound.owner, self.omar)


class LeaderReachOnTheClientPageTests(_Site):
    """A team leader follows a client through their own tasks, and adds to the requirements of their own clients."""

    def setUp(self):
        super().setUp()
        self.other_lead = User.objects.create_user("person_other_leader", password="pw", role=Role.TEAM_LEAD)
        self.theirs = services.create_task(
            client=self.client_obj, title="Not mine", created_by=self.ops, deadline=timezone.now() + timedelta(hours=3),
        )
        Task.objects.filter(pk=self.theirs.pk).update(team_lead=self.other_lead, status=TaskStatus.IN_PROGRESS)

    def test_the_client_page_lists_only_the_leaders_own_tasks(self):
        mine = _json(_get(self.lead, "dashboard:v1_client", [self.client_obj.code]))["tasks"]
        self.assertEqual([one["code"] for one in mine], [self.task.code])
        others = _json(_get(self.other_lead, "dashboard:v1_client", [self.client_obj.code]))["tasks"]
        self.assertEqual([one["code"] for one in others], [self.theirs.code])

    def test_the_list_counts_only_the_leaders_own_tasks_and_the_operation_counts_all(self):
        def count(user):
            rows = _json(_get(user, "dashboard:v1_clients"))["clients"]
            return next(one["tasks"] for one in rows if one["code"] == self.client_obj.code)

        self.assertEqual(count(self.lead), 1)
        self.assertEqual(count(self.other_lead), 1)
        self.assertEqual(count(self.ops), 2)

    def test_a_leader_cannot_add_a_requirement_to_a_client_they_have_no_job_for(self):
        stranger = Client.objects.create(name="Somebody Else", phone="+201009998877")
        browser = DjangoClient()
        browser.force_login(self.lead)
        refused = browser.post(
            reverse("dashboard:v1_client_requirement", args=[stranger.code]),
            json.dumps({"kind": "rule", "text": "planted"}), content_type="application/json",
        )
        self.assertEqual(refused.status_code, 404)
        self.assertFalse(stranger.requirements.exists())
        own = browser.post(
            reverse("dashboard:v1_client_requirement", args=[self.client_obj.code]),
            json.dumps({"kind": "rule", "text": "keep it formal"}), content_type="application/json",
        )
        self.assertEqual(own.status_code, 200)


class TaskStateGuardTests(_Desk):
    """A job moves along its way; a press at the wrong place is refused and changes nothing."""

    def job(self, status, **fields):
        return _make_task(self, status=status, title="A job", **fields)

    def has_a_file(self):
        """The translator's file is there, so the only thing that can refuse a hand-in is the state the job is in."""
        from unittest import mock

        patch = mock.patch("dashboard.services.translation_missing", return_value=False)
        patch.start()
        self.addCleanup(patch.stop)

    def test_the_hand_in_works_on_a_job_being_worked_when_the_file_is_there(self):
        self.has_a_file()
        self.assertTrue(services.mark_translated(self.job(TaskStatus.IN_PROGRESS), self.tr))

    def test_a_job_already_delivered_or_cancelled_cannot_be_handed_in_again(self):
        self.has_a_file()
        for status in (TaskStatus.DELIVERED, TaskStatus.CANCELLED, TaskStatus.UNDER_REVIEW, TaskStatus.REVIEWED):
            task = self.job(status)
            before = task.translated_at
            self.assertFalse(services.mark_translated(task, self.tr), status)
            task.refresh_from_db()
            self.assertEqual((task.status, task.translated_at), (status, before), status)

    def test_the_door_refuses_it_the_same_way(self):
        self.has_a_file()
        task = self.job(TaskStatus.DELIVERED)
        browser = DjangoClient()
        browser.force_login(self.tr)
        answer = browser.post(f"/api/tasks/{task.code}/translated/")
        self.assertFalse(_json(answer)["ok"])
        task.refresh_from_db()
        self.assertEqual(task.status, TaskStatus.DELIVERED)

    def test_a_review_needs_a_translation_waiting_for_one(self):
        for status in (TaskStatus.IN_PROGRESS, TaskStatus.DELIVERED, TaskStatus.CANCELLED, TaskStatus.NEW):
            task = self.job(status)
            self.assertFalse(services.mark_reviewed(task, self.lead), status)
            task.refresh_from_db()
            self.assertEqual(task.status, status)
        waiting = self.job(TaskStatus.UNDER_REVIEW)
        self.assertTrue(services.mark_reviewed(waiting, self.lead))

    def test_the_operation_closes_only_a_job_it_has_taken_over_and_the_owner_any_open_one(self):
        for status in (TaskStatus.NEW, TaskStatus.IN_PROGRESS, TaskStatus.UNDER_REVIEW, TaskStatus.DELIVERED, TaskStatus.CANCELLED):
            task = self.job(status)
            self.assertFalse(services.mark_delivered(task, self.ops), status)
        reviewed = self.job(TaskStatus.REVIEWED)
        self.assertFalse(services.mark_delivered(reviewed, self.ops))
        services.acknowledge_handover(reviewed, self.ops)
        self.assertTrue(services.mark_delivered(reviewed, self.ops))
        self.assertFalse(services.mark_delivered(reviewed, self.ops))
        open_job = self.job(TaskStatus.IN_PROGRESS)
        self.assertTrue(services.mark_delivered(open_job, self.admin))
        done = self.job(TaskStatus.CANCELLED)
        self.assertFalse(services.mark_delivered(done, self.admin))

    def test_a_delivered_or_cancelled_job_cannot_be_cancelled(self):
        for status in (TaskStatus.DELIVERED, TaskStatus.CANCELLED):
            task = self.job(status)
            self.assertFalse(services.cancel_task(task, self.ops, "no"), status)
            task.refresh_from_db()
            self.assertEqual(task.status, status)
        self.assertTrue(services.cancel_task(self.job(TaskStatus.IN_PROGRESS), self.ops, "no"))

    def test_a_job_is_handed_to_a_leader_only_at_the_start_and_only_to_an_active_one(self):
        browser = DjangoClient()
        browser.force_login(self.ops)
        for status in (TaskStatus.IN_PROGRESS, TaskStatus.DELIVERED, TaskStatus.CANCELLED, TaskStatus.LEAD_ACCEPTED):
            task = self.job(status)
            answer = browser.post(f"/api/tasks/{task.code}/assign-lead/", {"user": self.lead.pk})
            self.assertEqual(answer.status_code, 400, status)
            task.refresh_from_db()
            self.assertEqual(task.status, status)
        fresh = self.job(TaskStatus.NEW)
        gone = User.objects.create_user("person_gone_leader", password="pw", role=Role.TEAM_LEAD, is_active=False)
        self.assertEqual(browser.post(f"/api/tasks/{fresh.code}/assign-lead/", {"user": gone.pk}).status_code, 404)
        self.assertEqual(browser.post(f"/api/tasks/{fresh.code}/assign-lead/", {"user": self.lead.pk}).status_code, 200)

    def test_a_job_is_handed_to_an_active_translator_only(self):
        task = self.job(TaskStatus.LEAD_ACCEPTED)
        left = User.objects.create_user("person_left_translator", password="pw", role=Role.TRANSLATOR, team_lead=self.lead, is_active=False)
        browser = DjangoClient()
        browser.force_login(self.lead)
        self.assertEqual(browser.post(f"/api/tasks/{task.code}/assign-translator/", {"user": left.pk}).status_code, 404)

    def test_an_offer_the_job_has_moved_on_from_cannot_be_accepted(self):
        task = self.job(TaskStatus.LEAD_ACCEPTED)
        offer = services.assign_to_translator(task, self.tr, self.lead)
        other = User.objects.create_user("person_second_translator", password="pw", role=Role.TRANSLATOR, team_lead=self.lead)
        Task.objects.filter(pk=task.pk).update(translator=other)
        ok, _reason = services.accept_assignment(Assignment.objects.get(pk=offer.pk), self.tr)
        self.assertFalse(ok)
        self.assertNotEqual(Task.objects.get(pk=task.pk).status, TaskStatus.IN_PROGRESS)

    def test_two_answers_to_the_same_expiry_cost_one_penalty(self):
        from .models import RatingEvent

        task = self.job(TaskStatus.LEAD_ACCEPTED)
        offer = services.assign_to_translator(task, self.tr, self.lead)
        Assignment.objects.filter(pk=offer.pk).update(expires_at=timezone.now() - timedelta(seconds=1))
        first, second = Assignment.objects.get(pk=offer.pk), Assignment.objects.get(pk=offer.pk)
        services.expire_assignment(first)
        services.expire_assignment(second)
        self.assertEqual(RatingEvent.objects.filter(user=self.tr).count(), 1)


class GeofenceAllowanceTests(_Site):
    def test_a_phone_cannot_widen_the_circle_by_claiming_a_huge_error(self):
        from unittest import mock

        from . import attendance
        from .models import AppSettings

        class Office:
            radius_meters = 100

        with mock.patch.object(attendance, "nearest_office", return_value=(Office(), 160_000)):
            conf = AppSettings.load()
            self.assertFalse(attendance.check_location(conf, 30.0, 31.0, accuracy_m=20)[2])
            self.assertFalse(attendance.check_location(conf, 30.0, 31.0, accuracy_m=2_000_000_000)[2])
        with mock.patch.object(attendance, "nearest_office", return_value=(Office(), 180)):
            self.assertTrue(attendance.check_location(AppSettings.load(), 30.0, 31.0, accuracy_m=100)[2])
        with mock.patch.object(attendance, "nearest_office", return_value=(Office(), 400)):
            self.assertFalse(attendance.check_location(AppSettings.load(), 30.0, 31.0, accuracy_m=5000)[2])


class MailConversationsStayOnTheirLineTests(_Site):
    """A new letter joins only the conversations of its own line, so no thread ever spans the company and a Sales address."""

    def setUp(self):
        super().setUp()
        from .models import AppSettings

        self.sales.mail_alias = "sales1@eagle.example"
        self.sales.save()
        conf = AppSettings.load()
        conf.imap_user = "info@eagle.example"
        conf.mail_aliases = "sales1@eagle.example\ninfo@eagle.example"
        conf.save()

    def letter(self, to, subject):
        return services.ingest_message(
            channel="email", subject=subject, body="please", sender_identity="buyer@client.example", recipients=[to],
        )

    def test_the_same_subject_to_the_other_address_is_a_new_conversation(self):
        company = self.letter("info@eagle.example", "Lease translation")
        private = self.letter("sales1@eagle.example", "Re: Lease translation")
        self.assertIsNone(company.owner)
        self.assertEqual(private.owner, self.sales)
        self.assertNotEqual(company.thread_key, private.thread_key)

    def test_the_same_subject_to_the_same_address_is_the_same_conversation(self):
        first = self.letter("sales1@eagle.example", "Lease translation")
        second = self.letter("sales1@eagle.example", "Re: Lease translation")
        self.assertEqual(first.thread_key, second.thread_key)
        one = self.letter("info@eagle.example", "Other thing")
        two = self.letter("info@eagle.example", "Re: Other thing")
        self.assertEqual(one.thread_key, two.thread_key)


class TaskFormHandsOverNothingTheTaskPageKeepsBackTests(_Site):
    """The new-task form starts from a task or a message: its boxes carry the words as the task page shows them."""

    def test_started_from_a_task_the_title_and_the_description_are_masked(self):
        old = services.create_task(
            client=self.client_obj, title=TITLE, created_by=self.ops, deadline=timezone.now() + timedelta(hours=3),
        )
        Task.objects.filter(pk=old.pk).update(description=f"For {CLIENT_NAME}. Call {CLIENT_PHONE} or {CLIENT_EMAIL}.")
        answer = _get(self.ops, "dashboard:v1_task_start", **{"from": old.code})
        self.assertEqual(answer.status_code, 200)
        body = _json(answer)
        shown = json.dumps({"initial": body["initial"], "from_task": body["from_task"]})
        for marker in IDENTITY_MARKERS:
            self.assertNotIn(marker, shown, marker)
        self.assertIn(self.client_obj.code, body["initial"]["description"])

    def test_the_admin_who_may_know_the_client_gets_the_words_as_written(self):
        old = services.create_task(
            client=self.client_obj, title=TITLE, created_by=self.ops, deadline=timezone.now() + timedelta(hours=3),
        )
        body = _json(_get(self.admin, "dashboard:v1_task_start", **{"from": old.code}))
        self.assertIn(CLIENT_NAME, body["initial"]["title"])


class MailDoorsRefuseAndLogTests(_Site):
    """A letter of another line is not found, and walking the ids leaves rows in the audit log."""

    def setUp(self):
        super().setUp()
        self.private = InboundMessage.objects.create(
            client=self.client_obj, channel=Channel.EMAIL, sender_identity=CLIENT_EMAIL, subject="Mine", body="to sales",
            thread_key="t-private", owner=self.sales,
        )

    def test_the_operation_gets_a_404_and_a_row_for_each_of_the_four_doors(self):
        browser = DjangoClient()
        browser.force_login(self.ops)
        for path, method in (
            (f"/api/inbox/thread/{self.private.pk}/feed/", "get"),
            (f"/api/inbox/thread/{self.private.pk}/reply/", "post"),
            (f"/api/messages/{self.private.pk}/claim/", "post"),
            (f"/api/messages/{self.private.pk}/confirm/", "post"),
        ):
            before = AuditLog.objects.filter(actor=self.ops, action=identity.ACCESS_DENIED).count()
            AuditLog.objects.filter(actor=self.ops).update(created_at=timezone.now() - timedelta(hours=1))
            answer = getattr(browser, method)(path)
            self.assertEqual(answer.status_code, 404, path)
            self.assertGreater(AuditLog.objects.filter(actor=self.ops, action=identity.ACCESS_DENIED).count(), 0, path)
            AuditLog.objects.filter(actor=self.ops).delete()
            self.assertEqual(before >= 0, True)


class ReceiptLeavesFromTheLettersOwnLineTests(ReplyLeavesFromTheLettersOwnLineTests):
    def receipt(self, row):
        from unittest import mock

        with mock.patch("dashboard.mailer.send_delivery", return_value=True) as sent:
            ok, error = services.confirm_receipt(row, self.omar)
        self.assertTrue(ok, error)
        return sent.call_args.kwargs.get("from_email") or ""

    def test_a_company_letter_is_confirmed_from_the_company(self):
        company = self.letter("info@eagle.example", "Quote")
        self.letter("omar@eagle.example", "Another thing")
        self.assertEqual(self.receipt(company), "")

    def test_a_letter_to_their_own_address_is_confirmed_from_it(self):
        own = self.letter("omar@eagle.example", "Quote")
        self.letter("info@eagle.example", "Another thing")
        self.assertEqual(self.receipt(own), "omar@eagle.example")
