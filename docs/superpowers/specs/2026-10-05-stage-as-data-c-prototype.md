# Stage-as-data: the C prototype (prim-level numeric projection) — build spec

**Status:** draft for owner review, 2026-10-05. The smallest *real* slice of
the "USD stage approachable as data" direction (brainstorm 2026-10-05): project
a prim set to a prim-level numeric table, add one numeric predicate to the ask
grammar, and emit the table as rows / numpy / Arrow. Deterministic only — the
certified core. Learned vectors (B) and element-level tensors are out of scope.

**Goal:** make a stranger able to *query a USD stage as data* in one command —
`weft data scene.usda --select 'bbox_volume>50000'` prints a table and a
surgical set, with no authored `weft:` attributes and no full load.

## Why this shape

Two facts from the current code decide the design:

1. **The grammar already reserved this.** `ask.parse_seed` allows only `=` in
   `where:` and raises on `<`, `>`, `~`, `!`, `&` as "reserved" (weft/ask.py:10,
   33-35). The numeric predicate is activating a slot that was left open, not a
   new syntax.
2. **Cheap numerics without loading already work.** `resolve_seeds` opens the
   context `LoadNone` and `spatial_candidates()` reads `extentsHint` + a
   `UsdGeom.XformCache` world transform to place prims *without crossing any
   payload* (weft/ask.py:154-160). The same pattern gives bbox volume, extent
   dims and world centroid for free — the "cheap" column tier.

So selecting by cheap numerics stays **surgical** (no load to filter), and the
expensive columns (point/poly counts) are computed only once geometry is
present. That cheap→expensive split is the whole "use data to decide what to
load" ethos, applied to the data itself.

## 1. The metric registry (`weft/data.py`, new)

A fixed, ordered registry of deterministic columns. Each entry:
`{name, tier: "cheap"|"expensive", dtype, fn(prim, ctx) -> value|None}`.

v1 columns:

| name | tier | from | notes |
|---|---|---|---|
| `path` | cheap | `prim.GetPath()` | the row key (string) |
| `type` | cheap | `prim.GetTypeName()` | string |
| `has_payload` | cheap | `prim.HasAuthoredPayloads()` | bool |
| `centroid_x/y/z` | cheap | `XformCache` translation, or `extentsHint` center | 3 cols |
| `bbox_volume` | cheap | `extentsHint` × world xform (as in `spatial_candidates`) | `None` if no `extentsHint` |
| `point_count` | expensive | sum of `points` over the subtree's PointBased gprims | needs geometry loaded; see aggregation note |
| `poly_count` | expensive | sum of `faceVertexCounts` over the subtree's meshes | mesh geometry only |
| `byte_cost` | expensive | `point_count*12 + poly_count*4` (rough) | a load-cost estimate |

**Expensive metrics aggregate over the prim's subtree** (self + descendants),
because a placement is a container whose geometry lives in child gprims (ALab,
and the demo bench). Two honest `None` cases, never a misleading `0`: (a) an
**unloaded payload** anywhere in the subtree makes the count unknown-without-
loading; (b) **no mesh/point geometry** in the subtree (e.g. implicit
`Cube`/`Cylinder` surfaces, or a pure container) makes a mesh metric
not-applicable. The subtree walk uses the load-agnostic predicate
(active/defined/non-abstract) so an unloaded placement is still *seen* and
flagged, not silently skipped. (Cheap `bbox_volume`/`centroid` stay per-prim
from the prim's own `extentsHint`; only the counts aggregate.)

A column's `fn` returns `None` when it cannot be computed on the current
composition (expensive column on an unloaded prim, `bbox_volume` with no
`extentsHint`). `None` is honest, never a fabricated 0.

`ctx` carries the shared `XformCache` (and, later, a `BBoxCache`) so a whole
projection reuses one cache — same pattern as `resolve_seeds`.

## 2. The projection API (`weft/data.py`)

```python
def project(stage, paths=None, columns=None) -> Table:
    """Prim-level numeric table over `paths` (default: every active/defined/
    non-abstract prim, instance proxies included -- the resolve_seeds
    traversal). `columns` defaults to the cheap tier; naming an expensive
    column includes it (None where the prim isn't loaded). Never loads
    anything itself -- the caller controls load state (surgical)."""
```

`Table` is a tiny columnar holder, pure-Python core:

- `Table.names -> list[str]`, `Table.rows() -> list[dict]` — always available,
  zero deps (keeps the **bare** CI green).
- `Table.to_numpy() -> dict[str, np.ndarray]` — imports numpy lazily; raises a
  clear error if absent.
- `Table.to_arrow() -> pyarrow.Table` and `Table.to_parquet(path)` — lazy
  pyarrow; clear error if absent.
- `Table.to_csv(path)` / `Table.to_json(path)` — stdlib, always available.

numpy/pyarrow stay **optional** (import inside the method), matching the repo's
bare-vs-full CI split: bare tests rows()/csv/json; full tests numpy/arrow.

## 3. The numeric predicate (`weft/ask.py`)

Extend `parse_seed`'s `where:` branch: when the key is a registered metric,
allow the comparison operators; otherwise keep today's `=`-only facet behaviour
and the reserved-operator error.

- New syntax: `where:<metric><op><number>`, `op ∈ {>, <, >=, <=, ==, !=}`.
  Example: `where:bbox_volume>50000`, `where:point_count>=1000`.
- New `Seed(plane="metric", key=metric, value="<op><number>")`. `~` and `&`
  stay reserved. A `<`/`>` on a *non-metric* key still raises (unchanged).
- Resolution: add an `elif s.plane == "metric":` branch to `resolve_seeds`. It
  `project(stage, <candidate prims>, columns=[metric])`, then keeps the paths
  whose value satisfies the comparison. **v1 restriction:** a `metric` seed must
  name a **cheap** column (so selection never forces a load — the surgical
  guarantee). Naming an expensive metric in a seed raises with a message
  pointing at `weft data --load` for tabulation. Expensive columns are thus
  *tabulated*, cheap columns are *selectable* — a clean, honest v1 line.

A resolved `metric` seed feeds the existing `pull` pipeline unchanged: its paths
become seeds, so `weft pull 'where:bbox_volume>50000'` yields a **surgical
stage** of exactly the heavy prims. No `pull.py` change.

## 4. The CLI (`weft/cli.py`)

One new verb:

```
weft data <context.usda>
    [--select 'where:<metric><op><n>']   # filter rows (cheap metric only, like a seed)
    [--columns a,b,c]                    # default: cheap tier; add expensive names here
    [--load]                             # load the (selected) prims first, so expensive cols populate
    [--out FILE.{csv,json,parquet}]      # default: pretty table to stdout
```

Flow: open `LoadNone` → resolve `--select` to paths (cheap, no load) → if
`--load`, `stage.Load` those paths → `project(stage, paths, columns)` → print or
write. Without `--select` it projects every prim (cheap tier) — "describe this
stage as data" in one call.

## 5. Files

- **Create** `weft/data.py` — registry, `project`, `Table`. pxr + stdlib core;
  numpy/pyarrow lazy-optional.
- **Modify** `weft/ask.py` — `parse_seed` metric branch; `resolve_seeds` metric
  resolution (reusing the `spatial_candidates` cheap-numeric pattern).
- **Modify** `weft/cli.py` — the `data` verb.
- **Create** `tests/test_data.py` — see below. No change to `pull.py`,
  `manifest.py`, `compose.py`.

## 6. Testing (TDD)

- `project()` on a fixture stage → exact cheap values (type, has_payload,
  bbox_volume from a known `extentsHint`, centroid from a known xform).
- Expensive columns: `None` on a `LoadNone` prim; correct `point_count` /
  `poly_count` after `stage.Load`.
- `parse_seed`: `where:bbox_volume>5` parses to a `metric` seed; `where:foo~bar`
  still raises; `where:finish=translucent` still a facet seed (no regression).
- `resolve_seeds`: `where:bbox_volume>V` returns exactly the prims above `V`,
  computed with no load (assert `not prim.IsLoaded()` throughout). An expensive
  metric in a seed raises the pointing error.
- `Table`: `rows()`/`to_csv`/`to_json` with no optional deps (bare CI);
  `to_numpy`/`to_arrow` guarded by `pytest.importorskip` (full CI).
- **Acceptance (bench, then ALab):** `weft data scene.usda --select
  'where:bbox_volume>50000'` selects the furniture (big boxes), not the beakers;
  `--load --columns poly_count,point_count` fills those columns for the selected
  set; `--out table.parquet` round-trips through pyarrow.

## 7. Storage & recompute cost

**v1 stores nothing.** The projection is computed on read; `--out FILE` writes a
file the *user* owns, not state weft manages. No cache to invalidate, nothing
authored back into the stage — no preconditioning.

**Is recomputing every call costly? Split by tier:**

- **Cheap tier** (`type`, `has_payload`, `bbox_volume` from `extentsHint`,
  `centroid`): `O(prims)` metadata reads + one `XformCache` lookup each — the
  same work `resolve_seeds` already does on every `pull`, i.e. interactive
  (thousands of prims → single-digit ms; 100k → tens-to-hundreds of ms).
  Recomputing it per call is a non-issue. (`bbox_volume` is cheap *only* when
  `extentsHint` is authored; otherwise it is `None`, not a silent geometry load.)
- **Expensive tier** (`point_count`, `poly_count`, `byte_cost`): the cost is
  **loading the payload**, not the `len()` after it. In the surgical workflow
  the prims you care about are **already loaded** (you pulled them), so expensive
  metrics on that set are near-free. Real cost only appears in the anti-pattern
  the design discourages — expensive metrics across a *large, unloaded* set —
  which is why **selection uses cheap metrics (decision 1)**.

**v2 — content-addressed cache (deferred; a pure optimization, not a redesign).**
When the three pains below bite, store the table as a blob in the existing
`store.ObjectStore`, keyed by

```
table_id = sha256( manifest.digest(slice) + sorted(column_set) + usd_version )
```

Because the key *is* the slice's content identity, the cache is
**self-invalidating** (a changed layer changes `layer_hashes` → `digest` → key →
miss → recompute; a stale table is simply unaddressable, so there is no
invalidation logic to write) and **certifiable** (the table is addressed by the
same hash that certifies the slice). It is one more object in the store weft
already has — not a database. Adding it changes no numbers, so v1-ephemeral is
not a decision to regret. It earns its keep only for: (a) expensive metrics over
a large *unloaded* set queried repeatedly; (b) enormous stages (100k+ prims,
PointInstancers) where even the cheap pass is seconds; (c) cross-session reuse.

**Tier 3 — author-back (opt-in only, never default).** `weft data --author`
writes derived numerics into a sidecar `.weft` layer (`weft:data:*`), as
`extract.py` already does for interfaces, so the data travels with the asset for
non-weft tools. This is preconditioning: baked values go stale against source
and mutate the asset, so it is always opt-in, labelled "derived", and carries
the source `digest` so a consumer can detect staleness.

## 8. Certification tie-in (note, not v1 work)

The projection is deterministic, so a numeric query's result set is reproducible
and flows through the existing `manifest`/`verify` unchanged — the slice of
matching prims is certified exactly as any other pull. No new certification code
in v1; just the one-line observation that `where:bbox_volume>V` is a certifiable
selector.

## 9. Explicitly out of scope (named next steps)

- **Element-level tables / tensors** — one row per point/instance, point-cloud
  and `PointInstancer` transforms as (N,3)/(N,4,4). The sim/ML payoff; v2.
- **Expensive-metric selection** — a cheap→expensive two-phase *scheduler* that
  loads candidates to filter by `poly_count`. v1 tabulates expensive, selects
  cheap.
- **Time-sampled metrics** — a metric over the time axis (animation as a series).
- **Learned vectors (B)** — embeddings / `near:<ref> threshold:` as a pluggable,
  explicitly non-certified facet. Separate spec.
- **Derived feature vectors** — classical shape descriptors (the deterministic
  bridge toward B). Separate spec.

## 10. Decisions (settled 2026-10-05)

1. **Cheap selects, expensive tabulates.** A grammar `metric` seed must name a
   cheap column, so selection never breaks the no-load-to-filter guarantee.
2. **`None`, never fabricated zero**, for an uncomputable metric.
3. **numpy/pyarrow optional** — pure-Python rows/csv/json is the floor; the
   bare CI must stay green with neither installed.
4. **Reuse, don't rebuild** — the projection uses the existing `resolve_seeds`
   traversal and `XformCache` cheap-numeric pattern; `pull`/`manifest` unchanged.
