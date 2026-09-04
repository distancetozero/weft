# Just-in-time USD — how much of the thesis is real

## (a) Verdict

About one third of the JIT thesis is built, and that third is honest: a content-addressed chunk store, immutable revisions, channels with a gated promote, baselines/lockfile/drift, type-directed contract binding, consumer re-evaluation with the consumer's own tolerance, and a two-phase `compile` that turns a kilobyte query document into a stage with generator-computed mount points. The demo in IMPLEMENTATION.md reproduces exactly (`review` digest `a708249907d3cc61` matches the doc; 128/128 requested tests + 21/21 `test_pxr` pass).

But the "resolution layer *below* USD composition" does not exist. Nothing touches an Ar resolver, a file format plugin, or a scene index; `compile` writes a flat `.usda` that USD opens like any other file, and the `weft:obj/sha256:…` payload arcs the engine emits into revision layers and constant members are dead in stock USD (`Ar.GetResolver().Resolve("weft:obj/…")` returns `''`; the prim composes with no children). Generators are two in-process Python classes; no sandbox, no WASM, no exemplars declared, no Datalog, no claim lattice, no authorization tier, no live sessions, no sequencer. The versioning core is a well-reasoned single-writer prototype with three concrete data-loss paths under concurrency.

## (b) Claim table

| Design claim | Status | Evidence |
|---|---|---|
| Content-addressed, deduped object store (06 §1) | **built** | `weft/store.py:158-175`, chunker `chunker.py:46-48` (64 KiB) |
| Revisions immutable, never overwritten (03) | built | `ledger.py:181-231` O_EXCL |
| Channel pointer is the only mutable object (03) | built, CAS is TOCTOU | `ledger.py:255-278` — read at 271, write at 278, no lock |
| Baselines immutable (03/06) | **contradicted** — plain `write_text`, no O_EXCL; probe overwrote `000001` | `ledger.py:333` |
| "You never ask for a baseline; you receive one" (03) | partial — `weft resolve` mints; `compile` does not, emits `"(floating)"` | `cli.py:513-518` vs `query.py:153,243` |
| Merkle hierarchy, O(changes) diff (06) | stub — one hash over `(asset, rev, blob\|gen\|params)` | `ledger.py:580-605`; admitted `IMPLEMENTATION.md:171` |
| Bind by contract, not path (04) | built | `contracts.py:374-438`; `examples/wheelset.iface.usda` names no chassis |
| Envelope gate at promotion (03/04) | built | `contracts.py:454-536`; demo refused v003 (2.4 mm > 0.5 mm) |
| Consumer re-evaluation, consumer's own tolerance (03 "measured") | built | `reeval.py:351-408`; `contracts.py:319-324` reads `tolerance:linear` |
| Exemplars as the generator's test suite (04) | **stub** — field exists, no shipped generator declares any, no test sets one | `generators/__init__.py:74`; `ledger.py:446-474` unexercised |
| Generators: computed offers, bounds w/o geometry, context variation (04) | built (toy) | `generators/vehicle.py:277-301, 355-356` |
| Generator identity pinned; code drift detected (spec `generatorVersion`) | **partial/defective** — `code_hash` omits `offers`/`requires`/helpers | `generators/__init__.py:150`; probe: rewrite `hub_frames` → same hash, `drift` silent, compiled digest differs |
| Two planes: resolve then fan out geometry in parallel (02) | partial — phases split, phase B serial | `query.py:155-215` |
| "Hash the derivation, not the output bytes" (02) | contradicted — digest is sha256 of stage text | `query.py:134-135` |
| Context = claim set, 3 tiers, deny-by-default auth (05) | stub — 5 hard-coded presets, no tier 3 | `query.py:55-61` |
| ArResolver / SdfFileFormat / dynamic payload / Hydra hooks (02 table) | **absent** | only `extras/usdview/plugInfo.json` (a usdview Python UI plugin) |
| WASM/sandboxed kernels, deterministic FP (02) | absent | `IMPLEMENTATION.md:180` |
| Baseline + sparse overlay handoff (`sh0120 @ baseline118 + hero_car@wip`) (03) | absent — `Overlay` has no revision field; pins resolve at one coordinate | `slice.py:33-36, 509` |
| Override handles bound to interface (04, spec `WeftOverrideHandleAPI`) | absent | no reference in `weft/*.py` |
| Datalog core + constraint tier (02) | absent — index lookup | `contracts.py:386-392` |
| Units in the type system (04) | stub — `Param.unit` is a label, never checked | `generators/__init__.py:35-48` |
| Termination / fuel / cost class (04) | stub — `cost_class` only printed | `cli.py:158` |
| Receipts log of `(query, context, baseline, manifest)` (02) | partial — save/promote/baseline logged; `compile` logs nothing | `ledger.py:157-163`; `cli.py:165-194` |
| Live sessions, sequencer, relative refs `seq040~1` (03) | absent | `ledger.py:281-291` accepts `vNNN`/`@chan` only |
| Chunking survives re-export; 64 KiB knee (06 "Measured") | built, measured | `bench/granularity.py` |
| Storage claim "fails completely for re-export → per-prim hashing" | stale, contradicts OQ9 | `IMPLEMENTATION.md:353-389` vs `docs/08:83-107` |

## (c) Defects and risks, ranked

1. **`gc` races `save` → dangling blob.** `put_bytes` skips a chunk that already exists (`store.py:134-136,169`), then writes the manifest (`:174`). A concurrent `gc` between those steps deletes any chunk not referenced by a *reachable manifest* (`store.py:307-323`); the temp-file guard (`:317`) does not cover it. Reproduced: `get_bytes` → `KeyError: blob references missing chunk`. Also `reachable_blobs` (`ledger.py:606-640`) cannot see a revision whose `.usda` is not yet written. No repo-level lock exists anywhere.
2. **Baselines are overwritable.** `ledger.py:333` `p.write_text(body)` — non-atomic and non-exclusive, unlike `write_revision`. Two concurrent `cut_baseline` calls both compute the same `next_baseline()` and the second silently replaces "the lockfile". Also a crash mid-write leaves a truncated baseline.
3. **Generator drift is invisible for the method that matters.** `code_hash` (`generators/__init__.py:150`) hashes `surface` (the *base-class* method), `bounds`, `generate`, `bind_params` — never `offers`, `requires`, or helpers like `hub_frames`. Editing where the hubs are produces identical `merkle_root`, `drift` says "no drift", `verify` says "all match", and the compiled stage changes. This defeats the exact property the docstring promises (`:139-144`).
4. **`resolve()` silently floats `@approved` onto `@wip`** (`ledger.py:575`). Consequences: a baseline "of approved" pins unpromoted WIP; and the promotion gate re-evaluates WIP consumers — demo: an unpromoted `strict_wip_consumer` blocked `chassis v002 → @approved`. The doc's "only revisions on a channel are citable" is violated by default.
5. **Channel CAS is not a CAS.** `set_channel` reads (`ledger.py:271`) then renames (`:278`) with no lock; two promoters both pass `expect`. `ChannelRaced` fires only if the interleaving happens to be visible.
6. **Promotion cost is O(world), twice.** `check_promotion` → `exemplar_surfaces(pins_old)` and `(pins_new)` read every revision of every asset (`ledger.py:446-474, 476-491`): 406 `read_revision` calls for 202 assets with one consumer. No reverse index from contract → consumers. Fine at ALab (437); not at 100k assets.
7. **Whole file in RAM.** `put_file` → `read_bytes` (`store.py:177-178`), chunker over `bytes`; a 4 GB asset is 4 GB+ resident. `checkout` streams (`:222-255`) and does verify hashes — that part is right.
8. **`check_promotion` skips re-evaluation when the incumbent has no surface** (`ledger.py:440`), so adding a first contract surface that captures consumers is never checked.
9. **Config drift fallback.** `store.params()` returns current module defaults when `config.json` is absent (`store.py:122-123`) — exactly the silent-dedup-loss failure the docstring warns about; low likelihood because config and the 64 KiB default landed in the same commit (`093294f`).
10. **Dead payload arcs.** Every payload-backed revision and every constant slice member emits `@weft:obj/sha256:…@` (`ledger.py:199`, `query.py:41`) that no resolver serves; `test_pxr.py:66-67` only checks the string round-trips.

## (d) Strategic drift

Of the 24 commits after the wire rename (`2a8155c`, 2026-09-02), 23 are usdview/pull/threadgraph/ALab/docs; the last substantive engine commit is `660044c` (consumer re-eval, 2026-09-01). The README leads with "Pull the thread, not the world", spends its first 90 lines on `weft pull` against ALab and the usdview plugin, and demotes the JIT engine to a "for teams that want ground truth" section at line 94; `pyproject.toml:4` describes the package as "pull threads through OpenUSD"; `docs/index.html` mentions JIT once. `weft pull`/`who` explicitly need no `.weft/` repository (`IMPLEMENTATION.md:291-296`). The product, as positioned and as worked on, is **surgical pull on existing USD files with declared boundaries and a receipt**; the JIT engine is the scaffolding that produced the vocabulary (contracts, tolerances, receipts) and is now load-bearing only as a testbed for "measured compatibility" — which the pull side reuses via `deps breaks`. A first external user would run `weft pull … --mask-out` and the usdview panel; they would never `init` a repo, and if they tried `compile` they would find two toy generators and payloads USD cannot resolve. The docs still say "JIT-SD" throughout and IMPLEMENTATION.md still calls `compile` "the part that makes it just-in-time"; that is no longer where the effort or the value is, and the README should say so rather than let readers infer it.

## (e) Next steps

1. **S — Fix `code_hash`.** Hash every method defined on the subclass (walk `type(gen).__dict__`), not four fixed names. Add a test that rewrites `offers` and expects `drift`. Frees defect 3.
2. **S — Make baselines immutable.** Use the O_EXCL path from `write_revision` in `write_baseline` (`ledger.py:333`); raise on collision.
3. **S — Stop `@approved` falling back to `@wip`** (`ledger.py:575`). Require an explicit `--float-wip`; make `cut_baseline` refuse or annotate unpromoted assets. This also fixes the gate consulting WIP consumers.
4. **M — Repo-level lock + save/gc protocol.** A single `flock` on `.weft/lock` taken by `save`, `promote`, `baseline cut`, `gc`; or write a `.weft/inflight/<pid>` root that `reachable_blobs` includes. Turns the CAS at `ledger.py:271-278` into a real one.
5. **M — Serve the `weft:obj/` scheme.** Cheapest honest path: at `compile`/`checkout` time, materialise referenced blobs into `.weft/cache/` (docs/06 already describes this) and emit relative paths. A real `ArResolver` is C++ only (no Python Ar plugins), must be built against the exact `usd-core` ABI, and is the first thing that would make "below composition" literally true — size L, and it should be decided, not deferred, since the payload arcs are currently a lie to USD.
6. **M — Exercise exemplars.** Give `Chassis`/`WheelSet` two exemplars each, add a test where an exemplar (not the default binding) is what refuses the promotion; otherwise delete the field and the doc claim.
7. **M — Consumer index for the gate.** Persist a `contract → consumers` map on promote so `check_promotion` reads O(consumers), not O(world) twice (`ledger.py:446-491`).
8. **S — Reconcile the docs.** Delete or date-stamp `IMPLEMENTATION.md:353-389` (the "stop treating an asset as one opaque file" paragraph and the `1 MiB` at `:153`) so the repo carries one answer to OQ9; state in README which of pull/engine is the product and that `compile` is a testbed.
