"""Smoke tests for the Eagle workflow engine."""

from datetime import timedelta
from decimal import Decimal

from django.test import TestCase
from django.utils import timezone

from . import services
from .models import (
    AppSettings,
    AssignmentStatus,
    Client,
    Role,
    RoomKind,
    Task,
    TaskStatus,
    User,
)


class WorkflowTests(TestCase):
    def setUp(self):
        self.ops = User.objects.create_user("ops", password="x", role=Role.OPERATION)
        self.lead = User.objects.create_user("lead", password="x", role=Role.TEAM_LEAD)
        self.tr = User.objects.create_user(
            "tr", password="x", role=Role.TRANSLATOR, team_lead=self.lead
        )
        self.client_obj = Client.objects.create(name="ACME", phone="+201000000000")

    def make_task(self):
        return services.create_task(
            client=self.client_obj, title="Doc", created_by=self.ops,
            deadline=timezone.now() + timedelta(hours=2),
        )

    def test_codes_are_sequential(self):
        self.assertTrue(self.client_obj.code.startswith("CL-"))
        self.assertTrue(self.make_task().code.startswith("TSK-"))

    def test_rate_keyword_hides_message(self):
        msg = services.ingest_message(
            channel="whatsapp", body="what is your rate for 10 pages?",
            sender_identity="+201000000000",
        )
        self.assertTrue(msg.is_rate_blocked)
        self.assertFalse(msg.visible_to(self.ops))

    def test_client_identity_is_masked(self):
        self.assertEqual(self.client_obj.label_for(self.ops), self.client_obj.code)

    def test_full_happy_path(self):
        task = self.make_task()
        a1 = services.assign_to_lead(task, self.lead, self.ops)
        self.assertEqual(a1.status, AssignmentStatus.PENDING)
        ok, _ = services.accept_assignment(a1, self.lead)
        self.assertTrue(ok)
        task.refresh_from_db()
        self.assertEqual(task.status, TaskStatus.LEAD_ACCEPTED)

        a2 = services.assign_to_translator(task, self.tr, self.lead)
        ok, _ = services.accept_assignment(a2, self.tr)
        self.assertTrue(ok)
        task.refresh_from_db()
        self.assertEqual(task.status, TaskStatus.IN_PROGRESS)
        # ops+lead, the full group, and the relayed client room.
        self.assertEqual(task.rooms.count(), 3)
        client_room = task.rooms.get(kind=RoomKind.CLIENT)
        # The translator accepted, so they may talk to the client.
        self.assertIn(self.tr, client_room.members.all())

        services.mark_translated(task, self.tr)
        task.refresh_from_db()
        self.assertEqual(task.status, TaskStatus.UNDER_REVIEW)
        services.mark_reviewed(task, self.lead)
        task.refresh_from_db()
        self.assertEqual(task.status, TaskStatus.REVIEWED)
        services.mark_delivered(task, self.ops)
        task.refresh_from_db()
        self.assertEqual(task.status, TaskStatus.DELIVERED)

    def test_expired_assignment_costs_an_eighth_of_a_star(self):
        task = self.make_task()
        assignment = services.assign_to_lead(task, self.lead, self.ops)
        assignment.expires_at = timezone.now() - timedelta(seconds=1)
        assignment.save(update_fields=["expires_at"])

        services.sweep_expired_assignments()
        assignment.refresh_from_db()
        self.lead.refresh_from_db()
        task.refresh_from_db()

        self.assertEqual(assignment.status, AssignmentStatus.EXPIRED)
        self.assertEqual(self.lead.rating, Decimal("4.875"))
        self.assertEqual(task.status, TaskStatus.NEW)
        self.assertIsNone(task.team_lead_id)

    def test_delivery_sends_files_over_whatsapp(self):
        from unittest import mock

        from django.core.files.base import ContentFile

        from .models import ChatAttachment, ChatMessage, OutboundMessage, RoomKind

        task = self.make_task()
        task.team_lead, task.translator = self.lead, self.tr
        task.status = TaskStatus.REVIEWED
        task.save()
        room = services.ensure_room(task, RoomKind.GROUP)
        message = ChatMessage.objects.create(room=room, sender=self.tr, body="done")
        attachment = ChatAttachment.objects.create(
            message=message, file=ContentFile(b"translated", name="out.txt"),
            original_name="out.txt", size=10,
        )

        with mock.patch("dashboard.whatsapp.send_text", return_value="wamid.0"), \
                mock.patch("dashboard.whatsapp.send_file", return_value="wamid.1") as sender:
            ok, delivery, error = services.deliver_to_client(
                task, self.ops, attachment_ids=[attachment.id], note="اتفضل الملفات"
            )

        self.assertTrue(ok, error)
        self.assertEqual(delivery.status, OutboundMessage.Status.SENT)
        self.assertEqual(sender.call_count, 1)
        task.refresh_from_db()
        self.assertEqual(task.status, TaskStatus.DELIVERED)

    def test_failed_delivery_keeps_the_task_open(self):
        from unittest import mock

        from .models import OutboundMessage

        task = self.make_task()
        task.status = TaskStatus.REVIEWED
        task.save()

        from . import whatsapp as wa

        with mock.patch("dashboard.whatsapp.send_text",
                        side_effect=wa.WhatsAppError("فات 24 ساعة", "24h window closed")):
            ok, delivery, error = services.deliver_to_client(
                task, self.ops, attachment_ids=[], note="اتفضل"
            )

        self.assertFalse(ok)
        self.assertEqual(delivery.status, OutboundMessage.Status.FAILED)
        self.assertIn("24", error)
        task.refresh_from_db()
        self.assertEqual(task.status, TaskStatus.REVIEWED)

    def test_delivery_without_contact_details_fails_cleanly(self):
        from .models import OutboundMessage

        blank = Client.objects.create(name="No contact")
        task = services.create_task(client=blank, title="x", created_by=self.ops)
        task.status = TaskStatus.REVIEWED
        task.save()

        ok, delivery, error = services.deliver_to_client(task, self.ops, [], "hi")
        self.assertFalse(ok)
        self.assertEqual(delivery.status, OutboundMessage.Status.FAILED)
        task.refresh_from_db()
        self.assertEqual(task.status, TaskStatus.REVIEWED)

    def test_close_without_sending_still_delivers(self):
        from .models import OutboundMessage

        task = self.make_task()
        task.status = TaskStatus.REVIEWED
        task.save()
        ok, delivery, _ = services.deliver_to_client(task, self.ops, [], "", send=False)
        self.assertTrue(ok)
        self.assertEqual(delivery.status, OutboundMessage.Status.SKIPPED)
        task.refresh_from_db()
        self.assertEqual(task.status, TaskStatus.DELIVERED)

    def test_webhook_signature(self):
        from . import whatsapp as wa

        body = b'{"entry":[]}'
        secret = "s3cret"
        import hashlib
        import hmac
        good = "sha256=" + hmac.new(secret.encode(), body, hashlib.sha256).hexdigest()
        self.assertTrue(wa.verify_signature(secret, body, good))
        self.assertFalse(wa.verify_signature(secret, body, "sha256=deadbeef"))
        self.assertTrue(wa.verify_signature("", body, ""))  # not configured

    def test_deadline_warning_fires_once(self):
        conf = AppSettings.load()
        task = self.make_task()
        services.assign_to_lead(task, self.lead, self.ops)
        task.refresh_from_db()
        task.deadline = timezone.now() + timedelta(minutes=conf.deadline_warning_minutes - 1)
        task.translator = self.tr
        task.save()

        self.assertEqual(services.sweep_deadlines(), 1)
        self.assertEqual(services.sweep_deadlines(), 0)
        self.assertTrue(
            self.tr.notifications.filter(title_en="Deadline approaching").exists()
        )


class PayrollTests(TestCase):
    """The contract, checked against the numbers the owner gave."""

    def setUp(self):
        from datetime import date
        from .models import DayStatus, PayrollSettings, ProductionTier, SalaryRecord, WorkDay

        self.conf = PayrollSettings.load()
        ProductionTier.seed_defaults()
        self.person = User.objects.create_user("omar", password="x", role=Role.TRANSLATOR)
        SalaryRecord.objects.create(
            user=self.person, amount=Decimal("5500.00"), effective_from=date(2026, 1, 1)
        )
        self.DayStatus = DayStatus
        self.WorkDay = WorkDay
        self.date = date

    def build_month(self, year, month, present_days, words, leave=4, secondary=False,
                    unexcused=0):
        """Lay out a month: the leave days first, then the working days."""
        day = 1
        for _ in range(leave):
            self.WorkDay.objects.create(
                user=self.person, date=self.date(year, month, day),
                status=self.DayStatus.LEAVE,
            )
            day += 1
        for _ in range(unexcused):
            self.WorkDay.objects.create(
                user=self.person, date=self.date(year, month, day),
                status=self.DayStatus.UNEXCUSED, absence_reason="no call",
            )
            day += 1
        for _ in range(present_days):
            self.WorkDay.objects.create(
                user=self.person, date=self.date(year, month, day),
                status=self.DayStatus.PRESENT, words=words,
                is_secondary_language=secondary,
            )
            day += 1

    def line_for(self, year, month):
        from . import payroll

        return payroll.compute_line(self.person, year, month)

    # -- the bands ---------------------------------------------------------
    def test_hitting_the_daily_target_exactly_pays_no_bonus(self):
        """3,000 words is the job. The bonus starts above it."""
        from .models import ProductionTier

        self.assertEqual(ProductionTier.bonus_for(3000), Decimal("0.00"))
        self.assertEqual(ProductionTier.bonus_for(3001), Decimal("25"))
        self.assertEqual(ProductionTier.bonus_for(3800), Decimal("25"))
        self.assertEqual(ProductionTier.bonus_for(3801), Decimal("35"))
        self.assertEqual(ProductionTier.bonus_for(4600), Decimal("35"))
        self.assertEqual(ProductionTier.bonus_for(4601), Decimal("45"))
        self.assertEqual(ProductionTier.bonus_for(5900), Decimal("45"))
        self.assertEqual(ProductionTier.bonus_for(5901), Decimal("60"))

    def test_secondary_language_bands_start_at_fifteen_hundred(self):
        from .models import ProductionTier

        self.assertEqual(ProductionTier.bonus_for(1500, secondary=True), Decimal("0.00"))
        self.assertEqual(ProductionTier.bonus_for(1501, secondary=True), Decimal("25"))
        self.assertEqual(ProductionTier.bonus_for(2000, secondary=True), Decimal("25"))
        self.assertEqual(ProductionTier.bonus_for(2001, secondary=True), Decimal("35"))
        self.assertEqual(ProductionTier.bonus_for(5001, secondary=True), Decimal("95"))

    # -- the case the owner described --------------------------------------
    def test_full_month_on_target_pays_six_thousand(self):
        """5,500 salary, the four leave days, 26 days at exactly 3,000 words.

        No daily bonus, because no day beat the target. Both monthly bonuses,
        because the balance was not exceeded and 78,000 was reached.
        """
        self.conf.bonuses_need_approval = False
        self.conf.save()
        self.build_month(2026, 9, present_days=26, words=3000)
        line = self.line_for(2026, 9)

        self.assertEqual(line.total_words, 78000)
        self.assertEqual(line.production_bonus, Decimal("0.00"))
        self.assertEqual(line.discipline_bonus, Decimal("250.00"))
        self.assertEqual(line.target_bonus, Decimal("250.00"))
        self.assertEqual(line.deductions, Decimal("0.00"))
        self.assertEqual(line.net, Decimal("6000.00"))

    def test_same_month_above_target_adds_the_daily_bonus(self):
        """3,200 a day puts every day in the first band: 26 x 25 = 650."""
        self.conf.bonuses_need_approval = False
        self.conf.save()
        self.build_month(2026, 9, present_days=26, words=3200)
        line = self.line_for(2026, 9)

        self.assertEqual(line.production_bonus, Decimal("650.00"))
        self.assertEqual(line.net, Decimal("6650.00"))

    def test_bonuses_wait_for_approval_by_default(self):
        self.build_month(2026, 9, present_days=26, words=3000)
        line = self.line_for(2026, 9)

        self.assertTrue(line.discipline_bonus_earned)
        self.assertTrue(line.target_bonus_earned)
        self.assertEqual(line.discipline_bonus, Decimal("0.00"))
        self.assertEqual(line.net, Decimal("5500.00"))

    def test_releasing_the_bonuses_moves_the_net(self):
        from . import payroll

        self.build_month(2026, 9, present_days=26, words=3000)
        period = payroll.compute_period(2026, 9, users=[self.person])
        line = period.lines.get(user=self.person)
        self.assertEqual(line.net, Decimal("5500.00"))

        payroll.approve_bonuses(line, self.ops if hasattr(self, "ops") else None)
        line.refresh_from_db()
        self.assertEqual(line.net, Decimal("6000.00"))

    # -- leave and absence --------------------------------------------------
    def test_a_fifth_leave_day_is_a_pending_deduction_not_an_applied_one(self):
        from .models import ApprovalStatus, Violation

        self.conf.bonuses_need_approval = False
        self.conf.save()
        self.build_month(2026, 9, present_days=25, words=3000, leave=5)
        line = self.line_for(2026, 9)

        self.assertEqual(line.extra_leave_days, 1)
        self.assertEqual(line.deductions, Decimal("0.00"))
        self.assertFalse(line.discipline_bonus_earned)
        draft = Violation.objects.get(user=self.person, auto_key__startswith="extra_leave")
        self.assertEqual(draft.status, ApprovalStatus.PENDING)
        self.assertEqual(draft.penalty_days, Decimal("1.25"))

    def test_an_approved_deduction_is_priced_in_days_of_pay(self):
        from .models import Violation

        self.build_month(2026, 9, present_days=25, words=3000, leave=5)
        self.line_for(2026, 9)
        draft = Violation.objects.get(user=self.person, auto_key__startswith="extra_leave")
        draft.approve(self.person)

        line = self.line_for(2026, 9)
        # 5500 / 26 = 211.54 a day; 1.25 days = 264.43
        self.assertEqual(line.day_value, Decimal("211.54"))
        self.assertEqual(line.deductions, Decimal("264.43"))

    def test_the_third_absence_without_permission_escalates(self):
        from .models import Violation

        self.build_month(2026, 9, present_days=20, words=3000, unexcused=3)
        self.line_for(2026, 9)
        rows = Violation.objects.filter(
            user=self.person, auto_key__startswith="unexcused"
        ).order_by("date")
        self.assertEqual(rows.count(), 3)
        self.assertFalse(rows[0].escalated)
        self.assertTrue(rows[2].escalated)

    def test_recomputing_does_not_pile_up_duplicate_drafts(self):
        from .models import Violation

        self.build_month(2026, 9, present_days=25, words=3000, leave=5)
        for _ in range(3):
            self.line_for(2026, 9)
        self.assertEqual(
            Violation.objects.filter(user=self.person, auto_key__startswith="extra_leave").count(),
            1,
        )

    # -- production comes from the jobs -------------------------------------
    def test_word_count_is_read_from_the_tasks(self):
        from . import payroll

        client_obj = Client.objects.create(name="ACME", phone="+201111111111")
        task = Task.objects.create(
            client=client_obj, title="Doc", translator=self.person,
            status=TaskStatus.DELIVERED, word_count=4200,
            translated_at=timezone.make_aware(
                timezone.datetime(2026, 9, 10, 14, 0)
            ),
        )
        payroll.refresh_words(self.person, self.date(2026, 9, 1), self.date(2026, 9, 30))
        day = self.WorkDay.objects.get(user=self.person, date=self.date(2026, 9, 10))
        self.assertEqual(day.words, 4200)
        self.assertEqual(day.bonus(), Decimal("35"))
        self.assertEqual(task.production_date, self.date(2026, 9, 10))

    def test_a_difficult_file_is_exempt_from_the_daily_floor(self):
        self.build_month(2026, 9, present_days=1, words=1200)
        day = self.WorkDay.objects.filter(user=self.person).order_by("-date").first()
        self.assertTrue(day.is_under_target())
        day.difficult_file = True
        day.save()
        self.assertFalse(day.is_under_target())

    # -- history ------------------------------------------------------------
    def test_an_old_month_keeps_the_salary_it_was_paid_on(self):
        from .models import SalaryRecord

        SalaryRecord.objects.create(
            user=self.person, amount=Decimal("7000.00"),
            effective_from=self.date(2026, 10, 1),
        )
        self.build_month(2026, 9, present_days=26, words=3000)
        self.assertEqual(self.line_for(2026, 9).base_salary, Decimal("5500.00"))
        self.assertEqual(
            SalaryRecord.amount_on(self.person, self.date(2026, 10, 15)),
            Decimal("7000.00"),
        )

    def test_a_locked_month_is_not_recomputed(self):
        from . import payroll
        from .models import PeriodStatus

        self.build_month(2026, 9, present_days=26, words=3000)
        period = payroll.compute_period(2026, 9, users=[self.person])
        before = period.lines.get(user=self.person).net

        period.status = PeriodStatus.LOCKED
        period.save(update_fields=["status"])
        self.WorkDay.objects.filter(user=self.person).update(words=6000)
        payroll.compute_period(2026, 9, users=[self.person])

        self.assertEqual(period.lines.get(user=self.person).net, before)


class WordCountTests(TestCase):
    """Reading a job's size out of the file instead of trusting a typed number."""

    def make_docx(self, paragraphs):
        """A minimal but real .docx, built without any third-party package."""
        import io
        import zipfile

        body = "".join(
            "<w:p>" + "".join(f"<w:r><w:t>{run}</w:t></w:r>" for run in runs) + "</w:p>"
            for runs in paragraphs
        )
        document = (
            '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
            '<w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main">'
            f"<w:body>{body}</w:body></w:document>"
        )
        buffer = io.BytesIO()
        with zipfile.ZipFile(buffer, "w") as archive:
            archive.writestr("[Content_Types].xml", "<Types/>")
            archive.writestr("word/document.xml", document)
        return buffer.getvalue()

    def test_a_word_split_across_runs_is_still_one_word(self):
        """Word stores 'Hello' as two runs whenever formatting changes mid-word.

        Stripping tags to a space would make that two words and quietly inflate
        every translator's production.
        """
        from . import wordcount

        raw = self.make_docx([["Hel", "lo"], ["world"]])
        method, words = wordcount.count_bytes(raw, "a.docx")
        self.assertEqual(method, "docx")
        self.assertEqual(words, 2)

    def test_paragraphs_do_not_run_together(self):
        from . import wordcount

        raw = self.make_docx([["alpha"], ["beta"]])
        self.assertEqual(wordcount.count_bytes(raw, "a.docx")[1], 2)

    def test_arabic_counts_the_same_way(self):
        from . import wordcount

        raw = self.make_docx([["قواعد حساب"], ["مستحقات المترجمين"]])
        self.assertEqual(wordcount.count_bytes(raw, "a.docx")[1], 4)

    def test_a_number_with_a_comma_is_one_word(self):
        """Word counts "3,200" once. Counting it twice would inflate every
        document full of figures by several percent - enough to move a day
        across a bonus band."""
        from . import wordcount

        self.assertEqual(wordcount.count_text("3,200 كلمة"), 2)
        self.assertEqual(wordcount.count_text("3200 كلمة"), 2)
        self.assertEqual(wordcount.count_text("1.25 يوم"), 2)
        self.assertEqual(wordcount.count_text("state-of-the-art"), 1)
        self.assertEqual(wordcount.count_text("don't stop"), 2)

    def test_a_comma_between_two_words_still_separates_them(self):
        from . import wordcount

        self.assertEqual(wordcount.count_text("apples, oranges"), 2)
        self.assertEqual(wordcount.count_text("الأول، التاني"), 2)

    def test_plain_text_is_read(self):
        from . import wordcount

        method, words = wordcount.count_bytes("one two three".encode(), "a.txt")
        self.assertEqual((method, words), ("text", 3))

    def test_pdf_is_reported_unsupported_rather_than_guessed(self):
        """A half-read PDF returns a number that looks right and is not."""
        from . import wordcount

        method, words = wordcount.count_bytes(b"%PDF-1.7 ...", "scan.pdf")
        self.assertEqual(method, "unsupported")
        self.assertEqual(words, 0)

    def test_a_corrupt_file_does_not_raise(self):
        from . import wordcount

        method, words = wordcount.count_bytes(b"not a zip at all", "a.docx")
        self.assertEqual(method, "error")
        self.assertEqual(words, 0)


class TaskWordCountTests(TestCase):
    """Where the counted number is allowed to go on its own."""

    def setUp(self):
        from django.core.files.base import ContentFile

        from .models import ChatAttachment, ChatMessage, MessageAttachment, RoomKind

        self.ops = User.objects.create_user("ops2", password="x", role=Role.OPERATION)
        self.lead = User.objects.create_user("lead2", password="x", role=Role.TEAM_LEAD)
        self.tr = User.objects.create_user(
            "tr2", password="x", role=Role.TRANSLATOR, team_lead=self.lead
        )
        self.client_obj = Client.objects.create(name="ACME", phone="+201222222222")
        self.task = services.create_task(
            client=self.client_obj, title="Doc", created_by=self.ops,
        )
        self.task.translator = self.tr
        self.task.team_lead = self.lead
        self.task.save()
        self.ContentFile = ContentFile
        self.MessageAttachment = MessageAttachment
        self.ChatAttachment = ChatAttachment
        self.ChatMessage = ChatMessage
        self.RoomKind = RoomKind

    def text_file(self, words):
        return self.ContentFile(" ".join(["كلمة"] * words).encode(), name="f.txt")

    def add_source(self, words):
        message = services.ingest_message(
            channel="whatsapp", body="here", sender_identity=self.client_obj.phone,
        )
        message.task = self.task
        message.save(update_fields=["task"])
        self.MessageAttachment.objects.create(
            message=message, file=self.text_file(words),
            original_name="source.txt", size=words * 3,
        )

    def add_translation(self, words, sender=None):
        room = services.ensure_room(self.task, self.RoomKind.GROUP)
        message = self.ChatMessage.objects.create(room=room, sender=sender or self.tr)
        self.ChatAttachment.objects.create(
            message=message, file=self.text_file(words),
            original_name="done.txt", size=words * 3,
        )

    def test_a_matching_pair_is_applied_without_asking(self):
        from . import wordcount
        from .models import WordCountState

        self.add_source(1000)
        self.add_translation(1100)
        wordcount.recount_task(self.task)

        self.assertEqual(self.task.source_words, 1000)
        self.assertEqual(self.task.translated_words, 1100)
        # Payroll follows the client's file, not the translator's upload.
        self.assertEqual(self.task.word_count, 1000)
        self.assertEqual(self.task.word_count_state, WordCountState.AUTO)
        self.assertTrue(self.task.word_count_is_settled)

    def test_a_wide_gap_is_held_for_a_person(self):
        from . import wordcount
        from .models import WordCountState

        self.add_source(1000)
        self.add_translation(3000)
        wordcount.recount_task(self.task)

        self.assertEqual(self.task.word_count_state, WordCountState.REVIEW)
        self.assertFalse(self.task.word_count_is_settled)
        # The suspect number never reached the field payroll reads.
        self.assertEqual(self.task.word_count, 0)
        self.assertIn("200%", self.task.word_count_note)

    def test_one_readable_side_is_used_but_still_flagged(self):
        from . import wordcount
        from .models import WordCountState

        self.add_source(900)
        wordcount.recount_task(self.task)

        self.assertEqual(self.task.word_count, 900)
        self.assertEqual(self.task.word_count_state, WordCountState.REVIEW)

    def test_nothing_readable_asks_for_a_number(self):
        from . import wordcount
        from .models import WordCountState

        wordcount.recount_task(self.task)
        self.assertEqual(self.task.word_count_state, WordCountState.MANUAL_NEEDED)
        self.assertEqual(self.task.word_count, 0)

    def test_confirming_by_hand_settles_it(self):
        from . import wordcount
        from .models import WordCountState

        self.add_source(1000)
        self.add_translation(3000)
        wordcount.recount_task(self.task)
        wordcount.confirm_task(self.task, self.lead, words=2500)

        self.assertEqual(self.task.word_count, 2500)
        self.assertEqual(self.task.word_count_state, WordCountState.CONFIRMED)
        self.assertTrue(self.task.word_count_is_settled)

    def test_the_tolerance_is_a_setting_not_a_constant(self):
        from . import wordcount
        from .models import PayrollSettings, WordCountState

        conf = PayrollSettings.load()
        conf.word_count_gap_percent = 300
        conf.save()

        self.add_source(1000)
        self.add_translation(3000)
        wordcount.recount_task(self.task)
        self.assertEqual(self.task.word_count_state, WordCountState.AUTO)

    def test_finishing_the_translation_counts_the_files(self):
        self.add_source(1200)
        self.add_translation(1300)
        services.mark_translated(self.task, self.tr)
        self.task.refresh_from_db()
        self.assertEqual(self.task.word_count, 1200)

    def test_the_translator_cannot_settle_their_own_count(self):
        self.add_source(1000)
        self.add_translation(3000)
        self.client.force_login(self.tr)
        response = self.client.post(
            f"/tasks/{self.task.code}/words/", {"action": "translated"}
        )
        self.assertEqual(response.status_code, 404)
