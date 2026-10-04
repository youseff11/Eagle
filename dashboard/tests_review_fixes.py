"""What the first review found in the new doors, held as tests so it cannot come back.

The reviewers (privacy, 2026-10-04) read the new screens; every test here was reproduced against the code as it was before it was
fixed. The classic pages are not held to anything here: they are being deleted, so a leak found only in a classic page is not
fixed (it is listed in HANDOFF.md).

* A client's name typed into free text (a complaint, a deduction's reason) must reach nobody who may not know the client: not HR
  and not the translator reading their own payslip. A complaint logged on a task, with the client box left blank, is about that
  task's client.
* A reviewer is blind in the files too: a test file opens for the reviewer it is assigned to (or for anyone while nobody has taken
  it), not for any reviewer who guesses the address, and it downloads under a neutral name.
* A message to a candidate is never sent from the client's number: with no recruitment line set it is refused.
* Nobody decides their own probation review, and probation reviews cannot close an account that is not on probation.
* Money, days and minutes are never below zero (a negative penalty pays); a draft the engine no longer raises is not left waiting
  to be approved; a day recorded over an existing day keeps what was not sent; an overtime claim for a corrected day is not paid.
* A leave range, a date on the board, an office on the map, a username and a job title have the limits the rest of the system has.
* The owner cannot close the last owner's account; a pilot who has gone does not block the settings; the simulation switch is
  read; the owner's edits and test sends leave rows in the log.
* What a stranger calls a file never leaves the folder it is stored in.
* What a client's name was not masked against when a file arrived is masked when the client is named, and what a client said
  goes when the client goes (the copies forwarded into other chats, the files shared for a task that is reset).
"""

import json
from datetime import timedelta
from unittest import mock

from django.core.files.base import ContentFile
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import Client as DjangoClient
from django.urls import reverse

from . import attendance, payroll, services, webhooks, whatsapp
from .forms import (
    HireForm, LeaveRequestForm, OfficeLocationForm, PayrollSettingsForm, ProductionTierForm, SalaryPlanForm, SalaryRecordForm,
    ViolationForm, WorkDayForm,
)
from .models import (
    AppSettings, ApprovalStatus, AuditLog, CandidateTest, ChatMessage, ChatRoom, Client, ClientComplaint, EmploymentStatus,
    InboundMessage, OvertimeClaim, PayrollPeriod, PayrollSettings, ProbationReview, RoomKind, User, Violation, WorkDay,
)
from .tests_accounts_screen import LINE, SALARY_SAVE, VIOLATION_NEW, VIOLATIONS, _Accounts
from .tests_admin_screen import _Admin
from .tests_api_v1 import CLIENT_NAME, _json
from .tests_hr_candidates import MESSAGE, TEST, _Cand
from .tests_hr_people import _People

PHONE_IN_TEXT = "+201234567890"


class ComplaintPrivacyTests(_People):
    def test_the_door_masks_when_only_a_task_was_picked(self):
        ClientComplaint.objects.create(
            summary=f"{CLIENT_NAME} was angry", detail=f"Call {CLIENT_NAME} on {PHONE_IN_TEXT}", task=self.task, translator=self.tr,
        )
        self.assertIsNone(ClientComplaint.objects.get().client_id)
        raw = self.read("dashboard:v1_hr_complaints").content.decode()
        self.assertNotIn(CLIENT_NAME, raw)
        self.assertNotIn(PHONE_IN_TEXT, raw)
        self.assertIn(self.client_obj.code, raw)
        self.assertIn(CLIENT_NAME, self.read("dashboard:v1_hr_complaints", self.admin).content.decode())


class PayrollPrivacyTests(_Accounts):
    def setUp(self):
        super().setUp()
        self.violation(task=self.task, reason=f"Complaint from {CLIENT_NAME} call {PHONE_IN_TEXT}", status=ApprovalStatus.APPROVED)
        self.violation(task=self.task, reason=f"Pending: {CLIENT_NAME}")

    def test_a_translator_reads_the_code_on_their_own_payslip(self):
        line = self.line_of()
        raw = self.get(self.tr, LINE, [line.pk]).content.decode()
        self.assertNotIn(CLIENT_NAME, raw)
        self.assertNotIn(PHONE_IN_TEXT, raw)
        self.assertIn(self.task.client.code, raw)

    def test_a_payslip_computed_before_the_violation_was_remembered_is_masked_too(self):
        line = self.line_of()
        breakdown = line.breakdown
        for rows in (breakdown["deductions"], breakdown["pending"]):
            for row in rows:
                row.pop("violation", None)
        type(line).objects.filter(pk=line.pk).update(breakdown=breakdown)
        self.assertNotIn(CLIENT_NAME, self.get(self.tr, LINE, [line.pk]).content.decode())

    def test_a_translator_reads_the_code_on_their_home_payroll(self):
        self.line_of()
        raw = self.get(self.tr, "dashboard:v1_translator_payroll").content.decode()
        self.assertNotIn(CLIENT_NAME, raw)
        self.assertNotIn(PHONE_IN_TEXT, raw)
        self.assertIn(self.task.client.code, raw)

    def test_a_locked_month_is_masked_too(self):
        line = self.line_of()
        type(line.period).objects.filter(pk=line.period_id).update(status="locked")
        self.assertNotIn(CLIENT_NAME, self.get(self.tr, LINE, [line.pk]).content.decode())

    def test_the_owner_reads_the_words_as_typed(self):
        line = self.line_of()
        self.assertIn(CLIENT_NAME, self.get(self.admin, LINE, [line.pk]).content.decode())


class ReviewerFileTests(_Cand):
    def setUp(self):
        super().setUp()
        self.theirs = self.exam_row(title="Theirs", reviewer=self.other_reviewer)
        self.theirs.submission = SimpleUploadedFile("Mona Candidate answer.docx", b"DOCX")
        self.theirs.submission_name = "Mona Candidate answer.docx"
        self.theirs.assignment = SimpleUploadedFile("Test - Mona Hassan.docx", b"DOCX")
        self.theirs.assignment_name = "Test - Mona Hassan.docx"
        self.theirs.save()
        self.url = self.theirs.submission.url

    def open(self, who, url=None):
        browser = DjangoClient()
        browser.force_login(who)
        return browser.get(url or self.url)

    def test_a_test_file_opens_for_who_the_test_is_assigned_to_and_for_hr_and_the_owner_not_for_another_reviewer(self):
        self.assertEqual(self.open(self.other_reviewer).status_code, 200)
        self.assertEqual(self.open(self.hr).status_code, 200)
        self.assertEqual(self.open(self.admin).status_code, 200)
        self.assertEqual(self.open(self.reviewer).status_code, 404)
        self.assertEqual(self.open(self.lead).status_code, 404)

    def test_a_test_nobody_has_taken_opens_for_any_reviewer(self):
        free = self.exam_row(title="Free", submission=SimpleUploadedFile("work.docx", b"DOCX"))
        self.assertEqual(self.open(self.reviewer, free.submission.url).status_code, 200)

    def test_a_reviewer_downloads_under_a_neutral_name_and_hr_under_the_stored_one(self):
        blind = self.open(self.other_reviewer)["Content-Disposition"]
        self.assertNotIn("Mona", blind)
        self.assertNotIn("Candidate", blind)
        self.assertIn(".docx", blind)
        self.assertIn("Mona", self.open(self.hr)["Content-Disposition"])

    def test_the_name_hr_gave_the_test_file_is_not_the_blind_reviewers_to_read(self):
        shown = _json(self.read_test(self.other_reviewer, self.theirs))["test"]["assignment"]["name"]
        self.assertEqual(shown, "assignment.docx")
        self.assertEqual(_json(self.read_test(self.admin, self.theirs))["test"]["assignment"]["name"], "Test - Mona Hassan.docx")

    def read_test(self, who, exam):
        return self.read(TEST, who=who, args=[exam.pk])


class CandidateLineTests(_Cand):
    def test_with_no_recruitment_line_a_message_is_refused_and_nothing_goes_out_on_the_clients_number(self):
        self.assertFalse(AppSettings.load().recruit_phone_number_id)
        with mock.patch.object(whatsapp, "send_text", return_value={}) as sent:
            answer = self.post(self.hr, MESSAGE, {"body": "Hello"}, [self.person.code])
        self.assertEqual((answer.status_code, _json(answer)["error"]), (409, "no_recruit_line"))
        sent.assert_not_called()

    def test_the_candidate_page_says_whether_the_line_is_set(self):
        self.assertFalse(_json(self.read("dashboard:v1_hr_candidate", args=[self.person.code]))["line_ready"])
        app = AppSettings.load()
        app.recruit_phone_number_id = "RECRUIT-LINE-1"
        app.save()
        self.assertTrue(_json(self.read("dashboard:v1_hr_candidate", args=[self.person.code]))["line_ready"])


class ProbationTests(_People):
    def own_review(self):
        User.objects.filter(pk=self.flagged.pk).update(employment_status=EmploymentStatus.PROBATION)
        self.flagged.refresh_from_db()
        return ProbationReview.objects.create(user=self.flagged, stage="final", due_date=self.today)

    def test_nobody_decides_their_own_review(self):
        review = self.own_review()
        answer = self.post(self.flagged, "dashboard:v1_hr_probation_decide", {"values": {"outcome": "confirmed"}}, [review.pk])
        self.assertEqual((answer.status_code, _json(answer)["error"]), (409, "refused"))
        self.flagged.refresh_from_db()
        review.refresh_from_db()
        self.assertEqual((self.flagged.employment_status, review.is_decided), (EmploymentStatus.PROBATION, False))

    def test_somebody_else_still_decides_it(self):
        review = self.own_review()
        answer = self.post(self.hr, "dashboard:v1_hr_probation_decide", {"values": {"outcome": "confirmed"}}, [review.pk])
        self.assertEqual(answer.status_code, 200, answer.content)
        self.flagged.refresh_from_db()
        self.assertEqual(self.flagged.employment_status, EmploymentStatus.ACTIVE)


class ProbationScopeTests(_People):
    def review_for(self, person, stage="final"):
        return ProbationReview.objects.create(user=person, stage=stage, due_date=self.today)

    def test_the_owner_cannot_be_given_reviews_or_ended_by_one(self):
        opened = self.post(self.hr, "dashboard:v1_hr_probation_open", {}, [self.admin.pk])
        self.assertEqual((opened.status_code, _json(opened)["error"]), (409, "refused"))
        self.assertFalse(ProbationReview.objects.filter(user=self.admin).exists())
        review = self.review_for(self.admin)
        decided = self.post(self.hr, "dashboard:v1_hr_probation_decide", {"values": {"outcome": "terminated"}}, [review.pk])
        self.assertEqual((decided.status_code, _json(decided)["error"]), (409, "refused"))
        self.admin.refresh_from_db()
        self.assertEqual((self.admin.is_active, self.admin.employment_status), (True, EmploymentStatus.ACTIVE))

    def test_a_confirmed_person_cannot_be_ended_by_a_review_left_over(self):
        self.assertEqual(self.tr.employment_status, EmploymentStatus.ACTIVE)
        review = self.review_for(self.tr, "day_30")
        decided = self.post(self.hr, "dashboard:v1_hr_probation_decide", {"values": {"outcome": "terminated"}}, [review.pk])
        self.assertEqual((decided.status_code, _json(decided)["error"]), (409, "refused"))
        self.tr.refresh_from_db()
        review.refresh_from_db()
        self.assertEqual((self.tr.is_active, review.is_decided), (True, False))

    def test_a_person_already_gone_is_not_brought_back_by_a_confirmation(self):
        User.objects.filter(pk=self.tr.pk).update(employment_status=EmploymentStatus.LEFT, is_active=False)
        review = self.review_for(self.tr)
        decided = self.post(self.hr, "dashboard:v1_hr_probation_decide", {"values": {"outcome": "confirmed"}}, [review.pk])
        self.assertEqual(decided.status_code, 409)
        self.tr.refresh_from_db()
        self.assertEqual((self.tr.employment_status, self.tr.is_active), (EmploymentStatus.LEFT, False))

    def test_somebody_on_probation_still_has_reviews_opened_and_decided(self):
        User.objects.filter(pk=self.tr.pk).update(employment_status=EmploymentStatus.PROBATION)
        opened = self.post(self.hr, "dashboard:v1_hr_probation_open", {}, [self.tr.pk])
        self.assertEqual((opened.status_code, _json(opened)["created"]), (200, 3))
        final = ProbationReview.objects.get(user=self.tr, stage="final")
        decided = self.post(self.hr, "dashboard:v1_hr_probation_decide", {"values": {"outcome": "confirmed"}}, [final.pk])
        self.assertEqual(decided.status_code, 200, decided.content)
        self.tr.refresh_from_db()
        self.assertEqual(self.tr.employment_status, EmploymentStatus.ACTIVE)


class ClientFileNameTests(_Admin):
    """The admin names a client whose letters arrived with no name to mask against."""

    def letter(self, name, phone="201055500123"):
        return services.ingest_message(
            channel="whatsapp", body="here", sender_identity=phone,
            attachments=[{"file": ContentFile(b"%PDF", name=name), "name": name, "size": 4}],
        )

    def name_the_client(self, client):
        import json

        browser = DjangoClient()
        browser.force_login(self.admin)
        body = json.dumps({"values": {"name": "Acme Holdings"}})
        return browser.post(reverse("dashboard:v1_admin_client_save", args=[client.code]), body, content_type="application/json")

    def test_a_file_name_stored_before_the_client_was_named_is_masked_when_they_are(self):
        letter = self.letter("Acme Holdings PO 2291.pdf")
        client = letter.client
        self.assertEqual(client.name, "")
        self.assertIn("Acme Holdings", letter.attachments.get().original_name)
        self.assertEqual(self.name_the_client(client).status_code, 200)
        stored = letter.attachments.get()
        self.assertNotIn("Acme", stored.original_name)
        self.assertIn(client.code, stored.original_name)
        self.assertIn("Acme Holdings", stored.raw_name)

    def test_a_copy_of_the_file_in_a_chat_is_masked_too(self):
        from .models import ChatAttachment

        letter = self.letter("Acme Holdings PO 2291.pdf")
        client = letter.client
        room = ChatRoom.objects.create(kind=RoomKind.TEAM, title="Team", created_by=self.ops)
        message = ChatMessage.objects.create(room=room, sender=self.ops, body="", origin_client=client)
        ChatAttachment.objects.create(
            message=message, file=ContentFile(b"%PDF", name="copy.pdf"), original_name="Acme Holdings PO 2291.pdf", origin_client=client,
        )
        self.name_the_client(client)
        self.assertNotIn("Acme", ChatAttachment.objects.get(message=message).original_name)

    def test_what_a_translator_reads_in_a_work_chat_has_no_company_after_the_naming(self):
        letter = self.letter("Acme Holdings PO 2291.pdf")
        client = letter.client
        room = ChatRoom.objects.create(kind=RoomKind.TEAM, title="Team", created_by=self.ops)
        message = ChatMessage.objects.create(room=room, sender=self.ops, body="", inbound=letter)
        self.name_the_client(client)
        shown = [attachment.original_name for attachment in message.relay_files]
        self.assertTrue(shown)
        self.assertTrue(all("Acme" not in name for name in shown), shown)

    def test_files_of_another_client_are_left_alone(self):
        other = self.letter("Acme Holdings PO 2291.pdf")
        mine = self.letter("Zed Co brief.pdf", phone="201066600456")
        self.name_the_client(other.client)
        self.assertEqual(mine.attachments.get().original_name, "Zed Co brief.pdf")


class ClientGoneTests(_Admin):
    def test_what_was_forwarded_out_of_a_deleted_clients_letters_goes_with_them(self):
        client = Client.objects.create(name="Gone Ltd", phone="201077700789")
        letter = InboundMessage.objects.create(client=client, body="Ahmed from Gone Ltd +20 100 000 0000")
        room = ChatRoom.objects.create(kind=RoomKind.TEAM, title="Team", created_by=self.ops)
        copy = ChatMessage.objects.create(room=room, sender=self.ops, body=letter.body, origin_client=client)
        keep = ChatMessage.objects.create(room=room, sender=self.ops, body="our own words")
        ok, _error, codes, _blocked, _removed = services.delete_clients(self.admin, [client.pk])
        self.assertTrue(ok)
        self.assertEqual(codes, [client.code])
        self.assertFalse(ChatMessage.objects.filter(pk=copy.pk).exists())
        self.assertTrue(ChatMessage.objects.filter(pk=keep.pk).exists())

    def test_the_files_shared_into_a_work_chat_for_a_task_go_with_a_task_reset(self):
        letter = services.ingest_message(
            channel="whatsapp", body="job", sender_identity="201088800321",
            attachments=[
                {"file": ContentFile(b"%PDF", name="job.pdf"), "name": "job.pdf", "size": 4},
                {"file": ContentFile(b"%PDF", name="contract.pdf"), "name": "contract.pdf", "size": 4},
            ],
        )
        task = services.create_task(client=letter.client, title="Job", created_by=self.ops, messages=[letter])
        task.source_files.set(letter.attachments.filter(original_name__startswith="job"))
        room = ChatRoom.objects.create(kind=RoomKind.TEAM, title="Work", created_by=self.ops)
        services.share_source_files(task, room=room)
        shared = room.messages.get(inbound=letter)
        self.assertEqual([a.original_name for a in shared.relay_files], ["job.pdf"])
        self.admin.set_password("owner-secret-1")
        self.admin.save()
        ok, error, _backup, _deleted = services.reset_all_tasks(self.admin, "owner-secret-1")
        self.assertTrue(ok, error)
        self.assertEqual([a.original_name for message in room.messages.all() for a in message.relay_files], [])


class MoneyBelowZeroTests(_Accounts):
    def test_no_form_takes_money_days_or_minutes_below_zero(self):
        for form, field in (
            (ViolationForm({"penalty_amount": "-1000"}), "penalty_amount"),
            (ViolationForm({"penalty_days": "-1"}), "penalty_days"),
            (SalaryRecordForm({"amount": "-5"}), "amount"),
            (SalaryPlanForm({"name": "x", "fixed_allowance": "-1"}), "fixed_allowance"),
            (SalaryPlanForm({"name": "x", "target_miss_penalty": "-1"}), "target_miss_penalty"),
            (PayrollSettingsForm({"target_bonus": "-5"}), "target_bonus"),
            (PayrollSettingsForm({"unexcused_penalty_days": "-1"}), "unexcused_penalty_days"),
            (ProductionTierForm({"bonus": "-1"}), "bonus"),
            (WorkDayForm({"late_minutes": "-3"}), "late_minutes"),
            (HireForm({"salary": "-1"}), "salary"),
        ):
            self.assertIn(field, form.errors, type(form).__name__)

    def test_a_amount_of_nothing_or_more_is_still_taken(self):
        self.assertNotIn("penalty_amount", ViolationForm({"penalty_amount": "0.50"}).errors)
        self.assertNotIn("amount", SalaryRecordForm({"amount": "0"}).errors)

    def test_a_negative_deduction_is_refused_by_the_door_and_pays_nothing(self):
        answer = self.post(self.accounting, VIOLATION_NEW, {"values": {
            "user": str(self.tr.pk), "date": self.today.isoformat(), "kind": "quality", "penalty_amount": "-1000", "reason": "x",
        }})
        self.assertEqual((answer.status_code, _json(answer)["error"]), (400, "invalid"))
        self.assertIn("penalty_amount", _json(answer)["errors"])
        self.assertFalse(Violation.objects.exists())

    def test_a_negative_salary_is_refused_by_the_door(self):
        answer = self.post(self.accounting, SALARY_SAVE, {"values": {"amount": "-5000", "effective_from": self.today.isoformat()}}, [self.tr.pk])
        self.assertEqual((answer.status_code, _json(answer)["error"]), (400, "invalid"))


class StaleDraftTests(_Accounts):
    def test_a_draft_for_an_absence_that_was_corrected_is_not_left_to_be_approved(self):
        day = self.today.replace(day=1)
        row = WorkDay.objects.create(user=self.tr, date=day, status="unexcused", absence_reason="x")
        self.run_month()
        key = f"unexcused:{day:%Y-%m-%d}"
        self.assertTrue(Violation.objects.filter(user=self.tr, auto_key=key, status=ApprovalStatus.PENDING).exists())
        WorkDay.objects.filter(pk=row.pk).update(status="present")
        self.run_month()
        self.assertFalse(Violation.objects.filter(user=self.tr, auto_key=key).exists())

    def test_a_decided_deduction_and_one_a_person_proposed_are_never_touched(self):
        self.violation(reason="Proposed by a person")
        decided = self.violation(auto_key="unexcused:2020-01-01", status=ApprovalStatus.APPROVED, date=self.today)
        self.run_month()
        self.assertTrue(Violation.objects.filter(reason="Proposed by a person").exists())
        self.assertTrue(Violation.objects.filter(pk=decided.pk).exists())


class OvertimeClaimTests(_Accounts):
    def test_a_claim_waiting_for_a_day_that_was_corrected_is_dropped_and_a_decided_one_is_not(self):
        conf = PayrollSettings.load()
        conf.overtime_enabled = True
        conf.overtime_min_minutes = 15
        conf.save()
        first = self.today.replace(day=1)
        row = WorkDay.objects.create(user=self.tr, date=self.today, status="present", overtime_minutes=120, scheduled_minutes=480)
        attendance.raise_overtime(self.tr, first, self.today, conf=conf)
        self.assertEqual(OvertimeClaim.objects.filter(user=self.tr, date=self.today).count(), 1)
        WorkDay.objects.filter(pk=row.pk).update(overtime_minutes=0)
        attendance.raise_overtime(self.tr, first, self.today, conf=conf)
        self.assertFalse(OvertimeClaim.objects.filter(user=self.tr, date=self.today).exists())


class DoorBoundsTests(_Accounts):
    def test_a_month_that_has_not_begun_is_not_run(self):
        answer = self.post(self.accounting, "dashboard:v1_accounts_recalculate", {"period": "2099-12"})
        self.assertEqual((answer.status_code, _json(answer)["error"]), (400, "bad_period"))
        self.assertFalse(PayrollPeriod.objects.filter(year=2099).exists())
        self.assertEqual(self.post(self.accounting, "dashboard:v1_accounts_recalculate", {"period": self.period_text}).status_code, 200)

    def test_the_list_of_what_waits_is_capped(self):
        for number in range(3):
            self.violation(reason=f"Row {number}")
        with mock.patch("dashboard.api_accounts.MAX_PENDING", 2):
            body = _json(self.get(self.accounting, VIOLATIONS))
        self.assertEqual(len(body["pending"]), 2)


class HrBoundsTests(_People):
    def test_the_board_takes_a_date_the_calendar_can_hold_or_falls_back_to_today(self):
        for date_text in ("0001-01-01", "9999-12-31"):
            answer = self.read("dashboard:v1_hr_board", view="week", date=date_text)
            self.assertEqual(answer.status_code, 200, date_text)

    def test_a_leave_range_a_person_can_hold_in_their_head(self):
        today = self.today
        ok = LeaveRequestForm({"kind": "annual", "start_date": today.isoformat(), "end_date": (today + timedelta(days=3)).isoformat()})
        self.assertTrue(ok.is_valid(), ok.errors)
        for start, end, field in (
            ("2026-01-01", "9999-12-31", "end_date"),
            ((today + timedelta(days=500)).isoformat(), (today + timedelta(days=502)).isoformat(), "start_date"),
            ("2000-01-01", "2000-01-02", "start_date"),
            (today.isoformat(), (today + timedelta(days=200)).isoformat(), "end_date"),
        ):
            form = LeaveRequestForm({"kind": "annual", "start_date": start, "end_date": end})
            self.assertIn(field, form.errors, (start, end))

    def test_an_absurd_leave_request_is_refused_by_the_door_and_the_page_still_opens(self):
        answer = self.post(self.tr, "dashboard:v1_leave_request", {"values": {"kind": "annual", "start_date": "2026-01-01", "end_date": "9999-12-31"}})
        self.assertEqual((answer.status_code, _json(answer)["error"]), (400, "invalid"))
        self.assertEqual(self.read("dashboard:v1_leave", self.tr).status_code, 200)

    def test_an_office_is_a_place_on_the_earth_with_a_radius_that_measures_something(self):
        base = {"name": "HQ", "radius_meters": "100", "latitude": "30.04", "longitude": "31.23"}
        self.assertTrue(OfficeLocationForm(base).is_valid())
        for over, field in (({"latitude": "999.999999"}, "latitude"), ({"longitude": "-500"}, "longitude"), ({"radius_meters": "2000000000"}, "radius_meters")):
            self.assertIn(field, OfficeLocationForm({**base, **over}).errors, over)

    def test_a_job_title_and_a_username_have_the_limits_the_user_has_and_a_look_alike_name_is_taken(self):
        base = {"role": "translator", "joining_date": self.today.isoformat()}
        self.assertIn("job_title", HireForm({**base, "job_title": "x" * 121}, actor=self.hr).errors)
        self.assertIn("username", HireForm({**base, "username": "u" * 151}, actor=self.hr).errors)
        self.assertIn("username", HireForm({**base, "username": self.admin.username.upper()}, actor=self.hr).errors)
        self.assertIn("username", HireForm({**base, "username": "with space"}, actor=self.hr).errors)
        self.assertNotIn("username", HireForm({**base, "username": "a.fresh_name"}, actor=self.hr).errors)


class AdminPanelFixTests(_Admin):
    def post_json(self, name, body, args=None):
        browser = DjangoClient()
        browser.force_login(self.admin)
        return browser.post(reverse(name, args=args), json.dumps(body), content_type="application/json")

    def test_a_pilot_who_has_gone_does_not_stop_the_settings_from_being_saved(self):
        pilot = User.objects.create_user("pilot_translator", password="pw", role="translator")
        conf = AppSettings.load()
        conf.new_ui = {"translator_home": {"roles": [], "users": [pilot.pk]}}
        conf.save()
        User.objects.filter(pk=pilot.pk).update(is_active=False)
        answer = self.post_json("dashboard:v1_admin_settings_save", {"values": {"poll_ms": 5000}})
        self.assertEqual(answer.status_code, 200, answer.content)
        self.assertEqual(AppSettings.load().poll_ms, 5000)

    def test_the_last_owner_cannot_be_closed_or_demoted_and_one_of_two_can(self):
        for values in ({"is_active": False}, {"role": "translator"}):
            answer = self.post_json("dashboard:v1_admin_user_save", {"values": values}, [self.admin.pk])
            self.assertEqual((answer.status_code, _json(answer)["error"]), (400, "invalid"), values)
            self.assertIn("__all__", _json(answer)["errors"], values)
        self.admin.refresh_from_db()
        self.assertEqual((self.admin.role, self.admin.is_active), ("admin", True))
        second = User.objects.create_user("second_owner", password="pw", role="admin")
        again = self.post_json("dashboard:v1_admin_user_save", {"values": {"is_active": False}}, [second.pk])
        self.assertEqual(again.status_code, 200, again.content)

    def test_the_simulation_switch_is_read(self):
        conf = AppSettings.load()
        conf.simulation_enabled = False
        conf.save()
        browser = DjangoClient()
        browser.force_login(self.admin)
        body = {"channel": "whatsapp", "sender_identity": "201099900111", "body": "hello", "subject": ""}
        before = InboundMessage.objects.count()
        answer = browser.post(reverse("dashboard:v1_admin_simulate_send"), body)
        self.assertEqual((answer.status_code, _json(answer)["error"]), (409, "simulation_off"))
        self.assertEqual(InboundMessage.objects.count(), before)
        conf.simulation_enabled = True
        conf.save()
        sent = browser.post(reverse("dashboard:v1_admin_simulate_send"), body)
        self.assertEqual(sent.status_code, 200, sent.content)
        entry = AuditLog.objects.get(action="admin.simulate")
        self.assertNotIn("hello", entry.detail + entry.target)

    def test_a_save_of_a_persons_file_says_which_boxes_changed(self):
        answer = self.post_json("dashboard:v1_admin_user_save", {"values": {"attendance_manager": True}}, [self.ops.pk])
        self.assertEqual(answer.status_code, 200, answer.content)
        self.assertIn("attendance_manager", AuditLog.objects.filter(action="user.update").latest("pk").detail)

    def test_a_test_send_is_written_down_without_the_number(self):
        with mock.patch.object(whatsapp, "check_connection", return_value={"ok": True}):
            self.post_json("dashboard:v1_admin_test_whatsapp", {"to": "201011122233"})
        entry = AuditLog.objects.get(action="settings.test_send")
        self.assertNotIn("201011122233", entry.detail + entry.target)


class StrangerFileNameTests(_Cand):
    def test_what_a_sender_calls_a_file_never_leaves_its_folder(self):
        for given, wanted in (("../x.pdf", "x.pdf"), ("a/../../y.pdf", "y.pdf"), ("C:\\evil\\z.pdf", "z.pdf"), ("..", "file"), ("", "file"), (None, "file")):
            self.assertEqual(webhooks.clean_filename(given), wanted, given)
        self.assertEqual(webhooks.clean_filename("../", "fallback.bin"), "fallback.bin")

    def test_a_cv_and_a_test_file_are_stored_under_names_that_say_nothing_whatever_they_were_called(self):
        from .models import upload_cv, upload_test

        for make in (upload_cv, upload_test):
            stored = make(None, "../Mona Candidate CV.pdf")
            self.assertNotIn("..", stored)
            self.assertNotIn("Mona", stored)
            self.assertTrue(stored.endswith(".pdf"), stored)

    def test_hr_downloads_a_cv_under_the_name_it_came_with(self):
        from .models import Candidate

        self.person.cv = SimpleUploadedFile("Mona Candidate CV.pdf", b"%PDF")
        self.person.cv_name = "Mona Candidate CV.pdf"
        self.person.save()
        self.person.refresh_from_db()
        self.assertNotIn("Mona", self.person.cv.name)
        browser = DjangoClient()
        browser.force_login(self.hr)
        self.assertIn("Mona", browser.get(self.person.cv.url)["Content-Disposition"])
