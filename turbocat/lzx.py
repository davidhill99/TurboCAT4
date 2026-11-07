"""List the contents of Amiga LZX archives (names, sizes, dates).

Listing only needs the entry headers, so no decompression is required.
Extracting file data from LZX is not supported yet.
"""

import datetime
import struct

LZX_MAGIC = b"LZX"


def _date(v: int):
    day = (v >> 27) & 31
    month = ((v >> 23) & 15) + 1
    year = ((v >> 17) & 63) + 1970
    hour = (v >> 12) & 31
    minute = (v >> 6) & 63
    sec = v & 63
    try:
        return datetime.datetime(year, month, max(day, 1), hour, minute, min(sec, 59))
    except ValueError:
        return None


def list_lzx(data: bytes):
    """Yield dicts: name, size, date, comment, merged."""
    if data[:3] != LZX_MAGIC or len(data) < 10:
        raise ValueError("not an LZX archive")
    pos = 10
    entries = []
    while pos + 31 <= len(data):
        h = data[pos:pos + 31]
        unpack = struct.unpack("<I", h[2:6])[0]
        packed = struct.unpack("<I", h[6:10])[0]
        flags = h[12]
        clen = h[14]
        date = struct.unpack(">I", h[18:22])[0]
        nlen = h[30]
        pos += 31
        name = data[pos:pos + nlen].decode("latin-1")
        pos += nlen
        comment = data[pos:pos + clen].decode("latin-1")
        pos += clen
        entries.append({"name": name, "size": unpack, "date": _date(date),
                        "comment": comment, "merged": bool(flags & 1)})
        pos += packed
    return entries
