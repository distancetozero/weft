# Prim-Level Threads — Design

Date: 2026-09-01
Status: approved in conversation, section by section; pending written review
Author: designed collaboratively in-session; measured facts verified on this machine

## 1. Problem

Everything in jit-sd today pulls threads at **asset** granularity: a slice's
members are asset names, contracts bind asset surfaces, and the deps graph
aggregates to file × file. Real scene descriptions are not one entity per
file. "Pull the hero car," where the car is a prim inside a shot layer, is
not expressible — and ALab's tidy one-entity-per-file layout has hidden this
gap from every demo so far.

The premise this design serves, verbatim from the project owner:

> The whole premise is about pulling on threads explicitly with rules and not
> having to load the whole thing. And I would argue leads to not even needing
> to think of the main view as being a hierarchy but on relationships that can
> include hierarchy — but other relationships, and even specific relationships
> that can even be defined by a team for their own uses.

Two drift corrections were caught during design and are binding here:

1. **The ask must not presume location.** A prim path as the primary seed
   reintroduces drill-down at the exact moment the system goes to prim
   granularity. Identity, contract role, and binding attributes are the front
   door; path is the fallback.
2. **Team-defined relationships must survive as themselves.** Collapsing
   every authored relationship to a generic `usd:rel` kind makes
   `electrical:feeds` indistinguishable from `material:binding`. An edge's
   kind is the relationship's own namespaced name.

## 2. Scope

In scope (user decision): **pull + interrogation + prim seeds in slices.**

- Prim-level thread graph and closure from any seed.
- A pull manifest that stock USD consumes (population mask / load set).
- "What depends on this prim" interrogation.
- `prim`-granular seeds and members in slices, with honest pricing.

Out of scope, explicitly deferred:

- **Prim-level contracts and re-evaluation.** Offers/requirements stay at
  asset granularity. The gate does not change.
- **Semantic (vector) seed resolution.** The ask grammar reserves the slot;
  nothing vector-backed is built.
- **A separate Load-set for oversized members** (mask-with-partial-payloads).
  Recorded extension point only.
- **A persistent prim × prim index.** Closure walks on demand; measured need
  may revisit.

## 3. Verified mechanical facts this design rests on

Measured on this machine (USD 26.08, ALab 2.3.0), not assumed:

- `Usd.Stage.Open(entry, LoadNone)` opens all of ALab in ~126 ms. A prim
  behind **unloaded payloads** is addressable, and `GetPrimStack()` returns
  its authoring (layer, path) pairs — including the composed↔layer-local
  prefix mapping across reference re-rooting — without loading anything.
- Targeted `stage.Load(primPath)` is ~64 ms and loads that subtree only.
- `Load` follows composition arcs only: relationship targets (material
  bindings etc.) do **not** come along. Closure must compute them.
- Population masks include descendants **and ancestors** of masked paths, and
  strip relationship targets that fall outside the mask. (Also: Apple ships
  `/usr/bin/usdrecord` with `--mask` and a Metal Hydra backend on macOS; the
  spike renders in 1–4 s.)
- Re-rooting a prim via a new reference strips its out-of-scope relationship
  targets (the encapsulation finding). Therefore a pull is **deferral over
  the original stage, never extraction** — the context is opened in place and
  selectively populated; nothing is re-rooted.
- The spike (2026-09-01): hand-built masks reproduced the intended experience
  end to end — one bottle; bottle + bench skeleton; 26 translucent props
  floating with no common ancestor. The hand-glue in that spike is exactly
  what this design automates, and reproducing those masks from one-line asks
  is the acceptance criterion (§9).

## 4. Section 1 — The thread graph

**Node = (layer, prim path).** Not composed prims (composition is USD's job,
after population is decided), not files (files lose the hero car).
`deps.walk` already records every edge prim-scoped (`src_prim`); only the
file × file aggregation discards prim identity. Nothing is re-walked.

Closure alternates two moves, each done by the machinery that is cheap at it:

1. **Composed path → authored specs** (USD's move). `GetPrimStack` on the
   `LoadNone` context stage turns any composed path — a resolved seed, or a
   relationship target authored in an assembly — into its (layer, path)
   pairs, with the composed↔layer-local prefix mapping for free.
2. **Authored specs → new paths** (our move). In each layer of the stack,
   scan recorded edges whose `src_prim` is at or below that path. Each edge
   carries its kind (the follow vocabulary). Followed edges yield new paths:
   an ARC continues in the target layer at its target or defaultPrim; an
   in-layer relationship target resolves in that layer and maps back to a
   composed path by prefix rewrite (variant selections stripped when mapping
   to composed namespace). Repeat from move 1.

**Spine, not canopy.** Every member contributes its namespace ancestors' own
opinions (the transforms that place it) and never its siblings. This is also
precisely population-mask semantics — descendants plus ancestors — so the
graph's answer and the loader's behavior agree by construction.

Standing disciplines that carry over unchanged: kinds not followed are
counted and declared at the boundary, never silently dropped; `inherits` to a
class prim includes the class's specs (existing `class_hook` logic);
unreadable layers are recorded and non-fatal; closure runs seed-outward (the
pull direction, which terminates); the walk is on demand — no persistent
index.

## 5. Section 2 — The ask

A pull names a **context** (an asset in the ledger, or any raw USD file — the
tools stay usable with no ledger) and one or more **seed predicates**. Every
predicate resolves to a set of composed prim paths; only one speaks path:

| seed | plane it reads | example |
|---|---|---|
| `name:` (bare glob is shorthand) | namespace names, lexical | `chemistry_bottle01*` |
| `id:` | identity metadata (the `absent:id` anchor, promoted to a first-class address) | `id:hero-car` |
| `offers:` / `requires:` / `role:` | contract plane | `role:propSocket` |
| `where:` | binding attributes on interface surfaces | `where:finish=translucent` |
| `path:` | scene location — fallback, not default | `path:/root/shelf01/x` |

Rules:

1. **The receipt declares how every seed resolved** — e.g. `seed
   where:finish=translucent → 8 assets, 26 placements (attribute match,
   interface layers)`. A future semantic tier (`like:"hero car"`) slots in as
   one more declared resolution mode carrying confidence and runners-up;
   nothing else changes.
2. **Set-valued by nature; exact kinds expect uniqueness.** Globs and
   `where:` legitimately match many. `id:` or `path:` matching more than one
   is reported with candidates, never guessed (the deps three-step
   resolution discipline, reused).
3. **Asks read only the relational plane** — names, identity metadata,
   interface layers, contract surfaces — never composed geometry. Resolution
   stays `LoadNone`-cheap, and it is the same constraint rule sets already
   obey.

## 6. Section 3 — Closure and the manifest

Closure's output is a **population set** (composed prim paths) plus an
accounting. Population decides what exists; composition handles everything
inside what exists. Edge kinds therefore contribute differently:

- **`usd:arc`** (references/payloads inside a member): contributes **no
  members** — a populated prim's arcs compose normally. Arcs feed the
  manifest's accounting (layers and bytes that ride along) and the receipt.
- **Named relationships** (`material:binding`, connections, collections, and
  any team-authored kind such as `electrical:feeds` — kind = the
  relationship's own namespaced name; `usd:rel` only for unnamespaced rels):
  a followed target **joins the population set with its spine**. The pull is
  therefore **strand-free by construction**: masks cannot strip a followed
  target, because following it put it in the mask. A not-followed kind is
  declared at the boundary with a count ("26 binding targets not populated").
- **Contract edges** (`Mount`, `Represents`): followed via `boundTo`
  provenance, both directions on request. They contribute the offer's
  **anchor prim's spine**, plus — when the offer declares a **carrier** — the
  carrier prims' spines. `jitsd:offer:carrier` is a relationship naming the
  prims that physically realize an offer (the shelf furniture under the
  bottle). Extraction derives carriers only by a **stated, recorded rule**
  (e.g. "carrier = `furniture_*` placements of the offer's group"), exactly
  like the recorded 10%-footprint tolerance rule. No carrier authored → no
  carrier pulled, and the receipt says so.

**The manifest is a USDA file** (consistent with rules, revisions, slices):
`customLayerData` carries the context (asset@rev or raw file — never
re-rooted), the asks verbatim with their resolution declarations, the member
paths, boundary counts by kind, and the byte/layer accounting (from members'
prim stacks; unloaded payload cost is an estimate from authored hints and is
labeled as such). `--format mask` prints the comma-joined member list for
`usdview` / `usdrecord --mask` directly; anything richer reads the manifest.
v1 has one population mechanism: mask = members, payloads load fully within
it.

**Termination:** seed-outward only; depth capped by the rule set's existing
`depth`; every frontier edge either followed or counted at the boundary.

## 7. Section 4 — Prim seeds in slices

The slice algebra (seeds + closure + coordinate ± overlay, follow, view,
rules) is unchanged; prim granularity slots in:

- **Seeds:** the ask grammar becomes valid slice-seed syntax, scoped by
  context — `lab_workbench01:where:finish=translucent` — or context-free for
  identity (`id:hero-car`). Asset-name seeds keep today's meaning.
- **Members go two-tier.** A prim-seeded slice records *selections*:
  `lab_workbench01 @ v002 : [/root/shelf01/chemistry_bottle01_0004, …]` —
  the context pinned at the slice's coordinate, so composed paths resolve
  against a specific revision and the pull is reproducible forever. A
  whole-asset member is the degenerate selection.
- **Pricing gets honest.** The receipt prices a selection by the manifest's
  accounting — layers and bytes actually populated — not the whole asset's
  footprint. The JIT premise becomes a number in the receipt.
- **Impact stays asset-level, localized presentationally.** Re-evaluation
  and the gate are untouched. When `--impact` names broken consumers, the
  slice additionally maps them to placements inside the selection ("3
  consumers broken; 2 are prims in your view"). A membership join, not a new
  solver.
- **Rule sets need nothing new** — follow, depth, view already exist; asks
  obey the same read-only-relational-plane constraint.

## 8. Section 5 — Testing

Fixtures first, ALab as proof:

1. Unit tests per seed predicate against small authored fixtures
   (multi-line USDA — real Sdf rejects one-liners; the lesson stands).
2. Closure tests asserting the strand-free guarantee (every followed rel
   target present in the emitted mask) and spine-not-canopy (sibling absent;
   ancestor opinion present).
3. Boundary and receipt assertions: counts by kind, per-seed resolution
   declarations.
4. The spike, automated as the acceptance test: asks 1 and 3 reproduce the
   spike masks byte-for-byte against the ALab tree when present; ask 2
   (Mount + carrier) produces the mask the carrier *rule* derives — the
   spike's hand mask included all furniture and was approximate, and the
   rule, not the hand-glue, is authoritative. Skipped when ALab is absent
   (the existing pxr-gated pattern).
5. A carrier-rule test on extracted interfaces.

CI runs fixtures; ALab tests run locally, like the POC.

## 9. Acceptance criterion

Reproduce the 2026-09-01 spike renders from one-line asks, no hand-glue:

```
jitsd pull 'chemistry_bottle01_0004' --context lab_workbench01     → one bottle
jitsd pull 'chemistry_bottle01_0004' --follow Mount                → bottle + carrier
jitsd pull 'where:finish=translucent' --context lab_workbench01    → 26 placements, no common ancestor
```

Each emits a manifest whose member list, fed to `usdrecord --mask`, produces
the corresponding image; each receipt declares seed resolution, followed
kinds, boundary counts, and pricing.

## 10. Standing review verdicts honored

- Identity is metadata, never an address baked into hierarchy.
- Cut only at declared boundaries; never cut finer than a contract-closed
  unit (contracts stay asset-level here, so no prim-level cut crosses one).
- Integer-indexed correspondences (e.g. point-instancer `protoIndices`) are
  unsound under partial exclusion: instancer prototypes are pulled whole or
  declared at the boundary, never partially.
- Fail open on presence; silent omission is fatal; absence and boundary are
  always declared.
- Deferral (population/load) for working sets; authorization is a separate
  gate, not a side effect of non-population.
- Rules and asks read only the relational plane.
