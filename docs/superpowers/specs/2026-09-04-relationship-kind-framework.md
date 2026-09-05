# The relationship-kind framework (the pivot) — and why its v1 *is* the on-ramp

**Status:** design draft for owner review, 2026-09-04. The pivot named in the
north star (`2026-09-04-weft-north-star.md`): generalize weft's hardcoded
relationships into one declarable unit. Written so the framework *leads* and the
on-ramp is built *as its first instances* — so designing the framework reshapes
the on-ramp by construction, not by later rework (owner's "let one inform the
other").

## The unit

> **A weft relationship kind = (type, population, composition/resolution).**

- **type** — an id + meaning: `usd:arc` (hierarchy), `usd:collection`,
  `material` (shading), `weft:mount`, or a team's own (`powered-by`, …). Plus
  display metadata (label, color, whether it's a facet/structural kind).
- **population** — how members/edges are found, one of:
  - **derived** — computed by *reading native USD* (composition, `material:binding`,
    `UsdCollectionAPI`, `kind`, `purpose`, `assetInfo`). Zero prep.
  - **authored** — declared into a **weft sidecar** (never the stage), for axes
    USD can't express (`weft:mount` carriers, team contracts). This is
    "pre-conditioning," now just one population mode.
- **composition/resolution** — what *pulling* this kind does: today, resolve its
  member set (→ the existing `load_set` seam / a population mask). Later, drive
  LIVRPS (dynamic payloads, the resolver) to *compose* a bespoke stage. This
  clause is the socket the engine plugs into.

Same unit whether a relationship is read or authored — that is exactly the
owner's "derive and declare are the same mechanism; gateway now, authoring
later."

## The registry

`build_graph`'s hardcoded passes become a **registry of relationship kinds**.
Each kind implements a small interface:

```python
class RelationshipKind:
    type_id: str
    facet: bool                 # facet-node kind vs structural edge kind
    display: dict               # label, color, ...
    def populate(self, stage, ctx) -> Iterable[Edge|Member]: ...   # derive or read-authored
    def resolve(self, members, stage, ctx) -> set[SdfPath]: ...    # what a pull loads/composes (v1: the set)
```

`build_graph` becomes a thin driver: run the registered kinds' `populate`,
assemble nodes/edges/kinds. Pulling a kind calls its `resolve` through the
existing rule→set→load seam. Adding a relationship = registering a kind; no core
change. **That refactor is the "rethink the on-ramp" the owner anticipated** —
the current bespoke finish/shading/mount passes migrate into registered kinds.

## Existing relationships, re-expressed as instances (the reframe)

| kind | population | note |
|---|---|---|
| `usd:arc` (hierarchy) | **derived** (composition children) | already free |
| `usd:collection` | **derived** (`UsdCollectionAPI`) | **on-ramp — priority** |
| `material` (shading) | **derived** (`material:binding`) | **stop authoring; read native** |
| `finish` | derived *if* mechanical, else **authored** | the test case for derive-vs-declare |
| `weft:mount` | **authored** (sidecar carriers) | the axis USD can't express — pre-conditioning earns its keep here |

The insight the framework makes concrete: shading was being *authored* when it's
*derivable*; collections were *unused* when they're *free*. The framework moves
both to **derived**, shrinking authored pre-conditioning to only the
irreducible (mount, team contracts).

## Why v1 of the framework *is* the on-ramp

This is the reconciliation of "parallel, but one informs the other." Deliver the
framework in the order that also delivers the on-ramp:

**v1 — the registry + the DERIVED path + the first derived kinds.**
- The `RelationshipKind` interface + registry + `build_graph` refactored to a driver.
- Derived kinds shipped: `usd:collection` (the priority — respect what teams
  already authored), `material` (native binding → the shading lens, no more
  sidecar), and migrate the existing `usd:arc`/finish/shading into the registry.
- Result: **the on-ramp rounds out AND the framework is proven, from the same
  work.** weft now works on unprepped USD via its *existing relationships*,
  through the framework — not a bespoke lens beside it.

**v2 — the AUTHORED path + the util.** The declare side: a small API/util for a
team to register a kind and author its members into a sidecar. `weft:mount`
migrates to being authored through this util rather than hardcoded. This is
where pre-conditioning becomes *authoring*.

**v3 — the COMPOSE/RESOLVE clause → the engine.** `resolve` grows from
"return the member set" to "drive LIVRPS" (population masks now; dynamic
file-format payloads + the as-of resolver later), so pulling a declared
relationship *composes* a bespoke stage. This is where the framework meets the
engine altitude of the north star.

## Supersedes / absorbs

- The standalone **collections-lens spec** (`2026-09-04-collections-lens-ingestion.md`)
  is absorbed here: build the collections lens **as the `usd:collection` derived
  kind**, not as a bespoke `build_graph` pass. Same behavior, framework-shaped.
- The **pre-conditioning** discussion resolves here: it is the *authored
  population mode* (v2), reserved for axes USD can't express.

## Verify (v1)

- The registry driver reproduces today's graph exactly for the existing kinds
  (pin against the ALab acceptance: 152 nodes / 1018 edges must still hold when
  hierarchy/finish/shading run as registered kinds).
- New derived kinds: `material` from native `material:binding` yields a shading
  lens with **no interface-file dependency**; `usd:collection` yields the
  collections lens (per the absorbed spec's tests).
- Adding a throwaway test kind via the registry requires no core edit (proves
  extensibility).
- pxr-gated; suite stays green; nothing authored to the stage.

## Open questions

1. **Derive vs author for `finish`** — resolve the concrete test case: is finish
   mechanically derivable (material transmission/opacity) or a semantic
   judgment? Determines whether it's a derived or authored kind.
2. **How far does v1's `resolve` go** — just the member set (safe, matches
   today), or a population mask immediately (a first taste of surgical
   composition)? Lean: member set in v1, mask when it's cheap, LIVRPS in v3.
3. **Kind identity across the sidecar/stage boundary** — authored kinds live in
   the sidecar keyed by the identity signatures from the drift spec; confirm the
   two designs share one identity model.
