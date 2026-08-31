# Contracts, generators and exemplars

## Ports are applied API schemas

Teams do not publish assets. They publish **generators**: pure, parameterised
functions that declare an interface.

The chassis team publishes `chassis(params) → {geometry, ports}` where a port
carries a frame, a role, a fitment spec, units, and an interface schema
version. The wheel team publishes `wheel(hubSpec) → geometry`. The two couple
on the **interface type**, not on a namespace path.

This is the actual break from how USD is used today. USD composes by namespace
overlay — an `over` on `/World/Set/Trees/Tree_047` — so everyone must agree on
the tree in advance, and renaming a prim breaks downstream departments.
(Namespace editing and relocates exist to paper over this; they are a patch on
the underlying coupling.)

JIT-SD binds by **structural schema match**: the resolver finds a provider
whose emitted interface satisfies a consumer's declared requirement. **The
namespace becomes an output of composition rather than a precondition for it.**

Contracts are declared as **codeless applied API schemas** (USD 21.08+) — pure
plugin data, no C++ build. Teams agree on schemas, and nobody compiles
anything. See `specs/jitsdContracts/schema.usda`.

## What a generator declares

**1. Its contracts** — what it provides and requires.

**2. Its parameter domain** — the *space* of legal variation, with types,
units and constraints. Meaningfully different from `variantSet`s, which
*enumerate* variants someone anticipated. A domain *describes* the space and
lets the compiler pick a point in it. Enumerating is why studios end up with
fifteen authored LODs that drift; describing means the LOD is computed for the
budget actually present.

**3. Its variation points** — the declared places where context may change
what comes out. Everything else is context-invariant, which is what makes
cross-context consistency provable rather than hoped-for.

**4. Its effectivity** — when this definition is valid from, under what
conditions.

**5. Its cheap conservative bounds** — see below.

## Units in the type system

mm vs inch, N·m vs lbf·ft. Dimensional mismatch across team boundaries is the
empirical failure mode in this domain and is cheap to make unrepresentable.

## Tolerance envelopes make teams independent

A port is not a transform — it is a transform **plus an admissible envelope**.
This is what actually decouples teams: the wheel team iterates freely while
staying inside the envelope, and the chassis does not re-resolve. Only envelope
violations escalate.

## Contract archetypes

The neutral core ships a handful of archetypes; each industry specialises them.
The relational solver understands only archetypes; vocabulary is supplied by
domain schema packs.

**Mount / Socket** — provider emits placement frames plus a fitment spec;
consumer attaches.
*Film:* rig attachment points, prop sockets. *Games:* weapon sockets, decal
anchors. *Manufacturing:* fastener patterns on a panel. *AEC:* a façade grid
receiving panels. *Robotics:* sensor mount points.

**Field / Domain** — provider emits something sampleable over an area or
volume; consumer samples it.
*Film:* scatter density over terrain. *Games:* foliage and spawn distribution.
*Manufacturing:* pressure or thermal field. *AEC:* daylight or occupancy across
a floor plate.

**Envelope / Clearance** — provider claims a volume nothing may intrude into.
*Film:* FX sim bounds, camera frustum, action volume. *Manufacturing:* swept
volume of a moving part, service access. *AEC:* egress paths, ceiling plenum.
*Games:* navmesh clearance.
Violations are checkable relationally, before any geometry is built.

**Kinematic chain** — joints, degrees of freedom, limits.
*Film:* rigs. *Manufacturing:* mechanisms. *AEC:* operable doors and windows.
*Robotics:* actuators.
USD covers fragments of this from different ends (`UsdPhysics`, `UsdSkel`); the
archetype is the same.

### The canonical cross-industry case

"Wheels must match the chassis mount points" is exactly "props must sit on the
terrain after FX re-sculpts it" and "the rig must still work after the modeler
changes topology." Two teams, one generated thing depending on another
generated thing. Today the only way to stay in sync is for someone to
re-publish and someone else to re-open.

## Constants are generators

A hand-sculpted hero character is a generator with no parameters returning
fixed geometry. A supplier's scanned CAD part is a constant. If the paradigm
demands everything be procedural it is dead on arrival with exactly the people
who must adopt it.

The requirement is not "everything is procedural" — it is **"everything is
addressed as a function,"** and a constant is a perfectly good function.

## Exemplars

Nobody can author a function blind. A generator ships a small set of canonical
parameter bindings — representative configurations — and the authoring tool
opens one to work in. This already exists in spirit: Houdini HDA presets, Revit
family type instances, Unreal blueprint defaults.

> **The exemplar set is the generator's test suite.**

When an upstream dependency changes, re-evaluate every downstream generator's
exemplars at the new revision and diff the manifests. That is continuous
integration for 3D content, and **no industry currently does it well**. Film
finds out at dailies. Manufacturing at a design review. AEC at clash detection,
or on site. Games at cert. All of them late, by looking, with humans.

Contracts + exemplars + content-addressed manifests give a cheap automatic
"what did this change break?" — kilobyte diffs, not gigabyte re-renders. This
is also the mechanism that makes compatibility measurable rather than asserted
(`03-versioning.md`).

## Cheap conservative bounds — a contract obligation

Spatial queries ("what is in this frustum / streaming cell / floor / within
50 m") matter for games, digital twins and AEC. But:

> **You cannot spatially index something you have not generated yet.**

Therefore every generator must declare **conservative spatial bounds computable
without generating geometry** — from parameters alone, in microseconds, never
wrong in the direction that hides something. Then:

1. Build a spatial index over *bounds*, in the relational plane. No geometry.
2. Query the index for what intersects the region.
3. Materialise only those.

Prefer a BVH over declared bounds to a strict octree: scene content is
irregular and mostly surfaces, not uniformly dense volume. Octrees earn their
keep when occupancy is dense and uniform.

Bounds are useful well beyond spatial queries — budgeting, culling and
progressive loading all need "how big is this" answerable before "what does
this look like."

**Do not let spatial structure into the contract system beyond this.** A
generator declares bounds and nothing else spatial. The moment contracts
express "must be within this octree cell," teams are coupled to a partitioning
scheme that will change — path-coupling wearing a different hat.

## Overrides bind to contracts, not paths

Every industry needs "this one instance is special": the hero prop is scuffed
in this shot, serial #400 shipped a different bracket, this window is
fire-rated. USD handles local opinions beautifully via LIVRPS, and that is
retained entirely.

But an override must target a **declared handle on the generator's interface**,
never an arbitrary prim path.

This fixes a real daily USD production pain. Today a shot-level override on
`/World/Char/geo/mesh.points` silently detonates the moment the modeler changes
topology, and nobody finds out until a render looks wrong. Bound to a declared
handle, a generator change that removes the handle **fails loudly at
resolution** and names who owns it.

Same theme as everything else here: **couple to contracts, not to names.**

## Termination

Recursive parametric generation must be bounded: stratification, a fuel/depth
budget, and a declared cost class per generator.
