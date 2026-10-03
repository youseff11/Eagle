"""The AI's notes in the new app: the box on a task page, and the panel beside the leader's chat with a translator.

The notes are suggestions for a review and are read by the review's owner only: the admin and the task's own team leader see
the box, and the leader alone sees the panel. Nobody else - not the operation, not the translator whose work it is (who keeps
the smaller card), not another leader. What the AI quotes comes from the client's files, so for whoever may not know the client
every text is read through the mask; and a GET writes nothing.
"""

from django.db import connection
from django.test import Client as DjangoClient
from django.test.utils import CaptureQueriesContext
from django.urls import reverse
from django.utils import timezone

from .models import AICheckResult, AppSettings, AuditLog, ChatRoom, Role, TaskStatus, User
from .tests_api_v1 import CLIENT_EMAIL, CLIENT_NAME, CLIENT_PHONE, IDENTITY_MARKERS, _json, _Site

NOTES = "dashboard:v1_ai_task_notes"
GROUP = "dashboard:v1_ai_group_notes"
STAFF = "dashboard:v1_ai_staff_notes"


def issue(text, severity="medium", **over):
    return {
        "category": "terminology", "category_ar": "مصطلحات", "category_en": "Terminology", "severity": severity,
        "location": "page 2", "source_excerpt": "the source words", "translation_excerpt": "the translated words",
        "issue_ar": f"{text} ar", "issue_en": f"{text} en", "correct_meaning_ar": "المعنى في الأصل", **over,
    }


class _Notes(_Site):
    def setUp(self):
        super().setUp()
        self.task.status = TaskStatus.UNDER_REVIEW
        self.task.translated_at = timezone.now()
        self.task.save()
        self.other_lead = User.objects.create_user("person_leader_two", password="pw", role=Role.TEAM_LEAD)

    def check(self, issues=None, status=AICheckResult.Status.ISSUES, **fields):
        return AICheckResult.objects.create(
            task=self.task, status=status, issues=[issue("one")] if issues is None else issues, **fields,
        )

    def get(self, user, name, args=None):
        browser = DjangoClient()
        if user is not None:
            browser.force_login(user)
        return browser.get(reverse(name, args=args))

    def notes(self, user=None):
        return _json(self.get(user or self.lead, NOTES, [self.task.code]))


class TaskNotesDoorTests(_Notes):
    def test_the_admin_and_the_tasks_own_leader_read_it_and_nobody_else(self):
        self.check()
        for user in (self.lead, self.admin):
            answer = self.get(user, NOTES, [self.task.code])
            self.assertEqual(answer.status_code, 200, user.username)
            self.assertEqual(answer["Cache-Control"], "private, no-store")
        # The operation, the translator whose work it is, and everybody else who is not a team leader are refused.
        for user in (self.ops, self.tr, self.hr, self.reviewer, self.accounting, self.sales):
            answer = self.get(user, NOTES, [self.task.code])
            self.assertEqual((answer.status_code, _json(answer)), (403, {"ok": False, "error": "forbidden"}), user.username)
        self.assertEqual(self.get(None, NOTES, [self.task.code]).status_code, 401)
        browser = DjangoClient()
        browser.force_login(self.lead)
        self.assertEqual(browser.post(reverse(NOTES, args=[self.task.code])).status_code, 405)

    def test_another_leaders_task_is_a_404_and_a_row_in_the_audit_log_not_a_403(self):
        self.check()
        before = AuditLog.objects.filter(action=identity_denied()).count()
        answer = self.get(self.other_lead, NOTES, [self.task.code])
        self.assertEqual(answer.status_code, 404)
        self.assertEqual(AuditLog.objects.filter(action=identity_denied()).count(), before + 1)
        self.assertEqual(self.get(self.lead, NOTES, ["TSK-99999"]).status_code, 404)

    def test_a_leader_of_the_task_who_is_not_the_one_reviewing_it_anymore_is_refused_too(self):
        self.check()
        self.task.team_lead = self.other_lead
        self.task.save()
        self.assertEqual(self.get(self.lead, NOTES, [self.task.code]).status_code, 404)
        self.assertEqual(self.get(self.other_lead, NOTES, [self.task.code]).status_code, 200)

    def test_no_check_yet_says_so(self):
        body = self.notes()
        self.assertEqual((body["check"], body["issues"]), (None, []))
        self.assertEqual(body["task"], {"code": self.task.code, "title": self.task.title})

    def test_the_latest_check_is_the_one_read_with_its_numbers(self):
        self.check([issue("old one")])
        latest = self.check([issue("a"), issue("b")], summary="Looks mostly fine.", requested_by=self.lead)
        check = self.notes()["check"]
        self.assertEqual((check["id"], check["status"], check["count"]), (latest.pk, "issues", 2))
        self.assertEqual((check["summary"], check["automatic"], check["old"]), ("Looks mostly fine.", False, False))
        self.assertIn("en", check["at"])

    def test_a_check_nobody_asked_for_says_it_ran_by_itself(self):
        self.check()
        self.assertTrue(self.notes()["check"]["automatic"])

    def test_the_notes_come_most_serious_first_and_one_with_no_severity_is_a_medium_one(self):
        self.check([issue("low", "low"), issue("none", None), issue("high", "high"), issue("odd", "catastrophic"), issue("mid", "medium")])
        issues = self.notes()["issues"]
        self.assertEqual([one["text"]["en"] for one in issues], ["high en", "none en", "odd en", "mid en", "low en"])
        self.assertEqual([one["severity"] for one in issues], ["high", "medium", "medium", "medium", "low"])

    def test_each_note_carries_both_texts_the_category_and_what_the_source_means(self):
        self.check([issue("x", "high")])
        one = self.notes()["issues"][0]
        self.assertEqual((one["location"], one["source"], one["translation"]), ("page 2", "the source words", "the translated words"))
        self.assertEqual(one["category"], {"ar": "مصطلحات", "en": "Terminology"})
        self.assertEqual(one["text"], {"ar": "x ar", "en": "x en"})
        self.assertEqual((one["meaning"], one["compared"]), ("المعنى في الأصل", True))

    def test_a_note_with_one_language_says_it_in_both_and_one_with_no_category_has_none(self):
        self.check([{"severity": "low", "issue_en": "Only English", "source_excerpt": "s"}])
        one = self.notes()["issues"][0]
        self.assertEqual(one["text"], {"ar": "Only English", "en": "Only English"})
        self.assertIsNone(one["category"])
        self.assertEqual((one["location"], one["translation"], one["meaning"]), ("", "", ""))

    def test_a_check_from_before_the_side_by_side_comparison_is_read_and_called_old(self):
        self.check([{"severity": "high", "location": "row 4", "issue": "Wrong term"}], summary="Old summary")
        body = self.notes()
        self.assertTrue(body["check"]["old"])
        one = body["issues"][0]
        self.assertEqual(one["text"], {"ar": "Wrong term", "en": "Wrong term"})
        self.assertFalse(one["compared"])

    def test_things_that_are_not_notes_are_left_out(self):
        self.check(["a string", None, 5, issue("real")])
        self.assertEqual([one["text"]["en"] for one in self.notes()["issues"]], ["real en"])

    def test_no_more_than_fifty_notes_are_listed_but_all_are_counted(self):
        self.check([issue(f"n{index}") for index in range(70)])
        body = self.notes()
        self.assertEqual((len(body["issues"]), body["check"]["count"]), (50, 70))

    def test_a_check_that_found_nothing_has_no_notes_and_one_that_did_not_finish_says_why(self):
        self.check([], status=AICheckResult.Status.CLEAN, summary="Nothing obvious")
        body = self.notes()
        self.assertEqual((body["check"]["status"], body["issues"]), ("clean", []))
        self.check([], status=AICheckResult.Status.ERROR, error_message="HTTP 529: overloaded")
        body = self.notes()
        self.assertEqual((body["check"]["status"], body["check"]["error"]), ("error", "HTTP 529: overloaded"))
        # The error is only said of a check that failed.
        self.check([], status=AICheckResult.Status.CLEAN, error_message="stale")
        self.assertEqual(self.notes()["check"]["error"], "")

    def test_a_check_can_be_asked_for_again_only_when_it_is_on_and_not_already_running(self):
        self.check()
        conf = AppSettings.load()
        self.assertFalse(self.notes()["can_recheck"])
        conf.ai_check_enabled = True
        conf.save()
        self.assertFalse(self.notes()["can_recheck"])
        conf.claude_api_key = "a-test-key-not-a-real-one"
        conf.save()
        self.assertTrue(self.notes()["can_recheck"])
        self.check([], status=AICheckResult.Status.RUNNING)
        self.assertFalse(self.notes()["can_recheck"])

    def test_the_leader_reads_the_client_by_code_in_every_text_and_the_admin_as_it_was_written(self):
        written = f"{CLIENT_NAME} wrote to {CLIENT_EMAIL} or {CLIENT_PHONE}"
        self.check(
            [issue(written, source_excerpt=f"Dear {CLIENT_NAME}", translation_excerpt=written, location=f"{CLIENT_NAME} p1",
                   correct_meaning_ar=f"يقصد {CLIENT_NAME}", category_ar=f"{CLIENT_NAME} x")],
            summary=f"{CLIENT_NAME} document, contact {CLIENT_EMAIL}", status=AICheckResult.Status.ISSUES,
        )
        answer = self.get(self.lead, NOTES, [self.task.code])
        text = answer.content.decode("utf-8")
        for marker in IDENTITY_MARKERS:
            self.assertNotIn(marker, text, marker)
        self.assertIn(self.client_obj.code, text)
        raw = self.get(self.admin, NOTES, [self.task.code]).content.decode("utf-8")
        self.assertIn(CLIENT_NAME, raw)

    def test_the_error_of_a_check_does_not_quote_an_address_to_the_leader(self):
        self.check([], status=AICheckResult.Status.ERROR, error_message=f"could not read the file from {CLIENT_EMAIL}")
        text = self.get(self.lead, NOTES, [self.task.code]).content.decode("utf-8")
        self.assertNotIn(CLIENT_EMAIL, text)

    def test_a_get_writes_nothing(self):
        self.check()
        before = (AICheckResult.objects.count(), ChatRoom.objects.count(), AuditLog.objects.count())
        self.get(self.lead, NOTES, [self.task.code])
        self.get(self.admin, NOTES, [self.task.code])
        self.assertEqual(before, (AICheckResult.objects.count(), ChatRoom.objects.count(), AuditLog.objects.count()))

    def test_the_page_costs_the_same_however_many_notes(self):
        def cost():
            with CaptureQueriesContext(connection) as queries:
                self.get(self.lead, NOTES, [self.task.code])
            return len(queries)

        self.check([issue("a")])
        few = cost()
        AICheckResult.objects.all().delete()
        self.check([issue(f"n{index}") for index in range(40)])
        self.assertEqual(cost(), few)

    def test_the_classic_page_still_shows_the_same_box_to_the_same_people(self):
        self.check([issue("shown")])
        browser = DjangoClient()
        browser.force_login(self.lead)
        page = browser.get(reverse("dashboard:task_detail", args=[self.task.code])).content.decode("utf-8")
        self.assertIn("ملاحظات الـ AI على الترجمة", page)


def identity_denied():
    from . import identity

    return identity.ACCESS_DENIED


class StaffPanelTests(_Notes):
    def test_the_leader_reads_the_notes_on_what_the_translator_handed_over(self):
        self.check([issue("low", "low"), issue("high", "high")])
        body = _json(self.get(self.lead, STAFF, [self.tr.pk]))
        notes = body["notes"]
        self.assertEqual(notes["task"], {"code": self.task.code, "title": self.task.title})
        self.assertEqual((notes["count"], [one["severity"] for one in notes["issues"]]), (2, ["high", "low"]))

    def test_nothing_is_said_when_there_is_nothing_to_show(self):
        # No check yet, a check that found nothing, one that did not finish: no panel.
        self.assertIsNone(_json(self.get(self.lead, STAFF, [self.tr.pk]))["notes"])
        self.check([], status=AICheckResult.Status.CLEAN)
        self.assertIsNone(_json(self.get(self.lead, STAFF, [self.tr.pk]))["notes"])
        self.check([], status=AICheckResult.Status.ERROR, error_message="x")
        self.assertIsNone(_json(self.get(self.lead, STAFF, [self.tr.pk]))["notes"])

    def test_only_a_task_that_is_under_review_and_this_leaders_own_is_a_reason_for_a_panel(self):
        self.check()
        self.task.status = TaskStatus.IN_PROGRESS
        self.task.save()
        self.assertIsNone(_json(self.get(self.lead, STAFF, [self.tr.pk]))["notes"])
        self.task.status = TaskStatus.UNDER_REVIEW
        self.task.save()
        self.assertIsNotNone(_json(self.get(self.lead, STAFF, [self.tr.pk]))["notes"])
        # Another leader has no task with this translator.
        self.assertIsNone(_json(self.get(self.other_lead, STAFF, [self.tr.pk]))["notes"])
        # A colleague who handed over nothing.
        self.assertIsNone(_json(self.get(self.lead, STAFF, [self.ops.pk]))["notes"])

    def test_only_a_team_leader_reads_it_and_the_admin_has_nothing_to_review_here(self):
        self.check()
        for user in (self.ops, self.tr, self.hr, self.reviewer, self.accounting, self.sales):
            self.assertEqual(self.get(user, STAFF, [self.tr.pk]).status_code, 403, user.username)
        self.assertEqual(self.get(None, STAFF, [self.tr.pk]).status_code, 401)
        self.assertIsNone(_json(self.get(self.admin, STAFF, [self.tr.pk]))["notes"])

    def test_a_colleague_who_is_not_there_or_is_oneself_is_a_404(self):
        self.assertEqual(self.get(self.lead, STAFF, [self.lead.pk]).status_code, 404)
        self.assertEqual(self.get(self.lead, STAFF, [999999]).status_code, 404)
        self.tr.is_active = False
        self.tr.save()
        self.assertEqual(self.get(self.lead, STAFF, [self.tr.pk]).status_code, 404)

    def test_asking_opens_no_room_and_writes_nothing(self):
        self.check()
        before = (ChatRoom.objects.count(), AuditLog.objects.count(), AICheckResult.objects.count())
        self.get(self.lead, STAFF, [self.tr.pk])
        self.assertEqual(before, (ChatRoom.objects.count(), AuditLog.objects.count(), AICheckResult.objects.count()))

    def test_the_panel_names_the_client_only_by_code(self):
        self.check([issue(f"{CLIENT_NAME} {CLIENT_EMAIL}", source_excerpt=CLIENT_NAME)])
        text = self.get(self.lead, STAFF, [self.tr.pk]).content.decode("utf-8")
        for marker in IDENTITY_MARKERS:
            self.assertNotIn(marker, text, marker)

    def test_a_check_in_the_old_format_still_says_something(self):
        self.check([{"severity": "high", "location": "row 4", "issue": "Wrong term"}])
        one = _json(self.get(self.lead, STAFF, [self.tr.pk]))["notes"]["issues"][0]
        self.assertEqual((one["location"], one["text"]["en"]), ("row 4", "Wrong term"))

    def test_the_classic_chat_page_still_shows_the_panel_to_the_leader(self):
        self.check([issue("shown")])
        browser = DjangoClient()
        browser.force_login(self.lead)
        page = browser.get(reverse("dashboard:ops_staff_chat", args=[self.tr.pk]) + "?classic=1").content.decode("utf-8")
        self.assertIn("اقتراحات الـAI", page)


class GroupPanelTests(_Notes):
    def team_group(self, *translators):
        from . import services

        room, error = services.create_team_group(self.lead, "Leader and translator", list(translators or [self.tr]))
        self.assertIsNotNone(room, error)
        return room

    def test_the_leader_reads_the_notes_in_their_work_group_with_one_translator(self):
        self.check([issue("a")])
        room = self.team_group()
        notes = _json(self.get(self.lead, GROUP, [room.pk]))["notes"]
        self.assertEqual((notes["task"]["code"], notes["count"]), (self.task.code, 1))

    def test_a_group_of_two_translators_has_no_panel_because_it_would_not_say_whose(self):
        self.check()
        second = User.objects.create_user("person_translator_two", password="pw", role=Role.TRANSLATOR, team_lead=self.lead)
        room = self.team_group(self.tr, second)
        self.assertIsNone(_json(self.get(self.lead, GROUP, [room.pk]))["notes"])

    def test_a_room_that_is_not_a_work_group_has_no_panel_and_one_the_leader_may_not_open_is_a_404(self):
        self.check()
        # The leader is in the staff chat and it is not a work group: nothing to show. The task's own group and a client's
        # group are not rooms they may ask about: not theirs to open.
        self.assertIsNone(_json(self.get(self.lead, GROUP, [self.staff.pk]))["notes"])
        self.assertEqual(self.get(self.lead, GROUP, [self.task_group.pk]).status_code, 404)
        self.assertEqual(self.get(self.lead, GROUP, [self.client_group.pk]).status_code, 404)

    def test_a_room_that_is_not_theirs_is_a_404_and_a_row_in_the_audit_log(self):
        self.check()
        room = self.team_group()
        before = AuditLog.objects.filter(action=identity_denied()).count()
        self.assertEqual(self.get(self.other_lead, GROUP, [room.pk]).status_code, 404)
        self.assertGreater(AuditLog.objects.filter(action=identity_denied()).count(), before)
        self.assertEqual(self.get(self.lead, GROUP, [999999]).status_code, 404)

    def test_only_a_team_leader_reads_it(self):
        self.check()
        room = self.team_group()
        for user in (self.ops, self.tr, self.hr, self.reviewer, self.accounting, self.sales):
            self.assertEqual(self.get(user, GROUP, [room.pk]).status_code, 403, user.username)
        self.assertEqual(self.get(None, GROUP, [room.pk]).status_code, 401)
        # The admin may open any group, and has no review to be told about in it.
        answer = self.get(self.admin, GROUP, [room.pk])
        self.assertEqual(answer.status_code, 200)
        self.assertIsNone(_json(answer)["notes"])

    def test_it_is_the_same_panel_the_leader_gets_in_their_one_to_one_chat(self):
        self.check([issue("a"), issue("b", "high")])
        room = self.team_group()
        self.assertEqual(_json(self.get(self.lead, GROUP, [room.pk])), _json(self.get(self.lead, STAFF, [self.tr.pk])))

