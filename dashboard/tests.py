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
from .permissions import user_may_open


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
        # The client room is the operation's and the leader's. A translator
        # never talks to a client, not even after accepting.
        self.assertNotIn(self.tr, client_room.members.all())
        self.assertIn(self.lead, client_room.members.all())

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
        # Reviewed is not permission to send - somebody has to have the job.
        task.handover_ack_at = timezone.now()
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
        # Reviewed is not permission to send - somebody has to have the job.
        task.handover_ack_at = timezone.now()
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
        # Reviewed is not permission to send - somebody has to have the job.
        task.handover_ack_at = timezone.now()
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
        # Reviewed is not permission to send - somebody has to have the job.
        task.handover_ack_at = timezone.now()
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


# ---------------------------------------------------------------------------
# Attendance
# ---------------------------------------------------------------------------

class AttendanceMathTests(TestCase):
    """The rules that a wrong sign or a stray ``+ 1`` would quietly break."""

    def test_overnight_shift_is_eight_hours_not_minus_sixteen(self):
        from datetime import time
        from .models import span_minutes

        self.assertEqual(span_minutes(time(9, 0), time(17, 0)), 480)
        self.assertEqual(span_minutes(time(17, 0), time(1, 0)), 480)
        self.assertEqual(span_minutes(time(22, 0), time(6, 0)), 480)
        self.assertEqual(span_minutes(time(10, 0), time(14, 0)), 240)

    def test_grace_is_all_or_nothing(self):
        """The contract's own example: 09:06 present, 09:14 late by 14."""
        from datetime import datetime

        from .attendance import late_after_grace

        start = datetime(2026, 9, 20, 9, 0)
        self.assertEqual(late_after_grace(start, datetime(2026, 9, 20, 9, 6), 10), 0)
        self.assertEqual(late_after_grace(start, datetime(2026, 9, 20, 9, 10), 10), 0)
        # Not 4. Once the window is passed the whole delay counts.
        self.assertEqual(late_after_grace(start, datetime(2026, 9, 20, 9, 14), 10), 14)
        self.assertEqual(late_after_grace(start, datetime(2026, 9, 20, 8, 55), 10), 0)

    def test_distance_is_metres_not_degrees(self):
        from .attendance import haversine_m

        # A tenth of a degree of latitude is a shade over 11 km.
        self.assertAlmostEqual(
            haversine_m(30.0444, 31.2357, 30.1444, 31.2357), 11119, delta=40
        )
        self.assertEqual(haversine_m(30.0444, 31.2357, 30.0444, 31.2357), 0)


class AttendanceTests(TestCase):
    def setUp(self):
        from datetime import time

        from .models import OfficeLocation, PayrollSettings, ShiftTemplate, WorkMode

        self.conf = PayrollSettings.load()
        ShiftTemplate.seed_defaults()
        self.morning = ShiftTemplate.objects.get(name="Shift 1")      # 09:00-17:00
        self.night = ShiftTemplate.objects.get(name="Shift 3")        # 17:00-01:00
        self.time = time
        self.WorkMode = WorkMode

        self.person = User.objects.create_user(
            "noha", password="x", role=Role.TRANSLATOR, work_mode=WorkMode.REMOTE
        )
        self.hr = User.objects.create_user(
            "hr", password="x", role=Role.OPERATION, attendance_manager=True
        )
        self.office = OfficeLocation.objects.create(
            name="Head office", latitude=Decimal("30.044400"),
            longitude=Decimal("31.235700"), radius_meters=200,
        )

    # -- helpers -----------------------------------------------------------
    def roster(self, person, weekday, template, mode=""):
        from .models import Shift

        return Shift.objects.create(
            user=person, weekday=weekday, template=template, work_mode=mode
        )

    def at(self, year, month, day, hour, minute=0):
        from datetime import datetime

        return timezone.make_aware(datetime(year, month, day, hour, minute))

    # -- the punch ---------------------------------------------------------
    def test_a_remote_day_is_never_asked_for_a_location(self):
        """Section 14 as a test: no office day, no location check, no flag."""
        from . import attendance
        from .models import PunchKind

        # 2026-09-21 is a Monday.
        self.roster(self.person, 0, self.morning)
        row, event = attendance.punch(
            self.person, PunchKind.CHECK_IN, at=self.at(2026, 9, 21, 9, 3)
        )
        self.assertIsNone(event.within_geofence)
        self.assertFalse(row.off_site)
        self.assertFalse(row.needs_review)
        self.assertEqual(row.work_mode, "remote")

    def test_an_office_punch_from_far_away_is_flagged_not_lost(self):
        from . import attendance
        from .models import PunchKind

        self.roster(self.person, 0, self.morning, mode=self.WorkMode.OFFICE)
        row, event = attendance.punch(
            self.person, PunchKind.CHECK_IN, at=self.at(2026, 9, 21, 9, 3),
            latitude=Decimal("30.100000"), longitude=Decimal("31.235700"),
        )
        self.assertFalse(event.within_geofence)
        self.assertTrue(row.off_site)
        self.assertTrue(row.needs_review)
        # The person still arrived at work - the day is recorded.
        self.assertIsNotNone(row.check_in)

    def test_reject_policy_refuses_the_off_site_punch(self):
        from . import attendance
        from .models import OffSitePolicy, PunchKind, WorkDay

        self.conf.off_site_policy = OffSitePolicy.REJECT
        self.conf.save()
        self.roster(self.person, 0, self.morning, mode=self.WorkMode.OFFICE)
        with self.assertRaises(attendance.PunchRefused):
            attendance.punch(
                self.person, PunchKind.CHECK_IN, at=self.at(2026, 9, 21, 9, 3),
                latitude=Decimal("30.100000"), longitude=Decimal("31.235700"),
            )
        self.assertFalse(
            WorkDay.objects.filter(user=self.person).exclude(check_in=None).exists()
        )

    def test_gps_error_is_added_to_the_radius(self):
        """A 250 m reading with a 100 m error bar is not proof of absence."""
        from . import attendance
        from .models import PunchKind

        self.roster(self.person, 0, self.morning, mode=self.WorkMode.OFFICE)
        row, event = attendance.punch(
            self.person, PunchKind.CHECK_IN, at=self.at(2026, 9, 21, 9, 3),
            latitude=Decimal("30.046650"), longitude=Decimal("31.235700"),
            accuracy_m=120,
        )
        self.assertGreater(event.distance_m, 200)
        self.assertTrue(event.within_geofence)
        self.assertFalse(row.off_site)

    # -- the overnight shift ----------------------------------------------
    def test_a_checkout_after_midnight_belongs_to_the_shift_that_started(self):
        from . import attendance
        from .models import PunchKind

        # Monday 17:00 -> Tuesday 01:00.
        self.roster(self.person, 0, self.night)
        opened, _ = attendance.punch(
            self.person, PunchKind.CHECK_IN, at=self.at(2026, 9, 21, 17, 2)
        )
        closed, _ = attendance.punch(
            self.person, PunchKind.CHECK_OUT, at=self.at(2026, 9, 22, 0, 55)
        )
        # Same row - the day is Monday's, even though the clock says Tuesday.
        self.assertEqual(opened.pk, closed.pk)
        self.assertEqual(closed.date.day, 21)
        self.assertEqual(closed.work_minutes, 473)
        self.assertEqual(closed.late_minutes, 0)
        self.assertEqual(closed.short_minutes, 7)

    # -- breaks ------------------------------------------------------------
    def test_hours_are_out_minus_in_minus_break(self):
        from . import attendance
        from .models import PunchKind

        self.roster(self.person, 0, self.morning)
        attendance.punch(self.person, PunchKind.CHECK_IN, at=self.at(2026, 9, 21, 9, 0))
        attendance.punch(self.person, PunchKind.BREAK_START, at=self.at(2026, 9, 21, 13, 0))
        attendance.punch(self.person, PunchKind.BREAK_END, at=self.at(2026, 9, 21, 13, 30))
        row, _ = attendance.punch(
            self.person, PunchKind.CHECK_OUT, at=self.at(2026, 9, 21, 17, 0)
        )
        self.assertEqual(row.break_minutes, 30)
        self.assertEqual(row.work_minutes, 450)   # 480 - 30
        self.assertEqual(row.short_minutes, 30)

    def test_a_day_cannot_be_closed_with_a_break_still_running(self):
        from . import attendance
        from .models import PunchKind

        self.roster(self.person, 0, self.morning)
        attendance.punch(self.person, PunchKind.CHECK_IN, at=self.at(2026, 9, 21, 9, 0))
        attendance.punch(self.person, PunchKind.BREAK_START, at=self.at(2026, 9, 21, 13, 0))
        with self.assertRaises(attendance.PunchRefused):
            attendance.punch(
                self.person, PunchKind.CHECK_OUT, at=self.at(2026, 9, 21, 17, 0)
            )

    def test_you_cannot_check_in_twice(self):
        from . import attendance
        from .models import PunchKind

        self.roster(self.person, 0, self.morning)
        attendance.punch(self.person, PunchKind.CHECK_IN, at=self.at(2026, 9, 21, 9, 0))
        with self.assertRaises(attendance.PunchRefused):
            attendance.punch(
                self.person, PunchKind.CHECK_IN, at=self.at(2026, 9, 21, 9, 30)
            )

    # -- part-time ---------------------------------------------------------
    def test_a_part_timer_is_measured_against_their_own_hours(self):
        """Four scheduled hours worked in full is a complete day, not half of one."""
        from . import attendance
        from .models import EmploymentType, PunchKind, Shift

        person = User.objects.create_user(
            "sara", password="x", role=Role.TRANSLATOR,
            employment_type=EmploymentType.PART_TIME,
        )
        Shift.objects.create(
            user=person, weekday=0, start_time=self.time(10, 0), end_time=self.time(14, 0)
        )
        attendance.punch(person, PunchKind.CHECK_IN, at=self.at(2026, 9, 21, 10, 0))
        row, _ = attendance.punch(
            person, PunchKind.CHECK_OUT, at=self.at(2026, 9, 21, 14, 0)
        )
        self.assertEqual(row.scheduled_minutes, 240)
        self.assertEqual(row.work_minutes, 240)
        self.assertEqual(row.short_minutes, 0)
        self.assertEqual(row.overtime_minutes, 0)

    # -- the frozen schedule ----------------------------------------------
    def test_moving_the_roster_does_not_rewrite_a_recorded_day(self):
        from . import attendance
        from .models import PunchKind, WorkDay

        shift = self.roster(self.person, 0, self.morning)
        row, _ = attendance.punch(
            self.person, PunchKind.CHECK_IN, at=self.at(2026, 9, 21, 9, 30)
        )
        self.assertEqual(row.late_minutes, 30)

        # HR moves this person to the night shift from now on.
        shift.template = self.night
        shift.save()

        # The recorded day keeps the shift it was worked under.
        again = WorkDay.objects.get(pk=row.pk)
        attendance.recompute(again)
        self.assertEqual(again.late_minutes, 30)
        self.assertEqual(again.schedule_label, self.morning.label)

    # -- corrections -------------------------------------------------------
    def test_an_edit_without_a_reason_is_refused(self):
        from . import attendance
        from .models import PunchKind

        self.roster(self.person, 0, self.morning)
        row, _ = attendance.punch(
            self.person, PunchKind.CHECK_IN, at=self.at(2026, 9, 21, 9, 40)
        )
        with self.assertRaises(attendance.PunchRefused):
            attendance.apply_edit(
                row, self.hr, {"check_in": self.at(2026, 9, 21, 9, 0)}, ""
            )

    def test_an_edit_writes_the_trail_and_recomputes(self):
        from . import attendance
        from .models import AttendanceEdit, PunchKind

        self.roster(self.person, 0, self.morning)
        row, _ = attendance.punch(
            self.person, PunchKind.CHECK_IN, at=self.at(2026, 9, 21, 9, 40)
        )
        self.assertEqual(row.late_minutes, 40)

        attendance.apply_edit(
            row, self.hr, {"check_in": self.at(2026, 9, 21, 9, 0)},
            "بصمة الباب بتقول 09:00",
        )
        row.refresh_from_db()
        self.assertEqual(row.late_minutes, 0)
        trail = AttendanceEdit.objects.get(work_day=row, field="check_in")
        self.assertEqual(trail.actor, self.hr)
        self.assertIn("09:40", trail.old_value)
        self.assertIn("09:00", trail.new_value)
        # The punch itself is untouched - the evidence survives the correction.
        self.assertEqual(
            timezone.localtime(row.events.first().at).strftime("%H:%M"), "09:40"
        )

    # -- devices -----------------------------------------------------------
    def test_the_first_browser_is_trusted_and_the_second_waits(self):
        from . import attendance
        from .models import ApprovalStatus, AuthorizedDevice, PunchKind

        self.roster(self.person, 0, self.morning)
        attendance.punch(
            self.person, PunchKind.CHECK_IN, at=self.at(2026, 9, 21, 9, 0),
            fingerprint="aaaa1111",
        )
        first = AuthorizedDevice.objects.get(user=self.person, fingerprint="aaaa1111")
        self.assertEqual(first.status, ApprovalStatus.APPROVED)

        self.roster(self.person, 1, self.morning)
        row, _ = attendance.punch(
            self.person, PunchKind.CHECK_IN, at=self.at(2026, 9, 22, 9, 0),
            fingerprint="bbbb2222",
        )
        second = AuthorizedDevice.objects.get(user=self.person, fingerprint="bbbb2222")
        self.assertEqual(second.status, ApprovalStatus.PENDING)
        self.assertTrue(row.needs_review)

    # -- overtime ----------------------------------------------------------
    def test_overtime_becomes_a_claim_and_pays_only_once_approved(self):
        from datetime import date

        from . import attendance, payroll
        from .models import OvertimeClaim, PunchKind, SalaryRecord

        SalaryRecord.objects.create(
            user=self.person, amount=Decimal("5200.00"), effective_from=date(2026, 1, 1)
        )
        self.roster(self.person, 0, self.morning)
        attendance.punch(self.person, PunchKind.CHECK_IN, at=self.at(2026, 9, 21, 9, 0))
        row, _ = attendance.punch(
            self.person, PunchKind.CHECK_OUT, at=self.at(2026, 9, 21, 19, 0)
        )
        self.assertEqual(row.overtime_minutes, 120)

        line = payroll.compute_line(self.person, 2026, 9)
        claim = OvertimeClaim.objects.get(user=self.person, date=row.date)
        self.assertEqual(claim.status, "pending")
        self.assertEqual(line.overtime_bonus, Decimal("0.00"))
        self.assertEqual(line.overtime_minutes, 120)

        claim.approve(self.hr)
        line = payroll.compute_line(self.person, 2026, 9)
        # 5200 / 26 = 200 a day, / 8 hours = 25 an hour, two hours = 50.
        self.assertEqual(line.overtime_bonus, Decimal("50.00"))
        self.assertEqual(line.gross, line.base_salary + Decimal("50.00"))

    def test_recomputing_does_not_resurrect_a_rejected_claim(self):
        from datetime import date

        from . import attendance, payroll
        from .models import OvertimeClaim, PunchKind, SalaryRecord

        SalaryRecord.objects.create(
            user=self.person, amount=Decimal("5200.00"), effective_from=date(2026, 1, 1)
        )
        self.roster(self.person, 0, self.morning)
        attendance.punch(self.person, PunchKind.CHECK_IN, at=self.at(2026, 9, 21, 9, 0))
        attendance.punch(self.person, PunchKind.CHECK_OUT, at=self.at(2026, 9, 21, 19, 0))

        payroll.compute_line(self.person, 2026, 9)
        OvertimeClaim.objects.filter(user=self.person).first().reject(self.hr)
        payroll.compute_line(self.person, 2026, 9)
        self.assertEqual(
            OvertimeClaim.objects.get(user=self.person).status, "rejected"
        )

    # -- the report --------------------------------------------------------
    def test_the_month_counts_office_and_remote_days_apart(self):
        from datetime import date

        from . import attendance
        from .models import PunchKind, WorkMode

        self.person.work_mode = WorkMode.HYBRID
        self.person.save()
        self.roster(self.person, 0, self.morning, mode=WorkMode.OFFICE)   # Monday
        self.roster(self.person, 1, self.morning, mode=WorkMode.REMOTE)   # Tuesday

        attendance.punch(
            self.person, PunchKind.CHECK_IN, at=self.at(2026, 9, 21, 9, 0),
            latitude=Decimal("30.044400"), longitude=Decimal("31.235700"),
        )
        attendance.punch(self.person, PunchKind.CHECK_OUT, at=self.at(2026, 9, 21, 17, 0))
        attendance.punch(self.person, PunchKind.CHECK_IN, at=self.at(2026, 9, 22, 9, 0))
        attendance.punch(self.person, PunchKind.CHECK_OUT, at=self.at(2026, 9, 22, 17, 0))

        summary = attendance.month_summary(
            self.person, date(2026, 9, 1), date(2026, 9, 30)
        )
        self.assertEqual(summary["office_days"], 1)
        self.assertEqual(summary["remote_days"], 1)
        self.assertEqual(summary["present_days"], 2)
        self.assertEqual(summary["work_minutes"], 960)


class AttendancePageTests(TestCase):
    """The screens exist, and only the right people reach them."""

    def setUp(self):
        self.person = User.objects.create_user("kareem", password="x", role=Role.TRANSLATOR)
        self.hr = User.objects.create_user(
            "hrm", password="x", role=Role.OPERATION, attendance_manager=True
        )

    def test_everybody_gets_their_own_card(self):
        self.client.force_login(self.person)
        self.assertEqual(self.client.get("/attendance/").status_code, 200)

    def test_a_translator_cannot_open_the_board(self):
        self.client.force_login(self.person)
        self.assertEqual(self.client.get("/hr/attendance/").status_code, 403)

    def test_the_hr_flag_opens_the_board_without_being_an_admin(self):
        self.client.force_login(self.hr)
        for path in (
            "/hr/attendance/", "/hr/schedules/", "/hr/report/",
            "/hr/offices/", "/hr/devices/", "/hr/overtime/",
        ):
            self.assertEqual(self.client.get(path).status_code, 200, path)

    def test_a_punch_with_no_roster_still_answers(self):
        from .models import WorkDay

        self.client.force_login(self.person)
        response = self.client.post("/api/attendance/punch/", {"action": "check_in"})
        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.json()["ok"])
        self.assertTrue(WorkDay.objects.filter(user=self.person).exists())

    def test_a_bad_action_is_rejected(self):
        self.client.force_login(self.person)
        response = self.client.post("/api/attendance/punch/", {"action": "teleport"})
        self.assertEqual(response.status_code, 400)


# ---------------------------------------------------------------------------
# HR / recruitment
# ---------------------------------------------------------------------------

class RecruitmentPrivacyTests(TestCase):
    """Section 3 as code: the candidate does not learn who we are."""

    def setUp(self):
        from .models import Candidate, RecruitmentSettings

        self.conf = RecruitmentSettings.load()
        self.conf.redact_terms = "EagleLingua\nالنسر للتوريدات العامه\neagel-operation.com"
        self.conf.save()
        self.candidate = Candidate.objects.create(full_name="مرشح", phone="201000000001")

    def test_the_company_name_is_stripped_while_anonymous(self):
        from . import recruitment

        out = recruitment.outbound_text(
            self.candidate, "أهلًا بيك في EagleLingua، شوف eagel-operation.com",
            conf=self.conf,
        )
        self.assertNotIn("EagleLingua", out)
        self.assertNotIn("eagel-operation.com", out)
        self.assertIn("أهلًا بيك", out)

    def test_matching_ignores_case_and_spacing(self):
        """"Eagle  Lingua" across a line break is the same leak."""
        from . import recruitment

        out = recruitment.outbound_text(
            self.candidate, "welcome to eagle   lingua today", conf=self.conf
        )
        self.assertNotIn("lingua", out.lower())

    def test_revealing_lets_the_name_through_and_is_logged(self):
        from . import recruitment
        from .models import AuditLog

        hr = User.objects.create_user("hr1", password="x", role=Role.HR)
        recruitment.reveal_identity(self.candidate, hr, "اتقبل للمقابلة")
        self.candidate.refresh_from_db()

        self.assertTrue(self.candidate.identity_revealed)
        self.assertEqual(self.candidate.identity_revealed_by, hr)
        out = recruitment.outbound_text(self.candidate, "EagleLingua", conf=self.conf)
        self.assertEqual(out, "EagleLingua")
        self.assertTrue(
            AuditLog.objects.filter(action="recruitment.identity.reveal").exists()
        )

    def test_an_unknown_contact_is_still_scrubbed(self):
        """No candidate row yet is not a reason to leak the name."""
        from . import recruitment

        out = recruitment.outbound_text(None, "من EagleLingua", conf=self.conf)
        self.assertNotIn("EagleLingua", out)

    def test_a_name_split_across_a_line_is_still_caught(self):
        """The term is stored as one word; the leak arrives as two."""
        from . import recruitment

        out = recruitment.outbound_text(
            self.candidate, "welcome to Eagle\nLingua", conf=self.conf
        )
        self.assertNotIn("Lingua", out)

    def test_ordinary_words_survive(self):
        """A filter that eats normal sentences would just be switched off."""
        from . import recruitment

        for kept in ("نتشرف بترشيحك للوظيفة", "a sentence about eagles and lingo"):
            self.assertEqual(
                recruitment.outbound_text(self.candidate, kept, conf=self.conf), kept
            )

    def test_the_rule_is_armed_out_of_the_box(self):
        """Section 3 is a system rule, so it cannot wait to be switched on."""
        from .models import RecruitmentSettings

        RecruitmentSettings.objects.all().delete()
        conf = RecruitmentSettings.load()
        self.assertTrue(conf.term_list)


class RecruitmentBotTests(TestCase):
    """The bot collects and hands over. It never decides (section 28)."""

    def setUp(self):
        from datetime import time
        from unittest import mock

        from .models import (
            AnswerTarget, Department, QuestionKind, RecruitmentQuestion,
            RecruitmentSettings, ShiftTemplate, Vacancy, VacancyQuestion,
            VacancyStatus,
        )

        self.conf = RecruitmentSettings.load()
        ShiftTemplate.seed_defaults()
        Department.seed_defaults()
        self.department = Department.objects.get(name="Translation")
        self.shift = ShiftTemplate.objects.get(name="Shift 2")   # 12:00-20:00

        self.vacancy = Vacancy.objects.create(
            title="Arabic Translator", department=self.department,
            status=VacancyStatus.OPEN, job_description="ترجمة عربي-إنجليزي",
        )
        self.vacancy.shifts.add(self.shift)

        self.name_q = RecruitmentQuestion.objects.create(
            text="اسمك إيه؟", kind=QuestionKind.TEXT, maps_to=AnswerTarget.FULL_NAME,
        )
        self.tools_q = RecruitmentQuestion.objects.create(
            text="بتستخدم أنهي CAT tools؟", kind=QuestionKind.MULTI,
            options=["Trados", "memoQ", "Phrase"], department=self.department,
        )
        self.salary_q = RecruitmentQuestion.objects.create(
            text="الراتب المتوقع؟", kind=QuestionKind.TEXT,
            maps_to=AnswerTarget.EXPECTED_SALARY,
        )
        for order, question in enumerate(
            (self.name_q, self.tools_q, self.salary_q), start=1
        ):
            VacancyQuestion.objects.create(
                vacancy=self.vacancy, question=question, order=order
            )

        self.hr = User.objects.create_user("hr2", password="x", role=Role.HR)
        self.owner = User.objects.create_user("owner", password="x", role=Role.ADMIN)
        self.contact = "201111111111"
        self.mock = mock
        # Nothing in these tests should reach Meta.
        self.patcher = mock.patch("dashboard.whatsapp.send_text", return_value="wamid.x")
        self.sent = self.patcher.start()
        self.addCleanup(self.patcher.stop)

    def say(self, text="", attachments=None):
        from . import recruitment

        return recruitment.handle_inbound(
            contact=self.contact, body=text, display_name="نهى",
            attachments=attachments or [],
        )

    def replies(self):
        return [call.args[1] for call in self.sent.call_args_list]

    # -- the walk-through ---------------------------------------------------
    def test_a_full_application_lands_in_hr_screening(self):
        from .models import Candidate, CandidateStatus, SessionState

        self.say("السلام عليكم")          # greeting, then straight in (one vacancy)
        self.say("نعم")                    # the shift question
        self.say("نهى محمد")               # name
        self.say("1,3")                    # CAT tools, by number
        session = self.say("6000")         # expected salary -> finishes

        candidate = Candidate.objects.get(phone=self.contact)
        self.assertEqual(session.state, SessionState.DONE)
        # The furthest the bot may ever move somebody.
        self.assertEqual(candidate.status, CandidateStatus.SCREENING)
        self.assertEqual(candidate.full_name, "نهى محمد")
        self.assertEqual(candidate.expected_salary, "6000")
        self.assertEqual(candidate.shift_choice, "12:00 PM - 08:00 PM")
        self.assertEqual(candidate.answers.count(), 3)
        self.assertEqual(
            candidate.answers.get(question=self.tools_q).value, "Trados، Phrase"
        )

    def test_the_bot_never_names_the_company(self):
        self.conf.redact_terms = "EagleLingua"
        self.conf.save()
        self.vacancy.job_description = "ترجمة في EagleLingua"
        self.vacancy.save()

        self.say("اهلا")
        self.say("نعم")
        for reply in self.replies():
            self.assertNotIn("EagleLingua", reply)

    def test_hr_is_told_when_an_application_completes(self):
        from .models import Notification

        self.say("اهلا")
        self.say("نعم")
        self.say("نهى")
        self.say("1")
        self.say("5500")
        self.assertTrue(
            Notification.objects.filter(user=self.hr, title_en="New application").exists()
        )

    # -- the shift question --------------------------------------------------
    def test_one_shift_is_asked_as_a_yes_or_no(self):
        self.say("اهلا")
        prompt = self.replies()[-1]
        self.assertIn("12:00 PM - 08:00 PM", prompt)
        self.assertIn("نعم", prompt)

    def test_several_shifts_are_offered_as_a_numbered_list(self):
        from .models import Candidate, ShiftTemplate

        self.vacancy.shifts.add(ShiftTemplate.objects.get(name="Shift 1"))
        self.say("اهلا")
        prompt = self.replies()[-1]
        self.assertIn("1.", prompt)
        self.assertIn("2.", prompt)

        self.say("2")
        candidate = Candidate.objects.get(phone=self.contact)
        self.assertTrue(candidate.shift_choice)

    def test_saying_no_to_the_only_shift_still_continues(self):
        """Not available is an answer HR should see, not a dead end."""
        from .models import Candidate

        self.say("اهلا")
        self.say("لا")
        self.say("نهى")
        candidate = Candidate.objects.get(phone=self.contact)
        self.assertEqual(candidate.shift_choice, "")
        self.assertEqual(candidate.full_name, "نهى")

    # -- validation ----------------------------------------------------------
    def test_a_nonsense_choice_is_asked_again_not_stored(self):
        self.say("اهلا")
        self.say("نعم")
        self.say("نهى")
        before = self.sent.call_count
        self.say("بلاش")           # not a number, not an option
        self.assertGreater(self.sent.call_count, before)
        self.assertIn("القايمة", self.replies()[-1])

    def test_a_file_question_insists_on_a_file(self):
        from django.core.files.base import ContentFile

        from .models import Candidate, QuestionKind, RecruitmentQuestion, VacancyQuestion
        from .models import AnswerTarget

        cv_q = RecruitmentQuestion.objects.create(
            text="ابعت الـCV", kind=QuestionKind.FILE, maps_to=AnswerTarget.CV
        )
        VacancyQuestion.objects.create(vacancy=self.vacancy, question=cv_q, order=4)

        self.say("اهلا")
        self.say("نعم")
        self.say("نهى")
        self.say("1")
        self.say("5000")
        # Now on the CV question: text alone is refused.
        self.say("هبعته بعدين")
        self.assertIn("مرفق", self.replies()[-1])

        self.say("", attachments=[{
            "file": ContentFile(b"%PDF-1.4 cv", name="cv.pdf"), "name": "cv.pdf", "size": 10,
        }])
        candidate = Candidate.objects.get(phone=self.contact)
        self.assertTrue(candidate.cv)
        self.assertEqual(candidate.cv_name, "cv.pdf")

    def test_with_no_open_vacancy_the_bot_says_so_politely(self):
        from .models import Candidate, VacancyStatus

        self.vacancy.status = VacancyStatus.CLOSED
        self.vacancy.save()
        self.say("اهلا")
        self.assertIn("مفيش وظايف", self.replies()[-1])
        self.assertFalse(Candidate.objects.filter(phone=self.contact).exists())

    def test_a_switched_off_bot_answers_nothing(self):
        self.conf.bot_enabled = False
        self.conf.save()
        self.assertIsNone(self.say("اهلا"))
        self.assertEqual(self.sent.call_count, 0)


class RecruitmentPipelineTests(TestCase):
    """Who may move a candidate where, and who alone may hire."""

    def setUp(self):
        from .models import Candidate, CandidateStatus, Department, Vacancy, VacancyStatus

        Department.seed_defaults()
        self.department = Department.objects.get(name="Translation")
        self.vacancy = Vacancy.objects.create(
            title="Translator", department=self.department, status=VacancyStatus.OPEN
        )
        self.candidate = Candidate.objects.create(
            full_name="سارة", phone="201222222222", vacancy=self.vacancy,
            status=CandidateStatus.SCREENING, expected_salary="6000",
        )
        self.hr = User.objects.create_user("hr3", password="x", role=Role.HR)
        self.owner = User.objects.create_user("owner2", password="x", role=Role.ADMIN)
        self.CandidateStatus = CandidateStatus

    def test_the_pipeline_refuses_to_skip_its_own_steps(self):
        from . import recruitment

        with self.assertRaises(recruitment.PipelineError):
            recruitment.move_status(
                self.candidate, self.CandidateStatus.HIRED, self.hr
            )

    def test_hr_cannot_approve_a_hire(self):
        from . import recruitment

        self.candidate.status = self.CandidateStatus.OWNER_APPROVAL
        self.candidate.save()
        with self.assertRaises(recruitment.PipelineError):
            recruitment.decide_hiring(self.candidate, self.hr, approve=True)

    def test_reaching_the_owner_notifies_them(self):
        from . import recruitment
        from .models import Notification

        recruitment.move_status(self.candidate, self.CandidateStatus.INTERVIEW, self.hr)
        recruitment.move_status(self.candidate, self.CandidateStatus.FINAL_REVIEW, self.hr)
        recruitment.move_status(
            self.candidate, self.CandidateStatus.OWNER_APPROVAL, self.hr
        )
        self.assertTrue(
            Notification.objects.filter(
                user=self.owner, title_en="Candidate approval required"
            ).exists()
        )

    def test_hiring_carries_the_application_across(self):
        """Section 17: nothing is retyped, and the two stay linked."""
        from datetime import date
        from decimal import Decimal

        from . import recruitment
        from .models import EmploymentStatus, SalaryRecord

        self.candidate.email = "sara@example.com"
        self.candidate.languages = "AR, EN"
        self.candidate.status = self.CandidateStatus.OWNER_APPROVAL
        self.candidate.save()
        recruitment.decide_hiring(self.candidate, self.owner, approve=True)

        person = recruitment.hire(
            self.candidate, self.hr, role=Role.TRANSLATOR,
            job_title="Arabic Translator", joining_date=date(2026, 10, 1),
            salary=Decimal("5500.00"),
        )
        self.candidate.refresh_from_db()

        self.assertEqual(self.candidate.status, self.CandidateStatus.HIRED)
        self.assertEqual(self.candidate.hired_user, person)
        self.assertEqual(person.email, "sara@example.com")
        self.assertEqual(person.languages, "AR, EN")
        self.assertEqual(person.department, self.department)
        self.assertEqual(person.employment_status, EmploymentStatus.PROBATION)
        self.assertEqual(person.probation_start, date(2026, 10, 1))
        self.assertTrue(person.employee_code.startswith("EMP-"))
        self.assertEqual(
            SalaryRecord.objects.get(user=person).amount, Decimal("5500.00")
        )
        # The employee can be read back to the application that produced them.
        self.assertEqual(person.candidate_record, self.candidate)

    def test_nobody_is_hired_twice(self):
        from . import recruitment

        self.candidate.status = self.CandidateStatus.APPROVED
        self.candidate.save()
        recruitment.hire(self.candidate, self.hr)
        with self.assertRaises(recruitment.PipelineError):
            recruitment.hire(self.candidate, self.hr)

    def test_hiring_before_approval_is_refused(self):
        from . import recruitment

        with self.assertRaises(recruitment.PipelineError):
            recruitment.hire(self.candidate, self.hr)


class RecruitmentRoutingTests(TestCase):
    """One webhook, two lines: a client and a candidate never collide."""

    def setUp(self):
        from .models import AppSettings, RecruitmentSettings, Vacancy, VacancyStatus

        self.app = AppSettings.load()
        self.app.whatsapp_phone_number_id = "111client"
        self.app.recruit_phone_number_id = "222recruit"
        self.app.save()
        RecruitmentSettings.load()
        Vacancy.objects.create(title="Translator", status=VacancyStatus.OPEN)

    def post(self, number_id, body="اهلا"):
        import json
        from unittest import mock

        payload = {
            "entry": [{
                "changes": [{
                    "value": {
                        "metadata": {"phone_number_id": number_id},
                        "contacts": [{"wa_id": "201333333333", "profile": {"name": "خالد"}}],
                        "messages": [{
                            "from": "201333333333", "id": "wamid.1",
                            "type": "text", "text": {"body": body},
                        }],
                    }
                }]
            }]
        }
        with mock.patch("dashboard.whatsapp.send_text", return_value="wamid.x"):
            return self.client.post(
                "/webhooks/whatsapp/", data=json.dumps(payload),
                content_type="application/json",
            )

    def test_the_client_number_still_reaches_the_ops_inbox(self):
        from .models import Candidate, InboundMessage

        response = self.post("111client")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(InboundMessage.objects.count(), 1)
        self.assertEqual(Candidate.objects.count(), 0)

    def test_the_recruitment_number_reaches_the_bot_instead(self):
        from .models import CandidateSession, InboundMessage

        response = self.post("222recruit")
        self.assertEqual(response.status_code, 200)
        # Nothing landed in the client inbox.
        self.assertEqual(InboundMessage.objects.count(), 0)
        self.assertTrue(CandidateSession.objects.filter(contact="201333333333").exists())

    def test_with_no_recruitment_number_everything_is_a_client(self):
        from .models import CandidateSession, InboundMessage

        self.app.recruit_phone_number_id = ""
        self.app.save()
        self.post("222recruit")
        self.assertEqual(InboundMessage.objects.count(), 1)
        self.assertFalse(CandidateSession.objects.exists())


class RecruitmentPageTests(TestCase):
    """Section 24: each role reaches its own screens and no others."""

    def setUp(self):
        from .models import Candidate, RecruitmentSettings

        RecruitmentSettings.load()
        self.hr = User.objects.create_user("hr4", password="x", role=Role.HR)
        self.reviewer = User.objects.create_user("rev", password="x", role=Role.REVIEWER)
        self.owner = User.objects.create_user("owner3", password="x", role=Role.ADMIN)
        self.translator = User.objects.create_user("tr9", password="x", role=Role.TRANSLATOR)
        self.candidate = Candidate.objects.create(full_name="عمر", phone="201444444444")

    def test_hr_opens_the_recruitment_screens(self):
        self.client.force_login(self.hr)
        for path in (
            "/hr/recruitment/", "/hr/vacancies/", "/hr/questions/",
            "/hr/candidates/", "/hr/employees/", "/hr/recruitment/settings/",
            f"/hr/candidates/{self.candidate.code}/",
        ):
            self.assertEqual(self.client.get(path).status_code, 200, path)

    def test_a_translator_reaches_none_of_them(self):
        self.client.force_login(self.translator)
        for path in ("/hr/recruitment/", "/hr/candidates/", "/hr/approvals/"):
            self.assertEqual(self.client.get(path).status_code, 403, path)

    def test_hr_cannot_open_the_owner_queue(self):
        self.client.force_login(self.hr)
        self.assertEqual(self.client.get("/hr/approvals/").status_code, 403)

    def test_the_reviewer_gets_tests_and_nothing_else(self):
        self.client.force_login(self.reviewer)
        self.assertEqual(self.client.get("/reviewer/tests/").status_code, 200)
        self.assertEqual(self.client.get("/hr/candidates/").status_code, 403)

    def test_the_owner_reaches_everything(self):
        self.client.force_login(self.owner)
        for path in ("/hr/recruitment/", "/hr/approvals/", "/reviewer/tests/"):
            self.assertEqual(self.client.get(path).status_code, 200, path)


class InterviewScoreTests(TestCase):
    def test_the_total_is_computed_not_typed(self):
        from .models import Candidate, Interview

        candidate = Candidate.objects.create(full_name="ليلى", phone="201555555555")
        interview = Interview.objects.create(
            candidate=candidate, scheduled_at=timezone.now(),
            communication=8, experience=7, technical=9, computer_skills=6, attitude=10,
        )
        self.assertEqual(interview.total_score, 40)
        self.assertEqual(interview.max_score, 50)
        self.assertTrue(interview.is_evaluated)

    def test_an_unmarked_interview_is_not_a_zero(self):
        from .models import Candidate, Interview

        candidate = Candidate.objects.create(full_name="ليلى", phone="201555555556")
        interview = Interview.objects.create(
            candidate=candidate, scheduled_at=timezone.now()
        )
        self.assertFalse(interview.is_evaluated)


# ---------------------------------------------------------------------------
# Probation, leave, performance and per-person pay
# ---------------------------------------------------------------------------

class ProbationTests(TestCase):
    def setUp(self):
        from datetime import date

        from .models import EmploymentStatus, RecruitmentSettings

        RecruitmentSettings.load()
        self.hr = User.objects.create_user("hr5", password="x", role=Role.HR)
        self.person = User.objects.create_user(
            "newbie", password="x", role=Role.TRANSLATOR,
            joining_date=date(2026, 9, 1), probation_start=date(2026, 9, 1),
            probation_end=date(2026, 11, 30),
            employment_status=EmploymentStatus.PROBATION,
        )
        self.date = date
        self.EmploymentStatus = EmploymentStatus

    def test_hiring_opens_three_dated_reviews(self):
        from . import employees
        from .models import ProbationStage

        employees.open_probation(self.person, actor=self.hr)
        rows = {r.stage: r for r in self.person.probation_reviews.all()}
        self.assertEqual(len(rows), 3)
        self.assertEqual(rows[ProbationStage.DAY_30].due_date, self.date(2026, 10, 1))
        self.assertEqual(rows[ProbationStage.DAY_60].due_date, self.date(2026, 10, 31))
        self.assertEqual(rows[ProbationStage.FINAL].due_date, self.date(2026, 11, 30))

    def test_opening_twice_does_not_duplicate(self):
        from . import employees

        employees.open_probation(self.person, actor=self.hr)
        employees.open_probation(self.person, actor=self.hr)
        self.assertEqual(self.person.probation_reviews.count(), 3)

    def test_only_the_final_review_confirms_somebody(self):
        from . import employees
        from .models import ProbationOutcome, ProbationStage

        employees.open_probation(self.person, actor=self.hr)
        day30 = self.person.probation_reviews.get(stage=ProbationStage.DAY_30)
        employees.decide_probation(
            day30, self.hr, ProbationOutcome.CONFIRMED, score=8, notes="بداية كويسة"
        )
        self.person.refresh_from_db()
        # A thirty-day review is not a confirmation of employment.
        self.assertEqual(self.person.employment_status, self.EmploymentStatus.PROBATION)

        final = self.person.probation_reviews.get(stage=ProbationStage.FINAL)
        employees.decide_probation(final, self.hr, ProbationOutcome.CONFIRMED, score=9)
        self.person.refresh_from_db()
        self.assertEqual(self.person.employment_status, self.EmploymentStatus.ACTIVE)

    def test_extending_moves_the_end_and_the_final_review_with_it(self):
        from . import employees
        from .models import ProbationOutcome, ProbationStage

        employees.open_probation(self.person, actor=self.hr)
        day60 = self.person.probation_reviews.get(stage=ProbationStage.DAY_60)
        employees.decide_probation(
            day60, self.hr, ProbationOutcome.EXTENDED, extend_days=30
        )
        self.person.refresh_from_db()
        final = self.person.probation_reviews.get(stage=ProbationStage.FINAL)
        self.assertEqual(self.person.probation_end, self.date(2026, 12, 30))
        self.assertEqual(final.due_date, self.date(2026, 12, 30))

    def test_terminating_closes_the_account_without_deleting_it(self):
        from . import employees
        from .models import ProbationOutcome, ProbationStage

        employees.open_probation(self.person, actor=self.hr)
        final = self.person.probation_reviews.get(stage=ProbationStage.FINAL)
        employees.decide_probation(final, self.hr, ProbationOutcome.TERMINATED)
        self.person.refresh_from_db()
        self.assertEqual(self.person.employment_status, self.EmploymentStatus.LEFT)
        self.assertFalse(self.person.is_active)
        # The record survives, because their months still have to be readable.
        self.assertTrue(User.objects.filter(pk=self.person.pk).exists())

    def test_a_decided_review_cannot_be_decided_again(self):
        from . import employees
        from .models import ProbationOutcome, ProbationStage

        employees.open_probation(self.person, actor=self.hr)
        final = self.person.probation_reviews.get(stage=ProbationStage.FINAL)
        employees.decide_probation(final, self.hr, ProbationOutcome.CONFIRMED)
        with self.assertRaises(employees.LifecycleError):
            employees.decide_probation(final, self.hr, ProbationOutcome.TERMINATED)


class LeaveTests(TestCase):
    """The integration that matters: an approved leave reaches attendance."""

    def setUp(self):
        from datetime import date, time

        from .models import PayrollSettings, Shift, ShiftTemplate

        self.conf = PayrollSettings.load()
        ShiftTemplate.seed_defaults()
        self.morning = ShiftTemplate.objects.get(name="Shift 1")   # 09:00-17:00

        self.lead = User.objects.create_user("lead9", password="x", role=Role.TEAM_LEAD)
        self.hr = User.objects.create_user("hr6", password="x", role=Role.HR)
        self.person = User.objects.create_user(
            "mona", password="x", role=Role.TRANSLATOR, team_lead=self.lead
        )
        # Rostered every day, so no test date lands on a day off.
        for weekday in range(7):
            Shift.objects.create(user=self.person, weekday=weekday, template=self.morning)
        self.date = date
        self.time = time

    def test_an_approved_leave_is_written_onto_the_attendance_sheet(self):
        from . import employees
        from .models import DayStatus, LeaveKind, WorkDay

        row = employees.request_leave(
            self.person, kind=LeaveKind.ANNUAL,
            start_date=self.date(2026, 10, 5), end_date=self.date(2026, 10, 7),
            reason="سفر",
        )
        employees.decide_leave(row, self.hr, approve=True)
        row.refresh_from_db()

        self.assertTrue(row.is_approved)
        self.assertIsNotNone(row.applied_at)
        days = WorkDay.objects.filter(
            user=self.person, date__range=(self.date(2026, 10, 5), self.date(2026, 10, 7))
        )
        self.assertEqual(days.count(), 3)
        for day in days:
            self.assertEqual(day.status, DayStatus.LEAVE)

    def test_a_day_the_person_actually_worked_is_never_overwritten(self):
        """The punch is evidence. Leave does not get to erase it."""
        from . import attendance, employees
        from .models import LeaveKind, PunchKind, WorkDay

        attendance.punch(
            self.person, PunchKind.CHECK_IN,
            at=timezone.make_aware(
                timezone.datetime.combine(self.date(2026, 10, 5), self.time(9, 0))
            ),
        )
        row = employees.request_leave(
            self.person, kind=LeaveKind.ANNUAL,
            start_date=self.date(2026, 10, 5), end_date=self.date(2026, 10, 6),
        )
        employees.decide_leave(row, self.hr, approve=True)

        worked = WorkDay.objects.get(user=self.person, date=self.date(2026, 10, 5))
        self.assertIsNotNone(worked.check_in)
        self.assertEqual(worked.status, "present")
        # The other day was still written.
        self.assertEqual(
            WorkDay.objects.get(user=self.person, date=self.date(2026, 10, 6)).status,
            "leave",
        )

    def test_a_permission_stops_the_day_reading_as_short(self):
        from . import attendance, employees
        from .models import LeaveKind, PunchKind, WorkDay

        day = self.date(2026, 10, 5)

        def at(hour, minute=0):
            return timezone.make_aware(
                timezone.datetime.combine(day, self.time(hour, minute))
            )

        attendance.punch(self.person, PunchKind.CHECK_IN, at=at(9, 0))
        row, _ = attendance.punch(self.person, PunchKind.CHECK_OUT, at=at(15, 0))
        # Six hours of an eight-hour shift: two hours short.
        self.assertEqual(row.short_minutes, 120)

        leave = employees.request_leave(
            self.person, kind=LeaveKind.PERMISSION, start_date=day,
            start_time=self.time(15, 0), end_time=self.time(17, 0), reason="ظرف",
        )
        employees.decide_leave(leave, self.hr, approve=True)

        row = WorkDay.objects.get(user=self.person, date=day)
        self.assertEqual(row.excused_minutes, 120)
        self.assertEqual(row.short_minutes, 0)

    def test_the_manager_step_exists_only_when_the_setting_says_so(self):
        from . import employees
        from .models import LeaveKind, LeaveStatus

        self.conf.leave_needs_manager = True
        self.conf.save()
        row = employees.request_leave(
            self.person, kind=LeaveKind.ANNUAL, start_date=self.date(2026, 10, 12)
        )
        self.assertEqual(row.status, LeaveStatus.PENDING)

        employees.decide_leave(row, self.lead, approve=True)
        row.refresh_from_db()
        self.assertEqual(row.status, LeaveStatus.MANAGER_OK)
        # Still nothing on the attendance sheet - HR has not signed.
        self.assertIsNone(row.applied_at)

        employees.decide_leave(row, self.hr, approve=True)
        row.refresh_from_db()
        self.assertEqual(row.status, LeaveStatus.APPROVED)
        self.assertIsNotNone(row.applied_at)

    def test_with_the_setting_off_hr_alone_is_enough(self):
        from . import employees
        from .models import LeaveKind, LeaveStatus

        row = employees.request_leave(
            self.person, kind=LeaveKind.ANNUAL, start_date=self.date(2026, 10, 12)
        )
        self.assertEqual(row.status, LeaveStatus.MANAGER_OK)
        employees.decide_leave(row, self.hr, approve=True)
        row.refresh_from_db()
        self.assertEqual(row.status, LeaveStatus.APPROVED)

    def test_overlapping_leave_is_refused(self):
        from . import employees
        from .models import LeaveKind

        employees.request_leave(
            self.person, kind=LeaveKind.ANNUAL,
            start_date=self.date(2026, 10, 5), end_date=self.date(2026, 10, 8),
        )
        with self.assertRaises(employees.LifecycleError):
            employees.request_leave(
                self.person, kind=LeaveKind.ANNUAL,
                start_date=self.date(2026, 10, 7), end_date=self.date(2026, 10, 9),
            )

    def test_a_permission_longer_than_the_limit_is_refused(self):
        from . import employees
        from .models import LeaveKind

        with self.assertRaises(employees.LifecycleError):
            employees.request_leave(
                self.person, kind=LeaveKind.PERMISSION,
                start_date=self.date(2026, 10, 5),
                start_time=self.time(9, 0), end_time=self.time(17, 0),
            )

    def test_the_balance_counts_what_is_still_waiting(self):
        """Two requests must not both be approved into one empty allowance."""
        from . import employees
        from .models import LeaveKind

        employees.request_leave(
            self.person, kind=LeaveKind.ANNUAL,
            start_date=self.date(2026, 10, 5), end_date=self.date(2026, 10, 7),
        )
        balance = employees.leave_balance(self.person, 2026, 10)
        self.assertEqual(balance["pending"], 3)
        self.assertEqual(balance["left"], balance["allowance"] - 3)


class SalaryPlanTests(TestCase):
    """The rule that made plans safe: a blank falls back to the company."""

    def setUp(self):
        from datetime import date
        from decimal import Decimal as D

        from .models import PayrollSettings, ProductionTier, SalaryRecord

        self.conf = PayrollSettings.load()
        ProductionTier.seed_defaults()
        self.person = User.objects.create_user("plan1", password="x", role=Role.TRANSLATOR)
        SalaryRecord.objects.create(
            user=self.person, amount=D("5200.00"), effective_from=date(2026, 1, 1)
        )
        self.D = D
        self.date = date

    def test_somebody_with_no_plan_reads_the_company_rules(self):
        from . import payroll

        rules = payroll.rules_for(self.person)
        self.assertIsNone(rules.plan)
        self.assertEqual(rules.daily_target_words, self.conf.daily_target_words)
        self.assertEqual(rules.monthly_target_words, self.conf.monthly_target_words)
        self.assertEqual(rules.working_days_per_month, self.conf.working_days_per_month)
        self.assertTrue(rules.uses_tiers)
        self.assertEqual(rules.fixed_allowance, self.D("0.00"))

    def test_a_plan_overrides_only_what_it_sets(self):
        from . import payroll
        from .models import SalaryPlan

        plan = SalaryPlan.objects.create(name="Senior", daily_target_words=2000)
        self.person.salary_plan = plan
        self.person.save()

        rules = payroll.rules_for(self.person)
        self.assertEqual(rules.daily_target_words, 2000)
        # Everything it left blank still comes from the company.
        self.assertEqual(rules.monthly_target_words, self.conf.monthly_target_words)
        self.assertEqual(rules.discipline_bonus, self.conf.discipline_bonus)

    def test_an_inactive_plan_is_ignored(self):
        from . import payroll
        from .models import SalaryPlan

        plan = SalaryPlan.objects.create(
            name="Old", daily_target_words=1000, is_active=False
        )
        self.person.salary_plan = plan
        self.person.save()
        self.assertEqual(
            payroll.rules_for(self.person).daily_target_words,
            self.conf.daily_target_words,
        )

    def test_a_per_word_rate_replaces_the_bonus_bands(self):
        from . import payroll
        from .models import DayStatus, SalaryPlan, WorkDay

        plan = SalaryPlan.objects.create(
            name="Per word", daily_target_words=3000, extra_word_rate=self.D("0.0500")
        )
        self.person.salary_plan = plan
        self.person.save()

        day = WorkDay.objects.create(
            user=self.person, date=self.date(2026, 10, 5),
            status=DayStatus.PRESENT, words=3500,
        )
        rules = payroll.rules_for(self.person)
        self.assertFalse(rules.uses_tiers)
        # 500 words over the quota at 0.05 each.
        self.assertEqual(payroll.day_bonus(day, rules), self.D("25.00"))

    def test_a_fixed_allowance_reaches_the_gross(self):
        from . import payroll
        from .models import SalaryPlan

        plan = SalaryPlan.objects.create(name="With allowance", fixed_allowance=self.D("300.00"))
        self.person.salary_plan = plan
        self.person.save()

        line = payroll.compute_line(self.person, 2026, 10)
        self.assertEqual(line.allowance, self.D("300.00"))
        self.assertEqual(line.gross, line.base_salary + self.D("300.00"))

    def test_the_low_output_floor_is_the_plan_s_and_not_the_company_s(self):
        """A plan that lowers the daily target has to lower the penalty too.

        Otherwise somebody is held to a floor nobody agreed with them - which
        is the one thing per-person pay rules must never do.
        """
        from . import payroll
        from .models import (
            ApprovalStatus, DayStatus, SalaryPlan, Violation, ViolationKind, WorkDay,
        )

        plan = SalaryPlan.objects.create(name="Technical", daily_target_words=2000)
        self.person.salary_plan = plan
        self.person.save()

        # 2,500 is under the company's 3,000 and over the plan's 2,000.
        WorkDay.objects.create(
            user=self.person, date=self.date(2026, 10, 5),
            status=DayStatus.PRESENT, words=2500,
        )
        payroll.compute_line(self.person, 2026, 10)
        self.assertFalse(
            Violation.objects.filter(
                user=self.person, kind=ViolationKind.LOW_OUTPUT,
                status=ApprovalStatus.PENDING,
            ).exists()
        )

        # Under the plan's own floor, it is a draft like any other.
        WorkDay.objects.create(
            user=self.person, date=self.date(2026, 10, 6),
            status=DayStatus.PRESENT, words=1500,
        )
        payroll.compute_line(self.person, 2026, 10)
        draft = Violation.objects.get(
            user=self.person, kind=ViolationKind.LOW_OUTPUT, date=self.date(2026, 10, 6)
        )
        self.assertIn("2000", draft.reason)


class ApproveBonusesTests(TestCase):
    """The bug this caught: releasing bonuses used to delete the overtime."""

    def test_releasing_the_bonuses_keeps_every_other_component(self):
        from datetime import date
        from decimal import Decimal as D

        from . import payroll
        from .models import (
            ApprovalStatus, PayrollPeriod, PayrollLine, PayrollSettings, SalaryRecord,
        )

        conf = PayrollSettings.load()
        person = User.objects.create_user("bonus1", password="x", role=Role.TRANSLATOR)
        SalaryRecord.objects.create(
            user=person, amount=D("5000.00"), effective_from=date(2026, 1, 1)
        )
        period = PayrollPeriod.objects.create(year=2026, month=10)
        line = PayrollLine.objects.create(
            period=period, user=person,
            base_salary=D("5000.00"), allowance=D("200.00"),
            production_bonus=D("150.00"), overtime_bonus=D("75.00"),
            deductions=D("0.00"),
            discipline_bonus_earned=True, target_bonus_earned=False,
        )
        owner = User.objects.create_user("owner9", password="x", role=Role.ADMIN)
        payroll.approve_bonuses(line, owner)
        line.refresh_from_db()

        expected = (
            D("5000.00") + D("200.00") + D("150.00") + D("75.00") + conf.discipline_bonus
        )
        self.assertEqual(line.gross, expected)
        self.assertEqual(line.net, expected)


class SalaryChangeTests(TestCase):
    def setUp(self):
        from datetime import date
        from decimal import Decimal as D

        from .models import SalaryRecord

        self.hr = User.objects.create_user("hr7", password="x", role=Role.HR)
        self.owner = User.objects.create_user("owner10", password="x", role=Role.ADMIN)
        self.person = User.objects.create_user("payme", password="x", role=Role.TRANSLATOR)
        SalaryRecord.objects.create(
            user=self.person, amount=D("5000.00"), effective_from=date(2026, 1, 1)
        )
        self.D = D
        self.date = date

    def test_hr_asks_and_only_the_owner_decides(self):
        from . import employees

        row = employees.request_salary_change(
            self.person, new_amount=self.D("6000.00"),
            effective_from=self.date(2026, 11, 1), reason="ترقية", actor=self.hr,
        )
        self.assertEqual(row.current_amount, self.D("5000.00"))
        with self.assertRaises(employees.LifecycleError):
            employees.decide_salary_change(row, self.hr, approve=True)

    def test_approval_is_what_writes_the_salary_record(self):
        from . import employees
        from .models import SalaryRecord

        row = employees.request_salary_change(
            self.person, new_amount=self.D("6000.00"),
            effective_from=self.date(2026, 11, 1), actor=self.hr,
        )
        self.assertEqual(
            SalaryRecord.amount_on(self.person, self.date(2026, 11, 1)), self.D("5000.00")
        )
        employees.decide_salary_change(row, self.owner, approve=True)
        row.refresh_from_db()
        self.assertIsNotNone(row.salary_record)
        self.assertEqual(
            SalaryRecord.amount_on(self.person, self.date(2026, 11, 1)), self.D("6000.00")
        )

    def test_a_rejected_request_changes_nothing(self):
        from . import employees
        from .models import SalaryRecord

        row = employees.request_salary_change(
            self.person, new_amount=self.D("9000.00"),
            effective_from=self.date(2026, 11, 1), actor=self.hr,
        )
        employees.decide_salary_change(row, self.owner, approve=False, note="بدري")
        self.assertEqual(
            SalaryRecord.amount_on(self.person, self.date(2026, 11, 1)), self.D("5000.00")
        )

    def test_two_requests_cannot_queue_for_one_person(self):
        from . import employees

        employees.request_salary_change(
            self.person, new_amount=self.D("6000.00"),
            effective_from=self.date(2026, 11, 1), actor=self.hr,
        )
        with self.assertRaises(employees.LifecycleError):
            employees.request_salary_change(
                self.person, new_amount=self.D("7000.00"),
                effective_from=self.date(2026, 11, 1), actor=self.hr,
            )


class PerformanceTests(TestCase):
    def setUp(self):
        from datetime import date

        from .models import Client, PayrollSettings

        self.conf = PayrollSettings.load()
        self.lead = User.objects.create_user("lead8", password="x", role=Role.TEAM_LEAD)
        self.person = User.objects.create_user(
            "perf1", password="x", role=Role.TRANSLATOR, team_lead=self.lead,
            attendance_enabled=False,
        )
        self.client_obj = Client.objects.create(name="ACME")
        self.date = date

    def make_task(self, *, translated, deadline=None, score=None, words=1000):
        from .models import Task, TaskStatus

        task = Task.objects.create(
            client=self.client_obj, title="Doc", translator=self.person,
            team_lead=self.lead, status=TaskStatus.DELIVERED,
            word_count=words, deadline=deadline, review_score=score,
        )
        Task.objects.filter(pk=task.pk).update(translated_at=translated)
        task.refresh_from_db()
        return task

    def test_an_indicator_with_no_data_is_none_not_zero(self):
        from . import performance

        report = performance.for_month(self.person, 2026, 10)
        self.assertIsNone(report["parts"]["deadline"]["score"])
        self.assertIsNone(report["parts"]["quality"]["score"])
        self.assertIsNone(report["parts"]["attendance"]["score"])

    def test_the_overall_ignores_the_indicators_it_cannot_measure(self):
        """A missing indicator must not drag the average toward zero."""
        from . import performance
        from .models import DayStatus, WorkDay

        WorkDay.objects.create(
            user=self.person, date=self.date(2026, 10, 5),
            status=DayStatus.PRESENT, words=self.conf.monthly_target_words,
        )
        report = performance.for_month(self.person, 2026, 10)
        self.assertEqual(report["parts"]["productivity"]["score"], 100)
        # Productivity is the only reading, so it is the whole overall.
        self.assertEqual(report["overall"], 100)

    def test_deadlines_count_the_translation_not_the_delivery(self):
        from . import performance

        on_time = timezone.make_aware(timezone.datetime(2026, 10, 5, 12, 0))
        late = timezone.make_aware(timezone.datetime(2026, 10, 6, 12, 0))
        self.make_task(translated=on_time, deadline=on_time + timedelta(hours=2))
        self.make_task(translated=late, deadline=late - timedelta(hours=2))

        part = performance.deadlines(
            self.person, self.date(2026, 10, 1), self.date(2026, 10, 31)
        )
        self.assertEqual(part["total"], 2)
        self.assertEqual(part["late"], 1)
        self.assertEqual(part["score"], 50)

    def test_a_complaint_moves_the_quality_score(self):
        from . import performance
        from .models import ClientComplaint, ComplaintSeverity

        translated = timezone.make_aware(timezone.datetime(2026, 10, 5, 12, 0))
        self.make_task(translated=translated, score=9)
        clean = performance.quality(
            self.person, self.date(2026, 10, 1), self.date(2026, 10, 31)
        )
        self.assertEqual(clean["score"], 90)

        ClientComplaint.objects.create(
            translator=self.person, severity=ComplaintSeverity.HIGH,
            summary="ترجمة ناقصة", happened_on=self.date(2026, 10, 6),
        )
        after = performance.quality(
            self.person, self.date(2026, 10, 1), self.date(2026, 10, 31)
        )
        self.assertEqual(after["score"], 65)
        self.assertEqual(after["complaints"], 1)

    def test_sending_a_job_back_is_what_records_a_revision(self):
        from . import performance, services
        from .models import TaskStatus

        translated = timezone.make_aware(timezone.datetime(2026, 10, 5, 12, 0))
        task = self.make_task(translated=translated)
        task.status = TaskStatus.UNDER_REVIEW
        task.save()

        self.assertTrue(services.send_back_for_revision(task, self.lead, "الصياغة"))
        task.refresh_from_db()
        self.assertEqual(task.status, TaskStatus.IN_PROGRESS)
        self.assertEqual(task.revision_count, 1)
        self.assertIsNone(task.reviewed_at)

        report = performance.for_month(self.person, 2026, 10)
        self.assertEqual(report["returned_projects"], 1)
        self.assertEqual(report["revision_rate"], 100)

    def test_only_the_team_leader_scores_a_review(self):
        from . import services

        translated = timezone.make_aware(timezone.datetime(2026, 10, 5, 12, 0))
        task = self.make_task(translated=translated)
        self.assertFalse(services.score_review(task, self.person, 9))
        self.assertTrue(services.score_review(task, self.lead, 9, "كويس"))
        task.refresh_from_db()
        self.assertEqual(task.review_score, 9)

    def test_a_score_outside_ten_is_refused(self):
        from . import services

        translated = timezone.make_aware(timezone.datetime(2026, 10, 5, 12, 0))
        task = self.make_task(translated=translated)
        self.assertFalse(services.score_review(task, self.lead, 11))
        self.assertFalse(services.score_review(task, self.lead, "high"))

    def test_a_weight_of_zero_drops_its_indicator_from_the_overall(self):
        """The settings are what decide the mix - nothing here is hard-coded."""
        from . import performance
        from .models import DayStatus, WorkDay

        WorkDay.objects.create(
            user=self.person, date=self.date(2026, 10, 5),
            status=DayStatus.PRESENT, words=self.conf.monthly_target_words,
        )
        translated = timezone.make_aware(timezone.datetime(2026, 10, 6, 12, 0))
        self.make_task(translated=translated, score=5)  # quality = 50%

        both = performance.for_month(self.person, 2026, 10)["overall"]
        self.conf.weight_quality = 0
        self.conf.save()
        from .models import PayrollSettings
        PayrollSettings._cached = None

        only_productivity = performance.for_month(self.person, 2026, 10)["overall"]
        self.assertLess(both, 100)
        self.assertEqual(only_productivity, 100)


class PayrollSettingsFormTests(TestCase):
    """The six settings part 2 added are editable, and refuse the nonsense."""

    def setUp(self):
        from .models import PayrollSettings

        self.conf = PayrollSettings.load()

    def bound(self, **overrides):
        """The settings form filled with the row as it stands, plus overrides."""
        from .forms import PayrollSettingsForm

        data = {}
        for name in PayrollSettingsForm.Meta.fields:
            value = getattr(self.conf, name)
            if value is True:
                data[name] = "on"
            elif value is False:
                continue  # an unticked checkbox is simply absent
            else:
                data[name] = value
        data.update(overrides)
        return PayrollSettingsForm(data, instance=self.conf)

    def test_the_new_settings_are_on_the_form(self):
        from .forms import PayrollSettingsForm

        for name in (
            "leave_needs_manager", "permission_max_minutes",
            "weight_productivity", "weight_quality",
            "weight_deadline", "weight_attendance",
        ):
            self.assertIn(name, PayrollSettingsForm(instance=self.conf).fields)

    def test_an_unchanged_form_is_valid(self):
        """The guard against a test that passes because everything fails."""
        self.assertTrue(self.bound().is_valid(), self.bound().errors.as_text())

    def test_a_permission_longer_than_the_working_day_is_refused(self):
        form = self.bound(daily_hours=8, permission_max_minutes=600)
        self.assertFalse(form.is_valid())
        self.assertIn("permission_max_minutes", form.errors)

    def test_every_weight_at_zero_is_refused(self):
        form = self.bound(
            weight_productivity=0, weight_quality=0,
            weight_deadline=0, weight_attendance=0,
        )
        self.assertFalse(form.is_valid())
        self.assertIn("weight_attendance", form.errors)

    def test_a_sane_set_of_weights_saves(self):
        form = self.bound(
            weight_productivity=50, weight_quality=50,
            weight_deadline=0, weight_attendance=0,
            leave_needs_manager="on", permission_max_minutes=120,
        )
        self.assertTrue(form.is_valid(), form.errors.as_text())
        form.save()
        self.conf.refresh_from_db()
        self.assertTrue(self.conf.leave_needs_manager)
        self.assertEqual(self.conf.weight_deadline, 0)


class LifecyclePageTests(TestCase):
    def setUp(self):
        from .models import PayrollSettings, RecruitmentSettings

        PayrollSettings.load()
        RecruitmentSettings.load()
        self.hr = User.objects.create_user("hr8", password="x", role=Role.HR)
        self.owner = User.objects.create_user("owner11", password="x", role=Role.ADMIN)
        self.translator = User.objects.create_user("tr8", password="x", role=Role.TRANSLATOR)

    def test_everybody_reaches_their_own_leave_page(self):
        self.client.force_login(self.translator)
        self.assertEqual(self.client.get("/leave/").status_code, 200)

    def test_hr_reaches_the_lifecycle_screens(self):
        self.client.force_login(self.hr)
        for path in (
            "/hr/leave/", "/hr/probation/", "/hr/performance/",
            "/hr/complaints/", "/hr/salary-requests/",
        ):
            self.assertEqual(self.client.get(path).status_code, 200, path)

    def test_salary_plans_are_the_owner_s_alone(self):
        self.client.force_login(self.hr)
        self.assertEqual(self.client.get("/hr/salary-plans/").status_code, 403)
        self.client.force_login(self.owner)
        self.assertEqual(self.client.get("/hr/salary-plans/").status_code, 200)

    def test_a_translator_reaches_none_of_the_hr_screens(self):
        self.client.force_login(self.translator)
        for path in ("/hr/leave/", "/hr/probation/", "/hr/performance/"):
            self.assertEqual(self.client.get(path).status_code, 403, path)


class NextAfterLoginTests(TestCase):
    """Signing in while ?next= points at somebody else's page.

    Measured on the live site 20/09/2026: the POST to /login/ succeeded and the
    GET of /panel/ that followed returned 403. The session was never the
    problem - the destination was.
    """

    def setUp(self):
        self.translator = User.objects.create_user(
            "tr_next", password="x", role=Role.TRANSLATOR
        )
        self.owner = User.objects.create_user(
            "owner_next", password="x", role=Role.ADMIN
        )

    def test_a_translator_sent_to_the_admin_panel_lands_on_their_own_page(self):
        response = self.client.post(
            "/login/", {"username": "tr_next", "password": "x", "next": "/panel/"}
        )
        self.assertEqual(response.status_code, 302)
        self.assertEqual(response["Location"], "/")

    def test_the_owner_still_arrives_where_they_asked(self):
        response = self.client.post(
            "/login/", {"username": "owner_next", "password": "x", "next": "/panel/"}
        )
        self.assertEqual(response.status_code, 302)
        self.assertEqual(response["Location"], "/panel/")

    def test_a_page_behind_no_role_guard_is_still_honoured(self):
        response = self.client.post(
            "/login/", {"username": "tr_next", "password": "x", "next": "/leave/"}
        )
        self.assertEqual(response.status_code, 302)
        self.assertEqual(response["Location"], "/leave/")

    def test_the_rule_is_read_off_the_guard_not_a_second_copy(self):
        self.assertFalse(user_may_open(self.translator, "/panel/"))
        self.assertTrue(user_may_open(self.owner, "/panel/"))
        self.assertFalse(user_may_open(self.translator, "/no/such/page/"))

    def test_a_forbidden_page_opened_directly_is_still_refused(self):
        """The redirect fixes arrival, not permission. The door stays shut."""
        self.client.force_login(self.translator)
        self.assertEqual(self.client.get("/panel/").status_code, 403)


class SourceFilesReachTheTranslatorTests(TestCase):
    """The client's document has to reach the translator - the client must not.

    Measured 20/09/2026 on TSK-00002: the translator accepted, the group
    opened, and the file the client had sent stayed in the inbox, which only
    the admin and the operation can see. The group said "share the files here"
    and nothing in the code ever did.
    """

    def setUp(self):
        from django.core.files.base import ContentFile

        from .models import InboundMessage, MessageAttachment

        self.InboundMessage = InboundMessage
        self.ops = User.objects.create_user("ops_src", password="x", role=Role.OPERATION)
        self.lead = User.objects.create_user("lead_src", password="x", role=Role.TEAM_LEAD)
        self.tr = User.objects.create_user(
            "tr_src", password="x", role=Role.TRANSLATOR, team_lead=self.lead
        )
        self.client_obj = Client.objects.create(name="ACME", phone="+201000000001")
        self.inbound = InboundMessage.objects.create(
            client=self.client_obj, body="[document]",
            sender_identity="+201000000001", sender_display="Dr Kerolos",
        )
        MessageAttachment.objects.create(
            message=self.inbound, file=ContentFile(b"hello", name="brief.pdf"),
            original_name="brief.pdf", size=5,
        )
        self.task = services.create_task(
            client=self.client_obj, title="Doc", created_by=self.ops,
            messages=[self.inbound],
        )

    def _accept(self):
        assignment = services.assign_to_translator(self.task, self.tr, self.ops)
        services.accept_assignment(assignment, self.tr)
        return self.task.rooms.get(kind=RoomKind.GROUP)

    def _shared(self, room):
        return [m for m in room.messages.all() if not m.is_system]

    def test_accepting_puts_the_client_file_in_the_group(self):
        room = self._accept()
        shared = self._shared(room)
        self.assertEqual(len(shared), 1)
        self.assertEqual(
            [f.original_name for f in shared[0].relay_files], ["brief.pdf"]
        )

    def test_the_client_identity_does_not_travel_with_the_file(self):
        room = self._accept()
        for item in services.group_thread(room, self.tr):
            self.assertNotIn("+2010", item["body"])
            self.assertNotIn("Kerolos", item["body"])
            self.assertEqual(item["sender"], "")
            self.assertTrue(item["files"])

    def test_the_inbox_row_itself_stays_out_of_reach(self):
        """Only the file crosses. The message it came on does not."""
        self._accept()
        self.assertFalse(self.inbound.visible_to(self.tr))

    def test_sharing_again_does_not_double_the_file(self):
        room = self._accept()
        services.share_source_files(self.task)
        services.share_source_files(self.task)
        self.assertEqual(room.messages.filter(inbound__isnull=False).count(), 1)

    def test_a_client_message_with_no_file_is_not_shared(self):
        chatter = self.InboundMessage.objects.create(
            client=self.client_obj, body="thanks", task=self.task
        )
        room = self._accept()
        self.assertEqual(room.messages.filter(inbound=chatter).count(), 0)


class HandoverTests(TestCase):
    """Review, then a person takes the job, then the client. In that order.

    The step this covers did not exist before 20/09/2026: a reviewed task sat
    in a status, and whoever opened the page next could send it. Sending to a
    client is the one move nobody can take back, so it now waits for a person
    to be on record as having the job.
    """

    def setUp(self):
        self.ops = User.objects.create_user("ops_h", password="x", role=Role.OPERATION)
        self.lead = User.objects.create_user("lead_h", password="x", role=Role.TEAM_LEAD)
        self.tr = User.objects.create_user(
            "tr_h", password="x", role=Role.TRANSLATOR, team_lead=self.lead
        )
        self.client_obj = Client.objects.create(name="ACME", phone="+201000000002")

    def _task_in_progress(self):
        task = services.create_task(
            client=self.client_obj, title="Doc", created_by=self.ops,
        )
        first = services.assign_to_lead(task, self.lead, self.ops)
        services.accept_assignment(first, self.lead)
        second = services.assign_to_translator(task, self.tr, self.lead)
        services.accept_assignment(second, self.tr)
        task.refresh_from_db()
        return task

    def _reviewed_task(self):
        task = self._task_in_progress()
        services.mark_translated(task, self.tr)
        task.refresh_from_db()
        services.mark_reviewed(task, self.lead)
        task.refresh_from_db()
        return task

    # -- the handover ------------------------------------------------------
    def test_nothing_is_sent_before_somebody_takes_the_task(self):
        task = self._reviewed_task()
        ok, delivery, error = services.deliver_to_client(task, self.ops, [], "hi")
        self.assertFalse(ok)
        self.assertIsNone(delivery)
        self.assertTrue(error)
        task.refresh_from_db()
        self.assertEqual(task.status, TaskStatus.REVIEWED)

    def test_taking_it_over_opens_the_door(self):
        task = self._reviewed_task()
        self.assertTrue(services.acknowledge_handover(task, self.ops))
        task.refresh_from_db()
        self.assertEqual(task.handover_ack_by, self.ops)
        self.assertIsNotNone(task.handover_ack_at)

        ok, _, _ = services.deliver_to_client(task, self.ops, [], "", send=False)
        self.assertTrue(ok)
        task.refresh_from_db()
        self.assertEqual(task.status, TaskStatus.DELIVERED)

    def test_the_translator_cannot_take_the_task_over(self):
        task = self._reviewed_task()
        self.assertFalse(services.acknowledge_handover(task, self.tr))
        task.refresh_from_db()
        self.assertIsNone(task.handover_ack_at)

    def test_a_task_that_is_not_reviewed_cannot_be_taken_over(self):
        task = self._task_in_progress()
        self.assertFalse(services.acknowledge_handover(task, self.ops))

    def test_sending_it_back_cancels_the_handover(self):
        task = self._reviewed_task()
        services.acknowledge_handover(task, self.ops)
        services.send_back_for_revision(task, self.lead, "ناقص")
        task.refresh_from_db()
        self.assertIsNone(task.handover_ack_at)
        self.assertIsNone(task.handover_ack_by)

    # -- who hears about it ------------------------------------------------
    def test_the_group_is_told_the_review_is_done_not_only_the_creator(self):
        from .models import Notification

        task = self._reviewed_task()
        told = set(
            Notification.objects.filter(task=task, title_en__startswith="Reviewed")
            .values_list("user_id", flat=True)
        )
        self.assertIn(self.ops.id, told)
        # The person who pressed the button is not told about their own press.
        self.assertNotIn(self.lead.id, told)

    # -- the rooms ---------------------------------------------------------
    def test_the_translator_is_not_in_the_client_room(self):
        task = self._reviewed_task()
        room = task.rooms.get(kind=RoomKind.CLIENT)
        self.assertNotIn(self.tr, room.members.all())
        self.assertIn(self.lead, room.members.all())

    def test_an_admin_can_add_an_operation_to_the_group_afterwards(self):
        admin = User.objects.create_user("owner_h", password="x", role=Role.ADMIN)
        other = User.objects.create_user("ops_h2", password="x", role=Role.OPERATION)
        task = self._reviewed_task()
        self.assertTrue(services.add_group_member(task, admin, other))
        self.assertIn(other, task.rooms.get(kind=RoomKind.GROUP).members.all())
        # Twice is not an error, and does not add a second row.
        self.assertTrue(services.add_group_member(task, admin, other))

    def test_only_an_admin_adds_somebody_to_a_group(self):
        other = User.objects.create_user("ops_h3", password="x", role=Role.OPERATION)
        task = self._reviewed_task()
        self.assertFalse(services.add_group_member(task, self.lead, other))
        self.assertNotIn(other, task.rooms.get(kind=RoomKind.GROUP).members.all())

    # -- the automatic AI check -------------------------------------------
    def test_the_ai_check_starts_itself_when_the_translator_finishes(self):
        from unittest import mock

        from .models import AICheckResult

        conf = AppSettings.load()
        conf.ai_check_enabled = True
        conf.claude_api_key = "test-key"
        conf.save()

        task = self._task_in_progress()
        with mock.patch("dashboard.ai.threading.Thread") as thread:
            services.mark_translated(task, self.tr)
        self.assertTrue(thread.called)

        row = task.ai_checks.first()
        self.assertEqual(row.status, AICheckResult.Status.RUNNING)
        # Nobody asked for it - that is what makes it the automatic one.
        self.assertIsNone(row.requested_by)

    def test_no_check_is_written_when_the_admin_has_it_switched_off(self):
        task = self._task_in_progress()
        services.mark_translated(task, self.tr)
        self.assertEqual(task.ai_checks.count(), 0)

    def test_a_second_check_does_not_start_while_one_is_running(self):
        from unittest import mock

        conf = AppSettings.load()
        conf.ai_check_enabled = True
        conf.claude_api_key = "test-key"
        conf.save()

        task = self._task_in_progress()
        with mock.patch("dashboard.ai.threading.Thread"):
            from . import ai

            self.assertIsNotNone(ai.start_background_check(task))
            self.assertIsNone(ai.start_background_check(task))
        self.assertEqual(task.ai_checks.count(), 1)


class MailAndChatAreSeparateTests(TestCase):
    """One message, one place.

    Until 21/09/2026 every inbound message — WhatsApp and e-mail alike — sat in
    /ops/inbox/ *and* in the client chat. Two people answered the same client
    twice, which is the only kind of duplicate a client actually notices. The
    mail page is now e-mail and the chat is WhatsApp, and these tests are what
    keeps them apart.
    """

    def setUp(self):
        from .models import Channel, InboundMessage

        self.Channel = Channel
        self.InboundMessage = InboundMessage
        self.ops = User.objects.create_user("ops_mail", password="x", role=Role.OPERATION)
        self.client_obj = Client.objects.create(
            name="ACME", phone="+201000000002", email="client@example.com"
        )
        self.mail = InboundMessage.objects.create(
            client=self.client_obj, channel=Channel.EMAIL,
            subject="Bilingual contract", body="please quote the attached",
            sender_identity="client@example.com",
        )
        self.wa = InboundMessage.objects.create(
            client=self.client_obj, channel=Channel.WHATSAPP,
            body="any update?", sender_identity="+201000000002",
        )

    def test_the_mail_page_holds_the_mail_and_not_the_whatsapp(self):
        rows = list(services.inbox_queryset(self.ops))
        self.assertIn(self.mail, rows)
        self.assertNotIn(self.wa, rows)

    def test_the_chat_holds_the_whatsapp_and_not_the_mail(self):
        bodies = [e["body"] for e in services.client_thread(self.client_obj, self.ops)]
        self.assertIn("any update?", bodies)
        self.assertNotIn("please quote the attached", bodies)

    def test_a_client_we_have_only_e_mailed_is_not_in_the_chat_list(self):
        only_mail = Client.objects.create(name="MAILONLY", email="m@example.com")
        self.InboundMessage.objects.create(
            client=only_mail, channel=self.Channel.EMAIL, body="hello",
            sender_identity="m@example.com",
        )
        codes = [c.code for c in services.client_conversations(self.ops)]
        self.assertIn(self.client_obj.code, codes)
        self.assertNotIn(only_mail.code, codes)

    def test_the_mail_page_opens(self):
        self.client.force_login(self.ops)
        response = self.client.get("/ops/inbox/")
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Bilingual contract")
        self.assertNotContains(response, "any update?")

    def test_the_search_finds_a_subject(self):
        rows = list(services.inbox_queryset(self.ops, query="bilingual"))
        self.assertEqual(rows, [self.mail])

    def test_an_e_mail_does_not_open_the_whatsapp_window(self):
        """Meta's 24-hour clock is WhatsApp's alone.

        Counting an e-mail here would have the chat promise a free-form reply
        that Meta then refuses — the one thing the banner exists to prevent.
        """
        quiet = Client.objects.create(name="QUIET", phone="+201000000009",
                                      email="quiet@example.com")
        self.InboundMessage.objects.create(
            client=quiet, channel=self.Channel.EMAIL, body="hello",
            sender_identity="quiet@example.com",
        )
        self.assertFalse(quiet.reply_window_open)
        self.InboundMessage.objects.create(
            client=quiet, channel=self.Channel.WHATSAPP, body="hello",
            sender_identity="+201000000009",
        )
        self.assertTrue(quiet.reply_window_open)


class ReceiptTests(TestCase):
    """"استلمت" is a promise to the client, not a checkbox for us.

    The button both tells the client their message arrived and marks the row
    claimed — in that order. A row that says "handled" beside a client who was
    never told is the exact state the button exists to prevent.
    """

    def setUp(self):
        from .models import Channel, InboundMessage

        self.Channel = Channel
        self.ops = User.objects.create_user("ops_rcpt", password="x", role=Role.OPERATION)
        self.client_obj = Client.objects.create(
            name="ACME", phone="+201000000003", email="rcpt@example.com"
        )
        self.wa = InboundMessage.objects.create(
            client=self.client_obj, channel=Channel.WHATSAPP, body="hi",
            sender_identity="+201000000003",
        )
        self.mail = InboundMessage.objects.create(
            client=self.client_obj, channel=Channel.EMAIL, subject="Quote",
            body="hi", sender_identity="rcpt@example.com",
        )

    def test_a_whatsapp_message_is_answered_on_whatsapp(self):
        from unittest import mock

        with mock.patch("dashboard.whatsapp.send_text", return_value="wamid.r") as sent:
            ok, error = services.confirm_receipt(self.wa, self.ops)
        self.assertTrue(ok, error)
        self.assertEqual(sent.call_args[0][0], "+201000000003")
        self.assertEqual(sent.call_args[0][1], "confirmed")

    def test_an_e_mail_is_answered_by_e_mail_in_its_own_thread(self):
        from unittest import mock

        # The e-mail is the *older* of the two here, so a reply that followed
        # the client's latest channel would go out on WhatsApp instead.
        with mock.patch("dashboard.mailer.send_delivery", return_value=True) as sent:
            ok, error = services.confirm_receipt(self.mail, self.ops)
        self.assertTrue(ok, error)
        self.assertEqual(sent.call_args.kwargs["subject"], "Re: Quote")
        self.assertEqual(sent.call_args.kwargs["body"], "confirmed")

    def test_the_row_is_claimed_once_the_client_has_been_told(self):
        from unittest import mock

        with mock.patch("dashboard.whatsapp.send_text", return_value="wamid.r"):
            services.confirm_receipt(self.wa, self.ops)
        self.wa.refresh_from_db()
        self.assertEqual(self.wa.claimed_by, self.ops)

    def test_a_send_that_failed_leaves_the_row_unclaimed(self):
        from unittest import mock

        from . import whatsapp as wa

        with mock.patch(
            "dashboard.whatsapp.send_text",
            side_effect=wa.WhatsAppError("مش ظابط", "nope"),
        ):
            ok, error = services.confirm_receipt(self.wa, self.ops)
        self.assertFalse(ok)
        self.assertTrue(error)
        self.wa.refresh_from_db()
        self.assertIsNone(self.wa.claimed_by_id)

    def test_the_endpoint_belongs_to_the_operation(self):
        translator = User.objects.create_user(
            "tr_rcpt", password="x", role=Role.TRANSLATOR
        )
        self.client.force_login(translator)
        response = self.client.post(f"/api/messages/{self.wa.pk}/confirm/")
        self.assertIn(response.status_code, (403, 404))


class ActionsFollowTheFilesTests(TestCase):
    """The two buttons under a message belong to the file, not to the words.

    "Received" tells the client their file arrived, and the task is built out
    of that same file. A line of text has neither thing behind it, and a voice
    note is not a document to translate — so both of those get no buttons at
    all. Before this, the pair sat under every message a client ever sent.
    """

    def setUp(self):
        from django.core.files.base import ContentFile
        from .models import Channel, InboundMessage, MessageAttachment

        self.Channel = Channel
        self.InboundMessage = InboundMessage
        self.MessageAttachment = MessageAttachment
        self.ContentFile = ContentFile
        self.ops = User.objects.create_user("ops_acts", password="x", role=Role.OPERATION)
        self.client_obj = Client.objects.create(
            name="ACME", phone="+201000000021", email="acts@example.com"
        )

    def _message(self, body="", channel=None):
        return self.InboundMessage.objects.create(
            client=self.client_obj,
            channel=channel or self.Channel.WHATSAPP,
            body=body,
            sender_identity="+201000000021",
        )

    def _attach(self, message, name, mime=""):
        return self.MessageAttachment.objects.create(
            message=message,
            file=self.ContentFile(b"x", name=name),
            original_name=name, size=1, mime=mime,
        )

    def _entry(self, message):
        uid = f"in-{message.pk}"
        return next(
            entry for entry in services.client_thread(self.client_obj, self.ops)
            if entry["uid"] == uid
        )

    def test_a_message_carrying_a_document_keeps_the_buttons(self):
        message = self._message(body="[document]")
        self._attach(message, "contract.pdf", "application/pdf")
        self.assertTrue(self._entry(message)["has_docs"])

    def test_a_message_that_is_only_words_gets_none(self):
        message = self._message(body="ممكن سعر الترجمة؟")
        self.assertFalse(self._entry(message)["has_docs"])

    def test_a_voice_note_on_its_own_is_not_a_document(self):
        """Nothing to translate, so nothing to confirm and nothing to convert."""
        message = self._message()
        self._attach(message, "note.ogg", "audio/ogg")
        self.assertFalse(self._entry(message)["has_docs"])
        self.assertEqual(message.document_attachments, [])

    def test_a_voice_note_beside_a_document_still_counts(self):
        message = self._message()
        self._attach(message, "note.ogg", "audio/ogg")
        contract = self._attach(message, "contract.pdf", "application/pdf")
        self.assertTrue(self._entry(message)["has_docs"])
        self.assertEqual(message.document_attachments, [contract])

    def test_the_chat_draws_one_pair_of_buttons_for_two_messages(self):
        """One conversation, two messages, one file: one pair of buttons."""
        self._message(body="ممكن سعر الترجمة؟")
        with_file = self._message(body="[document]")
        self._attach(with_file, "contract.pdf", "application/pdf")
        self.client.force_login(self.ops)
        response = self.client.get(f"/ops/chats/{self.client_obj.code}/")
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "تحويل لتاسك", count=1)

    def test_a_letter_with_nothing_attached_shows_no_buttons(self):
        letter = self._message(body="just asking", channel=self.Channel.EMAIL)
        self.client.force_login(self.ops)
        response = self.client.get(f"/ops/inbox/thread/{letter.pk}/")
        self.assertEqual(response.status_code, 200)
        self.assertNotContains(response, "تحويل لتاسك")
        self.assertNotContains(response, 'data-ar="استلمت"')

    def test_a_letter_with_a_file_shows_them(self):
        letter = self._message(body="here it is", channel=self.Channel.EMAIL)
        self._attach(letter, "contract.pdf", "application/pdf")
        self.client.force_login(self.ops)
        response = self.client.get(f"/ops/inbox/thread/{letter.pk}/")
        self.assertContains(response, "تحويل لتاسك")
        self.assertContains(response, 'data-ar="استلمت"')


class PickedSourceFilesTests(TestCase):
    """Only the files somebody ticked are the job.

    A client's message can carry the contract, their signature, and a photo of
    their desk. Before this, all three walked into the task group. Empty still
    means "all of them", so every task made before the picker is unchanged.
    """

    def setUp(self):
        from django.core.files.base import ContentFile
        from .models import Channel, InboundMessage, MessageAttachment

        self.ops = User.objects.create_user("ops_pick", password="x", role=Role.OPERATION)
        self.lead = User.objects.create_user("lead_pick", password="x", role=Role.TEAM_LEAD)
        self.tr = User.objects.create_user(
            "tr_pick", password="x", role=Role.TRANSLATOR, team_lead=self.lead
        )
        self.client_obj = Client.objects.create(name="ACME", phone="+201000000004")
        self.inbound = InboundMessage.objects.create(
            client=self.client_obj, channel=Channel.WHATSAPP, body="[documents]",
            sender_identity="+201000000004",
        )
        self.contract = MessageAttachment.objects.create(
            message=self.inbound, file=ContentFile(b"contract", name="contract.pdf"),
            original_name="contract.pdf", size=8,
        )
        self.selfie = MessageAttachment.objects.create(
            message=self.inbound, file=ContentFile(b"selfie", name="selfie.jpg"),
            original_name="selfie.jpg", size=6,
        )

    def _task(self, picked=None):
        task = services.create_task(
            client=self.client_obj, title="Doc", created_by=self.ops,
            messages=[self.inbound],
        )
        if picked:
            task.source_files.set(picked)
        assignment = services.assign_to_translator(task, self.tr, self.ops)
        services.accept_assignment(assignment, self.tr)
        return task, task.rooms.get(kind=RoomKind.GROUP)

    def _names(self, room):
        shared = [m for m in room.messages.all() if not m.is_system]
        return [f.original_name for m in shared for f in m.relay_files]

    def test_only_the_ticked_file_reaches_the_translator(self):
        _task, room = self._task(picked=[self.contract])
        self.assertEqual(self._names(room), ["contract.pdf"])

    def test_nothing_ticked_still_means_everything(self):
        _task, room = self._task()
        self.assertEqual(sorted(self._names(room)), ["contract.pdf", "selfie.jpg"])

    def test_the_client_room_still_shows_what_the_client_actually_sent(self):
        """The picker trims the task group. It must not edit the record."""
        task, _room = self._task(picked=[self.contract])
        services.mirror_inbound_to_room(self.inbound)
        client_room = task.rooms.get(kind=RoomKind.CLIENT)
        names = [
            f.original_name
            for m in client_room.messages.filter(inbound=self.inbound)
            for f in m.relay_files
        ]
        self.assertEqual(sorted(names), ["contract.pdf", "selfie.jpg"])

    def test_an_id_from_another_message_cannot_walk_into_the_task(self):
        from django.core.files.base import ContentFile
        from .models import Channel, InboundMessage, MessageAttachment
        from .views import _picked_attachments

        other_client = Client.objects.create(name="OTHER", phone="+201000000005")
        other = InboundMessage.objects.create(
            client=other_client, channel=Channel.WHATSAPP, body="x",
            sender_identity="+201000000005",
        )
        stranger = MessageAttachment.objects.create(
            message=other, file=ContentFile(b"nope", name="secret.pdf"),
            original_name="secret.pdf", size=4,
        )
        picked = _picked_attachments(self.inbound, [f"{self.contract.pk},{stranger.pk}"])
        self.assertEqual(picked, [self.contract])

    def test_the_form_carries_the_ticked_files_into_the_task(self):
        self.client.force_login(self.ops)
        response = self.client.post("/ops/tasks/new/", {
            "message": self.inbound.pk,
            "files": [str(self.contract.pk)],
            "client": self.client_obj.pk,
            "title": "Contract",
            "description": "",
            "source_lang": "", "target_lang": "", "priority": "normal",
            "deadline": "", "word_count": "0",
        })
        self.assertEqual(response.status_code, 302, getattr(response, "context", None))
        task = Task.objects.latest("id")
        self.assertEqual(
            [a.original_name for a in task.source_files.all()], ["contract.pdf"]
        )


class TranslatorBoardTests(TestCase):
    """Who can take a job this minute — and the evidence behind the answer."""

    def setUp(self):
        self.lead = User.objects.create_user("lead_bd", password="x", role=Role.TEAM_LEAD)
        self.ops = User.objects.create_user("ops_bd", password="x", role=Role.OPERATION)
        self.free = User.objects.create_user(
            "free_bd", password="x", role=Role.TRANSLATOR, team_lead=self.lead
        )
        self.busy = User.objects.create_user(
            "busy_bd", password="x", role=Role.TRANSLATOR, team_lead=self.lead
        )
        self.away = User.objects.create_user(
            "away_bd", password="x", role=Role.TRANSLATOR, team_lead=self.lead
        )
        self.client_obj = Client.objects.create(name="ACME", phone="+201000000006")
        # Online means the site is open right now, and nothing else.
        for person in (self.free, self.busy):
            person.last_seen = timezone.now()
            person.save(update_fields=["last_seen"])

    def _states(self):
        return {
            row["person"].username: row["state"]
            for row in services.translator_board(self.lead)
        }

    def test_somebody_with_no_work_and_the_site_open_is_free(self):
        self.assertEqual(self._states()["free_bd"], "free")

    def test_a_running_task_makes_them_busy(self):
        task = services.create_task(
            client=self.client_obj, title="Doc", created_by=self.ops,
        )
        task.translator = self.busy
        task.status = TaskStatus.IN_PROGRESS
        task.save(update_fields=["translator", "status"])
        self.assertEqual(self._states()["busy_bd"], "busy")

    def test_an_unanswered_offer_already_holds_them(self):
        """An offer nobody has answered is work in flight, not free time."""
        task = services.create_task(
            client=self.client_obj, title="Doc", created_by=self.ops,
        )
        services.assign_to_translator(task, self.busy, self.lead)
        self.assertEqual(self._states()["busy_bd"], "busy")

    def test_somebody_who_never_opened_eagle_is_not_free(self):
        self.assertIn(self._states()["away_bd"], ("off", "shift"))

    def test_free_people_come_first(self):
        task = services.create_task(
            client=self.client_obj, title="Doc", created_by=self.ops,
        )
        task.translator = self.busy
        task.status = TaskStatus.IN_PROGRESS
        task.save(update_fields=["translator", "status"])
        rows = services.translator_board(self.lead)
        self.assertEqual(rows[0]["person"], self.free)

    def test_another_leader_s_team_is_not_on_this_board(self):
        other_lead = User.objects.create_user(
            "lead_bd2", password="x", role=Role.TEAM_LEAD
        )
        User.objects.create_user(
            "tr_other", password="x", role=Role.TRANSLATOR, team_lead=other_lead
        )
        self.assertNotIn("tr_other", self._states())

    def test_the_page_opens_for_the_leader_only(self):
        self.client.force_login(self.lead)
        self.assertEqual(self.client.get("/lead/translators/").status_code, 200)
        self.client.force_login(self.free)
        self.assertEqual(self.client.get("/lead/translators/").status_code, 403)


class MailboxParsingTests(TestCase):
    """Turning a real e-mail into an inbound row.

    Gmail sends most mail as plain text *and* HTML; a client who writes from a
    phone may send HTML only. Both have to arrive with words in them — a row
    with an empty body reads on the page as though the client sent nothing.
    """

    def _message(self, raw):
        import email as email_module

        from . import mailbox

        return mailbox.parse_message(email_module.message_from_string(raw))

    def test_plain_text_wins_over_the_html_copy(self):
        parsed = self._message(
            "From: Dr Sara <sara@example.com>\r\n"
            "Subject: Contract\r\n"
            'Content-Type: multipart/alternative; boundary="b"\r\n\r\n'
            "--b\r\nContent-Type: text/plain\r\n\r\nplease translate\r\n"
            "--b\r\nContent-Type: text/html\r\n\r\n<p>please translate</p>\r\n--b--\r\n"
        )
        self.assertEqual(parsed["body"], "please translate")
        self.assertEqual(parsed["sender_identity"], "sara@example.com")
        self.assertEqual(parsed["sender_display"], "Dr Sara")
        self.assertEqual(parsed["subject"], "Contract")

    def test_an_html_only_message_still_has_words(self):
        parsed = self._message(
            "From: sara@example.com\r\n"
            "Subject: Hi\r\n"
            "Content-Type: text/html\r\n\r\n"
            "<html><style>p{color:red}</style><p>hello <b>there</b></p></html>\r\n"
        )
        self.assertEqual(parsed["body"], "hello there")

    def test_an_attachment_comes_across_with_its_name(self):
        import base64

        payload = base64.b64encode(b"PDF-BYTES").decode()
        parsed = self._message(
            "From: sara@example.com\r\n"
            "Subject: Files\r\n"
            'Content-Type: multipart/mixed; boundary="b"\r\n\r\n'
            "--b\r\nContent-Type: text/plain\r\n\r\nsee attached\r\n"
            "--b\r\nContent-Type: application/pdf\r\n"
            'Content-Disposition: attachment; filename="brief.pdf"\r\n'
            f"Content-Transfer-Encoding: base64\r\n\r\n{payload}\r\n--b--\r\n"
        )
        self.assertEqual(len(parsed["attachments"]), 1)
        self.assertEqual(parsed["attachments"][0]["name"], "brief.pdf")

    def test_a_filename_cannot_carry_a_path(self):
        import base64

        payload = base64.b64encode(b"x").decode()
        parsed = self._message(
            "From: sara@example.com\r\n"
            'Content-Type: multipart/mixed; boundary="b"\r\n\r\n'
            "--b\r\nContent-Type: application/pdf\r\n"
            'Content-Disposition: attachment; filename="../../etc/passwd"\r\n'
            f"Content-Transfer-Encoding: base64\r\n\r\n{payload}\r\n--b--\r\n"
        )
        self.assertEqual(parsed["attachments"][0]["name"], "passwd")

    def test_a_parsed_message_becomes_an_inbox_row(self):
        Client.objects.create(name="ACME", email="sara@example.com")
        parsed = self._message(
            "From: sara@example.com\r\n"
            "Subject: Contract\r\n"
            "Message-ID: <abc@example.com>\r\n"
            "Content-Type: text/plain\r\n\r\nplease translate\r\n"
        )
        row = services.ingest_message(**parsed)
        self.assertEqual(row.channel, "email")
        self.assertEqual(row.subject, "Contract")
        ops = User.objects.create_user("ops_box", password="x", role=Role.OPERATION)
        self.assertIn(row, list(services.inbox_queryset(ops)))
        # The same letter arriving twice is the same row.
        self.assertEqual(services.ingest_message(**parsed).pk, row.pk)


class MailThreadTests(TestCase):
    """The mail page lists conversations, not letters — the way Gmail does.

    Until 21/09/2026 a client who wrote "Legal Arabic Translation", then
    "please share", then "word count please" was three rows, each read on its
    own. Now it is one row that opens on all three, oldest first.
    """

    def setUp(self):
        self.ops = User.objects.create_user("ops_thr", password="x", role=Role.OPERATION)
        self.admin = User.objects.create_user("adm_thr", password="x", role=Role.ADMIN)
        self.client_obj = Client.objects.create(name="ALHAMD", email="info@alhamd.ae")

    def _mail(self, subject, body="hello", sender="info@alhamd.ae", message_id="",
               in_reply_to="", references="", when=None):
        return services.ingest_message(
            channel="email", subject=subject, body=body, sender_identity=sender,
            external_id=message_id, reply_to_external=in_reply_to,
            references=references, received_at=when,
        )

    # -- grouping ---------------------------------------------------------

    def test_replies_with_the_same_subject_are_one_conversation(self):
        first = self._mail("Legal Arabic Translation | Rajesh & Meera", "the job")
        second = self._mail("Re: Legal Arabic Translation | Rajesh & Meera", "please share")
        third = self._mail("RE: Fwd:  legal arabic translation | Rajesh & Meera", "word count please")
        self.assertTrue(first.thread_key)
        self.assertEqual(second.thread_key, first.thread_key)
        self.assertEqual(third.thread_key, first.thread_key)

    def test_the_headers_win_over_a_changed_subject(self):
        first = self._mail("Bilingual - Yashba", message_id="<one@alhamd.ae>")
        reply = self._mail(
            "something else entirely", message_id="<two@alhamd.ae>",
            in_reply_to="<ours@gmail.com>",
            references="<one@alhamd.ae>\r\n <ours@gmail.com>",
        )
        self.assertEqual(reply.thread_key, first.thread_key)

    def test_a_different_subject_is_a_different_conversation(self):
        first = self._mail("Bilingual - Yashba")
        other = self._mail("Legal Arabic Translation | Rajesh & Meera")
        self.assertNotEqual(first.thread_key, other.thread_key)

    def test_another_client_with_the_same_subject_is_not_merged(self):
        ours = self._mail("Translation request")
        theirs = self._mail("Translation request", sender="someone@else.com")
        self.assertNotEqual(ours.thread_key, theirs.thread_key)

    def test_an_old_subject_reused_months_later_starts_over(self):
        old = self._mail("Translation request", when=timezone.now() - timedelta(days=90))
        new = self._mail("Translation request")
        self.assertNotEqual(old.thread_key, new.thread_key)

    def test_no_subject_is_never_a_conversation(self):
        first = self._mail("")
        second = self._mail("")
        self.assertNotEqual(first.thread_key, second.thread_key)

    def test_whatsapp_has_no_mail_thread(self):
        row = services.ingest_message(
            channel="whatsapp", body="hi", sender_identity="+201000000077",
        )
        self.assertEqual(row.thread_key, "")

    def test_the_references_header_reaches_the_ingest(self):
        import email as email_module

        from . import mailbox

        first = self._mail("Contract", message_id="<root@x.com>")
        parsed = mailbox.parse_message(email_module.message_from_string(
            "From: info@alhamd.ae\r\n"
            "Subject: totally new words\r\n"
            "Message-ID: <leaf@x.com>\r\n"
            "In-Reply-To: <gmail-sent@y.com>\r\n"
            "References: <root@x.com> <gmail-sent@y.com>\r\n"
            "Content-Type: text/plain\r\n\r\nany news?\r\n"
        ))
        row = services.ingest_message(**parsed)
        self.assertEqual(row.thread_key, first.thread_key)

    # -- the pages --------------------------------------------------------

    def test_the_list_has_one_row_per_conversation(self):
        self._mail("Legal Arabic Translation", "the job")
        self._mail("Re: Legal Arabic Translation", "please share")
        self._mail("Re: Legal Arabic Translation", "word count please")
        self._mail("Bilingual - Yashba", "another job")

        threads = services.inbox_threads(self.ops)
        self.assertEqual(len(threads), 2)
        # Newest conversation first, and the row speaks for its newest letter.
        self.assertEqual(threads[0].subject, "Bilingual - Yashba")
        legal = threads[1]
        self.assertEqual(legal.count, 3)
        self.assertEqual(legal.subject, "Legal Arabic Translation")
        self.assertEqual(legal.latest.body, "word count please")

        self.client.force_login(self.ops)
        response = self.client.get("/ops/inbox/")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.content.decode().count("data-thread="), 2)

    def test_a_search_brings_the_whole_conversation(self):
        self._mail("Legal Arabic Translation", "the job")
        self._mail("Re: Legal Arabic Translation", "word count please")
        threads = services.inbox_threads(self.ops, query="the job")
        self.assertEqual(len(threads), 1)
        self.assertEqual(threads[0].count, 2)

    def test_the_conversation_page_holds_every_letter_oldest_first(self):
        first = self._mail("Legal Arabic Translation", "the job")
        self._mail("Re: Legal Arabic Translation", "please share")
        last = self._mail("Re: Legal Arabic Translation", "word count please")

        self.client.force_login(self.ops)
        # Any letter opens the whole conversation.
        for pk in (first.pk, last.pk):
            response = self.client.get(f"/ops/inbox/thread/{pk}/")
            self.assertEqual(response.status_code, 200)
            html = response.content.decode()
            self.assertLess(html.index("the job"), html.index("please share"))
            self.assertLess(html.index("please share"), html.index("word count please"))

    def test_a_rate_letter_stays_hidden_inside_a_conversation(self):
        self._mail("Legal Arabic Translation", "the job")
        secret = self._mail("Re: Legal Arabic Translation", "what is your rate?")
        self.assertTrue(secret.is_rate_blocked)

        [thread] = services.inbox_threads(self.ops)
        self.assertEqual(thread.count, 1)
        [admin_thread] = services.inbox_threads(self.admin)
        self.assertEqual(admin_thread.count, 2)

        self.client.force_login(self.ops)
        self.assertEqual(self.client.get(f"/ops/inbox/thread/{secret.pk}/").status_code, 404)

    def test_the_live_feed_sends_the_conversation_row(self):
        first = self._mail("Legal Arabic Translation", "the job")
        reply = self._mail("Re: Legal Arabic Translation", "please share")

        self.client.force_login(self.ops)
        data = self.client.get(f"/api/inbox/feed/?after={first.pk}").json()
        self.assertEqual(len(data["items"]), 1)
        self.assertEqual(data["items"][0]["thread"], first.thread_key)
        self.assertEqual(data["last"], reply.pk)
        self.assertIn(f'data-thread="{first.thread_key}"', data["items"][0]["html"])

        thread_feed = self.client.get(
            f"/api/inbox/thread/{first.pk}/feed/?after={first.pk}"
        ).json()
        self.assertEqual([i["id"] for i in thread_feed["items"]], [reply.pk])

    def test_the_badge_counts_conversations_not_letters(self):
        self._mail("Legal Arabic Translation", "the job")
        self._mail("Re: Legal Arabic Translation", "please share")
        self._mail("Re: Legal Arabic Translation", "word count please")
        self._mail("Bilingual - Yashba", "another job")
        self.assertEqual(services.unclaimed_conversation_count(), 2)

    def test_the_notification_opens_the_conversation(self):
        from .models import Notification

        row = self._mail("Legal Arabic Translation", "the job")
        note = Notification.objects.filter(user=self.ops).latest("id")
        self.assertEqual(note.url, f"/ops/inbox/thread/{row.pk}/")

    def test_mail_from_before_threading_is_grouped_by_the_migration(self):
        import importlib

        from django.apps import apps

        from .models import InboundMessage

        migration = importlib.import_module("dashboard.migrations.0016_mail_threads")
        now = timezone.now()
        rows = [
            InboundMessage.objects.create(
                client=self.client_obj, channel="email", subject=subject,
                body="x", sender_identity="info@alhamd.ae",
                received_at=now - timedelta(minutes=10 - i),
            )
            for i, subject in enumerate(
                ["Bilingual - Yashba", "Re: Bilingual - Yashba", "Other job"]
            )
        ]
        self.assertEqual({r.thread_key for r in rows}, {""})

        migration.group_existing_mail(apps, None)
        keys = [InboundMessage.objects.get(pk=r.pk).thread_key for r in rows]
        self.assertTrue(all(keys))
        self.assertEqual(keys[0], keys[1])
        self.assertNotEqual(keys[0], keys[2])


class MailReplyTests(TestCase):
    """Answering a mail conversation from its own page, text and files.

    The reply has to land where Gmail would put it: inside the client's own
    thread in *their* mailbox (Re: + In-Reply-To + References), and inside the
    conversation on ours — and the client's answer to it has to come back to
    that same conversation, whatever they do to the subject.
    """

    def setUp(self):
        self.ops = User.objects.create_user("ops_rep", password="x", role=Role.OPERATION)
        self.client_obj = Client.objects.create(name="ALHAMD", email="info@alhamd.ae")
        self.first = self._mail("Legal Arabic Translation", "the job", "<a@alhamd.ae>")
        self.second = self._mail("Re: Legal Arabic Translation", "word count please", "<b@alhamd.ae>")

    def _mail(self, subject, body, message_id, in_reply_to=""):
        return services.ingest_message(
            channel="email", subject=subject, body=body,
            sender_identity="info@alhamd.ae", external_id=message_id,
            reply_to_external=in_reply_to,
        )

    def _reply(self, body="566 words", uploads=None, anchor=None):
        from unittest import mock

        with mock.patch("dashboard.mailer.send_delivery", return_value=True) as sent:
            result = services.reply_to_thread(
                anchor or self.first, self.ops, body=body, uploads=uploads
            )
        return result, sent

    def test_the_reply_goes_to_the_client_inside_their_own_thread(self):
        (ok, outbound, error), sent = self._reply()
        self.assertTrue(ok, error)
        self.assertEqual(sent.call_args.args[1], "info@alhamd.ae")
        self.assertEqual(sent.call_args.kwargs["subject"], "Re: Legal Arabic Translation")
        self.assertEqual(sent.call_args.kwargs["body"], "566 words")
        headers = sent.call_args.kwargs["headers"]
        self.assertEqual(headers["In-Reply-To"], "<b@alhamd.ae>")
        self.assertEqual(headers["References"], "<a@alhamd.ae> <b@alhamd.ae>")
        self.assertTrue(headers["Message-ID"])

        self.assertEqual(outbound.thread_key, self.first.thread_key)
        self.assertEqual(outbound.provider_id, headers["Message-ID"])
        self.assertEqual(outbound.subject, "Re: Legal Arabic Translation")

    def test_replying_claims_the_conversation(self):
        self._reply()
        for letter in (self.first, self.second):
            letter.refresh_from_db()
            self.assertEqual(letter.claimed_by, self.ops)
        self.assertEqual(services.unclaimed_conversation_count(), 0)

    def test_the_reply_shows_inside_the_conversation(self):
        (ok, outbound, _error), _sent = self._reply()
        [thread] = services.inbox_threads(self.ops)
        self.assertEqual(thread.count, 3)
        self.assertTrue(thread.answered)

        self.client.force_login(self.ops)
        html = self.client.get(f"/ops/inbox/thread/{self.first.pk}/").content.decode()
        self.assertIn(f'data-reply="{outbound.pk}"', html)
        self.assertLess(html.index("word count please"), html.index("566 words"))

    def test_the_clients_answer_to_our_reply_comes_back_to_it(self):
        (ok, outbound, _error), _sent = self._reply()
        answer = self._mail("thanks, a new subject", "ok received", "<c@alhamd.ae>",
                            in_reply_to=outbound.provider_id)
        self.assertEqual(answer.thread_key, self.first.thread_key)

    def test_an_empty_reply_is_refused(self):
        (ok, outbound, error), sent = self._reply(body="   ")
        self.assertFalse(ok)
        self.assertIsNone(outbound)
        self.assertTrue(error)
        sent.assert_not_called()

    def test_files_go_out_with_the_reply(self):
        import tempfile

        from django.conf import settings
        from django.core.files.uploadedfile import SimpleUploadedFile
        from django.test import override_settings

        local = {**settings.STORAGES,
                 "default": {"BACKEND": "django.core.files.storage.FileSystemStorage"}}
        with tempfile.TemporaryDirectory() as media, \
                override_settings(MEDIA_ROOT=media, STORAGES=local):
            upload = SimpleUploadedFile("brief.pdf", b"PDF-BYTES", content_type="application/pdf")
            (ok, outbound, error), sent = self._reply(body="", uploads=[upload])
            self.assertTrue(ok, error)
            [(name, content, _mime)] = sent.call_args.kwargs["attachments"]
            self.assertEqual((name, content), ("brief.pdf", b"PDF-BYTES"))
            self.assertEqual(outbound.uploads.count(), 1)

    def test_files_over_the_mail_limit_are_refused_before_sending(self):
        from django.core.files.uploadedfile import SimpleUploadedFile

        big = SimpleUploadedFile("big.pdf", b"x")
        big.size = services.MAX_MAIL_BYTES + 1
        (ok, _outbound, error), sent = self._reply(uploads=[big])
        self.assertFalse(ok)
        self.assertIn("25", error)
        sent.assert_not_called()

    def test_a_failed_reply_stays_on_the_page(self):
        from unittest import mock

        from . import mailer

        self.client.force_login(self.ops)
        with mock.patch("dashboard.mailer.send_delivery",
                        side_effect=mailer.MailError("الإرسال فشل", "failed")):
            response = self.client.post(
                f"/api/inbox/thread/{self.first.pk}/reply/", {"body": "566 words"}
            )
        self.assertEqual(response.status_code, 400)
        data = response.json()
        self.assertFalse(data["ok"])
        self.assertIn("is-failed", data["html"])

    def test_the_endpoint_answers_with_the_rendered_reply(self):
        from unittest import mock

        self.client.force_login(self.ops)
        with mock.patch("dashboard.mailer.send_delivery", return_value=True):
            response = self.client.post(
                f"/api/inbox/thread/{self.second.pk}/reply/", {"body": "566 words"}
            )
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertTrue(data["ok"], data)
        self.assertIn(f'data-reply="{data["id"]}"', data["html"])

        feed = self.client.get(
            f"/api/inbox/thread/{self.first.pk}/feed/?after={self.second.pk}&after_out=0"
        ).json()
        self.assertEqual([(i["kind"], i["id"]) for i in feed["items"]], [("out", data["id"])])

    def test_operation_cannot_reply_into_a_rate_letter(self):
        secret = self._mail("Re: Legal Arabic Translation", "what is your rate?", "<r@alhamd.ae>")
        self.assertTrue(secret.is_rate_blocked)
        self.client.force_login(self.ops)
        response = self.client.post(f"/api/inbox/thread/{secret.pk}/reply/", {"body": "hi"})
        self.assertEqual(response.status_code, 404)

    def test_an_e_mail_receipt_lands_in_the_conversation(self):
        from unittest import mock

        with mock.patch("dashboard.mailer.send_delivery", return_value=True) as sent:
            ok, error = services.confirm_receipt(self.second, self.ops)
        self.assertTrue(ok, error)
        self.assertEqual(sent.call_args.kwargs["headers"]["In-Reply-To"], "<b@alhamd.ae>")
        [thread] = services.inbox_threads(self.ops)
        self.assertEqual([r.body for r in thread.replies], ["confirmed"])


class MailPushTests(TestCase):
    """New mail is fetched the moment it lands, not at the next 3-minute poll.

    ``run_worker`` holds an IMAP IDLE connection open (``mailbox.watch``) and
    the server announces each new letter with ``* N EXISTS``. These tests play
    the server's side of that conversation.
    """

    class FakeSock:
        """Hands out scripted server lines; ``None`` is a read that times out."""

        def __init__(self, replies):
            self.replies = [r if r is None else r.encode() + b"\r\n" for r in replies]
            self.sent = []

        def settimeout(self, _seconds):
            pass

        def sendall(self, data):
            self.sent.append(data.decode().strip())

        def recv(self, _size):
            import socket

            item = self.replies.pop(0) if self.replies else None
            if item is None:
                raise socket.timeout("timed out")
            return item

        def close(self):
            pass

    class Conf:
        imap_host = "imap.example.com"
        imap_port = 993
        imap_user = "eagle@example.com"
        imap_password = "app password"
        imap_folder = "INBOX"

    HELLO = [
        "* OK ready",
        "E0001 OK logged in",
        "* CAPABILITY IMAP4rev1 IDLE UNSELECT", "E0002 OK",
        "* 3 EXISTS", "E0003 OK [READ-WRITE] INBOX selected",
    ]

    def test_new_mail_is_announced_straight_away(self):
        from . import mailbox

        sock = self.FakeSock(self.HELLO + [
            "+ idling",
            # Marking a letter read is not new mail; it must not count.
            "* 3 FETCH (FLAGS (\\Seen))",
            "* 4 EXISTS",
            "E0004 OK IDLE terminated",
        ])
        watcher = mailbox.IdleWatcher(self.Conf, sock=sock)
        self.assertTrue(watcher.wait(60))
        self.assertIn("E0004 IDLE", sock.sent)
        self.assertIn("DONE", sock.sent)

    def test_a_quiet_idle_is_renewed_not_mistaken_for_mail(self):
        from . import mailbox

        sock = self.FakeSock(self.HELLO + [
            "+ idling",
            "* 3 FETCH (FLAGS (\\Seen))",
            None,                             # nothing more before the renew time
            "E0004 OK IDLE terminated",
        ])
        watcher = mailbox.IdleWatcher(self.Conf, sock=sock)
        self.assertFalse(watcher.wait(60))
        self.assertIn("DONE", sock.sent)

    def test_a_server_without_idle_is_told_apart(self):
        from . import mailbox

        sock = self.FakeSock([
            "* OK ready", "E0001 OK logged in",
            "* CAPABILITY IMAP4rev1 UNSELECT", "E0002 OK",
        ])
        with self.assertRaises(mailbox.IdleUnsupported):
            mailbox.IdleWatcher(self.Conf, sock=sock)

    def test_the_password_is_quoted_on_the_wire(self):
        from . import mailbox

        self.assertEqual(mailbox._quote('a"b\\c d'), '"a\\"b\\\\c d"')

    def test_watch_fetches_on_connect_and_on_every_push(self):
        import threading
        from unittest import mock

        from . import mailbox
        from .models import AppSettings

        conf = AppSettings.load()
        conf.imap_host, conf.imap_user, conf.imap_password = "imap.x", "u@x.com", "p"
        conf.save()

        stop = threading.Event()
        fetched = []

        class Watcher:
            def __init__(self, _conf):
                self.rounds = 0

            def wait(self, _seconds):
                self.rounds += 1
                if self.rounds == 1:
                    return True           # a letter landed
                stop.set()
                return False

            def close(self):
                pass

        # close_old_connections would end the test's own transaction.
        with mock.patch.object(mailbox, "IdleWatcher", Watcher), \
                mock.patch("django.db.close_old_connections"):
            mailbox.watch(on_mail=lambda: fetched.append(1), stop=stop, log=lambda _m: None)
        # Once on connecting (catch-up), once for the push.
        self.assertEqual(len(fetched), 2)
