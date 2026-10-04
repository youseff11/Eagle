"""Recruitment in the new app, the pipeline side: the board, vacancies and the questions the bot asks, the question bank, the rules.

HR and the admin open them (recruitment rights, not the attendance flag). What these tests hold: the identity rule is said to be
armed or not (silence would read as safety), the questions are HR's to choose and order per vacancy, a deadline box left alone
leaves the date alone, a department added from the small box is open (the classic box saved it shut), a GET changes nothing, and
the new pages are reached only by who the HR switch is on for.
"""

import json
from datetime import date, timedelta
from decimal import Decimal

from django.test import Client as DjangoClient
from django.urls import reverse
from django.utils import timezone

from . import identity
from .models import (
    AppSettings, AuditLog, Candidate, Department, Interview, RecruitmentQuestion, RecruitmentSettings, ShiftTemplate, Vacancy,
    VacancyQuestion,
)
from .tests_api_v1 import _json
from .tests_hr_attendance import _Hr

BOARD = "dashboard:v1_hr_recruitment"
SETTINGS = "dashboard:v1_hr_recruitment_settings"
SETTINGS_SAVE = "dashboard:v1_hr_recruitment_settings_save"
VACANCIES = "dashboard:v1_hr_vacancies"
VACANCY_NEW = "dashboard:v1_hr_vacancy_create"
VACANCY = "dashboard:v1_hr_vacancy"
VACANCY_SAVE = "dashboard:v1_hr_vacancy_save"
VQ_ADD = "dashboard:v1_hr_vacancy_question_add"
VQ_ORDER = "dashboard:v1_hr_vacancy_questions_order"
VQ_DELETE = "dashboard:v1_hr_vacancy_question_delete"
QUESTIONS = "dashboard:v1_hr_questions"
QUESTION_SAVE = "dashboard:v1_hr_question_save"
DEPARTMENT = "dashboard:v1_hr_department_add"


class _Recruit(_Hr):
    def read(self, name, who=None, args=None, **query):
        browser = DjangoClient()
        browser.force_login(who or self.hr)
        return browser.get(reverse(name, args=args), query)

    def vacancy(self, **over):
        values = {"title": "Translator", "status": "open"}
        values.update(over)
        return Vacancy.objects.create(**values)

    def question(self, text="Why us?", **over):
        return RecruitmentQuestion.objects.create(text=text, **over)


class DoorMatrixTests(_Recruit):
    def setUp(self):
        super().setUp()
        self.vac = self.vacancy()
        self.q = self.question()
        self.link = VacancyQuestion.objects.create(vacancy=self.vac, question=self.q, order=1)

    def doors(self):
        return [
            ("GET", BOARD, None), ("GET", SETTINGS, None), ("POST", SETTINGS_SAVE, None), ("GET", VACANCIES, None),
            ("POST", VACANCY_NEW, None), ("GET", VACANCY, [self.vac.code]), ("POST", VACANCY_SAVE, [self.vac.code]),
            ("POST", VQ_ADD, [self.vac.code]), ("POST", VQ_ORDER, [self.vac.code]), ("POST", VQ_DELETE, [self.link.pk]),
            ("GET", QUESTIONS, None), ("POST", QUESTION_SAVE, None), ("POST", DEPARTMENT, None),
        ]

    def call(self, who, method, name, args):
        browser = DjangoClient()
        if who is not None:
            browser.force_login(who)
        url = reverse(name, args=args)
        return browser.get(url) if method == "GET" else browser.post(url, "{}", content_type="application/json")

    def test_hr_and_the_admin_are_answered_and_nobody_else_not_even_the_attendance_flag(self):
        for method, name, args in self.doors():
            for who in (self.ops, self.lead, self.tr, self.reviewer, self.accounting, self.sales, self.flagged):
                self.assertEqual(self.call(who, method, name, args).status_code, 403, f"{name} {who.username}")
            self.assertEqual(self.call(None, method, name, args).status_code, 401, name)
        for method, name, args in self.doors():
            for who in (self.hr, self.admin):
                self.assertNotIn(self.call(who, method, name, args).status_code, (401, 403), f"{name} {who.username}")
                self.link = VacancyQuestion.objects.get_or_create(vacancy=self.vac, question=self.q, defaults={"order": 1})[0]

    def test_a_refusal_is_written_down_and_changes_nothing(self):
        before = AuditLog.objects.filter(action=identity.ACCESS_DENIED).count()
        answer = self.call(self.flagged, "POST", VQ_DELETE, [self.link.pk])
        self.assertEqual((answer.status_code, _json(answer)["error"]), (403, "forbidden"))
        self.assertEqual(AuditLog.objects.filter(action=identity.ACCESS_DENIED).count(), before + 1)
        self.assertTrue(VacancyQuestion.objects.filter(pk=self.link.pk).exists())

    def test_the_wrong_method_is_refused(self):
        for name, args, wrong in (
            (BOARD, None, "post"), (SETTINGS, None, "post"), (VACANCIES, None, "post"), (VACANCY, [self.vac.code], "post"),
            (QUESTIONS, None, "post"), (SETTINGS_SAVE, None, "get"), (VACANCY_NEW, None, "get"), (VACANCY_SAVE, [self.vac.code], "get"),
            (VQ_ADD, [self.vac.code], "get"), (VQ_ORDER, [self.vac.code], "get"), (VQ_DELETE, [1], "get"), (QUESTION_SAVE, None, "get"),
            (DEPARTMENT, None, "get"),
        ):
            browser = DjangoClient()
            browser.force_login(self.hr)
            self.assertEqual(getattr(browser, wrong)(reverse(name, args=args)).status_code, 405, name)


class BoardTests(_Recruit):
    def test_the_counts_the_latest_applicants_and_who_waits_for_the_owner(self):
        vac = self.vacancy()
        Candidate.objects.create(full_name="Mona Candidate", phone="01011111111", vacancy=vac, status="owner_approval", source="whatsapp")
        Candidate.objects.create(full_name="Omar Candidate", phone="01022222222", vacancy=vac, status="new", source="referral")
        body = _json(self.read(BOARD))
        self.assertEqual((body["counts"]["total_applicants"], body["counts"]["pending_owner"], body["counts"]["open_vacancies"]), (2, 1, 1))
        recent = {one["name"]: one for one in body["recent"]}
        self.assertEqual(recent["Mona Candidate"]["source"], {"value": "whatsapp", "ar": "واتساب", "en": "WhatsApp"})
        self.assertEqual((recent["Mona Candidate"]["status"]["value"], recent["Mona Candidate"]["vacancy"], recent["Mona Candidate"]["anonymous"]), ("owner_approval", "Translator", True))
        self.assertEqual([one["name"] for one in body["waiting_owner"]], ["Mona Candidate"])

    def test_todays_interviews_are_named_with_their_time(self):
        candidate = Candidate.objects.create(full_name="Mona Candidate")
        Interview.objects.create(candidate=candidate, scheduled_at=timezone.make_aware(timezone.datetime.combine(self.today, timezone.datetime.min.time().replace(hour=14))), kind="online")
        Interview.objects.create(candidate=candidate, scheduled_at=timezone.now() + timedelta(days=3), kind="office")
        today = _json(self.read(BOARD))["today_interviews"]
        self.assertEqual(len(today), 1)
        self.assertEqual((today[0]["candidate"]["name"], today[0]["kind"]["en"], today[0]["at"]["ar"]), ("Mona Candidate", "Online", "2:00 م"))

    def test_it_says_when_the_identity_rule_is_not_armed_and_when_it_is(self):
        conf = RecruitmentSettings.load()
        self.assertTrue(_json(self.read(BOARD))["privacy_armed"])
        conf.redact_terms = ""
        conf.save()
        self.assertFalse(_json(self.read(BOARD))["privacy_armed"])

    def test_it_says_whether_the_bot_is_on_and_which_number_it_listens_on(self):
        conf = RecruitmentSettings.load()
        conf.bot_enabled = False
        conf.save()
        body = _json(self.read(BOARD))
        self.assertFalse(body["bot_enabled"])
        self.assertEqual(body["recruit_number"], AppSettings.load().recruit_number_display)

    def test_only_the_owner_is_offered_the_queue(self):
        self.assertFalse(_json(self.read(BOARD))["can"]["approve"])
        self.assertTrue(_json(self.read(BOARD, self.admin))["can"]["approve"])

    def test_a_get_writes_nothing_and_the_queries_do_not_grow(self):
        from django.db import connection
        from django.test.utils import CaptureQueriesContext

        audit = AuditLog.objects.count()
        vac = self.vacancy()

        def queries():
            with CaptureQueriesContext(connection) as seen:
                self.read(BOARD)
            return len(seen)

        queries()
        few = queries()
        for number in range(8):
            Candidate.objects.create(full_name=f"Person {number}", vacancy=vac, status="owner_approval")
        self.assertEqual(queries(), few)
        self.assertEqual(AuditLog.objects.count(), audit)


class VacancyListTests(_Recruit):
    def test_the_vacancies_come_with_how_many_applied_and_a_status_filter(self):
        open_one = self.vacancy(title="Open one")
        draft = self.vacancy(title="Draft one", status="draft")
        for number in range(3):
            Candidate.objects.create(full_name=f"P{number}", vacancy=open_one)
        rows = {one["title"]: one for one in _json(self.read(VACANCIES))["rows"]}
        self.assertEqual((rows["Open one"]["applicants"], rows["Open one"]["status"]["ar"], rows["Draft one"]["applicants"]), (3, "مفتوحة", 0))
        only = _json(self.read(VACANCIES, status="draft"))["rows"]
        self.assertEqual([one["code"] for one in only], [draft.code])

    def test_the_blank_form_speaks_both_languages_and_has_one_deadline_box_in_days(self):
        ShiftTemplate.objects.create(name="Morning", name_ar="الصبح", start_time="09:00", end_time="17:00")
        fields = {one["name"]: one for one in _json(self.read(VACANCIES))["form"]}
        self.assertNotIn("deadline", fields)
        self.assertEqual((fields["deadline_days"]["kind"], fields["deadline_days"]["label_ar"]), ("number", "الإعلان يقفل بعد (يوم)"))
        self.assertEqual((fields["title"]["label_en"], fields["shifts"]["kind"]), ("Job title", "multi"))
        self.assertEqual({c["value"]: c["label_en"] for c in fields["status"]["choices"] if c["value"]}["open"], "Open")
        self.assertEqual({c["value"]: c["label_ar"] for c in fields["employment_type"]["choices"] if c["value"]}["part_time"], "دوام جزئي")
        self.assertIn("shifts", fields)


class VacancyCreateTests(_Recruit):
    def create(self, values, who=None):
        return self.post(who or self.hr, VACANCY_NEW, {"values": values})

    def test_a_vacancy_is_created_with_its_code_who_made_it_and_a_trail(self):
        dept = Department.objects.create(name="Linguistics", name_ar="اللغويات")
        shift = ShiftTemplate.objects.create(name="Morning", start_time="09:00", end_time="17:00")
        answer = self.create({
            "title": "Senior translator", "department": str(dept.pk), "openings": "2", "salary_min": "3000", "salary_max": "4500.50",
            "employment_type": "part_time", "work_mode": "remote", "shifts": [str(shift.pk)], "status": "open",
        })
        self.assertEqual(answer.status_code, 200)
        row = Vacancy.objects.get(code=_json(answer)["code"])
        self.assertEqual((row.title, row.department, row.openings, row.created_by, row.status), ("Senior translator", dept, 2, self.hr, "open"))
        self.assertEqual((row.salary_max, list(row.shifts.all())), (Decimal("4500.50"), [shift]))
        self.assertTrue(AuditLog.objects.filter(action="recruitment.vacancy.create", actor=self.hr).exists())

    def test_the_forms_rules_are_the_rules(self):
        answer = self.create({"title": "X", "salary_min": "5000", "salary_max": "4000"})
        self.assertEqual((answer.status_code, "salary_max" in _json(answer)["errors"]), (400, True))
        self.assertEqual("title" in _json(self.create({}))["errors"], True)
        self.assertEqual(self.create({"title": "X", "created_by": 1}).status_code, 400)
        self.assertEqual(self.create({"title": "X", "department": "999999"}).status_code, 400)
        self.assertFalse(Vacancy.objects.exists())

    def test_a_deadline_in_days_is_that_many_days_from_today(self):
        row = Vacancy.objects.get(code=_json(self.create({"title": "X", "deadline_days": "10"}))["code"])
        self.assertEqual(row.deadline, self.today + timedelta(days=10))

    def test_no_deadline_box_is_no_deadline_and_zero_is_none_either(self):
        for values in ({"title": "A"}, {"title": "B", "deadline_days": ""}, {"title": "C", "deadline_days": "0"}):
            row = Vacancy.objects.get(code=_json(self.create(values))["code"])
            self.assertIsNone(row.deadline, values)

    def test_a_deadline_that_is_not_a_number_of_days_is_refused(self):
        for bad in ("-1", "abc", "1.5", "4000", True, ["3"]):
            self.assertEqual(self.create({"title": "X", "deadline_days": bad}).status_code, 400, bad)
        self.assertFalse(Vacancy.objects.exists())

    def test_a_body_that_is_not_the_shape_is_refused(self):
        browser = DjangoClient()
        browser.force_login(self.hr)
        for body in ("{bad", json.dumps({"values": []}), json.dumps({"values": {"title": ["a"]}})):
            self.assertEqual(browser.post(reverse(VACANCY_NEW), body, content_type="application/json").status_code, 400, body)


class VacancyPageTests(_Recruit):
    def setUp(self):
        super().setUp()
        self.vac = self.vacancy(deadline=self.today + timedelta(days=20))
        self.dept = Department.objects.create(name="Linguistics", name_ar="اللغويات")
        self.other = Department.objects.create(name="Elsewhere")

    def test_the_page_carries_the_details_the_questions_in_order_and_who_applied(self):
        later = self.question("Second", kind="text")
        sooner = self.question("First", kind="yes_no", maps_to="email")
        VacancyQuestion.objects.create(vacancy=self.vac, question=later, order=2, is_required=False)
        VacancyQuestion.objects.create(vacancy=self.vac, question=sooner, order=1)
        Candidate.objects.create(full_name="Mona Candidate", vacancy=self.vac, shift_choice="Morning")
        body = _json(self.read(VACANCY, args=[self.vac.code]))
        self.assertEqual((body["vacancy"]["code"], body["vacancy"]["applicants"], body["vacancy"]["deadline"]), (self.vac.code, 1, (self.today + timedelta(days=20)).isoformat()))
        self.assertEqual([(one["question"]["text"], one["order"], one["required"]) for one in body["links"]], [("First", 1, True), ("Second", 2, False)])
        self.assertEqual((body["links"][0]["question"]["kind"]["ar"], body["links"][0]["question"]["maps_to"]["en"]), ("نعم / لا", "E-mail"))
        self.assertEqual([one["name"] for one in body["candidates"]], ["Mona Candidate"])

    def test_the_questions_it_could_be_given_exclude_what_it_has_and_what_is_switched_off(self):
        have, free, off = self.question("Have"), self.question("Free"), self.question("Off", is_active=False)
        VacancyQuestion.objects.create(vacancy=self.vac, question=have, order=1)
        pool = {one["text"] for one in _json(self.read(VACANCY, args=[self.vac.code]))["pool"]}
        self.assertIn("Free", pool)
        self.assertNotIn("Have", pool)
        self.assertNotIn("Off", pool)

    def test_a_department_narrows_the_list_and_never_dictates_it(self):
        Vacancy.objects.filter(pk=self.vac.pk).update(department=self.dept)
        general, mine, theirs = self.question("General"), self.question("Mine", department=self.dept), self.question("Theirs", department=self.other)
        pool = {one["text"]: one["department"] for one in _json(self.read(VACANCY, args=[self.vac.code]))["pool"]}
        self.assertEqual(pool["General"], None)
        self.assertEqual(pool["Mine"], "اللغويات")
        self.assertNotIn("Theirs", pool)

    def test_a_vacancy_that_is_not_there_is_not_there(self):
        self.assertEqual(self.read(VACANCY, args=["VAC-9999"]).status_code, 404)
        self.assertEqual(self.post(self.hr, VACANCY_SAVE, {"values": {}}, ["VAC-9999"]).status_code, 404)

    def save(self, values):
        return self.post(self.hr, VACANCY_SAVE, {"values": values}, [self.vac.code])

    def test_a_save_changes_the_boxes_that_were_sent_and_leaves_the_deadline_alone(self):
        self.assertEqual(self.save({"title": "Renamed", "status": "closed"}).status_code, 200)
        self.vac.refresh_from_db()
        self.assertEqual((self.vac.title, self.vac.status, self.vac.deadline), ("Renamed", "closed", self.today + timedelta(days=20)))
        self.assertTrue(AuditLog.objects.filter(action="recruitment.vacancy.update").exists())

    def test_a_deadline_can_be_moved_or_taken_off(self):
        self.save({"deadline_days": "5"})
        self.vac.refresh_from_db()
        self.assertEqual(self.vac.deadline, self.today + timedelta(days=5))
        self.save({"deadline_days": "0"})
        self.vac.refresh_from_db()
        self.assertIsNone(self.vac.deadline)

    def test_the_form_starts_from_the_vacancy(self):
        fields = {one["name"]: one for one in _json(self.read(VACANCY, args=[self.vac.code]))["form"]}
        self.assertEqual((fields["title"]["value"], fields["status"]["value"]), ("Translator", "open"))
        self.assertEqual(fields["deadline_days"]["value"], "")

    def test_a_question_is_added_once_to_the_end_and_a_closed_or_missing_one_is_refused(self):
        a, b, off = self.question("A"), self.question("B"), self.question("Off", is_active=False)
        first = self.post(self.hr, VQ_ADD, {"question": a.pk}, [self.vac.code])
        self.assertEqual((first.status_code, _json(first)["added"]), (200, True))
        self.post(self.hr, VQ_ADD, {"question": b.pk}, [self.vac.code])
        again = self.post(self.hr, VQ_ADD, {"question": a.pk}, [self.vac.code])
        self.assertEqual(_json(again)["added"], False)
        self.assertEqual(list(VacancyQuestion.objects.filter(vacancy=self.vac).order_by("order").values_list("question__text", "order", "is_required")), [("A", 1, True), ("B", 2, True)])
        self.assertEqual(self.post(self.hr, VQ_ADD, {"question": off.pk}, [self.vac.code]).status_code, 404)
        for body in ({}, {"question": "3"}, {"question": True}, {"question": 0}):
            self.assertEqual(self.post(self.hr, VQ_ADD, body, [self.vac.code]).status_code, 400, body)

    def test_the_order_and_the_required_boxes_are_saved_in_one_go(self):
        a, b = self.question("A"), self.question("B")
        la = VacancyQuestion.objects.create(vacancy=self.vac, question=a, order=1)
        lb = VacancyQuestion.objects.create(vacancy=self.vac, question=b, order=2)
        answer = self.post(self.hr, VQ_ORDER, {"rows": [{"id": la.pk, "order": 2, "required": False}, {"id": lb.pk, "order": 1, "required": True}]}, [self.vac.code])
        self.assertEqual((answer.status_code, _json(answer)["saved"]), (200, 2))
        la.refresh_from_db(), lb.refresh_from_db()
        self.assertEqual((la.order, la.is_required, lb.order, lb.is_required), (2, False, 1, True))
        self.assertEqual([one["question"]["text"] for one in _json(self.read(VACANCY, args=[self.vac.code]))["links"]], ["B", "A"])

    def test_an_order_cannot_touch_another_vacancys_questions(self):
        other = self.vacancy(title="Other")
        link = VacancyQuestion.objects.create(vacancy=other, question=self.question("Theirs"), order=1)
        answer = self.post(self.hr, VQ_ORDER, {"rows": [{"id": link.pk, "order": 9, "required": False}]}, [self.vac.code])
        self.assertEqual(_json(answer)["saved"], 0)
        link.refresh_from_db()
        self.assertEqual((link.order, link.is_required), (1, True))

    def test_an_order_of_the_wrong_shape_is_refused(self):
        for body in ({}, {"rows": "x"}, {"rows": [{"id": 1}]}, {"rows": [{"id": "1", "order": 1, "required": True}]},
                     {"rows": [{"id": 1, "order": -1, "required": True}]}, {"rows": [{"id": 1, "order": 1, "required": "yes"}]},
                     {"rows": [{"id": True, "order": 1, "required": True}]}, {"rows": [{"id": 1, "order": 99999, "required": True}]}):
            self.assertEqual(self.post(self.hr, VQ_ORDER, body, [self.vac.code]).status_code, 400, body)

    def test_a_question_is_taken_off_the_vacancy_and_stays_in_the_bank(self):
        q = self.question("Gone")
        link = VacancyQuestion.objects.create(vacancy=self.vac, question=q, order=1)
        answer = self.post(self.hr, VQ_DELETE, {}, [link.pk])
        self.assertEqual((answer.status_code, _json(answer)["code"]), (200, self.vac.code))
        self.assertFalse(VacancyQuestion.objects.filter(pk=link.pk).exists())
        self.assertTrue(RecruitmentQuestion.objects.filter(pk=q.pk).exists())
        self.assertEqual(self.post(self.hr, VQ_DELETE, {}, [link.pk]).status_code, 404)
        self.assertTrue(AuditLog.objects.filter(action="recruitment.vacancy.question.remove").exists())


class QuestionBankTests(_Recruit):
    def save(self, values, which=None):
        body = {"values": values}
        if which is not None:
            body["id"] = which
        return self.post(self.hr, QUESTION_SAVE, body)

    def test_the_bank_lists_every_question_with_its_options_department_and_what_it_fills(self):
        dept = Department.objects.create(name="Linguistics", name_ar="اللغويات")
        self.question("Pick one", kind="choice", options=["A", "B"], department=dept, maps_to="languages")
        row = [one for one in _json(self.read(QUESTIONS))["rows"] if one["text"] == "Pick one"][0]
        self.assertEqual((row["options"], row["department"], row["kind"]["en"], row["maps_to"]["ar"], row["is_active"]), (["A", "B"], "اللغويات", "Multiple choice (one)", "اللغات", True))

    def test_a_filter_by_department_and_a_bad_id_is_refused(self):
        dept = Department.objects.create(name="Linguistics")
        mine, other = self.question("Mine", department=dept), self.question("General")
        texts = [one["text"] for one in _json(self.read(QUESTIONS, department=dept.pk))["rows"]]
        self.assertEqual(texts, ["Mine"])
        self.assertEqual(self.read(QUESTIONS, department="abc").status_code, 400)

    def test_the_form_starts_blank_or_from_the_question_being_changed(self):
        q = self.question("Pick one", kind="choice", options=["A", "B"])
        edited = _json(self.read(QUESTIONS, edit=q.pk))
        fields = {one["name"]: one for one in edited["form"]}
        self.assertEqual((edited["editing"], fields["text"]["value"], fields["options_text"]["value"]), (q.pk, "Pick one", "A\nB"))
        self.assertEqual((fields["text"]["label_ar"], fields["kind"]["kind"]), ("السؤال بالعربي", "select"))
        self.assertEqual({c["value"]: c["label_ar"] for c in fields["kind"]["choices"] if c["value"]}["yes_no"], "نعم / لا")
        self.assertIsNone(_json(self.read(QUESTIONS, edit="abc"))["editing"])

    def test_a_question_is_added_with_whoever_added_it_and_changed_by_the_boxes_sent(self):
        answer = self.save({"text": "Your name?", "kind": "text", "maps_to": "full_name"})
        self.assertEqual(answer.status_code, 200)
        row = RecruitmentQuestion.objects.get(text="Your name?")
        self.assertEqual((row.created_by, row.maps_to, row.is_active), (self.hr, "full_name", True))
        self.save({"text_en": "What is your name?"}, row.pk)
        row.refresh_from_db()
        self.assertEqual((row.text_en, row.text, row.created_by), ("What is your name?", "Your name?", self.hr))
        self.assertTrue(AuditLog.objects.filter(action="recruitment.question.save", actor=self.hr).exists())

    def test_a_pick_question_needs_two_options_and_they_are_one_per_line(self):
        refused = self.save({"text": "Pick", "kind": "choice", "options_text": "only one"})
        self.assertEqual((refused.status_code, "options_text" in _json(refused)["errors"]), (400, True))
        self.save({"text": "Pick", "kind": "choice", "options_text": "A\n\n  B  \nC"})
        self.assertEqual(RecruitmentQuestion.objects.get(text="Pick").options, ["A", "B", "C"])

    def test_the_forms_rules_are_the_rules(self):
        self.assertTrue("text" in _json(self.save({}))["errors"])
        self.assertEqual(self.save({"text": "x", "created_by": 1}).status_code, 400)
        self.assertEqual(self.save({"text": "x"}, 999999).status_code, 404)
        for body in ({"id": "1", "values": {}}, {"id": True, "values": {}}, {"values": []}):
            self.assertEqual(self.post(self.hr, QUESTION_SAVE, body).status_code, 400, body)

    def test_a_department_is_added_open_and_counted(self):
        answer = self.post(self.hr, DEPARTMENT, {"values": {"name": "Legal", "name_ar": "القانونية"}})
        self.assertEqual(answer.status_code, 200)
        row = Department.objects.get(name="Legal")
        self.assertTrue(row.is_active)
        self.question("Q", department=row)
        listed = {one["label"]: one["questions"] for one in _json(self.read(QUESTIONS))["departments"]}
        self.assertEqual(listed["القانونية"], 1)
        self.assertTrue(AuditLog.objects.filter(action="recruitment.department.add").exists())

    def test_a_department_box_takes_a_name_and_nothing_else(self):
        for values in ({"name": "X", "is_active": False}, {"name": "X", "id": 3}, {}, {"name": "x" * 200}):
            self.assertIn(self.post(self.hr, DEPARTMENT, {"values": values}).status_code, (400,), values)
        self.assertFalse(Department.objects.filter(name="X").exists())

    def test_the_number_of_queries_does_not_grow_with_the_questions(self):
        from django.db import connection
        from django.test.utils import CaptureQueriesContext

        def queries():
            with CaptureQueriesContext(connection) as seen:
                self.read(QUESTIONS)
            return len(seen)

        dept = Department.objects.create(name="Linguistics")
        self.question("One", department=dept)
        queries()
        few = queries()
        for number in range(10):
            self.question(f"More {number}", department=dept)
        self.assertEqual(queries(), few)


class SettingsTests(_Recruit):
    def test_the_rules_the_proof_the_filter_works_and_the_line(self):
        body = _json(self.read(SETTINGS))
        self.assertTrue(body["privacy_armed"])
        self.assertNotIn("EagleLingua", body["sample"])
        self.assertIn(RecruitmentSettings.load().redact_placeholder, body["sample"])
        fields = {one["name"]: one for one in body["form"]}
        self.assertEqual((fields["redact_terms"]["label_ar"], fields["probation_days"]["label_en"]), ("الكلمات (واحدة في كل سطر)", "Probation (days)"))
        self.assertIn("EagleLingua", fields["redact_terms"]["value"])
        self.assertEqual(set(body["line"]), {"number", "phone_number_id"})

    def test_the_phone_number_id_is_said_to_be_set_never_shown(self):
        conf = AppSettings.load()
        conf.recruit_phone_number_id = "1234567890123"
        conf.save()
        raw = self.read(SETTINGS).content.decode()
        self.assertNotIn("1234567890123", raw)
        self.assertTrue(_json(self.read(SETTINGS))["line"]["phone_number_id"])

    def test_with_nothing_to_redact_the_page_says_the_rule_is_not_armed(self):
        conf = RecruitmentSettings.load()
        conf.redact_terms = ""
        conf.save()
        body = _json(self.read(SETTINGS))
        self.assertFalse(body["privacy_armed"])

    def test_a_save_changes_the_boxes_sent_and_writes_a_trail(self):
        words = list(RecruitmentSettings.load().term_list)
        answer = self.post(self.hr, SETTINGS_SAVE, {"values": {"probation_days": "60", "bot_name_ar": "فريق جديد"}})
        self.assertEqual(answer.status_code, 200)
        conf = RecruitmentSettings.load()
        self.assertEqual((conf.probation_days, conf.bot_name_ar, conf.term_list), (60, "فريق جديد", words))
        self.assertTrue(AuditLog.objects.filter(action="recruitment.settings.update", actor=self.hr).exists())
        self.assertFalse(AuditLog.objects.filter(action="recruitment.redact.update").exists())

    def test_the_new_rule_is_what_the_filter_uses_at_once(self):
        from . import recruitment

        self.post(self.admin, SETTINGS_SAVE, {"values": {"redact_terms": "Acme", "redact_placeholder": "[hidden]"}})
        self.assertEqual(recruitment.outbound_text(None, "Hello from Acme"), "Hello from [hidden]")

    def test_hr_sees_the_words_locked_and_the_owner_sees_them_open(self):
        for who, can in ((self.hr, False), (self.admin, True)):
            body = _json(self.read(SETTINGS, who))
            fields = {one["name"]: one for one in body["form"]}
            self.assertEqual(body["can"], {"redact": can})
            self.assertEqual((fields["redact_terms"]["disabled"], fields["redact_placeholder"]["disabled"]), (not can, not can), who.username)
            self.assertFalse(fields["probation_days"]["disabled"])
            self.assertIn("EagleLingua", fields["redact_terms"]["value"])

    def test_hr_cannot_change_the_words_even_by_sending_the_same_ones_and_the_refusal_is_written_down(self):
        words = list(RecruitmentSettings.load().term_list)
        stand_in = RecruitmentSettings.load().redact_placeholder
        for values in (
            {"redact_terms": ""}, {"redact_terms": "Acme"}, {"redact_terms": "\n".join(words)},
            {"redact_placeholder": "x"}, {"redact_placeholder": stand_in}, {"probation_days": "70", "redact_terms": "Acme"},
        ):
            answer = self.post(self.hr, SETTINGS_SAVE, {"values": values})
            self.assertEqual((answer.status_code, _json(answer)["error"]), (403, "owner_only"), values)
        conf = RecruitmentSettings.load()
        self.assertEqual((conf.term_list, conf.redact_placeholder, conf.probation_days), (words, stand_in, 90))
        self.assertEqual(AuditLog.objects.filter(action="security.denied", actor=self.hr).count(), 1)
        self.assertTrue(_json(self.read(SETTINGS))["privacy_armed"])

    def test_nobody_but_the_owner_and_hr_is_answered_and_a_flagged_person_cannot_change_the_words(self):
        for who in (self.flagged, self.ops, self.tr):
            answer = self.post(who, SETTINGS_SAVE, {"values": {"redact_terms": ""}})
            self.assertEqual(answer.status_code, 403, who.username)
        self.assertTrue(RecruitmentSettings.load().term_list)

    def test_the_owner_changes_them_and_the_log_carries_the_words_that_went_and_came(self):
        before = list(RecruitmentSettings.load().term_list)
        answer = self.post(self.admin, SETTINGS_SAVE, {"values": {"redact_terms": "Acme\nAcme Ltd", "redact_placeholder": "[hidden]"}})
        self.assertEqual(answer.status_code, 200)
        conf = RecruitmentSettings.load()
        self.assertEqual((conf.term_list, conf.redact_placeholder), (["Acme", "Acme Ltd"], "[hidden]"))
        row = AuditLog.objects.get(action="recruitment.redact.update")
        self.assertEqual(row.actor, self.admin)
        for word in before:
            self.assertIn(word, row.detail)
        self.assertIn("Acme Ltd", row.detail)
        self.assertIn("[hidden]", row.detail)
        self.assertIn("armed: True", row.detail)

    def test_the_owner_emptying_the_list_is_written_down_as_disarmed(self):
        self.post(self.admin, SETTINGS_SAVE, {"values": {"redact_terms": ""}})
        row = AuditLog.objects.get(action="recruitment.redact.update")
        self.assertIn("armed: False", row.detail)
        self.assertFalse(_json(self.read(SETTINGS))["privacy_armed"])

    def test_the_owner_saving_something_else_writes_no_redact_row(self):
        self.post(self.admin, SETTINGS_SAVE, {"values": {"probation_days": "75"}})
        self.assertFalse(AuditLog.objects.filter(action="recruitment.redact.update").exists())

    def test_a_values_that_is_not_a_dict_is_a_400(self):
        for body in ({"values": []}, {"values": "x"}, {"values": None}):
            self.assertEqual(self.post(self.hr, SETTINGS_SAVE, body).status_code, 400, body)

    def test_the_forms_rules_are_the_rules(self):
        answer = self.post(self.hr, SETTINGS_SAVE, {"values": {"probation_days": "-5"}})
        self.assertEqual((answer.status_code, "probation_days" in _json(answer)["errors"]), (400, True))
        self.assertEqual(self.post(self.hr, SETTINGS_SAVE, {"values": {"singleton": 2}}).status_code, 400)
        self.assertEqual(RecruitmentSettings.load().probation_days, 90)


class HandOnTests(_Recruit):
    def setUp(self):
        super().setUp()
        self.switch(roles=["hr"])
        self.vac = self.vacancy()

    def classic(self, name, args=None, who=None, **query):
        browser = DjangoClient()
        browser.force_login(who or self.hr)
        return browser.get(reverse(f"dashboard:{name}", args=args), query)

    def test_each_page_is_handed_on_with_what_it_carries(self):
        for name, args, path, query, kept in (
            ("hr_recruitment", None, "/app/hr/recruitment", {}, ""),
            ("hr_vacancies", None, "/app/hr/vacancies", {"status": "draft"}, "status=draft"),
            ("hr_vacancy", [self.vac.code], f"/app/hr/vacancies/{self.vac.code}", {}, ""),
            ("hr_questions", None, "/app/hr/questions", {"department": "3", "edit": "4"}, "edit=4"),
            ("hr_recruitment_settings", None, "/app/hr/recruitment/settings", {}, ""),
        ):
            answer = self.classic(name, args, **query)
            self.assertEqual(answer.status_code, 302, name)
            self.assertTrue(answer["Location"].startswith(path), answer["Location"])
            self.assertIn(kept, answer["Location"])

    def test_a_vacancy_that_is_not_there_is_a_404_even_when_handed_on(self):
        self.assertEqual(self.classic("hr_vacancy", ["VAC-9999"]).status_code, 404)

    def test_the_classic_page_stays_reachable_and_the_flag_holder_is_not_let_in(self):
        for name in ("hr_recruitment", "hr_vacancies", "hr_questions", "hr_recruitment_settings"):
            self.assertEqual(self.classic(name, classic=1).status_code, 200, name)
            self.assertEqual(self.classic(name, who=self.flagged).status_code, 403, name)

    def test_the_classic_department_box_adds_a_department_that_is_open(self):
        browser = DjangoClient()
        browser.force_login(self.hr)
        answer = browser.post(reverse("dashboard:hr_department_add"), {"name": "Legal", "name_ar": "القانونية"})
        self.assertEqual(answer.status_code, 302)
        self.assertTrue(Department.objects.get(name="Legal").is_active)

    def test_a_post_to_a_classic_page_is_never_handed_on(self):
        browser = DjangoClient()
        browser.force_login(self.hr)
        answer = browser.post(reverse("dashboard:hr_recruitment_settings"), {"probation_days": "45", "session_timeout_hours": "48", "redact_placeholder": "[—]", "bot_name": "x", "bot_name_ar": "y"})
        self.assertEqual(answer.status_code, 302)
        self.assertEqual(answer["Location"], reverse("dashboard:hr_recruitment_settings"))
        self.assertEqual(RecruitmentSettings.load().probation_days, 45)
