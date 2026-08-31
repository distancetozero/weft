# Storage and on-disk layout

Three stores. That is the whole system.

## 1. Object store — the big data

Immutable, content-addressed, write-once, never edited or deleted. Deduped
across every version of everything. A Nix store or a git object store,
deliberately.

```
/jitsd/objects/
  sha256/8f/2c/8f2c9a1b….usdc      # geometry payload      (GB)
  sha256/d4/07/d407fe22….exr       # texture               (MB)
  sha256/aa/12/aa12cc90….wasm      # a generator kernel    (MB)
```

## 2. Ledger — the small data

Append-only, human-meaningful, all text, all diffable.

```
/jitsd/ledger/
  assets/hero_car/
    revisions/
      v036.usda        ← a real USD layer, ~3 KB
      v037.usda
      v038.usda
    channels/
      wip       → v038
      review    → v037
      approved  → v036
  baselines/
    000118.usda        ← "client_review" — pins every asset to a revision
    000119.usda
  log/
    2026-08-31.jsonl   ← who moved what, when, why
```

## 3. Workspace — per person, disposable

```
~/work/seq040_sh0120/
  shot.usda            ← what the artist edits.  ~20 KB.  In Perforce/git.
  jitsd.lock           ← auto-written: "resolved against baseline 118"
  .jitsd/cache/        ← hardlinks into the object store. Delete anytime.
```

**The only irreplaceable bytes are the small ones.** Deleting the cache costs a
re-download, never work.

## The thing that resolves the confusion

**A revision is a recipe, not the geometry.** `v037.usda` is about three
kilobytes — a real USD layer, openable in usdview right now, containing prim
definitions, contract declarations, parameters, and payloads pointing at
object-store hashes. The four gigabytes of geometry live once, in the object
store, shared by every version that did not change them.

## The mapping

| Concept | Where it lives | What people say | Size |
|---|---|---|---|
| **Revision** | `assets/hero_car/revisions/v037.usda` | "car v37" | KB |
| **Channel** | `assets/hero_car/channels/approved` | "the approved car" | bytes |
| **Baseline** | `baselines/000118.usda` | "the client review" | KB |
| **Shot / assembly** | `shots/sh0120/shot.usda` | "the shot" | KB |
| **Lock** | `shots/sh0120/jitsd.lock` | *never mentioned* | KB |
| **Blob** | `objects/sha256/8f/2c/…` | *never mentioned* | GB |
| **What is on screen** | local cache, disposable | "what I'm looking at" | GB |

The bottom two rows are the machine's business. The top four are what humans
touch, and all four are small text files.

## What happens on save

1. Serialise to `.usdc`, hash it → `sha256:3a91bd…`
2. Already in the object store? Nothing is written. Otherwise upload once.
3. Write a new revision layer `v039.usda` (3 KB) pointing at that hash.
4. Move the `wip` channel pointer.

Steps 3 and 4 are the only mutations. **Step 4 is the only thing in the entire
system that overwrites anything.**

## Merkle the hierarchy

Hash every node in the namespace hierarchy so a node's hash includes its
children's — a Merkle tree, as git hashes trees and IPFS hashes DAGs.

- **Subtree equality is one hash comparison.** `/Plant/Line_04` unchanged
  between two baselines? One comparison, not 40,000 prim visits.
- **Diff cost is O(changes), not O(scene size).** Exactly why `git status` is
  instant on a huge repo.
- **Dedup falls out.** Two identical city blocks share a subtree hash and store
  once.
- **A baseline is a root hash.**

This is a **core structural decision, not an optimisation**: the kilobyte-scale
"has anything drifted since sign-off" check only works if it is in place, and
it constrains what the manifest format must be.

The same hashing applies to the spatial hierarchy (`04-contracts.md`), so an
unchanged spatial subtree is also one comparison.

## Lessons taken from OpenVDB

**Tiles — constant-value collapse.** An internal node holds a single constant
instead of a child pointer, so a uniform region costs one entry regardless of
extent. Applied here: **baselines and manifests are sparse with tile
collapse.** An entire namespace subtree becomes one entry — "everything under
`/Plant/Line_04` is at baseline 118 defaults." Same for context compilation and
overlays.

**Topology separated from values.** VDB does union/intersection/difference on
tree structure without touching a voxel. Independent justification for the
two-plane split:

> **A baseline diff is a topological operation, not a value comparison.**

**Value accessors.** VDB caches the root-to-leaf path so coherent lookups skip
re-traversal. The equivalent is a **resolution accessor** caching the
derivation path for a subtree — a lighter working on one character re-resolves
nothing frame to frame. A real answer to per-request graph-resolution latency,
and a problem USD itself has with prim index and value resolution walks.

**Delayed leaf loading.** `.vdb` loads topology first and leaf buffers on
demand — the manifest/payload split, arrived at independently.

**NanoVDB is the strongest signal.** OpenVDB is a mutable pointer tree for
authoring; NanoVDB is flattened, pointer-free, read-only, for GPU consumption.

| System | Authoring representation | Consumption representation |
|---|---|---|
| OpenVDB | mutable pointer tree | NanoVDB |
| USD | `UsdStage` + composition | Fabric |
| JIT-SD | derivation + baseline | materialised payload |

Three independent teams converged on the same split: **authoring structure and
consumption structure should be different data structures, and the compile
between them is where the value is.**

**Where to stop.** Do not build a voxel structure for versioning. Content
addressing already gives dedup; implementing VDB-style tiles *and* Merkle
hashing on the same data does the job twice. Take the Merkle version — it
generalises further and gives the diff for free.

## Garbage collection

Anything reachable from a baseline carrying an approval is kept permanently.
Unreferenced WIP blobs are collected after a window. Same policy as Nix or git
GC, and cheap because reachability is walking baselines.

## Delivery to outside parties

Export a baseline as a self-contained bundle — the manifest plus every
reachable blob, packed. USDZ-style delivery for a vendor, a client, or a drive
someone physically mails. A pinned baseline, flattened.

## What is in version control

Only `shot.usda` and the revision layers — small text, diffable, reviewable.
The object store is infrastructure, not a repository.
