"""Read every outgoing edge from a USD layer, without composing a stage.

No stock USD API reports what this does. `GetExternalReferences`,
`GetCompositionAssetDependencies`, `UsdUtils.ExtractExternalReferences` and
`UsdUtils.ComputeAllDependencies` all report *composition arcs only* — which
files a file needs. None of them sees a `material:binding`, a `skel:skeleton`,
an attribute connection, or a collection include, and none of them is
prim-scoped. A dependency walker built on them computes a closure that strands
materials.

So the walk is hand-rolled over Sdf specs. Two kinds of edge come out, and the
difference matters:

  asset edges      a file path, resolved relative to the layer. Self-contained.
  namespace edges  a prim path like </World/Looks/Steel>. Means nothing until
                   you know which layer *defines* that prim — which is why
                   graph.py builds a defines-index before resolving these.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field, asdict
from typing import Dict, Iterator, List, Optional, Tuple

from pxr import Sdf


# Edge kinds. The first is file-level and resolves immediately; the rest are
# namespace-level and need the defines-index.
ARC = "arc"                # sublayer / reference / payload
ASSET_ATTR = "assetAttr"   # an asset-valued attribute, e.g. inputs:file
REL = "rel"                # relationship target: bindings, skel, proxyPrim, physics
CONN = "conn"              # attribute connection: shader networks
INHERIT = "inherit"        # inherits / specializes: class arcs, often invisible
COLLECTION = "collection"  # collection includes/excludes


@dataclass
class Edge:
    kind: str
    src_prim: str              # where in this layer the edge is authored
    name: str                  # property name, or "" for arcs
    target: str                # asset path (ARC/ASSET_ATTR) or prim path
    resolved: Optional[str] = None   # filled in by graph.py for namespace edges

    @property
    def is_asset_edge(self) -> bool:
        return self.kind in (ARC, ASSET_ATTR)


@dataclass
class LayerRecord:
    """Everything one layer contributes to the graph."""
    identifier: str
    defines: List[str] = field(default_factory=list)   # prim paths defined here
    edges: List[Edge] = field(default_factory=list)
    mtime: float = 0.0
    size: int = 0
    n_specs: int = 0

    def to_dict(self) -> Dict:
        d = asdict(self)
        d["edges"] = [asdict(e) for e in self.edges]
        return d

    @classmethod
    def from_dict(cls, d: Dict) -> "LayerRecord":
        edges = [Edge(**e) for e in d.pop("edges", [])]
        return cls(edges=edges, **d)


def _stat(identifier: str) -> Tuple[float, int]:
    """(mtime, size), or (0, 0) for anything not on a local filesystem."""
    try:
        st = os.stat(identifier)
        return st.st_mtime, st.st_size
    except OSError:
        return 0.0, 0


def _iter_prim_specs(spec) -> Iterator:
    """Depth-first over prim specs, including variants.

    Variant contents are real prim specs holding real edges. A walk that skips
    them under-reports dependencies, which is the error that strands things.
    """
    yield spec
    for child in spec.nameChildren:
        yield from _iter_prim_specs(child)
    for vset in spec.variantSets:
        for variant in vset.variants:
            yield from _iter_prim_specs(variant.primSpec)


def _list_op_items(list_op) -> List:
    """Every item in an Sdf list op, whichever slot it was authored into."""
    if list_op is None:
        return []
    out = []
    for attr in ("explicitItems", "prependedItems", "appendedItems", "addedItems",
                 "orderedItems"):
        out.extend(getattr(list_op, attr, ()) or ())
    return out


def walk_layer(layer: Sdf.Layer) -> LayerRecord:
    """Every edge this layer authors, and every prim path it defines."""
    mtime, size = _stat(layer.realPath or layer.identifier)
    rec = LayerRecord(identifier=layer.identifier, mtime=mtime, size=size)

    # Composition arcs, file-level. This much a stock API would give you.
    for dep in layer.GetCompositionAssetDependencies():
        rec.edges.append(Edge(ARC, "/", "", str(dep)))

    for root in layer.rootPrims:
        for spec in _iter_prim_specs(root):
            rec.n_specs += 1
            path = str(spec.path)

            # A prim is "defined" here only if this layer declares it -- `def`
            # or `class`. An `over` contributes opinions but is not the home of
            # a prim, and indexing overrides as definitions would make every
            # shot layer look like the owner of everything it tweaks.
            if spec.specifier in (Sdf.SpecifierDef, Sdf.SpecifierClass):
                rec.defines.append(path)

            # Per-prim reference and payload arcs, which the layer-level call
            # above reports without saying where they were authored.
            for ref in _list_op_items(spec.referenceList):
                if ref.assetPath:
                    rec.edges.append(Edge(ARC, path, "references", ref.assetPath))
            for pay in _list_op_items(spec.payloadList):
                if pay.assetPath:
                    rec.edges.append(Edge(ARC, path, "payload", pay.assetPath))

            # Class arcs. These fail the most invisibly of anything in USD --
            # an inherit to a missing class contributes nothing, with no
            # diagnostic whatsoever.
            for inh in _list_op_items(spec.inheritPathList):
                rec.edges.append(Edge(INHERIT, path, "inherits", str(inh)))
            for spc in _list_op_items(spec.specializesList):
                rec.edges.append(Edge(INHERIT, path, "specializes", str(spc)))

            for rel in spec.relationships:
                kind = COLLECTION if rel.name.startswith("collection:") else REL
                for target in _list_op_items(rel.targetPathList):
                    rec.edges.append(
                        Edge(kind, path, rel.name, str(target.GetPrimPath())))

            for attr in spec.attributes:
                for conn in _list_op_items(attr.connectionPathList):
                    rec.edges.append(
                        Edge(CONN, path, attr.name, str(conn.GetPrimPath())))
                # Asset-valued attributes: textures, volume files, sub-assets.
                if attr.typeName == Sdf.ValueTypeNames.Asset and attr.default:
                    p = getattr(attr.default, "path", None)
                    if p:
                        rec.edges.append(Edge(ASSET_ATTR, path, attr.name, str(p)))
                elif attr.typeName == Sdf.ValueTypeNames.AssetArray and attr.default:
                    for item in attr.default:
                        p = getattr(item, "path", None)
                        if p:
                            rec.edges.append(Edge(ASSET_ATTR, path, attr.name, str(p)))

    return rec


def walk_file(path: str) -> Optional[LayerRecord]:
    layer = Sdf.Layer.FindOrOpen(path)
    if not layer:
        return None
    return walk_layer(layer)
