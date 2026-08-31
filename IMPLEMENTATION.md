# Reference implementation — rung 1

Solo, offline, no contracts, no server. Per `docs/07-adoption.md`, nothing
above rung 1 may be required for rung 1 to be useful, so this implements only
what one person working alone needs.

```
pip install -e ".[dev]"      # numpy and pytest are optional
python -m jitsd init
python -m jitsd save hero_car car.usdc -m "reworked front wing"
```

## What it does

| Command | |
|---|---|
| `init` | create a repository (`.jitsd/`) |
| `save <asset> <file>` | store a revision, move `@wip` |
| `log <asset>` | revision history |
| `channels [asset]` | show channel pointers |
| `promote <asset> <rev> --to <chan>` | move a channel pointer |
| `back <asset> <rev>` | point `@wip` at an earlier revision |
| `checkout <asset> <rev\|@chan> <dest>` | materialise to a file |
| `baseline cut [--label L]` | pin the world |
| `resolve [--baseline N]` | write `jitsd.lock` (mints a baseline if floating) |
| `drift <baseline>` | has anything changed since sign-off? |
| `diff <asset> <a> <b>` | structural diff — chunks shared vs new |
| `stat` | storage and dedup |
| `gc` | drop unreachable blobs and chunks |

## What building it changed

**Whole-file content addressing does not deduplicate.** One changed byte
changes the file hash, so a 4 GB asset saved 200 times costs 800 GB. The claim
in `docs/06-storage.md` is only true with **content-defined chunking**, which
`jitsd/chunker.py` now implements (gear hash, ~1 MiB average). This was not in
the design docs and is a hard requirement, not an optimisation.

**Dedup granularity is the chunk size.** A 50 KB edit does not cost 50 KB — it
costs the chunks it touches, so ~1–2 MiB at the current parameters. Still far
better than a second full copy, but the docs should not imply byte-level
deltas.

**The obvious vectorisation is useless.** Computing all 64 shifted gear terms
across the file measured 2.3 MB/s. Two properties fix it: only the low `bits`
bits are ever tested, and the requirement is monotone under level, so the
candidate set halves each level instead of every position being carried
through. With a uint8 parity prefilter and min-size skipping it reaches
~22 MB/s in Python. A production implementation belongs in C or Rust; this one
exists to validate the model, not to ship.

## Deliberate limitations

- **Merkle is top-level only.** `Repo.merkle_root` hashes the pinned revisions,
  which gives "an identical world hashes identically" but not the O(changes)
  subtree diffs of `docs/06-storage.md`. Real subtree hashing needs a prim
  hierarchy, which arrives with the resolver.
- **No pxr dependency.** Revision and baseline files are real `.usda` that open
  in usdview, but machine-readable state travels in a JSON string inside
  `customLayerData` (`jitsd__meta`) because parsing `.usda` without USD is not
  worth doing. With pxr present this is read through the API instead; the files
  on disk do not change.
- **One file per asset.** No prim-level structure, so no contracts, no bounds,
  no context compilation. Those are rungs 4 and 5.
- **`checkout` reassembles in memory** per chunk; fine at these sizes, wrong
  for a streaming client.

## Benchmark

```
python bench/dedup.py --size-mb 64 --saves 30
```

Measures three edit patterns, because they do not behave alike: a localised
rework, several scattered edits, and a global re-export that perturbs every
value. The third is the worst case for any chunker and is reported rather than
hidden.
