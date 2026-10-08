# derive-real: relationships and facets from native USD, no authoring

**Date:** 2026-10-06. **Why:** preconditioning is the make-or-break for "USD as
data." Today it reads as a *tax paid before any value* (author `weft:` attrs,
then get a data layer), which kills the 10-minutes-on-unseen-USD bar. This spec
inverts it: make the **zero-authoring floor already deliver real relationships
and facets**, computed from native USD, so authoring becomes *enrichment*, not
*entry*. The numeric half of this floor already shipped (`weft data`); this is
the relationship/facet half. The forthcoming workbench UI (**the Loom**) is the
consumer — this spec is its data substrate, not the UI.

## The derive ladder (and the one rule)

The governing rule, stated by the owner: **derive only what the data genuinely
encodes; keep judgment authored — mechanical at the data, deliberate at the
rule.** Three tiers fall out:

1. **Auto-derived (pure, zero config):** a relationship the data *is* — a
   material binding, a collection, a composition arc. No judgment, so it runs on
   every stage with no declaration. Certifiable.
2. **Rule-derived (declared, one line):** a facet the data *implies under a
   stated rule* — opacity below a threshold → "translucent". The application is
   mechanical; the threshold is a judgment, so it lives in a `weft__kinds`
   `derive` declaration, not baked in. Certifiable given the rule.
3. **Mined (out of scope here):** inference that needs curation — a mount from
   bbox contact. Named for later; never auto, never silent.

Proof the pattern already works: `CollectionKind` (relkinds.py) derives every
`UsdCollectionAPI` on the stage automatically today. derive-real extends tier 1
to the other universal signals and ships tier 2's first real rule.

## Derivation surface — what we read, and how deep

weft derives **two different things from two different surfaces**; conflating
them is what makes "what do we derive" feel murky.

| | **Relationships** (thread graph / lenses / `pull`) | **Data** (`weft data` table) |
|---|---|---|
| answers | how prims *relate / group* | what a prim *measures / says* |
| surface | USD's **typed semantic constructs** | a prim's **attribute / primvar / metadata values** |
| depth | the composition + relationship graph, followed per pull `depth`/`follow` | the prim itself (+ optional subtree aggregation) |

**Auto-derived relationships come ONLY from constructs with one unambiguous
meaning in the USD data model** — composition arcs (reference/payload/inherit/
specialize), relationships (`rel`, incl. `material:binding`), and collections.
No judgment, identical across every DCC. Material binding resolves through USD's
own inheritance (`ComputeBoundMaterial`) and is bounded by load state (a binding
inside an unloaded payload isn't seen until that subtree is pulled — lazy-
consistent). That is the whole auto-relationship surface.

**Everything else is data, not a relationship.** Subdivision tokens
(`subdivisionScheme`), creases/corners, arbitrary primvars, and "authored in DCC
X" provenance metadata are **values**, surfaced (where asked) as `weft data`
columns — never auto-turned into lenses. Auto-faceting every token value would
mint thousands of meaningless lenses and destroy trust in the layer.

**The promotion rule (the derive/author line, stated sharply):** a *value*
becomes a *facet/relationship* — joins the lens + `pull` layer — **only by a
`weft__kinds` declaration**, never automatically, because "does this value
define a group worth pulling?" is a judgment and *which* key is pipeline-
specific. `subdivisionScheme is a facet`, or `the pipeline:sourceApp key is a
facet`, is one declared line; until then it is queryable data, not a lens. weft
never guesses provenance: there is no universal "which DCC" field, so it is
declared against your key or it is nothing.

This narrowness is the design, not a gap: auto-derive stays trustworthy and
DCC-agnostic *because* it only touches one-meaning constructs; all else is free
data or one declaration from being a facet.

## What to build

### Tier 1 — `MaterialBindingKind` (new, native, in the default REGISTRY)

The universal shading relationship, from `UsdShade` — not the ALab interface
convention the current `ShadingKind` reads.

- For each visited prim, `UsdShade.MaterialBindingAPI(prim).ComputeBoundMaterial()`
  (direct binding; collection-based bindings are a named follow-up). If bound,
  the material is a **facet node** `material:<name>` and the prim gets an edge to
  it — same facet shape as finish/shading, so it is a lens and `pull`/`weft data`
  consume it unchanged.
- Pure derive (a binding is a binding), deterministic, certifiable. Runs on any
  stage with zero authoring: point weft at a stranger's USD and "everything bound
  to material X" is immediately a thread and a selectable set.
- **Lazy-honest caveat:** a binding authored inside an *unloaded* payload isn't
  visible at the pull's load state, so it isn't derived until that subtree is
  pulled. derive sees what composition sees — consistent with weft's whole stance.

### Tier 2 — `opacity-finish` deriver (new, first entry in `BUILTIN_DERIVERS`)

The first real rule-deriver, dispatched by a `weft__kinds` `derive` declaration:

```json
{"kind": "finish", "structure": "facet",
 "population": {"derive": {"builtin": "opacity-finish", "threshold": 0.999,
                           "surface_input": "opacity"}}}
```

(The declared `kind` must be a *distinct* id — the loader refuses one that
shadows a built-in, so a derived finish can't reuse `weft:bind:finish`; it is
its own lens, which also keeps derived finish distinguishable from authored.)

- For each prim's bound material, read the `UsdPreviewSurface` `inputs:<surface_input>`
  (default `opacity`); `< threshold` → facet `finish:translucent`, else
  `finish:opaque`. Reuses the logic already in `extract.py::finish`, generalised
  to the natively-composed bound material instead of a passed look-layer.
- The **threshold and input are the judgment**, and they live in the declaration
  — so this is deliberate, per the rule. It is **not** added to the default
  REGISTRY (no baked-in judgment of what "translucent" means).
- **Honesty, from the ALab finding:** where opacity is not authored, finish is
  `None` — derive does **not** fabricate a finish the data doesn't carry (ALab's
  7/8 curated-translucent assets stay a *read* facet, authored, exactly as
  today). This is the derive/author boundary made concrete.

### Tier 1 — collections: already done

`CollectionKind` already derives `UsdCollectionAPI` natively. No change; cited
here as the template `MaterialBindingKind` follows.

### Data side — named-attribute columns (so "arbitrary attrs" are answerable)

So a subd token, a custom primvar, or a provenance key is surfaced *as data*
without being faceted, `weft data` gains a dynamic column form: a column named
`attr:<name>` reads that authored attribute/primvar off each prim (cheap — no
payload load for values authored at the placement; `None` where unauthored).
Example: `weft data scene.usda --columns type,attr:subdivisionScheme` or
`--columns attr:primvars:sourceApp`. This is the concrete answer to "will we
capture subd/primvar/DCC-metadata": **yes, as queryable data columns; never as
auto-relationships.** Value type is preserved for scalars; array-valued attrs
report their length (the datum that fits a table cell), the array itself left to
a later tensor-extraction mode.

## How it plugs in

- `MaterialBindingKind` → add to `relkinds.REGISTRY` (auto, like `CollectionKind`).
  It participates in `build_graph`, becomes a lens, and its facet nodes feed
  `pull` (pull-by-material) and `weft data` with no further wiring.
- `opacity-finish` → add the class to `kinds.BUILTIN_DERIVERS` under that name;
  the existing `load_kinds` derive-dispatch (kinds.py) already routes a
  `derive:{builtin:...}` declaration to it, carrying the declared `threshold`/
  `surface_input` as kwargs. (The dispatch scaffold exists; this fills it.)
- No change to `pull`, `manifest`, `compose`, or the cache — derived kinds are
  ordinary kinds; their members certify through the existing manifest path.

## Certification

Every derive-real output is deterministic: given the same composed stage (and,
for tier 2, the same declared rule), the derived relationships/facets are
reproducible, so a pull that follows them certifies through `manifest`/`verify`
unchanged. A tier-2 facet records its rule in the declaration, so "this finish
facet = opacity<0.999 on these prims" is reproducible and auditable — judgment
visible, not hidden.

## Files

- **Modify** `weft/relkinds.py` — add `MaterialBindingKind` (UsdShade binding →
  material facet); register it in `REGISTRY` / `LENS_ORDER`. Needs a `UsdShade`
  import (lazy, inside the kind, like the others).
- **Modify** `weft/kinds.py` — add the `opacity-finish` deriver class and
  register it in `BUILTIN_DERIVERS`; confirm `load_kinds` passes declared kwargs.
- **Modify** `weft/extract.py` (optional) — factor its `finish()` opacity logic
  into a small helper both it and the deriver call, so the rule lives once.
- **Modify** `weft/data.py` — accept an `attr:<name>` column that reads that
  authored attribute/primvar per prim (scalar value, or array length); unknown
  attrs resolve to `None`, not an error.
- **Create** `tests/test_derive_real.py`.

## Testing (TDD)

- `MaterialBindingKind` on a fixture with two prims bound to one material → one
  `material:<name>` facet node, two edges; an unbound prim contributes nothing;
  a binding behind an unloaded payload is absent until the prim is loaded.
- `opacity-finish`: a declared rule on a fixture with `inputs:opacity = 0.5` →
  `finish:translucent`; `1.0` → `finish:opaque`; no authored opacity → the prim
  is absent from the finish facet (not fabricated).
- Golden-parity: `build_graph` on the existing fixtures is unchanged except for
  the new material facet (the byte-for-byte golden gets a documented update).
- **Acceptance on ALab (measured 2026-10-07, mystery solved):** the first probe
  found only 2 bound gprims and I wrongly guessed "collections." Measuring
  properly: **ALab binds materials per USD *purpose* (`full`/`preview`) and by
  inheritance, not all-purpose** — 7,500 gprims resolve a `preview` material,
  6,141 a `full` one; all-purpose is the 2 anomalies. `MaterialBindingKind` is
  therefore **purpose-aware**: `ComputeBoundMaterial(purpose)` for `full` and
  `preview` (resolving inheritance + the all-purpose fallback), each purpose its
  own lens. On ALab `build_graph` this lights up the full material graph — **6,141 full / 7,500 preview**
  relationships (810/1,207 distinct materials) — by traversing **instance
  proxies** (79% of ALab is instanced) and collapsing each proxy material to its
  **prototype** identity so instances of an asset share one material node (naive
  proxy paths would explode 2,016 → 5,141 nodes). vs 2 before. Remaining honest
  note: at `LoadNone` the bindings sit behind payloads, so material
  relationships appear as geometry is pulled/loaded — lazy-consistent, like the
  numeric expensive tier.

## Out of scope (named next steps)

- **The Loom** — the "USD as data" workbench UI that surfaces these derived
  relationships live (see → derive → declare → query). Its own spec; this is its
  substrate.
- **Instance-proxy coverage** — DONE for `MaterialBindingKind` (traverses
  proxies, prototype-shared nodes). `CollectionKind`'s member resolution could
  take the same treatment if a scene needs instanced collection members.
- **Collection-based material bindings** (vs purpose/direct) — a further binding
  path, if a scene uses it (ALab does not).
- **Learned similarity (B)** — the fuzzy, non-deterministic top layer; only
  worth building once this deterministic floor exists.
- **Mining** (tier 3) — geometric/structural inference that needs curation.
