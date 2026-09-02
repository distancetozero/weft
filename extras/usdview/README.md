# weft's usdview plugin

A `Weft` menu inside usdview, backed by `weftViewer/` (see that package's
own docstrings for the command-by-command detail):

- **Ask...** -- resolve a `weft ask` against the *live* open stage and
  select the results.
- **Solo threads** -- pull the selection's threads and view-solo (author a
  session-layer deactivation on) everything else.
- **Restore world** -- reactivate whatever Solo threads deactivated.
- **Who depends on this?** -- incoming edges onto the selection.
- **Weft Threads...** -- the live thread-graph panel: a dockable
  `QWebEngineView` running weft's d3 thread viewer, wired to the open stage
  over `QWebChannel`. Clicking or pulling a thread in the graph selects
  the matching prim in usdview AND materializes it (`stage.Load(path)`).
  See `weftViewer/threadpanel.py` for the bridge, and
  `weft/threadgraph.py` for the pure graph-building logic it renders.

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

Then **Weft ▸ Weft Threads...** opens the panel. Click any prop, furniture,
group, or facet node: the matching prim (if it names one -- facet/concept
nodes like `finish:translucent` have none) is selected in usdview's own
tree/viewport and, if it has a payload, its bounding-box standin condenses
into real geometry. Pulling a thread (or the group children a lens reveals)
materializes every node it adds the same way.

`--unloaded` is what makes the payload-bearing prims start as bounding
boxes in the first place; `--bboxStandin` is what draws them as boxes
rather than nothing. Both are ordinary usdview flags -- the panel itself
never changes usdview's own load policy, it only calls `stage.Load()` on
the prims a click or a pull names.

## Verification

- `weft/threadgraph.py`'s `build_graph()` is pure (no Qt) and unit-tested
  in `tests/test_threadgraph.py`, including an acceptance test against the
  real ALab workbench gated on `WEFT_ALAB`/`JITSD_ALAB`.
- The panel itself (Qt + QtWebEngine + the QWebChannel bridge) needs a
  running usdview process to exercise; it isn't part of the pytest suite.
  A `testusdview --testScript` smoke run is the way to check it -- open
  with `--unloaded`, open the panel via the same registered command the
  menu item uses, then call the bridge's `select()`/`loaded()` exactly as
  the JS side would and assert `IsLoaded()` flips. See
  `.superpowers/threadpanel-report.md` for a worked example and its
  output.
