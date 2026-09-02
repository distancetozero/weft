# Stock USD vs weft, on ALab — three scenarios, steelmanned

This is a comparison, not a demo. It runs three realistic asks against
[Animal Logic's ALab](https://dpel.aswf.io/alab/) — the first open-sourced
complete USD production scene — once with the best stock USD tooling
available, once with `weft`, and reports both honestly, including the
scenario where the stock practice wins.

    python examples/alab/compare.py /path/to/ALab-2.3.0/ALab

Every number below is that script's own output, pasted verbatim (only the
local checkout path is shortened to `/path/to/…`). Re-run it to reproduce;
nothing here is hand-adjusted or rounded up.

## Methodology (printed by the script; reproduced here verbatim)

- Every baseline uses the best stock tooling available; no strawmen.
- Scenario 1's expected baseline win is published, not hidden.
- All numbers come from this committed script; re-run to reproduce.
- ALab's tidy one-entity-per-file layout is favorable terrain for the
  BASELINE; messier corpora shift every scenario toward weft.
- Timings: best-of-3 for each measurement, on a warm filesystem cache.

One more thing worth stating plainly, since it isn't printed by the script:
**this benchmark was written to let the baseline win where it legitimately
does.** Scenario 1 is included specifically because weft loses it on speed —
that result is reported as the headline of its section, not buried. A
benchmark that only shows wins is not a benchmark; it's an advertisement.

## The three scenarios

1. **Known asset, tidy library** — "give me `chemistry_bottle01`, and I know
   where it lives." The practitioner move (open the file you know) against
   `weft.pull` with a lexical seed and mask consumption.
2. **Find-then-extract by property** — "give me every translucent thing."
   A live `UsdShade` shading-network walk against `weft.pull
   'where:finish=translucent'` on a `LoadNone` context.
3. **Extraction completeness** — "take the asset and everything it needs."
   `UsdUtils.ComputeAllDependencies` (the machinery behind `usdz` packaging)
   against the `deps` dependency graph, by edge kind, plus a capability the
   baseline structurally lacks: a reverse query.

## The real run

Environment: ALab 2.3.0, USD 0.26.8, this repo at the commit this file ships
in. `WEFT_ALAB` interfaces were already regenerated root-anchored (with
`weft:offer:carrier`, `weft:bind:finish`, etc.) before this run — the
script checks and would regenerate them idempotently into the ALab tree if
they weren't there, which they were; nothing in the ALab tree changed as a
result of running it (verified with `find … -newer` before and after). Note
that this transcript therefore does not exercise the first-time
regeneration path itself; that path is exercised by
`tests/test_alab_pull.py`'s fixture.

```
==============================================================================
ALab comparison: stock USD practice vs weft
==============================================================================
ALab checkout: /path/to/ALab-2.3.0/ALab
USD version: 0.26.8

METHODOLOGY
- Every baseline uses the best stock tooling available; no strawmen.
- Scenario 1's expected baseline win is published, not hidden.
- All numbers come from this committed script; re-run to reproduce.
- ALab's tidy one-entity-per-file layout is favorable terrain for the
  BASELINE; messier corpora shift every scenario toward weft.
- Timings: best-of-3 for each measurement, on a warm filesystem cache.

interface regeneration: skipped -- interfaces already current, no write to the ALab tree

==============================================================================
SCENARIO 1 -- known asset, tidy library ("give me chemistry_bottle01, I know where it lives")
==============================================================================

-- baseline: Usd.Stage.Open(entity file directly) + Traverse() --
  path            entity/chemistry_bottle01/chemistry_bottle01.usda
  prims           27
  bytes (1 layer) 726
  time (best/3)   1.0 ms   all: 27.9 ms, 1.0 ms, 1.1 ms
  prerequisite    must already know the exact file path: entity/chemistry_bottle01/chemistry_bottle01.usda
  verifiability   none -- a stage, nothing recorded about how it was reached

-- weft: pull('chemistry_bottle01_0004') against the workbench context + mask consumption --
  seed members    ['/root/shelf01/chemistry_bottle01_0004']
  masked prims    29 total (2 spine ancestors carried for context, 27 belonging to the entity itself)
  layer bytes     668825 (every layer contributing to the seed's composed prim stack)
  time (best/3)   46.0 ms   all: 94.7 ms, 47.4 ms, 46.0 ms
  prerequisite    the workbench context file + one lexical name ('chemistry_bottle01_0004'); no need to know entity/chemistry_bottle01/chemistry_bottle01.usda exists
  verifiability   SHA256-hashed manifest (5456 bytes), re-verifiable with weft.manifest.verify()

-- cross-check --
  entity-only prim count from the mask (27) MATCHES the baseline's direct-open count (27)

-- HONEST RESULT --
  baseline is faster here (1.0 ms vs 46.0 ms) -- EXPECTED and PUBLISHED: zero-tooling path-open wins when the path is already known and the library is tidy.
  weft's difference in this scenario is the receipt and not needing the path, not speed.

==============================================================================
SCENARIO 2 -- find-then-extract by property ("give me every translucent thing")
==============================================================================

-- baseline: LoadAll the workbench, UsdShade.MaterialBindingAPI per placement, walk to the UsdPreviewSurface shader --
  placements scanned     437
  stage populated prims  12184
  layers stage loaded    1625 files, 101559512 bytes (Sdf layer sizes via stage.GetUsedLayers())
  custom code required   60 lines (this function)
  translucent found      26
  time (best/3)          209.7 ms   all: 252.6 ms, 210.6 ms, 209.7 ms

-- weft: pull("where:finish=translucent") on the LoadNone context --
  members                26
  layers consulted       59 files, 716248 bytes (manifest accounting)
  time (best/3)          82.1 ms   all: 82.1 ms, 84.6 ms, 83.4 ms

-- AMORTIZED SETUP -- one-time cost of deriving weft:bind:finish onto the interfaces weft's answer reads (run into a throwaway temp dir, does not touch the ALab tree) --
  look layers read       159 real look layers (fragment/look/surfacing/*)
  finish derived for     8/159 (8 translucent) -- rule: authored opacity < 0.999 on any Shader spec in the look layer; 8 of 159 looks author opacity at all
  time (best/3)          704.2 ms   all: 739.2 ms, 708.2 ms, 704.2 ms
  this cost is paid ONCE per republish of the look layers, not once per query -- every subsequent where:finish=translucent pull reuses it

-- AGREEMENT CHECK --
  MATCH: baseline's live shading-network walk and weft's interface-derived answer agree exactly -- 26/26 placements, identical set.
  spike's recorded mask (26) also matches: True

-- HONEST WRINKLE --
  weft's answer reads weft:bind:finish from interfaces derived ONCE from the look layers (spec-level walk across every representation: usd_full, usd_preview, usd_preview_proxy); the baseline inspects the COMPOSED shading network live, at one binding purpose ('preview') per placement. They agree on ALab because ALab's 'preview' purpose is where the authored scalar opacity actually lives -- the 'full' purpose material connects opacity to a texture node with no authored scalar to read at all, so a baseline written against 'full' purpose alone would silently find ZERO translucent placements. Getting the baseline right required discovering this; a less careful steelman could have under-measured itself into a false weft win.
  the derivation rule (authored opacity only, 8 of 159 looks) is recorded on the interfaces themselves, readable by anyone -- not just by this script.

==============================================================================
SCENARIO 3 -- extraction completeness ("take the asset and everything it needs")
==============================================================================

-- baseline: UsdUtils.ComputeAllDependencies -- arc-only closure, the machinery behind usdz packaging --
  chemistry_bottle01 (one entity)  layers=14   assets=6    unresolved=11   time(best/3)=1.8 ms
  lab_workbench01 assembly         layers=2134 assets=984  unresolved=1493  time(best/3)=274.5 ms

-- weft/deps: dependency graph over the ALab tree's own closures --
  layers discovered      4461 (deps.discover(ALab))
  full graph build, COLD 5587.5 ms  (single-shot -- the on-disk deps cache is deleted once at the start of this scenario, so this is the real first-ever-build cost, not a leftover from a previous run)
  full graph build, WARM 133.9 ms  (best/3, cache now populated)   all: 133.9 ms, 154.8 ms, 147.7 ms
  {'layers': 4461, 'specs': 40859, 'edges': 24761, 'resolved_edges': 6614, 'unresolved': 3525}
  entity closure         14 layers, 6 other assets (vs baseline's 14 layers, 6 assets)
  assembly closure       2134 layers, 984 other assets (vs baseline's 2134 layers, 984 assets)
  entity (chemistry_bottle01) edges by kind:
      arc           24
      assetAttr     16
      rel            4  (of which 3 are material:binding)
      conn          26
      inherit        2
      collection     0
      non-arc total (invisible to ComputeAllDependencies): 48
  assembly (lab_workbench01) edges by kind:
      arc         4199
      assetAttr   2322
      rel          633  (of which 477 are material:binding)
      conn        3630
      inherit      328
      collection     0
      non-arc total (invisible to ComputeAllDependencies): 6913

-- REVERSE QUERY -- structurally absent from the baseline --
  "what depends on chemistry_bottle01's own entity layer"
  dependents found       14
  time (best/3)          0.0 ms   all: 0.0 ms, 0.0 ms, 0.0 ms
  UsdUtils.ComputeAllDependencies has no reverse direction at all -- answering this with stock tooling means scanning every layer in the tree for a reference to this one, an O(corpus) operation with no API for it.

-- HONEST FRAMING --
  This is completeness-with-declaration vs silent omission, not a speed contest. ComputeAllDependencies is fast and correct for what it claims to compute (composition arcs). It does not claim to see material bindings, shader connections, inherits, or collections -- and does not surface that it isn't looking. The 48 non-arc edges in chemistry_bottle01's own closure (of which 3 are material bindings) are dependencies a usdz-style arc-only extraction would silently drop.

==============================================================================
METHODOLOGY (verbatim)
==============================================================================
- Every baseline uses the best stock tooling available; no strawmen.
- Scenario 1's expected baseline win is published, not hidden.
- All numbers come from this committed script; re-run to reproduce.
- ALab's tidy one-entity-per-file layout is favorable terrain for the
  BASELINE; messier corpora shift every scenario toward weft.
- Timings: best-of-3 for each measurement, on a warm filesystem cache.
```

Full test suite (292 passed, 1 skipped) passes unchanged against the same checkout;
running `compare.py` does not mutate the ALab tree (checked with
`find $ALAB -newer <marker> -type f` before and after — zero results both
times, across two separate runs).

## Summary table

| scenario / method | wall time (best of 3) | bytes / prims touched | prerequisite knowledge | verifiability |
|---|---|---|---|---|
| S1 baseline — open entity file | **1.0 ms** | 726 B, 27 prims (1 layer) | exact file path to the entity | none — a stage, no receipt |
| S1 weft — pull + mask | 46.0 ms | 668,825 B, 29 prims (27 content + 2 spine) | context file + one lexical name; **not** the entity's path | SHA-256 manifest, 5,456 B, `verify()`-able |
| S2 baseline — live shading walk | 209.7 ms | 101,559,512 B, 1,625 layers, 12,184 prims | `UsdShade` API **and** which binding purpose (`preview`) carries the authored scalar — a real discovery, disclosed above | none |
| S2 weft — `where:finish=translucent` | 82.1 ms (+ 704.2 ms amortized, one-time) | 716,248 B, 59 layers | the query grammar; the one-time interface derivation | per-query manifest; derivation rule recorded on the interfaces themselves |
| S3 baseline — `ComputeAllDependencies` (entity) | 1.8 ms | 14 layers + 6 assets | none beyond the API | arc-only; no reverse query, ever |
| S3 baseline — `ComputeAllDependencies` (assembly) | 274.5 ms | 2,134 layers + 984 assets | none beyond the API | arc-only; no reverse query, ever |
| S3 weft/deps — full graph build | 133.9 ms warm (best/3) · 5,587.5 ms cold — both script-measured; the cache is deleted at scenario start | 4,461 layers walked once | none beyond the CLI/API | every edge kept, with kind |
| S3 weft/deps — entity closure | included above | same 14 layers + 6 assets as baseline, **+ 48 non-arc edges** (3 material bindings) | — | non-arc edges declared, not dropped |
| S3 weft/deps — assembly closure | included above | same 2,134 layers + 984 assets as baseline, **+ 6,913 non-arc edges** (477 material bindings) | — | non-arc edges declared, not dropped |
| S3 weft/deps — reverse query (`dependents`) | **0.0 ms** for 14 dependents | — | — | a capability with no baseline equivalent at all |

## Reading the results honestly

**Scenario 1 is a loss for weft, and that's the point of including it.**
When the practitioner already knows the exact path into a tidy,
one-entity-per-file corpus, opening the file directly is unbeatable —
there is no tool overhead cheaper than zero tool overhead. weft is roughly
46× slower here (1.0 ms vs 46.0 ms) because it composes a masked view
through a full context stage instead of opening a small file directly, and
that cost buys two things the baseline has none of: a receipt (a
SHA-256-hashed manifest that can be re-verified against the layers it
touched) and freedom from needing to know `chemistry_bottle01`'s file path
in the first place. On ALab's tidy layout that trade doesn't pay for itself
on speed. On a messier corpus — where the practitioner does *not* already
know the path, or the path changes under reorganization — the baseline's
"just open the file" move stops being available and the comparison
reverses; that corpus isn't this one, so the reversal isn't claimed here,
only named.

**Scenario 2 is where the steelman had to be earned, not assumed.** The
brief called for the best stock shading-network walk, and the first honest
attempt at one found *zero* translucent placements — not because the rule
was wrong, but because ALab's `full`-purpose material binds opacity to a
texture node with no authored scalar to read at all; the scalar the
extractor's `finish()` rule keys on only exists on the `preview`-purpose
material. Getting the baseline right required discovering that ALab-specific
fact empirically (documented in `compare.py`'s `s2_baseline_translucent`).
With that fix, baseline and weft **agree exactly** — 26/26 placements,
identical set, matching the acceptance test's own recorded spike mask too.
weft is faster per query (82.1 ms vs 209.7 ms) but that comparison is
incomplete without the disclosed one-time cost of deriving `weft:bind:finish`
onto the interfaces in the first place (704.2 ms, run once per look-layer
republish, amortized across every future query) — printed as its own line,
not folded into the per-query number to make weft look better than it is.

**Scenario 3 is not a speed contest, and isn't framed as one.** Both
methods agree exactly on which *files* are dependencies — 14 layers/6 assets
for the entity, 2,134 layers/984 assets for the assembly — which is a
genuine cross-check that `deps`'s independently-built graph and USD's own
`ComputeAllDependencies` compute the same arc-only closure. Where they
diverge is completeness: `ComputeAllDependencies` is the actual mechanism
behind `usdz` packaging, and it only ever sees composition arcs (sublayer,
reference, payload). It has no concept of a `material:binding` relationship,
a shader input connection, an `inherit`, or a collection include — and
nothing in its return value says so. Republishing `chemistry_bottle01`
using only its arc-only dependency list would silently strand the **48**
non-arc edges in its own closure (3 of them material bindings); the
assembly's closure carries **6,913** such edges (477 material bindings).
The graph that sees all of this costs **5,587.5 ms to build cold** (measured
by the script itself after deleting its own cache) and **133.9 ms warm** —
and `deps` also answers a question `ComputeAllDependencies` cannot ask at
all — "what depends on this" — in under a millisecond once built, because
USD's dependency APIs are one-directional by construction.
