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


def pull_leaf(api, path):
    """Double-click PULL on a leaf: select AND materialize exactly this
    leaf (`stage.Load`, default LoadWithDescendants, so a leaf whose own
    geometry sits behind nested payloads actually appears -- never a
    cascade, because only leaves are ever pulled; the JS side routes
    group pulls to re-center-only and never calls this for them)."""
    prim = _valid_prim(api, path)
    if prim is None:
        return
    _select(api, prim)
    load_one(api, path)


def unload_paths(api, paths):
    """The focus moved off a non-pinned leaf: drop its geometry back to a
    bounding-box standin (`stage.Unload`). Selection untouched. Same
    batch/guard shape as load_paths."""
    if not isinstance(paths, (list, tuple)):
        return
    for path in paths:
        if _valid_prim(api, path) is None:
            continue
        try:
            api.stage.Unload(path)
        except Exception as e:
            api.PrintStatus("Weft Threads: unload %s failed: %s" % (path, e))


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
    """A batch of nodes were revealed (an expand in the native panel, or
    POSTed to /load by the browser viewer) -- materialize every one that
    names a real, valid prim. Selection is untouched here; only
    `select_and_load` moves the live selection."""
    if not isinstance(paths, (list, tuple)):
        return
    for path in paths:
        if not isinstance(path, str) or not path.startswith("/"):
            continue
        prim = api.stage.GetPrimAtPath(path)
        if prim and prim.IsValid():
            load_one(api, path)
