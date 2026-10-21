"""The B2B sheet in the Sales team's own shape (12/10/2026): their Google Sheet's status list, the priority and the deal value,
a cell edited on the sheet that saves that cell alone, and their sheet uploaded as it is."""

import importlib
from datetime import timedelta
from unittest import mock
from decimal import Decimal

from django.apps import apps
from django.test import SimpleTestCase
from django.urls import reverse
from django.utils import timezone

from . import b2b_import
from . import services
from .models import AuditLog, Channel, Client, Lead, LeadActivity, LeadNote, LeadSheet, OutboundMessage
from .tests_b2b import PHONE, _B2b, _json

#: The test company's WhatsApp number as WhatsApp sends it.
PHONE_DIGITS = "447700900123"

#: The Sales team's Google Sheet as a CSV, its own headers and words (the NAME column is empty there).
TEAM_SHEET = (
    "الشركة,الشخص المسؤول,رقم الهاتف,البريد الإلكتروني,الحالة,الأولوية,قيمة الصفقة,النشاط,ملاحظات,NAME,الدوله \n"
    ",,,,,,,,,,\n"
    "BASH,,96522213775,,تم التواصل,متوسطة,,Tourism,,,الكويت\n"
    "Tathkarah travels,,96522206222,,تم التواصل,متوسطة,\"1,500 $\",Tourism,قالي هيتواصلوا,,الكويت\n"
    "Captain Tours,,966590070360,,whatsapp,عالية,,Tourism,,Somebody,الكويت\n"
    "Khaitan,,24737021,,متابعة,,,Tourism,مفيش واتساب ولا ايميل,,الكويت\n"
    "Odd Co,,123,,E,urgent,a lot,,,,الكويت\n"
)


class TeamSheetReadTests(SimpleTestCase):
    def test_the_team_sheet_is_read_with_its_status_priority_deal_and_notes(self):
        rows, mapped = b2b_import.to_rows(b2b_import.read_text(TEAM_SHEET))
        self.assertEqual(mapped["status"], "الحالة")
        self.assertEqual(mapped["country"], "الدوله")
        self.assertEqual(len(rows), 5)
        bash, tathkarah, captain, khaitan, odd = rows
        self.assertEqual((bash["status"], bash["priority"], bash["industry"], bash["country"]), ("contacted", "medium", "Tourism", "الكويت"))
        self.assertEqual((tathkarah["deal_value"], tathkarah["notes"]), ("1500", "قالي هيتواصلوا"))
        self.assertEqual((captain["status"], captain["priority"]), ("whatsapp", "high"))
        # NAME is not the contact person: the first column named for it keeps it.
        self.assertEqual(captain["contact_person"], "")
        self.assertEqual(khaitan["status"], "follow_up")
        # A word the sheet does not know is left out: the row comes in «New client», with no priority and no value.
        self.assertNotIn("status", odd)
        self.assertNotIn("priority", odd)
        self.assertNotIn("deal_value", odd)


class CellTests(_B2b):
    def save(self, body, user=None):
        return self.post(user or self.sales, "v1_b2b_lead_save", body, self.lead.pk)

    def test_one_cell_saves_that_cell_and_nothing_else(self):
        Lead.objects.filter(pk=self.lead.pk).update(deal_value=Decimal("9"), priority="low")
        answer = self.save({"phone": "+965 2221 3775"})
        self.assertEqual(answer.status_code, 200, answer.content)
        self.lead.refresh_from_db()
        self.assertEqual(
            (self.lead.phone, self.lead.deal_value, self.lead.priority, self.lead.company_name, self.lead.email, self.lead.status),
            ("+965 2221 3775", Decimal("9"), "low", "Lingua GmbH", "anna@lingua.test", "new"),
        )
        self.assertFalse(self.lead.activities.exists())

    def test_the_status_cell_is_a_stage_change(self):
        self.assertEqual(self.save({"status": "won"}).status_code, 200)
        self.lead.refresh_from_db()
        self.assertEqual(self.lead.status, "won")
        self.assertEqual(self.lead.activities.get(kind=LeadActivity.Kind.STATUS).status, "won")

    def test_priority_and_deal_value(self):
        body = _json(self.save({"priority": "high", "deal_value": "1,500.50"}))
        self.assertEqual((body["lead"]["priority"], body["lead"]["deal_value"]), ("high", "1500.5"))
        self.lead.refresh_from_db()
        self.assertEqual((self.lead.priority, self.lead.deal_value), ("high", Decimal("1500.50")))
        self.assertEqual(_json(self.save({"deal_value": 2000}))["lead"]["deal_value"], "2000")
        cleared = _json(self.save({"priority": "", "deal_value": ""}))["lead"]
        self.assertEqual((cleared["priority"], cleared["deal_value"]), ("", ""))

    def test_a_cell_that_is_not_one_writes_nothing(self):
        Lead.objects.filter(pk=self.lead.pk).update(deal_value=Decimal("10"))
        for body in (
            {"priority": "urgent"}, {"deal_value": "-5"}, {"deal_value": "1.234"}, {"deal_value": "abc"}, {"deal_value": True},
            {"deal_value": "1e3"}, {"deal_value": "NaN"}, {"deal_value": "9999999999999"}, {"status": ""}, {"status": "meeting"},
            {"phone": 5}, {"next_follow_up": "soon"},
        ):
            self.assertEqual(self.save(body).status_code, 400, body)
        self.lead.refresh_from_db()
        self.assertEqual((self.lead.deal_value, self.lead.status, self.lead.priority), (Decimal("10"), "new", ""))

    def test_the_company_cell_may_not_be_emptied(self):
        self.assertEqual(_json(self.save({"company_name": "  "}))["error"], "no_company")
        self.lead.refresh_from_db()
        self.assertEqual(self.lead.company_name, "Lingua GmbH")

    def test_a_cell_on_a_sheet_that_is_not_ones_own_is_a_404(self):
        self.assertEqual(self.save({"priority": "high"}, user=self.other).status_code, 404)
        self.lead.refresh_from_db()
        self.assertEqual(self.lead.priority, "")

    def test_a_save_that_carries_notes_writes_nothing(self):
        # A note is added on its own door, never written over by a save from a page out of date.
        self.assertEqual(self.save({"priority": "high", "notes": "old block"}).status_code, 400)
        self.lead.refresh_from_db()
        self.assertEqual((self.lead.priority, self.lead.note_items.count()), ("", 0))

    def test_the_sheet_says_the_priorities_and_its_rows_carry_them(self):
        Lead.objects.filter(pk=self.lead.pk).update(priority="medium", deal_value=Decimal("250.00"))
        body = _json(self.get(self.sales, "v1_b2b_sheet", self.sheet.pk))
        self.assertEqual([one["value"] for one in body["priorities"]], ["high", "medium", "low"])
        self.assertEqual(
            [one["value"] for one in body["statuses"]],
            ["new", "contacted", "follow_up", "won", "lost", "whatsapp", "visit", "no_answer", "call"],
        )
        row = body["leads"][0]
        self.assertEqual((row["priority"], row["deal_value"]), ("medium", "250"))


class UploadTests(_B2b):
    def test_uploaded_rows_keep_their_status_priority_deal_and_notes(self):
        rows = [
            {"company_name": "BASH", "status": "contacted", "priority": "medium", "deal_value": "1500", "notes": "call back"},
            {"company_name": "Plain"},
        ]
        answer = self.post(self.sales, "v1_b2b_rows_add", {"rows": rows}, self.sheet.pk)
        self.assertEqual(answer.status_code, 200, answer.content)
        bash, plain = Lead.objects.get(company_name="BASH"), Lead.objects.get(company_name="Plain")
        self.assertEqual((bash.status, bash.priority, bash.deal_value), ("contacted", "medium", Decimal("1500")))
        note = bash.note_items.get()
        self.assertEqual((note.text, note.by), ("call back", self.sales))
        self.assertEqual((plain.status, plain.priority, plain.deal_value, plain.note_items.count()), ("new", "", None, 0))

    def test_an_uploaded_row_with_a_wrong_value_adds_nothing(self):
        for bad in ({"status": "meeting"}, {"priority": "top"}, {"deal_value": "-1"}):
            answer = self.post(self.sales, "v1_b2b_rows_add", {"rows": [{"company_name": "X", **bad}]}, self.sheet.pk)
            self.assertEqual(answer.status_code, 400, bad)
        self.assertFalse(Lead.objects.filter(company_name="X").exists())


class OldStagesTests(_B2b):
    def test_the_old_stages_become_the_sheets_words(self):
        migration = importlib.import_module("dashboard.migrations.0070_lead_sheet_columns")
        old = {"email_sent": "contacted", "follow_up_1": "follow_up", "follow_up_2": "follow_up", "meeting": "visit",
               "proposal": "follow_up", "negotiation": "follow_up", "won": "won", "lost": "lost", "new": "new"}
        made = {}
        for stage in old:
            lead = Lead.objects.create(sheet=self.sheet, company_name=f"Co {stage}")
            Lead.objects.filter(pk=lead.pk).update(status=stage)
            activity = LeadActivity.objects.create(lead=lead, kind=LeadActivity.Kind.STATUS, status=stage)
            LeadActivity.objects.filter(pk=activity.pk).update(status=stage)
            made[stage] = (lead.pk, activity.pk)
        migration.to_sheet_words(apps, None)
        for stage, (lead_id, activity_id) in made.items():
            self.assertEqual(Lead.objects.get(pk=lead_id).status, old[stage], stage)
            self.assertEqual(LeadActivity.objects.get(pk=activity_id).status, old[stage], stage)


class SeveralPhonesTests(_B2b):
    """A company with more than one number (12/10/2026): one a line in the phone cell."""

    def setUp(self):
        super().setUp()
        Lead.objects.filter(pk=self.lead.pk).update(whatsapp="")
        self.lead.refresh_from_db()
        self.lead.phone = "+965 2221 3775\n+965 9988 7766 / 24737021"
        self.lead.save()

    def test_every_number_is_read_and_kept_as_a_key(self):
        self.assertEqual(self.lead.all_phones, ["+96522213775", "+96599887766", "24737021"])
        self.assertEqual(self.lead.phone_key, "522213775")
        self.assertIn(" 599887766 ", self.lead.phone_keys)
        body = _json(self.get(self.sales, "v1_b2b_sheet", self.sheet.pk))
        self.assertEqual(body["leads"][0]["phones"], ["+96522213775", "+96599887766", "24737021"])

    def test_the_cell_takes_several_numbers(self):
        answer = self.post(self.sales, "v1_b2b_lead_save", {"phone": "0100 111 2222\n0122 333 4444"}, self.lead.pk)
        self.assertEqual(answer.status_code, 200, answer.content)
        self.lead.refresh_from_db()
        self.assertEqual(self.lead.all_phones, ["01001112222", "01223334444"])
        self.assertEqual(self.post(self.sales, "v1_b2b_lead_save", {"phone": "1" * 251}, self.lead.pk).status_code, 400)

    def test_whatsapp_goes_to_the_number_chosen_and_the_client_keeps_the_others(self):
        answer = self.post(self.sales, "v1_b2b_lead_whatsapp", {"number": "+965 9988 7766"}, self.lead.pk)
        self.assertEqual(answer.status_code, 200, answer.content)
        self.assertEqual(self.template.call_args.args[0], "96599887766")
        client = Client.objects.get(code=_json(answer)["chat"])
        self.assertEqual(client.phone, "96599887766")
        self.assertEqual(client.extra_phones.split("\n"), ["+96522213775", "24737021"])

    def test_without_a_choice_the_first_number_and_a_stranger_number_is_refused(self):
        self.assertEqual(self.post(self.sales, "v1_b2b_lead_whatsapp", {}, self.lead.pk).status_code, 200)
        self.assertEqual(self.template.call_args.args[0], "96522213775")
        answer = self.post(self.sales, "v1_b2b_lead_whatsapp", {"number": "+20 100 000 0000"}, self.lead.pk)
        self.assertEqual(_json(answer)["error"], "not_its_number")
        self.assertEqual(self.template.call_count, 1)

    def test_an_answer_from_the_second_number_marks_the_row(self):
        services.ingest_message(
            channel=Channel.WHATSAPP, body="hello", sender_identity="96599887766", external_id="wamid.two", owner=self.sales,
        )
        self.lead.refresh_from_db()
        self.assertIsNotNone(self.lead.replied_at)
        # And it is the company already on the sheet: no row of its own on the sheet of companies that wrote first.
        self.assertEqual(Lead.objects.count(), 1)

    def test_old_rows_get_the_keys_of_every_number(self):
        migration = importlib.import_module("dashboard.migrations.0071_lead_several_phones")
        Lead.objects.filter(pk=self.lead.pk).update(phone_keys="", phone_key="", whatsapp="+44 7700 900123")
        migration.keys_for_every_number(apps, None)
        self.lead.refresh_from_db()
        self.assertEqual(self.lead.phone_keys, " 700900123 522213775 599887766 24737021 ")
        self.assertEqual(self.lead.phone_key, "700900123")


class NoteTests(_B2b):
    """Each note on its own, with the day it was written and who wrote it (12/10/2026)."""

    def add(self, text, user=None):
        return self.post(user or self.sales, "v1_b2b_lead_note_add", {"text": text}, self.lead.pk)

    def test_the_doors_are_under_api_v1(self):
        from django.urls import reverse

        self.assertEqual(reverse("dashboard:v1_b2b_lead_note_add", args=[5]), "/api/v1/b2b/leads/5/notes/")
        self.assertEqual(reverse("dashboard:v1_b2b_lead_note_delete", args=[9]), "/api/v1/b2b/notes/9/delete/")
        self.assertEqual(reverse("dashboard:v1_b2b_lead_send", args=[5]), "/api/v1/b2b/leads/5/send/")

    def test_notes_are_added_one_by_one_each_dated_and_signed(self):
        self.assertEqual(self.add("  first call, no answer ").status_code, 200)
        body = _json(self.add("sent the rate sheet", user=self.manager))
        notes = body["lead"]["notes"]
        self.assertEqual([n["text"] for n in notes], ["first call, no answer", "sent the rate sheet"])
        self.assertEqual([n["by"]["name"] for n in notes], ["Seller", "Manager"])
        today = timezone.localtime().strftime("%d/%m/%Y")
        self.assertEqual({n["day"] for n in notes}, {today})
        self.assertTrue(AuditLog.objects.filter(action="b2b.note", detail__startswith="note ").exists())
        # The sheet answers the notes too.
        sheet = _json(self.get(self.sales, "v1_b2b_sheet", self.sheet.pk))
        self.assertEqual(len(sheet["leads"][0]["notes"]), 2)

    def test_an_empty_or_too_long_note_or_a_stranger_writes_nothing(self):
        self.assertEqual(_json(self.add("   "))["error"], "empty")
        self.assertEqual(self.add("x" * 4001).status_code, 400)
        self.assertEqual(self.add("hello", user=self.other).status_code, 404)
        self.assertEqual(self.add("hello", user=self.ops).status_code, 403)
        self.assertFalse(LeadNote.objects.exists())

    def test_a_note_is_taken_off_by_its_writer_or_the_manager_only(self):
        mine = LeadNote.objects.create(lead=self.lead, text="mine", by=self.sales)
        theirs = LeadNote.objects.create(lead=self.lead, text="the manager's", by=self.manager)
        answer = self.post(self.sales, "v1_b2b_lead_note_delete", {}, theirs.pk)
        self.assertEqual((answer.status_code, _json(answer)["error"]), (403, "not_yours"))
        self.assertEqual(self.post(self.other, "v1_b2b_lead_note_delete", {}, mine.pk).status_code, 404)
        self.assertEqual(self.post(self.sales, "v1_b2b_lead_note_delete", {}, mine.pk).status_code, 200)
        self.assertEqual(self.post(self.manager, "v1_b2b_lead_note_delete", {}, theirs.pk).status_code, 200)
        self.assertFalse(LeadNote.objects.exists())

    def test_the_old_block_of_notes_becomes_dated_notes(self):
        from django.db import connection

        migration = importlib.import_module("dashboard.migrations.0072_lead_notes_dated")

        class OldLead:
            def __init__(self, pk, notes, updated_at):
                self.pk, self.notes, self.updated_at = pk, notes, updated_at

        class OldLeads:
            def __init__(self, rows):
                self.rows = rows

            def exclude(self, **kw):
                return self

            def only(self, *names):
                return self.rows

        class FakeApps:
            def get_model(self, app, name):
                if name == "LeadNote":
                    return LeadNote
                fake = type("Lead", (), {})
                fake.objects = OldLeads([OldLead(self_lead.pk, "first\n\n  second  ", stamp)])
                return fake

        self_lead, stamp = self.lead, timezone.now() - timedelta(days=3)
        migration.notes_to_rows(FakeApps(), connection.schema_editor)
        notes = list(self.lead.note_items.all())
        self.assertEqual([n.text for n in notes], ["first", "second"])
        self.assertEqual({n.at for n in notes}, {stamp})
        self.assertEqual({n.by for n in notes}, {None})


class SeveralWhatsappTests(_B2b):
    def test_the_whatsapp_cell_takes_several_numbers_and_they_come_first(self):
        answer = self.post(self.sales, "v1_b2b_lead_save", {"whatsapp": "+44 7700 900123\n+44 7700 900456", "phone": "+44 20 1234 5678"}, self.lead.pk)
        self.assertEqual(answer.status_code, 200, answer.content)
        self.assertEqual(_json(answer)["lead"]["phones"], ["+447700900123", "+447700900456", "+442012345678"])


class SendTests(_B2b):
    """A message written on the sheet to a number or the address, marked on the row by itself (12/10/2026)."""

    def send(self, body, user=None):
        return self.post(user or self.sales, "v1_b2b_lead_send", body, self.lead.pk)

    def their_message(self, sender=PHONE_DIGITS):
        services.ingest_message(channel=Channel.WHATSAPP, body="hi", sender_identity=sender, external_id="wamid.in.s", owner=self.sales)

    def test_a_written_whatsapp_goes_when_they_wrote_in_the_last_day_and_marks_the_row(self):
        self.their_message()
        answer = self.send({"channel": "whatsapp", "to": PHONE, "body": "Thanks, here are our rates"})
        self.assertEqual(answer.status_code, 200, answer.content)
        self.text.assert_called_once()
        self.assertEqual(self.text.call_args.kwargs.get("from_id"), "900002")
        sent = OutboundMessage.objects.get(channel=Channel.WHATSAPP)
        self.assertEqual((sent.owner, sent.body, sent.status), (self.sales, "Thanks, here are our rates", "sent"))
        self.lead.refresh_from_db()
        self.assertIsNotNone(self.lead.whatsapp_at)
        self.assertEqual(self.lead.activities.filter(kind="whatsapp", incoming=False).count(), 1)
        self.assertEqual(_json(answer)["lead"]["whatsapp_at"] != "", True)

    def test_without_their_message_whatsapp_carries_only_the_opening_one(self):
        answer = self.send({"channel": "whatsapp", "to": PHONE, "body": "hello"})
        self.assertEqual(_json(answer)["error"], "window_closed")
        self.text.assert_not_called()
        self.template.assert_not_called()
        self.assertFalse(OutboundMessage.objects.exists())

    def test_the_window_is_the_number_they_wrote_from(self):
        Lead.objects.filter(pk=self.lead.pk).update(phone="+44 7700 900456")
        self.lead.refresh_from_db()
        self.lead.save()
        self.their_message()
        answer = self.send({"channel": "whatsapp", "to": "+44 7700 900456", "body": "hello"})
        self.assertEqual(_json(answer)["error"], "window_closed")
        self.text.assert_not_called()

    def test_a_stranger_number_an_empty_message_and_another_persons_sheet_are_refused(self):
        self.their_message()
        self.assertEqual(_json(self.send({"channel": "whatsapp", "to": "+20 100 000 0000", "body": "x"}))["error"], "not_its_number")
        self.assertEqual(_json(self.send({"channel": "whatsapp", "to": PHONE, "body": "  "}))["error"], "empty")
        self.assertEqual(_json(self.send({"channel": "whatsapp", "to": PHONE, "body": "x"}, user=self.manager))["error"], "not_yours")
        self.assertEqual(self.send({"channel": "fax", "body": "x"}).status_code, 400)
        self.text.assert_not_called()

    def test_an_email_goes_from_the_persons_address_and_marks_the_row(self):
        answer = self.send({"channel": "email", "subject": "Rates", "body": "Dear Anna"})
        self.assertEqual(answer.status_code, 200, answer.content)
        self.assertEqual(self.mail.call_args.kwargs["from_email"], "seller@eagle.test")
        self.lead.refresh_from_db()
        self.assertIsNotNone(self.lead.email_at)
        self.assertEqual(self.lead.status, "contacted")


class LetterFilesTests(_B2b):
    """The e-mail from the sheet's send button carries files (21/10/2026): the same fields as a multipart form, the files
    stored under a random name and opened from ``/files/`` only, and sent as real attachments of the letter."""

    def send(self, files, channel="email", **extra):
        from django.core.files.uploadedfile import SimpleUploadedFile

        form = {"channel": channel, "to": PHONE if channel == "whatsapp" else "", "subject": "Rates", "body": "Dear Anna", **extra}
        form["files"] = [SimpleUploadedFile(name, content) for name, content in files]
        return self.browser(self.sales).post(reverse("dashboard:v1_b2b_lead_send", args=[self.lead.pk]), form)

    def test_the_files_leave_attached_and_are_kept_on_the_letter(self):
        answer = self.send([("rates.pdf", b"%PDF rates"), ("logo.png", b"PNG logo")])
        self.assertEqual(answer.status_code, 200, answer.content)
        self.mail.assert_called_once()
        attached = self.mail.call_args.kwargs["attachments"]
        self.assertEqual([(name, content) for name, content, _mime in attached], [("rates.pdf", b"%PDF rates"), ("logo.png", b"PNG logo")])
        self.assertEqual(self.mail.call_args.kwargs["from_email"], "seller@eagle.test")
        sent = OutboundMessage.objects.get(channel=Channel.EMAIL)
        self.assertEqual((sent.status, sent.subject, sent.body), ("sent", "Rates", "Dear Anna"))
        stored = list(sent.uploads.order_by("pk"))
        self.assertEqual([u.original_name for u in stored], ["rates.pdf", "logo.png"])
        for upload in stored:
            # The path says nothing of the name it came with, and the link is the project's own door, never the CDN.
            self.assertNotIn("rates", upload.file.name)
            self.assertNotIn("logo", upload.file.name)
            self.assertTrue(upload.file.url.startswith("/files/"), upload.file.url)
        self.lead.refresh_from_db()
        self.assertIsNotNone(self.lead.email_at)

    def test_a_letter_without_files_still_goes_as_json(self):
        answer = self.post(self.sales, "v1_b2b_lead_send", {"channel": "email", "subject": "Rates", "body": "Dear Anna"}, self.lead.pk)
        self.assertEqual(answer.status_code, 200, answer.content)
        self.assertEqual(self.mail.call_args.kwargs["attachments"], [])

    def test_too_many_files_are_refused_in_arabic_and_nothing_is_sent(self):
        answer = self.send([(f"f{index}.pdf", b"x") for index in range(11)])
        self.assertEqual(answer.status_code, 400)
        self.assertEqual(_json(answer)["error"], "too_many_files")
        self.assertIn("10 ملفات", _json(answer)["message"])
        self.mail.assert_not_called()
        self.assertFalse(OutboundMessage.objects.exists())

    def test_files_over_what_a_mail_takes_are_refused(self):
        with mock.patch.object(services, "MAX_MAIL_BYTES", 5):
            answer = self.send([("a.pdf", b"1234"), ("b.pdf", b"1234")])
        self.assertEqual(_json(answer)["error"], "files_too_big")
        self.assertIn("25 ميجا", _json(answer)["message"])
        self.mail.assert_not_called()
        self.assertFalse(OutboundMessage.objects.exists())

    def test_an_empty_file_is_refused(self):
        answer = self.send([("empty.pdf", b"")])
        self.assertEqual(_json(answer)["error"], "empty_file")
        self.mail.assert_not_called()

    def test_whatsapp_from_the_sheet_takes_no_files(self):
        answer = self.send([("a.pdf", b"x")], channel="whatsapp")
        self.assertEqual(answer.status_code, 400)
        self.text.assert_not_called()
        self.assertFalse(OutboundMessage.objects.exists())

    def test_another_persons_sheet_is_refused_before_the_files_are_kept(self):
        from django.core.files.uploadedfile import SimpleUploadedFile

        answer = self.browser(self.manager).post(
            reverse("dashboard:v1_b2b_lead_send", args=[self.lead.pk]),
            {"channel": "email", "subject": "x", "body": "x", "files": [SimpleUploadedFile("a.pdf", b"x")]},
        )
        self.assertEqual(_json(answer)["error"], "not_yours")
        self.mail.assert_not_called()
        self.assertFalse(OutboundMessage.objects.exists())


class LastSentTests(_B2b):
    """The sheet marks the last row a message left from with its send button (15/10/2026), so its Sales person opens it
    where they stopped and writes to the next one."""

    def setUp(self):
        super().setUp()
        self.second = Lead.objects.create(sheet=self.sheet, company_name="Second Ltd", email="b@second.test", whatsapp="+44 7700 900777")

    def marked(self):
        answer = self.get(self.sales, "v1_b2b_sheet", self.sheet.pk)
        self.assertEqual(answer.status_code, 200, answer.content)
        return _json(answer)["sheet"]["last_sent"]

    def their_message(self, sender=PHONE_DIGITS, wamid="wamid.in.last"):
        services.ingest_message(channel=Channel.WHATSAPP, body="hi", sender_identity=sender, external_id=wamid, owner=self.sales)

    def test_the_doors_are_under_api_v1(self):
        self.assertEqual(reverse("dashboard:v1_b2b_sheet", args=[3]), "/api/v1/b2b/sheets/3/")
        self.assertEqual(reverse("dashboard:v1_b2b_lead_whatsapp", args=[3]), "/api/v1/b2b/leads/3/whatsapp/")
        self.assertEqual(reverse("dashboard:v1_b2b_lead_email", args=[3]), "/api/v1/b2b/leads/3/email/")

    def test_a_message_sent_from_the_row_marks_it_and_the_next_one_moves_the_mark(self):
        self.assertIsNone(self.marked())
        self.their_message()
        answer = self.post(self.sales, "v1_b2b_lead_send", {"channel": "whatsapp", "to": PHONE, "body": "Our rates"}, self.lead.pk)
        self.assertEqual(answer.status_code, 200, answer.content)
        self.assertEqual(_json(answer)["last_sent"], self.lead.pk)
        self.assertEqual(self.marked(), self.lead.pk)
        answer = self.post(self.sales, "v1_b2b_lead_send", {"channel": "email", "subject": "Rates", "body": "Dear team"}, self.second.pk)
        self.assertEqual(_json(answer)["last_sent"], self.second.pk)
        self.assertEqual(self.marked(), self.second.pk)

    def test_a_refused_send_marks_nothing(self):
        self.post(self.sales, "v1_b2b_lead_send", {"channel": "email", "subject": "Rates", "body": "Dear team"}, self.second.pk)
        answer = self.post(self.sales, "v1_b2b_lead_send", {"channel": "whatsapp", "to": PHONE, "body": "hello"}, self.lead.pk)
        self.assertEqual(_json(answer)["error"], "window_closed")
        self.assertNotIn("last_sent", _json(answer))
        answer = self.post(self.manager, "v1_b2b_lead_send", {"channel": "email", "subject": "x", "body": "x"}, self.lead.pk)
        self.assertEqual(_json(answer)["error"], "not_yours")
        self.assertEqual(self.marked(), self.second.pk)

    def test_the_opening_message_marks_the_row_and_a_chat_opened_with_nothing_sent_does_not(self):
        answer = self.post(self.sales, "v1_b2b_lead_whatsapp", {"number": PHONE}, self.lead.pk)
        self.assertEqual(answer.status_code, 200, answer.content)
        self.assertTrue(_json(answer)["sent"])
        self.assertEqual(_json(answer)["last_sent"], self.lead.pk)
        self.assertEqual(self.marked(), self.lead.pk)
        self.their_message(sender="447700900777", wamid="wamid.in.second")
        answer = self.post(self.sales, "v1_b2b_lead_whatsapp", {"number": "+44 7700 900777"}, self.second.pk)
        self.assertEqual(answer.status_code, 200, answer.content)
        self.assertFalse(_json(answer)["sent"])
        self.assertNotIn("last_sent", _json(answer))
        self.assertEqual(self.marked(), self.lead.pk)

    def test_the_email_door_marks_the_row(self):
        answer = self.post(self.sales, "v1_b2b_lead_email", {"subject": "Rates", "body": "Dear Anna"}, self.lead.pk)
        self.assertEqual(answer.status_code, 200, answer.content)
        self.assertEqual(_json(answer)["last_sent"], self.lead.pk)
        self.assertEqual(self.marked(), self.lead.pk)

    def test_a_marked_row_deleted_leaves_the_sheet_unmarked(self):
        LeadSheet.objects.filter(pk=self.sheet.pk).update(last_sent=self.second)
        self.second.delete()
        self.assertIsNone(self.marked())


class _Answer:
    """What ``urllib`` hands back: headers, and the body read in one go."""

    def __init__(self, body, kind="text/csv; charset=utf-8"):
        self.body, self.headers = body, {"Content-Type": kind}

    def read(self, limit=-1):
        return self.body if limit < 0 else self.body[:limit]

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


class LinkTests(_B2b):
    """A Google Sheets link instead of a file (12/10/2026): the server reads the sheet itself, when it is open to a link."""

    LINK = "https://docs.google.com/spreadsheets/d/1ApFC-DzCnxbIANj_AFZpWmAvaqleT74NYP0eU2xjsGQ/edit?usp=sharing"

    def read(self, link):
        return self.post(self.sales, "v1_b2b_rows_read", {"link": link}, self.sheet.pk)

    def test_the_export_address_is_built_from_the_id_and_the_tab_only(self):
        sheet_id = "1ApFC-DzCnxbIANj_AFZpWmAvaqleT74NYP0eU2xjsGQ"
        self.assertEqual(b2b_import.export_url(self.LINK), f"https://docs.google.com/spreadsheets/d/{sheet_id}/export?format=csv")
        self.assertEqual(
            b2b_import.export_url(f"https://docs.google.com/spreadsheets/d/{sheet_id}/edit#gid=12345"),
            f"https://docs.google.com/spreadsheets/d/{sheet_id}/export?format=csv&gid=12345",
        )
        self.assertEqual(
            b2b_import.export_url("https://docs.google.com/spreadsheets/d/e/2PACX-1vQabcdefghijklmnopqrstuv/pubhtml"),
            "https://docs.google.com/spreadsheets/d/e/2PACX-1vQabcdefghijklmnopqrstuv/pub?output=csv",
        )
        for bad in (
            "http://docs.google.com/spreadsheets/d/1ApFC-DzCnxbIANj_AFZpWmAvaqleT74NYP0eU2xjsGQ/edit",
            "https://docs.google.com.evil.test/spreadsheets/d/1ApFC-DzCnxbIANj_AFZpWmAvaqleT74NYP0eU2xjsGQ/edit",
            "https://evil.test/?https://docs.google.com/spreadsheets/d/1ApFC-DzCnxbIANj_AFZpWmAvaqleT74NYP0eU2xjsGQ",
            "https://docs.google.com/document/d/1ApFC-DzCnxbIANj_AFZpWmAvaqleT74NYP0eU2xjsGQ/edit",
            "https://docs.google.com/spreadsheets/d/short/edit",
            "file:///etc/passwd",
        ):
            with self.assertRaises(b2b_import.Unreadable, msg=bad):
                b2b_import.export_url(bad)

    def test_a_shared_sheet_is_read_into_rows_and_nothing_is_written(self):
        csv = TEAM_SHEET.encode("utf-8")
        with mock.patch("dashboard.b2b_import._open", return_value=_Answer(csv)) as opened:
            answer = self.read(self.LINK)
        self.assertEqual(answer.status_code, 200, answer.content)
        self.assertTrue(opened.call_args.args[0].startswith("https://docs.google.com/spreadsheets/d/1ApFC"))
        body = _json(answer)
        self.assertEqual([row["company_name"] for row in body["rows"]][:2], ["BASH", "Tathkarah travels"])
        self.assertEqual(body["rows"][0]["status"], "contacted")
        self.assertEqual(Lead.objects.count(), 1)
        self.assertTrue(AuditLog.objects.filter(action="b2b.read_link").exists())

    def test_a_closed_sheet_says_how_to_open_it(self):
        sign_in = _Answer(b"<!DOCTYPE html><html>Sign in</html>", kind="text/html")
        with mock.patch("dashboard.b2b_import._open", return_value=sign_in):
            body = _json(self.read(self.LINK))
        self.assertEqual(body["error"], "unreadable")
        self.assertIn("Anyone with the link", body["message_en"])

    def test_a_redirect_off_google_is_never_followed(self):
        handler = b2b_import._StayOnGoogle()
        for away in ("https://accounts.google.com/ServiceLogin?continue=x", "https://evil.test/x", "http://doc-0s.googleusercontent.com/x"):
            with self.assertRaises(b2b_import.Unreadable, msg=away):
                handler.redirect_request(None, None, 302, "Found", {}, away)
        self.assertTrue(b2b_import._google_host("https://doc-0s-1c-sheets.googleusercontent.com/export/abc"))
        self.assertFalse(b2b_import._google_host("https://googleusercontent.com.evil.test/x"))

    def test_google_unreachable_or_missing_or_too_big_says_why(self):
        import urllib.error

        cases = (
            (urllib.error.HTTPError(self.LINK, 404, "Not Found", {}, None), "does not exist"),
            (urllib.error.HTTPError(self.LINK, 403, "Forbidden", {}, None), "Anyone with the link"),
            (urllib.error.URLError("down"), "Could not reach Google"),
            (TimeoutError(), "Could not reach Google"),
        )
        for failure, words in cases:
            with mock.patch("dashboard.b2b_import._open", side_effect=failure):
                self.assertIn(words, _json(self.read(self.LINK))["message_en"])
        huge = _Answer(b"a,b\n" * (b2b_import.MAX_FILE_BYTES // 4 + 10))
        with mock.patch("dashboard.b2b_import._open", return_value=huge):
            self.assertIn("over 5 MB", _json(self.read(self.LINK))["message_en"])

    def test_a_link_that_is_not_a_sheet_opens_nothing(self):
        with mock.patch("dashboard.b2b_import._open") as opened:
            body = _json(self.read("http://127.0.0.1:8000/admin/"))
            self.assertEqual(self.read(5).status_code, 400)
        self.assertEqual(body["error"], "unreadable")
        opened.assert_not_called()


class NotACompanyListTests(SimpleTestCase):
    def test_a_sheet_whose_header_names_no_company_says_so(self):
        report = "مكالمات ,واتساب ,الايميلات ,عدد الشركات ,التاريخ ,الدوله \n,,67 ايميل ,87,8-9,السعوديه \n"
        with self.assertRaises(b2b_import.Unreadable) as caught:
            b2b_import.to_rows(b2b_import.read_text(report))
        self.assertIn("company column", caught.exception.en)
        # A paste with no header at all is still read in the sheet's own order.
        rows, mapped = b2b_import.to_rows(b2b_import.read_text("Alpha Ltd\tGermany\n"))
        self.assertEqual((rows[0]["company_name"], rows[0]["country"], mapped), ("Alpha Ltd", "Germany", {}))
