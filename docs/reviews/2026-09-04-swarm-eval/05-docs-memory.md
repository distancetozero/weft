# Docs & project memory — evaluation report

## (a) Verdict

**Strong raw material, weak curation.** The project's memory is unusually rich — commit bodies are genuine decision records (`6166f34`, `093294f`, `bae84d0`, `d6951d4` each explain what was measured, what was wrong, and why the fix is the fix), the ALab READMEs are verbatim runs, and BENCHMARK.md publishes a loss. But that memory is **scattered across five layers written in three eras** (JIT-SD design docs → IMPLEMENTATION.md → dated superpowers specs → landing page → commit bodies), and nothing reconciles them. There is **no single document that states the current thesis and architecture**; the closest is `docs/index.html` (a landing page, not an architecture doc) and the 2026-09-01 spec (which describes one subsystem). The self-critical posture is real (`bae84d0` "Make the repo tell the truth about itself"), but it has not been re-run since the prim-level pivot, so a reader who follows README's "reading order" is handed a design for a system that was substantially replaced.

The single most damaging defect: **IMPLEMENTATION.md contradicts itself** on the project's one closed open question (see table), and README/index.html carry three headline numbers with no reproducible source in the repo.

## (b) Contradictions and staleness

| Location | Issue | Fix |
|---|---|---|
| `IMPLEMENTATION.md:353-389` vs `IMPLEMENTATION.md:296-347` vs `docs/08:81-106` | "Benchmark" section says global row is "not a contrived worst case… the fix is to stop treating an asset as one opaque file… tracked as open question 9" — while the section immediately above ("settled by measurement") and OQ9 say the 1.0x figure *was* an artifact and byte chunking stays. Same file, opposite conclusions. | Delete or rewrite the Benchmark section's last two paragraphs; keep the table (numbers were re-measured at 64 KiB per `bae84d0`). |
| `IMPLEMENTATION.md:126-128` "169 tests instead of 107" | Actual: 303 collected; 297 pass / 7 skip here (183 pxr-gated, 120 bare). `BENCHMARK.md:182` says "292 passed, 1 skipped"; commits say 303/1. | Replace numbers with a pointer to CI, or a dated figure. |
| `README.md:128`, `index.html:221` "4,296 layers walked in 1.75 s (23 ms incremental)" | 4,296 comes from commit `67f20c3` (Aug 31); no script in the repo reproduces it. `BENCHMARK.md:139` measures **4,461** layers (4,296 + the 165 interface sublayers weft itself wrote into the tree), at **5,587 ms cold / 134 ms warm**. "23 ms" exists only as a docstring in `deps/graph.py:17,333` from a synthetic 500-asset run. | Cite BENCHMARK's numbers (they are script-produced), or add the walk to `compare.py`. |
| `README.md:129`, `index.html:220` "~126 ms" | Source is the spec's §3 probe (`2026-09-01…design.md:89`), measured once by hand. Not in any bench or test. | Add to `compare.py` or drop from "Measured". |
| `README.md:99-100` "the other **163 threads** declared at the boundary" | `examples/alab/README.md:131` prints **326 threads** (163 assets × 2 edge kinds). README conflates assets and threads. | "163 assets / 326 threads". |
| `docs/01-overview.md:26` | References `06-adoption.md`; the file is `07-adoption.md`. | Fix link. |
| `docs/04-contracts.md:25` | References `specs/jitsdContracts/schema.usda`; renamed to `specs/weftContracts/` in `593f542`. | Fix path. |
| `docs/01:3`, `docs/02:8,12` "sits *below* composition" | `bae84d0` explicitly corrected this to "runs before" because "the binder needs composed surfaces in hand… the one claim any Pcp-literate reader could falsify on sight." Correction landed in README (since rewritten) but never in docs/01-02. | Apply the recorded correction. |
| `docs/06:12-46`, `docs/07:40-71` | `/jitsd/objects`, `jitsd.lock`, `.jitsd/`, `jitsd init` — code uses `.weft/`, `weft.lock`, `weft` (`2a8155c`). 20 `jitsd` mentions in docs/07 alone. | Global rename in docs/, or a one-line note per file. |
| `README.md:141` "`docs/index.html` is the single-page design brief" | `ab16f74` replaced the brief with a landing page; the design content is gone. | Reword; the "brief" no longer exists anywhere. |
| `README.md:66-78` usdview section | Lists Ask/Solo/Restore/Who + receipt panel; omits the "headline" **Weft Threads** explorer, the native fallback, and the `weft_usdview.py` launcher that `extras/usdview/README.md:17-21` says is *required* for the panel to paint. README's `usdview shot.usda` invocation is incomplete on macOS. | Sync with extras README; link the launcher. |
| `extras/usdview/README.md:56,119` | Cites `.superpowers/threadpanel-report.md` for "the full investigation across every round" — file is not in the repo (session scratch). The decision trail for the panel exists only in commit bodies. | Move the round-by-round summary into the repo (see §d). |
| `IMPLEMENTATION.md:13-37` command table | Missing `verify` (added `6166f34`, "the missing fsck"), `select`, `pull`, `who`; `weft verify` is never mentioned in IMPLEMENTATION.md at all. | Regenerate table from `cli.py`'s 21 subcommands. |
| `docs/07:27-29` vs `IMPLEMENTATION.md:341,357` | "twelve saves of a 16 MiB asset… 205 KiB per save" vs "64 MiB, 30 saves… 456.7 KiB local". Both real, different parameters, neither says so. | Label the benchmark parameters in both. |
| `docs/07:53-72` "Real output, from the ALab proof of concept" | The `promote` transcript ("REFUSED: … v003 -> @approved is a breaking change / moved chemistry_test_tube02") is a paraphrase; `poc.py` prints "REFUSED by consumers: 19 props would break". | Paste actual output or say "abridged". |
| `docs/09:38` | "Canonical serialisation — absent, inherited as a risk — see OQ9" — OQ9 then found crate *is* deterministic within a version. | Update row. |
| `docs/superpowers/plans/…:3` | "REQUIRED SUB-SKILL: superpowers:subagent-driven-development" — agent-harness instructions shipped as project docs; 65 unchecked `- [ ]` boxes though every task was executed. | See §(4). |

**Staleness (pre-pull world).** `docs/02` (Datalog core, WASM kernels, ArResolver, "resolve then materialise"), `docs/04` (generators/exemplars/archetypes), `docs/05` (claim lattice), `docs/10` §"The screen"/"Plan" (worklist/catalog/map browser) describe an architecture that was never built beyond two toy generators and five presets (IMPLEMENTATION.md "Deliberate limitations" admits this). The built system's centre of gravity — `ask`/`follow`/`pull`/`manifest` over a raw `LoadNone` stage, no repo required, plus a usdview panel — appears in no numbered doc. `docs/10`'s plan step 2 ("the browser… map from bounds alone") was silently superseded by the usdview d3 panel, a different product decision, recorded nowhere but `1d7d71e`→`e441013`. `index.html` matches the *README*, not the md docs: it is thread-first and says nothing about generators, contexts, or Datalog.

## (c) Open questions — actual status

| # | Doc says | Code says | Status |
|---|---|---|---|
| 1 Channel ownership / promotion policy | open; "likely per-channel, gate default-on above @wip" | Gate is on for **every** channel including @wip; `--force` overrides; `set_channel(expect=)` CAS (`ledger.py:256`); no per-channel policy object | **Silently answered** (gate-everywhere + force), not per-channel |
| 2 Live-session checkpoint | open | No live sync built | Dormant; belongs in a parking lot |
| 3 Bounds as fn of params | open, three candidates | Candidate 3 chosen: `Generator.bounds(params)` (`generators/__init__.py:99`, `3d5a2e4`); spatial seeds use `extentsHint` (`ask.py`) | **Silently answered** |
| 4 Contract versioning semantics | open | Fully decided in `contracts.py:455` + `reeval.py`: breaking = removed/major bump/envelope tightened/frame beyond envelope/public or role flipped; consumer tolerance overrides provider envelope | **Silently answered**; the answer is the project's headline feature |
| 5 Sequencer scope | open | Per-asset monotonic revs via `O_EXCL` locally; no sequencer | Open, correctly |
| 6 Diamond deps | open | Cardinality `one` with >1 candidate → "ambiguous", no resolution | Open; IMPLEMENTATION.md:150 restates it without linking |
| 7 Live contract validation | open | `select --impact`, usdview `Ask`/`Who` are live but don't validate contracts | Partially answered (interrogation yes, validation no) |
| 8 Receipt log location | open | `ledger/log/YYYY-MM-DD.jsonl` via `log_event` (`ledger.py:150`); same store as ledger; as-of spec (§2) builds on it | **Silently answered** |
| 9 Granularity | RESOLVED | 64 KiB, config recorded | Resolved — but contradicted by IMPLEMENTATION.md |

**Raised by implementation, not listed anywhere in docs/08:** prim-level contracts / ECO-scoped gating; effectivity; federated multi-root contexts; conjunctive asks; relocates; mask-granular load-set; persistent closure index and its scale triggers (all spec §2); the write path/authorship (as-of spec §8); identity-key precedence per context; 1-hop-only consumer re-evaluation (`alab/README:378`); proof logged not stamped (`:380`); docs/10's own four questions (edit scope, demand-loop budget, demand promotion, receipt cost model); usdview: event-filter removal cost, imaging-engine rebuild per load, pin persistence, multi-select; whether the ALab "interfaces written into the tree" pattern is the intended deployment shape.

## (d) Decisions living only in git

- **The usdview panel's four reversals** — QWebEngine (`1d7d71e`) → native Qt (`56c60d9`, "per the agreed decision rule") → browser-bridge (`9e93367`) → embedded WebEngine again (`8e60d05`, "owner rejected… hacking a browser on the user") → root-caused as a PySide re-entrancy bug, not graphics (`d6951d4`). Six rounds, a wrong hypothesis held for five of them, and the "decision rule" itself is never written down.
- **"Sits below" → "runs before" composition** (`bae84d0`) — applied to README only.
- **Generators pinned by source hash; merkle folds it in** (`6166f34`) — drift semantics changed; IMPLEMENTATION.md's Merkle bullet unchanged.
- **GC keeps history by default; `--prune-history` opt-in** (`6166f34`) — reverses docs/06 §GC.
- **Class-hook inherits are not orphans** (`381aa66`) — a `deps` semantics decision.
- **Zero users ⇒ no migration shims for the wire rename** (`2a8155c`).
- **`jitsd` kept as CLI alias** (`4ecb232`) — pyproject only.
- **Interfaces written *into* the asset tree as a sublayer, not sidecars** (`6a8691d`) — a deployment-shape decision, in alab/README prose only.
- **`Usd.TraverseInstanceProxies` + drop `IsLoaded`** as the standing traversal predicate (`e50d89b`, `56c60d9`) — recurring bug class; no doc names the rule.
- **Imaging engine must be rebuilt on load/unload under `--bboxStandin`** (`ab2bccc`) — upstream limitation, plugin-wide consequence.

There is no ADR index and no running log. The superpowers specs are per-session snapshots ("Status: approved by owner 2026-09-03"); what the project forgets between sessions is exactly the *why-not* (what was tried and rejected), which is why the extras README points at a scratch file that no longer exists.

## (4) The 2,849-line plan

**Executed essentially in full.** All 13 tasks have a commit whose message is the plan's verbatim (`f1569d9`…`e50d89b`, Sept 1). Spot-checks (10): T1 `CACHE_VERSION == 2` ✓; T2 `follow.py` `FollowTerm`/`FOLLOW_LANGUAGE_VERSION` ✓; T3/T4 `ask.py` `DEFAULT_IDENTITY_KEYS` ✓ (`jitsd:id`→`weft:id`); T5 `pull.py` `_admit`, `_reverse_index` ✓; T7 `registry.py` omission classes ✓ (colliders rule moved from table to code — minor drift); T8 extractors ✓ (`weft__extractors`); T9 `manifest.py` `MANIFEST_VERSION`, `verify` ✓; T12 `slice.py:309,593,600` `is_prim_seed`, invariant, drift ✓; T13 `test_alab_pull.py` ✓ but the test *diverged* (embeds `SPIKE_TRANSLUCENT_MASK`, per `a953d37`), and T13's "add a row to README's What-exists table" targets a table that no longer exists. Tests: 31 files, every plan-named test file present.

**Is it misleading now?** Yes, mildly: 0/65 checkboxes ticked, all paths say `jitsd/`, all wire keys say `jitsd__*`, the agent-harness header is shipped as project documentation, and the plan carries no "executed on 2026-09-01, see commits X–Y" footer. It is a faithful record of *intent* and a wrong record of *state*.

## (6) Audience

README/index.html → studio evaluator (good). ALab README + BENCHMARK → sceptical evaluator (excellent). IMPLEMENTATION.md → the author (a changelog wearing a reference's clothes). docs/01–10 → a 2026-08-31 reader of a different project. Specs/plan → an AI executor. No CONTRIBUTING.md, no CLAUDE.md, no module map: a contributor learns that `weft/` has 18 modules only by `ls`. README's reading order (01→07, 09, 08, 10) sends a newcomer through ~1,700 lines of JIT-SD before the one spec that describes what exists.

## (7) Honesty

Largely earned: BENCHMARK publishes a 46× loss, alab/README has "What it does not show," IMPLEMENTATION.md records five self-inflicted syntax bugs and two measurement errors. Creep is confined to README/index.html's "Measured" block (two of six numbers unreproducible, one stale, one conflates assets/threads), "Proven on ALab", "from a scene that was never loaded" (it is composed under `LoadNone`; 59 layers/716 KB consulted), and index.html's "adversarially reviewed" without saying the six lenses were AI review passes (`c16b284`).

## (e) Next steps

1. **S — Fix the IMPLEMENTATION.md self-contradiction** (delete Benchmark §'s last two paragraphs), the `06-adoption`/`jitsdContracts` links, and the 163/326 line. One hour.
2. **S — Purge unreproducible numbers from README/index.html "Measured"**: drop 126 ms and 23 ms or add them to `compare.py`; replace 4,296/1.75 s with BENCHMARK's 4,461/134 ms warm; replace test counts with a CI badge.
3. **M — Write `ARCHITECTURE.md`** (the missing current-state doc): the two products as built — (i) repo-less `pull/who` over `ask`→`follow`→`pull`→`manifest`, backed by `deps`; (ii) the engine (`store`/`ledger`/`contracts`/`reeval`/`slice`); the usdview plugin; module map with one line each; the standing rules (traverse predicate, "silent omission is fatal", relational-plane-only). Point README's reading order at it *first*.
4. **M — Add `DECISIONS.md`** as a dated append-only log seeded from §(d): the panel's four reversals and root cause, below→before, GC history default, generator-hash drift, class hooks, interfaces-in-tree, wire rename with no shims. Each entry: date, decision, alternatives rejected, commit. Make the extras README point here instead of `.superpowers/`.
5. **S — Rewrite `docs/08-open-questions.md`**: mark 1, 3, 4, 8 answered-by-implementation with the commit; move 2, 5, 6 to a "parked (needs rung ≥2)" section; import the implementation-raised list above.
6. **M — Retire or reframe docs/01–07, 09**: add a banner ("design record, 2026-08-31, JIT-SD era; superseded where ARCHITECTURE.md disagrees"), apply the recorded "runs before" correction, and either s/jitsd/weft/ or leave with the banner. Do not spend effort modernising the Datalog/WASM/claim-lattice sections — they are aspiration, and should be labelled as such.
7. **S — Close the plan document**: strike the agent header, add an "Executed 2026-09-01, commits f1569d9…e50d89b; deviations: …" footer, tick the boxes or delete them. Same footer on the 2026-09-02 as-of spec ("unscheduled") and 09-03 spec ("built in 96fec96–036cfc3").
8. **L — Consolidate IMPLEMENTATION.md into ARCHITECTURE.md + DECISIONS.md**; what remains (the ALab and chunking measurements) becomes `MEASUREMENTS.md`, each table labelled with parameters, date, and the script that produced it. This is where "measurement corrected design" should live as a section, so the claim in README's Status is checkable.
