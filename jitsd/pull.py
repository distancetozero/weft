"""Prim-level closure (spec sections 4, 6, 7).

For POPULATED prims, edges are read from composed relationships — the prim
index already applied list-ops (deletes), variant selections, and Pcp
elision, so composed targets are the authority. The layer-space walk is
used only across unloaded payload arcs (Task 6). Spine ancestors ride into
the mask as opinions; their outgoing relationships are not scanned."""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple

from deps.walk import ARC, walk_file

from .ask import DEFAULT_IDENTITY_KEYS, ResolvedSeed, resolve_seeds
from .follow import FollowTerm, format_term, parse_follow
from .registry import omission_class


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


def _terms_for(kind: str, terms: List[FollowTerm]) -> List[FollowTerm]:
    """All follow terms naming this kind (a kind may be named by more than
    one term, e.g. both a forward and an `up:` term)."""
    return [t for t in terms if t.kind == kind]


def _admission(kind: str, direction: str, terms: List[FollowTerm],
               depth: int) -> Optional[int]:
    """The depth cap for an edge of `kind` traveled in `direction`, or None
    if no term admits it. An edge is admitted when ANY term naming its kind
    allows that direction (`both` admits either; `up` admits reverse;
    `down`/default admits forward). The cap is the MAX depth among the
    admitting terms (a term's own `None` depth means the global depth)."""
    admitting = [t for t in _terms_for(kind, terms)
                 if t.direction == "both" or t.direction == direction]
    if not admitting:
        return None
    return max(t.depth if t.depth is not None else depth for t in admitting)


def _admit(stage, path: str, via_kind: str, from_member: str,
           members: Dict[str, "PullMember"], p: "Pull",
           note: str = "") -> Optional[str]:
    """Admit a composed path as a member, widening per the instancing rule
    (spec section 4): a path resolving through an instance proxy is masked
    up to its instance root, since USD instancing populates prototypes
    whole-or-not-at-all — there is no such thing as "half an instance".

    Provenance: `note` carries the caller's own note (e.g. a seed's raw
    ask). When widening happens, the widening note takes precedence; the
    caller's note, if any, is appended after "; " so neither is lost.

    Returns the admitted path (may differ from `path`), or None."""
    prim = stage.GetPrimAtPath(path)
    widened = path
    wnote = ""
    if prim and prim.IsInstanceProxy():
        anc = prim
        while anc and anc.IsInstanceProxy():
            anc = anc.GetParent()
        widened = anc.GetPath().pathString
        wnote = ("widened to instance root %s: masks populate prototypes whole"
                 % widened)
        p.declarations.append("%s %s" % (path, wnote))
    if widened in members:
        return widened
    if wnote and note:
        final_note = wnote + "; " + note
    else:
        final_note = wnote or note
    members[widened] = PullMember(widened, via_kind, from_member, final_note)
    return widened


def _apply_physics_rules(stage, members: Dict[str, "PullMember"], p: "Pull") -> None:
    """Joint whole-or-declared (spec section 6): a joint whose body target
    is not populated silently becomes a joint to the world frame if left
    in place, so its exclusion must be declared meaning-changing rather
    than silently dropped or silently kept."""
    from pxr import Usd
    drop: List[str] = []
    for mpath in list(members):
        prim = stage.GetPrimAtPath(mpath)
        if not prim:
            continue
        for joint in Usd.PrimRange(prim):
            names = joint.GetAuthoredPropertyNames()
            bodies = []
            for rn in ("physics:body0", "physics:body1"):
                if rn in names:
                    rel = joint.GetRelationship(rn)
                    bodies += [t.GetPrimPath().pathString for t in rel.GetTargets()]
            if not bodies:
                continue
            missing = [b for b in bodies
                       if b not in members
                       and not any(b.startswith(m + "/") or m.startswith(b + "/")
                                   for m in members)]
            if missing:
                jp = joint.GetPath().pathString
                drop.append(jp)
                p.boundary.append(PullBoundary(
                    jp, "physics:joint", "excluded: body %s not populated"
                    % ", ".join(missing), omission=omission_class("physics:joint")))
    for jp in drop:
        # Excluded joints are removed from members when directly admitted;
        # when a joint rides inside a member's subtree it cannot be carved
        # out by a mask, so the declaration records it and the boundary
        # entry above stands — the consumer decides.
        members.pop(jp, None)
        p.declarations.append(
            "joint %s excluded from population (a joint with an absent body "
            "silently becomes a joint to the world frame)" % jp)


def _record_variants(prim, p: Pull) -> None:
    vsets = prim.GetVariantSets()
    for name in vsets.GetNames():
        sel = vsets.GetVariantSet(name).GetVariantSelection()
        if sel:
            entry = "%s %s=%s" % (prim.GetPath().pathString, name, sel)
            if entry not in p.variant_selections:
                p.variant_selections.append(entry)


def _unselected_variant_edges(
        prim, staged: Dict[Tuple[str, str], Tuple[str, str]]) -> None:
    """Stage edges authored in variants NOT selected (spec section 4).

    Staged into `(target, variant-label-kind) -> (reason, underlying rel
    kind)`. The target/label pair is keyed exactly like the
    `not_followed`/`depth_cut` maps in `pull()`, so the caller can flush to
    `p.boundary` only once the final member set is known (R13) — a target
    admitted on a later BFS wave must not carry a stale boundary entry, and
    repeated authored content must not duplicate one. The underlying rel
    kind rides along separately so the boundary's omission class reflects
    what the edge actually is (e.g. `physics:`), while the boundary's own
    `kind` field stays the variant label for consumers walking selections."""
    vsets = prim.GetVariantSets()
    for spec in prim.GetPrimStack():
        for vset in spec.variantSets:
            selected = vsets.GetVariantSet(vset.name).GetVariantSelection()
            for variant in vset.variants:
                if variant.name == selected:
                    continue
                for vspec in _iter_specs(variant.primSpec):
                    for rel in vspec.relationships:
                        under_kind = edge_kind_of(rel.name)
                        for t in _rel_targets(rel):
                            staged.setdefault(
                                (t, "usd:variant(%s=%s)" % (vset.name, variant.name)),
                                ("not in selected world", under_kind))


def _iter_specs(spec):
    yield spec
    for child in spec.nameChildren:
        yield from _iter_specs(child)


def _rel_targets(rel):
    items = []
    lo = rel.targetPathList
    for slot in ("explicitItems", "prependedItems", "appendedItems",
                 "addedItems", "orderedItems"):
        items.extend(getattr(lo, slot, ()) or ())
    return [str(t.GetPrimPath()) for t in items]


def _nearest_ancestor(stage, path):
    """The nearest valid ancestor prim of `path` (parent, grandparent, ...),
    or None if none exists below the pseudo-root. Shared by `_below_payload`
    (spec section 4) and the layer-recording pass (R15): an invalid path's
    own layer stack does not exist on this stage, so its nearest ancestor's
    does duty for it."""
    cur = path
    while cur and cur != "/":
        cur = cur.rsplit("/", 1)[0] or "/"
        prim = stage.GetPrimAtPath(cur)
        if prim:
            return prim
    return None


def _below_payload(stage, path, p: Pull) -> Optional[str]:
    """Confirm `path` exists below an unloaded payload by crossing the
    recorded ARC(payload) edge in layer space. Returns the path if the
    interior layer defines the remainder, else None. Spec section 4."""
    from pxr import Sdf
    prim = _nearest_ancestor(stage, path)
    if not prim:
        return None
    cur = prim.GetPath().pathString
    rest = path[len(cur):]           # e.g. "/mtl/usd_full"
    for spec in prim.GetPrimStack():
        layer_path = spec.layer.realPath or spec.layer.identifier
        rec = walk_file(layer_path)
        if rec is None:
            continue
        for e in rec.edges:
            if e.kind == ARC and e.name == "payload" and e.src_prim == str(spec.path):
                target = os.path.normpath(os.path.join(
                    os.path.dirname(layer_path), e.target))
                inner = Sdf.Layer.FindOrOpen(target)
                if not inner:
                    continue
                root = inner.defaultPrim or ""
                interior = "/%s%s" % (root, rest)
                if inner.GetPrimAtPath(interior):
                    if (target, "") not in p.layers:
                        p.layers.append((target, ""))
                    p.declarations.append(
                        "%s resolved below unloaded payload via %s"
                        % (path, os.path.basename(target)))
                    return path
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
            _admit(stage, path, "seed", "", members, p, note=r.seed.raw)

    # Seed paths arriving invalid on this LoadNone stage (e.g. a `path:`
    # seed under an unloaded payload) get one pull-side chance: cross the
    # payload arc in layer space and confirm the remainder is defined
    # there. If that fails too, drop the member rather than silently
    # keeping an unresolvable path (spec section 4).
    for path in list(members):
        if not stage.GetPrimAtPath(path):
            if _below_payload(stage, path, p) is None:
                del members[path]
                p.declarations.append("seed path %s: not in composed world" % path)

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
                cap = _admission(kind, direction, terms, depth)
                if cap is None:
                    if direction == "down":   # reverse edges only count when asked
                        not_followed.setdefault((target, kind), mpath)
                    continue
                if d >= cap:
                    depth_cut.setdefault((target, kind), "beyond depth %d" % cap)
                    continue
                before = len(members)
                admitted = _admit(stage, target, kind, mpath, members, p)
                if len(members) > before:
                    nxt.append(admitted)
        if not nxt:
            break
        frontier = nxt
    else:
        # Exhaustion sweep: the final frontier's own edges were never
        # examined by the loop above. It only looks at forward (authored)
        # edges, so it must apply the SAME direction-admission rule as the
        # main loop (an edge whose matching terms admit only "up" is
        # "not followed" here, never "beyond depth N") — reusing
        # `_admission` keeps the two paths from diverging.
        for mpath in frontier:
            prim = stage.GetPrimAtPath(mpath)
            if not prim:
                continue
            for kind, target in _out_edges(prim):
                if target in members:
                    continue
                cap = _admission(kind, "down", terms, depth)
                if cap is None:
                    not_followed.setdefault((target, kind), mpath)
                    continue
                depth_cut.setdefault((target, kind), "beyond depth %d" % cap)

    # Joint whole-or-declared (spec section 6): runs after closure is fully
    # settled, before boundary assembly, so a joint whose body is missing
    # from the FINAL member set is judged against that final set (not an
    # intermediate frontier), and any resulting exclusion is on record
    # before the variant/boundary passes below walk the member set.
    _apply_physics_rules(stage, members, p)

    # Variant recording and unselected-variant staging run once per FINAL
    # member (R14), after closure is fully settled — not per-wave inside the
    # loop above, so a member admitted on the last BFS wave (or only reached
    # by the exhaustion sweep) is not skipped. `_record_variants` is
    # naturally idempotent (guards on `entry not in ...`); staging into a
    # dict makes `_unselected_variant_edges` idempotent the same way.
    unselected_variant: Dict[Tuple[str, str], Tuple[str, str]] = {}
    for mpath in members:
        prim = stage.GetPrimAtPath(mpath)
        if not prim:
            continue
        _record_variants(prim, p)
        _unselected_variant_edges(prim, unselected_variant)

    for (target, kind), (reason, under_kind) in sorted(unselected_variant.items()):
        if target not in members:
            p.boundary.append(PullBoundary(
                target, kind, reason, omission=omission_class(under_kind)))
    for (target, kind), _via in sorted(not_followed.items()):
        if target not in members:
            p.boundary.append(PullBoundary(
                target, kind, "not followed", omission=omission_class(kind)))
    for (target, kind), reason in sorted(depth_cut.items()):
        if target not in members:
            p.boundary.append(PullBoundary(
                target, kind, reason, omission=omission_class(kind)))

    p.members = sorted(members.values(), key=lambda m: m.path)

    # Layer recording (R15): every distinct layer consulted for the final
    # member set. A valid member contributes its own GetPrimStack(); an
    # invalid-but-confirmed member (below an unloaded payload) has no prim
    # stack on this stage, so its nearest valid ancestor's stack does duty
    # for it. `_below_payload` already recorded the crossed interior layer
    # directly into p.layers during seed validation.
    seen_layers = {ident for ident, _ in p.layers}
    for m in p.members:
        prim = stage.GetPrimAtPath(m.path)
        source = prim if prim else _nearest_ancestor(stage, m.path)
        if not source:
            continue
        for spec in source.GetPrimStack():
            ident = spec.layer.identifier
            if ident not in seen_layers:
                seen_layers.add(ident)
                p.layers.append((ident, ""))

    p.accounting["members"] = len(p.members)

    # Fitness (spec section 6): a pull is never a physics-simulation-ready
    # extract — it is a soundness-preserving mask. `contact_unevaluated`
    # counts members whose subtree authors ANY physics: property (a joint,
    # collider, or body carried a level below the member itself still
    # counts, since PrimRange walks the whole subtree, not just the member
    # prim), so consumers can't mistake "populated" for "simulatable".
    from pxr import Usd
    scene_populated = any(
        prim.GetTypeName() == "PhysicsScene" for prim in stage.Traverse())
    contact_unevaluated = 0
    for m in p.members:
        prim = stage.GetPrimAtPath(m.path)
        if not prim:
            continue
        if any(any(n.startswith("physics:") for n in sub.GetAuthoredPropertyNames())
               for sub in Usd.PrimRange(prim)):
            contact_unevaluated += 1
    p.fitness = {
        "physics_scene_populated": scene_populated,
        "contact_unevaluated": contact_unevaluated,
        "statement": "contact-incomplete by construction",
    }

    return p


def who(context_file: str, seeds, kinds=None, depth: int = 1):
    """Incoming edges to the seeds: (source, kind, member). Spec section 7.

    Multi-hop: each hop collects (src, kind, target) rows for incoming
    edges to the current frontier; the next frontier is those srcs. The
    kinds filter applies at every hop, restricting both which rows are
    reported and which srcs seed the next hop (an edge outside `kinds`
    does not extend the interrogation)."""
    stage = _open(context_file)
    resolved = resolve_seeds(stage, list(seeds))
    targets = {path for r in resolved for path in r.paths}
    rev = _reverse_index(stage)
    want = set(kinds or ())
    out = set()
    frontier = set(targets)
    visited = set(targets)
    for _ in range(depth):
        nxt = set()
        for t in frontier:
            for src, kind in rev.get(t, ()):
                if want and kind not in want:
                    continue
                out.add((src, kind, t))
                if src not in visited:
                    nxt.add(src)
        if not nxt:
            break
        visited |= nxt
        frontier = nxt
    return sorted(out)
