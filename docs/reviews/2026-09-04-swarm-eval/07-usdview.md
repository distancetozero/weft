## Weft usdview plugin / thread-explorer — evaluation

### (a) Verdict

The interaction model (moving focus, peek/pull/pin, rule→set→load) is a genuinely good idea and the last five commits implement most of it — but it lives entirely in ~250 lines of **untested JavaScript**, the Python side that actually calls `stage.Load/Unload` has no notion of the invariant it is supposed to enforce, and the shipped "safe fallback" panel violates the product's founding claim outright. Roughly 4× more code churn went into WebEngine plumbing (four panel architectures in two days, one written-and-deleted the same day) than into the model. The crash root cause was found (credit: real lldb work), but the fix is a permanent surgical removal of a private usdview object, and the panel now leans on four private usdview surfaces. There is no committed evidence (screenshot, recording, report) that it works on ALab; the `.superpowers/threadpanel-report.md` cited ~8 times is not in the repo.

### (b) Panel-implementation timeline (16 commits, all 2026-09-02/03)

| commit | what | fate |
|---|---|---|
| 69af449→3ad9b7f | Ask/Solo/Restore/Who + receipt dock | live |
| fe4accf | `weft/threadgraph.py` build_graph (pure) | live |
| 1d7d71e | **R1** QWebEngineView+QWebChannel in `threadpanel.py` | crashed (exit 139) |
| 6fa157a | investigate; keep dock | no code change |
| 56c60d9 | **R3** pivot to native QGraphicsView (`threadpanel.py` rewritten) | kept as "fallback" |
| 95eca26 | **R4** native pan/zoom + expand | kept |
| 9e93367 | **R5** loopback HTTP `bridgeserver.py` (408 lines) + vendored d3 → external browser | deleted next commit (owner rejected) |
| 8e60d05 | **R6** re-embed WebEngine as `webenginepanel.py` + `weft_usdview.py` shim | still crashed |
| d6951d4 | **R7** root cause: PySide 6.11 re-entrancy in usdview's `AppEventFilter`; remove the filter | live |
| f70e385→036cfc3 | R8–R11: interaction model, engine-rebuild refresh, load-all-below, facet loads | live |

Plumbing (R1–R7): 7 commits, ~4,000 lines churned. Model (R8–R11): 5 commits, ~900 lines.

### (c) Invariant check

| Spec invariant | Holds? | Evidence |
|---|---|---|
| Only leaves load, only on pull/pin | **No** | Ask bar: `resetToSeed(r.ids)` → `notifyLoaded(revealedNow)` loads up to 40 name-matches incl. **groups** (`viewer_template.html:755, 773-775`) → `load_one` = `stage.Load(path)` with-descendants (`_stagebridge.py:229`). `notifySelect(seeds[0])` → `select_and_load` loads again (`:758`, `_stagebridge.py:204-218`). "⇣ load all below" on `/root` loads the whole scene (`:301-308`, `_stagebridge.py:193-196`). |
| Groups never load | **No** (native panel) | `threadpanel.py:262-266` `initial_view()` calls `_load_paths(kids)` on `/root`'s children = every group, with descendants = **the world loads on panel open**. Every click also calls `select_and_load` (`:298`). |
| loaded = {focus leaf} ∪ {pinned leaves}, bounded | **Partially** | Bookkeeping is JS-only (`ruleLoads`, `pinned`, `focus`, `:183-210`); Python never reads `stage.GetLoadSet()`. Ask-bar loads are tracked nowhere → set grows unboundedly. Subtree rule: `ruleLoads.set(id,[id])` (`:304`) so `notifyUnload([root])` (`:202`) → `stage.Unload(root)` unloads pinned **descendants** (the pin filter only checks exact paths; probe: `Unload(group)` cleared all children). Reverse: leaf focus under a pinned subtree is unloaded on move (`:199`). |
| Load with descendants, no cascade | Holds for leaves | `_stagebridge.py:229`; ALab leaves are single placements. |
| Moving focus unloads previous | Holds, but destructive on loaded stages | `unload_set` (`_stagebridge.py:167-185`) never checks whether the panel loaded the prim: on plain `usdview file.usda` (no `--unloaded`) walking the graph **removes geometry** the user opened with. |
| Solo deactivates in session layer; Restore lossless | **Mostly** | `Usd.EditContext(stage, GetSessionLayer())` (`__init__.py:311,430`); probe: a user's own prior `active=false` survives Restore; empty `over`s remain (cosmetic). **But** on the panel's own documented `--unloaded` invocation, `deactivation_set` uses `GetChildren()` (default predicate requires *loaded*, `core.py:300`) — probe: frontier for `a_0001` on LoadNone = `['/root/shelf02']`, missing unloaded siblings `b_0002,c_0003`; on a loaded stage all three. **Solo does not solo on an unloaded stage.** Tests only cover loaded stages. |
| Lens semantics | Holds | `recenter` filters `a.kind===lens` (`:380`); facet pull switches lens (`:327-328`). |
| Stage reload / new file | **Not handled** | Graph built once (`webenginepanel.py:266`), dock cached (`:249`); JS state keeps old paths; only `_valid_prim` prevents errors. No refresh command. |

### (d) Defects / hazards, ranked

1. **Native "fallback" loads the world on open** — `threadpanel.py:266` + `_stagebridge.py:229`. Directly contradicts README's "never changes usdview's own load policy".
2. **Solo frontier wrong on `--unloaded` stages** — `core.py:300` default-predicate `GetChildren()`; same class of bug fixed in `threadgraph.py:157` and `ask.py:143` but not here.
3. **Unload without selection guard** — `moveFocusTo` unloads `prev` (`viewer_template.html:206`) *before* selecting the new focus; usdview's selection/property focus may still sit on a Mesh under the prim being unloaded. `__init__.py:271-284` documents exactly this "Accessed invalid null prim" crash for deactivation and clears selection first; `_stagebridge.unload_set` does not.
4. **Ask bar bypasses the model** — loads groups, untracked, never released (`:755,758`). Also `focus` is not updated by `resetToSeed(seedIds)`.
5. **Pinned descendants unloaded by subtree release** — `:202` filters exact paths only; `stage.Unload` is recursive.
6. **Crash fix is a permanent private-API amputation** — `webenginepanel.py:222-225` removes `appController._filterObj` for the process life; plus `_UsdviewApi__appController`, `_stageView.closeRenderer()`, `_frameSelection()` (`_stagebridge.py:75-81,106`). Any usdview release can break all four silently (guarded to PrintStatus, so degradation is at least visible).
7. **Engine rebuild per load/unload** — `closeRenderer()` (`_stagebridge.py:79`) on every gesture; on a fully-loaded scene this is a full Hydra repopulate per double-click.
8. **Facet pull selection echo** — `pull_set` adds N prims one by one (`_stagebridge.py:161-162`); each emits `signalPrimSelectionChanged` → `focusPrim` → JS `onStageFocus` (`:160-165`) does `render()`+`inspect(member)` N times, ending with the inspector on a member instead of the facet.
9. **Duplication**: `_wire_stage_selection` copied verbatim (`threadpanel.py:70-104` / `webenginepanel.py:89-123`); `_guard` ×2 (`__init__.py:60`, `_stagebridge.py:17`); root synthesis and tidy-tree in both JS and Python (`threadpanel.py:109-171` / html `:125-127,437-455`); legacy `select`/`loaded` slots and `load_paths/unload_paths/pull_leaf/load_subtree` compatibility names all still wired.
10. **Graph is ALab-only**: hardcoded `/root`→group→`<asset>_NNNN` and regex-parsed interface files (`threadgraph.py:34-36,159-176`); any other stage yields one node (`test_threadgraph.py:567-592`).

The rule→set→load seam itself (`load_set/pull_set/unload_set`) is a clean, small interface — the problem is that half the callers (`select_and_load`, `loaded`, native panel) go around it, and the *set bookkeeping* lives on the wrong side of it.

### (e) Testability + evidence

`pytest -q tests/test_usdview_core.py tests/test_threadgraph.py`: **29 passed, 2 skipped** (ALab-gated). All of `core`, `_stagebridge`, `threadpanel`, `webenginepanel` import headless with no Qt in `sys.modules` (stderr warnings only). `_stagebridge.py` is Qt-free and takes an `api` duck — **zero tests**. The interaction model (JS) has **zero tests** beyond `node --check`. No screenshots/recordings of the panel are committed; `docs/assets/*.png` are `usdrecord` landing-page renders (commit ab16f74).

### (f) Value

Versus stock prim browser + `--mask`: the differentiator is real — Mount/finish/shading lenses and "load everything translucent" in one gesture is something `--mask` cannot express. But it is an ALab demo, not a usdview tool (item 10), and the compelling behaviour is undermined by items 1, 4 and 5.

### (g) Next steps

1. **(S) Delete `threadpanel.py` and the "native panel" command**; it loads the world and has none of the model. Delete `select`/`loaded` slots, `notifySelect/notifyLoaded`, and the four compatibility wrappers. Route the ask bar through `uiPullFacet`/`pullSet` only.
2. **(S) Fix `deactivation_set` predicate** to `PrimIsActive & PrimIsDefined & ~PrimIsAbstract` (as `threadgraph.py:157`); add a LoadNone test (the probe above is the test).
3. **(S) Guard unloads like Solo does**: in `unload_set`, snapshot selection, clear it, unload, re-add survivors; and select the new focus *before* releasing the old one.
4. **(M) Move loaded-set bookkeeping to Python**: a `FocusModel` (pure, tested) holding `focus/pinned/ruleLoads`, exposing `move_focus/pin/unpin/home` that return `(to_load, to_unload)` diffs computed against `stage.GetLoadSet()` and a `panel_loaded` set — so the panel only ever unloads what it loaded, pinned descendants survive, and the invariant is asserted in a unit test. JS becomes view-only.
5. **(S) Refresh on stage change**: subscribe to `api.dataModel.signalStageReplaced` (or rebuild on `_onThreads` when `stageIdentifier` changed); reset JS state.
6. **(M) Batch selection** in `pull_set` (usdview's selection `batchPrimChanges` context) and coalesce `focusPrim` to one emit.
7. **(M) Commit evidence**: one screenshot pair (bbox → loaded) and the threadpanel report, or drop the references.
8. **(L, decision) Vehicle**: stay in usdview *only* as a thin renderer of a usdview-independent model. The load/unload rules and graph should be a `weft explore` core (Python, tested), with the WebEngine dock as one shell. Do not pursue a Hydra scene index (this is load-rule policy, not scene filtering) or a standalone Qt app (you'd re-implement the viewport). If the private-API count grows past the current four, the browser-bridge (R5, 408 lines already written once) is the least fragile fallback despite the owner's objection.
