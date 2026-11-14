"""Workbench icons (.info files) for TurboView: the tool icon (with its tooltypes), the floppies'
disk icons and the hard-drive drawer icon.

Classic icons marked as Workbench 2 icons (revision 1, as 2.04 and 3.1 make them; Workbench 1.3
reads them too), no GlowIcons, drawn from TurboCAT's own 16x16 pixel art
(icons/mark.svg and disk.svg), which already uses the four Workbench 2.0 colours. Each art pixel
becomes 4x2 Workbench pixels (64x32), which looks square on a 640x256 Workbench.

The file layout (all big-endian), as icon.library reads it:
  DiskObject (78 bytes), with a Gadget inside; DrawerData (56 bytes) for disks and drawers;
  Image (20 bytes) and its bitplanes; the default tool (length + text); the tooltypes
  ((count + 1) * 4, then length + text for each); and, for disks and drawers of revision 1,
  DrawerData2 (6 bytes: flags and view mode) at the very end.
"""
import os
import re
import struct

ICON_DIR = os.path.join(os.path.dirname(__file__), "icons")
WBDISK, WBDRAWER, WBTOOL, WBPROJECT = 1, 2, 3, 4
NO_POSITION = 0x80000000
# Workbench 2.0 pens, by the colours the pixel art uses
PENS = {"#AAAAAA": 0, "#000000": 1, "#FFFFFF": 2, "#6688BB": 3}


def art(name):
    """A 16x16 grid of pens (0-3) from one of TurboCAT's pixel-art SVGs."""
    with open(os.path.join(ICON_DIR, name + ".svg"), encoding="utf-8") as f:
        svg = f.read()
    grid = [[0] * 16 for _ in range(16)]
    for x, y, w, h, fill in re.findall(
            r'<rect x="(\d+)" y="(\d+)" width="(\d+)" height="(\d+)" fill="(#[0-9A-Fa-f]{6})"', svg):
        pen = PENS.get(fill.upper(), 1)
        for yy in range(int(y), int(y) + int(h)):
            for xx in range(int(x), int(x) + int(w)):
                if 0 <= xx < 16 and 0 <= yy < 16:
                    grid[yy][xx] = pen
    return grid


def _image(grid, sx=4, sy=2):
    """An Image struct and its two bitplanes for a grid of pens, scaled sx by sy."""
    w, h = len(grid[0]) * sx, len(grid) * sy
    row_bytes = ((w + 15) // 16) * 2
    planes = []
    for plane in range(2):
        data = bytearray(row_bytes * h)
        for y in range(h):
            for x in range(w):
                if grid[y // sy][x // sx] >> plane & 1:
                    data[y * row_bytes + x // 8] |= 0x80 >> (x % 8)
        planes.append(bytes(data))
    head = struct.pack(">hhhhhIBBI", 0, 0, w, h, 2, 1, 3, 0, 0)
    return w, h, head + b"".join(planes)


def _text(s):
    b = s.encode("latin-1", "replace") + b"\0"
    return struct.pack(">I", len(b)) + b


def make(kind, picture, tooltypes=(), default_tool="", stack=0, window=(50, 30, 400, 120)):
    """The bytes of a .info file. kind: WBDISK, WBDRAWER, WBTOOL or WBPROJECT; picture: an art()
    grid; window: where a disk's or drawer's window opens (left, top, width, height)."""
    w, h, image = _image(picture)
    has_drawer = kind in (WBDISK, WBDRAWER)
    gadget = struct.pack(">IhhhhHHHIIIiIHI",
                         0, 0, 0, w, h + 1,        # next; left, top, width, height (+1: Workbench's own)
                         4,                         # flags: GADGIMAGE, highlight by complementing
                         3, 1,                      # activation RELVERIFY|GADGIMMEDIATE; BOOLGADGET
                         1, 0, 0, 0, 0, 0,          # render (an image follows), select, text, mutex, special, id
                         1)                         # user data: revision 1, a Workbench 2 icon
    tools = list(tooltypes)
    head = (struct.pack(">HH", 0xE310, 1) + gadget
            + struct.pack(">BBIIIIIII", kind, 0, 1 if default_tool else 0, 1 if tools else 0,
                          NO_POSITION, NO_POSITION, 1 if has_drawer else 0, 0, stack))
    assert len(head) == 78
    out = [head]
    if has_drawer:
        left, top, width, height = window
        new_window = struct.pack(">hhhhBBIIIIIIIhhHHH", left, top, width, height, 255, 255, 0, 0,
                                 0, 0, 0, 0, 0, 90, 40, 0xFFFF, 0xFFFF, 1)    # Type 1: Workbench screen
        out.append(new_window + struct.pack(">ii", 0, 0))
        assert len(out[-1]) == 56
    out.append(image)
    if default_tool:
        out.append(_text(default_tool))
    if tools:
        out.append(struct.pack(">I", (len(tools) + 1) * 4) + b"".join(_text(t) for t in tools))
    if has_drawer:                  # Workbench 2's view settings: show icons, view by icon
        out.append(struct.pack(">IH", 1, 1))
    return b"".join(out)


def tool_icon(tooltypes=(), stack=40000):
    """TurboView's own icon: the TurboCAT cat."""
    return make(WBTOOL, art("mark"), tooltypes=tooltypes, stack=stack)


def disk_icon():
    """A TurboView floppy's icon."""
    return make(WBDISK, art("disk"), window=(60, 30, 360, 110))


def drawer_icon():
    """The drawer TurboView is installed in."""
    return make(WBDRAWER, art("mark"), window=(80, 40, 360, 110))


def readme_icon():
    """The floppies' ReadMe: opens in Workbench's More (Utilities/More is on 1.3 to 3.x)."""
    return make(WBPROJECT, art("magazine"), default_tool="SYS:Utilities/More")


def read(data):
    """(kind, tooltypes, default tool) from a .info file made here (or any classic icon)."""
    if data[:2] != b"\xe3\x10":
        raise ValueError("not an icon")
    kind = data[48]
    has_tool, has_types = struct.unpack(">II", data[50:58])
    has_drawer = struct.unpack(">I", data[66:70])[0]
    pos = 78 + (56 if has_drawer else 0)
    for render_at in (18, 22):                     # GadgetRender, then SelectRender (in the Gadget)
        if struct.unpack(">I", data[4 + render_at:8 + render_at])[0]:
            w, h, depth = struct.unpack(">hhh", data[pos + 4:pos + 10])
            pos += 20 + ((w + 15) // 16) * 2 * h * depth

    def text(at):
        n = struct.unpack(">I", data[at:at + 4])[0]
        return data[at + 4:at + 4 + n].rstrip(b"\0").decode("latin-1"), at + 4 + n
    tool = ""
    if has_tool:
        tool, pos = text(pos)
    types = []
    if has_types:
        count = struct.unpack(">I", data[pos:pos + 4])[0] // 4 - 1
        pos += 4
        for _ in range(count):
            t, pos = text(pos)
            types.append(t)
    return kind, types, tool
