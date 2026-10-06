# ALab benchmarks: is working surgically more convenient?

**Date:** 2026-10-05. **Question the project lives or dies by:** does weft make a
real USD stage *more* convenient to work with, not less? These are hard numbers
on the Animal Logic **ALab** production scene, measured end to end.

## Setup & method

- **Machine:** MacBook Air (Apple Silicon). **USD:** conda-forge `usd-core`
  26.8 (headless). Single run per scenario (expect ±10–20% run-to-run).
- **Scene:** ALab **Asset Structure (v2.3.0) + Techvar geometry (v2.2.0)** only.
  The **71 GB texture pack and 18 GB procedurals were deliberately excluded** —
  rendering-only, and they don't fit. So every memory number here is
  *geometry-only* and therefore **understates** a real production full-load.
- **"Full load"** = `Stage.Open` (default, loads payloads) + `Load()` + read
  every gprim's `points` (materialise the geometry — composition alone is lazy).
- **"Surgical"** = weft `pull` (compute the closure) → `OpenMasked` →
  `Load` → read the slice's points. This credits weft's *real* mechanism, not a
  hand-made mask.
- **Peak RAM** = `getrusage` max RSS, each scenario in its **own subprocess** so
  the numbers don't bleed together.
- Harness: `extras/bench/bench_alab.py` (`report` and `sweep`). Reproducible.

## How big ALab actually is

| | |
|---|---|
| prims at the unloaded (LoadNone) level | **4,541** |
| of those, **behind payloads** (lazy) | **4,338 — 95.5%** |
| prims once **fully composed** | **47,401** (≈10× from instancing/payloads) |
| gprims / points fully loaded | 7,523 / **14.54 M** |

Almost the entire scene is lazy-loadable — which is exactly the surface weft
pulls against.

## Result 1 — pull one asset vs load everything

Surgical target auto-picked: `decor_jar01` (a jar on a shelf).

| | time | peak RAM | prims | points |
|---|---|---|---|---|
| **Full** (load + read all) | 0.38 s | 262 MB | 47,401 | 14,541,890 |
| **Surgical** (one jar) | 0.12 s | 120 MB | 425 | 36,758 |
| **ratio** | **3.1× faster** | **2.2× lighter** | **0.9%** | **0.25%** |

To work with one asset you materialise **0.9% of the prims and 0.25% of the
geometry.**

## Result 2 — query the whole scene as data, with zero load

`weft data` (cheap tier) projected **all 4,541 prims to a numeric table in
0.15 s, 125 MB, ~30,000 prims/sec — without loading any of the 14.5 M points.**
Interrogating the scene (bbox, centroid, type, payload-ness) costs nothing near
the geometry.

## Result 3 — the slice sweep: where does the win bend?

Pulling progressively larger slices (asset → shelf → bench → workbench → set)
against the full baseline (0.36 s, 261 MB, 47,401 prims, 14.5 M pts):

| slice | prims | % scene | points | % pts | time | RAM | × faster | × lighter |
|---|---|---|---|---|---|---|---|---|
| one jar (GEO) | 425 | 0.9% | 36,758 | 0.3% | 0.129 s | 121 MB | 2.8 | 2.2 |
| jar | 447 | 0.9% | 38,407 | 0.3% | 0.137 s | 121 MB | 2.7 | 2.2 |
| shelf | 6,499 | 13.7% | 1.11 M | 7.6% | 0.148 s | 134 MB | 2.5 | 2.0 |
| bench | 12,492 | 26.4% | 1.80 M | 12.4% | 0.177 s | 144 MB | 2.1 | 1.8 |
| workbench | 20,471 | 43.2% | 3.02 M | 20.8% | 0.217 s | 172 MB | 1.7 | 1.5 |
| whole set | 46,773 | 98.7% | 14.16 M | 97.4% | 0.447 s | 261 MB | **0.8** | 1.0 |

**The curve, read honestly:**
- **Below ~15% of the scene:** ~2.5–2.8× faster *and* ~2× lighter. A clear win,
  and the smaller the slice the bigger it gets.
- **~25–45%:** diminishing — 1.7–2.1× faster, 1.5–1.8× lighter. Still positive.
- **~99% (the whole set):** **0.8× — slower than just loading everything.**
  Masking the whole scene plus computing the pull is pure overhead with nothing
  saved.

So the crossover sits somewhere around wanting ~half-to-most of the scene. That
is the *expected, honest* boundary: **surgical pays when you want a slice; if you
want the whole thing, don't be surgical.** The thesis holds precisely where it
should. (Note points% < prims% at every level — a slice's geometry is lighter
than its prim share, and RAM tracks points, so the memory win is steadier than
the prim fraction suggests.)

## Result 4 — `weft data`: the stage as data, on production meshes

The numeric data plane (`weft data`) run on ALab, not the synthetic bench — so
`point_count`/`poly_count`/`byte_cost` carry real geometry, not the `-` an
implicit-surface bench shows.

- **Whole scene, cheap tier, zero geometry loaded:** 4,541 prims projected to a
  table in a fraction of a second. 4,319 carry an authored `extentsHint` (so
  `bbox_volume`/`centroid` populate); the meshes sit behind payloads (only 2
  inline `Mesh` at the unloaded level), so the expensive columns are honestly
  `None`, not loaded.
- **Cheap selection, then load a slice:** `--select 'where:bbox_volume>1e6'`
  filtered 4,541 → **63 prims with no load**, then `--load` materialised just
  those and the expensive columns aggregated over each placement's subtree:

  | asset (tail) | points | polys | ~bytes |
  |---|---|---|---|
  | decor_choko_experiment01/GEO | 370,761 | 368,219 | 5.9 MB |
  | lab_structure01/structure_roof/GEO | 192,469 | 185,166 | 3.0 MB |
  | decor_medical_screen01/GEO | 115,256 | 113,674 | 1.8 MB |
  | lab_structure01/structure_base01/GEO | 108,955 | 108,008 | 1.7 MB |
  | … | | | |
  | **total (45 meshed of 63 selected)** | **1,701,650** | **1,676,849** | **~27 MB** |

What this validates on real data: the cheap→expensive tier split (filter 4,541 →
63 with no load, load only then); subtree aggregation over production structure
(ALab's `GEO` high-res and `GEO_PROXY` LOD both surface as rows); and the
honesty rule — 18 of the 63 selected (lights, pure containers) are `None`, never
a fabricated `0`.

## Verdict against "more convenient, not less"

- **Footprint convenience: proven.** One asset = 0.9% of prims, 0.25% of
  geometry; the whole scene is queryable as data in 150 ms with no geometry load.
- **Speed convenience: real but scene-size-dependent.** At this package's scale
  everything is sub-second, so the absolute time win is modest (3× on a 0.38 s
  baseline). The *ratio and curve shape* are the transferable result.
- **It scales the right way.** The excluded textures/procedurals (89 GB) and any
  larger assembled world don't change the curve's shape — they blow up the
  *full-load* end of it. Surgical touches ~0.25% of the geometry, so it would
  touch ~0.25% of the textures too: extrapolated, **~180 MB vs 71 GB.** The win
  grows with everything we left out.

## Threats to validity (so we don't fool ourselves)

- Single machine, single run, no averaging — treat ratios as ±10–20%.
- Geometry-only; no textures/shaders/procedurals/render. Real full-loads are
  heavier, so these numbers flatter the *baseline*, not weft.
- `pull` overhead was a large fraction of a tiny slice (≈0.11 s of the 0.12 s
  jar pull). **Since addressed:** lazy seed resolution dropped a cold pull to
  ~0.098 s (it no longer walks the whole stage for a `path:` seed), and the
  cross-call cache (`pull --cache`) makes a repeated pull of an unchanged
  context ~0.003 s — **~77× faster**, floored no longer by the stage open.
  ~94% of a *cold* pull remains USD's `LoadNone` open, which only the cache
  amortises.
- The sweep uses ancestor paths (nested slices); batch-pulling N scattered
  assets is a separate shape not measured here.

## Reproduce

```sh
ENTRY=~/weft-demo/alab/ALab-2.3.0/ALab/entry.usda
PY="PYTHONPATH=<weft repo> ~/weft-demo/env/bin/python"

# the convenience delta + the slice sweep
$PY extras/bench/bench_alab.py report
$PY extras/bench/bench_alab.py sweep

# Result 4 — the stage as data
$PY -m weft data "$ENTRY"                                   # whole scene, cheap, no load
$PY -m weft data "$ENTRY" --select 'where:bbox_volume>1e6' \
    --load --columns point_count,poly_count,byte_cost      # a slice, real mesh metrics
```
(ALab under `~/weft-demo/alab/ALab-2.3.0/ALab/entry.usda`.)
