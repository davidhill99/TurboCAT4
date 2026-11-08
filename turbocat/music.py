"""Music modules: recognise them on disks, and play them.

Recognition looks at the file's contents (ProTracker and its relatives, OctaMED, OctaMED
SoundStudio, Oktalyzer, FastTracker 2, Scream Tracker 3, Impulse Tracker, AHX), plus the older
15-instrument Soundtracker modules, which have no signature, when the name says "mod.".

Playback renders the module with libopenmpt (through ctypes) and the window plays the sound
with Qt Multimedia. libopenmpt is usually already installed on Linux (VLC uses it); on Windows
TurboCAT looks for libopenmpt.dll next to itself, on macOS for Homebrew's copy.
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
            names = [ctypes.util.find_library("openmpt"),
                     os.path.join(here, "lib", "libopenmpt.dll"), "libopenmpt.dll",
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
    if _Lib.get() is None:
        return False, ("libopenmpt is not installed (on Debian, Ubuntu or Mint: "
                       "sudo apt install libopenmpt0)")
    try:
        import PySide6.QtMultimedia  # noqa: F401
    except ImportError:
        return False, "Qt Multimedia is not installed (pip install PySide6-Addons)"
    return True, ""


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
            self._buf, len(data), None, None, None, None, ctypes.byref(err), ctypes.byref(msg), None)
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


def fmt_time(sec):
    sec = int(round(sec))
    return f"{sec // 60}:{sec % 60:02d}"
