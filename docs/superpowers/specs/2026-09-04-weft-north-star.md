# weft — north star: the thesis, and the map of everything against it

**Status:** the connective tissue, 2026-09-04. Written to stop treating the
pieces (pull, lenses, compose, drift, collections, resolver, pre-conditioning)
as separate features and hold them as facets of one thing. Owner's framing;
this doc just makes it explicit and maps where we actually are.

## The thesis

> **Just-in-time USD.** You declare relationships and pull exactly the world you
> want — composed on demand. The composed stage is a **function of
> (relationships + rule + context)**, computed by driving **LIVRPS as an engine,
> not a fixed pipeline**. The goal: highly **dynamic, repeatable, flexible**
> relationships with USD that let **any industry** engage with it
> **relationship-first — no matter the relationship — and surgically.**

Three altitudes, and we must not confuse them:
- **The wedge (the now-problem):** load/see exactly what you want, don't load the
  world. Surgical read.
- **The product (the engine):** composition itself is programmable — pulling a
  relationship *composes* a bespoke, surgical stage via LIVRPS levers.
- **The horizon (the paradigm):** the source of truth shifts from a baked
  hierarchy to a **relationship graph**; the composed USD becomes a derived,
  on-demand view — a new way to *build*, not just to read.

## The five properties (the test to hold every build against)

1. **Surgical** — a pull yields exactly the rule's closure, nothing more.
2. **Relationship-first** — the view organizes by *any* relationship, hierarchy
   being just one; team-defined relationships are first-class.
3. **Dynamic** — the composed world is computed on demand, not baked.
4. **Repeatable** — same relationships + rule + context ⇒ same world, provably
   (certifiable, diffable, no database).
5. **Flexible / any-industry** — relationship *kinds* are open, not a fixed
   vocabulary; not tied to VFX.

## The value ladder (and where pre-conditioning actually lives)

```
READ      what USD already says (composition, bindings, collections, assetInfo, kind, purpose)
  ↓         zero prep · works on any scene · align to USD's own surface  ── THE ON-RAMP
DERIVE    higher-level facets/lenses computed from READ                   ── still zero prep
  ↓
DECLARE   the relationships USD can't express, added by a util            ── THE AUTHORING SURFACE
  ↓         (this is what "pre-conditioning" becomes)
CERTIFY   drift receipts over any set/relationship from any rung          ── THE TRUST LEG
  ↓
COMPOSE   pulling a relationship drives LIVRPS to build a bespoke stage   ── THE ENGINE
```

**Pre-conditioning is the DECLARE rung** — and the owner's key insight is that
it is a *gateway now, authoring eventually*, because DERIVE and DECLARE are the
**same mechanism** at two points on the ladder: a relationship is either
*derived* (read from native USD, zero prep) or *declared* (authored, for the
axes USD can't express). Same unit, different origin. That is what makes
pre-conditioning stop being a rigid tax and become the on-ramp *and* the
authoring surface.

## The one unifying unit

Everything reduces to a single declarable thing:

> **A weft relationship kind = (type, population, composition/resolution).**
> - **type** — what the relationship means (hierarchy, mount, powered-by,
>   calibrated-against, a team's own).
> - **population** — how its members are found: **derived** from native USD, or
>   **declared/authored** (sidecar, never hacking the stage).
> - **composition/resolution** — what *pulling* it does to the engine: which
>   arcs/masks/resolves (the LIVRPS-as-engine clause).

A fixed trio (hierarchy/mount/finish/shading) is an *instance* of this. The
thesis needs the *framework* — that is the pivot from "a tool with three
relationships" to "an engine you extend, in any industry."

## Honest status map

| Piece | Serves | Status |
|---|---|---|
| Thread explorer (pull / peek / re-center / lenses) | surgical, relationship-first | **shipped** (main) |
| Facet loading + `load_set` rule→set→load seam | surgical | **shipped** (main) |
| Compose-mode selection algebra | relationship-first, flexible | **built** (branch); align structural predicates to `SdfPathExpression`, weft owns value/relationship |
| Drift receipts (sidecar, identity, Merkle, no DB) | repeatable | **prototype** (branch), one predicate |
| Collections-lens ingestion | READ base, relationship-first | **specced** (branch) — the on-ramp's first real reader |
| As-of resolver (named coords, open-manifest, executors) | dynamic, COMPOSE | **specced** — first slice of the engine |
| Assembly-compiler / authorship cycle | dynamic, horizon (authoring) | **specced/queued** |
| Pre-conditioning (`weft:offer/bind` + interfaces) | DECLARE | **hardcoded instance** — must become the relationship-kind framework |

## The honest read (where we are vs the thesis)

- **Surgical: strong and real.** The wedge is built and proven. This is our
  credibility.
- **Relationship-first: partial.** Real via lenses/compose, but on a *fixed*
  relationship set. Collections lens broadens it; full "any relationship" needs
  the framework.
- **Repeatable: emerging.** Drift prototype is the trust leg, early (one
  predicate) but sound, and the "no database" model is validated.
- **Dynamic: mostly ahead of us.** Almost everything today operates on a
  *static composed stage* (read → select → load-subset). The **engine** —
  composing bespoke stages by driving LIVRPS (population masks, dynamic
  file-format payloads, a context resolver) — is largely **unbuilt**; the as-of
  resolver is the first slice. **This is the biggest gap between what's built
  and the vision.**
- **Flexible / any-industry: weak.** Fixed vocabulary, one dataset (ALab/VFX),
  and — the standing reality check — **no outside user yet**.

Net: we've built the *surgical-read wedge* very well, started the *certify* leg,
and the *dynamic engine + relationship-first authoring* — the actual paradigm —
is still mostly design and horizon. That's the right order (the wedge earns the
right to the engine), but the center of gravity of the vision is where the depth
still has to go.

## Where we go (the merged forward path)

1. **On-ramp (now):** make READ/DERIVE real — native readers (material binding →
   shading, collections → sets, kind/purpose/structure) so weft works on
   *unprepped* USD. Collections lens first. This is the 10-minute bar and the
   outside-user test.
2. **The pivot:** generalize the hardcoded `weft:offer/bind` into the
   **relationship-kind framework** (type + population[derive|author] +
   compose/resolve). This is the single most important structural move — it
   makes weft flexible/any-relationship and turns pre-conditioning into
   authoring.
3. **The engine:** wire the framework to LIVRPS levers so pulling a declared
   relationship *composes* a surgical stage (dynamic JIT-USD). As-of resolver +
   assembly-compiler are slices of this.
4. **The trust:** generalize drift/receipts across the framework so every
   composed world is repeatable.
5. **The reality check:** get it in front of a second industry and an outside
   user — "any industry, relationship-first" is untested beyond ALab and the
   author.

## Standards posture (so we neither reinvent nor get boxed in)

Align the **structural** half of selection to USD's own `SdfPathExpression`
surface (globs, `+ & - ~`, `isa`/`kind`/`hasAPI`/`variant`) — even build on its
engine. Own the half USD provably doesn't and isn't heading toward: **value
facets, relationship traversal, certification/drift, and dynamic composition.**
Ride the standard for the plumbing; the engine is weft's.

## The discipline (the careful part)

Paradigm shifts ship as surgical wedges. Every build must be a concrete now-win
*and* ladder toward the engine — never "boil the ocean," never blow the
10-minute bar. The pull is the wedge; keep it sharp while the engine grows under
it. When a build starts sounding like "a nicer USD reader," check it against
this doc — that framing amputates the ambition.
