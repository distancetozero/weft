"""RelationshipKind framework -- the pluggable "kinds" of edge the Weft
Threads graph (weft/threadgraph.py) draws.

Background
----------
threadgraph.build_graph used to be one hand-written walk with the four kinds
of edge (hierarchy, mount/contract, finish, shading) hardcoded inline. This
module factors each of those into a self-contained RelationshipKind object and
turns build_graph into a thin driver that iterates a registry of them, so a
new kind is added by registering an object -- no edit to the driver.

Reproducing the old graph exactly
---------------------------------
The old build_graph emitted nodes and edges in a specific *interleaved* order:
for each placement prim it appended, in order, its hierarchy edge, then finish,
then shading, then mount. That order is load-bearing for byte-for-byte
equality (node de-duplication is first-touch-wins, so e.g. a mount carrier
prim gets the attributes of whichever pass added it first). To preserve it, a
kind that hangs off the root -> group -> placement convention contributes
through two per-walk hooks -- `enter_group` and `visit_placement` -- which the
driver calls once per group/placement in *registry order*. A stage-global kind
(one that isn't a function of a single placement, e.g. usd:collection) instead
implements `populate`, called once after the walk. A kind uses whichever hooks
fit; the unused ones default to no-ops.

Everything here is pure `pxr` + stdlib: no Qt, no stage writes, lazy imports of
pxr inside the methods that need it, and never raises on missing/odd data --
it degrades to emitting less, matching threadgraph's guard-everything contract.
"""

from __future__ import annotations

import glob
import os
import re
from typing import Dict, List, Mapping, Optional, Set

# -- interface-file facet readers (moved verbatim from threadgraph) ----------
#
# The finish/shading facets are authored in each entity's own small static
# interface over (entity/<asset>/interface/<asset>_interface.usda), read as
# text, not off the composed stage -- those files are not part of the live
# stage the panel is pointed at. See threadgraph's module docstring.

_FINISH_RE = re.compile(r'weft:bind:finish\s*=\s*"([^"]+)"')
_SHADING_LIST_RE = re.compile(r'weft:bind:shading\s*=\s*\[([^\]]*)\]')
_SHADING_SCALAR_RE = re.compile(r'weft:bind:shading\s*=\s*"([^"]+)"')


def asset_of(name: str) -> str:
    """Strip a placement's trailing instance number ("_0007") to recover the
    asset id its interface file is named for ("chemistry_bottle01"). A name
    with no numeric suffix is returned unchanged."""
    parts = name.rsplit("_", 1)
    return parts[0] if len(parts) == 2 and parts[1].isdigit() else name


def alab_root_from_stage(stage, alab_root: Optional[str]) -> Optional[str]:
    """The ALab checkout root (so facet lookup can find the interface files),
    derived from the open stage's own root-layer path unless the caller passed
    it. Returns None (never raises) when the stage isn't a file on disk or the
    derived directory doesn't look like an ALab tree."""
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


def facets_from_interfaces(alab_root: Optional[str]):
    """asset -> finish label, and asset -> sorted shading tokens, read off
    every entity's own interface file under `alab_root`. Empty dicts (never an
    exception) when `alab_root` is None or nothing matches."""
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


# -- the shared graph accumulator + walk context ----------------------------


class GraphBuilder:
    """Accumulates nodes (de-duplicated first-touch-wins, insertion order
    preserved) and edges (in append order) -- the same two structures the old
    build_graph closed over."""

    def __init__(self) -> None:
        self.nodes: "Dict[str, Dict]" = {}
        self.edges: "List[Dict]" = []

    def add(self, node_id, label, node_type, extra=None):
        if node_id not in self.nodes:
            entry = {"id": node_id, "label": label, "type": node_type}
            if extra:
                entry.update(extra)
            self.nodes[node_id] = entry
        return node_id

    def add_edge(self, source, target, kind):
        self.edges.append({"source": source, "target": target, "kind": kind})


class Context:
    """Everything a kind needs during a build: the stage, the accumulator, the
    predicate the driver walks with, and the precomputed interface facets. Kept
    as a plain attribute bag so kinds stay decoupled from build_graph."""

    def __init__(self, stage, builder: GraphBuilder, predicate,
                 asset_finish: Mapping[str, str],
                 asset_shading: Mapping[str, List[str]]) -> None:
        self.stage = stage
        self.builder = builder
        self.predicate = predicate
        self.asset_finish = asset_finish
        self.asset_shading = asset_shading


# -- the RelationshipKind interface ------------------------------------------


class RelationshipKind:
    """One kind of relationship the graph can draw. Subclasses set the class
    attributes and override whichever hooks apply.

    Attributes:
      type_id  -- stable identifier for the kind (e.g. "usd:arc"). Note this is
                  the kind's *identity*; the string written into each edge's
                  "kind" field is normally type_id but need not be (MountKind
                  tags edges with the authored contract name it read).
      facet    -- True for facet kinds (shared grouping nodes many prims point
                  at, e.g. finish/shading) vs. structural kinds (hierarchy,
                  mount). Advisory metadata for the panel; not emitted in v1.
      display  -- {"label":..., "color":...} panel presentation metadata. Not
                  emitted into the graph in v1 (would change the wire shape).

    Hooks (all optional; defaults are no-ops):
      enter_group(ctx, group)          -- once per root-child group, in registry
                                          order, before its placements.
      visit_placement(ctx, group, pl)  -- once per placement prim, in registry
                                          order.
      populate(stage, ctx)             -- once after the whole walk, for
                                          stage-global kinds.
      resolve(members, stage, ctx)     -- membership resolution. v1 is identity
                                          (the existing load_set behaviour): the
                                          member prim-path set, as Sdf.Paths. No
                                          LIVRPS/masks yet.
    """

    type_id: str = ""
    facet: bool = False
    display: Mapping = {}

    def enter_group(self, ctx: Context, group) -> None:  # noqa: D401
        pass

    def visit_placement(self, ctx: Context, group, placement) -> None:
        pass

    def populate(self, stage, ctx: Context) -> None:
        pass

    def resolve(self, members, stage, ctx: Context) -> "Set":
        from pxr import Sdf
        out = set()
        for m in members:
            try:
                out.add(m if isinstance(m, Sdf.Path) else Sdf.Path(str(m)))
            except Exception:
                continue
        return out


# -- the four migrated kinds --------------------------------------------------


class UsdArcKind(RelationshipKind):
    """Hierarchy edges derived from composition: the root -> group -> placement
    structure. Owns creation of the group and placement nodes (everything else
    hangs off them), so it is registered first."""

    type_id = "usd:arc"
    facet = False
    display = {"label": "USD hierarchy", "color": "#8a8f98"}

    def enter_group(self, ctx: Context, group) -> None:
        # Every root-child group gets a node, even one with no placements --
        # its REAL prim path is the id so the panel can select it.
        ctx.builder.add(group.GetPath().pathString, group.GetName(), "group")

    def visit_placement(self, ctx: Context, group, placement) -> None:
        gid = group.GetPath().pathString
        n = placement.GetName()
        asset = asset_of(n)
        ntype = "furniture" if n.startswith("furniture_") else "prop"
        pid = ctx.builder.add(placement.GetPath().pathString, n, ntype,
                              {"asset": asset, "group": group.GetName()})
        ctx.builder.add_edge(gid, pid, self.type_id)


class FinishKind(RelationshipKind):
    """Authored finish facet, read from the asset's interface file (curated,
    not derivable -- 7/8 translucent ALab assets carry no material signal)."""

    type_id = "weft:bind:finish"
    facet = True
    display = {"label": "Finish", "color": "#c48be0"}

    def visit_placement(self, ctx: Context, group, placement) -> None:
        asset = asset_of(placement.GetName())
        label = ctx.asset_finish.get(asset)
        if label is None:
            return
        pid = placement.GetPath().pathString
        cid = ctx.builder.add("finish:%s" % label, "finish: %s" % label, "finish")
        ctx.builder.add_edge(pid, cid, self.type_id)


class ShadingKind(RelationshipKind):
    """Authored shading facet (the representation set
    ["usd_full","usd_preview","usd_preview_proxy"]), read from the interface
    file -- a representation set, not material identity."""

    type_id = "weft:bind:shading"
    facet = True
    display = {"label": "Shading", "color": "#6bb1e0"}

    def visit_placement(self, ctx: Context, group, placement) -> None:
        asset = asset_of(placement.GetName())
        pid = placement.GetPath().pathString
        for tok in ctx.asset_shading.get(asset, []):
            cid = ctx.builder.add("shading:%s" % tok, tok, "shading")
            ctx.builder.add_edge(pid, cid, self.type_id)


class MountKind(RelationshipKind):
    """Authored mount/contract edge: read each placement's own
    weft:offer:contract (the edge is tagged with the contract's own name, e.g.
    "Mount") and weft:offer:carrier (its target prim(s))."""

    type_id = "weft:mount"
    facet = False
    display = {"label": "Mount", "color": "#e0a96b"}

    def visit_placement(self, ctx: Context, group, placement) -> None:
        contract_attr = placement.GetAttribute("weft:offer:contract")
        if not (contract_attr and contract_attr.HasAuthoredValue()):
            return
        kind = str(contract_attr.Get()).split("@")[0]
        carrier_rel = placement.GetRelationship("weft:offer:carrier")
        if not carrier_rel:
            return
        pid = placement.GetPath().pathString
        gname = group.GetName()
        for target in carrier_rel.GetTargets():
            target_path = target.GetPrimPath().pathString
            target_prim = ctx.stage.GetPrimAtPath(target_path)
            if target_prim:
                ctx.builder.add(
                    target_path, target_prim.GetName(),
                    "furniture" if target_prim.GetName().startswith("furniture_")
                    else "prop", {"group": gname})
                ctx.builder.add_edge(pid, target_path, kind)


# -- the new derived kind: usd:collection ------------------------------------


class CollectionKind(RelationshipKind):
    """Derived kind: every UsdCollectionAPI on the stage becomes a collection
    node with usd:collection edges to its resolved member prim paths. Honors
    expansionRule, includes/excludes and membershipExpression transparently via
    ComputeMembershipQuery/ComputeIncludedPaths. Purely additive and guarded:
    a stage with no collections emits nothing (so it never appears in the kinds
    list). Reads membership without forcing payload loads (walks with the same
    load-agnostic predicate the rest of the graph uses)."""

    type_id = "usd:collection"
    facet = True
    display = {"label": "Collections", "color": "#7fd0a0"}

    def populate(self, stage, ctx: Context) -> None:
        if stage is None:
            return
        from pxr import Usd
        for prim in stage.Traverse(ctx.predicate):
            try:
                colls = Usd.CollectionAPI.GetAllCollections(prim)
            except Exception:
                continue
            for coll in colls:
                self._emit(stage, ctx, coll)

    def _emit(self, stage, ctx: Context, coll) -> None:
        from pxr import Usd
        try:
            coll_path = coll.GetCollectionPath().pathString
        except Exception:
            return
        name = coll.GetName()
        members = self._members(stage, ctx, coll)
        if not members:
            return
        cid = ctx.builder.add(coll_path, name, "collection")
        resolved = self.resolve(members, stage, ctx)
        for path in sorted(resolved, key=str):
            prim = stage.GetPrimAtPath(path)
            if not (prim and prim.IsValid()):
                continue
            tpath = path.pathString
            name_t = prim.GetName()
            ntype = "furniture" if name_t.startswith("furniture_") else "prop"
            ctx.builder.add(tpath, name_t, ntype)
            ctx.builder.add_edge(cid, tpath, self.type_id)

    def _members(self, stage, ctx: Context, coll):
        """Resolved member prim paths of one collection, honoring
        includes/excludes/expansionRule/membershipExpression. Never raises."""
        from pxr import Usd
        try:
            query = coll.ComputeMembershipQuery()
            return list(Usd.CollectionAPI.ComputeIncludedPaths(
                query, stage, ctx.predicate))
        except Exception:
            return []


class MaterialBindingKind(RelationshipKind):
    """Derived, native: each gprim's bound material, resolved per USD material
    PURPOSE. USD (and ALab in particular) binds materials *per purpose* -- `full`
    (render) and `preview` -- and *by inheritance* (the binding sits on an
    ancestor, descendants inherit), NOT on the all-purpose `material:binding`.
    `ComputeBoundMaterial(purpose)` resolves exactly that (inheritance +
    all-purpose fallback). Each purpose is its own lens
    (`usd:material:binding:full` / `:preview`) so render vs preview materials
    stay distinguishable. gprims only -- the things that actually render with a
    material (inheritance would otherwise fan an edge onto every intermediate
    scope). Bindings behind unloaded payloads aren't seen until pulled --
    derive sees what composition sees.

    (Measured: this takes ALab from 2 all-purpose bindings to ~7,500 preview +
    ~6,141 full -- the materials were always there, on the purposes we weren't
    asking for.)"""

    type_id = "usd:material:binding"
    facet = True
    display = {"label": "Material", "color": "#d08b8b"}
    purposes = ("full", "preview")

    def populate(self, stage, ctx: Context) -> None:
        if stage is None:
            return
        from pxr import UsdShade, UsdGeom
        ptok = {"full": UsdShade.Tokens.full, "preview": UsdShade.Tokens.preview}
        for prim in stage.Traverse(ctx.predicate):
            if not UsdGeom.Gprim(prim):
                continue
            api = UsdShade.MaterialBindingAPI(prim)
            for pname in self.purposes:
                try:
                    mat, _ = api.ComputeBoundMaterial(ptok[pname])
                except Exception:
                    continue
                if not (mat and mat.GetPrim().IsValid()):
                    continue
                mprim = mat.GetPrim()
                mpath = mprim.GetPath().pathString
                mid = ctx.builder.add("material:%s" % mpath, mprim.GetName(), "material")
                ctx.builder.add_edge(prim.GetPath().pathString, mid,
                                     "%s:%s" % (self.type_id, pname))


# -- the registry ------------------------------------------------------------
#
# Order here is the *walk/emission* order (arc first so it creates the group
# and placement nodes; then finish, shading, mount -- exactly the old inline
# order). Stage-global kinds (populate-only) run after the walk in this order.
# A new kind is added by appending an instance -- no edit to threadgraph's
# driver.

REGISTRY: "List[RelationshipKind]" = [
    UsdArcKind(),
    FinishKind(),
    ShadingKind(),
    MountKind(),
    CollectionKind(),
    MaterialBindingKind(),
]

# The lens-selector display order for the kinds list build_graph returns --
# a separate concern from emission order (Mount ranks above the facets in the
# selector but is emitted after them). Keyed by the *edge kind* string each
# kind writes. Kinds not listed here sort alphabetically after these, matching
# the old _KIND_ORDER behaviour exactly.
LENS_ORDER: "List[str]" = [
    "usd:arc",
    "Mount",
    "weft:bind:shading",
    "weft:bind:finish",
    "usd:collection",
    "usd:material:binding:full",
    "usd:material:binding:preview",
]
