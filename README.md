# jit-sd

**Just-In-Time Scene Description.** A resolution layer that sits *below* USD
composition and turns a stage from a file you open into a query you evaluate.

USD's composition engine is already a pure functional evaluator — LIVRPS is a
deterministic function from a layer stack to a composed stage. What is rigid is
not the evaluator but that **its inputs are static files on disk**.

> JIT-SD keeps USD's evaluator and makes its inputs generated on demand and
> parameterised by who is asking.

```
Consumption    Hydra · Fabric · renderers · game runtimes
Composition    USD — LIVRPS, layers, schemas, payloads        ← unchanged
Resolution     JIT-SD — contracts, channels, baselines, contexts   ← new
Storage        content-addressed objects + append-only ledger
```

**One line:** JIT-SD moves the source of truth from the big files to the small
ones. Today the precious artifact is a 4 GB `hero_car_v037.usd`. Here it is a
3 KB recipe, and the 4 GB is a cache anyone can rebuild.

Not film-specific: the same two phases (Definition / Assembly) exist in games,
manufacturing, AEC and robotics. Not a new format: glTF and USDZ are output
codecs. Not procedural-only: constants are functions.

## Status

Design phase. No implementation yet. These documents capture the architecture
decisions; `docs/08-open-questions.md` lists what is still undecided.

## Read the brief

[`docs/index.html`](docs/index.html) is a single-page design brief covering the
whole architecture — the shareable version. It lives in `docs/`, so enabling
GitHub Pages on that folder serves it directly.

## Documents

| | |
|---|---|
| [`docs/index.html`](docs/index.html) | single-page design brief — the whole architecture, shareable |
| [`docs/01-overview.md`](docs/01-overview.md) | thesis, positioning, the two phases, cross-industry mapping |
| [`docs/02-architecture.md`](docs/02-architecture.md) | layer stack, the two planes, USD integration points, the two clocks, protocol |
| [`docs/03-versioning.md`](docs/03-versioning.md) | revisions / channels / baselines, naming, live WIP |
| [`docs/04-contracts.md`](docs/04-contracts.md) | generators, archetypes, exemplars, bounds, overrides |
| [`docs/05-contexts.md`](docs/05-contexts.md) | claims, the three tiers, declassification, approval |
| [`docs/06-storage.md`](docs/06-storage.md) | the three stores, on-disk layout, Merkle hierarchy, OpenVDB lessons |
| [`docs/07-adoption.md`](docs/07-adoption.md) | the rung ladder, comparisons to USD / Omniverse / Fabric, risks |
| [`docs/09-usd-audit.md`](docs/09-usd-audit.md) | what USD already holds, and what is genuinely absent |
| [`docs/08-open-questions.md`](docs/08-open-questions.md) | what is still undecided |

## Draft specs

| | |
|---|---|
| [`specs/revision-layer.usda`](specs/revision-layer.usda) | what a revision looks like — a 3 KB recipe |
| [`specs/baseline-layer.usda`](specs/baseline-layer.usda) | the evaluation coordinate — a lockfile, not a timestamp |
| [`specs/jitsdContracts/schema.usda`](specs/jitsdContracts/schema.usda) | codeless API schemas for the contract archetypes |

## Core commitments

- **Versions are acts of intent, not moments in time.** The evaluation
  coordinate is a baseline someone decided to cut, never a wall clock.
- **Exactly one mutable object exists: the channel pointer.** Everything else
  is immutable and content-addressed.
- **Couple to contracts, not to names.** Prim paths are an output of
  composition, not a precondition for it.
- **Compatibility is measured, not asserted** — exemplar re-evaluation at
  promotion.
- **Live is viewable, never citable.** Only revisions can be resolved against.
- **No rung may be required for a lower rung to be useful.** It must work solo,
  offline, with zero contracts — like `git init`.
