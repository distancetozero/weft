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

   consumer tolerances derived for 159/164 props: proc_dev_circuit_fuse01 0.06 cm .. furniture_workbench01 44.96 cm

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

Materials belong on the same offer (`jitsd:bind:materials`, a set) but the
Asset Structure package ships **placeholder** look layers — "to be replaced
with the techvar_assets package" — so material extraction needs the Techvar
download and is wired but not exercised here.

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
