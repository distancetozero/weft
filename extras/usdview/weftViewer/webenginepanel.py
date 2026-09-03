#
# The "Weft Threads" panel: the d3 thread viewer (viewer_template.html),
# EMBEDDED live inside usdview -- a QWebEngineView docked into the main
# window, wired to the open stage over an in-process QWebChannel bridge.
# No network, no HTTP server, no token: the whole "trust boundary" is
# "this is usdview's own embedded page," nothing else talks to it.
#
# ROUND 6. History, briefly (full detail in
# .superpowers/threadpanel-report.md): round 1 built exactly this --
# QWebEngineView + QWebChannel -- and it crashed the real usdview GUI on
# macOS (exit 139) the moment the panel was opened, confirmed by the owner
# testing the actual interactive GUI directly. Rounds 3-4 replaced it with
# a native QGraphicsView panel (kept in the tree as a secondary command,
# see threadpanel.py) to get something working, but it never reproduced
# the d3 viewer's own lens/ask-bar/inspector interaction. Round 5 tried
# running the d3 viewer in an external browser instead -- the owner
# explicitly rejected that ("i don't like hacking a browser on the user").
# Round 6 (this file) goes back to embedding WebEngine, but fixes the
# ACTUAL root cause instead of working around it: QtWebEngine's Chromium
# compositor needs `Qt.AA_ShareOpenGLContexts` set before usdview's own
# `QApplication` is constructed, which no usdview PLUGIN can do (plugins
# load after that QApplication -- and usdview's whole main window --
# already exist) -- only a LAUNCHER standing in front of usdview's own
# entry point can. See ../weft_usdview.py, which also forces QtWebEngine
# onto CPU compositing (`QTWEBENGINE_CHROMIUM_FLAGS=--disable-gpu`),
# removing the Chromium-Metal-vs-usdview-OpenGL GPU-surface conflict this
# whole crash history traces back to. Launching usdview through that shim
# (see extras/usdview/README.md) is a REQUIREMENT for this panel, not an
# optional nicety -- without it, this is the exact code that crashed
# before.
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
# Qt-free, unit-testable graph logic lives in weft/threadgraph.py; the
# select/load stage-facing operations live in _stagebridge.py, shared with
# the native panel (threadpanel.py) rather than duplicated here.
#
from __future__ import annotations

import json
import os

from . import _stagebridge

_VIEWER_TEMPLATE = os.path.join(os.path.dirname(__file__), "viewer_template.html")


def _load_viewer_html(data: dict) -> str:
    with open(_VIEWER_TEMPLATE, "r") as fh:
        tpl = fh.read()
    return tpl.replace("__DATA__", json.dumps(data))


def _wire_stage_selection(container, api, bridge):
    """Stage -> JS: connect usdview's own selection-changed signal so
    selecting a prim in the tree/viewport focuses the matching node in the
    panel. Best-effort: if the signal isn't reachable off
    `api.dataModel.selection`, the panel still works viewer -> stage, just
    not the other way, and that is reported (once) rather than silently
    swallowed."""
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

    handler = _stagebridge.guard(api, "Weft Threads", _on_changed)
    try:
        selection.signalPrimSelectionChanged.connect(handler)
    except Exception as e:
        api.PrintStatus(
            "Weft Threads: stage -> viewer selection sync unavailable (%s); "
            "viewer -> stage still works" % e)
        return
    # Held on the container so neither the connection nor its closure is
    # garbage-collected out from under Qt while the dock is alive.
    container._threadWebSelection = (selection, handler)


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
                _stagebridge.select_and_load(self._api, path)
            except Exception as e:
                self._api.PrintStatus("Weft Threads: select(%r) failed: %s" % (path, e))

        @Slot(list)
        def loaded(self, paths):
            try:
                _stagebridge.load_paths(self._api, paths)
            except Exception as e:
                self._api.PrintStatus("Weft Threads: loaded(...) failed: %s" % e)

    return ThreadPanelBridge


# -- panel lifecycle ----------------------------------------------------

def open_panel(container, api):
    """Create (first call) or raise (subsequent calls) the "Weft Threads"
    dock. Returns True once the panel is showing; on any failure -- most
    importantly QtWebEngine failing to initialize inside usdview's own
    process -- reports the exact error through `api.PrintStatus` and
    returns False. Never falls back to something else silently."""
    if getattr(container, "_threadWebDock", None) is not None:
        container._threadWebDock.show()
        container._threadWebDock.raise_()
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
                         "inside usdview (%s). Was usdview launched through "
                         "extras/usdview/weft_usdview.py? A plain `usdview` process "
                         "does not set the OpenGL context sharing this panel needs." % e)
        return False

    dock = QDockWidget("Weft Threads", api.qMainWindow)
    dock.setWidget(view)
    api.qMainWindow.addDockWidget(Qt.RightDockWidgetArea, dock)
    dock.show()
    dock.raise_()

    # Held on the container (the WeftViewerContainer instance, which
    # outlives this call) so PySide doesn't garbage-collect the bridge or
    # channel out from under the page's live JS <-> Python connection.
    container._threadWebDock = dock
    container._threadWebView = view
    container._threadWebBridge = bridge
    container._threadWebChannel = channel

    _wire_stage_selection(container, api, bridge)

    api.PrintStatus("Weft Threads: panel open (%d nodes, %d edges)"
                     % (len(data.get("nodes", [])), len(data.get("edges", []))))
    return True
