"""Run Python's cyclic garbage collector on the GUI thread only.

Why: Shiboken drops the GIL while it deletes the C++ side of a PySide wrapper. The GUI thread can therefore sit
half-way through tearing a widget tree down (``QWidget::~QWidget`` -> ``Shiboken::Object::destroy``, waiting for the
GIL again) while a worker ``QThread`` runs Python. If that worker's allocations trigger a collection, the collector
walks wrappers that are being destroyed and segfaults in ``gc_collect_main -> visit_decref -> libshiboken6``. Core
dump 3258852 (the updater's check thread, during ``tests/ui/test_ui_update.py``) shows exactly this: the worker
inside ``_Py_HandlePending -> gc_collect_main`` and the GUI thread blocked in ``PyGILState_Ensure`` under
``QWidget::~QWidget``.

The fix is to make sure no thread but the GUI thread ever starts a collection: automatic collection is switched off
and a ``QTimer`` that lives on the GUI thread calls ``gc.collect()`` every couple of seconds. Reference counting still
frees everything that is not in a cycle at once; cycles are collected a little later, from a timer callback, where
the GUI thread is not in the middle of a teardown. Both worker threads (the pedal's and the library updater's) are
covered, including the moment between a queued slot's dispatch and its first line.
"""

from __future__ import annotations

import gc

from PySide6.QtCore import QCoreApplication, QTimer

COLLECT_EVERY_MS = 2000

_timer: QTimer | None = None


def install(app: QCoreApplication, interval_ms: int = COLLECT_EVERY_MS) -> QTimer:
    """Disable automatic collection and collect from a GUI-thread timer owned by ``app``; replaces an earlier guard."""
    global _timer
    if _timer is not None:
        _timer.stop()
        _timer.deleteLater()
    gc.disable()
    _timer = QTimer(app)
    _timer.setInterval(interval_ms)
    _timer.timeout.connect(lambda: gc.collect())
    _timer.start()
    return _timer
