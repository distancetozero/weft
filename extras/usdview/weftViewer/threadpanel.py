#
# The "Weft Threads" panel: the d3 thread viewer (viewer_template.html),
# live inside usdview -- a QWebEngineView docked into the main window,
# wired to the open stage over a QWebChannel bridge.
#
# "Open as bounding boxes, materialize geometry as you navigate": the panel
# itself never loads or unloads anything on its own. Every load happens
# because the bridge below was told to -- by a click or a pulled thread in
# the viewer (JS -> Python: `select`/`loaded`), which is exactly the
# gesture a person makes navigating the graph. Run usdview `--unloaded` on
# an ALab scene (see extras/usdview/README.md) and each of those gestures
# is what turns a bounding-box standin into real geometry.
#
# All Qt and QtWebEngine imports are deferred into open_panel() and the
# functions it calls -- never at module import time -- both to keep
# plugin-load cheap (matching weftViewer/__init__.py's existing discipline)
# and because QtWebEngine's availability inside an already-running usdview
# process is exactly the thing this module has to verify defensively: if it
# genuinely cannot initialize, open_panel() reports that through
# `api.PrintStatus` and returns False rather than silently degrading into
# something else.
#
# Qt-free, unit-testable graph logic lives in weft/threadgraph.py -- this
# file is the wiring only.
#
from __future__ import annotations

import json
import os

_VIEWER_TEMPLATE = os.path.join(os.path.dirname(__file__), "viewer_template.html")


def _load_viewer_html(data: dict) -> str:
    with open(_VIEWER_TEMPLATE, "r") as fh:
        tpl = fh.read()
    return tpl.replace("__DATA__", json.dumps(data))


def _guard(api, label, fn):
    """Local copy of weftViewer/__init__.py's `_guard`: wrap a Qt slot (or a
    signal handler connected here) so any exception becomes a PrintStatus
    message, never an uncaught exception inside Qt's event loop. Duplicated
    rather than imported to avoid a circular import between this module and
    the package `__init__.py` that imports it."""
    def wrapped(*args, **kwargs):
        try:
            return fn(*args, **kwargs)
        except Exception as e:
            api.PrintStatus("%s: %s" % (label, e))
    return wrapped


# -- stage-facing operations (guarded; never raise into a Qt slot) ----------

def _select_and_load(api, path):
    """JS -> Python `select(path)`: select `path` in usdview's own
    selection AND materialize it -- `stage.Load` on a prim with a payload
    condenses its bounding-box standin into real geometry; on anything else
    it is a harmless no-op. A facet/concept node id (e.g. "finish:
    translucent", "shading:usd_full") never starts with "/" -- the viewer
    itself already filters those out before calling this, but the guard is
    repeated here since this is also the trust boundary for whatever the
    page sends."""
    if not isinstance(path, str) or not path.startswith("/"):
        return
    prim = api.stage.GetPrimAtPath(path)
    if not prim or not prim.IsValid():
        return
    api.ClearPrimSelection()
    api.AddPrimToSelection(prim)
    api.UpdateGUI()
    _load_one(api, path)


def _load_one(api, path):
    try:
        api.stage.Load(path)
    except Exception as e:
        api.PrintStatus("Weft Threads: load %s failed: %s" % (path, e))


def _load_paths(api, paths):
    """JS -> Python `loaded(paths)`: a thread was pulled / nodes were
    revealed in the viewer -- materialize every one of them that names a
    real, valid prim. Selection is untouched here; only `select` moves the
    live selection."""
    if not isinstance(paths, (list, tuple)):
        return
    for path in paths:
        if not isinstance(path, str) or not path.startswith("/"):
            continue
        prim = api.stage.GetPrimAtPath(path)
        if prim and prim.IsValid():
            _load_one(api, path)


def _make_bridge_class():
    """Built lazily so PySide6.QtCore is never imported at module load
    time. QWebChannel marshals a JS array argument into a Python list for
    a slot declared `@Slot(list)`, and a JS string into `str` for
    `@Slot(str)` -- no manual (de)serialization needed on either side."""
    from PySide6.QtCore import QObject, Signal, Slot

    class ThreadPanelBridge(QObject):
        # Python -> JS: usdview's own prim selection changed; the panel
        # focuses (and reveals, if not already visible) the matching node.
        focusPrim = Signal(str)

        def __init__(self, api, parent=None):
            super().__init__(parent)
            self._api = api

        @Slot(str)
        def select(self, path):
            try:
                _select_and_load(self._api, path)
            except Exception as e:
                self._api.PrintStatus("Weft Threads: select(%r) failed: %s" % (path, e))

        @Slot(list)
        def loaded(self, paths):
            try:
                _load_paths(self._api, paths)
            except Exception as e:
                self._api.PrintStatus("Weft Threads: loaded(...) failed: %s" % e)

    return ThreadPanelBridge


def _wire_stage_selection(container, api, bridge):
    """Stage -> JS: connect usdview's own selection-changed signal so
    selecting a prim in the tree/viewport focuses the matching node in the
    panel. Best-effort, exactly as the brief allows: if the signal isn't
    reachable off `api.dataModel.selection`, the panel still works
    viewer -> stage, just not the other way, and that is reported (once)
    rather than silently swallowed."""
    try:
        selection = api.dataModel.selection
    except Exception as e:
        api.PrintStatus(
            "Weft Threads: stage -> viewer selection sync unavailable (%s); "
            "viewer -> stage still works" % e)
        return

    def _on_changed(added, _removed):
        if not added:
            return
        try:
            path = sorted(str(p) for p in added)[0]
        except Exception:
            return
        bridge.focusPrim.emit(path)

    handler = _guard(api, "Weft Threads", _on_changed)
    try:
        selection.signalPrimSelectionChanged.connect(handler)
    except Exception as e:
        api.PrintStatus(
            "Weft Threads: stage -> viewer selection sync unavailable (%s); "
            "viewer -> stage still works" % e)
        return
    # Held on the container so neither the connection nor its closure is
    # garbage-collected out from under Qt while the dock is alive.
    container._threadSelection = (selection, handler)


# -- panel lifecycle ----------------------------------------------------

def open_panel(container, api):
    """Create (first call) or raise (subsequent calls) the "Weft Threads"
    dock. Returns True once the panel is showing; on any failure -- most
    importantly QtWebEngine failing to initialize inside usdview's own
    QApplication -- reports the exact error through `api.PrintStatus` and
    returns False. Never falls back to something else silently."""
    if getattr(container, "_threadDock", None) is not None:
        container._threadDock.show()
        container._threadDock.raise_()
        return True

    try:
        from PySide6.QtCore import Qt
        from PySide6.QtWebChannel import QWebChannel
        from PySide6.QtWebEngineWidgets import QWebEngineView
        from PySide6.QtWidgets import QDockWidget
    except ImportError as e:
        api.PrintStatus(
            "Weft Threads: BLOCKED -- QtWebEngine is not importable in this "
            "usdview process (%s)" % e)
        return False

    try:
        from weft.threadgraph import build_graph
        data = build_graph(api.stage)
    except Exception as e:
        api.PrintStatus("Weft Threads: build_graph failed, opening an empty panel: %s" % e)
        data = {"nodes": [], "edges": [], "kinds": []}

    try:
        html = _load_viewer_html(data)
    except OSError as e:
        api.PrintStatus("Weft Threads: could not read viewer_template.html: %s" % e)
        return False

    try:
        view = QWebEngineView()
        bridge_cls = _make_bridge_class()
        bridge = bridge_cls(api)
        channel = QWebChannel()
        channel.registerObject("bridge", bridge)
        view.page().setWebChannel(channel)
        view.setHtml(html)
    except Exception as e:
        api.PrintStatus("Weft Threads: BLOCKED -- QtWebEngine failed to initialize "
                         "inside usdview (%s)" % e)
        return False

    dock = QDockWidget("Weft Threads", api.qMainWindow)
    dock.setWidget(view)
    api.qMainWindow.addDockWidget(Qt.RightDockWidgetArea, dock)
    dock.show()
    dock.raise_()

    # Held on the container (the WeftViewerContainer instance, which
    # outlives this call) so PySide doesn't garbage-collect the bridge or
    # channel out from under the page's live JS <-> Python connection.
    container._threadDock = dock
    container._threadView = view
    container._threadBridge = bridge
    container._threadChannel = channel

    _wire_stage_selection(container, api, bridge)

    api.PrintStatus("Weft Threads: panel open (%d nodes, %d edges)"
                     % (len(data.get("nodes", [])), len(data.get("edges", []))))
    return True
