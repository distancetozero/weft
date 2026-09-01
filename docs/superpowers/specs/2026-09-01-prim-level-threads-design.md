# Prim-Level Threads — Design

Date: 2026-09-01 (rev 2, after six-lens adversarial review)
Status: revised against review findings; pending owner review
Review record: §13. Findings were verified before adoption — the probes in §3
adjudicated every contested mechanical claim, and two reviewer claims were
narrowed by measurement.

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

Two drift corrections caught during design are binding:

1. **The ask must not presume location.** Identity, contract role, binding
   attributes — and now spatial extent — are the front door; path is the
   fallback.
2. **Team-defined relationships survive as themselves.** An edge's kind is
   the relationship's own namespaced name; `usd:rel` only for unnamespaced
   rels.

## 2. Scope

In scope (owner decision, extended by review):

- Prim-level thread graph and closure from any seed.
- A pull manifest that stock USD consumes, self-certifying (§8).
- Directional follow and the "what depends on this prim" interrogation (§7).
- Spatial seeds over declared bounds (§5) — three review lenses showed the
  slices doc already promises them and the prim grammar had dropped them.
- `prim`-granular seeds and members in slices, with honest pricing and a
  stated authority rule (§9).

Out of scope, each deferred **with its consequence named**:

- **Prim-level contracts and re-evaluation.** The gate stays asset-level. On
  monolithic layers (a 200-station line in one file) this means the gate
  refuses at *file* granularity — change control at the ZIP level — while
  interrogation and per-offer violation naming stay prim-precise. Prim-level
  contracts are the roadmap item that makes ECO-scoped gating possible.
- **Effectivity.** Configuration = variant selections is first-class now
  (§4, §8); date/serial/option effectivity — including channels where two
  revisions are concurrently in force — is a ledger design of its own. An
  `eff:` seed slot is reserved.
- **Federated multi-root contexts.** v1 pulls name one context. Cross-file
  links joined by external identity (IFC GlobalId) rather than authored rels
  need an identity-join edge class; reserved, not built. A pull that needs
  five discipline files today needs a master stage that references them.
- **Semantic (vector) seed resolution.** Slot reserved in the receipt
  grammar; nothing built.
- **Conjunctive asks.** Multiple seeds union (§5); "translucent AND on
  shelf01" is inexpressible in v1 and says so; syntax reserved.
- **Relocates.** Detected and declared unsupported, never mistranslated.
- **A mask-granular payload Load-set.** The manifest reserves the field
  (§8); note this extension is the designed fix for payload-interior
  population cost, so it must be designed against §4's payload rules.
- **A persistent prim × prim closure index.** On-demand walking holds at
  ALab scale (§3); named triggers for revisiting: reverse interrogation on
  high-fan-in nodes (the M8-bolt where-used), single monolithic layers with
  ~10⁵+ relationships, and OFPA-scale (10⁵–10⁶ file) worlds where even
  `LoadNone` open is minutes. The small **identity index is not deferred**
  (§5) — it is cheap and committed.
- **Runtime streaming.** This is editor/working-set tooling. A
  frame-budget-governed streamer may *consume* manifests; it is not produced
  by them.
- **Aggregate/threshold contract kinds.** Following `electrical:feeds` gives
  topology only; "can busway BW-4 take another 8 kW" needs the deferred
  solver tier, and every system-trace example must carry that caveat.

## 3. Verified mechanical facts

Measured on this machine (USD 26.08, ALab 2.3.0 + fixtures). Facts marked
**[26.08]** are the kind that shift across releases; the manifest records the
USD version its mask semantics were validated against (§8).

- `Usd.Stage.Open(entry, LoadNone)` opens all of ALab in ~126 ms; targeted
  `stage.Load(primPath)` is ~64 ms. **Scale honesty:** ALab is 4,296 mostly
  small layers. Nothing here is measured at 10⁵–10⁶ files or on single
  multi-GB layers; §2 names those as index/partial-open triggers.
- A prim whose specs exist **outside payload interiors** is addressable under
  `LoadNone` and `GetPrimStack()` returns its (layer, path) pairs. **A prim
  defined only inside an unloaded payload is not on the stage at all**
  (probe: `GetPrimAtPath` → invalid), and `GetPrimStack` on the
  payload-bearing prim lists only layers outside the payload. The original
  spike worked because placement-level paths satisfy the narrow condition.
  Closure must cross payload arcs itself (§4).
- `Load` follows composition arcs only; relationship targets do not load.
- Population masks include descendants **and ancestors** of masked paths.
  **[26.08]** A mask does not rewrite relationship target *lists*: under a
  mask excluding the target, `GetTargets()` still returns the path; the
  target **object** is simply unpopulated (a computed binding resolves to an
  invalid prim). Stranding is real; the mechanism is non-population, not
  list surgery.
- **Instancing (probe, [26.08]):** a mask path *below* an instance root is
  honored — the instance populates, the deep path is valid as an **instance
  proxy**, and `GetPrimStack` on instance-proxy paths returns
  prototype-space specs, so closure's move 1 works inside instances. But the
  **prototype is never carved**: masking inside an instance still populates
  the shared prototype whole. Spine-not-canopy is therefore false *inside*
  instances, and pricing/declaration must be at prototype granularity (§4).
- Re-rooting a prim via a new reference strips out-of-scope relationship
  targets (the encapsulation finding). A pull is **deferral over the
  original stage, never extraction**.
- `deps/walk.py` as it stands: records every variant's edges (by design),
  **skips internal (asset-path-less) references and payloads entirely**, and
  unions list-op slots **ignoring deletes**; value clips are invisible.
  Implementation must fix all three (§4); they are recorded here because the
  review caught the spec assuming completeness the walker doesn't have.

## 4. The thread graph

**Node = (layer, prim path).** Closure alternates two moves:

1. **Composed path → authored specs (USD's move).** The authority is the
   **prim index**, not naive prefix rewrite: traverse
   `prim.GetPrimIndex()` nodes (`ComputeExpandedPrimIndex` where culled) and
   map spec paths through `node.mapToRoot`, which handles variant
   components, inherits/specializes, and multi-pair maps correctly, and is
   available under `LoadNone` — including on instance-proxy paths
   (prototype-space specs, per §3). Where the prim index is unavailable
   (below unloaded payloads), see the payload rule below. Relocates:
   detected → declared unsupported.
2. **Authored specs → new paths (our move).** In each layer of the stack,
   scan recorded edges whose `src_prim` is at or below the spec path,
   **filtered to the variant branches actually selected** in the composed
   context (selections are visible in the spec paths' `{vset=sel}`
   components plus authored selections). Edges in unselected variants are
   declared at the boundary as their own kind
   (`usd:variant(lod=full): 3 edges, not in selected world`), never
   followed silently and never silently dropped. Followed relationship
   targets apply **full list-op semantics — deletes honored, strongest
   opinion wins** — not a union of slots. Targets that fail path
   translation out of an arc's domain are **elided exactly as Pcp would
   elide them** and declared, never reinterpreted as composed-namespace
   paths. Internal references/payloads are edges. Value-clip asset paths
   enter the accounting.

**Payload interiors.** Below an unloaded payload, move 1 has no prim index.
Closure continues **in layer space** across the recorded ARC(payload) edge —
the deps records exist because layers are walked offline — synthesizing the
composed↔layer mapping from the arc chain. Variant selections *inside* an
unloaded payload are unknowable without loading; closure over-approximates
there (errs inclusive, so strand-freedom survives; pricing becomes an upper
bound) and the mandatory verification pass (§8) is the backstop.
Implementations may instead target-`Load` the spine during closure at ~64
ms/member, declared in the receipt.

**Instancing rule** (extends §12's instancer verdict): members inside
instances are legal (proxies address them), but masks populate prototypes
whole. The manifest therefore **accounts and declares at prototype
granularity** — "member …/b1/geo/glass rides prototype of bottle.usd (whole,
shared ×100)" — and closure treats a followed target inside a *different*
instance as pulling that instance's root. De-instancing (session-layer
`instanceable=false`) is a priced, declared escape hatch, never an implicit
side effect.

**Spine, not canopy** — outside instances, unchanged: every member
contributes its ancestors' own opinions and never its siblings, agreeing
with mask semantics by construction. One physics-shaped exception in §6.

Standing disciplines carry over: unreadable layers recorded, non-fatal;
`inherits` to class prims includes class specs (and the receipt notes class
opinions can arrive from any root-stack layer); closure runs seed-outward on
demand.

## 5. The ask

A pull names a **context** (asset in the ledger, or any raw USD file) and
one or more seed predicates. **Multiple seeds union.**

| seed | plane it reads | example |
|---|---|---|
| `name:` (bare glob shorthand) | namespace names, lexical | `chemistry_bottle01*` |
| `id:` | the identity plane (below) | `id:hero-car`, `id:occ:...` |
| `offers:` / `requires:` / `role:` | contract plane | `role:propSocket` |
| `where:` | attribute plane (below) | `where:finish=translucent` |
| `near:` / `within:` | declared bounds | `near:id:rack-R42,5m`, `within:0,0,0,10,3,10` |
| `path:` | scene location — fallback | `path:/root/shelf01/x` |

**The identity plane.** Identity is metadata, never an address — and the key
is **configurable per context**: an ordered precedence of metadata fields
(`absent:id`, `ifc:GlobalId`, `assetInfo.identifier`, …) declared in the
context's rules, because converters issue identity in their own dialects.
Two identity levels: **entity** identity (what a thing is) and **occurrence**
identity (this placement — authored on the placement prim, the same
`absent:id` promotion one level down), so `id:occ:…` addresses one placement
restructure-proof. Type-identity resolving to thousands of instances is
reported as such, not treated as ambiguity. A small **persisted identity
index** (id → paths per context@rev) is committed — it is not the deferred
closure index, and full-stage metadata scans per pull are not acceptable at
10⁶ prims.

**The attribute plane.** `where:` reads interface surfaces where they exist,
and **falls back on raw contexts to attributes and customData authored on
the prims themselves** (readable `LoadNone`-cheap from prim stacks) — so an
IFC monolith with property sets is queryable before any extraction, and a
Pset extractor is the AEC analogue of `extract.py`. The resolution
declaration carries the **complement**: `matched 212; 340 surfaces do not
author 'material' — not evaluated`. Sparse authorship must never produce a
confident under-count.

**Predicate grammar (v1, defined not exemplified):**
`where:<attr>=<value>` — `=` is the only v1 operator. Against exact-kind
attributes: canonical-typed equality (values parsed to the attribute's type;
no stringly comparison). Against set-kind attributes: **membership** of the
value. Spatial/angular attributes are not addressable by `where:` in v1
(reserved, error). Values do not glob; only `name:` globs. Conjunction:
deferred, syntax reserved.

**Spatial seeds.** `within:` (axis-aligned box, context units) and `near:`
(radius around a resolved seed) evaluate against **declared bounds** —
`extentsHint` and equivalent authored hints on placements — which keeps them
on the relational plane: bounds are declarations, not loaded geometry.
Placements without authored bounds are declared in the complement count.

**Registered edge extractors.** References encoded in attributes
(`asset game:spawnTable = @…@`, path-valued strings) produce no edge and
would otherwise be invisible rather than boundary-declared. Teams register
extractors — "attribute X of schema Y encodes an edge of kind Z" —
versioned and promoted like rule sets. The completeness claim is scoped
honestly everywhere it appears: **strand-free over relationships, arcs, and
registered extractors; attribute-encoded references outside registered
extractors are not visible and cannot be declared.** The robotics
calibration-chain and games soft-reference cases are both this finding; the
recommended authoring pattern for new data is a contract offer whose members
are rel targets (a `CalibratedRig` offer), which `role:` then pulls closed.

Rules: every seed's resolution is declared in the receipt (mode, matches,
complement, and — for the future semantic tier — confidence and runners-up).
Exact kinds (`id:`, `path:`) matching more than one report candidates, never
guess. Asks read only the relational plane.

## 6. What a followed edge contributes

- **`usd:arc`**: no members (composition handles populated prims' arcs);
  feeds accounting.
- **Named relationships**: the target joins the population set with its
  spine — with the elision, list-op, variant, and instancing rules of §4.
- **Contract edges**: the bound offer's anchor spine, plus declared
  **carrier** spines. Carrier and `boundTo` are **authored in
  assembly/interface layers, at composed-scope paths, outside payload
  interiors** — authored inside a referenced asset they cannot target
  sibling placements (Pcp elides out-of-domain targets; the project's own
  encapsulation finding, pointed at its own mechanism). A carrier whose
  targets fail translation is a declared receipt error. Derivation-rule
  carriers (the `furniture_*` rule) are **advisory**: legitimate for set
  dressing, refused for offers with physical meaning (authored loadLimit,
  or offers that resolve into joints) — an engineered flange's carrier is
  authored or absent, never guessed.

**Semantic omission classes.** A boundary count alone is dishonest when
omission changes meaning rather than leaving a hole. Every not-populated
declaration carries a class: **inert** (an unbound material: renders grey)
or **meaning-changing** (a physics joint body: the joint silently becomes a
joint-to-world; a collision-group collection; a skel binding). The class
comes from a registry keyed by relationship kind/schema, extensible by
teams alongside their edge extractors.

**Physics closure rules** (the §12 discipline applied where the review
showed it stopped one step short):

- A **joint** with any body target outside the population is unsound:
  either all bodies join the population or the joint prim is excluded and
  declared (meaning-changing).
- An **articulation** (subtree under `PhysicsArticulationRootAPI` plus its
  joint set) is pulled whole or declared at the boundary, never partially —
  `JitsdArticulationInterfaceAPI.publicJoints/root` is the natural closure
  unit. Partial articulations change reduced-coordinate solver topology
  while composing without error.
- A populated prim under a `PhysicsRigidBodyAPI` ancestor pulls that body's
  full collision/mass subtree, or the RigidBodyAPI opinion is excluded and
  declared — partial collision sets silently corrupt computed inertia.
- The manifest carries a **fitness declaration**: population is
  render/inspection-complete relative to followed kinds and
  **contact-incomplete by construction** — gravity, `PhysicsScene`, ground
  contact, and broadphase pairing are non-relational and no edge walk can
  close over them. It states whether a `PhysicsScene` prim is populated and
  counts PhysicsAPI-bearing members whose contact environment was not
  evaluated. A sim consumer must be able to reject a manifest mechanically.

## 7. Direction, depth, and interrogation

Follow terms are **direction-qualified per term**: `Mount` (its natural
direction — requirement→offer), `up:electrical:feeds` (reverse: "everything
that feeds me"), `both:Mount`. Depth may also be per-term
(`electrical:feeds*8`), defaulting to the rule set's global depth. The
resolved direction and depth of every term is recorded in the manifest.

**Reverse closure** scans recorded edges for targets at or below the
frontier prims — on demand at current scale; §2 names the index trigger.
**Any reverse or `both:` term converts the pull from seed-outward closure to
depth-bounded component closure** (bottle → shelf → the shelf's 26 other
props), and the receipt says so; docs/10's rule — directional and
depth-limited, always — is imported into this spec verbatim.

**"What depends on this prim"** — in scope since rev 1 but never designed
until this revision — is reverse closure reported as interrogation rather
than population: `jitsd who <ask>` returns the incoming-edge set (kind,
source, via) at each depth, without emitting a manifest. Same machinery, no
mask.

**Ordered provenance.** The manifest records per-member provenance — `via
kind K from member M` — so a system trace (`up:electrical:feeds` from rack
R42) reads back as the chain (R42 ← PDU-2B ← BW-4 ← TX-1), not a bag of
paths. The walk has this in hand; discarding it was the omission.

The **follow language** is versioned: bare kind names and the
direction/depth prefixes above are the v1 subset; syntax containing `->` or
quantifiers is reserved for the path algebra (`Mount⁻¹ ∘ shading` stays
latent but the wire format won't break when it lands). Contract names and
relationship kinds share the namespace; `contract:` prefix disambiguates,
and a bare contract term may pin a major (`Mount@2`).

## 8. The manifest

A USDA file whose `customLayerData` records **the complete evaluation
inputs** — a pull is verifiable by recompute-and-compare, like everything
else in the system:

- context: `asset@rev` for ledger contexts; **content hashes for raw-file
  contexts** (a bare path is not an identity);
- **the layer set**: identity + content hash for every layer in members'
  prim stacks — `context@rev` pins one layer, not the composition, and a
  manifest is valid against its recorded layer set, not a name;
- **variant selections in force** at closure time (the mask is meaningful
  only in that composed world);
- asks verbatim, per-seed resolution declarations with complements;
- follow terms **with resolved direction and depth**, rule set as
  `name@rev`, carrier rules and edge-extractor registry as `name@rev`;
- members with per-member provenance and instancing/widening declarations;
- boundary per §8-def below; fitness declaration (§6); accounting: layer
  bytes (upper bound where payload-interior, labeled), **non-layer assets
  reachable from members** (textures, clips — enumerated or declared "N
  asset-path targets not priced"; composed cost is out of scope for v1
  pricing and says so);
- USD version the mask semantics were validated on (§3);
- a digest over (member list + layer set + evaluation inputs);
- a reserved `loadSet` field for the deferred partial-payload extension.

**Boundary, defined** (so two implementations cannot disagree while both
"conforming"): `boundary(P, F, d)` = the set of **distinct composed target
paths** t ∉ P reachable by one recorded edge (s, kind, t) where s is among
P's member specs (spine-ancestor-authored edges excluded — ancestors are
opinions, not members), the edge untraversed; **grouped by kind** (kind is
the group-by, not the membership criterion); edges cut by the depth cap
reported under a distinct reason from kind-not-followed; targets already in
P excluded. Multiplicity is available as a secondary count.

**Verification pass — mandatory.** After emit, open the masked stage and
assert every member path resolves to a populated prim; an unresolved member
is fatal (it means closure over-approximated into a world the mask isn't
valid for — the exact silent omission §12 forbids). Consumers re-run the
same check against the recorded layer hashes before trusting a manifest.

**Consumption:** `--format mask` writes the member list to a **file**
(10⁴-member selections exceed ARG_MAX; the comma-joined form is a
convenience for small pulls), consumed as
`usdrecord --mask "$(cat pull.mask)"` or via the Python population-mask API.

## 9. Prim seeds in slices

- Ask grammar = slice-seed syntax, context-scoped
  (`lab_workbench01:where:finish=translucent`) or context-free for `id:`.
- **Members are selections with an authority rule** (the review's sharpest
  cross-lens convergence): *at the slice's own coordinate, the recorded
  paths are authoritative and MUST equal ask replay — a checkable
  invariant. At any other coordinate the ask is authoritative: the
  selection re-resolves, the diff is reported as drift, and recorded paths
  that no longer resolve are declared — never silently reused, never
  silently dropped.* With occurrence ids, renames surface as moved, not
  lost. A selection is pinned by the slice's **full coordinate** (the
  baseline/pin set), not the context asset's revision alone.
- Pricing: from the manifest's accounting (upper-bound labels included).
- Impact: asset-level re-evaluation, joined to selections presentationally.
- Rule sets: gain the follow-language version field (§7); otherwise
  unchanged.

## 10. Testing

1. Per-seed unit tests on authored fixtures (multi-line USDA).
2. Closure: strand-free (every followed target populated), spine-not-canopy
   (sibling absent, ancestor opinion present), **variant filtering** (edge
   in unselected variant → boundary, not member), **list-op deletes
   honored**, **elision** (out-of-domain target declared, not invented),
   **internal references** followed.
3. **Instancing fixtures**: mask below instance root → prototype-whole
   accounting declared; followed target inside foreign instance → instance
   root pulled.
4. **Physics fixtures**: a two-link jointed body asserts
   both-bodies-or-excluded-and-declared; an articulation asserts
   whole-or-boundary. Without these the strand-free suite proves the wrong
   theorem.
5. **Boundary conformance**: byte-identical boundary counts across fixtures
   per the §8 definition.
6. **Manifest**: recompute-and-compare from recorded inputs reproduces the
   digest; verification pass catches a deliberately vacuous member.
7. Payload-interior closure: member below unloaded payload reached via
   layer-space arc crossing; verification pass confirms.
8. ALab acceptance (§11), pxr-gated, local like the POC.

## 11. Acceptance criterion

Reproduce the 2026-09-01 spike renders from one-line asks, no hand-glue:

```
jitsd pull 'chemistry_bottle01_0004' --context lab_workbench01          → one bottle
jitsd pull 'chemistry_bottle01_0004' --context lab_workbench01 \
           --follow Mount                                               → bottle + carrier
jitsd pull 'where:finish=translucent' --context lab_workbench01         → 26 placements
```

Asks 1 and 3 reproduce the spike masks byte-for-byte; ask 2 produces the
mask the carrier *rule* derives (the spike's hand mask was approximate; the
rule is authoritative). `--follow Mount` uses the contract's natural
direction; the flag is part of the recorded evaluation inputs (§8), which is
why it appears in the manifest even though it is not part of the quoted ask.
Each manifest passes the §8 verification pass and recompute-and-compare.

## 12. Standing review verdicts honored

- Identity is metadata, never an address.
- Cut only at declared boundaries; never finer than a contract-closed unit.
- **Indexed and structural correspondences are unsound under partial
  exclusion** — point-instancer `protoIndices`, skel joint indices, GeomSubset
  indices, **physics joints/articulations/rigid-bodies (§6), scenegraph
  instance prototypes (§4)**: pulled whole, or excluded and declared.
- Fail open on presence; silent omission is fatal; absence, boundary, and
  **omission class** (inert vs meaning-changing) are always declared.
- Deferral for working sets; authorization is a separate gate.
- Rules and asks read only the relational plane.
- Completeness claims are scoped to what the walker can see (§5 extractors).

## 13. Review record (2026-09-01)

Six adversarial lenses: manufacturing/PLM, AEC/data-center, robotics/sim,
games/realtime, USD internals, data-model/query semantics. Convergence
before adjudication: variant-world validity (2 lenses, independently),
instancing (5), spatial seeds (3), direction (3), ask-vs-paths authority
(2), attribute-encoded references (2 via different domains). Probes
confirmed: payload-interior invisibility, mask non-carving of prototypes
(narrowing the reviewer's refusal claim — proxies are addressable and move 1
works through them), mask target-list precision, walker internal-ref and
list-op-delete gaps. Adopted as design: §4 variant filtering + payload
crossing + instancing rule, §5 identity plane/occurrence ids/spatial
seeds/raw-context fallback/extractors/predicate grammar, §6 omission
classes + physics rules + carrier constraints, §7 direction/interrogation/
provenance/follow-language versioning, §8 self-certifying manifest +
boundary definition + verification pass, §9 authority rule. Deferred with
named consequences: §2. Not adopted: refusing masks below instance roots
(measurement showed proxies work; accounting rule instead); federation
N-root contexts (scoped out, reserved); effectivity channels (ledger
design, not this spec).
