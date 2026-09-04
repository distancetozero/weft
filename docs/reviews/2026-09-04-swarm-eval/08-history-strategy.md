# weft — history, trajectory, and product strategy

## (a) History timeline

The whole repo is **five calendar days** (2026-08-30 → 09-03), 106 commits, one human author (`Ashraf Ghoniem` / `distancetozero`), every commit co-authored by a Claude session. PRs #1–#14 are all merged; commits per day: 2 / 17 / **62** / 16 / 9.

| Phase | Dates | Outputs | Pivot / correction by measurement |
|---|---|---|---|
| 1. JIT-SD design + rung-1 engine | 08-30 → 08-31 (PR #1) | `docs/01–09`, `weft/{store,ledger,contracts,generators,query,usda}.py`, CI (`2d6c7b1`) | Chunk default 1 MiB→64 KiB; "crate isn't byte-stable" retracted; 3 of 4 contract archetypes found to duplicate UsdPhysics/primvars (`093294f`, `187cec6`, `29a4ab2`); 5 USD syntax bugs in shipping code (`b086878`); `pip install -e .` was broken until CI simulated (`2d6c7b1`) |
| 2. USD-facing tools + correctness | 08-31 → 09-01 (PR #2) | `deps/`, `absent/`; silent-corruption/gc/ledger fixes (`6166f34`) | ALab enters: 361 "orphans" were the standard class-hook idiom (`381aa66`); "needs 5825 layers" in a 4,296-layer scene (`67f20c3`) |
| 3. Slices + ALab contract POC + truth pass | 09-01 (PRs #3–#7) | `docs/10-slices.md`, `weft/slice.py`, `weft/extract.py`, `examples/alab/poc.py`, `specs/weftContracts` | Slice closure pulled **nothing** on real USD because no ALab layer declares a contract → walk reference edges (`ea17dd2`); README said "no implementation yet" above 169 tests, docs/07 carried a fabricated CLI session, schema had never passed usdGenSchema (`bae84d0`) |
| 4. Prim-level threads → rename | 09-01 (PR #8) | spec/plan (`f6f45e5`, `6e672b4`, 2,849-line plan), `weft/{ask,follow,pull,manifest,extractors}.py`, `weft pull`/`who`, rename to weft (`4ecb232`) | **Pivot: asset-level slices → prim-level pull.** Default `Usd.PrimRange` predicate silently empty on ALab (`e50d89b`, `a953d37`); installed console script never worked — `deps`/`absent` weren't packaged (`89e8d41`) |
| 5. Landing page + benchmark | 09-01 → 09-02 (PRs #9–#11) | `docs/index.html`, `examples/alab/{compare.py,BENCHMARK.md}` | Steelmanned benchmark publishes a **46× loss** in scenario 1 (`d0796c6`); demo GIF added then dropped after first outside feedback (`2909df8`, `3ffdeb4`) |
| 6. usdview plugin + Threads panel | 09-02 → 09-03 (PRs #12–#14) | `extras/usdview/` (2,706 lines), `weft/threadgraph.py`, wire rename `jitsd:*→weft:*` (`2a8155c`) | 7 rounds on a segfault: WebEngine (`1d7d71e`) → native Qt pivot (`56c60d9`) → browser bridge (`9e93367`) → rejected by owner → WebEngine restored, root-caused to a PySide event-filter re-entrancy (`d6951d4`); bbox-standin viewport doesn't resync on load → engine rebuild (`ab2bccc`) |

**Where time went:** Phase 6 is 18 of 106 commits but **+3,935 / −1,333 lines** in ~36 hours, with three panel architectures tried and two shipped side-by-side (`webenginepanel.py`, `threadpanel.py`) plus a launcher shim (`weft_usdview.py`) needed only for macOS painting.

## (b) Lines per area (git numstat, rename-followed)

| Area | Added | Deleted | Now (lines) | Note |
|---|---|---|---|---|
| `weft/` | 6,967 | 470 | 6,497 | engine + pull/ask/slice + threadgraph |
| `docs/` | 6,793 | 1,187 | 5,606 (+3,580 in `docs/superpowers/`) | design ≈ code |
| `tests/` | 5,742 | 179 | 5,563 | 297 pass / 7 skip in 7.5 s without ALab |
| `extras/usdview` | 4,224 | **1,379** | 2,706 | highest churn ratio in repo |
| `examples/` | 2,039 | 240 | 1,799 | ALab POC, compare, transcripts |
| `specs/` | 1,007 | 250 | 757 | codeless schema |
| `deps/` | 994 | 13 | 981 | near-zero rework — the most stable code |
| `absent/` | 478 | 1 | 477 | " |
| `bench/` | 402 | 15 | 387 | |

## (c) Unmerged branch work

None. `origin/claude/agent-swarm-eval-f9xgct` == `main` (`e441013`). No tags, no releases. Working tree clean. Two referenced artifacts are *not* in the repo: `.superpowers/threadpanel-report.md` (cited in `extras/usdview/README.md` and four commit bodies) and the ALab checkout every headline number depends on.

## (d) Positioning assessment per goal

**Are the four goals one product?** No — two. The **toolkit** (`weft pull/who`, `deps`, `absent`, usdview Ask/Solo/Who) works on any USD file with no authored metadata. The **engine** (`save/promote/compile/select/baseline/resolve/drift`, contracts, generators, envelope gate, slices, as-of resolver) requires a `.weft/` repo, `weft:*` interface layers, and team buy-in. `weft --help` lists all 22 subcommands under one banner that still reads "JIT-SD rung 1: solo, offline, no contracts" (`weft/cli.py`). README ordering (pull first, engine as "for teams that want ground truth") already implies the split; the CLI and docs do not.

**1. Surgical USD usage (pull → manifest → mask).** Strongest evidence of value: the translucent pull is asserted byte-identical to a 26-path reference in `tests/test_alab_pull.py`; benchmark S2 touches 716 KB / 59 layers vs 101 MB / 1,625 layers for the stock `UsdShade` walk, 82 ms vs 210 ms (`examples/alab/BENCHMARK.md` §Summary). Differentiation vs stock USD is real but narrow: population masks exist, but need paths as input; weft *computes* the mask from a predicate and hands back a verifiable receipt. Honest caveat the repo itself states: S1 (known path) is a 46× loss.

**2. Taxonomy (ask grammar, identity plane, `where:`).** Most dependent on buy-in, despite being marketed as "runs on any USD file": `where:finish=translucent` only works after `weft/extract.py` has *written* `weft:bind:finish` into every entity's interface sublayer — the "704 ms amortized one-time" step in BENCHMARK.md that mutates the corpus. On a stock file with no `weft:*` attributes the seed grammar reduces to `name:`/`path:`. USD's own Kind, collections, and `UsdSemantics` (labels API in 24.x+) already carry taxonomy; weft's addition is derivation rules recorded as provenance. Least differentiated of the four.

**3. Relationship mapping (`deps`, `absent`, `who`).** Most differentiated and most stable code (994 lines, 13 deleted). `UsdUtils.ComputeAllDependencies` remains forward-only and known-slow on large trees ([AOUSD forum](https://forum.aousd.org/t/get-dependencies-faster-than-computealldependencies-from-usdutils/2488)); `deps` adds reverse queries, non-arc edges (bindings, connections, class arcs), and class-hook-aware orphan detection, walking 4,296 layers in 1.75 s. Nearest ecosystem overlap is NVIDIA's USD Search / Asset Graph Search API, which is Nucleus/server-side ([usdsearch-client](https://nvidia-omniverse.github.io/usdsearch-client/)); a local, zero-server graph is a defensible niche. The `absent` "28 validators" comparison is now dated: OpenUSD 25.11 made the `UsdValidation` framework default in `usdchecker` and added a validation widget with `UsdValidationFixer` to usdview ([AOUSD 25.11](https://aousd.org/blog/announcing-openusd-v25-11-key-features-and-improvements/)) — `absent`'s checks could become validators in that framework rather than a parallel tool.

**4. Just-in-time engine.** Furthest from usable and the largest doc/spec footprint. Generators are two toy Python callables (`weft/generators/`); the ALab "refused by 19 consumers" demo is, per `31784f5`, "simulated at the interface level — offers shifted, payload unchanged"; 25× dedup is on a synthetic crate (`bench/`); the as-of resolver is a 198-line spec explicitly unscheduled (`docs/superpowers/specs/2026-09-02-as-of-resolver-design.md`); auto-versioning is "intended, not built" (`docs/07`). Ecosystem has moved under it: OpenExec (preview 25.08, continued in 26.08, [openusd.org](https://openusd.org/release/intro_to_openexec.html)) is Pixar's own value-driven computation engine and will absorb part of the "bounds/offers as a function of parameters" thesis; continued namespace-editor investment reduces the pain that `id:` addressing targets; `docs/07`'s Nucleus comparison is aging (Enterprise Nucleus Cache and Launcher deprecated in 2025, [NVIDIA](https://docs.omniverse.nvidia.com/utilities/latest/cache/enterprise.html)).

**Ecosystem sources:** [AOUSD 25.11](https://aousd.org/blog/announcing-openusd-v25-11-key-features-and-improvements/), [ComplianceChecker deprecation](https://forum.aousd.org/t/deprecating-usdutils-compliancechecker/2774), [OpenExec intro](https://openusd.org/release/intro_to_openexec.html), [OpenUSD 26.05 RC](https://forum.aousd.org/t/openusd-v26-05-release-candidate-is-now-available-on-github/2901), [ComputeAllDependencies perf](https://forum.aousd.org/t/executing-pxr-usdutils-computealldependencies-taking-an-inodinate-amount-of-time-to-complete/1786), [population mask](https://openusd.org/dev/api/class_usd_stage_population_mask.html), [Nucleus cache deprecation](https://docs.omniverse.nvidia.com/utilities/latest/cache/enterprise.html).

## Adoption: the honest rung today

- **Not published**: `pypi.org/pypi/weft-usd` → 404 (the bare name `weft` is taken, so `weft-usd` is the right dist name). No tags/releases.
- **Installs**: `pip install -e .` works (packages declared explicitly, `pyproject.toml`); `weft`, `python -m deps`, `python -m absent` all run. Suite green without ALab.
- **No stock quickstart**: `README` "Runs on any USD file, today" gives four commands but no file to run them on; `examples/shot.usda` is a generator query document, not a scene. `weft pull 'name:*' --context examples/shot.usda` returns 3 members in 0.2 s; **`weft who` prints nothing and exits 0** on that file — silent for a first user.
- **usdview plugin**: two env vars, a launcher shim (`weft_usdview.py`) required for the headline panel to paint, macOS-specific reasoning, README example path is an ALab file, and it points readers to a report file that isn't in the repo.
- **Rung reached**: rung 1 works but is not the product a first user would try. A pipeline TD could use `deps breaks/needs/why/orphans` and `weft pull --mask-out` today; a manufacturing/AEC user has nothing addressed to them despite `docs/01` arguing they are the stronger case (no CAD/BIM example, no `near:`/spatial demo on non-film data).

## (e) Risk register

| Risk | Evidence | Severity |
|---|---|---|
| Bus factor 1; AI-assisted velocity outpaces review | 1 author, 106 commits/5 days, `bae84d0` found README false "five merged PRs later" | High |
| Zero users; all validation is self-run on one corpus | README "no outside users yet"; every number from ALab 2.3.0; `--context` ALab path hardcoded in docs | High |
| Scope breadth: 22 CLI verbs, 4 goals, 2 products | `weft/cli.py`; design docs 5.6k + specs 3.6k lines vs 6.5k code | High |
| usdview panel time sink; dual architectures + shim | +3,935/−1,333 in 36 h; two panels shipped; macOS-only fixes | Med-High |
| Taxonomy needs corpus mutation ("buy-in" hidden in "no buy-in") | `extract.py` writes interface sublayers into ALab tree | Med |
| Docs debt / branding drift | 14 tracked files still say jitsd/JIT-SD; CLI banner; `docs/01–10` predate rename; missing `.superpowers` report | Med |
| Python-only performance | 5.6 s cold `deps` build; 46 ms vs 1 ms in S1 | Med |
| Ecosystem catches up (UsdValidation, OpenExec, AGS) | sources above | Med |
| No packaging/release/versioning | no PyPI, no tag, `version = "0.1.0"` never cut | Med |

## (f) 30/60/90-day plan

**30 days — freeze, split, publish (toolkit only)**
1. **Stop** all usdview panel work; keep one panel (`threadpanel.py`, no shim) and mark `webenginepanel.py`/`weft_usdview.py` experimental in `extras/usdview/README.md`. (S) Evidence: churn ratio, macOS-only fixes.
2. **Split the CLI**: `weft pull|who|deps|absent` as the documented surface; move `save/promote/compile/select/...` behind `weft engine ...` or a separate entry point; fix the "JIT-SD rung 1" banner in `weft/cli.py`. (M)
3. **Ship a stock quickstart**: add a small real scene (e.g. Kitchen_set or the ASWF asset corpus) to `examples/`, a `QUICKSTART.md` that runs `pull`, `who`, `deps breaks`, `absent` in <5 min; make `weft who` print "0 incoming edges" instead of nothing. (S)
4. **Publish `weft-usd 0.1.0` to PyPI** with a git tag and a GitHub release; add a wheel-install smoke job to `.github/workflows/tests.yml` (the console-script bug in `89e8d41` shipped once already). (S)
5. **Docs truth pass #2**: finish the jitsd→weft sweep in 14 files; delete or retitle `docs/index.html`'s stale line; remove the dangling `.superpowers` reference. (S)

**60 days — validate with one real user, measure on a second corpus**
6. Find one pipeline TD (ASWF `wg-usd-assets` or AOUSD forum) and run `deps` + `pull` on *their* tree; record findings in `examples/<corpus>/`. (M) Evidence: ALab is favorable terrain (BENCHMARK.md says so).
7. Second corpus benchmark: re-run `examples/alab/compare.py` logic on a non-film dataset (a CAD-to-USD export) to test the `docs/01` "non-film is stronger" claim, which currently has zero evidence. (M)
8. Reframe `absent` as `UsdValidation` validators (25.11+) rather than a parallel checker; keep the CLI as a wrapper. (M)
9. Measure cold `deps build` (5.6 s) and decide whether a cached index format is enough vs. a native walker. (S)

**90 days — decide the engine's fate**
10. **Freeze** `docs/03–06`, `10-slices.md`, the as-of spec, and generators until a user asks for versioning; move the ALab contract POC to `examples/alab/engine/` labelled "interface-level simulation". (S)
11. If a user does want compatibility gating, build it against *their* real republish, not a shifted offer; otherwise cut `select/compile/declare` from the published wheel. (L)
12. Write a one-page `docs/00-positioning.md` choosing one of the sentences below. (S)

**Stop doing:** adding design docs before a user exists; measuring only on ALab; shipping two implementations of the same UI; quoting the 19-consumer refusal without the "simulated" qualifier; using `--force`-style rewrites of prose in place of tests.

**Candidate positionings**
- **A.** "weft pulls any subset of an OpenUSD scene by what it is — a name, a material, a relationship — into a verifiable mask, without loading the world." — *supported by the evidence (S2, acceptance test).*
- **B.** "The dependency map OpenUSD doesn't ship: forward, reverse, and non-arc edges across a whole tree in seconds." — *supported, narrowest, cheapest to ship first.*
- **C.** "A version-control and contract layer for USD assets with measured compatibility." — *the original thesis; the evidence is weakest and the ecosystem (OpenExec, PLM tools) is moving here.*

Recommendation: lead with A, ship B as the wedge, hold C until a paying user asks.
