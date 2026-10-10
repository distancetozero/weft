# The Loom as a Pivot over USD — Design

**Date:** 2026-10-10
**Status:** Implemented on branch `loom-explore` (Tasks 1–8) — ALab smoke-test
passed, full suite green (379 passed, 10 skipped). Known degradation: the static
`--export` bundle's graph/card need the live server (the table, organize-by, and
filtering work offline); coherent static graph/card is a follow-up.
**Supersedes the layout of:** `2026-10-07-the-loom.md` (keeps its read-only stance,
localhost bind, engine-wrapper thinness, static export, and the graph viewer —
changes what greets you and how the pieces connect).

## Goal

Rebuild the Loom around a single spine so a stranger gets value on unseen USD in
ten minutes without knowing any weft vocabulary — and *learns* the slice language
by using the GUI. One surface: a filterable, pivotable data table over the stage.
Everything else (prim detail, graph, certification) hangs off wherever you are in
that surface.

## The problem we're fixing

The v1 Loom shipped five surfaces sitting next to each other — profile, a table, a
relationship graph, a query box, a pull/certify box — with no spine telling you
what to do first. The graph greeted you (and on a real scene showed "too large" or,
worse, a blank canvas from a render crash). Clicking explored into a root-centric
hierarchy-walker heavy with controls. A new user who doesn't know to search "jar"
has no entry point. Verdict from driving it on ALab: *"this whole thing feels
unusable, I don't get what I'm seeing."* Correct. The surfaces never added up to one
thing.

## The spine — one sentence

**Land on the scene as data → organize it by any dimension → filter to a slice →
inspect a prim → certify or graph the slice.**

Every surface is a view of one shared thing: the **current slice** (the set of prims
currently in hand — the whole stage until you narrow it). It flows table → card →
graph → certify. Nothing is a separate mode.

## Information architecture

```
┌───────────────────────────────────────────────────────────────┐
│ PROFILE (header): context · N prims · % behind payloads ·       │
│                   follow-able relationship kinds                │
├───────────────────────────────────────────────────────────────┤
│ EXPRESSION BAR:  where:bbox_volume>1e6  where:purpose=render │ ← live, editable
├───────────────────────────────────────────────────────────────┤
│ Organize by: [ Hierarchy ▾ ]     Sort: [ bbox ▾ ]   Columns:…   │
├───────────────────────────────────────────────────────────────┤
│ ▾ /root/alab_set01              Xform    ·        —             │
│   ▾ lab_electronics01_0001      Xform    ·        —             │ ← the pivot table
│     ▸ bench01                   Xform    ·        12.4 m³       │   (the star)
│       construction_cinder…      Xform    behind   1.2 m³  →card │
├───────────────────────────────────────────────────────────────┤
│ SLICE BAR (only when narrowed): 138 prims · 142 m³              │
│                       [ lock this slice ]  [ view as graph ]    │
└───────────────────────────────────────────────────────────────┘
          PRIM CARD opens as a right drawer on row click.
          GRAPH opens as a summoned view, never a resident pane.
```

## Component 1 — The pivot table (the star)

The stage as a dataset. Rows are prims; columns are USD data. This is the thing you
land on and the thing that carries both earlier instincts — "show the hierarchy" and
"show the whole data table" — because hierarchy is just the *default grouping*, not
the structure.

**Rows.** Projected from the already-open stage with `data.project` at the cheap tier
(no payload load): path/name, type, has_payload, bbox_volume, centroid. Expensive
columns (point_count, poly_count, byte_cost) populate only after an explicit load,
exactly as `weft data` already tiers them. `attr:<name>` columns surface any authored
attribute or primvar.

**Organize by (the pivot dimension).** A selector whose default is Hierarchy:

| Dimension | Grouping key | Cost |
|---|---|---|
| **Hierarchy** (default) | path prefix → indented collapsible tree | cheap |
| **Type** | prim type (Mesh, Xform, Material…) | cheap |
| **Material** | bound material (`material:binding:full`) | *expensive* (needs load) |
| **Purpose** | `purpose` | cheap |
| **Payload status** | behind-payload vs loaded | cheap |
| **Attr / primvar** | value of any authored attr (`subdivisionScheme`, a primvar…) | cheap |
| **Bbox bucket** | bbox_volume bucketed | cheap |

Grouping collapses rows into expandable groups by that key's value; each group shows
its member count and a cheap aggregate (e.g. summed bbox). Hierarchy renders as the
familiar path-indented tree; every other dimension renders as flat groups.

**Sort** is orthogonal to grouping: within any grouping, order rows (and groups) by
any numeric column.

**Collapsed by default, lazy-expanded.** ALab is 4,541 unloaded / 47,401 composed
prims; the table shows top-level groups collapsed and expands on demand so nothing
dumps 47k rows at once.

## Component 2 — The prim card

Opens as a right-hand drawer when you click a row. Answers the plain question the
graph never did: *what is this prim, and what is it wired to?*

Contents:
- **Identity**: path, type, payload status.
- **Data**: bbox, centroid, and authored attrs/primvars worth showing.
- **Relationships** — a plain labeled list, derived with the existing `relkinds` /
  derive machinery:
  - `material:binding:full → /root/.../mtl/cinderBlock_surfacing`
  - `material:binding:preview → /root/.../mtl/cinderBlock_preview`
  - collections it belongs to; any native authored relationships.
- **Actions**: *view as graph* (the slice graph, demoted to here), *pull just this*
  (a `path:` slice → certified digest), *copy path*.

No lenses, no "pull / load / reveal / +1 level." Reading, not operating.

## Component 3 — The live expression bar (the teacher)

A single text field at the top of the table that is always the weft-ask expression
for the current organize + filter + selection state. **Bidirectional:** a GUI gesture
writes to it; editing the text re-drives the table. Beginners read it like subtitles;
power users start typing it. The word "slice" and the DSL both arrive *after* the user
has already made one by clicking.

**Authoritative gesture → expression mapping** (grounded in `weft/ask.py`):

| GUI gesture | Expression written | Grammar support |
|---|---|---|
| Click a prim row | `path:/root/.../cinder_block` | `path:` seed |
| Name filter | `name:jar*` (fnmatch glob) | `name:` seed |
| Numeric column filter | `where:bbox_volume>1e6` | `where:<metric><op><n>`, selectable metrics |
| Facet filter on any authored attr | `where:subdivisionScheme=catmullClark` | `where:<attr>=<value>` |
| Spatial box / proximity | `within:x0,y0,z0,x1,y1,z1` · `near:bench,50` | `within:` / `near:` seeds |
| Follow a relationship forward | `follow:usd:material:binding:full` | `follow:` (compose) |
| Depth bound | `depth:2` | `depth:` (compose) |

Hand-typed expressions that don't round-trip to clicks still drive the table; a parse
error (ask.py raises `ValueError` with guidance) shows inline under the bar, table
unchanged.

**Coverage map — the honest part.** Some organize-by dimensions have *no* expression
yet. Rather than hide them, the bar shows a caption and the dimension still works in
the GUI:
- **Organize by Type** → `(organizing by Type — no slice expression yet; prim type
  isn't a seed predicate)`
- **Pick a Material group** → a *reverse* relationship lookup ("all prims bound to
  X"); `follow:` only goes forward → `(GUI-only — no reverse-follow expression yet)`

These captions make the GUI a living spec for what the grammar should grow
(`type:` seed, a reverse/`bound-by:` follow). The GUI stops being a toy on top of the
DSL; the two keep each other honest. **Growing the grammar to close these gaps is out
of scope for this spec** (tracked below).

## Component 4 — Slice is the unit

Any active filter or selected group *is* a slice — a certifiable, graphable,
exportable set — with no expression typed.

- **Slice bar** appears whenever the current view is narrower than the whole stage:
  member count, a cheap aggregate, and `[ lock this slice ]`, `[ view as graph ]`,
  `[ export ]`.
- **A group under "organize by" is a slice** (its member set). Expand
  `cinderBlock_surfacing (84 prims)`, hit lock, get a digest.
- **Lock** reuses `compose.compose` + `manifest` (the existing `/pull` path) to
  produce the self-certifying digest. **Graph** reuses `/viewer?expr=` (slice graph,
  with the dangling-edge fix already landed). **Export** reuses the static bundle.

## Data flow

1. **Startup**: open stage `LoadNone`; `profile()`; project the cheap table once.
2. **Organize / sort / filter**: recompute from row data client-side where the data is
   already present (hierarchy/type/attr/bbox/payload grouping, numeric sort,
   name/attr filter). A filter needing a metric not yet fetched, or an expensive
   dimension (real material binding, point counts), calls `/data` with
   `columns`/`select` after a confirm-to-load prompt.
3. **Click row**: `GET /card?path=…` → prim-card JSON.
4. **Slice actions**: `POST /query` (members), `POST /pull` (certify),
   `GET /viewer?expr=…` (graph) — all existing.

## Endpoints

Keep: `/`, `/profile`, `/data`, `/query`, `/pull`, `/viewer`, static `export`.

**New:** `GET /card?path=<path>` →
```json
{ "path": "...", "type": "Xform", "payload": true,
  "bbox_volume": 1.2, "centroid": [x,y,z],
  "attrs": { "purpose": "render", "subdivisionScheme": "catmullClark" },
  "relationships": [ { "kind": "usd:material:binding:full", "target": "/root/.../mtl/x" } ] }
```
Thin wrapper over `data.project([path])` + `relkinds` derivation for that one prim.
Never 500s; returns `{ "error": "..." }` on a bad path.

Grouping stays client-side (the server returns rows, not groups) to keep the server a
thin data source and grouping instant.

## Error handling

- **Expensive dimension/column without load** → inline "load N prims to organize by
  material" prompt, never an auto-load and never a crash.
- **Bad hand-typed expression** → ask.py's `ValueError` text shown under the bar;
  table unchanged.
- **Slice too big to graph** → existing `GRAPH_EDGE_CAP` "go deeper" page; cross-slice
  edges already handled by the landed `_close_dangling` fix.
- **Unmapped dimension** → "(no slice expression yet)" caption; GUI still works.
- **Bad `/card` path** → `{ "error": … }`, drawer shows it.

## Testing

- `test_card` — `/card` returns identity + data + derived relationships for a bound
  mesh; bad path returns an error, not a 500.
- `test_pivot_grouping` — project then group by hierarchy / type / attr; groups and
  member counts are correct; expensive dimension without load is flagged, not faked.
- `test_expression_roundtrip` — a set of GUI states → expected expression strings, and
  `parse_expression(expr)` → the same member set (the bidirectional contract).
- `test_coverage_gaps` — organizing by Type and picking a Material group yield the
  "no expression yet" marker, not a crash or a wrong expression.
- All existing loom tests (profile / graph / data / query / pull / slice / export)
  stay green.

## What we keep from v1

Read-only stance, 127.0.0.1 bind, engine-wrapper thinness, static `--export`, the
graph viewer (now summoned, not resident), `GRAPH_EDGE_CAP`, and the `_close_dangling`
slice fix.

## Out of scope / YAGNI

- **Growing the grammar** to close the coverage gaps (`type:` seed, reverse/`bound-by:`
  follow) — tracked, separate plan. This spec only *surfaces* the gaps.
- Authoring of any kind (weft consumes, it does not author).
- The B similarity facet.
- Packaging the viewer HTML into the wheel (existing follow-up, unchanged).

## Tracked grammar gaps (for a later plan)

1. `type:<Schema>` seed — organize/filter by prim type as a first-class predicate.
2. A reverse-follow (`bound-by:` / `incoming:<kind>`) — "all prims that point at X",
   which makes every "organize by relationship" group a typed expression.
