"""The orders the help assistant can carry out for the owner.

What is held here, in the order it matters:

* it works for the owner and nobody else, and only while the owner has switched it on (and the AI is there to read the order);
* the model proposes and the server decides: a person is found by name in the database, never by an id the model wrote, every
  value is checked, and the card the owner presses is worded by the server from those checked values;
* nothing runs until the owner confirms, and it runs once;
* it goes through the real door, so what the door refuses the order refuses, and what the door writes down is written down;
* a deduction is only recorded, waiting for approval - the assistant approves no money.
"""

import json
from datetime import date, timedelta
from unittest import mock

from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from . import helpactions, helpbot, services
from .models import (
    AppSettings, AuditLog, Client, ClientRequirement, HelpAction, HelpQuestion, LeaveRequest, LeaveStatus, Role,
    ScheduleOverride, ShiftTemplate, Task, TaskStatus, User, Violation,
)

TODAY = timezone.localdate()


def _order(name, **params):
    """What the model replies when it prepares an order."""
    return json.dumps({"answer": "تم التنفيذ بنجاح", "guides": [], "found": True, "action": {"name": name, "params": params}})


class _Owner(TestCase):
    def setUp(self):
        make = lambda name, role, **kw: User.objects.create_user(name, password="pw", role=role, first_name=kw.pop("first", ""), last_name=kw.pop("last", ""), **kw)
        self.admin = make("owner_one", Role.ADMIN)
        self.other_admin = make("owner_two", Role.ADMIN)
        self.ops = make("ops_person", Role.OPERATION, first="Omar", last="Operation")
        self.lead = make("lead_person", Role.TEAM_LEAD, first="Laila", last="Leader")
        self.tr = make("tr_person", Role.TRANSLATOR, first="Tarek", last="Translator", team_lead=self.lead)
        self.tr2 = make("tr_two", Role.TRANSLATOR, first="Tamer", last="Translator")
        self.hr = make("hr_person", Role.HR)
        self.accounting = make("acc_person", Role.ACCOUNTING)
        self.sales = make("sales_person", Role.SALES, first="Sara", last="Sales")
        self.reviewer = make("rev_person", Role.REVIEWER)
        self.everyone = [self.admin, self.ops, self.lead, self.tr, self.hr, self.accounting, self.sales, self.reviewer]
        self.client_obj = Client.objects.create(name="ACME Secret Ltd", phone="+201001234567", email="boss@acme-secret.example")
        self.switch(ai=True, orders=True)
        # The limit on questions a minute has its own test (tests_helpbot); here a test asks as often as it needs to.
        for name in ("ASKS_PER_MINUTE", "AI_PER_HOUR"):
            patcher = mock.patch.object(helpbot, name, 10_000)
            patcher.start()
            self.addCleanup(patcher.stop)

    def switch(self, ai=True, orders=True, key="sk-test-key-1234567890"):
        conf = AppSettings.load()
        conf.helpbot_ai_enabled = ai
        conf.helpbot_actions_enabled = orders
        conf.claude_api_key = key
        conf.save()

    def sign_in(self, who=None):
        self.client.force_login(who or self.admin)
        return who or self.admin

    def post(self, name, body=None, **kwargs):
        return self.client.post(reverse(f"dashboard:{name}", kwargs=kwargs or None), json.dumps(body or {}), content_type="application/json")

    def ask(self, question, reply, who=None, **extra):
        """The owner asks; the model (mocked) answers with ``reply``. Returns the door's answer as JSON."""
        self.sign_in(who)
        with mock.patch.object(helpbot, "_call_claude", return_value=reply) as call:
            response = self.post("v1_help_ask", {"question": question, "lang": "ar", **extra})
        self.call = call
        return response.json()

    def press(self, order_id, lang="ar"):
        return self.post("v1_help_order_run", {"lang": lang}, pk=order_id)

    def prepare_and_run(self, name, **params):
        data = self.ask("اعمل كذا", _order(name, **params))
        self.assertIsNotNone(data["order"], data)
        response = self.press(data["order"]["id"])
        self.assertEqual(response.status_code, 200, response.content)
        return data, response.json()


# ----------------------------------------------------------------------------------------------------------------------
# Who may give orders
# ----------------------------------------------------------------------------------------------------------------------

class WhoMayTests(_Owner):
    def test_only_the_owner_with_both_switches_and_a_key(self):
        conf = AppSettings.load()
        self.assertTrue(helpactions.available(conf, self.admin))
        for person in self.everyone[1:]:
            self.assertFalse(helpactions.available(conf, person), person.role)
        for ai, orders, key in ((False, True, "sk-x" * 5), (True, False, "sk-x" * 5), (True, True, "")):
            self.switch(ai, orders, key)
            self.assertFalse(helpactions.available(AppSettings.load(), self.admin), (ai, orders, key))

    def test_a_superuser_is_the_owner_whatever_their_role(self):
        chief = User.objects.create_user("chief", password="pw", role=Role.OPERATION, is_superuser=True)
        self.assertTrue(helpactions.available(AppSettings.load(), chief))

    def test_the_switch_is_off_by_default(self):
        self.assertFalse(User.objects.model._meta.app_config.get_model("AppSettings").objects.none().exists())
        fresh = AppSettings()
        self.assertFalse(fresh.helpbot_actions_enabled)
        self.assertFalse(fresh.helpbot_ai_enabled)

    def test_the_door_tells_only_the_owner_that_orders_are_on(self):
        for person in self.everyone:
            self.sign_in(person)
            data = self.client.get(reverse("dashboard:v1_help")).json()
            self.assertEqual(data["orders"], person.role == Role.ADMIN, person.role)
        self.switch(orders=False)
        self.sign_in(self.admin)
        self.assertFalse(self.client.get(reverse("dashboard:v1_help")).json()["orders"])

    def test_the_orders_are_in_the_prompt_for_the_owner_alone(self):
        for person in self.everyone:
            self.ask("ازاي اسجل حضور", json.dumps({"answer": "x", "guides": [], "found": True}), person)
            system = self.call.call_args.args[1]
            with self.subTest(role=person.role):
                self.assertEqual("ORDERS:" in system, person.role == Role.ADMIN)
                self.assertEqual("shift.create" in system, person.role == Role.ADMIN)

    def test_a_model_that_proposes_an_order_to_someone_else_gets_nothing_done(self):
        # Even if the model were talked into it, an order is prepared for nobody but the owner.
        for person in self.everyone[1:]:
            data = self.ask("اعمل شيفت", _order("shift.create", start="09:07", end="17:43"), person)
            with self.subTest(role=person.role):
                self.assertIsNone(data["order"])
                self.assertEqual(data["source"], "ai")
        self.assertEqual(HelpAction.objects.count(), 0)

    def test_with_the_switch_off_an_order_in_the_reply_is_ignored(self):
        self.switch(orders=False)
        data = self.ask("اعمل شيفت", _order("shift.create", start="09:07", end="17:43"))
        self.assertIsNone(data["order"])
        self.assertNotIn("ORDERS:", self.call.call_args.args[1])
        self.assertEqual(HelpAction.objects.count(), 0)

    def test_nobody_but_the_owner_can_press_run_or_cancel(self):
        data = self.ask("اعمل شيفت", _order("shift.create", start="09:07", end="17:43"))
        order_id = data["order"]["id"]
        for person in self.everyone[1:]:
            self.sign_in(person)
            self.assertEqual(self.press(order_id).status_code, 403, person.role)
            self.assertEqual(self.post("v1_help_order_cancel", pk=order_id).status_code, 403, person.role)
        self.client.logout()
        self.assertEqual(self.press(order_id).status_code, 401)
        self.assertEqual(HelpAction.objects.get().status, "pending")
        self.assertEqual(ShiftTemplate.objects.filter(start_time="09:07").count(), 0)

    def test_another_owners_order_is_not_found(self):
        data = self.ask("اعمل شيفت", _order("shift.create", start="09:07", end="17:43"))
        self.sign_in(self.other_admin)
        self.assertEqual(self.press(data["order"]["id"]).status_code, 404)
        self.assertEqual(self.post("v1_help_order_cancel", pk=data["order"]["id"]).status_code, 404)
        self.assertEqual(HelpAction.objects.get().status, "pending")


# ----------------------------------------------------------------------------------------------------------------------
# The model proposes, the server decides
# ----------------------------------------------------------------------------------------------------------------------

class ServerDecidesTests(_Owner):
    def test_the_card_is_worded_by_the_server_not_by_the_model(self):
        data = self.ask("اعمل شيفت", _order("shift.create", title="الصبح", start="09:07", end="17:43", break_minutes=30))
        self.assertEqual(data["source"], "action")
        self.assertNotIn("تم التنفيذ", data["answer"])
        card = data["order"]
        self.assertIn("الصبح", card["summary"])
        self.assertIn("9:07", card["summary"])
        self.assertIn("5:43", card["summary"])
        self.assertIn("30", card["summary"])
        self.assertFalse(card["danger"])
        self.assertGreater(card["expires_in"], 0)

    def test_preparing_runs_nothing(self):
        self.ask("اعمل شيفت", _order("shift.create", start="09:07", end="17:43"))
        self.assertEqual(ShiftTemplate.objects.filter(start_time="09:07:00").count(), 0)
        row = HelpAction.objects.get()
        self.assertEqual((row.status, row.name, row.user), ("pending", "shift.create", self.admin))

    def test_an_unknown_order_is_refused_in_words(self):
        data = self.ask("امسح كل حاجة", _order("db.drop_everything"))
        self.assertIsNone(data["order"])
        self.assertIn("مش من الأوامر", data["answer"])
        self.assertEqual(HelpAction.objects.count(), 0)

    def test_only_the_orders_own_parameters_are_read(self):
        # "status" and "user" are not parameters of a deduction: the deduction is still only recorded, waiting.
        data = self.ask("اخصم", _order("violation.create", employee="Tarek Translator", days=1, reason="تأخير",
                                       status="approved", user=self.admin.pk, created_by=self.admin.pk))
        self.assertEqual(self.press(data["order"]["id"]).status_code, 200)
        row = Violation.objects.get()
        self.assertEqual((row.status, row.user), ("pending", self.tr))
        self.assertIsNone(row.approved_by)

    def test_a_person_is_found_by_name_never_by_an_id(self):
        data = self.ask("اخصم", _order("violation.create", employee=str(self.tr.pk), days=1, reason="x"))
        self.assertIsNone(data["order"])
        self.assertIn("مفيش موظف", data["answer"])
        data = self.ask("اخصم", _order("violation.create", employee={"id": self.tr.pk}, days=1, reason="x"))
        self.assertIsNone(data["order"])

    def test_names_are_matched_the_way_people_write_them(self):
        for written in ("Tarek Translator", "tarek translator", "tr_person", "Tarek", "المترجم Tarek"):
            data = self.ask("اخصم", _order("violation.create", employee=written, days=1, reason="x"))
            with self.subTest(written=written):
                self.assertIsNotNone(data["order"], data)
                self.assertIn("Tarek", data["order"]["summary"])

    def test_two_people_who_fit_are_not_guessed_between(self):
        User.objects.filter(pk__in=(self.tr.pk, self.tr2.pk)).update(last_name="Hassan")
        data = self.ask("اخصم", _order("violation.create", employee="Hassan", days=1, reason="x"))
        self.assertIsNone(data["order"])
        self.assertIn("Tarek", data["answer"])
        self.assertIn("Tamer", data["answer"])

    def test_an_arabic_name_is_found_whichever_way_it_is_spelled(self):
        self.tr2.first_name, self.tr2.last_name = "أحمد", "إبراهيم"
        self.tr2.save()
        for written in ("احمد ابراهيم", "أحمد إبراهيم", "احمد"):
            data = self.ask("اخصم", _order("violation.create", employee=written, days=1, reason="x"))
            self.assertIsNotNone(data["order"], written)

    def test_the_owner_cannot_be_the_target_of_an_order(self):
        for name in ("owner_one", "owner_two"):
            data = self.ask("وقف", _order("employee.set_active", employee=name, active=False))
            self.assertIsNone(data["order"], name)

    def test_an_order_names_the_roles_it_may_touch(self):
        # A deduction is for a translator; an address is for operation or Sales; a leader is a team leader.
        self.assertIsNone(self.ask("اخصم", _order("violation.create", employee="Omar", days=1, reason="x"))["order"])
        self.assertIsNone(self.ask("عنوان", _order("employee.mail_alias", employee="Tarek", address="a@b.co"))["order"])
        self.assertIsNone(self.ask("ليدر", _order("task.assign_lead", task="1", leader="Tarek"))["order"])

    def test_a_value_that_does_not_hold_is_refused_before_anything_is_kept(self):
        bad = [
            ("shift.create", dict(start="25:00", end="17:00")),
            ("shift.create", dict(start="9", end="17:00")),
            ("shift.create", dict(start="09:07", end="17:43", break_minutes=999)),
            ("shift.create", dict(start="09:07", end="17:43", break_minutes="abc")),
            ("shift.create", dict(end="17:00")),
            ("violation.create", dict(employee="Tarek", days="NaN", reason="x")),
            ("violation.create", dict(employee="Tarek", days="Infinity", reason="x")),
            ("violation.create", dict(employee="Tarek", days=31, reason="x")),
            ("violation.create", dict(employee="Tarek", days=-1, reason="x")),
            ("violation.create", dict(employee="Tarek", days=1)),
            ("violation.create", dict(employee="Tarek", reason="x")),
            ("violation.create", dict(employee="Tarek", days=1, reason="x", kind="free_money")),
            ("violation.create", dict(employee="Tarek", days=1, reason="x" * 251)),
            ("violation.create", dict(employee="Tarek", days=1, reason="x", date="yesterday")),
            ("violation.create", dict(employee="Tarek", days=1, reason="x", date=(TODAY - timedelta(days=900)).isoformat())),
            ("day.override", dict(employee="Tarek", date=TODAY.isoformat())),
            ("day.override", dict(employee="Tarek", date=TODAY.isoformat(), day_off="yes")),
            ("leave.decide", dict(employee="Tarek", decision="maybe")),
            ("task.cancel", dict(task="TSK-99999")),
            ("task.cancel", dict(task="no such")),
            ("client.requirement", dict(client="CL-9999", text="x")),
            ("client.requirement", dict(client=self.client_obj.code, text="")),
            ("employee.mail_alias", dict(employee="Omar", address="not an address")),
        ]
        for name, params in bad:
            data = self.ask("اعمل", _order(name, **params))
            with self.subTest(name=name, params=params):
                self.assertIsNone(data["order"], data)
                self.assertEqual(data["source"], "ai")
        self.assertEqual(HelpAction.objects.count(), 0)

    def test_what_the_model_may_not_do_with_a_state_it_cannot_see(self):
        delivered = self._task(TaskStatus.DELIVERED)
        self.assertIsNone(self.ask("الغي", _order("task.cancel", task=delivered.code))["order"])
        busy = self._task(TaskStatus.IN_PROGRESS)
        self.assertIsNone(self.ask("ابعت", _order("task.assign_lead", task=busy.code, leader="Laila"))["order"])

    def test_one_order_waits_at_a_time(self):
        first = self.ask("اعمل شيفت", _order("shift.create", start="09:07", end="17:43"))["order"]["id"]
        second = self.ask("اعمل شيفت", _order("shift.create", start="10:07", end="18:43"))["order"]["id"]
        self.assertEqual(HelpAction.objects.get(pk=first).status, "cancelled")
        self.assertEqual(self.press(first).status_code, 409)
        self.assertEqual(HelpAction.objects.get(pk=second).status, "pending")

    def test_the_log_says_an_order_was_prepared(self):
        self.ask("اعمل شيفت", _order("shift.create", start="09:07", end="17:43"))
        row = HelpQuestion.objects.get()
        self.assertEqual((row.source, row.guides), ("action", "shift.create"))

    def test_no_client_identity_is_in_what_an_order_says_or_keeps(self):
        data = self.ask("ضيف متطلب", _order("client.requirement", client=self.client_obj.code, kind="rule", text="Use British spelling"))
        self.assertIn(self.client_obj.code, data["order"]["summary"])
        self.press(data["order"]["id"])
        everything = json.dumps(list(HelpAction.objects.values()), default=str) + json.dumps(data, ensure_ascii=False)
        for secret in ("ACME", "acme-secret", "1234567"):
            self.assertNotIn(secret, everything)

    def _task(self, status):
        task = Task.objects.create(client=self.client_obj, title="Doc", created_by=self.ops, status=status)
        return task


# ----------------------------------------------------------------------------------------------------------------------
# The owner confirms
# ----------------------------------------------------------------------------------------------------------------------

class ConfirmTests(_Owner):
    def test_it_runs_once(self):
        order = self.ask("اعمل شيفت", _order("shift.create", start="09:07", end="17:43"))["order"]["id"]
        first = self.press(order)
        self.assertEqual(first.status_code, 200)
        self.assertEqual(first.json()["done"], True)
        again = self.press(order)
        self.assertEqual(again.status_code, 409)
        self.assertEqual(ShiftTemplate.objects.filter(start_time="09:07").count(), 1)

    def test_a_second_press_while_the_first_is_still_running_does_nothing(self):
        # Two requests at once: while the door is working for the first, the second must find the order already taken.
        order = self.ask("اعمل شيفت", _order("shift.create", start="09:07", end="17:43"))["order"]["id"]
        real_call, inner = helpactions._call, []

        def slow_door(request, user, call):
            try:
                helpactions.run(request, user, order, "ar")
            except helpactions.NotAllowed as refusal:
                inner.append(refusal.code)
            return real_call(request, user, call)

        with mock.patch.object(helpactions, "_call", side_effect=slow_door):
            self.assertEqual(self.press(order).status_code, 200)
        self.assertEqual(inner, ["done"])
        self.assertEqual(ShiftTemplate.objects.filter(start_time="09:07").count(), 1)

    def test_it_does_not_run_late(self):
        order = self.ask("اعمل شيفت", _order("shift.create", start="09:07", end="17:43"))["order"]["id"]
        HelpAction.objects.filter(pk=order).update(created_at=timezone.now() - helpactions.LIFETIME - timedelta(seconds=5))
        self.assertEqual(self.press(order).status_code, 409)
        self.assertEqual(HelpAction.objects.get().status, "cancelled")
        self.assertEqual(ShiftTemplate.objects.filter(start_time="09:07").count(), 0)

    def test_no_does_not_run(self):
        order = self.ask("اعمل شيفت", _order("shift.create", start="09:07", end="17:43"))["order"]["id"]
        self.assertEqual(self.post("v1_help_order_cancel", pk=order).status_code, 200)
        self.assertEqual(self.press(order).status_code, 409)
        self.assertEqual(ShiftTemplate.objects.filter(start_time="09:07").count(), 0)
        self.assertEqual(self.post("v1_help_order_cancel", pk=order).status_code, 404)

    def test_turning_the_option_off_stops_an_order_already_prepared(self):
        order = self.ask("اعمل شيفت", _order("shift.create", start="09:07", end="17:43"))["order"]["id"]
        for ai, orders in ((True, False), (False, True)):
            self.switch(ai, orders)
            self.sign_in()
            response = self.press(order)
            self.assertEqual((response.status_code, response.json()["error"]), (403, "orders_off"))
        self.assertEqual(HelpAction.objects.get().status, "pending")
        self.assertEqual(ShiftTemplate.objects.filter(start_time="09:07").count(), 0)

    def test_a_bad_press_is_refused(self):
        order = self.ask("اعمل شيفت", _order("shift.create", start="09:07", end="17:43"))["order"]["id"]
        url = reverse("dashboard:v1_help_order_run", kwargs={"pk": order})
        self.assertEqual(self.client.post(url, "x", content_type="application/json").status_code, 400)
        self.assertEqual(self.client.get(url).status_code, 405)
        self.assertEqual(HelpAction.objects.get().status, "pending")

    def test_too_many_runs_a_minute_are_refused(self):
        HelpAction.objects.bulk_create([
            HelpAction(user=self.admin, name="shift.create", status="done", finished_at=timezone.now())
            for _ in range(helpactions.RUNS_PER_MINUTE)
        ])
        order = self.ask("اعمل شيفت", _order("shift.create", start="09:07", end="17:43"))["order"]["id"]
        self.assertEqual(self.press(order).status_code, 429)
        self.assertEqual(ShiftTemplate.objects.filter(start_time="09:07").count(), 0)

    def test_a_door_that_refuses_leaves_the_order_refused_and_says_why(self):
        task = Task.objects.create(client=self.client_obj, title="Doc", created_by=self.ops, status=TaskStatus.NEW)
        order = self.ask("الغي", _order("task.cancel", task=task.code))["order"]["id"]
        # Delivered between the card and the press: the service refuses and the order says so.
        Task.objects.filter(pk=task.pk).update(status=TaskStatus.DELIVERED)
        response = self.press(order)
        self.assertEqual(response.status_code, 200)
        self.assertFalse(response.json()["done"])
        self.assertTrue(response.json()["message"])
        row = HelpAction.objects.get()
        self.assertEqual(row.status, "failed")
        self.assertFalse(row.result["ok"])
        task.refresh_from_db()
        self.assertEqual(task.status, TaskStatus.DELIVERED)

    def test_every_order_that_ran_is_in_the_audit_log(self):
        self.prepare_and_run("shift.create", title="الصبح", start="09:07", end="17:43")
        row = AuditLog.objects.get(action="help.action")
        self.assertEqual((row.actor, row.target), (self.admin, "shift.create"))
        self.assertTrue(row.detail.startswith("done"))
        # The door wrote its own line as well: the order is the click's equal.
        self.assertTrue(AuditLog.objects.filter(action="schedule.template.save").exists())


# ----------------------------------------------------------------------------------------------------------------------
# What each order does, through the real door
# ----------------------------------------------------------------------------------------------------------------------

class EachOrderTests(_Owner):
    def test_a_shift_is_made(self):
        _data, done = self.prepare_and_run("shift.create", title="شيفت الصبح", start="09:07", end="17:43", break_minutes=30)
        self.assertTrue(done["done"])
        shift = ShiftTemplate.objects.get(name_ar="شيفت الصبح")
        self.assertEqual((str(shift.start_time), str(shift.end_time), shift.break_minutes, shift.is_active), ("09:07:00", "17:43:00", 30, True))

    def test_a_shift_with_no_name_is_named_by_its_hours(self):
        self.prepare_and_run("shift.create", start="14:07", end="22:43")
        self.assertEqual(ShiftTemplate.objects.get(start_time="14:07").name, "2:07 PM - 10:43 PM")

    def test_a_shift_the_form_refuses_is_refused_in_the_forms_words(self):
        # Same start and end: the shift form's own rule, not one written here.
        data = self.ask("اعمل شيفت", _order("shift.create", start="09:07", end="09:07"))
        response = self.press(data["order"]["id"])
        self.assertFalse(response.json()["done"])
        self.assertIn("بداية الشيفت ونهايته", response.json()["message"])
        self.assertEqual(ShiftTemplate.objects.filter(start_time="09:07").count(), 0)

    def test_a_deduction_is_recorded_waiting_for_approval_and_never_approved(self):
        data, done = self.prepare_and_run("violation.create", employee="Tarek", kind="quality", days=1.5, reason="غلط في الأرقام")
        self.assertIn("مستنية الاعتماد", data["order"]["summary"])
        row = Violation.objects.get()
        self.assertEqual(
            (row.user, row.kind, str(row.penalty_days), str(row.penalty_amount), row.reason, row.status, row.created_by, row.date),
            (self.tr, "quality", "1.50", "0.00", "غلط في الأرقام", "pending", self.admin, TODAY),
        )
        self.assertIsNone(row.approved_by)
        self.assertIn("الاعتماد", done["message"])

    def test_a_deduction_by_amount_and_for_a_day_in_the_past(self):
        day = TODAY - timedelta(days=3)
        self.prepare_and_run("violation.create", employee="Tarek", amount="250.5", reason="كذا", date=day.isoformat())
        row = Violation.objects.get()
        self.assertEqual((str(row.penalty_amount), str(row.penalty_days), row.date), ("250.50", "0.00", day))

    def test_a_day_off_is_given(self):
        day = TODAY + timedelta(days=3)
        self.prepare_and_run("day.override", employee="Omar", date=day.isoformat(), day_off=True, reason="ظرف")
        row = ScheduleOverride.objects.get()
        self.assertEqual((row.user, row.date, row.is_day_off, row.reason, row.created_by), (self.ops, day, True, "ظرف", self.admin))

    def test_other_hours_on_one_day(self):
        day = TODAY + timedelta(days=2)
        self.prepare_and_run("day.override", employee="Sara", date=day.isoformat(), start="16:00", end="20:00")
        row = ScheduleOverride.objects.get()
        self.assertEqual((row.user, row.is_day_off, str(row.start_time), str(row.end_time)), (self.sales, False, "16:00:00", "20:00:00"))

    def test_a_leave_request_is_decided(self):
        leave = LeaveRequest.objects.create(user=self.tr, start_date=TODAY + timedelta(days=5), end_date=TODAY + timedelta(days=6), reason="x")
        _data, done = self.prepare_and_run("leave.decide", employee="Tarek", decision="reject", note="الشغل كتير")
        leave.refresh_from_db()
        self.assertEqual((leave.status, leave.decision_note), (LeaveStatus.REJECTED, "الشغل كتير"))
        self.assertTrue(done["done"])

    def test_a_leave_request_is_found_for_the_person_or_the_order_is_refused(self):
        self.assertIsNone(self.ask("وافق", _order("leave.decide", employee="Tarek", decision="approve"))["order"])
        for offset in (5, 9):
            LeaveRequest.objects.create(user=self.tr, start_date=TODAY + timedelta(days=offset), end_date=TODAY + timedelta(days=offset))
        data = self.ask("وافق", _order("leave.decide", employee="Tarek", decision="approve"))
        self.assertIsNone(data["order"])
        self.assertIn("أكتر من طلب", data["answer"])

    def test_a_task_is_cancelled_and_the_card_is_red(self):
        task = Task.objects.create(client=self.client_obj, title="Doc", created_by=self.ops, status=TaskStatus.NEW)
        data = self.ask("الغي", _order("task.cancel", task=task.code.lower(), reason="العميل لغى"))
        self.assertTrue(data["order"]["danger"])
        self.press(data["order"]["id"])
        task.refresh_from_db()
        self.assertEqual(task.status, TaskStatus.CANCELLED)
        self.assertTrue(AuditLog.objects.filter(action="task.cancel", target=task.code).exists())

    def test_a_task_is_sent_to_a_team_leader(self):
        task = Task.objects.create(client=self.client_obj, title="Doc", created_by=self.ops, status=TaskStatus.NEW)
        number = str(int(task.code.split("-")[1]))
        self.prepare_and_run("task.assign_lead", task=number, leader="Laila")
        task.refresh_from_db()
        self.assertEqual(task.status, TaskStatus.AWAITING_LEAD)

    def test_a_client_requirement_is_added(self):
        self.prepare_and_run("client.requirement", client=self.client_obj.code.lower(), kind="dislike", text="No abbreviations")
        row = ClientRequirement.objects.get()
        self.assertEqual((row.client, row.kind, row.text, row.author), (self.client_obj, "dislike", "No abbreviations", self.admin))

    def test_an_account_is_switched_off_and_on_again(self):
        data, _done = self.prepare_and_run("employee.set_active", employee="Omar", active=False)
        self.assertTrue(data["order"]["danger"])
        self.ops.refresh_from_db()
        self.assertFalse(self.ops.is_active)
        # A person who is off is still found, to be switched on again.
        self.prepare_and_run("employee.set_active", employee="Omar", active=True)
        self.ops.refresh_from_db()
        self.assertTrue(self.ops.is_active)

    def test_a_mail_address_is_given(self):
        conf = AppSettings.load()
        conf.mail_aliases = "omar@company.example\nsara@company.example"
        conf.save()
        self.prepare_and_run("employee.mail_alias", employee="Omar", address="Omar@Company.example")
        self.ops.refresh_from_db()
        self.assertEqual(self.ops.mail_alias, "omar@company.example")
        self.assertTrue(AuditLog.objects.filter(action="user.mail_alias").exists())

    def test_an_address_that_is_not_on_the_mailbox_is_refused_by_the_form(self):
        data = self.ask("عنوان", _order("employee.mail_alias", employee="Omar", address="stranger@elsewhere.example"))
        response = self.press(data["order"]["id"])
        self.assertFalse(response.json()["done"])
        self.ops.refresh_from_db()
        self.assertEqual(self.ops.mail_alias, "")

    def test_the_last_owner_cannot_be_switched_off_even_by_an_order(self):
        # The door's own guard stands: the order cannot do what the page could not. (No other owner may be named anyway.)
        data = self.ask("وقف", _order("employee.set_active", employee="owner_two", active=False))
        self.assertIsNone(data["order"])
        self.admin.refresh_from_db()
        self.assertTrue(self.admin.is_active)


class CatalogTests(TestCase):
    def test_every_order_is_whole(self):
        for name, action in helpactions.ACTIONS.items():
            with self.subTest(order=name):
                self.assertEqual(action.name, name)
                self.assertTrue(all(action.title) and action.about)
                self.assertTrue(action.params)
                for param in action.params:
                    self.assertTrue(all(param.label))
                    self.assertIn(param.kind, ("person", "text", "date", "time", "int", "number", "choice", "bool", "task", "client"))
                    if param.kind == "choice":
                        self.assertTrue(param.choices)
                    if param.kind in ("int", "number"):
                        self.assertIsNotNone(param.lo)
                        self.assertIsNotNone(param.hi)

    def test_every_order_goes_through_a_real_door(self):
        for name, action in helpactions.ACTIONS.items():
            # Build the request with plausible values and make sure the address exists and is a POST-only view.
            sample = {"employee": {"id": 1, "name": "x"}, "leader": {"id": 1, "name": "x"}, "task": {"code": "TSK-00001", "status": "new"},
                      "client": {"code": "CL-0001", "id": 1}, "title": "x", "source_lang": "en", "target_lang": "ar", "request": {"id": 1, "from": "2026-01-01", "to": "2026-01-02"},
                      "decision": "approve", "active": False, "address": "a@b.co", "text": "x", "kind": "rule", "reason": "x",
                      "start": "09:00", "end": "17:00", "date": "2026-01-01", "days": "1.00", "amount": "0.00",
                      "violation": {"id": 1, "date": "2026-01-01"}}
            call = action.call(sample)
            with self.subTest(order=name):
                path = reverse(f"dashboard:{call.url}", args=call.args)
                self.assertTrue(path.startswith(("/api/v1/", "/api/")))

    def test_the_prompt_names_every_order_and_its_parameters(self):
        text = helpactions.prompt_text()
        for name, action in helpactions.ACTIONS.items():
            self.assertIn(f"- {name}:", text)
            for param in action.params:
                self.assertIn(param.name, text)


class ReviewTests(_Owner):
    """What the review of 2026-10-06 found."""

    def test_a_value_that_looks_like_a_digit_but_is_not_one_is_refused_not_a_server_error(self):
        for params in (
            dict(start="09:07", end="17:43", break_minutes="\u00b2"),
            dict(start="09:07", end="17:43", break_minutes="--5"),
            dict(start="09:07", end="17:43", break_minutes="\u0663"),
            dict(start="09:3\u0660", end="17:43"),
            dict(start="\uff10\uff19:07", end="17:43"),
        ):
            reply = self.ask("اعمل شيفت", _order("shift.create", **params))
            with self.subTest(params=params):
                self.assertIsNone(reply["order"], reply)
                self.assertEqual(reply["source"], "ai")
        self.assertEqual(HelpAction.objects.count(), 0)

    def test_a_task_code_written_in_arabic_digits_is_the_same_code(self):
        task = Task.objects.create(client=self.client_obj, title="Doc", created_by=self.ops, status=TaskStatus.NEW)
        arabic = str.maketrans("0123456789", "\u0660\u0661\u0662\u0663\u0664\u0665\u0666\u0667\u0668\u0669")
        number = str(int(task.code.split("-")[1])).translate(arabic)
        card = self.ask("الغي", _order("task.cancel", task=f"TSK-{number}"))["order"]
        self.assertIn(task.code, card["summary"])

    def test_whatever_breaks_while_the_values_are_read_is_a_refusal_in_words(self):
        with mock.patch.object(helpactions, "check_values", side_effect=ValueError("boom")):
            reply = self.ask("اعمل شيفت", _order("shift.create", start="09:07", end="17:43"))
        self.assertIsNone(reply["order"])
        self.assertIn("مش مظبوطة", reply["answer"])
        self.assertEqual(HelpAction.objects.count(), 0)

    def test_the_deduction_card_says_the_date_and_the_kind(self):
        day = TODAY - timedelta(days=2)
        card = self.ask("اخصم", _order("violation.create", employee="Tarek", kind="unexcused", days=1, reason="غاب", date=day.isoformat()))["order"]
        self.assertIn(day.isoformat(), card["summary"])
        self.assertIn("غياب من غير إذن", card["summary"])
        english = self.ask("اخصم", _order("violation.create", employee="Tarek", kind="quality", days=1, reason="x"), lang="en")
        self.assertIsNotNone(english["order"])

    def test_the_requirement_card_says_the_kind_and_who_reads_it(self):
        card = self.ask("متطلب", _order("client.requirement", client=self.client_obj.code, kind="dislike", text="No abbreviations"))["order"]
        self.assertIn("مابيحبوش", card["summary"])
        self.assertIn("مترجم", card["summary"])

    def test_the_cancel_and_day_cards_say_the_reason_that_will_reach_other_people(self):
        task = Task.objects.create(client=self.client_obj, title="Doc", created_by=self.ops, status=TaskStatus.NEW)
        card = self.ask("الغي", _order("task.cancel", task=task.code, reason="السبب الفلاني"))["order"]
        self.assertIn("السبب الفلاني", card["summary"])
        self.assertIn("المترجم", card["summary"])
        day = (TODAY + timedelta(days=4)).isoformat()
        card = self.ask("اجازة", _order("day.override", employee="Omar", date=day, day_off=True, reason="ظرف عائلي"))["order"]
        self.assertIn("ظرف عائلي", card["summary"])
        # Without a reason the card has no empty "reason" line.
        card = self.ask("اجازة", _order("day.override", employee="Omar", date=day, day_off=True))["order"]
        self.assertNotIn("السبب", card["summary"])

    def test_a_username_that_is_also_the_start_of_another_name_is_asked_about(self):
        User.objects.create_user("ahmed", password="pw", role=Role.OPERATION, first_name="Ali", last_name="Mostafa")
        User.objects.create_user("asamir", password="pw", role=Role.OPERATION, first_name="Ahmed", last_name="Samir")
        reply = self.ask("وقف", _order("employee.set_active", employee="ahmed", active=False))
        self.assertIsNone(reply["order"])
        self.assertIn("Ali", reply["answer"])
        self.assertIn("Ahmed", reply["answer"])
        # The whole name is not a question.
        self.assertIsNotNone(self.ask("وقف", _order("employee.set_active", employee="Ahmed Samir", active=False))["order"])

    def test_an_answer_that_names_people_is_not_sent_back_as_conversation(self):
        User.objects.filter(pk__in=(self.tr.pk, self.tr2.pk)).update(last_name="Hassan")
        reply = self.ask("اخصم", _order("violation.create", employee="Hassan", days=1, reason="x"))
        self.assertIn("Tarek", reply["answer"])
        self.assertIs(reply["keep"], False)
        ordinary = self.ask("ازاي اسجل حضور", json.dumps({"answer": "x", "guides": [], "found": True}))
        self.assertIs(ordinary["keep"], True)

    def test_a_door_that_blew_up_is_not_reported_as_a_refusal_that_changed_nothing(self):
        order = self.ask("اعمل شيفت", _order("shift.create", start="09:07", end="17:43"))["order"]["id"]
        with mock.patch.object(helpactions, "_call", return_value=(500, {})):
            reply = self.press(order).json()
        self.assertFalse(reply["done"])
        self.assertIn("مش متأكد", reply["message"])
        self.assertNotIn("محصلش حاجة", reply["message"])


class OpenEmployeeTests(_Owner):
    def _open(self, name):
        return json.dumps({"answer": "x", "guides": [], "found": True, "open_employee": name})

    def test_the_owner_gets_the_button_to_the_named_file(self):
        data = self.ask("افتحلي ملف الموظف Tarek", self._open("Tarek"))
        self.assertEqual(data["open"]["path"], f"/hr/employees/{self.tr.pk}")
        self.assertIsNone(data["order"])
        self.assertFalse(data["keep"])

    def test_a_name_that_fits_no_one_opens_nothing(self):
        data = self.ask("افتحلي ملف Nobody", self._open("Nobody"))
        self.assertIsNone(data["open"])

    def test_two_who_fit_are_asked_about(self):
        data = self.ask("افتحلي ملف Translator", self._open("Translator"))
        self.assertIsNone(data["open"])

    def test_it_works_with_orders_switched_off(self):
        self.switch(ai=True, orders=False)
        data = self.ask("افتحلي ملف Tarek", self._open("Tarek"))
        self.assertEqual(data["open"]["path"], f"/hr/employees/{self.tr.pk}")

    def test_nobody_but_the_owner_is_given_it(self):
        data = self.ask("افتحلي ملف Tarek", self._open("Tarek"), who=self.hr)
        self.assertIsNone(data["open"])
        self.assertNotIn("open_employee", self.call.call_args.args[1])

    def test_the_owner_is_told_the_open_instruction(self):
        self.ask("افتحلي ملف Tarek", self._open("Tarek"))
        self.assertIn("open_employee", self.call.call_args.args[1])

    def test_the_log_of_a_client_edit_holds_the_boxes_not_the_values(self):
        from .models import AuditLog
        reply = _order("client.update", client=self.client_obj.code, email="new@secret.example")
        self.ask("عدل", reply, auto=True)
        detail = AuditLog.objects.filter(action="help.action", target="client.update").latest("pk").detail
        self.assertIn("email", detail)
        self.assertNotIn("secret.example", detail)


class RunAtOnceTests(_Owner):
    def auto(self, question, reply, who=None, **extra):
        return self.ask(question, reply, who=who, auto=True, **extra)

    def test_an_order_is_carried_out_without_a_press(self):
        before = ShiftTemplate.objects.count()
        data = self.auto("اعمل شيفت", _order("shift.create", start="09:07", end="17:43"))
        self.assertTrue(data["ran"]["done"], data)
        self.assertEqual(ShiftTemplate.objects.count(), before + 1)

    def test_without_the_flag_it_still_waits(self):
        data = self.ask("اعمل شيفت", _order("shift.create", start="09:07", end="17:43"))
        self.assertIsNone(data["ran"])
        self.assertIsNotNone(data["order"])

    def test_the_switch_off_runs_nothing(self):
        self.switch(ai=True, orders=False)
        data = self.auto("اعمل شيفت", _order("shift.create", start="09:07", end="17:43"))
        self.assertIsNone(data["order"])
        self.assertIsNone(data["ran"])

    def test_a_refusal_by_the_door_is_told(self):
        task = Task.objects.create(client=self.client_obj, title="t", status=TaskStatus.NEW)
        data = self.auto("الغي", _order("task.cancel", task=task.code))
        self.assertIn("done", data["ran"])

    def test_the_deadline_is_set(self):
        task = Task.objects.create(client=self.client_obj, title="t", status=TaskStatus.NEW)
        data = self.auto("ديدلاين", _order("task.deadline", task=task.code, days=2, hours=3))
        self.assertTrue(data["ran"]["done"], data)
        task.refresh_from_db()
        self.assertIsNotNone(task.deadline)

    def test_a_waiting_deduction_is_decided(self):
        from .models import ApprovalStatus, Violation
        row = Violation.objects.create(user=self.tr, date=timezone.localdate(), kind="manual", penalty_days="1.00", reason="x")
        data = self.auto("اعتمد", _order("violation.decide", employee="Tarek", decision="approve"))
        self.assertTrue(data["ran"]["done"], data)
        row.refresh_from_db()
        self.assertEqual(row.status, ApprovalStatus.APPROVED)

    def test_a_client_is_edited(self):
        data = self.auto("عدل", _order("client.update", client=self.client_obj.code, company="New Co"))
        self.assertTrue(data["ran"]["done"], data)
        self.client_obj.refresh_from_db()
        self.assertEqual(self.client_obj.company, "New Co")

    def test_an_edit_with_nothing_to_change_is_refused(self):
        data = self.auto("عدل", _order("client.update", client=self.client_obj.code))
        self.assertIsNone(data["ran"])
        self.assertIsNone(data["order"])


class MessageOrderTests(RunAtOnceTests):
    def test_a_message_reaches_the_colleague(self):
        from .models import ChatMessage
        data = self.auto("ابعت", _order("staff.message", employee="Tarek", text="اهلا"))
        self.assertTrue(data["ran"]["done"], data)
        self.assertTrue(ChatMessage.objects.filter(body="اهلا").exists())

    def test_the_owner_cannot_message_themselves(self):
        data = self.auto("ابعت", _order("staff.message", employee="owner_one", text="x"))
        self.assertIsNone(data["order"])


class TaskCreateOrderTests(RunAtOnceTests):
    def test_a_task_is_created_for_the_client(self):
        data = self.auto("اعمل تاسك", _order("task.create", client=self.client_obj.code, title="عقد", source_lang="English", target_lang="Arabic", days=2))
        self.assertTrue(data["ran"]["done"], data)
        task = Task.objects.get(title="عقد")
        self.assertEqual(task.client_id, self.client_obj.pk)
        self.assertIsNotNone(task.deadline)

    def test_a_task_needs_its_languages(self):
        data = self.auto("اعمل تاسك", _order("task.create", client=self.client_obj.code, title="عقد"))
        self.assertIsNone(data["order"])
