"""A file on a client's requirements (27/10/2026): the operation or a team leader attaches it, the people on the job read it.

The rules: it is added through the same two doors as the words (the task's and the client's), the name it came with is shown by
the client's code to everybody but the admin, and it opens only to who reads those requirements (``files._requirement_open_to``).
"""

import tempfile

from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import Client as DjangoClient
from django.test import override_settings
from django.urls import reverse

from . import files, services
from .models import AuditLog, ClientRequirement, Role, User
from .tests_api_v1 import CLIENT_NAME, _json, _Site

LOCAL = {"default": {"BACKEND": "dashboard.storages.ProtectedFileSystemStorage"}}
TASK_DOOR = "dashboard:v1_task_requirement"
CLIENT_DOOR = "dashboard:v1_client_requirement"


class _Requirements(_Site):
    def setUp(self):
        super().setUp()
        from django.conf import settings

        media = tempfile.TemporaryDirectory()
        self.addCleanup(media.cleanup)
        override = override_settings(MEDIA_ROOT=media.name, STORAGES={**dict(settings.STORAGES), **LOCAL})
        override.enable()
        self.addCleanup(override.disable)
        self.lead2 = User.objects.create_user("person_leader_two", password="pw", role=Role.TEAM_LEAD)
        self.tr2 = User.objects.create_user("person_translator_two", password="pw", role=Role.TRANSLATOR, team_lead=self.lead2)

    def browser(self, who):
        browser = DjangoClient()
        if who is not None:
            browser.force_login(who)
        return browser

    def upload(self, name="style guide.txt", body=b"use short sentences"):
        return SimpleUploadedFile(name, body, content_type="text/plain")

    def attach(self, who, door=TASK_DOOR, args=None, **fields):
        payload = {"kind": "rule", "text": "", "file": self.upload()}
        payload.update(fields)
        return self.browser(who).post(reverse(door, args=args or [self.task.code]), payload)

    def made(self, who=None, **fields):
        answer = self.attach(who or self.ops, **fields)
        self.assertEqual(answer.status_code, 200, answer.content)
        return ClientRequirement.objects.get(pk=_json(answer)["requirement"]["id"])

    def opens(self, who, row):
        return self.browser(who).get(reverse("dashboard:serve_file", args=[row.file.name])).status_code


class AttachingTests(_Requirements):
    def test_the_operation_attaches_a_file_alone_and_it_comes_back_with_the_row(self):
        answer = self.attach(self.ops)
        self.assertEqual(answer.status_code, 200, answer.content)
        sent = _json(answer)["requirement"]
        self.assertEqual((sent["text"], sent["file"]["name"]), ("", "style guide.txt"))
        self.assertTrue(sent["file"]["url"].startswith("/files/requirements/"))
        row = ClientRequirement.objects.get()
        self.assertEqual((row.client_id, row.author_id, row.size), (self.client_obj.pk, self.ops.pk, len(b"use short sentences")))
        self.assertTrue(AuditLog.objects.filter(action="client.requirement", target=self.client_obj.code).exists())

    def test_the_leader_of_the_task_attaches_a_file_with_words(self):
        row = self.made(self.lead, text="Follow the guide")
        self.assertEqual((row.text, row.author_id), ("Follow the guide", self.lead.pk))
        self.assertTrue(row.file)

    def test_the_client_page_door_takes_a_file_too(self):
        row = self.made(self.ops, door=CLIENT_DOOR, args=[self.client_obj.code])
        self.assertEqual(row.client_id, self.client_obj.pk)
        self.assertTrue(row.file)

    def test_a_file_name_with_the_clients_name_is_shown_by_the_code(self):
        row = self.made(self.ops, file=self.upload(f"{CLIENT_NAME} glossary.txt"))
        self.assertNotIn("ACME", row.original_name)
        self.assertIn(self.client_obj.code, row.original_name)
        self.assertEqual(row.raw_name, f"{CLIENT_NAME} glossary.txt")
        self.assertNotIn("ACME", row.file.name)
        self.assertNotIn("ACME", files.download_name(self.lead, row.file.name, ("requirement", row)))
        self.assertIn("ACME", files.download_name(self.admin, row.file.name, ("requirement", row)))

    def test_neither_words_nor_file_is_refused_and_nothing_is_written(self):
        answer = self.browser(self.ops).post(reverse(TASK_DOOR, args=[self.task.code]), {"kind": "rule", "text": "  "})
        self.assertEqual((answer.status_code, _json(answer)["error"]), (400, "bad_requirement"))
        self.assertEqual(ClientRequirement.objects.count(), 0)

    def test_an_empty_file_a_huge_file_and_two_files_are_refused(self):
        with override_settings():
            from . import api_ops

            old = api_ops.MAX_REQUIREMENT_FILE_BYTES
            api_ops.MAX_REQUIREMENT_FILE_BYTES = 10
            self.addCleanup(setattr, api_ops, "MAX_REQUIREMENT_FILE_BYTES", old)
            big = self.attach(self.ops, file=self.upload(body=b"x" * 11))
        empty = self.attach(self.ops, file=self.upload(body=b""))
        two = self.browser(self.ops).post(
            reverse(TASK_DOOR, args=[self.task.code]), {"kind": "rule", "text": "x", "file": [self.upload(), self.upload("b.txt")]},
        )
        self.assertEqual([(a.status_code, _json(a)["error"]) for a in (big, empty, two)],
                         [(400, "file_too_big"), (400, "empty_file"), (400, "bad_request")])
        self.assertEqual(ClientRequirement.objects.count(), 0)

    def test_who_may_not_write_a_requirement_may_not_attach_a_file(self):
        for who in (self.tr, self.hr, self.reviewer, self.accounting, self.sales):
            self.assertEqual(self.attach(who).status_code, 403, who.username)
        # A leader who is not on the task does not find it.
        self.assertEqual(self.attach(self.lead2).status_code, 404)
        self.assertEqual(ClientRequirement.objects.count(), 0)


class OpeningTests(_Requirements):
    def test_who_reads_the_requirements_opens_the_file(self):
        row = self.made(self.ops)
        for who in (self.ops, self.admin, self.lead, self.tr, self.sales):
            self.assertEqual(self.opens(who, row), 200, who.username)

    def test_everybody_else_is_refused_with_a_404(self):
        row = self.made(self.ops)
        for who in (self.lead2, self.tr2, self.hr, self.reviewer, self.accounting, None):
            self.assertIn(self.opens(who, row), (302, 401, 404), getattr(who, "username", "anonymous"))
            self.assertNotEqual(self.opens(who, row), 200, getattr(who, "username", "anonymous"))

    def test_a_translator_who_left_the_clients_work_no_longer_opens_it(self):
        row = self.made(self.ops)
        self.assertEqual(self.opens(self.tr, row), 200)
        self.task.assignments.filter(assignee=self.tr).update(status="cancelled")
        self.task.translator = None
        self.task.save(update_fields=["translator"])
        self.assertEqual(self.opens(self.tr, row), 404)


def _docx(text):
    import io
    import zipfile

    out = io.BytesIO()
    with zipfile.ZipFile(out, "w") as archive:
        archive.writestr("word/document.xml", f"<w:document><w:body><w:p><w:r><w:t>{text}</w:t></w:r></w:p></w:body></w:document>")
    return out.getvalue()


class PreviewTests(_Requirements):
    """The page draws the file itself (a Word file's text, a PDF's pages): the same address answers, under the same rule."""

    def test_a_word_file_is_read_as_text_by_who_may_open_it_and_by_nobody_else(self):
        row = self.made(self.ops, file=self.upload("rules.docx", _docx("Always say Dear Sir")))
        url = reverse("dashboard:serve_file", args=[row.file.name])
        for who in (self.ops, self.lead, self.tr):
            answer = self.browser(who).get(url, {"preview": "full"})
            self.assertEqual(answer.status_code, 200, who.username)
            self.assertEqual(_json(answer)["text"], "Always say Dear Sir")
        for who in (self.lead2, self.tr2, self.hr):
            self.assertEqual(self.browser(who).get(url, {"preview": "full"}).status_code, 404, who.username)

    def test_a_pdf_opens_inline_for_the_page_and_a_download_asks_for_it(self):
        row = self.made(self.ops, file=SimpleUploadedFile("guide.pdf", b"%PDF-1.4 x", content_type="application/pdf"))
        url = reverse("dashboard:serve_file", args=[row.file.name])
        inline = self.browser(self.lead).get(url)
        self.assertEqual((inline.status_code, inline["Content-Type"]), (200, "application/pdf"))
        self.assertTrue(inline["Content-Disposition"].startswith("inline"))
        saved = self.browser(self.lead).get(url, {"dl": "1"})
        self.assertTrue(saved["Content-Disposition"].startswith("attachment"))


class EdgeTests(_Requirements):
    def test_technical_support_neither_opens_the_file_nor_reads_the_requirements(self):
        support = User.objects.create_user("person_support", password="pw", role=Role.SUPPORT)
        row = self.made(self.ops)
        self.assertEqual(self.opens(support, row), 404)
        self.assertEqual(_json(self.get(support, "v1_task", [self.task.code]))["task"]["requirements"], [])
        self.assertEqual(self.get(support, "v1_client", [self.client_obj.code]).status_code, 403)
        self.assertEqual(self.get(support, "v1_translator_task", [self.task.code]).status_code, 403)

    def test_an_accountant_with_the_identity_switch_still_does_not_open_it(self):
        self.accounting.client_identity_access = True
        self.accounting.save()
        row = self.made(self.ops)
        self.assertEqual(self.opens(self.accounting, row), 404)

    def test_a_leader_taken_off_the_task_stops_opening_it(self):
        row = self.made(self.ops)
        self.assertEqual(self.opens(self.lead, row), 200)
        self.task.team_lead = self.lead2
        self.task.save(update_fields=["team_lead"])
        self.assertEqual(self.opens(self.lead, row), 404)
        self.assertEqual(self.opens(self.lead2, row), 200)

    def test_a_translator_offered_the_job_reads_the_file_before_accepting(self):
        # The task page shows the requirements to who is offered the job, so the file opens to them too.
        row = self.made(self.ops)
        self.task.assignments.filter(assignee=self.tr).update(status="pending")
        self.task.translator = None
        self.task.save(update_fields=["translator"])
        self.assertEqual(self.opens(self.tr, row), 200)

    def test_deleting_the_client_removes_the_stored_file(self):
        from django.core.files.storage import default_storage

        from .models import Client

        client = Client.objects.create(phone="+201007770000")
        row = ClientRequirement.objects.create(client=client, kind="rule", text="", author=self.ops, file=self.upload("rules.txt"))
        name = row.file.name
        self.assertTrue(default_storage.exists(name))
        ok, error, *_rest = services.delete_clients(self.admin, [client.pk])
        self.assertTrue(ok, error)
        self.assertFalse(default_storage.exists(name))


class ReadingTests(_Requirements):
    def test_the_operation_the_client_page_and_the_translator_see_the_file_by_its_masked_name(self):
        self.made(self.ops, file=self.upload(f"{CLIENT_NAME} rules.txt"))
        reads = (
            (self.ops, "v1_task", [self.task.code], lambda body: body["task"]["requirements"]),
            (self.lead, "v1_task", [self.task.code], lambda body: body["task"]["requirements"]),
            (self.ops, "v1_client", [self.client_obj.code], lambda body: body["requirements"]),
            (self.tr, "v1_translator_task", [self.task.code], lambda body: body["task"]["requirements"]),
        )
        for who, name, args, pick in reads:
            answer = self.get(who, name, args)
            self.assertEqual(answer.status_code, 200, (who.username, name))
            (requirement,) = pick(_json(answer))
            self.assertIn(self.client_obj.code, requirement["file"]["name"])
            self.assertNotIn("ACME", answer.content.decode("utf-8"))

    def test_a_requirement_with_no_file_says_so(self):
        ClientRequirement.objects.create(client=self.client_obj, kind="rule", text="Formal tone", author=self.ops)
        (requirement,) = _json(self.get(self.ops, "v1_client", [self.client_obj.code]))["requirements"]
        self.assertIsNone(requirement["file"])

    def test_the_ai_is_told_the_words_and_not_the_empty_ones(self):
        from . import ai

        self.made(self.ops)
        ClientRequirement.objects.create(client=self.client_obj, kind="like", text="Short", author=self.ops)
        self.assertEqual(ai.requirements_text(self.task), "- [Likes] Short")

    def test_remasking_follows_a_name_the_admin_writes_later(self):
        bare = services.ingest_message  # noqa: F841 - the base class built the client with a name; make a fresh one without
        from .models import Client

        client = Client.objects.create(phone="+201009990000")
        row = ClientRequirement.objects.create(
            client=client, kind="rule", text="", author=self.ops, file=self.upload("Zenith Corp rules.txt"),
            original_name="Zenith Corp rules.txt", raw_name="Zenith Corp rules.txt",
        )
        client.name = "Zenith Corp"
        client.save()
        files.remask_names(client)
        row.refresh_from_db()
        self.assertNotIn("Zenith", row.original_name)
        self.assertIn(client.code, row.original_name)
