"""Find what a USD stage refers to that is no longer there.

USD can tell you what is in a scene. It cannot tell you what is missing.

An `over` at a path that no longer composes is *structurally identical* to a
legitimate sparse override authored ahead of its target -- which is why none of
USD's shipped validators catch one, and why they never will. The same silence
covers relationship targets that resolve to nothing, material bindings to
deactivated materials, and collection patterns that match zero prims.

This module reports those. On a stock stage it can say "this refers to nothing".
Given anchor names (see ANCHOR_KEY), it can say *why*: the target is gone, or the
target moved and here is where it went. That distinction is the whole argument
for carrying a name separate from the hierarchy.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict, Iterable, Iterator, List, Optional

from pxr import Sdf, Usd, UsdShade


# A stable name for a thing a scene refers to, carried in-band as prim custom
# data. Never an address -- nothing resolves it to fetch a prim on the hot path.
ANCHOR_KEY = "absent:id"

# Recorded by whoever authors an override: the anchor it was authored against.
# This is what turns "refers to nothing" into "dead" versus "moved".
AUTHORED_AGAINST_KEY = "absent:authoredAgainst"


DEAD = "dead"        # target absent, and its anchor is absent too
MOVED = "moved"      # target absent, but its anchor is elsewhere on the stage
UNKNOWN = "unknown"  # target absent, nothing recorded -- cannot tell why


@dataclass
class Finding:
    kind: str                        # what sort of absence
    path: str                        # where the dangling reference lives
    detail: str                      # what it points at
    verdict: str = UNKNOWN
    layer: str = ""                  # which layer authored it, when known
    moved_to: Optional[str] = None   # populated when verdict is MOVED

    def __str__(self) -> str:
        head = "%-22s %-7s %s" % (self.kind, self.verdict, self.path)
        if self.moved_to:
            return "%s\n    %s\n    anchor now at %s" % (head, self.detail, self.moved_to)
        return "%s\n    %s" % (head, self.detail)


@dataclass
class Report:
    findings: List[Finding] = field(default_factory=list)
    prims_scanned: int = 0
    specs_scanned: int = 0
    anchors_found: int = 0

    @property
    def dead(self) -> List[Finding]:
        return [f for f in self.findings if f.verdict == DEAD]

    @property
    def moved(self) -> List[Finding]:
        return [f for f in self.findings if f.verdict == MOVED]

    @property
    def unknown(self) -> List[Finding]:
        return [f for f in self.findings if f.verdict == UNKNOWN]


# -- anchors ---------------------------------------------------------------

def anchor_index(stage: Usd.Stage, key: str = ANCHOR_KEY) -> Dict[str, str]:
    """Map every anchor name on the stage to the path it currently sits at.

    This is the only thing anchor names are used for here: telling a target that
    vanished from a target that moved. They are never used to address anything.
    """
    index: Dict[str, str] = {}
    for prim in stage.TraverseAll():
        name = prim.GetCustomDataByKey(key)
        if name:
            index[str(name)] = str(prim.GetPath())
    return index


def _nested_get(data, key: str):
    """Read a colon-delimited key out of a raw customData dict.

    Usd.Prim.GetCustomDataByKey treats ':' as a nesting delimiter, so a key like
    "absent:id" lives at customData["absent"]["id"]. Sdf spec customData is a
    plain dict, so we have to walk it ourselves to match that behaviour.
    """
    cur = data
    for part in key.split(":"):
        if not hasattr(cur, "get"):
            return None
        cur = cur.get(part)
        if cur is None:
            return None
    return cur


def _adjudicate(recorded: Optional[str], anchors: Dict[str, str]) -> tuple:
    """Given the anchor an override recorded, decide dead / moved / unknown."""
    if not recorded:
        return UNKNOWN, None
    where = anchors.get(str(recorded))
    if where:
        return MOVED, where
    return DEAD, None


# -- spec walking ----------------------------------------------------------

def _walk_prim_specs(spec) -> Iterator:
    yield spec
    for child in spec.nameChildren:
        yield from _walk_prim_specs(child)


def _local_layers(stage: Usd.Stage) -> List[Sdf.Layer]:
    """The layers this pipeline authors into -- the root layer stack.

    Deliberately excludes referenced and payloaded layers: an `over` inside a
    published asset is that asset's business, not this stage's.
    """
    session = stage.GetSessionLayer()
    return [ly for ly in stage.GetLayerStack(includeSessionLayers=False) if ly != session]


# -- the checks ------------------------------------------------------------

def stale_overrides(stage: Usd.Stage, anchors: Dict[str, str], report: Report) -> None:
    """`over` specs whose composed prim is not defined by anything.

    The classic silent failure: the asset renamed Hat to Cap, the lighter's
    visibility override stayed behind, and it composes to nothing forever.
    """
    for layer in _local_layers(stage):
        for root in layer.rootPrims:
            for spec in _walk_prim_specs(root):
                report.specs_scanned += 1
                if spec.specifier != Sdf.SpecifierOver:
                    continue
                prim = stage.GetPrimAtPath(spec.path)
                if prim and prim.IsValid() and prim.IsDefined():
                    continue  # a legitimate sparse override -- says nothing
                recorded = _nested_get(spec.customData, AUTHORED_AGAINST_KEY)
                verdict, moved_to = _adjudicate(recorded, anchors)
                report.findings.append(Finding(
                    kind="stale-override",
                    path=str(spec.path),
                    detail="over composes to nothing; no prim is defined here",
                    verdict=verdict,
                    layer=layer.identifier,
                    moved_to=moved_to,
                ))


def overrides_under_instances(stage: Usd.Stage, report: Report) -> None:
    """`over` specs beneath an instanceable prim, which USD silently discards."""
    for layer in _local_layers(stage):
        for root in layer.rootPrims:
            for spec in _walk_prim_specs(root):
                if spec.specifier != Sdf.SpecifierOver:
                    continue
                prim = stage.GetPrimAtPath(spec.path)
                if not (prim and prim.IsValid()):
                    continue
                if not prim.IsInstanceProxy():
                    continue
                report.findings.append(Finding(
                    kind="override-in-instance",
                    path=str(spec.path),
                    detail="beneath an instanceable prim; this opinion is discarded",
                    verdict=DEAD,
                    layer=layer.identifier,
                ))


def dangling_targets(stage: Usd.Stage, anchors: Dict[str, str], report: Report) -> None:
    """Relationship targets that resolve to nothing, or to a deactivated prim."""
    for prim in stage.TraverseAll():
        report.prims_scanned += 1
        for rel in prim.GetRelationships():
            # material:binding gets a more specific check of its own.
            if rel.GetName().startswith("material:binding"):
                continue
            for target in rel.GetTargets():
                prim_path = target.GetPrimPath()
                tgt = stage.GetPrimAtPath(prim_path)

                if not (tgt and tgt.IsValid()):
                    recorded = prim.GetCustomDataByKey(AUTHORED_AGAINST_KEY)
                    verdict, moved_to = _adjudicate(recorded, anchors)
                    report.findings.append(Finding(
                        kind="dangling-target",
                        path="%s.%s" % (prim.GetPath(), rel.GetName()),
                        detail="targets %s, which does not exist" % target,
                        verdict=verdict,
                        moved_to=moved_to,
                    ))
                    continue

                if not tgt.IsActive():
                    report.findings.append(Finding(
                        kind="target-deactivated",
                        path="%s.%s" % (prim.GetPath(), rel.GetName()),
                        detail="targets %s, which is deactivated -- still resolves, "
                               "silently" % target,
                        verdict=DEAD,
                    ))
                elif not tgt.IsDefined():
                    report.findings.append(Finding(
                        kind="dangling-target",
                        path="%s.%s" % (prim.GetPath(), rel.GetName()),
                        detail="targets %s, which is override-only and never "
                               "defined" % target,
                        verdict=UNKNOWN,
                    ))


def stripped_targets(stage: Usd.Stage, report: Report) -> None:
    """Relationships whose targets were authored, then removed by composition.

    When a relationship target points outside the scope of the reference that
    brought it in, USD discards the target — the relationship survives with an
    empty target list. A mesh whose material binding is emptied this way renders
    unshaded.

    USD does warn at composition time, but that warning goes to a log during a
    scene open that prints hundreds of lines, and the stage is otherwise valid.
    This finds it after the fact, which is when anyone actually looks.
    """
    for prim in stage.TraverseAll():
        for rel in prim.GetRelationships():
            if rel.GetTargets():
                continue
            authored = []
            try:
                for spec in rel.GetPropertyStack(Usd.TimeCode.Default()):
                    items = spec.targetPathList
                    for slot in ("explicitItems", "prependedItems", "appendedItems",
                                 "addedItems"):
                        authored.extend(getattr(items, slot, ()) or ())
            except Exception:
                continue
            if not authored:
                continue  # a relationship that never had targets is not a finding
            report.findings.append(Finding(
                kind="targets-stripped",
                path="%s.%s" % (prim.GetPath(), rel.GetName()),
                detail="targets %s were authored, then dropped in composition — "
                       "out of scope of the reference that brought them in"
                       % ", ".join(str(a) for a in authored[:3]),
                verdict=DEAD,
            ))


def material_bindings(stage: Usd.Stage, report: Report) -> None:
    """Bindings to a material that is missing or deactivated.

    ComputeBoundMaterial() hands back a valid UsdShade.Material wrapping an
    inactive prim, so nothing downstream notices until a render looks wrong.
    """
    for prim in stage.Traverse():
        rel = UsdShade.MaterialBindingAPI(prim).GetDirectBindingRel()
        if not rel:
            continue
        for target in rel.GetTargets():
            mat = stage.GetPrimAtPath(target.GetPrimPath())
            if not (mat and mat.IsValid()):
                report.findings.append(Finding(
                    kind="binding-missing",
                    path=str(prim.GetPath()),
                    detail="bound to %s, which does not exist" % target,
                    verdict=DEAD,
                ))
            elif not mat.IsActive():
                report.findings.append(Finding(
                    kind="binding-deactivated",
                    path=str(prim.GetPath()),
                    detail="bound to %s, which is deactivated; ComputeBoundMaterial "
                           "still returns it" % target,
                    verdict=DEAD,
                ))


def empty_collections(stage: Usd.Stage, report: Report) -> None:
    """Collections that were authored with membership but now match nothing.

    Katana's CEL failure mode, in USD: after a restructure the pattern matches
    zero and nothing complains. Zero-match should be an error, not a no-op.
    """
    for prim in stage.TraverseAll():
        try:
            collections = Usd.CollectionAPI.GetAllCollections(prim)
        except Exception:
            return  # API not available in this USD build; skip the whole check
        for coll in collections:
            includes = coll.GetIncludesRel()
            authored = bool(includes and includes.GetTargets())
            expr_attr = coll.GetMembershipExpressionAttr()
            if not authored and not (expr_attr and expr_attr.HasAuthoredValue()):
                continue  # nothing was ever asked for; not a finding
            try:
                query = coll.ComputeMembershipQuery()
                included = Usd.CollectionAPI.ComputeIncludedPaths(query, stage)
            except Exception:
                continue
            if not included:
                report.findings.append(Finding(
                    kind="empty-collection",
                    path=str(coll.GetCollectionPath()),
                    detail="membership was authored but matches zero prims",
                    verdict=DEAD,
                ))


CHECKS = {
    "stale-override": stale_overrides,
    "override-in-instance": overrides_under_instances,
    "dangling-target": dangling_targets,
    "targets-stripped": stripped_targets,
    "material-binding": material_bindings,
    "empty-collection": empty_collections,
}


def scan(stage: Usd.Stage, anchor_key: str = ANCHOR_KEY) -> Report:
    """Run every check against a composed stage."""
    report = Report()
    anchors = anchor_index(stage, anchor_key)
    report.anchors_found = len(anchors)

    stale_overrides(stage, anchors, report)
    overrides_under_instances(stage, report)
    dangling_targets(stage, anchors, report)
    stripped_targets(stage, report)
    material_bindings(stage, report)
    empty_collections(stage, report)

    order = {DEAD: 0, MOVED: 1, UNKNOWN: 2}
    report.findings.sort(key=lambda f: (order.get(f.verdict, 3), f.kind, f.path))
    return report


def scan_file(path: str, anchor_key: str = ANCHOR_KEY) -> Report:
    stage = Usd.Stage.Open(path)
    if not stage:
        raise IOError("could not open stage: %s" % path)
    return scan(stage, anchor_key)
