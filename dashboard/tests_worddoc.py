"""Old Word files (``.doc``): the AI can read their words, so a leader who sends one is not told "cannot read this file"."""

import struct

from django.test import SimpleTestCase

from . import ai, ai_translate, doc_review, worddoc

END, FREE, FATSECT = 0xFFFFFFFE, 0xFFFFFFFF, 0xFFFFFFFD
SECTOR = 512


def _entry(name, kind, start, size):
    raw = name.encode("utf-16le")
    head = raw.ljust(64, b"\0") + struct.pack("<HBB", len(raw) + 2 if name else 0, kind, 1)
    return (head + struct.pack("<III", FREE, FREE, FREE) + b"\0" * 36 + struct.pack("<IQ", start, size)).ljust(128, b"\0")


def _ole(streams):
    """A compound file holding ``streams`` (name -> bytes, each at least 4096 long so none goes to the mini stream)."""
    sectors, chains = [], {}
    for name, data in streams.items():
        data = data.ljust(-(-max(len(data), 4096) // SECTOR) * SECTOR, b"\0")
        chains[name] = (2 + len(sectors), len(data))
        sectors.extend(data[i:i + SECTOR] for i in range(0, len(data), SECTOR))
    # The FAT is one sector (128 entries): sector 0 is the FAT itself, 1 the directory, the streams follow.
    assert len(sectors) + 2 <= 128
    fat = [FATSECT, END] + [FREE] * 126
    for name, (first, size) in chains.items():
        count = size // SECTOR
        for i in range(count):
            fat[first + i] = first + i + 1 if i + 1 < count else END
    directory = _entry("Root Entry", 5, END, 0) + b"".join(
        _entry(name, 2, first, size) for name, (first, size) in chains.items()
    )
    directory = directory.ljust(SECTOR, b"\0")
    fat_sector = struct.pack("<128I", *fat)
    header = (
        b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1" + b"\0" * 16 + struct.pack("<HHHHH", 0x3E, 3, 0xFFFE, 9, 6) + b"\0" * 6
        + struct.pack("<I", 0)  # 0x28: directory sector count (0 in version 3)
        # 0x2C: FAT sectors, first directory sector, transaction signature, mini stream cutoff, mini FAT (first, count), DIFAT (first, count)
        + struct.pack("<IIIIIIII", 1, 1, 0, 4096, END, 0, END, 0)
        + struct.pack("<109I", 0, *([FREE] * 108))
    )
    return header.ljust(SECTOR, b"\0") + fat_sector + directory + b"".join(sectors)


def make_doc(pieces, encrypted=False):
    """A ``.doc`` whose body is the ``pieces`` (each a ``str``: plain ASCII/Latin-1 goes as 8-bit text, anything else as UTF-16)."""
    word = bytearray(8192)
    struct.pack_into("<H", word, 0, 0xA5EC)
    struct.pack_into("<H", word, 0x0A, 0x0200 | (0x0100 if encrypted else 0))
    struct.pack_into("<H", word, 0x20, 14)
    struct.pack_into("<H", word, 0x3E, 22)
    total = sum(len(p) for p in pieces)
    struct.pack_into("<I", word, 0x40 + 3 * 4, total)
    struct.pack_into("<H", word, 0x98, 93)
    at, cps, pcds, cp = 0x800, [0], b"", 0
    for piece in pieces:
        try:
            body, fc = piece.encode("cp1252"), (at * 2) | 0x40000000
        except UnicodeEncodeError:
            body, fc = piece.encode("utf-16le"), at
        word[at:at + len(body)] = body
        at += len(body) + (len(body) % 2)
        cp += len(piece)
        cps.append(cp)
        pcds += struct.pack("<HIH", 0, fc, 0)
    plc = struct.pack("<%dI" % len(cps), *cps) + pcds
    clx = b"\x02" + struct.pack("<I", len(plc)) + plc
    struct.pack_into("<II", word, 0x1A2, 0, len(clx))
    table = clx.ljust(4096, b"\0")
    return _ole({"WordDocument": bytes(word), "1Table": table})


class WordDocTests(SimpleTestCase):
    def test_the_words_of_a_doc_come_out_in_order_and_in_both_encodings(self):
        raw = make_doc(["Dear Visa Officer,\rI plan a trip.\r", "مرحبا بالعالم\r"])
        words = worddoc.text(raw)
        self.assertEqual(words, "Dear Visa Officer,\nI plan a trip.\nمرحبا بالعالم\n")

    def test_field_codes_are_dropped_and_what_the_field_shows_stays(self):
        raw = make_doc(["See \x13 HYPERLINK \"http://x\" \x14the site\x15 now.\r"])
        self.assertEqual(worddoc.text(raw), "See the site now.\n")

    def test_table_cell_marks_become_tabs(self):
        self.assertEqual(worddoc.text(make_doc(["a\x07b\x07\r"])), "a\tb\t\n")

    def test_an_encrypted_or_damaged_file_is_unreadable_not_a_crash(self):
        self.assertEqual(worddoc.text(make_doc(["secret\r"], encrypted=True)), "")
        self.assertEqual(worddoc.text(b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1" + b"\0" * 40), "")
        self.assertEqual(worddoc.text(b"plain bytes, not a Word file"), "")
        self.assertEqual(worddoc.text(make_doc(["cut\r"])[:700]), "")

    def test_the_ai_reads_a_doc_by_its_name(self):
        raw = make_doc(["Plan\r"])
        self.assertEqual(ai.text_from_bytes(raw, "Trip Plan (425).doc").strip(), "Plan")
        self.assertEqual(ai.text_from_bytes(raw, "TRIP.DOC").strip(), "Plan")

    def test_a_doc_is_a_kind_the_ai_screens_accept(self):
        self.assertTrue(ai_translate.readable("trip.doc"))

    def test_the_leader_review_takes_a_doc_as_the_translation(self):
        # The case from the field: a PDF source and a .doc translation was answered "the AI cannot read this translation file".
        text, documents, names, skipped = doc_review._prepare([("Trip Plan (425).doc", make_doc(["Dear Visa Officer\r"]))])
        self.assertIn("Dear Visa Officer", text)
        self.assertEqual((documents, skipped, names), ([], [], ["Trip Plan (425).doc"]))

    def test_a_doc_that_cannot_be_read_is_still_said_so(self):
        text, documents, _names, skipped = doc_review._prepare([("old.doc", b"not word")])
        self.assertEqual((text, documents, skipped), ("", [], ["old.doc"]))
