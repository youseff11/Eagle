"""Recruitment in the new app, the candidates' side: the list, a candidate's file and what HR does to one, the owner's approvals,
hiring, and the reviewer's blind queue of tests.

What these tests hold:

* HR and the owner open the candidates; the owner alone decides a hire; the reviewer, a team leader and the owner open the tests
  - nobody else, not even the attendance flag, and a refusal is written down.
* A message to a candidate goes through the identity filter and nothing else; revealing the company is logged and stays revealed.
* A move is the pipeline's own: it cannot skip a step, "hired" is not a move, and the owner's queue is entered by being sent there.
* HR hires into the roles it may hand out (not the owner's, not Sales, not the money role), with a password the settings accept,
  once; and a password is never in an answer.
* A reviewer reads a code and the work: no name, phone, e-mail, salary or vacancy, not even in the name of the candidate's file;
  and a test that is another reviewer's is not there.
* A file is stored under a name that says nothing; the name it came with is kept beside it.
"""

import json
import tempfile
from datetime import timedelta
from unittest import mock

from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import Client as DjangoClient
from django.test import override_settings
from django.urls import reverse
from django.utils import timezone

from . import identity, recruitment, whatsapp
from .forms import CandidateForm, HireForm
from .models import (
    AppSettings, AuditLog, Candidate, CandidateAnswer, CandidateTest, Department, Interview, Notification,
    RecruitmentQuestion, RecruitmentSettings, Role, SalaryRecord, User,
)
from .tests_api_v1 import _json
from .tests_hr_recruit import _Recruit

CANDIDATES = "dashboard:v1_hr_candidates"
CANDIDATE = "dashboard:v1_hr_candidate"
SAVE = "dashboard:v1_hr_candidate_save"
CV = "dashboard:v1_hr_candidate_cv"
STATUS = "dashboard:v1_hr_candidate_status"
REVEAL = "dashboard:v1_hr_candidate_reveal"
MESSAGE = "dashboard:v1_hr_candidate_message"
INTERVIEW_NEW = "dashboard:v1_hr_interview_create"
TEST_NEW = "dashboard:v1_hr_candidate_test_create"
HIRE_FORM = "dashboard:v1_hr_hire_form"
HIRE = "dashboard:v1_hr_hire"
INTERVIEW = "dashboard:v1_hr_interview"
INTERVIEW_SCORE = "dashboard:v1_hr_interview_score"
APPROVALS = "dashboard:v1_hr_approvals"
DECIDE = "dashboard:v1_hr_approval_decide"
QUEUE = "dashboard:v1_reviewer_tests"
TEST = "dashboard:v1_reviewer_test"
TEST_SCORE = "dashboard:v1_reviewer_test_score"

NAME = "Mona Candidate"
PHONE = "01011111111"
EMAIL = "mona.candidate@example.com"
SALARY = "7777 EGP"
STRONG = "A-long-pass-phrase-2026"

LOCAL = {"default": {"BACKEND": "dashboard.storages.ProtectedFileSystemStorage"}}


class _Cand(_Recruit):
    def setUp(self):
        super().setUp()
        self.department, _made = Department.objects.get_or_create(name="Translation", defaults={"name_ar": "الترجمة"})
        self.vac = self.vacancy(title="Arabic Translator", department=self.department)
        self.person = self.candidate()
        self.other_reviewer = User.objects.create_user("person_reviewer_two", password="pw", role=Role.REVIEWER)
        media = tempfile.TemporaryDirectory()
        self.addCleanup(media.cleanup)
        override = override_settings(MEDIA_ROOT=media.name, STORAGES={**self._storages(), **LOCAL})
        override.enable()
        self.addCleanup(override.disable)

    @staticmethod
    def _storages():
        from django.conf import settings

        return dict(settings.STORAGES)

    def candidate(self, **over):
        values = {
            "full_name": NAME, "phone": PHONE, "email": EMAIL, "vacancy": self.vac, "status": "screening",
            "expected_salary": SALARY, "source": "whatsapp", "languages": "AR, EN",
        }
        values.update(over)
        return Candidate.objects.create(**values)

    def multipart(self, who, name, args, fields, **files):
        browser = DjangoClient()
        browser.force_login(who)
        return browser.post(reverse(name, args=args), {**fields, **files})

    def exam_row(self, **over):
        values = {"candidate": self.person, "title": "Sample", "language_pair": "EN-AR", "word_count": 300}
        values.update(over)
        return CandidateTest.objects.create(**values)


# ---------------------------------------------------------------------------
# Who may open what
# ---------------------------------------------------------------------------

class DoorMatrixTests(_Cand):
    def setUp(self):
        super().setUp()
        self.interview = Interview.objects.create(candidate=self.person, scheduled_at=timezone.now())
        self.exam = self.exam_row()

    def hr_doors(self):
        code = [self.person.code]
        return [
            ("GET", CANDIDATES, None), ("GET", CANDIDATE, code), ("POST", SAVE, code), ("POST", CV, code), ("POST", STATUS, code),
            ("POST", REVEAL, code), ("POST", MESSAGE, code), ("POST", INTERVIEW_NEW, code), ("POST", TEST_NEW, code),
            ("GET", HIRE_FORM, code), ("POST", HIRE, code), ("GET", INTERVIEW, [self.interview.pk]),
            ("POST", INTERVIEW_SCORE, [self.interview.pk]),
        ]

    def owner_doors(self):
        return [("GET", APPROVALS, None), ("POST", DECIDE, [self.person.code, "approve"])]

    def marker_doors(self):
        return [("GET", QUEUE, None), ("GET", TEST, [self.exam.pk]), ("POST", TEST_SCORE, [self.exam.pk])]

    def call(self, who, method, name, args):
        browser = DjangoClient()
        if who is not None:
            browser.force_login(who)
        url = reverse(name, args=args)
        return browser.get(url) if method == "GET" else browser.post(url, "{}", content_type="application/json")

    def assert_doors(self, doors, allowed, refused):
        for method, name, args in doors:
            for who in allowed:
                self.assertNotIn(self.call(who, method, name, args).status_code, (401, 403), f"{name} {who.username}")
            for who in refused:
                self.assertEqual(self.call(who, method, name, args).status_code, 403, f"{name} {who.username}")
            self.assertEqual(self.call(None, method, name, args).status_code, 401, name)

    def test_the_candidates_are_hrs_and_the_owners_not_even_the_attendance_flags(self):
        self.assert_doors(self.hr_doors(), (self.hr, self.admin), (self.ops, self.lead, self.tr, self.reviewer, self.accounting, self.sales, self.flagged))

    def test_the_approvals_are_the_owners_alone_not_hrs(self):
        self.assert_doors(self.owner_doors(), (self.admin,), (self.hr, self.ops, self.lead, self.tr, self.reviewer, self.accounting, self.sales, self.flagged))

    def test_the_tests_are_the_reviewers_a_team_leaders_and_the_owners(self):
        self.assert_doors(self.marker_doors(), (self.reviewer, self.lead, self.admin), (self.hr, self.ops, self.tr, self.accounting, self.sales, self.flagged))

    def test_a_refusal_is_written_down_and_changes_nothing(self):
        before = AuditLog.objects.filter(action=identity.ACCESS_DENIED).count()
        answer = self.call(self.hr, "POST", DECIDE, [self.person.code, "approve"])
        self.assertEqual((answer.status_code, _json(answer)["error"]), (403, "forbidden"))
        self.assertEqual(AuditLog.objects.filter(action=identity.ACCESS_DENIED).count(), before + 1)
        self.person.refresh_from_db()
        self.assertEqual(self.person.status, "screening")

    def test_the_wrong_method_is_refused(self):
        code = [self.person.code]
        for name, args, wrong in (
            (CANDIDATES, None, "post"), (CANDIDATE, code, "post"), (INTERVIEW, [self.interview.pk], "post"), (HIRE_FORM, code, "post"),
            (APPROVALS, None, "post"), (QUEUE, None, "post"), (TEST, [self.exam.pk], "post"),
            (SAVE, code, "get"), (CV, code, "get"), (STATUS, code, "get"), (REVEAL, code, "get"), (MESSAGE, code, "get"),
            (INTERVIEW_NEW, code, "get"), (TEST_NEW, code, "get"), (HIRE, code, "get"), (INTERVIEW_SCORE, [self.interview.pk], "get"),
            (TEST_SCORE, [self.exam.pk], "get"),
        ):
            browser = DjangoClient()
            browser.force_login(self.admin)
            self.assertEqual(getattr(browser, wrong)(reverse(name, args=args)).status_code, 405, name)

    def test_every_answer_is_private(self):
        browser = DjangoClient()
        browser.force_login(self.admin)
        for name, args in ((CANDIDATES, None), (CANDIDATE, [self.person.code]), (APPROVALS, None), (QUEUE, None), (TEST, [self.exam.pk])):
            self.assertIn("no-store", browser.get(reverse(name, args=args))["Cache-Control"], name)


# ---------------------------------------------------------------------------
# The list and the file
# ---------------------------------------------------------------------------

class ListTests(_Cand):
    def test_everyone_with_the_status_the_source_and_the_vacancy_and_a_search(self):
        other_vac = self.vacancy(title="Editor")
        second = self.candidate(full_name="Omar Applicant", phone="01099999999", email="omar@else.org", vacancy=other_vac, status="new", source="referral")
        names = lambda **query: sorted(one["name"] for one in _json(self.read(CANDIDATES, **query))["rows"])
        self.assertEqual(names(), sorted([NAME, "Omar Applicant"]))
        self.assertEqual(names(status="new"), ["Omar Applicant"])
        self.assertEqual(names(source="whatsapp"), [NAME])
        self.assertEqual(names(vacancy=other_vac.code), ["Omar Applicant"])
        self.assertEqual(names(q="omar"), ["Omar Applicant"])
        self.assertEqual(names(q="01011"), [NAME])
        self.assertEqual(names(q=second.code), ["Omar Applicant"])
        self.assertEqual(names(q="example.com"), [NAME])
        self.assertEqual(names(q="nobody-called-this"), [])

    def test_it_says_how_many_there_are_when_it_shows_fewer(self):
        for number in range(3):
            self.candidate(full_name=f"Extra {number}", phone=f"0100000000{number}")
        with mock.patch("dashboard.api_candidates.MAX_CANDIDATES", 2):
            body = _json(self.read(CANDIDATES))
        self.assertEqual((len(body["rows"]), body["total"], body["limit"]), (2, 4, 2))

    def test_it_offers_the_filters_it_understands(self):
        body = _json(self.read(CANDIDATES))
        self.assertIn("owner_approval", [one["value"] for one in body["statuses"]])
        self.assertIn("referral", [one["value"] for one in body["sources"]])
        self.assertIn(self.vac.code, [one["code"] for one in body["vacancies"]])
        self.assertIn("total_applicants", body["counts"])

    def test_a_search_is_cut_to_a_sensible_length_and_a_junk_filter_finds_nothing(self):
        self.assertEqual(_json(self.read(CANDIDATES, q="x" * 5000))["rows"], [])
        self.assertEqual(_json(self.read(CANDIDATES, status="not-a-status"))["rows"], [])

    def test_a_get_changes_nothing(self):
        before = (AuditLog.objects.count(), Candidate.objects.count())
        self.read(CANDIDATES)
        self.read(CANDIDATE, args=[self.person.code])
        self.assertEqual((AuditLog.objects.count(), Candidate.objects.count()), before)


class FileTests(_Cand):
    def test_the_whole_application_on_one_answer(self):
        question = RecruitmentQuestion.objects.create(text="Why us?")
        CandidateAnswer.objects.create(candidate=self.person, question=question, order=1, value="Because", file_name="")
        Interview.objects.create(candidate=self.person, scheduled_at=timezone.now(), kind="online", communication=8, experience=7)
        self.exam_row(title="Sample test")
        body = _json(self.read(CANDIDATE, args=[self.person.code]))
        who = body["candidate"]
        self.assertEqual((who["name"], who["phone"], who["email"], who["code"]), (NAME, PHONE, EMAIL, self.person.code))
        self.assertEqual((who["vacancy"], who["expected_salary"], who["anonymous"], who["identity"]["revealed"]), ("Arabic Translator", SALARY, True, False))
        self.assertEqual([(one["question"], one["value"]) for one in body["answers"]], [("Why us?", "Because")])
        self.assertEqual((body["interviews"][0]["total"], body["interviews"][0]["max"], body["interviews"][0]["evaluated"]), (15, 50, True))
        self.assertEqual(body["tests"][0]["title"], "Sample test")
        self.assertEqual(body["privacy_armed"], bool(RecruitmentSettings.load().term_list))

    def test_the_form_has_no_cv_box_and_a_cv_cannot_be_sent_as_a_value(self):
        body = _json(self.read(CANDIDATE, args=[self.person.code]))
        self.assertNotIn("cv", [one["name"] for one in body["form"]])
        self.assertNotIn("cv", [one["name"] for one in body["test_form"]])
        self.assertNotIn("assignment", [one["name"] for one in body["test_form"]])
        answer = self.post(self.hr, SAVE, {"values": {"cv": "x.pdf"}}, [self.person.code])
        self.assertEqual((answer.status_code, _json(answer)["error"]), (400, "bad_body"))

    def test_the_moves_offered_are_the_pipelines_own_and_never_hired(self):
        offered = lambda status: [one["value"] for one in _json(self.read(CANDIDATE, args=[self.candidate(status=status).code]))["next_statuses"]]
        self.assertEqual(offered("screening"), ["interview", "test", "rejected"])
        self.assertEqual(offered("owner_approval"), [])
        self.assertEqual(offered("approved"), ["rejected"])
        self.assertEqual(offered("hired"), [])

    def test_a_file_is_linked_by_the_protected_address_never_by_the_host_behind_it(self):
        CandidateAnswer.objects.create(
            candidate=self.person, question=RecruitmentQuestion.objects.create(text="CV?"), value="",
            file=SimpleUploadedFile("answer.pdf", b"PDF"), file_name="answer.pdf",
        )
        body = _json(self.read(CANDIDATE, args=[self.person.code]))
        self.assertTrue(body["answers"][0]["file"]["url"].startswith("/files/"))

    def test_a_candidate_that_is_not_there_is_not_there(self):
        self.assertEqual(self.read(CANDIDATE, args=["CAN-9999"]).status_code, 404)


class SaveTests(_Cand):
    def test_only_the_boxes_that_changed_are_written(self):
        answer = self.post(self.hr, SAVE, {"values": {"hr_notes": "Strong on terminology", "hr_recommendation": "Interview"}}, [self.person.code])
        self.assertEqual(answer.status_code, 200)
        self.person.refresh_from_db()
        self.assertEqual((self.person.hr_notes, self.person.hr_recommendation), ("Strong on terminology", "Interview"))
        self.assertEqual((self.person.full_name, self.person.phone, self.person.vacancy_id, self.person.source), (NAME, PHONE, self.vac.pk, "whatsapp"))
        self.assertTrue(AuditLog.objects.filter(action="recruitment.candidate.update", target=self.person.code).exists())

    def test_a_candidate_on_a_vacancy_that_has_closed_can_still_be_saved(self):
        self.vac.status = "closed"
        self.vac.save()
        answer = self.post(self.hr, SAVE, {"values": {"hr_notes": "Still here"}}, [self.person.code])
        self.assertEqual(answer.status_code, 200, answer.content)
        self.person.refresh_from_db()
        self.assertEqual((self.person.hr_notes, self.person.vacancy_id), ("Still here", self.vac.pk))

    def test_nobody_can_be_moved_onto_a_closed_vacancy(self):
        closed = self.vacancy(title="Old job", status="closed")
        answer = self.post(self.hr, SAVE, {"values": {"vacancy": str(closed.pk)}}, [self.person.code])
        self.assertEqual((answer.status_code, _json(answer)["error"]), (400, "invalid"))
        self.assertIn("vacancy", _json(answer)["errors"])

    def test_the_forms_own_rules_apply(self):
        answer = self.post(self.hr, SAVE, {"values": {"email": "not-an-address"}}, [self.person.code])
        self.assertEqual((answer.status_code, _json(answer)["error"]), (400, "invalid"))
        self.assertIn("email", _json(answer)["errors"])
        self.person.refresh_from_db()
        self.assertEqual(self.person.email, EMAIL)

    def test_a_box_the_form_does_not_have_is_refused_not_ignored(self):
        for values in ({"status": "hired"}, {"identity_revealed": True}, {"hired_user": 1}):
            answer = self.post(self.hr, SAVE, {"values": values}, [self.person.code])
            self.assertEqual((answer.status_code, _json(answer)["error"]), (400, "bad_body"), values)
        self.person.refresh_from_db()
        self.assertEqual((self.person.status, self.person.identity_revealed), ("screening", False))

    def test_the_classic_form_keeps_a_closed_vacancy_too(self):
        self.vac.status = "closed"
        self.vac.save()
        form = CandidateForm({"full_name": NAME, "phone": PHONE, "email": EMAIL, "vacancy": self.vac.pk, "source": "whatsapp"}, instance=self.person)
        self.assertTrue(form.is_valid(), form.errors)


class CvTests(_Cand):
    def upload(self, name="Mona Candidate CV.pdf", data=b"%PDF-1.4 cv", **over):
        return self.multipart(over.get("who", self.hr), CV, [self.person.code], {}, file=SimpleUploadedFile(name, data))

    def test_it_is_stored_under_a_name_that_says_nothing_and_keeps_the_name_it_came_with(self):
        self.assertEqual(self.upload().status_code, 200)
        self.person.refresh_from_db()
        self.assertEqual(self.person.cv_name, "Mona Candidate CV.pdf")
        self.assertNotIn("Mona", self.person.cv.name)
        self.assertNotIn("Candidate", self.person.cv.name)
        self.assertTrue(self.person.cv.name.endswith(".pdf"))
        self.assertTrue(AuditLog.objects.filter(action="recruitment.candidate.cv", target=self.person.code).exists())
        body = _json(self.read(CANDIDATE, args=[self.person.code]))
        self.assertEqual(body["candidate"]["cv"]["name"], "Mona Candidate CV.pdf")
        self.assertTrue(body["candidate"]["cv"]["url"].startswith("/files/"))

    def test_hr_opens_it_through_the_protected_address_and_a_stranger_does_not(self):
        self.upload()
        self.person.refresh_from_db()
        url = _json(self.read(CANDIDATE, args=[self.person.code]))["candidate"]["cv"]["url"]
        opened = DjangoClient()
        opened.force_login(self.hr)
        self.assertEqual(opened.get(url).status_code, 200)
        stranger = DjangoClient()
        stranger.force_login(self.tr)
        self.assertEqual(stranger.get(url).status_code, 404)

    def test_a_new_cv_replaces_the_old_one(self):
        self.upload("first.pdf")
        self.upload("second.docx")
        self.person.refresh_from_db()
        self.assertEqual((self.person.cv_name, self.person.cv.name.endswith(".docx")), ("second.docx", True))

    def test_an_empty_file_a_missing_file_and_a_huge_one_are_refused(self):
        self.assertEqual(_json(self.upload(data=b""))["error"], "bad_file")
        browser = DjangoClient()
        browser.force_login(self.hr)
        self.assertEqual(_json(browser.post(reverse(CV, args=[self.person.code]), {}))["error"], "bad_file")
        with mock.patch("dashboard.api_candidates.MAX_DOC_BYTES", 5):
            self.assertEqual(_json(self.upload(data=b"123456"))["error"], "bad_file")
        self.person.refresh_from_db()
        self.assertFalse(self.person.cv)

    def test_a_strange_extension_is_not_kept(self):
        self.upload("cv.p!f")
        self.person.refresh_from_db()
        self.assertNotIn("!", self.person.cv.name)


# ---------------------------------------------------------------------------
# The pipeline
# ---------------------------------------------------------------------------

class StatusTests(_Cand):
    def move(self, target, reason="", code=None, who=None):
        return self.post(who or self.hr, STATUS, {"status": target, "reason": reason}, [code or self.person.code])

    def test_a_legal_move_is_made_and_written_down(self):
        self.assertEqual(self.move("interview").status_code, 200)
        self.person.refresh_from_db()
        self.assertEqual(self.person.status, "interview")
        self.assertTrue(AuditLog.objects.filter(action="recruitment.status", target=self.person.code).exists())

    def test_a_step_cannot_be_skipped_and_the_refusal_is_in_words(self):
        answer = self.move("owner_approval")
        self.assertEqual((answer.status_code, _json(answer)["error"]), (409, "refused"))
        self.assertTrue(_json(answer)["message"])
        self.assertTrue(_json(answer)["message_en"])
        self.person.refresh_from_db()
        self.assertEqual(self.person.status, "screening")

    def test_hired_is_not_a_move_it_is_the_hire(self):
        self.person.status = "approved"
        self.person.save()
        answer = self.move("hired")
        self.assertEqual((answer.status_code, _json(answer)["error"]), (409, "refused"))
        self.person.refresh_from_db()
        self.assertEqual((self.person.status, self.person.hired_user_id), ("approved", None))

    def test_the_owners_queue_is_entered_by_being_sent_there_and_hr_cannot_leave_it(self):
        self.person.status = "final_review"
        self.person.save()
        self.assertEqual(self.move("owner_approval").status_code, 200)
        self.assertTrue(Notification.objects.filter(user=self.admin, title_en="Candidate approval required").exists())
        for target in ("approved", "rejected", "final_review"):
            answer = self.move(target)
            self.assertEqual(answer.status_code, 409, target)
        self.person.refresh_from_db()
        self.assertEqual(self.person.status, "owner_approval")

    def test_a_rejection_keeps_its_reason(self):
        self.move("rejected", "Not a fit for the shift")
        self.person.refresh_from_db()
        self.assertEqual((self.person.status, self.person.rejection_reason), ("rejected", "Not a fit for the shift"))

    def test_a_status_that_is_not_one_and_a_wrong_shape_are_refused(self):
        self.assertEqual(_json(self.move("flying"))["error"], "bad_status")
        for body in ({"status": 5}, {"status": "interview", "reason": "x" * 300}, {}):
            answer = self.post(self.hr, STATUS, body, [self.person.code])
            self.assertEqual(answer.status_code, 400, body)
        self.person.refresh_from_db()
        self.assertEqual(self.person.status, "screening")


class RevealTests(_Cand):
    def test_it_is_logged_with_who_and_why_and_cannot_be_undone(self):
        self.assertEqual(self.post(self.hr, REVEAL, {"reason": "Offer stage"}, [self.person.code]).status_code, 200)
        self.person.refresh_from_db()
        self.assertTrue(self.person.identity_revealed)
        self.assertEqual(self.person.identity_revealed_by, self.hr)
        entry = AuditLog.objects.get(action="recruitment.identity.reveal", target=self.person.code)
        self.assertIn("Offer stage", entry.detail)
        body = _json(self.read(CANDIDATE, args=[self.person.code]))["candidate"]["identity"]
        self.assertEqual((body["revealed"], body["by"]), (True, self.hr.short_name))

    def test_asking_twice_writes_one_line(self):
        self.post(self.hr, REVEAL, {}, [self.person.code])
        self.post(self.hr, REVEAL, {}, [self.person.code])
        self.assertEqual(AuditLog.objects.filter(action="recruitment.identity.reveal", target=self.person.code).count(), 1)


class MessageTests(_Cand):
    def setUp(self):
        super().setUp()
        conf = RecruitmentSettings.load()
        conf.redact_terms = "Acme Translation\nacme.example"
        conf.save()
        app = AppSettings.load()
        app.recruit_phone_number_id = "RECRUIT-LINE-1"
        app.save()

    def send(self, text, code=None):
        with mock.patch.object(whatsapp, "send_text", return_value={}) as sent:
            answer = self.post(self.hr, MESSAGE, {"body": text}, [code or self.person.code])
        return answer, sent

    def test_the_company_is_scrubbed_out_while_the_candidate_is_anonymous_and_it_goes_from_the_recruitment_line(self):
        answer, sent = self.send("Welcome to Acme Translation, see acme.example")
        self.assertEqual(answer.status_code, 200)
        [(number, body), kwargs] = [sent.call_args.args, sent.call_args.kwargs]
        self.assertEqual(number, PHONE)
        self.assertNotIn("Acme", body)
        self.assertNotIn("acme.example", body)
        self.assertEqual(kwargs["from_id"], "RECRUIT-LINE-1")

    def test_after_the_reveal_it_goes_as_written(self):
        recruitment.reveal_identity(self.person, self.hr, "ok")
        answer, sent = self.send("Welcome to Acme Translation")
        self.assertEqual(answer.status_code, 200)
        self.assertIn("Acme Translation", sent.call_args.args[1])

    def test_the_words_are_never_kept_in_the_log(self):
        self.send("A private offer of 12345 pounds")
        entry = AuditLog.objects.get(action="recruitment.message", target=self.person.code)
        self.assertNotIn("12345", entry.detail)

    def test_a_failed_send_says_so_and_a_missing_phone_is_its_own_refusal(self):
        with mock.patch.object(whatsapp, "send_text", side_effect=whatsapp.WhatsAppError("الرقم مش مسجل على واتساب.", "x")):
            answer = self.post(self.hr, MESSAGE, {"body": "Hello"}, [self.person.code])
        self.assertEqual((answer.status_code, _json(answer)["error"]), (502, "send_failed"))
        self.assertIn("واتساب", _json(answer)["message"])
        self.assertFalse(AuditLog.objects.filter(action="recruitment.message").exists())
        nobody = self.candidate(full_name="No Phone", phone="")
        answer, sent = self.send("Hello", nobody.code)
        self.assertEqual((answer.status_code, _json(answer)["error"]), (409, "no_phone"))
        sent.assert_not_called()

    def test_an_empty_or_huge_message_is_refused_before_anything_is_sent(self):
        for text in ("   ", "x" * 5000):
            answer, sent = self.send(text)
            self.assertEqual(answer.status_code, 400, len(text))
            sent.assert_not_called()


# ---------------------------------------------------------------------------
# Interviews and tests
# ---------------------------------------------------------------------------

class InterviewTests(_Cand):
    def book(self, **values):
        body = {"scheduled_at": "2026-10-20T15:30", "kind": "online"}
        body.update(values)
        return self.post(self.hr, INTERVIEW_NEW, {"values": body}, [self.person.code])

    def test_it_is_booked_for_the_candidate_by_the_person_who_booked_it(self):
        answer = self.book(interviewer=str(self.lead.pk), meeting_link="https://meet.example/abc")
        self.assertEqual(answer.status_code, 200)
        row = Interview.objects.get(pk=_json(answer)["id"])
        self.assertEqual((row.candidate, row.created_by, row.interviewer, row.kind), (self.person, self.hr, self.lead, "online"))
        self.assertEqual((timezone.localtime(row.scheduled_at).strftime("%Y-%m-%d %H:%M"), row.meeting_link), ("2026-10-20 15:30", "https://meet.example/abc"))
        shown = _json(self.read(CANDIDATE, args=[self.person.code]))["interviews"][0]
        self.assertEqual((shown["evaluated"], shown["total"]), (False, 0))

    def test_a_time_is_needed_and_must_be_one(self):
        self.assertEqual(_json(self.book(scheduled_at=""))["error"], "invalid")
        self.assertIn("scheduled_at", _json(self.book(scheduled_at="tomorrow-ish"))["errors"])
        self.assertFalse(Interview.objects.exists())

    def test_it_is_marked_out_of_ten_five_times_and_the_system_adds_it_up(self):
        row = Interview.objects.create(candidate=self.person, scheduled_at=timezone.now())
        answer = self.post(self.hr, INTERVIEW_SCORE, {"values": {"communication": 8, "experience": 7, "technical": 9, "computer_skills": 6, "attitude": 10, "comments": "Good"}}, [row.pk])
        self.assertEqual((answer.status_code, _json(answer)["total"], _json(answer)["max"]), (200, 40, 50))
        row.refresh_from_db()
        self.assertEqual((row.evaluated_by, row.comments, row.is_evaluated), (self.hr, "Good", True))
        self.assertIsNotNone(row.evaluated_at)
        self.assertTrue(AuditLog.objects.filter(action="recruitment.interview.score", target=self.person.code, detail="40/50").exists())

    def test_no_typed_total_and_nothing_over_ten_and_an_empty_form_is_not_a_mark(self):
        row = Interview.objects.create(candidate=self.person, scheduled_at=timezone.now())
        for values, bad in (({"total_score": 50}, "bad_body"), ({"communication": 11}, "invalid"), ({"communication": -1}, "invalid"), ({}, "invalid")):
            answer = self.post(self.hr, INTERVIEW_SCORE, {"values": values}, [row.pk])
            self.assertEqual((answer.status_code, _json(answer)["error"]), (400, bad), values)
        row.refresh_from_db()
        self.assertFalse(row.is_evaluated)
        self.assertIsNone(row.evaluated_at)

    def test_the_marks_so_far_come_with_the_form(self):
        row = Interview.objects.create(candidate=self.person, scheduled_at=timezone.now(), communication=5)
        body = _json(self.read(INTERVIEW, args=[row.pk]))
        self.assertEqual((body["candidate"]["code"], body["candidate"]["name"]), (self.person.code, NAME))
        self.assertEqual({one["name"]: one["value"] for one in body["form"]}["communication"], 5)
        self.assertEqual(self.read(INTERVIEW, args=[99999]).status_code, 404)


class TestSettingTests(_Cand):
    def make(self, values=None, **files):
        return self.multipart(self.hr, TEST_NEW, [self.person.code], {"values": json.dumps(values or {"title": "Sample"})}, **files)

    def test_a_test_is_set_with_how_long_the_candidate_gets(self):
        answer = self.post(self.hr, TEST_NEW, {"values": {"title": "Sample", "language_pair": "EN-AR", "word_count": 400, "deadline_days": 1, "deadline_hours": "2"}}, [self.person.code])
        self.assertEqual(answer.status_code, 200, answer.content)
        row = CandidateTest.objects.get(pk=_json(answer)["id"])
        self.assertEqual((row.candidate, row.created_by, row.title, row.word_count), (self.person, self.hr, "Sample", 400))
        wait = row.deadline - timezone.now()
        self.assertTrue(timedelta(hours=25, minutes=58) < wait < timedelta(hours=26, minutes=2), wait)
        self.assertEqual(row.department, self.vac.department)

    def test_no_boxes_means_no_deadline(self):
        row = CandidateTest.objects.get(pk=_json(self.post(self.hr, TEST_NEW, {"values": {"title": "x"}}, [self.person.code]))["id"])
        self.assertIsNone(row.deadline)

    def test_the_file_is_stored_anonymously_and_keeps_its_name(self):
        answer = self.make(assignment=SimpleUploadedFile("Mona Candidate test.docx", b"DOCX"))
        self.assertEqual(answer.status_code, 200, answer.content)
        row = CandidateTest.objects.get(pk=_json(answer)["id"])
        self.assertEqual(row.assignment_name, "Mona Candidate test.docx")
        self.assertNotIn("Mona", row.assignment.name)
        self.assertTrue(row.assignment.name.endswith(".docx"))
        self.assertTrue(_json(self.read(CANDIDATE, args=[self.person.code]))["tests"][0]["assignment"]["url"].startswith("/files/"))

    def test_a_bad_deadline_a_bad_file_and_an_unknown_box_are_refused(self):
        for values in ({"deadline_days": "-1"}, {"deadline_days": "abc"}, {"deadline_hours": 99999}, {"deadline_days": True}):
            answer = self.post(self.hr, TEST_NEW, {"values": values}, [self.person.code])
            self.assertEqual((answer.status_code, _json(answer)["error"]), (400, "bad_body"), values)
        self.assertEqual(_json(self.post(self.hr, TEST_NEW, {"values": {"marked_at": "2026-01-01"}}, [self.person.code]))["error"], "bad_body")
        self.assertEqual(_json(self.make(assignment=SimpleUploadedFile("t.docx", b"")))["error"], "bad_file")
        self.assertEqual(_json(self.multipart(self.hr, TEST_NEW, [self.person.code], {"values": "not json"}))["error"], "bad_body")
        self.assertFalse(CandidateTest.objects.exists())

    def test_the_reviewer_may_be_a_reviewer_a_team_leader_or_the_owner_and_no_one_else(self):
        choices = {one["name"]: one for one in _json(self.read(CANDIDATE, args=[self.person.code]))["test_form"]}["reviewer"]["choices"]
        offered = {int(one["value"]) for one in choices if one["value"]}
        self.assertTrue({self.reviewer.pk, self.lead.pk, self.admin.pk} <= offered)
        self.assertFalse({self.hr.pk, self.tr.pk, self.sales.pk, self.accounting.pk} & offered)


# ---------------------------------------------------------------------------
# The owner's approvals
# ---------------------------------------------------------------------------

class ApprovalTests(_Cand):
    def setUp(self):
        super().setUp()
        self.person.status = "owner_approval"
        self.person.hr_recommendation = "Hire"
        self.person.save()

    def decide(self, action, reason="", who=None, code=None):
        return self.post(who or self.admin, DECIDE, {"reason": reason}, [code or self.person.code, action])

    def test_the_queue_carries_what_the_owner_decides_on(self):
        Interview.objects.create(candidate=self.person, scheduled_at=timezone.now(), communication=9, experience=8)
        self.exam_row(accuracy=7, grammar=8)
        row = _json(self.read(APPROVALS, who=self.admin))["waiting"][0]
        self.assertEqual((row["name"], row["expected_salary"], row["hr_recommendation"]), (NAME, SALARY, "Hire"))
        self.assertEqual((row["interview_score"], row["test_score"]), ({"total": 17, "max": 50}, {"total": 15, "max": 50}))

    def test_a_score_that_was_never_given_is_nothing_not_zero(self):
        row = _json(self.read(APPROVALS, who=self.admin))["waiting"][0]
        self.assertEqual((row["interview_score"], row["test_score"]), (None, None))

    def test_approving_is_recorded_with_who_and_when(self):
        self.assertEqual(self.decide("approve").status_code, 200)
        self.person.refresh_from_db()
        self.assertEqual((self.person.status, self.person.owner_decision_by), ("approved", self.admin))
        self.assertIsNotNone(self.person.owner_decision_at)
        decided = _json(self.read(APPROVALS, who=self.admin))["decided"][0]
        self.assertEqual((decided["code"], decided["can_hire"]), (self.person.code, True))

    def test_rejecting_keeps_the_reason(self):
        self.decide("reject", "Salary expectations")
        self.person.refresh_from_db()
        self.assertEqual((self.person.status, self.person.rejection_reason), ("rejected", "Salary expectations"))

    def test_a_candidate_that_is_not_waiting_is_a_refusal_in_words_and_changes_nothing(self):
        self.person.status = "screening"
        self.person.save()
        answer = self.decide("approve")
        self.assertEqual((answer.status_code, _json(answer)["error"]), (409, "refused"))
        self.person.refresh_from_db()
        self.assertEqual(self.person.status, "screening")

    def test_only_approve_and_reject_are_actions_and_hr_cannot_decide(self):
        self.assertEqual(self.decide("hire").status_code, 404)
        self.assertEqual(self.decide("approve", who=self.hr).status_code, 403)
        self.person.refresh_from_db()
        self.assertEqual(self.person.status, "owner_approval")

    def test_a_decision_that_is_not_text_is_refused(self):
        answer = self.post(self.admin, DECIDE, {"reason": ["a"]}, [self.person.code, "reject"])
        self.assertEqual(answer.status_code, 400)


# ---------------------------------------------------------------------------
# Hiring
# ---------------------------------------------------------------------------

class HireTests(_Cand):
    def setUp(self):
        super().setUp()
        self.person.status = "approved"
        self.person.department = self.vac.department
        self.person.save()

    def hire(self, values=None, who=None, code=None):
        return self.post(who or self.hr, HIRE, {"values": {"role": "translator", **(values or {})}}, [code or self.person.code])

    def fields(self, who=None, code=None):
        body = _json(self.read(HIRE_FORM, who=who, args=[code or self.person.code]))
        return body, {one["name"]: one for one in body["form"]}

    def test_the_form_starts_from_the_vacancy_and_today(self):
        body, fields = self.fields()
        self.assertTrue(body["hireable"])
        self.assertEqual((fields["job_title"]["value"], fields["joining_date"]["value"]), ("Arabic Translator", timezone.localdate().isoformat()))
        self.assertEqual(body["candidate"]["name"], NAME)

    def test_hr_is_offered_the_roles_it_may_hand_out_and_the_owner_all_of_them(self):
        _body, as_hr = self.fields()
        self.assertEqual({one["value"] for one in as_hr["role"]["choices"]}, {"translator", "reviewer", "operation", "team_lead"})
        _body, as_owner = self.fields(who=self.admin)
        self.assertEqual({one["value"] for one in as_owner["role"]["choices"]}, {value for value, _label in Role.choices})

    def test_the_roles_are_named_in_both_languages(self):
        _body, fields = self.fields()
        by_value = {one["value"]: one for one in fields["role"]["choices"]}
        self.assertEqual((by_value["translator"]["label_ar"], by_value["translator"]["label_en"]), ("مترجم", "Translator"))
        self.assertEqual(by_value["team_lead"]["label_ar"], "تيم ليدر")

    def test_a_password_is_never_in_an_answer(self):
        _body, fields = self.fields()
        self.assertEqual(fields["password"]["kind"], "password")
        self.assertNotIn("value", fields["password"])
        self.assertFalse(fields["password"]["saved"])
        answer = self.hire({"password": STRONG, "username": "mona.new"})
        self.assertNotIn(STRONG.encode(), answer.content)
        self.assertFalse(AuditLog.objects.filter(detail__contains=STRONG).exists())

    def test_a_starting_salary_is_the_owners_to_write_and_hr_is_not_offered_the_box(self):
        _body, as_hr = self.fields()
        self.assertNotIn("salary", as_hr)
        _body, as_owner = self.fields(who=self.admin)
        self.assertIn("salary", as_owner)
        refused = self.hire({"salary": "999999"})
        self.assertEqual((refused.status_code, _json(refused)["error"]), (400, "bad_body"))
        self.assertFalse(SalaryRecord.objects.exists())
        done = self.hire({"salary": "5500.00", "username": "mona.owner"}, who=self.admin)
        self.assertEqual(done.status_code, 200, done.content)
        self.assertEqual(SalaryRecord.objects.get().amount, 5500)

    def test_the_application_becomes_the_employee_once(self):
        answer = self.hire({"job_title": "Arabic Translator", "joining_date": "2026-10-11", "username": "mona.new", "password": STRONG})
        self.assertEqual(answer.status_code, 200, answer.content)
        person = User.objects.get(pk=_json(answer)["id"])
        self.assertEqual((person.username, person.role, person.email, person.phone, person.department), ("mona.new", "translator", EMAIL, PHONE, self.vac.department))
        self.assertEqual((person.employment_status, str(person.probation_start)), ("probation", "2026-10-11"))
        self.assertTrue(person.check_password(STRONG))
        self.assertFalse(SalaryRecord.objects.filter(user=person).exists())
        self.person.refresh_from_db()
        self.assertEqual((self.person.status, self.person.hired_user), ("hired", person))
        again = self.hire({"username": "mona.two"})
        self.assertEqual((again.status_code, _json(again)["error"]), (409, "refused"))
        self.assertEqual(User.objects.filter(username__startswith="mona").count(), 1)

    def test_a_box_left_alone_is_sent_as_the_page_drew_it(self):
        answer = self.hire({})
        self.assertEqual(answer.status_code, 200, answer.content)
        person = User.objects.get(pk=_json(answer)["id"])
        self.assertEqual((person.job_title, person.joining_date), ("Arabic Translator", timezone.localdate()))
        self.assertFalse(person.has_usable_password())

    def test_hr_cannot_make_an_owner_a_salesman_or_an_accountant(self):
        for role in ("admin", "sales", "accounting", "hr"):
            answer = self.hire({"role": role})
            self.assertEqual((answer.status_code, _json(answer)["error"]), (400, "invalid"), role)
            self.assertIn("role", _json(answer)["errors"], role)
        self.person.refresh_from_db()
        self.assertEqual((self.person.status, self.person.hired_user_id), ("approved", None))

    def test_the_owner_may_hire_into_any_role(self):
        answer = self.hire({"role": "sales"}, who=self.admin)
        self.assertEqual(answer.status_code, 200, answer.content)
        self.assertEqual(User.objects.get(pk=_json(answer)["id"]).role, "sales")

    def test_a_password_the_settings_refuse_is_refused_and_not_echoed(self):
        for weak in ("12345678", "password1", "short"):
            answer = self.hire({"password": weak})
            self.assertEqual((answer.status_code, _json(answer)["error"]), (400, "invalid"), weak)
            self.assertIn("password", _json(answer)["errors"], weak)
            self.assertNotIn(b'"' + weak.encode() + b'"', answer.content, weak)
        self.person.refresh_from_db()
        self.assertEqual(self.person.status, "approved")

    def test_a_username_that_is_taken_is_refused(self):
        answer = self.hire({"username": self.admin.username})
        self.assertEqual((answer.status_code, _json(answer)["error"]), (400, "invalid"))
        self.assertIn("username", _json(answer)["errors"])

    def test_nobody_is_hired_before_the_owner_approves(self):
        for index, status in enumerate(("screening", "owner_approval", "rejected", "hired")):
            other = self.candidate(status=status, phone=f"010000000{index}")
            body, _fields = self.fields(code=other.code)
            self.assertFalse(body["hireable"], status)
            self.assertEqual(body["form"], [], status)
            answer = self.hire(code=other.code)
            self.assertEqual((answer.status_code, _json(answer)["error"]), (409, "refused"), status)

    def test_a_manager_is_a_team_leader_and_nobody_else(self):
        answer = self.hire({"team_lead": str(self.tr.pk)})
        self.assertEqual((answer.status_code, _json(answer)["error"]), (400, "invalid"))
        ok = self.hire({"team_lead": str(self.lead.pk)})
        self.assertEqual(ok.status_code, 200, ok.content)

    def test_the_classic_form_is_the_narrow_one_too(self):
        classic = HireForm({"role": "admin", "joining_date": "2026-10-11"}, actor=self.hr)
        self.assertFalse(classic.is_valid())
        self.assertIn("role", classic.errors)
        self.assertFalse(HireForm({"role": "admin", "joining_date": "2026-10-11"}).is_valid())
        self.assertTrue(HireForm({"role": "admin", "joining_date": "2026-10-11"}, actor=self.admin).is_valid())


# ---------------------------------------------------------------------------
# The reviewer's blind queue
# ---------------------------------------------------------------------------

class ReviewerTests(_Cand):
    def setUp(self):
        super().setUp()
        self.mine = self.exam_row(title="Mine", reviewer=self.reviewer, brief="Translate the paragraph")
        self.nobodys = self.exam_row(title="Unassigned")
        self.theirs = self.exam_row(title="Theirs", reviewer=self.other_reviewer)

    def titles(self, body, key="pending"):
        return sorted(one["title"] for one in body[key])

    def test_a_reviewer_sees_their_own_and_the_ones_nobody_has_taken(self):
        body = _json(self.read(QUEUE, who=self.reviewer))
        self.assertEqual(self.titles(body), ["Mine", "Unassigned"])
        self.assertEqual(self.titles(_json(self.read(QUEUE, who=self.other_reviewer))), ["Theirs", "Unassigned"])

    def test_the_owner_sees_every_test(self):
        self.assertEqual(self.titles(_json(self.read(QUEUE, who=self.admin))), ["Mine", "Theirs", "Unassigned"])

    def test_marked_tests_move_to_the_done_list_with_their_total(self):
        self.mine.accuracy, self.mine.grammar, self.mine.marked_at = 8, 9, timezone.now()
        self.mine.save()
        body = _json(self.read(QUEUE, who=self.reviewer))
        self.assertEqual((self.titles(body), self.titles(body, "done")), (["Unassigned"], ["Mine"]))
        self.assertEqual((body["done"][0]["total"], body["done"][0]["max"]), (17, 50))
        self.assertIsNone(body["pending"][0]["total"])

    def test_a_reviewer_reads_a_code_and_the_work_and_no_part_of_the_person(self):
        self.person.cv_name = "private-cv.pdf"
        self.person.save()
        led = self.exam_row(title="Led", reviewer=self.lead)
        for who, exam in ((self.reviewer, self.mine), (self.lead, led)):
            for text in (self.read(QUEUE, who=who).content.decode(), self.read(TEST, who=who, args=[exam.pk]).content.decode()):
                for secret in (NAME, "Mona", PHONE, EMAIL, SALARY, "Arabic Translator", "private-cv"):
                    self.assertNotIn(secret, text, f"{who.username}: {secret}")
                self.assertIn(self.person.code, text)

    def test_the_owner_reads_who_it_is(self):
        body = _json(self.read(TEST, who=self.admin, args=[self.mine.pk]))
        self.assertEqual((body["blind"], body["candidate"]["name"]), (False, NAME))
        blind = _json(self.read(TEST, who=self.reviewer, args=[self.mine.pk]))
        self.assertEqual((blind["blind"], blind["candidate"]), (True, {"code": self.person.code}))

    def test_the_name_the_candidate_gave_their_file_is_not_the_reviewers_to_read(self):
        self.mine.submission = SimpleUploadedFile("Mona Candidate answer.docx", b"DOCX")
        self.mine.submission_name = "Mona Candidate answer.docx"
        self.mine.save()
        blind = _json(self.read(TEST, who=self.reviewer, args=[self.mine.pk]))["test"]["submission"]
        self.assertEqual(blind["name"], "submission.docx")
        self.assertNotIn("Mona", blind["name"])
        owner = _json(self.read(TEST, who=self.admin, args=[self.mine.pk]))["test"]["submission"]
        self.assertEqual(owner["name"], "Mona Candidate answer.docx")

    def test_another_reviewers_test_is_not_there_and_the_attempt_is_written_down(self):
        before = AuditLog.objects.filter(action=identity.ACCESS_DENIED).count()
        self.assertEqual(self.read(TEST, who=self.reviewer, args=[self.theirs.pk]).status_code, 404)
        answer = self.post(self.reviewer, TEST_SCORE, {"values": {"accuracy": 9}}, [self.theirs.pk])
        self.assertEqual(answer.status_code, 404)
        self.assertEqual(AuditLog.objects.filter(action=identity.ACCESS_DENIED).count(), before + 2)
        self.theirs.refresh_from_db()
        self.assertFalse(self.theirs.is_marked)

    def test_an_unassigned_test_is_taken_by_whoever_marks_it(self):
        answer = self.post(self.reviewer, TEST_SCORE, {"values": {"accuracy": 9, "grammar": 8, "terminology": 7, "formatting": 6, "instructions": 10, "comments": "Fine"}}, [self.nobodys.pk])
        self.assertEqual((answer.status_code, _json(answer)["total"], _json(answer)["max"]), (200, 40, 50))
        self.nobodys.refresh_from_db()
        self.assertEqual((self.nobodys.reviewer, self.nobodys.comments), (self.reviewer, "Fine"))
        self.assertIsNotNone(self.nobodys.marked_at)
        self.assertTrue(AuditLog.objects.filter(action="recruitment.test.score", target=self.person.code, detail="40/50").exists())

    def test_the_marks_are_out_of_ten_and_an_empty_form_is_not_a_mark(self):
        for values, bad in (({"accuracy": 11}, "invalid"), ({"grammar": -1}, "invalid"), ({}, "invalid"), ({"total_score": 5}, "bad_body"), ({"reviewer": 1}, "bad_body")):
            answer = self.post(self.reviewer, TEST_SCORE, {"values": values}, [self.mine.pk])
            self.assertEqual((answer.status_code, _json(answer)["error"]), (400, bad), values)
        self.mine.refresh_from_db()
        self.assertFalse(self.mine.is_marked)
        self.assertIsNone(self.mine.marked_at)

    def test_the_candidates_work_is_attached_anonymously(self):
        answer = self.multipart(self.reviewer, TEST_SCORE, [self.mine.pk], {"values": json.dumps({"accuracy": 8})}, submission=SimpleUploadedFile("Mona Candidate answer.docx", b"DOCX"))
        self.assertEqual(answer.status_code, 200, answer.content)
        self.mine.refresh_from_db()
        self.assertEqual(self.mine.submission_name, "Mona Candidate answer.docx")
        self.assertNotIn("Mona", self.mine.submission.name)
        self.assertIsNotNone(self.mine.submitted_at)
        shown = _json(self.read(TEST, who=self.reviewer, args=[self.mine.pk]))["test"]["submission"]
        self.assertEqual(shown["name"], "submission.docx")
        self.assertTrue(shown["url"].startswith("/files/"))
        self.assertNotIn("Mona", shown["url"])

    def test_a_reviewer_opens_the_work_and_hr_cannot_mark(self):
        self.mine.assignment = SimpleUploadedFile("brief.pdf", b"PDF")
        self.mine.assignment_name = "brief.pdf"
        self.mine.save()
        url = _json(self.read(TEST, who=self.reviewer, args=[self.mine.pk]))["test"]["assignment"]["url"]
        opened = DjangoClient()
        opened.force_login(self.reviewer)
        self.assertEqual(opened.get(url).status_code, 200)
        self.assertEqual(self.read(TEST, who=self.hr, args=[self.mine.pk]).status_code, 403)

    def test_a_test_that_is_not_there_is_not_there(self):
        self.assertEqual(self.read(TEST, who=self.reviewer, args=[99999]).status_code, 404)

    def test_a_get_changes_nothing(self):
        before = (AuditLog.objects.count(), CandidateTest.objects.filter(marked_at__isnull=False).count())
        self.read(QUEUE, who=self.reviewer)
        self.read(TEST, who=self.reviewer, args=[self.mine.pk])
        self.assertEqual((AuditLog.objects.count(), CandidateTest.objects.filter(marked_at__isnull=False).count()), before)


# ---------------------------------------------------------------------------
# The classic pages and the switches
# ---------------------------------------------------------------------------

class HandOnTests(_Cand):
    def setUp(self):
        super().setUp()
        self.switch(roles=["hr"])
        self.exam = self.exam_row(reviewer=self.reviewer)
        self.interview = Interview.objects.create(candidate=self.person, scheduled_at=timezone.now())

    def classic(self, name, args=None, who=None, **query):
        browser = DjangoClient()
        browser.force_login(who or self.hr)
        return browser.get(reverse(f"dashboard:{name}", args=args), query)

    def reviewer_switch(self, roles=(), users=()):
        conf = AppSettings.load()
        conf.save()

    def test_each_page_is_handed_on_with_what_it_carries(self):
        code = self.person.code
        for name, args, path, query, kept in (
            ("hr_candidates", None, "/app/hr/candidates", {"status": "new", "q": "mona"}, "q=mona"),
            ("hr_candidate", [code], f"/app/hr/candidates/{code}", {}, ""),
            ("hr_hire", [code], f"/app/hr/candidates/{code}/hire", {}, ""),
            ("hr_interview_score", [self.interview.pk], f"/app/hr/interviews/{self.interview.pk}", {}, ""),
        ):
            answer = self.classic(name, args, **query)
            self.assertEqual(answer.status_code, 302, name)
            self.assertTrue(answer["Location"].startswith(path), answer["Location"])
            self.assertIn(kept, answer["Location"])
        self.assertTrue(self.classic("hr_approvals", who=self.admin)["Location"].startswith("/app/hr/approvals"))

    def test_the_reviewers_pages_are_handed_on(self):
        answer = self.classic("reviewer_tests", who=self.reviewer)
        self.assertEqual((answer.status_code, answer["Location"]), (302, "/app/reviewer/tests"))
        answer = self.classic("hr_test_score", [self.exam.pk], who=self.reviewer)
        self.assertEqual((answer.status_code, answer["Location"]), (302, f"/app/reviewer/tests/{self.exam.pk}"))
        # The old way back to the classic page is not a thing any more.
        self.assertEqual(self.classic("reviewer_tests", who=self.reviewer, classic=1)["Location"], "/app/reviewer/tests")

    def test_a_team_leader_marking_is_handed_on_too(self):
        answer = self.classic("hr_test_score", [self.exam.pk], who=self.lead)
        self.assertEqual((answer.status_code, answer["Location"]), (302, f"/app/reviewer/tests/{self.exam.pk}"))

