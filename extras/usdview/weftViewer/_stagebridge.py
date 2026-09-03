#
# Shared, Qt-free stage-facing operations for the Weft Threads panel(s):
# the native QGraphicsView panel (threadpanel.py) and the embedded
# QWebEngineView panel (webenginepanel.py) both need the exact same
# "select+materialize" and "materialize a batch" semantics, so they live
# here once rather than being copy-pasted (and drifting) between the two
# shells. No Qt imports -- every function here just takes a
# usdviewApi-shaped `api` object and plain data; each CALLER is
# responsible for making sure it only runs on usdview's own Qt main
# thread where that matters (both current callers invoke these directly
# from Qt slots already running on the main thread, so this is naturally
# satisfied today -- flagged here for whichever shell adds one next).
#
from __future__ import annotations


def guard(api, label, fn):
    """Wrap a callable (a Qt slot, a signal handler, ...) so any exception
    it raises becomes a PrintStatus message instead of propagating -- the
    same discipline weftViewer/__init__.py's own `_guard` uses; duplicated
    there rather than imported from here to avoid a circular import with
    the package `__init__.py`."""
    def wrapped(*args, **kwargs):
        try:
            return fn(*args, **kwargs)
        except Exception as e:
            api.PrintStatus("%s: %s" % (label, e))
    return wrapped


def _valid_prim(api, path):
    """The shared trust-boundary guard: a prim-like id always starts with
    "/" (facet/concept ids like "finish:translucent" never do), and must
    resolve to a valid prim on the open stage. Returns the prim or None."""
    if not isinstance(path, str) or not path.startswith("/"):
        return None
    prim = api.stage.GetPrimAtPath(path)
    if not prim or not prim.IsValid():
        return None
    return prim


def _select(api, prim):
    api.ClearPrimSelection()
    api.AddPrimToSelection(prim)
    api.UpdateGUI()


def _refresh_viewport(api, frame=False):
    """Make a just-completed stage.Load/Unload VISIBLE in the viewport.

    Under `usdview --bboxStandin` (UsdImagingGL's
    `displayUnloadedPrimsWithBounds`), the imaging scene does NOT resync
    a prim whose load state changes: stage.Load() succeeds, IsLoaded()
    flips, but the viewport keeps drawing the bounding-box standin
    forever. Measured directly (round 9, pixel-level, camera fixed):
    even usdview's OWN outliner-Load refresh path
    (`appController.editComplete` -> `updateView(forceComputeBBox=True)`)
    leaves the render byte-identical (0.24% diff, all of it the HUD
    text), and `SetForceRefresh(True)` changes nothing either; only
    rebuilding the imaging engine (`stageView.closeRenderer()`, then a
    repaint lazily recreating it) makes the loaded geometry appear
    (8.6% of the frame changed = the actual model). This is an upstream
    UsdImagingGL limitation of the bounds-standin mode in USD v26.08,
    not a usdview-plugin problem -- and rebuilding the engine per
    load/unload is the price of a correct picture. Cheap on scenes where
    most prims are unloaded standins (exactly this panel's use case);
    revisit if upstream teaches the standin mode to resync.

    With frame=True, `_frameSelection()` afterwards flies the camera to
    the selection (its updateView(resetCam=True, forceComputeBBox=True)
    also repaints, triggering the lazy engine rebuild). Best-effort on
    private surfaces, reported once if unreachable."""
    try:
        controller = api._UsdviewApi__appController
        view = controller._stageView
        if view is None:
            return
        view.closeRenderer()
        if frame:
            controller._frameSelection()
        else:
            view.updateView(resetCam=False, forceComputeBBox=True)
    except Exception as e:
        if not getattr(api, "_weft_refresh_unavailable", False):
            api._weft_refresh_unavailable = True
            api.PrintStatus(
                "Weft Threads: viewport refresh unavailable (%s); loads/"
                "unloads may not appear until the camera moves" % e)


def peek(api, path):
    """Single-click PEEK (see docs/superpowers/specs/
    2026-09-03-thread-explorer-interaction.md): select the prim in
    usdview and FRAME the camera to it -- a quick look around the current
    focus. Explicitly NO stage.Load: peeking must never materialize
    anything. Framing uses appController._frameSelection() (the same op
    as usdview's own View > Frame Selection); if that private surface
    ever moves, peek degrades to select+highlight -- usdview highlights
    the selected prim's bbox on its own -- reported once, not silently."""
    prim = _valid_prim(api, path)
    if prim is None:
        return
    _select(api, prim)
    try:
        api._UsdviewApi__appController._frameSelection()
    except Exception as e:
        if not getattr(api, "_weft_frame_unavailable", False):
            api._weft_frame_unavailable = True
            api.PrintStatus(
                "Weft Threads: camera framing unavailable (%s); peek "
                "selects/highlights only" % e)


# -- the rule -> set -> load seam ---------------------------------------
#
# Every way of materializing geometry in this panel is a RULE that
# evaluates to a SET of prim paths, and every set goes through the same
# two doors below -- never a bespoke load path per feature:
#
#   load_set(api, paths, frame=)   materialize a set (+ one viewport
#                                  refresh; optional camera framing)
#   pull_set(api, paths)           the set BECOMES the focus's load:
#                                  select it all, materialize it, frame
#                                  the camera to fit it
#   unload_set(api, paths)         drop a set back to bbox standins
#
# Rule kinds so far: a leaf (set = [leaf]), a subtree (set = [root] --
# stage.Load's default LoadWithDescendants carries the recursion), a
# facet (set = the facet's member prims, computed by the viewer from
# the thread graph's weft:bind:* edges). A future rule (spatial,
# frustum, ask-driven...) computes its own path list and calls these
# same functions to get identical load/refresh/framing behaviour.

def load_set(api, paths, frame=False):
    """THE one bulk-materialize door. Loads every valid prim path in the
    set (stage.Load, default LoadWithDescendants per member), then does
    a single viewport refresh -- framing the camera to the current
    selection when frame=True. Selection is untouched here."""
    if not isinstance(paths, (list, tuple)):
        return
    loaded = False
    for path in paths:
        if _valid_prim(api, path) is not None:
            load_one(api, path)
            loaded = True
    if loaded:
        _refresh_viewport(api, frame=frame)


def pull_set(api, paths):
    """A rule's set becomes the current focus's load: select every prim
    in the set (so usdview's own selection shows exactly what the rule
    named), materialize it through load_set, and frame the camera to
    fit the whole set."""
    prims = [p for p in (paths if isinstance(paths, (list, tuple)) else [])
             if _valid_prim(api, p) is not None]
    if not prims:
        return
    api.ClearPrimSelection()
    for p in prims:
        api.AddPrimToSelection(api.stage.GetPrimAtPath(p))
    api.UpdateGUI()
    load_set(api, prims, frame=True)


def unload_set(api, paths):
    """The focus moved off a rule's set (a leaf, a subtree root, a
    facet's members): drop it back to bounding-box standins
    (`stage.Unload`), with one symmetric viewport refresh so the
    geometry visibly condenses back rather than lingering until a
    camera move. Selection untouched."""
    if not isinstance(paths, (list, tuple)):
        return
    unloaded = False
    for path in paths:
        if _valid_prim(api, path) is None:
            continue
        try:
            api.stage.Unload(path)
            unloaded = True
        except Exception as e:
            api.PrintStatus("Weft Threads: unload %s failed: %s" % (path, e))
    if unloaded:
        _refresh_viewport(api)


def pull_leaf(api, path):
    """Double-click PULL on a leaf: rule = this one leaf; set = [leaf]."""
    pull_set(api, [path])


def load_subtree(api, path):
    """"Load all below": rule = everything under this node; set = [node]
    (stage.Load's default LoadWithDescendants carries the recursion)."""
    pull_set(api, [path])


# Compatibility name kept for existing callers; unload_set is canonical.
def unload_paths(api, paths):
    unload_set(api, paths)


def select_and_load(api, path):
    """A node was picked (clicked in the native panel, or POSTed to
    /select by the browser viewer) -> select `path` in usdview's own
    selection AND materialize it: `stage.Load` on a prim with a payload
    condenses its bounding-box standin into real geometry; on anything
    else it is a harmless no-op. A facet/concept node id (e.g.
    "finish:translucent", "shading:usd_full") never starts with "/" --
    guarded here since this is the trust boundary for whatever called in,
    whether that's a Qt click or an HTTP request body."""
    prim = _valid_prim(api, path)
    if prim is None:
        return
    _select(api, prim)
    load_one(api, path)
    _refresh_viewport(api)


def load_one(api, path):
    # A click materializes the picked node AND what hangs off it (a group
    # loads its members' geometry; a leaf loads its own) -- LoadWithDescendants,
    # Stage.Load's default. This is only "pull the thread" and not "load the
    # world" because the panel never auto-loads on open and never auto-loads
    # the pseudo-root: nothing materializes until the user clicks a specific
    # node, and each click loads exactly that node's subtree.
    try:
        api.stage.Load(path)
    except Exception as e:
        api.PrintStatus("Weft Threads: load %s failed: %s" % (path, e))


def load_paths(api, paths):
    """Compatibility name kept for existing callers (the native panel,
    the bridge's pin-load); load_set is canonical."""
    load_set(api, paths)
