"""Decoders for Amiga pictures found on disks: IFF ILBM/PBM images and Workbench .info icons.

Everything returns an Image (width, height, RGBA bytes) and can be saved as PNG with
write_png(). No third-party libraries are needed.
"""
import struct
import zlib
from dataclasses import dataclass


@dataclass
class Image:
    width: int
    height: int
    rgba: bytes          # width * height * 4
    planes: int = 0      # colour depth of the original, for judging pictures
    note: str = ""       # e.g. "HAM6", "EHB", "GlowIcon"


# ---------------------------------------------------------------- PNG

def write_png(img: Image) -> bytes:
    raw = bytearray()
    stride = img.width * 4
    for y in range(img.height):
        raw.append(0)
        raw += img.rgba[y * stride:(y + 1) * stride]

    def chunk(tag, data):
        c = struct.pack(">I", len(data)) + tag + data
        return c + struct.pack(">I", zlib.crc32(tag + data) & 0xFFFFFFFF)

    return (b"\x89PNG\r\n\x1a\n"
            + chunk(b"IHDR", struct.pack(">IIBBBBB", img.width, img.height, 8, 6, 0, 0, 0))
            + chunk(b"IDAT", zlib.compress(bytes(raw), 9))
            + chunk(b"IEND", b""))


def scale(img: Image, sx: int, sy: int) -> Image:
    """Repeat pixels sx times across and sy times down (to square up Amiga pixels)."""
    if sx == 1 and sy == 1:
        return img
    out = bytearray()
    stride = img.width * 4
    for y in range(img.height):
        row = img.rgba[y * stride:(y + 1) * stride]
        if sx > 1:
            row = b"".join(row[x * 4:x * 4 + 4] * sx for x in range(img.width))
        out += row * sy
    return Image(img.width * sx, img.height * sy, bytes(out), img.planes, img.note)


# ---------------------------------------------------------------- planar helpers

def _planar_rows(data, width, height, depth, row_bytes, pos=0, interleaved=True):
    """Yield, per row, a list of colour indexes from planar data."""
    for y in range(height):
        idx = [0] * width
        for p in range(depth):
            if interleaved:
                off = pos + (y * depth + p) * row_bytes
            else:
                off = pos + (p * height + y) * row_bytes
            line = data[off:off + row_bytes]
            if len(line) < row_bytes:
                line = line + bytes(row_bytes - len(line))
            bit = 1 << p
            for x in range(width):
                if line[x >> 3] & (0x80 >> (x & 7)):
                    idx[x] |= bit
        yield idx


# ---------------------------------------------------------------- IFF

def is_iff_picture(head: bytes) -> bool:
    return len(head) >= 12 and head[:4] == b"FORM" and head[8:12] in (b"ILBM", b"PBM ", b"ACBM")


def _chunks(data, start, end):
    pos = start
    while pos + 8 <= end:
        tag = data[pos:pos + 4]
        size = struct.unpack(">I", data[pos + 4:pos + 8])[0]
        yield tag, data[pos + 8:pos + 8 + size]
        pos += 8 + size + (size & 1)


def _byterun1(src, out_len):
    out = bytearray()
    i, n = 0, len(src)
    while len(out) < out_len and i < n:
        c = src[i]
        i += 1
        if c < 128:
            out += src[i:i + c + 1]
            i += c + 1
        elif c > 128:
            if i < n:
                out += bytes([src[i]]) * (257 - c)
            i += 1
    if len(out) < out_len:
        out += bytes(out_len - len(out))
    return bytes(out[:out_len])


def decode_iff(data: bytes):
    """Decode an IFF ILBM / PBM / ACBM picture. Returns (Image, info dict) or None."""
    if not is_iff_picture(data):
        return None
    form = data[8:12]
    end = min(len(data), 8 + struct.unpack(">I", data[4:8])[0])
    bmhd = cmap = body = None
    camg = 0
    for tag, chunk in _chunks(data, 12, end):
        if tag == b"BMHD":
            bmhd = chunk
        elif tag == b"CMAP":
            cmap = chunk
        elif tag == b"CAMG" and len(chunk) >= 4:
            camg = struct.unpack(">I", chunk[:4])[0]
        elif tag in (b"BODY", b"ABIT"):
            body = chunk
    if not bmhd or body is None or len(bmhd) < 20:
        return None
    w, h, _, _, planes, masking, comp, _, transp, xasp, yasp = struct.unpack(">HHhhBBBBHBB", bmhd[:16])
    if not (0 < w <= 2048 and 0 < h <= 2048 and 0 < planes <= 32):
        return None
    pal = []
    if cmap:
        vals = list(cmap[:len(cmap) // 3 * 3])
        if vals and all(v & 0x0F == 0 for v in vals):          # OCS 4-bit colours
            vals = [v | (v >> 4) for v in vals]
        pal = [tuple(vals[i:i + 3]) for i in range(0, len(vals), 3)]
    ham = bool(camg & 0x800) or (planes in (6, 8) and len(pal) in (16, 64) and planes - 2 == len(pal).bit_length() - 1)
    ehb = bool(camg & 0x80) or (planes == 6 and len(pal) == 32 and not ham)
    if ehb:
        pal = (pal + [(0, 0, 0)] * 32)[:32]
        pal += [(r >> 1, g >> 1, b >> 1) for r, g, b in pal]
    out = bytearray(w * h * 4)
    note = "HAM%d" % planes if ham else ("EHB" if ehb else "")

    if form == b"PBM ":
        row_bytes = w + (w & 1)
        pixels = _byterun1(body, row_bytes * h) if comp == 1 else body
        for y in range(h):
            for x in range(w):
                i = pixels[y * row_bytes + x] if y * row_bytes + x < len(pixels) else 0
                r, g, b = pal[i] if i < len(pal) else (i, i, i)
                o = (y * w + x) * 4
                out[o:o + 4] = bytes((r, g, b, 255))
        return Image(w, h, bytes(out), 8, note), {"camg": camg, "xasp": xasp, "yasp": yasp}

    row_bytes = ((w + 15) // 16) * 2
    total_planes = planes + (1 if masking == 1 else 0)
    if form == b"ACBM":
        pixels, interleaved = body, False
        total_planes = planes
    else:
        pixels = _byterun1(body, row_bytes * total_planes * h) if comp == 1 else body
        interleaved = True
    o = 0
    for idx in _planar_rows(pixels, w, h, total_planes if interleaved else planes, row_bytes,
                            interleaved=interleaved):
        if masking == 1:
            mask_bit = 1 << planes
            idx = [(i & ~mask_bit) for i in idx]
        if planes == 24:
            for i in idx:
                out[o:o + 4] = bytes((i & 0xFF, (i >> 8) & 0xFF, (i >> 16) & 0xFF, 255))
                o += 4
        elif ham:
            cbits = planes - 2
            r = g = b = 0
            if pal:
                r, g, b = pal[0]
            shift = 8 - cbits
            for i in idx:
                mode, val = i >> cbits, i & ((1 << cbits) - 1)
                if mode == 0:
                    r, g, b = pal[val] if val < len(pal) else (0, 0, 0)
                else:
                    v = ((val << shift) | (val >> (cbits - shift))) & 0xFF
                    if mode == 1:
                        b = v
                    elif mode == 2:
                        r = v
                    else:
                        g = v
                out[o:o + 4] = bytes((r, g, b, 255))
                o += 4
        else:
            for i in idx:
                if i < len(pal):
                    r, g, b = pal[i]
                else:                       # no palette: grey ramp
                    r = g = b = (i * 255 // ((1 << planes) - 1)) if planes else 0
                a = 0 if masking == 2 and i == transp else 255
                out[o:o + 4] = bytes((r, g, b, a))
                o += 4
    return Image(w, h, bytes(out), planes, note), {"camg": camg, "xasp": xasp, "yasp": yasp}


def square_pixels(img: Image, info: dict) -> Image:
    """Make an Amiga picture look right on a PC screen (hires or interlaced pixels aren't square)."""
    camg = info.get("camg", 0)
    hires, lace = bool(camg & 0x8000), bool(camg & 0x4)
    if not camg:                          # guess from the size
        hires = img.width >= 600
        lace = img.height >= 400
    if hires and not lace:
        return scale(img, 1, 2)
    if lace and not hires:
        return scale(img, 2, 1)
    return img


# ---------------------------------------------------------------- .info icons

# Workbench palettes: 1.x (blue background) and 2.0+ (grey, with the MagicWB extra colours).
WB13 = [(0, 85, 170), (255, 255, 255), (0, 0, 0), (255, 136, 0)]
WB20 = [(149, 149, 149), (0, 0, 0), (255, 255, 255), (59, 103, 162),
        (123, 123, 123), (175, 175, 175), (170, 144, 124), (255, 169, 151)]


def _icon_image(data, pos, palette):
    if pos + 20 > len(data):
        return None, pos
    left, top, w, h, depth, _, pick, onoff, _ = struct.unpack(">hhhhhIBBI", data[pos:pos + 20])
    pos += 20
    if not (0 < w <= 512 and 0 < h <= 512 and 0 < depth <= 8):
        return None, pos
    row_bytes = ((w + 15) // 16) * 2
    size = row_bytes * h * depth
    planes = data[pos:pos + size]
    pos += size
    out = bytearray(w * h * 4)
    o = 0
    for idx in _planar_rows(planes, w, h, depth, row_bytes, interleaved=False):
        for i in idx:
            if i == 0:
                out[o:o + 4] = b"\0\0\0\0"            # colour 0 is the Workbench background
            else:
                r, g, b = palette[i] if i < len(palette) else palette[i % len(palette)]
                out[o:o + 4] = bytes((r, g, b, 255))
            o += 4
    return Image(w, h, bytes(out), depth), pos


def _bits(data, nbits):
    """Read a stream of nbits-wide values, most significant bit first."""
    acc = have = 0
    for byte in data:
        acc = (acc << 8) | byte
        have += 8
        while have >= nbits:
            have -= nbits
            yield (acc >> have) & ((1 << nbits) - 1)
            acc &= (1 << have) - 1


def _glow_rle(data, depth, count):
    out = []
    # Control bytes and values share one bit stream.
    stream = _BitReader(data)
    while len(out) < count and not stream.done():
        c = stream.read(8)
        if c is None:
            break
        if c < 128:
            for _ in range(c + 1):
                v = stream.read(depth)
                if v is None:
                    break
                out.append(v)
        elif c > 128:
            v = stream.read(depth)
            if v is None:
                break
            out += [v] * (257 - c)
    return (out + [0] * count)[:count]


class _BitReader:
    def __init__(self, data):
        self.data, self.pos = data, 0

    def done(self):
        return self.pos >= len(self.data) * 8

    def read(self, n):
        if self.pos + n > len(self.data) * 8:
            return None
        v = 0
        for _ in range(n):
            byte = self.data[self.pos >> 3]
            v = (v << 1) | ((byte >> (7 - (self.pos & 7))) & 1)
            self.pos += 1
        return v


def _glowicon(data):
    """OS 3.5 GlowIcon: an IFF FORM ICON appended to the classic icon."""
    at = data.find(b"FORM", 78)
    while at >= 0 and data[at + 8:at + 12] != b"ICON":
        at = data.find(b"FORM", at + 4)
    if at < 0:
        return None
    end = min(len(data), at + 8 + struct.unpack(">I", data[at + 4:at + 8])[0])
    w = h = None
    for tag, chunk in _chunks(data, at + 12, end):
        if tag == b"FACE" and len(chunk) >= 2:
            w, h = chunk[0] + 1, chunk[1] + 1
        elif tag == b"IMAG" and w and len(chunk) >= 10:
            transp, ncol, flags, ifmt, pfmt, depth = chunk[:6]
            nimg = struct.unpack(">H", chunk[6:8])[0] + 1
            npal = struct.unpack(">H", chunk[8:10])[0] + 1
            ncol += 1
            img = chunk[10:10 + nimg]
            pal_raw = chunk[10 + nimg:10 + nimg + npal] if flags & 2 else b""
            if not (flags & 2) or not 1 <= depth <= 8:
                return None
            idx = _glow_rle(img, depth, w * h) if ifmt == 1 else list(_bits(img, depth))[:w * h]
            pal_bytes = _glow_rle(pal_raw, 8, ncol * 3) if pfmt == 1 else list(pal_raw[:ncol * 3])
            pal = [tuple(pal_bytes[i:i + 3]) for i in range(0, len(pal_bytes) - 2, 3)]
            out = bytearray()
            for i in (idx + [0] * (w * h))[:w * h]:
                if flags & 1 and i == transp:
                    out += b"\0\0\0\0"
                else:
                    r, g, b = pal[i] if i < len(pal) else (0, 0, 0)
                    out += bytes((r, g, b, 255))
            return Image(w, h, bytes(out), depth, "GlowIcon")
    return None


def decode_icon(data: bytes):
    """Decode a Workbench .info icon: OS4 PNG icons are returned as raw PNG bytes,
    GlowIcons and classic icons as an Image. Returns None if it isn't an icon."""
    if data[:8] == b"\x89PNG\r\n\x1a\n":
        return data
    if len(data) < 78 or data[:2] != b"\xe3\x10":
        return None
    glow = None
    try:
        glow = _glowicon(data)
    except Exception:
        glow = None
    if glow:
        return glow
    gadget = data[4:48]
    user_data = struct.unpack(">I", gadget[40:44])[0]
    drawer_data = struct.unpack(">I", data[66:70])[0]
    palette = WB20 if (user_data & 0xFF) >= 1 else WB13
    pos = 78 + (56 if drawer_data else 0)
    img, _ = _icon_image(data, pos, palette)
    if img is not None:
        img.note = "Workbench 2+" if palette is WB20 else "Workbench 1.3"
    return img
