"""Background work in processes of its own: the picture search and finding out about games.

They used to run in threads of the window's own process. Python runs one thread at a time, so
however low their priority, the window had to wait its turn behind them and TurboCAT slowed down
while they ran (worse at low priority: a thread paused by the system kept everyone else waiting).
In a process of its own the work can't hold the window up. It runs at the lowest priority for the
processor and the disk, waits while the user is busy in the window, and reports how far it has got
through a pipe, which ProcessWorker turns into the same signals the threads had.

Both kinds run at the same time, side by side.
"""
import multiprocessing
import os
import sys
import time
import traceback

from PySide6.QtCore import QThread, Signal

from . import background

STOP_GRACE = 60          # seconds a stopped process gets to finish its current disk before it is ended


def _lowest_priority():
    """This whole process: idle priority for the processor, and for the disk where the system has it."""
    try:
        os.nice(19)
    except (OSError, AttributeError):
        pass
    if sys.platform.startswith("linux"):
        try:
            os.sched_setscheduler(0, os.SCHED_IDLE, os.sched_param(0))
        except (OSError, AttributeError):
            pass
        try:                                         # ioprio_set(IOPRIO_WHO_PROCESS, self, IDLE class)
            import ctypes
            import platform
            nr = {"x86_64": 251, "aarch64": 30, "i686": 289}.get(platform.machine())
            if nr:
                ctypes.CDLL(None, use_errno=True).syscall(nr, 1, 0, 3 << 13)
        except Exception:
            pass
    elif sys.platform == "win32":
        try:
            import ctypes
            ctypes.windll.kernel32.SetPriorityClass(ctypes.windll.kernel32.GetCurrentProcess(), 0x40)
        except Exception:
            pass


def _child(job, db_path, flags, stop_event, last_input, conn, args=()):
    """The process's whole life: run one job, reporting through conn."""
    _lowest_priority()
    background.attach(last_input)
    stop = stop_event.is_set
    progress = lambda *a: conn.send(("progress", a))

    def say(*a):                 # report, after waiting while the user is busy
        background.pace(stop)
        progress(*a)
    try:
        res = JOBS[job](db_path, flags, stop, say, progress, *args)
        conn.send(("done", res))
    except Exception as ex:
        traceback.print_exc()
        conn.send(("failed", str(ex) or type(ex).__name__))
    finally:
        conn.close()


def _name(m):
    try:
        return os.path.basename(m["source"])
    except Exception:
        return ""


def picture_job(db_path, flags, stop, say, progress):
    """Icons and pictures on new items; online too when the user agreed; then the list, read for
    the window (so it doesn't have to), and TurboView's copy brought up to date."""
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")     # drawing pictures needs Qt, not a window
    from PySide6.QtGui import QGuiApplication
    app = QGuiApplication.instance() or QGuiApplication(["turbocat-pictures"])   # noqa: F841
    from . import coverdisks, games, identify, madepics, magcovers, pictures, turboview
    from .catalogue import Catalogue
    from .gui import _has_disks, load_items
    cat = Catalogue(db_path)
    on = lambda flag: bool(flags[flag].value) and not stop()
    res = {}
    # The TOSEC list of Amiga disks, if the user agreed to it (once, then every two months).
    tosec = cat.get_meta(identify.TOSEC_CONSENT, False)
    if (tosec and (not identify.have_tosec() or identify.tosec_is_old())) or (
            not tosec and cat.get_meta(identify.CONSENT, False)
            and (not identify.have_list() or identify.list_is_old())):
        try:
            progress("identify", 0, 0, "tosec" if tosec else "")
            fetch = identify.download_tosec if tosec else identify.download
            fetch(stop, lambda d, t: progress("identify", d // 1024, t // 1024, "tosec" if tosec else ""))
            res["identify_fetched"] = True
        except pictures.Stopped:
            pass
        except Exception as ex:
            res["identify_error"] = str(ex)
    known_full = identify.for_catalogue(cat)
    known = {k: v[0] for k, v in known_full.items()}
    res["identified"] = len(known)
    res["disk"] = pictures.build(
        cat, lambda i, n, m, inner=None: say("disk", i, n, _name(m)) if inner is None else say(
            "disk-inside", inner[0], inner[1], f"{_name(m)}\t{inner[2]}"), stop)
    if not stop():
        res["lengths"] = pictures.measure_music(cat, lambda i, n, m: say("lengths", i, n, ""), stop)
    if on("online"):
        res["online"] = pictures.lookup_online(
            cat, lambda i, n, m: say("online", i, n, _name(m)), stop, known=known)
    if on("online"):
        # magazine covers for coverdisks, from the scans on the Internet Archive
        issues = []
        for m in cat.db.execute("SELECT id, source FROM media WHERE parent_id IS NULL"):
            cd = coverdisks.recognise(m["source"], known_full.get(m["id"]))
            if cd is not None and cd.magazine and cd.issue:
                issues.append((cd.magazine, magcovers.issue_key(cd.issue)))
        if issues:
            res["covers"] = magcovers.lookup(cat, issues, lambda i, n, w: say("covers", i, n, w), stop)
    if not stop():
        # disks still without a picture: draw their Workbench window or Shell listing
        res["drawn"] = madepics.make(cat, set(games.classify(cat)),
                                     lambda i, n, m: say("drawing", i, n, _name(m)), stop)
    if not stop():
        # the list read again here, so the window doesn't have to (38 seconds on a big catalogue)
        progress("reading", 0, 0, "")
        res["items"] = load_items(cat)
    if not stop() and _has_disks(cat):         # keep the Amiga's copy up to date
        try:
            folder = cat.get_meta("turboview_dir") or turboview.default_folder()
            turboview.install(folder)
            res["turboview"] = turboview.export(cat, res["items"], folder)
        except Exception as ex:
            res["turboview_error"] = str(ex)
    cat.db.close()
    return res


def info_job(db_path, flags, stop, say, progress):
    """What is known about the games and utilities: Wikidata, then Wikipedia's summaries."""
    from . import gameinfo, identify
    from .catalogue import Catalogue
    cat = Catalogue(db_path)
    try:
        known = {k: v[0] for k, v in identify.for_catalogue(cat).items()}
    except Exception:
        known = {}
    res = gameinfo.lookup(cat, lambda phase, i, n, what: say(phase, i, n, what), stop,
                          known=known, pace=lambda: background.pace(stop))
    cat.db.close()
    return res


def turboview_job(db_path, flags, stop, say, progress):
    """Bring TurboView's copy of the catalogue up to date (right after a scan: it doesn't wait for
    the picture search, which can take hours on a big collection)."""
    from . import turboview
    from .catalogue import Catalogue
    from .gui import _has_disks, load_items
    cat = Catalogue(db_path)
    try:
        if not _has_disks(cat):          # nothing to list: don't make TurboView's folder yet
            return {}
        folder = cat.get_meta("turboview_dir") or turboview.default_folder()
        items = load_items(cat)
        if stop():
            return {"stopped": True}
        turboview.install(folder)
        return turboview.export(cat, items, folder)
    finally:
        cat.db.close()                   # let go of the file (Windows can't move it otherwise)


def online_again_job(db_path, flags, stop, say, progress, ids):
    """Look online again for these items only (the details panel's Look online again…)."""
    from . import identify, pictures
    from .catalogue import Catalogue
    cat = Catalogue(db_path)
    try:
        try:
            known = {k: v[0] for k, v in identify.for_catalogue(cat).items() if k in set(ids)}
        except Exception:
            known = {}
        return pictures.lookup_online(cat, lambda i, n, m: progress("online-again", i, n, _name(m)),
                                      stop, known=known, only=ids)
    finally:
        cat.db.close()


JOBS = {"pictures": picture_job, "info": info_job, "turboview": turboview_job,
        "online-again": online_again_job}


class ProcessWorker(QThread):
    """Runs a job in a process of its own and passes on what it says, as signals in the window."""
    progress = Signal(str, int, int, str)      # phase, done, total, what it is looking at
    done = Signal(object)
    failed = Signal(str)
    JOB = ""
    FLAGS = ()

    def __init__(self, db_path, args=(), **flags):
        super().__init__()
        self.db_path = db_path
        self.args = tuple(args)          # passed on to the job after its usual ones
        self._ctx = multiprocessing.get_context("spawn")     # a fresh process: no copy of the window
        self._stop = self._ctx.Event()
        self._flags = {f: self._ctx.Value("b", bool(flags.get(f, False))) for f in self.FLAGS}
        self.exit_code = None

    @property
    def stop_wanted(self):
        return self._stop.is_set()

    @stop_wanted.setter
    def stop_wanted(self, value):
        if value:
            self._stop.set()

    def set_flag(self, name, value):
        self._flags[name].value = bool(value)

    def flag(self, name):
        return bool(self._flags[name].value)

    def run(self):
        receive, send = self._ctx.Pipe(duplex=False)
        proc = self._ctx.Process(
            target=_child, args=(self.JOB, self.db_path, self._flags, self._stop,
                                 background.shared_last_input(), send, self.args),
            daemon=True, name=f"turbocat-{self.JOB}")
        try:
            proc.start()
        except Exception as ex:
            self.failed.emit(f"couldn't start: {ex}")
            return
        send.close()
        ended = False
        stopped_at = None
        while not ended:
            if self.stop_wanted and stopped_at is None:
                stopped_at = time.monotonic()
            if stopped_at is not None and time.monotonic() - stopped_at > STOP_GRACE:
                proc.terminate()                    # stuck on one disk: everything done so far is saved
                break
            try:
                if not receive.poll(0.2):
                    if not proc.is_alive() and not receive.poll(0):
                        break
                    continue
                kind, value = receive.recv()
            except (EOFError, OSError):
                break
            if kind == "progress":
                self.progress.emit(*value)
            elif kind == "done":
                self.done.emit(value)
                ended = True
            elif kind == "failed":
                self.failed.emit(value)
                ended = True
        proc.join(10)
        self.exit_code = proc.exitcode
        if not ended and not self.stop_wanted:
            self.failed.emit(f"it stopped unexpectedly (exit code {proc.exitcode})")
        receive.close()


class PictureWorker(ProcessWorker):
    """Look for icons and pictures on items not yet looked at; optionally online too."""
    JOB = "pictures"
    FLAGS = ("online",)

    def __init__(self, db_path, online=False):
        super().__init__(db_path, online=online)

    online = property(lambda self: self.flag("online"), lambda self, v: self.set_flag("online", v))


class InfoWorker(ProcessWorker):
    """Find out about the games and utilities (gameinfo), alongside the picture search."""
    JOB = "info"


class OnlineAgainWorker(ProcessWorker):
    """Look online again for the pictures of a few items (online_again_job)."""
    JOB = "online-again"

    def __init__(self, db_path, ids):
        super().__init__(db_path, args=(list(ids),))


class TurboViewWorker(ProcessWorker):
    """Rewrite TurboView's catalogue files (turboview_job)."""
    JOB = "turboview"
