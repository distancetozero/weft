# jit-sd

**Just-In-Time Scene Description.** A resolution layer that runs *before* USD
composition and turns a stage from a file you open into a query you evaluate.

USD's composition engine is already a pure functional evaluator — LIVRPS is a
deterministic function from a layer stack to a composed stage. USD supplies
every hook for demand-driven resolution and no standard for what plugs into
them; each pipeline builds that layer privately and incompatibly.

> JIT-SD keeps USD's evaluator and compiles its inputs on demand,
> parameterised by who is asking.

```
Consumption    Hydra · Fabric · renderers · game runtimes
Composition    USD — LIVRPS, layers, schemas, payloads        ← unchanged
Resolution     JIT-SD — contracts, channels, baselines, slices     ← new
Storage        content-addressed objects + append-only ledger
```

Not film-specific: the same two phases (Definition / Assembly) exist in games,
manufacturing, AEC and robotics. Not a new format: glTF and USDZ are output
codecs. Not procedural-only: constants are functions.

## Status

A working prototype, validated against real production USD. The design
documents below came first; the implementation now covers most of them, and
where measurement disagreed with the design, the docs record the correction.
`docs/08-open-questions.md` lists what is still undecided.

## What exists

Four subsystems. The first two run on stock USD with no dependency on the rest.

| | |
|---|---|
| `absent/` | finds references that resolve to nothing on a composed stage — the silences USD ships with: stale overrides after a rename, bindings to deactivated materials, targets stripped by encapsulation. None of USD's 28 shipped validators catch these. |
| `deps/` | the dependency graph, including edges no stock USD API reports (material bindings, skel bindings, connections, class arcs) and the reverse direction USD does not have at all: *what breaks if I republish this*. 4,296 ALab layers walked in 1.75 s. |
| `jitsd/` | the engine: content-addressed store, revisions/channels/baselines, contracts with binding attributes, and a promotion gate whose compatibility is **measured** — every consumer re-evaluated against its own tolerance, not just the provider's promise. |
| slices | selection as the query: seeds, closure by relationship kind (`--follow Mount,usd:binding`), team rule sets as versioned content, a cost receipt before anything loads, and cross-slice impact preview. |

**Proven on a production scene** — [Animal Logic's ALab](https://dpel.aswf.io/alab/),
437 props placed on a workbench, contracts derived rather than hand-written
(`examples/alab/`): a shelf moved 0.7 cm passes the provider's 1 cm promise and
is **refused by 19 consumers** whose own tolerances are tighter; seeding one
bottle with `--follow Mount` pulls 2 assets instead of 165, with the other 163
threads declared at the boundary.

```
$ jitsd init                                # a repository, offline, no server
$ jitsd save car car.usda -m "first pass"   # immutable revision, deduped
$ jitsd promote car v002 --to approved      # gated: measured compatibility
$ jitsd select 'chassis*' --follow Mount    # a slice, priced before loading
$ jitsd verify                              # re-hash the store, check pinned code
$ python -m deps breaks ./assets hub.usda   # what depends on this?
$ python -m absent shot.usda                # what silently resolves to nothing?
```

169 tests (107 without `pxr`/numpy — rung 1 needs neither).

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
- **Compatibility is measured, not asserted.** At promotion, every consumer is
  re-evaluated against its own declared tolerance, and the channel refuses to
  move on breakage — built, and demonstrated on ALab, where a change inside
  the provider's promise was refused by 19 consumers.
- **Live is viewable, never citable.** Only revisions can be resolved against.
- **No rung may be required for a lower rung to be useful.** It must work solo,
  offline, with zero contracts — like `git init`.
