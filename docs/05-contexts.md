# Context-directed compilation

The strongest departure from how USD is used, and the widest gap from
`variantSet`s.

## Why variants are not enough

`variantSet`s must be **authored ahead and ship inside the asset**. Every
consumer receives every variant and picks one. So someone must anticipate and
build all of them, they drift out of sync, they bloat the file, and an
outsourcing vendor receives the unreleased-character variant whether or not
they are allowed to see it.

JIT-SD's variation is compiled per request. **The other variants never exist.**
That is a security property, not merely an efficiency one.

## Context is an argument, not a filter

`compile(query, context) → payload`. Different context ⇒ different derivation ⇒
different hash, so context enters the cache key automatically with no extra
machinery.

## Claims, not roles

"Engineer" and "consumer" do not compose, and explode the moment "previz artist
at an outsourcing vendor on a tablet" appears. A context is a **claim set** —
`{department, purpose, platform, poly budget, clearance, jurisdiction, units,
device}` — and rules predicate on claims. Roles become named presets that
expand into claims at the edge. ABAC over RBAC.

Carried in USD via `ArResolverContext`, which studios already use to inject
shot context.

## Three tiers, deliberately kept apart

Their failure modes differ, so their enforcement must too.

**1. Representation** — LOD, tessellation, subdiv level, displacement, texture
budget and format, coordinate convention, output codec. Pure negotiation, no
security consequence. May live in a Hydra filter.

**2. Semantics** — a different *derivation*, not a coarser one.
The animator gets a fast proxy with a working rig and no shading. The lighter
gets full subdivision, displacement and the shader network but no rig. The FX
artist gets collision proxies and velocity attributes. The game build gets a
decimated LOD chain with baked normals and an atlased material. The game
*server* gets collision hulls and nothing else — no materials, no textures, no
LODs.

Today each is a separate published asset built by a separate pipeline step, and
they **drift**: the game LOD3 is two revisions behind the film hero, the FX
collision proxy no longer matches the model. Here they are all compiled from
one derivation, so a design change lands in every one at the next baseline, or
in none.

For games this is the headline: **one authored asset, N platform compilations,
consistent by construction, generated when the target asks.** Games already do
JIT at runtime — streaming, LOD selection, procedural placement. The gap is
that authoring-time and runtime are entirely different systems agreeing only by
human discipline. This closes it.

**3. Authorization** — outsourcing vendors, unannounced characters, licensed IP
with territory restrictions, pre-release marketing, supplier A never seeing
supplier B's internals.

> Tier 3 **must** be enforced by an independent deny-by-default gate over the
> final manifest, not by a rule in the same engine that does tiers 1 and 2.
> Otherwise a bug in a LOD rule *is* a data breach.

Compiler proposes, policy checker disposes, before a single blob streams. And
because redaction must happen before bytes leave the server, tier 3 is always
resolution-side, never Hydra-side.

## The trap: omission is not redaction

Removing a prim leaves the hole in the floor geometry, the shadow-catching
holdout, the light rig aimed at nothing, and a bounding volume that gives away
the silhouette. A decimated mesh can be partially inverted. A boolean
subtraction leaves the negative of the part removed. A shrink-wrapped hull
still encodes the aero surface.

> **Compile a different program; do not compile the full one down.**

The restricted variant must be produced by a **separate declassifying
generator** that provably emits only a permitted feature set. "Just decimate
the real model" is the tempting and wrong architecture, and it is the kind of
thing discovered after it ships.

## Cross-context consistency

The marketing render must be the actual car. The game LOD0 must be the actual
model.

Enforce by allowing context to influence only **which rules fire** and **which
codec is emitted** — never the parameters flowing through shared nodes. Declare
explicit **variation points**; everything outside them is context-invariant.

Consequence: shared subgraphs hash identically across contexts, so all contexts
share cache. **Consistency and cache efficiency come from the same
constraint.**

## Spatially varying context

Once a spatial hierarchy over declared bounds exists (`04-contracts.md`),
context stops being one global setting and becomes something that **varies
through the hierarchy** — hero fidelity near camera, proxy at mid distance,
impostors far field, all from one derivation and one budget declaration.

This is how games already do LOD. The difference is that it is a *compilation*
decision resolved through the hierarchy, not a set of pre-baked LOD assets
maintained by hand — which is what makes "N platform compilations from one
asset" work at scene scale rather than per asset.

## Approval attaches to a derivation, not a file

Dailies approval, engineering change sign-off, issued-for-construction, cert —
all become "someone signed derivation *H* at baseline *E* under context *C*."

Two consequences: you can **prove** what was approved, and "has anything
drifted since approval?" is answered by re-resolving at the current baseline
and diffing manifest hashes. Kilobyte-scale and instant, for a question that
currently takes a person a day and is usually answered wrong.

Regulated industries need this legally. Film just needs it badly.
