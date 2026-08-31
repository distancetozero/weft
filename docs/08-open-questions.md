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
