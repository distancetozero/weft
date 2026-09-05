"""Build the node/edge graph the Weft Threads viewer panel draws, straight
from a composed USD stage.

Pure logic: only `pxr` (passed in as an already-open `stage`, never opened
here) plus the standard library. No Qt, no weft/pull machinery -- this is
importable and unit-testable without a display (see
tests/test_threadgraph.py), and is the sole source of truth the Qt panel
(extras/usdview/weftViewer/threadpanel.py) renders through QWebChannel.

The taxonomy of edges -- hierarchy ("usd:arc"), mount/carrier contracts,
finish and shading facets, and (when present) USD collections -- is no longer
hardcoded in the walk below. Each kind is a RelationshipKind object in
weft/relkinds.py's registry; build_graph is a thin driver that walks the
stage's root -> group -> placement structure once and lets each registered
kind contribute nodes and edges. Adding a kind is registering an object; the
driver does not change. See relkinds.py for how the interleaved emission order
(and thus byte-for-byte parity with the previous hand-written graph) is kept.

Every source each kind reads is optional: a stage without /root's
group/placement convention, or without a discoverable ALab root, or with no
collections, still returns a (possibly empty) graph rather than raising -- see
the panel's own guard-everything requirement.
"""

from __future__ import annotations

from typing import Dict, List, Optional

from .relkinds import (
    LENS_ORDER,
    Context,
    GraphBuilder,
    alab_root_from_stage,
    facets_from_interfaces,
)


def build_graph(stage, alab_root: Optional[str] = None, registry=None) -> Dict:
    """The live thread graph for `stage`: {"nodes": [...], "edges": [...],
    "kinds": [...]} in the exact shape the d3 viewer's template `DATA`
    constant expects (the viewer synthesizes the /root node and its group
    edges on load -- neither is emitted here).

    Each node: id, label, type (group/prop/furniture/finish/shading/
    collection), deg, and -- for prop/furniture nodes -- asset, group. Each
    edge: source, target, kind. `registry` overrides the default kind set (for
    tests / extensibility); it defaults to kinds.discover(stage) -- the
    built-in relkinds.REGISTRY plus any weft__kinds declared on the context
    layer, so a declared kind shows up as a lens automatically (and a stage
    with no declarations gets exactly the built-ins). Never raises on a
    stage that doesn't match ALab's convention or has no discoverable interface
    files -- it returns whatever it could build, down to an empty graph.
    """
    if registry is None:
        from .kinds import discover
        kinds = discover(stage)
    else:
        kinds = registry

    resolved_root = alab_root_from_stage(stage, alab_root)
    asset_finish, asset_shading = facets_from_interfaces(resolved_root)

    builder = GraphBuilder()

    root = stage.GetPrimAtPath("/root") if stage else None
    if not root or not root.IsValid():
        root = stage.GetPseudoRoot() if stage else None
    if root is None:
        return {"nodes": [], "edges": [], "kinds": []}

    # UsdPrimDefaultPredicate is "active && defined && loaded && !abstract"
    # (pxr/usd/usd/primFlags.h) -- GetChildren()'s own default. The panel's
    # whole point is showing the graph BEFORE anything is loaded ("open as
    # bounding boxes"), and on a stage opened with `--unloaded` a prim with no
    # local "def" opinion outside its own payload composes as
    # present-but-not-yet-loaded -- GetChildren() would skip it, quietly
    # shrinking the graph. Usd.PrimAllPrimsPredicate is NOT the fix: it drops
    # the active/defined/abstract terms too, pulling in inactive/abstract/
    # undefined placeholders and nearly tripling the node count. The right
    # predicate is the default MINUS the loaded requirement.
    from pxr import Usd
    predicate = Usd.PrimIsActive & Usd.PrimIsDefined & ~Usd.PrimIsAbstract

    ctx = Context(stage, builder, predicate, asset_finish, asset_shading)

    # One walk of the root -> group -> placement convention; each registered
    # kind contributes per group and per placement in registry order, so edges
    # interleave exactly as the old inline build_graph emitted them.
    for grp in root.GetFilteredChildren(predicate):
        for k in kinds:
            k.enter_group(ctx, grp)
        for pl in grp.GetFilteredChildren(predicate):
            suffix = pl.GetName().rsplit("_", 1)[-1]
            if not suffix.isdigit():
                continue
            for k in kinds:
                k.visit_placement(ctx, grp, pl)

    # Stage-global kinds (e.g. usd:collection) contribute after the walk.
    for k in kinds:
        k.populate(stage, ctx)

    deg: Dict[str, int] = {}
    for e in builder.edges:
        deg[e["source"]] = deg.get(e["source"], 0) + 1
        deg[e["target"]] = deg.get(e["target"], 0) + 1
    for node_id, node in builder.nodes.items():
        node["deg"] = deg.get(node_id, 0)

    # The lens selector's kind order: the preferred ranking first (those
    # actually present), then any other present kinds sorted after.
    present = {e["kind"] for e in builder.edges}
    kinds_list = [k for k in LENS_ORDER if k in present]
    kinds_list += sorted(present - set(LENS_ORDER))

    return {"nodes": list(builder.nodes.values()), "edges": builder.edges,
            "kinds": kinds_list}
