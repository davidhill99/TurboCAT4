"""A map of every block on an Amiga floppy, for the X-Copy-style track map in the details panel.

Each 512-byte block is classified by following the disk's own AmigaDOS structures: the boot block,
the root block, the bitmap (which blocks are free), the directory tree (hash tables and chains),
each file's header and extension blocks, and its data blocks. Checksums are checked on the way, so
a damaged header or OFS data block shows as bad. A disk that isn't AmigaDOS (a game with its own
loader) is shown as one block of non-DOS data, with blank (all-zero) blocks marked.

Pure Python: no Qt, no amitools. Works on DD (1,760 blocks) and HD (3,520 blocks) images.
"""
import struct
from dataclasses import dataclass, field

BLOCK = 512
SECTORS = {1760: 11, 3520: 22}           # sectors per track, by blocks on the disk

# What a block is: (key, label for people). The order is the legend's order.
KINDS = [
    ("boot", "Boot block"),
    ("root", "Root block (the disk's name and top folder)"),
    ("bitmap", "Bitmap (which blocks are free)"),
    ("dir", "Folder"),
    ("header", "File header"),
    ("list", "File list (extension block)"),
    ("data", "File data"),
    ("damaged", "In a damaged file"),
    ("bad", "Bad block (checksum wrong)"),
    ("used", "Used, but no file claims it"),
    ("free", "Free"),
    ("blank", "Blank (all zeros)"),
    ("nondos", "Non-DOS data (the disk's own loader)"),
]
LABEL = dict(KINDS)


@dataclass
class DiskMap:
    blocks: int
    sectors: int                          # per track
    kind: list = field(default_factory=list)     # per block: a KINDS key
    owner: list = field(default_factory=list)    # per block: the file or folder it belongs to ("")
    dos: bool = True
    ffs: bool = False

    def counts(self):
        out = {}
        for k in self.kind:
            out[k] = out.get(k, 0) + 1
        return out

    def where(self, block):
        """(cylinder, side, sector) of a block: cylinders 0-79, sides 0-1."""
        track, sector = divmod(block, self.sectors)
        return track // 2, track % 2, sector

    def describe(self, block):
        cyl, side, sector = self.where(block)
        text = f"Cylinder {cyl}, side {side}, sector {sector} (block {block}): {LABEL[self.kind[block]]}"
        if self.owner[block]:
            text += f"\n{self.owner[block]}"
        return text


def _long(b, off):
    return struct.unpack_from(">I", b, off)[0]


def _slong(b, off):
    return struct.unpack_from(">i", b, off)[0]


def _checksum_ok(b, at=20):
    return sum(struct.unpack(">128I", b)) & 0xFFFFFFFF == 0


def build(adf, damaged_paths=()):
    """The DiskMap of an ADF (bytes). damaged_paths: files the scan found unreadable, whose blocks
    are marked as in a damaged file."""
    blocks = len(adf) // BLOCK
    if blocks not in SECTORS:            # over- or under-sized dump: map the normal size
        blocks = 3520 if blocks > 2600 else 1760
        adf = (bytes(adf) + bytes(blocks * BLOCK))[:blocks * BLOCK]
    m = DiskMap(blocks, SECTORS[blocks], ["free"] * blocks, [""] * blocks)
    get = lambda n: adf[n * BLOCK:(n + 1) * BLOCK]
    zero = bytes(BLOCK)

    def blank_rest(default):
        for n in range(blocks):
            if m.kind[n] == default and get(n) == zero:
                m.kind[n] = "blank"

    if adf[:3] != b"DOS":
        m.dos = False
        m.kind = ["nondos"] * blocks
        m.kind[0] = m.kind[1] = "boot"
        blank_rest("nondos")
        return m
    m.ffs = bool(adf[3] & 1)
    m.kind[0] = m.kind[1] = "boot"
    root = blocks // 2
    seen = {0, 1}

    def mark(n, kind, owner=""):
        if 0 <= n < blocks:
            m.kind[n], m.owner[n] = kind, owner
            seen.add(n)

    rb = get(root)
    if _long(rb, 0) != 2 or _slong(rb, BLOCK - 4) != 1:
        # no root block where it should be: show what can be told without one
        for n in range(2, blocks):
            m.kind[n] = "used"
        blank_rest("used")
        return m
    mark(root, "root" if _checksum_ok(rb) else "bad", "(the disk's top folder)")

    # The bitmap: bit set = free. Pages listed in the root (and its extension blocks on big disks).
    pages = [p for p in (_long(rb, 316 + 4 * i) for i in range(25)) if 0 < p < blocks]
    ext = _long(rb, 416)
    while 0 < ext < blocks and ext not in seen and len(pages) < 200:
        eb = get(ext)
        mark(ext, "bitmap")
        pages += [p for p in (_long(eb, 4 * i) for i in range(127)) if 0 < p < blocks]
        ext = _long(eb, 508)
    free = set()
    bit_block = 2
    for p in pages:
        pb = get(p)
        mark(p, "bitmap" if _checksum_ok(pb) else "bad")
        for i in range(1, 128):
            word = _long(pb, 4 * i)
            for bit in range(32):
                if bit_block >= blocks:
                    break
                if word & (1 << bit):
                    free.add(bit_block)
                bit_block += 1
    damaged = set(damaged_paths)

    def walk_dir(hb, prefix, depth):
        if depth > 32:
            return
        for i in range(72):
            n = _long(hb, 24 + 4 * i)
            hops = 0
            while 0 < n < blocks and n not in seen and hops < 500:
                hops += 1
                b = get(n)
                ok = _checksum_ok(b)
                name = b[433:433 + min(b[432], 30)].decode("latin-1", "replace")
                sec = _slong(b, BLOCK - 4)
                path = prefix + name
                if not ok or _long(b, 0) != 2:
                    mark(n, "bad", path)
                elif sec == 2:                                   # a folder
                    mark(n, "dir", path + "/")
                    walk_dir(b, path + "/", depth + 1)
                elif sec == -3:                                  # a file
                    walk_file(n, b, path)
                else:                                            # links: just a header
                    mark(n, "header", path)
                n = _long(b, 496)                                # next in this hash chain

    def walk_file(n, hb, path):
        hurt = path in damaged
        mark(n, "header", path)
        datas, lb, hops = [], hb, 0
        while True:
            count = min(_long(lb, 8), 72)
            datas += [_long(lb, 24 + 4 * (71 - i)) for i in range(count)]
            ext = _long(lb, 504)
            hops += 1
            if not (0 < ext < blocks) or ext in seen or hops > 200:
                break
            lb = get(ext)
            mark(ext, "list" if _checksum_ok(lb) else "bad", path)
        for d in datas:
            if not (0 < d < blocks) or d in seen:
                continue
            db = get(d)
            if not m.ffs and (_long(db, 0) != 8 or not _checksum_ok(db)):
                mark(d, "bad", path)                             # OFS data blocks carry a checksum
            else:
                mark(d, "damaged" if hurt else "data", path)

    walk_dir(rb, "", 0)
    for n in range(2, blocks):
        if n not in seen:
            m.kind[n] = "free" if n in free else "used"
    return m
