# Architecture

## The layer stack

```
Consumption    Hydra · Fabric · renderers · game runtimes
Composition    USD — LIVRPS, layers, schemas, payloads        ← unchanged
Resolution     JIT-SD — contracts, channels, baselines, contexts   ← new
Storage        content-addressed objects + append-only ledger
```

JIT-SD does not touch composition. Everything USD does well it keeps. What it
adds is the layer *below* composition: where layers come from and what they
mean.

## The two planes — the single most important structural rule

**Relational plane.** Parameters, ports, contracts, constraints, dependency
structure. Kilobytes. Never sees a triangle.

**Geometric plane.** Opaque kernels invoked at the leaves of a resolved
derivation. Gigabytes.

If geometry leaks into the relational plane you lose termination guarantees,
cacheability, and any hope of resolving a graph in under a second. Keep them
strictly separated.

Operational consequence: resolve the entire graph using only parameters and
port specs — fast, small, high cache hit — *then* fan out geometry generation
in parallel. Naive fan-out gives a serial chain (chassis → hub → wheel →
aero-on-wheel) where tail latency **sums** rather than maxes.

## USD already has the doors

Far less new machinery than it first appears. These are the integration
points, all existing USD:

| Hook | Role in JIT-SD |
|---|---|
| `ArResolver` (Ar 2.0) | asset paths need not be files; the resolver generates them |
| `ArResolverContext` | per-stage context bound at `UsdStage::Open` — the channel for **caller context** |
| Dynamic file format arguments / dynamic payloads | `SdfFileFormat` generates layer content from metadata authored on the prim — the core procedural hook |
| Payloads | explicit, deferrable — USD's own two-phase design |
| Population masks (`OpenMasked`) | pull only a subtree |
| `purpose` (proxy/render/guide) | USD already ships a **two-context compilation system**; JIT-SD generalises it to N |
| Codeless API schemas (21.08+) | declare contracts as pure plugin data, no C++ build |
| Hydra scene indices | filtering / generative procedurals at the consumption end |

**Two possible insertion points, and the choice matters.** At the
asset-resolution end (Ar + dynamic payloads) the DCC receives a fully formed
stage. At the Hydra end (scene index filters) transformation happens per
renderer, per frame.

Trade-off is latency vs. trust: resolution-side compilation can enforce
redaction *before bytes leave the server*; Hydra-side is faster and more
interactive but the client already holds everything.

> **Anything security-relevant happens resolution-side. Anything purely about
> representation may happen in Hydra.**

## The two clocks — never conflate these

- **Subject time** — *when in the thing being described*. Film: the frame.
  Manufacturing: a step in an assembly sequence or an operating state. AEC:
  construction phase. Robotics: episode timestep. USD models this well:
  `timeCode`.
- **Evaluation coordinate** — *which version of the world's definitions*. USD
  models this **not at all**. This is the baseline (`03-versioning.md`).

"Give me frame 47" and "give me frame 47 as the world was defined at baseline
118" are different queries, and only the second is reproducible.

## Protocol: resolve, then materialise

1. **Resolve** → a **manifest**: the resolved derivation, each node a content
   hash of `(kernel id + version + fully substituted arguments)`. Kilobytes.
   A readable `.usda`.
2. **Materialise** → the heavy `.usdc` crates behind the payloads, fetched by
   hash, immutable, cacheable forever.

USD's payload mechanism *is* the manifest/blob split. Nothing new is added; the
existing phase is pointed at a generator instead of a disk.

**Hash the derivation, not the output bytes.** Meshers and subdivision are not
bit-deterministic across architectures and compiler flags; keying the cache on
output bytes yields silent misses forever. Key on
`(generator, version, resolved inputs, baseline)`; use the output hash only for
integrity.

If output determinism is wanted anyway, WASM kernels give deterministic FP,
sandboxed vendor code, and portability — and let vendors ship a kernel instead
of hosting an endpoint.

## Rules layer

**Datalog core**, not RETE and not an OO schema, because:

- magic-set rewriting gives exactly the demand-driven top-down pull required —
  "give me the Car" only touches the facts it needs;
- why-provenance falls out free, and the derivation tree *is* the build receipt;
- monotone, so incremental maintenance on an upstream parameter change is a
  solved problem (semi-naive / DRed / differential dataflow);
- stratified negation is enough for real rules and keeps evaluation decidable.

Facts are USD-shaped (`hasAPI`, `provides`, `requires`, `satisfies`). Output is
a **composition plan**: an anonymous root layer of references, payloads and
variant selections. The Datalog never touches a polygon.

**A constraint tier sits above it.** Datalog cannot express "diameter must
satisfy arch clearance, from the approved list, minimising unsprung mass."
Datalog resolves the discrete question (which providers, what structure,
candidate space); an interval/CSP or LP solver resolves the numeric fit.

**The emitted plan must always be flattenable and inspectable in usdview.**
"The system decided something and I cannot see why" is fatal in production. The
derivation must be a USD layer a TD can open at 2am. Provenance rides along as
prim metadata.

## Partial failure and arbitration

**Failure policy is declared, not exceptional.** Each dependency is
`required | substitutable(fallback) | omittable`. An endpoint being down should
not mean no car. With no server retry state, the client re-issues against the
same baseline — cheap, because everything already resolved is cache-hot.

**Arbitration is declared, not emergent.** When aero wants −20 mm ride height
and suspension travel forbids it, authority ordering per property must be a
first-class rule with a defined outcome. If it emerges from evaluation order,
the same query answers differently depending on endpoint latency.

## Feedback is out of band

Assembly constantly discovers things Definition must fix: the rig cannot hit
the pose, two parts interfere, a duct runs through a beam. **Do not let the
engine write back upstream** — that is how you get the stateful synchronised
mess this design exists to avoid.

Dataflow stays strictly acyclic. Feedback is a **change proposal**. The upside
of declared contracts is that a downstream failure is expressible as a
*violated contract predicate* — machine-readable, and routable to the team that
owns the contract. Better than a ticket saying "the wheel does not fit."

## Operational payoff

No session affinity. Any coordinator instance serves any request; the hash
determines the work. Failover is trivial, scaling is linear.

## Receipts

The one thing that is never forgotten: an append-only log of
`(query, context, baseline, manifest hash)`. Not for the engine — for the
humans who need to know what actually rendered or shipped. Stateless
evaluation, persistent receipts, kilobytes each.
