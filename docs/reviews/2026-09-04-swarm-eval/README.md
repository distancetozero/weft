# weft — swarm evaluation, 2026-09-04

Eight independent review agents, one per dimension, each working read-only
against `main` at `e441013` with `usd-core 26.8` installed and the suite green
(297 passed / 7 skipped; ALab absent on the host). Each agent probed its claims
empirically in a scratch directory rather than reading the docs and trusting
them. The per-dimension reports are alongside this file; this page is the
synthesis and the consolidated next steps.

| # | Dimension | Report |
|---|---|---|
| 1 | Surgical USD usage | [`01-surgical.md`](01-surgical.md) |
| 2 | Taxonomy | [`02-taxonomy.md`](02-taxonomy.md) |
| 3 | Relationship mapping | [`03-relationships.md`](03-relationships.md) |
| 4 | Just-in-time engine | [`04-jit-engine.md`](04-jit-engine.md) |
| 5 | Design docs and memory | [`05-docs-memory.md`](05-docs-memory.md) |
| 6 | Code quality and tests | [`06-code-tests.md`](06-code-tests.md) |
| 7 | usdview plugin and explorer | [`07-usdview.md`](07-usdview.md) |
| 8 | History and strategy | [`08-history-strategy.md`](08-history-strategy.md) |

## Verdict in one paragraph

Five days, 106 commits, one author, no users. The repo holds two products that
share a CLI: a **toolkit** (`weft pull`/`who`, `deps`, `absent`, the usdview
panel) that runs on any USD file today, and an **engine** (store, ledger,
contracts, generators, `compile`, `select`) that needs a `.weft/` repo and team
buy-in. Effort and positioning have moved to the toolkit since 2026-09-01; the
engine is roughly one third of its design and has no hook below USD composition
at all. The toolkit's founding guarantee — *what you didn't pull is declared,
never silently absent* — is the project's best idea and is currently broken in
six independent places, two of them on the most common production shape. The
library code is careful; the edges (CLI, packaging, docs) are rough; the docs
are rich in decision history but have no current-state document and contradict
themselves on the one question they call resolved.

## Scorecard against the four stated goals

| Goal | Status | Strongest evidence | Biggest hole |
|---|---|---|---|
| **Surgical USD usage** | Partially met, at one granularity | ALab S2: 716 KB / 59 layers consulted vs 101 MB / 1,625 for the stock walk; instance widening is correct and declared | `pull` reads only the member prim's own relationships (`weft/pull.py:68`) while the mask populates its whole subtree — a shot-layer material binding on a referenced mesh is neither followed nor declared. `--verify` never recomputes (`weft/manifest.py:127`) |
| **Taxonomy** | Not coherent | The follow grammar and seed planes are well designed on paper | Five stringly-typed vocabularies (deps, slice, pull, threadgraph, absent) with no shared registry; `usd:arc` means composition arc in `slice.py:374` and namespace hierarchy in `threadgraph.py:176`; `contract:Mount@2` is parsed then ignored (`pull.py:106`) |
| **Relationship mapping** | Broadest coverage, unsound resolution | `deps/walk.py` records bindings, connections, class arcs, collections, clips; the most stable code in the repo (994 lines, 13 deleted) | `_defined_locally` (`deps/graph.py:307`) treats any prefix-defined target as local, so under the standard "every layer defines `/root`" convention **zero** geo→look binding edges exist; `orphans` is blind to dangling targets under a defined ancestor |
| **Just-in-time USD** | About one third built; the rest is design | Store, revisions, channels, envelope gate and consumer re-evaluation all work and the IMPLEMENTATION.md demo reproduces byte-for-byte | Nothing plugs into Ar, Sdf file formats, or Hydra; `weft:obj/sha256:…` payload arcs resolve to nothing in stock USD; `write_baseline` overwrites (`ledger.py:333`); `gc` races `save`; `code_hash` misses `offers`/helpers so generator drift is invisible |

## Six cross-cutting findings

**1. The "never silently absent" guarantee fails in six places.** Each was
reproduced with a fixture:

- Subtree relationships not scanned (`pull.py:68`).
- Attribute connections, inherits/specializes and internal references are
  neither followed nor put at the boundary (`pull.py:63-86`).
- Physics joints inside an unloaded payload are unjudged and undeclared
  (`pull.py:174-179` comments the intent; the prims are not on the stage).
- Unknown relationship kinds default to *inert* with no "defaulted"
  declaration (`registry.py:32`), including PointInstancer `prototypes`.
- `deps` loses cross-layer bindings under a shared root (`graph.py:307`).
- `absent` misses `material:binding:<purpose>` and collection bindings
  (`detect.py:192`) and reports an explicit `rel material:binding = []`
  unbind as "targets-stripped, dead".

**2. `--verify` is tamper-evidence, not recompute-and-compare.** It hashes only
layers found in member prims' own prim stacks, so payload interiors, descendant
reference layers and edge-adding sublayers are unrecorded; blanking every hash
and re-digesting still verifies clean (`manifest.py:137`). `cli.py:405` runs
verify immediately after pull in-process, which is tautological.

**3. Two products, one CLI, drifting positioning.** 23 of the 24 commits since
the wire rename are toolkit work; the last engine commit is `660044c`. The
README leads with `pull`, `pyproject.toml` describes "pull threads", but
`weft --help` still says "JIT-SD rung 1: solo, offline, no contracts" while
offering `bind`, `check`, `promote`, and the numbered docs describe Datalog,
WASM kernels and a claim lattice that were never built.

**4. Memory is rich but uncurated.** Commit bodies are real decision records;
the docs are three eras deep with nothing reconciling them. `IMPLEMENTATION.md`
says both "keep byte chunking" (lines 296-347) and "stop treating an asset as
one opaque file" (353-389). README's "Measured" block has three numbers with
no reproducing script (126 ms, 23 ms, 4,296 layers/1.75 s; BENCHMARK.md
measures 4,461 layers at 134 ms warm) and "163 threads" where the run prints
326. Ten decisions live only in git, including the panel's four reversals.

**5. The usdview explorer's invariants do not hold.** The interaction model is
good and mostly implemented, but loaded-set bookkeeping lives in ~250 lines of
untested JavaScript; the ask bar loads groups untracked; the native fallback
panel loads the world on open (`threadpanel.py:266`); Solo's frontier is wrong
on `--unloaded` stages (`core.py:300`, the same predicate bug fixed elsewhere);
`stage.Unload` runs without the selection guard Solo already has. Plumbing
cost ~4,000 churned lines across four panel architectures in 36 hours; the
model cost ~900.

**6. Library code is good; edges are rough.** No digest non-determinism, no
Python 3.9 violations, atomic writes almost everywhere. But `cli.py` is 38%
covered with no error boundary (a dozen ordinary mistakes end in tracebacks),
`Repo.find` raises `SystemExit` from library code, tempdirs leak per `pull`,
and `tests/test_slice_references.py:57` uses `importorskip` in a decorator so
the one test written to prove the bare-install promise has never run in the
bare CI job.

## What has been done (condensed)

| Phase | Dates | Produced | Corrected by measurement |
|---|---|---|---|
| JIT-SD design + rung-1 engine | 08-30 → 08-31 | docs/01–09, store/ledger/contracts/generators/query, CI | chunk 1 MiB→64 KiB; 5 USD syntax bugs in shipping code; 3 of 4 archetypes duplicated UsdPhysics/primvars |
| USD-facing tools | 08-31 → 09-01 | `deps`, `absent` | 361 "orphans" were class hooks |
| Slices + ALab contract POC | 09-01 | slice.py, extract.py, poc.py, schema | closure pulled nothing on real USD; README/docs truth pass |
| Prim-level pull + rename | 09-01 | ask/follow/pull/manifest, `weft pull`/`who` | default PrimRange predicate silently empty on ALab |
| Landing page + benchmark | 09-01 → 09-02 | index.html, compare.py, BENCHMARK.md | published a 46× loss in S1 |
| usdview plugin + Threads panel | 09-02 → 09-03 | extras/usdview (2,706 lines), threadgraph.py | segfault root-caused to PySide re-entrancy after four architectures |

Lines today: weft 6.5k, tests 5.6k, docs 5.6k (+3.6k specs/plans), usdview
2.7k, examples 1.8k, deps 1.0k, absent 0.5k. No unmerged branches, no tags, no
PyPI release.

## Concrete next steps

Ordered by dependency and by how much trust each one buys back. Sizes: S ≤ a
day, M ≤ a week, L longer.

### First: restore the guarantee and tell the truth (all S, roughly one week)

1. **Scan member subtrees for edges.** In `pull()`, iterate
   `Usd.PrimRange(member, predicate)` for `_out_edges` instead of the member
   alone (`weft/pull.py:68`). Add the shot-layer-binds-referenced-mesh fixture
   as a test.
2. **Fix `deps` locality.** Treat a target as intra-layer only when the layer
   defines the exact prim, not a prefix (`deps/graph.py:307`); report dangling
   targets under a defined ancestor from `orphans`. Add an ALab-shaped `/root`
   fixture to `tests/test_deps.py`.
3. **Fix `absent`.** Cover all `material:binding*` names and both ends of
   collection bindings; treat composed-empty as stripped only when no stronger
   spec authors an explicit `[]`/`delete` (`absent/detect.py:192, 240-262`).
4. **Declare what pull cannot follow.** Emit boundary entries for attribute
   connections, inherits/specializes and internal references even when no
   follow term names them; emit `inert (defaulted)` for unclassified kinds
   (`weft/registry.py:32`) and add explicit entries for `prototypes` and
   `proxyPrim`.
5. **Close the three durability holes.** `write_baseline` through the O_EXCL
   path (`ledger.py:333`); `code_hash` over every method in the subclass
   `__dict__` (`generators/__init__.py:150`) with a test that rewriting
   `offers` trips `drift`; a repo-level `flock` taken by save/promote/cut/gc.
6. **CLI error boundary.** One `try/except` in `main()` for `KeyError`,
   `ValueError`, `OSError`, `UsdaError`, `RevisionExists`, `ChannelRaced`;
   add `NotARepository` and stop raising `SystemExit` in `Repo.find`
   (`ledger.py:369`); clean up the `mkdtemp` leaks in `cli.py:332` and
   `slice.py:175`.
7. **Un-hide the bare test.** Replace `importorskip` in the decorator at
   `tests/test_slice_references.py:57` with `find_spec`.
8. **Docs truth pass.** Delete the last two paragraphs of the IMPLEMENTATION.md
   Benchmark section; replace 126 ms / 23 ms / 4,296 / 1.75 s with
   BENCHMARK.md's script-produced figures or add them to `compare.py`; "163
   assets / 326 threads"; drop "hand-built" and "byte-identical" for the spike
   mask; fix the `06-adoption.md` and `jitsdContracts` links; replace the
   `cli.py:651` banner; make `test_alab_pull` write interfaces to a temp copy,
   not into the dataset.

### Next: one vocabulary, honest verify, one panel (M, two to three weeks)

9. **`weft/kinds.py`.** A single registry of thread kinds, the deps-edge and
   relationship-name mappings, the omission table, and the violation kinds,
   consumed by deps, slice, pull, threadgraph and the plugin. Give the
   viewer's hierarchy edge its own name so `usd:arc` has one meaning. Honour
   `contract:` and `@major` in `_admission`. Unify the two seed grammars
   (`provides:`/`offers:`, `box:`/`within:`).
10. **Make verify recompute.** Re-run `pull()` from the manifest's recorded
    asks, follow terms, depth and extractors and diff members plus boundary;
    record `GetUsedLayers()` of the masked LoadAll stage; treat empty hashes
    as findings; drop the in-process verify at `cli.py:405`.
11. **Spatial seeds via `UsdGeomBBoxCache(useExtentsHint=True)`** at a
    recorded time code (`ask.py:154`); never abort a seed on one prim.
12. **Close the extension loop.** Thread extractors through `who()` and the
    plugin; record extractor and omission registries by `name@rev` in the
    manifest; add a `weft__omissions` document form.
13. **usdview: delete the native panel** (`threadpanel.py` loads the world on
    open) and its compatibility slots. Move `focus/pinned/ruleLoads` into a
    pure Python `FocusModel` that diffs against `stage.GetLoadSet()` and only
    unloads what the panel loaded; route the ask bar through it; fix the
    `deactivation_set` predicate (`core.py:300`); snapshot and clear selection
    before `Unload`. Commit one screenshot pair or drop the references to the
    missing report.
14. **`ARCHITECTURE.md` and `DECISIONS.md`.** The current-state doc (two
    products, module map, standing rules such as the traversal predicate) and
    a dated append-only decision log seeded from the ten git-only decisions.
    Rewrite `docs/08-open-questions.md` (1, 3, 4, 8 are answered by code);
    banner docs/01–07 and 09 as the JIT-SD design record; add the "executed
    2026-09-01" footer to the plan.
15. **Split the CLI surface and test it.** `weft pull|who` plus `deps` and
    `absent` as the documented toolkit; engine verbs under `weft engine …` or
    labelled experimental; `tests/test_cli.py` driving every subcommand; a
    public API in `weft/__init__.py` (`pull`, `who`, `resolve_slice`,
    `check_compatibility`) without importing `cli` at package import.
16. **Quickstart on a stock scene and a release.** A small real scene in
    `examples/` (not the generator query document), a `QUICKSTART.md` that
    runs pull/who/deps/absent in under five minutes, `weft who` printing
    "0 incoming edges" instead of nothing, `weft-usd 0.1.0` on PyPI with a
    tag and a wheel-install smoke job in CI.

### Decisions only the owner can make

- **Positioning.** The evidence supports "pull any subset of an OpenUSD scene
  by what it is — a name, a material, a relationship — into a verifiable
  mask, without loading the world" as the lead, and "the dependency map
  OpenUSD doesn't ship" as the cheapest wedge. The engine thesis has the
  weakest evidence and OpenExec is moving under it.
- **The `weft:obj/` scheme.** Either materialise blobs into `.weft/cache/` at
  compile/checkout and emit relative paths (M), commit to a C++ `ArResolver`
  against a pinned `usd-core` ABI (L), or stop emitting arcs USD cannot
  resolve. Deferring leaves every payload-backed revision a lie to USD.
- **The engine's scope.** Freeze docs/03–06, the as-of spec and the generators
  until a user asks for versioning; label the ALab "19 consumers" demo as the
  interface-level simulation it is.
- **Validation beyond ALab.** One outside pipeline TD's tree and one non-film
  corpus (a CAD-to-USD export) before any new feature. The "non-film is the
  stronger case" claim in docs/01 has zero evidence today.
- **`absent` as `UsdValidation` validators.** OpenUSD 25.11 made that
  framework the default in `usdchecker`; a parallel checker will age fast.

### Stop doing

- Adding design documents before a user exists.
- Shipping two implementations of the same panel.
- Quoting numbers that no script in the repo reproduces.
- Spending days on viewer plumbing while the pull guarantee is broken.
