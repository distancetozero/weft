# Drift verify prototype — build spec

**Status:** draft for owner review, 2026-09-04. The first end-to-end proof of the
drift-receipt model (`2026-09-04-sidecar-identity-and-drift-receipts.md`),
scoped to **Tier-A asset identity + the `facet:finish` predicate**. Pure
Python + `pxr`, Qt-free, sidecar-only. If this loop is airtight, the tiers and
predicates generalize.

**Goal:** `capture` a receipt for a facet rule into `.weft/receipts/`, and
`verify` it against a (possibly changed) stage, producing an honest drift report
— rename ⇒ "renamed, not drifted"; a finish change ⇒ "that asset departed,
meaning-changing"; an unrelated edit ⇒ no drift. Nothing written to the stage.

## Module

`weft/drift.py` (new), following the shape of `weft/threadgraph.py`: takes an
already-open `Usd.Stage`, imports `pxr` lazily, never raises on missing data.

### Public API

```python
def capture(stage, rule: dict, *, name: str, alab_root=None) -> Receipt
def verify(receipt: Receipt, stage, *, alab_root=None) -> DriftReport
def write_receipt(receipt: Receipt, path: str) -> None      # JSON to .weft/receipts/<name>.weft
def read_receipt(path: str) -> Receipt

rule = {"kind": "facet", "facet": "finish", "value": "translucent"}   # v1: this shape only
```

## Receipt file (JSON, human-readable, diffable) — `.weft/receipts/<name>.weft`

```json
{
  "weft_receipt": 1,
  "name": "translucent-set",
  "rule": {"kind": "facet", "facet": "finish", "value": "translucent"},
  "context": {"root_layer": "<stage root layer identifier>", "time": null, "variants": {}},
  "provenance": {"created": "<iso8601 UTC>", "tool": "weft", "tool_version": "<ver>"},
  "members": [
    {
      "signature": {
        "asset": "decor_bottle_cap01",
        "asset_ref": "entity/decor_bottle_cap01/decor_bottle_cap01.usda",
        "type": "setpiece",
        "where": ["/root/floor_dressing01", 0],
        "path": "/root/floor_dressing01/decor_bottle_cap01_0002",
        "id_hint": null,
        "tier": "A"
      },
      "read": {"finish": "translucent"},
      "fingerprint": "<sha256 of the canonical read, see §4>"
    }
  ],
  "merkle_root": "<sha256, see §5>"
}
```

## 1. Identity signature (Tier A, from ALab's `assetInfo`)

`_signature(prim, stage) -> dict` reads (never writes):
- `asset` = `Usd.ModelAPI(prim).GetAssetName()` (ALab authors this on every placement).
- `asset_ref` = the reference target asset path from the prim's composition arcs
  (first `references` arc pointing at `entity/<name>/…`); `None` if absent.
- `type` = `assetInfo:entityType` (e.g. `setpiece`).
- `where` = `[nearest named ancestor group path, index among same-asset siblings
  under it]` — the Tier-B instance discriminator, recorded even at Tier A for
  disambiguation.
- `path` = current prim path (provenance + last-resort locator; NOT identity).
- `id_hint` = `assetInfo:identifier` if non-empty, else a `weft:id` customData if
  present, else `None`.
- `tier` = `"C"` if `id_hint`, else `"A"` if `asset` present, else `"B"` if only
  `where`, else `"path"` (last resort).

## 2. Rule evaluation (facet)

`_members(stage, rule, alab_root)` returns the set of member prims + each
member's **read value**. Reuse the finish/shading source `weft/threadgraph.py`
already uses (the asset interface file `entity/<asset>/interface/
<asset>_interface.usda`, `weft:bind:finish`): a prim is a member iff its asset's
resolved `weft:bind:finish` equals `rule["value"]`. The **read value** recorded
per member is that resolved finish string (asset-scoped — all instances of an
asset share it, which is why a finish change drifts a whole asset's instances
together, matching Tier-A identity).

> Completeness note (generalization, not v1): the fully-correct fingerprint seed
> is the resolved value plus its `GetPropertyStack` footprint. v1 hashes the
> resolved value only; the property-stack footprint is the documented next step.

## 3. capture

1. `members, reads = _members(stage, rule)`.
2. For each member prim: `signature = _signature(prim, stage)`,
   `read = {"finish": reads[prim]}`, `fingerprint = _fp(read)` (§4).
3. `merkle_root = _merkle(sorted fingerprints)` (§5).
4. Assemble Receipt with rule/context/provenance; `write_receipt` to
   `.weft/receipts/<name>.weft`.

## 4. Fingerprint (the drift half)

`_fp(read) = sha256(canonical_json(read))` — canonical = sorted keys, no
whitespace, UTF-8. The seed is the **resolved read value(s)**, nothing else
(not the path, not provenance — those live in the signature, separate by
design so identity and drift never contaminate each other).

## 5. Merkle root

`_merkle(leaf_hashes)`: sort leaves, pair-hash up a binary tree
(`sha256(a+b)`, odd node promoted), return the root. Prototype uses it for the
one-compare "did anything change" gate; localization-by-tree-walk is available
but the report (§6) also diffs member lists directly, so v1 need not implement
the `log n` walk — just store and compare the root, and diff members for detail.

## 6. verify → DriftReport

`verify(receipt, stage)`:
1. **Re-locate** each recorded member by its signature (§ identity spec, no
   index): candidates = prims whose `asset`+`asset_ref` match; disambiguate by
   `where`. Result per member: `matched(prim, path_changed?)`, `departed`, or
   `ambiguous`.
2. For each `matched`: re-read finish, `_fp`, compare to recorded fingerprint.
3. **Re-run the rule** fresh (`_members`) to find `arrived` (prims now matching
   whose signature is in no recorded member).
4. Classify every finding:

```
DriftReport = {
  clean: bool,                       # true iff no meaning-changing findings
  renamed:  [{member, old_path, new_path, tier}],     # matched, path changed, fingerprint SAME  -> INERT
  changed:  [{member, old, new, tier}],               # matched, fingerprint differs             -> MEANING-CHANGING (departs set)
  departed: [{member, tier}],                         # not found                                -> MEANING-CHANGING
  arrived:  [{signature, read}],                      # newly matches                            -> MEANING-CHANGING
  ambiguous:[{member, candidates, tier}],             # Tier-B could not disambiguate            -> reported, not asserted
  merkle_root_before, merkle_root_after
}
```

`clean` ignores `renamed` (inert) and treats `ambiguous` as a warning, not a
failure — honest, not alarmist.

## 7. CLI

Extend `weft/cli.py`:
- `weft drift capture <stage.usd> --finish <value> --name <name>` → writes
  `.weft/receipts/<name>.weft`, prints member count + merkle root.
- `weft drift verify <receipt.weft> <stage.usd>` → prints the DriftReport
  (human summary: `N renamed (inert) · M changed · K departed · J arrived`),
  exit 0 if `clean`, non-zero if meaning-changing drift (so it can gate CI).

## 8. Tests — `tests/test_drift.py` (pxr-gated)

Synthetic stage: 2 assets (`assetInfo` authored) under a group, one bound
`finish=translucent`, one `matte`; ≥2 instances of the translucent asset.

1. **capture** → receipt has the right members, Tier A signatures, a stable
   merkle root; `read_receipt(write_receipt(r)) == r`.
2. **no-op verify** (same stage) → `clean`, empty findings.
3. **rename an instance** (move the prim, keep asset) → `renamed` (inert),
   `clean` stays true, fingerprint unchanged.
4. **change the asset's finish** in an override layer (translucent→matte) →
   `changed`/`departed` for that asset's instances, meaning-changing, `clean`
   false.
5. **add a new translucent instance** → `arrived`, meaning-changing.
6. **edit an unrelated attribute** (a matte asset's color) → `clean`, no
   findings (proves precision: reading only what the rule read).
7. **ambiguous**: two same-asset instances, delete the `where` disambiguator
   condition → `ambiguous` reported, not a crash, not a false `changed`.
8. **WEFT_ALAB acceptance** (gated): capture `finish=translucent` on the real
   workbench; verify against the unchanged stage → `clean`; verify against a
   copy with one interface finish flipped → exactly that asset's members
   `changed`.

## 9. Out of scope (later)

Predicates beyond `facet:finish` (path/name/mount/spatial); the property-stack
footprint (§2 note); Merkle `log n` localization; hash-chained receipt history;
signatures; the compose-panel "verify this expression" UI. v1 proves the loop;
these generalize it.
