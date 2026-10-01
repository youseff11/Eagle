"""``/files/<path>``: what opens inside the page and what is always a download.

A file opened inline runs as our own site, with the viewer's session, if the browser takes it for a document - an SVG,
HTML, any XML type, script. The extension is the uploader's choice, so the decision is made from a short list of the
types known to be inert (``files.opens_inline``), never from a list of the dangerous ones: that list is never complete
(``application/xslt+xml`` and ``application/mathml+xml`` were not on it).
"""

from unittest import mock

from django.core.files.base import ContentFile
from django.test import TestCase

from . import files, services
from .models import Role, User


class OpensInlineTests(TestCase):
    def test_only_the_inert_types_open_in_the_page(self):
        for kind in (
            "image/png", "image/jpeg", "image/gif", "image/webp", "application/pdf", "text/plain",
            "audio/mpeg", "audio/ogg", "audio/webm", "video/mp4", "video/webm",
        ):
            self.assertTrue(files.opens_inline(kind), kind)

    def test_everything_that_can_be_a_document_with_script_is_a_download(self):
        for kind in (
            "image/svg+xml", "text/html", "application/xhtml+xml", "text/xml", "application/xml",
            "application/javascript", "text/javascript", "application/ecmascript",
            # The ones a deny-list of seven types missed.
            "application/xslt+xml", "application/mathml+xml", "application/rdf+xml", "application/atom+xml",
            "application/rss+xml", "application/vnd.mozilla.xul+xml", "application/smil+xml", "application/gpx+xml",
            # And things that are not documents at all, but nothing is gained by showing them.
            "application/octet-stream", "application/zip", "application/json", "text/css", "text/csv",
            "application/msword", "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
            "multipart/mixed", "", None,
        ):
            self.assertFalse(files.opens_inline(kind), kind)

    def test_a_type_is_read_by_what_comes_before_its_parameters_and_without_case(self):
        self.assertTrue(files.opens_inline("text/plain; charset=utf-8"))
        self.assertTrue(files.opens_inline("IMAGE/PNG"))
        self.assertFalse(files.opens_inline("text/html; charset=utf-8"))
        self.assertFalse(files.opens_inline("Application/XSLT+XML"))
        # A family is the whole type name, not any word that starts like it.
        self.assertFalse(files.opens_inline("audiobook/x-fake"))
        self.assertFalse(files.opens_inline("videos/x-fake"))


class ServedFileTests(TestCase):
    """The page that serves a stored file, for somebody who may open it."""

    def setUp(self):
        self.ops = User.objects.create_user("person_operation", password="pw", role=Role.OPERATION)

    def served(self, name, content=b"data", mime="", query=""):
        message = services.ingest_message(
            channel="whatsapp", body="a file", sender_identity="+201000000777",
            attachments=[{"file": ContentFile(content, name=name), "name": name, "size": len(content), "mime": mime}],
        )
        self.client.force_login(self.ops)
        return self.client.get(message.attachments.get().file.url + query)

    def test_a_picture_a_pdf_a_text_and_sound_open_in_the_page(self):
        for name in ("a.png", "a.jpg", "a.jpeg", "a.gif", "a.pdf", "a.txt", "a.mp3", "a.mp4"):
            response = self.served(name)
            self.assertEqual(response.status_code, 200, name)
            self.assertTrue(response["Content-Disposition"].startswith("inline"), (name, response["Content-Disposition"]))

    def test_anything_that_could_be_a_page_of_ours_is_a_download(self):
        for name in ("a.svg", "a.html", "a.htm", "a.xhtml", "a.xml", "a.js", "a.docx", "a.zip", "a.json", "noextension"):
            response = self.served(name)
            self.assertEqual(response.status_code, 200, name)
            self.assertTrue(response["Content-Disposition"].startswith("attachment"), (name, response["Content-Disposition"]))

    def test_a_type_nobody_listed_is_a_download_too(self):
        # What the host's own type table says about an extension is not known here: the type is, and it is XML.
        with mock.patch("dashboard.files.content_type", return_value="application/xslt+xml"):
            response = self.served("transform.xslt")
        self.assertTrue(response["Content-Disposition"].startswith("attachment"))
        self.assertEqual(response["Content-Type"], "application/xslt+xml")

    def test_a_download_can_be_asked_for_by_hand_even_for_a_picture(self):
        response = self.served("a.png", query="?dl=1")
        self.assertTrue(response["Content-Disposition"].startswith("attachment"))

    def test_the_browser_is_told_not_to_guess_a_type_of_its_own(self):
        for name in ("a.png", "a.html", "a.xslt"):
            self.assertEqual(self.served(name)["X-Content-Type-Options"], "nosniff", name)

    def test_a_page_given_a_picture_name_is_still_served_as_what_the_name_says(self):
        # HTML under a .png name: the type is the picture's, and with nosniff the browser does not make a page of it.
        response = self.served("a.png", content=b"<html><script>alert(1)</script></html>")
        self.assertEqual(response["Content-Type"], "image/png")
        self.assertEqual(response["X-Content-Type-Options"], "nosniff")
