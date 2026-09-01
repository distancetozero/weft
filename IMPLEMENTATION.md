# Reference implementation

Solo, offline, no server. Per `docs/07-adoption.md`, nothing above rung 1 may
be required for rung 1 to be useful — so versioning works with no contracts
declared and no generator in sight, and each layer above is an upgrade.

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
| `declare <asset> --generator G` | an asset that is a **function**, not a file |
| `generators` | list registered generators and their parameter domains |
| `compile <query.usda>` | **compile a stage on demand** |

## Compiling on demand

This is the part that makes it just-in-time. A query document names generators,
parameters and a context — about a kilobyte of readable USD, and the only
durable artifact. It names no geometry, no file, and no positions.

```
$ jitsd compile examples/shot.usda --context review -o stage.usda
stage.usda  context review  baseline floating
  bindings   1
  bounds     (-1.87, -0.33, -0.903) .. (1.87, 1.41, 0.903)
  phase A       0.38 ms   relational -- parameters, contracts, bounds
  phase B       1.00 ms   materialise -- geometry
  digest     sha256:186d110a5835791d
```

### The contract surface is computed, not authored

`Chassis.offers()` derives its hub frames from `wheelbase` and `track`. So
changing one parameter moves the mount points, and the wheelset — which never
names the chassis and is never edited — follows:

```
wheelbase 2.84 -> wheel x: [1.42, 1.42, -1.42, -1.42]
wheelbase 3.30 -> wheel x: [1.65, 1.65, -1.65, -1.65]
```

That is the scenario the project opened with, executable.

### One query, five contexts

| context | meshes | points | phase B | note |
|---|---|---|---|---|
| hero | 5 | 520 | 1.41 ms | |
| review | 5 | 200 | 0.60 ms | |
| proxy | 5 | 104 | 0.44 ms | |
| engineering | **6** | 528 | 1.48 ms | includes the battery cell |
| collision | 5 | 72 | 0.32 ms | |

`engineering` is a **different derivation, not a coarser one** — the other four
never generate the internal cell at all. Each context yields a distinct digest,
and recompiling any of them is byte-identical.

### The two planes, measured

Phase A resolves parameters, contract surfaces, bindings and bounds without
touching geometry:

| chassis instances | phase A | phase B | ratio |
|---|---|---|---|
| 1 | 0.30 ms | 1.42 ms | 5x |
| 8 | 1.12 ms | 9.77 ms | 9x |
| 32 | 3.68 ms | 38.87 ms | 11x |
| 128 | 14.71 ms | 152.24 ms | 10x |
| 512 | 56.97 ms | 640.15 ms | 11x |

At 512 instances, phase A answers bindings and scene bounds in 57 ms without
producing any of the 16 MB of geometry phase B would. That is the operational
justification for the relational/geometric split, and what makes "what is in
this frustum" answerable before anything is generated.

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
- **Generators are Python callables, not sandboxed kernels.** `docs/02` calls
  for WASM: deterministic FP, sandboxed vendor code, portable. These are
  in-process and trusted.
- **Two toy generators.** `chassis` and `wheelset` exercise computed offers,
  bounds-without-geometry and context variation. They are boxes and cylinders,
  not a test of anything at production complexity.
- **Overrides and the baseline+overlay handoff are not built.** A query
  document pins parameters and a baseline; it cannot yet express
  "baseline 118 + chassis@wip", which `docs/03` makes the unit of handoff.
- **Contexts are five presets**, not the claim lattice of `docs/05`. No
  authorization tier, no redaction, no declassifying generators.
- **Stored payloads cannot be parameterised.** An asset is either a generator
  or a blob; compiling a query against a blob-backed asset fails loudly rather
  than silently ignoring the parameters.
- **The fallback parser is more lenient than USD.** `jitsd/usda.py` now uses
  `Sdf.Layer` when pxr is installed and its own parser when it is not — and
  the hand-rolled one accepts layers real USD rejects (a closing brace on the
  same line as a value, for one). A layer authored offline can therefore fail
  once pxr is present. `test_both_reader_backends_agree` locks the two together
  on everything in `examples/`, but leniency in one direction remains.
- **`checkout` reassembles in memory** per chunk; fine at these sizes, wrong
  for a streaming client.

## Validated against real USD

`pip install -e ".[dev]"` brings in `usd-core`. The suite then runs 74 tests
instead of 54; without pxr the extra ones skip and everything else still
passes, because rung 1 must run with nothing installed.

`tests/test_pxr.py` opens **everything jitsd writes** in real USD — revision
layers (both generator- and payload-backed), baseline layers, every authored
example and spec, and compiled stages in all five contexts — then checks each
mesh's face counts against its index list, and compares our cheap parametric
bounds against `UsdGeom.BBoxCache`.

Wiring it found five real syntax bugs that nothing else would have caught:

| | |
|---|---|
| `prepend payload` emitted in the prim **body** | it is prim metadata; belongs in the `( )` block. In `write_revision`, on the payload-backed path the demo never exercised |
| `over "World" ( … )` with **no `{ }` body** | in `write_baseline`, and in the spec draft |
| `uniform rel` | relationships cannot be uniform (`specs/jitsdContracts/schema.usda`) |
| the same payload bug in `specs/revision-layer.usda` | hand-written in the design phase, never validated |
| the same bodyless `over` in `specs/baseline-layer.usda` | likewise |

Three were in hand-written spec drafts that nothing consumed; **two were in
shipping code**, on paths the demos happened to miss. The design documents had
claimed for weeks that this "fits USD". It mostly did — but not exactly, and
only real USD could say which.

Compilation is unaffected by which backend is present: a stage compiled with
pxr absent has the same digest as one compiled with it installed, and opens
cleanly in USD.

## Slices (docs/10-slices.md, plan step 1)

`jitsd select` resolves a slice entirely in the relational plane and prints its
receipt. Nothing materialises.

```
$ jitsd select wheelset --pin "glass_building: reflects into the shot"
slice: wheelset  +needs  depth 4  ctx:review
coordinate: floating on @approved

members (3):
  chassis        v001  closure  needs Mount@2 <- wheelset       gen:heavy
  glass_building v001  pin      dana: reflects into the shot    3.0 MiB
  wheelset       v001  seed     wheelset                        gen:moderate

est. cost: 3.0 MiB stored payloads · 2 generators to run
bounds:    (-1.87, -0.33, -0.88) .. (1.87, 1.41, 0.88)
```

Seeds: name/glob, `provides:C@N`, `requires:C@N`, `role:R`, `author:A`,
`changed-since:BASELINE`, `box:x0,y0,z0,x1,y1,z1` (from declared bounds —
blob-backed assets honestly cannot answer spatially). Closure: `needs` on by
default following required edges; `substitutable`/`omittable` providers go to
the **boundary list**, pulled only with `--include-optional`; `feeds` opt-in.

Overlays are the algebra, not UI sugar: `--pin "asset: reason"` carries
attribution and participates in closure; `--omit` excludes an asset from
membership *and* from the closure graph, and the consequence is surfaced —
omitting the chassis under a wheelset prints
`wheelset requires Mount@2, but its provider chassis is omitted (dana: too
heavy)` and exits non-zero. Every member answers "why am I here".

`-o` emits the slice as an ordinary query document (the spec rides in
`customLayerData`), so `jitsd compile` materialises it unchanged and
`select --from` reloads it. Blob-backed members compile as **constants** — a
payload arc into the object store — which closed a real gap: compile
previously refused them, contradicting "constants are functions".

### Closure, priced

`bench/closure.py` builds a K-link chain (each link requires the next — the
worst closure shape: maximally deep, one edge per hop) and selects link 0:

| chain | select |
|---|---|
| 50 | 12 ms |
| 200 | 34 ms |
| 500 | 104 ms |
| 1000 | 188 ms |

The first implementation measured 1,474 ms at 1000 — quadratic, from the
resolver scanning the whole catalogue per requirement and the edge set being
built three times. Indexing offers by contract key and resolving once made it
linear. The receipt stays interactive at four-digit asset counts; beyond that
the resolution accessor from `06-storage.md` is the identified mechanism.

## Storage granularity — settled by measurement

`bench/granularity.py` tests the storage claims against **real USD** rather
than synthetic binary: 4000 meshes, 13.9 MiB of crate, 64 KiB chunks.

| perturbation | bytes new | fields new |
|---|---|---|
| re-serialise, no change | 0.0% | 0.0% |
| one mesh of 4000 edited | 0.1% | 0.0% |
| every prim reordered | 1.3% | 0.0% |
| float noise on every value | 100.0% | 69.0% |

**Recommendation: keep byte-level chunking; do not move to per-field hashing.**
Field-level wins in one case only — global value perturbation — and saves 31%
there. That does not justify layer decomposition, value canonicalisation, pack
files and a pxr dependency in the write path.

It corrected three earlier claims. Crate *is* deterministic within a version
and writer, so "no byte-stable output" was overstated. Byte chunking *does*
survive a re-export. And the alarming numbers that motivated the question —
"1.0x on re-export", then "88% for a one-mesh edit" — were both artifacts: the
first from perturbing every 512th byte of random binary, the second from
running 1 MiB chunks against a 710 KiB file, which is two chunks.

The real fix was the chunk size, not the strategy. Default moved from 1 MiB to
**64 KiB**:

| avg chunk | one-mesh edit | prim reorder | chunks per GiB |
|---|---|---|---|
| 16 KiB | 0.31% | 0.87% | 55,780 |
| 64 KiB | 0.31% | 2.53% | 13,205 |
| 1 MiB | 12.53% | 67.57% | 591 |

Effect on the original benchmark, per additional save: local **2.0 MiB →
205 KiB**, scattered **9.6 MiB → 596 KiB**.

A store now records its chunker parameters in `objects/config.json` and uses
those rather than the current defaults — different boundaries mean nothing new
deduplicates against anything already stored, and the failure is silent.

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
