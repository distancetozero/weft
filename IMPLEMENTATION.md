# Reference implementation — rung 1, plus contract resolution

Solo, offline, no server. Per `docs/07-adoption.md`, nothing above rung 1 may
be required for rung 1 to be useful — so versioning works with no contracts
declared at all, and contracts are an upgrade layered on top.

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
| `save --interface <f.usda>` | attach an authored contract surface |
| `bind` | resolve requirements to offers **by contract identity** |
| `check <asset> <rev>` | would promoting this break anything? |
| `promote` | refuses breaking changes unless `--force` |

## Contract resolution

The first thing here USD cannot do. Consumers declare a requirement against a
contract identity; providers declare an offer satisfying one; the resolver
matches by type. **No prim path crosses an asset boundary in either
direction** — `examples/wheelset.iface.usda` names `Mount@2` and the role
`wheelHub`, and never names the chassis. The chassis team can rename or
restructure their internals freely.

```
$ jitsd bind
3 assets  ·  5 offered  ·  2 required

  aero rail        Mount@2  -> chassis/chassis/mounts/aeroRail
  wheelset hubs    Mount@2  -> chassis/chassis/mounts/hubFL, .../hubFR, .../hubRL, .../hubRR
```

### The envelope gate

`docs/03-versioning.md` claims compatibility is measured, not asserted. That is
now executable. An offer declares how far it may move before consumers care;
promotion compares a candidate against what is currently on the channel.

```
$ jitsd promote chassis v002 --to approved     # hub nudged 0.3 mm, envelope 0.5 mm
chassis v002 -> @approved: compatible
@approved -> chassis v002                       # consumers untouched, no re-work

$ jitsd promote chassis v003 --to approved     # hub moved 2.7 mm
REFUSED: chassis v003 -> @approved is a breaking change
  envelope   /chassis/mounts/hubFL: moved 0.0027, envelope allows 0.0005
             -- provider broke its own promise
```

Breaking: an offer removed, its contract major bumped, its envelope tightened,
or its frame moved beyond what it promised. Compatible: offers added, or an
offer moving inside its envelope.

Failure policy decides severity rather than being an exception path. With the
providers gone, `wheelset` (`required`) errors and `aero` (`substitutable`)
warns, from the same absence.

### What this deliberately does not do

Cardinality is `one` or `many`, and `one` with several candidates is reported
as ambiguous rather than guessed. Real disambiguation — four wheels, four hubs,
each bound individually — is an assembly-level concern that needs the query
document, which rung 1 does not have.

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
- **One file per asset payload.** The contract surface is authored separately
  and attached at save time; there is no prim-level structure inside the
  payload itself. No bounds evaluation, no context compilation.
- **`jitsd/usda.py` is a restricted parser, and temporary.** Contracts had to
  be authored in real USD — declaring an interface in JSON would prove nothing
  about whether the design fits USD — but rung 1 has no pxr. It handles prims,
  nested prims, applied API schemas and uniform attributes; no variants, no
  references, no composition of any kind. When pxr is available the file is
  deleted and `GetAppliedSchemas()` / `GetAttribute()` replace it outright.
- **`checkout` reassembles in memory** per chunk; fine at these sizes, wrong
  for a streaming client.

## Benchmark

```
python bench/dedup.py --size-mb 64 --saves 30
```

Measures three edit patterns, because they do not behave alike: a localised
rework, several scattered edits, and a global re-export that perturbs every
value.

Measured — 64 MiB asset, 30 saves, 0.5% of the asset edited per save:

| pattern | as separate files | on disk | dedup | vs. one copy |
|---|---|---|---|---|
| local | 1.9 GiB | 121.8 MiB | 15.8x | 1.90x |
| scattered | 1.9 GiB | 341.1 MiB | 5.6x | 5.33x |
| global | 1.9 GiB | 1.9 GiB | **1.0x** | **30.00x** |

Per additional save: 2.0 MiB local, 9.6 MiB scattered, 64.0 MiB global.

**The storage claim holds for localised editing and fails completely for
re-export.** Thirty versions of an asset costing 1.9x one copy is the claim in
`docs/06-storage.md`, and it is real. But the third row is not a contrived
worst case — it is what happens when an artist re-exports from a DCC instead of
saving incrementally, and a re-export routinely rewrites the whole file:
different vertex ordering, different float noise in the low bits, regenerated
metadata. Byte-level chunking cannot see through any of that.

The fix is not a better chunker. It is to **stop treating an asset as one
opaque file**: content-address per prim and per attribute array, so a re-export
that perturbs one mesh leaves every other mesh, material and texture reference
hashing identically. That makes the Merkle hierarchy in `docs/06-storage.md`
load-bearing for deduplication, not only for fast diffs — which is a stronger
reason to build it than the one the design docs give. Tracked as open question
9.
