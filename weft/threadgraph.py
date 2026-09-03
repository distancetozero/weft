"""Build the node/edge graph the Weft Threads viewer panel draws, straight
from a composed USD stage.

Pure logic: only `pxr` (passed in as an already-open `stage`, never opened
here) plus the standard library. No Qt, no weft/pull machinery -- this is
importable and unit-testable without a display (see
tests/test_threadgraph.py), and is the sole source of truth the Qt panel
(extras/usdview/weftViewer/threadpanel.py) renders through QWebChannel.

Reuses the exact taxonomy proven against the real ALab tree in the
scratchpad's threadgraph4.py spike: hierarchy edges (kind "usd:arc") from
/root's group -> placement structure, Mount/carrier contract edges read off
each placement's own `weft:offer:contract` / `weft:offer:carrier`, and
finish/shading facet nodes read from each asset's own interface file
(`entity/<asset>/interface/<asset>_interface.usda`) -- located relative to
the stage's own root layer, not hardcoded, so this works against any ALab
checkout. Every one of those sources is optional: a stage without /root's
group/placement convention, or without a discoverable ALab root, still
returns a (possibly empty) graph rather than raising -- see the panel's own
guard-everything requirement.
"""

from __future__ import annotations

import glob
import os
import re
from typing import Dict, List, Optional, Tuple

# The interface file's own textual attribute forms -- read as text, not
# composed values, exactly as the proven spike did: these files are
# small, static per-asset overs, not part of the live composed stage the
# panel is pointed at, so there is no stage to read them off of.
_FINISH_RE = re.compile(r'weft:bind:finish\s*=\s*"([^"]+)"')
_SHADING_LIST_RE = re.compile(r'weft:bind:shading\s*=\s*\[([^\]]*)\]')
_SHADING_SCALAR_RE = re.compile(r'weft:bind:shading\s*=\s*"([^"]+)"')

# Preferred display order for the viewer's lens selector; anything else
# found gets appended after these, sorted, so a graph is never silently
# missing a kind just because this list doesn't know its name.
_KIND_ORDER = ["usd:arc", "Mount", "weft:bind:shading", "weft:bind:finish"]


def _asset_of(name: str) -> str:
    """Strip a placement's trailing instance number ("_0007") to recover
    the asset id its interface file is named for ("chemistry_bottle01").
    A name with no numeric suffix (already just an asset id) is returned
    unchanged."""
    parts = name.rsplit("_", 1)
    return parts[0] if len(parts) == 2 and parts[1].isdigit() else name


def _alab_root_from_stage(stage, alab_root: Optional[str]) -> Optional[str]:
    """The ALab checkout root, so facet lookup can find
    entity/*/interface/*_interface.usda -- derived from the open stage's own
    root layer path (ALab's own convention:
    <ALAB_ROOT>/entity/<name>/<name>.usda), not hardcoded, unless the caller
    already knows it and passes it explicitly. Returns None (never raises)
    when the stage isn't a file on disk, or the derived directory doesn't
    look like an ALab tree -- callers degrade to omitting facets."""
    if alab_root:
        return alab_root
    if stage is None:
        return None
    root_layer = stage.GetRootLayer()
    real = root_layer.realPath if root_layer else ""
    if not real:
        return None
    d = os.path.dirname(real)
    for _ in range(2):
        parent = os.path.dirname(d)
        if not parent or parent == d:
            return None
        d = parent
    return d if os.path.isdir(os.path.join(d, "entity")) else None


def _facets_from_interfaces(
    alab_root: Optional[str],
) -> Tuple[Dict[str, str], Dict[str, List[str]]]:
    """asset -> finish label, and asset -> sorted shading tokens, read off
    every entity's own interface file under `alab_root`. Empty dicts (never
    an exception) when `alab_root` is None or nothing matches -- the panel
    still renders hierarchy and Mount without facets."""
    finish: Dict[str, str] = {}
    shading: Dict[str, List[str]] = {}
    if not alab_root:
        return finish, shading
    pattern = os.path.join(alab_root, "entity", "*", "interface", "*_interface.usda")
    for path in glob.glob(pattern):
        asset = os.path.basename(path).replace("_interface.usda", "")
        try:
            with open(path) as fh:
                text = fh.read()
        except OSError:
            continue
        m = _FINISH_RE.search(text)
        if m:
            finish[asset] = m.group(1)
        toks: List[str] = []
        for m in _SHADING_LIST_RE.finditer(text):
            toks += re.findall(r'"([^"]+)"', m.group(1))
        for m in _SHADING_SCALAR_RE.finditer(text):
            toks.append(m.group(1))
        if toks:
            shading[asset] = sorted(set(toks))
    return finish, shading


def build_graph(stage, alab_root: Optional[str] = None) -> Dict:
    """The live thread graph for `stage`: {"nodes": [...], "edges": [...],
    "kinds": [...]} in the exact shape the d3 viewer's template `DATA`
    constant expects (the viewer itself synthesizes the /root node and its
    group edges on load -- neither is emitted here, matching the proven
    spike's own output shape).

    Each node: id, label, type (group/prop/furniture/finish/shading), deg,
    and -- for prop/furniture nodes -- asset, group. Each edge: source,
    target, kind. Never raises on a stage that doesn't match ALab's
    convention or has no discoverable interface files -- it returns
    whatever it could build, down to an empty graph.
    """
    resolved_root = _alab_root_from_stage(stage, alab_root)
    asset_finish, asset_shading = _facets_from_interfaces(resolved_root)

    nodes: Dict[str, Dict] = {}
    edges: List[Dict] = []

    def add(node_id, label, node_type, extra=None):
        if node_id not in nodes:
            entry = {"id": node_id, "label": label, "type": node_type}
            if extra:
                entry.update(extra)
            nodes[node_id] = entry
        return node_id

    root = stage.GetPrimAtPath("/root") if stage else None
    if not root or not root.IsValid():
        root = stage.GetPseudoRoot() if stage else None
    if root is None:
        return {"nodes": [], "edges": [], "kinds": []}

    # UsdPrimDefaultPredicate is "active && defined && loaded && !abstract"
    # (see pxr/usd/usd/primFlags.h) -- GetChildren()'s own default. The
    # panel's whole point is showing the graph BEFORE anything is loaded
    # ("open as bounding boxes"), and on a stage opened with `--unloaded` a
    # prim that has no local "def" opinion outside its own payload composes
    # as present-but-not-yet-loaded -- GetChildren() would skip it, quietly
    # shrinking the graph to whatever happened to already be loaded.
    # Usd.PrimAllPrimsPredicate is NOT the fix: it drops every other term
    # too (active, defined, abstract), which pulled in inactive/abstract/
    # undefined placeholder prims and nearly tripled the node count in
    # testing against this ALab workbench. The right predicate is the
    # default MINUS the loaded requirement: still only real, active,
    # defined, non-abstract prims, just not gated on payload load state.
    from pxr import Usd
    hierarchy_predicate = Usd.PrimIsActive & Usd.PrimIsDefined & ~Usd.PrimIsAbstract

    for grp in root.GetFilteredChildren(hierarchy_predicate):
        gname = grp.GetName()
        # Use the group's REAL prim path as its node id (not a synthetic
        # "/g/<name>"): the panel selects+materializes a clicked node by
        # GetPrimAtPath(id), so a group must carry a path that resolves --
        # otherwise clicking a group is a silent no-op (invalid prim) and it
        # never highlights in usdview's own outliner.
        gid = add(grp.GetPath().pathString, gname, "group")
        for pl in grp.GetFilteredChildren(hierarchy_predicate):
            n = pl.GetName()
            suffix = n.rsplit("_", 1)[-1]
            if not suffix.isdigit():
                continue
            asset = _asset_of(n)
            ntype = "furniture" if n.startswith("furniture_") else "prop"
            pid = add(pl.GetPath().pathString, n, ntype,
                       {"asset": asset, "group": gname})
            edges.append({"source": gid, "target": pid, "kind": "usd:arc"})

            if asset in asset_finish:
                cid = add("finish:%s" % asset_finish[asset],
                           "finish: %s" % asset_finish[asset], "finish")
                edges.append({"source": pid, "target": cid, "kind": "weft:bind:finish"})
            for tok in asset_shading.get(asset, []):
                cid = add("shading:%s" % tok, tok, "shading")
                edges.append({"source": pid, "target": cid, "kind": "weft:bind:shading"})

            contract_attr = pl.GetAttribute("weft:offer:contract")
            if contract_attr and contract_attr.HasAuthoredValue():
                kind = str(contract_attr.Get()).split("@")[0]
                carrier_rel = pl.GetRelationship("weft:offer:carrier")
                if carrier_rel:
                    for target in carrier_rel.GetTargets():
                        target_path = target.GetPrimPath().pathString
                        target_prim = stage.GetPrimAtPath(target_path)
                        if target_prim:
                            add(target_path, target_prim.GetName(),
                                "furniture" if target_prim.GetName().startswith("furniture_")
                                else "prop", {"group": gname})
                            edges.append({"source": pid, "target": target_path, "kind": kind})

    deg: Dict[str, int] = {}
    for e in edges:
        deg[e["source"]] = deg.get(e["source"], 0) + 1
        deg[e["target"]] = deg.get(e["target"], 0) + 1
    for node_id, node in nodes.items():
        node["deg"] = deg.get(node_id, 0)

    present = {e["kind"] for e in edges}
    kinds = [k for k in _KIND_ORDER if k in present]
    kinds += sorted(present - set(_KIND_ORDER))

    return {"nodes": list(nodes.values()), "edges": edges, "kinds": kinds}
