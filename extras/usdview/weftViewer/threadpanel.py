#
# The "Weft Threads" panel: a live thread-graph view docked into usdview,
# wired to the open stage -- NATIVE Qt (QGraphicsView/QGraphicsScene), no
# QtWebEngine, no QWebChannel, no Chromium.
#
# History: the first cut of this panel embedded weft's tuned d3 viewer in a
# QWebEngineView. That crashed the real usdview GUI (macOS, exit 139) when
# the panel was opened -- confirmed definitive by the owner testing the
# actual interactive GUI directly. Native Qt replaced it (see
# .superpowers/threadpanel-report.md for the full investigation) and
# SURVIVED real-GUI testing -- but the first native cut rendered the whole
# 149-node hierarchy at once, statically, with no pan/zoom: "not
# interactive feeling ... very hard to use," per the owner's next round of
# testing. This revision ports the actual interaction model -- pan, zoom,
# and expand-on-demand -- from viewer_template.html (the original d3
# viewer's `expand`/`revealChild`/`collapse`/`prune`/`resetToSeed`), not
# just its layout math.
#
# "Open as bounding boxes, materialize geometry as you navigate": the panel
# itself never loads or unloads anything on its own. Every load happens
# because a node click calls into `_select_and_load` below -- the exact
# gesture a person makes navigating the graph, and now only for the ring
# actually revealed, not the whole tree at once.
#
# Scope of this cut (matches the brief): the HIERARCHY lens only -- the
# usd:arc tree from build_graph, revealed one ring at a time starting from
# /root + its first ring, panned/zoomed/re-laid-out as the owner pulls.
# Mount/finish/shading lenses, the weft-ask seed bar, and true
# mental-map-preserving incremental layout (this cut relays out the whole
# VISIBLE subtree on every expand/collapse, not just the new ring) are the
# d3 viewer's own richer model (still reference-able there, and in
# viewer_template.html, which remains valid as a standalone browser demo --
# just no longer embedded live here) and are follow-up work.
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

from . import _stagebridge

_BG = "#17130f"
_INK = "#f0ebe2"
_LINE = "#443b31"
_ACCENT = "#e59a6c"
_TYPE_COLOR = {"group": "#cdb570", "prop": "#e3a06a", "furniture": "#86a6a0"}

_MIN_ZOOM = 0.15
_MAX_ZOOM = 4.0
_ZOOM_STEP = 1.15


def _wire_stage_selection(container, api, on_stage_selection):
    """Stage -> graph: connect usdview's own selection-changed signal so
    selecting a prim in the tree/viewport highlights the matching node in
    the panel (only if it's currently visible -- this does not force an
    expand). Best-effort: if the signal isn't reachable off
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
        on_stage_selection(path)

    handler = _stagebridge.guard(api, "Weft Threads", _on_changed)
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


def _children_map(edges):
    """source -> sorted list of usd:arc targets, over ALL edges (not just
    currently visible ones) -- the full hierarchy adjacency `_GraphController`
    reveals rings from and computes "does this node have anything left to
    expand" against."""
    children = {}
    for e in edges:
        if e.get("kind") != "usd:arc":
            continue
        children.setdefault(e["source"], []).append(e["target"])
    for kids in children.values():
        kids.sort()
    return children


def _tidy_tree_positions(children, visible, root_id="/root", dx=90.0, dy=110.0):
    """A simple tidy-tree layout over the usd:arc subgraph restricted to
    `visible`: each leaf (within `visible`) gets the next slot along the
    sibling axis, each internal node centers over its visible children's
    slots, depth maps to the other axis. Ported in spirit from
    viewer_template.html's `tidyTree()` (which calls d3.tree(), a full
    Reingold-Tilford implementation) -- this is the same idea (recursive
    in-order leaf placement, parent = average of children) without d3's
    contour-based compaction, which is a fine trade for a first native cut:
    it never overlaps siblings, it just isn't always as tight. Called again
    (over the new `visible`) on every expand/collapse -- a full relayout of
    the visible subtree each time, not incremental/position-pinning; also a
    documented, deliberate simplification (see module docstring)."""
    positions = {}
    next_x = [0.0]

    def layout(node_id, depth):
        kids = [k for k in children.get(node_id, []) if k in visible]
        if not kids:
            x = next_x[0]
            next_x[0] += dx
            positions[node_id] = (x, depth * dy)
            return x
        xs = [layout(k, depth + 1) for k in kids]
        x = sum(xs) / len(xs)
        positions[node_id] = (x, depth * dy)
        return x

    if root_id in visible:
        layout(root_id, 0)
    return positions


# -- Qt: view (pan + zoom) ------------------------------------------------

class _GraphView(QtWidgets.QGraphicsView if QtWidgets else object):
    """Drag empty canvas to pan, scroll wheel to zoom to cursor, clamped to
    a sane range. `ScrollHandDrag` only takes over panning when a press
    lands on empty canvas -- a press landing on a `_NodeItem` (which
    accepts the event in its own `mousePressEvent`) still reaches the item
    first; this is standard `QGraphicsView` event propagation, not
    something this class has to arbitrate itself."""

    def __init__(self, scene):
        super().__init__(scene)
        self.setDragMode(QtWidgets.QGraphicsView.ScrollHandDrag)
        self.setTransformationAnchor(QtWidgets.QGraphicsView.AnchorUnderMouse)
        self.setRenderHint(QtGui.QPainter.Antialiasing)
        self._zoom = 1.0

    def wheelEvent(self, event):
        factor = _ZOOM_STEP if event.angleDelta().y() > 0 else 1.0 / _ZOOM_STEP
        new_zoom = self._zoom * factor
        if _MIN_ZOOM <= new_zoom <= _MAX_ZOOM:
            self.scale(factor, factor)
            self._zoom = new_zoom
        event.accept()


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


# -- Qt: the graph controller (holds all interactive state) -----------------

class _GraphController:
    """Everything the panel needs to be a live, navigable graph rather than
    a static dump: which nodes are currently revealed (`visible`), which of
    those have had their children pulled in (`expanded`), the current
    layout (`positions`), and the click -> select+load -> toggle-expand ->
    relayout pipeline. One instance per open panel, held on the
    `WeftViewerContainer` (see `open_panel`) so it (and its scene/items)
    outlive the call that created it."""

    def __init__(self, api, nodes, edges, root_id="/root"):
        self.api = api
        self.root_id = root_id
        self.nodes_by_id = {n["id"]: n for n in nodes}
        self.edges = edges
        self.children = _children_map(edges)

        self.visible = set()
        self.expanded = set()
        self.positions = {}
        self.node_items = {}
        self.highlighted = None

        self.scene = QtWidgets.QGraphicsScene()
        self.scene.setBackgroundBrush(QtGui.QColor(_BG))
        self.view = None  # set by open_panel once the view is constructed

    # -- default / reset view --------------------------------------------

    def initial_view(self):
        """/root + its first ring (its direct usd:arc children) -- matches
        viewer_template.html's own `resetToSeed()` default (no seed ->
        reveal SEED's usd:arc children too). Never the whole tree."""
        self.visible = {self.root_id}
        self.expanded = set()
        self.highlighted = None
        kids = self.children.get(self.root_id, [])
        if kids:
            self.visible.update(kids)
            self.expanded.add(self.root_id)
        self._load_paths(kids)
        self._relayout_and_render()

    def home(self):
        """The Home button: back to the default view, refit the viewport."""
        self.initial_view()
        self._fit()

    def _fit(self):
        if self.view is not None and self.node_items:
            self.view.fitInView(self.scene.itemsBoundingRect(), QtCore.Qt.KeepAspectRatio)

    # -- stage-facing ------------------------------------------------------

    def _load_paths(self, paths):
        _stagebridge.load_paths(self.api, paths)

    def on_stage_selection(self, path):
        """Stage -> graph: highlight the matching node ONLY if it's already
        visible -- this does not force an expand/reveal (kept simple, see
        module docstring's scope note)."""
        if path not in self.node_items:
            return
        self.highlighted = path
        self._apply_highlight_pens()
        if self.view is not None:
            self.view.centerOn(self.node_items[path])

    # -- node click: select+load, then toggle-expand ------------------------

    def on_node_clicked(self, node_id):
        try:
            _stagebridge.select_and_load(self.api, node_id)
        except Exception as e:
            self.api.PrintStatus("Weft Threads: select(%r) failed: %s" % (node_id, e))

        self.highlighted = node_id if node_id in self.nodes_by_id else None

        kids = self.children.get(node_id, [])
        if kids:
            if node_id in self.expanded:
                self._collapse(node_id)
            else:
                self._expand(node_id)

        # Defer the actual scene rebuild: this runs from INSIDE the clicked
        # item's own mousePressEvent, and _render() below calls
        # scene.clear(), which would delete that very item mid-event -- a
        # classic Qt use-after-free / crash risk. QTimer.singleShot(0, ...)
        # runs the rebuild on the next event-loop turn instead, once the
        # item's own event has finished being handled.
        self._pending_focus = node_id
        QtCore.QTimer.singleShot(0, self._relayout_render_and_focus)

    def _expand(self, node_id):
        kids = self.children.get(node_id, [])
        newly_revealed = [k for k in kids if k not in self.visible]
        self.visible.update(kids)
        self.expanded.add(node_id)
        # Only the newly revealed ring is loaded -- "pull the thread, don't
        # load the world," now true for the GRAPH as well as the geometry.
        self._load_paths(newly_revealed)

    def _collapse(self, node_id):
        """Prunes node_id's entire subtree (not node_id itself) out of
        `visible`/`expanded` -- ported from viewer_template.html's
        `collapse()`+`prune()`."""
        to_remove = set()
        stack = list(self.children.get(node_id, []))
        while stack:
            c = stack.pop()
            if c in to_remove:
                continue
            to_remove.add(c)
            stack.extend(self.children.get(c, []))
        self.visible -= to_remove
        self.expanded -= to_remove
        self.expanded.discard(node_id)
        if self.highlighted in to_remove:
            self.highlighted = None

    def _relayout_render_and_focus(self):
        self._relayout_and_render()
        item = self.node_items.get(self._pending_focus)
        if item is not None and self.view is not None:
            self.view.centerOn(item)

    # -- layout + render -----------------------------------------------

    def _relayout_and_render(self):
        self.positions = _tidy_tree_positions(self.children, self.visible, self.root_id)
        self._render()

    def _render(self):
        self.scene.clear()
        self.node_items = {}

        line_pen = _pen(_LINE, 1.2)
        for e in self.edges:
            if e.get("kind") != "usd:arc":
                continue
            s, t = e.get("source"), e.get("target")
            if s not in self.positions or t not in self.positions:
                continue
            sx, sy = self.positions[s]
            tx, ty = self.positions[t]
            self.scene.addLine(sx, sy, tx, ty, line_pen)

        for node_id, (x, y) in self.positions.items():
            node = self.nodes_by_id.get(node_id)
            if node is None:
                continue
            radius = 9 if node.get("type") == "group" else 6
            color = _TYPE_COLOR.get(node.get("type"), "#aaaaaa")

            item = _NodeItem(node_id, radius, self.on_node_clicked)
            item.setBrush(QtGui.QBrush(QtGui.QColor(color)))
            item.setPos(x, y)
            item.setZValue(1)
            self.scene.addItem(item)
            self.node_items[node_id] = item

            label = QtWidgets.QGraphicsSimpleTextItem(node.get("label", node_id))
            label.setBrush(QtGui.QBrush(QtGui.QColor(_INK)))
            font = label.font()
            font.setPointSize(8)
            label.setFont(font)
            label.setPos(x + radius + 4, y - 8)
            label.setZValue(1)
            self.scene.addItem(label)

            # Disclosure badge: "+" when this node has usd:arc children that
            # are NOT all currently visible -- ported from
            # viewer_template.html's own badge (`hasUnexpanded`).
            kids = self.children.get(node_id, [])
            if kids and any(k not in self.visible for k in kids):
                badge = QtWidgets.QGraphicsSimpleTextItem("+")
                badge.setBrush(QtGui.QBrush(QtGui.QColor(_ACCENT)))
                bfont = badge.font()
                bfont.setPointSize(8)
                bfont.setBold(True)
                badge.setFont(bfont)
                badge.setPos(x + radius - 2, y - radius - 12)
                badge.setZValue(2)
                self.scene.addItem(badge)

        self._apply_highlight_pens()

    def _apply_highlight_pens(self):
        for node_id, item in self.node_items.items():
            item.setPen(_pen(_ACCENT, 3) if node_id == self.highlighted else _pen(_BG, 1.6))


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
        controller = _GraphController(api, nodes, edges)
        view = _GraphView(controller.scene)
        controller.view = view
        controller.initial_view()
        controller._fit()
    except Exception as e:
        api.PrintStatus("Weft Threads: failed to build the graph view: %s" % e)
        return False

    home_button = QtWidgets.QPushButton("⌂ Home")
    home_button.setToolTip("Back to /root + its first ring, refit the view")
    home_button.clicked.connect(_stagebridge.guard(api, "Weft Threads", lambda: (
        controller.home())))

    toolbar = QtWidgets.QHBoxLayout()
    toolbar.addWidget(home_button)
    toolbar.addStretch(1)

    panel_widget = QtWidgets.QWidget()
    panel_layout = QtWidgets.QVBoxLayout(panel_widget)
    panel_layout.setContentsMargins(4, 4, 4, 4)
    panel_layout.addLayout(toolbar)
    panel_layout.addWidget(view)

    dock = QtWidgets.QDockWidget("Weft Threads", api.qMainWindow)
    dock.setWidget(panel_widget)
    api.qMainWindow.addDockWidget(QtCore.Qt.RightDockWidgetArea, dock)
    dock.show()
    dock.raise_()

    # Held on the container (the WeftViewerContainer instance, which
    # outlives this call) so PySide doesn't garbage-collect the controller,
    # its scene, or its items out from under the dock.
    container._threadDock = dock
    container._threadView = view
    container._threadScene = controller.scene
    container._threadController = controller

    _wire_stage_selection(container, api, controller.on_stage_selection)

    api.PrintStatus("Weft Threads: panel open (%d nodes visible)" % len(controller.visible))
    return True
