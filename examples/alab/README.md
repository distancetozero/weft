# Measured compatibility on real geometry — the ALab workbench

The one mechanism in this project with no prior art anywhere is a contract
whose compatibility is *measured*: a provider declares how far each offered
mount may move, and a promotion that moves one further is **refused and
named**. Until now that only ever ran on a toy car of boxes and cylinders.

This runs it on [Animal Logic's ALab](https://dpel.aswf.io/alab/), the first
open-sourced complete USD production scene: `lab_workbench01`, an assembly
placing **437 props at real transforms** under six groups.

    python examples/alab/poc.py /path/to/ALab-2.3.0/ALab

## What is authored, and what is honest about it

**Nothing is hand-written.** `jitsd/extract.py` reads the assembly and derives
the contract surfaces from it:

- the workbench **offers** one `Mount@1` per placement, frame = the assembly's
  own `xformOp:translate`, role = the placed asset's name;
- each placed asset **requires** `Mount@1` with role = itself, cardinality
  `many`, so it binds every place the bench offers it.

Props are base-origin — verified from their authored `extentsHint`: bottles,
screws, washers, the bench seat all have `min.y ≈ 0`, centred in x/z — so an
offer frame really is where a prop's base sits.

**Where the tolerances come from — three tiers, kept distinct.**

| value | tier | source |
|---|---|---|
| offer frames | derived from data | the assembly's own translates |
| provider envelope (1 cm) | **policy** | given to the extractor; every offer carries `jitsd:envelope:source = "policy:extractor-default"` so nobody mistakes it for the shelf's real promise |
| consumer tolerance | derived by a stated rule | **10 % of the prop's own footprint**, from `extentsHint`; recorded on the interface as `# derived: 10% of a 5.9 footprint`. A thumb tack gets 0.08 cm, a bottle 0.59 cm, the bench 45 cm. Five props state no extent and get no tolerance — the envelope governs them, which is honest; an invented number is not. |

## A relationship is not a position

An offer binds on a **set of named attributes**, each with its own rule for
"still compatible": `spatial` (moved less than a tolerance), `angular`,
`exact` (a material id, a unit system — unchanged), `set` (purposes offered —
still offers everything required). A consumer constrained on material only
binds where it matches, and a material change on the provider is a break for
it. A *view* is which attributes a consumer reads: lighting binds on material
and position, FX on collision purpose and position, an engineer on neither.

Threshold and aggregate kinds (power draw, busway capacity) are deliberately
absent: they need a solver, not a comparison.

This run exercises the spatial attribute on real geometry; the exact and set
kinds are covered by `tests/test_reeval.py`.

**The republish is simulated at the interface level.** "Raise shelf01 by 3 cm"
shifts that group's offers by a vector; the payload is unchanged. Re-modelling
ALab is out of scope, and the gate only ever reads the surface — it cannot
tell the difference. That is the point of the design, and the reason the
simulation is legitimate rather than a cheat.

## The run

```
== extract contract surfaces from the assembly
   437 placements in 6 groups -> 437 offers, 164 consumer surfaces  (221 ms)
   camera01             3 mounts
   floor_dressing01     8 mounts
   shelf01             65 mounts
   shelf02             51 mounts
   wall_dressing01      9 mounts
   workbench01        301 mounts

== ingest: workbench + every placed prop, each with its surface
   165 assets on @approved

== bind: requirements -> offers, by contract and role only
   164 consumers bound to 437 offers; ok=True

   shading sets from 158 real look layers; finish derived for 8 (8 translucent, 0 opaque)
   consumer tolerances derived for 159/164 props: proc_dev_circuit_fuse01 0.06 cm .. furniture_workbench01 44.96 cm

== bind: requirements -> offers, by contract and role only
   328 consumers bound to 601 offers; ok=True        (164 mounts + 164 representations)

== cut baseline
   baseline 000001  merkle f51109e315d0b3f1

== republish workbench: shelf01 raised 0.05 cm (inside every tolerance)
   promoted v002 -> @approved  (0 violations)

== MEASURED, NOT ASSERTED: shelf01 raised 0.7 cm -- inside the provider's 1 cm promise
   provider self-check (what it asserted): 0 violations
   consumer re-evaluation (what was measured): 164 consumers checked, 19 broken
   REFUSED by consumers: 19 props would break, though the provider kept its promise
     chemistry_bottle01         position moved 0.65, consumer tolerates 0.5913
     chemistry_test_tube02      position moved 0.65, consumer tolerates 0.2225
     decor_thumb_tack01         position moved 0.65, consumer tolerates 0.0823
     ... and 16 more
   @approved still at v002

== republish workbench: shelf01 raised 3 cm (past the envelope)
   REFUSED: lab_workbench01 v004 -> @approved  (65 provider violations, 62 consumer violations)
     envelope  /lab_workbench01/shelf01/chemistry_bottle01_0004: moved 2.95, envelope allows 1
     ... and 61 more, every one on shelf01
   @approved still at v002

== impact preview from a slice: a lighter's slice of the bottles
   slice: 3 bottles.  candidate lab_workbench01@wip breaks 34 consumers:
     inside the slice  (3): chemistry_bottle01, chemistry_bottle02, chemistry_bottle03
     outside the slice (31): chemistry_microscope01, chemistry_test_tube02, ...
   -- the lighter sees what their edit breaks for other teams, without loading their slices

== pull one thread: closure by relationship kind, and a team's rule set
   seed chemistry_bottle01, follow everything: 165 members  (the bench references every prop)
   seed chemistry_bottle01, follow Mount only: 2 members  -> chemistry_bottle01, lab_workbench01
   declared at the boundary, not pulled: 163 threads (usd:arc not followed)
   rule set lookdev.rules@v001 saved and promoted; applied to a different seed: 2 members

== drift since baseline 000001
   baseline f51109e315d0b3f1   now d44304852ec16712   DRIFTED

== verify
   blobs ok 333  corrupt 0  missing 0   stale generators 0
```

## The contract runs both ways

The prop consumes a mount. With `represent=True` it also **offers what it
is**: a `Represents@1` offer whose `provides` set is derived from its own
department sublayers — and on this corpus the set is genuinely informative:
326 entities carry `{modelling, preview, surfacing}`, assemblies differ, one
carries `rigging`. The bench **requires** each placed asset's representations,
so the assembly is a consumer of its own props.

```
== two-sided: a prop republished without its preview department
   REFUSED: chemistry_bottle01 dropped preview
     unresolved lab_workbench01 rep_chemistry_bottle01: no provider of Represents@1
   -- the ASSEMBLY is the broken consumer: the contract runs both ways
```

**Shading, from the real look layers.** The Asset Structure package ships
placeholder looks; with the Techvar data overlaid, 158 assets yield a real
shading set — and ALab names its materials uniformly (`usd_full`,
`usd_preview`, `usd_preview_proxy`), which makes the names a *vocabulary*,
not identity. That uniformity is exactly what a set attribute wants:

```
== shading is a binding attribute: tool_screw01 republished without usd_full
   REFUSED: tool_screw01 dropped usd_full from its shading set
     unresolved lab_workbench01 rep_tool_screw01: no provider of Represents@1
   -- a shading change breaks exactly the consumers bound on shading
```

Material *identity* lives in the shader parameters, so one exact attribute is
derived from them: `finish` — translucent or opaque, from authored
`UsdPreviewSurface` opacity. Only 8 looks author opacity (all translucent —
bottles and jars at 0.1); the other 150 get **no** finish attribute, because a
rule that invents "opaque" for unauthored data would be a claim nobody made.

**Interface sublayers.** With `into_assets`, each surface is written into the
entity's own structure — `entity/<a>/interface/<a>_interface.usda`, sublayered
into the entity root as one more department beside `modelling/`, `preview/`,
`surfacing/` — rather than a sidecar. The surface is then versioned with the
asset and visible to any USD tool. (`departments()` deliberately ignores the
`interface` sublayer, or extraction would be self-polluting: every re-run
would add "interface" to the very set the interface declares.)

## Pulling one thread

The premise of the whole system is pulling on threads explicitly, by rule,
without loading the whole thing. Closure that follows *every* relationship
reconverges on the whole thing: seed one bottle and you get all 165 assets,
because the bottle needs the bench and the bench's assembly references every
prop. Correct, and useless.

`follow` makes which threads to pull a choice. Every edge carries the kind of
relationship it is — a contract name like `Mount`, or a USD kind like
`usd:binding`, `usd:arc`, `usd:inherit` — and closure follows only the kinds
named. What is not followed is **declared at the boundary**, never silently
dropped: *163 threads, usd:arc not followed*.

A **rule set** is the reusable half of a slice — closure, follow, depth,
attributes in view, context — stored as an asset revision, promoted through
channels like anything else. `lookdev.rules@v001` above is one: *mounts only,
one hop, position in view*. A team shares a way of seeing, not a scene file.

    jitsd select chemistry_bottle01 --follow Mount
    jitsd select chemistry_bottle01 --rules lookdev.rules
    jitsd select 'chemistry_*' --follow Mount,usd:binding --save-rules lighting.rules

Whole run: **3.5 s** (2.6 s of it opening 164 entity layers for `extentsHint`).

## What it shows

- **Every one of 437 real placements bound by contract and role alone.** No
  consumer names the workbench; no consumer names a path inside it.
- **Measured, not asserted — the exemplar half, on real geometry.** The
  0.7 cm move is inside the provider's 1 cm promise: the provider's own check
  passes with 0 violations. Re-evaluating the 164 consumers finds 19 whose own
  tolerance is tighter, and the promotion is refused *by the consumers*, each
  named with what it tolerates. The envelope is what the provider asserted;
  this is what was measured.
- **The 3 cm move fails both halves**: 65 provider violations (its promise) and
  62 consumer violations (their tolerances), every one on the moved shelf and
  none of the other 372 mounts.
- **Impact preview across slices.** A lighter's slice of three bottles asks
  what the candidate breaks: 3 inside their slice, 31 outside it — without
  loading anyone else's slice. This is the same computation as the gate,
  called from the slice.
- **The gate measures against what is in force.** Distances are reported
  against the currently approved surface (already +0.05), not the original.
- **`@approved` never moved.** Both refused revisions exist in the ledger and
  can be inspected.
- **Drift is visible and attributable.** The baseline's merkle root differs
  from the current world because a compatible republish landed after the cut.

## Pulling at prim level

Everything above pulls at *asset* granularity: `jitsd select` decides which
assets to load, not which prims inside them. `jitsd pull` (spec sections
4–8) works one level down — seed by identity, attribute, bounds, or path,
follow only the relationship kinds named, and get back a prim mask, no
asset ingestion and no `.jitsd/` repository required. It runs directly
against the checked-out ALab tree:

    JITSD_ALAB=/path/to/ALab-2.3.0/ALab python -m pytest tests/test_alab_pull.py -v

The test's setup fixture regenerates the workbench and placed-prop
interfaces with `anchor="root"` and `carrier_rule="group-furniture"`
(Task 11) — root-anchored overs so the surface composes onto the
assembly's own `/root` placements, which the asset-anchored interfaces
checked into this tree earlier do not.

**One prim, by path or by bare name** — the lexical form finds the same
prim without a path in the question:

    $ jitsd pull 'path:/root/shelf01/chemistry_bottle01_0004' --context $JITSD_ALAB/entity/lab_workbench01/lab_workbench01.usda
    seed path:/root/shelf01/chemistry_bottle01_0004 -> 1 (path)
    members (1):
      /root/shelf01/chemistry_bottle01_0004        seed
    boundary (8):
      /root/shelf01/furniture_lbracket01_0001      Mount                    not followed [inert]
      /root/shelf01/furniture_lbracket01_0001      jitsd:offer:carrier      not followed [inert]
      /root/shelf01/furniture_lbracket01_2         Mount                    not followed [inert]
      /root/shelf01/furniture_lbracket01_2         jitsd:offer:carrier      not followed [inert]
      /root/shelf01/furniture_parts_cabinet02_0002 Mount                    not followed [inert]
      /root/shelf01/furniture_parts_cabinet02_0002 jitsd:offer:carrier      not followed [inert]
      /root/shelf01/furniture_shelving01_0001      Mount                    not followed [inert]
      /root/shelf01/furniture_shelving01_0001      jitsd:offer:carrier      not followed [inert]
    fitness: contact-incomplete by construction

    $ jitsd pull 'chemistry_bottle01_0004' --context $JITSD_ALAB/entity/lab_workbench01/lab_workbench01.usda
    seed chemistry_bottle01_0004 -> 1 (lexical)
    members (1):
      /root/shelf01/chemistry_bottle01_0004        seed

**Following the Mount contract to its carrier.** `--follow Mount` walks the
advisory `jitsd:offer:carrier` edges the regenerated interface authors,
pulling the shelf furniture that carries the bottle — not the other 300+
props on the bench:

    $ jitsd pull 'path:/root/shelf01/chemistry_bottle01_0004' --follow Mount --context $JITSD_ALAB/entity/lab_workbench01/lab_workbench01.usda
    members (5):
      /root/shelf01/chemistry_bottle01_0004        seed
      /root/shelf01/furniture_lbracket01_0001      Mount <- /root/shelf01/chemistry_bottle01_0004
      /root/shelf01/furniture_lbracket01_2         Mount <- /root/shelf01/chemistry_bottle01_0004
      /root/shelf01/furniture_parts_cabinet02_0002 Mount <- /root/shelf01/chemistry_bottle01_0004
      /root/shelf01/furniture_shelving01_0001      Mount <- /root/shelf01/chemistry_bottle01_0004

**An attribute ask, rendered.** `where:finish=translucent` resolves against
`jitsd:bind:finish`, authored on each placed asset's own `Represents` offer
— derived at extraction from real `UsdPreviewSurface` opacity
(`jitsd/extract.py:finish`), never invented. No path names a single one of
the 26 hits:

    $ jitsd pull 'where:finish=translucent' --context $JITSD_ALAB/entity/lab_workbench01/lab_workbench01.usda --mask-out /tmp/pull.mask
    seed where:finish=translucent -> 26 (attribute, 1744 do not author the key)
    members (26):
      /root/shelf01/chemistry_bottle01_0004        seed
      /root/shelf01/chemistry_bottle01_0005        seed
      /root/shelf01/chemistry_bottle01_0007        seed
      ... 20 more, all under /root, every one a bottle, beaker, jar or set
          square from the 8 translucent assets
    boundary (16): the shelf furniture that carries these props, and every
      other contract on the bench — 8 furniture pieces (Mount + carrier,
      not followed), plus the 8 hits' own `represents` instance proxies
      widened to their placement roots
    fitness: contact-incomplete by construction
    mask: /tmp/pull.mask  (usdrecord --mask "$(cat /tmp/pull.mask | tr '\n' ',')" ...)

    $ /usr/bin/usdrecord -w 1280 --mask "$(tr '\n' ',' < /tmp/pull.mask)" $JITSD_ALAB/entity/lab_workbench01/lab_workbench01.usda /tmp/pull.png
    Recording time code: EARLIEST

26 members — exactly the 26 paths an earlier exploratory spike recorded by
hand. `tests/test_alab_pull.py::test_ask_translucent_matches_spike_mask`
embeds that spike's mask as `SPIKE_TRANSLUCENT_MASK` and asserts
`set(paths) == set(SPIKE_TRANSLUCENT_MASK)` — an enforced invariant this
suite checks on every acceptance run, not a one-off observation. The
render shows 26 pieces of glassware — beakers, bottles, a soda bottle, set
squares — floating at their production transforms in otherwise empty
space. Nothing else on the lab bench, and none of its non-translucent
props, was ever composed.

**Who depends on this prim.**

    $ jitsd who 'path:/root/shelf01/furniture_shelving01_0001' --kinds Mount --context $JITSD_ALAB/entity/lab_workbench01/lab_workbench01.usda
      /root/shelf01/chemistry_bottle01_0004        Mount                    -> /root/shelf01/furniture_shelving01_0001
      /root/shelf01/chemistry_bottle01_0005        Mount                    -> /root/shelf01/furniture_shelving01_0001
      /root/shelf01/chemistry_bottle01_0007        Mount                    -> /root/shelf01/furniture_shelving01_0001
      ... 58 more

61 placements mount to this one shelf.

**The manifest is verifiable.**

    $ jitsd pull 'where:finish=translucent' --context $JITSD_ALAB/entity/lab_workbench01/lab_workbench01.usda --out /tmp/pull.manifest.usda
    manifest: /tmp/pull.manifest.usda
    $ jitsd pull --verify /tmp/pull.manifest.usda
    verify: ok

### A bug this run found

Attribute- and name-based seeds (`where:`, bare lexical names, `id:`)
resolve by scanning `stage.Traverse()`. Against the fixtures every other
test uses — no payload arcs, no instancing — that traversal sees every
prim, so the bug was invisible until this run: against ALab it silently
matched nothing at all. `pull.py` opens the context with
`Usd.Stage.LoadNone` specifically so a pull never has to load anything
first, but every ALab placement references its entity layer with
`instanceable = true`, and that entity layer's heavy geometry sits behind
a payload — so every placement has `IsLoaded() == False`, and Usd's
default traversal predicate requires `UsdPrimIsLoaded`. A `LoadNone`
context stage made every attribute and name seed match nothing. Separately,
`chemistry_bottle01_0004`'s own `Represents` offer — the very prim
`where:finish` matches — lives inside the instance's prototype, invisible
to plain `Traverse()` regardless of predicate, because `instanceable = true`
elides prototype content from ordinary traversal.

The fix (`jitsd/ask.py:resolve_seeds`, `jitsd/pull.py:_reverse_index`,
`jitsd/pull.py`'s fitness pass): traverse with
`Usd.TraverseInstanceProxies(...)` and drop the loaded requirement from the
predicate. `pull()`'s existing instance-widening in `_admit` (spec section
4) does the rest — a matched `.../represents` instance proxy widens back to
its instance root before it becomes a member, which is why the 26-member
mask above lands on exactly the spike's 26 placement paths, not 26
`represents` children.

## What it does not show

- **Real re-modelling.** The geometry was not changed; the surface was. A
  full test would re-export the workbench with the shelf moved and re-extract.
- **Rotation, material, purposes on real data.** The extractor emits
  translates only and no non-spatial attributes, so those kinds are proven on
  fixtures (`tests/test_reeval.py`), not on ALab. Deriving material bindings
  and purposes from the look layers is the natural next extraction.
- **One hop.** Consumers of the workbench are re-evaluated; consumers of
  *those* consumers are not.
- **The proof is logged, not stamped.** The spec puts
  `jitsd__compatibilityProof` on the revision; revisions are immutable, so
  the proof is recorded with the promotion event instead.
