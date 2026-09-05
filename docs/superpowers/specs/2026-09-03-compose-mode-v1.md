# Compose mode v1 — build spec

**Status:** draft for owner review, 2026-09-03. Implements the compose half of
`2026-09-03-selection-algebra-and-compose-mode.md`, scoped to what we can ship
now over the predicates already in the graph. No camera, no persistence, no
manifests — those are later cycles.

**Goal:** make writing an expression as tangible as walking the graph, and make
explore-mode and compose-mode two views of one selection. Build it into the
embedded Weft Threads viewer (`extras/usdview/weftViewer/viewer_template.html`),
loading through the existing `load_set` seam.

## The key simplification

The client-side graph (`DATA.nodes` / `DATA.edges`, already fully in the page)
**already contains everything v1's predicates need to evaluate** — facet
membership (`weft:bind:*` edges), paths (node ids), names (labels), Mount
(`Mount` edges). So the v1 evaluator runs **entirely in JS against the loaded
graph**; the only backend touch is `bridge.pullSet(paths)` to load the result.
No new bridge methods, no `build_graph` change.

## 1. Expression model (JS)

```
Expression = Term[]
Term = { op: "∪" | "∩" | "∖",           // vs the accumulator; first term's op ignored (seed)
         pred: Predicate }
Predicate =
  | { kind: "facet", facet: "finish"|"shading", value: string }
  | { kind: "path",  value: string, scope: "below"|"children" }  // below=prefix; children=direct only
  | { kind: "name",  glob: string }       // glob on node label
  | { kind: "mount", of: string }         // prims Mount-carried by `of` (depth 1)
```

**Operators are ASCII** (owner decision): `+` = union (∪), `&` = intersect (∩),
`-` = difference (∖), in both the typed text and the chip operator selector.

v1 is a **flat left-to-right fold** — `A + B & C` = `((A ∪ B) ∩ C)`. Nested
parentheses are v2. Keep the data structure ready for nesting (a term could
later hold a sub-Expression) but don't build the UI for it yet.

## 2. Evaluator (pure JS, unit-testable)

`evalExpr(expr, graph) -> Set<primPath>` — resolves each predicate to a set of
**loadable prim paths** (type `prop`/`furniture`; never facet/group ids), then
folds with the term operators:

- `facet`: prims on the other end of this facet node's `weft:bind:*` edges.
- `path`: `path:/root/shelf01` (scope `below`) = prim nodes under it (prefix,
  and-below); `path:/root/shelf01/*` (scope `children`) = its direct children
  only. The parser reads a trailing `/*` as scope `children`, else `below`.
- `name`: prim nodes whose label matches `glob` (`*`/`?`).
- `mount`: prims that are `Mount`-carried by `of` (follow `Mount` edges; depth 1
  for v1).

Fold: seed = first term's set; then `∪`=union, `∩`=intersection, `∖`=difference.
Keep `evalExpr` a **pure function with no DOM/bridge deps** so it can be
`node`-tested against a fixture graph.

## 3. The compose panel (in-viewer overlay)

A collapsible overlay panel inside the viewer (NOT a separate dock — the bridge
to explore must be immediate). Contents, top to bottom:

- **Text line** — the expression as text, editable, using the existing weft-ask
  grammar with `+`/`&`/`-` operators (`finish=translucent + name:decor_*`).
  Typing re-parses into chips; chips edit back into text. The existing `#seedq`
  ask bar is the seed of this — extend it, don't add a second parser.
- **Chip row** — each term as a removable token: `[⊕ finish=translucent ×]`,
  with a small operator selector (`+`/`&`/`-`) between chips. Color chips by
  predicate kind (reuse `--finish`/`--shading`/`--prop`/`--group` tokens).
- **Cost readout** — `N prims · P% of scene` (exact count from `evalExpr`;
  live). Byte-size estimate is deferred (needs a bridge call to sum payload
  sizes — flagged, not v1).
- **Actions** — `Load set` (→ `bridge.pullSet(result)`, becomes the focus's
  rule-load, unloads on move unless pinned — identical semantics to facet
  loading), `Pin set`, `Explore result` (drop into explore mode on the set).

## 4. Tangibility — click-to-build

The graph is the palette. Without breaking peek(single)/pull(double):

- **Shift-click a node** = add it to the expression as a **union** term:
  a facet node → `facet:…`; a group → `path:<its path>`; a leaf → `path:<leaf>`.
  **Always union on add** (owner decision); change the operator afterward via the
  chip's `+`/`&`/`-` selector. One gesture to learn, no modifier combos.
- Adding a term opens the compose panel if collapsed and updates text + chips +
  preview together.
- Facet chips in a node's inspector also get an **"＋ add to expression"**
  affordance.

## 5. Live preview

On every expression change (debounced ~120ms), `evalExpr` runs and the matching
prim nodes are **highlighted in the graph** (a preview ring/glow distinct from
selection and pin styling). Nothing loads on preview — preview is look, not
pull. The cost readout updates from the same evaluation.

## 6. The two-way bridge

- **Explore → Compose ("Describe selection"):** a button that reads the current
  manual selection (focus's set + pinned) and renders it as an expression —
  **literal union by default** (`path:/a ∪ path:/b ∪ …`), honest over magical.
  If the literal set *exactly* equals a facet's membership, show a one-line
  **"generalize? → facet:finish=translucent"** suggestion the user can accept.
- **Compose → Explore ("Explore result"):** take the evaluated set, drop into
  explore mode centered on it (re-center the graph on the set; the set becomes
  the focus's neighborhood as bboxes; `Load set` optional from there).

One selection, two views. This bridge is the whole point — build it in v1, not
as a follow-up.

## 7. Files

- `extras/usdview/weftViewer/viewer_template.html` — all of the above (panel UI,
  `evalExpr`, chip editor, text↔chip sync, shift-click gesture, preview
  highlight, bridge actions). The bulk of the work.
- `extras/usdview/weftViewer/_stagebridge.py` — **no change required**
  (`pull_set`/`load_set` already exist). Optional (deferred): `estimate(paths)`
  for the byte-size readout.
- No `build_graph` / `weft/` change.
- Standalone: everything must still work in a plain browser with `bridge` null
  (preview + evaluation work offline; the load actions no-op, as today).

## 8. Testing

- **`evalExpr` unit tests** (node, against a small fixture graph): each
  predicate kind, each operator, the fold order, empty results, facet with no
  members, path prefix boundaries, glob edge cases.
- **Real onscreen usdview** (`weftview.sh`): build an expression by shift-click
  AND by typing (assert text↔chips stay in sync); preview highlights exactly the
  evaluated set (no loads during preview — `IsLoaded` unchanged); `Load set`
  materializes exactly the set (pixel + `IsLoaded`); `Explore result` re-centers
  on it; `Describe selection` round-trips a manual pin-set back to a literal
  expression whose `evalExpr` reproduces that set. Panel survives, exit 0.
- `node --check` the viewer JS; existing suite stays green (nothing touched
  outside the viewer + tests).

## 9. Explicitly out of scope (later cycles)

Camera/spatial/temporal predicates; nested parenthesized boolean; byte-size cost
estimate; saving/naming expressions to disk or a manifest; `UsdCollectionAPI`
round-trip; minimal-rule *inference* beyond the single exact-facet
"generalize?" hint.

## 10. Review decisions (settled 2026-09-03)

1. **Add gesture** — shift-click always adds as **union**; the operator is
   changed afterward in the chip's `+`/`&`/`-` selector. No modifier combos.
2. **Operator syntax** — **ASCII `+` / `&` / `-`** (union / intersect /
   difference) in both text and chips.
3. **Path scope** — support **both**: `path:X` = that prim and everything below;
   `path:X/*` = its direct children only.
