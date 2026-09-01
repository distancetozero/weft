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
  own `xformOp:translate`, role = the placed asset's name, envelope 1 cm;
- each placed asset **requires** `Mount@1` with role = itself, cardinality
  `many`, so it binds every place the bench offers it.

Props are base-origin — verified from their authored `extentsHint`: bottles,
screws, washers, the bench seat all have `min.y ≈ 0`, centred in x/z — so an
offer frame really is where a prop's base sits.

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

== cut baseline
   baseline 000001  merkle f51109e315d0b3f1

== republish workbench: shelf01 raised 0.5 cm (inside the 1 cm envelope)
   promoted v002 -> @approved  (0 violations)

== republish workbench: shelf01 raised 3 cm (past the envelope)
   REFUSED: lab_workbench01 v003 -> @approved  (65 violations)
     envelope  /lab_workbench01/shelf01/chemistry_bottle01_0004: moved 2.5, envelope allows 1 -- provider broke its own promise
     envelope  /lab_workbench01/shelf01/chemistry_bottle01_0005: moved 2.5, envelope allows 1 -- provider broke its own promise
     ... and 59 more, every one on shelf01
   @approved still at v002

== drift since baseline 000001
   baseline f51109e315d0b3f1   now d44304852ec16712   DRIFTED

== verify
   blobs ok 332  corrupt 0  missing 0   stale generators 0
```

Whole run: **0.9 s**.

## What it shows

- **Every one of 437 real placements bound by contract and role alone.** No
  consumer names the workbench; no consumer names a path inside it.
- **The compatible change promoted; the breaking one was refused**, and the
  refusal named all 65 offers on the moved shelf — and *only* those. The other
  372 mounts are untouched and the gate says nothing about them.
- **The gate measures against what is in force.** The refusal reports *moved
  2.5*, not 3: the shelf had already been raised 0.5 cm by the promoted
  republish, and the envelope is checked against the surface consumers are
  currently bound to.
- **`@approved` never moved.** The refused revision exists (`v003`), is in the
  ledger, and can be inspected; the channel pointer stayed at `v002`.
- **Drift is visible and attributable.** The baseline's merkle root differs
  from the current world because a compatible republish landed after the cut —
  which is exactly what a lockfile should say.

## What it does not show

- **Real re-modelling.** The geometry was not changed; the surface was. A
  full test would re-export the workbench with the shelf moved and re-extract.
- **Rotation.** The extractor emits translates only. `envelope_angular` is
  enforced by the gate but every extracted offer has the default of 0 and an
  orientation of 0, so a rotated shelf would not be caught by this POC.
- **Downstream re-evaluation.** The gate checks the provider against its own
  declared envelope. Re-evaluating *consumers* at promotion — the exemplar
  half of the design — is still unbuilt.
