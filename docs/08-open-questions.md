# Open questions

Decisions not yet made. Each one changes the shape of something downstream.

## 1. Channel ownership and promotion policy

Who owns a channel, and what does promotion require?

Whether promotion is a pure permission check, gated on the exemplar suite
passing, or on a human sign-off changes the shape of the whole system — and it
is the point where this stops being a data architecture and becomes an
organisational one.

Likely answer: policy is per-channel and declared, with the exemplar gate
default-on for anything above `@wip`.

## 2. What a checkpoint captures during a multi-participant live session

Two candidates:

- **One shared revision, co-authored** — a snapshot of the whole composed WIP
  stack.
- **Per-participant sublayer revisions that compose** — each participant's
  layer checkpoints independently.

This decides whether authorship is per-asset or per-layer, and changes how
promotion and credit work. It also decides what "revert" means when three
people are in the session.

## 3. Bounds as a function of parameters

Substantially narrowed by the audit. `UsdGeomModelAPI.extentsHint` already
exists precisely so bounds can be read **without loading payloads** — which is
most of what this question asked for, and it is authored per purpose. Reuse it;
do not invent a bounds representation.

What `extentsHint` does not give is the part that matters for a JIT system: it
is **authored data fixed at write time**, not a cheap evaluation. A generator
must answer "where will you be for parameter set P" in microseconds without
generating anything.

So the question is now only: what is the form of that function, and who writes
it? Candidates: an authored conservative hull that covers the whole legal
parameter domain (trivial, wasteful, always correct); a declared per-parameter
sensitivity the resolver composes; or a cheap bounds-only kernel entry point
alongside the main generator.

Still open beneath it: are bounds time-varying (a swinging door, an animated
character), and per-variation-point (the shell-only variant is smaller)?

## 4. Contract versioning semantics

Semver-like, but for what exactly? Adding an optional port is compatible;
removing one is breaking; tightening a tolerance envelope is breaking for some
consumers and not others. Where is the line drawn, and how much can the
exemplar suite decide automatically rather than by declaration?

## 5. Sequencer scope

Per-project, per-org, or global? Affects whether two studios can exchange
baselines without renumbering, and whether an offline site can promote at all.

## 6. Diamond dependency resolution

Two consumers need incompatible revisions of the same provider. Package
managers have twenty years of answers (hoisting, duplication, refusal). Which
apply when the "package" is geometry that must be spatially coherent with
itself?

## 7. Live session ↔ contract validation

Contracts are validated at promotion. Should they also be validated live, so a
participant sees "you have just broken the wheel team's mount" as they work?
Valuable, but it puts relational evaluation on the interactive path.

## 8. Where the receipt log lives

Append-only and kilobyte-scale, but it is the one thing that must survive
everything else. Same store as the ledger, or separately durable?

## 9. Granularity of content addressing — RESOLVED

**Recommendation: keep byte-level content-defined chunking. Do not move to
per-`(path, field)` hashing.** Full measurements in `docs/06-storage.md`.

The question existed because byte chunking supposedly could not survive a DCC
re-export. Measured against real USD, it survives easily: a one-mesh edit in a
4000-mesh scene costs 0.1% of the file, and reordering every prim costs 1.3%.
Crate is deterministic and keeps edits local. The original "1.0x on re-export"
number came from perturbing every 512th byte of random binary — a synthetic
worst case no USD workflow produces.

Field-level hashing wins in exactly one case: float noise on every value, where
it stores 69% against byte chunking's 100%. A 31% saving does not justify
layer decomposition, value canonicalisation, pack files, and a pxr dependency
in the write path.

What actually changed: the default average chunk moved from 1 MiB to **64 KiB**
(measured knee), and a store now records its chunker parameters so a future
change is an explicit migration rather than a silent loss of dedup.

**Reopen this if** exports from a real DCC pipeline show heavy prim renaming or
re-tessellation that perturbs every value. The test scene is synthetic — one
USD version, uniform meshes, no textures, time samples or references. A cheaper
middle path exists if it is needed: hash per *prim* rather than per field,
which survives reordering and renaming without full value canonicalisation.

