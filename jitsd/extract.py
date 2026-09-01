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
                       cost_class: str = "heavy") -> str:
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
        'def Xform "%s" (' % ex.provider,
        '    prepend apiSchemas = ["JitsdGeneratorAPI"]',
        ")",
        "{",
        '    uniform token jitsd:costClass = "%s"' % cost_class,
        '    uniform token jitsd:envelope:source = "policy:extractor-default"',
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


def consumer_interface(asset: str, contract: str = DEFAULT_CONTRACT,
                       cost_class: str = "trivial",
                       tolerance: Optional[float] = None,
                       tolerance_rule: str = "") -> str:
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
    lines += ["}", ""]
    return "\n".join(lines)


def write_interfaces(ex: Extraction, out_dir: str, contract: str = DEFAULT_CONTRACT,
                     envelope: float = 1.0,
                     nudge: Optional[Dict[str, Vec3]] = None,
                     tolerance_fraction: Optional[float] = None) -> Dict[str, str]:
    """Write provider + consumer interface layers. Returns {asset: path}.

    With `tolerance_fraction`, each consumer's tolerance is that fraction of
    its own footprint (from extentsHint), and the interface records the rule.
    """
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    paths: Dict[str, str] = {}
    p = out / ("%s.iface.usda" % ex.provider)
    p.write_text(provider_interface(ex, contract, envelope, nudge))
    paths[ex.provider] = str(p)
    targets = {q.asset: q.target for q in ex.placements if q.target}
    for asset in ex.assets:
        tol, rule = None, ""
        if tolerance_fraction is not None and targets.get(asset):
            fp = footprint(targets[asset])
            if fp:
                tol = round(fp * tolerance_fraction, 4)
                rule = "%.0f%% of a %s footprint" % (tolerance_fraction * 100, _f(fp))
        c = out / ("%s.iface.usda" % asset)
        c.write_text(consumer_interface(asset, contract, tolerance=tol, tolerance_rule=rule))
        paths[asset] = str(c)
    return paths
