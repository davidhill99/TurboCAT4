"""Work TurboCAT does by itself (finding pictures, looking up games online) runs gently, so the
window stays quick while it goes on:

  * it runs in processes of its own at the lowest priority (jobs.py);
  * it waits while the user is using the window (clicking, typing, scrolling), and carries on
    a moment after they stop. The window notes the time of each key, click and scroll here; the
    background processes see the same time through a shared value.
"""
import os
import sys
import threading
import time

QUIET_FOR = 1.5          # seconds without the user doing anything before background work goes on
LONGEST_WAIT = 20.0      # it never waits longer than this at a time (someone holding a key down)

_last_input = 0.0
_shared = None           # the window: a multiprocessing value the background processes read
_attached = None         # a background process: the window's value


def shared_last_input():
    """The value handed to background processes (made on first use)."""
    global _shared
    if _shared is None:
        import multiprocessing
        _shared = multiprocessing.get_context("spawn").Value("d", _last_input, lock=False)
    return _shared


def attach(value):
    """In a background process: read the window's last-input time from value."""
    global _attached
    _attached = value


def user_did_something():
    """Called by the window for every key, click and scroll."""
    global _last_input
    _last_input = time.monotonic()      # the same clock in every process (Linux, macOS, Windows)
    if _shared is not None:
        _shared.value = _last_input


def user_busy():
    last = _attached.value if _attached is not None else _last_input
    return time.monotonic() - last < QUIET_FOR


def lower_priority():
    """Make the calling thread the lowest priority (call it at the start of a worker's run)."""
    if sys.platform.startswith("linux"):
        try:
            os.setpriority(os.PRIO_PROCESS, threading.get_native_id(), 19)
        except (OSError, AttributeError):
            pass


def pace(stop=lambda: False):
    """Wait while the user is busy with the window (up to LONGEST_WAIT), then return."""
    start = time.monotonic()
    while user_busy() and not stop() and time.monotonic() - start < LONGEST_WAIT:
        time.sleep(0.2)
