# weft's usdview plugin

A `Weft` menu inside usdview, backed by `weftViewer/` (see that package's
own docstrings for the command-by-command detail):

- **Ask...** -- resolve a `weft ask` against the *live* open stage and
  select the results.
- **Solo threads** -- pull the selection's threads and view-solo (author a
  session-layer deactivation on) everything else.
- **Restore world** -- reactivate whatever Solo threads deactivated.
- **Who depends on this?** -- incoming edges onto the selection.
- **Weft Threads...** -- the headline command. Opens weft's tuned d3
  thread viewer in your own **browser**, live-bridged to the open stage:
  click a node to select AND materialize that geometry
  (`stage.Load(path)`) on the real usdview stage, cross-process. See
  "The browser viewer" below.
- **Weft Threads (native panel)...** -- a secondary, in-usdview
  alternative: a dockable native Qt (`QGraphicsView`, no browser, no
  WebEngine) view of the hierarchy graph, pan/zoom + expand-on-demand.
  Kept because it works and some may prefer not opening a browser, but the
  browser viewer above is where weft's fuller lens/ask-bar/inspector
  interaction actually lives -- this panel never reimplemented that. See
  "The native panel" below.

## Making the plugin discoverable

usdview finds it two separate ways, both required:

```sh
export PXR_PLUGINPATH_NAME=/path/to/weft/extras/usdview   # discovery: plugInfo.json
export PYTHONPATH=/path/to/weft:/path/to/weft/extras/usdview:$PYTHONPATH  # import: weftViewer/
```

## The browser viewer (headline command)

`Weft ▸ Weft Threads...` starts a local HTTP bridge server and opens your
browser to `weft-viewer.html` -- the same polished d3 thread viewer as
always (lens selector, weft-ask bar, inspector, back/home, label
declutter), unchanged, now reading and writing the LIVE usdview stage over
that bridge instead of running as a static export. Click a node: it
selects the matching prim in usdview's own tree/viewport and, if it has a
payload, its bounding-box standin condenses into real geometry -- pull the
thread, don't load the world, all the way down to the render, from a real
browser tab.

### Why a separate browser window

An earlier version embedded the d3 viewer directly in usdview via
`QWebEngineView`; that crashed the real usdview GUI on macOS (Chromium's
own compositor fighting usdview's OpenGL-composited main window),
confirmed by direct interactive testing, not just headless. A native-Qt
rebuild (`QGraphicsView`, no WebEngine) fixed the crash but couldn't
reproduce the d3 viewer's own richer interaction without reimplementing
all of it from scratch in Qt. Running the already-built, already-liked
viewer in its native habitat -- a real browser, a separate OS process --
with usdview as a live data source over plain HTTP sidesteps both
problems at once: no Chromium-in-usdview's-window conflict (there's no
Chromium in usdview's process at all now), and no UI to rebuild. See
`.superpowers/threadpanel-report.md` for the full investigation across
every round that led here.

### Security

This is a real local HTTP server, treated accordingly (see
`weftViewer/bridgeserver.py`'s own module docstring for the complete
reasoning):

- Bound to **127.0.0.1 only** (never `0.0.0.0`), an OS-assigned ephemeral
  port -- not reachable from another machine, and nothing to port-scan for
  on this one beyond "some local process has some loopback port open."
- A random per-session token (`secrets.token_urlsafe(32)`) is required
  (query param `?t=` or an `X-Weft-Token` header, compared with
  `hmac.compare_digest`) on every page load and every API call; a missing
  or wrong token gets a bare 403, before any USD stage access happens.
  This is what stops another local process, or a stray browser tab left
  over from a previous session, from talking to the bridge.
- Exactly four routes exist, all hardcoded string comparisons -- there is
  no dynamic filesystem-path-to-file mapping anywhere in the server, so
  there is no path-traversal surface to have a bug in.
- `d3.min.js` is vendored into `weftViewer/assets/` and served locally;
  the Google Fonts `<link>` is dropped entirely for the live-served page
  (the CSS already declares a solid system-font fallback, so this is a
  clean removal, not a broken one). The served page makes **zero external
  network calls**.
- The server shuts down via `atexit`, registered the moment it starts.

### Threading

`stage.Load()`, selection changes, and even read-only `build_graph()`
calls only ever run on usdview's own Qt **main thread** -- never on an
HTTP request-handling thread. A `_MainThreadBridge` `QObject`, built on
the main thread, is what a request thread actually calls; it emits a
Qt signal carrying the work plus a `threading.Event`, which becomes a
QUEUED connection automatically (emitter and receiver are on different
threads) so the real work runs on the main thread's own event loop, and
the request thread blocks on the event until it's done. See
`weftViewer/bridgeserver.py`'s module docstring for the complete design
and why this specific approach (not `QTimer.singleShot` from a foreign
thread, not a naive shared-state race) was chosen.

### Endpoints

- `GET /?t=TOKEN` -- the viewer page (a graph snapshot from when the
  server started is embedded for a fast first paint).
- `GET /graph.json?t=TOKEN` -- `build_graph(api.stage)`, rebuilt fresh on
  every call, main-thread-marshaled. Not yet wired into the page's own
  boot sequence (which still uses the embedded snapshot) -- implemented
  and independently verified over real HTTP; a "refresh" affordance in
  the UI is follow-up work, deliberately not added this round to keep the
  diff to "the live bridge," not new UI.
- `GET /assets/d3.min.js` -- the vendored asset; no token required (a
  static, non-sensitive file, hardcoded whitelist).
- `POST /select {"path": "..."}` -- select `path` in usdview AND
  `stage.Load()` it. A facet/concept node id (never starting with `/`) is
  a harmless no-op.
- `POST /load {"paths": [...]}` -- `stage.Load()` every valid path in the
  list; selection untouched.
- Not yet built (explicit follow-up, not silently dropped): a
  stage-selection -> viewer-focus channel (`GET /selection` polling, or a
  push channel) -- the bridge is viewer -> stage only for now.

## The native panel (secondary command)

`Weft ▸ Weft Threads (native panel)...` -- a dockable `QGraphicsView` in
usdview itself, no browser, no WebEngine. Opens showing `/root` + its
first ring only (not the whole tree); click a node to select+materialize
it AND toggle its children open/closed (a `+` badge marks anything with
more to reveal); drag empty canvas to pan, scroll to zoom, "⌂ Home" to
reset. Hierarchy lens only -- no Mount/finish/shading lenses, no weft-ask
bar, no true incremental (position-pinning) layout. See
`weftViewer/threadpanel.py`'s module docstring for the full design.

## The "bounding boxes that condense into geometry as you navigate" experience

This is Weft Threads' whole point on an ALab-scale scene, in either
command: open with payloads **unloaded** (bounding-box standins) and let
the viewer materialize real geometry only for what you actually click --
pull the thread, don't load the world, all the way down to the render.

```sh
usdview --unloaded --bboxStandin \
  /path/to/ALab/entity/lab_workbench01/lab_workbench01.usda
```

`--unloaded` is what makes the payload-bearing prims start as bounding
boxes in the first place; `--bboxStandin` is what draws them as boxes
rather than nothing. Both are ordinary usdview flags -- neither Weft
Threads command ever changes usdview's own load policy; they only call
`stage.Load()` on the prims a click names.

## Verification

- `weft/threadgraph.py`'s `build_graph()` is pure (no Qt) and unit-tested
  in `tests/test_threadgraph.py`, including an acceptance test against the
  real ALab workbench gated on `WEFT_ALAB`/`JITSD_ALAB`, and a regression
  test that it returns the identical graph whether the stage was opened
  loaded or with `--unloaded` (payload-unloaded prims still have to be
  walked to build the graph in the first place).
- Both panels need a running usdview process to exercise; neither is part
  of the pytest suite. Because the earlier QtWebEngine crash only
  reproduced in a REAL (non-offscreen, non-`--norender`) usdview process,
  every smoke test in this tree is run the same way, not headless.
- The browser viewer's own smoke test (`testusdview --testScript`) runs
  the `Weft Threads...` command with `webbrowser.open` mocked out (so an
  automated run doesn't try to pop a real GUI browser window), then talks
  to the real running bridge server over plain HTTP: confirms 403 with no
  or a wrong token on every gated route; confirms a valid-token `GET /`
  serves HTML referencing only the local `/assets/d3.min.js`, never the
  CDN or Google Fonts; confirms `GET /assets/d3.min.js` matches the
  vendored file on disk byte-for-byte; and -- the core mechanic -- POSTs a
  valid-token `/select` for a target prim from a background thread while
  pumping the main thread's own Qt event loop (the only way to exercise
  the queued-signal cross-thread marshal without deadlocking a same-
  process test harness; see `weftViewer/bridgeserver.py`'s docstring),
  and confirms that single HTTP call flips the target's `IsLoaded()`
  False -> True and moves usdview's own selection to it.
- See `.superpowers/threadpanel-report.md` for the full investigation
  across every round -- the WebEngine crash, the isolation testing that
  preceded the native-Qt pivot, the pan/zoom + expand-on-demand pass, and
  this round's browser-bridge build, with every real-GUI run's output.
