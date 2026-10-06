"""``/files/<path>?preview=full``: the whole text of a Word file, for the viewer that opens it over the chat instead of saving it.

The viewer is the same protected address as a download, so the same rule decides who may open it. What these tests hold: the text
comes back whole up to a limit and says when it was cut, the first-words preview stays short, anybody who may not open the file
gets the same refusal as for the file itself, and a file that is not Word gives no text (the viewer then offers the download).
"""

import io
import zipfile

from django.core.files.base import ContentFile
from django.test import TestCase

from . import files, services
from .models import Role, User


def _docx(paragraphs):
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as archive:
        archive.writestr(
            "word/document.xml",
            "<w:document><w:body>" + "".join(f"<w:p><w:r><w:t>{one}</w:t></w:r></w:p>" for one in paragraphs) + "</w:body></w:document>",
        )
    return buffer.getvalue()


class FullTextTests(TestCase):
    def setUp(self):
        self.ops = User.objects.create_user("person_operation", password="pw", role=Role.OPERATION)
        self.tr = User.objects.create_user("person_translator", password="pw", role=Role.TRANSLATOR)

    def stored(self, name, content):
        message = services.ingest_message(
            channel="whatsapp", body="a file", sender_identity="+201000000888",
            attachments=[{"file": ContentFile(content, name=name), "name": name, "size": len(content), "mime": ""}],
        )
        return message.attachments.get().file.url

    def ask(self, url, who=None, mode="full"):
        self.client.force_login(who or self.ops)
        return self.client.get(url + f"?preview={mode}")

    def test_the_whole_text_comes_back_and_is_not_marked_cut(self):
        url = self.stored("long.docx", _docx([f"Paragraph number {n} " + "word " * 30 for n in range(40)]))
        data = self.ask(url).json()
        self.assertTrue(data["ok"])
        self.assertFalse(data["truncated"])
        self.assertIn("Paragraph number 39", data["text"])
        # The card's own preview stays short.
        short = self.ask(url, mode="1").json()
        self.assertLessEqual(len(short["text"]), files.PREVIEW_CHARS)
        self.assertNotIn("Paragraph number 39", short["text"])

    def test_a_very_long_file_is_cut_at_the_limit_and_says_so(self):
        url = self.stored("huge.docx", _docx(["x" * 1000 for _ in range(files.FULL_TEXT_CHARS // 1000 + 20)]))
        data = self.ask(url).json()
        self.assertTrue(data["truncated"])
        self.assertEqual(len(data["text"]), files.FULL_TEXT_CHARS)

    def test_a_file_exactly_at_the_limit_is_not_called_cut(self):
        text, truncated = files.document_full_text("a.docx", _docx(["y" * (files.FULL_TEXT_CHARS - 1)]))
        self.assertFalse(truncated)
        self.assertEqual(len(text), files.FULL_TEXT_CHARS - 1)

    def test_markup_in_the_file_is_text_in_the_answer(self):
        url = self.stored("markup.docx", _docx(["&lt;img src=x&gt; Birth certificate"]))
        self.assertEqual(self.ask(url).json()["text"], "<img src=x> Birth certificate")

    def test_anybody_who_may_not_open_the_file_gets_the_files_own_refusal(self):
        url = self.stored("private.docx", _docx(["Secret"]))
        refused = self.ask(url, self.tr)
        self.assertEqual(refused.status_code, 404)
        self.assertNotIn("Secret", refused.content.decode("utf-8", errors="ignore"))
        self.assertEqual(self.ask(url, self.tr, mode="1").status_code, 404)
        self.client.logout()
        self.assertIn(self.client.get(url + "?preview=full").status_code, (302, 404))

    def test_a_file_that_is_not_word_gives_no_text(self):
        for name, content in (("a.pdf", b"%PDF-1.4"), ("a.zip", b"PK"), ("a.txt", b"plain")):
            data = self.ask(self.stored(name, content)).json()
            self.assertEqual((data["text"], data["truncated"]), ("", False), name)

    def test_a_broken_word_file_gives_no_text_not_an_error(self):
        data = self.ask(self.stored("broken.docx", b"not a zip at all")).json()
        self.assertEqual((data["ok"], data["text"]), (True, ""))

    def test_the_answer_is_never_cached_by_anybody_in_between(self):
        url = self.stored("c.docx", _docx(["Text"]))
        self.assertEqual(self.ask(url)["Cache-Control"], "private, no-store")

    def test_saving_is_still_a_download_and_the_viewer_never_changes_that(self):
        url = self.stored("d.docx", _docx(["Text"]))
        self.client.force_login(self.ops)
        response = self.client.get(url + "?dl=1")
        self.assertTrue(response["Content-Disposition"].startswith("attachment"))
