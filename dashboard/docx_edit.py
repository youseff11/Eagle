"""Find-and-replace inside a Word file, keeping everything else of it as it was (03/11/2026).

The review chat's AI cannot write a file, only words. When the leader asks for the corrected file it answers with a list of edits (the
words as they are, and the words that should stand there), and this module makes them in a copy of his ``.docx``: the XML of the parts that
hold text is changed in place, as text, so the tables, the styles, the pictures and the right-to-left settings of the file are not
touched. A parser would rewrite the namespaces of the file; this does not.

An edit lives inside one paragraph. The words of a paragraph may be split over several runs (a bold word, a change of font); the new
words go into the run where the old ones began, so they take its look, and the rest of the old words is taken out of the runs it covered.
"""

import io
import re
import zipfile

#: The parts of a Word file that hold text a reader sees.
_PARTS = re.compile(r"^word/(document|footnotes|endnotes|header\d*|footer\d*)\.xml$")
#: The most a file may unpack to: a guard against a zip that is small and huge, not a limit anyone is expected to meet.
MAX_UNPACKED_BYTES = 200 * 1024 * 1024

_PARAGRAPH = re.compile(r"<w:p(?:\s[^>]*)?>.*?</w:p>", re.DOTALL)
_TEXT = re.compile(r"(<w:t(?:\s[^>]*)?>)(.*?)(</w:t>)", re.DOTALL)
_ENTITY = re.compile(r"&(#x[0-9a-fA-F]+|#[0-9]+|amp|lt|gt|quot|apos);")
_NAMED = {"amp": "&", "lt": "<", "gt": ">", "quot": '"', "apos": "'"}
#: Spaces that look like a space and are not one: a model quotes them as a space. Same length, so places stay places.
_SPACES = str.maketrans({" ": " ", " ": " ", " ": " "})


class DocxError(Exception):
    """The file is not one this can edit."""


def _unescape(text):
    def one(found):
        name = found.group(1)
        if name.startswith("#x"):
            return chr(int(name[2:], 16))
        if name.startswith("#"):
            return chr(int(name[1:]))
        return _NAMED[name]

    return _ENTITY.sub(one, text)


def _escape(text):
    return text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def _same(text):
    return text.translate(_SPACES)


def _edit_paragraph(paragraph, edits, counts):
    """The paragraph's XML with every edit made, and ``counts[i]`` raised by how many times edit ``i`` was found in it."""
    pieces = list(_TEXT.finditer(paragraph))
    if not pieces:
        return paragraph
    texts = [_unescape(piece.group(2)) for piece in pieces]
    starts, joined = [], ""
    for text in texts:
        starts.append(len(joined))
        joined += text
    seen = _same(joined)
    changed = False
    for number, (old, new) in enumerate(edits):
        needle = _same(old)
        if not needle:
            continue
        # The last match first: the places of the earlier ones stay where they were while the later ones change.
        found, at = [], seen.find(needle)
        while at != -1:
            found.append(at)
            at = seen.find(needle, at + len(needle))
        for begin in reversed(found):
            end = begin + len(needle)
            first = max(i for i, start in enumerate(starts) if start <= begin)
            last = max(i for i, start in enumerate(starts) if start < end)
            head = texts[first][: begin - starts[first]]
            tail = texts[last][end - starts[last]:]
            if first == last:
                texts[first] = head + new + tail
            else:
                texts[first] = head + new
                for middle in range(first + 1, last):
                    texts[middle] = ""
                texts[last] = tail
            counts[number] += 1
            changed = True
        if found:
            joined = ""
            starts = []
            for text in texts:
                starts.append(len(joined))
                joined += text
            seen = _same(joined)
    if not changed:
        return paragraph
    out, cursor = [], 0
    for piece, text in zip(pieces, texts):
        opening = piece.group(1)
        if "xml:space" not in opening and text != text.strip():
            opening = opening[:-1] + ' xml:space="preserve">'
        out.append(paragraph[cursor:piece.start()])
        out.append(opening + _escape(text) + piece.group(3))
        cursor = piece.end()
    out.append(paragraph[cursor:])
    return "".join(out)


def _edit_part(xml, edits, counts):
    return _PARAGRAPH.sub(lambda found: _edit_paragraph(found.group(0), edits, counts), xml)


def apply(raw, edits):
    """``(bytes, counts)``: the Word file ``raw`` with ``edits`` (a list of ``(old, new)``) made in it, and how many times each was found.

    Every place an ``old`` stands is changed. A file with nothing found comes back the same, byte for byte. :class:`DocxError` when ``raw``
    is not a Word file."""
    edits = [(old, new) for old, new in edits]
    counts = [0] * len(edits)
    try:
        source = zipfile.ZipFile(io.BytesIO(raw))
    except zipfile.BadZipFile as failure:
        raise DocxError("not a zip") from failure
    with source:
        names = source.namelist()
        if "word/document.xml" not in names:
            raise DocxError("not a Word file")
        if sum(info.file_size for info in source.infolist()) > MAX_UNPACKED_BYTES:
            raise DocxError("too big")
        buffer = io.BytesIO()
        with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as target:
            for info in source.infolist():
                data = source.read(info.filename)
                if _PARTS.match(info.filename):
                    xml = data.decode("utf-8")
                    data = _edit_part(xml, edits, counts).encode("utf-8")
                target.writestr(info, data)
    if not any(counts):
        return raw, counts
    return buffer.getvalue(), counts
