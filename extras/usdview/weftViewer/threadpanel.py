#
# The "Weft Threads" panel: a live thread-graph view docked into usdview,
# wired to the open stage -- NATIVE Qt (QGraphicsView/QGraphicsScene), no
# QtWebEngine, no QWebChannel, no Chromium.
#
# History: the first cut of this panel embedded weft's tuned d3 viewer in a
# QWebEngineView. That crashed the real usdview GUI (macOS, exit 139) when
# the panel was opened -- confirmed definitive by the owner testing the
# actual interactive GUI directly (usdview launches and the rest of the
# Weft menu works fine; only opening this panel crashed it). A separate
# top-level WebEngine window was tried as a fix and also found unreliable
# in isolation testing (see .superpowers/threadpanel-report.md for the full
# investigation). Decision: drop WebEngine entirely. A QGraphicsView uses
# no separate GPU compositor of its own -- it paints through the same
# QWidget/QPainter stack usdview's rest of the UI already uses -- so it
# coexists with usdview's own OpenGL-composited Storm viewport instead of
# fighting it for a native surface.
#
# "Open as bounding boxes, materialize geometry as you navigate": the panel
# itself never loads or unloads anything on its own. Every load happens
# because a node click calls into `_select_and_load` below -- the exact
# gesture a person makes navigating the graph. Run usdview `--unloaded` on
# an ALab scene (see extras/usdview/README.md) and that gesture is what
# turns a bounding-box standin into real geometry.
#
# Scope of this cut (first native version, matches the brief): the
# HIERARCHY lens only -- the full usd:arc tree from build_graph, laid out
# with a simple tidy-tree algorithm ported from viewer_template.html's d3
# layout, rendered once when the panel opens. Mount/finish/shading lenses,
# progressive pull/expand, and the weft-ask seed bar are the d3 viewer's
# own richer interaction model (still reference-able there, and in
# viewer_template.html, which remains valid as a standalone browser demo --
# just no longer embedded live here) and are follow-up work once this
# native shell is proven not to crash.
#
# Qt is imported the same way weftViewer/__init__.py imports it --
# `pxr.Usdviewq.qt`, which picks whatever PySide/PyQt binding usdview
# itself is running on -- not raw PySide6. Unlike the old QtWebEngine
# import, this one is cheap and carries none of Chromium's initialization
# risk, so it is safe at module import time (matching __init__.py's own
# top-level Qt import, guarded the same way for the case this module is
# ever imported outside a running usdview).
#
# Qt-free, unit-testable graph logic lives in weft/threadgraph.py -- this
# file is the wiring only.
#
from __future__ import annotations

import sys

try:
    from pxr.Usdviewq.qt import QtCore, QtGui, QtWidgets
except ImportError as _e:
    print("weftViewer.threadpanel: pxr.Usdviewq.qt unavailable (%s); the Weft "
          "Threads panel cannot be built outside usdview" % _e, file=sys.stderr)
    QtCore = QtGui = QtWidgets = None

_BG = "#17130f"
_INK = "#f0ebe2"
_LINE = "#443b31"
_ACCENT = "#e59a6c"
_TYPE_COLOR = {"group": "#cdb570", "prop": "#e3a06a", "furniture": "#86a6a0"}


def _guard(api, label, fn):
    """Wrap a Qt slot (or a signal handler connected here) so any exception
    becomes a PrintStatus message, never an uncaught exception inside Qt's
    event loop. Same discipline as weftViewer/__init__.py's own `_guard`;
    duplicated rather than imported to avoid a circular import."""
    def wrapped(*args, **kwargs):
        try:
            return fn(*args, **kwargs)
        except Exception as e:
            api.PrintStatus("%s: %s" % (label, e))
    return wrapped


# -- stage-facing operations (guarded; never raise into a Qt slot) ----------

def _select_and_load(api, path):
    """Node click -> select `path` in usdview's own selection AND
    materialize it: `stage.Load` on a prim with a payload condenses its
    bounding-box standin into real geometry; on anything else it is a
    harmless no-op. Only usd:arc hierarchy nodes are ever rendered in this
    cut, so every node id is a real prim path -- but the leading-"/" guard
    is kept anyway since a future facet/concept node (finish:/shading:,
    never starting with "/") would reuse this same callback."""
    if not isinstance(path, str) or not path.startswith("/"):
        return
    prim = api.stage.GetPrimAtPath(path)
    if not prim or not prim.IsValid():
        return
    api.ClearPrimSelection()
    api.AddPrimToSelection(prim)
    api.UpdateGUI()
    try:
        api.stage.Load(path)
    except Exception as e:
        api.PrintStatus("Weft Threads: load %s failed: %s" % (path, e))


def _wire_stage_selection(container, api, apply_highlight):
    """Stage -> graph: connect usdview's own selection-changed signal so
    selecting a prim in the tree/viewport highlights the matching node in
    the panel. Best-effort: if the signal isn't reachable off
    `api.dataModel`, the panel still works graph -> stage, just not the
    other way, and that is reported once rather than silently swallowed."""
    try:
        selection = api.dataModel.selection
    except Exception as e:
        api.PrintStatus(
            "Weft Threads: stage -> graph selection sync unavailable (%s); "
            "graph -> stage still works" % e)
        return

    def _on_changed(added, _removed):
        if not added:
            return
        try:
            path = sorted(str(p) for p in added)[0]
        except Exception:
            return
        apply_highlight(path)

    handler = _guard(api, "Weft Threads", _on_changed)
    try:
        selection.signalPrimSelectionChanged.connect(handler)
    except Exception as e:
        api.PrintStatus(
            "Weft Threads: stage -> graph selection sync unavailable (%s); "
            "graph -> stage still works" % e)
        return
    # Held on the container so neither the connection nor its closure is
    # garbage-collected out from under Qt while the dock is alive.
    container._threadSelection = (selection, handler)


# -- graph shaping (pure-ish: dict/list in, no Qt) ---------------------------

def _synthesize_root(data):
    """Mirrors viewer_template.html's own `DATA.nodes.push({id:"/root",...})`
    step: build_graph never emits a /root node or its edges to each group
    (see weft/threadgraph.py's own docstring on this) -- the renderer adds
    both, exactly as the d3 viewer did, so "nothing selected" still shows
    a real tree rooted at /root."""
    nodes = list(data.get("nodes", []))
    edges = list(data.get("edges", []))
    ids = {n["id"] for n in nodes}
    if "/root" not in ids:
        nodes.append({"id": "/root", "label": "root", "type": "group"})
    for n in nodes:
        if n.get("type") == "group" and n["id"] != "/root":
            edges.append({"source": "/root", "target": n["id"], "kind": "usd:arc"})
    return nodes, edges


def _tidy_tree_positions(nodes, edges, root_id="/root", dx=90.0, dy=110.0):
    """A simple tidy-tree layout over the usd:arc-only subgraph: each leaf
    gets the next slot along the sibling axis, each internal node centers
    over its children's slots, depth maps to the other axis. Ported in
    spirit from viewer_template.html's `tidyTree()` (which calls d3.tree(),
    a full Reingold-Tilford implementation) -- this is the same idea
    (recursive in-order leaf placement, parent = average of children)
    without d3's contour-based compaction, which is a fine trade for a
    first native cut: it never overlaps siblings, it just isn't always as
    tight. Nodes unreachable from `root_id` via usd:arc edges (there
    shouldn't be any -- see threadgraph.py -- but if there are, e.g. a
    malformed stage) simply get no position and are skipped by the caller,
    same as `edges.append` skips edges whose endpoints have none."""
    children = {}
    for e in edges:
        if e.get("kind") != "usd:arc":
            continue
        children.setdefault(e["source"], []).append(e["target"])
    for kids in children.values():
        kids.sort()

    positions = {}
    next_x = [0.0]

    def layout(node_id, depth):
        kids = children.get(node_id, [])
        if not kids:
            x = next_x[0]
            next_x[0] += dx
            positions[node_id] = (x, depth * dy)
            return x
        xs = [layout(k, depth + 1) for k in kids]
        x = sum(xs) / len(xs)
        positions[node_id] = (x, depth * dy)
        return x

    node_ids = {n["id"] for n in nodes}
    if root_id in node_ids:
        layout(root_id, 0)
    return positions


# -- Qt scene building --------------------------------------------------

class _NodeItem(QtWidgets.QGraphicsEllipseItem if QtWidgets else object):
    """A hierarchy node: an ellipse that knows its own prim path and calls
    back into Python on click. This IS the entire "bridge" now -- no
    QWebChannel, no JS round-trip, just a Qt mouse event calling a Python
    closure directly."""

    def __init__(self, node_id, radius, on_click):
        super().__init__(-radius, -radius, 2 * radius, 2 * radius)
        self._node_id = node_id
        self._on_click = on_click
        self.setAcceptHoverEvents(True)
        self.setCursor(QtCore.Qt.PointingHandCursor)
        self.setToolTip(node_id)

    def mousePressEvent(self, event):
        self._on_click(self._node_id)
        super().mousePressEvent(event)


def _pen(color, width):
    pen = QtGui.QPen(QtGui.QColor(color))
    pen.setWidthF(width)
    return pen


def _build_scene(nodes, edges, positions, api):
    """Builds the QGraphicsScene for the (already root-synthesized,
    already-positioned) hierarchy graph. Returns (scene, node_items,
    apply_highlight) -- `node_items` maps prim path -> the QGraphicsEllipseItem
    so `_wire_stage_selection` can highlight a node the STAGE selected;
    `apply_highlight` is what a node's own click uses to highlight itself."""
    scene = QtWidgets.QGraphicsScene()
    scene.setBackgroundBrush(QtGui.QColor(_BG))

    line_pen = _pen(_LINE, 1.2)
    for e in edges:
        if e.get("kind") != "usd:arc":
            continue
        s, t = e.get("source"), e.get("target")
        if s not in positions or t not in positions:
            continue
        sx, sy = positions[s]
        tx, ty = positions[t]
        scene.addLine(sx, sy, tx, ty, line_pen)

    node_items = {}
    state = {"highlighted": None}

    def apply_highlight(node_id):
        prev = state.get("highlighted")
        if prev is not None and prev in node_items:
            node_items[prev].setPen(_pen(_BG, 1.6))
        item = node_items.get(node_id)
        if item is not None:
            item.setPen(_pen(_ACCENT, 3))
            state["highlighted"] = node_id
        else:
            state["highlighted"] = None

    def on_click(node_id):
        try:
            _select_and_load(api, node_id)
        except Exception as e:
            api.PrintStatus("Weft Threads: select(%r) failed: %s" % (node_id, e))
        apply_highlight(node_id)

    for node in nodes:
        nid = node.get("id")
        if nid not in positions:
            continue
        x, y = positions[nid]
        radius = 9 if node.get("type") == "group" else 6
        color = _TYPE_COLOR.get(node.get("type"), "#aaaaaa")

        item = _NodeItem(nid, radius, on_click)
        item.setBrush(QtGui.QBrush(QtGui.QColor(color)))
        item.setPen(_pen(_BG, 1.6))
        item.setPos(x, y)
        item.setZValue(1)
        scene.addItem(item)
        node_items[nid] = item

        label = QtWidgets.QGraphicsSimpleTextItem(node.get("label", nid))
        label.setBrush(QtGui.QBrush(QtGui.QColor(_INK)))
        font = label.font()
        font.setPointSize(8)
        label.setFont(font)
        label.setPos(x + radius + 4, y - 8)
        label.setZValue(1)
        scene.addItem(label)

    return scene, node_items, apply_highlight


# -- panel lifecycle ----------------------------------------------------

def open_panel(container, api):
    """Create (first call) or raise (subsequent calls) the "Weft Threads"
    dock. Returns True once the panel is showing; on any failure reports
    the exact error through `api.PrintStatus` and returns False. Never
    falls back to something else silently."""
    if getattr(container, "_threadDock", None) is not None:
        container._threadDock.show()
        container._threadDock.raise_()
        return True

    if QtWidgets is None:
        api.PrintStatus("Weft Threads: BLOCKED -- pxr.Usdviewq.qt is unavailable "
                         "in this process")
        return False

    try:
        from weft.threadgraph import build_graph
        data = build_graph(api.stage)
    except Exception as e:
        api.PrintStatus("Weft Threads: build_graph failed, opening an empty panel: %s" % e)
        data = {"nodes": [], "edges": [], "kinds": []}

    try:
        nodes, edges = _synthesize_root(data)
        positions = _tidy_tree_positions(nodes, edges)
        scene, node_items, apply_highlight = _build_scene(nodes, edges, positions, api)
        view = QtWidgets.QGraphicsView(scene)
        view.setRenderHint(QtGui.QPainter.Antialiasing)
        view.setDragMode(QtWidgets.QGraphicsView.ScrollHandDrag)
    except Exception as e:
        api.PrintStatus("Weft Threads: failed to build the graph view: %s" % e)
        return False

    dock = QtWidgets.QDockWidget("Weft Threads", api.qMainWindow)
    dock.setWidget(view)
    api.qMainWindow.addDockWidget(QtCore.Qt.RightDockWidgetArea, dock)
    dock.show()
    dock.raise_()

    # Held on the container (the WeftViewerContainer instance, which
    # outlives this call) so PySide doesn't garbage-collect the scene or
    # its items out from under the dock.
    container._threadDock = dock
    container._threadView = view
    container._threadScene = scene
    container._threadNodeItems = node_items

    _wire_stage_selection(container, api, apply_highlight)

    api.PrintStatus("Weft Threads: panel open (%d hierarchy nodes)" % len(node_items))
    return True
