"""Capture and verify drift receipts against a composed USD stage.

The first end-to-end proof of the drift-receipt model
(docs/superpowers/specs/2026-09-04-sidecar-identity-and-drift-receipts.md),
scoped per the build spec (2026-09-04-drift-verify-prototype.md) to Tier-A
asset identity + the `facet:finish` predicate.

Pure logic in the shape of weft/threadgraph.py: takes an already-open
`Usd.Stage` (never opened here), imports `pxr` lazily, and never raises on
missing data -- a prim without `assetInfo`, a stage without a discoverable
ALab root, a receipt member that no longer exists all degrade to honest
report entries, not exceptions. Nothing here writes to the stage: a receipt
is a sidecar JSON file (`.weft/receipts/<name>.weft`) recording, per member,
an identity signature (the *stable* half -- how to re-find the prim) and a
read fingerprint (the *drifting* half -- a hash of exactly the resolved
value the rule read). Keeping the two separate is the core rule: a reshaded
bottle must verify as "same bottle, drifted", never "a different bottle".

Completeness note (generalization, not v1): the fully-correct fingerprint
seed is the resolved value plus its `GetPropertyStack` footprint. v1 hashes
the resolved value only; the property-stack footprint is the documented
next step.
"""

from __future__ import annotations

import hashlib
import json
import os
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Dict, List, Optional, Tuple

from . import __version__
# These moved from threadgraph.py into relkinds.py (public names) when
# build_graph was refactored to the relationship-kind registry; aliased here
# to keep drift.py's internal call sites unchanged.
from .relkinds import (
    alab_root_from_stage as _alab_root_from_stage,
    facets_from_interfaces as _facets_from_interfaces,
)

# Model kinds that carry `assetInfo` without being placements themselves --
# ALab authors assetInfo:name on assembly roots too (e.g. /root of the
# workbench IS `lab_workbench01`), and treating those as members would fold
# a whole set into one leaf.
_CONTAINER_KINDS = ("assembly", "group")


# -- receipt / report shapes ----------------------------------------------

@dataclass
class Receipt:
    """One captured rule: members' identity signatures + read fingerprints."""
    name: str
    rule: Dict
    context: Dict
    provenance: Dict
    members: List[Dict]
    merkle_root: str
    weft_receipt: int = 1

    def to_dict(self) -> Dict:
        return {
            "weft_receipt": self.weft_receipt,
            "name": self.name,
            "rule": self.rule,
            "context": self.context,
            "provenance": self.provenance,
            "members": self.members,
            "merkle_root": self.merkle_root,
        }

    @classmethod
    def from_dict(cls, d: Dict) -> "Receipt":
        return cls(
            name=d.get("name", ""),
            rule=d.get("rule", {}),
            context=d.get("context", {}),
            provenance=d.get("provenance", {}),
            members=d.get("members", []),
            merkle_root=d.get("merkle_root", ""),
            weft_receipt=d.get("weft_receipt", 1),
        )


@dataclass
class DriftReport:
    """verify()'s honest findings, each tagged meaning-changing vs inert.

    `clean` is true iff nothing meaning-changing was found: `renamed` is
    inert by definition (same identity, same read), and `ambiguous` is a
    warning (a Tier-B limit, possibly just a reorg), not a failure."""
    clean: bool
    renamed: List[Dict] = field(default_factory=list)
    changed: List[Dict] = field(default_factory=list)
    departed: List[Dict] = field(default_factory=list)
    arrived: List[Dict] = field(default_factory=list)
    ambiguous: List[Dict] = field(default_factory=list)
    merkle_root_before: str = ""
    merkle_root_after: str = ""

    def summary(self) -> str:
        return ("%d renamed (inert) · %d changed · %d departed · %d arrived"
                % (len(self.renamed), len(self.changed),
                   len(self.departed), len(self.arrived)))


# -- fingerprint + merkle (the drift half) --------------------------------

def _canonical(obj) -> bytes:
    """Canonical JSON: sorted keys, no whitespace, UTF-8."""
    return json.dumps(obj, sort_keys=True, separators=(",", ":"),
                      ensure_ascii=False).encode("utf-8")


def _fp(read: Dict) -> str:
    """sha256 of the canonical read values -- and ONLY the read values.
    Path and provenance live in the signature, kept out of the seed by
    design so identity and drift never contaminate each other."""
    return hashlib.sha256(_canonical(read)).hexdigest()


def _merkle(leaf_hashes: List[str]) -> str:
    """Root of a binary tree over the sorted leaves: pair-hash upward,
    odd node promoted. One compare answers "did anything change"; v1
    stores and compares only the root (the report diffs member lists
    directly, so the log-n localization walk is deferred)."""
    level = sorted(leaf_hashes)
    if not level:
        return hashlib.sha256(b"").hexdigest()
    while len(level) > 1:
        nxt = []
        for i in range(0, len(level) - 1, 2):
            nxt.append(hashlib.sha256(
                (level[i] + level[i + 1]).encode("ascii")).hexdigest())
        if len(level) % 2:
            nxt.append(level[-1])
        level = nxt
    return level[0]


# -- placements + rule membership -----------------------------------------

def _hierarchy_predicate():
    # The default predicate minus the loaded requirement, for the same
    # reason threadgraph.build_graph uses it: an --unloaded stage must
    # yield the same member set as a loaded one.
    from pxr import Usd
    return Usd.PrimIsActive & Usd.PrimIsDefined & ~Usd.PrimIsAbstract


def _placement_asset_id(prim) -> Optional[str]:
    """The asset id a prim places, or None if it isn't a placement:
    `assetInfo:name` when authored (ALab authors it on every placement),
    else derived from the `<asset>_<NNNN>` naming convention -- the same
    fallback threadgraph uses. Container models (assembly/group kinds)
    are not placements even though they carry assetInfo."""
    from pxr import Usd
    ma = Usd.ModelAPI(prim)
    name = ma.GetAssetName()
    if name:
        return None if ma.GetKind() in _CONTAINER_KINDS else name
    parts = prim.GetName().rsplit("_", 1)
    if len(parts) == 2 and parts[1].isdigit():
        return parts[0]
    return None


def _placements(stage):
    """Yield (prim, asset_id) for every placement-level prim on the stage,
    pruning below each placement so an asset's internal prims are never
    mistaken for placements of their own. Empty on a None stage."""
    if stage is None:
        return
    from pxr import Usd
    it = iter(Usd.PrimRange.Stage(stage, _hierarchy_predicate()))
    for prim in it:
        asset_id = _placement_asset_id(prim)
        if asset_id:
            yield prim, asset_id
            it.PruneChildren()


def _members(stage, rule: Dict, alab_root: Optional[str]):
    """The facet rule's member prims + each member's read value, from the
    same source threadgraph reads finish from: the asset interface files
    (`entity/<asset>/interface/<asset>_interface.usda`, `weft:bind:finish`)
    under the ALab root derived from the stage. A prim is a member iff its
    asset's resolved finish equals the rule value; the read value recorded
    is that resolved finish string (asset-scoped -- all instances of an
    asset share it, which is why a finish change drifts a whole asset's
    instances together, matching Tier-A identity).

    Returns (members, finish_map, resolved_root) where members is a list of
    (prim, asset_id, read) tuples."""
    resolved_root = _alab_root_from_stage(stage, alab_root)
    finish, _shading = _facets_from_interfaces(resolved_root)
    value = rule.get("value")
    out = []
    if value is None:
        # A missing value must not match every asset that lacks a finish
        # entry (`.get()` yields None for those too).
        return out, finish, resolved_root
    for prim, asset_id in _placements(stage):
        if finish.get(asset_id) == value:
            out.append((prim, asset_id, {"finish": value}))
    return out, finish, resolved_root


# -- identity signature (the stable half) ---------------------------------

def _reference_target(prim, alab_root: Optional[str]) -> Optional[str]:
    """The reference-target asset path from the prim's composition arcs:
    the first `references` arc pointing at `entity/<name>/...`, normalized
    to be checkout-relative (`entity/<name>/<name>.usda`) so the same
    placement in two checkouts of the tree carries the same identity.
    None when the prim has no such arc (e.g. a prim defined inline)."""
    from pxr import Usd
    try:
        arcs = Usd.PrimCompositionQuery.GetDirectReferences(prim).GetCompositionArcs()
    except Exception:
        return None
    root = (alab_root or "").replace(os.sep, "/").rstrip("/")
    for arc in arcs:
        node = arc.GetTargetNode()
        layer = node.layerStack.identifier.rootLayer if node else None
        ident = (layer.identifier if layer else "").replace(os.sep, "/")
        if not ident:
            continue
        if root and ident.startswith(root + "/"):
            ident = ident[len(root) + 1:]
        else:
            i = ident.find("/entity/")
            if i >= 0:
                ident = ident[i + 1:]
        if ident.startswith("entity/"):
            return ident
    return None


def _where(prim, asset_id: str) -> Optional[List]:
    """The Tier-B instance discriminator: [nearest named ancestor group
    path, index among same-asset siblings under it] in composed child
    order. Recorded even at Tier A for disambiguation. None only when the
    prim has no parent to anchor to."""
    parent = prim.GetParent()
    if not parent or not parent.IsValid():
        return None
    index = 0
    for sib in parent.GetFilteredChildren(_hierarchy_predicate()):
        if _placement_asset_id(sib) != asset_id:
            continue
        if sib.GetPath() == prim.GetPath():
            break
        index += 1
    return [parent.GetPath().pathString, index]


def _signature(prim, asset_id: str, alab_root: Optional[str]) -> Dict:
    """The identity signature: how to re-find this prim, built from its
    stable half (reads only, never writes). Tiered by robustness: "C" when
    the data carries a real id, "A" on authored asset identity, "B" when
    only the structural locator exists, "path" as the last resort."""
    from pxr import Usd
    ma = Usd.ModelAPI(prim)
    asset = ma.GetAssetName() or None
    info = prim.GetAssetInfo() or {}
    entity_type = info.get("entityType") or None

    id_hint = None
    ident = ma.GetAssetIdentifier()
    if ident and ident.path:
        id_hint = ident.path
    else:
        custom = prim.GetCustomDataByKey("weft:id")
        if custom:
            id_hint = str(custom)

    where = _where(prim, asset_id)
    tier = ("C" if id_hint else
            "A" if asset else
            "B" if where else "path")
    return {
        "asset": asset,
        "asset_ref": _reference_target(prim, alab_root),
        "type": entity_type,
        "where": where,
        "path": prim.GetPath().pathString,
        "id_hint": id_hint,
        "tier": tier,
    }


# -- capture ---------------------------------------------------------------

def _check_rule(rule: Dict) -> None:
    if (not isinstance(rule, dict) or rule.get("kind") != "facet"
            or rule.get("facet") != "finish" or "value" not in rule):
        raise ValueError(
            'v1 supports only {"kind": "facet", "facet": "finish", '
            '"value": <finish>}, got %r' % (rule,))


def capture(stage, rule: Dict, *, name: str, alab_root: Optional[str] = None) -> Receipt:
    """Evaluate the rule against the stage and record a receipt: one entry
    per member with its identity signature, read value, and fingerprint,
    plus a Merkle root over the sorted fingerprints. Reads only."""
    _check_rule(rule)
    members, _finish, resolved_root = _members(stage, rule, alab_root)
    entries = []
    for prim, asset_id, read in members:
        entries.append({
            "signature": _signature(prim, asset_id, resolved_root),
            "read": read,
            "fingerprint": _fp(read),
        })
    entries.sort(key=lambda e: e["signature"]["path"])
    root_layer = stage.GetRootLayer() if stage else None
    return Receipt(
        name=name,
        rule=dict(rule),
        context={
            "root_layer": root_layer.identifier if root_layer else None,
            "time": None,
            "variants": {},
        },
        provenance={
            "created": datetime.now(timezone.utc).isoformat(),
            "tool": "weft",
            "tool_version": __version__,
        },
        members=entries,
        merkle_root=_merkle([e["fingerprint"] for e in entries]),
    )


def write_receipt(receipt: Receipt, path: str) -> None:
    """JSON, human-readable and diffable, to e.g. `.weft/receipts/<name>.weft`."""
    d = os.path.dirname(path)
    if d:
        os.makedirs(d, exist_ok=True)
    with open(path, "w") as fh:
        json.dump(receipt.to_dict(), fh, indent=2, sort_keys=True)
        fh.write("\n")


def read_receipt(path: str) -> Receipt:
    with open(path) as fh:
        return Receipt.from_dict(json.load(fh))


# -- verify ----------------------------------------------------------------

def _sig_key(sig: Dict) -> Tuple:
    """The candidate-gathering key: asset + reference target -- the
    rename-proof Tier-A core. Prims sharing it are instances of the same
    asset; `where`/path only disambiguate within the group."""
    return (sig.get("asset"), sig.get("asset_ref"))


def _pair(recorded: List[Dict], candidates: List[Dict]):
    """Pair recorded members with current candidates of the same asset.
    Strongest evidence first: exact path (untouched instance), then the
    structural `where` locator (a rename that kept its place), then a
    single leftover on each side (nothing else it could be). Whatever
    remains genuinely cannot be told apart -- the Tier-B limit."""
    pairs = []
    recs = list(recorded)
    cands = list(candidates)

    def take(match):
        nonlocal recs, cands
        matched = []
        for r in recs:
            for c in cands:
                if match(r, c):
                    matched.append((r, c))
                    cands.remove(c)
                    break
        taken = {id(p[0]) for p in matched}
        recs = [r for r in recs if id(r) not in taken]
        pairs.extend(matched)

    take(lambda r, c: r["signature"]["path"] == c["sig"]["path"])
    take(lambda r, c: r["signature"].get("where") is not None
         and r["signature"].get("where") == c["sig"].get("where"))
    if len(recs) == 1 and len(cands) == 1:
        pairs.append((recs[0], cands[0]))
        recs, cands = [], []
    return pairs, recs, cands


def verify(receipt: Receipt, stage, *, alab_root: Optional[str] = None) -> DriftReport:
    """Re-locate every recorded member by its signature (a fresh read of
    the current stage -- no database, no index), re-hash what the rule
    read, and re-run the rule to catch arrivals. Never raises on missing
    data: a member that cannot be re-found is a `departed` finding, one
    that cannot be told apart from a sibling is `ambiguous`."""
    members, finish, resolved_root = _members(stage, receipt.rule, alab_root)

    # Every placement on the stage is a re-location candidate -- membership
    # is NOT required, so an instance whose finish changed is found and
    # reported `changed`, not mistaken for `departed`.
    candidates = [{"prim": prim, "asset_id": asset_id,
                   "sig": _signature(prim, asset_id, resolved_root)}
                  for prim, asset_id in _placements(stage)]

    by_key: Dict[Tuple, List[Dict]] = {}
    for c in candidates:
        by_key.setdefault(_sig_key(c["sig"]), []).append(c)
    rec_by_key: Dict[Tuple, List[Dict]] = {}
    for m in receipt.members:
        rec_by_key.setdefault(_sig_key(m["signature"]), []).append(m)

    report = DriftReport(clean=True, merkle_root_before=receipt.merkle_root)
    paired_cand_ids = set()
    ambiguous_keys = set()

    for key, recs in rec_by_key.items():
        cands = by_key.get(key, [])
        pairs, leftover_recs, leftover_cands = _pair(recs, cands)
        for rec, cand in pairs:
            paired_cand_ids.add(id(cand))
            new_read = {"finish": finish.get(cand["asset_id"])}
            sig = rec["signature"]
            if _fp(new_read) != rec["fingerprint"]:
                report.changed.append({
                    "member": sig, "old": rec["read"], "new": new_read,
                    "tier": sig.get("tier"),
                })
            elif cand["sig"]["path"] != sig["path"]:
                report.renamed.append({
                    "member": sig, "old_path": sig["path"],
                    "new_path": cand["sig"]["path"], "tier": sig.get("tier"),
                })
        if leftover_recs and leftover_cands:
            # >1 unmatched on both sides: a reorg has defeated `where`.
            # Report honestly rather than asserting a pairing; their
            # candidates are accounted for here, not double-counted as
            # arrivals below.
            ambiguous_keys.add(key)
            for rec in leftover_recs:
                report.ambiguous.append({
                    "member": rec["signature"],
                    "candidates": [c["sig"]["path"] for c in leftover_cands],
                    "tier": rec["signature"].get("tier"),
                })
        else:
            for rec in leftover_recs:
                report.departed.append({
                    "member": rec["signature"],
                    "tier": rec["signature"].get("tier"),
                })

    # Arrivals: fresh rule members whose signature paired with no recorded
    # member (and whose asset group isn't already reported ambiguous).
    member_prim_paths = {prim.GetPath().pathString for prim, _a, _r in members}
    fresh_fps = []
    for c in candidates:
        if c["sig"]["path"] not in member_prim_paths:
            continue
        fresh_fps.append(_fp({"finish": finish.get(c["asset_id"])}))
        if id(c) in paired_cand_ids or _sig_key(c["sig"]) in ambiguous_keys:
            continue
        report.arrived.append({
            "signature": c["sig"],
            "read": {"finish": finish.get(c["asset_id"])},
        })

    report.merkle_root_after = _merkle(fresh_fps)
    report.clean = not (report.changed or report.departed or report.arrived)
    return report
