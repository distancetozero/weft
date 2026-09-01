"""The query document, and compiling one into a stage.

A query document is the assembly artifact from docs/01-overview.md: which
generators, at which baseline, with which parameters, under which context. It
is kilobytes of readable .usda and it is the only durable thing -- everything
else is derived and can be thrown away.

Compilation runs in the two phases of docs/02-architecture.md, and the split is
the point rather than an optimisation:

  Phase A -- relational.  Parameters, contract surfaces, bounds, bindings.
                          Kilobytes. Touches no geometry, so it is fast enough
                          to answer "what is in this frustum" or "does this
                          still resolve" without generating anything.

  Phase B -- materialise. Calls each generator. The only expensive step, and
                          the only one that produces a triangle.
"""

from __future__ import annotations

import hashlib
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List, Optional, Tuple

from .contracts import Offer, Resolution, Surface, resolve


class _Constant:
    """A stored payload wearing the generator interface: emits a payload arc
    to the object store instead of geometry. Context cannot vary it."""

    def __init__(self, revision):
        self._rev = revision

    def generate(self, params, ctx, bindings) -> str:
        return (
            '    def Xform "%s" (\n'
            '        prepend payload = @jitsd:obj/sha256:%s@\n'
            '    )\n'
            '    {\n'
            '        uniform int64 jitsd:payloadSize = %d\n'
            '    }\n' % (self._rev.asset, self._rev.blob, self._rev.size)
        )
from .generators import Context, Vec3
from .generators import get as get_generator
from .usda import Layer, parse

INSTANCE_API = "JitsdInstanceAPI"

# Named contexts expand to claim sets at the edge (docs/05-contexts.md): roles
# do not compose, claims do. These are presets, not the type.
CONTEXTS: Dict[str, Dict[str, object]] = {
    "hero":        {"fidelity": "hero",      "internals": False},
    "review":      {"fidelity": "review",    "internals": False},
    "proxy":       {"fidelity": "proxy",     "internals": False},
    "engineering": {"fidelity": "hero",      "internals": True},
    "collision":   {"fidelity": "collision", "internals": False},
}


def context_for(name: str) -> Context:
    if name not in CONTEXTS:
        raise KeyError("unknown context %r (have: %s)"
                       % (name, ", ".join(sorted(CONTEXTS))))
    return Context(name=name, claims=dict(CONTEXTS[name]))


@dataclass
class Instance:
    name: str
    asset: str
    params: Dict[str, float] = field(default_factory=dict)


@dataclass
class Query:
    instances: List[Instance] = field(default_factory=list)
    baseline: Optional[str] = None
    context: str = "review"
    label: str = ""


def parse_query(layer: Layer) -> Query:
    meta = layer.meta.get("customLayerData") or {}
    q = Query(
        baseline=(meta.get("jitsd__baseline") or None),
        context=str(meta.get("jitsd__context") or "review"),
        label=str(meta.get("jitsd__label") or ""),
    )
    for prim in layer.walk():
        if not prim.has_api(INSTANCE_API):
            continue
        asset = prim.attrs.get("jitsd:instance:asset")
        if not asset:
            continue
        params = {
            k.split(":", 2)[2]: v
            for k, v in prim.attrs.items()
            if k.startswith("jitsd:param:")
        }
        q.instances.append(Instance(name=prim.name, asset=str(asset), params=params))
    return q


def parse_query_file(path: Path) -> Query:
    return parse_query(parse(Path(path).read_text()))


# -- compilation ----------------------------------------------------------

@dataclass
class Compiled:
    stage: str
    query: Query
    context: Context
    pins: Dict[str, str]
    resolution: Resolution
    bounds: Dict[str, Tuple[Vec3, Vec3]]
    scene_bounds: Optional[Tuple[Vec3, Vec3]]
    phase_a_ms: float
    phase_b_ms: float

    @property
    def digest(self) -> str:
        return hashlib.sha256(self.stage.encode()).hexdigest()

    @property
    def ok(self) -> bool:
        return self.resolution.ok


def _union(a, b):
    if a is None:
        return b
    return (tuple(min(a[0][i], b[0][i]) for i in range(3)),
            tuple(max(a[1][i], b[1][i]) for i in range(3)))


def compile_query(repo, query: Query, context: Optional[str] = None,
                  geometry: bool = True) -> Compiled:
    """Resolve a query against pinned revisions and materialise a stage."""
    ctx = context_for(context or query.context)
    pins = repo.resolve(baseline=query.baseline)

    # ---- Phase A: relational. No geometry. ------------------------------
    t0 = time.perf_counter()
    gens: Dict[str, object] = {}
    bound: Dict[str, Dict[str, float]] = {}
    surfaces: Dict[str, Surface] = {}
    bounds: Dict[str, Tuple[Vec3, Vec3]] = {}

    for inst in query.instances:
        rev = pins.get(inst.asset)
        if rev is None:
            raise KeyError("query names asset %r, which no baseline pins" % inst.asset)
        r = repo.ledger.read_revision(inst.asset, rev)
        if r.generator:
            gen = get_generator(r.generator)
            params = gen.bind_params({**(r.params or {}), **inst.params})
            gens[inst.name] = gen
            bound[inst.name] = params
            surfaces[inst.name] = gen.surface(params)
            bounds[inst.name] = gen.bounds(params)
        else:
            # A constant is a generator with no parameters (docs/04). A stored
            # payload is a valid member; it just cannot be parameterised.
            if inst.params:
                raise ValueError(
                    "asset %r revision %s is a stored payload and cannot be "
                    "parameterised (params given: %s)"
                    % (inst.asset, rev, ", ".join(sorted(inst.params))))
            gens[inst.name] = _Constant(r)
            bound[inst.name] = {}
            surfaces[inst.name] = Surface.from_dict(r.surface)

    res = resolve(surfaces)

    # A consumer's real extent is its own, placed at every frame it resolved.
    offer_by_path: Dict[str, Offer] = {
        "%s%s" % (name, o.path): o for name, s in surfaces.items() for o in s.offers
    }
    bindings_by_instance: Dict[str, Dict[str, List[Offer]]] = {n: {} for n in bound}
    scene = None
    for b in res.bindings:
        offers = [offer_by_path[p] for p in b.providers if p in offer_by_path]
        bindings_by_instance[b.consumer][b.requirement.rsplit(":", 1)[-1]] = offers
        lo, hi = bounds[b.consumer]
        for o in offers:
            placed = (tuple(lo[i] + o.frame[i] for i in range(3)),
                      tuple(hi[i] + o.frame[i] for i in range(3)))
            bounds[b.consumer] = _union(bounds[b.consumer], placed)
    for bb in bounds.values():
        scene = _union(scene, bb)
    phase_a = (time.perf_counter() - t0) * 1000.0

    # ---- Phase B: materialise. The only expensive step. -----------------
    t1 = time.perf_counter()
    body = ""
    if geometry and res.ok:
        parts = []
        for inst in query.instances:
            parts.append(gens[inst.name].generate(
                bound[inst.name], ctx, bindings_by_instance.get(inst.name, {})))
        body = "".join(parts)
    phase_b = (time.perf_counter() - t1) * 1000.0

    stage = _emit(query, ctx, pins, scene, body)
    return Compiled(stage=stage, query=query, context=ctx, pins=pins, resolution=res,
                    bounds=bounds, scene_bounds=scene,
                    phase_a_ms=phase_a, phase_b_ms=phase_b)


def _emit(query: Query, ctx: Context, pins: Dict[str, str],
          scene: Optional[Tuple[Vec3, Vec3]], body: str) -> str:
    pin_lines = "\n".join('            string "%s" = "%s"' % (a, r)
                          for a, r in sorted(pins.items()))
    claims = ", ".join("%s=%s" % (k, v) for k, v in sorted(ctx.claims.items()))
    extent = ("    float3[] extent = [(%.6g, %.6g, %.6g), (%.6g, %.6g, %.6g)]\n"
              % (scene[0] + scene[1])) if scene else ""
    return (
        '#usda 1.0\n'
        '(\n'
        '    defaultPrim = "World"\n'
        '    customLayerData = {\n'
        '        string jitsd__compiled = "%s"\n'
        '        string jitsd__baseline = "%s"\n'
        '        string jitsd__context  = "%s"\n'
        '        string jitsd__claims   = "%s"\n'
        '        dictionary jitsd__pins = {\n%s\n        }\n'
        '    }\n'
        ')\n\n'
        'def Xform "World"\n{\n%s%s}\n'
        % (query.label or "(unlabelled)", query.baseline or "(floating)",
           ctx.name, claims, pin_lines, extent, body)
    )
