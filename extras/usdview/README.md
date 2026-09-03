# weft's usdview plugin

A `Weft` menu inside usdview, backed by `weftViewer/` (see that package's
own docstrings for the command-by-command detail):

- **Ask...** -- resolve a `weft ask` against the *live* open stage and
  select the results.
- **Solo threads** -- pull the selection's threads and view-solo (author a
  session-layer deactivation on) everything else.
- **Restore world** -- reactivate whatever Solo threads deactivated.
- **Who depends on this?** -- incoming edges onto the selection.
- **Weft Threads...** -- the live thread-graph panel: a dockable, NATIVE
  Qt view (`QGraphicsView`/`QGraphicsScene` -- no QtWebEngine, no
  QWebChannel, no Chromium) drawing the hierarchy graph, one ring at a
  time. Pan by dragging empty canvas, zoom with the scroll wheel. Click a
  node: it selects the matching prim in usdview AND materializes it
  (`stage.Load(path)`), AND toggles its children open/closed -- an
  unexpanded node with children shows a small `+` badge. A "⌂ Home" button
  resets to `/root` + its first ring and refits the view. See
  `weftViewer/threadpanel.py` for the scene building, the click ->
  select+load -> expand/collapse pipeline (`_GraphController`), and the
  pan/zoom view (`_GraphView`); `weft/threadgraph.py` for the pure
  graph-building logic it renders. (An earlier version embedded weft's
  tuned d3 thread viewer in a `QWebEngineView`; that crashed the real
  usdview GUI on macOS -- confirmed by direct interactive testing, not
  just headless. A first native-Qt cut fixed the crash but rendered the
  ENTIRE hierarchy statically at once, which was unusable -- "not
  interactive feeling ... very hard to use." This revision ports the
  actual pan/zoom/expand-on-demand interaction model from the d3 viewer.
  See `.superpowers/threadpanel-report.md` for the full investigation. The
  d3 viewer itself, and its richer lens/ask-bar model, still lives in
  `weftViewer/viewer_template.html` as a standalone browser demo -- just
  not embedded live in usdview anymore.)

## Making the plugin discoverable

usdview finds it two separate ways, both required:

```sh
export PXR_PLUGINPATH_NAME=/path/to/weft/extras/usdview   # discovery: plugInfo.json
export PYTHONPATH=/path/to/weft:/path/to/weft/extras/usdview:$PYTHONPATH  # import: weftViewer/
```

## The "bounding boxes that condense into geometry as you navigate" experience

This is Weft Threads' whole point on an ALab-scale scene: open with payloads
**unloaded** (bounding-box standins) and let the panel materialize real
geometry only for what you actually click or pull -- pull the thread,
don't load the world, all the way down to the render.

```sh
usdview --unloaded --bboxStandin \
  /path/to/ALab/entity/lab_workbench01/lab_workbench01.usda
```

Then **Weft ▸ Weft Threads...** opens the panel showing just `/root` and its
first ring (the scene's top-level groups) -- NOT the whole tree. Click a
group: it expands to show its own children (a "+" badge marks any node with
more to reveal), and every newly-revealed prim gets `stage.Load()`ed the
same way a direct click does -- pull the thread, don't load the world, for
the graph itself now too, not just the geometry. Click an already-expanded
node to collapse its subtree back down. Drag empty canvas to pan, scroll to
zoom, "⌂ Home" to reset. (This cut is the hierarchy lens only -- the d3
viewer's Mount/finish/shading lenses, the weft-ask seed bar, and true
mental-map-preserving incremental layout are follow-up work; see
`weftViewer/threadpanel.py`'s module docstring.)

`--unloaded` is what makes the payload-bearing prims start as bounding
boxes in the first place; `--bboxStandin` is what draws them as boxes
rather than nothing. Both are ordinary usdview flags -- the panel itself
never changes usdview's own load policy, it only calls `stage.Load()` on
the prims a click or a pull names.

## Verification

- `weft/threadgraph.py`'s `build_graph()` is pure (no Qt) and unit-tested
  in `tests/test_threadgraph.py`, including an acceptance test against the
  real ALab workbench gated on `WEFT_ALAB`/`JITSD_ALAB`, and a regression
  test that it returns the identical graph whether the stage was opened
  loaded or with `--unloaded` (payload-unloaded prims still have to be
  walked to build the graph in the first place).
- The panel itself (native Qt: `QGraphicsView`/`QGraphicsScene`, the
  click -> select+load -> expand/collapse controller) needs a running
  usdview process to exercise; it isn't part of the pytest suite. Because
  the earlier QtWebEngine version's crash only reproduced in a REAL
  (non-offscreen, non-`--norender`) usdview process, this panel's own
  smoke test must be run the same way, not headless -- a `testusdview
  --testScript` run that opens with `--unloaded`, opens the panel via the
  same registered command the menu item uses, confirms the initial view is
  small (root + first ring, not the whole tree), drives the controller's
  own `on_node_clicked` exactly as a real mouse click would to expand a
  group, click a revealed child (asserting usdview's own selection moves
  to it), collapse the group back down (asserting its subtree is pruned),
  and reset via Home. See `.superpowers/threadpanel-report.md` for the
  full investigation, the isolation testing that ruled out a simpler
  WebEngine-vs-OpenGL explanation, and the real-GUI verification runs
  across every round.
