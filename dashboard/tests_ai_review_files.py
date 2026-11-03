"""«مراجعة بالـAI» gives back the Word file with the corrections made (03/11/2026).

The AI cannot write a file, so it lists edits at the end of its answer and the server makes them in a copy of the leader's ``.docx``:

- the edit blocks never reach the leader, only the prose and a line saying which file is ready and what could not be done;
- the copy keeps the rest of the file as it was, takes words split over several runs, escapes what XML needs, and changes every place;
- the copy is kept on the answer, opens for its owner and nobody else, and a later edit goes on from the last copy;
- a PDF, a name that is not in the session and words that are not in the file are said, never made up.
"""

import io
import zipfile

from django.core.files.uploadedfile import SimpleUploadedFile
from django.urls import reverse

from . import ai, docx_edit, doc_review, files
from .models import AIReviewFile, AIReviewMessage
from .tests_ai_review_chat import SEND, _json, _Review

STYLES = '<w:styles xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main"><w:style w:styleId="Keep"/></w:styles>'


def _docx(*paragraphs):
    """A Word file whose paragraphs are each a list of runs (or one string)."""
    body = ""
    for paragraph in paragraphs:
        runs = [paragraph] if isinstance(paragraph, str) else paragraph
        body += "<w:p>" + "".join(f'<w:r><w:rPr><w:b/></w:rPr><w:t>{run}</w:t></w:r>' for run in runs) + "</w:p>"
    document = (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        '<w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main"><w:body>' + body + "</w:body></w:document>"
    )
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as archive:
        archive.writestr("[Content_Types].xml", "<Types/>")
        archive.writestr("word/document.xml", document)
        archive.writestr("word/styles.xml", STYLES)
    return buffer.getvalue()


def _upload(name, raw):
    return SimpleUploadedFile(name, raw, content_type="application/vnd.openxmlformats-officedocument.wordprocessingml.document")


def _part(raw, name="word/document.xml"):
    with zipfile.ZipFile(io.BytesIO(raw)) as archive:
        return archive.read(name).decode("utf-8")


def _block(name, *pairs):
    lines = "".join(f"OLD: {old}\nNEW: {new}\n" for old, new in pairs)
    return f"[[FILE: {name}]]\n{lines}[[END]]"


class DocxEditTests(_Review):
    def test_words_split_over_runs_are_changed_in_the_run_where_they_began(self):
        raw = _docx(["Total: 1", "23 AED", " paid"])
        new, counts = docx_edit.apply(raw, [("123", "456")])
        self.assertEqual(counts, [1])
        self.assertEqual(ai.text_from_bytes(new, "a.docx").strip(), "Total: 456 AED paid")
        # The words went into the first run of the old ones: its look stays, the rest of what it covered is taken out.
        self.assertIn("<w:t>Total: 456</w:t>", _part(new))
        self.assertIn('<w:t xml:space="preserve"> AED</w:t>', _part(new))

    def test_every_place_is_changed_and_nothing_else_of_the_file_is(self):
        raw = _docx("ذ.م.م و ذ.م.م", "غيره")
        new, counts = docx_edit.apply(raw, [("ذ.م.م", "ش.ذ.م.م")])
        self.assertEqual(counts, [2])
        self.assertEqual(_part(new, "word/styles.xml"), STYLES)
        self.assertEqual(_part(new).count("ش.ذ.م.م"), 2)
        self.assertIn("غيره", _part(new))
        self.assertEqual(sorted(zipfile.ZipFile(io.BytesIO(new)).namelist()), sorted(zipfile.ZipFile(io.BytesIO(raw)).namelist()))

    def test_what_xml_needs_is_escaped_and_read_back(self):
        raw = _docx("A &amp; B &lt; C")
        new, counts = docx_edit.apply(raw, [("A & B", "X & Y <z>")])
        self.assertEqual(counts, [1])
        self.assertIn("X &amp; Y &lt;z&gt; &lt; C", _part(new))

    def test_a_space_that_is_not_one_matches_the_space_the_model_wrote(self):
        raw = _docx("P.O.Box 58670")
        new, counts = docx_edit.apply(raw, [("P.O.Box 58670", "P.O.Box 11111")])
        self.assertEqual(counts, [1])
        self.assertIn("P.O.Box 11111", _part(new))

    def test_nothing_found_gives_the_same_file_back(self):
        raw = _docx("hello")
        new, counts = docx_edit.apply(raw, [("absent", "x")])
        self.assertEqual((new, counts), (raw, [0]))

    def test_a_file_that_is_not_word_is_refused(self):
        with self.assertRaises(docx_edit.DocxError):
            docx_edit.apply(b"%PDF-1.4 not a zip", [("a", "b")])
        archive = io.BytesIO()
        with zipfile.ZipFile(archive, "w") as zipped:
            zipped.writestr("readme.txt", "x")
        with self.assertRaises(docx_edit.DocxError):
            docx_edit.apply(archive.getvalue(), [("a", "b")])


class SplitTests(_Review):
    def test_the_blocks_are_taken_out_and_kept_in_order(self):
        text = "غلطتين.\n\n" + _block("a.docx", ("one", "1"), ("two", "2")) + "\n" + _block("a.docx", ("three", "3")) + "\n" + _block("b.docx", ("x", ""))
        prose, edits, cut = doc_review.split_edits(text)
        self.assertEqual(prose, "غلطتين.")
        self.assertEqual(edits, {"a.docx": [("one", "1"), ("two", "2"), ("three", "3")], "b.docx": [("x", "")]})
        self.assertFalse(cut)

    def test_a_block_left_open_is_dropped_and_said(self):
        prose, edits, cut = doc_review.split_edits("تمام.\n[[FILE: a.docx]]\nOLD: a\nNEW: b\n")
        self.assertEqual((prose, edits, cut), ("تمام.", {}, True))


class FilesFromAnswerTests(_Review):
    def start(self, name="Receipt.docx", raw=None, text="صلّح الملف"):
        raw = raw or _docx("ختم: فلنسبورج للاستثمارات", "رقم 123")
        session = _json(self.write(text, uploads=[_upload(name, raw)]))["session"]["id"]
        return session, raw

    def answered(self, session, text):
        self.answer(text)
        return _json(self.read(session))["messages"][-1]

    def test_the_answer_carries_the_edited_file_and_hides_the_blocks(self):
        session, raw = self.start()
        line = self.answered(session, "غيّرت الختم.\n" + _block("Receipt.docx", ("فلنسبورج للاستثمارات", "فلنسبورغ للاستثمار")))
        self.assertEqual(line["status"], "done")
        self.assertNotIn("[[", line["body"])
        self.assertIn("غيّرت الختم.", line["body"])
        self.assertIn("الملف المعدّل جاهز للتحميل: Receipt (edited).docx (1 تعديل)", line["body"])
        (shown,) = line["files"]
        self.assertEqual(shown["name"], "Receipt (edited).docx")
        self.assertTrue(shown["url"].startswith("/files/aireview/"))
        stored = AIReviewFile.objects.get(message__role=AIReviewMessage.Role.ASSISTANT)
        self.assertIn("فلنسبورغ للاستثمار", ai.text_from_bytes(stored.file.read(), "x.docx"))
        # The file he sent is untouched.
        sent = AIReviewFile.objects.get(message__role=AIReviewMessage.Role.USER)
        self.assertEqual(sent.file.read(), raw)

    def test_the_copy_opens_for_its_owner_and_nobody_else(self):
        session, _raw = self.start()
        self.answered(session, _block("Receipt.docx", ("123", "456")))
        stored = AIReviewFile.objects.get(message__role=AIReviewMessage.Role.ASSISTANT)
        self.assertTrue(files.may_open(self.lead, stored.file.name)[0])
        for who in (self.other_lead, self.admin, self.ops, self.translator):
            self.assertFalse(files.may_open(who, stored.file.name)[0], who.username)

    def test_a_later_edit_goes_on_from_the_last_copy(self):
        session, _raw = self.start()
        self.answered(session, _block("Receipt.docx", ("123", "456")))
        self.write("وكمان الختم", session=session)
        self.answered(session, _block("Receipt.docx", ("فلنسبورج", "فلنسبورغ")))
        copies = AIReviewFile.objects.filter(message__role=AIReviewMessage.Role.ASSISTANT).order_by("id")
        self.assertEqual(copies.count(), 2)
        last = ai.text_from_bytes(copies.last().file.read(), "x.docx")
        self.assertIn("456", last)
        self.assertIn("فلنسبورغ", last)
        # The edited copy may also be named: it is the same file.
        self.write("كمان", session=session)
        self.answered(session, _block("Receipt (edited).docx", ("456", "789")))
        self.assertIn("789", ai.text_from_bytes(AIReviewFile.objects.order_by("id").last().file.read(), "x.docx"))

    def test_what_cannot_be_done_is_said_and_no_file_is_made_up(self):
        session, _raw = self.start()
        line = self.answered(
            session,
            "حاولت.\n" + _block("Receipt.docx", ("مش موجودة", "x")) + "\n" + _block("Other.docx", ("a", "b")) + "\n" + _block("scan.pdf", ("a", "b")),
        )
        self.assertEqual(line["files"], [])
        self.assertIn("مالقيتش في الملف «مش موجودة»", line["body"])
        self.assertIn("Other.docx: مش في الجلسة دي", line["body"])
        self.assertIn("scan.pdf: مش ملف Word (.docx) فمش بيتعدّل", line["body"])
        self.assertFalse(AIReviewFile.objects.filter(message__role=AIReviewMessage.Role.ASSISTANT).exists())

    def test_an_answer_of_blocks_only_still_says_what_is_ready(self):
        session, _raw = self.start()
        line = self.answered(session, _block("Receipt.docx", ("123", "456")))
        self.assertEqual(line["status"], "done")
        self.assertTrue(line["body"].startswith("— الملف المعدّل جاهز"))

    def test_a_file_that_is_not_word_inside_a_docx_name_is_said(self):
        session, _raw = self.start(name="Fake.docx", raw=b"not a zip at all")
        line = self.answered(session, _block("Fake.docx", ("a", "b")))
        self.assertIn("Fake.docx: مش ملف Word سليم", line["body"])
        self.assertEqual(line["files"], [])

    def test_an_answer_without_blocks_is_as_it_was(self):
        session, _raw = self.start()
        line = self.answered(session, "الترجمة سليمة.")
        self.assertEqual((line["body"], line["files"]), ("الترجمة سليمة.", []))

    def test_the_model_is_told_it_can_hand_back_a_word_file(self):
        self.assertIn("[[FILE:", doc_review.SYSTEM_PROMPT)
        self.assertIn("[[END]]", doc_review.SYSTEM_PROMPT)

    def test_the_file_is_not_sent_back_to_the_model_as_the_leaders(self):
        session, _raw = self.start()
        self.answered(session, _block("Receipt.docx", ("123", "456")))
        self.write("كمان", session=session)
        call = self.answer("تمام")
        sent = call.call_args.args[1]
        names = [block["text"] for message in sent if message["role"] == "user" for block in message["content"] if block["type"] == "text"]
        self.assertFalse(any("(edited)" in text for text in names if text.startswith("===")))
