"""Give an existing assembly a contract surface.

The adoption path for every studio that has a USD library and no contracts.
An assembly already *is* the data: it places props at real transforms under
named groups. Read that, and emit interface layers --

  provider   one JitsdOfferAPI mount per placement, frame = the placement's
             translate, role = the placed asset's name, plus an envelope
  consumers  one JitsdRequireAPI per placed asset: Mount, role = itself,
             cardinality many, so it binds every place the provider offers it

Role = asset name is the deliberate choice. Per-placement roles would make a
consumer *asset* name a particular placement, which is per-instance data on a
per-asset surface; and they would reintroduce the discrimination problem the
review flagged, where contract+role converges on the prim namespace. Asset
roles are 1:many, deterministic, and say exactly what a prop needs: a mount
meant for it.

Nothing here composes a stage. It reads specs (variants included) through
the `deps` walker, so it needs pxr and is optional at runtime like `deps`.
"""

from __future__ import annotations

import os
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List, Optional, Tuple

Vec3 = Tuple[float, float, float]

DEFAULT_CONTRACT = "Mount@1"
INSTANCE_SUFFIX = re.compile(r"_\d{3,}$")


@dataclass
class Placement:
    prim: str          # path of the placement prim in the assembly
    group: str         # first group under root, or "root"
    name: str          # placement prim name, e.g. chemistry_bottle01_0004
    asset: str         # placed asset name, e.g. chemistry_bottle01
    translate: Vec3
    target: str = ""   # the placed layer, resolved


def departments(entity_layer: str) -> List[str]:
    """Which department sublayers an entity actually carries.

    ALab's convention: an entity root sublayers one file per department --
    surfacing/, modelling/, preview/, sometimes rigging/ or lighting/. The
    directory prefix IS the department. Derived, not asserted: measured over
    the real corpus, 326 entities carry {modelling, preview, surfacing}, the
    assemblies differ, and one carries rigging -- so the set is informative.
    """
    try:
        from pxr import Sdf
        layer = Sdf.Layer.FindOrOpen(entity_layer)
    except Exception:
        return []
    if not layer:
        return []
    out = set()
    for sub in layer.subLayerPaths:
        first = str(sub).lstrip("./").split("/", 1)[0]
        if first and not first.startswith("@"):
            out.add(first)
    # The interface sublayer is ours -- written by write_interfaces(into_assets).
    # Counting it would make extraction self-polluting: every re-extraction
    # would add "interface" to provides, and the constraint would then require
    # the thing that declares the constraint.
    out.discard("interface")
    return sorted(out)


def footprint(layer_path: str) -> Optional[float]:
    """A placed asset's horizontal footprint from its authored extentsHint.

    Used to derive a consumer's tolerance as a fraction of its own size -- a
    stated rule, not a magic number. A 6 cm bottle and a 1 cm screw should not
    tolerate the same drift. None when the asset states no extent, in which
    case no tolerance is emitted and the provider's envelope governs.
    """
    try:
        from pxr import Usd, UsdGeom
        st = Usd.Stage.Open(layer_path, Usd.Stage.LoadNone)
        root = st.GetDefaultPrim() or st.GetPrimAtPath("/root")
        hint = UsdGeom.ModelAPI(root).GetExtentsHintAttr().Get() if root else None
    except Exception:
        return None
    if not hint or len(hint) < 2:
        return None
    lo, hi = hint[0], hint[1]
    return float(max(hi[0] - lo[0], hi[2] - lo[2]))


@dataclass
class Extraction:
    provider: str
    placements: List[Placement] = field(default_factory=list)

    @property
    def assets(self) -> List[str]:
        return sorted({p.asset for p in self.placements})

    @property
    def groups(self) -> List[str]:
        return sorted({p.group for p in self.placements})


def _translate_of(spec) -> Optional[Vec3]:
    t = spec.attributes.get("xformOp:translate")
    if t is not None and t.default is not None:
        return tuple(float(x) for x in t.default)
    m = spec.attributes.get("xformOp:transform")
    if m is not None and m.default is not None:
        row = m.default[3]
        return (float(row[0]), float(row[1]), float(row[2]))
    return None


def read_assembly(assembly: str, provider: str) -> Extraction:
    """Every reference/payload placement in an assembly layer, with its frame."""
    from pxr import Sdf
    from deps.walk import ARC, walk_file

    rec = walk_file(assembly)
    if rec is None:
        raise IOError("could not read assembly layer: %s" % assembly)
    layer = Sdf.Layer.FindOrOpen(assembly)

    out = Extraction(provider=provider)
    seen = set()
    for e in rec.edges:
        if e.kind != ARC or e.src_prim in ("/", "") or e.src_prim in seen:
            continue
        seen.add(e.src_prim)
        spec = layer.GetPrimAtPath(e.src_prim)
        if spec is None:
            continue
        t = _translate_of(spec)
        if t is None:
            continue   # a reference with no placement is not a mount
        parts = e.src_prim.strip("/").split("/")
        group = parts[1] if len(parts) > 2 else "root"
        name = parts[-1]
        asset = INSTANCE_SUFFIX.sub("", os.path.splitext(os.path.basename(e.target))[0])
        # walk_file reports the authored asset path; resolve it here, relative
        # to the assembly, so footprint() can open the placed layer.
        if os.path.isabs(e.target):
            target = os.path.normpath(e.target)
        else:
            target = os.path.normpath(os.path.join(os.path.dirname(assembly), e.target))
        if not os.path.exists(target):
            target = ""
        out.placements.append(Placement(e.src_prim, group, name, asset, t, target=target))
    out.placements.sort(key=lambda p: (p.group, p.name))
    return out


# -- emitting interface layers ----------------------------------------------

def _f(v: float) -> str:
    return ("%.6f" % v).rstrip("0").rstrip(".") or "0"


def provider_interface(ex: Extraction, contract: str = DEFAULT_CONTRACT,
                       envelope: float = 1.0,
                       nudge: Optional[Dict[str, Vec3]] = None,
                       cost_class: str = "heavy",
                       represents: Optional[Dict[str, List[str]]] = None) -> str:
    """The provider's surface: one offer per placement, grouped as authored.

    `nudge` shifts every offer in a group by a vector. It stands in for the
    modelling change a republish would carry -- the shelf moved -- so the
    promotion gate can be exercised without re-modelling geometry. Say so
    wherever it is used.
    """
    nudge = nudge or {}
    lines = [
        "#usda 1.0",
        "#",
        "# Contract surface extracted from an existing assembly. One mount per",
        "# placement; frames are the assembly's own translates. No consumer is",
        "# named, and no consumer names any of these paths.",
        "#",
        "# The envelope is NOT derived from the data: it is a policy value the",
        "# extractor was given, and each offer says so. A provider's real promise",
        "# is a human decision; replace it deliberately.",
        "#",
        "(",
        '    defaultPrim = "%s"' % ex.provider,
        ")",
        "",
    ]
    schemas = ['"JitsdGeneratorAPI"']
    schemas += ['"JitsdRequireAPI:rep_%s"' % a for a in sorted(represents or {})]
    lines += [
        'def Xform "%s" (' % ex.provider,
        "    prepend apiSchemas = [%s]" % ", ".join(schemas),
        ")",
        "{",
        '    uniform token jitsd:costClass = "%s"' % cost_class,
        '    uniform token jitsd:envelope:source = "policy:extractor-default"',
    ]
    for a, deps_ in sorted((represents or {}).items()):
        # The reverse direction: the assembly CONSUMES each placed asset's
        # representations. The constraint is the department set the asset
        # carried at extraction -- derived, and honest: the assembly was built
        # against exactly these. A prop republished without one of them breaks
        # the assembly at re-evaluation.
        lines += [
            "",
            '    uniform token   jitsd:require:rep_%s:contract      = "%s"' % (a, REPRESENTS_CONTRACT),
            '    uniform token   jitsd:require:rep_%s:role          = "%s"' % (a, a),
            '    uniform token   jitsd:require:rep_%s:cardinality   = "one"' % a,
            '    uniform token   jitsd:require:rep_%s:failurePolicy = "required"' % a,
            "    uniform token[] jitsd:require:rep_%s:bind:provides = [%s]"
            % (a, ", ".join('"%s"' % d for d in sorted(deps_))),
        ]
    for group in ex.groups:
        lines += ["", '    def Scope "%s"' % group, "    {"]
        d = nudge.get(group, (0.0, 0.0, 0.0))
        for p in (q for q in ex.placements if q.group == group):
            t = (p.translate[0] + d[0], p.translate[1] + d[1], p.translate[2] + d[2])
            lines += [
                '        def Xform "%s" (' % p.name,
                '            prepend apiSchemas = ["JitsdOfferAPI", "JitsdMountAPI", "JitsdEnvelopeAPI"]',
                "        )",
                "        {",
                '            uniform token  jitsd:offer:contract  = "%s"' % contract,
                '            uniform token  jitsd:offer:archetype = "mount"',
                '            uniform token  jitsd:mount:role      = "%s"' % p.asset,
                "            uniform double jitsd:envelope:linear = %s" % _f(envelope),
                "            double3 xformOp:translate = (%s, %s, %s)" % tuple(_f(x) for x in t),
                "        }",
            ]
        lines.append("    }")
    lines += ["}", ""]
    return "\n".join(lines)


REPRESENTS_CONTRACT = "Represents@1"


def consumer_interface(asset: str, contract: str = DEFAULT_CONTRACT,
                       cost_class: str = "trivial",
                       tolerance: Optional[float] = None,
                       tolerance_rule: str = "",
                       provides: Optional[List[str]] = None,
                       materials: Optional[List[str]] = None) -> str:
    """A placed asset's surface: it needs a mount meant for it, wherever offered.

    `tolerance` is the consumer's own limit on drift, checked at
    re-evaluation regardless of what the provider promised. Omitted when
    unknown -- an unstated tolerance means the envelope governs, which is
    honest; an invented one is not.
    """
    lines = [
        "#usda 1.0",
        "#",
        "# Contract surface for a placed asset. Names a contract and a role;",
        "# never a provider, never a path inside one.",
        "#",
        "(",
        '    defaultPrim = "%s"' % asset,
        ")",
        "",
        'def Xform "%s" (' % asset,
        '    prepend apiSchemas = ["JitsdGeneratorAPI", "JitsdRequireAPI:mount"]',
        ")",
        "{",
        '    uniform token jitsd:costClass = "%s"' % cost_class,
        "",
        '    uniform token jitsd:require:mount:contract      = "%s"' % contract,
        '    uniform token jitsd:require:mount:role          = "%s"' % asset,
        '    uniform token jitsd:require:mount:cardinality   = "many"',
        '    uniform token jitsd:require:mount:failurePolicy = "required"',
    ]
    if tolerance is not None:
        lines += [
            "",
            "    # derived: %s" % (tolerance_rule or "stated by the consumer"),
            "    uniform double jitsd:require:mount:tolerance:linear = %s" % _f(tolerance),
        ]
    if provides:
        # The contract is two-sided. The prop consumes a mount; it also OFFERS
        # what it is -- which representations it carries, derived from its own
        # department sublayers, and (when the look data is present) which
        # materials. The assembly is the consumer of this offer, so dropping a
        # department breaks the assembly at re-evaluation, in the reverse
        # direction from the mount check.
        lines += [
            "",
            '    def Xform "represents" (',
            '        prepend apiSchemas = ["JitsdOfferAPI"]',
            "    )",
            "    {",
            '        uniform token   jitsd:offer:contract  = "%s"' % REPRESENTS_CONTRACT,
            '        uniform token   jitsd:offer:archetype = "field"',
            '        uniform token   jitsd:mount:role      = "%s"' % asset,
            "        uniform token[] jitsd:bind:provides   = [%s]"
            % ", ".join('"%s"' % d for d in sorted(provides)),
        ]
        if materials:
            lines += [
                "        uniform token[] jitsd:bind:materials  = [%s]"
                % ", ".join('"%s"' % m for m in sorted(materials)),
            ]
        lines += ["    }"]
    lines += ["}", ""]
    return "\n".join(lines)


def _ensure_sublayer(entity_layer: str, rel_path: str) -> bool:
    """Insert an interface sublayer into an entity's own root layer.

    The interface-sublayer convention: the contract surface lives INSIDE the
    asset's structure, as one more department alongside modelling/, preview/,
    surfacing/ -- versioned with the asset, visible to any USD tool. Returns
    True if the layer was modified.
    """
    from pxr import Sdf
    layer = Sdf.Layer.FindOrOpen(entity_layer)
    if not layer or rel_path in list(layer.subLayerPaths):
        return False
    subs = list(layer.subLayerPaths)
    subs.insert(0, rel_path)
    layer.subLayerPaths = subs
    layer.Save()
    return True


def write_interfaces(ex: Extraction, out_dir: str, contract: str = DEFAULT_CONTRACT,
                     envelope: float = 1.0,
                     nudge: Optional[Dict[str, Vec3]] = None,
                     tolerance_fraction: Optional[float] = None,
                     represent: bool = False,
                     materials_by_asset: Optional[Dict[str, List[str]]] = None,
                     into_assets: Optional[Dict[str, str]] = None) -> Dict[str, str]:
    """Write provider + consumer interface layers. Returns {asset: path}.

    With `tolerance_fraction`, each consumer's tolerance is that fraction of
    its own footprint (from extentsHint), and the interface records the rule.

    With `represent`, each placed asset also OFFERS its representations --
    the department set derived from its own sublayers, plus materials when
    given -- and the provider REQUIRES them: the contract runs both ways.

    `into_assets` maps asset -> its entity directory. When given, each
    interface is written to `<dir>/interface/<asset>_interface.usda` and
    inserted as a sublayer of the entity's root layer, so the surface lives
    inside the asset's own structure rather than beside it.
    """
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    paths: Dict[str, str] = {}
    targets = {q.asset: q.target for q in ex.placements if q.target}
    mats = materials_by_asset or {}

    provides: Dict[str, List[str]] = {}
    if represent:
        for asset in ex.assets:
            if targets.get(asset):
                d = departments(targets[asset])
                if d:
                    provides[asset] = d

    def _place(asset: str, text: str, default_name: str) -> str:
        if into_assets and asset in into_assets:
            d = Path(into_assets[asset]) / "interface"
            d.mkdir(parents=True, exist_ok=True)
            p = d / ("%s_interface.usda" % asset)
            p.write_text(text)
            entity = Path(into_assets[asset]) / ("%s.usda" % asset)
            if entity.exists():
                _ensure_sublayer(str(entity), "interface/%s_interface.usda" % asset)
            return str(p)
        p = out / default_name
        p.write_text(text)
        return str(p)

    paths[ex.provider] = _place(
        ex.provider,
        provider_interface(ex, contract, envelope, nudge,
                           represents=provides if represent else None),
        "%s.iface.usda" % ex.provider)

    for asset in ex.assets:
        tol, rule = None, ""
        if tolerance_fraction is not None and targets.get(asset):
            fp = footprint(targets[asset])
            if fp:
                tol = round(fp * tolerance_fraction, 4)
                rule = "%.0f%% of a %s footprint" % (tolerance_fraction * 100, _f(fp))
        text = consumer_interface(asset, contract, tolerance=tol, tolerance_rule=rule,
                                  provides=provides.get(asset),
                                  materials=mats.get(asset))
        paths[asset] = _place(asset, text, "%s.iface.usda" % asset)
    return paths
