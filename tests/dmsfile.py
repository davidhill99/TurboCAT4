"""A minimal DMS writer, for tests only: packs an ADF as a genuine DMS archive with no compression
(mode 0, "NOCOMP"), with the header and track CRCs and checksums xdms checks. Lets the tests prove
xdms works on every system without needing anyone's own DMS files."""
import struct


def _crc_table():
    table = []
    for i in range(256):                     # CRC-16/ARC, as xdms's CreateCRC (crc_csum.c)
        c = i
        for _ in range(8):
            c = (c >> 1) ^ 0xA001 if c & 1 else c >> 1
        table.append(c)
    return table


_TABLE = _crc_table()


def crc(data):
    c = 0
    for b in data:
        c = _TABLE[(c ^ b) & 255] ^ (c >> 8)
    return c


def checksum(data):
    return sum(data) & 0xFFFF


def pack(adf):
    """DMS bytes for an 880 KB ADF: 80 tracks (cylinders) of 11,264 bytes, stored as they are."""
    track = 11264
    assert len(adf) == 80 * track
    head = bytearray(56)
    head[0:4] = b"DMS!"
    struct.pack_into(">H", head, 16, 0)          # first track
    struct.pack_into(">H", head, 18, 79)         # last track
    head[21:24] = len(adf).to_bytes(3, "big")    # packed size (stored as it is)
    head[25:28] = len(adf).to_bytes(3, "big")    # unpacked size
    struct.pack_into(">H", head, 46, 111)        # made "with DMS 1.11"
    struct.pack_into(">H", head, 50, 1)          # an AmigaDOS disk
    struct.pack_into(">H", head, 52, 0)          # mode 0: no compression
    struct.pack_into(">H", head, 54, crc(head[4:54]))
    out = [bytes(head)]
    for n in range(80):
        data = adf[n * track:(n + 1) * track]
        th = bytearray(20)
        th[0:2] = b"TR"
        struct.pack_into(">HxxHHHBBHH", th, 2, n, track, track, track, 0, 0, checksum(data), crc(data))
        struct.pack_into(">H", th, 18, crc(th[:18]))
        out += [bytes(th), data]
    return b"".join(out)
