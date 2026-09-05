# Sidecar identity signatures + drift receipts

**Status:** design draft for owner review, 2026-09-04. Grounded in what the ALab
workbench actually carries (measured, not assumed). Nothing in this design
writes to the composed stage — everything lives in weft's `.weft/` sidecar.

## Principle

weft **reads** the stage and records its findings **on the side**. A drift
receipt is a small, recomputable file — never a database, never a layer others
must carry. The USD files are the only source of truth; the receipt is a cache
you re-check against them.

Two things are recorded per certified prim, and they must stay **separate**:
- **Identity signature** — a rename-robust "how to re-find this prim." Built
  from the *stable* half of the prim.
- **Read fingerprints** — hashes of exactly the resolved values the rule read
  (the *drifting* half). See §4.

Splitting them is the core rule: a reshaded bottle must read as "same bottle,
drifted," never "a different bottle."

## 1. What ALab actually carries (measured 2026-09-04)

Every placement is a USD `component` model with authored `assetInfo`:
- `assetInfo:name` = e.g. `"decor_bottle_cap01"` (the asset's real name) — present
  on every placement.
- `assetInfo:entityType` = e.g. `"setpiece"`.
- a reference to the asset file: `entity/<name>/<name>.usda`.
- `assetInfo:identifier` is **empty** (`@@`); `assetInfo:version` is blank.
- No per-instance unique id. Three `tool_screw01` instances
  (`_0008/_0009/_0010`) share identical `assetInfo` and differ **only** by prim
  name — i.e. by the path a rename would change.

Consequence: **asset-level identity is free and rename-proof; instance-level
identity is not present** and must be reconstructed best-effort.

## 2. The identity signature

A tuple, computed by reading the stage, stored in the sidecar. Tiered by
robustness — use the strongest tier the prim supports:

```
signature = {
  asset:    assetInfo:name + reference-target(asset file)   # rename-proof, ALab has it
  type:     assetInfo:entityType                            # coarse class
  # instance discriminator, only when the receipt is instance-scoped:
  where:    structural locator — (nearest named ancestor group,
            index among same-asset siblings under that group)
  path:     the prim path AT CAPTURE TIME                   # provenance + last-resort
  idHint:   assetInfo:identifier | a stable customData id, IF ever present  # future-proof
}
```

- **`asset` + `type`** answer "what asset is this" and survive any rename of the
  placement — the robust core, free from ALab's `assetInfo`.
- **`where`** is the instance discriminator: which group it sits under and its
  order among same-asset siblings. More robust than the raw name, not
  bulletproof (a reorganization can shuffle it).
- **`path`** is recorded for provenance and as the last-resort locator when
  nothing better exists; it is *not* the identity, just a hint.
- **`idHint`** is a hook: if a pipeline ever authors a real id
  (`assetInfo:identifier`, a `weft:id` customData), the signature upgrades to
  use it automatically and renames become perfectly robust — with zero change
  to this design.

### Robustness tiers (what a receipt honestly claims)

- **Tier A — asset-scoped** (`asset`+`type`): rename-proof. Covers "everything
  translucent", "everything decor", "this asset's shading". **Most rules.**
- **Tier B — instance-scoped** (`asset`+`where`): best-effort. Survives a
  rename; may be confused by a structural reorg. Flagged as best-effort in the
  receipt.
- **Tier C — id-scoped** (`idHint`): perfectly robust, available only when the
  data carries an id. Not present in ALab today; supported for when it is.

The receipt records **which tier** each member's identity rests on, so drift
reports can say "this departure is certain (Tier A)" vs "possibly a reorg, not a
real change (Tier B)."

## 3. Re-finding a prim on verify (no stage writes, no index)

`verify` re-opens the stage and, for each recorded signature, **re-locates** the
prim:
1. Tier C: look up the id. Tier A/B: gather candidate prims by
   `assetInfo:name` + reference-target (a cheap traversal, or the deps graph),
   then disambiguate by `where`.
2. Found exactly one → matched (note if the path changed → "renamed, not
   drifted").
3. Found none → **departed** (deleted, or its asset identity changed).
4. Found >1 and `where` can't disambiguate → **ambiguous** (report honestly;
   Tier B limit).

No database is consulted — re-location is a fresh read of the current stage.

## 4. The read fingerprints (the drift half)

Separately, per member, the receipt stores hashes of the **resolved values the
rule actually read** (§ "what's the seed": the composed value, not the raw
spec, not the whole opinion stack):
- facet rule → hash of the resolved `weft:bind:finish/shading` value.
- path/name rule → the fact of existence + the matched name/path.
- mount rule → the resolved carrier-target list.
- (spatial rule, later) → the resolved extent/bbox.

`verify` = re-locate by signature (§3) + re-hash the read values + **re-run the
rule** to catch arrivals. Output: `departed / arrived / changed / renamed`, each
tagged meaning-changing vs inert, and each carrying its identity tier so the
reader knows how much to trust it.

## 5. Digest structure (Merkle, so drift localizes)

Don't store one flat hash of everything. Build a **Merkle tree over the member
fingerprints**: leaves = per-member read-fingerprints, internal nodes = hashes
of children, root = the receipt's one digest.
- The root answers "did anything change" in one compare.
- A mismatch walks the tree in `log n` to the exact changed members — no full
  re-scan.
- Subtrees are shareable/dedupable across receipts of overlapping sets.

This is the principled version of the earlier "tiered digest": a Merkle DAG, the
same structure git uses for versioned content.

## 6. What lives in `.weft/`

```
.weft/receipts/<name>.weft   # one receipt: rule + context + tolerances,
                             # member signatures (with tier), read-fingerprints,
                             # Merkle root, provenance (when/stage/who)
```

A plain, human-readable, diffable file. Committable, shippable, reviewable in a
PR. Nothing is written into the assets or the composed stage.

## 7. Honest limits

- **Instance identity is best-effort** without an authored id; a structural
  reorg can confuse Tier B. weft says so rather than pretending.
- **Footprint completeness** (§4) is the correctness risk carried over from the
  drift design: under-recording what a rule read yields a silent false
  "no drift." The tricky arcs (inherits/specializes, variant selection,
  rel-targets, clips, time samples) need dedicated tests.
- **Time/variant context**: a fingerprint is valid only for the time + variant
  selection it was captured under; the receipt records that context.

## 8. First proof (scope)

Prototype end-to-end on **Tier-A asset identity + the facet predicate**:
capture signatures + read-fingerprints for `finish=translucent` into a
`.weft/receipts/*.weft`, then (a) rename an instance → verify reports "renamed,
not drifted"; (b) change one asset's finish in a sublayer → verify reports
exactly that member departed, meaning-changing; (c) edit something unrelated →
no drift. If that loop is airtight, the tiers and predicates generalize.
