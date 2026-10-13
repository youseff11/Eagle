"""Reading a block of companies into a B2B sheet: an Excel file, a CSV file, or cells pasted from Google Sheets / Excel.

Nothing here writes anything: it reads, and answers the rows it found (``read``), for the Sales person to correct on the page
before they are added (``api_b2b.rows_add``, the same door a typed row goes through).

The columns are found by their names, in Arabic or English ("Company", "اسم الشركة", "Phone", "Mobile", "واتساب"...), so a file
does not have to be in the sheet's order; a first row that names none of them is data, read in the sheet's own order.

Only the standard library, as the project keeps it (CLAUDE.md): an ``.xlsx`` is a zip of XML read with ``zipfile`` and
``xml.etree``. A file is untrusted: its size, its unpacked size and its rows are bounded, and an XML that declares a DTD is
refused (the entity tricks live there).
"""

import csv
import io
import re
import urllib.error
import urllib.request
import zipfile
from urllib.parse import urlsplit
from xml.etree import ElementTree

from . import b2b, net

#: The largest file read, what its parts may unpack to all together, and the most rows a file brings.
MAX_FILE_BYTES = 5 * 1024 * 1024
MAX_UNPACKED_BYTES = 40 * 1024 * 1024
MAX_ROWS = b2b.MAX_PASTE_ROWS
#: The most columns a row is read across.
MAX_COLUMNS = 40

MAIN = "{http://schemas.openxmlformats.org/spreadsheetml/2006/main}"
REL = "{http://schemas.openxmlformats.org/officeDocument/2006/relationships}"
PACKAGE_REL = "{http://schemas.openxmlformats.org/package/2006/relationships}"


class Unreadable(Exception):
    """The file is not one this reads: the reason in both languages."""

    def __init__(self, ar, en):
        super().__init__(en)
        self.ar, self.en = ar, en


# ---------------------------------------------------------------------------
# Which column is which
# ---------------------------------------------------------------------------

#: Words a header may use for each of the sheet's columns, besides the sheet's own names. Compared folded (``_fold``).
SYNONYMS = {
    "company_name": ("company", "company name", "organization", "organisation", "agency", "business", "name of company",
                     "الشركة", "اسم الشركة", "الشركه", "اسم الشركه", "المؤسسة", "الوكالة"),
    "country": ("country", "location", "الدولة", "البلد", "الدوله"),
    "website": ("website", "web site", "site", "url", "web", "الموقع", "الويب سايت", "الموقع الالكتروني"),
    "industry": ("industry", "type", "company type", "sector", "category", "نوع الشركة", "المجال", "النشاط", "القطاع"),
    "contact_person": ("contact", "contact person", "contact name", "person", "name", "full name", "الشخص", "الشخص المسؤول",
                       "المسؤول", "الاسم", "اسم المسؤول"),
    "position": ("position", "title", "job title", "role", "designation", "المنصب", "الوظيفة", "المسمى الوظيفي"),
    "email": ("email", "e-mail", "mail", "email address", "الايميل", "الإيميل", "البريد", "البريد الالكتروني", "ايميل"),
    "phone": ("phone", "telephone", "tel", "phone number", "mobile", "mobile number", "cell", "التليفون", "الهاتف",
              "الموبايل", "رقم التليفون", "رقم الهاتف", "الجوال", "رقم الموبايل"),
    "whatsapp": ("whatsapp", "whats app", "wa", "whatsapp number", "واتساب", "واتس", "رقم الواتساب", "واتس اب"),
    "linkedin": ("linkedin", "linked in", "linkedin url", "لينكدإن", "لينكدان", "لينكد ان"),
    "languages": ("languages", "language", "language pairs", "language pair", "pairs", "اللغات", "اللغة", "ازواج اللغات"),
    "services": ("services", "service", "services required", "needs", "الخدمات", "الخدمات المطلوبة", "الخدمة"),
    "source": ("source", "lead source", "from", "المصدر"),
}


#: The sheet's own fields a file may carry besides the columns (the Sales team's Google Sheet has them): found by their
#: header only, never by their place, and read into the sheet's values (``_sheet_value``).
EXTRA_SYNONYMS = {
    "status": ("status", "stage", "الحالة", "الحاله", "المرحلة"),
    "priority": ("priority", "الأولوية", "الاولوية", "الأولويه"),
    "deal_value": ("deal value", "deal", "value", "amount", "قيمة الصفقة", "قيمة الصفقه", "القيمة"),
    "notes": ("notes", "note", "comments", "remarks", "ملاحظات", "الملاحظات", "ملاحظة"),
}
#: The words a status or a priority cell may hold, as the sheet's values. A word not here leaves the row «New client».
STATUS_WORDS = {
    "new": ("new", "new client", "new lead", "عميل جديد", "جديد"),
    "contacted": ("contacted", "تم التواصل"),
    "follow_up": ("follow up", "follow-up", "followup", "متابعة", "متابعه"),
    "won": ("won", "contracted", "تم التعاقد"),
    "lost": ("lost", "refused", "rejected", "مرفوض"),
    "whatsapp": ("whatsapp", "whats app", "واتساب"),
    "visit": ("visit", "meeting", "زيارة", "زياره"),
    "no_answer": ("no answer", "لم يتم الرد"),
    "call": ("call", "مكالمة", "مكالمه"),
}
PRIORITY_WORDS = {
    "high": ("high", "عالية", "عاليه"),
    "medium": ("medium", "متوسطة", "متوسطه"),
    "low": ("low", "منخفضة", "منخفضه"),
}


def _fold(text):
    """A header as compared: lower case, Arabic letter shapes folded, spaces and punctuation squeezed."""
    text = str(text or "").strip().lower()
    text = re.sub("[ً-ْـ]", "", text)
    text = re.sub("[أإآ]", "ا", text).replace("ة", "ه").replace("ى", "ي")
    return re.sub(r"[\s_\-./:()]+", " ", text).strip()


def _header_index():
    index = {}
    for name, _limit, ar, en in b2b.COLUMNS:
        for word in (name, ar, en, *SYNONYMS.get(name, ())):
            index.setdefault(_fold(word), name)
    for name, words in EXTRA_SYNONYMS.items():
        for word in (name, *words):
            index.setdefault(_fold(word), name)
    return index


def _word_value(cell, words):
    folded = _fold(cell)
    for value, names in words.items():
        if folded in {_fold(name) for name in names}:
            return value
    return ""


def _deal_value(cell):
    """A deal value as a number the sheet takes ("1,500 $" -> "1500"), or "" for anything that is not one."""
    text = re.sub(r"[\s,$٬]", "", cell)
    return text if re.fullmatch(r"\d{1,12}(\.\d{1,2})?", text) else ""


def _sheet_value(name, cell):
    if name == "status":
        return _word_value(cell, STATUS_WORDS)
    if name == "priority":
        return _word_value(cell, PRIORITY_WORDS)
    if name == "deal_value":
        return _deal_value(cell)
    return cell[: b2b.MAX_NOTES]


def map_header(cells):
    """``{position: column}`` for a first row that names the sheet's columns, or ``None`` when it names fewer than two
    of them (a first row of data, read in the sheet's order). A column named twice keeps its first place."""
    index = _header_index()
    found = {}
    for position, cell in enumerate(cells):
        column = index.get(_fold(cell))
        if column and column not in found.values():
            found[position] = column
    return found if len(found) >= 2 or (len(found) == 1 and "company_name" in found.values()) else None


def to_rows(table):
    """``(rows, mapped)``: the table's lines as rows of the sheet's columns, cut to each column's length; lines with nothing
    in them dropped. ``mapped`` is ``{column: the header it came from}`` when the first line named the columns."""
    table = [[str(cell if cell is not None else "").strip() for cell in line[:MAX_COLUMNS]] for line in table]
    table = [line for line in table if any(line)]
    if not table:
        return [], {}
    header = map_header(table[0])
    order = [name for name, *_rest in b2b.COLUMNS]
    if header is not None:
        # A first row that names columns but no company: a sheet of something else (a daily report, payments...), not a
        # list of companies. Said plainly, instead of a grid of rows with no name that adds nothing.
        if "company_name" not in header.values():
            raise Unreadable(
                "مالقيتش عمود اسم الشركة في أول صف. الشيت ده شكله مش قايمة شركات: لازم يبقى فيه عمود اسمه «الشركة» أو «Company».",
                "No company column in the first row. This sheet does not look like a list of companies: it needs a column named «الشركة» or «Company».",
            )
        mapped = {column: table[0][position] for position, column in header.items()}
        body = table[1:]
    else:
        header = dict(enumerate(order))
        mapped = {}
        body = table
    rows = []
    for line in body[:MAX_ROWS]:
        row = {name: "" for name in order}
        for position, column in header.items():
            if position >= len(line):
                continue
            if column in EXTRA_SYNONYMS:
                value = _sheet_value(column, line[position])
                if value:
                    row[column] = value
            else:
                row[column] = line[position][: b2b.COLUMN_LIMITS[column]]
        if any(row.get(name) for name in order):
            rows.append(row)
    return rows, mapped


# ---------------------------------------------------------------------------
# Reading the three kinds
# ---------------------------------------------------------------------------

def _xml(archive, name):
    with archive.open(name) as handle:
        data = handle.read(MAX_UNPACKED_BYTES + 1)
    if len(data) > MAX_UNPACKED_BYTES:
        raise Unreadable("الملف أكبر من اللي ينفع يتقري.", "The file is too large to read.")
    if b"<!DOCTYPE" in data[:4096].upper() or b"<!ENTITY" in data.upper():
        raise Unreadable("الملف ده مش Excel سليم.", "That is not a valid Excel file.")
    try:
        return ElementTree.fromstring(data)
    except ElementTree.ParseError:
        raise Unreadable("الملف ده مش Excel سليم.", "That is not a valid Excel file.") from None


def _column_number(reference):
    """``"C12"`` -> 2 (columns counted from 0)."""
    letters = re.match(r"[A-Z]+", reference or "")
    if not letters:
        return None
    number = 0
    for letter in letters.group(0):
        number = number * 26 + (ord(letter) - 64)
    return number - 1


def _cell_text(cell, shared):
    kind = cell.get("t", "")
    if kind == "inlineStr":
        return "".join(t.text or "" for t in cell.iter(f"{MAIN}t"))
    value = cell.find(f"{MAIN}v")
    raw = value.text if value is not None and value.text is not None else ""
    if kind == "s":
        try:
            return shared[int(raw)]
        except (ValueError, IndexError):
            return ""
    if kind == "b":
        return "TRUE" if raw == "1" else "FALSE"
    if kind in ("str", "e"):
        return raw
    # A number: a phone typed as a number comes as 2.01012345678E11 or 201012345678.0 - written back as its digits.
    try:
        number = float(raw)
    except ValueError:
        return raw
    if number.is_integer() and abs(number) < 1e17:
        return str(int(number))
    return raw


def read_xlsx(data):
    """The first sheet of an ``.xlsx`` as lines of cells."""
    try:
        archive = zipfile.ZipFile(io.BytesIO(data))
    except zipfile.BadZipFile:
        raise Unreadable("الملف ده مش Excel سليم. احفظه .xlsx أو CSV.", "That is not a valid Excel file. Save it as .xlsx or CSV.") from None
    with archive:
        if sum(info.file_size for info in archive.infolist()) > MAX_UNPACKED_BYTES:
            raise Unreadable("الملف أكبر من اللي ينفع يتقري.", "The file is too large to read.")
        names = set(archive.namelist())
        if "xl/workbook.xml" not in names:
            raise Unreadable("الملف ده مش Excel سليم. احفظه .xlsx أو CSV.", "That is not a valid Excel file. Save it as .xlsx or CSV.")
        shared = []
        if "xl/sharedStrings.xml" in names:
            for item in _xml(archive, "xl/sharedStrings.xml").iter(f"{MAIN}si"):
                shared.append("".join(t.text or "" for t in item.iter(f"{MAIN}t")))
        # The first sheet of the workbook, found through its relationship (it is not always sheet1.xml).
        target = "xl/worksheets/sheet1.xml"
        first = _xml(archive, "xl/workbook.xml").find(f"{MAIN}sheets/{MAIN}sheet")
        if first is not None and "xl/_rels/workbook.xml.rels" in names:
            wanted = first.get(f"{REL}id")
            for rel in _xml(archive, "xl/_rels/workbook.xml.rels").iter(f"{PACKAGE_REL}Relationship"):
                if rel.get("Id") == wanted:
                    path = rel.get("Target", "").lstrip("/")
                    target = path if path.startswith("xl/") else f"xl/{path}"
        if target not in names:
            raise Unreadable("الملف مفيهوش شيت.", "The file has no sheet.")
        table = []
        for line in _xml(archive, target).iter(f"{MAIN}row"):
            cells = {}
            for position, cell in enumerate(line.iter(f"{MAIN}c")):
                column = _column_number(cell.get("r")) if cell.get("r") else position
                if column is not None and column < MAX_COLUMNS:
                    cells[column] = _cell_text(cell, shared)
            table.append([cells.get(i, "") for i in range(max(cells) + 1)] if cells else [])
            if len(table) > MAX_ROWS + 1:
                break
        return table


def _decode(data):
    """CSV text: UTF-8 (with or without its mark) as Google Sheets writes it, else Windows Arabic as an Arabic Excel does."""
    for encoding in ("utf-8-sig", "cp1256"):
        try:
            return data.decode(encoding)
        except UnicodeDecodeError:
            continue
    return data.decode("latin-1")


def read_text(text):
    """Cells as lines of text: pasted from a spreadsheet (tabs), or a CSV (commas or semicolons, whichever the first line
    uses most)."""
    text = (text or "").replace("\r\n", "\n").replace("\r", "\n")
    first = text.split("\n", 1)[0]
    delimiter = max(("\t", ",", ";"), key=first.count) if first else "\t"
    reader = csv.reader(io.StringIO(text), delimiter=delimiter)
    table = []
    for line in reader:
        table.append(line)
        if len(table) > MAX_ROWS + 1:
            break
    return table


# ---------------------------------------------------------------------------
# A Google Sheets link (12/10/2026): read the sheet itself instead of a file downloaded from it
# ---------------------------------------------------------------------------

#: A Google Sheets link as the Share button or the address bar gives it: the sheet's id (or, for a sheet published to the
#: web, its "e/..." id), and anything after it. Nothing but this is ever opened: the server never fetches an address a
#: person typed, only the export address it builds from the id.
SHEET_LINK = re.compile(r"^https://docs\.google\.com/spreadsheets/d/(e/)?([A-Za-z0-9_-]{20,200})(?:[/?#].*)?$")
GID = re.compile(r"[#?&]gid=(\d{1,15})")
#: How long Google is waited for.
LINK_TIMEOUT = 20

def _not_shared():
    return Unreadable(
        "الشيت مقفول. افتحه في Google Sheets واضغط Share ← General access ← Anyone with the link (Viewer)، وبعدين حط اللينك تاني.",
        "The sheet is not shared. In Google Sheets press Share → General access → Anyone with the link (Viewer), then paste the link again.",
    )


def export_url(link):
    """The address Google gives the sheet's tab as CSV, built from the link's id and tab. ``Unreadable`` for anything that
    is not a Google Sheets link."""
    link = (link or "").strip()
    found = SHEET_LINK.match(link) if len(link) <= 2000 else None
    if found is None:
        raise Unreadable(
            "ده مش لينك Google Sheet. انسخ اللينك من زرار Share في الشيت (بيبدأ بـ https://docs.google.com/spreadsheets/).",
            "That is not a Google Sheets link. Copy it from the sheet's Share button (it starts with https://docs.google.com/spreadsheets/).",
        )
    published, sheet_id = found.group(1), found.group(2)
    tab = GID.search(link)
    tab = f"&gid={tab.group(1)}" if tab else ""
    if published:
        return f"https://docs.google.com/spreadsheets/d/e/{sheet_id}/pub?output=csv{tab}"
    return f"https://docs.google.com/spreadsheets/d/{sheet_id}/export?format=csv{tab}"


def _google_host(url):
    parts = urlsplit(url)
    host = (parts.hostname or "").lower()
    return parts.scheme == "https" and (host == "docs.google.com" or host.endswith(".googleusercontent.com"))


class _StayOnGoogle(urllib.request.HTTPRedirectHandler):
    """Google answers the export with a redirect to its file server; a sheet that is not shared sends it to the sign-in
    page instead. Anything that leaves Google's sheet and file hosts is the sheet not being open to a link - and is never
    followed."""

    def redirect_request(self, req, fp, code, msg, headers, newurl):
        if not _google_host(newurl):
            raise _not_shared()
        return super().redirect_request(req, fp, code, msg, headers, newurl)


def _open(url):
    request = urllib.request.Request(url, headers={"User-Agent": "Eagle/1.0", "Accept": "text/csv"})
    return net.opener(_StayOnGoogle()).open(request, timeout=LINK_TIMEOUT)


def read_link(link):
    """``(rows, mapped)`` from a Google Sheets link, read as CSV. The sheet must be open to anyone with the link: a closed
    one, one that is not there, Google out of reach, or an answer over ``MAX_FILE_BYTES`` is ``Unreadable`` with why."""
    url = export_url(link)
    try:
        with _open(url) as response:
            kind = (response.headers.get("Content-Type") or "").lower()
            data = response.read(MAX_FILE_BYTES + 1)
    except Unreadable:
        raise
    except urllib.error.HTTPError as exc:
        if exc.code in (401, 403):
            raise _not_shared() from None
        if exc.code == 404:
            raise Unreadable("الشيت ده مش موجود. اتأكد من اللينك.", "That sheet does not exist. Check the link.") from None
        raise Unreadable("جوجل مارضيش يدّي الشيت دلوقتي. جرّب تاني بعد شوية.", "Google did not give the sheet now. Try again in a while.") from None
    except (urllib.error.URLError, TimeoutError, OSError):
        raise Unreadable("مقدرتش أوصل لجوجل دلوقتي. جرّب تاني بعد شوية.", "Could not reach Google now. Try again in a while.") from None
    if len(data) > MAX_FILE_BYTES:
        raise Unreadable("الشيت أكبر من 5 ميجا. قسّمه على أكتر من شيت.", "The sheet is over 5 MB. Split it into smaller ones.")
    # A sign-in or error page instead of the cells: the sheet is not open to a link.
    if "html" in kind or data[:200].lstrip().lower().startswith((b"<!doctype", b"<html")):
        raise _not_shared()
    return to_rows(read_text(_decode(data)))


def read(name, data):
    """``(rows, mapped)`` from an uploaded file, by its name and its first bytes. ``Unreadable`` for anything else."""
    if len(data) > MAX_FILE_BYTES:
        raise Unreadable("الملف أكبر من 5 ميجا. قسّمه على أكتر من ملف.", "The file is over 5 MB. Split it into smaller ones.")
    lower = (name or "").lower()
    if data[:2] == b"PK" or lower.endswith((".xlsx", ".xlsm")):
        return to_rows(read_xlsx(data))
    if lower.endswith(".xls"):
        raise Unreadable("ده Excel قديم (.xls). افتحه واحفظه .xlsx أو CSV.", "That is an old Excel file (.xls). Open it and save it as .xlsx or CSV.")
    if lower.endswith((".csv", ".tsv", ".txt")) or not lower:
        return to_rows(read_text(_decode(data)))
    raise Unreadable("ارفع ملف Excel (.xlsx) أو CSV.", "Upload an Excel (.xlsx) or CSV file.")
