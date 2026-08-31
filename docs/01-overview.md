# JIT-SD — Overview

**Just-In-Time Scene Description.** A resolution layer that sits *below* USD
composition and turns a stage from a file you open into a query you evaluate.

## Thesis

USD's composition engine is already a pure functional evaluator. LIVRPS
(Local → Inherits → VariantSets → References → Payloads → Specializes) is a
deterministic function from a layer stack to a composed stage. Pixar already
built the evaluator.

What is rigid is not the evaluator — it is that **its inputs are static files
on disk**. Someone must publish `hero_car_v037.usd` before anyone can
reference it, and the reference is a path, so it points at a thing that
already exists.

> **JIT-SD keeps USD's evaluator and makes its inputs generated on demand and
> parameterised by who is asking.**

## What it is not

- Not a new scene description format. USD stays.
- Not a competitor to glTF or USDZ. Those are **output codecs** — the compiled
  binaries. JIT-SD is the compiler and the build system.
- Not a replacement for live collaborative editing (see `06-adoption.md` on
  Omniverse). Live sync is consumed, not replaced.
- Not a requirement that everything be procedural. A hand-sculpted hero asset
  is a generator with no parameters. **Constants are functions.**

## The one-line summary

> **JIT-SD moves the source of truth from the big files to the small ones.**

Today the precious artifact is a 4 GB `hero_car_v037.usd` that must never be
deleted. Here the precious artifact is a 3 KB recipe, and the 4 GB is a cache
anyone can rebuild.

## Lineage

Nothing here is invented from nothing. The parts are borrowed deliberately:

| Idea | Borrowed from |
|---|---|
| Content-addressed immutable derivations | Nix, Git |
| Hermetic build graph, cheap incremental | Bazel |
| Demand-driven relational resolution | Datalog, magic sets, differential dataflow |
| Per-request shaping by caller | GraphQL |
| Lockfiles and channel-based release | npm / Cargo / Nix flakes |
| Procedural DAG authoring | Houdini HDAs, Grasshopper, Revit families |
| Sparse hierarchy, topology/value split | OpenVDB |
| Configuration baselines, effectivity | PLM / systems engineering |

## The two phases, industry-neutral

Every USD workflow has two halves. Film names them "asset build" and "shot
execution"; those are not film-specific activities.

**Definition** — authoring a reusable, context-free, timeless description of a
*kind of thing*. A type, not an instance.

**Assembly** — binding definitions into a specific place, at a specific
moment, for a specific purpose, and materialising the result.

| | Film/TV | Games | Manufacturing | AEC | Robotics / Sim |
|---|---|---|---|---|---|
| **Definition** | asset | prefab / blueprint | part definition, catalog item | product family | robot / sensor model |
| **Assembly** | shot | level, streaming cell | configured unit / BOM instance | building model on a site | scenario / episode |
| **Placement** | layout | level design | mating | site placement | scene setup |
| **Articulation** | rigging | anim blueprint | joints, DOF | operable parts, MEP | joints & actuators |
| **Appearance** | look dev | material setup | finish spec | finish schedule | sensor response |
| **Analysis** | FX / sim | physics | CAE / FEA / CFD | clash, energy | physics sim |
| **Output** | frames | cooked build | illustrations, work instructions | drawing sets | synthetic data |
| **Gate** | dailies / approval | cert | engineering change sign-off | issued-for-construction | regression suite |
| **Version pinning** | version pinned to shot | content build | **effectivity** | issue set / revision | scenario version |

Read the last row. **Every one of these industries independently invented the
epoch**, and each implements it as a bespoke pipeline database bolted onto USD
from outside. That is the strongest evidence for this design, and the reason
the versioning model (`03-versioning.md`) is the core of it.

## Why the non-film case is the stronger one

Outside entertainment, USD is used as a **downstream assembly and
visualisation target, not a source of truth.** Truth stays in CAD, PLM, or BIM;
something converts to USD; the USD gets assembled, lit, simulated, looked at.

At that conversion boundary you lose, every time: parametric intent (a feature
tree becomes triangles), version identity (the part revision and its
effectivity live in PLM), and bidirectionality (the round trip is broken).

> **CAD, PLM and BIM are already just-in-time systems. The bake to USD is what
> stops them being one.**

A CAD model *is* a program that generates geometry from parameters. A Revit
family *is* a generator that builds itself against its host. PLM effectivity
*is* an epoch. These industries have had JIT-SD's core ideas for thirty years
in their authoring tools, and discard all of it at export.

So outside film, JIT-SD is not asking anyone to adopt a new paradigm. It is
asking them to stop discarding the one they already have. Film has to be
persuaded its bakes are a problem; manufacturing already knows.
