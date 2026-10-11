"""Reading companies into a B2B sheet from an Excel file, a CSV or pasted cells (``b2b_import``, ``api_b2b.rows_read``).

Held here: the columns are found by their names in either language and in any order; a phone typed as a number keeps its
digits; the workbook's first sheet is read even when it is not ``sheet1.xml``; CSV from Google Sheets (UTF-8) and from an
Arabic Excel (Windows-1256) both read; a file that is not one, an old ``.xls``, a DTD or a file too large is refused; and
nothing is ever written by reading - the same doors as the sheet decide who may.
"""

import io
import zipfile

from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import SimpleTestCase
from django.urls import reverse

from . import b2b_import
from .models import Lead
from .tests_b2b import _B2b, _json

MAIN = 'xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main"'
REL_NS = 'xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships"'


def xlsx(rows, sheet_file="sheet1.xml", inline=False, extra=None):
    """A minimal .xlsx: ``rows`` of strings or numbers, strings shared (or inline), the first sheet at ``sheet_file``."""
    shared, xml_rows = [], []
    for r, line in enumerate(rows, start=1):
        cells = []
        for c, value in enumerate(line):
            ref = f"{chr(65 + c)}{r}"
            if isinstance(value, (int, float)):
                cells.append(f'<c r="{ref}"><v>{value}</v></c>')
            elif inline:
                cells.append(f'<c r="{ref}" t="inlineStr"><is><t>{value}</t></is></c>')
            else:
                shared.append(value)
                cells.append(f'<c r="{ref}" t="s"><v>{len(shared) - 1}</v></c>')
        xml_rows.append(f'<row r="{r}">{"".join(cells)}</row>')
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as archive:
        archive.writestr("xl/workbook.xml", f'<workbook {MAIN} {REL_NS}><sheets><sheet name="Leads" sheetId="1" r:id="rId1"/></sheets></workbook>')
        archive.writestr("xl/_rels/workbook.xml.rels",
                         '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
                         f'<Relationship Id="rId1" Target="worksheets/{sheet_file}"/></Relationships>')
        archive.writestr("xl/sharedStrings.xml", f'<sst {MAIN}>' + "".join(f"<si><t>{s}</t></si>" for s in shared) + "</sst>")
        archive.writestr(f"xl/worksheets/{sheet_file}", f'<worksheet {MAIN}><sheetData>{"".join(xml_rows)}</sheetData></worksheet>')
        for name, content in (extra or {}).items():
            archive.writestr(name, content)
    return buffer.getvalue()


class ReadTests(SimpleTestCase):
    def test_columns_are_found_by_name_in_any_order_and_a_numeric_phone_keeps_its_digits(self):
        data = xlsx([["Email", "Company Name", "Mobile", "Country"], ["a@alpha.test", "Alpha Ltd", 201012345678.0, "Egypt"]])
        rows, mapped = b2b_import.read("leads.xlsx", data)
        self.assertEqual(len(rows), 1)
        self.assertEqual((rows[0]["company_name"], rows[0]["email"], rows[0]["phone"], rows[0]["country"]),
                         ("Alpha Ltd", "a@alpha.test", "201012345678", "Egypt"))
        self.assertEqual(mapped["phone"], "Mobile")

    def test_arabic_headers_and_inline_strings(self):
        data = xlsx([["اسم الشركه", "الموبايل", "الإيميل"], ["شركة بيتا", "01000000000", "b@beta.test"]], inline=True)
        rows, _mapped = b2b_import.read("x.xlsx", data)
        self.assertEqual((rows[0]["company_name"], rows[0]["phone"], rows[0]["email"]), ("شركة بيتا", "01000000000", "b@beta.test"))

    def test_the_first_sheet_is_found_through_the_workbook(self):
        data = xlsx([["Company"], ["Gamma"]], sheet_file="sheet7.xml")
        self.assertEqual(b2b_import.read("x.xlsx", data)[0][0]["company_name"], "Gamma")

    def test_no_header_reads_in_the_sheets_order_and_empty_lines_are_dropped(self):
        rows, mapped = b2b_import.to_rows(b2b_import.read_text("Delta\tFrance\n\n\nEpsilon\tSpain\n"))
        self.assertEqual([(r["company_name"], r["country"]) for r in rows], [("Delta", "France"), ("Epsilon", "Spain")])
        self.assertEqual(mapped, {})

    def test_csv_from_google_sheets_and_from_an_arabic_excel(self):
        google = "Company,WhatsApp,Languages\nZeta,+44 7700 900111,\"EN>AR, FR>AR\"\n".encode("utf-8-sig")
        rows, _ = b2b_import.read("Leads - Sheet1.csv", google)
        self.assertEqual((rows[0]["whatsapp"], rows[0]["languages"]), ("+44 7700 900111", "EN>AR, FR>AR"))
        arabic = "الشركة;الدولة\nشركة إيتا;مصر\n".encode("cp1256")
        rows, _ = b2b_import.read("leads.csv", arabic)
        self.assertEqual((rows[0]["company_name"], rows[0]["country"]), ("شركة إيتا", "مصر"))

    def test_a_cell_is_cut_to_its_columns_length(self):
        rows, _ = b2b_import.to_rows([["Company", "Country"], ["Theta", "x" * 300]])
        self.assertEqual(len(rows[0]["country"]), 80)

    def test_what_is_not_a_spreadsheet_is_refused(self):
        bomb = xlsx([["Company"], ["A"]], extra={"xl/sharedStrings.xml": '<!DOCTYPE x [<!ENTITY a "aaaa">]><sst/>'})
        for name, data in (("x.xlsx", b"PK\x03\x04 broken"), ("old.xls", b"\xd0\xcf\x11\xe0"), ("photo.png", b"\x89PNG"),
                           ("x.xlsx", bomb), ("big.csv", b"a" * (b2b_import.MAX_FILE_BYTES + 1))):
            with self.assertRaises(b2b_import.Unreadable, msg=name):
                b2b_import.read(name, data)


class DoorTests(_B2b):
    def read(self, user, **payload):
        browser = self.browser(user)
        url = reverse("dashboard:v1_b2b_rows_read", args=[self.sheet.pk])
        if "text" in payload:
            import json

            return browser.post(url, json.dumps(payload), content_type="application/json")
        return browser.post(url, payload)

    def test_the_door_is_under_api_v1(self):
        self.assertEqual(reverse("dashboard:v1_b2b_rows_read", args=[3]), "/api/v1/b2b/sheets/3/read/")

    def test_a_file_is_read_and_nothing_is_written(self):
        before = Lead.objects.count()
        upload = SimpleUploadedFile("leads.xlsx", xlsx([["Company", "Email"], ["Iota", "i@iota.test"]]))
        body = _json(self.read(self.sales, file=upload))
        self.assertEqual(body["rows"][0]["company_name"], "Iota")
        self.assertEqual(body["mapped"], {"company_name": "Company", "email": "Email"})
        self.assertEqual(Lead.objects.count(), before)

    def test_pasted_cells_are_read_the_same_way(self):
        body = _json(self.read(self.sales, text="Company\tPhone\nKappa\t+20100"))
        self.assertEqual((body["rows"][0]["company_name"], body["rows"][0]["phone"]), ("Kappa", "+20100"))

    def test_an_unreadable_file_says_why(self):
        answer = self.read(self.sales, file=SimpleUploadedFile("old.xls", b"\xd0\xcf\x11\xe0"))
        self.assertEqual((answer.status_code, _json(answer)["error"]), (400, "unreadable"))
        self.assertIn(".xlsx", _json(answer)["message"])

    def test_the_sheets_own_doors_decide_who_may(self):
        upload = lambda: SimpleUploadedFile("leads.csv", b"Company\nLambda\n")
        self.assertEqual(self.read(self.other, file=upload()).status_code, 404)
        self.assertEqual(self.read(self.ops, file=upload()).status_code, 403)
        self.assertEqual(self.read(self.manager, file=upload()).status_code, 200)
