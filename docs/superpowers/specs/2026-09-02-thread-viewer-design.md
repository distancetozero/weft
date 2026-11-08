# The Thread Viewer — Lenses over a Pulled Scene

Date: 2026-09-02
Status: design; a web prototype validates it before the usdview port.
Grounding: UX research (`.superpowers/ux-research.md`, out-of-repo) surveying
Neo4j Bloom, Obsidian, Cambridge Intelligence KeyLines/ReGraph, Kumu,
Cytoscape, yFiles, and the DCC node editors (Houdini/Nuke/Blender/Unreal).
Two prototype iterations already taught the central lesson (§9).

## 1. What this is

A relationship explorer for a USD scene — the visual face of a weft pull.
It lives ultimately as a **panel inside usdview**; a standalone web build is
the iteration surface. It does not replace the hierarchy tree; it sits beside
it and lets you see the scene through **any relationship**, not only
namespace.

The founding premise, made into one control: hierarchy is not the world, it
is one **lens**. You choose which relationship becomes the frame.

## 2. The lens — the organizing concept

A **lens** is the relationship chosen as the coordinate system for the view.
It does three things at once, which is why it is the spine of the design and
not merely a filter:

1. **Organizes the layout.** Hierarchy lens → a layered tree (layout keyed to
   arc direction, not force). Shading lens → props gather around shared
   shading tokens. Mount lens → props cluster by what carries them.
2. **Selects what to follow.** Viewing through a lens follows that lens's
   thread kind by default — so "how do I see it" and "what do I pull" are one
   choice. The lens selector and the CLI's `--follow`/view rules are the same
   object; this panel is the GUI face of a slice's **view axis**
   (docs/10-slices.md already defined view as "which binding attributes a
   consumer reads").
3. **Projects, never mutates.** Every lens shows the same ground-truth prims,
   re-viewed. Consistent with the standing principle: an index is a
   disposable projection of ground truth.

Two families of lens, both reducible to "pick a relation":
- **Structural** (a relationship kind): Hierarchy (`usd:arc`), Mount,
  material:binding, and any team kind (`electrical:feeds`). Edges connect
  prim→prim.
- **Facet** (a binding attribute): Shading, Finish, Material. Nodes gather
  around shared **values** (a prim→value relation), producing the
  cross-cutting stars. This resurrects the earlier "facet model": a lens is a
  facet, expressed as a viewpoint rather than a data model.

**The lens list is derived from the threads present in the current pull** —
never a fixed menu of empty options, never overwhelming. Team-defined kinds
appear automatically (same extensibility as edge extractors and the follow
vocabulary). **Default lens: Hierarchy** — a usdview user arrives
tree-brained; starting there is zero cognitive cost, and the product's
teaching moment is the lens *swap* ("you've seen the tree — now turn the
world sideways"). The contrast needs the familiar baseline to land.

## 3. The interaction model (research-grounded)

Legibility is a **consequence** of this model, not a separate fight.

- **Open filter-first, near-empty.** A seed query, a lens selector, a
  thread-kind checklist. No hairball on load.
- **Seed as a single focus node with collapsed, count-badged stubs.** The
  current usdview prim (or a query result) appears as one node with stubs:
  `▸ 12 children`, `▸ 1 material`, `▸ 3 mounts`. Nothing exploded.
- **Expand one ring at a time, along enabled thread kinds only.** Clicking a
  stub (or node) grows exactly that ring. Never a global reveal.
- **Stable incremental layout — the single most important mechanic.**
  Existing nodes are pinned; only newcomers are placed (KeyLines
  "adaptive organic" / yFiles from-sketch). Our prototypes re-solved the
  whole graph every frame — the real reason even 150 nodes read as a
  hairball. This fix matters more than any visual tweak.
- **Aggregate shared vocabulary into one count-badged hub, never N live
  edges.** 131 props → a single `usd_full ×131` node, expandable on demand.
- **Cap every expansion** ("first N + more…").
- **Dim, don't delete** on focus; labels only on focus + neighbors + hover,
  with reserved label space and middle-ellipsis paths.
- **Color = thread kind** — the DCC muscle memory (typed wires in
  Houdini/Nuke/Blender/Unreal).

## 4. Select → inspect → pivot (the core loop)

The heart of "navigate by relationships, not paths":

1. **Select** a prim (in the graph, or synced from usdview's tree/viewport).
2. **Inspect** — a read-only panel shows the prim's facets and threads:
   its type, identity, the binding attributes it carries (finish, shading,
   material, …), and its threads grouped by kind with counts. This is the
   "see its properties" step. Read-only — no USD authoring here.
3. **Pivot** — clicking a facet or thread-kind in the inspector re-scopes the
   graph: either **re-seed** on this prim, or **switch the lens** to that
   facet's plane, and the graph re-forms. "Scope to that lens and the graph
   changes," made literal.

This loop is bounded and cheap: inspection reads already-resolved data; the
pivot is a re-seed or lens change, both of which the model already supports.

## 5. Pairing with rules / filtering

The thread-kind checklist is a **degree-of-interest function** (Cytoscape's
formal framing): it decides which threads are expandable and visible. Lens +
enabled-kinds + seed together are precisely a slice's rules — so a
configuration here is a reusable **thread-query** (Kumu's saveable Views),
serializable to the same rule-set format the CLI consumes. The viewer and
`weft select --follow …` are two faces of one vocabulary.

## 6. usdview integration (the endpoint)

- A docked, non-modal panel (the DCC norm; Houdini/Nuke/VS Code precedent).
- **Bidirectional selection sync**: selecting a node selects the prim in
  usdview's tree, viewport, and property panel; selecting there updates the
  focus here. Single selection model across views.
- Minimap + breadcrumb for orientation once expanded (Houdini dive-in).
- Reuses the plugin machinery already shipped (extras/usdview): the viewer is
  a second panel beside Ask/Solo/Who, driven by `weft.pull`/`weft.ask` and
  the deps graph. Selecting/pulling here can feed Solo threads
  (materialize the pulled set) — the graph becomes the find half, Solo the
  load half.

## 7. Data sources

- Prim-level threads and facets from the composed stage / interfaces (as the
  acceptance and prototype extractors already do).
- Reverse threads ("who depends on this") from the deps graph.
- At usdview-panel scale, expansion is per-ring and lazy, so the viewer never
  needs the whole graph resident — consistent with the pull thesis.

## 8. Anti-patterns (named, some already learned)

- **Dump-everything global graph** — our first two prototypes; the hairball.
- **Full re-layout on every expand** — nauseating; breaks the mental map.
- **Rendering an aggregate relation as N edges** — always a count-badged hub.
- **Force-directed as the only layout** — prefer layered/hierarchical when a
  lens has direction (hierarchy, feeds).
- **Uncapped expansion.**
- **A fixed lens menu** — derive it from the pull.

## 9. What the prototypes taught

- v1 (hand-rolled canvas): dead drag from a read-only-property coordinate bug,
  then a `touch-action` iframe bug. Lesson: use a real graph library.
- v2 (d3, 1018 edges dumped): robust drag/zoom, but an unreadable hairball.
  Lesson: the density problem is conceptual, not visual — the fix is
  filter-first + expand-on-demand, i.e. this spec. The lens concept
  (owner's) is what makes the filtered views *meaningful* rather than merely
  smaller.

## 10. Prototype v3 scope (validates this spec, web build)

d3, richer per-node facet data. Implements: Hierarchy default lens + lens
selector (derived from present kinds); seed as focus node with collapsed
count-badged stubs; expand-one-ring with pinned incremental layout;
aggregated facet hubs; inspector panel (select → facets + threads-by-kind);
pivot (click a facet/kind → re-seed or switch lens). Out of scope for the
web prototype: live usdview sync, USD authoring, minimap.
