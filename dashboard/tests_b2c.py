"""B2C (``b2c.py``, ``api_b2c.py``, the B2C half of ``api_b2b.py``): the companies inside Egypt and the field visits.

Held here:

* a Sales person's kind of work is set on their file (B2B, B2C online, B2C field) and is nobody else's; no new role;
* a sheet is one team's: given to that team's people only, run by that team's manager (and the owner), never read by the
  other team's manager;
* a B2C sheet has the requirements' stages: «Lost» needs its reason, «Waiting» and «Follow-up later» their day;
* the company's place is typed or pasted from Google Maps, and every move of it is in the log;
* a visit is made by the field person whose sheet it is; «I arrived» reads the place once and the server measures it; one
  visit open at a time; «I am done» needs the report and puts the visit before the manager;
* a visit is never verified by itself: the manager verifies or turns down (with the reason), never their own, and a visit
  handed to the owner is the owner's alone; the first verified visit gives a company with no place its place;
* the month's target is lowered by approved leave; a visit left open past its day goes to the manager marked.
"""

import json
from datetime import date, datetime, timedelta
from decimal import Decimal

from django.db import connection
from django.test import Client as DjangoClient
from django.test import TestCase
from django.test.utils import CaptureQueriesContext
from django.urls import reverse
from django.utils import timezone

from . import b2b, b2c
from .forms import StaffEditForm
from .models import (
    AppSettings, AuditLog, FieldVisit, Lead, LeadActivity, LeadSheet, LeadStatus, LeaveKind, LeaveRequest, LeaveStatus,
    Market, Role, SalesTrack, User,
)

#: Cairo Tower, and a point about 50 m east of it, and one about 1 km away.
TOWER = (Decimal("30.045900"), Decimal("31.224300"))
NEAR = (30.0459, 31.2248)
FAR = (30.0459, 31.2347)


def _json(response):
    return json.loads(response.content.decode("utf-8"))


class _B2c(TestCase):
    def setUp(self):
        make = lambda name, role, **kw: User.objects.create_user(name, password="pw", role=role, first_name=name.title(), **kw)
        self.admin = make("owner", Role.ADMIN)
        self.b2b_manager = make("b2bboss", Role.SALES, is_sales_manager=True)
        self.b2b_sales = make("abroad", Role.SALES)
        self.manager = make("b2cboss", Role.SALES, is_sales_manager=True, sales_track=SalesTrack.B2C_ONLINE)
        self.field = make("walker", Role.SALES, sales_track=SalesTrack.B2C_FIELD)
        self.field2 = make("runner", Role.SALES, sales_track=SalesTrack.B2C_FIELD)
        self.online = make("caller", Role.SALES, sales_track=SalesTrack.B2C_ONLINE)
        self.ops = make("ops", Role.OPERATION)
        self.sheet = LeadSheet.objects.create(title="Cairo", assigned_to=self.field, created_by=self.manager, market=Market.B2C)
        self.lead = Lead.objects.create(
            sheet=self.sheet, company_name="Nile Trading", governorate="Cairo", address="Zamalek",
            latitude=TOWER[0], longitude=TOWER[1], phone="01001234567",
        )
        self.b2b_sheet = LeadSheet.objects.create(title="Germany", assigned_to=self.b2b_sales, created_by=self.b2b_manager)
        self.b2b_lead = Lead.objects.create(sheet=self.b2b_sheet, company_name="Lingua GmbH")

    def browser(self, user):
        browser = DjangoClient()
        browser.force_login(user)
        return browser

    def get(self, user, name, *args, **query):
        return self.browser(user).get(reverse(f"dashboard:{name}", args=args), query)

    def post(self, user, name, body, *args):
        return self.browser(user).post(reverse(f"dashboard:{name}", args=args), json.dumps(body), content_type="application/json")

    def visit(self, person=None, lead=None):
        return b2c.plan(lead or self.lead, person or self.field, person or self.field)

    def arrive(self, visit, place=NEAR, accuracy=10, **extra):
        body = {"lat": place[0], "lng": place[1], "accuracy": accuracy, **extra} if place else extra
        return self.post(visit.person, "v1_b2c_visit_check_in", body, visit.pk)

    def leave(self, visit, place=NEAR, **report):
        body = {"lat": place[0], "lng": place[1], "accuracy": 10, "outcome": "interested", "summary": "Met the manager.", **report}
        return self.post(visit.person, "v1_b2c_visit_check_out", body, visit.pk)


class DoorTests(_B2c):
    def test_the_doors_are_under_api_v1(self):
        # A test of a door that is not there passes blind: each name is the address the page calls.
        self.assertEqual(reverse("dashboard:v1_b2c_visits"), "/api/v1/b2c/visits/")
        self.assertEqual(reverse("dashboard:v1_b2c_visit_new"), "/api/v1/b2c/visits/new/")
        self.assertEqual(reverse("dashboard:v1_b2c_visit_check_in", args=[4]), "/api/v1/b2c/visits/4/check-in/")
        self.assertEqual(reverse("dashboard:v1_b2c_visit_check_out", args=[4]), "/api/v1/b2c/visits/4/check-out/")
        self.assertEqual(reverse("dashboard:v1_b2c_visit_decide", args=[4]), "/api/v1/b2c/visits/4/decide/")
        self.assertEqual(reverse("dashboard:v1_b2c_visit_escalate", args=[4]), "/api/v1/b2c/visits/4/escalate/")
        self.assertEqual(reverse("dashboard:v1_b2c_visits_verify_clean"), "/api/v1/b2c/visits/verify-clean/")
        self.assertEqual(reverse("dashboard:v1_b2c_leads"), "/api/v1/b2c/leads/")

    def test_the_visits_page_is_the_field_people_and_the_managers(self):
        for user in (self.field, self.manager, self.admin):
            self.assertEqual(self.get(user, "v1_b2c_visits").status_code, 200, user)
        for user in (self.online, self.b2b_sales, self.b2b_manager, self.ops):
            answer = self.get(user, "v1_b2c_visits")
            self.assertEqual(answer.status_code, 403, user)
        self.assertTrue(AuditLog.objects.filter(action="security.denied").exists())

    def test_me_says_the_sales_track(self):
        me = _json(self.get(self.field, "v1_me"))["user"]
        self.assertEqual(me["sales_track"], "b2c_field")
        self.assertEqual(_json(self.get(self.ops, "v1_me"))["user"]["sales_track"], "")


class TrackTests(_B2c):
    def form(self, person, **changes):
        data = {name: value for name, value in StaffEditForm(instance=person).initial.items() if value is not None}
        data.update(changes)
        data.pop("team_lead", None)
        return StaffEditForm(data=data, instance=person)

    def test_the_owner_sets_the_kind_of_sales_work_on_the_file(self):
        form = self.form(self.b2b_sales, sales_track=SalesTrack.B2C_FIELD)
        self.assertTrue(form.is_valid(), form.errors)
        form.save()
        self.b2b_sales.refresh_from_db()
        self.assertTrue(self.b2b_sales.is_field_sales)
        self.assertEqual(self.b2b_sales.sales_market, Market.B2C)

    def test_another_role_has_no_sales_track(self):
        form = self.form(self.ops, sales_track=SalesTrack.B2C_FIELD)
        self.assertFalse(form.is_valid())
        self.assertIn("sales_track", form.errors)
        # And moved off Sales, the person loses it, whatever screen moved them.
        self.field.role = Role.OPERATION
        self.field.save()
        self.field.refresh_from_db()
        self.assertEqual(self.field.sales_track, SalesTrack.B2B)
        self.assertFalse(self.field.is_field_sales)


class TeamTests(_B2c):
    def test_a_b2c_sheet_goes_to_a_b2c_sales_person_only(self):
        answer = self.post(self.manager, "v1_b2b_sheet_create", {"title": "Giza", "assigned_to": self.b2b_sales.pk})
        self.assertEqual(_json(answer)["error"], "no_sales")
        answer = _json(self.post(self.manager, "v1_b2b_sheet_create", {"title": "Giza", "assigned_to": self.online.pk}))
        self.assertTrue(answer["ok"], answer)
        self.assertEqual(LeadSheet.objects.get(pk=answer["sheet"]["id"]).market, Market.B2C)
        # The B2B manager makes B2B sheets: a B2C person is not theirs to give one to.
        answer = self.post(self.b2b_manager, "v1_b2b_sheet_create", {"title": "Spain", "assigned_to": self.online.pk})
        self.assertEqual(_json(answer)["error"], "no_sales")

    def test_the_owner_says_which_team_a_sheet_is(self):
        answer = _json(self.post(self.admin, "v1_b2b_sheet_create", {"title": "Alex", "assigned_to": self.field.pk, "market": "b2c"}))
        self.assertTrue(answer["ok"], answer)
        self.assertEqual(answer["sheet"]["market"], "b2c")
        # A manager cannot make a sheet of the other team by saying so.
        answer = self.post(self.b2b_manager, "v1_b2b_sheet_create", {"title": "Alex", "assigned_to": self.field.pk, "market": "b2c"})
        self.assertEqual(_json(answer)["error"], "no_sales")

    def test_a_manager_reads_their_own_teams_sheets_only(self):
        self.assertEqual(self.get(self.manager, "v1_b2b_sheet", self.sheet.pk).status_code, 200)
        self.assertEqual(self.get(self.manager, "v1_b2b_sheet", self.b2b_sheet.pk).status_code, 404)
        self.assertEqual(self.get(self.b2b_manager, "v1_b2b_sheet", self.sheet.pk).status_code, 404)
        self.assertEqual(self.get(self.b2b_manager, "v1_b2b_sheet", self.b2b_sheet.pk).status_code, 200)
        listed = [s["id"] for s in _json(self.get(self.manager, "v1_b2b_sheets"))["sheets"]]
        self.assertEqual(listed, [self.sheet.pk])
        listed = [s["id"] for s in _json(self.get(self.b2b_manager, "v1_b2b_sheets"))["sheets"]]
        self.assertEqual(listed, [self.b2b_sheet.pk])
        # Asking for the other team changes nothing for a manager; the owner reads either.
        listed = [s["id"] for s in _json(self.get(self.b2b_manager, "v1_b2b_sheets", market="b2c"))["sheets"]]
        self.assertEqual(listed, [self.b2b_sheet.pk])
        listed = [s["id"] for s in _json(self.get(self.admin, "v1_b2b_sheets", market="b2c"))["sheets"]]
        self.assertEqual(listed, [self.sheet.pk])
        listed = [s["id"] for s in _json(self.get(self.admin, "v1_b2b_sheets"))["sheets"]]
        self.assertEqual(listed, [self.b2b_sheet.pk])

    def test_a_company_moves_inside_its_team_only(self):
        other = LeadSheet.objects.create(title="Abroad 2", assigned_to=self.b2b_sales, market=Market.B2B)
        with self.assertRaises(b2b.Refused) as refused:
            b2b.move_lead(self.lead, other, self.admin)
        self.assertEqual(refused.exception.code, "other_team")

    def test_the_kpis_of_a_manager_are_their_teams(self):
        answer = _json(self.get(self.manager, "v1_b2b_kpis"))
        names = {row["person"]["name"] for row in answer["rows"]}
        self.assertIn("Walker", names)
        self.assertNotIn("Abroad", names)
        answer = _json(self.get(self.b2b_manager, "v1_b2b_kpis"))
        names = {row["person"]["name"] for row in answer["rows"]}
        self.assertIn("Abroad", names)
        self.assertNotIn("Walker", names)


class StageTests(_B2c):
    def save(self, body, user=None, lead=None):
        return self.post(user or self.field, "v1_b2b_lead_save", body, (lead or self.lead).pk)

    def test_a_b2c_sheet_offers_the_requirements_stages(self):
        answer = _json(self.get(self.field, "v1_b2b_sheet", self.sheet.pk))
        self.assertEqual(
            [s["value"] for s in answer["statuses"]],
            ["new", "contacted", "requirement", "quoted", "waiting", "negotiation", "won", "lost", "later"],
        )
        self.assertIn("location", [c["name"] for c in answer["columns"]])
        self.assertTrue(answer["sheet"]["can_visit"])
        self.assertEqual(answer["leads"][0]["location"], "30.0459, 31.2243")
        # The B2B team's sheet keeps its own list.
        answer = _json(self.get(self.b2b_sales, "v1_b2b_sheet", self.b2b_sheet.pk))
        self.assertIn("visit", [s["value"] for s in answer["statuses"]])
        self.assertNotIn("negotiation", [s["value"] for s in answer["statuses"]])

    def test_a_stage_of_the_other_team_is_refused(self):
        self.assertEqual(self.save({"status": "visit"}).status_code, 400)
        self.assertEqual(self.save({"status": "negotiation"}, self.b2b_sales, self.b2b_lead).status_code, 400)
        self.assertEqual(self.save({"status": "negotiation"}).status_code, 200)

    def test_lost_needs_its_reason_and_another_stage_drops_it(self):
        answer = self.save({"status": "lost"})
        self.assertEqual(_json(answer)["error"], "lost_reason")
        self.lead.refresh_from_db()
        self.assertEqual(self.lead.status, LeadStatus.NEW)
        self.assertEqual(_json(self.save({"status": "lost", "lost_reason": "price"}))["lead"]["lost_reason"], "price")
        self.assertEqual(_json(self.save({"status": "negotiation"}))["lead"]["lost_reason"], "")

    def test_waiting_and_later_need_the_next_follow_up(self):
        for stage in ("waiting", "later"):
            self.assertEqual(_json(self.save({"status": stage}))["error"], "needs_follow_up")
        day = (timezone.localdate() + timedelta(days=3)).isoformat()
        self.assertTrue(_json(self.save({"status": "later", "next_follow_up": day}))["ok"])
        # And the day cannot be taken off while the stage waits on it.
        self.assertEqual(_json(self.save({"next_follow_up": ""}))["error"], "needs_follow_up")

    def test_the_b2b_sheet_needs_no_reason(self):
        self.assertTrue(_json(self.save({"status": "lost"}, self.b2b_sales, self.b2b_lead))["ok"])

    def test_the_place_is_typed_or_pasted_and_its_move_is_logged(self):
        link = "https://www.google.com/maps/place/Cairo+Tower/@30.0459482,31.2242987,17z/data=!3m1"
        answer = _json(self.save({"location": link}))
        self.assertEqual(answer["lead"]["location"], "30.045948, 31.224299")
        self.assertTrue(AuditLog.objects.filter(action="b2c.lead_place", target=f"lead {self.lead.pk}").exists())
        self.assertEqual(_json(self.save({"location": "https://maps.app.goo.gl/abc123"}))["error"], "short_link")
        self.assertEqual(_json(self.save({"location": "Zamalek"}))["error"], "bad_location")
        self.assertEqual(_json(self.save({"location": ""}))["lead"]["location"], "")

    def test_a_bad_place_in_a_block_names_its_company(self):
        rows = [{"company_name": "Good Co", "location": "30.1, 31.2"}, {"company_name": "Bad Co", "location": "nowhere"}]
        answer = _json(self.post(self.field, "v1_b2b_rows_add", {"rows": rows}, self.sheet.pk))
        self.assertEqual(answer["error"], "bad_location")
        self.assertIn("Bad Co", answer["message"])
        self.assertFalse(Lead.objects.filter(company_name="Good Co").exists())

    def test_a_block_takes_the_nearest_stage_and_a_lost_one_says_other(self):
        rows = [{"company_name": "A", "status": "visit"}, {"company_name": "B", "status": "lost"}]
        self.assertTrue(_json(self.post(self.field, "v1_b2b_rows_add", {"rows": rows}, self.sheet.pk))["ok"])
        self.assertEqual(Lead.objects.get(company_name="A").status, LeadStatus.CONTACTED)
        self.assertEqual(Lead.objects.get(company_name="B").lost_reason, "other")


class PlaceTests(TestCase):
    def test_the_ways_a_place_is_written(self):
        for text in (
            "30.0459, 31.2243", "30.0459,31.2243", "30.0459 31.2243",
            "https://www.google.com/maps?q=30.0459,31.2243",
            "https://maps.google.com/?q=30.0459%2C31.2243",
            "https://www.google.com/maps/search/?api=1&query=30.0459,31.2243",
            "https://www.google.com/maps/place/x/data=!3d30.0459!4d31.2243",
        ):
            self.assertEqual(b2c.parse_location(text), (Decimal("30.045900"), Decimal("31.224300")), text)
        self.assertIsNone(b2c.parse_location(" "))
        for text in ("91, 31", "30, 200", "abc"):
            with self.assertRaises(b2b.Refused):
                b2c.parse_location(text)


class VisitTests(_B2c):
    def test_only_the_field_person_whose_sheet_it_is_plans_a_visit(self):
        answer = _json(self.post(self.field, "v1_b2c_visit_new", {"lead": self.lead.pk, "purpose": "Intro"}))
        self.assertTrue(answer["ok"], answer)
        self.assertEqual(answer["visit"]["status"], "planned")
        # Another field person's company is a 404 written down; the manager plans one for the holder.
        self.assertEqual(self.post(self.field2, "v1_b2c_visit_new", {"lead": self.lead.pk}).status_code, 404)
        answer = _json(self.post(self.manager, "v1_b2c_visit_new", {"lead": self.lead.pk}))
        self.assertEqual(FieldVisit.objects.get(pk=answer["visit"]["id"]).person, self.field)
        # An online person's sheet has no visits.
        online_sheet = LeadSheet.objects.create(title="Phone", assigned_to=self.online, market=Market.B2C)
        lead = Lead.objects.create(sheet=online_sheet, company_name="Delta Co")
        with self.assertRaises(b2b.Refused):
            b2c.plan(lead, self.online, self.manager)

    def test_arriving_measures_the_place_once(self):
        visit = self.visit()
        answer = _json(self.arrive(visit, NEAR))
        self.assertEqual(answer["visit"]["status"], "checked_in")
        self.assertLess(answer["visit"]["check_in_distance"], 100)
        self.assertEqual(answer["visit"]["flags"], [])
        self.assertTrue(AuditLog.objects.filter(action="b2c.visit_check_in").exists())

    def test_far_and_unsure_presses_are_flagged(self):
        visit = self.visit()
        answer = _json(self.arrive(visit, FAR, accuracy=500))
        self.assertGreater(answer["visit"]["check_in_distance"], 500)
        self.assertEqual(answer["visit"]["flags"], ["far", "weak_gps"])

    def test_a_company_with_no_place_is_flagged(self):
        self.lead.latitude = self.lead.longitude = None
        self.lead.save()
        answer = _json(self.arrive(self.visit()))
        self.assertIsNone(answer["visit"]["check_in_distance"])
        self.assertEqual(answer["visit"]["flags"], ["no_place"])

    def test_no_location_needs_the_reason(self):
        visit = self.visit()
        self.assertEqual(_json(self.arrive(visit, None))["error"], "no_location")
        answer = _json(self.arrive(visit, None, reason="The phone's GPS is broken"))
        self.assertEqual(answer["visit"]["flags"], ["no_gps"])
        self.assertEqual(answer["visit"]["no_location_reason"], "The phone's GPS is broken")

    def test_one_visit_open_at_a_time(self):
        first, second = self.visit(), self.visit()
        self.arrive(first)
        self.assertEqual(_json(self.arrive(second))["error"], "one_open")

    def test_a_second_visit_the_same_day_is_flagged(self):
        first = self.visit()
        self.arrive(first)
        self.leave(first)
        answer = _json(self.arrive(self.visit()))
        self.assertIn("same_day", answer["visit"]["flags"])

    def test_another_persons_visit_is_a_404(self):
        visit = self.visit()
        self.assertEqual(self.post(self.field2, "v1_b2c_visit_check_in", {"lat": NEAR[0], "lng": NEAR[1]}, visit.pk).status_code, 404)
        visit.refresh_from_db()
        self.assertEqual(visit.status, FieldVisit.Status.PLANNED)

    def test_leaving_needs_the_report_and_puts_it_before_the_manager(self):
        visit = self.visit()
        self.arrive(visit)
        self.assertEqual(_json(self.leave(visit, outcome=""))["error"], "no_outcome")
        self.assertEqual(_json(self.leave(visit, summary=" "))["error"], "no_summary")
        day = (timezone.localdate() + timedelta(days=5)).isoformat()
        answer = _json(self.leave(visit, next_step="Send the prices", next_step_on=day, interest="high"))
        self.assertEqual(answer["visit"]["status"], "pending")
        self.lead.refresh_from_db()
        self.assertEqual(self.lead.next_follow_up.isoformat(), day)
        self.assertEqual(self.lead.priority, "high")
        # The visit is on the company's timeline, for the person who held it, and a new company is now «Contacted».
        line = LeadActivity.objects.get(lead=self.lead, kind=LeadActivity.Kind.VISIT)
        self.assertEqual(line.owner, self.field)
        self.assertEqual(self.lead.status, LeadStatus.CONTACTED)
        self.assertIsNotNone(self.lead.last_outreach_at)

    def test_a_planned_visit_is_cancelled_a_started_one_stays(self):
        planned, started = self.visit(), self.visit()
        self.arrive(started)
        self.assertTrue(_json(self.post(self.field, "v1_b2c_visit_cancel", {}, planned.pk))["ok"])
        self.assertFalse(FieldVisit.objects.filter(pk=planned.pk).exists())
        self.assertEqual(_json(self.post(self.field, "v1_b2c_visit_cancel", {}, started.pk))["error"], "started")


class DecisionTests(_B2c):
    def pending(self, place=NEAR, person=None):
        visit = self.visit(person)
        self.arrive(visit, place)
        self.leave(visit, place)
        visit.refresh_from_db()
        return visit

    def decide(self, user, visit, verified, note=""):
        return self.post(user, "v1_b2c_visit_decide", {"verified": verified, "note": note}, visit.pk)

    def test_nothing_is_verified_by_itself(self):
        self.assertEqual(self.pending().status, FieldVisit.Status.PENDING)

    def test_turning_down_needs_the_reason_and_tells_the_person(self):
        visit = self.pending()
        self.assertEqual(_json(self.decide(self.manager, visit, False))["error"], "needs_reason")
        answer = _json(self.decide(self.manager, visit, False, "The photo of the street does not match"))
        self.assertEqual(answer["visit"]["status"], "rejected")
        self.assertTrue(self.field.notifications.filter(title_ar="زيارة اترفضت").exists())
        # A decided visit is decided: nothing changes it after.
        self.assertEqual(_json(self.decide(self.manager, visit, True, "x"))["error"], "not_pending")

    def test_a_flagged_visit_needs_the_reason_it_is_fine(self):
        visit = self.pending(FAR)
        self.assertEqual(_json(self.decide(self.manager, visit, True))["error"], "needs_reason")
        self.assertEqual(_json(self.decide(self.manager, visit, True, "The company moved next door"))["visit"]["status"], "verified")

    def test_only_the_b2c_manager_and_the_owner_decide(self):
        visit = self.pending()
        for user in (self.field, self.b2b_manager, self.online):
            answer = self.decide(user, visit, True)
            self.assertIn(answer.status_code, (403, 404), user)
        visit.refresh_from_db()
        self.assertEqual(visit.status, FieldVisit.Status.PENDING)

    def test_nobody_decides_their_own_visit(self):
        self.manager.sales_track = SalesTrack.B2C_FIELD
        self.manager.save()
        own = LeadSheet.objects.create(title="Mine", assigned_to=self.manager, market=Market.B2C)
        lead = Lead.objects.create(sheet=own, company_name="Boss Co", latitude=TOWER[0], longitude=TOWER[1])
        visit = b2c.plan(lead, self.manager, self.manager)
        self.arrive(visit)
        self.leave(visit)
        self.assertEqual(self.decide(self.manager, visit, True).status_code, 403)
        self.assertEqual(_json(self.decide(self.admin, visit, True))["visit"]["status"], "verified")

    def test_a_visit_handed_to_the_owner_is_the_owners_alone(self):
        visit = self.pending(FAR)
        self.assertEqual(_json(self.post(self.manager, "v1_b2c_visit_escalate", {"note": ""}, visit.pk))["error"], "needs_reason")
        answer = _json(self.post(self.manager, "v1_b2c_visit_escalate", {"note": "Looks like his home"}, visit.pk))
        self.assertTrue(answer["visit"]["escalated"])
        self.assertTrue(self.admin.notifications.filter(title_ar="زيارة محتاجة قرارك").exists())
        self.assertEqual(self.decide(self.manager, visit, False, "no").status_code, 403)
        self.assertEqual(_json(self.decide(self.admin, visit, False, "Not the company"))["visit"]["status"], "rejected")

    def test_the_first_verified_visit_gives_a_company_its_place(self):
        self.lead.latitude = self.lead.longitude = None
        self.lead.save()
        visit = self.pending()
        self.decide(self.manager, visit, True, "First visit, the place is new")
        self.lead.refresh_from_db()
        self.assertEqual((float(self.lead.latitude), float(self.lead.longitude)), NEAR)
        self.assertTrue(AuditLog.objects.filter(action="b2c.place_from_visit").exists())

    def test_verify_clean_leaves_the_flagged_ones(self):
        clean, flagged = self.pending(), self.pending(FAR)
        answer = _json(self.post(self.manager, "v1_b2c_visits_verify_clean", {"ids": [clean.pk, flagged.pk]}))
        self.assertEqual(answer["verified"], 1)
        clean.refresh_from_db()
        flagged.refresh_from_db()
        self.assertEqual(clean.status, FieldVisit.Status.VERIFIED)
        self.assertEqual(flagged.status, FieldVisit.Status.PENDING)
        self.assertEqual(self.post(self.field, "v1_b2c_visits_verify_clean", {"ids": [flagged.pk]}).status_code, 403)

    def test_a_visit_left_open_goes_to_the_manager_marked(self):
        visit = self.visit()
        self.arrive(visit)
        FieldVisit.objects.filter(pk=visit.pk).update(check_in_at=timezone.now() - timedelta(days=1))
        self.assertEqual(b2c.sweep(), 1)
        visit.refresh_from_db()
        self.assertEqual(visit.status, FieldVisit.Status.PENDING)
        self.assertIn("no_checkout", visit.flags)
        self.assertEqual(b2c.sweep(), 0)


class TargetTests(_B2c):
    def test_the_target_is_lowered_by_approved_leave(self):
        first = date(2026, 11, 1)
        self.assertEqual(b2c.due_target(self.field, first)[0], 220)
        # Sunday 1 to Wednesday 4 November: four working days of 22.
        LeaveRequest.objects.create(
            user=self.field, kind=LeaveKind.ANNUAL, start_date=date(2026, 11, 1), end_date=date(2026, 11, 4),
            status=LeaveStatus.APPROVED,
        )
        LeaveRequest.objects.create(
            user=self.field, kind=LeaveKind.ANNUAL, start_date=date(2026, 11, 10), end_date=date(2026, 11, 12),
            status=LeaveStatus.PENDING,
        )
        self.assertEqual(b2c.due_target(self.field, first), (180, 4))

    def test_the_board_counts_verified_visits_against_the_target(self):
        conf = AppSettings.load()
        conf.b2c_visit_target = 10
        conf.save()
        for _ in range(2):
            visit = self.visit()
            self.arrive(visit)
            self.leave(visit)
            visit.refresh_from_db()
            b2c.decide(visit, self.manager, True, "ok")
        answer = _json(self.get(self.field, "v1_b2c_visits"))
        [row] = answer["board"]
        self.assertEqual((row["target"], row["verified"], row["remaining"], row["achievement"]), (10, 2, 8, 20))
        self.assertEqual(row["verification_rate"], 100)
        # The manager reads every field person's row; a person reads their own.
        names = [row["person"]["name"] for row in _json(self.get(self.manager, "v1_b2c_visits"))["board"]]
        self.assertEqual(sorted(names), ["Runner", "Walker"])

    def test_the_list_of_visits_is_written_down(self):
        self.visit()
        self.get(self.manager, "v1_b2c_visits")
        self.assertTrue(AuditLog.objects.filter(target="b2c visits").exists())


class LockedRowTests(_B2c):
    """The visit a press or a decision locks is read alone. Postgres refuses ``SELECT ... FOR UPDATE`` over an outer join
    and SQLite drops the lock, so the quick settings would never see it (CLAUDE.md): what is held is the shape."""

    def selects(self, run):
        with CaptureQueriesContext(connection) as seen:
            run()
        return [one["sql"] for one in seen.captured_queries if one["sql"].startswith("SELECT") and 'FROM "dashboard_fieldvisit"' in one["sql"]]

    def test_every_step_reads_the_visit_without_joining_anything(self):
        visit = self.visit()
        report = {"outcome": "interested", "summary": "ok"}
        steps = (
            lambda: b2c.check_in(visit, self.field, lat=NEAR[0], lng=NEAR[1], accuracy=5),
            lambda: b2c.check_out(visit, self.field, report, lat=NEAR[0], lng=NEAR[1], accuracy=5),
            lambda: b2c.escalate(visit, self.manager, "why"),
            lambda: b2c.decide(visit, self.admin, True, "fine"),
        )
        for step in steps:
            selects = self.selects(step)
            self.assertTrue(selects)
            for sql in selects:
                self.assertNotIn("JOIN", sql)


class GuideTests(_B2c):
    def test_the_b2c_guides_are_told_to_their_people(self):
        from . import guides

        told = lambda user: {guide.id for guide in guides.for_user(user)}
        self.assertTrue({"b2c-sheets", "b2c-visits"} <= told(self.field))
        self.assertNotIn("b2c-visits-approve", told(self.field))
        self.assertIn("b2c-sheets", told(self.online))
        self.assertNotIn("b2c-visits", told(self.online))
        self.assertIn("b2c-visits-approve", told(self.manager))
        self.assertFalse({"b2c-sheets", "b2c-visits", "b2c-visits-approve"} & told(self.b2b_sales))
        self.assertNotIn("b2c-visits-approve", told(self.b2b_manager))


class BackstopTests(_B2c):
    def test_the_manager_cannot_press_for_the_field_person(self):
        # The manager sees every visit, so the door lets them in: the press itself must still be the person's own.
        visit = self.visit()
        answer = self.post(self.manager, "v1_b2c_visit_check_in", {"lat": NEAR[0], "lng": NEAR[1], "accuracy": 5}, visit.pk)
        self.assertEqual(_json(answer)["error"], "not_yours")
        visit.refresh_from_db()
        self.assertEqual(visit.status, FieldVisit.Status.PLANNED)

    def test_a_managers_numbers_are_their_teams_whoever_asks(self):
        start = timezone.now() - timedelta(days=1)
        people = b2b.kpi_people(self.manager, start, timezone.now())
        self.assertIn(self.field, people)
        self.assertNotIn(self.b2b_sales, people)
