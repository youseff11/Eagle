"""The words of an old Word file (``.doc``, Word 97 to 2003), read with the standard library only.

A ``.doc`` is an OLE compound file: a small file system inside the file. The text sits in its ``WordDocument`` stream and the piece
table that says where each stretch of it starts sits in the ``0Table`` or ``1Table`` stream (the File Information Block says which).
Only the body is read - not headers, footnotes or text boxes - because that is what is translated and reviewed. A file that is
encrypted, older than Word 97, or damaged yields ``""``, which the callers already treat as "cannot read this one".
"""

import struct

OLE_MAGIC = b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1"

_FREE, _END = 0xFFFFFFFF, 0xFFFFFFFE
_MAX_SECTORS = 1_000_000

#: Word's own marks inside the text, as what a reader would see.
_MARKS = {"\r": "\n", "\x07": "\t", "\x0b": "\n", "\x0c": "\n", "\x1e": "-", "\x1f": ""}


def _chain(fat, first, limit):
    out, seen = [], set()
    sector = first
    while sector < _END and sector not in seen and len(out) < limit:
        seen.add(sector)
        out.append(sector)
        if sector >= len(fat):
            break
        sector = fat[sector]
    return out


def _streams(raw, wanted):
    """``{name: bytes}`` for the streams called one of ``wanted`` in an OLE file; ``ValueError`` when it is not a readable one."""
    if len(raw) < 512 or not raw.startswith(OLE_MAGIC):
        raise ValueError("not an OLE file")
    shift, mini_shift = struct.unpack_from("<HH", raw, 0x1E)
    if shift not in (9, 12) or mini_shift != 6:
        raise ValueError("odd sector size")
    size = 1 << shift
    n_fat, first_dir, _tx, cutoff, first_mini, n_mini, first_difat, n_difat = struct.unpack_from("<IIIIIIII", raw, 0x2C)
    # 0x2C: FAT sectors, 0x30: first directory sector, 0x34: transaction signature, 0x38: mini stream cutoff, 0x3C/0x40: mini FAT,
    # 0x44/0x48: DIFAT.

    def sector(index):
        start = (index + 1) * size
        return raw[start:start + size]

    difat = list(struct.unpack_from("<109I", raw, 0x4C))
    nxt = first_difat
    for _ in range(min(n_difat, 4096)):
        if nxt >= _END:
            break
        block = struct.unpack("<%dI" % (size // 4), sector(nxt).ljust(size, b"\xff"))
        difat.extend(block[:-1])
        nxt = block[-1]
    fat = []
    for index in difat[:n_fat]:
        if index >= _END:
            continue
        fat.extend(struct.unpack("<%dI" % (size // 4), sector(index).ljust(size, b"\xff")))

    def read(first, length=None):
        data = b"".join(sector(i) for i in _chain(fat, first, _MAX_SECTORS))
        return data if length is None else data[:length]

    directory = read(first_dir)
    entries = []
    for at in range(0, len(directory) - 127, 128):
        name_len, kind = struct.unpack_from("<HB", directory, at + 0x40)
        if kind == 0 or name_len < 2:
            continue
        name = directory[at:at + name_len - 2].decode("utf-16le", errors="ignore")
        start, length = struct.unpack_from("<IQ", directory, at + 0x74)
        entries.append((name, kind, start, length & 0xFFFFFFFF))

    mini_stream = b""
    mini_fat = []
    root = next((e for e in entries if e[1] == 5), None)
    if root is not None and n_mini:
        mini_stream = read(root[2], root[3])
        packed = read(first_mini)
        mini_fat = list(struct.unpack("<%dI" % (len(packed) // 4), packed[:len(packed) // 4 * 4]))

    found = {}
    for name, kind, start, length in entries:
        if kind != 2 or name not in wanted or name in found:
            continue
        if length < cutoff:
            chunks = [mini_stream[i * 64:(i + 1) * 64] for i in _chain(mini_fat, start, _MAX_SECTORS)]
            found[name] = b"".join(chunks)[:length]
        else:
            found[name] = read(start, length)
    return found


def _field_free(text):
    """Drop the field instructions (HYPERLINK ..., PAGEREF ...) and keep what the field shows."""
    out, depth, hidden = [], 0, []
    for ch in text:
        if ch == "\x13":
            depth += 1
            hidden.append(True)
        elif ch == "\x14" and hidden:
            hidden[-1] = False
        elif ch == "\x15" and hidden:
            hidden.pop()
            depth -= 1
        elif not any(hidden):
            out.append(ch)
    return "".join(out)


def _clean(text):
    text = _field_free(text)
    out = []
    for ch in text:
        if ch in _MARKS:
            out.append(_MARKS[ch])
        elif ch == "\t" or ch == "\n" or (ch >= " " and ch != "\x7f" and not 0x80 <= ord(ch) < 0xA0):
            out.append(ch)
    return "".join(out)


def text(raw):
    """The body text of a ``.doc`` held in memory, or ``""`` when it cannot be read."""
    try:
        return _text(raw)
    except Exception:  # noqa: BLE001 - a damaged file is "unreadable", never a crash
        return ""


def _text(raw):
    streams = _streams(raw, {"WordDocument", "0Table", "1Table"})
    word = streams.get("WordDocument", b"")
    if len(word) < 0x1A8 or struct.unpack_from("<H", word, 0)[0] != 0xA5EC:
        return ""
    flags = struct.unpack_from("<H", word, 0x0A)[0]
    if flags & 0x0100:
        return ""
    table = streams.get("1Table" if flags & 0x0200 else "0Table", b"")

    csw = struct.unpack_from("<H", word, 0x20)[0]
    lw_at = 0x22 + csw * 2
    cslw = struct.unpack_from("<H", word, lw_at)[0]
    lw = lw_at + 2
    ccp_text = struct.unpack_from("<I", word, lw + 3 * 4)[0]
    fc_at = lw + cslw * 4 + 2
    fc_clx, lcb_clx = struct.unpack_from("<II", word, fc_at + 33 * 8)
    clx = table[fc_clx:fc_clx + lcb_clx]

    # The CLX holds any number of property blocks (type 1) and then the piece table (type 2).
    at = 0
    while at < len(clx) and clx[at] == 1:
        at += 3 + struct.unpack_from("<H", clx, at + 1)[0]
    if at >= len(clx) or clx[at] != 2:
        return ""
    plc_len = struct.unpack_from("<I", clx, at + 1)[0]
    plc = clx[at + 5:at + 5 + plc_len]
    pieces = (len(plc) - 4) // 12
    cps = struct.unpack_from("<%dI" % (pieces + 1), plc, 0)

    out, left = [], ccp_text
    for i in range(pieces):
        if left <= 0:
            break
        count = min(cps[i + 1] - cps[i], left)
        left -= count
        fc = struct.unpack_from("<I", plc, (pieces + 1) * 4 + i * 8 + 2)[0]
        if fc & 0x40000000:
            start = (fc & 0x3FFFFFFF) // 2
            out.append(word[start:start + count].decode("cp1252", errors="replace"))
        else:
            start = fc & 0x3FFFFFFF
            out.append(word[start:start + count * 2].decode("utf-16le", errors="replace"))
    return _clean("".join(out))
