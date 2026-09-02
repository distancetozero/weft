"""Prim-level closure (spec sections 4, 6, 7).

For POPULATED prims, edges are read from composed relationships — the prim
index already applied list-ops (deletes), variant selections, and Pcp
elision, so composed targets are the authority. The layer-space walk is
used only across unloaded payload arcs (Task 6). Spine ancestors ride into
the mask as opinions; their outgoing relationships are not scanned."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple

from .ask import DEFAULT_IDENTITY_KEYS, ResolvedSeed, resolve_seeds
from .follow import FollowTerm, format_term, parse_follow


@dataclass
class PullMember:
    path: str
    via_kind: str
    from_member: str = ""
    note: str = ""


@dataclass
class PullBoundary:
    target: str
    kind: str
    reason: str
    omission: str = "inert"


@dataclass
class Pull:
    context: str
    depth: int
    members: List[PullMember] = field(default_factory=list)
    boundary: List[PullBoundary] = field(default_factory=list)
    resolutions: List[ResolvedSeed] = field(default_factory=list)
    follow: List[str] = field(default_factory=list)
    layers: List[Tuple[str, str]] = field(default_factory=list)
    variant_selections: List[str] = field(default_factory=list)
    accounting: Dict[str, object] = field(default_factory=dict)
    fitness: Dict[str, object] = field(default_factory=dict)
    declarations: List[str] = field(default_factory=list)


def edge_kind_of(rel_name: str) -> str:
    """A relationship's kind is its own namespaced name (spec drift fix 2)."""
    return rel_name if ":" in rel_name else "usd:rel"


def _open(context_file: str):
    from pxr import Usd
    return Usd.Stage.Open(context_file, Usd.Stage.LoadNone)


def _out_edges(prim) -> List[Tuple[str, str]]:
    """(kind, composed target path) for every authored relationship, plus
    (spec §6) a contract-bearing prim's declared carrier spines exposed as
    edges of the contract's own kind."""
    out = []
    for rel in prim.GetAuthoredRelationships():
        kind = edge_kind_of(rel.GetName())
        for t in rel.GetTargets():
            out.append((kind, t.GetPrimPath().pathString))

    c = prim.GetAttribute("jitsd:offer:contract")
    if c and c.HasAuthoredValue():
        kind = str(c.Get()).split("@")[0]          # "Mount@1" -> "Mount"
        rel = prim.GetRelationship("jitsd:offer:carrier")
        if rel:
            for t in rel.GetTargets():
                out.append((kind, t.GetPrimPath().pathString))

    return out


def _reverse_index(stage) -> Dict[str, List[Tuple[str, str]]]:
    """target path -> [(source path, kind)] over the populated stage."""
    idx: Dict[str, List[Tuple[str, str]]] = {}
    for p in stage.Traverse():
        for kind, t in _out_edges(p):
            idx.setdefault(t, []).append((p.GetPath().pathString, kind))
    return idx


def _term_for(kind: str, terms: List[FollowTerm]) -> Optional[FollowTerm]:
    for t in terms:
        if t.kind == kind:
            return t
    return None


def pull(context_file: str, seeds, follow=None, depth: int = 4,
         identity_keys=DEFAULT_IDENTITY_KEYS) -> Pull:
    stage = _open(context_file)
    terms = parse_follow(follow)
    p = Pull(context=context_file, depth=depth,
             follow=[format_term(t) for t in terms])
    p.resolutions = resolve_seeds(stage, list(seeds), identity_keys)

    members: Dict[str, PullMember] = {}
    for r in p.resolutions:
        for path in r.paths:
            members.setdefault(path, PullMember(path, "seed", "", r.seed.raw))

    needs_up = any(t.direction in ("up", "both") for t in terms)
    rev = _reverse_index(stage) if needs_up else {}
    if needs_up:
        p.declarations.append(
            "reverse terms present: pull is depth-bounded component closure")

    not_followed: Dict[Tuple[str, str], str] = {}
    depth_cut: Dict[Tuple[str, str], str] = {}
    frontier = list(members)
    for d in range(depth):
        nxt: List[str] = []
        for mpath in frontier:
            prim = stage.GetPrimAtPath(mpath)
            candidates: List[Tuple[str, str, str]] = []   # kind, target, direction
            if prim:
                for kind, target in _out_edges(prim):
                    candidates.append((kind, target, "down"))
            for src, kind in rev.get(mpath, ()):
                candidates.append((kind, src, "up"))
            for kind, target, direction in candidates:
                if target in members:
                    continue
                t = _term_for(kind, terms)
                followed = t is not None and (
                    t.direction == "both" or t.direction == direction)
                if not followed:
                    if direction == "down":   # reverse edges only count when asked
                        not_followed.setdefault((target, kind), mpath)
                    continue
                cap = t.depth if t.depth is not None else depth
                if d >= cap:
                    depth_cut.setdefault((target, kind), "beyond depth %d" % cap)
                    continue
                members[target] = PullMember(target, kind, mpath)
                nxt.append(target)
        if not nxt:
            break
        frontier = nxt
    else:
        for mpath in frontier:
            prim = stage.GetPrimAtPath(mpath)
            if not prim:
                continue
            for kind, target in _out_edges(prim):
                if target not in members and _term_for(kind, terms):
                    depth_cut.setdefault((target, kind), "beyond depth %d" % depth)

    for (target, kind), _via in sorted(not_followed.items()):
        if target not in members:
            p.boundary.append(PullBoundary(target, kind, "not followed"))
    for (target, kind), reason in sorted(depth_cut.items()):
        if target not in members:
            p.boundary.append(PullBoundary(target, kind, reason))

    p.members = sorted(members.values(), key=lambda m: m.path)
    p.accounting["members"] = len(p.members)
    return p


def who(context_file: str, seeds, kinds=None, depth: int = 1):
    """Incoming edges to the seeds: (source, kind, member). Spec section 7."""
    stage = _open(context_file)
    resolved = resolve_seeds(stage, list(seeds))
    targets = {path for r in resolved for path in r.paths}
    rev = _reverse_index(stage)
    want = set(kinds or ())
    out = []
    for t in sorted(targets):
        for src, kind in rev.get(t, ()):
            if not want or kind in want:
                out.append((src, kind, t))
    return sorted(out)
