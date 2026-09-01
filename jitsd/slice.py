"""The slice as an object (docs/10-slices.md, plan step 1).

    slice = (seeds + rules)^closure  ±  overlay,  at one coordinate

No UI here. A slice resolves entirely in the relational plane -- revisions,
surfaces, bounds, sizes -- and never touches geometry. Its receipt is a
cost-and-contents preview computed before anything materialises, and every
member carries provenance: seeded, pulled by closure via a named edge, or
pinned by a person with a reason. The moment something can be in a slice
without a "why am I here" answer, the mystery scene file has been recreated.

A slice serialises to an ordinary query document, so `jitsd compile`
materialises it with no new machinery.
"""

from __future__ import annotations

import fnmatch
import json
import re
from dataclasses import dataclass, field, asdict
from pathlib import Path
from typing import Dict, List, Optional, Tuple

from .contracts import Surface, resolve, split_contract

SLICE_RE = re.compile(r'string\s+jitsd__slice\s*=\s*"((?:[^"\\]|\\.)*)"')

DEFAULT_DEPTH = 4


# -- specification ---------------------------------------------------------

@dataclass
class Overlay:
    asset: str
    author: str
    reason: str


@dataclass
class SliceSpec:
    seeds: List[str] = field(default_factory=list)
    closure: List[str] = field(default_factory=lambda: ["needs"])
    depth: int = DEFAULT_DEPTH
    include_optional: bool = False
    pins: List[Overlay] = field(default_factory=list)
    omits: List[Overlay] = field(default_factory=list)
    baseline: Optional[str] = None
    channel: str = "approved"
    context: str = "review"
    label: str = ""

    def to_json(self) -> str:
        return json.dumps(asdict(self), separators=(",", ":"), sort_keys=True)

    @classmethod
    def from_json(cls, text: str) -> "SliceSpec":
        d = json.loads(text)
        d["pins"] = [Overlay(**p) for p in d.get("pins", [])]
        d["omits"] = [Overlay(**o) for o in d.get("omits", [])]
        return cls(**d)


# -- result ----------------------------------------------------------------

@dataclass
class Provenance:
    kind: str            # seed | closure | pin
    detail: str          # the predicate, the edge, or the reason
    author: str = ""


@dataclass
class Member:
    asset: str
    rev: str
    provenance: Provenance
    size: int = 0                       # stored payload bytes (blob-backed)
    generator: Optional[str] = None
    cost_class: str = ""
    bounds: Optional[Tuple] = None


@dataclass
class BoundaryItem:
    asset: str
    via: str             # who referenced it and how
    why_excluded: str    # "substitutable, not forced" | "beyond depth N"


@dataclass
class SliceResult:
    spec: SliceSpec
    coordinate: str                      # "baseline 000003" or "floating on @approved"
    members: List[Member]
    omitted: List[Tuple[Overlay, str]]   # (overlay, what its provenance would have been)
    boundary: List[BoundaryItem]
    diagnostics: List[str]               # human-readable warnings/errors
    errors: int

    @property
    def ok(self) -> bool:
        return self.errors == 0

    def bounds_union(self) -> Optional[Tuple]:
        acc = None
        for m in self.members:
            if not m.bounds:
                continue
            lo, hi = m.bounds
            if acc is None:
                acc = (tuple(lo), tuple(hi))
            else:
                acc = (tuple(min(acc[0][i], lo[i]) for i in range(3)),
                       tuple(max(acc[1][i], hi[i]) for i in range(3)))
        return acc

    def payload_bytes(self) -> int:
        return sum(m.size for m in self.members)


# -- the universe: everything the coordinate pins --------------------------

@dataclass
class _AssetInfo:
    asset: str
    rev: str
    author: str
    size: int
    generator: Optional[str]
    cost_class: str
    params: Optional[Dict]
    surface: Surface
    bounds: Optional[Tuple]


def _load_universe(repo, pins: Dict[str, str]) -> Dict[str, _AssetInfo]:
    from .generators import get as get_generator

    out: Dict[str, _AssetInfo] = {}
    for asset, rev in pins.items():
        r = repo.ledger.read_revision(asset, rev)
        bounds = None
        cost_class = ""
        if r.generator:
            gen = get_generator(r.generator)
            cost_class = gen.cost_class
            bounds = gen.bounds(gen.bind_params(r.params))
        out[asset] = _AssetInfo(
            asset=asset, rev=rev, author=r.author, size=r.size,
            generator=r.generator, cost_class=cost_class, params=r.params,
            surface=Surface.from_dict(r.surface), bounds=bounds,
        )
    return out


# -- seed predicates -------------------------------------------------------

def _boxes_intersect(a, b) -> bool:
    return all(a[0][i] <= b[1][i] and b[0][i] <= a[1][i] for i in range(3))


def _seed_matches(seed: str, info: _AssetInfo, repo,
                  pins: Dict[str, str]) -> bool:
    if seed.startswith("provides:"):
        want = split_contract(seed[len("provides:"):])
        return any(o.key == want for o in info.surface.offers)
    if seed.startswith("requires:"):
        want = split_contract(seed[len("requires:"):])
        return any(r.key == want for r in info.surface.requires)
    if seed.startswith("role:"):
        want = seed[len("role:"):]
        return any(o.role == want for o in info.surface.offers)
    if seed.startswith("author:"):
        return info.author == seed[len("author:"):]
    if seed.startswith("changed-since:"):
        base = repo.ledger.read_baseline(seed[len("changed-since:"):])
        return base.pins.get(info.asset) != info.rev
    if seed.startswith("box:"):
        vals = [float(x) for x in seed[len("box:"):].split(",")]
        if len(vals) != 6:
            raise ValueError("box: wants x0,y0,z0,x1,y1,z1")
        if info.bounds is None:
            return False   # honest: no declared bounds, no spatial answer
        return _boxes_intersect(info.bounds, (tuple(vals[:3]), tuple(vals[3:])))
    # plain name or glob
    return fnmatch.fnmatchcase(info.asset, seed)


# -- closure edges ---------------------------------------------------------

@dataclass
class _Edge:
    consumer: str
    provider: str
    contract: str
    policy: str          # required | substitutable | omittable


def _build_edges(universe: Dict[str, _AssetInfo]):
    """One resolution pass; both the edge list and the Resolution are reused
    everywhere downstream. Building this three times made closure quadratic."""
    surfaces = {a: i.surface for a, i in universe.items() if i.surface}
    res = resolve(surfaces)
    policy_of = {
        (a, "%s:%s" % (r.path, r.instance)): r.failure_policy
        for a, s in surfaces.items() for r in s.requires
    }
    edges: List[_Edge] = []
    for b in res.bindings:
        policy = policy_of.get((b.consumer, b.requirement), "required")
        for provider in {p.split("/", 1)[0] for p in b.providers}:
            edges.append(_Edge(b.consumer, provider, b.contract, policy))
    return edges, res


# -- resolution ------------------------------------------------------------

def resolve_slice(repo, spec: SliceSpec) -> SliceResult:
    pins = repo.resolve(baseline=spec.baseline, channel=spec.channel)
    universe = _load_universe(repo, pins)
    coordinate = ("baseline %s" % spec.baseline if spec.baseline
                  else "floating on @%s" % spec.channel)

    diagnostics: List[str] = []
    errors = 0
    omitted_assets = {o.asset for o in spec.omits}

    def member_from(asset: str, prov: Provenance) -> Member:
        i = universe[asset]
        return Member(asset=asset, rev=i.rev, provenance=prov, size=i.size,
                      generator=i.generator, cost_class=i.cost_class,
                      bounds=i.bounds)

    members: Dict[str, Member] = {}

    # seeds
    for seed in spec.seeds:
        hits = [a for a, i in sorted(universe.items())
                if a not in omitted_assets and _seed_matches(seed, i, repo, pins)]
        if not hits and not seed.startswith(("changed-since:",)):
            diagnostics.append("seed %r matched nothing" % seed)
        for a in hits:
            members.setdefault(a, member_from(a, Provenance("seed", seed)))

    # pins participate in closure like seeds; unknown pins are errors
    for pin in spec.pins:
        if pin.asset in omitted_assets:
            diagnostics.append("pin and omit both name %r; omit wins" % pin.asset)
            continue
        if pin.asset not in universe:
            diagnostics.append("pin %r: no such asset at this coordinate" % pin.asset)
            errors += 1
            continue
        members.setdefault(
            pin.asset,
            member_from(pin.asset, Provenance("pin", pin.reason, pin.author)))

    # closure -- omitted assets are excluded from the graph entirely, so they
    # can neither join nor pull anything in; the consequences surface below.
    all_edges, resolution = _build_edges(universe)
    edges = [e for e in all_edges
             if e.consumer not in omitted_assets and e.provider not in omitted_assets]
    needs_by_consumer: Dict[str, List[_Edge]] = {}
    feeds_by_provider: Dict[str, List[_Edge]] = {}
    for e in edges:
        needs_by_consumer.setdefault(e.consumer, []).append(e)
        feeds_by_provider.setdefault(e.provider, []).append(e)

    boundary: List[BoundaryItem] = []
    frontier = list(members)
    for depth in range(spec.depth):
        nxt: List[str] = []
        for a in frontier:
            if "needs" in spec.closure:
                for e in needs_by_consumer.get(a, []):
                    if e.provider in members:
                        continue
                    if e.policy == "required" or spec.include_optional:
                        members[e.provider] = member_from(
                            e.provider,
                            Provenance("closure", "needs %s <- %s" % (e.contract, a)))
                        nxt.append(e.provider)
                    else:
                        boundary.append(BoundaryItem(
                            e.provider,
                            "%s requires %s" % (a, e.contract),
                            "%s, not forced" % e.policy))
            if "feeds" in spec.closure:
                for e in feeds_by_provider.get(a, []):
                    if e.consumer not in members:
                        members[e.consumer] = member_from(
                            e.consumer,
                            Provenance("closure", "feeds %s -> %s" % (e.contract, a)))
                        nxt.append(e.consumer)
        if not nxt:
            break
        frontier = nxt
    else:
        # depth exhausted with frontier still hot: report what stayed outside
        if "needs" in spec.closure:
            for a in frontier:
                for e in needs_by_consumer.get(a, []):
                    if e.provider not in members and e.policy == "required":
                        boundary.append(BoundaryItem(
                            e.provider, "%s requires %s" % (a, e.contract),
                            "beyond depth %d" % spec.depth))

    # omits: recorded with what they displaced, and with consequences
    omitted: List[Tuple[Overlay, str]] = []
    for o in spec.omits:
        if o.asset not in universe:
            diagnostics.append("omit %r: no such asset at this coordinate" % o.asset)
            continue
        omitted.append((o, "excluded from membership and from closure"))
    for e in all_edges:
        if e.consumer in members and e.provider in omitted_assets and e.policy == "required":
            who = next(o for o in spec.omits if o.asset == e.provider)
            diagnostics.append(
                "%s requires %s, but its provider %s is omitted (%s: %s)"
                % (e.consumer, e.contract, e.provider, who.author, who.reason))
            errors += 1

    # unbound requirements among members
    member_surfaces = {a: universe[a].surface for a in members if universe[a].surface}
    bound_reqs = {(b.consumer, b.requirement) for b in resolution.bindings}
    for a in members:
        for r in member_surfaces.get(a, Surface()).requires:
            key = (a, "%s:%s" % (r.path, r.instance))
            if key not in bound_reqs:
                msg = "%s requires %s: no provider (%s)" % (a, r.contract, r.failure_policy)
                diagnostics.append(msg)
                if r.failure_policy == "required":
                    errors += 1

    ordered = sorted(members.values(), key=lambda m: m.asset)
    return SliceResult(spec=spec, coordinate=coordinate, members=ordered,
                       omitted=omitted, boundary=boundary,
                       diagnostics=diagnostics, errors=errors)


# -- serialisation: a slice IS a query document ----------------------------

def _esc(s: str) -> str:
    return s.replace("\\", "\\\\").replace('"', '\\"')


def emit_query_document(result: SliceResult) -> str:
    spec = result.spec
    head = [
        "#usda 1.0",
        "(",
        "    customLayerData = {",
        '        string jitsd__label   = "%s"' % _esc(spec.label or "slice"),
        '        string jitsd__context = "%s"' % spec.context,
    ]
    if spec.baseline:
        head.append('        string jitsd__baseline = "%s"' % spec.baseline)
    head += [
        '        string jitsd__slice = "%s"' % _esc(spec.to_json()),
        "    }",
        ")",
        "",
        'def Xform "Slice"',
        "{",
    ]
    body = []
    for m in result.members:
        body += [
            '    def Xform "%s" (' % m.asset,
            '        prepend apiSchemas = ["JitsdInstanceAPI"]',
            "    )",
            "    {",
            '        uniform token jitsd:instance:asset = "%s"' % _esc(m.asset),
            '        uniform token jitsd:provenance = "%s"'
            % _esc("%s: %s" % (m.provenance.kind, m.provenance.detail)),
            "    }",
        ]
    return "\n".join(head + body + ["}", ""])


def read_spec(path: Path) -> SliceSpec:
    m = SLICE_RE.search(Path(path).read_text())
    if not m:
        raise ValueError("%s carries no jitsd__slice block" % path)
    return SliceSpec.from_json(m.group(1).encode().decode("unicode_escape"))


# -- the receipt -----------------------------------------------------------

def _human(n: float) -> str:
    for u in ("B", "KiB", "MiB", "GiB"):
        if abs(n) < 1024 or u == "GiB":
            return ("%.0f %s" if u == "B" else "%.1f %s") % (n, u)
        n /= 1024.0
    return "%.1f GiB" % n


def receipt(result: SliceResult) -> str:
    spec = result.spec
    lines = []
    expr = " ".join(spec.seeds) or "(no seeds)"
    lines.append("slice: %s  +%s  depth %d  ctx:%s"
                 % (expr, ",".join(spec.closure) or "none", spec.depth, spec.context))
    lines.append("coordinate: %s" % result.coordinate)
    lines.append("")
    lines.append("members (%d):" % len(result.members))
    for m in result.members:
        cost = _human(m.size) if m.size else ("gen:%s" % (m.cost_class or "?"))
        who = ("%s: " % m.provenance.author) if m.provenance.author else ""
        lines.append("  %-14s %-5s %-8s %-38s %s"
                     % (m.asset, m.rev, m.provenance.kind,
                        (who + m.provenance.detail)[:38], cost))
    if result.omitted:
        lines.append("")
        lines.append("omitted (%d):" % len(result.omitted))
        for o, note in result.omitted:
            lines.append("  %-14s %s: %s  [%s]" % (o.asset, o.author, o.reason, note))
    if result.boundary:
        lines.append("")
        lines.append("boundary (%d):  referenced but not pulled" % len(result.boundary))
        for b in result.boundary:
            lines.append("  %-14s via %-34s %s" % (b.asset, b.via, b.why_excluded))
    if result.diagnostics:
        lines.append("")
        for d in result.diagnostics:
            lines.append("  ! %s" % d)
    lines.append("")
    gens = sum(1 for m in result.members if m.generator)
    bb = result.bounds_union()
    lines.append("est. cost: %s stored payloads · %d generator%s to run"
                 % (_human(result.payload_bytes()), gens, "" if gens == 1 else "s"))
    if bb:
        lines.append("bounds:    (%.3g, %.3g, %.3g) .. (%.3g, %.3g, %.3g)"
                     % (bb[0] + bb[1]))
    return "\n".join(lines)
