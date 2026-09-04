# weft — code quality, correctness & test health

## (a) Verdict

**Library code: good. CLI and packaging edges: rough.** The core modules (`store`, `ledger`, `contracts`, `slice`, `pull`, `chunker`) are careful — atomic writes with fsync, O_EXCL revisions, compare-and-swap channels, sorted iteration everywhere a digest is computed, canonical `json.dumps(sort_keys=True, separators=…)` before hashing, lazy `pxr` imports behind a documented bare/full split. I found no non-determinism bug in any digest path and no Python-3.9 syntax/stdlib violation (AST parse at `feature_version=(3,9)` clean; no `removeprefix`/`zip(strict)`/`match`).

The weak layer is `weft/cli.py`: **38% covered**, no top-level exception boundary, so a dozen ordinary user mistakes end in a raw Python traceback. Test health is strong in volume (297 pass, 7.3 s) but one bare-mode test that exists specifically to prove the bare promise **never runs in the bare CI job** because of a collection-time `importorskip` in a decorator. Docs overstate nothing dangerous but the test count claim is stale (says 169/107; actual 304/134).

## (b) Numbers

| Run | Result | Notes |
|---|---|---|
| Full (`numpy 2.4.6`, `usd-core 26.8`) | **297 passed, 7 skipped** in 7.3 s | skips: 6 × `WEFT_ALAB` unset, 1 × `test_cli_bare` (pxr present) |
| Bare venv (`pytest` + `pip install -e . --no-deps`) | **115 passed, 19 skipped** in 8.1 s | 17 modules skip on `pxr`, 1 on `numpy`, 1 module-level skip (see D2) |
| IMPLEMENTATION.md claim | "169 tests instead of 107" | stale — actual 304 vs 134 collected |
| Coverage (full env, `weft/* deps/* absent/* extras/*`) | **77% total** (4832 stmts, 1091 missed) | |
| ↳ `weft/cli.py` | 38% (377/613 missed) | every `cmd_*` except `pull`/`who` is 87–98% unexecuted |
| ↳ `extras/usdview/weftViewer/__init__.py` | 9% | Qt; expected. `core.py` 96% |
| ↳ `weft/extract.py` | 83% | `footprint()` 91% missed |
| ↳ `weft/contracts.py` | 86% | `_euler_from_matrix` 92% missed (rotation-from-matrix path never exercised) |
| ↳ everything else | 88–100% | `pull.py` 95, `query.py` 98, `follow.py` 100 |
| CI schema step (`usdGenSchema` regen + diff) | reproduced locally: **no diff** | committed pair current for usd-core 26.8 |
| ruff `F,B,E7,PLW,BLE` / pyflakes | 26 unused imports, 1 redefinition, 2 B904, ~40 `except Exception` (mostly usdview guards) | nothing that changes behaviour |
| ALab dataset | **absent** on this host | 6 acceptance tests cannot run here |

## (c) Defects, ranked

**D1 — CLI has no error boundary; ledger `KeyError`/`FileNotFoundError`/`UsdaError` leak as tracebacks.** `weft/cli.py:815`:
```python
def main(argv=None) -> int:
    args = build_parser().parse_args(argv)
    return args.fn(args)
```
Repro (inside a repo): `weft checkout nope r1 o.usda`, `weft drift 999`, `weft diff nope a b`, `weft check nope r1`, `weft promote car r1 --to approved`, `weft compile nofile.usda`, `weft save a ok.usda --interface bad.usda` — all print a traceback (exit 1, but `KeyError: "cannot resolve 'r1' …"` is the last line). `cmd_pull`/`cmd_who`/`cmd_select` wrap `(KeyError, ValueError)` individually; the other 15 commands don't. First thing an external user hits.

**D2 — `tests/test_slice_references.py` is skipped wholesale in the bare job, hiding the two pure tests it contains.** `tests/test_slice_references.py:57`:
```python
@pytest.mark.skipif(pytest.importorskip("pxr", reason="needs usd-core") is None, ...)
```
`importorskip` raises `Skipped` at *import* time, so the module collects `0 items / 1 skipped` (verified). `test_closure_without_pxr_is_contracts_only` (line 39) — whose purpose is the no-pxr path — has therefore never run in the bare CI job. Fix: `pxr = importlib.util.find_spec("pxr")` + `skipif(pxr is None)`.

**D3 — `Repo.find()` raises `SystemExit` from library code.** `weft/ledger.py:369`:
```python
raise SystemExit("not a weft repository (no .weft found) -- run `weft init`")
```
Any programmatic caller (`weft.Repo.find()`, the usdview plugin) gets a process exit instead of an exception. Should be a `weft`-specific exception the CLI translates.

**D4 — Temp directories leak on every `select --save-rules` and every `pull/who --context <asset>`.** `weft/slice.py:175-179` and `weft/cli.py:332-335` use `tempfile.mkdtemp(prefix="weft-…")` and never remove it. After one test run there were 15 `/tmp/weft-rules-*`/`weft-ctx-*` dirs. `save_rules` could `repo.save` from bytes; `_context_file` should use a `TemporaryDirectory` whose lifetime is the command.

**D5 — `write_baseline` is the one durability hole.** `weft/ledger.py:333`: `p.write_text(body)` — plain truncating write with no O_EXCL, while `write_revision`, `set_channel`, and the store all go through fsync+rename+O_EXCL. `next_baseline()` is read-then-write, so two concurrent `weft resolve`/`baseline cut` calls can both mint `000007` and the second silently overwrites the first — exactly the race the file's own comments (lines 220-223) explain for revisions.

**D6 — `weft resolve` mints a new baseline every invocation.** `weft/cli.py:513-518` ("you never ask for a baseline — you receive one"). Verified: two `resolve` calls → two baselines with identical pins. Intended semantics, but there's no dedup on identical merkle root, so CI-style repeated resolves fill `baselines/` and `weft baseline` becomes unreadable. Also `--out` defaults to `weft.lock` in **cwd**, not the repo root, and `.gitignore` ignores `weft.lock` — a lockfile you can't commit is an odd default.

**D7 — Import-time side effects and a heavy `import weft`.** `weft/__init__.py:10-12` imports `.cli`, which imports `.generators.vehicle` "to register the built-ins" (cli.py:18) — so `import weft` pulls argparse, `getpass`, slice, query, and mutates the global `_REGISTRY` (`generators/__init__.py:109`). Meanwhile `import weft` exports `ObjectStore, Stats, Ledger, Repo, Revision, Baseline, main` but **not** `pull`, `who`, `resolve_slice`, `Surface`, or `check_compatibility` — the functions a programmatic user actually wants. The `if __name__ == "__main__"` block in `__init__.py:14` is dead code. Stale text: `cli.py:651` describes the tool as `"JIT-SD rung 1: solo, offline, no contracts."` while the same parser has `bind`, `check`, `promote`.

**D8 — Help text is thin.** 22 subcommands; `python -m weft <cmd> --help` for `promote --to`, `check --to`, `save file/asset`, `baseline --label/--channel`, `pull --depth`, `who --kinds`, `compile --context`, `select --depth/--pin/--omit/--baseline/--context` show no help string at all. `checkout` has no `-f`; it will `os.replace` over an existing `dest` silently (`store.py:251`).

**D9 — Silent fallbacks in `extract.py` and `absent/detect.py`.** `extract.py:56-60, 85-89, 129-133, 167-173` catch `Exception` and return `[]`/`None`, so a corrupt look layer produces a consumer interface with no `provides`/`shading` and no diagnostic. `absent/detect.py:301-304` does `return` (not `continue`) on the first exception inside `for prim in stage.TraverseAll()`, silently abandoning the `empty-collection` check for every remaining prim.

**D10 — Minor/stylistic but real:** `ask.py:50,60` re-raise inside `except` without `from` (B904, loses the original); `deps/__main__.py:37/39` `prog` redefined; `generators/__init__.py:114` registers an unversioned alias that "resolves to whatever was registered last" — `pin()` mitigates for storage, but `weft declare --generator chassis` silently picks the newest; unused imports in 12 source files; 213-line `resolve_slice`, 188-line `pull()`, 163-line `build_parser` (readable, but the two closure loops in `slice.py:636-683` and `pull.py:361-408` are near-duplicates of each other's BFS-with-exhaustion-sweep and would benefit from one shared frontier helper).

**Not defects (checked and fine):** `unicode_escape` readers in slice/registry/manifest are safe because `json.dumps` ensures ASCII; `_esc` handles `\n`/`\t`/quotes/backslashes (test-covered); merkle/manifest/reeval digests all sort; `test_deps.py:416` mtime sleep is not flaky (size also changes); `pyproject` `packages` list matches reality (`weft.generators` present, `extras/usdview/weftViewer` intentionally unpackaged and documented as PYTHONPATH-loaded); `jitsd` alias works; no lockfile is acceptable for a zero-dependency package.

## (d) Test quality notes

Behavioural, not snapshot-y: assertions are on computed properties (`hits/misses`, violation kinds, member sets, digest inequality), no golden files. The `test_correctness.py` set (flipped byte, missing chunk, gc keeps history, raced channel, newline in message) is exactly the right shape. Weak spots: `tests/test_pull.py` and `test_extract.py` lean on `assert "..." in text` over emitted USDA (18/24 such asserts) — brittle to formatting, not to meaning; `test_generators.py:73` `assert c.generate(p,ctx,{}) == c.generate(p,ctx,{})` is determinism-only. No `conftest.py`, so the seven fixture helpers (`_repo`, `_blob`, random-bytes writers) are copy-pasted across files. CLI behaviour is tested only via `test_cli_pull.py` (5 tests) and `test_cli_bare.py` (1).

## (e) Next steps

1. **S** — Wrap `main()` in one `try/except (KeyError, ValueError, OSError, UsdaError, RevisionExists, ChannelRaced)` → stderr message + exit 1; add `WeftError`/`NotARepository` and stop raising `SystemExit` in `Repo.find` (D1, D3).
2. **S** — Replace the `importorskip`-in-decorator idiom in `test_slice_references.py` with `find_spec`; add a bare-job assertion that at least N pure tests collected from that module (D2).
3. **S** — Route `write_baseline` through `_write_text_atomic` with O_EXCL like `write_revision`; skip minting in `resolve` when the merkle root equals the latest baseline's (D5, D6).
4. **S** — Clean up tempdirs (`TemporaryDirectory` in `_context_file`; `Repo.save_bytes` for rules) and fix the two silent `return`/`except Exception` sites in `absent/detect.py:303` and `extract.py` to at least emit a diagnostic (D4, D9).
5. **M** — Add a `tests/test_cli.py` driving every subcommand through `main([...])` + `capsys` on a tmp repo (happy path + one bad-ref case each). This alone lifts `cli.py` from 38% to ~80% and would have caught D1. Move shared fixtures to `conftest.py`.
6. **M** — Define the public API: `weft/__init__.py` exports `Repo, pull, who, resolve_slice, Surface, check_compatibility` lazily; stop importing `cli` at package import; make generator registration explicit (`weft.generators.load_builtins()`); fix the stale "JIT-SD … no contracts" description and IMPLEMENTATION.md's test counts (D7).
7. **M** — Fill in argparse `help=` for every flag, add `checkout --force` and refuse to overwrite otherwise, run `ruff --select F` in CI to hold the line on unused imports (D8, D10).
8. **L** — Extract the shared BFS/exhaustion-sweep from `slice.resolve_slice` and `pull.pull` into one frontier helper with a unit test that both call sites' boundary reporting agrees; this is the highest-risk duplicated logic in the codebase.
