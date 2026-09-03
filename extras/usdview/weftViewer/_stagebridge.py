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


def select_and_load(api, path):
    """A node was picked (clicked in the native panel, or POSTed to
    /select by the browser viewer) -> select `path` in usdview's own
    selection AND materialize it: `stage.Load` on a prim with a payload
    condenses its bounding-box standin into real geometry; on anything
    else it is a harmless no-op. A facet/concept node id (e.g.
    "finish:translucent", "shading:usd_full") never starts with "/" --
    guarded here since this is the trust boundary for whatever called in,
    whether that's a Qt click or an HTTP request body."""
    if not isinstance(path, str) or not path.startswith("/"):
        return
    prim = api.stage.GetPrimAtPath(path)
    if not prim or not prim.IsValid():
        return
    api.ClearPrimSelection()
    api.AddPrimToSelection(prim)
    api.UpdateGUI()
    load_one(api, path)


def load_one(api, path):
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
