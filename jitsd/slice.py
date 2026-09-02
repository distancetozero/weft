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
    # Which relationship KINDS closure may follow. Empty means every kind --
    # which on a real assembly means everything, since the bench's assembly
    # references every prop. "Pull one thread" needs this to be a choice:
    # follow Mount contracts and material bindings, leave sublayers alone.
    # Kinds are contract names ("Mount") or USD edge kinds ("usd:binding").
    follow: List[str] = field(default_factory=list)
    # Which binding attributes are in view -- what this slice's consumers read.
    # Empty means all. Passed to re-evaluation for the impact preview.
    view: List[str] = field(default_factory=list)
    pins: List[Overlay] = field(default_factory=list)
    omits: List[Overlay] = field(default_factory=list)
    baseline: Optional[str] = None
    channel: str = "approved"
    context: str = "review"
    label: str = ""
    rules: Optional[str] = None     # provenance: the rule set applied, "name@rev"
    # Recorded prim selections, as plain dicts (so to_json/from_json need no
    # special construction, unlike pins/omits): {"context", "rev", "ask",
    # "paths"}. Written by cmd_select from a resolved SliceResult; read back
    # by resolve_slice to enforce the authority rule against a fresh replay.
    selections: Optional[List[Dict]] = None

    def to_json(self) -> str:
        return json.dumps(asdict(self), separators=(",", ":"), sort_keys=True)

    @classmethod
    def from_json(cls, text: str) -> "SliceSpec":
        d = json.loads(text)
        d["pins"] = [Overlay(**p) for p in d.get("pins", [])]
        d["omits"] = [Overlay(**o) for o in d.get("omits", [])]
        known = {f for f in cls.__dataclass_fields__}
        return cls(**{k: v for k, v in d.items() if k in known})


# -- rule sets: a team's way of seeing the scene, as content ---------------

RULES_RE = re.compile(r'string\s+jitsd__rules\s*=\s*"((?:[^"\\]|\\.)*)"')


@dataclass
class RuleSet:
    """The reusable half of a slice: everything except what was seeded.

    docs/10-slices.md: rule sets are content -- revisioned, channelled, owned,
    promoted like any asset. "The lighting closure rule v12" is a publishable
    artifact, so a team shares a way of seeing rather than a scene file. One
    hard constraint, kept here: a rule reads only the relational plane.
    """
    closure: List[str] = field(default_factory=lambda: ["needs"])
    follow: List[str] = field(default_factory=list)
    depth: int = DEFAULT_DEPTH
    include_optional: bool = False
    view: List[str] = field(default_factory=list)
    context: str = "review"
    label: str = ""
    author: str = ""
    note: str = ""

    def to_json(self) -> str:
        return json.dumps(asdict(self), separators=(",", ":"), sort_keys=True)

    @classmethod
    def from_json(cls, text: str) -> "RuleSet":
        d = json.loads(text)
        known = {f for f in cls.__dataclass_fields__}
        return cls(**{k: v for k, v in d.items() if k in known})

    @classmethod
    def from_spec(cls, spec: "SliceSpec", author: str = "", note: str = "") -> "RuleSet":
        return cls(closure=list(spec.closure), follow=list(spec.follow), depth=spec.depth,
                   include_optional=spec.include_optional, view=list(spec.view),
                   context=spec.context, label=spec.label, author=author, note=note)

    def apply(self, spec: "SliceSpec", overrides: Dict[str, object]) -> "SliceSpec":
        """Rules fill in what the caller did not say. Explicit flags win."""
        for name in ("closure", "follow", "depth", "include_optional", "view", "context"):
            if overrides.get(name) is None:
                setattr(spec, name, getattr(self, name))
        if not spec.label and self.label:
            spec.label = self.label
        return spec


def emit_rules_document(rs: RuleSet, name: str) -> str:
    return "\n".join([
        "#usda 1.0",
        "#",
        "# A rule set: a team's way of seeing the scene. Reads only the relational",
        "# plane. Apply with `jitsd select --rules %s`." % name,
        "#",
        "(",
        "    customLayerData = {",
        '        string jitsd__rules = "%s"' % _esc(rs.to_json()),
        "    }",
        ")",
        "",
    ])


def read_rules(text: str) -> RuleSet:
    m = RULES_RE.search(text)
    if not m:
        raise ValueError("no jitsd__rules block")
    return RuleSet.from_json(m.group(1).encode().decode("unicode_escape"))


def load_rules(repo, ref: str) -> Tuple[RuleSet, str]:
    """`name` or `name@ref` from the repository. Returns (rules, "name@rev").

    Unqualified names take @approved when it exists -- the team's published
    way of seeing -- and fall back to @wip.
    """
    name, _, rev_ref = ref.partition("@")
    if rev_ref:
        rev = repo.ledger.resolve_ref(name, rev_ref)
    else:
        try:
            rev = repo.ledger.resolve_ref(name, "approved")
        except KeyError:
            rev = repo.ledger.resolve_ref(name, "wip")
    r = repo.ledger.read_revision(name, rev)
    if not r.blob:
        raise ValueError("%s %s carries no payload" % (name, rev))
    return read_rules(repo.store.get_bytes(r.blob).decode()), "%s@%s" % (name, rev)


def save_rules(repo, name: str, rs: RuleSet, author: str, message: str = "") -> str:
    """Store a rule set as an asset revision. Returns the revision id."""
    import tempfile
    d = Path(tempfile.mkdtemp(prefix="jitsd-rules-"))
    p = d / ("%s.usda" % name)
    p.write_text(emit_rules_document(rs, name))
    return repo.save(name, p, author, message or ("rules: %s" % name)).rev


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
class Selection:
    """A prim-level ask, scoped by a context asset and pinned at its slice
    revision (spec section 9). `paths` is the cached resolution at
    (context, rev); `layer_bytes` is priced from the pull manifest's own
    accounting, not re-derived here."""
    context: str          # ledger asset name
    rev: str              # context revision pinned at resolve time
    ask: str          # the raw ask, authoritative at other coordinates
    paths: List[str] = field(default_factory=list)
    layer_bytes: int = 0


@dataclass
class SliceResult:
    spec: SliceSpec
    coordinate: str                      # "baseline 000003" or "floating on @approved"
    members: List[Member]
    omitted: List[Tuple[Overlay, str]]   # (overlay, what its provenance would have been)
    boundary: List[BoundaryItem]
    diagnostics: List[str]               # human-readable warnings/errors
    errors: int
    untracked: List["_Untracked"] = field(default_factory=list)
    selections: List[Selection] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return self.errors == 0

    def untracked_bytes(self) -> int:
        return sum(u.size for u in self.untracked)

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
    source: Optional[str] = None


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
            source=getattr(r, "source", None),
        )
    return out


# -- prim seeds: the ask grammar as slice-seed syntax, scoped by context ---
#
# spec section 9. A seed of the form "<context>:<ask>" is a prim seed when
# <ask> itself starts with one of the ask grammar's plane prefixes -- so
# "bench:role:propSocket" is a prim seed (ask "role:propSocket" inside
# context "bench") while a bare "role:propSocket" stays the asset-level
# predicate it always was. partition() splits on the FIRST colon, so
# <context> can never itself contain a colon; the check is exactly "does
# what follows the first colon look like an ask".

_PRIM_PLANES = ("name:", "id:", "where:", "near:", "within:", "path:",
                "role:", "offers:", "requires:")


def is_prim_seed(seed: str) -> bool:
    ctx, sep, rest = seed.partition(":")
    if not sep or not ctx:
        return False
    return rest.startswith(_PRIM_PLANES)


def split_prim_seed(seed: str) -> Tuple[str, str]:
    """A prim seed's (context asset name, ask). Caller must have already
    confirmed `is_prim_seed(seed)`."""
    ctx, _, rest = seed.partition(":")
    return ctx, rest


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
    contract: str        # "Mount@1" for a contract edge; "usd:binding" etc. for a USD edge
    policy: str          # required | substitutable | omittable

    @property
    def kind(self) -> str:
        """What `follow` matches on: the contract name, or the USD edge kind."""
        return split_contract(self.contract)[0]


def _usd_kind(edge) -> str:
    """Label a deps edge by the relationship it is, so closure can choose."""
    from deps.walk import ARC, ASSET_ATTR, COLLECTION, CONN, INHERIT, REL
    if edge.kind == ARC:
        return "usd:arc"
    if edge.kind == ASSET_ATTR:
        return "usd:asset"
    if edge.kind == REL:
        return "usd:binding" if edge.name.startswith("material:binding") else "usd:rel"
    if edge.kind == CONN:
        return "usd:conn"
    if edge.kind == INHERIT:
        return "usd:inherit"
    if edge.kind == COLLECTION:
        return "usd:collection"
    return "usd:%s" % edge.kind


REFERENCE_CONTRACT = "usd:reference"


@dataclass
class _Untracked:
    """A file a member references that is not a tracked asset at this coordinate.

    It is still required -- the reference will resolve or strand regardless of
    whether jitsd knows about it -- so the receipt must count its bytes. Hiding
    it is how the receipt reported 765 B for an asset that needs 11 layers.
    """
    consumer: str
    path: str
    size: int


def _reference_edges(universe: Dict[str, _AssetInfo]):
    """Closure edges from the USD reference graph, for assets without contracts.

    Contract edges are the model; reference edges are what real assets have.
    Measured on ALab: not one of 4,296 layers declares a contract, and every
    one of them references, payloads or binds something. A closure that sees
    only contracts pulls nothing and the receipt lies about cost.

    Optional at runtime: needs pxr via `deps`. Absent, rung 1 behaves as it
    did -- contract edges only -- and says nothing false, just less.
    """
    sources = {i.source: a for a, i in universe.items() if i.source}
    if not sources:
        return [], []
    try:
        from deps import build as _build_graph
    except ImportError:
        return [], []

    # Walk to a fixpoint. `build` walks only the paths it is given, so an
    # untracked layer a member references would contribute no edges of its
    # own -- and the cost would stop one hop out. On ALab that reported 3
    # files for an asset that needs 11 layers and 6 textures. Each round adds
    # the USD layers discovered last round; textures and caches are counted
    # but never opened.
    layer_ext = (".usd", ".usda", ".usdc", ".usdz")
    paths = set(sources)
    g = _build_graph(sorted(paths))
    for _ in range(32):
        found = {t for p in paths for t in g.direct_needs(p)
                 if t not in paths and t.lower().endswith(layer_ext)}
        if not found:
            break
        paths |= found
        g = _build_graph(sorted(paths))

    # From each tracked asset, walk outward but STOP at the next tracked
    # asset: that becomes an edge, and its own references are its business.
    # Untracked files are expanded through, so an edge tracked -> untracked ->
    # tracked is recorded as a direct requirement -- which it is -- while a
    # chain of tracked assets keeps its hops, so `--depth` means what it says.
    # Each edge keeps the KIND of relationship it came from -- a material
    # binding, a reference, a class arc -- so closure can follow one thread
    # and not another. Through an untracked intermediate, the kind is the
    # first hop's: how the consumer reached out.
    edges: List[_Edge] = []
    seen_edges = set()
    untracked: Dict[str, _Untracked] = {}
    for src, asset in sources.items():
        seen = {src}
        frontier: List[Tuple[str, Optional[str]]] = [(src, None)]
        while frontier:
            nxt: List[Tuple[str, Optional[str]]] = []
            for node, via in frontier:
                for target in sorted(g.direct_needs(node)):
                    if target in seen:
                        continue
                    seen.add(target)
                    kinds = sorted({_usd_kind(e) for e in g.why(node, target)}) or ["usd:arc"]
                    label = via or kinds[0]
                    other = sources.get(target)
                    if other is not None:
                        if other != asset:
                            for k in ([via] if via else kinds):
                                if (asset, other, k) not in seen_edges:
                                    seen_edges.add((asset, other, k))
                                    edges.append(_Edge(asset, other, k, "required"))
                        continue
                    if target not in untracked:
                        try:
                            size = Path(target).stat().st_size
                        except OSError:
                            size = 0
                        untracked[target] = _Untracked(asset, target, size)
                    nxt.append((target, label))
            frontier = nxt
    return edges, list(untracked.values())


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
    ref_edges, untracked = _reference_edges(universe)
    seen = {(e.consumer, e.provider, e.contract) for e in edges}
    for e in ref_edges:
        if (e.consumer, e.provider, e.contract) not in seen:
            edges.append(e)
    return edges, res, untracked


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

    prim_seeds = [s for s in spec.seeds if is_prim_seed(s)]
    asset_seeds = [s for s in spec.seeds if not is_prim_seed(s)]

    # seeds (asset-level)
    for seed in asset_seeds:
        hits = [a for a, i in sorted(universe.items())
                if a not in omitted_assets and _seed_matches(seed, i, repo, pins)]
        if not hits and not seed.startswith(("changed-since:",)):
            diagnostics.append("seed %r matched nothing" % seed)
        for a in hits:
            members.setdefault(a, member_from(a, Provenance("seed", seed)))

    # prim seeds (spec section 9): resolved against the context asset's
    # source, at the revision this coordinate pins it to. The context asset
    # joins membership too, so closure/impact see it like any other seed.
    selections: List[Selection] = []
    for seed in prim_seeds:
        ctx_name, ask = split_prim_seed(seed)
        if ctx_name in omitted_assets:
            diagnostics.append(
                "prim seed %r: context %r is omitted" % (seed, ctx_name))
            continue
        if ctx_name not in universe:
            diagnostics.append(
                "prim seed %r: no context asset %r at this coordinate"
                % (seed, ctx_name))
            errors += 1
            continue
        info = universe[ctx_name]
        if not info.source or not Path(info.source).exists():
            diagnostics.append(
                "prim seed %r: context %r has no source file" % (seed, ctx_name))
            errors += 1
            continue
        from . import manifest as _manifest
        from .pull import pull as _pull_fn
        try:
            p = _pull_fn(info.source, [ask], follow=spec.follow or None,
                         depth=spec.depth)
        except ValueError as e:
            diagnostics.append("prim seed %r: %s" % (seed, e))
            errors += 1
            continue
        _manifest.layer_hashes(p)
        sel = Selection(context=ctx_name, rev=info.rev, ask=ask,
                        paths=[m.path for m in p.members],
                        layer_bytes=int(p.accounting.get("layer_bytes", 0)))
        selections.append(sel)
        if not sel.paths:
            diagnostics.append("prim seed %r matched nothing" % seed)
        members.setdefault(ctx_name, member_from(ctx_name, Provenance("seed", seed)))

    # authority rule: resolve_slice always re-runs the ask. A spec loaded via
    # --from may carry selections recorded at resolve time; at the SAME
    # context rev the recorded paths must equal the replay (a checkable
    # invariant -- mismatch is an error). At a different rev the replay wins
    # and the difference is only ever a diagnostic: the ask is authoritative,
    # not the cache.
    for rec in (spec.selections or []):
        cur = next((s for s in selections
                    if s.context == rec.get("context") and s.ask == rec.get("ask")), None)
        if cur is None:
            continue
        if rec.get("rev") == cur.rev:
            if rec.get("paths") != cur.paths:
                diagnostics.append(
                    "selection %s:%s: recorded paths differ from replay at "
                    "the same rev %s -- invariant violated"
                    % (cur.context, cur.ask, cur.rev))
                errors += 1
        else:
            old = set(rec.get("paths") or [])
            new = set(cur.paths)
            diagnostics.append(
                "selection drift %s:%s: +%d -%d vs recorded at %s (ask is "
                "authoritative)" % (cur.context, cur.ask, len(new - old),
                                    len(old - new), rec.get("rev")))

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
    all_edges, resolution, untracked = _build_edges(universe)
    edges = [e for e in all_edges
             if e.consumer not in omitted_assets and e.provider not in omitted_assets]
    needs_by_consumer: Dict[str, List[_Edge]] = {}
    feeds_by_provider: Dict[str, List[_Edge]] = {}
    for e in edges:
        needs_by_consumer.setdefault(e.consumer, []).append(e)
        feeds_by_provider.setdefault(e.provider, []).append(e)

    follow = set(spec.follow)

    def followed(e: _Edge) -> bool:
        return not follow or e.kind in follow

    boundary: List[BoundaryItem] = []
    not_followed: Dict[Tuple[str, str], str] = {}
    frontier = list(members)
    for depth in range(spec.depth):
        nxt: List[str] = []
        for a in frontier:
            if "needs" in spec.closure:
                for e in needs_by_consumer.get(a, []):
                    if e.provider in members:
                        continue
                    if not followed(e):
                        # Declared, not silent: the thread exists, it was not pulled.
                        not_followed.setdefault((e.provider, e.kind), a)
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
                    if e.consumer in members:
                        continue
                    if not followed(e):
                        not_followed.setdefault((e.consumer, e.kind), a)
                        continue
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
                    if e.provider not in members and e.policy == "required" and followed(e):
                        boundary.append(BoundaryItem(
                            e.provider, "%s requires %s" % (a, e.contract),
                            "beyond depth %d" % spec.depth))
    for (asset_, kind), via in sorted(not_followed.items()):
        if asset_ not in members:
            boundary.append(BoundaryItem(asset_, "%s via %s" % (via, kind),
                                         "%s not followed" % kind))

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

    # references from members to files that are not tracked assets: required,
    # not pullable, and costed
    untracked_refs = [u for u in untracked if u.consumer in members]

    ordered = sorted(members.values(), key=lambda m: m.asset)
    return SliceResult(spec=spec, coordinate=coordinate, members=ordered,
                       omitted=omitted, boundary=boundary,
                       diagnostics=diagnostics, errors=errors,
                       untracked=untracked_refs, selections=selections)


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
    if spec.follow:
        lines.append("follow: %s" % ", ".join(spec.follow))
    if spec.view:
        lines.append("view:   %s" % ", ".join(spec.view))
    if spec.rules:
        lines.append("rules:  %s" % spec.rules)
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
    if result.selections:
        lines.append("")
        lines.append("selections (%d):" % len(result.selections))
        for s in result.selections:
            lines.append("  %s@%s : %s -> %d prims, %s"
                         % (s.context, s.rev, s.ask, len(s.paths), _human(s.layer_bytes)))
    if result.diagnostics:
        lines.append("")
        for d in result.diagnostics:
            lines.append("  ! %s" % d)
    lines.append("")
    if result.untracked:
        by_consumer: Dict[str, List[_Untracked]] = {}
        for u in result.untracked:
            by_consumer.setdefault(u.consumer, []).append(u)
        lines.append("")
        lines.append("untracked references (%d):  required by members, not tracked "
                     "as assets" % len(result.untracked))
        for consumer in sorted(by_consumer):
            us = by_consumer[consumer]
            lines.append("  %-14s %d file%s, %s"
                         % (consumer, len(us), "" if len(us) == 1 else "s",
                            _human(sum(u.size for u in us))))
    lines.append("")
    gens = sum(1 for m in result.members if m.generator)
    bb = result.bounds_union()
    cost = "est. cost: %s stored payloads · %d generator%s to run" % (
        _human(result.payload_bytes()), gens, "" if gens == 1 else "s")
    if result.untracked:
        cost += " · %s untracked" % _human(result.untracked_bytes())
    lines.append(cost)
    if bb:
        lines.append("bounds:    (%.3g, %.3g, %.3g) .. (%.3g, %.3g, %.3g)"
                     % (bb[0] + bb[1]))
    return "\n".join(lines)
