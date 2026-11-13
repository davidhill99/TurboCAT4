"""Music modules: recognise them on disks, and play them.

Recognition looks at the file's contents (ProTracker and its relatives, OctaMED, OctaMED
SoundStudio, Oktalyzer, FastTracker 2, Scream Tracker 3, Impulse Tracker, AHX), plus the older
15-instrument Soundtracker modules, which have no signature, when the name says "mod.".

Playback renders the module with libopenmpt (through ctypes) and the window plays the sound
with Qt Multimedia. TurboCAT's own copy in turbocat/lib is used first (libopenmpt 0.8+ plays
OctaMED synth instruments); otherwise the system's (Linux; VLC uses it), or Homebrew's on macOS.
AHX tunes are recognised but libopenmpt can't play them.
"""
import ctypes
import ctypes.util
import os
import re

PT_TAGS = {b"M.K.": "ProTracker", b"M!K!": "ProTracker", b"M&K!": "ProTracker",
           b"FLT4": "StarTrekker", b"FLT8": "StarTrekker", b"4CHN": "FastTracker",
           b"6CHN": "FastTracker", b"8CHN": "FastTracker", b"CD81": "Octalyser",
           b"N.T.": "NoiseTracker"}
NAME_HINT = re.compile(r"(^|/)(mod|med|xm|s3m|okt|ahx|thx)\.[^/]+$|\.(mod|med|xm|s3m|it|okt|ahx|thx)$",
                       re.I)
PLAYABLE = {"ProTracker", "StarTrekker", "FastTracker", "Octalyser", "Oktalyzer", "NoiseTracker",
            "Soundtracker", "OctaMED", "FastTracker 2", "Scream Tracker 3", "Impulse Tracker"}
RATE = 48000


def _soundtracker15(data):
    """The original 15-instrument Soundtracker format has no signature: check that it adds up."""
    if len(data) < 600 + 1024:
        return False
    song_len = data[470]
    pats = data[472:600]
    if not 1 <= song_len <= 128 or max(pats) > 63:
        return False
    for i in range(15):
        h = data[20 + i * 30:50 + i * 30]
        if h[25] > 64 or (h[24] & 0xF0):          # volume 0-64, finetune none
            return False
    return 600 + (max(pats) + 1) * 1024 <= len(data) + 4096


def identify(name, data):
    """Return (format, title) if data is a music module, else None."""
    if len(data) < 64:
        return None
    if len(data) >= 1084 and data[1080:1084] in PT_TAGS:
        return PT_TAGS[data[1080:1084]], _clean(data[:20])
    if len(data) >= 1084 and re.fullmatch(rb"\d\dCH|\dCHN|TDZ\d", data[1080:1084]):
        return "FastTracker", _clean(data[:20])
    head = data[:4]
    if head in (b"MMD0", b"MMD1", b"MMD2", b"MMD3"):
        return "OctaMED", ""
    if data[:8] == b"OKTASONG":
        return "Oktalyzer", ""
    if data[:17] == b"Extended Module: ":
        return "FastTracker 2", _clean(data[17:37])
    if len(data) > 48 and data[44:48] == b"SCRM":
        return "Scream Tracker 3", _clean(data[:28])
    if head == b"IMPM":
        return "Impulse Tracker", _clean(data[4:30])
    if head[:3] == b"THX" and head[3] in (0, 1, 2):
        return "AHX", ""
    if NAME_HINT.search(name) and name.lower().rsplit("/", 1)[-1].startswith("mod.") \
            and _soundtracker15(data):
        return "Soundtracker", _clean(data[:20])
    return None


def embedded(data, limit=8):
    """ProTracker modules built into a program (music disks, intros): [(offset, length, title)].
    Only uncrunched programs keep the module whole; packed ones can't be searched."""
    out = []
    pos = data.find(b"M.K.", 1080)
    while pos >= 0 and len(out) < limit:
        st = pos - 1080
        song_len = data[st + 950]
        pats = data[st + 952:st + 1080]
        if 1 <= song_len <= 128 and pats and max(pats) < 100:
            samples = sum(int.from_bytes(data[st + 42 + i * 30:st + 44 + i * 30], "big") * 2
                          for i in range(31))
            length = 1084 + (max(pats) + 1) * 1024 + samples
            if st + length <= len(data) + 2048:
                out.append((st, min(length, len(data) - st), _clean(data[st:st + 20])))
                pos = data.find(b"M.K.", st + length)
                continue
        pos = data.find(b"M.K.", pos + 4)
    return out


def _clean(raw):
    t = raw.split(b"\0", 1)[0].decode("latin-1", "replace")
    t = "".join(c if c.isprintable() else " " for c in t)
    return " ".join(t.split())


def might_be_module(name, size):
    """Worth opening to check? (Files that are clearly something else are skipped.)"""
    return 600 <= size <= 4_000_000 and (NAME_HINT.search(name) is not None or 1084 <= size)


# ---------------------------------------------------------------- libopenmpt

class _Lib:
    lib = None

    @classmethod
    def get(cls):
        if cls.lib is None:
            here = os.path.dirname(os.path.abspath(__file__))
            # TurboCAT's own copy first (turbocat/lib): libopenmpt 0.8 and later play OctaMED's
            # synthesised and hybrid instruments, which the 0.7 that older Linux systems have can't.
            mine = [os.path.join(here, "lib", n) for n in
                    ("libopenmpt.so", "libopenmpt.dll", "libopenmpt.dylib")]
            names = mine + [ctypes.util.find_library("openmpt"), "libopenmpt.dll",
                            "libopenmpt.so.0", "/opt/homebrew/lib/libopenmpt.dylib",
                            "/usr/local/lib/libopenmpt.dylib", "libopenmpt.dylib"]
            lib = None
            for name in filter(None, names):
                try:
                    lib = ctypes.CDLL(name)
                    break
                except OSError:
                    continue
            if lib is None:
                cls.lib = False
                return None
            c = ctypes
            lib.openmpt_module_create_from_memory2.restype = c.c_void_p
            lib.openmpt_module_create_from_memory2.argtypes = [
                c.c_void_p, c.c_size_t, c.c_void_p, c.c_void_p, c.c_void_p, c.c_void_p,
                c.POINTER(c.c_int), c.POINTER(c.c_char_p), c.c_void_p]
            lib.openmpt_module_destroy.argtypes = [c.c_void_p]
            lib.openmpt_module_read_interleaved_stereo.restype = c.c_size_t
            lib.openmpt_module_read_interleaved_stereo.argtypes = [
                c.c_void_p, c.c_int32, c.c_size_t, c.POINTER(c.c_int16)]
            lib.openmpt_module_get_duration_seconds.restype = c.c_double
            lib.openmpt_module_get_duration_seconds.argtypes = [c.c_void_p]
            lib.openmpt_module_set_position_seconds.restype = c.c_double
            lib.openmpt_module_set_position_seconds.argtypes = [c.c_void_p, c.c_double]
            lib.openmpt_module_get_metadata.restype = c.c_void_p
            lib.openmpt_module_get_metadata.argtypes = [c.c_void_p, c.c_char_p]
            lib.openmpt_free_string.argtypes = [c.c_void_p]
            lib.openmpt_module_set_render_param.restype = c.c_int
            lib.openmpt_module_set_render_param.argtypes = [c.c_void_p, c.c_int, c.c_int32]
            lib.openmpt_module_ctl_set_text.restype = c.c_int
            lib.openmpt_module_ctl_set_text.argtypes = [c.c_void_p, c.c_char_p, c.c_char_p]
            cls.lib = lib
        return cls.lib or None


def available():
    """(ok, reason): can modules be played on this computer?"""
    if _Lib.get() is None and _Xmp.get() is None:
        return False, ("libopenmpt is not installed (on Debian, Ubuntu or Mint: "
                       "sudo apt install libopenmpt0)")
    try:
        import PySide6.QtMultimedia  # noqa: F401
    except ImportError:
        return False, "Qt Multimedia is not installed (pip install PySide6-Addons)"
    return True, ""


_LOG = ctypes.CFUNCTYPE(None, ctypes.c_char_p, ctypes.c_void_p)
_QUIET = _LOG(lambda message, user: None)      # libopenmpt's warnings go nowhere


class Module:
    """One module loaded into libopenmpt."""

    def __init__(self, data):
        lib = _Lib.get()
        if lib is None:
            raise RuntimeError("libopenmpt is not installed")
        self.lib = lib
        self._buf = ctypes.create_string_buffer(bytes(data), len(data))
        err = ctypes.c_int(0)
        msg = ctypes.c_char_p()
        self.mod = lib.openmpt_module_create_from_memory2(
            self._buf, len(data), ctypes.cast(_QUIET, ctypes.c_void_p), None, None, None,
            ctypes.byref(err), ctypes.byref(msg), None)
        if not self.mod:
            raise ValueError("this module can't be played" +
                             (f" ({msg.value.decode(errors='replace')})" if msg.value else ""))
        # Sound like an Amiga: its filter and resampling, with the channels a little less
        # widely split than real hardware (easier on headphones).
        lib.openmpt_module_ctl_set_text(self.mod, b"render.resampler.emulate_amiga", b"1")
        lib.openmpt_module_set_render_param(self.mod, 2, 70)     # stereo separation %

    def meta(self, key):
        p = self.lib.openmpt_module_get_metadata(self.mod, key.encode())
        if not p:
            return ""
        s = ctypes.string_at(p).decode("utf-8", "replace")
        self.lib.openmpt_free_string(p)
        return s.strip()

    @property
    def duration(self):
        return self.lib.openmpt_module_get_duration_seconds(self.mod)

    def seek(self, seconds):
        return self.lib.openmpt_module_set_position_seconds(self.mod, seconds)

    def render(self, frames, rate=RATE):
        """Up to `frames` stereo frames of 16-bit sound; b"" once the tune has ended."""
        buf = (ctypes.c_int16 * (frames * 2))()
        n = self.lib.openmpt_module_read_interleaved_stereo(self.mod, rate, frames, buf)
        return bytes(buf)[:n * 4]

    def close(self):
        if self.mod:
            self.lib.openmpt_module_destroy(self.mod)
            self.mod = None


# ---------------------------------------------------------------- libxmp (second opinion)

def versions():
    """{"libopenmpt": "0.7.13" or None, "libxmp": "4.6.0" or None} for the About box."""
    out = {"libopenmpt": None, "libxmp": None}
    lib = _Lib.get()
    if lib is not None:
        try:
            lib.openmpt_get_library_version.restype = ctypes.c_uint32
            v = lib.openmpt_get_library_version()
            out["libopenmpt"] = f"{v >> 24}.{(v >> 16) & 0xFF}.{v & 0xFFFF}"
        except Exception:
            out["libopenmpt"] = "installed"
    xmp = _Xmp.get()
    if xmp is not None:
        try:
            out["libxmp"] = ctypes.c_char_p.in_dll(xmp, "xmp_version").value.decode()
        except Exception:
            out["libxmp"] = "installed"
    return out


class _Xmp:
    lib = None

    @classmethod
    def get(cls):
        if cls.lib is None:
            lib = None
            for name in filter(None, [ctypes.util.find_library("xmp"), "libxmp.so.4", "libxmp.dll",
                                      "/opt/homebrew/lib/libxmp.dylib", "libxmp.dylib"]):
                try:
                    lib = ctypes.CDLL(name)
                    break
                except OSError:
                    continue
            if lib is None:
                cls.lib = False
                return None
            c = ctypes
            lib.xmp_create_context.restype = c.c_void_p
            lib.xmp_load_module_from_memory.argtypes = [c.c_void_p, c.c_void_p, c.c_long]
            lib.xmp_start_player.argtypes = [c.c_void_p, c.c_int, c.c_int]
            lib.xmp_play_buffer.argtypes = [c.c_void_p, c.c_void_p, c.c_int, c.c_int]
            lib.xmp_get_frame_info.argtypes = [c.c_void_p, c.c_void_p]
            lib.xmp_get_module_info.argtypes = [c.c_void_p, c.c_void_p]
            lib.xmp_seek_time.argtypes = [c.c_void_p, c.c_int]
            lib.xmp_set_player.argtypes = [c.c_void_p, c.c_int, c.c_int]
            for f in ("xmp_end_player", "xmp_release_module", "xmp_free_context"):
                getattr(lib, f).argtypes = [c.c_void_p]
            cls.lib = lib
        return cls.lib or None


class XmpModule:
    """The same as Module, played by libxmp: used for tunes libopenmpt can't play properly,
    such as OctaMED songs built from synthesised instruments."""

    def __init__(self, data, rate=RATE):
        lib = _Xmp.get()
        if lib is None:
            raise RuntimeError("libxmp is not installed")
        self.lib, self.rate = lib, rate
        self._buf = ctypes.create_string_buffer(bytes(data), len(data))
        self.ctx = lib.xmp_create_context()
        if lib.xmp_load_module_from_memory(self.ctx, self._buf, len(data)) != 0:
            lib.xmp_free_context(self.ctx)
            self.ctx = None
            raise ValueError("this module can't be played")
        lib.xmp_start_player(self.ctx, rate, 0)                # 16-bit stereo
        lib.xmp_set_player(self.ctx, 1, 70)                    # XMP_PLAYER_MIX: stereo separation %
        self.ended = False
        frame = ctypes.create_string_buffer(16384)
        lib.xmp_get_frame_info(self.ctx, frame)
        self._duration = int.from_bytes(frame.raw[32:36], "little", signed=True) / 1000.0
        mi = ctypes.create_string_buffer(64)
        lib.xmp_get_module_info(self.ctx, mi)
        mod_ptr = int.from_bytes(mi.raw[24:32], "little") if ctypes.sizeof(ctypes.c_void_p) == 8 \
            else int.from_bytes(mi.raw[20:24], "little")
        self._name = self._type = ""
        if mod_ptr:
            self._name = ctypes.string_at(mod_ptr, 64).split(b"\0")[0].decode("latin-1").strip()
            self._type = ctypes.string_at(mod_ptr + 64, 64).split(b"\0")[0].decode("latin-1").strip()

    def meta(self, key):
        if key == "type_long":
            return (self._type or "Module") + " (played by libxmp)"
        if key == "title":
            return self._name
        return ""

    @property
    def mod(self):                    # for code that checks whether the module is still open
        return self.ctx

    @property
    def duration(self):
        return self._duration

    def seek(self, seconds):
        self.lib.xmp_seek_time(self.ctx, int(seconds * 1000))
        return seconds

    def render(self, frames, rate=RATE):
        if self.ended or not self.ctx:
            return b""
        out = ctypes.create_string_buffer(frames * 4)
        if self.lib.xmp_play_buffer(self.ctx, out, frames * 4, 1) != 0:    # play once
            self.ended = True
            return b""
        return out.raw

    def close(self):
        if self.ctx:
            self.lib.xmp_end_player(self.ctx)
            self.lib.xmp_release_module(self.ctx)
            self.lib.xmp_free_context(self.ctx)
            self.ctx = None


def open_module(data, rate=RATE):
    """The best player for this tune: libopenmpt, or libxmp when libopenmpt can't play it
    properly (it says so in its warnings, e.g. synthesised MED instruments) or can't open it."""
    mod = None
    try:
        mod = Module(data)
    except Exception:
        mod = None
    if mod is not None and "not supported" not in mod.meta("warnings"):
        return mod
    if _Xmp.get() is not None:
        try:
            x = XmpModule(data, rate)
            if mod is not None:
                mod.close()
            return x
        except Exception:
            pass
    if mod is None:
        raise ValueError("this module can't be played")
    return mod


def fmt_time(sec):
    sec = int(round(sec))
    return f"{sec // 60}:{sec % 60:02d}"
