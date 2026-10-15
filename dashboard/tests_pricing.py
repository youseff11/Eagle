"""Part 4 (15/10/2026): the price list and its versions, the discount limits and their approval (``pricing.py``), and the
objection to a turned-down field visit (``b2c.appeal``).

Held here: a version is never changed and the newest is in force; a quotation keeps the version and price it was priced
against; a rate under the list counts as discount; beyond the maker's limit the quotation waits and is not sent; the
team's manager approves up to their limit, the owner beyond, nobody their own; a turned-down discount is changed and saved
again; an objection is once, and the owner decides it for good.
"""

import json
from decimal import Decimal

from django.urls import reverse

from . import b2c, pricing
from .models import AppSettings, AuditLog, FieldVisit, PriceList, Quotation, Role, User
from .tests_b2b import _B2b, _json
from .tests_b2c import NEAR, _B2c

FIGURES = {
    "source_lang": "english", "target_lang": "Arabic", "service": "translation", "unit": "words", "quantity": 1000,
    "rate": "0.10", "discount_percent": "0", "currency": "USD", "deadline": "", "payment_terms": "", "notes": "",
}
LIST = [
    {"service": "translation", "unit": "words", "currency": "USD", "pair": "EN>AR", "rate": "0.10"},
    {"service": "translation", "unit": "words", "currency": "USD", "pair": "", "rate": "0.12"},
]


class _Pricing(_B2b):
    def setUp(self):
        super().setUp()
        pricing.save_version(self.admin, LIST, "first")

    def make(self, user=None, **over):
        answer = self.post(user or self.sales, "v1_b2b_quotation_create", {**FIGURES, **over}, self.lead.pk)
        self.assertEqual(answer.status_code, 200, answer.content)
        return Quotation.objects.get(pk=_json(answer)["quotation"]["id"])

    def send(self, quote, user=None):
        return _json(self.post(user or self.sales, "v1_b2b_quotation_send", {}, quote.pk))

    def decide(self, user, quote, approved, note=""):
        return self.post(user, "v1_quote_discount", {"approved": approved, "note": note}, quote.pk)


class VersionTests(_Pricing):
    def test_the_doors_are_under_api_v1(self):
        self.assertEqual(reverse("dashboard:v1_price_list"), "/api/v1/b2b/price-list/")
        self.assertEqual(reverse("dashboard:v1_price_list_save"), "/api/v1/b2b/price-list/save/")
        self.assertEqual(reverse("dashboard:v1_price_list_limits"), "/api/v1/b2b/price-list/limits/")
        self.assertEqual(reverse("dashboard:v1_quote_discount", args=[3]), "/api/v1/b2b/quotations/3/discount/")
        self.assertEqual(reverse("dashboard:v1_b2c_visit_appeal", args=[3]), "/api/v1/b2c/visits/3/appeal/")

    def test_a_new_version_leaves_the_old_one_as_it_was(self):
        first = self.make()
        answer = _json(self.post(self.admin, "v1_price_list_save", {"note": "2027", "items": [{**LIST[0], "rate": "0.20"}]}))
        self.assertEqual(answer["list"]["version"], 2)
        old = _json(self.browser(self.sales).get(reverse("dashboard:v1_price_list"), {"version": 1}))
        self.assertEqual([item["rate"] for item in old["list"]["items"]], ["0.12", "0.1"])
        first.refresh_from_db()
        self.assertEqual((first.price_list.version, first.list_rate), (1, Decimal("0.1000")))
        self.assertEqual(self.make().price_list.version, 2)

    def test_only_the_owner_saves_the_list_and_the_limits(self):
        for user in (self.sales, self.manager, self.ops):
            self.assertIn(self.post(user, "v1_price_list_save", {"items": LIST}).status_code, (403,), user)
            self.assertEqual(self.post(user, "v1_price_list_limits", {"sales": "50", "manager": "60"}).status_code, 403)
        self.assertEqual(PriceList.objects.count(), 1)
        self.assertEqual(self.browser(self.sales).get(reverse("dashboard:v1_price_list")).status_code, 200)

    def test_a_bad_line_is_refused(self):
        bad = [
            ([{**LIST[0], "pair": "english to arabic"}], "bad_pair"),
            ([{**LIST[0], "rate": "0"}], "bad_rate"),
            ([LIST[0], LIST[0]], "twice"),
            ([{**LIST[0], "service": "magic"}], "bad_item"),
        ]
        for items, code in bad:
            self.assertEqual(_json(self.post(self.admin, "v1_price_list_save", {"items": items}))["error"], code)

    def test_the_pair_price_first_then_any_pair(self):
        self.assertEqual(self.make().list_rate, Decimal("0.1000"))
        other = self.make(target_lang="French")
        self.assertEqual(other.list_rate, Decimal("0.1200"))
        none = self.make(currency="EUR")
        self.assertIsNone(none.price_list)
        self.assertTrue(AuditLog.objects.filter(action="pricing.version").exists())


class DiscountTests(_Pricing):
    def test_within_the_limit_it_goes(self):
        quote = self.make(discount_percent="10")
        self.assertEqual((quote.effective_discount, quote.discount_state), (Decimal("10.00"), ""))

    def test_a_lower_rate_counts_as_discount(self):
        # 0.08 against a list price of 0.10 is 20% under the list, though the discount box says 0.
        quote = self.make(rate="0.08")
        self.assertEqual((quote.effective_discount, quote.discount_state), (Decimal("20.00"), "pending"))
        self.assertEqual(self.send(quote)["error"], "discount_waits")
        self.assertTrue(self.manager.notifications.filter(title_ar="خصم محتاج اعتمادك").exists())

    def test_the_manager_approves_up_to_their_limit_the_owner_beyond(self):
        within = self.make(rate="0.08")
        self.assertEqual(_json(self.decide(self.manager, within, True))["state"], "approved")
        self.assertTrue(self.send(within)["ok"])
        beyond = self.make(rate="0.05")
        self.assertEqual(beyond.effective_discount, Decimal("50.00"))
        self.assertEqual(self.decide(self.manager, beyond, True).status_code, 403)
        self.assertFalse(self.manager.notifications.filter(body_ar__contains=beyond.code).exists())
        self.assertEqual(_json(self.decide(self.admin, beyond, True))["state"], "approved")

    def test_the_maker_never_approves_their_own(self):
        quote = self.make(rate="0.08")
        self.assertEqual(self.decide(self.sales, quote, True).status_code, 403)
        quote.refresh_from_db()
        self.assertEqual(quote.discount_state, "pending")

    def test_turned_down_with_the_reason_then_changed(self):
        quote = self.make(rate="0.08")
        self.assertEqual(_json(self.decide(self.manager, quote, False))["error"], "needs_reason")
        self.assertEqual(_json(self.decide(self.manager, quote, False, "Too low"))["state"], "rejected")
        self.assertEqual(self.send(quote)["error"], "discount_rejected")
        self.assertTrue(self.sales.notifications.filter(title_ar="الخصم اترفض").exists())
        self.post(self.sales, "v1_b2b_quotation_save", {**FIGURES, "rate": "0.095"}, quote.pk)
        quote.refresh_from_db()
        self.assertEqual(quote.discount_state, "")
        self.assertTrue(self.send(quote)["ok"])

    def test_a_save_beyond_the_limit_waits_again_after_an_approval(self):
        quote = self.make(rate="0.08")
        self.decide(self.manager, quote, True)
        self.post(self.sales, "v1_b2b_quotation_save", {**FIGURES, "rate": "0.07"}, quote.pk)
        quote.refresh_from_db()
        self.assertEqual(quote.discount_state, "pending")

    def test_the_limits_are_the_owners_to_set(self):
        answer = _json(self.post(self.admin, "v1_price_list_limits", {"sales": "25", "manager": "15"}))
        self.assertEqual(answer["error"], "manager_below")
        self.assertTrue(_json(self.post(self.admin, "v1_price_list_limits", {"sales": "25", "manager": "40"}))["ok"])
        self.assertEqual(self.make(rate="0.08").discount_state, "")

    def test_the_waiting_list_is_the_approvers(self):
        quote = self.make(rate="0.08")
        listed = lambda user: [one["code"] for one in _json(self.browser(user).get(reverse("dashboard:v1_price_list")))["waiting"]]
        self.assertEqual(listed(self.manager), [quote.code])
        self.assertEqual(listed(self.admin), [quote.code])
        self.assertEqual(listed(self.sales), [])
        self.assertTrue(AuditLog.objects.filter(target="discounts waiting").exists())

    def test_the_other_teams_manager_never_approves(self):
        b2c_boss = User.objects.create_user("b2cboss", password="pw", role=Role.SALES, is_sales_manager=True, sales_track="b2c_online")
        quote = self.make(rate="0.08")
        self.assertEqual(self.decide(b2c_boss, quote, True).status_code, 404)


class AppealTests(_B2c):
    def rejected(self):
        visit = self.visit()
        self.arrive(visit)
        self.leave(visit)
        visit.refresh_from_db()
        b2c.decide(visit, self.manager, False, "Not the company")
        visit.refresh_from_db()
        return visit

    def appeal(self, visit, note="I was there, the GPS drifted", user=None):
        return _json(self.post(user or self.field, "v1_b2c_visit_appeal", {"note": note}, visit.pk))

    def test_an_objection_goes_to_the_owner_who_decides_for_good(self):
        visit = self.rejected()
        self.assertEqual(self.appeal(visit, "")["error"], "needs_reason")
        answer = self.appeal(visit)
        self.assertEqual((answer["visit"]["status"], answer["visit"]["escalated"]), ("pending", True))
        self.assertEqual(answer["visit"]["appealed_from"], "Not the company")
        self.assertTrue(self.admin.notifications.filter(title_ar="اعتراض على زيارة اترفضت").exists())
        # The manager no longer decides it; the owner does, and that is final.
        self.assertEqual(self.post(self.manager, "v1_b2c_visit_decide", {"verified": True, "note": "ok"}, visit.pk).status_code, 403)
        self.assertEqual(_json(self.post(self.admin, "v1_b2c_visit_decide", {"verified": False, "note": "Still no"}, visit.pk))["visit"]["status"], "rejected")
        self.assertEqual(self.appeal(visit)["error"], "appealed")

    def test_only_the_person_and_only_a_turned_down_visit(self):
        visit = self.rejected()
        self.assertIn(self.post(self.field2, "v1_b2c_visit_appeal", {"note": "x"}, visit.pk).status_code, (403, 404))
        self.assertEqual(self.post(self.manager, "v1_b2c_visit_appeal", {"note": "x"}, visit.pk).status_code, 403)
        pending = self.visit()
        self.arrive(pending)
        self.leave(pending)
        self.assertEqual(self.appeal(pending)["error"], "not_rejected")
        self.assertTrue(AuditLog.objects.filter(action="b2c.visit_reject").exists())


class RuleTests(_Pricing):
    def test_only_the_owner_whoever_calls(self):
        for user in (self.sales, self.manager):
            with self.assertRaises(pricing.Refused):
                pricing.save_version(user, LIST)
            with self.assertRaises(pricing.Refused):
                pricing.save_limits(user, "50", "60")

    def test_a_manager_never_approves_their_own_even_within_a_raised_limit(self):
        from .models import Lead, LeadSheet

        own = LeadSheet.objects.create(title="Mine", assigned_to=self.manager, created_by=self.manager)
        lead = Lead.objects.create(sheet=own, company_name="Boss GmbH", email="boss@gmbh.test")
        answer = self.post(self.manager, "v1_b2b_quotation_create", {**FIGURES, "rate": "0.07"}, lead.pk)
        quote = Quotation.objects.get(pk=_json(answer)["quotation"]["id"])
        self.assertEqual(quote.discount_state, "pending")
        pricing.save_limits(self.admin, "10", "40")
        self.assertEqual(self.decide(self.manager, quote, True).status_code, 403)
        self.assertEqual(_json(self.decide(self.admin, quote, True))["state"], "approved")
