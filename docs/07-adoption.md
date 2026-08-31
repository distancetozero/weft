# Adoption, comparisons and risks

## The rung ladder

The constraint that keeps this adoptable:

| Rung | What you add | What it needs |
|---|---|---|
| **1. Solo** | local object store + ledger, auto-versioning, baselines | nothing — no server, no network |
| **2. Solo, many machines** | a remote; push/pull revisions and baselines | a dumb blob store |
| **3. Small team, one asset** | live sync on a WIP channel | a delta relay |
| **4. Multiple teams** | channels, promotion, contracts | + a sequencer |
| **5. Cross-org** | contexts, redaction, exemplar CI | + policy + build workers |

> **No rung may be required for a lower rung to be useful.**

If declaring a contract is a prerequisite for anything working, this dies
before it starts.

## What rung 1 gives one person

Real value, not a promise of future value, with zero collaborators, zero
contracts and zero servers:

1. **Every save versioned, forever, automatically.** No more
   `car_v3_final_FINAL_useThis.usd`.
2. **Storage collapses.** Measured (`bench/dedup.py`, 64 KiB chunks): twelve
   saves of a 16 MiB asset under localised editing cost 1.14x one copy, about
   205 KiB per save. On real USD crate, editing one mesh in a 4000-mesh scene
   costs 0.1% of the file. This is the one people feel on day one — with the
   caveat that a re-export perturbing *every* value deduplicates nothing; see
   `06-storage.md`.
3. **Instant rollback** — a pointer move, no data copying.
4. **Reproducible renders, even solo.** "Why does this frame look different
   from yesterday's" is a daily problem for one person too.
5. **Named checkpoints** — "the version before I redid the topology."
6. **Structural diff** between any two revisions.

```
$ jitsd init                       # creates .jitsd/ — that is it
$ jitsd open car.usda              # or just work in Maya/Houdini/Blender
  … autosave every 30s → immutable revisions, deduped …
$ jitsd log car
  v041   2m ago    ← wip
  v040   18m ago   "before topology redo"
$ jitsd back car v040              # instant
```

## Everyday commands

```
$ jitsd promote hero_car v038 --to review
  ✓ contracts unchanged (MountAPI v2)
  ✓ 14 downstream exemplars re-evaluated, 14 match
  → review now points at v038

$ jitsd open shots/sh0120
  sh0120 · baseline 118 · lighting
  hero_car v37   env_desert v12   rig_key v4

  ! hero_car v38 is now on @approved (baseline 119 available)

$ jitsd try hero_car@wip        # temporary overlay — lock untouched
$ jitsd update hero_car         # take just this one
$ jitsd update --baseline 119   # take the whole new world
```

## vs. plain USD

| | Plain USD | JIT-SD |
|---|---|---|
| Version identity | none — no concept of "as of" | baselines, first-class |
| Coupling between teams | prim paths | declared contracts |
| Provenance | which layer won, and that is all | full derivation |
| Variation | `variantSet`s authored ahead, shipped whole | compiled per context; others never exist |
| Parameter space | enumerated variants | declared domains |
| Breakage detection | someone looks and notices | exemplar re-evaluation at promotion |
| Storage identity | asset paths (names) | content hashes |
| Redaction | all-or-nothing layer access | derivation-level, deny-by-default |

**Framing matters — avoid "USD is rigid."** These are not USD's failures. USD
was deliberately scoped as an interchange and composition format, leaving
pipeline concerns to the studio, and at that scope it succeeded more completely
than anything before it. Pixar had a pipeline team to fill the empty layer.

The problem is that USD's success carried it into industries with no
Pixar-scale pipeline team, each now rebuilding that missing layer badly and
incompatibly.

> **JIT-SD is a proposal to standardise the layer USD deliberately left empty**,
> not a criticism of what USD chose to do.

## vs. Omniverse / Nucleus

Nucleus with live layers is a **push** model: state lives on a server, clients
mutate in place, deltas broadcast. That is precisely the "synchronised stateful
database" this design set out to avoid.

JIT-SD is a **pull** model: nothing is mutated; immutable revisions are created
and pointers move deliberately.

| | Nucleus live sync | JIT-SD |
|---|---|---|
| Direction | push — server broadcasts mutations | pull — client resolves on demand |
| State | shared, mutable, live | immutable revisions + one movable pointer |
| Latency | milliseconds | resolve then materialise |
| "Which version is this?" | the current one, whatever that is | a baseline, always |
| Reproducible later | via checkpoints, if someone made one | by construction |
| Best at | four people rearranging a room together | handoff between teams, over weeks |

**They compose rather than compete:**

> **Live sync is what happens inside a revision. JIT-SD is what happens between
> revisions.**

A team collaborates live on `hero_car@wip` using Nucleus-style delta sync; on
promotion to `@review`, JIT-SD's immutable revision, contract check and
exemplar validation engage. Consume the live layer as the WIP channel's
transport; do not replace it.

Do not compete on live multi-user editing. Pull-based resolution is *worse* at
it, and pretending otherwise would be a mistake.

## vs. Fabric

A different layer entirely, not a competitor.

Fabric exists because `UsdStage` is optimised for authoring and composition,
not for touching values a hundred times a second — every read pays value
resolution, and the memory layout is not GPU-friendly. Fabric provides a flat,
structure-of-arrays, GPU-adjacent representation of the *already-composed*
stage.

- **JIT-SD** answers: which scene, from whose definitions, at what baseline,
  compiled for whom.
- **Fabric** answers: how do I touch the resulting values 120 times a second.

Fabric is a **materialisation target downstream of JIT-SD**. The natural
pipeline: JIT-SD resolves a baseline and compiles a context-specific stage →
that stage populates Fabric → simulation and RTX run against Fabric.

Fabric strengthens the case: it proves the industry already accepts that the
runtime representation should be a compiled derivative rather than the authored
one. JIT-SD extends the same logic one layer up.

## Packaging

- **Neutral core** — generators, contracts, baselines, context compilation,
  content-addressed materialisation, the archetypes.
- **Domain schema packs** — codeless API schemas per industry, on top.
- **Kernels** — geometry generators per domain, sandboxed and versioned.

A core neutral by design and specialised by schema pack is the shape that lands
in an AOUSD-era ecosystem spanning film, CAD/manufacturing, AEC and hardware. A
core hardcoding film assumptions will not.

## Risks, honestly

**Interactive latency.** A hot Fabric cache will always beat resolving a
derivation graph. The resolve/materialise split, resolution accessors, and
relational-plane-only resolution must carry real weight, or this feels sluggish
next to Omniverse. "Architecturally superior but slower" loses every time.

**Ecosystem.** Omniverse has connectors to dozens of DCC and CAD applications
and years of RTX engineering. Do not rebuild that — sit behind the asset
resolver so existing connectors keep working.

**The cold-start problem — the serious one.** Value comes from teams coupling
through contracts, so one team adopting in isolation gets almost nothing.
Network-effect systems die in that gap. Mitigation is the rung ladder:
single-team value must be real on day one, and contracts become an upgrade
earned once a second team appears.

**The sequencer.** Monotonic numbers need one ordering authority. It appears
exactly when a second person does — which is what keeps rung 1 serverless.

**Determinism of kernels.** Bit-identical output across architectures and
compiler flags is not free. Mitigated by hashing derivations rather than
outputs; WASM if output determinism is wanted.

**When this is the wrong paradigm.** For a locked film shot or a shipped game
level, bake it. The real home is assets in flux with many authors:
configurators, engineering review, simulation prep, live product data, anything
with a supply chain.

But a bake is just **a query pinned to a baseline, flattened to `.usdc`**, so
it falls out for free, and the file is demoted from source of truth to cached
result. Far easier to sell than "files are obsolete," with the advantage of
being true.
