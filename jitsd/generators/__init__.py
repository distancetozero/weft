"""Generators: the part that makes this just-in-time.

Everything before this was a version-control system with contracts. A generator
is a pure function from parameters to geometry, and three things about it are
load-bearing:

  offers(params)   The contract surface is COMPUTED, not authored. A chassis
                   does not declare where its hubs are; it declares how to
                   work them out from wheelbase and track. Change the
                   wheelbase and the mount points move -- which is the whole
                   scenario this project started from.

  bounds(params)   Answers "where will you be" without answering "what will
                   you look like". Cheap enough to index spatially before
                   generating anything (docs/04-contracts.md).

  generate(...)    The only expensive call, and the only one that touches a
                   triangle. Kept strictly below the relational plane.

A constant is a generator with no parameters. Everything is ADDRESSED as a
function; not everything is procedural.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Optional, Sequence, Tuple

from ..contracts import Offer, Requirement, Surface

Vec3 = Tuple[float, float, float]


@dataclass
class Param:
    name: str
    default: float
    minimum: Optional[float] = None
    maximum: Optional[float] = None
    unit: str = ""

    def coerce(self, value: Any) -> float:
        v = float(value)
        if self.minimum is not None and v < self.minimum:
            raise ValueError("%s = %g below minimum %g" % (self.name, v, self.minimum))
        if self.maximum is not None and v > self.maximum:
            raise ValueError("%s = %g above maximum %g" % (self.name, v, self.maximum))
        return v


@dataclass
class Context:
    """A claim set. Only declared variation points may read it."""
    name: str = "default"
    claims: Dict[str, Any] = field(default_factory=dict)

    def get(self, key: str, default: Any = None) -> Any:
        return self.claims.get(key, default)


class Generator:
    """Base class. Subclasses declare params and implement the three calls."""

    id: str = ""
    version: str = "0.0.0"
    params: Sequence[Param] = ()
    variation_points: Sequence[str] = ()
    cost_class: str = "moderate"

    # -- parameters -------------------------------------------------------
    def defaults(self) -> Dict[str, float]:
        return {p.name: p.default for p in self.params}

    def bind_params(self, overrides: Optional[Dict[str, Any]] = None) -> Dict[str, float]:
        by_name = {p.name: p for p in self.params}
        out = self.defaults()
        for k, v in (overrides or {}).items():
            if k not in by_name:
                raise ValueError("%s has no parameter %r" % (self.id, k))
            out[k] = by_name[k].coerce(v)
        return out

    # -- the three calls --------------------------------------------------
    def offers(self, params: Dict[str, float]) -> List[Offer]:
        return []

    def requires(self, params: Dict[str, float]) -> List[Requirement]:
        return []

    def surface(self, params: Dict[str, float]) -> Surface:
        return Surface(offers=self.offers(params), requires=self.requires(params))

    def bounds(self, params: Dict[str, float]) -> Tuple[Vec3, Vec3]:
        """Conservative, computed from parameters alone. No geometry."""
        raise NotImplementedError

    def generate(self, params: Dict[str, float], context: Context,
                 bindings: Dict[str, List[Offer]]) -> str:
        """Emit a .usda fragment. The only expensive call."""
        raise NotImplementedError


_REGISTRY: Dict[str, Generator] = {}


def register(gen: Generator) -> Generator:
    _REGISTRY["%s@%s" % (gen.id, gen.version)] = gen
    _REGISTRY[gen.id] = gen  # unversioned alias -- resolution only, never storage
    return gen


def get(ident: str) -> Generator:
    if ident not in _REGISTRY:
        raise KeyError("no generator %r (have: %s)"
                       % (ident, ", ".join(sorted(k for k in _REGISTRY if "@" in k))))
    return _REGISTRY[ident]


def pin(ident: str) -> str:
    """Resolve a possibly-unversioned name to `id@version`.

    A revision must never store a bare name. The unversioned alias resolves to
    whatever was registered last, so a baseline pinning "chassis" recomposes
    through new code the day a new version registers -- different geometry,
    different mount points, from a coordinate that is supposed to be fixed.
    Pin at declare time so the revision records which function it meant.
    """
    gen = get(ident)
    return "%s@%s" % (gen.id, gen.version)


def code_hash(gen: Generator) -> str:
    """A digest of the generator's own code.

    The version string is a promise; this is evidence. Folding it into the
    baseline's merkle root means editing a generator without bumping its
    version shows up as drift instead of passing silently.
    """
    import hashlib
    import inspect

    h = hashlib.sha256()
    h.update(("%s@%s" % (gen.id, gen.version)).encode())
    for name in ("surface", "bounds", "generate", "bind_params"):
        fn = getattr(type(gen), name, None)
        if fn is None:
            continue
        try:
            src = inspect.getsource(fn)
        except (OSError, TypeError):
            src = ""            # C extension or REPL-defined; version only
        h.update(name.encode())
        h.update(src.encode())
    for p in getattr(gen, "params", ()) or ():
        h.update(repr(p).encode())
    return h.hexdigest()


def known() -> List[str]:
    return sorted(k for k in _REGISTRY if "@" in k)


# -- small mesh helpers ---------------------------------------------------

def box(center: Vec3, size: Vec3) -> Tuple[List[Vec3], List[int], List[int]]:
    cx, cy, cz = center
    hx, hy, hz = (s / 2.0 for s in size)
    pts = [
        (cx - hx, cy - hy, cz - hz), (cx + hx, cy - hy, cz - hz),
        (cx + hx, cy + hy, cz - hz), (cx - hx, cy + hy, cz - hz),
        (cx - hx, cy - hy, cz + hz), (cx + hx, cy - hy, cz + hz),
        (cx + hx, cy + hy, cz + hz), (cx - hx, cy + hy, cz + hz),
    ]
    idx = [0, 3, 2, 1,  4, 5, 6, 7,  0, 1, 5, 4,
           1, 2, 6, 5,  2, 3, 7, 6,  3, 0, 4, 7]
    return pts, [4] * 6, idx


def cylinder(center: Vec3, radius: float, width: float,
             segments: int, axis: int = 2) -> Tuple[List[Vec3], List[int], List[int]]:
    """A wheel: a disc pair swept along `axis`. `segments` is the LOD knob."""
    import math

    cx, cy, cz = center
    pts: List[Vec3] = []
    for side in (-1, 1):
        off = side * width / 2.0
        for i in range(segments):
            a = 2.0 * math.pi * i / segments
            u, v = radius * math.cos(a), radius * math.sin(a)
            if axis == 2:
                pts.append((cx + u, cy + v, cz + off))
            elif axis == 1:
                pts.append((cx + u, cy + off, cz + v))
            else:
                pts.append((cx + off, cy + u, cz + v))

    counts: List[int] = []
    idx: List[int] = []
    for i in range(segments):
        j = (i + 1) % segments
        idx += [i, j, segments + j, segments + i]
        counts.append(4)
    # caps as fans
    for base, rev in ((0, False), (segments, True)):
        ring = list(range(base, base + segments))
        if rev:
            ring.reverse()
        for i in range(1, segments - 1):
            idx += [ring[0], ring[i], ring[i + 1]]
            counts.append(3)
    return pts, counts, idx


def fmt_points(pts: Sequence[Vec3]) -> str:
    return "[" + ", ".join("(%.6g, %.6g, %.6g)" % p for p in pts) + "]"


def fmt_ints(xs: Sequence[int]) -> str:
    return "[" + ", ".join(str(x) for x in xs) + "]"


def mesh_prim(name: str, pts, counts, idx, indent: str = "    ") -> str:
    lo = tuple(min(p[i] for p in pts) for i in range(3)) if pts else (0, 0, 0)
    hi = tuple(max(p[i] for p in pts) for i in range(3)) if pts else (0, 0, 0)
    return (
        '{i}def Mesh "{n}"\n{i}{{\n'
        '{i}    point3f[] points = {p}\n'
        '{i}    int[] faceVertexCounts = {c}\n'
        '{i}    int[] faceVertexIndices = {x}\n'
        '{i}    float3[] extent = [({lo}), ({hi})]\n'
        '{i}}}\n'
    ).format(i=indent, n=name, p=fmt_points(pts), c=fmt_ints(counts), x=fmt_ints(idx),
             lo="%.6g, %.6g, %.6g" % lo, hi="%.6g, %.6g, %.6g" % hi)
