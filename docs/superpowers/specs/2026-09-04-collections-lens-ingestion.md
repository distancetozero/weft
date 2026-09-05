# Collections lens — ingest USD collections as weft threads

**Status:** design draft for owner review, 2026-09-04. Adds a "Collections"
source/lens to the thread viewer that reads existing `UsdCollectionAPI`
collections and lets you pull on them — **zero weft pre-conditioning**, because
collections are relationships teams already authored into the USD.

## Why this matters most

weft's rich lenses today (Mount, finish, shading) need the weft metadata pass.
`UsdCollectionAPI` collections need **nothing** — they're already in the stage
(material-binding sets, light-linking sets, render/department groupings). They
are literally "team-defined relationships, already encoded in USD," which is
weft's founding premise sitting in the file. So a Collections lens is the
single highest-leverage way to make weft useful on an **unprepped, real** scene:
open weft on your stage, and pull on the sets you already have.

It also puts weft *with the grain of USD* — consuming the standard set
primitive rather than a private one — which is the most AOUSD-aligned move on
the roadmap.

## Scope (v1)

- **Ingest, read-only.** Enumerate collections on the stage; show them as a
  lens; resolve membership; pull a collection like any other rule.
- **No export, no live-expression translation in this spec** (see the guardrail
  below on why "baking out" is deliberately limited).

## What it reads

- Enumerate: for prims carrying `UsdCollectionAPI`, list their collections
  (`Usd.CollectionAPI.GetAllCollectionNames` / `GetAllCollections`). Also expose
  collections wherever they live (a common convention is a `/collections` or
  per-model scope) — discover, don't assume a path.
- Resolve membership: `collection.ComputeMembershipQuery()` →
  `Usd.ComputeIncludedPaths(query, stage)` (or the query's `IsPathIncluded`),
  honoring `expansionRule` (explicitOnly / expandPrims / expandPrimsAndProperties)
  and `includes`/`excludes`. Support both explicit and `membershipExpression`
  collections transparently — USD computes both; weft just consumes the result.
- Metadata: collection name, the prim it's defined on, member count, and whether
  it's expression- or explicit-based (for display).

## How it surfaces in the viewer

- A **"Collections"** entry in the lens selector (alongside Hierarchy / Mount /
  Shading / Finish). Selecting it re-centers the graph on collection nodes —
  each collection is a node; its members are the prims it includes (edges
  `usd:collection`).
- A collection node behaves like a facet node under the existing rule→set→load
  seam: **double-click = pull** → `load_set` the resolved member prim paths
  (bounded-set discipline: becomes the focus's load, unloads on move unless
  pinned); inspector shows "load all N in this collection" + the member list.
- Peek/expand/pin all inherited from the existing machinery. Only leaf/prim
  members load; a collection that includes non-leaf scopes resolves to the
  loadable prims under them (same predicate-result filtering as the other
  lenses).

## build_graph changes

`weft/threadgraph.py` gains an optional collections pass (guarded, additive,
never raises): for each discovered collection, add a node
(`collection:<prim>.<name>`) and `usd:collection` edges to its resolved member
prim paths. Emitted only when collections exist; degrades to nothing when they
don't — same defensive shape as the finish/shading facet pass. Membership
resolution is lazy where possible (resolve on pull, cache; don't force-load
payloads to enumerate). `usd:collection` joins the `kinds` list so the lens
selector offers it only when present.

## The strategic guardrail — why we ingest but do NOT "bake out" live

Exporting weft expressions as *live* native USD collections (a
`membershipExpression` USD itself evaluates) is tempting, but **it can hollow
out weft's own value**, so v1 deliberately does not do it:

- If a weft rule becomes a native collection that USD evaluates on its own, then
  for that rule weft is just a one-time generator — the *ongoing* thing (the
  pull UX, drift certification, relationship-thread navigation, derivation) is
  what isn't baked out. Bake out the **portable artifact** (a snapshot
  collection as *output*, certified by a drift receipt — see the drift spec),
  keep the **live value** (navigation + certification + the team-relationship
  framework) in weft. Don't bake out the thing that *is* weft.
- Also technical: `SdfPathExpression` is path-centric; weft's facet
  (attribute-value) and mount (relationship-traversal) predicates don't
  translate to a live path-expression anyway (they'd have to materialize to
  explicit `includes` — a snapshot). So the live round-trip is both partly
  impossible and partly self-negating. Ingest freely; export only as certified
  snapshots; keep the live layer weft's.

(Export-as-certified-snapshot is specified with the drift work, not here.)

## Verify

- Synthetic stage with 2+ `UsdCollectionAPI` collections (one explicit
  includes/excludes, one `membershipExpression`), a mix of prim and scope
  members. pxr-gated tests: enumeration finds them; membership resolves to the
  expected prim set for both kinds; the graph gains the right
  `collection:*` nodes + `usd:collection` edges; a non-collection stage yields
  no collection nodes (graceful).
- Real onscreen usdview via `weftview.sh`: the Collections lens appears only
  when the stage has collections; pulling a collection loads exactly its
  members (pixel/IsLoaded), unloads on focus move.
- Existing suite stays green; `build_graph`'s other outputs unchanged when no
  collections exist.

## Open questions

1. **Discovery breadth** — enumerate collections only on models/`/root`, or a
   full-traverse for any prim carrying `UsdCollectionAPI`? (Full-traverse is
   complete but costs a walk; likely traverse-but-cache.)
2. **Huge collections** — a light-linking collection can include most of the
   scene. Cap/omit from the graph above N members, offer as a pull-only rule
   without drawing every edge? (Lean: show the node + count, draw edges on
   expand, cap per ring like everything else.)
3. **Nested collections** — collections can include other collections; resolve
   fully via `ComputeMembershipQuery` (which handles it) and treat as flat
   membership, or show the nesting as structure? (v1: flat via the query;
   nesting display later.)
