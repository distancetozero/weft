# The Loom as a Pivot over USD — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Rebuild the Loom around one spine — a filterable, pivotable data table over the stage — with a prim card on click, a live bidirectional expression bar that teaches the slice DSL, and the graph demoted to a summoned view.

**Architecture:** The server stays a thin read-only data source (adds one `/card` endpoint; grouping/filtering/sorting happen client-side over the rows `/data` already returns). `weft/loom/app.html` is rewritten from a four-pane shell into the pivot UI. No new dependencies; no authoring.

**Tech Stack:** Python 3 + `pxr` (USD) for the server; stdlib `ThreadingHTTPServer`; vanilla HTML/CSS/JS (no framework, CSP-safe) for the client; `pytest` (pxr-gated) for server tests; the Claude-in-Chrome tools for browser smoke tests.

**Spec:** `docs/superpowers/specs/2026-10-10-loom-pivot.md` — read it alongside this plan.

## Global Constraints

- **Read-only.** No authoring, no edit target, no overlay. Every endpoint is a thin wrapper over existing weft (`data`, `ask`, `compose`, `pull`, `manifest`, `relkinds`/`kinds`, `threadgraph`).
- **Localhost only.** Server binds `127.0.0.1`. Unchanged.
- **Honest cost tiers.** Cheap dimensions/columns (type, payload, purpose, attr, bbox) never load payloads. Expensive ones (real material binding, point/poly/byte counts) load only after an explicit user confirm — never auto-load.
- **Keep every existing loom test green** (`tests/test_loom.py`: profile / graph / data / query / pull / slice / export) and the full suite (369 passed, 10 skipped at plan time).
- **Run tests/CLI with** `PYTHONPATH=. /Users/ashrafghoniem/weft-demo/env/bin/python` from the worktree root `/Users/ashrafghoniem/.superset/projects/jit-sd/.claude/worktrees/prim-threads`.
- **Branch:** `loom-explore` (already carries today's `__main__` and `_close_dangling` fixes).
- **ALab for browser smoke tests:** `/Users/ashrafghoniem/weft-demo/alab/ALab-2.3.0/ALab/entry.usda`.
- **Commit trailers** on every commit:
  ```
  Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>
  Claude-Session: https://claude.ai/code/session_01LQPSqkEKXofapykZQPLbLv
  ```
- **Grammar growth is out of scope.** `type:` seed and reverse-follow stay unbuilt; the GUI only *surfaces* those gaps as captions (Task 6).

## File Structure

- **Modify** `weft/loom/server.py` — add `LoomState.card(path)` and the `GET /card` route (Task 1). Everything else in it is unchanged.
- **Modify** `weft/loom/app.html` — rewritten incrementally across Tasks 3–7 into the pivot UI. Stays a single self-contained file (inline CSS/JS, CSP-safe), matching the existing pattern.
- **Modify** `tests/test_loom.py` — add `test_card`, `test_card_bad_path`, `test_gui_target_expressions_resolve`, and serving-contract markers per client task.

The authoritative test gate for the JS tasks is the pytest **serving-contract** checks (the markers each task adds to `app.html` are asserted present by the HTTP test) plus a **controller-run browser smoke test** (Task 8). Individual client tasks are verified by their serving check; the controller runs the browser pass once the UI is assembled, because an implementer subagent may not have browser tools.

---

### Task 1: `/card` endpoint — prim-card data (server)

**Files:**
- Modify: `weft/loom/server.py` (add `LoomState.card`, add `/card` route in `do_GET`)
- Test: `tests/test_loom.py`

**Interfaces:**
- Consumes: `data.project(stage, [path], columns=...)` → `Table` with `.names` / `.rows()`; `kinds.discover(stage)` → registry; each registry kind exposes `.edges_for(ctx, prim)` or the project's existing relationship API (confirm against `relkinds.py` before writing — use whatever `threadgraph.build_graph` calls to get a prim's outgoing edges).
- Produces: `LoomState.card(path: str) -> dict` with keys `path, type, payload, bbox_volume, centroid, attrs, relationships`; HTTP `GET /card?path=<path>` returning that dict as JSON, or `{"error": ...}` with code 400 on a bad path.

- [ ] **Step 1: Write the failing test**

Add to `tests/test_loom.py` (the `SCENE` fixture already has `/root/bench/a`, a Mesh with `material:binding:full` and `custom rel electrical:feeds`):

```python
def test_card(ctx):
    from weft.loom import LoomState
    st = LoomState(ctx, load=True)
    c = st.card("/root/bench/a")
    assert c["path"] == "/root/bench/a"
    assert c["type"] == "Mesh"
    kinds = {r["kind"] for r in c["relationships"]}
    targets = {r["target"] for r in c["relationships"]}
    assert any("material:binding" in k for k in kinds)
    assert "/root/bench/mtl/glass" in targets
    assert "electrical:feeds" in kinds            # native rel surfaces too
    assert "/root/bench" in targets


def test_card_bad_path(ctx):
    from weft.loom import LoomState
    st = LoomState(ctx, load=True)
    c = st.card("/does/not/exist")
    assert "error" in c
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `PYTHONPATH=. /Users/ashrafghoniem/weft-demo/env/bin/python -m pytest tests/test_loom.py::test_card tests/test_loom.py::test_card_bad_path -v`
Expected: FAIL (`LoomState` has no attribute `card`).

- [ ] **Step 3: Implement `LoomState.card`**

Add this method to `LoomState` in `weft/loom/server.py`, after `data(...)`. Derive relationships the same way `threadgraph.build_graph` does — find the call it uses to enumerate a prim's edges and reuse it; the sketch below assumes a `relkinds`-style `edges_for(ctx, prim)` yielding `(kind, target_path)`. **Confirm the real API first** and adapt.

```python
def card(self, path: str) -> dict:
    """Everything the prim card shows for one prim: identity + cheap data +
    its authored/derived relationships. Read-only, one prim, no whole-stage
    work. Returns {"error": ...} on a bad path rather than raising."""
    from .. import data as _data
    from ..kinds import discover
    Usd = self._Usd
    prim = self.stage.GetPrimAtPath(path)
    if not prim or not prim.IsValid():
        return {"error": "no prim at %s" % path}
    tbl = _data.project(self.stage, [path],
                        columns=["type", "has_payload", "bbox_volume", "centroid"])
    row = tbl.rows()[0] if tbl.rows() else {}
    attrs = {}
    for a in prim.GetAuthoredAttributes():
        try:
            attrs[a.GetName()] = str(a.Get())
        except Exception:
            pass
    rels = []
    registry = discover(self.stage)
    ctx = _rel_context(self.stage, Usd)   # mirror build_graph's context setup
    for kind in registry:
        for target in kind.edges_for(ctx, prim):   # ADAPT to real API
            rels.append({"kind": kind.id, "target": str(target)})
    for r in prim.GetAuthoredRelationships():       # native rels
        for t in r.GetTargets():
            rels.append({"kind": r.GetName(), "target": str(t)})
    return {
        "path": path,
        "type": prim.GetTypeName() or "",
        "payload": bool(row.get("has_payload")),
        "bbox_volume": row.get("bbox_volume"),
        "centroid": row.get("centroid"),
        "attrs": attrs,
        "relationships": rels,
    }
```

If `build_graph`'s edge enumeration isn't reusable per-prim cleanly, the fallback is: build the slice graph for `path:<path>` (reuse `slice_graph`) and read the edges whose `source == path`. Prefer the direct per-prim call; use the fallback only if the direct API doesn't exist.

- [ ] **Step 4: Add the `/card` route**

In `do_GET`, alongside `/data`:

```python
elif path == "/card":
    self._json(state.card(q.get("path", "")))
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `PYTHONPATH=. /Users/ashrafghoniem/weft-demo/env/bin/python -m pytest tests/test_loom.py -v`
Expected: PASS (new + existing).

- [ ] **Step 6: Commit**

```bash
git add weft/loom/server.py tests/test_loom.py
git commit -m "loom: /card endpoint -- one prim's data + relationships

Thin read-only wrapper: data.project for cheap data + authored attrs +
derived/native relationships for a single prim. Returns {error} on a bad
path, never 500s. Backs the prim card drawer.

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_01LQPSqkEKXofapykZQPLbLv"
```

---

### Task 2: Lock the GUI's expression targets from the Python side

**Files:**
- Test: `tests/test_loom.py`

**Interfaces:**
- Consumes: `compose.parse_expression(expr)` → object with `.seeds`, `.follow`, `.depth`; `pull.pull(context, seeds, follow=, depth=, cache=True)` → `.members`.
- Produces: a test asserting every expression string the GUI will emit (Task 6's mapping) parses and resolves against the fixture — so the client half has a guaranteed-valid target set.

This protects the bidirectional bar: the JS builds these exact strings, and this test proves they're real weft-ask. The JS→string direction is verified in the browser (Task 8); this nails the string→members direction in CI.

- [ ] **Step 1: Write the failing test**

```python
def test_gui_target_expressions_resolve(ctx):
    from weft import compose as _compose, pull as _pull
    st_ctx = ctx
    # every shape the pivot UI emits (Task 6 mapping) must be valid weft-ask
    exprs = [
        "path:/root/bench/a",
        "name:a",
        "name:a*",
        "where:bbox_volume>0",
        "where:bbox_volume>=0",
    ]
    for e in exprs:
        parsed = _compose.parse_expression(e)
        p = _pull.pull(st_ctx, parsed.seeds, follow=parsed.follow,
                       depth=parsed.depth, cache=False)
        assert p is not None            # parses and resolves, no raise
    # the facet form reads any authored attr; fixture mesh has points authored
    parsed = _compose.parse_expression("where:purpose=render")
    assert parsed.seeds                 # parses even when nothing matches
```

- [ ] **Step 2: Run to verify it fails or passes**

Run: `PYTHONPATH=. /Users/ashrafghoniem/weft-demo/env/bin/python -m pytest tests/test_loom.py::test_gui_target_expressions_resolve -v`
Expected: likely PASS already (the grammar exists) — this is a **lock/characterization test**. If any expression raises, that string is NOT a valid GUI target: fix the mapping in the spec/Task 6, do not weaken the test. Confirm `parse_expression` exposes `.seeds/.follow/.depth` (adjust attribute names to the real dataclass if they differ).

- [ ] **Step 3: Commit**

```bash
git add tests/test_loom.py
git commit -m "loom: lock the GUI's expression targets as valid weft-ask

Characterization test: every expression string the pivot UI will emit must
parse and resolve. Nails the string->members half of the bidirectional bar in
CI; the gesture->string half is a browser check.

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_01LQPSqkEKXofapykZQPLbLv"
```

---

### Task 3: Pivot table — rows + hierarchy grouping (the default view)

**Files:**
- Modify: `weft/loom/app.html` (rewrite the table section; keep header/profile wiring)
- Test: `tests/test_loom.py` (serving-contract markers)

**Interfaces:**
- Consumes: `GET /data?columns=path,type,has_payload,bbox_volume` → `{columns, rows}`.
- Produces: a client that renders rows as a **collapsible hierarchy tree** indented by path; each row carries `data-p="<path>"`; clicking a row calls `openCard(path)` (a stub until Task 5). Marker strings (asserted by the test): `organize-by`, `data-depth`, `id="pivot"`.

- [ ] **Step 1: Write the failing serving test**

```python
def test_pivot_shell_serves(ctx):
    from weft.loom import serve
    httpd = serve(ctx, port=0, load=True, open_browser=False)
    port = httpd.server_address[1]
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    try:
        html = urllib.request.urlopen("http://127.0.0.1:%d/" % port, timeout=10).read()
        assert b"organize-by" in html          # the pivot selector exists
        assert b'id="pivot"' in html            # the pivot table container
    finally:
        httpd.shutdown()
```

- [ ] **Step 2: Run to verify it fails**

Run: `PYTHONPATH=. /Users/ashrafghoniem/weft-demo/env/bin/python -m pytest tests/test_loom.py::test_pivot_shell_serves -v`
Expected: FAIL (markers absent from current app.html).

- [ ] **Step 3: Rewrite the table section of `app.html`**

Replace the `<aside>` table section and its JS with a pivot container. Keep the existing `<header>`/profile fetch. Core structure:

```html
<main>
  <section id="work">
    <div class="bar">
      <label>Organize by <select id="organize-by">
        <option value="hierarchy">Hierarchy</option>
      </select></label>
      <label>Sort <select id="sortby"><option value="">—</option></select></label>
    </div>
    <div id="pivot"></div>
  </section>
  <aside id="card" hidden></aside>
</main>
```

JS — fetch rows once, render a hierarchy tree. Build a path→children map, render top level collapsed, toggle on click:

```js
let ROWS = [];
const byId = id => document.getElementById(id);
function loadRows(){
  return fetch("/data?columns=path,type,has_payload,bbox_volume")
    .then(r=>r.json()).then(d=>{ ROWS = d.rows; renderHierarchy(); });
}
function childrenOf(prefix){
  // direct children: one path segment deeper than prefix
  const depth = prefix === "" ? 1 : prefix.split("/").length;
  return ROWS.filter(r=>{
    const segs = r.path.split("/");
    return r.path.startsWith(prefix+"/") || (prefix==="" );
  });
}
function renderHierarchy(){
  // group rows by parent path; render roots, expand on click
  const kids = {};
  ROWS.forEach(r=>{ const parent = r.path.slice(0, r.path.lastIndexOf("/")) || "/";
                    (kids[parent]=kids[parent]||[]).push(r); });
  const roots = ROWS.filter(r=> (r.path.match(/\//g)||[]).length === 1);
  const open = new Set();
  function rowHtml(r, depth){
    const hasKids = !!kids[r.path];
    const name = r.path.split("/").pop();
    return `<div class="trow" data-p="${r.path}" data-depth="${depth}"
      style="padding-left:${8+depth*16}px">
      <span class="tw">${hasKids?(open.has(r.path)?"▾":"▸"):"·"}</span>
      <span class="tn">${name}</span><span class="tt">${r.type||""}</span>
      <span class="tb">${r.bbox_volume==null?"":r.bbox_volume}</span></div>`;
  }
  function paint(){
    const out=[]; const walk=(list,depth)=>list.forEach(r=>{
      out.push(rowHtml(r,depth));
      if(open.has(r.path)&&kids[r.path]) walk(kids[r.path],depth+1);
    });
    walk(roots,0); byId("pivot").innerHTML = out.join("");
    byId("pivot").querySelectorAll(".trow").forEach(el=>{
      el.onclick=(e)=>{ const p=el.dataset.p;
        if(kids[p]){ open.has(p)?open.delete(p):open.add(p); paint(); }
        openCard(p); };
    });
  }
  paint();
}
function openCard(p){ /* stub until Task 5 */ }
loadRows();
```

Keep CSS consistent with the existing dark palette. (Exact selectors are the implementer's to match; the markers in the test are the contract.)

- [ ] **Step 4: Run the serving test to verify it passes**

Run: `PYTHONPATH=. /Users/ashrafghoniem/weft-demo/env/bin/python -m pytest tests/test_loom.py -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add weft/loom/app.html tests/test_loom.py
git commit -m "loom: pivot table with hierarchy grouping (default view)

The stage as a collapsible, path-indented data table -- the surface you land
on. Rows from /data (cheap tier, no load), expand/collapse by hierarchy, each
row click will open the prim card (stub). Hierarchy is now the default
grouping, not the only structure.

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_01LQPSqkEKXofapykZQPLbLv"
```

---

### Task 4: Organize-by dimensions + sort

**Files:**
- Modify: `weft/loom/app.html`
- Test: `tests/test_loom.py` (serving markers)

**Interfaces:**
- Consumes: the same `ROWS` already loaded; `GET /data?columns=...&load=1` for an expensive dimension after confirm.
- Produces: `#organize-by` offers `hierarchy, type, payload, purpose, bbox-bucket, attr:<name>, material`; non-hierarchy dimensions render **flat groups** (group header + member count + aggregate, expand to rows). Expensive dimensions (`material`, point/poly counts) show a **confirm-to-load** prompt instead of auto-loading. Sort orders rows/groups by a numeric column. Markers: `value="type"`, `value="material"`.

- [ ] **Step 1: Write the failing serving test**

```python
def test_organize_dimensions_offered(ctx):
    from weft.loom import serve
    httpd = serve(ctx, port=0, load=True, open_browser=False)
    port = httpd.server_address[1]
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    try:
        html = urllib.request.urlopen("http://127.0.0.1:%d/" % port, timeout=10).read()
        for v in (b'value="type"', b'value="payload"', b'value="material"'):
            assert v in html
    finally:
        httpd.shutdown()
```

- [ ] **Step 2: Run to verify it fails**

Run: `...pytest tests/test_loom.py::test_organize_dimensions_offered -v` → FAIL.

- [ ] **Step 3: Implement grouping + sort**

Add the options to `#organize-by`. Add a `groupKey(row, dim)` and a flat-group renderer; switch `renderHierarchy` → `render()` that branches on the selected dimension:

```js
const CHEAP = {
  hierarchy: null,
  type: r=>r.type||"(untyped)",
  payload: r=> r.has_payload ? "behind payload":"loaded",
  purpose: r=> r["attr:purpose"]||"(no purpose)",
  "bbox-bucket": r=> r.bbox_volume==null?"(none)": bucket(r.bbox_volume),
};
const EXPENSIVE = { material: true };   // needs load + a material column
function render(){
  const dim = byId("organize-by").value;
  if(dim==="hierarchy") return renderHierarchy();
  if(EXPENSIVE[dim]) return promptLoad(dim);   // confirm-to-load, no auto-load
  const key = CHEAP[dim];
  const groups = {};
  ROWS.forEach(r=>{ const k=key(r); (groups[k]=groups[k]||[]).push(r); });
  renderGroups(groups);                 // header: name (N prims · Σbbox), expand to rows
}
```

`renderGroups` builds collapsible group blocks; each group header carries `data-group` and its rows carry `data-p`. Sort: read `#sortby`, order rows within groups (and groups by aggregate) numerically. `promptLoad(dim)` renders an inline "Load N prims to organize by material? [load]" that, on click, refetches `/data` with the needed column + `load=1`, then renders.

- [ ] **Step 4: Run tests**

Run: `...pytest tests/test_loom.py -v` → PASS.

- [ ] **Step 5: Commit**

```bash
git add weft/loom/app.html tests/test_loom.py
git commit -m "loom: organize-by pivot dimensions + sort

The table pivots by any USD-data dimension -- type, payload, purpose, bbox
bucket, any attr -- with hierarchy as the default. Cheap dimensions group with
no load; material and other expensive dimensions prompt to load first, never
auto-load. Sort orders rows/groups by a numeric column. USD as data, re-indexed
on demand.

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_01LQPSqkEKXofapykZQPLbLv"
```

---

### Task 5: Prim card drawer

**Files:**
- Modify: `weft/loom/app.html`
- Test: `tests/test_loom.py` (serving markers)

**Interfaces:**
- Consumes: `GET /card?path=<path>` (Task 1).
- Produces: `openCard(path)` un-hides `#card` and fills it: identity (path/type/payload), data (bbox/centroid/attrs), **relationships as a labeled list** (`kind → target`, target clickable to open that prim's card), and actions: *view as graph* (`/viewer?expr=path:<p>` in a modal/iframe), *pull just this* (`POST /pull {expression:"path:<p>"}` → digest), *copy path*. Marker: `id="card"`, `view as graph`.

- [ ] **Step 1: Write the failing serving test**

```python
def test_card_drawer_present(ctx):
    from weft.loom import serve
    httpd = serve(ctx, port=0, load=True, open_browser=False)
    port = httpd.server_address[1]
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    try:
        html = urllib.request.urlopen("http://127.0.0.1:%d/" % port, timeout=10).read()
        assert b'id="card"' in html
        assert b"view as graph" in html
    finally:
        httpd.shutdown()
```

- [ ] **Step 2: Run to verify it fails** → FAIL.

- [ ] **Step 3: Implement the drawer**

Replace the `openCard` stub:

```js
function openCard(p){
  const c = byId("card"); c.hidden=false; c.innerHTML="loading…";
  fetch("/card?path="+encodeURIComponent(p)).then(r=>r.json()).then(d=>{
    if(d.error){ c.innerHTML='<div class="muted">'+d.error+'</div>'; return; }
    const rels = (d.relationships||[]).map(r=>
      `<li><span class="rk">${r.kind}</span> →
        <a href="#" data-p="${r.target}">${r.target}</a></li>`).join("");
    const attrs = Object.entries(d.attrs||{}).map(([k,v])=>
      `<li>${k}: <b>${v}</b></li>`).join("");
    c.innerHTML = `
      <h2>${p.split("/").pop()}</h2>
      <div class="muted">${p}</div>
      <div>${d.type||"—"} · ${d.payload?"behind payload":"loaded"} ·
        bbox ${d.bbox_volume==null?"—":d.bbox_volume}</div>
      <h3>relationships</h3><ul class="rels">${rels||"<li class=muted>none</li>"}</ul>
      <h3>data</h3><ul class="attrs">${attrs||"<li class=muted>none</li>"}</ul>
      <div class="row">
        <button id="cg">view as graph</button>
        <button id="cp">pull just this</button>
        <button id="cc">copy path</button>
      </div>
      <div class="out" id="cardout"></div>`;
    c.querySelectorAll("a[data-p]").forEach(a=>a.onclick=e=>{e.preventDefault();openCard(a.dataset.p);});
    byId("cg").onclick=()=> showGraph("path:"+p);
    byId("cp").onclick=()=> fetch("/pull",{method:"POST",
        headers:{"Content-Type":"application/json"},
        body:JSON.stringify({expression:"path:"+p})}).then(r=>r.json())
        .then(r=> byId("cardout").textContent = r.error||("digest "+(r.digest||"").slice(0,16)+"…"));
    byId("cc").onclick=()=> navigator.clipboard && navigator.clipboard.writeText(p);
  });
}
function showGraph(expr){ /* modal iframe -> /viewer?expr=... ; implemented here */ }
```

`showGraph` opens a modal/overlay iframe pointing at `/viewer?expr=<expr>` (the existing slice-graph viewer, with the dangling-edge fix). This is the ONLY place the graph appears.

- [ ] **Step 4: Run tests** → PASS.

- [ ] **Step 5: Commit**

```bash
git add weft/loom/app.html tests/test_loom.py
git commit -m "loom: prim card drawer on row click

Click a prim -> a drawer answering 'what is this and what's it wired to':
identity, cheap data, authored attrs, and relationships as a plain kind->target
list (targets clickable). Actions: view as graph (the only place the graph
appears now), pull just this (certified digest), copy path. Replaces the
root-centric graph-walker as what a click does.

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_01LQPSqkEKXofapykZQPLbLv"
```

---

### Task 6: Live bidirectional expression bar + coverage captions

**Files:**
- Modify: `weft/loom/app.html`
- Test: `tests/test_loom.py` (serving markers)

**Interfaces:**
- Consumes: current organize+filter+selection state; `POST /query {expression}` to re-drive the table from a hand-typed expression.
- Produces: `#expr` text input that (a) is rewritten by every gesture via `syncExpr()`, (b) on edit re-drives the table via `/query`, and (c) shows a coverage caption when the current organize dimension has no expression. Mapping per the spec table. Markers: `id="expr"`, `no slice expression yet`.

- [ ] **Step 1: Write the failing serving test**

```python
def test_expression_bar_present(ctx):
    from weft.loom import serve
    httpd = serve(ctx, port=0, load=True, open_browser=False)
    port = httpd.server_address[1]
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    try:
        html = urllib.request.urlopen("http://127.0.0.1:%d/" % port, timeout=10).read()
        assert b'id="expr"' in html
        assert b"no slice expression yet" in html   # the coverage caption string
    finally:
        httpd.shutdown()
```

- [ ] **Step 2: Run to verify it fails** → FAIL.

- [ ] **Step 3: Implement the bar**

Add `<input id="expr">` and `<div id="exprgap" class="muted"></div>` above the table. Build the expression from state and keep gaps honest:

```js
// dimensions that have NO weft-ask form yet (spec coverage map)
const DIM_GAP = {
  type: "organizing by Type — no slice expression yet (type isn't a seed predicate)",
  material: "organizing by Material — GUI-only, no reverse-follow expression yet",
};
let FILTERS = [];   // [{expr:"where:bbox_volume>1e6"}, ...] built by gestures
function syncExpr(){
  const dim = byId("organize-by").value;
  byId("exprgap").textContent = DIM_GAP[dim] || "";
  byId("expr").value = FILTERS.map(f=>f.expr).join("  ");
}
byId("expr").addEventListener("change", ()=>{
  const e = byId("expr").value.trim(); if(!e) return;
  fetch("/query",{method:"POST",headers:{"Content-Type":"application/json"},
    body:JSON.stringify({expression:e})}).then(r=>r.json()).then(q=>{
      if(q.error){ byId("exprgap").textContent = q.error; return; }
      const set = new Set(q.members);
      renderFiltered(set);            // narrow the table to the hand-typed slice
    });
});
```

Every filter gesture (name box, numeric filter, facet click) pushes the mapped string onto `FILTERS` and calls `syncExpr()` + re-renders. A row click also writes `path:<p>` as the current selection into the bar. A parse error from `/query` shows in `#exprgap`, table unchanged.

- [ ] **Step 4: Run tests** → PASS.

- [ ] **Step 5: Commit**

```bash
git add weft/loom/app.html tests/test_loom.py
git commit -m "loom: live bidirectional expression bar (the teacher)

The bar mirrors the current organize+filter+selection as weft-ask: gestures
write it, editing it re-drives the table via /query. Beginners read it like
subtitles; power users type it. Dimensions the grammar can't express yet (Type,
Material reverse-lookup) show an honest caption instead of a fake expression --
the GUI becomes a living spec for what the DSL should grow.

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_01LQPSqkEKXofapykZQPLbLv"
```

---

### Task 7: Slice bar — certify / graph / export on the current slice

**Files:**
- Modify: `weft/loom/app.html`
- Test: `tests/test_loom.py` (serving markers)

**Interfaces:**
- Consumes: the current narrowed member set (from a filter, a hand-typed expression, or an expanded group); `POST /pull {expression}`; `GET /viewer?expr=`; the static-export flow (unchanged — surfaced as a hint/link).
- Produces: `#slicebar` (hidden until the view is narrower than the whole stage) showing member count + aggregate and `[lock this slice]` (→ `/pull` digest), `[view as graph]` (→ `showGraph`), `[export]`. A group header also exposes "lock this group" using the group's members. Markers: `id="slicebar"`, `lock this slice`.

- [ ] **Step 1: Write the failing serving test**

```python
def test_slice_bar_present(ctx):
    from weft.loom import serve
    httpd = serve(ctx, port=0, load=True, open_browser=False)
    port = httpd.server_address[1]
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    try:
        html = urllib.request.urlopen("http://127.0.0.1:%d/" % port, timeout=10).read()
        assert b'id="slicebar"' in html
        assert b"lock this slice" in html
    finally:
        httpd.shutdown()
```

- [ ] **Step 2: Run to verify it fails** → FAIL.

- [ ] **Step 3: Implement the slice bar**

```html
<div id="slicebar" hidden>
  <span id="slicecount"></span>
  <button id="slock">lock this slice</button>
  <button id="sgraph">view as graph</button>
  <button id="sexport">export</button>
  <span class="out" id="sliceout"></span>
</div>
```

```js
let CURRENT_EXPR = "";   // the expression for whatever is currently narrowed
function setSlice(expr, count){
  CURRENT_EXPR = expr;
  byId("slicebar").hidden = !expr;
  byId("slicecount").textContent = expr ? (count+" prims · "+expr) : "";
}
byId("slock").onclick = ()=> fetch("/pull",{method:"POST",
    headers:{"Content-Type":"application/json"},
    body:JSON.stringify({expression:CURRENT_EXPR})}).then(r=>r.json())
    .then(r=> byId("sliceout").textContent = r.error||("digest "+(r.digest||"").slice(0,16)+"…"));
byId("sgraph").onclick = ()=> showGraph(CURRENT_EXPR);
byId("sexport").onclick = ()=> byId("sliceout").textContent =
    "run: weft loom <stage> --export <dir>   (static, shareable)";
```

`setSlice` is called whenever a filter/expression narrows the table or a group is expanded (pass that group's expression if it has one, else leave the bar showing the gap caption and disable lock for GUI-only groups).

- [ ] **Step 4: Run tests** → PASS.

- [ ] **Step 5: Commit**

```bash
git add weft/loom/app.html tests/test_loom.py
git commit -m "loom: slice bar -- lock / graph / export the current slice

Any narrowed view (filter, typed expression, or expression-backed group) is a
slice: the bar shows its count and offers a certified digest (/pull), the graph
view, and the static export. Slice is the unit the whole surface flows toward.
GUI-only groups (no expression yet) show the caption and don't offer lock.

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_01LQPSqkEKXofapykZQPLbLv"
```

---

### Task 8: Full browser smoke test on ALab + cleanup

**Files:** none (verification task; fixes only if the pass finds breakage)

**Interfaces:**
- Consumes: the assembled UI on the real ALab stage.
- Produces: a verified end-to-end pass with screenshots; `test_static_export` still green (the export rewrites must still work with the new app.html).

- [ ] **Step 1: Launch the Loom on ALab**

```
PYTHONPATH=. /Users/ashrafghoniem/weft-demo/env/bin/python -m weft.cli loom /Users/ashrafghoniem/weft-demo/alab/ALab-2.3.0/ALab/entry.usda --no-open
```
(background; confirm `lsof -ti:8765` is listening).

- [ ] **Step 2: Drive it with the Claude-in-Chrome tools and screenshot each:**
  1. Land → the hierarchy tree renders, collapsed, readable.
  2. Expand into an asset; click a prim → card drawer shows type + material relationships.
  3. Organize by → Type; groups form. Organize by → Material; the load prompt appears (not an auto-load, not a crash).
  4. Add a numeric filter → the expression bar shows `where:bbox_volume>…`; the slice bar shows the count.
  5. Organize by Type → the coverage caption appears ("no slice expression yet").
  6. From the slice bar, "lock this slice" → a digest; "view as graph" → the slice graph renders (no blank canvas, console clean).
  7. From a prim card, "view as graph" → renders.

- [ ] **Step 3: Confirm the browser console is clean** (`read_console_messages` with `onlyErrors:true`) at each step; fix any JS error found before proceeding.

- [ ] **Step 4: Run the full suite**

Run: `PYTHONPATH=. /Users/ashrafghoniem/weft-demo/env/bin/python -m pytest tests/ -q`
Expected: all green (the 369 baseline + the new loom tests). Pay attention to `test_static_export` — the export rewrites (`/* STATIC */`, `src="viewer"`) must still match the rewritten app.html; update the export string replacements in `server.py` if the new shell changed those anchors.

- [ ] **Step 5: Commit any fixes + update the spec's status**

```bash
git add -A
git commit -m "loom: ALab smoke-test pass for the pivot UI

End-to-end verification on ALab: land/expand/card/organize/filter/slice/graph
all render with a clean console. <list any fixes>. Full suite green.

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_01LQPSqkEKXofapykZQPLbLv"
```

---

## Self-Review

**Spec coverage:** spine (Tasks 3–7 assemble land→organize→filter→inspect→certify) ✓; pivot table + organize-by + cost tiers (Tasks 3,4) ✓; prim card (Task 5) ✓; live bidirectional expression bar + coverage captions (Tasks 2,6) ✓; slice as unit + certify/graph/export (Task 7) ✓; `/card` endpoint (Task 1) ✓; graph demoted to summoned view (Tasks 5,7 via `showGraph`) ✓; keeps read-only/localhost/export (Global Constraints, Task 8) ✓. Grammar growth correctly absent (out of scope).

**Placeholder scan:** The one deliberate `ADAPT` is Task 1's relationship-enumeration call — flagged explicitly with a named fallback (reuse `slice_graph` edges) because the exact `relkinds` per-prim API must be confirmed against the code, not guessed. `showGraph`'s modal is specified as "iframe → /viewer?expr=" and implemented in Task 5. No "TBD"/"add error handling"-style gaps.

**Type consistency:** `/card` returns `{path,type,payload,bbox_volume,centroid,attrs,relationships[{kind,target}]}` in Task 1 and is consumed with those exact keys in Task 5. `CURRENT_EXPR`/`setSlice` (Task 7), `FILTERS`/`syncExpr` (Task 6), `ROWS`/`openCard`/`showGraph` (Tasks 3,5) are named consistently across tasks. Expression strings in Task 2's lock-test match the mapping the bar emits in Task 6.

**Risk note for the executor:** the heaviest task is the app.html work (Tasks 3–7), verified by serving-contract markers in CI plus the Task 8 browser pass — because an implementer subagent may lack browser tools, the controller runs Task 8. If executing inline, run the browser checks as you go rather than only at the end.
