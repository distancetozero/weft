# weft's usdview plugin

A `Weft` menu inside usdview, backed by `weftViewer/` (see that package's
own docstrings for the command-by-command detail):

- **Ask...** -- resolve a `weft ask` against the *live* open stage and
  select the results.
- **Solo threads** -- pull the selection's threads and view-solo (author a
  session-layer deactivation on) everything else.
- **Restore world** -- reactivate whatever Solo threads deactivated.
- **Who depends on this?** -- incoming edges onto the selection.
- **Weft Threads...** -- the headline command. The full, polished d3
  thread viewer (lens selector, weft-ask bar, inspector, back/home, label
  declutter -- all of it, unchanged), **embedded** in usdview itself as a
  `QWebEngineView` docked into the main window, bridged in-process over
  `QWebChannel`. Click a node: it selects AND materializes that geometry
  (`stage.Load(path)`) on the open stage. **Requires usdview to be
  launched through `weft_usdview.py`** (below) to be VISIBLE -- without
  that launcher the panel opens and works but paints nothing (the crash
  that plagued earlier rounds is fixed in the plugin itself; the launcher
  is about pixels). See `weftViewer/webenginepanel.py`.
- **Weft Threads (native panel)...** -- a secondary, always-available
  fallback: a dockable native Qt (`QGraphicsView`, no WebEngine) view of
  the hierarchy graph, pan/zoom + expand-on-demand. Works with a plain
  `usdview` launch, no shim needed, but doesn't have the embedded viewer's
  fuller interaction. See `weftViewer/threadpanel.py`.

## Making the plugin discoverable

usdview finds it two separate ways, both required:

```sh
export PXR_PLUGINPATH_NAME=/path/to/weft/extras/usdview   # discovery: plugInfo.json
export PYTHONPATH=/path/to/weft:/path/to/weft/extras/usdview:$PYTHONPATH  # import: weftViewer/
```

## Launching for the embedded viewer: `weft_usdview.py`

`Weft ▸ Weft Threads...` embeds a `QWebEngineView` (Chromium) inside
usdview's own OpenGL-composited main window. Two independent macOS
problems had to be separated (the round-7 investigation in
`.superpowers/threadpanel-report.md` has the full evidence):

- **The crash** (exit 139) that plagued earlier rounds turned out to be a
  PySide wrapper-creation re-entrancy bug triggered by usdview's app-wide
  Python event filter meeting events posted to WebEngine's internal C++
  QObjects -- nothing to do with graphics. It is fixed **in the plugin**
  (`webenginepanel.py` removes that filter before creating the view); no
  launcher involved, a plain `usdview` no longer crashes.
- **Painting.** usdview's `QOpenGLWidget` viewport forces the main
  window's backing store onto OpenGL; the `QQuickWidget` that presents
  WebEngine's frames defaults to Metal on macOS and refuses the mismatch
  ("Failed to get a QRhi..."), leaving the panel alive but invisible.
  Matching them needs `QSG_RHI_BACKEND=opengl` and
  `Qt.AA_ShareOpenGLContexts` set BEFORE usdview's own `QApplication` is
  constructed -- which no usdview PLUGIN can do (usdview builds its
  `QApplication` deep inside its own `Launcher.Run()`, well before any
  plugin gets a chance to run code). A launcher, run in PLACE of the
  `usdview` binary, can:

```sh
export PXR_PLUGINPATH_NAME=/path/to/weft/extras/usdview
export PYTHONPATH=/path/to/weft:/path/to/weft/extras/usdview:$PYTHONPATH

python /path/to/weft/extras/usdview/weft_usdview.py \
  --unloaded --bboxStandin \
  /path/to/ALab/entity/lab_workbench01/lab_workbench01.usda
```

Same arguments as `usdview` itself -- `weft_usdview.py` sets
`QSG_RHI_BACKEND=opengl` (respecting any value already in the
environment) and `Qt.AA_ShareOpenGLContexts`, then calls usdview's own
real entry point (`pxr.Usdviewq.Launcher().Run()`) with `sys.argv`
untouched. See the file's own module docstring for the full reasoning.

**A plain `usdview` process still works fine for everything else** --
`Ask`/`Solo`/`Restore`/`Who`, and the native-panel fallback below -- the
shim is only required for the embedded `Weft Threads...` webview.

One documented trade-off of the crash fix: the first time the embedded
panel is opened in a usdview process, usdview's own app-wide event filter
is removed for the life of that process (it cannot safely coexist with
WebEngine under PySide 6.11 -- see `webenginepanel.py`'s module
docstring). What that filter provided -- focus-follows-mouse and
arrow-key TreeView routing -- is lost from then on; menus, clicking,
explicit focus, and all hotkeys are unaffected. usdview processes that
never open the embedded panel keep stock behavior.

## The "bounding boxes that condense into geometry as you navigate" experience

This is Weft Threads' whole point on an ALab-scale scene, in either
command: open with payloads **unloaded** (bounding-box standins) and let
the viewer materialize real geometry only for what you actually click --
pull the thread, don't load the world, all the way down to the render.
`--unloaded` is what makes the payload-bearing prims start as bounding
boxes in the first place; `--bboxStandin` is what draws them as boxes
rather than nothing. Neither Weft Threads command ever changes usdview's
own load policy; they only call `stage.Load()` on the prims a click names.

## Verification

- `weft/threadgraph.py`'s `build_graph()` is pure (no Qt) and unit-tested
  in `tests/test_threadgraph.py`, including an acceptance test against the
  real ALab workbench gated on `WEFT_ALAB`/`JITSD_ALAB`, and a regression
  test that it returns the identical graph whether the stage was opened
  loaded or with `--unloaded`.
- Both panels need a running usdview process to exercise; neither is part
  of the pytest suite. Because both bugs here ONLY reproduced on a real,
  onscreen, interactively-composited GUI (a headless/scripted harness gave
  false confidence about them before), every smoke test in this tree runs
  a REAL (non-offscreen, non-`--norender`) `testusdview` process, through
  the shim, forces the embedded page to actually finish loading and
  execute its own JS (pumping the event loop past `loadFinished`, then
  `runJavaScript` to read back real values, including the page-side
  QWebChannel handshake and a `notifySelect` that must flip a prim's
  `IsLoaded()`), and pixel-grabs the widget to prove the panel is
  actually PAINTING, not just alive.
- See `.superpowers/threadpanel-report.md` for the full investigation
  across every round -- the original WebEngine crash, the isolation
  testing, the native-Qt pivot, pan/zoom + expand-on-demand, the
  browser-bridge attempt (tried, then dropped when the owner rejected
  popping an external browser), and this round's embedded-webview fix,
  with every real-GUI run's output.
