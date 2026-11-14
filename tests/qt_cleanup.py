"""Imported by the tests that open Qt windows. Just before Python starts shutting down, it deletes
any windows the tests left behind, while Qt is still whole: left to Python's own shutdown they are
destroyed in an order Qt doesn't survive, and the run ends with a crash (exit 139) after "OK"."""
import atexit
import gc


def _clean_up():
    try:
        from PySide6.QtCore import QEvent
        from PySide6.QtWidgets import QApplication
    except ImportError:
        return
    app = QApplication.instance()
    if app is None:
        return
    for w in QApplication.topLevelWidgets():
        w.hide()
        w.deleteLater()
    app.sendPostedEvents(None, QEvent.Type.DeferredDelete.value)
    gc.collect()
    app.sendPostedEvents(None, QEvent.Type.DeferredDelete.value)


atexit.register(_clean_up)
