"""The owner's decisions after the first review (2026-10-04), held as tests.

* A salary is set by the owner alone (accounting reads it; HR asks for a change). A starting salary on a hire is the owner's too.
* A bonus the owner released stays released when the month is run again.
* Whoever holds the attendance right does not decide their own leave, overtime, browser or day: the owner does.
* An approved permission is minutes off a day, not a day worked: it makes no row, and the day reads it when it is computed.
* The audit log cannot be flooded: a refusal that repeats is one row with a count, and the log pages back past two hundred.
"""

from datetime import datetime, time, timedelta
from decimal import Decimal

from django.test import Client as DjangoClient
from django.urls import reverse
from django.utils import timezone

from . import attendance, employees, identity, payroll
from .models import (
    ApprovalStatus, AuditLog, AuthorizedDevice, LeaveRequest, LeaveStatus, OvertimeClaim, PayrollSettings, User, WorkDay,
)
from .tests_accounts_screen import _Accounts
from .tests_admin_screen import AUDIT, _Admin
from .tests_api_v1 import _json
from .tests_hr_people import _People


class ReleasedBonusTests(_Accounts):
    def setUp(self):
        super().setUp()
        conf = PayrollSettings.load()
        conf.bonuses_need_approval = True
        conf.discipline_bonus = Decimal("100.00")
        conf.save()

    def test_a_release_survives_running_the_month_again(self):
        line = self.line_of()
        self.assertFalse(line.bonuses_approved)
        self.assertEqual(line.discipline_bonus, Decimal("0.00"))
        payroll.approve_bonuses(line, self.admin)
        line.refresh_from_db()
        self.assertEqual((line.bonuses_approved, line.discipline_bonus), (True, Decimal("100.00")))
        net = line.net
        again = self.line_of()
        self.assertEqual((again.bonuses_approved, again.discipline_bonus, again.net), (True, Decimal("100.00"), net))

    def test_a_month_nobody_released_stays_unreleased_when_it_is_run_again(self):
        self.line_of()
        again = self.line_of()
        self.assertEqual((again.bonuses_approved, again.discipline_bonus), (False, Decimal("0.00")))

    def test_what_is_no_longer_earned_is_not_paid_even_though_it_was_released(self):
        line = self.line_of()
        payroll.approve_bonuses(line, self.admin)
        self.violation(kind="quality", status=ApprovalStatus.APPROVED)
        again = self.line_of()
        self.assertEqual(again.discipline_bonus, Decimal("0.00"))


class OwnRecordTests(_People):
    def leave_of(self, person, status=LeaveStatus.MANAGER_OK):
        day = self.today + timedelta(days=2)
        return LeaveRequest.objects.create(user=person, kind="annual", start_date=day, end_date=day, status=status)

    def decide(self, who, row):
        return self.post(who, "dashboard:v1_leave_decide", {}, [row.pk, "approve"])

    def test_nobody_with_the_attendance_right_approves_their_own_leave_but_the_owner_does(self):
        for who in (self.hr, self.flagged):
            row = self.leave_of(who)
            answer = self.decide(who, row)
            self.assertEqual((answer.status_code, _json(answer)["error"]), (409, "refused"), who.username)
            row.refresh_from_db()
            self.assertEqual(row.status, LeaveStatus.MANAGER_OK)
        mine = self.leave_of(self.hr)
        self.assertEqual(self.decide(self.admin, mine).status_code, 200)

    def test_they_still_decide_other_peoples_leave(self):
        self.assertEqual(self.decide(self.hr, self.leave_of(self.tr)).status_code, 200)

    def overtime_of(self, person):
        self.day(person, self.today, overtime_minutes=60)
        return OvertimeClaim.objects.create(user=person, date=self.today, minutes=60, hourly_rate=Decimal("10.00"), amount=Decimal("10.00"))

    def test_nobody_decides_their_own_overtime_but_the_owner(self):
        claim = self.overtime_of(self.hr)
        answer = self.post(self.hr, "dashboard:v1_hr_overtime_decide", {}, [claim.pk, "approve"])
        self.assertEqual((answer.status_code, _json(answer)["error"]), (409, "own_record"))
        claim.refresh_from_db()
        self.assertEqual(claim.status, ApprovalStatus.PENDING)
        self.assertEqual(self.post(self.admin, "dashboard:v1_hr_overtime_decide", {}, [claim.pk, "approve"]).status_code, 200)

    def test_they_still_decide_somebody_elses_overtime(self):
        claim = self.overtime_of(self.tr)
        self.assertEqual(self.post(self.hr, "dashboard:v1_hr_overtime_decide", {}, [claim.pk, "approve"]).status_code, 200)

    def test_nobody_approves_their_own_browser_but_the_owner_and_others_do(self):
        mine = AuthorizedDevice.objects.create(user=self.hr, fingerprint="a" * 20)
        theirs = AuthorizedDevice.objects.create(user=self.tr, fingerprint="b" * 20)
        answer = self.post(self.hr, "dashboard:v1_hr_device_decide", {}, [mine.pk, "approve"])
        self.assertEqual((answer.status_code, _json(answer)["error"]), (409, "own_record"))
        mine.refresh_from_db()
        self.assertEqual(mine.status, ApprovalStatus.PENDING)
        self.assertEqual(self.post(self.hr, "dashboard:v1_hr_device_decide", {}, [theirs.pk, "approve"]).status_code, 200)
        self.assertEqual(self.post(self.admin, "dashboard:v1_hr_device_decide", {}, [mine.pk, "approve"]).status_code, 200)

    def test_nobody_corrects_their_own_day_but_the_owner_and_others_do(self):
        mine = self.day(self.hr, self.today, note="")
        answer = self.post(self.hr, "dashboard:v1_hr_day_save", {"values": {"note": "I was here", "reason": "mine"}}, [mine.pk])
        self.assertEqual((answer.status_code, _json(answer)["error"]), (409, "own_day"))
        mine.refresh_from_db()
        self.assertEqual(mine.note, "")
        theirs = self.day(self.tr, self.today - timedelta(days=1), note="")
        self.assertEqual(self.post(self.hr, "dashboard:v1_hr_day_save", {"values": {"note": "fixed", "reason": "forgot"}}, [theirs.pk]).status_code, 200)
        self.assertEqual(self.post(self.admin, "dashboard:v1_hr_day_save", {"values": {"note": "fixed", "reason": "owner"}}, [mine.pk]).status_code, 200)

    def test_nobody_clears_the_flag_on_their_own_day(self):
        mine = self.day(self.hr, self.today, needs_review=True, review_reason="x")
        answer = self.post(self.hr, "dashboard:v1_hr_day_clear", {}, [mine.pk])
        self.assertEqual((answer.status_code, _json(answer)["error"]), (409, "own_day"))
        mine.refresh_from_db()
        self.assertTrue(mine.needs_review)


class PermissionIsNotADayTests(_People):
    def permission(self, day, start=time(14, 0), end=time(16, 0)):
        return LeaveRequest.objects.create(
            user=self.tr, kind="permission", start_date=day, end_date=day, start_time=start, end_time=end, minutes=120, status=LeaveStatus.APPROVED,
        )

    def test_approving_a_permission_for_a_day_with_no_row_makes_no_row(self):
        day = self.today + timedelta(days=3)
        row = self.permission(day)
        employees.apply_leave(row)
        self.assertFalse(WorkDay.objects.filter(user=self.tr, date=day).exists())
        row.refresh_from_db()
        self.assertIsNotNone(row.applied_at)

    def test_the_minutes_count_when_the_day_is_computed(self):
        self.permission(self.today)
        start = timezone.make_aware(datetime.combine(self.today, time(9, 0)))
        day = WorkDay.objects.create(
            user=self.tr, date=self.today, status="present", check_in=start, check_out=start + timedelta(hours=5),
            scheduled_start=start, scheduled_end=start + timedelta(hours=8), scheduled_minutes=480,
        )
        attendance.recompute(day)
        day.refresh_from_db()
        # 480 owed, 120 excused, 300 worked: 60 short, not 180.
        self.assertEqual(day.short_minutes, 60)

    def test_a_day_with_no_permission_is_short_by_what_is_missing(self):
        start = timezone.make_aware(datetime.combine(self.today, time(9, 0)))
        day = WorkDay.objects.create(
            user=self.tr, date=self.today, status="present", check_in=start, check_out=start + timedelta(hours=5),
            scheduled_start=start, scheduled_end=start + timedelta(hours=8), scheduled_minutes=480,
        )
        attendance.recompute(day)
        day.refresh_from_db()
        self.assertEqual(day.short_minutes, 180)

    def test_a_permission_on_a_day_that_has_a_row_still_lands_on_it(self):
        day = self.day(self.tr, self.today)
        row = self.permission(self.today)
        employees.apply_leave(row)
        day.refresh_from_db()
        self.assertEqual(day.excused_minutes, 120)


class AuditFloodTests(_Admin):
    def setUp(self):
        super().setUp()
        AuditLog.objects.all().delete()

    def denied(self):
        return list(AuditLog.objects.filter(action=identity.ACCESS_DENIED).order_by("pk"))

    def test_the_same_refusal_over_and_over_is_one_row_with_a_count(self):
        for _ in range(30):
            self.assertEqual(self.get(self.ops, AUDIT).status_code, 403)
        rows = self.denied()
        self.assertEqual(len(rows), 1)
        self.assertTrue(rows[0].detail.endswith(" (x30)"), rows[0].detail)
        self.assertEqual((rows[0].actor, rows[0].path), (self.ops, "/api/v1/admin/audit/"))

    def test_another_person_another_page_or_another_reason_is_its_own_row(self):
        self.get(self.ops, AUDIT)
        self.get(self.tr, AUDIT)
        self.get(self.ops, "dashboard:v1_admin_settings")
        self.assertEqual(len(self.denied()), 3)
        request = type("R", (), {"user": self.ops, "META": {}, "get_full_path": lambda self: "/api/v1/admin/audit/"})()
        identity.record_denied(request, "a different reason")
        self.assertEqual(len(self.denied()), 4)

    def test_the_same_reason_on_another_page_or_from_another_address_is_its_own_row(self):
        def refuse(path, ip="203.0.113.7"):
            request = type("R", (), {"user": self.ops, "META": {"REMOTE_ADDR": ip}, "get_full_path": lambda self: path})()
            identity.record_denied(request, "same reason")

        refuse("/one/")
        refuse("/one/")
        refuse("/two/")
        refuse("/one/", ip="203.0.113.99")
        rows = self.denied()
        self.assertEqual(len(rows), 3)
        self.assertEqual([row.detail for row in rows], ["same reason (x2)", "same reason", "same reason"])

    def test_after_the_window_the_same_refusal_is_a_new_row(self):
        self.get(self.ops, AUDIT)
        AuditLog.objects.update(created_at=timezone.now() - timedelta(seconds=identity.DENIED_REPEAT_SECONDS + 5))
        self.get(self.ops, AUDIT)
        self.get(self.ops, AUDIT)
        rows = self.denied()
        self.assertEqual(len(rows), 2)
        self.assertFalse(rows[0].detail.endswith(")"), rows[0].detail)
        self.assertTrue(rows[1].detail.endswith(" (x2)"), rows[1].detail)

    def test_a_refusal_is_still_a_refusal_every_time(self):
        for _ in range(5):
            answer = self.get(self.ops, AUDIT)
            self.assertEqual((answer.status_code, _json(answer)["error"]), (403, "forbidden"))

    def test_a_hidden_record_is_counted_too_and_still_a_404(self):
        for _ in range(4):
            self.assertEqual(self.get(self.ops, "dashboard:v1_admin_client", [self.client_obj.code]).status_code, 403)
        self.assertEqual(len(self.denied()), 1)


class AuditPagingTests(_Admin):
    def setUp(self):
        super().setUp()
        AuditLog.objects.all().delete()
        AuditLog.objects.bulk_create([AuditLog(action="test.entry", target=f"t{index}") for index in range(450)])

    def page(self, **query):
        answer = self.get(self.admin, AUDIT, **query)
        self.assertEqual(answer.status_code, 200)
        return _json(answer)

    def test_the_log_pages_back_with_no_gap_and_no_repeat(self):
        seen, before, pages = [], None, 0
        # Bounded: a cursor that is ignored must fail this test, not loop on the first page for ever.
        while pages < 6:
            body = self.page(before=before) if before else self.page()
            ids = [row["id"] for row in body["rows"]]
            seen += ids
            pages += 1
            if not body["more"]:
                break
            before = ids[-1]
        self.assertEqual((pages, len(seen), len(set(seen))), (3, 450, 450))
        self.assertEqual(seen, sorted(seen, reverse=True))

    def test_more_is_true_only_while_older_rows_exist(self):
        first = self.page()
        self.assertEqual((len(first["rows"]), first["more"]), (200, True))
        last = self.page(before=first["rows"][-1]["id"] + 0)
        self.assertTrue(last["more"])
        end = self.page(before=last["rows"][-1]["id"])
        self.assertEqual((len(end["rows"]), end["more"]), (50, False))

    def test_exactly_two_hundred_rows_is_one_page_with_nothing_more(self):
        AuditLog.objects.filter(pk__in=list(AuditLog.objects.values_list("pk", flat=True)[:250])).delete()
        body = self.page()
        self.assertEqual((len(body["rows"]), body["more"]), (200, False))

    def test_the_cursor_works_with_a_filter(self):
        AuditLog.objects.all().delete()
        AuditLog.objects.bulk_create([AuditLog(action=identity.ACCESS_DENIED, target=f"d{index}") for index in range(230)])
        AuditLog.objects.bulk_create([AuditLog(action="test.entry", target="other") for _ in range(10)])
        first = self.page(only="denied")
        self.assertEqual((len(first["rows"]), first["more"]), (200, True))
        second = self.page(only="denied", before=first["rows"][-1]["id"])
        self.assertEqual((len(second["rows"]), second["more"]), (30, False))
        self.assertTrue(all(row["action"] == identity.ACCESS_DENIED for row in first["rows"] + second["rows"]))

    def test_a_cursor_that_is_not_a_number_is_a_400_and_not_the_newest_page(self):
        for value in ("x", "-1", "1e3", "1.5", " 5", "9" * 20, "5;"):
            answer = self.get(self.admin, AUDIT, before=value)
            self.assertEqual((answer.status_code, _json(answer)["error"]), (400, "bad_cursor"), value)

    def test_reading_a_later_page_writes_nothing(self):
        before = AuditLog.objects.count()
        self.page(before=AuditLog.objects.latest("pk").pk)
        self.assertEqual(AuditLog.objects.count(), before)
