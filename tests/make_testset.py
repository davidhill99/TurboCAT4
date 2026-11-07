"""Build a synthetic Amiga test collection for TurboCAT 2026.

Creates OFS/FFS disks, an LHA WHDLoad pack, archives inside disks, an RDB hard
disk image, a bare-partition HDF, a damaged disk, a virus-style bootblock, an
ADZ, an Amiga folder and a duplicate.
"""

import gzip
import os
import shutil
import struct
import subprocess
import sys
import tempfile
import time

OUT = sys.argv[1]
os.makedirs(OUT, exist_ok=True)
TMP = tempfile.mkdtemp()


def run(*cmd):
    p = subprocess.run(cmd, capture_output=True, text=True)
    if p.returncode:
        raise SystemExit(f"{cmd}: {p.stdout}{p.stderr}")


# ------------------------------------------------------------ minimal LHA writer
def crc16(data):
    crc = 0
    for b in data:
        crc ^= b
        for _ in range(8):
            crc = (crc >> 1) ^ 0xA001 if crc & 1 else crc >> 1
    return crc


def dos_time(t=(1995, 8, 1, 12, 0, 0)):
    y, mo, d, h, mi, s = t
    date = ((y - 1980) << 9) | (mo << 5) | d
    tim = (h << 11) | (mi << 5) | (s // 2)
    return (date << 16) | tim


def lha(files):
    """files: list of (name, bytes). Stored (-lh0-) level-0 archive."""
    out = b""
    for name, data in files:
        nb = name.replace("/", "\\").encode("latin-1")
        body = (b"-lh0-" + struct.pack("<IIIBB", len(data), len(data), dos_time(), 0x20, 0)
                + bytes([len(nb)]) + nb + struct.pack("<H", crc16(data)))
        out += bytes([len(body), sum(body) & 0xFF]) + body + data
    return out + b"\x00"


# ------------------------------------------------------------ WHDLoad slave
def slave(name, copy, info):
    strings = b""
    hdr_len = 48
    offs = []
    for s in (name, copy, info):
        offs.append(hdr_len + len(strings))
        strings += s.encode("latin-1").replace(b"\n", b"\xff") + b"\x00"
    blob = (struct.pack(">I", 0x70FF4E75) + b"WHDLOADS" + struct.pack(">HHI", 17, 0x0005, 0x80000)
            + struct.pack(">I", 0) + struct.pack(">HHHBB", 0, 0, 0, 0x58, 0x59)
            + struct.pack(">I", 0) + struct.pack(">HHH", *offs))
    blob += b"\x00" * (hdr_len - len(blob)) + strings
    blob += b"\x00" * (-len(blob) % 4)
    longs = len(blob) // 4
    return (struct.pack(">IIIII", 0x3F3, 0, 1, 0, 0) + struct.pack(">I", longs)
            + struct.pack(">II", 0x3E9, longs) + blob + struct.pack(">I", 0x3F2))


def write_tmp(name, data):
    p = os.path.join(TMP, name)
    os.makedirs(os.path.dirname(p), exist_ok=True)
    with open(p, "wb") as f:
        f.write(data)
    return p


# 1. WHDLoad pack (LHA) - Turrican 2 style
whd = lha([
    ("Turrican2/Turrican2.slave", slave("Turrican II", "1991 Factor 5 / Rainbow Arts",
                                        "installed by Test\nVersion 1.4")),
    ("Turrican2/Turrican2.info", b"\xe3\x10" + b"\x00" * 300),
    ("Turrican2/disk.1", os.urandom(40000)),
    ("Turrican2/ReadMe", b"Turrican II WHDLoad install. Press F10 to quit.\n"),
])
open(os.path.join(OUT, "Turrican2_v1.4.lha"), "wb").write(whd)

# 2. OFS work disk with folders, an LHA inside and a readme
ofs = os.path.join(OUT, "PD_Utilities_01.adf")
readme = write_tmp("readme.txt", b"DiskMaster 2 - the classic file manager\n" * 20)
dm = write_tmp("DiskMaster", os.urandom(60000))
inner = write_tmp("Archives.lha", lha([("SysInfo/SysInfo", os.urandom(30000)),
                                       ("SysInfo/SysInfo.doc", b"SysInfo 3.24 by Nic Wilson\n" * 30)]))
run("xdftool", "-f", ofs, "create", "+", "format", "PD_Utils_01", "ofs",
    "+", "makedir", "Tools", "+", "write", dm, "Tools/DiskMaster",
    "+", "write", readme, "Tools/DiskMaster.readme",
    "+", "write", inner, "Archives.lha")

# 3. FFS disk sharing a file with the OFS disk (file-level duplicate)
ffs = os.path.join(OUT, "Coverdisk_52.adf")
run("xdftool", "-f", ffs, "create", "+", "format", "AS52_Disk1", "ffs",
    "+", "write", dm, "DiskMaster", "+", "write", readme, "DiskMaster.readme")

# 4. Exact duplicate of a disk under another name
shutil.copy(ofs, os.path.join(OUT, "copy_of_PD_Utils.adf"))

# 5. Damaged disk: corrupt an OFS data block in the copy
bad = os.path.join(OUT, "Damaged_Disk.adf")
d = bytearray(open(ofs, "rb").read())
# find a data block of Tools/DiskMaster: OFS data blocks start with type 8
for blk in range(2, 1760):
    o = blk * 512
    if struct.unpack(">I", d[o:o + 4])[0] == 8:
        d[o + 100:o + 140] = b"\xAA" * 40          # breaks the block checksum
        break
open(bad, "wb").write(d)

# 6. Virus-style bootblock: code that writes ExecBase->CoolCapture
vir = bytearray(open(ffs, "rb").read())
code = bytes.fromhex("2C780004" "2D7C00000400002E" "4EAEFE5C" "4E75") + b"(fake test virus)"
vir[12:12 + len(code)] = code
vir[4:8] = b"\x00\x00\x00\x00"
s = 0
for i in range(0, 1024, 4):
    s += struct.unpack(">I", vir[i:i + 4])[0]
    if s > 0xFFFFFFFF:
        s = (s & 0xFFFFFFFF) + 1
vir[4:8] = struct.pack(">I", (~s) & 0xFFFFFFFF)
open(os.path.join(OUT, "Suspicious_Boot.adf"), "wb").write(vir)

# 7. ADZ (gzipped ADF)
open(os.path.join(OUT, "Coverdisk_52.adz"), "wb").write(gzip.compress(open(ffs, "rb").read()))

# 8. RDB hard disk with two FFS partitions
hdf = os.path.join(OUT, "Workbench_HD.hdf")
run("rdbtool", "-f", hdf, "create", "size=20Mi", "+", "init", "+",
    "add", "size=45%", "name=DH0", "+", "add", "size=45%", "name=DH1")
run("xdftool", hdf, "open", "part=DH0", "+", "format", "System", "ffs",
    "+", "makedir", "S", "+", "makedir", "C",
    "+", "write", write_tmp("ss", b"LoadWB\nEndCLI >NIL:\n"), "S/Startup-Sequence",
    "+", "write", write_tmp("dir", os.urandom(4000)), "C/Dir")
run("xdftool", hdf, "open", "part=DH1", "+", "format", "Games", "ffs",
    "+", "write", os.path.join(OUT, "Turrican2_v1.4.lha"), "Turrican2_v1.4.lha")

# 9. Bare single-partition HDF (no RDB)
raw = os.path.join(OUT, "Work_partition.hdf")
run("xdftool", "-f", raw, "create", "size=4Mi", "+", "format", "Work", "ffs",
    "+", "write", readme, "Notes.txt")

# 10. An Amiga folder used as an emulated hard drive
fold = os.path.join(OUT, "FS-UAE_HD")
for p, c in [("S/Startup-Sequence", b"LoadWB\n"), ("C/LoadWB", os.urandom(2000)),
             ("Utilities/DiskMaster", open(dm, "rb").read())]:
    full = os.path.join(fold, p)
    os.makedirs(os.path.dirname(full), exist_ok=True)
    open(full, "wb").write(c)

# 11. Something that isn't Amiga at all (should be ignored)
open(os.path.join(OUT, "holiday_photo.jpg"), "wb").write(b"\xff\xd8\xff" + os.urandom(5000))

shutil.rmtree(TMP)
print("test set written to", OUT)
