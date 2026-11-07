"""Read the header of a WHDLoad .slave file to get the game name and credits."""

import struct

HUNK_HEADER, HUNK_CODE, HUNK_DATA = 0x3F3, 0x3E9, 0x3EA


def _first_hunk_data(data: bytes):
    if len(data) < 32 or struct.unpack(">I", data[:4])[0] != HUNK_HEADER:
        return None
    pos = 4
    # resident library names (always 0 for executables)
    while True:
        n = struct.unpack(">I", data[pos:pos + 4])[0]
        pos += 4
        if n == 0:
            break
        pos += n * 4
    table, first, last = struct.unpack(">III", data[pos:pos + 12])
    pos += 12 + (last - first + 1) * 4
    while pos + 8 <= len(data):
        htype = struct.unpack(">I", data[pos:pos + 4])[0] & 0x3FFFFFFF
        if htype in (HUNK_CODE, HUNK_DATA):
            size = (struct.unpack(">I", data[pos + 4:pos + 8])[0] & 0x3FFFFFFF) * 4
            return data[pos + 8:pos + 8 + size]
        return None
    return None


def _cstr(blob: bytes, off: int) -> str:
    if off <= 0 or off >= len(blob):
        return ""
    end = blob.find(b"\x00", off)
    raw = blob[off:end if end >= 0 else len(blob)]
    # WHDLoad uses byte -1 (0xFF) as a line break in ws_info
    return raw.replace(b"\xff", b"\n").decode("latin-1").strip()


def parse_slave(data: bytes):
    """Return a dict with WHDLoad slave details, or None if not a slave."""
    blob = _first_hunk_data(data)
    if not blob or len(blob) < 32 or blob[4:12] != b"WHDLOADS":
        return None
    version, flags, basemem = struct.unpack(">HHI", blob[12:20])
    info = {"slave_version": version, "flags": flags, "basemem": basemem,
            "name": "", "copyright": "", "info": ""}
    if version >= 10 and len(blob) >= 42:
        name_o, copy_o, info_o = struct.unpack(">HHH", blob[36:42])
        info["name"] = _cstr(blob, name_o)
        info["copyright"] = _cstr(blob, copy_o)
        info["info"] = _cstr(blob, info_o)
    return info
