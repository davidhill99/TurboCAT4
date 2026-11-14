"""Help › Report a problem / Suggest an idea, and the crash catcher's report.

A report goes to GitHub Issues on TurboCAT's repository: TurboCAT opens the browser at a new issue
with the tester's words and the technical details already filled in, and the tester presses
Submit there. TurboCAT itself sends nothing, and needs no account, token or server.

What the details hold: TurboCAT, Python and Qt versions, the operating system, what Check setup
found (emulators, music players...), and how many items the catalogue has. Never file lists or the
catalogue. Anything that could name the person (their home folder, user name) is replaced first,
and the window shows the exact text before it goes anywhere.
"""
import getpass
import os
import platform
import re
import sys
import traceback
import urllib.parse

from . import APP_NAME, VERSION

REPO = "https://github.com/davidhill99/TurboCAT4"
# Issue forms in the repository (.github/ISSUE_TEMPLATE): their field ids are filled from the link
TEMPLATES = {"problem": "problem.yml", "idea": "idea.yml", "amiga": "amiga.yml"}
MAX_URL = 7500           # browsers and GitHub cope with links about this long


def scrub(text):
    """The text with the user's home folder shown as ~ and their user name taken out."""
    if not text:
        return ""
    home = os.path.expanduser("~")
    if home and home not in ("/", "~"):
        text = text.replace(home, "~")
        text = text.replace(home.replace("\\", "/"), "~")
    try:
        user = getpass.getuser()
    except Exception:
        user = ""
    if user and len(user) > 2:
        text = re.sub(rf"(?<![\w]){re.escape(user)}(?![\w])", "<user>", text)
    return text


def details(checks=None, items=None):
    """The technical details, as plain lines, already scrubbed."""
    lines = [f"{APP_NAME} {VERSION}"]
    try:
        from . import setup
        lines.append(f"System: {setup.platform_name()} ({platform.machine()})")
    except Exception:
        lines.append(f"System: {platform.system()} {platform.release()} ({platform.machine()})")
    lines.append(f"Python {platform.python_version()}")
    try:
        import PySide6
        from PySide6.QtGui import QGuiApplication
        qpa = QGuiApplication.platformName() if QGuiApplication.instance() else ""
        lines.append(f"Qt (PySide6) {PySide6.__version__}" + (f", {qpa}" if qpa else ""))
    except Exception:
        pass
    if items is not None:
        lines.append(f"Catalogue: {items:,} items")
    if checks:
        lines.append("Setup:")
        for c in checks:
            lines.append(f"  {c.name}: {c.status}" + (f" ({c.detail})" if c.detail else ""))
    return scrub("\n".join(lines))


def error_text(exc_type, exc, tb):
    """An error's details for a report: the type, message and where it happened, scrubbed."""
    return scrub("".join(traceback.format_exception(exc_type, exc, tb)).strip())


def body(kind, fields, tech):
    """The report as one text (shown to the tester, and what Copy details copies)."""
    heads = {"what": "What were you doing?", "happened": "What happened?",
             "expected": "What did you expect?", "idea": "The idea", "why": "Why it would help",
             "amiga": "Your Amiga", "tried": "What you tried", "went": "How it went"}
    parts = []
    for key, text in fields.items():
        if text.strip():
            parts.append(f"### {heads.get(key, key)}\n{text.strip()}")
    parts.append(f"### Details\n```\n{tech}\n```")
    return "\n\n".join(parts)


def issue_url(kind, title, fields, tech):
    """A link to a new GitHub issue with everything filled in. A very long report (a big error)
    is cut down to fit; Copy details always has all of it."""
    tech_cut = tech
    while True:
        q = {"template": TEMPLATES[kind], "title": title}
        q.update({k: v for k, v in fields.items() if v.strip()})
        q["details"] = tech_cut
        url = f"{REPO}/issues/new?" + urllib.parse.urlencode(q, quote_via=urllib.parse.quote)
        if len(url) <= MAX_URL or len(tech_cut) < 200:
            return url
        tech_cut = tech_cut[:len(tech_cut) * 2 // 3].rstrip() + "\n… (cut short: Copy details has it all)"


def install_catcher(show):
    """Send any unexpected error to show(exc_type, exc, tb) as well as to the console. show is
    called on whichever thread the error happened; the window moves it to its own."""
    old = sys.excepthook

    def hook(exc_type, exc, tb):
        try:
            old(exc_type, exc, tb)
        except Exception:
            pass
        if issubclass(exc_type, KeyboardInterrupt):
            return
        try:
            show(exc_type, exc, tb)
        except Exception:
            pass
    sys.excepthook = hook
    import threading

    def thread_hook(args):
        hook(args.exc_type, args.exc_value, args.exc_traceback)
    threading.excepthook = thread_hook
    return hook


# ---------------------------------------------------------------- the kill switch

STORM_SHOWN = 3            # error boxes shown within STORM_MINUTES ...
STORM_TOTAL = 20           # ... or errors of any kind (shown or not) within it
STORM_MINUTES = 10


class CrashLog:
    """Every unexpected error this session, shown or not, so TurboCAT can tell when it is
    interrupting too often (a storm) and say exactly why error reports were switched off."""

    def __init__(self, clock=None):
        import time
        self.clock = clock or time.monotonic
        self.started = self.clock()
        self.errors = []          # [(when, kind, message, where)]
        self.shown = []           # when each error box was shown

    def add(self, exc_type, exc, tb):
        where = ""
        frames = traceback.extract_tb(tb) if tb is not None else []
        if frames:
            f = frames[-1]
            where = f"{os.path.basename(f.filename)}:{f.lineno} in {f.name}"
        self.errors.append((self.clock(), exc_type.__name__, scrub(str(exc))[:200], where))

    def box_shown(self):
        self.shown.append(self.clock())

    def storm(self):
        """True when error boxes are coming too often: another would be nagging."""
        since = self.clock() - STORM_MINUTES * 60
        return (sum(1 for t in self.shown if t >= since) >= STORM_SHOWN
                or sum(1 for e in self.errors if e[0] >= since) >= STORM_TOTAL)

    def kinds(self):
        """[(kind, message, where, times)], most frequent first."""
        count = {}
        for _t, kind, msg, where in self.errors:
            key = (kind, msg, where)
            count[key] = count.get(key, 0) + 1
        return sorted(((k, m, w, n) for (k, m, w), n in count.items()), key=lambda r: -r[3])

    def reason(self, how):
        """Why error reports were switched off, in words, for a report.
        how: 'auto' (TurboCAT paused them) or 'user' (the tester turned them off)."""
        mins = max(1, round((self.clock() - self.started) / 60))
        n, boxes = len(self.errors), len(self.shown)
        head = ("TurboCAT paused its error reports by itself: they were coming too often"
                if how == "auto" else "The tester switched error reports off")
        lines = [f"{head}. {n} unexpected error{'s' if n != 1 else ''} in {mins} minute"
                 f"{'s' if mins != 1 else ''} of use; {boxes} error box{'es' if boxes != 1 else ''} shown."]
        for kind, msg, where, times in self.kinds()[:10]:
            lines.append(f"  {times}x {kind}: {msg}" + (f"  ({where})" if where else ""))
        return "\n".join(lines)
