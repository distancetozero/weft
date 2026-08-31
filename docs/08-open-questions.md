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

## 3. Bounds declaration format

What a generator's cheap conservative bounds actually look like
(`04-contracts.md`). Constrains the contract schema and is much easier to
design in now than to retrofit.

Open sub-questions: are bounds time-varying (a swinging door, an animated
character)? Are they per-variation-point (the shell-only variant is smaller)?
Is a single AABB enough, or is an OBB / convex hull / sphere set worth the
complexity?

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

## 9. Granularity of content addressing

Measured in `bench/dedup.py`: byte-level content-defined chunking gives 15.8x
dedup on localised edits and **1.0x on a whole-file re-export**, which is the
common case whenever someone exports from a DCC rather than saving
incrementally. So the unit of content addressing cannot be the file.

An earlier draft of this question asked whether to decompose assets into
per-prim, per-attribute pieces. That was the wrong question: **USD already is
that decomposition.** An `SdfLayer` is a sparse map from `(path, field)` to
value, and `SdfAbstractData` exposes exactly that. The question is only at what
granularity to hash the decomposition USD already provides.

### The shape it actually has

**USD layers — hash per `(path, field)`.** A re-export perturbing float noise
on one mesh leaves every other prim's fields hashing identically, which is the
property byte chunking demonstrably cannot deliver. Crate's own intra-file
value dedup becomes irrelevant, because fields are stored individually anyway.

**Opaque payloads — keep the chunker.** Textures, VDB volumes, point caches,
Alembic, video. USD's data model gives nothing here; they are bytes behind an
asset path, and content-defined chunking is the only tool. The re-export
problem is milder for these: a texture that was not re-authored usually
produces identical bytes.

### Hash values, not bytes

USD does **not** guarantee that semantically identical data serialises to
identical bytes. Crate output varies with writer version and value-table
ordering. So hash the typed value in a canonical encoding rather than its
serialisation.

This is an improvement, not a tax: a `float3[]` then hashes the same whether it
came from `.usda` or `.usdc`, and whether it was written by one USD version or
another. Byte hashing would have failed silently and late.

### What it costs

- **Small-object explosion.** Millions of prims times several fields each. Hash
  individually, store in packs, as git does. Design it in now rather than
  discovering it at scale.
- **A pxr dependency in the write path.** Rung 1 deliberately has none. Store
  granularity and the USD dependency therefore arrive together — a decision
  point, not a free upgrade.

Still open: whether canonicalisation should also normalise prim and array
ordering (defeating re-exports that only reorder, at the risk of being lossy),
and what the pack format is.
